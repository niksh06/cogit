"""Claude Code hook (COG-012 capture, COG-043 session-start re-anchor)."""

import contextlib
import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "integrations"))

import claude_code_hook as hook  # noqa: E402

from tests.helpers import fact_doc, ts  # noqa: E402
from cogit.repo import Repository  # noqa: E402


class HookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="cogit-hook-")
        self.addCleanup(self.tmp.cleanup)
        os.environ["COGIT_JOURNAL_DIR"] = self.tmp.name
        self.addCleanup(os.environ.pop, "COGIT_JOURNAL_DIR", None)
        os.environ.pop("COGIT_PROJECT", None)

    def _digest(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            hook.on_session_start({"cwd": self.tmp.name})
        return out.getvalue()

    def test_firehose_mode_captures_everything(self):
        os.environ["COGIT_CAPTURE"] = "all"
        self.addCleanup(os.environ.pop, "COGIT_CAPTURE", None)
        payload = {
            "cwd": self.tmp.name,
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
            "tool_response": "3 files",
            "session_id": "s-1",
        }
        hook.on_post_tool_use(payload)
        hook.on_stop(payload)
        repo = Repository.open(self.tmp.name)
        facts = repo.facts()["facts"]
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["subject"], "tool:Bash")
        self.assertEqual(repo.log()[0]["message"], "Turn checkpoint: 1 captured belief(s)")

    def test_selective_mode_ignores_noise(self):
        payload = {
            "cwd": self.tmp.name,
            "tool_name": "Bash",
            "tool_input": {"command": "ls -la"},
            "tool_response": "14 entries",
        }
        hook.on_post_tool_use(payload)
        hook.on_stop(payload)  # nothing staged -> no thought
        repo = Repository.open(self.tmp.name)
        self.assertIsNone(repo.status()["thought"])

    def test_selective_captures_git_commit_and_supersedes(self):
        os.environ["COGIT_PROJECT"] = "demo"
        self.addCleanup(os.environ.pop, "COGIT_PROJECT", None)
        first = {
            "cwd": self.tmp.name,
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m 'fix things'"},
            "tool_response": "[main abc1234] fix things\n 2 files changed",
            "session_id": "sess42xyz-full",
        }
        hook.on_post_tool_use(first)
        hook.on_stop(first)
        second = dict(first, tool_response="[main def5678] follow-up\n 1 file changed")
        hook.on_post_tool_use(second)
        hook.on_stop(second)
        repo = Repository.open(self.tmp.name)
        rows = repo.facts(subject="git:demo")["facts"]
        self.assertEqual(len(rows), 1)  # previous head_commit superseded
        self.assertEqual(rows[0]["object"], "def5678: follow-up")
        self.assertEqual(rows[0]["qualifiers"], {"branch": "main", "project": "demo"})
        # COG-052: the writer is attributable down to the session
        self.assertEqual(rows[0]["actor"], "claude-code-sess42xy")

    def test_selective_captures_suite_status_transitions(self):
        os.environ["COGIT_PROJECT"] = "demo"
        self.addCleanup(os.environ.pop, "COGIT_PROJECT", None)
        red = {
            "cwd": self.tmp.name,
            "tool_name": "Bash",
            "tool_input": {"command": "python -m unittest discover"},
            "tool_response": "Ran 5 tests\nFAILED (failures=1)",
        }
        hook.on_post_tool_use(red)
        hook.on_stop(red)
        green = dict(red, tool_response="Ran 5 tests\nOK")
        hook.on_post_tool_use(green)
        # identical repeat must not stage a rival
        hook.on_post_tool_use(green)
        hook.on_stop(green)
        repo = Repository.open(self.tmp.name)
        rows = repo.facts(subject="test:demo")["facts"]
        self.assertEqual([(r["object"], r["qualifiers"]["runner"]) for r in rows],
                         [("green", "unittest")])

    def _commit_payload(self, session, sha="abc1234", subject="fix things"):
        return {
            "cwd": self.tmp.name,
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m 'x'"},
            "tool_response": f"[main {sha}] {subject}\n 1 file changed",
            "session_id": session,
        }

    def test_capture_never_touches_the_shared_index(self):
        # COG-062: the parallel-hostility root cause — hook staging — is gone
        os.environ["COGIT_PROJECT"] = "demo"
        self.addCleanup(os.environ.pop, "COGIT_PROJECT", None)
        payload = self._commit_payload("sess-a")
        hook.on_post_tool_use(payload)
        repo = Repository.open(self.tmp.name)
        status = repo.status()
        self.assertEqual(status["staged"], [])   # buffered, not staged
        self.assertEqual(status["removed"], [])
        hook.on_stop(payload)
        status = repo.status()
        self.assertEqual(status["staged"], [])   # published atomically
        self.assertIsNotNone(status["thought"])

    def test_parallel_sessions_do_not_absorb_each_other(self):
        os.environ["COGIT_PROJECT"] = "demo"
        self.addCleanup(os.environ.pop, "COGIT_PROJECT", None)
        a = self._commit_payload("sessionA-11112222", "aaa1111", "from A")
        b = {
            "cwd": self.tmp.name, "tool_name": "Bash",
            "tool_input": {"command": "python -m unittest discover"},
            "tool_response": "Ran 5 tests\nOK", "session_id": "sessionB-33334444",
        }
        hook.on_post_tool_use(a)
        hook.on_post_tool_use(b)
        hook.on_stop(a)  # A's turn ends first
        repo = Repository.open(self.tmp.name)
        rows = {r["subject"]: r for r in repo.facts()["facts"]}
        self.assertIn("git:demo", rows)
        self.assertNotIn("test:demo", rows)  # B's capture is NOT absorbed by A
        self.assertEqual(rows["git:demo"]["actor"], "claude-code-sessionA")
        self.assertEqual(repo.log()[0]["author"], "claude-code-sessionA")
        hook.on_stop(b)
        rows = {r["subject"]: r for r in repo.facts()["facts"]}
        self.assertEqual(rows["test:demo"]["actor"], "claude-code-sessionB")
        self.assertEqual(repo.log()[0]["author"], "claude-code-sessionB")

    def test_dirty_index_defers_but_never_loses_captures(self):
        os.environ["COGIT_PROJECT"] = "demo"
        self.addCleanup(os.environ.pop, "COGIT_PROJECT", None)
        payload = self._commit_payload("sess-defer")
        repo = Repository.open(hook.journal_repo(payload).cogit_dir)
        _claim, staged = repo.add_fact(fact_doc("explicit-staging", when=ts(0)))
        hook.on_post_tool_use(payload)
        buffer = hook.buffer_path(repo, payload)
        with self.assertRaises(hook.CogitError):
            hook.on_stop(payload)  # batch refuses the dirty index...
        self.assertTrue(os.path.exists(buffer))  # ...and the buffer SURVIVES
        self.assertEqual(repo.status()["staged"], [staged])  # staging untouched
        repo.remove_fact(staged, "unstage")  # the explicit session finishes
        hook.on_stop(payload)  # retry next turn: captures land
        self.assertFalse(os.path.exists(buffer))
        rows = repo.facts(subject="git:demo")["facts"]
        self.assertEqual(len(rows), 1)

    def test_session_start_digest_empty_journal(self):
        self.assertIn("journal is empty", self._digest())

    def test_session_start_digest_reports_new_debt(self):
        # COG-067: the ratchet reaches the agent without being asked
        repo = Repository.open(hook.journal_repo({"cwd": self.tmp.name}).cogit_dir)
        repo.micro_commit(fact_doc("clean"), timestamp=ts(0))
        repo.anchor("lint-baseline-t0", "HEAD", timestamp=ts(1))
        digest = self._digest()
        self.assertIn("no new debt since lint-baseline-t0", digest)
        noisy = fact_doc("state", obj="ok")
        noisy["claim"]["subject"] = "spaced out subject"
        repo.micro_commit(noisy, timestamp=ts(2))
        digest = self._digest()
        self.assertIn("NEW finding(s) since lint-baseline-t0", digest)
        self.assertIn("supersede_fact", digest)

    def test_session_start_digest_reanchors(self):
        repo = Repository.open(hook.journal_repo({"cwd": self.tmp.name}).cogit_dir)
        repo.micro_commit(fact_doc("resume"), timestamp=ts(0))
        repo.anchor("m1", "HEAD", timestamp=ts(1))
        repo.micro_commit(fact_doc("later"), timestamp=ts(2))
        digest = self._digest()
        self.assertIn("cogit re-anchor", digest)
        self.assertIn("since m1: 1 thought(s), +1/-0 beliefs", digest)
        self.assertIn("agent_decision: test later", digest)  # recent log line
        self.assertIn("dump", digest)


if __name__ == "__main__":
    unittest.main()
