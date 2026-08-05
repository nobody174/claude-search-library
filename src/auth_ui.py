#
# Claude Search Library
# Author:  nobody174
# Repo:    https://github.com/nobody174/claude-search-library
# Patreon: https://www.patreon.com/c/Nobody174
# License: MIT
# "It's never too late to give up!"
#

"""Local GUI credential prompt for Claude Search Library.

Replaces getpass.getpass()/input() for passphrase + TOTP entry with a
small local Tkinter popup, dark-themed to match the web UI. Exists purely
to solve a real usability gap: getpass()/input() only work in a genuine
interactive terminal, so any automated caller (an agent driving the CLI,
a scheduled task, a non-interactive shell) has no way to supply these
values at all short of a plaintext env var workaround.

Nothing entered here is ever written to disk — values are returned to the
caller in memory only, exactly like the terminal prompts they replace.
This module has no import-time dependency on crypto.py; crypto.py imports
it lazily and only when the GUI path is actually selected, so environments
without a display (headless servers, SSH sessions) are unaffected as long
as they keep using the terminal prompts.

IMPORTANT: every popup here runs on the calling thread, not a background
thread. An earlier version ran Tk in a spawned thread (to avoid blocking
callers that might have their own event loop) and hit real, reproducible
Tcl-level crashes ("Tcl_AsyncDelete: async handler deleted by the wrong
thread") on submit — Tcl/Tk is not reliably safe to drive from a
non-main thread on this platform. Tkinter is meant to own the thread it
runs on; every caller of this module (CLI commands, the sync daemon) is
expected to call these functions directly from its own main thread.
"""
from __future__ import annotations

from typing import Optional

BG = "#0f1115"
BG_PANEL = "#171a21"
BG_INPUT = "#1f232c"
FG = "#e6e8eb"
FG_MUTED = "#8b93a1"
ACCENT = "#5b8cff"
BORDER = "#2a2f3a"
ERROR = "#ff6b6b"

# Hard ceiling on how long a popup can block the calling process before it
# tears itself down automatically. Defense in depth: the primary safeguard
# is that automated/test code must never reach this module at all (see
# crypto.USE_GUI_AUTH and tests/test_crypto.py's autouse fixture), but a
# real popup did once escape into an automated context and hang
# indefinitely with no way to recover short of killing the process.
AUTH_UI_TIMEOUT_SECONDS = 180


class AuthCancelled(Exception):
    """Raised when the user closes the popup without submitting."""


class AuthTimedOut(Exception):
    """Raised when a popup receives no response within AUTH_UI_TIMEOUT_SECONDS."""


def _run_popup(build_fn) -> dict:
    """Run a Tkinter popup built by `build_fn` on the current thread.

    `build_fn(root, result)` should call `result.update(...)` and
    `root.quit()` on submit, or just `root.quit()` on cancel (leaving
    `result` empty). Must be called from the same thread the caller
    intends to block on — do not call this from inside another Tk
    mainloop or from a non-main thread.
    """
    import tkinter as tk

    root = tk.Tk()
    result: dict = {}
    timed_out = {"flag": False}

    def _on_timeout():
        timed_out["flag"] = True
        root.quit()

    timer_id = root.after(int(AUTH_UI_TIMEOUT_SECONDS * 1000), _on_timeout)

    try:
        build_fn(root, result)
        root.mainloop()
    finally:
        try:
            root.after_cancel(timer_id)
        except Exception:
            pass
        try:
            root.destroy()
        except tk.TclError:
            pass

    if timed_out["flag"]:
        raise AuthTimedOut(
            f"No response to the authentication prompt within {AUTH_UI_TIMEOUT_SECONDS}s"
        )
    if not result:
        raise AuthCancelled("Authentication prompt was closed without submitting")
    return result


def _style_entry(entry, show: Optional[str] = None) -> None:
    entry.configure(
        bg=BG_INPUT, fg=FG, insertbackground=FG,
        relief="flat", highlightthickness=1,
        highlightbackground=BORDER, highlightcolor=ACCENT,
        font=("Segoe UI", 12),
    )
    if show is not None:
        entry.configure(show=show)


def _center_window(root, width: int, height: int) -> None:
    root.update_idletasks()
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    x = (screen_w - width) // 2
    y = (screen_h - height) // 2
    root.geometry(f"{width}x{height}+{x}+{y}")


