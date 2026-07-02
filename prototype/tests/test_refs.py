import os
import unittest

from tests.helpers import TS, make_repo
from cogit.errors import ConcurrentUpdateError, UserError
from cogit.refs import validate_ref_name

A = "sha256:" + "a" * 64
B = "sha256:" + "b" * 64


class RefStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.repo = make_repo()
        self.addCleanup(self.tmp.cleanup)
        self.refs = self.repo.refs

    def test_ref_name_validation(self):
        validate_ref_name("refs/heads/main")
        validate_ref_name("refs/heads/recovered/plan-b.1")
        for bad in ("refs/heads/", "refs//x", "refs/heads/a..b", "refs/heads/x.lock",
                    "refs/heads/UPPER", "refs/heads/sp ace", "refs/heads/a@{b}", "refs\\x"):
            with self.assertRaises(UserError, msg=bad):
                validate_ref_name(bad)

    def test_update_and_read(self):
        self.refs.update_ref("refs/heads/main", A, None, "agent", "commit", "first", TS)
        self.assertEqual(self.refs.read_ref("refs/heads/main"), A)

    def test_old_target_check_blocks_lost_update(self):
        self.refs.update_ref("refs/heads/main", A, None, "agent", "commit", "first", TS)
        with self.assertRaises(ConcurrentUpdateError):
            self.refs.update_ref("refs/heads/main", B, None, "agent", "commit", "stale", TS)
        # ref unchanged after failed update
        self.assertEqual(self.refs.read_ref("refs/heads/main"), A)

    def test_lock_contention(self):
        lock = os.path.join(self.repo.cogit_dir, "refs", "heads", "main.lock")
        os.makedirs(os.path.dirname(lock), exist_ok=True)
        with open(lock, "w"):
            pass
        with self.assertRaises(ConcurrentUpdateError):
            self.refs.update_ref("refs/heads/main", A, None, "agent", "commit", "locked", TS)
        os.unlink(lock)

    def test_every_move_appends_reflog(self):
        self.refs.update_ref("refs/heads/main", A, None, "agent", "commit", "first", TS)
        self.refs.update_ref("refs/heads/main", B, A, "agent", "commit", "second", TS)
        entries = self.refs.read_reflog("refs/heads/main")
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["old"], "null")
        self.assertEqual(entries[0]["new"], A)
        self.assertEqual(entries[1]["old"], A)
        self.assertEqual(entries[1]["new"], B)
        self.assertEqual(entries[1]["op"], "commit")
        self.assertEqual(entries[1]["reason"], "second")

    def test_reflog_reason_newlines_flattened(self):
        self.refs.update_ref("refs/heads/main", A, None, "agent", "commit", "line1\nline2", TS)
        entries = self.refs.read_reflog("refs/heads/main")
        self.assertEqual(entries[0]["reason"], "line1 line2")

    def test_actor_with_whitespace_rejected(self):
        with self.assertRaises(UserError):
            self.refs.update_ref("refs/heads/main", A, None, "two words", "commit", "r", TS)

    def test_head_stale_expected_content_rejected(self):
        # COG-014: a concurrent HEAD move must fail the write, not be overwritten
        raw = self.refs.read_head_raw()
        self.refs.write_head(A, None, "agent", "checkout", "detach", TS, expected_raw=raw)
        with self.assertRaises(ConcurrentUpdateError):
            self.refs.write_head(B, A, "agent", "checkout", "stale", TS, expected_raw=raw)
        # HEAD unchanged after the failed write, and only one reflog entry
        self.assertEqual(self.refs.read_head(), ("detached", A))
        self.assertEqual(len(self.refs.read_reflog("HEAD")), 1)

    def test_reflog_expire(self):
        for i in range(5):
            expected_old = None if i == 0 else f"sha256:{chr(ord('a') + i - 1) * 64}"
            self.refs.update_ref("refs/heads/main", f"sha256:{chr(ord('a') + i) * 64}",
                                 expected_old, "agent", "commit", f"c{i}", TS)
        # dry run reports but keeps everything
        kept, dropped = self.refs.expire_reflog("refs/heads/main", 2, dry_run=True)
        self.assertEqual((kept, dropped), (2, 3))
        self.assertEqual(len(self.refs.read_reflog("refs/heads/main")), 5)
        # real expiry keeps the newest entries and the file still parses
        kept, dropped = self.refs.expire_reflog("refs/heads/main", 2)
        self.assertEqual((kept, dropped), (2, 3))
        entries = self.refs.read_reflog("refs/heads/main")
        self.assertEqual([e["reason"] for e in entries], ["c3", "c4"])
        # keep >= size is a no-op; keep < 1 is a user error
        self.assertEqual(self.refs.expire_reflog("refs/heads/main", 10), (2, 0))
        with self.assertRaises(UserError):
            self.refs.expire_reflog("refs/heads/main", 0)

    def test_list_reflogs(self):
        self.refs.update_ref("refs/heads/main", A, None, "agent", "commit", "c", TS)
        self.refs.append_reflog("HEAD", None, A, "agent", "commit", "c", TS)
        names = list(self.refs.list_reflogs())
        self.assertIn("HEAD", names)
        self.assertIn("refs/heads/main", names)

    def test_head_lock_contention(self):
        lock = os.path.join(self.repo.cogit_dir, "HEAD.lock")
        with open(lock, "w"):
            pass
        with self.assertRaises(ConcurrentUpdateError):
            self.refs.write_head(A, None, "agent", "checkout", "locked", TS, expected_raw="x")
        os.unlink(lock)


if __name__ == "__main__":
    unittest.main()
