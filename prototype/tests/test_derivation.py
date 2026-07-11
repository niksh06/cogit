"""Derivation-graph queries (COG-050): taint closure, maximin support."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "integrations"))

import derivation  # noqa: E402

from cogit.errors import UserError  # noqa: E402
from tests.helpers import make_repo, ts  # noqa: E402


def doc(subject, confidence, premises=None, uri="test:fixture", when=ts(0)):
    body = {
        "claim": {"type": "claim", "kind": "agent_decision", "subject": subject,
                  "predicate": "verdict", "object": f"value-{subject}",
                  "qualifiers": {"project": "demo"}},
        "assertion": {"type": "assertion", "status": "asserted",
                      "source": {"type": "tool", "uri": uri},
                      "confidence_bps": confidence, "asserted_at": when,
                      "actor": "tester", "method": {"type": "fixture"}},
    }
    if premises:
        body["assertion"]["premises"] = sorted(premises)
    return body


class DiamondGraphTests(unittest.TestCase):
    """A(9800) <- B(9000), C(5000); D(9500) <- B, C  (diamond over A..D)."""

    def setUp(self):
        self.tmp, self.repo = make_repo()
        self.addCleanup(self.tmp.cleanup)
        self.a = self.repo.micro_commit(
            doc("ev:a", 9800, uri="tool:grafana"), timestamp=ts(0))
        self.b = self.repo.micro_commit(
            doc("mid:b", 9000, premises=[self.a["assertion"]]), timestamp=ts(1))
        self.c = self.repo.micro_commit(
            doc("mid:c", 5000, premises=[self.a["assertion"]]), timestamp=ts(2))
        self.d = self.repo.micro_commit(
            doc("top:d", 9500, premises=[self.b["assertion"], self.c["assertion"]]),
            timestamp=ts(3))

    def test_taint_closure_is_exact(self):
        result = derivation.taint(self.repo, self.a["assertion"])
        self.assertEqual(result["matched_by"], "assertion")
        by_subject = {row["subject"]: row["depth"] for row in result["tainted"]}
        self.assertEqual(by_subject, {"mid:b": 1, "mid:c": 1, "top:d": 2})
        # a mid-node taints only its own downstream
        partial = derivation.taint(self.repo, self.c["assertion"])
        self.assertEqual({r["subject"] for r in partial["tainted"]}, {"top:d"})

    def test_taint_by_source_uri(self):
        result = derivation.taint(self.repo, "grafana")
        self.assertEqual(result["matched_by"], "source")
        self.assertEqual(result["seeds"], [self.a["assertion"]])
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["adoption"]["with_premises"], 3)

    def test_support_takes_the_widest_path(self):
        # D's best chain goes through B (min 9000), not C (min 5000)
        result = derivation.support(self.repo, self.d["assertion"])
        self.assertEqual(result["support_bps"], 9000)
        subjects = [link["subject"] for link in result["chain"]]
        self.assertEqual(subjects, ["top:d", "mid:b", "ev:a"])
        self.assertEqual(result["bottleneck"], self.b["assertion"])
        self.assertEqual(result["premise_count"], 2)

    def test_support_bottleneck_can_be_the_conclusion_itself(self):
        weak_top = self.repo.micro_commit(
            doc("top:weak", 4000, premises=[self.b["assertion"]]), timestamp=ts(4))
        result = derivation.support(self.repo, weak_top["assertion"])
        self.assertEqual(result["support_bps"], 4000)
        self.assertEqual(result["bottleneck"], weak_top["assertion"])

    def test_leaf_support_is_its_own_confidence(self):
        result = derivation.support(self.repo, self.a["assertion"])
        self.assertEqual(result["support_bps"], 9800)
        self.assertEqual(len(result["chain"]), 1)

    def test_unknown_seed_is_a_clean_error(self):
        with self.assertRaises(UserError):
            derivation.taint(self.repo, "no-such-source-anywhere")


class HistoryAndChainTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.repo = make_repo()
        self.addCleanup(self.tmp.cleanup)

    def test_chain_min_propagates(self):
        # chain: e1(9900) <- e2(6000) <- e3(9900): bottleneck is the middle
        e1 = self.repo.micro_commit(doc("c:1", 9900), timestamp=ts(0))
        e2 = self.repo.micro_commit(doc("c:2", 6000, premises=[e1["assertion"]]),
                                    timestamp=ts(1))
        e3 = self.repo.micro_commit(doc("c:3", 9900, premises=[e2["assertion"]]),
                                    timestamp=ts(2))
        result = derivation.support(self.repo, e3["assertion"])
        self.assertEqual(result["support_bps"], 6000)
        self.assertEqual(result["bottleneck"], e2["assertion"])

    def test_taint_history_reaches_retired_dependents(self):
        e1 = self.repo.micro_commit(doc("h:1", 9000), timestamp=ts(0))
        e2 = self.repo.micro_commit(doc("h:2", 9000, premises=[e1["assertion"]]),
                                    timestamp=ts(1))
        self.repo.retire_fact([e2["assertion"]], "scope moved", "tester", timestamp=ts(2))
        active_only = derivation.taint(self.repo, e1["assertion"])
        self.assertEqual(active_only["total"], 0)
        with_history = derivation.taint(self.repo, e1["assertion"], history=True)
        self.assertEqual(with_history["total"], 1)
        self.assertFalse(with_history["tainted"][0]["active"])


if __name__ == "__main__":
    unittest.main()
