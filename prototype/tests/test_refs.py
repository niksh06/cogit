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


if __name__ == "__main__":
    unittest.main()
