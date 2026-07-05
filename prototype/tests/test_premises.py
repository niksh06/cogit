"""Derivation edges / premises (ADR-0013, COG-049)."""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cogit.errors import UserError  # noqa: E402
from cogit.objects import validate_object  # noqa: E402
from tests.helpers import fact_doc, make_repo, ts  # noqa: E402


def assertion_with(premises):
    return {
        "type": "assertion", "claim": "sha256:" + "a" * 64, "status": "asserted",
        "source": {"type": "agent", "uri": "session:x"}, "confidence_bps": 8000,
        "asserted_at": ts(0), "actor": "agent", "method": {"type": "inference"},
        "premises": premises,
    }


class PremisesValidationTests(unittest.TestCase):
    def test_shape_rules(self):
        good = ["sha256:" + "b" * 64, "sha256:" + "c" * 64]
        validate_object(assertion_with(good))  # must not raise
        for bad, why in [
            ([], "empty"),
            (["not-an-oid"], "non-oid"),
            (list(reversed(good)), "unsorted"),
            ([good[0], good[0]], "duplicate"),
            ("sha256:" + "b" * 64, "not a list"),
        ]:
            with self.subTest(why=why):
                with self.assertRaises(UserError):
                    validate_object(assertion_with(bad))


class PremisesRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.repo = make_repo()
        self.addCleanup(self.tmp.cleanup)
        self.base = self.repo.micro_commit(fact_doc("evidence", confidence=9900),
                                           timestamp=ts(0))

    def _derived_doc(self, premises):
        doc = fact_doc("conclusion", obj="root-cause-x", confidence=8200, when=ts(1))
        doc["assertion"]["premises"] = premises
        return doc

    def test_premises_must_reference_existing_assertions(self):
        with self.assertRaises(UserError):
            self.repo.add_fact(self._derived_doc(["sha256:" + "d" * 64]))
        with self.assertRaises(UserError):  # a claim id is not an assertion
            self.repo.add_fact(self._derived_doc([self.base["claim"]]))

    def test_premises_round_trip_in_rows_and_dump(self):
        derived = self.repo.micro_commit(self._derived_doc([self.base["assertion"]]),
                                         timestamp=ts(1))
        rows = self.repo.facts()["facts"]
        by_assertion = {row["assertion"]: row for row in rows}
        self.assertEqual(by_assertion[derived["assertion"]]["premises"],
                         [self.base["assertion"]])
        self.assertEqual(by_assertion[self.base["assertion"]]["premises"], [])
        self.assertEqual(by_assertion[self.base["assertion"]]["actor"], "tester")  # COG-052
        dump = self.repo.dump()
        dumped = {row["assertion"]: row for row in dump["facts"]}
        self.assertEqual(dumped[derived["assertion"]]["premises"],
                         [self.base["assertion"]])

    def test_premises_change_assertion_identity(self):
        with_premises = self._derived_doc([self.base["assertion"]])
        without = self._derived_doc([self.base["assertion"]])
        del without["assertion"]["premises"]
        _c1, a_with = self.repo.add_fact(with_premises)
        _c2, a_without = self.repo.add_fact(without)
        self.assertNotEqual(a_with, a_without)


class PremisesCliTests(unittest.TestCase):
    def test_cli_premise_flag_expands_prefixes(self):
        import io
        from contextlib import redirect_stdout
        from cogit.cli import main
        tmp, repo = make_repo()
        self.addCleanup(tmp.cleanup)

        def run(*argv):
            out = io.StringIO()
            with redirect_stdout(out):
                code = main(["--repo", tmp.name, *argv])
            self.assertEqual(code, 0, out.getvalue())
            return out.getvalue()

        base = repo.micro_commit(fact_doc("evidence"), timestamp=ts(0))
        prefix = base["assertion"].removeprefix("sha256:")[:12]
        run("add-fact", "--kind", "agent_decision", "--subject", "bug:x",
            "--predicate", "root_cause", "--object", "pool-exhaustion",
            "--source", "agent:s", "--confidence", "8200",
            "--asserted-at", ts(1), "--premise", prefix,
            "--commit", "--timestamp", ts(1))
        rows = json.loads(run("facts", "--json"))["facts"]
        derived = next(r for r in rows if r["predicate"] == "root_cause")
        self.assertEqual(derived["premises"], [base["assertion"]])


if __name__ == "__main__":
    unittest.main()
