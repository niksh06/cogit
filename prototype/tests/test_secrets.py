import unittest

from tests.helpers import *  # noqa: F401,F403 (sys.path setup)
from cogit.errors import UserError
from cogit.secrets import reject_suspected_secrets


class SecretPatternTests(unittest.TestCase):
    def assert_rejected(self, text):
        with self.assertRaises(UserError, msg=text):
            reject_suspected_secrets(text)

    def assert_allowed(self, text):
        reject_suspected_secrets(text)  # must not raise

    def test_known_shapes_rejected(self):
        # secret-shaped fixtures are assembled at runtime so repository
        # scanners (e.g. GitHub push protection) never see the literal
        self.assert_rejected("key AKIA" + "ABCDEFGHIJKLMNOP in env")
        self.assert_rejected("-----BEGIN RSA PRIVATE KEY-----")
        self.assert_rejected("token ghp_" + "a1B2" * 10)
        self.assert_rejected("password = hunter2secret")
        self.assert_rejected("aws_secret_access_key: 'wJalrXUtnFEMIK7MDENG" + "bPxRfiCYEXAMPLEKEYaa'")

    def test_credentials_in_url_rejected(self):
        self.assert_rejected("fetched https://svc-account:S3cretPass@internal.example.com/repo")
        self.assert_allowed("fetched https://internal.example.com/repo without auth")

    def test_high_entropy_token_rejected(self):
        self.assert_rejected("session bearer m7Kp2Qx9Lw4Vt8Zr3Ny6Jb1Hd5Fg0Sc")

    def test_filesystem_paths_never_trigger(self):
        # COG-048: the exact live-failure string must be accepted
        self.assert_allowed(
            "~/Reports/projects/aleph/reference/cogit-claim-modeling-memo-2026-07-05.md")
        self.assert_allowed("/Users/nsh/Downloads/cogit/prototype/integrations/mcp_server.py")
        self.assert_allowed("see docs/spec/repository-layout-v1.md and tools/interop-test.sh")
        # slash-bearing random material must STILL be rejected
        self.assert_rejected("token aB3dEf/Gh1jKl/Mn0pQr/xY2zAb/Cd4eFg9")
        self.assert_rejected(
            "aws_secret_access_key: 'wJalrXUtnFEMIK7MDENG" + "bPxRfiCYEXAMPLEKEYaa'")

    def test_cogit_object_ids_never_trigger(self):
        # the tool's own IDs are long hex strings — guards must pass them
        self.assert_allowed("sha256:" + "ab12cd34" * 8)
        self.assert_allowed("blame " + "0f4e3049370b0e34ae89ea0c52f5d8312c53f7a6b9003c8976e023a70ba1e235")

    def test_identifiers_and_prose_never_trigger(self):
        self.assert_allowed("ConcurrentUpdateErrorHandlerFactoryRegistry raised again")
        self.assert_allowed("path prototype/tests/test_maintenance.py contains fixtures")
        self.assert_allowed("the quick brown fox jumps over the lazy dog repeatedly")
        self.assert_allowed("BASE64_ENCODED_CONTENT_MARKER_V2")  # no lowercase+digit mix

    def test_nested_values_scanned(self):
        with self.assertRaises(UserError):
            reject_suspected_secrets({"qualifiers": {"note": ["ok", "xoxb-123456789012-abcdefghij"]}})


if __name__ == "__main__":
    unittest.main()
