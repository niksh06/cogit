"""Agent-write ergonomics (COG-073): subject slug + lifecycle by family."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cogit.errors import UserError  # noqa: E402
from cogit.repo import normalize_subject  # noqa: E402
from tests.helpers import fact_doc, make_repo, ts  # noqa: E402


def lifecycle_assertion(when):
    return {
        "type": "assertion", "status": "asserted",
        "source": {"type": "agent", "uri": "test:ux"},
        "confidence_bps": 9100, "asserted_at": when,
        "actor": "tester", "method": {"type": "fixture"},
    }


class SubjectSlugTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.repo = make_repo()
        self.addCleanup(self.tmp.cleanup)

    def test_phrase_subjects_normalize_at_the_choke_point(self):
        doc = fact_doc("verdict", when=ts(0))
        doc["claim"]["subject"] = "  OSV Distro   Full-Scope Land "
        self.repo.micro_commit(doc, timestamp=ts(0))
        row = self.repo.facts()["facts"][0]
        self.assertEqual(row["subject"], "osv-distro-full-scope-land")

    def test_case_and_space_variants_share_one_identity(self):
        one = fact_doc("verdict", when=ts(0))
        one["claim"]["subject"] = "Cogit:COG-073 Status"
        two = fact_doc("verdict", when=ts(0))
        two["claim"]["subject"] = "cogit:cog-073 status"
        first = self.repo.micro_commit(one, timestamp=ts(0))
        second = self.repo.micro_commit(two, timestamp=ts(1))
        self.assertEqual(first["claim"], second["claim"])  # same claim family

    def test_read_filters_match_either_spelling(self):
        doc = fact_doc("verdict", when=ts(0))
        doc["claim"]["subject"] = "svc:orders api"
        self.repo.micro_commit(doc, timestamp=ts(0))
        self.assertEqual(len(self.repo.facts(subject="SVC:Orders API")["facts"]), 1)
        self.assertEqual(len(self.repo.facts(subject="svc:orders-api")["facts"]), 1)
        self.assertEqual(len(self.repo.facts(subject="svc:*")["facts"]), 1)

    def test_normalize_subject_keeps_punctuation(self):
        self.assertEqual(normalize_subject("api:/Orders V2"), "api:/orders-v2")


class LifecycleByFamilyTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.repo = make_repo()
        self.addCleanup(self.tmp.cleanup)
        doc = fact_doc("current_version", obj="0.4.1", when=ts(0))
        doc["claim"]["subject"] = "cogit:release"
        doc["claim"]["qualifiers"]["project"] = "cogit"
        self.seed = self.repo.micro_commit(doc, timestamp=ts(0))

    def test_supersede_by_subject_and_predicate(self):
        result = self.repo.supersede_fact(
            None, "0.5.0", lifecycle_assertion(ts(1)), timestamp=ts(1),
            subject="cogit:release", predicate="current_version", project="cogit")
        self.assertEqual(result["old_assertion"], self.seed["assertion"])
        rows = self.repo.facts(subject="cogit:release")["facts"]
        self.assertEqual([r["object"] for r in rows], ["0.5.0"])

    def test_family_addressing_needs_both_parts(self):
        with self.assertRaises(UserError):
            self.repo.supersede_fact(None, "x", lifecycle_assertion(ts(1)),
                                     subject="cogit:release")

    def test_empty_family_is_a_clean_error(self):
        with self.assertRaises(UserError) as ctx:
            self.repo.resolve_family("cogit:release", "nonexistent")
        self.assertIn("add-fact", str(ctx.exception))

    def test_rival_family_refuses_and_names_candidates(self):
        rival = fact_doc("current_version", obj="9.9.9", when=ts(1))
        rival["claim"]["subject"] = "cogit:release"
        rival["claim"]["qualifiers"]["project"] = "cogit"
        rival["claim"]["kind"] = "tool_observation"  # different claim, same family axis
        other = self.repo.micro_commit(rival, timestamp=ts(1))
        with self.assertRaises(UserError) as ctx:
            self.repo.resolve_family("cogit:release", "current_version")
        message = str(ctx.exception)
        self.assertIn("2 active rivals", message)
        self.assertIn(self.seed["assertion"], message)
        self.assertIn(other["assertion"], message)

    def test_retire_and_refute_by_family(self):
        self.repo.retire_fact([], "stale", "tester", timestamp=ts(1),
                              subject="cogit:release", predicate="current_version")
        self.assertEqual(self.repo.facts(subject="cogit:release")["facts"], [])
        doc = fact_doc("root_cause", obj="dns flaps", when=ts(2))
        doc["claim"]["subject"] = "bug:x"
        self.repo.micro_commit(doc, timestamp=ts(2))
        result = self.repo.refute_fact(None, lifecycle_assertion(ts(3)), timestamp=ts(3),
                                       subject="bug:x", predicate="root_cause")
        self.assertTrue(result["negation"]["assertion"])
        active = self.repo.facts(subject="bug:x")["facts"]
        self.assertEqual([r["negation"] for r in active], [True])


if __name__ == "__main__":
    unittest.main()
