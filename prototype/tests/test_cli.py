"""CLI-level tests, including the PRD acceptance scenario."""

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from tests.helpers import fact_doc, ts  # noqa: F401 (sys.path setup)
from cogit.cli import main


class CliHarness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="cogit-cli-")
        self.addCleanup(self.tmp.cleanup)
        self.run_cli("init", self.tmp.name)

    def run_cli(self, *argv, expect=0):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--repo", self.tmp.name, *argv])
        self.assertEqual(
            code, expect, f"argv={argv}\nstdout={out.getvalue()}\nstderr={err.getvalue()}"
        )
        return out.getvalue()

    def add_fact(self, predicate, n=0, **kwargs):
        doc = fact_doc(predicate, when=ts(n), **kwargs)
        out = self.run_cli("add-fact", json.dumps(doc))
        return out.splitlines()[1].split()[-1]  # staged assertion id

    def commit(self, message, n=0):
        out = self.run_cli("commit-thought", "--message", message, "--author", "agent", "--timestamp", ts(n))
        return out.split()[-1]


class AcceptanceScenarioTests(CliHarness):
    def test_prd_acceptance_scenario(self):
        """PRD: init, add two facts, commit, branch, add different fact, checkout back."""
        a1 = self.add_fact("first")
        a2 = self.add_fact("second")
        t1 = self.commit("two facts", n=1)

        self.run_cli("branch", "hypothesis-a", "--timestamp", ts(2))
        self.run_cli("checkout", "hypothesis-a", "--timestamp", ts(3))
        a3 = self.add_fact("alternative", n=4)
        t2 = self.commit("alternative view", n=5)

        self.run_cli("checkout", "main", "--timestamp", ts(6))
        status = json.loads(self.run_cli("status", "--json"))
        self.assertEqual(status["branch"], "main")
        self.assertEqual(status["thought"], t1)

        # rewriting identical fact content returns the same object ID
        a1_again = self.add_fact("first")
        self.assertEqual(a1, a1_again)

        # cat-object decodes every object created so far
        for oid in (a1, a2, a3, t1, t2):
            decoded = json.loads(self.run_cli("cat-object", oid))
            self.assertIn(decoded["type"], ("assertion", "thought"))

        # diff reports additions and removals between the two thoughts
        diff = json.loads(self.run_cli("diff", t1, t2, "--json"))
        self.assertEqual(diff["added"], [a3])
        self.assertEqual(diff["removed"], [])

        # blame identifies the introducing thought
        blame = json.loads(self.run_cli("blame-fact", a3, t2, "--json"))
        self.assertEqual(blame["thought"], t2)

        # every HEAD movement created a reflog entry
        reflog = json.loads(self.run_cli("log", "-g", "--json"))
        self.assertGreaterEqual(len(reflog), 4)  # commit x2 + checkout x2 at minimum

        # verify: healthy repository (dirty index from a1_again -> clean it first)
        self.run_cli("remove-fact", a1_again, "--reason", "test-cleanup")
        healthy = self.run_cli("verify")
        self.assertIn("healthy", healthy)

    def test_exit_codes(self):
        # 2: not a repository
        with tempfile.TemporaryDirectory() as empty:
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = main(["--repo", empty, "status"])
            self.assertEqual(code, 2)
        # 1: user error (bad input)
        self.run_cli("add-fact", "{\"nonsense\": true}", expect=1)
        # 1: empty commit
        self.run_cli("commit-thought", "--message", "x", "--author", "a", expect=1)

    def test_verify_detects_corruption_exit_3(self):
        a1 = self.add_fact("fragile")
        self.commit("ok")
        from cogit.repo import Repository

        repo = Repository.open(self.tmp.name)
        with open(repo.store.path_for(a1), "wb") as handle:
            handle.write(b"garbage")
        self.run_cli("verify", expect=3)
        self.run_cli("cat-object", a1, expect=3)

    def test_merge_conflict_flow(self):
        self.add_fact("base")
        self.commit("base", n=0)
        self.run_cli("branch", "side", "--timestamp", ts(1))
        a_main = self.add_fact("disputed", n=2, confidence=9000)
        self.commit("main view", n=2)
        self.run_cli("checkout", "side", "--timestamp", ts(3))
        a_side = self.add_fact("disputed", n=2, confidence=1000)
        self.commit("side view", n=4)
        self.run_cli("checkout", "main", "--timestamp", ts(5))
        out = self.run_cli("merge", "side", "--timestamp", ts(6), expect=1)
        self.assertIn("CONFLICT", out)
        status = json.loads(self.run_cli("status", "--json"))
        self.assertTrue(status["merge_in_progress"])
        claim = status["conflicts"][0]["claim"]
        self.run_cli("commit-thought", "--message", "x", "--author", "a", expect=1)
        self.run_cli("resolve", claim, "--keep", a_side)
        merge_out = self.commit("merged", n=7)
        log = json.loads(self.run_cli("log", "--json"))
        self.assertEqual(log[0]["id"], merge_out)
        self.assertEqual(len(log[0]["parents"]), 2)
        self.assertIn(a_side, json.loads(self.run_cli("cat-object", log[0]["mindset"]))["assertions"])
        self.assertNotIn(a_main, json.loads(self.run_cli("cat-object", log[0]["mindset"]))["assertions"])

    def test_anchor_and_listing(self):
        self.add_fact("m")
        t1 = self.commit("milestone")
        self.run_cli("anchor", "plan-approved", t1, "--timestamp", ts(1))
        listing = self.run_cli("anchor")
        self.assertIn("plan-approved", listing)
        branches = self.run_cli("branch")
        self.assertIn("* main", branches)

    def test_facts_and_show(self):
        a1 = self.add_fact("belief-one")
        a2 = self.add_fact("belief-two")
        t1 = self.commit("two beliefs", n=1)
        result = json.loads(self.run_cli("facts", "--json"))
        self.assertEqual(result["thought"], t1)
        by_assertion = {row["assertion"]: row for row in result["facts"]}
        self.assertEqual(set(by_assertion), {a1, a2})
        # enough to pick the right ID without cat-object: claim content is inline
        self.assertEqual(
            sorted(row["predicate"] for row in result["facts"]),
            ["belief-one", "belief-two"],
        )
        text = self.run_cli("facts")
        self.assertIn("belief-one", text)
        self.assertIn("conf=9000", text)
        shown = json.loads(self.run_cli("show", t1, "--json"))
        self.assertEqual(shown["id"], t1)
        self.assertEqual(shown["message"], "two beliefs")
        self.assertEqual(len(shown["facts"]), 2)
        # works via anchor deref too
        self.run_cli("anchor", "m1", t1, "--timestamp", ts(2))
        via_anchor = json.loads(self.run_cli("facts", "m1", "--json"))
        self.assertEqual(via_anchor["thought"], t1)

    def test_add_fact_shorthand_matches_json_ids(self):
        doc = fact_doc("shorthand-parity", when=ts(0))
        json_out = self.run_cli("add-fact", json.dumps(doc))
        short_out = self.run_cli(
            "add-fact",
            "--kind", "agent_decision", "--subject", "test",
            "--predicate", "shorthand-parity", "--object", "yes",
            "--source", "manual:test:fixture", "--confidence", "9000",
            "--actor", "tester", "--method", "fixture",
            "--asserted-at", ts(0),
        )
        self.assertEqual(json_out, short_out)  # identical claim and assertion IDs

    def test_add_fact_shorthand_negates_and_validation(self):
        doc = fact_doc("original", when=ts(0))
        out = self.run_cli("add-fact", json.dumps(doc))
        original_claim = out.splitlines()[0].split()[-1]
        neg_out = self.run_cli(
            "add-fact",
            "--kind", "agent_decision", "--subject", "test",
            "--predicate", "original", "--object-json", "false",
            "--negates", original_claim,
            "--source", "agent:review", "--confidence", "9500",
            "--asserted-at", ts(1),
        )
        neg_claim = neg_out.splitlines()[0].split()[-1]
        decoded = json.loads(self.run_cli("cat-object", neg_claim))
        self.assertEqual(decoded["negates"], original_claim)
        self.assertIs(decoded["object"], False)
        # missing required shorthand flags -> user error
        self.run_cli("add-fact", "--kind", "agent_decision", expect=1)
        # both json and shorthand -> user error
        self.run_cli("add-fact", json.dumps(doc), "--kind", "agent_decision", expect=1)

    def test_log_fact_events(self):
        a1 = self.add_fact("volatile")
        t1 = self.commit("introduce", n=1)
        self.run_cli("remove-fact", a1, "--reason", "superseded")
        t2 = self.commit("remove", n=2)
        out = self.run_cli("add-fact", json.dumps(fact_doc("volatile", when=ts(0))))
        self.assertEqual(out.splitlines()[1].split()[-1], a1)  # same fact re-staged
        t3 = self.commit("re-introduce", n=3)

        introduced = json.loads(self.run_cli("log", "--introduced-fact", a1, "--json"))
        self.assertEqual([e["id"] for e in introduced], [t3, t1])  # newest first
        self.assertTrue(all(e["event"] == "introduced" for e in introduced))
        removed = json.loads(self.run_cli("log", "--removed-fact", a1, "--json"))
        self.assertEqual([e["id"] for e in removed], [t2])
        # abbreviated fact id works; flags are mutually exclusive
        short = a1[len("sha256:") : len("sha256:") + 12]
        self.assertEqual(len(json.loads(self.run_cli("log", "--introduced-fact", short, "--json"))), 2)
        self.run_cli("log", "--introduced-fact", a1, "--removed-fact", a1, expect=1)
        self.run_cli("log", "-g", "--introduced-fact", a1, expect=1)

    def test_add_fact_commit_micro_flow(self):
        # one invocation: claim + assertion + mindset + thought (COG-030)
        result = json.loads(self.run_cli(
            "add-fact",
            "--kind", "agent_decision", "--subject", "demo", "--predicate", "micro",
            "--object", "yes", "--source", "agent:s", "--confidence", "9000",
            "--actor", "fable", "--asserted-at", ts(0),
            "--commit", "--timestamp", ts(1), "--json",
        ))
        self.assertIn("thought", result)
        thought = json.loads(self.run_cli("cat-object", result["thought"]))
        self.assertEqual(thought["message"], "agent_decision: demo micro")
        self.assertEqual(thought["author"], "fable")  # defaults from assertion actor
        status = json.loads(self.run_cli("status", "--json"))
        self.assertEqual(status["staged"], [])  # index clean after micro-commit
        # micro-commit refuses to swallow unrelated staged state
        self.add_fact("staged-elsewhere")
        self.run_cli(
            "add-fact", "--kind", "agent_decision", "--subject", "demo",
            "--predicate", "second", "--object", "y", "--source", "agent:s",
            "--confidence", "9000", "--commit", expect=1,
        )

    def test_add_fact_stdin(self):
        import io as _io
        from contextlib import redirect_stdout
        from unittest.mock import patch

        from cogit.cli import main

        doc = fact_doc("via-stdin", when=ts(0))
        arg_out = self.run_cli("add-fact", json.dumps(doc))
        out = _io.StringIO()
        with patch("sys.stdin", _io.StringIO(json.dumps(doc))), redirect_stdout(out):
            code = main(["--repo", self.tmp.name, "add-fact", "-"])
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue(), arg_out)  # byte-identical IDs (idempotent)

    def test_recap(self):
        a1 = self.add_fact("keep")
        t1 = self.commit("baseline", n=1)
        self.run_cli("anchor", "task-understood", t1, "--timestamp", ts(2))
        self.add_fact("gained")
        self.commit("progress", n=3)
        self.run_cli("remove-fact", a1, "--reason", "superseded")
        self.commit("cleanup", n=4)
        result = json.loads(self.run_cli("recap", "task-understood", "--json"))
        self.assertEqual(result["from"], t1)
        self.assertEqual(len(result["thoughts"]), 2)
        self.assertEqual([t["message"] for t in result["thoughts"]], ["progress", "cleanup"])
        self.assertEqual([r["predicate"] for r in result["added"]], ["gained"])
        self.assertEqual([r["predicate"] for r in result["removed"]], ["keep"])
        text = self.run_cli("recap", "task-understood")
        self.assertIn("beliefs: +1 -1", text)
        self.assertIn("position: branch main", text)
        # unrelated <from> is a user error with a hint
        self.run_cli("branch", "island", t1, "--timestamp", ts(5))
        self.run_cli("recap", "HEAD", t1, expect=1)

    def test_annotate_and_log_annotations(self):
        a1 = self.add_fact("annotated")
        t1 = self.commit("subject thought", n=1)
        note = json.loads(self.run_cli(
            "annotate", t1, "-m", "review: solid reasoning",
            "--namespace", "audit", "--author", "reviewer",
            "--timestamp", ts(2), "--json",
        ))
        self.assertEqual(note["namespace"], "audit")
        listing = json.loads(self.run_cli("annotations", t1, "--json"))
        self.assertEqual(len(listing), 1)
        self.assertEqual(listing[0]["body"], "review: solid reasoning")
        # abbreviated target works, annotations display inline in log
        self.run_cli("annotate", t1[len("sha256:") :][:12], "-m", "second look", "--timestamp", ts(3))
        text = self.run_cli("log", "--annotations")
        self.assertIn("review: solid reasoning", text)
        self.assertIn("second look", text)
        with_json = json.loads(self.run_cli("log", "--annotations", "--json"))
        self.assertEqual(len(with_json[0]["annotations"]), 2)
        self.run_cli("verify")

    def test_abbreviated_object_ids(self):
        a1 = self.add_fact("prefixed")
        t1 = self.commit("prefix test")
        short_a1 = a1[len("sha256:") : len("sha256:") + 12]
        decoded = json.loads(self.run_cli("cat-object", short_a1))
        self.assertEqual(decoded["type"], "assertion")
        blame = json.loads(self.run_cli("blame-fact", short_a1, "--json"))
        self.assertEqual(blame["thought"], t1)
        diff = json.loads(self.run_cli("diff", t1[len("sha256:") :][:12], t1, "--json"))
        self.assertEqual(diff["added"], [])
        # unknown and too-short prefixes are user errors
        self.run_cli("cat-object", "0123456789ab", expect=1)
        self.run_cli("cat-object", "abc", expect=1)

    def test_json_on_mutating_commands(self):
        added = json.loads(self.run_cli(
            "add-fact", json.dumps(fact_doc("json-mode", when=ts(0))), "--json"
        ))
        self.assertIn("assertion", added)
        committed = json.loads(self.run_cli(
            "commit-thought", "--message", "m", "--author", "a", "--timestamp", ts(1), "--json"
        ))
        self.assertTrue(committed["thought"].startswith("sha256:"))
        branch = json.loads(self.run_cli("branch", "side", "--timestamp", ts(2), "--json"))
        self.assertEqual(branch["target"], committed["thought"])
        checkout = json.loads(self.run_cli("checkout", "side", "--timestamp", ts(3), "--json"))
        self.assertEqual(checkout, {"mode": "branch", "thought": committed["thought"]})
        merged = json.loads(self.run_cli("merge", "main", "--timestamp", ts(4), "--json"))
        self.assertEqual(merged["result"], "already-up-to-date")
        anchor = json.loads(self.run_cli(
            "anchor", "js", committed["thought"], "--timestamp", ts(5), "--json"
        ))
        self.assertEqual(anchor["name"], "js")
        listing = json.loads(self.run_cli("branch", "--json"))
        self.assertEqual(sorted(b["name"] for b in listing), ["main", "side"])

    def test_hash_object_without_write_does_not_mutate(self):
        doc = fact_doc("pure")["claim"]
        oid = self.run_cli("hash-object", "--type", "claim", json.dumps(doc)).strip()
        self.run_cli("cat-object", oid, expect=1)  # not stored
        self.run_cli("hash-object", "--type", "claim", "--write", json.dumps(doc))
        decoded = json.loads(self.run_cli("cat-object", oid))
        self.assertEqual(decoded["predicate"], "pure")


if __name__ == "__main__":
    unittest.main()
