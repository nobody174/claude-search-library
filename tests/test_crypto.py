import pyotp
import pytest
from cryptography.fernet import InvalidToken

from src import crypto


@pytest.fixture(autouse=True)
def redirect_log(tmp_path, monkeypatch):
    monkeypatch.setattr(crypto, "LOG_PATH", tmp_path / "crypto.log")
    crypto.logger.handlers.clear()
    # Tests must never be able to spawn a real GUI popup - it would hang
    # forever waiting for a human who isn't there. This is unconditional,
    # not just a default: a real popup escaped into a pytest run once
    # already (see the regression tests below) and looped indefinitely.
    monkeypatch.setattr(crypto, "USE_GUI_AUTH", False)
    # join_device_existing_setup() writes a session cache file on success;
    # without this redirect every test that exercises the full join flow
    # would write to (and could read a stale session from) the real
    # ~/.claude-search-library/.session_cache.json.
    monkeypatch.setattr(crypto, "SESSION_CACHE_PATH", tmp_path / ".session_cache.json")
    yield


def test_derive_encryption_key_is_deterministic():
    key1 = crypto.derive_encryption_key("correct-horse-battery", "JBSWY3DPEHPK3PXP")
    key2 = crypto.derive_encryption_key("correct-horse-battery", "JBSWY3DPEHPK3PXP")
    assert key1 == key2


def test_derive_encryption_key_differs_by_passphrase():
    key1 = crypto.derive_encryption_key("passphrase-a", "JBSWY3DPEHPK3PXP")
    key2 = crypto.derive_encryption_key("passphrase-b", "JBSWY3DPEHPK3PXP")
    assert key1 != key2


def test_derive_encryption_key_differs_by_totp_secret():
    key1 = crypto.derive_encryption_key("same-passphrase", "JBSWY3DPEHPK3PXP")
    key2 = crypto.derive_encryption_key("same-passphrase", "AAAAAAAAAAAAAAAA")
    assert key1 != key2


def test_derive_encryption_key_is_32_bytes_urlsafe_b64():
    key = crypto.derive_encryption_key("passphrase", "JBSWY3DPEHPK3PXP")
    # Fernet requires a 32-byte key, base64-urlsafe-encoded (44 chars with padding).
    from cryptography.fernet import Fernet
    Fernet(key)  # raises if malformed


def test_encrypt_decrypt_roundtrip():
    key = crypto.derive_encryption_key("passphrase", "JBSWY3DPEHPK3PXP")
    plaintext = b"super secret session data"
    ciphertext = crypto.encrypt_data(plaintext, key)
    assert isinstance(ciphertext, str)
    decrypted = crypto.decrypt_data(ciphertext, key)
    assert decrypted == plaintext


def test_decrypt_with_wrong_key_fails():
    key1 = crypto.derive_encryption_key("passphrase-a", "JBSWY3DPEHPK3PXP")
    key2 = crypto.derive_encryption_key("passphrase-b", "JBSWY3DPEHPK3PXP")
    ciphertext = crypto.encrypt_data(b"data", key1)
    with pytest.raises(InvalidToken):
        crypto.decrypt_data(ciphertext, key2)


def test_generate_totp_secret_is_valid_base32():
    secret = crypto.generate_totp_secret()
    totp = pyotp.TOTP(secret)  # raises on invalid base32
    assert totp.now() is not None


def test_verify_totp_code_accepts_current_code():
    secret = crypto.generate_totp_secret()
    totp = pyotp.TOTP(secret)
    current_code = totp.now()
    assert crypto.verify_totp_code(secret, current_code) is True


def test_verify_totp_code_rejects_wrong_code():
    secret = crypto.generate_totp_secret()
    assert crypto.verify_totp_code(secret, "000000") is False


