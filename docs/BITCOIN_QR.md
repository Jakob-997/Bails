# Static QR transfer

Open **CipherStick** > **QR transfer**, or the **QR transfer** application.
This tool uses one static QR per transfer. It does not use BBQr or UR.

## Requirements

Use the normal Bails installation on Tails, with Bitcoin Core running.
The tool uses `bitcoin-cli`, Zenity, `zbarcam` from `zbar-tools`, `xdg-open`,
Python 3, and Tails' `python3-qr` command from `python3-qrcode`. It uses that
command's default PNG renderer without selecting PIL or another image factory.
It installs nothing.
Run `bails-qr --check` to check the local dependencies. Wallet export also
requires Core's `exportwatchonlywallet` RPC (Core 32 or later).
Options such as `-regtest` and `-datadir=/path` can be passed to `bails-qr`;
they are forwarded to `bitcoin-cli`.

## Transfer the watch-only wallet

1. On the CryoStick, open the signing wallet in Bitcoin Core.

2. Choose **Export watch-only wallet** and select that loaded wallet.
   Core creates a watch-only *wallet.dat*. The tool compresses it with gzip
   and opens a static QR image. The signing wallet file is never sent.
   The export preserves the public wallet data that Core includes, such as
   transactions, labels, and receive-request metadata.

3. On the CipherStick, choose **Import watch-only wallet** (or **Scan QR**).
   Hold the QR steady in view of the camera. Close the camera window to cancel;
   scanning times out after
   three minutes.

4. Save the received file with a new name, such as *watch-only.dat*.
   Choose a location in **Persistent Storage** only if you want to keep it.

5. In Bitcoin Core, choose **File** > **Restore Wallet** and select the file.
   Core validates and restores it. The QR tool recognizes the SQLite file
   header; it does not itself validate or restore the wallet database.

## Transfer a PSBT

1. Save an unsigned or signed PSBT from Bitcoin Core.

2. Choose **Send PSBT** and select the file. Core checks that it decodes.
   The static QR contains its Base64 representation, which Sparrow can scan.
   Both binary and Base64 PSBT files are accepted.

3. On the other computer, choose **Scan QR** and save the PSBT.

4. In Core, choose **File** > **Load PSBT from file**. Review the transaction
   before signing or broadcasting. The QR tool does neither.

Scanning also accepts the gzip-compressed PSBT format in the manual
[CryoStick instructions](CRYOSTICK.md). It does not accept Sparrow's UR or
BBQr QR exports; save a PSBT file in Sparrow for the return trip.

## Check a receive address

Choose **Scan QR** and scan an address or a `bitcoin:` payment URI. The tool
checks Core's `ismine` result across the open wallets automatically. Open your
signing wallet in Core first; no wallet selection is needed for this check.
An owned address gets a green check mark. An address that none of the open
wallets recognize gets a warning to confirm it again on the offline signing
wallet before sending funds. Bech32 addresses are displayed in lowercase;
case-sensitive Base58 addresses keep their original case. Payment URI amounts
and other parameters are not used.

## Transfer files when a QR is too large or no camera is available

A binary QR can hold at most 2,953 bytes at the lowest error correction level.
Wallet transfers use compressed bytes; PSBT transfers use Base64 text, which
leaves room for at most 2,214 PSBT bytes. Real cameras may not read the densest
codes reliably. Wallets can grow beyond these limits even with compression.

If a transfer is too large, the tool offers to save the original file.
Use a new filename. To transfer without a camera:

1. Export a watch-only wallet using **File** > **Export watch-only wallet**,
   or save the PSBT in Core. Never copy the signing wallet's *wallet.dat*.

2. Copy the exported file to a USB stick or microSD card, move it to the
   receiving computer, and copy it there.

3. Restore the watch-only file, or load the PSBT, using the Core menu above.

The QR opens directly in the normal image viewer without a separate instruction
popup. Each transfer uses a new image file, so an earlier image cannot be reused
by the viewer for a different transfer. Close the QR image after scanning.

The QR tool keeps working files in `/tmp` with private permissions and removes
them when it exits normally. Saved files are written only where you choose;
existing files are not overwritten.

## Validation

Run `python3 tests/bails-qr.py` with `qrcode`, Pillow, and `zxing-cpp`
available in the test environment. The QR tests invoke the upstream generator's
command entry point and decode its PNG output independently.

The Windows development checks cover QR image round trips with an independent
decoder, compressed wallet bytes, raw oneshot scan output without an appended
newline, size limits, PSBT RPC validation, address selection, cancellation,
and file saving. Core and desktop
calls are simulated in those checks. They do not replace a Tails test.

Before using real funds, test on the supported Tails release with two computers:
export and restore a fresh watch-only wallet, compare its labels and metadata,
transfer an unsigned PSBT, sign it in Core, transfer it back, and check an address.
Also exercise camera cancellation, an unreadable QR, an oversized export,
an invalid PSBT, a missing dependency, and a save destination that already exists.
