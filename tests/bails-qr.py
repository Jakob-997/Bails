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

    def scan(self, payload):
        with patch.object(qr, "run", return_value=payload + b"\n"), \
                patch.object(qr, "save") as save, patch.object(qr, "dialog"), \
                patch.object(qr, "rpc", return_value={}):
            qr.scan()
            return save.call_args.args

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
        with patch.object(qr, "run"), patch.object(qr, "dialog"):
            qr.show(payload, original, "wallet.dat", self.directory)
        result = zxingcpp.read_barcode(Image.open(self.directory / "qr.png"))
        self.assertIsNotNone(result)
        self.assertEqual(result.bytes, payload)
        self.assertEqual(self.scan(result.bytes), (original, "watch-only.dat"))

    def test_base64_psbt_image_roundtrip(self):
        encoded = base64.b64encode(PSBT)
        with patch.object(qr, "run"), patch.object(qr, "dialog"):
            qr.show(encoded, PSBT, "transaction.psbt", self.directory)
        result = zxingcpp.read_barcode(Image.open(self.directory / "qr.png"))
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
        with patch.object(qr, "run"), patch.object(qr, "dialog"):
            qr.show(payload, payload, "wallet.dat", self.directory)
        result = zxingcpp.read_barcode(Image.open(self.directory / "qr.png"))
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

    def test_address_check_uses_selected_wallet(self):
        address = "bcrt1qexample"
        with patch.object(qr, "run", return_value=f"bitcoin:{address}?amount=1\n".encode()), \
                patch.object(qr, "wallet_name", return_value="selected"), \
                patch.object(qr, "rpc", side_effect=[{"isvalid": True}, {"ismine": True}]) as rpc, \
                patch.object(qr, "dialog") as dialog:
            qr.scan()
            self.assertEqual(rpc.call_args.args, ("getaddressinfo", address))
            self.assertEqual(rpc.call_args.kwargs, {"wallet": "selected"})
            self.assertIn("belongs to wallet selected", dialog.call_args.args[1])

    def test_dependency_failure_and_camera_cancellation(self):
        with patch.object(qr.shutil, "which", return_value=None), self.assertRaisesRegex(ValueError, "Missing zenity"):
            qr.main()
        with patch.object(qr, "run", return_value=b""), self.assertRaises(qr.Cancelled):
            qr.scan()
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
                patch.object(qr, "dialog", side_effect=["Export watch-only wallet", qr.Cancelled]), \
                patch.object(qr, "wallet_name", return_value="signing"), \
                patch.object(qr, "rpc", side_effect=export), patch.object(qr, "show") as show:
            with self.assertRaises(qr.Cancelled):
                qr.main()
            self.assertEqual(gzip.decompress(show.call_args.args[0]), show.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
