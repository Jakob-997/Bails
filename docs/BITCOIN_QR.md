# Static QR transfer

Open **CipherStick** > **QR transfer**, or the **QR transfer** application.
This tool uses one static QR per transfer. It does not use BBQr or UR.
The main menu offers **Verify Receiving Address**, **Receive PSBT**, **Send PSBT**,
and **Wallet Tools**. Each scanning action accepts only its selected type.

## Requirements

Use the normal Bails installation on Tails, with Bitcoin Core running.
The tool uses `bitcoin-cli`, Zenity, `zbarcam` from `zbar-tools`, `xdg-open`,
and Tails' GTK 3 Python bindings for the clipboard,
Python 3, and Tails' `python3-qrcode` library and `python3-qr` command. It uses the
library's default PNG renderer without selecting PIL or another image factory.
It installs nothing.
Wallet export requires Core's `exportwatchonlywallet` RPC (Core 32 or later).
Options such as `-regtest` and `-datadir=/path` can be passed to `bails-qr`;
they are forwarded to `bitcoin-cli`.

## Transfer the watch-only wallet

1. On the CryoStick, open the signing wallet in Bitcoin Core.

2. Choose **Wallet Tools** > **Export Watch-Only Wallet** and select that loaded wallet.
   Core creates a watch-only *wallet.dat*. The tool compresses it with gzip
   and opens a static QR image. The signing wallet file is never sent.
   The export preserves the public wallet data that Core includes, such as
   transactions, labels, and receive-request metadata.

3. On the CipherStick, choose **Wallet Tools** > **Import Watch-Only Wallet**.
   Hold the QR steady in view of the camera. Close the camera window to cancel;
   scanning times out after
   three minutes.

4. Save the received file with a new name, such as *watch-only.dat*.
   Choose a location in **Persistent Storage** only if you want to keep it.

5. In Bitcoin Core, choose **File** > **Restore Wallet** and select the file.
   Core validates and restores it. The QR tool recognizes the SQLite file
   header; it does not itself validate or restore the wallet database.

## Transfer a PSBT

1. Copy an unsigned or signed PSBT as text from Bitcoin Core.

2. Choose **Send PSBT**, paste the text into the box, and click **OK**. Core checks that it decodes.
   The static QR contains its Base64 representation, which Sparrow can scan.

3. On the other computer, choose **Receive PSBT**. Core checks that the transaction
   decodes, then the tool shows its Base64 text. Click **Copy**, or select the
   text and press **Ctrl+C**.

4. In Core, select your wallet, then choose **File** > **Load PSBT from clipboard**. Review the transaction
   before signing or broadcasting. The QR tool does neither.
   Close the text window after loading it in Core.

Scanning also accepts the gzip-compressed PSBT format in the manual
[CryoStick instructions](CRYOSTICK.md). It does not accept Sparrow's UR or
BBQr QR exports; copy the PSBT as Base64 text in Sparrow for the return trip.

## Check a receive address

Choose **Verify Receiving Address** and scan an address or a `bitcoin:` payment URI. The tool
checks Core's `ismine` result across the open wallets automatically. Open your
signing wallet in Core first; no wallet selection is needed for this check.
An owned address shows **You own this address**. An address that none of the open
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

The QR opens in Tails' normal image viewer without a separate instruction popup.
Close the image after scanning. The viewer controls window size and zoom.

The QR tool keeps working files in `/tmp` with private permissions and removes
them when it exits normally. Saved files are written only where you choose;
existing files are not overwritten.

## Validation

Run `python3 tests/bails-qr.py` with `qrcode`, Pillow, and `zxing-cpp`
available in the test environment. The QR tests use the upstream generator
and decode its PNG output independently.

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
