"""End-to-end MCP server test: real subprocess, real stdio JSON-RPC."""

import json
import os
import subprocess
import sys
import tempfile
import unittest

from tests.helpers import *  # noqa: F401,F403 (sys.path setup)

SERVER = os.path.join(os.path.dirname(__file__), "..", "integrations", "mcp_server.py")


class McpClient:
    def __init__(self, repo_path):
        self.proc = subprocess.Popen(
            [sys.executable, SERVER, "--repo", repo_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.next_id = 0

    def request(self, method, params=None):
        self.next_id += 1
        message = {"jsonrpc": "2.0", "id": self.next_id, "method": method}
        if params is not None:
            message["params"] = params
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()
        response = json.loads(self.proc.stdout.readline())
        assert response["id"] == self.next_id, response
        return response

    def notify(self, method):
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}) + "\n")
        self.proc.stdin.flush()

    def call_tool(self, name, arguments=None):
        response = self.request("tools/call", {"name": name, "arguments": arguments or {}})
        result = response["result"]
        payload = result["content"][0]["text"]
        return result["isError"], (json.loads(payload) if not result["isError"] else payload)

    def close(self):
        self.proc.stdin.close()
        self.proc.wait(timeout=10)
        self.proc.stdout.close()
        self.proc.stderr.close()


class McpServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="cogit-mcp-")
        self.addCleanup(self.tmp.cleanup)
        self.client = McpClient(self.tmp.name)
        self.addCleanup(self.client.close)

    def test_handshake_and_tool_listing(self):
        response = self.client.request("initialize", {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"},
        })
        result = response["result"]
        self.assertEqual(result["protocolVersion"], "2025-03-26")
        self.assertEqual(result["serverInfo"]["name"], "cogit")
        self.assertIn("tools", result["capabilities"])
        self.client.notify("notifications/initialized")

        tools = self.client.request("tools/list")["result"]["tools"]
        names = {tool["name"] for tool in tools}
        self.assertIn("add_fact", names)
        self.assertIn("recap", names)
        self.assertIn("dump", names)
        self.assertIn("analytics", names)
        self.assertIn("bisect_thought", names)
        # destructive maintenance is NOT exposed (ADR-0009)
        self.assertNotIn("reflog_expire", names)
        for tool in tools:
            self.assertEqual(tool["inputSchema"]["type"], "object", tool["name"])
            self.assertIn("description", tool)

        self.assertEqual(self.client.request("ping")["result"], {})
        error = self.client.request("nonsense/method")
        self.assertEqual(error["error"]["code"], -32601)

    def test_full_workflow_over_mcp(self):
        self.client.request("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}})
        self.client.notify("notifications/initialized")

        # add + micro-commit
        is_error, added = self.client.call_tool("add_fact", {
            "kind": "agent_decision", "subject": "mcp", "predicate": "works",
            "object": True, "source": "agent:mcp-test", "confidence_bps": 9500,
            "actor": "mcp-client", "commit": True,
        })
        self.assertFalse(is_error, added)
        self.assertIn("thought", added)

        # anchor the milestone, then a second belief
        is_error, _ = self.client.call_tool("anchor", {"name": "m1", "thought_id": added["thought"]})
        self.assertFalse(is_error)
        is_error, second = self.client.call_tool("add_fact", {
            "kind": "tool_observation", "subject": "suite", "predicate": "passed",
            "object": "108", "source": "tool:unittest", "confidence_bps": 10000,
            "commit": True,
        })
        self.assertFalse(is_error, second)

        # blame the first fact back to its introducing thought
        is_error, blame = self.client.call_tool("blame_fact", {"fact_id": added["assertion"]})
        self.assertFalse(is_error, blame)
        self.assertEqual(blame["thought"], added["thought"])
        self.assertEqual(blame["source"]["type"], "agent")

        # recap from the anchor: one thought, one added belief
        is_error, recap = self.client.call_tool("recap", {"from": "m1"})
        self.assertFalse(is_error, recap)
        self.assertEqual(len(recap["thoughts"]), 1)
        self.assertEqual(recap["added"][0]["predicate"], "passed")

        # dump: the one-call reader surface agrees with the pieces (COG-042)
        is_error, dump = self.client.call_tool("dump", {})
        self.assertFalse(is_error, dump)
        self.assertEqual({row["assertion"] for row in dump["facts"]},
                         set(dump["introducer"]))
        self.assertEqual(dump["recap"]["from_anchor"], "m1")

        # facts + status + verify
        is_error, facts = self.client.call_tool("facts")
        self.assertFalse(is_error)
        self.assertEqual(len(facts["facts"]), 2)
        # COG-052: explicit actors survive; nothing defaults to bare "agent"
        for row in facts["facts"]:
            self.assertNotEqual(row["actor"], "agent")

        # record: batch facts land as ONE thought (COG-044 affordance)
        is_error, recorded = self.client.call_tool("record", {
            "facts": [
                {"kind": "agent_decision", "subject": "svc:a", "predicate": "owner",
                 "object": "core", "source": "agent:test", "confidence_bps": 9000,
                 "project": "demo"},
                {"kind": "agent_decision", "subject": "svc:b", "predicate": "owner",
                 "object": "infra", "source": "agent:test", "confidence_bps": 9000,
                 "project": "demo"},
            ],
            "message": "batch: ownership decisions",
        })
        self.assertFalse(is_error, recorded)
        self.assertEqual(len(recorded["facts"]), 2)
        is_error, log = self.client.call_tool("log", {"limit": 1})
        self.assertFalse(is_error, log)
        self.assertEqual(log["thoughts"][0]["message"], "batch: ownership decisions")
        self.assertEqual(log["thoughts"][0]["id"], recorded["thought"])
        # COG-052: facts recorded without an explicit actor get the
        # per-session instance id, never bare "agent"
        is_error, facts = self.client.call_tool("facts", {"subject": "svc:a"})
        self.assertFalse(is_error)
        self.assertTrue(facts["facts"][0]["actor"].startswith("agent-"),
                        facts["facts"][0]["actor"])

        # analytics: calibration/volatility over the same history (COG-045)
        is_error, report = self.client.call_tool("analytics", {})
        self.assertFalse(is_error, report)
        self.assertGreaterEqual(report["assertions_seen"], 4)
        self.assertIn("calibration_by_band", report)

        is_error, verify = self.client.call_tool("verify")
        self.assertFalse(is_error)
        self.assertTrue(verify["healthy"], verify)

    OK_FACT = {"kind": "agent_decision", "subject": "batch:a", "predicate": "state",
               "object": "v1", "source": "agent:test", "confidence_bps": 9000}

    def test_record_is_all_or_nothing(self):
        # COG-055: a bad later item must leave HEAD and the index untouched
        self.client.request("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}})
        is_error, message = self.client.call_tool("record", {
            "facts": [dict(self.OK_FACT), {"subject": "batch:b"}],
            "message": "must not land",
        })
        self.assertTrue(is_error)
        self.assertIn("missing required field", message)
        is_error, status = self.client.call_tool("status")
        self.assertFalse(is_error)
        self.assertEqual(status["staged"], [])
        self.assertIsNone(status["thought"])
        # a removal that is not active fails with the same guarantee
        is_error, message = self.client.call_tool("record", {
            "facts": [dict(self.OK_FACT)],
            "removals": [{"assertion_id": "sha256:" + "0" * 64, "reason": "superseded"}],
            "message": "still must not land",
        })
        self.assertTrue(is_error, message)
        is_error, status = self.client.call_tool("status")
        self.assertFalse(is_error)
        self.assertEqual(status["staged"], [])
        self.assertIsNone(status["thought"])

    def test_record_refuses_dirty_index_and_preserves_it(self):
        # a batch must not absorb or roll back someone else's staging session
        self.client.request("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}})
        is_error, staged = self.client.call_tool("add_fact", {
            "kind": "agent_decision", "subject": "other", "predicate": "session",
            "object": "staging", "source": "agent:other", "confidence_bps": 8000,
        })
        self.assertFalse(is_error, staged)
        is_error, message = self.client.call_tool("record", {
            "facts": [dict(self.OK_FACT)], "message": "batch during staging",
        })
        self.assertTrue(is_error)
        self.assertIn("non-empty index", message)
        is_error, status = self.client.call_tool("status")
        self.assertFalse(is_error)
        self.assertEqual(status["staged"], [staged["assertion"]])

    def test_record_replaces_active_fact_in_one_thought(self):
        self.client.request("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}})
        is_error, first = self.client.call_tool("add_fact", {**self.OK_FACT, "commit": True})
        self.assertFalse(is_error, first)
        replacement = {**self.OK_FACT, "object": "v2"}
        is_error, batch = self.client.call_tool("record", {
            "facts": [replacement],
            "removals": [{"assertion_id": first["assertion"], "reason": "superseded"}],
            "message": "supersede v1 -> v2",
        })
        self.assertFalse(is_error, batch)
        self.assertEqual(batch["removed"], [first["assertion"]])
        is_error, facts = self.client.call_tool("facts", {"subject": "batch:a"})
        self.assertFalse(is_error)
        self.assertEqual([row["object"] for row in facts["facts"]], ["v2"])
        is_error, log = self.client.call_tool("log", {"limit": 1})
        self.assertFalse(is_error)
        self.assertEqual(log["thoughts"][0]["id"], batch["thought"])

    def test_unexpected_exceptions_are_sanitized_not_fatal(self):
        # COG-055: non-CogitError bugs must not kill the stdio loop or echo payloads
        self.client.request("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}})
        is_error, message = self.client.call_tool("add_fact", {
            **self.OK_FACT, "negates": 42,  # non-string: used to escape as AttributeError
        })
        self.assertTrue(is_error)
        self.assertIn("internal error", message)
        self.assertNotIn("42", message)  # sanitized: no payload echo
        is_error, _ = self.client.call_tool("status")
        self.assertFalse(is_error)

    def test_tool_errors_are_soft(self):
        self.client.request("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}})
        # secrets rejected through MCP too — as a tool error, not a crash
        is_error, message = self.client.call_tool("add_fact", {
            "kind": "tool_observation", "subject": "env", "predicate": "leak",
            "object": "AKIA" + "ABCDEFGHIJKLMNOP", "source": "tool:env", "confidence_bps": 10000,
        })
        self.assertTrue(is_error)
        self.assertIn("secret", message)
        # empty commit -> soft error; server keeps serving
        is_error, message = self.client.call_tool("commit_thought", {"message": "empty"})
        self.assertTrue(is_error)
        is_error, _ = self.client.call_tool("status")
        self.assertFalse(is_error)


if __name__ == "__main__":
    unittest.main()
