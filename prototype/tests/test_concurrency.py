"""COG-035/036/037: atomic micro-commits, index locking, belief queries."""

import os
import threading
import unittest

from tests.helpers import fact_doc, make_repo, ts
from cogit.errors import ConcurrentUpdateError, UserError
from cogit.index_state import index_lock
from cogit.repo import Repository
from cogit.verify import verify_repository


class MicroCommitTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.repo = make_repo()
        self.addCleanup(self.tmp.cleanup)

    def test_micro_commit_creates_full_chain_without_index(self):
        result = self.repo.micro_commit(fact_doc("solo"), timestamp=ts(0))
        self.assertFalse(result["already_active"])
        thought = self.repo.store.read(result["thought"])
        self.assertEqual(thought["message"], "agent_decision: test solo")
        self.assertEqual(thought["author"], "tester")  # from assertion actor
        self.assertEqual(self.repo._mindset_assertions(result["thought"]), {result["assertion"]})

    def test_micro_commit_already_active_is_noop(self):
        first = self.repo.micro_commit(fact_doc("same"), timestamp=ts(0))
        second = self.repo.micro_commit(fact_doc("same"), timestamp=ts(1))
        self.assertTrue(second["already_active"])
        self.assertEqual(second["thought"], first["thought"])  # no empty commit
        self.assertEqual(len(self.repo.log()), 1)

    def test_micro_commit_refuses_dirty_index(self):
        self.repo.add_fact(fact_doc("staged-work"))
        with self.assertRaises(UserError):
            self.repo.micro_commit(fact_doc("micro"))

    def test_micro_commit_rejects_contradiction(self):
        claim_oid, _a0 = self.repo.add_fact(fact_doc("belief"))
        self.repo.commit_thought("believe", "agent", ts(0))
        neg = fact_doc("belief", obj=False)
        neg["claim"]["negates"] = claim_oid
        with self.assertRaises(UserError):
            self.repo.micro_commit(neg)

    def test_parallel_micro_commits_all_land(self):
        """Two writers, N micro-commits each, one repository: nothing lost."""
        writers, per_writer = 2, 5
        errors = []

        def worker(writer_id):
            repo = Repository.open(self.tmp.name)  # own instance, like a subagent
            for n in range(per_writer):
                try:
                    repo.micro_commit(fact_doc(f"w{writer_id}-fact-{n}"))
                except Exception as exc:  # noqa: BLE001 — record and fail the test
                    errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(writers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        facts = self.repo.facts()["facts"]
        self.assertEqual(len(facts), writers * per_writer)
        self.assertEqual(len(self.repo.log()), writers * per_writer)  # linear history
        self.assertEqual([f for f in verify_repository(self.repo) if f["severity"] == "error"], [])

    def test_index_lock_contention_and_hint(self):
        lock_path = os.path.join(self.repo.cogit_dir, "index.json.lock")
        with open(lock_path, "w"):
            pass
        try:
            with self.assertRaises(ConcurrentUpdateError) as ctx:
                with index_lock(self.repo.cogit_dir, timeout=0.05):
                    pass
            self.assertIn("index.json.lock", str(ctx.exception))  # stale-lock hint
        finally:
            os.unlink(lock_path)


class BeliefQueryTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.repo = make_repo()
        self.addCleanup(self.tmp.cleanup)
        for subject, predicate, project, n in [
            ("cogit:COG-035", "shipped", "cogit", 0),
            ("cogit:COG-036", "shipped", "cogit", 1),
            ("api:/orders", "timeout_seconds", "engram", 2),
        ]:
            doc = fact_doc(predicate, when=ts(n))
            doc["claim"]["subject"] = subject
            doc["claim"]["qualifiers"] = {"project": project}
            self.repo.micro_commit(doc, timestamp=ts(n))

    def test_subject_prefix_and_exact_filters(self):
        rows = self.repo.facts(subject="cogit:*")["facts"]
        self.assertEqual(sorted(r["subject"] for r in rows), ["cogit:COG-035", "cogit:COG-036"])
        rows = self.repo.facts(subject="api:/orders")["facts"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(self.repo.facts(subject="nothing:*")["facts"], [])

    def test_predicate_and_project_filters(self):
        rows = self.repo.facts(predicate="shipped", project="cogit")["facts"]
        self.assertEqual(len(rows), 2)
        rows = self.repo.facts(project="engram")["facts"]
        self.assertEqual(rows[0]["subject"], "api:/orders")
        self.assertIn("qualifiers", rows[0])

    def test_project_qualifier_changes_claim_identity(self):
        base = fact_doc("same-statement", when=ts(5))
        base["claim"]["qualifiers"] = {"project": "alpha"}
        other = fact_doc("same-statement", when=ts(5))
        other["claim"]["qualifiers"] = {"project": "beta"}
        claim_a, _, _ = self.repo._write_fact_objects(base)
        claim_b, _, _ = self.repo._write_fact_objects(other)
        self.assertNotEqual(claim_a, claim_b)

    def test_recap_defaults_to_newest_anchor_and_reports_same_point(self):
        thoughts = self.repo.log()
        self.repo.anchor("older", thoughts[-1]["id"], timestamp=ts(10))
        self.repo.anchor("newest", thoughts[1]["id"], timestamp=ts(11))
        recap = self.repo.recap()
        self.assertEqual(recap["from_anchor"], "newest")
        self.assertFalse(recap["same_point"])
        self.assertEqual(len(recap["thoughts"]), 1)  # only the tip is newer
        at_tip = self.repo.recap("HEAD")
        self.assertTrue(at_tip["same_point"])

    def test_recap_without_anchors_starts_at_root(self):
        tmp2, repo2 = make_repo()
        self.addCleanup(tmp2.cleanup)
        repo2.micro_commit(fact_doc("one"), timestamp=ts(0))
        repo2.micro_commit(fact_doc("two"), timestamp=ts(1))
        recap = repo2.recap()
        self.assertIsNone(recap["from_anchor"])
        self.assertEqual(len(recap["thoughts"]), 1)  # root excluded, tip included
        self.assertEqual(len(recap["added"]), 1)


if __name__ == "__main__":
    unittest.main()
