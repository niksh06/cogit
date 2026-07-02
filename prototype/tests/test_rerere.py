import unittest

from tests.helpers import fact_doc, make_repo, ts
from cogit.errors import UserError
from cogit.index_state import EMPTY_INDEX, load_index, save_index
from cogit.rerere import conflict_fingerprint, forget, load_rerere


class FingerprintTests(unittest.TestCase):
    def test_orientation_invariant(self):
        a = {"claim": "sha256:" + "c" * 64, "ours": ["sha256:" + "1" * 64],
             "theirs": ["sha256:" + "2" * 64], "base": []}
        b = {"claim": a["claim"], "ours": a["theirs"], "theirs": a["ours"], "base": []}
        self.assertEqual(conflict_fingerprint(a), conflict_fingerprint(b))

    def test_base_changes_fingerprint(self):
        a = {"claim": "sha256:" + "c" * 64, "ours": ["sha256:" + "1" * 64],
             "theirs": ["sha256:" + "2" * 64], "base": []}
        b = {**a, "base": ["sha256:" + "0" * 64]}
        self.assertNotEqual(conflict_fingerprint(a), conflict_fingerprint(b))

    def test_extra_keys_ignored(self):
        a = {"claim": "sha256:" + "c" * 64, "ours": [], "theirs": ["sha256:" + "2" * 64], "base": []}
        b = {**a, "fingerprint": "x", "suggestion": {"keep": None}}
        self.assertEqual(conflict_fingerprint(a), conflict_fingerprint(b))


class RerereWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.repo = make_repo()
        self.addCleanup(self.tmp.cleanup)
        # base with disputed claim asserted two ways on two branches
        _c, self.a_base = self.repo.add_fact(fact_doc("shared"))
        self.repo.commit_thought("base", "agent", ts(0))
        self.repo.branch("side", timestamp=ts(1))
        _c, self.a_main = self.repo.add_fact(fact_doc("disputed", confidence=9000))
        self.repo.commit_thought("main view", "agent", ts(2))
        self.repo.checkout("side", timestamp=ts(3))
        _c, self.a_side = self.repo.add_fact(fact_doc("disputed", confidence=1000))
        self.repo.commit_thought("side view", "agent", ts(4))
        self.repo.checkout("main", timestamp=ts(5))

    def merge_conflict(self, n):
        result = self.repo.merge("side", timestamp=ts(n))
        self.assertEqual(result["result"], "conflicts")
        return result["conflicts"][0]

    def test_record_suggest_apply_and_forget(self):
        # first merge: conflict with no suggestion
        conflict = self.merge_conflict(6)
        self.assertNotIn("suggestion", conflict)
        self.assertIn("fingerprint", conflict)
        # manual resolution is recorded
        self.repo.resolve_conflict(conflict["claim"], keep=self.a_side)
        store = load_rerere(self.repo.cogit_dir)
        self.assertEqual(len(store), 1)
        self.assertEqual(next(iter(store.values()))["keep"], self.a_side)
        # abort the merge and redo it: the suggestion is surfaced, not applied
        save_index(self.repo.cogit_dir, dict(EMPTY_INDEX))
        conflict = self.merge_conflict(7)
        self.assertEqual(conflict["suggestion"], {"keep": self.a_side})
        index = load_index(self.repo.cogit_dir)
        self.assertEqual(len(index["conflicts"]), 1)  # still unresolved
        # explicit apply, then commit with the remembered outcome
        self.repo.resolve_conflict(conflict["claim"], use_suggestion=True)
        merged = self.repo.commit_thought("merge remembered", "agent", ts(8))
        mindset = self.repo._mindset_assertions(merged)
        self.assertIn(self.a_side, mindset)
        self.assertNotIn(self.a_main, mindset)
        # forget by claim id: next identical conflict has no suggestion
        removed = forget(self.repo.cogit_dir, conflict["claim"])
        self.assertEqual(removed, 1)
        self.assertEqual(load_rerere(self.repo.cogit_dir), {})

    def test_drop_resolution_remembered(self):
        conflict = self.merge_conflict(6)
        self.repo.resolve_conflict(conflict["claim"], drop=True)
        save_index(self.repo.cogit_dir, dict(EMPTY_INDEX))
        conflict = self.merge_conflict(7)
        self.assertEqual(conflict["suggestion"], {"keep": None})
        self.repo.resolve_conflict(conflict["claim"], use_suggestion=True)
        merged = self.repo.commit_thought("merge drop", "agent", ts(8))
        mindset = self.repo._mindset_assertions(merged)
        self.assertNotIn(self.a_main, mindset)
        self.assertNotIn(self.a_side, mindset)
        self.assertIn(self.a_base, mindset)

    def test_suggested_without_stored_resolution_fails(self):
        conflict = self.merge_conflict(6)
        with self.assertRaises(UserError):
            self.repo.resolve_conflict(conflict["claim"], use_suggestion=True)
        with self.assertRaises(UserError):
            self.repo.resolve_conflict(conflict["claim"], keep=self.a_side, drop=True)


if __name__ == "__main__":
    unittest.main()
