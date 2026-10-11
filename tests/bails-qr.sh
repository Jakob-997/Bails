#!/bin/bash
# Copyright (c) 2026 Bails contributors
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

# Real Core/QR integration; only Zenity, image viewing and camera are replaced.
# Requires Core 32+, jq, python3-qr, zbarimg and the standard GNU utilities.
# Variables such as wallet are consumed by the sourced application functions.
# shellcheck disable=SC2034
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
# shellcheck source=/dev/null
source "$root/bails/.local/bin/bails-qr"
tmp=$(mktemp -d)
node="$tmp/node"
mkdir "$node" "$tmp/bin"
core_args=(-regtest -datadir="$node")
cleanup() {
    local status=$?
    if ((status != 0)); then
        cat "$tmp/last-dialog" "$tmp/camera-error" "$tmp/rpc-error" 2>/dev/null || true
    fi
    rpc stop >/dev/null 2>&1 || true
    for ((i=0; i<100; i++)); do
        [[ -e $node/regtest/bitcoind.pid ]] || break
        sleep 0.1
    done
    [[ ! -e $node/regtest/bitcoind.pid ]] || return 1
    rm -rf -- "$tmp"
}
trap cleanup EXIT

# No real dialogs, clipboard, camera, networking or funds in this test.
dialog() {
    printf '%s\n' "$*" >"$tmp/last-dialog"
    [[ ${cancel_dialog:-false} == false ]] || return 1
    case "$*" in *--entry*) printf "%s\n" "$new_wallet" ;; *--file-selection*) printf '%s\n' "$destination" ;; esac
}
xdg-open() { cp -- "$1" "$TEST_QR"; }
choose_wallet() { wallet=offline; }
wallet_frames() {
    if [[ $1 == show ]]; then
        python3 "$root/tests/bails-qr-frames.py" --render "$2" "$WALLET_FRAMES"
    else
        python3 "$root/bails/.local/bin/bails-qr-frames" "$@"
    fi
}
cat >"$tmp/bin/zbarcam" <<'EOF'
#!/bin/bash
if [[ ${CAMERA_FAIL:-false} == true ]]; then
    exit 1
elif [[ $* != *--oneshot* ]]; then
    cat "$WALLET_FRAMES"
    exec sleep 30
elif [[ -n ${SCAN_BYTES:-} ]]; then
    cat "$SCAN_BYTES"
else
    exec zbarimg --nodbus --quiet --raw -Sbinary "$TEST_QR"
fi
EOF
printf '#!/bin/sh\ncat >/dev/null\n' >"$tmp/bin/zenity"
chmod +x "$tmp/bin/zbarcam" "$tmp/bin/zenity"
export PATH="$tmp/bin:$PATH" TEST_QR="$tmp/qr.png" WALLET_FRAMES="$tmp/wallet-frames"

reject() { if "$@"; then printf 'FAIL: accepted %s\n' "$*" >&2; exit 1; fi; }
pass() { printf 'PASS: %s\n' "$*"; }

bitcoind "${core_args[@]}" -daemonwait -listen=0 -connect=0 -dnsseed=0 -fallbackfee=0.0001 >/dev/null
rpc createwallet offline >/dev/null
wallet=offline
first=$(wallet_rpc getnewaddress 'Savings label')
second=$(wallet_rpc getnewaddress $'Second label\nUnicode: cafe')
unlabeled=$(wallet_rpc getnewaddress '')
export_wallet
new_wallet=online
receive_wallet

rpc -rpcwallet=online getwalletinfo | jq -e '.private_keys_enabled == false' >/dev/null
rpc -rpcwallet=online getaddressinfo "$first" | jq -e '.labels == ["Savings label"]' >/dev/null
rpc -rpcwallet=online getaddressinfo "$second" | jq -e '.labels == ["Second label\nUnicode: cafe"]' >/dev/null
[[ $(wallet_rpc getnewaddress) == "$(rpc -rpcwallet=online getnewaddress)" ]]
rpc -rpcwallet=online getaddressinfo "$unlabeled" | jq -e '.labels == [""]' >/dev/null
wallet_rpc exportwatchonlywallet "$tmp/comparison.dat" >/dev/null
printf 'Wallet setup size: %s bytes; wallet database: %s bytes\n' "$(stat -c %s "$tmp/watch-only.json")" "$(stat -c %s "$tmp/comparison.dat")"
pass 'wallet QR restores labels, watch-only status and next address index'

