#!/usr/bin/env python3
"""Run with qrcode, Pillow, and zxing-cpp installed; no real wallets are used."""
import base64
import gzip
import importlib.machinery
import importlib.util
import io
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
import zxingcpp

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader("qr_transfer", str(ROOT / "bails/.local/bin/bails-qr"))
spec = importlib.util.spec_from_loader(loader.name, loader)
qr = importlib.util.module_from_spec(spec)
loader.exec_module(qr)
qr.CORE_ARGS = ["-regtest"]
PSBT = b"psbt\xff" + bytes.fromhex(
    "01003d0200000001" + "11" * 32 + "0000000000ffffffff01e803000000000000015100000000000000")


class StaticQRTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def scan(self, payload, kind="Receive PSBT"):
        with patch.object(qr, "run", return_value=payload), \
                patch.object(qr, "save") as save, patch.object(qr, "dialog"), \
                patch.object(qr, "rpc", return_value={}):
            qr.scan(kind)
            return save.call_args.args

    def show(self, payload, original, name):
        def command(*args, **kwargs):
            if args[0] == "python3-qr":
                return subprocess.check_output([sys.executable, "-m", "qrcode.console_scripts", *args[1:]], **kwargs)
            return b""
        with patch.object(qr, "run", side_effect=command) as run, patch.object(qr, "dialog") as dialog:
            qr.show(payload, original, name, self.directory)
            dialog.assert_not_called()
            self.assertEqual(run.call_args.args[0], "xdg-open")
            return Path(run.call_args.args[1])

    def test_psbt_formats_and_binary_newline(self):
        for payload in (PSBT, base64.b64encode(PSBT), gzip.compress(PSBT), PSBT + b"\n"):
            expected = PSBT + b"\n" if payload == PSBT + b"\n" else PSBT
            self.assertEqual(self.scan(payload), (expected, "received.psbt"))

    def test_compressed_wallet_image_roundtrip(self):
        wallet = self.directory / "fixture.dat"
        with sqlite3.connect(wallet) as connection:
            connection.execute("CREATE TABLE wallet (label TEXT, request TEXT)")
            connection.execute("INSERT INTO wallet VALUES (?, ?)", ("savings", "request metadata"))
        connection.close()
        original = wallet.read_bytes()
        payload = gzip.compress(original, mtime=0)
        image = self.show(payload, original, "wallet.dat")
        result = zxingcpp.read_barcode(Image.open(image))
        self.assertIsNotNone(result)
        self.assertEqual(result.bytes, payload)
        self.assertEqual(self.scan(result.bytes, "Import Watch-Only Wallet"), (original, "watch-only.dat"))

    def test_base64_psbt_image_roundtrip(self):
        encoded = base64.b64encode(PSBT)
        image = self.show(encoded, PSBT, "transaction.psbt")
        result = zxingcpp.read_barcode(Image.open(image))
        self.assertEqual(result.bytes, encoded)
        self.assertEqual(self.scan(result.bytes), (PSBT, "received.psbt"))

    def test_size_limits_and_file_fallback(self):
        with patch.object(qr, "save") as save, patch.object(qr, "dialog"), patch.object(qr, "run") as run:
            qr.show(b"x" * 2954, PSBT, "transaction.psbt", self.directory)
            save.assert_called_once_with(PSBT, "transaction.psbt")
            run.assert_not_called()
        with self.assertRaises(ValueError):
            self.scan(gzip.compress(b"x" * (qr.MAX_FILE + 1)))
        with self.assertRaises(ValueError):
            self.scan(b"x" * 2954)
        for payload in (b"", b"x" * (qr.MAX_FILE + 1)):
            source = self.directory / "oversized.psbt"
            source.write_bytes(payload)
            with self.assertRaises(ValueError):
                qr.read_file(source)

    def test_largest_binary_static_qr(self):
        payload = bytes((i * 73 + 19) % 256 for i in range(2953))
        image = self.show(payload, payload, "wallet.dat")
        result = zxingcpp.read_barcode(Image.open(image))
        self.assertIsNotNone(result)
        self.assertEqual(result.bytes, payload)

    def test_gzip_integrity(self):
        data = gzip.compress(PSBT)
        for invalid in (data[:-1], data[:-8] + b"\xff" * 8):
            with self.assertRaises((OSError, EOFError)):
                self.scan(invalid)

    def test_core_validates_psbt_and_receives_options(self):
        with patch.object(qr, "run", return_value=b"{}") as run:
            self.assertEqual(qr.psbt_bytes(PSBT), PSBT)
            self.assertEqual(run.call_args.args, ("bitcoin-cli", "-regtest", "-stdin", "decodepsbt"))
            self.assertEqual(run.call_args.kwargs["input"], base64.b64encode(PSBT) + b"\n")
        error = subprocess.CalledProcessError(1, "bitcoin-cli", stderr=b"invalid PSBT")
        with patch.object(qr, "rpc", side_effect=error), self.assertRaises(subprocess.CalledProcessError):
            qr.psbt_bytes(PSBT)

    def test_existing_file_is_preserved_and_save_can_cancel(self):
        target = self.directory / "existing.dat"
        target.write_bytes(b"keep")
        with patch.object(qr, "dialog", return_value=str(target)), self.assertRaises(FileExistsError):
            qr.save(b"replace", "wallet.dat")
        self.assertEqual(target.read_bytes(), b"keep")
        with patch.object(qr, "dialog", side_effect=qr.Cancelled), self.assertRaises(qr.Cancelled):
            qr.save(b"new", "wallet.dat")

    def test_wallet_names_are_not_split(self):
        name = 'wallet with spaces and "quotes"\nnext line'
        with patch.object(qr, "rpc", return_value=["", name]), patch.object(qr, "dialog", return_value="1"):
            self.assertEqual(qr.wallet_name(), name)

    def test_address_checks_loaded_wallets_without_selection(self):
        address = "bcrt1qexample"
        with patch.object(qr, "run", return_value=f"bitcoin:{address.upper()}?amount=1".encode()), \
                patch.object(qr, "wallet_name") as choose, \
                patch.object(qr, "rpc", side_effect=[{"isvalid": True}, ["other", "signing"],
                                                    {"ismine": False}, {"ismine": True}]) as rpc, \
                patch.object(qr, "dialog") as dialog:
            qr.scan("Verify Receiving Address")
            self.assertEqual(rpc.call_args.args, ("getaddressinfo", address))
            self.assertEqual(rpc.call_args.kwargs, {"wallet": "signing"})
            choose.assert_not_called()
            dialog.assert_called_once_with("--info", "--title=Address confirmed",
                                           f"--text=You own this address.\n\n{address}")

    def test_plain_address_without_scanner_newline(self):
        with patch.object(qr, "run", return_value=b"bcrt1qexample"), \
                patch.object(qr, "rpc", side_effect=[{"isvalid": True}, ["signing"], {"ismine": True}]) as rpc, \
                patch.object(qr, "dialog"):
            qr.scan("Verify Receiving Address")
            self.assertEqual(rpc.call_args.args, ("getaddressinfo", "bcrt1qexample"))

    def test_unowned_address_has_prominent_warning(self):
        with patch.object(qr, "run", return_value=b"BCRT1QEXAMPLE"), \
                patch.object(qr, "rpc", side_effect=[{"isvalid": True}, ["signing"], {"ismine": False}]), \
                patch.object(qr, "dialog") as dialog:
            qr.scan("Verify Receiving Address")
            self.assertEqual(dialog.call_args.args[0], "--warning")
            message = dialog.call_args.args[2]
            for text in ("WARNING", "You do not own this address", "bcrt1qexample", "may be compromised"):
                self.assertIn(text, message)

    def test_address_check_requires_an_open_wallet(self):
        with patch.object(qr, "run", return_value=b"bcrt1qexample"), \
                patch.object(qr, "rpc", side_effect=[{"isvalid": True}, []]), \
                patch.object(qr, "dialog") as dialog, self.assertRaisesRegex(ValueError, "Open your wallet"):
            qr.scan("Verify Receiving Address")
        dialog.assert_not_called()

    def test_base58_address_keeps_its_case(self):
        address = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
        with patch.object(qr, "run", return_value=address.encode()), \
                patch.object(qr, "rpc", side_effect=[{"isvalid": True}, ["signing"], {"ismine": True}]) as rpc, \
                patch.object(qr, "dialog") as dialog:
            qr.scan("Verify Receiving Address")
            self.assertEqual(rpc.call_args.args, ("getaddressinfo", address))
            self.assertIn(address, dialog.call_args.args[2])

    def test_invalid_address_is_not_normalized_into_validity(self):
        with patch.object(qr, "run", return_value=b"bCrT1qExAmPlE"), \
                patch.object(qr, "rpc", return_value={"isvalid": False}) as rpc, \
                patch.object(qr, "dialog") as dialog, self.assertRaises(ValueError):
            qr.scan("Verify Receiving Address")
        rpc.assert_called_once_with("validateaddress", "bCrT1qExAmPlE")
        dialog.assert_not_called()

    def test_wallet_rpc_failure_does_not_report_unowned(self):
        error = subprocess.CalledProcessError(1, "bitcoin-cli", stderr=b"wallet unavailable")
        with patch.object(qr, "run", return_value=b"bcrt1qexample"), \
                patch.object(qr, "rpc", side_effect=[{"isvalid": True}, ["signing"], error]), \
                patch.object(qr, "dialog") as dialog, self.assertRaises(subprocess.CalledProcessError):
            qr.scan("Verify Receiving Address")
        dialog.assert_not_called()

    def test_import_wallet_rejects_other_qr_types(self):
        with patch.object(qr, "run", return_value=base64.b64encode(PSBT)), \
                patch.object(qr, "save") as save, self.assertRaisesRegex(ValueError, "wallet.dat"):
            qr.scan("Import Watch-Only Wallet")
        save.assert_not_called()

    def test_import_wallet_menu_routes_to_scan(self):
        with patch.object(qr.shutil, "which", return_value="available"), \
                patch.object(qr.tempfile, "TemporaryDirectory", return_value=self.temporary), \
                patch.object(qr, "dialog", side_effect=["Wallet Tools", "Import Watch-Only Wallet", qr.Cancelled]) as dialog, \
                patch.object(qr, "scan") as scan, self.assertRaises(qr.Cancelled):
            qr.main()
        self.assertNotIn("Import Watch-Only Wallet", dialog.call_args_list[0].args)
        self.assertIn("Import Watch-Only Wallet", dialog.call_args_list[1].args)
        scan.assert_called_once_with("Import Watch-Only Wallet")

    def test_address_and_psbt_have_separate_menu_actions(self):
        for action in ("Verify Receiving Address", "Receive PSBT"):
            temporary = tempfile.TemporaryDirectory
            with patch.object(qr.shutil, "which", return_value="available"), \
                    patch.object(qr.tempfile, "TemporaryDirectory", side_effect=lambda **kw: temporary()), \
                    patch.object(qr, "dialog", side_effect=[action, qr.Cancelled]) as dialog, \
                    patch.object(qr, "scan") as scan, self.assertRaises(qr.Cancelled):
                qr.main()
            self.assertEqual(dialog.call_args_list[0].args,
                             ("--list", "--column=Action", "Verify Receiving Address", "Receive PSBT", "Send PSBT", "Wallet Tools"))
            scan.assert_called_once_with(action)

    def test_receive_psbt_does_not_verify_an_address(self):
        with patch.object(qr, "run", return_value=b"bcrt1qexample"), \
                patch.object(qr, "rpc") as rpc, patch.object(qr, "save") as save, \
                self.assertRaisesRegex(ValueError, "Expected a PSBT QR"):
            qr.scan("Receive PSBT")
        rpc.assert_not_called()
        save.assert_not_called()

    def test_verify_address_does_not_save_a_psbt(self):
        with patch.object(qr, "run", return_value=base64.b64encode(PSBT)), \
                patch.object(qr, "rpc", return_value={"isvalid": False}), \
                patch.object(qr, "save") as save, self.assertRaisesRegex(ValueError, "Expected a Bitcoin address"):
            qr.scan("Verify Receiving Address")
        save.assert_not_called()

    def test_wallet_tools_cancellation_returns_to_main_menu(self):
        temporary = tempfile.TemporaryDirectory
        with patch.object(qr.shutil, "which", return_value="available"), \
                patch.object(qr.tempfile, "TemporaryDirectory", side_effect=lambda **kw: temporary()), \
                patch.object(qr, "dialog", side_effect=["Wallet Tools", qr.Cancelled, qr.Cancelled]) as dialog, \
                self.assertRaises(qr.Cancelled):
            qr.main()
        self.assertEqual(dialog.call_args_list[0].args, dialog.call_args_list[2].args)

    def test_dependency_failure_and_camera_cancellation(self):
        with patch.object(qr.shutil, "which", return_value=None), self.assertRaisesRegex(ValueError, "Missing zenity"):
            qr.main()
        with patch.object(qr, "run", return_value=b""), self.assertRaises(qr.Cancelled):
            qr.scan("Verify Receiving Address")
        error = subprocess.CalledProcessError(1, "zenity")
        with patch.object(qr, "run", side_effect=error), self.assertRaises(qr.Cancelled):
            qr.dialog("--list")

    def test_export_uses_core_watchonly_rpc_and_main_can_exit(self):
        def export(method, path, wallet):
            self.assertEqual((method, wallet), ("exportwatchonlywallet", "signing"))
            Path(path).write_bytes(b"SQLite format 3\x00" + b"public wallet data")
            return {}
        temporary = tempfile.TemporaryDirectory
        with patch.object(qr.shutil, "which", return_value="available"), \
                patch.object(qr.tempfile, "TemporaryDirectory", side_effect=lambda **kw: temporary()), \
                patch.object(qr, "dialog", side_effect=["Wallet Tools", "Export Watch-Only Wallet", qr.Cancelled]), \
                patch.object(qr, "wallet_name", return_value="signing"), \
                patch.object(qr, "rpc", side_effect=export), patch.object(qr, "show") as show:
            with self.assertRaises(qr.Cancelled):
                qr.main()
            self.assertEqual(gzip.decompress(show.call_args.args[0]), show.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
