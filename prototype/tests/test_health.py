"""Project parity + compact reader + health surface (COG-059)."""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "integrations"))

import analytics  # noqa: E402
import health as health_mod  # noqa: E402

from cogit.errors import UserError  # noqa: E402
from tests.helpers import fact_doc, make_repo, ts  # noqa: E402


def pdoc(predicate, obj, project, when, **kwargs):
    doc = fact_doc(predicate, obj=obj, when=when, **kwargs)
    doc["claim"]["qualifiers"]["project"] = project
    doc["claim"]["subject"] = f"{project}:topic"
    return doc


class TwoProjectScopingTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.repo = make_repo()
        self.addCleanup(self.tmp.cleanup)
        self.a1 = self.repo.micro_commit(pdoc("state", "v1", "alpha", ts(0)), timestamp=ts(0))
        self.b1 = self.repo.micro_commit(pdoc("state", "w1", "beta", ts(1)), timestamp=ts(1))
        # alpha revises; beta stays put — churn belongs to alpha only
        self.repo.supersede_fact(self.a1["assertion"], "v2", {
            "type": "assertion", "status": "asserted",
            "source": {"type": "agent", "uri": "t"}, "confidence_bps": 9000,
            "asserted_at": ts(2), "actor": "tester", "method": {"type": "fixture"},
        }, timestamp=ts(2))

    def test_analytics_project_scopes_classification(self):
        report = analytics.analyze(self.repo, project="alpha")
        self.assertEqual(report["project"], "alpha")
        self.assertEqual(report["assertions_seen"], 2)  # v1 superseded + v2 open
        subjects = {f["subject"] for f in report["volatility"]}
        self.assertEqual(subjects, {"alpha:topic"})
        beta = analytics.analyze(self.repo, project="beta")
        self.assertEqual(beta["assertions_seen"], 1)

    def test_dump_project_scopes_log_too(self):
        dump = self.repo.dump(project="alpha")
        log_ids = [entry["id"] for entry in dump["log"]]
        self.assertNotIn(self.b1["thought"], log_ids)  # beta thought filtered
        self.assertEqual(len(log_ids), 2)  # alpha assert + alpha supersede
        subjects = {row["subject"] for row in dump["facts"]}
        self.assertEqual(subjects, {"alpha:topic"})

    def test_fact_rows_expose_asserted_at_and_method(self):
        row = self.repo.facts(project="beta")["facts"][0]
        self.assertEqual(row["asserted_at"], ts(1))
        self.assertEqual(row["method"], "fixture")

    def test_health_requires_project_on_shared_journal(self):
        with self.assertRaises(UserError) as ctx:
            health_mod.health(self.repo)
        self.assertIn("alpha", str(ctx.exception))
        self.assertIn("beta", str(ctx.exception))

    def test_health_scopes_and_counts(self):
        doc = health_mod.health(self.repo, project="alpha")
        self.assertEqual(doc["project"], "alpha")
        self.assertEqual(doc["beliefs"]["active"], 1)
        self.assertEqual(doc["beliefs"]["outcomes"]["superseded"], 1)
        self.assertEqual(doc["beliefs"]["outcomes"]["open"], 1)
        self.assertEqual(doc["beliefs"]["revised_families"], 1)
        self.assertTrue(doc["integrity"]["healthy"])
        self.assertIsNotNone(doc["last_project_thought"])
        # no foreign project content anywhere in the document
        self.assertNotIn("beta:topic", json.dumps(doc))

    def test_unknown_project_is_empty_not_global(self):
        doc = health_mod.health(self.repo, project="ghost")
        self.assertEqual(doc["project"], "ghost")
        self.assertEqual(doc["beliefs"]["active"], 0)
        self.assertEqual(doc["beliefs"]["outcomes"],
                         {"open": 0, "superseded": 0, "refuted": 0, "retired": 0})


class ProjectSlugNormalizationTests(unittest.TestCase):
    """COG-063: 'Aleph' vs 'aleph' must never split a project again."""

    def setUp(self):
        self.tmp, self.repo = make_repo()
        self.addCleanup(self.tmp.cleanup)

    def test_write_normalizes_project_qualifier(self):
        doc = fact_doc("case", obj="v", when=ts(0))
        doc["claim"]["qualifiers"]["project"] = "  Aleph  Prime "
        self.repo.micro_commit(doc, timestamp=ts(0))
        row = self.repo.facts()["facts"][0]
        self.assertEqual(row["qualifiers"]["project"], "aleph-prime")

    def test_read_filters_normalize_too(self):
        doc = fact_doc("case", obj="v", when=ts(0))
        doc["claim"]["qualifiers"]["project"] = "aleph"
        self.repo.micro_commit(doc, timestamp=ts(0))
        for spelled in ("aleph", "Aleph", "ALEPH"):
            self.assertEqual(len(self.repo.facts(project=spelled)["facts"]), 1, spelled)
        self.assertEqual(health_mod.health(self.repo, project="Aleph")["project"], "aleph")
        self.assertEqual(analytics.analyze(self.repo, project="ALEPH")["assertions_seen"], 1)

    def test_case_variants_produce_identical_ids(self):
        upper = fact_doc("owner", obj="core", when=ts(0))
        upper["claim"]["qualifiers"]["project"] = "Aleph"
        lower = fact_doc("owner", obj="core", when=ts(0))
        lower["claim"]["qualifiers"]["project"] = "aleph"
        c1, a1 = self.repo.add_fact(upper)
        c2, a2 = self.repo.add_fact(lower)
        self.assertEqual((c1, a1), (c2, a2))  # one family, not two


class CompactModeTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.repo = make_repo()
        self.addCleanup(self.tmp.cleanup)

    def test_health_is_bounded_on_long_prose(self):
        prose = ("the quick brown fox keeps explaining itself at length " * 8).strip()
        for n in range(125):
            doc = fact_doc(f"case_{n:03d}", obj=f"{prose} #{n}", when=ts(n))
            doc["claim"]["qualifiers"]["project"] = "bulk"
            doc["claim"]["subject"] = f"bulk:{n:03d}"
            self.repo.micro_commit(doc, timestamp=ts(n))
        doc = health_mod.health(self.repo, project="bulk")
        size = len(json.dumps(doc, ensure_ascii=False).encode("utf-8"))
        self.assertLess(size, 20_000, f"health doc is {size} bytes")
        self.assertEqual(doc["beliefs"]["active"], 125)  # totals stay exact

    def test_compact_dump_previews_but_full_mode_unchanged(self):
        long_obj = "x" * 500
        self.repo.micro_commit(fact_doc("blob", obj=long_obj), timestamp=ts(0))
        full = self.repo.dump()
        self.assertEqual(full["facts"][0]["object"], long_obj)
        self.assertNotIn("object_truncated", full["facts"][0])
        compact = self.repo.dump(compact=True)
        row = compact["facts"][0]
        self.assertTrue(row["object_truncated"])
        self.assertLess(len(row["object"]), 140)
        self.assertEqual(row["object_bytes"], 500)
        # identity, provenance and scalars survive compaction
        self.assertEqual(row["assertion"], full["facts"][0]["assertion"])
        self.assertEqual(row["confidence_bps"], full["facts"][0]["confidence_bps"])

    def test_single_project_journal_needs_no_arg(self):
        doc = fact_doc("solo", obj="fine", when=ts(0))
        doc["claim"]["qualifiers"]["project"] = "only"
        self.repo.micro_commit(doc, timestamp=ts(0))
        report = health_mod.health(self.repo)
        self.assertEqual(report["project"], "only")


if __name__ == "__main__":
    unittest.main()
