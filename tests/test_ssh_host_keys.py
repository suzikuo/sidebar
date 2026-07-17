import base64
import hashlib
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from plugins.ssh_manager.views import (
    HostKeyConfirmationRequired,
    SFTPSession,
)


class _FakeKey:
    def get_name(self):
        return "ssh-ed25519"

    def asbytes(self):
        return b"agile-tiles-test-host-key"


class _MissingHostKeyPolicy:
    pass


class _FakeClient:
    def __init__(self, key=None, unknown_host=False):
        self.key = key
        self.unknown_host = unknown_host
        self.policy = None
        self.system_keys_loaded = False
        self.loaded_host_keys = []
        self.closed = False

    def load_system_host_keys(self):
        self.system_keys_loaded = True

    def load_host_keys(self, path):
        self.loaded_host_keys.append(path)

    def set_missing_host_key_policy(self, policy):
        self.policy = policy

    def connect(self, **_kwargs):
        if self.unknown_host:
            self.policy.missing_host_key(self, "[example.com]:2222", self.key)

    def close(self):
        self.closed = True


class _FakeHostKeys:
    def __init__(self):
        self.loaded_paths = []
        self.added = []
        self.saved_paths = []

    def load(self, path):
        self.loaded_paths.append(path)

    def add(self, hostname, key_type, key):
        self.added.append((hostname, key_type, key))

    def save(self, path):
        self.saved_paths.append(path)


class SSHHostKeyTest(unittest.TestCase):
    def test_confirmation_uses_sha256_fingerprint(self):
        key = _FakeKey()
        confirmation = HostKeyConfirmationRequired("example.com", key)
        expected = base64.b64encode(hashlib.sha256(key.asbytes()).digest())
        expected = "SHA256:" + expected.decode("ascii").rstrip("=")

        self.assertEqual(confirmation.hostname, "example.com")
        self.assertEqual(confirmation.key_type, "ssh-ed25519")
        self.assertEqual(confirmation.fingerprint, expected)

    def test_unknown_host_key_is_not_automatically_accepted(self):
        key = _FakeKey()
        client = _FakeClient(key=key, unknown_host=True)
        paramiko = types.SimpleNamespace(
            MissingHostKeyPolicy=_MissingHostKeyPolicy,
            SSHClient=lambda: client,
        )

        with self.assertRaises(HostKeyConfirmationRequired):
            SFTPSession._open_paramiko_client(
                paramiko,
                {"hostname": "example.com", "port": 2222},
            )

        self.assertTrue(client.system_keys_loaded)
        self.assertTrue(client.closed)

    def test_plugin_known_hosts_file_is_loaded(self):
        client = _FakeClient()
        paramiko = types.SimpleNamespace(
            MissingHostKeyPolicy=_MissingHostKeyPolicy,
            SSHClient=lambda: client,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            known_hosts = Path(temp_dir) / "known_hosts"
            known_hosts.touch()
            result = SFTPSession._open_paramiko_client(
                paramiko,
                {"hostname": "example.com", "port": 22},
                known_hosts,
            )

        self.assertIs(result, client)
        self.assertEqual(client.loaded_host_keys, [str(known_hosts)])

    def test_confirmed_host_key_is_saved(self):
        key = _FakeKey()
        confirmation = HostKeyConfirmationRequired("example.com", key)
        fake_host_keys = _FakeHostKeys()
        fake_paramiko = types.SimpleNamespace(HostKeys=lambda: fake_host_keys)

        with tempfile.TemporaryDirectory() as temp_dir:
            known_hosts = Path(temp_dir) / "ssh" / "known_hosts"
            session = SFTPSession({}, known_hosts)
            with patch.dict(sys.modules, {"paramiko": fake_paramiko}):
                session.trust_host_key(confirmation)

            self.assertEqual(
                fake_host_keys.added,
                [("example.com", "ssh-ed25519", key)],
            )
            self.assertEqual(fake_host_keys.saved_paths, [str(known_hosts)])


if __name__ == "__main__":
    unittest.main()
