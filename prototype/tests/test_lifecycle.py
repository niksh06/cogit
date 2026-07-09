"""Atomic lifecycle porcelain (COG-056): supersede / refute / retire."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "integrations"))

import analytics  # noqa: E402

from cogit.errors import UserError  # noqa: E402
from cogit.verify import verify_repository  # noqa: E402
from tests.helpers import fact_doc, make_repo, ts  # noqa: E402


def _assertion(actor="tester", confidence=9000, when=None, premises=None):
    doc = {
        "type": "assertion",
        "status": "asserted",
        "source": {"type": "agent", "uri": "lifecycle-test"},
        "confidence_bps": confidence,
        "asserted_at": when or ts(30),
        "actor": actor,
        "method": {"type": "fixture"},
    }
    if premises:
        doc["premises"] = premises
    return doc


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.repo = make_repo()
        self.addCleanup(self.tmp.cleanup)
        self.v1 = self.repo.micro_commit(fact_doc("owner", obj="core"), timestamp=ts(0))

    def active(self):
        return {row["assertion"]: row for row in self.repo.facts()["facts"]}

    def test_supersede_is_one_thought_same_family(self):
        before = len(self.repo.log())
        result = self.repo.supersede_fact(
            self.v1["assertion"], "infra", _assertion(), timestamp=ts(1))
        self.assertEqual(len(self.repo.log()), before + 1)  # exactly ONE thought
        rows = self.active()
        self.assertNotIn(self.v1["assertion"], rows)
        row = rows[result["assertion"]]
        self.assertEqual(row["object"], "infra")
        self.assertEqual(row["subject"], "test")          # family preserved
        self.assertEqual(row["predicate"], "owner")
        self.assertEqual(result["old_assertion"], self.v1["assertion"])
        self.assertEqual(result["old_claim"], self.v1["claim"])
        # analytics classifies the replaced assertion as superseded
        outcomes, _rows, _families = analytics.belief_outcomes(self.repo)
        self.assertEqual(outcomes[self.v1["assertion"]], "superseded")

    def test_supersede_stale_target_rejected(self):
        self.repo.supersede_fact(self.v1["assertion"], "infra", _assertion(), timestamp=ts(1))
        with self.assertRaises(UserError) as ctx:  # second writer loses the race
            self.repo.supersede_fact(self.v1["assertion"], "late", _assertion(), timestamp=ts(2))
        self.assertIn("not active", str(ctx.exception))

    def test_refute_removes_all_rivals_and_activates_negation(self):
        # a second assertion of the SAME claim (corroboration from another writer)
        rival_doc = fact_doc("owner", obj="core")
        rival_doc["assertion"]["actor"] = "second-writer"
        rival = self.repo.micro_commit(rival_doc, timestamp=ts(1))
        self.assertEqual(rival["claim"], self.v1["claim"])
        before = len(self.repo.log())
        result = self.repo.refute_fact(self.v1["assertion"], _assertion(confidence=9800),
                                       timestamp=ts(2))
        self.assertEqual(len(self.repo.log()), before + 1)
        self.assertEqual(sorted(result["refuted_assertions"]),
                         sorted([self.v1["assertion"], rival["assertion"]]))
        rows = self.active()
        self.assertNotIn(self.v1["assertion"], rows)
        self.assertNotIn(rival["assertion"], rows)
        negation_row = rows[result["negation"]["assertion"]]
        self.assertEqual(negation_row["negates"], self.v1["claim"])
        self.assertTrue(negation_row["negation"])
        findings = verify_repository(self.repo)
        self.assertEqual([f for f in findings if f["severity"] == "error"], [])  # invariant 25 holds
        outcomes, _rows, _families = analytics.belief_outcomes(self.repo)
        self.assertEqual(outcomes[self.v1["assertion"]], "refuted")

    def test_retire_removes_without_negation(self):
        extra = self.repo.micro_commit(fact_doc("phase", obj="pilot"), timestamp=ts(1))
        result = self.repo.retire_fact(
            [self.v1["assertion"], extra["assertion"]],
            "scope moved to another journal", "tester", timestamp=ts(2))
        self.assertEqual(sorted(result["retired"]),
                         sorted([self.v1["assertion"], extra["assertion"]]))
        self.assertEqual(self.active(), {})
        outcomes, _rows, _families = analytics.belief_outcomes(self.repo)
        self.assertEqual(outcomes[self.v1["assertion"]], "retired")

    def test_retire_refuted_reason_redirected(self):
        with self.assertRaises(UserError) as ctx:
            self.repo.retire_fact([self.v1["assertion"]], "refuted", "tester", timestamp=ts(1))
        self.assertIn("refute-fact", str(ctx.exception))

    def test_lifecycle_leaves_state_unchanged_on_failure(self):
        head_before = self.repo.status()["thought"]
        with self.assertRaises(UserError):
            self.repo.supersede_fact("sha256:" + "0" * 64, "x", _assertion())
        with self.assertRaises(UserError):
            self.repo.retire_fact([], "reason", "tester")
        self.assertEqual(self.repo.status()["thought"], head_before)
        self.assertEqual(self.repo.status()["staged"], [])

    def test_dirty_index_blocks_lifecycle(self):
        self.repo.add_fact(fact_doc("staged", obj="pending", when=ts(1)))
        with self.assertRaises(UserError) as ctx:
            self.repo.supersede_fact(self.v1["assertion"], "infra", _assertion(), timestamp=ts(2))
        self.assertIn("non-empty index", str(ctx.exception))
        self.assertEqual(len(self.repo.status()["staged"]), 1)  # staging survives


if __name__ == "__main__":
    unittest.main()