def prompt_passphrase_and_totp(title: str = "Unlock Claude Search Library") -> dict:
    """Show a dark popup asking for the master passphrase and a TOTP code.

    Returns {"passphrase": str, "totp_code": str}. Raises AuthCancelled if
    the window is closed without submitting.
    """

    def build(root, result):
        import tkinter as tk
        from tkinter import font as tkfont

        root.title(title)
        root.configure(bg=BG)
        root.resizable(False, False)
        _center_window(root, 380, 320)
        root.attributes("-topmost", True)

        heading_font = tkfont.Font(family="Segoe UI", size=15, weight="bold")
        label_font = tkfont.Font(family="Segoe UI", size=10)

        panel = tk.Frame(root, bg=BG_PANEL, highlightbackground=BORDER, highlightthickness=1)
        panel.pack(fill="both", expand=True, padx=16, pady=16)

        tk.Label(panel, text=title, bg=BG_PANEL, fg=FG, font=heading_font).pack(
            anchor="w", padx=20, pady=(20, 4)
        )
        tk.Label(
            panel,
            text="Nothing you enter here is stored on disk.",
            bg=BG_PANEL, fg=FG_MUTED, font=label_font,
        ).pack(anchor="w", padx=20, pady=(0, 16))

        tk.Label(panel, text="Master passphrase", bg=BG_PANEL, fg=FG, font=label_font).pack(
            anchor="w", padx=20
        )
        passphrase_entry = tk.Entry(panel)
        _style_entry(passphrase_entry, show="•")
        passphrase_entry.pack(fill="x", padx=20, pady=(4, 16), ipady=6)

        tk.Label(panel, text="Authenticator code", bg=BG_PANEL, fg=FG, font=label_font).pack(
            anchor="w", padx=20
        )
        totp_entry = tk.Entry(panel)
        _style_entry(totp_entry)
        totp_entry.pack(fill="x", padx=20, pady=(4, 8), ipady=6)

        error_label = tk.Label(panel, text="", bg=BG_PANEL, fg=ERROR, font=label_font)
        error_label.pack(anchor="w", padx=20, pady=(0, 8))

        def submit(_event=None):
            passphrase = passphrase_entry.get()
            totp_code = totp_entry.get().strip()
            if not passphrase:
                error_label.configure(text="Passphrase is required")
                return
            if not totp_code.isdigit() or len(totp_code) != 6:
                error_label.configure(text="Enter the 6-digit code from your app")
                return
            result.update({"passphrase": passphrase, "totp_code": totp_code})
            root.quit()

        def cancel(_event=None):
            root.quit()

        button_row = tk.Frame(panel, bg=BG_PANEL)
        button_row.pack(fill="x", padx=20, pady=(8, 20))

        cancel_btn = tk.Button(
            button_row, text="Cancel", command=cancel,
            bg=BG_PANEL, fg=FG_MUTED, activebackground=BG_PANEL, activeforeground=FG,
            relief="flat", font=label_font, bd=0, cursor="hand2",
        )
        cancel_btn.pack(side="right", padx=(8, 0))

        submit_btn = tk.Button(
            button_row, text="Unlock", command=submit,
            bg=ACCENT, fg="#ffffff", activebackground="#4a78e0", activeforeground="#ffffff",
            relief="flat", font=("Segoe UI", 10, "bold"), bd=0, padx=16, pady=6, cursor="hand2",
        )
        submit_btn.pack(side="right")

        root.bind("<Return>", submit)
        root.bind("<Escape>", cancel)
        root.protocol("WM_DELETE_WINDOW", cancel)
        passphrase_entry.focus_set()

    return _run_popup(build)


