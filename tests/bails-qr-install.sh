#!/bin/bash
# Verify the normal installer carries the QR program, menu, launcher and icon.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
stage=$(mktemp -d)
trap 'rm -rf -- "$stage"' EXIT
mkdir "$stage/home" "$stage/persistent"
# Use the same rsync operation as the installer, without touching a real home.
rsync -a --perms "$root/bails/" "$stage/home/"
rsync -a --perms "$root/bails/" "$stage/persistent/"
for target in home persistent; do
    app="$stage/$target/.local/bin/bails-qr"
    test -x "$app"
    test -f "$stage/$target/.local/bin/bails-qr-frames"
    test -f "$stage/$target/.local/bin/bails-qr-wallet"
    "$app" --check
    grep -q 'bails-qr' "$stage/$target/.local/bin/bails-menu"
    grep -qx 'Exec=/live/persistence/TailsData_unlocked/dotfiles/.local/bin/bails-qr' \
        "$stage/$target/.local/share/applications/bails-qr.desktop"
    test -s "$stage/$target/.local/share/icons/hicolor/scalable/apps/bails-qr.svg"
done
# Missing/broken QR support must stop installation before its first copy.
# shellcheck disable=SC2016
grep -Fq 'bash "$BAILS_DIR/bails/.local/bin/bails-qr" --check || exit 1' "$root/b"
# shellcheck source=/dev/null
source "$root/bails/.local/bin/bails-qr"
# Functions and wallet are used/assigned by the sourced application.
# shellcheck disable=SC2317,SC2154
(
    # Exercise real wallet selection with whitespace and punctuation in names.
    rpc() { printf '%s' '["first", "wallet with spaces and \"quotes\""]'; }
    dialog() { cat >"$stage/wallet-rows"; printf 1; }
    choose_wallet
    [[ $wallet == 'wallet with spaces and "quotes"' ]]
    [[ $(wc -l <"$stage/wallet-rows") == 4 ]]
    rpc() { printf '[ \n ]'; }
    fail() { return 1; }
    if choose_wallet; then exit 1; fi
)
fail() { printf '%s\n' "$1" >&2; return 1; }
python3-qr() { return 1; }
if check_runtime; then
    echo 'Broken QR encoder passed the installer check' >&2
    exit 1
fi
echo 'PASS: installed QR runtime, launcher, menu, icon and failed-encoder check'
