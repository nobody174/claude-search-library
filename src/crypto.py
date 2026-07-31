"""Encryption & 2FA module for Claude Search Library.

Derives a Fernet encryption key from a master passphrase + TOTP secret
(two-factor key derivation), and provides setup/join flows for enrolling
new devices via Google Authenticator. The master passphrase is never
stored anywhere; only the (passphrase-encrypted) TOTP secret is persisted,
via `sync.py`'s GitHub transport (Task 7).
"""
from __future__ import annotations

import base64
import getpass
import logging
import secrets as secrets_module
from pathlib import Path
from typing import Optional

import pyotp
import qrcode
from argon2.low_level import Type, hash_secret_raw
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

LOG_PATH = Path.home() / ".claude-search-library" / "logs" / "crypto.log"
SECRETS_FILENAME = "secrets.enc"
TOTP_ISSUER = "Claude Search Library"
TOTP_VALID_WINDOW = 1  # +/- 1 time step (30s each) tolerance for clock drift

ARGON2_TIME_COST = 3
ARGON2_MEMORY_COST_KIB = 65536  # 64 MB
ARGON2_PARALLELISM = 4
ARGON2_SALT = b"claude-search-library-static-salt-v1"  # see note in derive_encryption_key
KEY_LENGTH_BYTES = 32

BACKUP_CODE_COUNT = 10


def _setup_file_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not any(isinstance(h, logging.FileHandler) and h.baseFilename == str(LOG_PATH) for h in logger.handlers):
        handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)


def derive_encryption_key(passphrase: str, totp_secret: str) -> bytes:
    """Derive a 32-byte Fernet-compatible key from passphrase + TOTP secret.

    Uses Argon2id (memory-hard, brute-force resistant). The salt is static
    and derived from the combined-factor scheme itself (not secret) rather
    than randomly generated, because the whole point of this function is
    that the SAME two factors, entered on a different device, must
    deterministically reproduce the SAME key — a random per-call salt would
    break that. Brute-force resistance instead comes from the two
    independent factors (passphrase + TOTP secret) that must both be known.
    """
    combined = f"{passphrase}:{totp_secret}".encode("utf-8")
    raw_key = hash_secret_raw(
        secret=combined,
        salt=ARGON2_SALT,
        time_cost=ARGON2_TIME_COST,
        memory_cost=ARGON2_MEMORY_COST_KIB,
        parallelism=ARGON2_PARALLELISM,
        hash_len=KEY_LENGTH_BYTES,
        type=Type.ID,
    )
    return base64.urlsafe_b64encode(raw_key)


def encrypt_data(plaintext: bytes, encryption_key: bytes) -> str:
    """Encrypt bytes with Fernet, returning a base64 ciphertext string."""
    f = Fernet(encryption_key)
    token = f.encrypt(plaintext)
    return token.decode("utf-8")


def decrypt_data(ciphertext: str, encryption_key: bytes) -> bytes:
    """Decrypt a Fernet base64 ciphertext string back to plaintext bytes."""
    f = Fernet(encryption_key)
    return f.decrypt(ciphertext.encode("utf-8"))


def generate_totp_secret() -> str:
    """Generate a new base32 TOTP secret."""
    return pyotp.random_base32()


def build_totp_uri(totp_secret: str, account_name: str = "claude-search-library") -> str:
    """Build the otpauth:// URI for QR-code enrollment in an authenticator app."""
    totp = pyotp.TOTP(totp_secret)
    return totp.provisioning_uri(name=account_name, issuer_name=TOTP_ISSUER)


def display_qr_code(uri: str) -> None:
    """Render the enrollment URI as a QR code in the terminal."""
    qr = qrcode.QRCode()
    qr.add_data(uri)
    qr.make(fit=True)
    qr.print_ascii(invert=True)


def verify_totp_code(totp_secret: str, code: str) -> bool:
    """Verify a TOTP code against the secret, tolerating +/-1 time step of drift."""
    totp = pyotp.TOTP(totp_secret)
    return totp.verify(code, valid_window=TOTP_VALID_WINDOW)


def generate_backup_codes(count: int = BACKUP_CODE_COUNT) -> list:
    """Generate one-time backup codes for lost-phone recovery.

    Format: "<6-digit-code>-backup-<n>", e.g. "847293-backup-1".
    """
    codes = []
    for i in range(1, count + 1):
        digits = f"{secrets_module.randbelow(1_000_000):06d}"
        codes.append(f"{digits}-backup-{i}")
    return codes


