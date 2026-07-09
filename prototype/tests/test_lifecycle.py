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


class RemovalProvenanceTests(unittest.TestCase):
    """ADR-0014: removal reasons survive the index — on the thought."""

    def setUp(self):
        self.tmp, self.repo = make_repo()
        self.addCleanup(self.tmp.cleanup)
        self.v1 = self.repo.micro_commit(fact_doc("owner", obj="core"), timestamp=ts(0))
        self.repo.anchor("start", "HEAD", timestamp=ts(0))

    def test_thought_records_reasons_and_recap_exposes_them(self):
        result = self.repo.supersede_fact(
            self.v1["assertion"], "infra", _assertion(), timestamp=ts(1))
        thought = self.repo.show(result["thought"])
        self.assertEqual(thought["removals"],
                         [{"assertion": self.v1["assertion"], "reason": "superseded"}])
        recap = self.repo.recap("start")
        removed = {row["assertion"]: row["removal_reason"] for row in recap["removed"]}
        self.assertEqual(removed[self.v1["assertion"]], "superseded")
        # log rows carry the field verbatim
        head_entry = self.repo.log()[0]
        self.assertIn("removals", head_entry)

    def test_staged_flow_records_reasons_too(self):
        self.repo.add_fact(fact_doc("owner", obj="v2", when=ts(1)))
        self.repo.remove_fact(self.v1["assertion"], "superseded")
        tid = self.repo.commit_thought("revise", "tester", timestamp=ts(1))
        thought = self.repo.show(tid)
        self.assertEqual(thought["removals"][0]["reason"], "superseded")
        findings = verify_repository(self.repo)
        self.assertEqual([f for f in findings if f["severity"] == "error"], [])
        self.assertEqual([f for f in findings if f["code"] == "removals-incomplete"], [])

    def test_analytics_prefers_recorded_label_over_structure(self):
        # 'superseded' recorded WITHOUT a same-family replacement: structure
        # alone would say 'retired'; the recorded label must win (ADR-0014)
        self.repo.micro_commit_batch(
            [], [{"id": self.v1["assertion"], "reason": "superseded"}],
            "external system replaced it", author="tester", timestamp=ts(1))
        outcomes, _rows, _families = analytics.belief_outcomes(self.repo)
        self.assertEqual(outcomes[self.v1["assertion"]], "superseded")

    def test_verify_flags_inconsistent_removal_records(self):
        # hand-write a thought claiming a removal that never happened
        head = self.repo.status()["thought"]
        mindset = self.repo.show(head)["mindset"]
        bogus = self.repo.store.write({
            "type": "thought",
            "parents": [head],
            "mindset": mindset,  # same mindset: nothing was actually removed
            "operation": "commit",
            "message": "lying about removals",
            "author": "tester",
            "timestamp": ts(2),
            "removals": [{"assertion": self.v1["assertion"], "reason": "superseded"}],
        })
        findings = verify_repository(self.repo)
        codes = {f["code"] for f in findings if bogus in f["message"]}
        self.assertIn("removal-not-removed", codes)

    def test_merge_resolution_reasons_recorded(self):
        # change-delete conflict: main strengthens the claim, side retires it
        self.repo.branch("side", timestamp=ts(1))
        _claim, boost = self.repo.add_fact(
            fact_doc("owner", obj="core", confidence=9900, when=ts(2)))
        self.repo.commit_thought("boost confidence", "tester", timestamp=ts(2))
        self.repo.checkout("side", timestamp=ts(3))
        self.repo.retire_fact([self.v1["assertion"]], "stale", "tester", timestamp=ts(3))
        self.repo.checkout("main", timestamp=ts(4))
        self.repo.merge("side", timestamp=ts(5))
        conflict_claim = self.repo.status()["conflicts"][0]["claim"]
        self.repo.resolve_conflict(conflict_claim, keep=boost)
        tid = self.repo.commit_thought("merge side: keep boosted", "tester", timestamp=ts(6))
        thought = self.repo.show(tid)
        self.assertEqual(len(thought["parents"]), 2)
        recorded = {e["assertion"]: e["reason"] for e in thought["removals"]}
        self.assertEqual(recorded[self.v1["assertion"]], "merge-conflict-resolution")
        findings = verify_repository(self.repo)
        self.assertEqual([f for f in findings if f["severity"] == "error"], [])

    def test_schema_rejects_malformed_removals(self):
        from cogit.objects import validate_object
        base = {
            "type": "thought", "parents": [], "mindset": self.repo.show("HEAD")["mindset"],
            "operation": "commit", "message": "m", "author": "a",
            "timestamp": ts(3),
        }
        for removals in ([],  # empty list
                         [{"assertion": self.v1["assertion"]}],  # missing reason
                         [{"assertion": self.v1["assertion"], "reason": ""}],  # empty reason
                         [{"assertion": "zz", "reason": "r"}]):  # bad oid
            with self.assertRaises(UserError, msg=repr(removals)):
                validate_object({**base, "removals": removals})
        two = sorted([self.v1["assertion"], self.repo.show("HEAD")["mindset"]])
        unsorted = [{"assertion": two[1], "reason": "r"}, {"assertion": two[0], "reason": "r"}]
        with self.assertRaises(UserError):
            validate_object({**base, "removals": unsorted})


if __name__ == "__main__":
    unittest.main()