def prompt_passphrase_only(title: str = "Enter Master Passphrase") -> str:
    """Show a dark popup asking only for the master passphrase.

    Used where the TOTP secret isn't known yet (e.g. joining an existing
    device, where the passphrase must decrypt the TOTP secret before its
    QR code can even be shown) so a combined passphrase+TOTP popup can't
    be used. Returns the entered passphrase. Raises AuthCancelled if the
    window is closed without submitting.
    """

    def build(root, result):
        import tkinter as tk
        from tkinter import font as tkfont

        root.title(title)
        root.configure(bg=BG)
        root.resizable(False, False)
        _center_window(root, 340, 200)
        root.attributes("-topmost", True)

        heading_font = tkfont.Font(family="Segoe UI", size=15, weight="bold")
        label_font = tkfont.Font(family="Segoe UI", size=10)

        panel = tk.Frame(root, bg=BG_PANEL, highlightbackground=BORDER, highlightthickness=1)
        panel.pack(fill="both", expand=True, padx=16, pady=16)

        tk.Label(panel, text=title, bg=BG_PANEL, fg=FG, font=heading_font).pack(
            anchor="w", padx=20, pady=(20, 16)
        )

        tk.Label(panel, text="Master passphrase", bg=BG_PANEL, fg=FG, font=label_font).pack(
            anchor="w", padx=20
        )
        passphrase_entry = tk.Entry(panel)
        _style_entry(passphrase_entry, show="•")
        passphrase_entry.pack(fill="x", padx=20, pady=(4, 8), ipady=6)

        error_label = tk.Label(panel, text="", bg=BG_PANEL, fg=ERROR, font=label_font)
        error_label.pack(anchor="w", padx=20)

        def submit(_event=None):
            passphrase = passphrase_entry.get()
            if not passphrase:
                error_label.configure(text="Passphrase is required")
                return
            result.update({"passphrase": passphrase})
            root.quit()

        def cancel(_event=None):
            root.quit()

        button_row = tk.Frame(panel, bg=BG_PANEL)
        button_row.pack(fill="x", padx=20, pady=(8, 20))

        tk.Button(
            button_row, text="Cancel", command=cancel,
            bg=BG_PANEL, fg=FG_MUTED, activebackground=BG_PANEL, activeforeground=FG,
            relief="flat", font=label_font, bd=0, cursor="hand2",
        ).pack(side="right", padx=(8, 0))

        tk.Button(
            button_row, text="Continue", command=submit,
            bg=ACCENT, fg="#ffffff", activebackground="#4a78e0", activeforeground="#ffffff",
            relief="flat", font=("Segoe UI", 10, "bold"), bd=0, padx=16, pady=6, cursor="hand2",
        ).pack(side="right")

        root.bind("<Return>", submit)
        root.bind("<Escape>", cancel)
        root.protocol("WM_DELETE_WINDOW", cancel)
        passphrase_entry.focus_set()

    result = _run_popup(build)
    return result["passphrase"]


def prompt_totp_only(title: str = "Confirm sync") -> str:
    """Show a dark popup asking only for a live TOTP code.

    Used where the passphrase has already been supplied out-of-band (e.g.
    the daemon already holds a derived key) but a fresh liveness check is
    still wanted. Returns the entered code. Raises AuthCancelled if the
    window is closed without submitting.
    """

    def build(root, result):
        import tkinter as tk
        from tkinter import font as tkfont

        root.title(title)
        root.configure(bg=BG)
        root.resizable(False, False)
        _center_window(root, 340, 200)
        root.attributes("-topmost", True)

        heading_font = tkfont.Font(family="Segoe UI", size=15, weight="bold")
        label_font = tkfont.Font(family="Segoe UI", size=10)

        panel = tk.Frame(root, bg=BG_PANEL, highlightbackground=BORDER, highlightthickness=1)
        panel.pack(fill="both", expand=True, padx=16, pady=16)

        tk.Label(panel, text=title, bg=BG_PANEL, fg=FG, font=heading_font).pack(
            anchor="w", padx=20, pady=(20, 16)
        )

        tk.Label(panel, text="Authenticator code", bg=BG_PANEL, fg=FG, font=label_font).pack(
            anchor="w", padx=20
        )
        totp_entry = tk.Entry(panel)
        _style_entry(totp_entry)
        totp_entry.pack(fill="x", padx=20, pady=(4, 8), ipady=6)

        error_label = tk.Label(panel, text="", bg=BG_PANEL, fg=ERROR, font=label_font)
        error_label.pack(anchor="w", padx=20)

        def submit(_event=None):
            code = totp_entry.get().strip()
            if not code.isdigit() or len(code) != 6:
                error_label.configure(text="Enter the 6-digit code from your app")
                return
            result.update({"totp_code": code})
            root.quit()

        def cancel(_event=None):
            root.quit()

        button_row = tk.Frame(panel, bg=BG_PANEL)
        button_row.pack(fill="x", padx=20, pady=(8, 20))

        tk.Button(
            button_row, text="Cancel", command=cancel,
            bg=BG_PANEL, fg=FG_MUTED, activebackground=BG_PANEL, activeforeground=FG,
            relief="flat", font=label_font, bd=0, cursor="hand2",
        ).pack(side="right", padx=(8, 0))

        tk.Button(
            button_row, text="Confirm", command=submit,
            bg=ACCENT, fg="#ffffff", activebackground="#4a78e0", activeforeground="#ffffff",
            relief="flat", font=("Segoe UI", 10, "bold"), bd=0, padx=16, pady=6, cursor="hand2",
        ).pack(side="right")

        root.bind("<Return>", submit)
        root.bind("<Escape>", cancel)
        root.protocol("WM_DELETE_WINDOW", cancel)
        totp_entry.focus_set()

    result = _run_popup(build)
    return result["totp_code"]

# Built with assistance from Claude Code by Anthropic.
