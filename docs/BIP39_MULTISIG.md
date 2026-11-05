# BIP39 and multisig wallet setup

This branch adds **Wallet Setup** to the CipherStick menu. Bitcoin Core remains
responsible for wallet storage, key derivation, descriptors, addresses, and
PSBT signing. The existing **Bitcoin QR** tool transfers the watch-only wallet
and PSBTs.

## Seed handling

New phrases use Trezor's pinned `python-mnemonic` implementation. The wizard
offers 12, 15, 18, 21, or 24 words (128 to 256 bits of entropy), optional user
entropy, and an optional BIP39 passphrase. Restoring checks the BIP39 checksum
and supports an optional BIP39 passphrase.

Before asking for user entropy, the wizard displays SHA-256 commitments to a
temporary Core `wallet.dat` and 32 bytes from Linux's CSPRNG. It creates that
temporary wallet with Bitcoin Core networking disabled, checks for zero peers,
stops Core, hashes the file, and requires the temporary directory to be
`tmpfs`. The final entropy is:

```text
SHA256(b"Bails-BIP39-v1\0" || SHA256(wallet.dat) || OS_random_32 ||
       uint32_be(length(user_entropy_utf8)) || user_entropy_utf8)
```

The wizard uses 16, 20, 24, 28, or 32 bytes for 12, 15, 18, 21, or 24 words.
Trezor's library converts that entropy to the phrase and the BIP39 seed. The
audit receipt records the source commitments, the formula, and a SHA-256
commitment to the final entropy. It never records the phrase, raw OS
randomness, user entropy, BIP39 passphrase, or extended private key. This makes
the receipt reviewable but intentionally insufficient to recreate the wallet;
the recovery phrase remains the backup.

## Multisig

The first version creates native SegWit P2WSH `sortedmulti` wallets. The local
signer uses `m/48'/0'/0'/2'`. Other signers provide one account xpub per line,
with optional origin metadata such as:

```text
[f23c9abc/48'/0'/0'/2']Zpub...
```

The wizard accepts mainnet xpubs and Zpubs, preserves supplied origins, and
does not require other signers to use the local signer's derivation path. It
converts SLIP-132 Zpub version bytes to standard xpub version bytes, then asks
Bitcoin Core to validate the resulting descriptor. Compare every origin and
key with the hardware wallet before receiving funds; Core cannot prove that
user-supplied origin metadata is truthful.

## Boundaries

- Requires a running mainnet Bitcoin Core 32.1 or newer.
- Runs only when the CryoStick marker exists and the persistent Core node has
  networking disabled with zero peers.
- The temporary Core process uses a separate RAM-backed data directory and
  `-networkactive=0`; it does not connect to or sync the Bitcoin network.
- Single-signature wallets use Core's native SegWit descriptor. Multisig uses
  Core's descriptor checksum and `importdescriptors`.
- Wallet-file encryption is optional and separate from a BIP39 passphrase.
- No custom elliptic-curve or descriptor-checksum code is added. BIP39 uses
  Trezor's pinned library; BIP32 root serialization uses Bails' pinned
  `python-codex32` API; Core handles public derivation and descriptor parsing.

This topic branch has not been integration-tested on supported Tails hardware
or independently security-reviewed. Do not use it to hold funds until those
reviews are complete.
