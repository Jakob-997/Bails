# QR transfer

A small Bash/Zenity program for exchanging Bitcoin Core wallet data between
online and offline computers. A small Python helper displays and collects fixed
BBQr wallet frames using the QR and GTK modules already required on Tails 7.

## Try the testing branch

On Tails, install the complete fork (including Bitcoin Core and QR transfer):

```sh
git clone --branch zenity-qr-mvp https://github.com/Jakob-997/Bails.git bails-qr-test
bash bails-qr-test/b
```

Follow the normal persistent-storage setup. Open **QR transfer** from the
application launcher or the **CipherStick** menu. Install on both computers;
the same program handles unsigned and signed transactions in either direction.

Transaction QR generation uses `python3-qr --factory=pil --error-correction=L`,
matching the existing CryoStick instructions. Wallet QR generation uses the same
Python `qrcode` module directly. Scanning uses `zbarcam --raw`, with binary and
QR-only options: one-shot for transactions/addresses, continuous for wallets.
No `qrencode`, `jq`, or downloaded QR protocol library is required.
The installer checks these commands and exercises PNG generation before
changing the installation. An incompatible environment stops with an error.
Other runtime requirements are Zenity, Python 3, `gzip`, GNU coreutils and
`xdg-open`; Bitcoin Core 32+ supplies descriptor RPCs through the normal
Bails Core installation. The wallet viewer uses the GTK 4/PyGObject modules
also used by Bails' codex32 application; the installer checks them.

When included in a normal Bails installation, **QR transfer** appears as its own
application launcher with a QR icon and in the **CipherStick** menu. The `.desktop`
launcher uses Bails' installed Persistent Storage path. The script, launcher
and icon are copied by the normal installer and persisted with Bails.

For development only, run `bash bails/.local/bin/bails-qr` from the checkout
with Core already installed. Append `-regtest -datadir=/path/to/test-node`
to use a test node. `--check` tests the QR runtime without opening the menu.

## Everyday actions

- **Scan QR** — import a transaction (PSBT) or verify a receive address. The
  program recognizes an address/BIP21 URI or a PSBT automatically. For an address,
  select the loaded wallet to check; Core's `getaddressinfo` supplies `ismine`.
  For a PSBT, choose a new filename, then open it in Core using **File → Load PSBT
  from file**. Offline, review and sign. Online, review the returned signed
  transaction before broadcasting in Core.
- **Send transaction** — show a transaction as a QR for the other wallet. Select
  a PSBT saved by Core: unsigned goes offline for signing; signed goes online.
  This action only displays the QR.
- **Wallet tools** opens the less frequent setup actions: **Export watch-only
  wallet** on the offline computer, or **Receive watch-only wallet** online.
  Export creates one compact JSON file containing public descriptors, their
  ranges and next address indexes, and BIP329-style address/label records
  (including empty labels). It excludes the wallet database and private keys.
  Compressed data cycles through smaller numbered QR frames. Receive opens
  the camera immediately, then asks for a new wallet name and imports directly
  into a fresh, blank wallet with private keys disabled. Core rescans from the
  descriptor timestamps to recover used-address history; historical blocks must
  be available. Update both computers before transferring wallets.

The native Zenity menu uses compact single-click action buttons and short
explanations above them. Wallet tools provides the less frequent watch-only
setup actions. The dialog displays the bundled QR icon using its installed file
path, so it does not depend on finding that icon in the desktop theme cache.
Scan QR uses a camera symbol when an emoji font is available and a plain
label otherwise, avoiding missing-glyph boxes. Close and Escape exit the menu. Previews show the actual Zenity dialog; its
appearance can vary with the installed Tails theme.

Scan QR opens the camera immediately. Send transaction opens the file picker
immediately. Wallet export opens its QR window after wallet selection, without
a confirmation screen. Close the camera or wallet progress window to cancel.
Transaction/address scans time out after two minutes; wallet scans after five.
Transaction QR images open in a separate viewer; close it after scanning.
Received files are saved only to a user-selected new path; existing files and
symlinks are never overwritten.

## Limits and security boundaries

- Transactions use gzip-compressed binary in one QR, compatible with the
  CryoStick manual commands. Scan QR also accepts raw binary/base64 PSBTs and
  addresses/BIP21 address QRs. Transaction data must fit 2,953 compressed bytes;
  large PSBTs still require Core file transfer. UR is not supported.
- Wallets use [BBQr](https://github.com/coinkite/BBQr/blob/master/BBQr.md), binary
  type `J`, with raw DEFLATE (`Z`) compression or uncompressed base32 (`2`).
  The receiver also accepts BBQr hex (`H`). Each displayed QR is version 12,
  error correction L, at most 488 characters, and advances every 600 ms.
  A fixed finite set repeats; no fountain encoding is used. The JSON
  payload is a versioned Bails setup bundle, not a cross-wallet setup standard.
- Wallet exports are limited to 1 MiB uncompressed and 256 QR frames. Transfers
  exceeding these limits require Core file transfer. Frames must agree on their
  headers and lengths; conflicting duplicates and truncated compressed data are
  rejected. BBQr checks neither sender identity nor whole-file authenticity.
- Receive watch-only wallet expects the new BBQr format. Legacy single-gzip
  wallet QRs can still be received with the manual CryoStick commands.
- Scans and decompression are bounded. Core validates PSBTs. Scanned text is
  never evaluated as shell code and scanned URLs are never opened. The helper
  does not unlock wallets, sign transactions or broadcast transactions.
- A wallet export scanned from the main screen directs the user to Wallet tools.
  Wallet setup metadata and network are validated before creating a wallet;
  Core validates descriptors and rejects private keys. Import never replaces
  an existing wallet. An unsuccessful rescan/import can leave a partial new
  wallet: inspect the error in Core before retrying with another name.
- The address check verifies ownership only. It ignores BIP21 payment parameters
  and does not prove the selected wallet can sign. Control/binary bytes in an
  address payload are rejected instead of silently removed.
- Exported wallet data is private financial metadata. Temporary files are kept
  with restrictive permissions under `/tmp`, which is memory-backed on Tails,
  and removed on normal exit/signals. The program does not enforce the air gap;
  use CryoStick's existing offline setup.

## Validation

```sh
bash -n bails/.local/bin/bails-qr
shellcheck bails/.local/bin/bails-qr tests/bails-qr.sh
bash tests/bails-qr.sh
bash tests/bails-qr-install.sh
python3 tests/bails-qr-frames.py
desktop-file-validate bails/.local/share/applications/bails-qr.desktop
git diff --check
```

The integration test uses a network-disabled Core regtest node and actual QR
images decoded by `zbarimg`. It covers wallet metadata preservation, unsigned and
signed PSBT transfer, automatic format detection, address ownership, malformed
input, size limits, cancellation, camera failure, overwrite/symlink protection,
and Zenity menu dispatch, including nonzero extra-button status. Multipart tests
cover real frame images, out-of-order/repeated/missed parts, compression bounds,
camera completion/cancellation, and byte-identical setup transfer, label preservation and Core history reconstruction.

Before deployment, test on current stable Tails with real webcams: launcher and
menu appearance, themed icons, camera cancellation/timeout, full-size image
scanning, wallet restoration, encrypted-wallet signing, and both transfer
directions. Headless integration tests do not replace those checks.
