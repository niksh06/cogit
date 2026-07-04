"""Web viewer (COG-038): state building, HTTP serving, snapshot export."""

import contextlib
import io
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "integrations"))

import web_viewer  # noqa: E402

from tests.helpers import fact_doc, make_repo, ts  # noqa: E402


class ViewerStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.repo = make_repo()
        self.addCleanup(self.tmp.cleanup)
        self.t1 = self.repo.micro_commit(fact_doc("framework", obj="stdlib"), timestamp=ts(0))
        self.t2 = self.repo.micro_commit(
            fact_doc("endpoint", obj="/api/state", when=ts(1)), timestamp=ts(1)
        )
        self.repo.anchor("viewer-start", "HEAD", timestamp=ts(2))
        self.repo.branch("side", timestamp=ts(3))
        self.repo.checkout("side", timestamp=ts(4))
        self.t3 = self.repo.micro_commit(fact_doc("experiment", obj=True, when=ts(5)), timestamp=ts(5))
        self.repo.checkout("main", timestamp=ts(6))
        self.t4 = self.repo.micro_commit(fact_doc("port", obj=8323, when=ts(7)), timestamp=ts(7))
        self.repo.annotate(self.t2["thought"], "checked by viewer tests", timestamp=ts(8))

    def test_state_covers_all_branch_tips_newest_first(self):
        state = web_viewer.build_state(self.repo)
        ids = [n["id"] for n in state["graph"]]
        self.assertIn(self.t3["thought"], ids)  # side tip present even though HEAD is main
        self.assertEqual(ids[0], self.t4["thought"])
        self.assertEqual(state["counts"]["thoughts"], 4)
        self.assertEqual(state["counts"]["branches"], 2)
        self.assertEqual(state["status"]["branch"], "main")

    def test_introducer_and_per_thought_deltas(self):
        state = web_viewer.build_state(self.repo)
        self.assertEqual(state["introducer"][self.t1["assertion"]], self.t1["thought"])
        self.assertEqual(state["introducer"][self.t3["assertion"]], self.t3["thought"])
        head_node = state["graph"][0]
        self.assertEqual(head_node["added"], [self.t4["assertion"]])
        self.assertEqual(head_node["removed"], [])

    def test_head_facts_badges_recap_annotations(self):
        state = web_viewer.build_state(self.repo)
        # HEAD is main: side-branch belief must not be active here
        self.assertEqual(len(state["head_facts"]), 3)
        self.assertNotIn(self.t3["assertion"], {r["assertion"] for r in state["head_facts"]})
        by_id = {n["id"]: n for n in state["graph"]}
        self.assertIn("viewer-start", by_id[self.t2["thought"]]["anchors"])
        self.assertIn("side", by_id[self.t3["thought"]]["branches"])
        self.assertIn("main", by_id[self.t4["thought"]]["branches"])
        recap = state["recap"]
        self.assertEqual(recap["from_anchor"], "viewer-start")
        self.assertFalse(recap["same_point"])
        self.assertEqual([t["id"] for t in recap["thoughts"]], [self.t4["thought"]])
        notes = state["annotations"][self.t2["thought"]]
        self.assertEqual(notes[0]["body"], "checked by viewer tests")

    def test_empty_repository_state(self):
        tmp2, repo2 = make_repo()
        self.addCleanup(tmp2.cleanup)
        state = web_viewer.build_state(repo2)
        self.assertEqual(state["graph"], [])
        self.assertEqual(state["head_facts"], [])
        self.assertEqual(state["counts"]["thoughts"], 0)
        self.assertIn("error", state["recap"])


class ViewerHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.repo = make_repo()
        self.addCleanup(self.tmp.cleanup)
        self.repo.micro_commit(fact_doc("served", obj=True), timestamp=ts(0))
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), web_viewer.ViewerHandler)
        self.server.repo_path = self.tmp.name
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def _get(self, path):
        with urllib.request.urlopen(self.base + path) as resp:
            return resp.status, resp.headers.get("Content-Type"), resp.read()

    def test_state_endpoint(self):
        status, ctype, body = self._get("/api/state")
        self.assertEqual(status, 200)
        self.assertIn("application/json", ctype)
        state = json.loads(body)
        self.assertEqual(state["counts"]["thoughts"], 1)
        self.assertEqual(state["head_facts"][0]["predicate"], "served")

    def test_index_serves_live_page(self):
        status, ctype, body = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ctype)
        self.assertIn(b"cogit viewer", body)
        # live page polls; the snapshot marker is the ASSIGNMENT, absent here
        self.assertNotIn(b"window.COGIT_STATE = ", body)

    def test_unknown_path_is_json_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/nope")
        error = ctx.exception
        self.assertEqual(error.code, 404)
        body = error.read()
        error.close()
        self.assertEqual(json.loads(body)["error"], "not found")

    def test_server_never_writes(self):
        before = self.repo.reflog("HEAD")
        self._get("/api/state")
        self._get("/api/state")
        self.assertEqual(self.repo.reflog("HEAD"), before)


class SnapshotTests(unittest.TestCase):
    def test_snapshot_embeds_state_and_escapes_script_breakout(self):
        tmp, repo = make_repo()
        self.addCleanup(tmp.cleanup)
        repo.micro_commit(fact_doc("payload", obj="</script><b>x"), timestamp=ts(0))
        out = os.path.join(tmp.name, "snap.html")
        web_viewer.write_snapshot(repo, out)
        with open(out, encoding="utf-8") as handle:
            html = handle.read()
        self.assertIn("window.COGIT_STATE", html)
        self.assertNotIn("</script><b>x", html)  # '<' must be <-escaped
        embedded = html.split("window.COGIT_STATE = ", 1)[1].split(";</script>", 1)[0]
        state = json.loads(embedded)
        self.assertEqual(state["head_facts"][0]["object"], "</script><b>x")

    def test_main_snapshot_mode(self):
        tmp, repo = make_repo()
        self.addCleanup(tmp.cleanup)
        repo.micro_commit(fact_doc("cli"), timestamp=ts(0))
        out = os.path.join(tmp.name, "page.html")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = web_viewer.main(["--repo", tmp.name, "--snapshot", out])
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(out))
        self.assertEqual(buf.getvalue().strip(), out)

    def test_main_reports_missing_repository(self):
        bare = tempfile.TemporaryDirectory(prefix="cogit-norepo-")
        self.addCleanup(bare.cleanup)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = web_viewer.main(
                ["--repo", bare.name, "--snapshot", os.path.join(bare.name, "x.html")]
            )
        self.assertEqual(code, 1)
        self.assertIn("error:", err.getvalue())


if __name__ == "__main__":
    unittest.main()
