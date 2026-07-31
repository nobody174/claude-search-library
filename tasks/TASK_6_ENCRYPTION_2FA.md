# Task 6: Encryption & 2FA Module

Create the encryption and 2FA module (`src/crypto.py`) for master passphrase + Google Authenticator TOTP.

## Requirements

1. **Function: `setup_device_first_time() -> dict`**
   - Generate TOTP secret (base32)
   - Display QR code for Google Authenticator
   - Prompt user for master passphrase
   - Verify TOTP code (must be current)
   - Derive encryption key from (passphrase + TOTP secret)
   - Encrypt TOTP secret with passphrase
   - Store encrypted TOTP on GitHub (`secrets.enc`)
   - Return: `{"encryption_key": bytes, "totp_secret": str}`

2. **Function: `join_device_existing_setup() -> dict`**
   - Prompt user for master passphrase
   - Fetch encrypted TOTP from GitHub
   - Decrypt using passphrase
   - Display QR code for Google Authenticator
   - Verify TOTP code
   - Derive encryption key from (passphrase + TOTP secret)
   - Return: `{"encryption_key": bytes, "totp_secret": str}`

3. **Function: `derive_encryption_key(passphrase: str, totp_secret: str) -> bytes`**
   - Combine both factors: `f"{passphrase}:{totp_secret}".encode()`
   - Use Argon2 for key derivation (slow, brute-force resistant)
   - Return 32-byte key for Fernet

4. **Function: `encrypt_data(plaintext: bytes, encryption_key: bytes) -> str`**
   - Use Fernet (AES-128 CBC)
   - Return base64 ciphertext

5. **Function: `decrypt_data(ciphertext: str, encryption_key: bytes) -> bytes`**
   - Use Fernet
   - Return plaintext

6. **TOTP Verification**
   - Verify code is current (within ±1 time step)
   - Handle time drift gracefully
   - Use `pyotp` library

7. **Backup Codes**
   - Generate 10 backup codes (for lost phone recovery)
   - Store encrypted on GitHub
   - Format: "847293-backup-1", etc.

## Libraries Required

```
cryptography  # Fernet encryption
pyotp         # Google Authenticator TOTP
argon2-cffi   # Key derivation
qrcode        # QR code display
```

## Setup Flow (First Device)

```
$ python3 -m src.crypto --setup

1. Generate TOTP Secret
   → QR Code displayed: [QR CODE]
   → Scan into Google Authenticator app

2. Enter Master Passphrase
   $ Enter master passphrase: solar-penguin-framework-mountain-crystal

3. Verify TOTP Code
   → Check Google Authenticator on phone
   $ Enter code from Authenticator: 847293

4. Success
   ✓ Encryption key derived and ready
   ✓ TOTP secret encrypted and stored on GitHub
   ✓ Master passphrase NOT stored anywhere
```

## Join Flow (Second Device)

```
$ python3 -m src.crypto --join-device

1. Enter Master Passphrase
   $ Enter master passphrase: solar-penguin-framework-mountain-crystal

2. Download & Decrypt TOTP Secret
   → App fetches secrets.enc from GitHub
   → Decrypts using passphrase

3. Add to Google Authenticator
   → QR Code displayed
   → Scan into Google Authenticator

4. Verify TOTP Code
   $ Enter code from Authenticator: 847293

5. Success
   ✓ Same encryption key as first device
   ✓ Same TOTP secret synced
```

## Testing

- Mock TOTP generation
- Verify encryption/decryption roundtrips
- Test passphrase validation
- Test backup codes generation

## Output File

Save as: `src/crypto.py`

---

**Paste into Claude Code!**