def test_verify_totp_code_tolerates_time_drift(monkeypatch):
    secret = crypto.generate_totp_secret()
    totp = pyotp.TOTP(secret)
    # Code from one time-step (30s) in the past should still verify within window.
    import time
    past_code = totp.at(int(time.time()) - 30)
    assert crypto.verify_totp_code(secret, past_code) is True


def test_build_totp_uri_contains_issuer():
    secret = crypto.generate_totp_secret()
    uri = crypto.build_totp_uri(secret)
    assert "otpauth://totp/" in uri
    assert "Claude%20Search%20Library" in uri or "Claude Search Library" in uri


def test_generate_backup_codes_count_and_format():
    codes = crypto.generate_backup_codes()
    assert len(codes) == 10
    for i, code in enumerate(codes, start=1):
        assert code.endswith(f"-backup-{i}")
        digits = code.split("-")[0]
        assert digits.isdigit()
        assert len(digits) == 6


def test_generate_backup_codes_custom_count():
    codes = crypto.generate_backup_codes(count=3)
    assert len(codes) == 3


def test_generate_backup_codes_are_unique():
    codes = crypto.generate_backup_codes()
    digit_parts = [c.split("-")[0] for c in codes]
    assert len(set(digit_parts)) == len(digit_parts)


def test_setup_device_first_time_full_flow(monkeypatch):
    fixed_secret = pyotp.random_base32()
    pushed = {}

    monkeypatch.setattr(crypto, "generate_totp_secret", lambda: fixed_secret)
    monkeypatch.setattr(crypto, "display_qr_code", lambda uri: None)
    monkeypatch.setattr(crypto, "_prompt_passphrase", lambda: "test-passphrase")
    monkeypatch.setattr(crypto, "_prompt_totp_code", lambda: pyotp.TOTP(fixed_secret).now())
    monkeypatch.setattr(crypto, "_push_secrets_to_github", lambda blob: pushed.setdefault("blob", blob))

    result = crypto.setup_device_first_time()

    assert result["totp_secret"] == fixed_secret
    assert isinstance(result["encryption_key"], bytes)
    assert "blob" in pushed


def test_setup_device_first_time_rejects_bad_totp(monkeypatch):
    fixed_secret = pyotp.random_base32()
    monkeypatch.setattr(crypto, "generate_totp_secret", lambda: fixed_secret)
    monkeypatch.setattr(crypto, "display_qr_code", lambda uri: None)
    monkeypatch.setattr(crypto, "_prompt_passphrase", lambda: "test-passphrase")
    monkeypatch.setattr(crypto, "_prompt_totp_code", lambda: "000000")

    with pytest.raises(ValueError):
        crypto.setup_device_first_time()


def test_join_device_existing_setup_full_flow(monkeypatch):
    fixed_secret = pyotp.random_base32()
    passphrase = "test-passphrase"
    passphrase_key = crypto._derive_passphrase_only_key(passphrase)
    encrypted_totp = crypto.encrypt_data(fixed_secret.encode("utf-8"), passphrase_key)

    monkeypatch.setattr(crypto, "_prompt_passphrase", lambda: passphrase)
    monkeypatch.setattr(crypto, "_fetch_secrets_from_github", lambda: encrypted_totp)
    monkeypatch.setattr(crypto, "display_qr_code", lambda uri: None)
    monkeypatch.setattr(crypto, "_prompt_totp_code", lambda: pyotp.TOTP(fixed_secret).now())

    result = crypto.join_device_existing_setup()

    assert result["totp_secret"] == fixed_secret
    # Same passphrase + same TOTP secret => same encryption key as setup device.
    expected_key = crypto.derive_encryption_key(passphrase, fixed_secret)
    assert result["encryption_key"] == expected_key


def test_join_device_existing_setup_wrong_passphrase_fails(monkeypatch):
    fixed_secret = pyotp.random_base32()
    correct_key = crypto._derive_passphrase_only_key("correct-passphrase")
    encrypted_totp = crypto.encrypt_data(fixed_secret.encode("utf-8"), correct_key)

    monkeypatch.setattr(crypto, "_prompt_passphrase", lambda: "wrong-passphrase")
    monkeypatch.setattr(crypto, "_fetch_secrets_from_github", lambda: encrypted_totp)

    with pytest.raises(ValueError):
        crypto.join_device_existing_setup()


