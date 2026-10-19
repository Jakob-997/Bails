#!/usr/bin/python3
"""RPC-boundary tests; run the regtest suite for real Core restoration."""
import base64
import contextlib
import importlib.machinery
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader("qr_wallet", str(ROOT / "bails/.local/bin/bails-qr-wallet"))
spec = importlib.util.spec_from_loader(loader.name, loader)
wallet = importlib.util.module_from_spec(spec)
loader.exec_module(wallet)


class WalletTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "transfer.json"
        self.calls = []
        self.raw = b"SQLite format 3\0" + b"public database" * 500
        self.info = {"ismine": True, "parent_desc": "public#checksum"}
        self.status = {"private_keys_enabled": False, "descriptors": True}
        self.private = False
        self.network = "regtest"
        self.cli = patch.object(wallet.subprocess, "run", side_effect=self.rpc)
        self.cli.start()
        self.addCleanup(self.cli.stop)

    def rpc(self, command, **kwargs):
        self.calls.append((command, kwargs))
        args = [s for s in command[1:] if not s.startswith("-")]
        method, *params = args
        result = None
        if method == "getblockchaininfo":
            result = {"chain": self.network}
        elif method == "exportwatchonlywallet":
            Path(params[0]).write_bytes(self.raw)
        elif method == "restorewallet":
            self.assertEqual(Path(params[1]).read_bytes(), self.raw)
            self.assertEqual(params[2], "false")
        elif method == "getwalletinfo":
            result = self.status
        elif method == "getaddressinfo":
            result = self.info
        elif method == "listdescriptors":
            result = {"descriptors": [{"desc": "private secret" if self.private else "public"}]}
        elif method == "getdescriptorinfo":
            self.assertIn("-stdin", command)
            self.assertNotIn("private secret", command)
            result = {"descriptor": "public#checksum", "hasprivatekeys": self.private}
        elif method != "unloadwallet":
            raise AssertionError("Unexpected RPC: " + method)
        return subprocess.CompletedProcess(command, 0, json.dumps(result), "")

    def methods(self):
        return [next(s for s in command[1:] if not s.startswith("-")) for command, _ in self.calls]

    def export(self):
        wallet.transfer("export", str(self.path), "offline", ["-regtest"])
        return json.loads(self.path.read_bytes())

    def address(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            wallet.transfer("address", "bcrt1address", "offline", ["-regtest"])
        return output.getvalue()

    def test_database_export_uses_core_watch_only_rpc(self):
        bundle = self.export()
        self.assertEqual(bundle["version"], 2)
        self.assertEqual(base64.b64decode(bundle["wallet"]), self.raw)
        self.assertEqual(self.methods(), ["getblockchaininfo", "exportwatchonlywallet"])
        self.assertFalse(self.path.with_suffix(".core.dat").exists())

    def test_database_restore_checks_private_keys_and_cleans_temporary_file(self):
        self.export()
        wallet.transfer("import", str(self.path), "online", ["-regtest"])
        self.assertIn("restorewallet", self.methods())
        self.assertIn("listdescriptors", self.methods())
        self.assertFalse(self.path.with_suffix(".received.dat").exists())

    def test_wrong_network_rejected_before_restore(self):
        self.export()
        self.network = "main"
        with self.assertRaisesRegex(ValueError, "different Bitcoin network"):
            wallet.transfer("import", str(self.path), "online", [])
        self.assertNotIn("restorewallet", self.methods())

    def test_signing_wallet_unloaded_and_rejected(self):
        self.export()
        self.status["private_keys_enabled"] = True
        with self.assertRaisesRegex(ValueError, "not watch-only"):
            wallet.transfer("import", str(self.path), "online", [])
        self.assertEqual(self.methods()[-1], "unloadwallet")

    def test_private_descriptor_unloaded_and_rejected(self):
        self.export()
        self.private = True
        with self.assertRaisesRegex(ValueError, "contains private keys"):
            wallet.transfer("import", str(self.path), "online", [])
        self.assertEqual(self.methods()[-1], "unloadwallet")

    def test_malformed_database_rejected_before_restore(self):
        for encoded in ("%%%", base64.b64encode(b"not sqlite").decode()):
            self.path.write_text(json.dumps({"format": "bails-watch-only", "version": 2,
                                            "network": "regtest", "wallet": encoded}))
            with self.assertRaises(ValueError):
                wallet.transfer("import", str(self.path), "online", [])
        self.assertNotIn("restorewallet", self.methods())

    def test_export_limit_and_cleanup(self):
        self.raw = b"SQLite format 3\0" + b"a" * wallet.MAX_FILE
        with self.assertRaisesRegex(ValueError, "1 MiB"):
            self.export()
        self.assertFalse(self.path.exists())
        self.assertFalse(self.path.with_suffix(".core.dat").exists())

    def test_watch_only_ownership_is_separate_from_keys(self):
        text = self.address()
        self.assertIn("Address belongs", text)
        self.assertIn("Private keys: No", text)
        self.assertNotIn("listdescriptors", self.methods())

    def test_signing_key_is_address_specific_and_not_in_arguments(self):
        self.status["private_keys_enabled"] = True
        self.private = True
        text = self.address()
        self.assertIn("Private keys: Yes", text)
        self.assertIn("additional keys or conditions", text)
        self.assertNotIn("private secret", text)

    def test_mixed_wallet_public_address(self):
        self.status["private_keys_enabled"] = True
        self.assertIn("Private keys: No signing key", self.address())

    def test_unrelated_private_descriptor_does_not_claim_signing(self):
        self.status["private_keys_enabled"] = True
        self.private = True
        self.info["parent_desc"] = "other-address#checksum"
        self.assertIn("Private keys: No signing key", self.address())

    def test_missing_parent_is_unknown(self):
        self.status["private_keys_enabled"] = True
        self.info.pop("parent_desc")
        self.assertIn("Private keys: Not checked", self.address())

    def test_locked_wallet_does_not_claim_keys(self):
        self.status.update(private_keys_enabled=True, unlocked_until=0)
        self.assertIn("Private keys: Not checked", self.address())
        self.assertNotIn("listdescriptors", self.methods())

    def test_unrelated_address(self):
        self.info = {"ismine": False}
        self.assertIn("does NOT belong", self.address())
        self.assertNotIn("getwalletinfo", self.methods())


if __name__ == "__main__":
    unittest.main()
