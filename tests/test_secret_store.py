import os
import unittest

from core.security import (
    SecretProtectionError,
    is_protected_secret,
    protect_secret,
    unprotect_secret,
)


@unittest.skipUnless(os.name == "nt", "Windows DPAPI is required")
class SecretStoreTest(unittest.TestCase):
    def test_secret_round_trip_uses_dpapi_ciphertext(self):
        secret = "cloudflare-test-token-123"

        protected = protect_secret(secret)

        self.assertTrue(is_protected_secret(protected))
        self.assertNotIn(secret, protected)
        self.assertEqual(unprotect_secret(protected), secret)

    def test_protect_is_idempotent(self):
        protected = protect_secret("secret")
        self.assertEqual(protect_secret(protected), protected)

    def test_plaintext_is_supported_for_legacy_migration(self):
        self.assertEqual(unprotect_secret("legacy-plaintext"), "legacy-plaintext")

    def test_invalid_protected_value_is_rejected(self):
        with self.assertRaises(SecretProtectionError):
            unprotect_secret("dpapi:v1:not valid base64!")


if __name__ == "__main__":
    unittest.main()