def test_join_device_existing_setup_caches_session_after_full_flow(monkeypatch):
    fixed_secret = pyotp.random_base32()
    passphrase = "test-passphrase"
    passphrase_key = crypto._derive_passphrase_only_key(passphrase)
    encrypted_totp = crypto.encrypt_data(fixed_secret.encode("utf-8"), passphrase_key)

    monkeypatch.setattr(crypto, "_prompt_passphrase", lambda: passphrase)
    monkeypatch.setattr(crypto, "_fetch_secrets_from_github", lambda: encrypted_totp)
    monkeypatch.setattr(crypto, "display_qr_code", lambda uri: None)
    monkeypatch.setattr(crypto, "_prompt_totp_code", lambda: pyotp.TOTP(fixed_secret).now())

    crypto.join_device_existing_setup()

    assert crypto.SESSION_CACHE_PATH.exists()
    cached = crypto._load_cached_session()
    assert cached is not None
    assert cached["totp_secret"] == fixed_secret
    assert cached["encryption_key"] == crypto.derive_encryption_key(passphrase, fixed_secret)


def test_join_device_existing_setup_uses_cache_without_reprompting(monkeypatch):
    """Regression test for the "logs in 3 times in one session" friction:
    a still-valid cached session must short-circuit join_device_existing_setup()
    entirely - no passphrase prompt, no GitHub fetch, no QR/TOTP prompt."""
    key = crypto.derive_encryption_key("cached-passphrase", "JBSWY3DPEHPK3PXP")
    crypto._save_session_cache(key, "JBSWY3DPEHPK3PXP")

    def _fail(*args, **kwargs):
        raise AssertionError("should not prompt/fetch when a valid session is cached")

    monkeypatch.setattr(crypto, "_prompt_passphrase", _fail)
    monkeypatch.setattr(crypto, "_fetch_secrets_from_github", _fail)
    monkeypatch.setattr(crypto, "_prompt_totp_code", _fail)

    result = crypto.join_device_existing_setup()

    assert result == {"encryption_key": key, "totp_secret": "JBSWY3DPEHPK3PXP"}


def test_join_device_existing_setup_expired_cache_falls_through(monkeypatch):
    import json
    from datetime import datetime, timedelta, timezone

    crypto.SESSION_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    expired = datetime.now(timezone.utc) - timedelta(seconds=1)
    crypto.SESSION_CACHE_PATH.write_text(
        json.dumps({"encryption_key": "stale", "totp_secret": "stale", "expires_at": expired.isoformat()}),
        encoding="utf-8",
    )

    fixed_secret = pyotp.random_base32()
    passphrase = "test-passphrase"
    passphrase_key = crypto._derive_passphrase_only_key(passphrase)
    encrypted_totp = crypto.encrypt_data(fixed_secret.encode("utf-8"), passphrase_key)

    monkeypatch.setattr(crypto, "_prompt_passphrase", lambda: passphrase)
    monkeypatch.setattr(crypto, "_fetch_secrets_from_github", lambda: encrypted_totp)
    monkeypatch.setattr(crypto, "display_qr_code", lambda uri: None)
    monkeypatch.setattr(crypto, "_prompt_totp_code", lambda: pyotp.TOTP(fixed_secret).now())

    result = crypto.join_device_existing_setup()

    assert result["totp_secret"] == fixed_secret  # real flow ran, not the stale cache


