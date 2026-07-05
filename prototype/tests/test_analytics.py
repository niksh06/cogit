"""Belief analytics (COG-045): structural outcome inference, bands, volatility."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "integrations"))

import analytics  # noqa: E402

from tests.helpers import fact_doc, make_repo, ts  # noqa: E402


class AnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.repo = make_repo()
        self.addCleanup(self.tmp.cleanup)
        # open, observed band
        self.repo.micro_commit(fact_doc("stable", confidence=9900), timestamp=ts(0))
        # superseded chain: v1 (inferred) -> v2 (inferred, open)
        v1 = self.repo.micro_commit(
            fact_doc("churn", obj="v1", confidence=7500), timestamp=ts(1))
        self.repo.add_fact(fact_doc("churn", obj="v2", confidence=7600, when=ts(2)))
        self.repo.remove_fact(v1["assertion"], "superseded")
        self.repo.commit_thought("churn revised", "agent", timestamp=ts(2))
        # refuted: belief (hypothesis band) killed by a negation (observed band)
        wrong = self.repo.micro_commit(
            fact_doc("wrong", obj=True, confidence=5000), timestamp=ts(3))
        negation = fact_doc("wrong", obj=True, confidence=9800, when=ts(4))
        negation["claim"]["negates"] = wrong["claim"]
        self.repo.add_fact(negation)
        self.repo.remove_fact(wrong["assertion"], "refuted")
        self.repo.commit_thought("wrong refuted", "agent", timestamp=ts(4))
        # retired: removed without replacement or negation
        gone = self.repo.micro_commit(
            fact_doc("gone", confidence=4500), timestamp=ts(5))
        self.repo.remove_fact(gone["assertion"], "irrelevant")
        self.repo.commit_thought("gone dropped", "agent", timestamp=ts(6))
        self.report = analytics.analyze(self.repo)

    def test_outcome_classification_counts(self):
        bands = self.report["calibration_by_band"]
        self.assertEqual(bands["observed"],
                         {"n": 2, "open": 2, "superseded": 0, "refuted": 0,
                          "retired": 0, "avg_confidence_bps": 9850,
                          "survival_rate": 1.0})
        self.assertEqual(bands["inferred"]["superseded"], 1)
        self.assertEqual(bands["inferred"]["open"], 1)
        self.assertEqual(bands["inferred"]["survival_rate"], 1.0)
        hypothesis = bands["hypothesis"]
        self.assertEqual((hypothesis["refuted"], hypothesis["retired"]), (1, 1))
        self.assertEqual(hypothesis["survival_rate"], 0.0)
        self.assertEqual(self.report["assertions_seen"], 6)

    def test_source_grouping(self):
        self.assertEqual(list(self.report["calibration_by_source"]), ["manual"])
        self.assertEqual(self.report["calibration_by_source"]["manual"]["n"], 6)

    def test_volatility_orders_by_revisions(self):
        top = self.report["volatility"]
        self.assertEqual((top[0]["subject"], top[0]["predicate"]), ("test", "churn"))
        self.assertEqual(top[0]["revisions"], 2)
        self.assertEqual(top[0]["current_object"], "v2")
        wrong = next(v for v in top if v["predicate"] == "wrong")
        self.assertEqual(wrong["refuted"], 1)
        self.assertEqual(wrong["current_object"], "NOT True")

    def test_empty_repository(self):
        tmp2, repo2 = make_repo()
        self.addCleanup(tmp2.cleanup)
        report = analytics.analyze(repo2)
        self.assertEqual(report["assertions_seen"], 0)
        self.assertEqual(report["volatility"], [])


if __name__ == "__main__":
    unittest.main()
