"""Tests for src/auth_ui.py.

_run_popup() must run on the calling (main) thread — a background-thread
version was tried first and hit real, reproducible Tcl crashes
("Tcl_AsyncDelete: async handler deleted by the wrong thread") on submit.
Most tests here mock _run_popup() itself rather than driving a real Tk
window with no human to click it (which would hang until the timeout).
The one test that does create a real, short-lived Tk root
(test_run_popup_times_out_and_raises) relies on AUTH_UI_TIMEOUT_SECONDS
to guarantee it can't hang, and is skipped if no display is available.
"""
import time

import pytest

from src import auth_ui


def test_auth_cancelled_is_an_exception_subclass():
    assert issubclass(auth_ui.AuthCancelled, Exception)


def test_auth_timed_out_is_an_exception_subclass():
    assert issubclass(auth_ui.AuthTimedOut, Exception)


def test_prompt_passphrase_and_totp_raises_cancelled_when_queue_empty(monkeypatch):
    """If the popup is closed without submitting (result_queue stays
    empty), the caller must get AuthCancelled, not hang or return None."""

    def fake_run_popup(build_fn):
        raise auth_ui.AuthCancelled("closed without submitting")

    monkeypatch.setattr(auth_ui, "_run_popup", fake_run_popup)

    with pytest.raises(auth_ui.AuthCancelled):
        auth_ui.prompt_passphrase_and_totp()


def test_prompt_totp_only_raises_cancelled_when_queue_empty(monkeypatch):
    def fake_run_popup(build_fn):
        raise auth_ui.AuthCancelled("closed without submitting")

    monkeypatch.setattr(auth_ui, "_run_popup", fake_run_popup)

    with pytest.raises(auth_ui.AuthCancelled):
        auth_ui.prompt_totp_only()


def test_prompt_passphrase_and_totp_returns_dict_from_run_popup(monkeypatch):
    monkeypatch.setattr(
        auth_ui, "_run_popup", lambda build_fn: {"passphrase": "hunter2", "totp_code": "123456"}
    )
    result = auth_ui.prompt_passphrase_and_totp()
    assert result == {"passphrase": "hunter2", "totp_code": "123456"}


def test_prompt_totp_only_extracts_code_from_run_popup_result(monkeypatch):
    monkeypatch.setattr(auth_ui, "_run_popup", lambda build_fn: {"totp_code": "654321"})
    assert auth_ui.prompt_totp_only() == "654321"


def test_run_popup_times_out_and_raises(monkeypatch):
    """A build_fn that never resolves `result` or calls root.quit() itself
    (simulating an unresponsive/hung window) must cause _run_popup() to
    tear itself down via its own internal timer and raise AuthTimedOut,
    rather than block the calling thread forever."""
    if not _tk_display_available():
        pytest.skip("no display available for a real Tk root in this environment")

    monkeypatch.setattr(auth_ui, "AUTH_UI_TIMEOUT_SECONDS", 0.2)

    def build_fn(root, result):
        pass  # never populates result or calls root.quit()

    start = time.monotonic()
    with pytest.raises(auth_ui.AuthTimedOut):
        auth_ui._run_popup(build_fn)
    elapsed = time.monotonic() - start
    assert elapsed < 5  # bounded by AUTH_UI_TIMEOUT_SECONDS, not hanging indefinitely


def test_run_popup_returns_result_on_submit(monkeypatch):
    """A build_fn that populates `result` and calls root.quit() (the
    documented submit contract) must have _run_popup() return that dict."""
    if not _tk_display_available():
        pytest.skip("no display available for a real Tk root in this environment")

    monkeypatch.setattr(auth_ui, "AUTH_UI_TIMEOUT_SECONDS", 5)

    def build_fn(root, result):
        # Simulate an immediate "submit" without waiting for a real click -
        # schedule it via after() so it runs once mainloop() has started,
        # exactly like a real button/Enter-key callback would.
        def do_submit():
            result.update({"passphrase": "hunter2", "totp_code": "123456"})
            root.quit()

        root.after(10, do_submit)

    result = auth_ui._run_popup(build_fn)
    assert result == {"passphrase": "hunter2", "totp_code": "123456"}


def test_run_popup_raises_cancelled_on_empty_submit(monkeypatch):
    """A build_fn that calls root.quit() without populating `result`
    (the documented cancel contract) must raise AuthCancelled."""
    if not _tk_display_available():
        pytest.skip("no display available for a real Tk root in this environment")

    monkeypatch.setattr(auth_ui, "AUTH_UI_TIMEOUT_SECONDS", 5)

    def build_fn(root, result):
        root.after(10, root.quit)

    with pytest.raises(auth_ui.AuthCancelled):
        auth_ui._run_popup(build_fn)


def _tk_display_available() -> bool:
    """A bare tk.Tk() isn't a sufficient check on its own - found via a
    real CI failure (2026-08-07): GitHub's windows-latest runner image
    can construct a root Tk window fine (no display/DISPLAY-env problem)
    while its bundled Tcl/Tk library files are still incomplete
    (tk.tcl's entry.tcl was missing), which only surfaces once a real
    widget - not just the bare root - is built. _run_popup() always
    builds an Entry widget, so this check must too, or it reports
    "display available" for an environment where the real popup path
    still crashes with TclError."""
    try:
        import tkinter as tk

        root = tk.Tk()
        try:
            tk.Entry(root)
        finally:
            root.destroy()
        return True
    except Exception:
        return False
