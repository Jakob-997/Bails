#!/usr/bin/env python3
"""Run with qrcode, Pillow, and zxing-cpp installed; no real wallets are used."""
import base64
import gzip
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile
from threading import Event
import unittest
from unittest.mock import MagicMock, patch

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
DESCRIPTORS = [{"desc": "wpkh(public-key)#checksum", "timestamp": 123, "active": True,
                "internal": False, "range": [0, 999], "next_index": 7}]
EXPORT = {"wallet_name": "signing", "descriptors": DESCRIPTORS}
SINGLE = {"ismine": True, "parent_desc": "wpkh(public-key)#12345678"}
SIGNING = {"descriptors": True, "private_keys_enabled": True}


class StaticQRTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def scan(self, payload, kind="Receive PSBT", copy=True):
        gtk = MagicMock()
        gdk = MagicMock()
        gtk.MessageDialog.return_value.run.side_effect = lambda: gtk.Button.return_value.connect.call_args.args[1](None) if copy else None
        buffer = gtk.TextView.return_value.get_buffer.return_value
        buffer.get_bounds.return_value = ("start", "end")
        with patch.dict(sys.modules, {"gi": MagicMock(), "gi.repository": MagicMock(Gtk=gtk, Gdk=gdk)}), \
                patch.object(qr, "run", return_value=payload), \
                patch.object(qr, "save") as save, patch.object(qr, "dialog"), \
                patch.object(qr, "rpc", return_value={}):
            qr.scan(kind)
            if kind == "Receive PSBT":
                save.assert_not_called()
                gtk.MessageDialog.return_value.run.assert_called_once()
                gtk.MessageDialog.return_value.destroy.assert_called_once()
                gdk.Display.get_default.return_value.flush.assert_called_once()
                packed = gtk.MessageDialog.return_value.get_content_area.return_value.pack_start.call_args_list
                self.assertIs(packed[0].args[0], gtk.Button.return_value)
                self.assertIs(packed[1].args[0], gtk.ScrolledWindow.return_value)
                sys.modules["gi"].require_versions.assert_called_once_with({"Gtk": "3.0", "Gdk": "3.0"})
                if copy:
                    buffer.select_range.assert_called_once_with("start", "end")
                    buffer.copy_clipboard.assert_called_once_with(gtk.Clipboard.get.return_value)
                else:
                    buffer.copy_clipboard.assert_not_called()
                return base64.b64decode(buffer.set_text.call_args.args[0])
            return save.call_args.args

    def show(self, data, name):
        def command(*args, **kwargs):
            if args[0] == "python3-qr":
                return subprocess.check_output([sys.executable, "-m", "qrcode.console_scripts", *args[1:]], **kwargs)
            return b""
        with patch.object(qr, "run", side_effect=command) as run, patch.object(qr, "dialog") as dialog, patch.object(qr, "Timer") as timer:
            qr.show(data, name, self.directory)
            dialog.assert_not_called()
            self.assertEqual(run.call_args.args[0], "python3-qr")
            self.assertEqual(timer.call_args.args[0], 0.5)
            timer.return_value.start.assert_called_once()
            timer.call_args.args[1](*timer.call_args.kwargs["args"])
            self.assertEqual(run.call_args.args[0], "xdg-open")
            return Path(run.call_args.args[1])

    def test_viewer_launch_is_delayed_without_blocking_menu(self):
        opened = Event()
        def command(*args, **kwargs):
            if args[0] == "xdg-open":
                self.assertTrue(Path(args[1]).is_file())
                opened.set()
            return b"png"
        with patch.object(qr, "run", side_effect=command):
            qr.show(b"psbt\xff", "transaction.psbt", self.directory)
            self.assertFalse(opened.wait(0.1))
            self.assertTrue(opened.wait(3))

    def test_psbt_formats_and_binary_newline(self):
        for payload in (PSBT, base64.b64encode(PSBT), gzip.compress(PSBT), PSBT + b"\n"):
            expected = PSBT + b"\n" if payload == PSBT + b"\n" else PSBT
            self.assertEqual(self.scan(payload), expected)

    def test_psbt_is_not_copied_without_clicking_copy(self):
        self.assertEqual(self.scan(PSBT, copy=False), PSBT)

    def test_send_psbt_accepts_pasted_text_and_validates_before_display(self):
        encoded = base64.b64encode(PSBT)
        with patch.object(qr.shutil, "which", return_value="available"), \
                patch.object(qr.tempfile, "TemporaryDirectory", return_value=self.temporary), \
                patch.object(qr, "dialog", side_effect=["↑  Send PSBT", encoded.decode(), qr.Cancelled]) as dialog, \
                patch.object(qr, "rpc", return_value={}) as rpc, \
                patch.object(qr, "show") as show, self.assertRaises(qr.Cancelled):
            qr.main()
        self.assertIn("--text-info", dialog.call_args_list[1].args)
        self.assertIn("--editable", dialog.call_args_list[1].args)
        self.assertIn("--width=800", dialog.call_args_list[1].args)
        self.assertIn("--height=400", dialog.call_args_list[1].args)
        self.assertTrue(any("Create Unsigned" in arg and "Copy to Clipboard" in arg for arg in dialog.call_args_list[1].args))
        rpc.assert_called_once_with("decodepsbt", data=encoded + b"\n")
        self.assertEqual(show.call_args.args[:2], (PSBT, "transaction.psbt"))

    def test_oversized_pasted_psbt_does_not_reach_core(self):
        with patch.object(qr, "rpc") as rpc, self.assertRaisesRegex(ValueError, "larger than 1 MiB"):
            qr.psbt_bytes(base64.b64encode(PSBT + b"x" * qr.MAX_FILE))
        rpc.assert_not_called()

    def test_multiline_psbt_paste(self):
        encoded = base64.b64encode(PSBT)
        with patch.object(qr, "rpc"):
            self.assertEqual(qr.psbt_bytes(encoded[:32] + b"\n" + encoded[32:] + b"\n"), PSBT)

    def test_compressed_wallet_image_roundtrip(self):
        original = json.dumps(EXPORT).encode()
        payload = gzip.compress(original, mtime=0)
        image = self.show(original, "descriptors.json")
        result = zxingcpp.read_barcode(Image.open(image))
        self.assertIsNotNone(result)
        self.assertEqual(result.bytes, payload)
        with patch.object(qr, "run", return_value=result.bytes), \
                patch.object(qr, "dialog") as dialog, \
                patch.object(qr, "rpc", side_effect=[{}, [{"success": True}]]) as rpc:
            qr.scan("Import Watch-Only Wallet")
        self.assertEqual(rpc.call_args_list[0].args, ("createwallet", "[Watch-only] signing", "true", "true"))
        self.assertEqual(json.loads(rpc.call_args.kwargs["data"]), DESCRIPTORS)
        self.assertEqual(rpc.call_args.kwargs["wallet"], "[Watch-only] signing")
        dialog.assert_called_once()
        self.assertIn("Window > Receiving addresses", dialog.call_args.args[1])

    def test_compressed_psbt_image_roundtrip(self):
        image = self.show(PSBT, "transaction.psbt")
        result = zxingcpp.read_barcode(Image.open(image))
        self.assertEqual(result.bytes, gzip.compress(PSBT, compresslevel=9, mtime=0))
        self.assertEqual(self.scan(result.bytes), PSBT)

    def test_small_payload_stays_raw_when_gzip_is_larger(self):
        payload = b"psbt\xffx"
        result = zxingcpp.read_barcode(Image.open(self.show(payload, "transaction.psbt")))
        self.assertEqual(result.bytes, payload)

    def test_large_compressible_payload_fits_without_file_fallback(self):
        payload = b"psbt\xff" + b"repeated metadata" * 1000
        result = zxingcpp.read_barcode(Image.open(self.show(payload, "transaction.psbt")))
        self.assertLess(len(result.bytes), 2953)
        self.assertEqual(gzip.decompress(result.bytes), payload)

    def test_size_limits_and_file_fallback(self):
        with patch.object(qr, "save") as save, patch.object(qr, "dialog"), patch.object(qr, "run") as run:
            payload = random.Random(0).randbytes(2954)
            qr.show(payload, "transaction.psbt", self.directory)
            save.assert_called_once_with(payload, "transaction.psbt")
            run.assert_not_called()
        with self.assertRaises(ValueError):
            self.scan(gzip.compress(b"x" * (qr.MAX_FILE + 1)))
        with self.assertRaises(ValueError):
            self.scan(b"x" * 2954)

    def test_largest_binary_static_qr(self):
        payload = random.Random(0).randbytes(2953)
        image = self.show(payload, "wallet.dat")
        result = zxingcpp.read_barcode(Image.open(image))
        self.assertIsNotNone(result)
        self.assertEqual(result.bytes, payload)

    def test_gzip_integrity(self):
        data = gzip.compress(PSBT)
        for invalid in (data[:-1], data[:-8] + b"\xff" * 8):
            with self.assertRaises((OSError, EOFError)):
                self.scan(invalid)

    def test_generated_images_decode_at_various_payload_sizes(self):
        for size in (100, 700, 1500, 2953):
            payload = bytes((i * 73 + 19) % 256 for i in range(size))
            image = Image.open(self.show(payload, "wallet.dat"))
            self.assertEqual(image.width, image.height)
            self.assertEqual(set(image.convert("L").tobytes()), {0, 255})
            result = zxingcpp.read_barcode(image)
            self.assertIsNotNone(result)
            self.assertEqual(gzip.decompress(result.bytes) if result.bytes.startswith(b"\x1f\x8b") else result.bytes, payload)

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
                                                    {"ismine": False}, SINGLE, SIGNING]) as rpc, \
                patch.object(qr, "dialog") as dialog:
            qr.scan("Verify Receiving Address")
            self.assertEqual(rpc.call_args_list[-2].args, ("getaddressinfo", address))
            self.assertEqual(rpc.call_args.kwargs, {"wallet": "signing"})
            choose.assert_not_called()
            dialog.assert_called_once_with("--info", "--title=Address confirmed",
                                           f"--text=This wallet holds the key needed to sign for this address.\n\n✓ Address matches wallet:\nsigning\n\n{address}")

    def test_plain_address_without_scanner_newline(self):
        with patch.object(qr, "run", return_value=b"bcrt1qexample"), \
                patch.object(qr, "rpc", side_effect=[{"isvalid": True}, ["signing"], SINGLE, SIGNING]) as rpc, \
                patch.object(qr, "dialog"):
            qr.scan("Verify Receiving Address")
            self.assertEqual(rpc.call_args_list[-2].args, ("getaddressinfo", "bcrt1qexample"))

    def test_address_signing_classification_and_encryption(self):
        cases = [
            ("pkh(KEY)", SIGNING, True),
            ("wpkh(KEY)", SIGNING, True),
            ("sh(wpkh(KEY))", SIGNING, True),
            ("tr(KEY)", SIGNING, True),
            ("wsh(sortedmulti(2,KEY1,KEY2,KEY3))", SIGNING, False),
            ("tr(KEY,pk(OTHER))", SIGNING, False),
            ("tr(KEY,{pk(OTHER),pk(THIRD)})", SIGNING, False),
            ("rawtr(KEY)", SIGNING, False),
            ("wpkh(KEY)", dict(SIGNING, private_keys_enabled=False), False),
            ("wsh(sortedmulti(2,KEY1,KEY2,KEY3))", dict(SIGNING, private_keys_enabled=False), False),
            ("wpkh(KEY)", dict(SIGNING, descriptors=False), False),
            ("", SIGNING, False),
        ]
        for desc, wallet, confirmed in cases:
            for encrypted in (False, True):
                with self.subTest(desc=desc, wallet=wallet, encrypted=encrypted):
                    info = dict(SINGLE, parent_desc=desc + "#12345678" if desc else "")
                    state = dict(wallet, unlocked_until=0) if encrypted else wallet
                    with patch.object(qr, "run", return_value=b"bcrt1qexample"), \
                            patch.object(qr, "rpc", side_effect=[{"isvalid": True}, ["signing"], info, state]), \
                            patch.object(qr, "dialog") as dialog:
                        qr.scan("Verify Receiving Address")
                    self.assertEqual(dialog.call_args.args[0], "--info" if confirmed and not encrypted else "--warning")
                    message = dialog.call_args.args[2]
                    self.assertEqual("holds the key needed to sign" in message, confirmed)
                    self.assertEqual("encryption passphrase" in message, encrypted)
                    self.assertEqual("✓ Address matches wallet" in message, confirmed)
                    if encrypted:
                        self.assertTrue(message.startswith("--text=⚠ ENCRYPTED WALLET"))
                        self.assertEqual(dialog.call_args.args[1], "--title=WARNING: Encrypted wallet")
                    if not wallet.get("private_keys_enabled"):
                        self.assertIn("WARNING: You do not own the signing key", message)
                        self.assertIn("found in a watch-only wallet", message)
                        self.assertIn("If you expected this to be your signing wallet and this is not a mistake", message)
                        self.assertIn("this computer may be compromised", message)
                        self.assertIn("YOU WILL NOT BE ABLE TO SPEND WITH THIS WALLET ALONE", message)
                        self.assertIn("DO NOT SEND FUNDS TO THIS ADDRESS", message)
                        self.assertIn("VERIFY IT IN YOUR OFFLINE SIGNING WALLET", message)
                        self.assertNotIn("Signing is not confirmed", message)
                        if not encrypted:
                            self.assertEqual(dialog.call_args.args[1], "--title=WARNING: Signing key not owned")
                    elif not confirmed:
                        self.assertIn("Signing is not confirmed", message)

    def test_unowned_address_has_prominent_warning(self):
        with patch.object(qr, "run", return_value=b"BCRT1QEXAMPLE"), \
                patch.object(qr, "rpc", side_effect=[{"isvalid": True}, ["signing"], {"ismine": False}]), \
                patch.object(qr, "dialog") as dialog:
            qr.scan("Verify Receiving Address")
            self.assertEqual(dialog.call_args.args[0], "--warning")
            message = dialog.call_args.args[2]
            for text in ("WARNING", "You do not own this address", "bcrt1qexample", "YOUR WALLET", "your computer and all software running on it, including Bitcoin Core, may be compromised", "Do not send funds to this address"):
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
                patch.object(qr, "rpc", side_effect=[{"isvalid": True}, ["signing"], SINGLE, SIGNING]) as rpc, \
                patch.object(qr, "dialog") as dialog:
            qr.scan("Verify Receiving Address")
            self.assertEqual(rpc.call_args_list[-2].args, ("getaddressinfo", address))
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
                patch.object(qr, "save") as save, self.assertRaises(ValueError):
            qr.scan("Import Watch-Only Wallet")
        save.assert_not_called()

    def test_import_wallet_menu_routes_to_scan(self):
        with patch.object(qr.shutil, "which", return_value="available"), \
                patch.object(qr.tempfile, "TemporaryDirectory", return_value=self.temporary), \
                patch.object(qr, "dialog", side_effect=["⚙  Wallet Tools", "↓  Import Watch-Only Wallet", qr.Cancelled]) as dialog, \
                patch.object(qr, "scan") as scan, self.assertRaises(qr.Cancelled):
            qr.main()
        self.assertNotIn("Import Watch-Only Wallet", dialog.call_args_list[0].args)
        self.assertIn("↓  Import Watch-Only Wallet", dialog.call_args_list[1].args)
        scan.assert_called_once_with("Import Watch-Only Wallet")

    def test_address_and_psbt_have_separate_menu_actions(self):
        for action in ("Verify Receiving Address", "Receive PSBT"):
            temporary = tempfile.TemporaryDirectory
            with patch.object(qr.shutil, "which", return_value="available"), \
                    patch.object(qr.tempfile, "TemporaryDirectory", side_effect=lambda **kw: temporary()), \
                    patch.object(qr, "dialog", side_effect=[("✓  " if action == "Verify Receiving Address" else "↓  ") + action, qr.Cancelled]) as dialog, \
                    patch.object(qr, "scan") as scan, self.assertRaises(qr.Cancelled):
                qr.main()
            self.assertEqual(dialog.call_args_list[0].args,
                             ("--list", "--width=640", "--height=520", "--text=Choose an action.\n\nScanning tips: try maximizing the window showing the QR code.\nQR codes can be scanned sideways or upside down.", "--column=Action", "✓  Verify Receiving Address", "↓  Receive PSBT", "↑  Send PSBT", "⚙  Wallet Tools"))
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

    def test_export_uses_only_public_descriptors_and_main_can_exit(self):
        temporary = tempfile.TemporaryDirectory
        with patch.object(qr.shutil, "which", return_value="available"), \
                patch.object(qr.tempfile, "TemporaryDirectory", side_effect=lambda **kw: temporary()), \
                patch.object(qr, "dialog", side_effect=["⚙  Wallet Tools", "↑  Export Watch-Only Wallet", qr.Cancelled]), \
                patch.object(qr, "wallet_name", return_value="signing"), \
                patch.object(qr, "rpc", side_effect=[dict(EXPORT), ["", "Savings"], {"test-address": {"purpose": "receive"}}]) as rpc, patch.object(qr, "show") as show:
            with self.assertRaises(qr.Cancelled):
                qr.main()
            self.assertEqual(json.loads(show.call_args.args[0]), dict(EXPORT, labels={"test-address": "Savings"}))
            self.assertEqual(rpc.call_args_list[0].args, ("listdescriptors", "false"))
            self.assertEqual(rpc.call_args_list[2].args, ("getaddressesbylabel", "Savings"))
            self.assertEqual(rpc.call_count, 3)

    def test_labels_are_imported_only_after_descriptors_succeed(self):
        labels = {"test-address": 'Savings "quotes" and café'}
        exported = dict(EXPORT, labels=labels)
        with patch.object(qr, "run", return_value=gzip.compress(json.dumps(exported).encode())), \
                patch.object(qr, "dialog"), patch.object(qr, "rpc", side_effect=[{}, [{"success": True}], None]) as rpc:
            qr.scan("Import Watch-Only Wallet")
        self.assertEqual(rpc.call_args.args, ("setlabel", "test-address", labels["test-address"]))
        self.assertEqual(rpc.call_args.kwargs, {"wallet": "[Watch-only] signing"})

    def test_core_void_result_is_accepted(self):
        with patch.object(qr, "run", return_value=b""):
            self.assertIsNone(qr.rpc("setlabel", "address", "Savings", wallet="online"))

    def test_invalid_label_payload_does_not_create_wallet(self):
        for labels in ([], {"address": 3}):
            with patch.object(qr, "run", return_value=json.dumps(dict(EXPORT, labels=labels)).encode()), \
                    patch.object(qr, "rpc") as rpc, self.assertRaisesRegex(ValueError, "labels"):
                qr.scan("Import Watch-Only Wallet")
            rpc.assert_not_called()

    def test_default_wallet_address_confirmation_shows_name(self):
        with patch.object(qr, "run", return_value=b"bcrt1qexample"), \
                patch.object(qr, "rpc", side_effect=[{"isvalid": True}, [""], SINGLE, SIGNING]), \
                patch.object(qr, "dialog") as dialog:
            qr.scan("Verify Receiving Address")
        self.assertIn("(default)", dialog.call_args.args[2])

    def test_descriptor_import_failure_is_not_reported_as_success(self):
        with patch.object(qr, "run", return_value=json.dumps(EXPORT).encode()), \
                patch.object(qr, "dialog", return_value="online") as dialog, \
                patch.object(qr, "rpc", side_effect=[{}, [{"success": False, "error": {"message": "invalid descriptor"}}]]), \
                self.assertRaisesRegex(ValueError, "incomplete"):
            qr.scan("Import Watch-Only Wallet")
        dialog.assert_not_called()

    def test_range_conflict_retries_with_current_range_and_index(self):
        failure = {"success": False, "error": {"message": "new range must include current range"}}
        current = dict(DESCRIPTORS[0], range=[0, 1004], next_index=12)
        with patch.object(qr, "run", return_value=json.dumps(EXPORT).encode()), \
                patch.object(qr, "dialog"), \
                patch.object(qr, "rpc", side_effect=[{}, [failure], {"descriptors": [current]}, [{"success": True}]]) as rpc:
            qr.scan("Import Watch-Only Wallet")
        retried = json.loads(rpc.call_args.kwargs["data"])
        self.assertEqual(retried[0]["range"], [0, 1004])
        self.assertEqual(retried[0]["next_index"], 12)
        self.assertEqual(rpc.call_count, 4)

    def test_range_retry_only_retries_failed_descriptor_without_rewinding(self):
        first = dict(DESCRIPTORS[0], desc="other-public-descriptor")
        failed = dict(DESCRIPTORS[0], range=[2, 1100], next_index=20)
        current = dict(failed, range=[0, 1004], next_index=12)
        export = dict(EXPORT, descriptors=[first, failed], labels={"address": "Savings"})
        failure = {"success": False, "error": {"message": "new range must include current range"}}
        with patch.object(qr, "run", return_value=json.dumps(export).encode()), \
                patch.object(qr, "dialog"), \
                patch.object(qr, "rpc", side_effect=[{}, [{"success": True}, failure], {"descriptors": [current]}, [{"success": True}], None]) as rpc:
            qr.scan("Import Watch-Only Wallet")
        self.assertEqual(json.loads(rpc.call_args_list[3].kwargs["data"]),
                         [dict(failed, range=[0, 1100], next_index=20)])
        self.assertEqual(rpc.call_args.args, ("setlabel", "address", "Savings"))

    def test_scan_failure_returns_to_menu_with_visible_error(self):
        for error in (ValueError("Invalid QR payload"), subprocess.TimeoutExpired("zbarcam", 180)):
            temporary = tempfile.TemporaryDirectory
            with patch.object(qr.shutil, "which", return_value="available"), \
                    patch.object(qr.tempfile, "TemporaryDirectory", side_effect=lambda **kw: temporary()), \
                    patch.object(qr, "dialog", side_effect=["Receive PSBT", "", qr.Cancelled]) as dialog, \
                    patch.object(qr, "scan", side_effect=error), self.assertRaises(qr.Cancelled):
                qr.main()
            self.assertEqual(dialog.call_args_list[1].args, ("--error", f"--text={error}"))
            self.assertEqual(dialog.call_args_list[0].args, dialog.call_args_list[2].args)

    def test_range_conflict_retry_failure_is_reported(self):
        export = dict(EXPORT, labels={"address": "Savings"})
        failure = {"success": False, "error": {"message": "new range must include current range"}}
        with patch.object(qr, "run", return_value=json.dumps(export).encode()), \
                patch.object(qr, "dialog") as dialog, \
                patch.object(qr, "rpc", side_effect=[{}, [failure], {"descriptors": DESCRIPTORS}, [failure]]) as rpc, \
                self.assertRaisesRegex(ValueError, "incomplete"):
            qr.scan("Import Watch-Only Wallet")
        self.assertEqual(rpc.call_count, 4)
        dialog.assert_not_called()

    def test_invalid_descriptor_payload_does_not_create_wallet(self):
        for data in ({}, [], ["not a descriptor object"], {"wallet_name": 4, "descriptors": DESCRIPTORS}):
            with patch.object(qr, "run", return_value=json.dumps(data).encode()), \
                    patch.object(qr, "rpc") as rpc, self.assertRaises(ValueError):
                qr.scan("Import Watch-Only Wallet")
            rpc.assert_not_called()

    def test_imported_wallet_name_is_not_a_path(self):
        exported = dict(EXPORT, wallet_name="../folder/wallet\\name")
        with patch.object(qr, "run", return_value=json.dumps(exported).encode()), \
                patch.object(qr, "dialog"), patch.object(qr, "rpc", side_effect=[{}, [{"success": True}]]) as rpc:
            qr.scan("Import Watch-Only Wallet")
        self.assertEqual(rpc.call_args_list[0].args, ("createwallet", "[Watch-only] .._folder_wallet_name", "true", "true"))


if __name__ == "__main__":
    unittest.main()
