import os
import unittest

from tests.helpers import fact_doc, make_repo, ts
from cogit.errors import ConcurrentUpdateError, UserError
from cogit.index_state import load_index
from cogit.repo import Repository, init_repository
from cogit.verify import verify_repository


class RepositoryWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.repo = make_repo()
        self.addCleanup(self.tmp.cleanup)

    def commit_fact(self, predicate, message, n=0, **kwargs):
        _claim, assertion = self.repo.add_fact(fact_doc(predicate, **kwargs))
        thought = self.repo.commit_thought(message, "agent", ts(n))
        return assertion, thought

    # -- init ----------------------------------------------------------------

    def test_init_is_idempotent(self):
        assertion, thought = self.commit_fact("keep-me", "first")
        init_repository(self.tmp.name)  # re-init must not destroy state
        repo = Repository.open(self.tmp.name)
        self.assertEqual(repo.head_info()[1], thought)
        self.assertIn(assertion, repo._mindset_assertions(thought))

    def test_open_unknown_extension_refused(self):
        from cogit.errors import UnsupportedFormatError

        with open(os.path.join(self.repo.cogit_dir, "config"), "a", encoding="utf-8") as handle:
            handle.write("\tweirdExtension = on\n")
        with self.assertRaises(UnsupportedFormatError):
            Repository.open(self.tmp.name)

    # -- staging & commit -------------------------------------------------------

    def test_add_commit_and_mindset(self):
        a1, t1 = self.commit_fact("one", "first")
        a2, t2 = self.commit_fact("two", "second", n=1)
        self.assertEqual(self.repo._mindset_assertions(t2), {a1, a2})
        thought = self.repo.store.read(t2)
        self.assertEqual(thought["parents"], [t1])
        # index cleared after commit
        index = load_index(self.repo.cogit_dir)
        self.assertEqual(index["staged_facts"], [])

    def test_empty_commit_rejected(self):
        with self.assertRaises(UserError):
            self.repo.commit_thought("empty", "agent")

    def test_add_fact_idempotent_staging(self):
        self.repo.add_fact(fact_doc("same"))
        _claim, assertion = self.repo.add_fact(fact_doc("same"))
        index = load_index(self.repo.cogit_dir)
        self.assertEqual(index["staged_facts"], [assertion])

    def test_remove_fact_requires_reason_and_membership(self):
        a1, _t1 = self.commit_fact("stay", "first")
        with self.assertRaises(UserError):
            self.repo.remove_fact(a1, "")
        with self.assertRaises(UserError):
            self.repo.remove_fact("sha256:" + "0" * 64, "refuted")
        self.repo.remove_fact(a1, "refuted")
        t2 = self.repo.commit_thought("drop it", "agent", ts(1))
        self.assertEqual(self.repo._mindset_assertions(t2), set())

    def test_commit_fails_if_ref_moved_since_staging(self):
        a1, t1 = self.commit_fact("base", "first")
        self.repo.add_fact(fact_doc("mine"))
        # simulate another writer advancing main behind our back
        mindset = self.repo.store.write(
            {"type": "mindset", "assertions": [], "created_at": ts(2)}
        )
        other = self.repo.store.write(
            {
                "type": "thought",
                "parents": [t1],
                "mindset": mindset,
                "operation": "commit",
                "message": "concurrent",
                "author": "other",
                "timestamp": ts(2),
            }
        )
        self.repo.refs.update_ref("refs/heads/main", other, t1, "other", "commit", "race", ts(2))
        with self.assertRaises(ConcurrentUpdateError):
            self.repo.commit_thought("mine", "agent", ts(3))

    def test_secrets_rejected_not_stored(self):
        doc = fact_doc("leak", obj="AKIA" + "ABCDEFGHIJKLMNOP")
        with self.assertRaises(UserError):
            self.repo.add_fact(doc)
        with self.assertRaises(UserError):
            self.commit_fact("ok", "password = hunter2secret")

    # -- branch / checkout --------------------------------------------------------

    def test_branch_checkout_detach_and_reflog(self):
        a1, t1 = self.commit_fact("base", "first")
        self.repo.branch("hypothesis-a", actor="agent", timestamp=ts(1))
        self.repo.checkout("hypothesis-a", timestamp=ts(2))
        a2, t2 = self.commit_fact("alt", "on hypothesis", n=3)
        self.repo.checkout("main", timestamp=ts(4))
        self.assertEqual(self.repo.head_info()[1], t1)
        # branching copied no objects: both tips share ancestry object t1
        self.assertEqual(self.repo.store.read(t2)["parents"], [t1])
        # detached checkout
        mode, thought = self.repo.checkout(t2, timestamp=ts(5))
        self.assertEqual((mode, thought), ("detached", t2))
        self.assertIsNone(self.repo.head_info()[0])
        # reflog recovery: HEAD log knows every move, newest first
        entries = self.repo.reflog("HEAD")
        moves = [entry["op"] for entry in entries]
        self.assertEqual(moves.count("checkout"), 3)
        # where was HEAD before the last move? -> old target of the newest entry
        self.assertEqual(entries[0]["old"], t1)
        self.assertEqual(entries[0]["new"], t2)
        # US-015: a recovered thought can be branched
        self.repo.branch("recovered/hypothesis", entries[0]["new"], timestamp=ts(6))
        self.assertEqual(self.repo.refs.read_ref("refs/heads/recovered/hypothesis"), t2)

    def test_duplicate_branch_rejected(self):
        self.commit_fact("base", "first")
        self.repo.branch("dup")
        with self.assertRaises(UserError):
            self.repo.branch("dup")

    def test_dirty_index_blocks_checkout(self):
        self.commit_fact("base", "first")
        self.repo.branch("other")
        self.repo.add_fact(fact_doc("staged"))
        with self.assertRaises(UserError):
            self.repo.checkout("other")

    def test_detached_commit_moves_head(self):
        _a1, t1 = self.commit_fact("base", "first")
        self.repo.checkout(t1, timestamp=ts(1))
        _a2, t2 = self.commit_fact("detached-work", "in detached", n=2)
        kind, value = self.repo.refs.read_head()
        self.assertEqual((kind, value), ("detached", t2))
        # main did not move
        self.assertEqual(self.repo.refs.read_ref("refs/heads/main"), t1)

    # -- diff -------------------------------------------------------------------

    def test_diff_sets(self):
        a1, t1 = self.commit_fact("one", "first")
        self.repo.remove_fact(a1, "superseded")
        _c, a2 = self.repo.add_fact(fact_doc("two"))
        t2 = self.repo.commit_thought("swap", "agent", ts(1))
        diff = self.repo.diff(t1, t2)
        self.assertEqual(diff["added"], [a2])
        self.assertEqual(diff["removed"], [a1])
        self.assertEqual(diff["unchanged"], [])

    # -- merge ------------------------------------------------------------------

    def make_fork(self):
        """base commit on main, then branch 'side' — both at t0."""
        a0, t0 = self.commit_fact("base", "base", n=0)
        self.repo.branch("side", timestamp=ts(1))
        return a0, t0

    def test_merge_already_up_to_date_and_fast_forward(self):
        _a0, t0 = self.make_fork()
        self.assertEqual(self.repo.merge("side")["result"], "already-up-to-date")
        self.repo.checkout("side", timestamp=ts(2))
        _a1, t1 = self.commit_fact("ahead", "side work", n=3)
        self.repo.checkout("main", timestamp=ts(4))
        result = self.repo.merge("side", timestamp=ts(5))
        self.assertEqual(result["result"], "fast-forward")
        self.assertEqual(self.repo.head_info()[1], t1)

    def test_clean_merge_creates_two_parent_thought(self):
        a0, t0 = self.make_fork()
        _a1, t_main = self.commit_fact("main-only", "main work", n=2)
        self.repo.checkout("side", timestamp=ts(3))
        _c, a2 = self.repo.add_fact(fact_doc("side-only"))
        t_side = self.repo.commit_thought("side work", "agent", ts(4))
        self.repo.checkout("main", timestamp=ts(5))
        result = self.repo.merge("side", timestamp=ts(6))
        self.assertEqual(result["result"], "staged")
        self.assertEqual(result["base"], t0)
        merge_thought = self.repo.commit_thought("merge side", "agent", ts(7))
        thought = self.repo.store.read(merge_thought)
        self.assertEqual(thought["operation"], "merge")
        self.assertEqual(thought["parents"], [t_main, t_side])  # semantic order: ours, theirs
        merged = self.repo._mindset_assertions(merge_thought)
        self.assertIn(a2, merged)
        self.assertIn(a0, merged)
        self.assertEqual(len(merged), 3)

    def test_conflicting_merge_blocks_commit_until_resolved(self):
        a0, _t0 = self.make_fork()
        # both sides assert about the SAME claim with different confidence
        _c, a_main = self.repo.add_fact(fact_doc("disputed", confidence=9000))
        self.repo.commit_thought("main view", "agent", ts(2))
        self.repo.checkout("side", timestamp=ts(3))
        _c, a_side = self.repo.add_fact(fact_doc("disputed", confidence=1000))
        self.repo.commit_thought("side view", "agent", ts(4))
        self.repo.checkout("main", timestamp=ts(5))
        result = self.repo.merge("side", timestamp=ts(6))
        self.assertEqual(result["result"], "conflicts")
        self.assertEqual(len(result["conflicts"]), 1)
        conflict = result["conflicts"][0]
        self.assertEqual(conflict["ours"], [a_main])
        self.assertEqual(conflict["theirs"], [a_side])
        # conflict blocks commit — merge never silently drops facts
        with self.assertRaises(UserError):
            self.repo.commit_thought("premature", "agent", ts(7))
        # keep theirs: ours assertion is removed with explicit reason
        self.repo.resolve_conflict(conflict["claim"], keep=a_side)
        merge_thought = self.repo.commit_thought("merge resolved", "agent", ts(8))
        merged = self.repo._mindset_assertions(merge_thought)
        self.assertIn(a_side, merged)
        self.assertNotIn(a_main, merged)
        self.assertIn(a0, merged)

    def test_change_delete_conflict(self):
        a0, _t0 = self.make_fork()
        # ours: add new view on base claim; theirs: refute base fact entirely
        _c, a_new = self.repo.add_fact(fact_doc("base", confidence=500))
        self.repo.commit_thought("weaken belief", "agent", ts(2))
        self.repo.checkout("side", timestamp=ts(3))
        self.repo.remove_fact(a0, "refuted")
        self.repo.commit_thought("refute base", "agent", ts(4))
        self.repo.checkout("main", timestamp=ts(5))
        result = self.repo.merge("side", timestamp=ts(6))
        self.assertEqual(result["result"], "conflicts")
        self.repo.resolve_conflict(result["conflicts"][0]["claim"], drop=True)
        merge_thought = self.repo.commit_thought("merge drop", "agent", ts(7))
        self.assertEqual(self.repo._mindset_assertions(merge_thought), set())

    # -- blame -----------------------------------------------------------------

    def test_blame_first_introducer_not_last_modifier(self):
        a1, t1 = self.commit_fact("origin", "introduced here", n=0)
        self.commit_fact("noise-1", "later 1", n=1)
        self.commit_fact("noise-2", "later 2", n=2)
        blame = self.repo.blame_fact(a1)
        self.assertEqual(blame["thought"], t1)
        self.assertEqual(blame["message"], "introduced here")
        self.assertEqual(blame["source"]["type"], "manual")

    def test_blame_unknown_in_ancestry(self):
        self.commit_fact("known", "first")
        _c, foreign = self.repo.add_fact(fact_doc("never-committed"))
        # clear staged state so the fact exists as an object but not in history
        from cogit.index_state import EMPTY_INDEX, save_index

        save_index(self.repo.cogit_dir, dict(EMPTY_INDEX))
        with self.assertRaises(UserError):
            self.repo.blame_fact(foreign)

    # -- anchors ------------------------------------------------------------------

    def test_anchor_create_list_resolve(self):
        _a1, t1 = self.commit_fact("milestone", "reached")
        anchor_oid = self.repo.anchor("plan-approved", t1, timestamp=ts(1))
        anchors = self.repo.list_anchors()
        self.assertEqual(anchors[0]["name"], "plan-approved")
        self.assertEqual(anchors[0]["target"], t1)
        self.assertEqual(self.repo.resolve("plan-approved"), t1)  # deref to thought
        anchor_obj = self.repo.store.read(anchor_oid)
        self.assertEqual(anchor_obj["target"], t1)
        with self.assertRaises(UserError):
            self.repo.anchor("plan-approved", t1)  # anchors are fixed in MVP

    # -- verify ---------------------------------------------------------------------

    def test_verify_healthy_and_dangling_warning(self):
        _a1, t1 = self.commit_fact("sound", "ok")
        self.assertEqual(verify_repository(self.repo), [])
        # detached commit later abandoned -> dangling thought warning, not error
        self.repo.checkout(t1, timestamp=ts(1))
        _a2, t2 = self.commit_fact("abandoned", "detached", n=2)
        self.repo.checkout("main", timestamp=ts(3))
        findings = verify_repository(self.repo)
        self.assertTrue(all(f["severity"] == "warning" for f in findings))
        self.assertTrue(any(t2 in f["message"] for f in findings))

    def test_verify_detects_corruption_and_missing_links(self):
        a1, _t1 = self.commit_fact("fragile", "ok")
        os.unlink(self.repo.store.path_for(a1))  # missing assertion
        findings = verify_repository(self.repo)
        self.assertTrue(any(f["code"] == "missing-assertion" for f in findings))
        self.assertTrue(any(f["severity"] == "error" for f in findings))

    def test_verify_detects_bad_ref(self):
        self.commit_fact("x", "ok")
        with open(os.path.join(self.repo.cogit_dir, "refs", "heads", "main"), "w") as handle:
            handle.write("garbage\n")
        findings = verify_repository(self.repo)
        self.assertTrue(any(f["severity"] == "error" for f in findings))


if __name__ == "__main__":
    unittest.main()
