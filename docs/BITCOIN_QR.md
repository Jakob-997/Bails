# QR transfer

Use **QR transfer** to check receiving addresses, move transactions between your
online CipherStick and offline CryoStick, and set up a watch-only wallet.
Open Bitcoin Core on both computers, then choose **CipherStick** > **QR transfer**.

Keep the QR image open until the other computer scans it. Try maximizing the
image window if scanning is difficult. Sideways and upside-down QRs also work.
Close the camera window to cancel a scan; it also stops after three minutes.

## Set up your watch-only wallet

1. On the CryoStick, open your signing wallet in Bitcoin Core.

2. Choose **Wallet Tools** > **Export Watch-Only Wallet**, then select that wallet.
   A QR image opens. It contains the public wallet information and address labels,
   without the private keys.

3. On the CipherStick, choose **Wallet Tools** > **Import Watch-Only Wallet**
   and scan the QR image.

4. Wait for the import to finish. Core may need time to find past payments;
   missing historical blocks can prevent it from completing.
   Select **[Watch-only] <original wallet name>** in Core.
   Find imported receiving addresses and labels under **Window** > **Receiving addresses**.

An existing wallet with that name is not replaced. If import fails, the new
wallet may be incomplete; do not use it until the problem is resolved.
Saved payment requests are not copied. The next address matches the signing
wallet at the time of export; later address requests do not synchronize the copies.
Choose the same address type on both computers when comparing addresses.

## Check a receiving address

1. On the CryoStick, open your signing wallet in Core.

2. Choose **Verify Receiving Address** and scan the receiving address from
   your online wallet.

3. Check the address and wallet name in the result. A confirmation means that
   wallet holds the signing key; it does not prove nobody else has a copy.
   For an encrypted wallet, make sure you have the passphrase and can unlock it.

If a warning says the address is unrecognized, the signing key is missing,
or signing is not confirmed, stop and check with your offline signing wallet.
Do not send funds until you have resolved the warning. A watch-only match is
not a signing-key confirmation. Multisig and other complex wallets need
additional verification that this tool does not perform.

## Move a transaction for signing

1. On the CipherStick, prepare your payment in Core and choose **Create Unsigned**,
   then **Copy to Clipboard**. For a transaction already open in Core, use its
   **Copy to Clipboard** button.

2. Choose **Send PSBT**, paste the copied text, and click **Show QR**.

3. On the CryoStick, choose **Receive PSBT**, scan the QR, and click **Copy**.

4. In Core, select your signing wallet and choose **File** > **Load PSBT from clipboard**.
   Keep the text window open until Core has loaded the transaction, then close it.
   Check the recipient, amount, change, and fee before choosing **Sign Tx**.

5. Copy the signed transaction from Core and repeat the transfer in the other
   direction. On the CipherStick, load it in Core, review it, and choose **Broadcast Tx**.

Use this tool on both computers. Its compressed transaction QRs cannot be
scanned directly by Sparrow. Animated QRs are not supported.
The QR tool itself never unlocks a wallet, signs, or broadcasts.

## Use a USB stick or microSD card instead

If there is no webcam or a QR is too large or difficult to scan, transfer a file.
If the tool offers to save an oversized export, you can choose **Cancel** and use
Core's file options below instead.

For a watch-only wallet:

1. On the CryoStick, select your signing wallet in Core and choose
   **File** > **Export watch-only wallet**. Save the exported file.

2. Copy that file to a USB stick or microSD card and move it to the CipherStick.
   Only move the exported watch-only file; never copy your signing wallet.

3. On the CipherStick, choose **File** > **Restore Wallet** and select the file.
   This uses a different file format from **Import Watch-Only Wallet** in the QR tool.

For a transaction, save the PSBT in Core, move the file to the other computer,
and choose **File** > **Load PSBT from file**. After signing, save and return the
signed file to the CipherStick, then load, review, and broadcast it in Core.
