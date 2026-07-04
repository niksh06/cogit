"""Belief-recovery benchmark harness (COG-039): generation invariants and grader."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "benchmarks"))

import belief_bench  # noqa: E402

from cogit.repo import Repository  # noqa: E402
from cogit.verify import verify_repository  # noqa: E402


class BenchmarkGenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="cogit-bench-")
        cls.out = cls.tmp.name
        cls.manifest = belief_bench.generate(cls.out, sessions=2, seed=20260704)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_manifest_and_probe_counts(self):
        self.assertEqual(len(self.manifest["sessions"]), 2)
        for session in self.manifest["sessions"]:
            self.assertEqual(session["probes"], 10)
            with open(os.path.join(self.out, "media", session["id"], "probes.json"),
                      encoding="utf-8") as handle:
                probes = json.load(handle)
            self.assertEqual({p["class"] for p in probes},
                             {"P1", "P2", "P3", "P4", "P5"})

    def test_generation_is_deterministic(self):
        with tempfile.TemporaryDirectory(prefix="cogit-bench2-") as out2:
            belief_bench.generate(out2, sessions=1, seed=20260704)
            for name in ("media/s01/probes.json", "truth/s01.json"):
                with open(os.path.join(self.out, name), encoding="utf-8") as a, \
                        open(os.path.join(out2, name), encoding="utf-8") as b:
                    self.assertEqual(a.read(), b.read())

    def test_journal_medium_is_a_valid_repository(self):
        repo = Repository.open(os.path.join(self.out, "media", "s01", "journal"))
        errors = [f for f in verify_repository(repo) if f["level"] == "error"]
        self.assertEqual(errors, [])
        anchors = {a["name"] for a in repo.list_anchors()}
        self.assertEqual(anchors, {"m1", "m2"})

    def test_dump_medium_is_one_call_equivalent(self):
        with open(os.path.join(self.out, "media", "s01", "dump.json"),
                  encoding="utf-8") as handle:
            dump = json.load(handle)
        self.assertGreater(len(dump["facts"]), 0)
        # every active fact has a first introducer recorded
        self.assertEqual({row["assertion"] for row in dump["facts"]},
                         set(dump["introducer"]))
        self.assertIn("from_anchor", dump["recap"])
        self.assertEqual({a["name"] for a in dump["anchors"]}, {"m1", "m2"})

    def test_markdown_and_transcript_shapes(self):
        with open(os.path.join(self.out, "media", "s01", "notes.md"),
                  encoding="utf-8") as handle:
            notes = handle.read()
        self.assertIn("## Current state", notes)
        self.assertIn("superseded", notes)
        self.assertIn("milestone **m2**", notes)
        with open(os.path.join(self.out, "media", "s01", "transcript.log"),
                  encoding="utf-8") as handle:
            transcript = handle.read()
        self.assertIn("-- checkpoint m2 --", transcript)
        # transcript keeps noise; disciplined notes must not
        self.assertNotIn("healthz", notes)

    def test_grader_scores_perfect_answers_at_one(self):
        answers_dir = os.path.join(self.out, "perfect-answers")
        os.makedirs(answers_dir, exist_ok=True)
        for session in self.manifest["sessions"]:
            sid = session["id"]
            with open(os.path.join(self.out, "truth", f"{sid}.json"),
                      encoding="utf-8") as handle:
                truth = json.load(handle)
            answers = {pid: {k: v for k, v in expected.items() if k != "class"}
                       for pid, expected in truth.items()}
            for medium in belief_bench.MEDIA:
                with open(os.path.join(answers_dir, f"{sid}-{medium}.json"), "w",
                          encoding="utf-8") as handle:
                    json.dump(answers, handle)
        results = belief_bench.grade(self.out, answers_dir)
        for medium in belief_bench.MEDIA:
            self.assertEqual(results["overall"][medium], 1.0)

    def test_scaled_mode_shape(self):
        with tempfile.TemporaryDirectory(prefix="cogit-bench-scale-") as out:
            manifest = belief_bench.generate(out, sessions=1, seed=20260705, segments=3)
            session = manifest["sessions"][0]
            self.assertEqual(session["probes"], 12)
            self.assertGreater(session["events"], 30)
            with open(os.path.join(out, "media", "s01", "probes.json"),
                      encoding="utf-8") as handle:
                probes = json.load(handle)
            self.assertEqual({p["class"] for p in probes}, {"P1", "P2", "P3", "P4", "P5"})
            repo = Repository.open(os.path.join(out, "media", "s01", "journal"))
            errors = [f for f in verify_repository(repo) if f["level"] == "error"]
            self.assertEqual(errors, [])

    def test_grader_partial_credit(self):
        expected = {"class": "P4", "changed": ["a b", "c d"]}
        self.assertEqual(
            belief_bench.score_answer("P4", expected, {"changed": ["a b"]}),
            2 * (1.0 * 0.5) / 1.5)
        self.assertEqual(belief_bench.score_answer("P1", {"value": True}, {"value": "true"}), 1.0)
        self.assertEqual(
            belief_bench.score_answer("P3",
                                      {"existed": True, "outcome": "refuted", "replacement": None},
                                      {"existed": True, "outcome": "superseded", "replacement": None}),
            2 / 3)


if __name__ == "__main__":
    unittest.main()