# A separate miner keeps the signing wallet small and gives it a used address.
rpc createwallet miner >/dev/null
mine=$(rpc -rpcwallet=miner getnewaddress)
rpc generatetoaddress 101 "$mine" >/dev/null
funding=$(rpc -rpcwallet=miner sendtoaddress "$first" 2)
rpc generatetoaddress 1 "$mine" >/dev/null
wallet_rpc exportwatchonlywallet "$tmp/used.dat" >/dev/null
rpc restorewallet used "$tmp/used.dat" >/dev/null
rpc -rpcwallet=used getaddressinfo "$first" | jq -e '.labels == ["Savings label"]' >/dev/null
rpc -rpcwallet=used gettransaction "$funding" | jq -e '.amount == 2' >/dev/null
pass 'Core watch-only export preserves used-address transaction and label'

# Labels and Core state from an export larger than one QR survive multipart QR.
for ((i=0; i<35; i++)); do
    label=$(head -c 64 /dev/urandom | base64 -w0)
    wallet_rpc getnewaddress "$label" >/dev/null
done
export_wallet
[[ $(wc -l <"$WALLET_FRAMES") -gt 1 ]]
new_wallet=large
receive_wallet

rpc -rpcwallet=large getaddressinfo "$first" | jq -e '.labels == ["Savings label"]' >/dev/null
rpc -rpcwallet=large gettransaction "$funding" | jq -e '.amount == 2' >/dev/null
[[ $(wallet_rpc getnewaddress) == "$(rpc -rpcwallet=large getnewaddress)" ]]
wallet_rpc listlabels >"$tmp/offline-labels"
rpc -rpcwallet=large listlabels >"$tmp/online-labels"
cmp "$tmp/offline-labels" "$tmp/online-labels"
# Private descriptors and a wrong network are rejected before a wallet is created.
wallet_rpc listdescriptors true >"$tmp/private-descriptors"
python3 - "$tmp" <<'PY'
import json, pathlib, sys
root=pathlib.Path(sys.argv[1]); bundle=json.loads((root/'watch-only.json').read_text())
bundle['descriptors']=json.loads((root/'private-descriptors').read_text())['descriptors']
for item in bundle['descriptors']: item.pop('next', None)
(root/'private.json').write_text(json.dumps(bundle))
bundle=json.loads((root/'watch-only.json').read_text()); bundle['network']='main'
(root/'network.json').write_text(json.dumps(bundle))
PY
reject wallet_data import "$tmp/private.json" rejected-private "${core_args[@]}"
reject wallet_data import "$tmp/network.json" rejected-network "${core_args[@]}"
rpc listwallets | jq -e 'index("rejected-private") == null and index("rejected-network") == null' >/dev/null
pass 'compact QR preserves labels, history and next index; unsafe imports rejected'

unsigned=$(rpc -rpcwallet=large -named walletcreatefundedpsbt outputs="{\"$mine\":1}" | jq -r .psbt)
printf %s "$unsigned" | base64 -d >"$tmp/unsigned.psbt"
destination="$tmp/unsigned.psbt"
send_psbt
destination="$tmp/scanned-unsigned.psbt"
scan_transfer
cmp "$tmp/unsigned.psbt" "$destination"
signed=$(printf '%s\n' "$unsigned" | wallet_rpc -stdin walletprocesspsbt | jq -r .psbt)
printf %s "$signed" | base64 -d >"$tmp/signed.psbt"
destination="$tmp/signed.psbt"
send_psbt
scan && unpack || exit 1
cmp "$tmp/signed.psbt" "$tmp/payload"
{ base64 -w0 "$tmp/payload"; printf '\n'; } | rpc -stdin finalizepsbt | jq -e '.complete == true' >/dev/null
pass 'received PSBT can be signed and sent back as a complete transaction'

printf %s "$unsigned" >"$tmp/payload"
validate_psbt
cmp "$tmp/unsigned.psbt" "$tmp/transaction.psbt"
pass 'base64 PSBT input accepted as well as Core binary files'

