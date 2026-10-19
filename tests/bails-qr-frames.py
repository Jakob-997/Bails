#!/usr/bin/python3
"""Real QR images, bounded reassembly, and streaming camera lifecycle tests."""
import json
import base64
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import types
import zlib

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "bails/.local/bin/bails-qr-frames"
loader = importlib.machinery.SourceFileLoader("wallet_frames", str(HELPER))
spec = importlib.util.spec_from_loader(loader.name, loader)
transport = importlib.util.module_from_spec(spec)
loader.exec_module(transport)


def fixture(size):
    return json.dumps({"format":"bails-watch-only", "padding":os.urandom(size).hex()}).encode()


def rendered_frames(data, file_type="J"):
    result = []
    with tempfile.TemporaryDirectory() as directory:
        image = Path(directory) / "frame.png"
        for frame in transport.encode(data, file_type):
            image.write_bytes(transport.make_png(frame))
            decoded = subprocess.check_output(["zbarimg", "--nodbus", "--quiet", "--raw", "-Sbinary", str(image)])
            result.append(decoded.decode("ascii").rstrip("\n"))
        if file_type == "P":
            Path(os.environ["TEST_QR"]).write_bytes(transport.make_png(result[0]))
    return result


def decode(frames):
    receiver = transport.Receiver()
    data = None
    for frame in frames:
        data = receiver.add(frame)
    return data


