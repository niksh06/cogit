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


if __name__ == "__main__":
    unittest.main()
