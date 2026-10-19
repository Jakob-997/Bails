#!/usr/bin/python3
"""RPC-boundary regression tests; real Core coverage is in bails-qr.sh."""
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

PARENT = "wpkh([d34db33f/84h/1h/0h]tpubABC123/0/*)#checksum"
ADDRESS = "bcrt1exampleaddress"


class WalletTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "transfer.json"
        self.calls = []
        self.info = {"address": ADDRESS, "ismine": True, "parent_desc": PARENT, "hdkeypath": "m/84h/1h/0h/0/7"}
        self.status = {"private_keys_enabled": True, "descriptors": True, "blank": False}
        self.keys = [{"xpub": "tpubABC123", "has_private": True,
                      "descriptors": [{"desc": PARENT, "active": True}]}]
        self.derived = [ADDRESS]
        self.loaded = ["offline"]
        self.directory_names = ["offline", "archived"]
        self.fail_load = set()
        self.fail_address = set()
        self.fail_unload = set()
        self.invalid = False
        self.private = False
        self.network = "regtest"
        self.descriptors = [{"desc": PARENT, "timestamp": 123, "active": True, "internal": False,
                             "range": [0, 1000], "next": 8, "next_index": 8}]
        self.raw = b"SQLite format 3\0" + b"public database" * 500
        self.cli = patch.object(wallet.subprocess, "run", side_effect=self.rpc_run)
        self.cli.start()
        self.addCleanup(self.cli.stop)

    def rpc_run(self, command, **kwargs):
        self.calls.append((command, kwargs))
        args = [s for s in command[1:] if not s.startswith("-")]
        method, *params = args
        selected = next((s.split("=", 1)[1] for s in command if s.startswith("-rpcwallet=")), None)
        if method == "getblockchaininfo":
            result = {"chain": self.network}
        elif method == "getwalletinfo":
            result = self.status
        elif method == "getaddressinfo":
            if selected in self.fail_address:
                raise ValueError("Address lookup failed")
            result = self.info
        elif method == "gethdkeys":
            self.assertEqual(params, [])  # Never request/export private keys.
            result = self.keys
        elif method == "deriveaddresses":
            self.assertEqual(params[0], self.info["parent_desc"])
            self.assertEqual(json.loads(params[1]), [7, 7])
            result = self.derived
        elif method == "validateaddress":
            result = {"isvalid": not self.invalid}
        elif method == "listwallets":
            result = list(self.loaded)
        elif method == "listwalletdir":
            result = {"wallets": [{"name": name} for name in self.directory_names]}
        elif method == "loadwallet":
            self.assertEqual(len(params), 1)  # Preserve startup preferences.
            if params[0] in self.fail_load:
                raise ValueError("Could not load wallet")
            self.loaded.append(params[0])
            result = {"name": params[0]}
        elif method == "unloadwallet":
            self.assertEqual(params, ["online", "false"] if params[0] == "online" else [params[0]])
            if params[0] in self.fail_unload:
                raise ValueError("Unload failed")
            self.loaded.remove(params[0])
            result = None
        elif method == "listdescriptors":
            result = {"descriptors": self.descriptors}
        elif method == "listlabels":
            result = ["", "Savings\nUnicode: café"]
        elif method == "getaddressesbylabel":
            result = {ADDRESS if params[0] else "bcrt1unused": {"purpose": "receive"}}
        elif method == "getdescriptorinfo":
            self.assertIn("-stdin", command)
            result = {"descriptor": PARENT, "hasprivatekeys": self.private}
        elif method == "restorewallet":
            self.assertEqual(Path(params[1]).read_bytes(), self.raw)
            self.assertEqual(params[2], "false")
            self.loaded.append(params[0])
            result = {"name": params[0]}
        elif method == "createwallet":
            self.assertEqual(params[1:3], ["true", "true"])
            self.loaded.append(params[0])
            self.status["private_keys_enabled"] = False
            result = {"name": params[0]}
        elif method == "importdescriptors":
            result = [{"success": True}]
        elif method == "setlabel":
            result = None
        else:
            raise AssertionError("Unexpected RPC: " + method)
        return subprocess.CompletedProcess(command, 0, json.dumps(result), "")

    def methods(self):
        return [next(s for s in command[1:] if not s.startswith("-")) for command, _ in self.calls]

    def address(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            wallet.transfer("address", ADDRESS, "offline", ["-regtest"])
        return output.getvalue()

    def export(self):
        wallet.transfer("export", str(self.path), "offline", ["-regtest"])
        return json.loads(self.path.read_bytes())

    def database_envelope(self):
        self.path.write_text(json.dumps({"format": "bails-watch-only", "version": 2,
                                        "network": "regtest",
                                        "wallet": base64.b64encode(self.raw).decode()}))

    def test_hd_key_confirmation_derives_exact_address(self):
        self.assertIn("This wallet has the key needed to spend", self.address())
        self.assertIn("✓", self.address())
        self.assertIn("deriveaddresses", self.methods())
        self.assertNotIn("getdescriptorinfo", self.methods())
        self.assertNotIn("listdescriptors", self.methods())

    def test_master_inventory_key_and_normalized_account_descriptor_can_differ(self):
        self.keys[0]["xpub"] = "tpubStoredMasterKey"
        self.assertIn("This wallet has the key needed to spend", self.address())
        self.assertIn("deriveaddresses", self.methods())

    def test_ambiguous_key_inventory_is_not_confirmation(self):
        self.keys.append({"xpub": "tpubOther", "has_private": True,
                          "descriptors": [{"desc": PARENT}]})
        self.assertIn("Key status not verified", self.address())

    def test_other_descriptor_with_private_key_is_not_confirmation(self):
        self.keys[0]["descriptors"][0]["desc"] = "other descriptor"
        self.assertIn("Key status not verified", self.address())

    def test_derived_address_mismatch_is_not_confirmation(self):
        self.derived = ["bcrt1wrongaddress"]
        self.assertIn("derived address did not match", self.address())
        self.assertNotIn("This wallet has the key needed to spend", self.address())

    def test_core_uppercase_bech32_qr_uses_validated_canonical_address(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            wallet.transfer("address", ADDRESS.upper(), "offline", [])
        self.assertIn("This wallet has the key needed to spend", output.getvalue())
        self.assertIn("Address ownership: confirmed", output.getvalue())

    def test_search_display_lowercases_bech32_and_preserves_base58(self):
        for address, expected in ((ADDRESS.upper(), ADDRESS.lower()),
                                  ("1CaseSensitiveAddress", "1CaseSensitiveAddress")):
            with contextlib.redirect_stdout(io.StringIO()):
                wallet.transfer("address-all", address, str(self.path), [])
            self.assertIn("\n" + expected + "\n", self.path.read_text(encoding="utf-8"))

    def test_base58_is_not_blindly_case_folded(self):
        self.info["address"] = "1CaseSensitiveAddress"
        self.derived = ["1casesensitiveaddress"]
        self.assertIn("derived address did not match", self.address())

    def test_missing_canonical_address_never_confirms(self):
        self.info.pop("address")
        self.assertIn("Key status not verified", self.address())

    def test_public_hd_key_is_not_confirmation(self):
        self.keys[0]["has_private"] = False
        self.assertIn("Key status not verified", self.address())

    def test_missing_parent_is_unknown(self):
        self.info.pop("parent_desc")
        self.assertIn("Key status not verified", self.address())

    def test_missing_derivation_index_is_unknown(self):
        self.info.pop("hdkeypath")
        self.assertIn("missing or unsupported", self.address())

    def test_locked_wallet_can_report_possession_without_unlock(self):
        self.status["unlocked_until"] = 0
        text = self.address()
        self.assertIn("This wallet has the key needed to spend", text)
        self.assertIn("Wallet is locked", text)
        self.assertNotIn("walletpassphrase", self.methods())

    def test_multisig_never_claims_complete_spending(self):
        self.info["parent_desc"] = "wsh(sortedmulti(2,tpubABC123/0/*,tpubOther/0/*))#sum"
        self.keys[0]["descriptors"][0]["desc"] = self.info["parent_desc"]
        text = self.address()
        self.assertIn("⚠", text)
        self.assertNotIn("✓", text)
        self.assertIn("Full spending ability not verified", text)
        self.assertIn("Multisig policy: this wallet may not hold all required signing keys", text)
        self.assertNotIn("This wallet has the key needed to spend", text)

    def test_watch_only_is_definite_and_does_not_query_keys(self):
        self.status["private_keys_enabled"] = False
        self.assertIn("Cannot spend locally: watch-only", self.address())
        self.assertIn("✗", self.address())
        self.assertNotIn("gethdkeys", self.methods())

    def test_blank_wallet_is_not_signing_confirmation(self):
        self.status["blank"] = True
        self.assertIn("wallet is marked blank", self.address())

    def test_unrelated_address(self):
        self.info = {"ismine": False}
        self.assertIn("does NOT belong", self.address())

    def test_search_includes_unloaded_and_unloads_only_what_it_opened(self):
        with contextlib.redirect_stdout(io.StringIO()):
            wallet.transfer("address-all", ADDRESS, str(self.path), [])
        report = self.path.read_text(encoding="utf-8")
        self.assertIn('Wallet: "offline"', report)
        self.assertIn('Wallet: "archived"', report)
        self.assertEqual(self.loaded, ["offline"])
        self.assertEqual(self.methods().count("loadwallet"), 1)
        self.assertEqual(self.methods().count("unloadwallet"), 1)

    def test_search_hides_watch_only_matches_and_warns_no_signer(self):
        self.status["private_keys_enabled"] = False
        with contextlib.redirect_stdout(io.StringIO()):
            wallet.transfer("address-all", ADDRESS, str(self.path), [])
        report = self.path.read_text(encoding="utf-8")
        self.assertIn("NO SIGNING WALLET FOUND", report)
        self.assertIn("Do not use this receive address yet", report)
        self.assertNotIn('Wallet: "offline"', report)
        self.assertNotIn("watch-only", report.lower())
        self.assertIn("does not prove compromise", report)

    def test_unverified_key_lookup_reports_incomplete_not_definite_no_match(self):
        self.derived = ["bcrt1different"]
        with contextlib.redirect_stdout(io.StringIO()):
            wallet.transfer("address-all", ADDRESS, str(self.path), [])
        report = self.path.read_text(encoding="utf-8")
        self.assertIn("ADDRESS CHECK INCOMPLETE", report)
        self.assertNotIn("NO SIGNING WALLET FOUND", report)

    def test_search_includes_partial_multisig_when_core_reports_a_private_key(self):
        self.info["parent_desc"] = "wsh(sortedmulti(2,tpubABC123/0/*,tpubOther/0/*))#sum"
        self.keys[0]["descriptors"][0]["desc"] = self.info["parent_desc"]
        with contextlib.redirect_stdout(io.StringIO()):
            wallet.transfer("address-all", ADDRESS, str(self.path), [])
        report = self.path.read_text(encoding="utf-8")
        self.assertIn('Wallet: "offline"', report)
        self.assertIn("Multisig policy", report)
        self.assertNotIn("✓", report)

    def test_failed_lookup_still_unloads_and_reports_incomplete(self):
        self.fail_address.add("archived")
        with contextlib.redirect_stdout(io.StringIO()):
            wallet.transfer("address-all", ADDRESS, str(self.path), [])
        self.assertIn("Incomplete check", self.path.read_text(encoding="utf-8"))
        self.assertEqual(self.loaded, ["offline"])

    def test_failed_load_is_reported(self):
        self.fail_load.add("archived")
        with contextlib.redirect_stdout(io.StringIO()):
            wallet.transfer("address-all", ADDRESS, str(self.path), [])
        self.assertIn("Could not check", self.path.read_text(encoding="utf-8"))
        self.assertEqual(self.loaded, ["offline"])

    def test_invalid_address_does_not_load_wallets(self):
        self.invalid = True
        with self.assertRaisesRegex(ValueError, "rejected this address"):
            wallet.transfer("address-all", ADDRESS, str(self.path), [])
        self.assertNotIn("loadwallet", self.methods())

    def test_compact_export_preserves_ranges_next_index_and_empty_labels(self):
        bundle = self.export()
        self.assertEqual(bundle["version"], 1)
        self.assertNotIn("wallet", bundle)
        self.assertEqual(bundle["descriptors"][0]["next_index"], 8)
        self.assertNotIn("next", bundle["descriptors"][0])
        self.assertEqual(bundle["descriptors"][0]["range"], [0, 1000])
        self.assertEqual([row["label"] for row in bundle["labels"]], ["", "Savings\nUnicode: café"])
        self.assertNotIn("exportwatchonlywallet", self.methods())

    def test_public_export_rejects_private_descriptor(self):
        self.private = True
        with self.assertRaisesRegex(ValueError, "private descriptor"):
            self.export()
        self.assertFalse(self.path.exists())

    def test_wrong_network_rejected_before_create(self):
        self.export()
        self.network = "main"
        with self.assertRaisesRegex(ValueError, "different Bitcoin network"):
            wallet.transfer("import", str(self.path), "online", [])
        self.assertNotIn("createwallet", self.methods())

    def test_compact_import_uses_private_keys_disabled_and_sets_labels(self):
        self.export()
        wallet.transfer("import", str(self.path), "online", [])
        self.assertIn("importdescriptors", self.methods())
        self.assertEqual(self.methods().count("setlabel"), 2)

    def test_old_database_import_still_rejects_signing_wallet(self):
        self.database_envelope()
        with self.assertRaisesRegex(ValueError, "not watch-only"):
            wallet.transfer("import", str(self.path), "online", [])
        self.assertNotIn("online", self.loaded)

    def test_old_database_import_checks_private_descriptors(self):
        self.database_envelope()
        self.status["private_keys_enabled"] = False
        self.private = True
        with self.assertRaisesRegex(ValueError, "contains private keys"):
            wallet.transfer("import", str(self.path), "online", [])
        self.assertNotIn("online", self.loaded)


if __name__ == "__main__":
    unittest.main()
