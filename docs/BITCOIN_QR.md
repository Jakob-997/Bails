# QR transfer

A small Bash/Zenity program for exchanging Bitcoin Core wallet data between
online and offline computers. A small Python helper displays and collects fixed
BBQr wallet frames using the QR and GTK modules already required on Tails 7.

## Update and test the fork

On Tails, install the complete fork (including Bitcoin Core and QR transfer):

```sh
git clone --branch qr-wallet-checks https://github.com/Jakob-997/Bails.git bails-qr-test
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
  the program searches every loaded wallet and wallet found by Core's
  `listwalletdir`. Unloaded wallets are temporarily loaded and then unloaded;
  existing startup preferences are preserved. Loading can require a rescan.
  Progress and per-wallet failures are shown. Every matching wallet is listed.
  Ownership and key status are separate results. No wallet-selection prompt
  is needed for address checks.
  For a PSBT, choose a new filename, then open it in Core using **File → Load PSBT
  from file**. Offline, review and sign. Online, review the returned signed
  transaction before broadcasting in Core.
- **Send transaction** — show a transaction as a QR for the other wallet. Select
  a PSBT saved by Core: unsigned goes offline for signing; signed goes online.
  This action only displays the QR.
- **Wallet tools** opens the less frequent setup actions: **Export watch-only
  wallet** on the offline computer, or **Receive watch-only wallet** online.
  Export creates a compact version 1 public-descriptor bundle: descriptor
  timestamps, receive/change ranges, next-address indexes, and all saved
  address-book entries and labels, including empty labels and unused issued
  receive addresses. Core confirms the descriptors contain no private keys.
  The bundle is compressed and cycles through numbered QR frames. Receive
  creates a new wallet with private keys disabled, imports the descriptors,
  rescans their history, and restores the labels. Relevant historical blocks
  must be available to the receiving node. Transaction history and the wallet
  database are not transmitted. Older version 2 database exports remain
  importable. Update both computers before transferring wallets.

The GTK menus use single-click buttons with bundled SVG icons directly beside
their labels. The larger initial window shows all actions without scrolling.
There is no decorative QR image or separate expanding icon column. **Close**
and Escape exit the main menu. Zenity handles the other transfer dialogs.

Scan QR opens the camera immediately. Send transaction opens the file picker
immediately. Wallet export opens its QR window after wallet selection, without
a confirmation screen. Close the camera window to cancel. Wallet scanning uses
brief desktop progress notifications when available, without a persistent
instructions dialog covering the camera preview.
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
  Network and encoding are checked before restoration. Core parses the database;
  a restored wallet that fails the watch-only checks is unloaded and rejected.
  Restored wallets are not automatically loaded at startup. Import never
  replaces an existing wallet. A failed import can leave a wallet directory:
  inspect the error in Core before retrying with another name.
- The address check uses `getaddressinfo` for ownership and `getwalletinfo`
  for enforced watch-only status. For ordinary single-key HD descriptors
  (`pkh`, `wpkh`, `sh(wpkh)`, and `tr` without a script tree), it matches the
  exact parent descriptor against the key-to-descriptor association in Core's
  `gethdkeys` inventory, requires one associated HD key with `has_private=true`, and
  requires `deriveaddresses` at the address index to reproduce the scanned
  address exactly. It never requests private HD keys or unlocks wallets.
  Locked-wallet key possession can still be reported; signing requires unlock.
  Core may store a master xpub while displaying a normalized account xpub in
  the descriptor. These strings are not required to match; Core's association
  supplies that relationship. Fingerprints alone are never used as proof.
  This trusts Core's key inventory; it is not a cryptographic signing test.
  Complex scripts, multisig, individual imported keys, unavailable RPCs and
  ambiguous derivations are reported as unverified. Neither `ismine` nor
  `private_keys_enabled` alone is treated as proof of signing ability.
  BIP21 amounts and balances are not checked. Control/binary bytes in an
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
python3 tests/bails-qr-wallet.py
desktop-file-validate bails/.local/share/applications/bails-qr.desktop
git diff --check
```

The integration test uses a network-disabled Core regtest node and actual QR
images decoded by `zbarimg`. It covers wallet metadata preservation, unsigned and
signed PSBT transfer, automatic format detection, address ownership, malformed
input, size limits, cancellation, camera failure, overwrite/symlink protection,
and menu dispatch. Multipart tests
cover real frame images, out-of-order/repeated/missed parts, compression bounds,
camera completion/cancellation, and byte-identical setup transfer, label preservation and Core history rescanning.

The RPC-boundary tests exercise exact key/descriptor/address matching, locked
and watch-only wallets, unsupported policies, failed lookups, temporary loading,
cleanup, and compact exports. The regtest script additionally checks real Core
key inventory and derivation, unloaded-wallet lookup, encrypted locked wallets,
and address/label preservation. These tests must pass on the supported Core
build before treating a new key-status integration as validated.

Before deployment, test on current stable Tails with real webcams: launcher and
menu appearance, themed icons, camera cancellation/timeout, full-size image
scanning, wallet restoration, encrypted-wallet signing, and both transfer
directions. Headless integration tests do not replace those checks.

