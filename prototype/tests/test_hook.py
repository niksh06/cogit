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

    def test_capture_then_turn_commit(self):
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
        self.assertEqual(repo.log()[0]["message"], "Turn checkpoint: 1 tool observation(s)")

    def test_session_start_digest_empty_journal(self):
        self.assertIn("journal is empty", self._digest())

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