def test_resolve_encryption_key_matches_join_device_flow(monkeypatch):
    """server.py's /sync must derive the exact same key join-device would."""
    fixed_secret = pyotp.random_base32()
    passphrase = "test-passphrase"
    passphrase_key = crypto._derive_passphrase_only_key(passphrase)
    encrypted_totp = crypto.encrypt_data(fixed_secret.encode("utf-8"), passphrase_key)

    monkeypatch.setattr(crypto, "_fetch_secrets_from_github", lambda: encrypted_totp)

    code = pyotp.TOTP(fixed_secret).now()
    key = crypto.resolve_encryption_key(passphrase, code)

    assert key == crypto.derive_encryption_key(passphrase, fixed_secret)


def test_resolve_encryption_key_wrong_passphrase_raises(monkeypatch):
    fixed_secret = pyotp.random_base32()
    correct_key = crypto._derive_passphrase_only_key("correct-passphrase")
    encrypted_totp = crypto.encrypt_data(fixed_secret.encode("utf-8"), correct_key)

    monkeypatch.setattr(crypto, "_fetch_secrets_from_github", lambda: encrypted_totp)

    with pytest.raises(ValueError):
        crypto.resolve_encryption_key("wrong-passphrase", "123456")


def test_resolve_encryption_key_wrong_totp_raises(monkeypatch):
    fixed_secret = pyotp.random_base32()
    passphrase = "test-passphrase"
    passphrase_key = crypto._derive_passphrase_only_key(passphrase)
    encrypted_totp = crypto.encrypt_data(fixed_secret.encode("utf-8"), passphrase_key)

    monkeypatch.setattr(crypto, "_fetch_secrets_from_github", lambda: encrypted_totp)

    with pytest.raises(ValueError):
        crypto.resolve_encryption_key(passphrase, "000000")


def test_resolve_encryption_key_unreachable_github_raises(monkeypatch):
    def raise_unreachable():
        raise RuntimeError("No git repository at that path")

    monkeypatch.setattr(crypto, "_fetch_secrets_from_github", raise_unreachable)

    with pytest.raises(ValueError):
        crypto.resolve_encryption_key("any-passphrase", "123456")


def test_join_device_existing_setup_rejects_bad_totp(monkeypatch):
    fixed_secret = pyotp.random_base32()
    passphrase = "test-passphrase"
    passphrase_key = crypto._derive_passphrase_only_key(passphrase)
    encrypted_totp = crypto.encrypt_data(fixed_secret.encode("utf-8"), passphrase_key)

    monkeypatch.setattr(crypto, "_prompt_passphrase", lambda: passphrase)
    monkeypatch.setattr(crypto, "_fetch_secrets_from_github", lambda: encrypted_totp)
    monkeypatch.setattr(crypto, "display_qr_code", lambda uri: None)
    monkeypatch.setattr(crypto, "_prompt_totp_code", lambda: "000000")

    with pytest.raises(ValueError):
        crypto.join_device_existing_setup()


def test_setup_and_join_produce_matching_keys(monkeypatch):
    """End-to-end: a device that sets up and a device that joins must derive
    the same encryption key, given the same passphrase."""
    fixed_secret = pyotp.random_base32()
    passphrase = "shared-passphrase"
    github_storage = {}

    monkeypatch.setattr(crypto, "generate_totp_secret", lambda: fixed_secret)
    monkeypatch.setattr(crypto, "display_qr_code", lambda uri: None)
    monkeypatch.setattr(crypto, "_prompt_passphrase", lambda: passphrase)
    monkeypatch.setattr(crypto, "_prompt_totp_code", lambda: pyotp.TOTP(fixed_secret).now())
    monkeypatch.setattr(crypto, "_push_secrets_to_github", lambda blob: github_storage.__setitem__("blob", blob))

    setup_result = crypto.setup_device_first_time()

    monkeypatch.setattr(crypto, "_fetch_secrets_from_github", lambda: github_storage["blob"])
    join_result = crypto.join_device_existing_setup()

    assert setup_result["encryption_key"] == join_result["encryption_key"]
    assert setup_result["totp_secret"] == join_result["totp_secret"]
