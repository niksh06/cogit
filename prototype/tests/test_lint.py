"""Claim-modeling linter (COG-047)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "integrations"))

import lint as lint_mod  # noqa: E402

from tests.helpers import make_repo, ts  # noqa: E402


def doc(subject, predicate, obj, source_type="agent", confidence=9000,
        qualifiers=None, when=ts(0), actor="tester"):
    return {
        "claim": {"type": "claim", "kind": "agent_decision", "subject": subject,
                  "predicate": predicate, "object": obj,
                  "qualifiers": qualifiers if qualifiers is not None else {"project": "demo"}},
        "assertion": {"type": "assertion", "status": "asserted",
                      "source": {"type": source_type, "uri": "test:lint"},
                      "confidence_bps": confidence, "asserted_at": when,
                      "actor": actor, "method": {"type": "fixture"}},
    }


class LintTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.repo = make_repo()
        self.addCleanup(self.tmp.cleanup)

    def _lint(self, **kwargs):
        return lint_mod.lint(self.repo, **kwargs)

    def test_clean_belief_produces_no_findings(self):
        self.repo.micro_commit(doc("svc:api", "timeout_seconds", 30,
                                   source_type="tool", confidence=9900), timestamp=ts(0))
        report = self._lint()
        self.assertTrue(report["clean"], report["findings"])

    def test_rule_violations_are_named(self):
        cases = [
            doc("daily:2026-07-05", "outcome",
                "nine of ten green; vdb reconcile clean; pythia stage killed again but "
                "loudly with tombstone and surviving scheduler logs", when=ts(1)),
            doc("svc:api", "observed status", "red", when=ts(2)),
            doc("svc:worker", "state", "ok",
                qualifiers={"project": "demo", "details": "x" * 120}, when=ts(3)),
            doc("svc:queue", "depth", 5, source_type="tool", confidence=7000, when=ts(4)),
            doc("svc:cache", "ttl", 60, qualifiers={}, when=ts(5)),
            doc("svc:anon", "state", "ok", actor="agent", when=ts(6)),
        ]
        for n, fixture in enumerate(cases):
            self.repo.micro_commit(fixture, timestamp=ts(10 + n))
        report = self._lint()
        rules = report["by_rule"]
        self.assertEqual(rules["R2-prose-object"], 1)
        self.assertEqual(rules["R3-ephemeral-subject"], 1)
        self.assertEqual(rules["R3-predicate-whitespace"], 1)
        self.assertEqual(rules["R6-blob-qualifier"], 1)
        self.assertEqual(rules["R4-underconfident-observation"], 1)
        self.assertEqual(rules["R8-missing-project"], 1)
        self.assertEqual(rules["R10-generic-actor"], 1)
        self.assertEqual(report["facts_checked"], 6)
        self.assertGreaterEqual(report["warnings"], 5)

    def test_project_filter_scopes_lint(self):
        self.repo.micro_commit(doc("svc:a", "state", "ok " * 20), timestamp=ts(0))
        other = doc("svc:b", "state", "fine", qualifiers={"project": "other"})
        self.repo.micro_commit(other, timestamp=ts(1))
        report = self._lint(project="other")
        self.assertEqual(report["facts_checked"], 1)
        self.assertTrue(report["clean"])

    def test_empty_repository(self):
        report = self._lint()
        self.assertEqual(report["facts_checked"], 0)
        self.assertTrue(report["clean"])


class HygieneTests(unittest.TestCase):
    """Lifecycle hygiene candidates (COG-058)."""

    def setUp(self):
        self.tmp, self.repo = make_repo()
        self.addCleanup(self.tmp.cleanup)

    def _rules(self, **kwargs):
        return lint_mod.lint(self.repo, **kwargs)["by_rule"]

    def test_family_rivalry_awaiting_then_shipped(self):
        self.repo.micro_commit(doc("feat:x", "status", "awaiting approval"), timestamp=ts(0))
        self.repo.micro_commit(doc("feat:x", "status", "shipped"), timestamp=ts(1))
        report = lint_mod.lint(self.repo)
        rivalry = [f for f in report["findings"] if f["rule"] == "R11-family-rivalry"]
        self.assertEqual(len(rivalry), 1)
        self.assertEqual(len(rivalry[0]["rivals"]), 2)
        self.assertFalse(rivalry[0]["heuristic"])
        self.assertIn("competing active values", rivalry[0]["message"])

    def test_corroboration_is_not_rivalry(self):
        self.repo.micro_commit(doc("feat:x", "status", "shipped", actor="a1"), timestamp=ts(0))
        second = doc("feat:x", "status", "shipped", actor="a2", when=ts(1))
        self.repo.micro_commit(second, timestamp=ts(1))
        self.assertNotIn("R11-family-rivalry", self._rules())

    def test_singleton_state_across_families(self):
        # same subject+predicate modeled with different qualifiers -> R12
        self.repo.micro_commit(
            doc("svc:q", "owner", "core", qualifiers={"project": "demo", "shift": "day"}),
            timestamp=ts(0))
        self.repo.micro_commit(
            doc("svc:q", "owner", "infra", qualifiers={"project": "demo", "shift": "night"}),
            timestamp=ts(1))
        rules = self._rules()
        self.assertIn("R12-singleton-state", rules)
        self.assertNotIn("R11-family-rivalry", rules)  # families differ

    def test_advisory_marker_is_heuristic_info(self):
        self.repo.micro_commit(
            doc("hyp:cache", "verdict", "REFUTE: earlier claim was wrong about ttl"),
            timestamp=ts(0))
        report = lint_mod.lint(self.repo)
        marker = [f for f in report["findings"] if f["rule"] == "R13-advisory-marker"]
        self.assertEqual(len(marker), 1)
        self.assertEqual(marker[0]["severity"], "info")
        self.assertTrue(marker[0]["heuristic"])

    def test_structural_negation_never_triggers_marker(self):
        first = self.repo.micro_commit(doc("hyp:dns", "cause", "dns flaps suspected here"),
                                       timestamp=ts(0))
        negation = doc("hyp:dns", "cause", "dns flaps suspected here", when=ts(1))
        negation["claim"]["negates"] = first["claim"]
        self.repo.add_fact(negation)
        self.repo.remove_fact(first["assertion"], "refuted")
        self.repo.commit_thought("refute dns", "tester", timestamp=ts(1))
        rules = self._rules()
        self.assertNotIn("R13-advisory-marker", rules)
        self.assertNotIn("R11-family-rivalry", rules)


class RatchetTests(unittest.TestCase):
    """Baseline ratchet + bounded output (COG-058)."""

    def setUp(self):
        self.tmp, self.repo = make_repo()
        self.addCleanup(self.tmp.cleanup)
        # old debt BEFORE the baseline
        self.debt = self.repo.micro_commit(
            doc("legacy topic", "state", "ok"), timestamp=ts(0))
        self.repo.anchor("baseline", "HEAD", timestamp=ts(1))

    def test_existing_vs_new_classification(self):
        self.repo.micro_commit(doc("fresh topic", "state", "ok"), timestamp=ts(2))
        report = lint_mod.lint(self.repo, since="baseline")
        ages = {f["subject"]: f["age"] for f in report["findings"]
                if f["rule"] == "R3-subject-whitespace"}
        self.assertEqual(ages["legacy topic"], "existing")
        self.assertEqual(ages["fresh topic"], "new")
        self.assertEqual(report["baseline"]["new_warnings"],
                         sum(1 for f in report["findings"]
                             if f["age"] == "new" and f["severity"] == "warn"))

    def test_superseding_debt_clears_it_and_reintroduction_is_new(self):
        self.repo.retire_fact([self.debt["assertion"]], "cleanup", "tester", timestamp=ts(2))
        report = lint_mod.lint(self.repo, since="baseline")
        subjects = {f["subject"] for f in report["findings"]}
        self.assertNotIn("legacy topic", subjects)  # active-only: debt is gone
        # reintroducing the same shape after the baseline is NEW debt
        self.repo.micro_commit(doc("legacy topic", "state", "ok", when=ts(3)),
                               timestamp=ts(3))
        report = lint_mod.lint(self.repo, since="baseline")
        again = [f for f in report["findings"] if f["subject"] == "legacy topic"]
        self.assertTrue(again)
        self.assertTrue(all(f["age"] == "new" for f in again), again)

    def test_non_ancestor_baseline_fails_clearly(self):
        self.repo.branch("side", timestamp=ts(2))
        self.repo.checkout("side", timestamp=ts(2))
        side = self.repo.micro_commit(doc("s", "p", "v"), timestamp=ts(3))
        self.repo.checkout("main", timestamp=ts(4))
        self.repo.micro_commit(doc("m", "p", "v"), timestamp=ts(5))
        with self.assertRaises(lint_mod.UserError):
            lint_mod.lint(self.repo, since=side["thought"])

    def test_bounded_output_keeps_totals_exact(self):
        for n in range(4):
            self.repo.micro_commit(doc(f"noisy subject {n}", "state", "ok", when=ts(2 + n)),
                                   timestamp=ts(2 + n))
        report = lint_mod.lint(self.repo)
        shaped = lint_mod.shape_report(report, limit=2)
        self.assertEqual(shaped["shown"], 2)
        self.assertEqual(shaped["matched"], len(report["findings"]))
        self.assertEqual(shaped["truncated"], len(report["findings"]) - 2)
        self.assertEqual(shaped["by_rule"], report["by_rule"])  # totals untouched
        only_rule = lint_mod.shape_report(report, rule="R3-subject-whitespace")
        self.assertTrue(all(f["rule"] == "R3-subject-whitespace"
                            for f in only_rule["findings"]))
        summary = lint_mod.shape_report(report, summary=True)
        self.assertEqual(summary["findings"], [])
        self.assertEqual(summary["matched"], len(report["findings"]))


if __name__ == "__main__":
    unittest.main()