printf '%s' "bitcoin:$first?amount=0.1" | python3-qr --factory=pil >"$TEST_QR"
scan_transfer
grep -q 'Address belongs' "$tmp/last-dialog"
printf '%s' "$mine" | python3-qr --factory=pil >"$TEST_QR"
reject scan_transfer
grep -q 'does NOT belong' "$tmp/last-dialog"
pass 'BIP21 owned address and unrelated address are distinguished'

printf 'not a PSBT' >"$tmp/payload"
reject validate_psbt
printf 'not gzip\n' >"$tmp/raw"
export SCAN_BYTES="$tmp/raw"
scan
reject unpack
printf '\x00\x0a\xff\x0a' >"$tmp/raw"
cancel_dialog=true
scan
cancel_dialog=false
cmp "$tmp/raw" "$tmp/scan"
: >"$tmp/raw"
reject scan
head -c 3000 /dev/zero >"$tmp/raw"
reject scan
unset SCAN_BYTES
pass 'binary bytes preserved; invalid PSBT, invalid gzip, empty and oversized scan rejected'

head -c 1048577 /dev/zero | gzip >"$tmp/scan"
reject unpack
gzip -c <"$tmp/unsigned.psbt" >"$tmp/scan"
truncate -s -3 "$tmp/scan"
reject unpack
head -c 4096 /dev/urandom >"$tmp/large"
reject show_qr "$tmp/large"
pass 'decompression limit, damaged gzip and QR capacity enforced'

destination="$tmp/existing"
printf original >"$destination"
reject save_received "$tmp/unsigned.psbt" existing
[[ $(cat "$destination") == original ]]
ln -s "$destination" "$tmp/link"
destination="$tmp/link"
reject save_received "$tmp/unsigned.psbt" link
[[ $(cat "$destination") == original ]]
cancel_dialog=true
reject save_received "$tmp/unsigned.psbt" cancelled
cancel_dialog=false
pass 'existing files, symlink targets and cancellation are safe'
head -n1 "$WALLET_FRAMES" | tr -d '\n' >"$tmp/wallet-frame"
export SCAN_BYTES="$tmp/wallet-frame"
reject scan_transfer
grep -q 'Wallet tools' "$tmp/last-dialog"
unset SCAN_BYTES
# Raw base64 PSBT and plain address QRs also use the same Scan QR action.
printf '%s' "$unsigned" | python3-qr --factory=pil >"$TEST_QR"
destination="$tmp/raw-psbt.psbt"
scan_transfer
cmp "$tmp/unsigned.psbt" "$destination"
printf '%s' "$first" | python3-qr --factory=pil >"$TEST_QR"
scan_transfer
grep -q 'Address belongs' "$tmp/last-dialog"
printf '%s' 'not a transaction' | python3-qr --factory=pil >"$TEST_QR"
reject scan_transfer
export CAMERA_FAIL=true
reject scan_transfer
unset CAMERA_FAIL
# Legacy single gzip wallet QRs still get directed to Wallet tools.
printf 'SQLite format 3\0' >"$tmp/tiny-wallet"
show_qr "$tmp/tiny-wallet"
reject scan_transfer
grep -q 'Wallet tools' "$tmp/last-dialog"
pass 'Scan QR detects address and PSBT formats, redirects wallets and rejects camera errors'

# Exercise Zenity action dispatch, including a nonzero extra-button status.
# These overrides are called indirectly by the sourced menu functions.
# shellcheck disable=SC2317
(
    printf 0 >"$tmp/menu-step"
    dialog() {
        local step
        step=$(cat "$tmp/menu-step")
        printf %s "$((step + 1))" >"$tmp/menu-step"
        case "$step" in
            0) printf '🔧  Wallet tools'; return 1 ;;
            1) printf '↙  Receive watch-only wallet'; return 1 ;;
            2) printf '📷  Scan QR'; return 1 ;;
            3) printf '📤  Send transaction'; return 1 ;;
            *) return 1 ;;
        esac
    }
    receive_wallet() { echo wallet >>"$tmp/actions"; }
    scan_transfer() { echo scan >>"$tmp/actions"; }
    send_psbt() { echo send >>"$tmp/actions"; }
    transfer_menu
    printf 'wallet\nscan\nsend\n' >"$tmp/expected-actions"
    cmp "$tmp/expected-actions" "$tmp/actions"
)
pass 'Wallet tools, Scan QR, Send transaction and Close dispatch correctly'
echo 'All QR transfer tests passed.'