class WalletFramesTests(unittest.TestCase):
    def test_reference_psbt_vectors_and_compression_limits(self):
        bundle = json.loads((ROOT / "tests/fixtures/bbqr-psbt.json").read_text())
        for frames in bundle["vectors"]:
            receiver = transport.Receiver("P")
            for frame in reversed(frames):
                result = receiver.add(frame)
            self.assertEqual(result, base64.b64decode(bundle["psbt"]))
        for data in (b"psbt\xff" + b"x" * transport.MAX_FILE,):
            compressor = zlib.compressobj(9, zlib.DEFLATED, -10)
            compressed = compressor.compress(data) + compressor.flush()
            text = base64.b32encode(compressed).decode().rstrip("=")
            pieces = [text[i:i+480] for i in range(0, len(text), 480)]
            receiver = transport.Receiver("P")
            with self.assertRaises(ValueError):
                for i, part in enumerate(pieces):
                    receiver.add(f"B$ZP{transport.base36(len(pieces))}{transport.base36(i)}{part}")

    def test_psbt_encodings_and_independent_reassembly(self):
        # Independently construct the wire format used by Sparrow: chunks align
        # to complete base32 groups; Z is raw DEFLATE, not a zlib/gzip wrapper.
        data = b"psbt\xff" + bytes(range(256)) * 12
        compressor = zlib.compressobj(9, zlib.DEFLATED, -10)
        compressed = compressor.compress(data) + compressor.flush()
        for encoding, payload in (("H", data), ("2", data), ("Z", compressed)):
            text = payload.hex().upper() if encoding == "H" else base64.b32encode(payload).decode().rstrip("=")
            pieces = [text[i:i+200] for i in range(0, len(text), 200)]
            frames = [f"B${encoding}P{transport.base36(len(pieces))}{transport.base36(i)}{part}"
                      for i, part in enumerate(pieces)]
            receiver = transport.Receiver("P")
            self.assertIsNone(receiver.add(frames[-1]))
            self.assertIsNone(receiver.add(frames[-1]))
            for frame in frames[-2::-1]:
                result = receiver.add(frame)
            self.assertEqual(result, data)
        frames = transport.encode(data, "P")
        payload = "".join(f[8:] for f in frames)
        raw = base64.b32decode(payload + "=" * (-len(payload) % 8))
        self.assertEqual(zlib.decompress(raw, -10) if frames[0][2] == "Z" else raw, data)
        self.assertTrue(all(f[3] == "P" for f in frames))

    def test_psbt_type_magic_and_seed(self):
        data = b"psbt\xff" + b"example" * 30
        frames = transport.encode(data, "P")
        self.assertEqual(len(frames), 1)
        with self.assertRaises(ValueError):
            transport.Receiver().add(frames[0])
        with self.assertRaises(ValueError):
            transport.Receiver("P").add("B$HP010000")
        with self.assertRaises(ValueError):
            transport.encode(b"not a PSBT", "P")
        with tempfile.TemporaryDirectory() as directory:
            initial, output = Path(directory)/"first", Path(directory)/"output"
            initial.write_text(frames[0])
            with patch.object(transport.subprocess, "Popen") as camera:
                transport.scan(output, "P", initial)
                camera.assert_not_called()
            self.assertEqual(output.read_bytes(), data)

    def test_counter_placement_uses_clear_side_or_rearranges(self):
        self.assertEqual(transport.side_positions((30, 100, 640, 480), (0, 0, 380, 120), (1366, 768)),
                         (None, (686, 100)))
        self.assertEqual(transport.side_positions((360, 100, 640, 480), (0, 0, 380, 120), (1366, 768)),
                         ((16, 100), (672, 100)))
        self.assertEqual(transport.side_positions((200, 100, 640, 480), (0, 0, 380, 120), (1024, 768)),
                         (None, (200, 596)))
        self.assertIsNone(transport.side_positions((0, 0, 640, 480), (0, 0, 380, 120), (640, 480)))

    def test_x11_placement_requests_nonoverlapping_window_positions(self):
        import ctypes
        tree = ('  0x101 "zbar barcode reader": () 640x480+0+0 +360+100\n'
                '  0x102 "Wallet QR transfer": () 380x120+0+0 +500+400\n')
        lib = MagicMock()
        lib.XOpenDisplay.return_value = 1
        lib.XDefaultRootWindow.return_value = 10
        lib.XInternAtom.return_value = 42
        moves = []
        def sent(_display, _root, _propagate, _mask, pointer):
            event = pointer._obj.client
            self.assertEqual(event.message_type, 42)
            self.assertEqual(event.format, 32)
            moves.append((event.window, event.data.l[1], event.data.l[2]))
            return 1
        lib.XSendEvent.side_effect = sent
        replies = [subprocess.CompletedProcess([], 0, tree, ""),
                   subprocess.CompletedProcess([], 0, "Width: 1366\nHeight: 768\n", "")]
        with patch.dict(os.environ, {"DISPLAY": ":test"}), \
                patch.object(transport.shutil, "which", return_value="/usr/bin/xwininfo"), \
                patch.object(transport.subprocess, "run", side_effect=replies), \
                patch("ctypes.util.find_library", return_value="test-X11"), \
                patch.object(ctypes, "CDLL", return_value=lib):
            self.assertTrue(transport.position_counter())
        self.assertEqual(moves, [(0x101, 16, 100), (0x102, 672, 100)])
        lib.XCloseDisplay.assert_called_once_with(1)

    def test_counter_cancellation_stops_camera(self):
        camera, progress = MagicMock(), MagicMock()
        camera.poll.return_value = None
        camera.wait.return_value = 0
        progress.poll.return_value = 0
        progress.wait.return_value = 0
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "received"
            with patch.object(transport.subprocess, "Popen", side_effect=[camera, progress]), \
                    patch.object(transport.selectors, "DefaultSelector"):
                with self.assertRaises(transport.Cancelled):
                    transport.scan(output)
            self.assertFalse(output.exists())
        camera.terminate.assert_called_once()
        camera.stdout.close.assert_called_once()
        progress.stdin.close.assert_called_once()

    def test_psbt_seeded_progress_and_cleanup(self):
        self.test_progress_counter_and_camera_cleanup_without_desktop("P")

    def test_progress_counter_and_camera_cleanup_without_desktop(self, file_type="J"):
        # Real child processes exercise the pipe/progress lifecycle. Only the
        # camera/UI commands and platform-specific readiness selector are replaced.
        class Ready:
            def __enter__(self): return self
            def __exit__(self, *_args): pass
            def register(self, *_args): pass
            def select(self, *_args): return [True]

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output, progress_log = root / "frames", root / "wallet", root / "progress"
            data = b"psbt\xff" + os.urandom(2000) if file_type == "P" else fixture(2000)
            frames = transport.encode(data, file_type)
            initial = root / "initial"
            initial.write_text(frames[0])
            camera_frames = frames[1:] if file_type == "P" else frames
            source.write_bytes(("\n".join(camera_frames) + "\n").encode("ascii"))
            real_popen = subprocess.Popen
            children = []
            def spawn(command, **kwargs):
                if command[0] == "zbarcam":
                    command = [sys.executable, "-c",
                               "import pathlib,sys,time; sys.stdout.buffer.write(pathlib.Path(sys.argv[1]).read_bytes()); sys.stdout.buffer.flush(); time.sleep(30)",
                               str(source)]
                elif command[0] == "zenity":
                    command = [sys.executable, "-c",
                               "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text(sys.stdin.read())",
                               str(progress_log)]
                else:
                    raise AssertionError(command)
                process = real_popen(command, **kwargs)
                children.append(process)
                return process
            with patch.object(transport.subprocess, "Popen", side_effect=spawn), \
                    patch.object(transport.selectors, "DefaultSelector", Ready):
                transport.scan(output, file_type, initial if file_type == "P" else None)
            self.assertEqual(output.read_bytes(), data)
            text = progress_log.read_text()
            self.assertIn(f"{len(frames)} of {len(frames)} QR frames received", text)
            self.assertIn("100", text)
            self.assertTrue(all(child.poll() is not None for child in children))

    def test_first_qr_render_failure_is_not_silent_success(self):
        gtk, glib, gdk = MagicMock(), MagicMock(), MagicMock()
        gi = types.ModuleType("gi")
        repository = types.ModuleType("gi.repository")
        repository.Gdk = gdk
        gi.repository = repository
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "wallet.json"
            source.write_bytes(fixture(10))
            with patch.dict(sys.modules, {"gi": gi, "gi.repository": repository}), \
                    patch.object(transport, "gtk_modules", return_value=(glib, gtk)), \
                    patch.object(transport, "make_png", side_effect=ValueError("test PNG failure")):
                with self.assertRaisesRegex(ValueError, "QR display failed: test PNG failure"):
                    transport.show(source)
            gtk.Window.return_value.present.assert_not_called()
            gtk.Window.return_value.destroy.assert_called_once()

    def test_database_envelope_roundtrip(self):
        database = b"SQLite format 3\0" + os.urandom(16000)
        data = json.dumps({"format": "bails-watch-only", "version": 2, "network": "regtest",
                           "wallet": base64.b64encode(database).decode()}).encode()
        frames = transport.encode(data)
        self.assertGreater(len(frames), 1)
        restored = decode(reversed(frames))
        self.assertEqual(base64.b64decode(json.loads(restored)["wallet"]), database)

    def test_real_multiframe_images(self):
        data = fixture(10000)
        frames = rendered_frames(data)
        self.assertGreater(len(frames), 1)
        # Dropped frames are recovered on the next cycle, duplicates ignored.
        receiver = transport.Receiver()
        for frame in frames[::2] + frames[::2]:
            self.assertIsNone(receiver.add(frame))
        for frame in reversed(frames[1::2]):
            restored = receiver.add(frame)
        self.assertEqual(restored, data)

    def test_compression_and_supported_encodings(self):
        data = json.dumps({"format":"bails-watch-only", "padding":"repeat" * 100}).encode()
        frames = transport.encode(data)
        self.assertTrue(frames[0].startswith("B$ZJ"))
        self.assertEqual(decode(frames), data)
        self.assertEqual(decode(["B$HJ0100" + data.hex().upper()]), data)
        text = base64.b32encode(data).decode().rstrip("=")
        self.assertEqual(decode(["B$2J0100" + text]), data)

    def test_limits_and_invalid_frames(self):
        for frame in ("", "B$HJ0000AA", "B$HJ0101AA", "B$HJZZ00AA", "B$HJ0100XX",
                      "B$2J0100AB", "B$ZJ0100AAAA", "B$HP010000", "B$HJ0100" + "A" * 4300):
            with self.subTest(frame=frame[:20]), self.assertRaises((ValueError, zlib.error)):
                transport.Receiver().add(frame)
        with self.assertRaises(ValueError):
            transport.encode(os.urandom(200000))
        with self.assertRaises(ValueError):
            transport.encode(b"\0" * (transport.MAX_FILE + 1))
        frames = transport.encode(fixture(2000))
        receiver = transport.Receiver()
        receiver.add(frames[0])
        with self.assertRaises(ValueError):
            receiver.add(frames[0][:-1] + ("A" if frames[0][-1] != "A" else "B"))
        with self.assertRaises(ValueError):
            receiver.add("B$HJ010000")
        with self.assertRaises(ValueError):
            decode(["B$HJ0200" + b"SQLite format 3\0".hex().upper(), "B$HJ0201" + "00" * 17])
        compressor = zlib.compressobj(9, zlib.DEFLATED, -10)
        bomb = compressor.compress(b"\0" * (transport.MAX_FILE + 1)) + compressor.flush()
        with self.assertRaises(ValueError):
            decode(["B$ZJ0100" + base64.b32encode(bomb).decode().rstrip("=")])

    def test_camera_completion_cancellation_and_cleanup(self):
        data = fixture(3000)
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            camera = directory / "zbarcam"
            progress = directory / "zenity"
            source, output = directory / "frames", directory / "wallet.dat"
            # Test doubles only replace camera hardware and progress UI.
            camera.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >"$CAMERA_ARGS"\ncat "$CAMERA_FRAMES"\nexec sleep 30\n')
            progress.write_text('#!/bin/sh\ncat >"$PROGRESS_LOG"\n')
            camera.chmod(0o755)
            progress.chmod(0o755)
            frames = transport.encode(data)
            source.write_text("\n".join(frames[::-1]) + "\n")
            env = dict(os.environ, PATH=str(directory) + ":" + os.environ["PATH"],
                       CAMERA_ARGS=str(directory / "args"), CAMERA_FRAMES=str(source),
                       PROGRESS_LOG=str(directory / "progress"))
            result = subprocess.run([sys.executable, str(HELPER), "scan", str(output)], env=env, timeout=10)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(output.read_bytes(), data)
            self.assertNotIn("--oneshot", (directory / "args").read_text())
            progress_text = (directory / "progress").read_text()
            self.assertIn(f"{len(frames)} of {len(frames)} QR frames received", progress_text)
            self.assertIn("100", progress_text)
            output.unlink()
            camera.write_text('#!/bin/sh\nexit 0\n')
            result = subprocess.run([sys.executable, str(HELPER), "scan", str(output)], env=env, timeout=10)
            self.assertEqual(result.returncode, 2)
            self.assertFalse(output.exists())
            camera.write_text('#!/bin/sh\nexit 1\n')
            result = subprocess.run([sys.executable, str(HELPER), "scan", str(output)], env=env,
                                    timeout=10, capture_output=True)
            self.assertEqual(result.returncode, 1)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    if len(sys.argv) in (4, 5) and sys.argv[1] == "--render":
        frames = rendered_frames(Path(sys.argv[2]).read_bytes(), sys.argv[4] if len(sys.argv) == 5 else "J")
        Path(sys.argv[3]).write_text("\n".join(frames) + "\n")
    else:
        unittest.main()