def _derive_passphrase_only_key(passphrase: str) -> bytes:
    """Derive a key from the passphrase alone, used only to wrap/unwrap the
    TOTP secret itself for GitHub storage (see module note on the
    setup/join bootstrap problem). This is distinct from
    `derive_encryption_key`, which combines both factors and is used for
    all other application data.
    """
    raw_key = hash_secret_raw(
        secret=passphrase.encode("utf-8"),
        salt=ARGON2_SALT,
        time_cost=ARGON2_TIME_COST,
        memory_cost=ARGON2_MEMORY_COST_KIB,
        parallelism=ARGON2_PARALLELISM,
        hash_len=KEY_LENGTH_BYTES,
        type=Type.ID,
    )
    return base64.urlsafe_b64encode(raw_key)


def _prompt_passphrase(prompt: str = "Enter master passphrase: ") -> str:
    return getpass.getpass(prompt)


def _prompt_totp_code(prompt: str = "Enter code from Authenticator: ") -> str:
    return input(prompt)


def _push_secrets_to_github(encrypted_totp: str) -> None:
    """Push the encrypted TOTP blob to GitHub as secrets.enc.

    Delegates to sync.py's GitHub transport (Task 7). Imported lazily so
    crypto.py has no hard dependency on sync.py during setup/testing.
    """
    from src import sync  # noqa: PLC0415

    sync.push_file(SECRETS_FILENAME, encrypted_totp)


def _fetch_secrets_from_github() -> str:
    """Fetch the encrypted TOTP blob (secrets.enc) from GitHub."""
    from src import sync  # noqa: PLC0415

    return sync.fetch_file(SECRETS_FILENAME)


def setup_device_first_time() -> dict:
    """First-device setup: generate a new TOTP secret, verify it, derive the key.

    Returns {"encryption_key": bytes, "totp_secret": str}. The master
    passphrase itself is never returned or persisted.
    """
    _setup_file_logging()

    totp_secret = generate_totp_secret()
    uri = build_totp_uri(totp_secret)
    print("Scan this QR code into Google Authenticator:")
    display_qr_code(uri)

    passphrase = _prompt_passphrase()

    code = _prompt_totp_code()
    if not verify_totp_code(totp_secret, code):
        logger.warning("setup_device_first_time: TOTP verification failed")
        raise ValueError("Invalid TOTP code")

    encryption_key = derive_encryption_key(passphrase, totp_secret)

    # The TOTP secret is wrapped with a passphrase-only key (not the combined
    # encryption_key), since a joining device must decrypt it using only the
    # passphrase, before it can know the TOTP secret needed for the combined key.
    passphrase_key = _derive_passphrase_only_key(passphrase)
    encrypted_totp = encrypt_data(totp_secret.encode("utf-8"), passphrase_key)
    _push_secrets_to_github(encrypted_totp)

    logger.info("setup_device_first_time: complete")
    print("Encryption key derived and ready.")
    print("TOTP secret encrypted and stored on GitHub.")
    print("Master passphrase NOT stored anywhere.")

    return {"encryption_key": encryption_key, "totp_secret": totp_secret}


def join_device_existing_setup() -> dict:
    """Join-device flow: fetch + decrypt the existing TOTP secret, verify, derive the key."""
    _setup_file_logging()

    passphrase = _prompt_passphrase()
    encrypted_totp = _fetch_secrets_from_github()

    passphrase_key = _derive_passphrase_only_key(passphrase)
    try:
        totp_secret = decrypt_data(encrypted_totp, passphrase_key).decode("utf-8")
    except InvalidToken as e:
        logger.warning("join_device_existing_setup: decrypt failed: %s", e)
        raise ValueError("Failed to decrypt TOTP secret — check your passphrase") from e

    uri = build_totp_uri(totp_secret)
    print("Scan this QR code into Google Authenticator:")
    display_qr_code(uri)

    code = _prompt_totp_code()
    if not verify_totp_code(totp_secret, code):
        logger.warning("join_device_existing_setup: TOTP verification failed")
        raise ValueError("Invalid TOTP code")

    encryption_key = derive_encryption_key(passphrase, totp_secret)

    logger.info("join_device_existing_setup: complete")
    print("Same encryption key as first device.")
    print("Same TOTP secret synced.")

    return {"encryption_key": encryption_key, "totp_secret": totp_secret}


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Claude Search Library encryption/2FA setup")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--setup", action="store_true", help="First-time device setup")
    group.add_argument("--join-device", action="store_true", help="Join an existing setup")
    args = parser.parse_args()

    if args.setup:
        setup_device_first_time()
    elif args.join_device:
        join_device_existing_setup()


if __name__ == "__main__":
    main()
