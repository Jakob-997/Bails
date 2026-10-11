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


def rendered_frames(data):
    result = []
    with tempfile.TemporaryDirectory() as directory:
        image = Path(directory) / "frame.png"
        for frame in transport.encode(data):
            image.write_bytes(transport.make_png(frame))
            decoded = subprocess.check_output(["zbarimg", "--nodbus", "--quiet", "--raw", "-Sbinary", str(image)])
            result.append(decoded.decode("ascii").rstrip("\n"))
    return result


def decode(frames):
    receiver = transport.Receiver()
    data = None
    for frame in frames:
        data = receiver.add(frame)
    return data


class WalletFramesTests(unittest.TestCase):
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
            self.assertIn("100", (directory / "progress").read_text())
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
    if len(sys.argv) == 4 and sys.argv[1] == "--render":
        frames = rendered_frames(Path(sys.argv[2]).read_bytes())
        Path(sys.argv[3]).write_text("\n".join(frames) + "\n")
    else:
        unittest.main()
