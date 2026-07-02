import json
import os
import sys
import tempfile
import unittest

from tests.helpers import fact_doc, make_repo, ts
from cogit.bisect import BAD, GOOD, SKIP, bisect_thought
from cogit.errors import UserError


class BisectTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.repo = make_repo()
        self.addCleanup(self.tmp.cleanup)
        # linear history t0..t5; the "wrong belief" enters at t3
        self.thoughts = []
        self.probed = []
        for n in range(6):
            self.repo.add_fact(fact_doc(f"step-{n}"))
            if n == 3:
                _c, self.bad_fact = self.repo.add_fact(fact_doc("wrong-belief"))
            self.thoughts.append(self.repo.commit_thought(f"t{n}", "agent", ts(n)))

    def oracle(self, verdict_map=None):
        def run(thought_oid):
            self.probed.append(thought_oid)
            if verdict_map and thought_oid in verdict_map:
                return verdict_map[thought_oid]
            has_bad = self.bad_fact in self.repo._mindset_assertions(thought_oid)
            return BAD if has_bad else GOOD

        return run

    def test_finds_first_bad(self):
        result = bisect_thought(self.repo, self.thoughts[0], self.thoughts[5], self.oracle())
        self.assertEqual(result["result"], "found")
        self.assertEqual(result["first_bad"], self.thoughts[3])
        self.assertEqual(result["skipped_suspects"], [])
        # binary search, not a linear scan: 5 candidates -> at most 3 probes
        self.assertLessEqual(len(self.probed), 3)
        # log is replayable: every probe recorded with its verdict
        self.assertEqual([e["thought"] for e in result["log"]], self.probed)

    def test_skip_on_first_bad_narrows_to_candidate_range(self):
        result = bisect_thought(
            self.repo, self.thoughts[0], self.thoughts[5],
            self.oracle({self.thoughts[3]: SKIP}),
        )
        # the skipped thought could be the first bad -> honest inconclusive range
        self.assertEqual(result["result"], "inconclusive")
        self.assertEqual(result["range"], [self.thoughts[3], self.thoughts[4]])

    def test_all_skipped_is_inconclusive(self):
        result = bisect_thought(
            self.repo, self.thoughts[0], self.thoughts[5],
            lambda oid: SKIP,
        )
        self.assertEqual(result["result"], "inconclusive")
        self.assertIsNone(result["first_bad"])
        self.assertGreater(len(result["range"]), 1)

    def test_good_must_be_ancestor(self):
        with self.assertRaises(UserError):
            bisect_thought(self.repo, self.thoughts[5], self.thoughts[0], self.oracle())
        with self.assertRaises(UserError):
            bisect_thought(self.repo, self.thoughts[2], self.thoughts[2], self.oracle())


class BisectCliTests(unittest.TestCase):
    def test_cli_run_with_real_oracle(self):
        import io
        from contextlib import redirect_stdout

        from cogit.cli import main
        from cogit.repo import Repository, init_repository

        tmp = tempfile.TemporaryDirectory(prefix="cogit-bisect-")
        self.addCleanup(tmp.cleanup)
        init_repository(tmp.name)
        repo = Repository.open(tmp.name)
        thoughts = []
        for n in range(4):
            repo.add_fact(fact_doc(f"s{n}"))
            if n == 2:
                repo.add_fact(fact_doc("regression"))
            thoughts.append(repo.commit_thought(f"t{n}", "agent", ts(n)))

        proto_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        # oracle: bad when the regression belief is active at the probed thought
        oracle = (
            f'PYTHONPATH={proto_dir} {sys.executable} -m cogit --repo {tmp.name} '
            f'facts "$COGIT_THOUGHT" --json | grep -q regression && exit 1 || exit 0'
        )
        log_path = os.path.join(tmp.name, "bisect.log")
        out = io.StringIO()
        with redirect_stdout(out):
            code = main([
                "--repo", tmp.name, "bisect-thought",
                "--good", thoughts[0], "--bad", thoughts[3],
                "--run", oracle, "--log", log_path, "--json",
            ])
        self.assertEqual(code, 0, out.getvalue())
        result = json.loads(out.getvalue())
        self.assertEqual(result["first_bad"], thoughts[2])
        with open(log_path, "r", encoding="utf-8") as handle:
            lines = handle.read().strip().splitlines()
        self.assertTrue(lines[0].startswith("# bisect-thought"))
        self.assertTrue(all(line.split()[1] in ("good", "bad", "skip") for line in lines[1:]))


if __name__ == "__main__":
    unittest.main()
