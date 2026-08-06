#
# Claude Search Library
# Author:  nobody174
# Repo:    https://github.com/nobody174/claude-search-library
# Patreon: https://www.patreon.com/c/Nobody174
# License: MIT
# "It's never too late to give up!"
#

"""Android device bridge for Claude Search Library.

Drives a connected Android phone over ADB to extract Claude conversation
content from its own screen - not via claude.ai's API, not via any
export flow, just reading what's visibly on screen through Android's
standard accessibility tree (the same mechanism screen readers use).
Never touches claude.ai's servers directly, so none of the ToS concerns
that ruled out automating iOS/API access apply here (see CHANGELOG.md's
2026-08-06 iOS investigation and ROADMAP.md's Android+iOS bridge entry).

Real discovery this exploits: claude.ai conversations are one
cloud-synced account across every mobile client - a conversation
started on iPhone appears on Android within seconds under the same
account (verified live, 2026-08-06). So this collector reaches
iPhone-originated conversations too, as a side effect of the account
being shared, without ever touching the iPhone.

Split into two halves on purpose, since there's no way to unit-test
against real hardware in CI:

- Pure parsing functions (parse_conversation_list, parse_message_bubbles,
  is_scroll_stalled, messages_to_raw_export) operate on XML strings/dicts
  only, no subprocess/network - these have real fixture-based test
  coverage (tests/test_android_bridge.py, fixtures in
  tests/fixtures/android/).
- Device-driving functions (connect_device, launch_claude_app, dump_ui,
  tap_bounds, scroll_down, ...) shell out to `adb` - not unit-tested,
  verified instead via a real device during development (see
  CHANGELOG.md), same as collect_from_claude_desktop()'s IndexedDB path
  was verified against a real local store rather than a hand-built
  fixture.

Role attribution (user vs. assistant) is NOT inferrable from any
resource-id/content-desc label - the Claude Android app sets neither.
Confirmed empirically instead (2026-08-06, against a real dump): a
message's *bubble container* signals its role by horizontal offset -
the user's message sits in a container indented from the screen's left
edge (e.g. bounds starting at x=95 on a 1080px-wide screen), while
Claude's response sits in a full-width container starting at x=0. This
is structural (container bounds), not a fragile raw-text-position
heuristic - see _ROLE_INDENT_THRESHOLD_FRACTION below.
"""
from __future__ import annotations

import json
import logging
import platform
import re
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Bare "adb" resolving via PATH can't be relied on - confirmed during
# development that even with the Android SDK installed and adb working
# fine from a normal terminal, a Python subprocess call to bare "adb"
# raised FileNotFoundError (PATH as seen by the Python process differed
# from the interactive shell's). Resolved once, lazily, and cached -
# checks PATH first (shutil.which, so a real PATH entry is honored if
# present), then the standard per-platform Android SDK install location
# as a fallback, matching where this project's own manual verification
# found adb.exe (see CHANGELOG.md's 2026-08-06 Android entries).
_adb_path: Optional[str] = None


def _resolve_adb_path() -> str:
    global _adb_path
    if _adb_path is not None:
        return _adb_path

    found = shutil.which("adb")
    if found:
        _adb_path = found
        return _adb_path

    if platform.system().lower() == "windows":
        candidate = Path.home() / "AppData" / "Local" / "Android" / "Sdk" / "platform-tools" / "adb.exe"
    else:
        candidate = Path.home() / "Android" / "Sdk" / "platform-tools" / "adb"

    if candidate.exists():
        _adb_path = str(candidate)
        return _adb_path

    # Deliberately includes the local filesystem path in the message (R-6,
    # Project Reviewer 2026-08-06): this exception is CLI-only, surfaces
    # on the user's own machine, and is never logged to a file, synced, or
    # committed anywhere - the path is the whole point (tells the user
    # exactly where to look), so redacting it here would only make the
    # error less actionable for no real exposure reduction.
    raise AndroidNotConnectedError(
        "Could not find adb (Android SDK platform-tools) on PATH or at the "
        f"default SDK location ({candidate}). Install Android SDK "
        "platform-tools and either add it to PATH or install it at the "
        "default location."
    )


DEVICE_STATE_PATH = Path.home() / ".claude-search-library" / "data" / "android_device.json"

# A message-group container starting further right than this fraction of
# the screen width is treated as the user's own message (indented/offset
# bubble); anything starting closer to the left edge (0) is Claude's
# response (full-width text block, no bubble). Derived from one real
# observed sample (95px indent on a 1080px screen = ~8.8%) - set well
# below that so it tolerates different screen sizes/densities without
# tolerating so much drift it misclassifies a genuinely full-width
# assistant block. Revisit with more real samples if this misclassifies
# in practice.
_ROLE_INDENT_THRESHOLD_FRACTION = 0.04

# Minimum width (as a fraction of screen width) for a container to be
# considered a message-group wrapper rather than a button/icon/chrome
# element. Derived from the same real sample as the threshold above
# (400px on a 1080px screen = ~37%) - was previously a hardcoded pixel
# value that silently assumed a 1080px-wide screen; expressed as a
# fraction here so it scales correctly on other real device widths.
_MIN_MESSAGE_CONTAINER_WIDTH_FRACTION = 400 / 1080


class AndroidNotConnectedError(RuntimeError):
    """No Android device is reachable - connect_device() failed, or no
    address (current or last-known) was available to try."""


class AndroidUIElementNotFoundError(RuntimeError):
    """An expected on-screen element (by text or role) wasn't present in
    the latest UI dump. Raised loudly instead of guessing a tap target -
    matches this project's existing philosophy of failing loudly on a
    genuine mismatch rather than silently misparsing (see
    SchemaTooNewError in src/storage.py)."""


class AndroidDumpFailedError(AndroidUIElementNotFoundError):
    """dump_ui() exhausted its retries without ever getting a dump
    containing a real <hierarchy> root - the returned text is the last
    failed attempt's stdout, not a genuine (if unexpected) screen state.
    Distinct from AndroidUIElementNotFoundError's normal case (a real
    dump that just doesn't contain the expected element) so callers and
    error messages can tell "the device stopped responding" apart from
    "the app is showing something we didn't expect"."""


# --- Pure parsing functions (unit-testable, no subprocess/network) -----

def parse_conversation_list(xml: str) -> list[dict]:
    """Extract every conversation title + its tap bounds from a sidebar
    UI dump.

    Returns [{"title": str, "bounds": str}, ...] in the order they
    appear in the dump (top to bottom on screen). `bounds` is the raw
    "[x1,y1][x2,y2]" string as it appears in the XML, passed straight
    through to tap_bounds() later - re-read fresh each time rather than
    cached, since the sidebar can scroll between enumeration and tap.
    """
    conversations = []
    for m in re.finditer(
        r'<node[^>]*text="([^"]+)"[^>]*class="android\.widget\.TextView"[^>]*bounds="(\[\d+,\d+\]\[\d+,\d+\])"',
        xml,
    ):
        title, bounds = m.group(1), m.group(2)
        if title in _SIDEBAR_CHROME_LABELS:
            continue
        conversations.append({"title": _unescape_xml_text(title), "bounds": bounds})
    return conversations


# Sidebar section headers/nav items that match the same TextView pattern
# as real conversation titles but aren't conversations - excluded by
# exact match rather than a length/heuristic filter, since a short real
# conversation title is legitimate and shouldn't be dropped.
_SIDEBAR_CHROME_LABELS = frozenset({
    "Claude", "Chats", "Projects", "Artifacts", "Code", "Dispatch",
    "Starred", "Recents", "New chat",
})


def parse_message_bubbles(xml: str, screen_width: int) -> list[dict]:
    """Extract every message's text + inferred role from a conversation
    UI dump.

    Returns [{"role": "user"|"assistant", "text": str}, ...] in the
    order they appear top-to-bottom on screen. Groups text nodes by
    their enclosing message-container bounds (a container may hold
    several TextView children - e.g. Claude's reply is often several
    paragraph nodes inside one container) and assigns role from that
    container's left-edge offset - see _ROLE_INDENT_THRESHOLD_FRACTION.

    screen_width must come from the same dump (the outermost node's
    bounds, e.g. [0,0][1080,2123] -> 1080) rather than being hardcoded,
    since real devices vary.
    """
    threshold_x = screen_width * _ROLE_INDENT_THRESHOLD_FRACTION
    groups = _group_message_nodes_by_container(xml, screen_width)
    bubbles = []
    for container_x1, texts in groups:
        if not texts:
            continue
        role = "user" if container_x1 > threshold_x else "assistant"
        bubbles.append({"role": role, "text": "\n\n".join(texts)})
    return bubbles


_BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


def _group_message_nodes_by_container(xml: str, screen_width: int) -> list[tuple[int, list[str]]]:
    """Walk the dump's real element tree (not regex - nested XML needs
    a real parser to group text correctly by ancestor container) for the
    shallowest View containers wide enough to be a message-group wrapper
    (not a button/icon/chrome element), and collect the message text
    nested anywhere inside each one. Returns
    [(container_left_x, [text, ...]), ...] in document order, skipping
    known non-message text (UI chrome, disclaimers).

    "Shallowest wide container" (not every wide container, since a
    message group's own descendants are often also wide) is what keeps
    each real message group as exactly one entry instead of being
    re-matched at every nesting level inside itself.
    """
    root = ET.fromstring(xml)
    groups: list[tuple[int, list[str]]] = []
    min_width = int(screen_width * _MIN_MESSAGE_CONTAINER_WIDTH_FRACTION)
    _walk_for_message_containers(root, groups, min_width=min_width)
    return groups


def _walk_for_message_containers(node: ET.Element, groups: list[tuple[int, list[str]]], min_width: int) -> None:
    """Record the SMALLEST (most specific, deepest) wide-enough View
    containers that hold real message text - not the first/outermost
    one encountered. A real dump nests several qualifying wide View
    ancestors around each message group (the scrollable list itself is
    also "wide"), so this must recurse into children FIRST and only
    fall back to treating the current node as one message group if none
    of its descendants already claimed a group of their own - otherwise
    every message on screen collapses into one giant top-level group.
    """
    before = len(groups)
    for child in node:
        _walk_for_message_containers(child, groups, min_width)
    if len(groups) > before:
        return  # a descendant already claimed a message group in here

    bounds = node.get("bounds", "")
    m = _BOUNDS_RE.match(bounds)
    is_wide_view = (
        node.get("class") == "android.view.View"
        and m is not None
        and (int(m.group(3)) - int(m.group(1))) >= min_width
    )
    if is_wide_view:
        texts = _collect_message_texts(node)
        if texts:
            groups.append((int(m.group(1)), texts))


def _collect_message_texts(node: ET.Element) -> list[str]:
    """All real TextView text found anywhere under this node, in
    document order, excluding known non-message chrome."""
    texts = []
    for el in node.iter():
        if el.get("class") == "android.widget.TextView":
            text = el.get("text", "")  # ElementTree already decodes XML entities
            if len(text) >= 15 and text not in _MESSAGE_CHROME_LABELS:
                texts.append(text)
    return texts


# Non-message text that can appear inside a wide container (disclaimers,
# input placeholders) - excluded by exact/prefix match, not a length
# heuristic, since real short messages are legitimate.
_MESSAGE_CHROME_LABELS = frozenset({
    "Claude is AI and can make mistakes.",
    "Please double-check responses.",
    "Reply to Claude…",
})


def is_scroll_stalled(prev_bubbles: list[dict], curr_bubbles: list[dict]) -> bool:
    """True if a scroll step produced no new message content.

    Compares extracted message *text*, not raw XML - raw XML dumps
    differ trivially between identical-looking screens (timestamps,
    sub-pixel scroll position) even when no new content actually
    loaded, which would cause false "still scrolling" positives if
    compared directly.
    """
    prev_texts = {b["text"] for b in prev_bubbles}
    curr_texts = {b["text"] for b in curr_bubbles}
    return curr_texts <= prev_texts


def merge_scroll_pages(pages: list[list[dict]]) -> list[dict]:
    """Merge message-bubble lists from successive scroll steps into one
    deduplicated, ordered transcript.

    Each scroll step's dump overlaps the previous one (whatever stayed
    on screen). Dedup by (role, text) while preserving first-seen order
    across all pages - later pages extend the transcript rather than
    reordering earlier messages, since scrolling only ever reveals
    earlier-in-conversation content pushed further down each dump.
    """
    seen = set()
    merged: list[dict] = []
    for page in pages:
        for bubble in page:
            key = (bubble["role"], bubble["text"])
            if key in seen:
                continue
            seen.add(key)
            merged.append(bubble)
    return merged


def messages_to_raw_export(title: str, bubbles: list[dict]) -> dict:
    """Convert an extracted, ordered bubble list into the raw-export
    shape normalize_session() expects (see src/collector.py).

    No real timestamps are available from the accessibility tree (the
    UI doesn't display per-message times in the dumped text) - messages
    get an empty timestamp, same convention as other collectors when a
    precise time isn't recoverable; normalize_session() already falls
    back to created_at/updated_at at the session level in that case.
    """
    return {
        "id": None,  # normalize_session() derives an id from a content hash when raw has none
        "title": title,
        "messages": [{"role": b["role"], "content": b["text"]} for b in bubbles],
    }


def _unescape_xml_text(text: str) -> str:
    return (
        text.replace("&#10;", "\n")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&apos;", "'")
    )


def _screen_width_from_dump(xml: str) -> int:
    m = re.search(r'bounds="\[0,0\]\[(\d+),\d+\]"', xml)
    if not m:
        raise AndroidUIElementNotFoundError("Could not find a full-screen root node to read screen width from")
    return int(m.group(1))


def _screen_height_from_dump(xml: str) -> int:
    m = re.search(r'bounds="\[0,0\]\[\d+,(\d+)\]"', xml)
    if not m:
        raise AndroidUIElementNotFoundError("Could not find a full-screen root node to read screen height from")
    return int(m.group(1))


# --- Device-driving functions (real ADB, not unit-tested) --------------

def _run_adb(args: list[str], device: Optional[str] = None, timeout: float = 15.0) -> subprocess.CompletedProcess:
    cmd = [_resolve_adb_path()]
    if device:
        cmd += ["-s", device]
    cmd += args
    # encoding="utf-8" explicitly, not text=True's platform default - a
    # real conversation's XML dump routinely contains non-ASCII text
    # (em-dashes, accented characters), and Windows' default console
    # encoding (cp1252) can't decode adb's UTF-8 stdout, raising
    # UnicodeDecodeError deep inside subprocess's reader thread rather
    # than a clean, catchable error at the call site.
    try:
        return subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise AndroidNotConnectedError(
            f"adb command timed out after {timeout}s: {' '.join(args)} - device may have "
            "gone unreachable over WiFi mid-run (see connect_device()'s docstring for "
            "reconnecting)."
        ) from e


def connect_device(address: Optional[str] = None) -> str:
    """Connect to an Android device over ADB WiFi and return its serial.

    address defaults to the last-known-working address persisted by
    `cli.py android-connect` (see DEVICE_STATE_PATH) - explicit reconnect
    step rather than auto-discovery, matching this project's existing
    pattern of an explicit setup step before automated collection (2FA
    setup is separate from sync, same idea here). Raises
    AndroidNotConnectedError with the exact command to run manually if
    no address is known or the connection fails.
    """
    if address is None:
        address = _load_last_known_address()
    if address is None:
        raise AndroidNotConnectedError(
            "No Android device address known. Run: cli.py android-connect <phone-ip>:<port> "
            "(find this on the phone under Settings -> Developer options -> Wireless debugging)"
        )

    result = _run_adb(["connect", address], timeout=10.0)
    if "connected" not in result.stdout.lower():
        raise AndroidNotConnectedError(
            f"adb connect {address} failed: {result.stdout.strip() or result.stderr.strip()}"
        )

    _save_last_known_address(address)
    return address


def _load_last_known_address() -> Optional[str]:
    if not DEVICE_STATE_PATH.exists():
        return None
    try:
        return json.loads(DEVICE_STATE_PATH.read_text(encoding="utf-8")).get("address")
    except (json.JSONDecodeError, OSError):
        return None


def _save_last_known_address(address: str) -> None:
    DEVICE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEVICE_STATE_PATH.write_text(json.dumps({"address": address}), encoding="utf-8")


def launch_claude_app(device: str) -> None:
    _run_adb(["shell", "am", "force-stop", "com.anthropic.claude"], device=device)
    time.sleep(1)
    _run_adb(
        ["shell", "monkey", "-p", "com.anthropic.claude", "-c", "android.intent.category.LAUNCHER", "1"],
        device=device,
    )
    time.sleep(4)  # fixed sleep, not poll-until-ready: launch time is fairly consistent in practice (verified manually)


def dump_ui(device: str, retries: int = 2) -> str:
    """Dump the current screen's accessibility tree and return the raw
    XML text. Uses a fixed remote/local filename (not unique per call) -
    each dump fully overwrites the last, which is fine since nothing
    reads the previous dump concurrently.

    Retries once (real, observed failure mode during development, not
    hypothetical): `uiautomator dump` can genuinely return an empty or
    truncated file if the screen is mid-transition/animating when it
    runs, since it isn't itself aware of in-flight UI changes. A dump
    missing even the root `<hierarchy>` node isn't a real screen state
    to parse - it's a transient capture failure, worth one retry before
    surfacing to the caller as real content.

    Raises AndroidDumpFailedError (not a silent empty/failed string) if
    every attempt fails - previously this returned the last failed
    attempt's stdout as if it were real content, so a downstream parse
    error would misleadingly look like "the screen doesn't match what we
    expected" instead of "the dump itself never worked"."""
    result = None
    for attempt in range(retries + 1):
        _run_adb(["shell", "uiautomator", "dump", "/sdcard/csl_dump.xml"], device=device)
        result = _run_adb(["shell", "cat", "/sdcard/csl_dump.xml"], device=device)
        if "<hierarchy" in result.stdout:
            return result.stdout
        if attempt < retries:
            logger.info("uiautomator dump returned no <hierarchy> (attempt %d/%d) - retrying", attempt + 1, retries)
            time.sleep(1)
    raise AndroidDumpFailedError(
        f"uiautomator dump failed to produce a valid <hierarchy> after {retries + 1} attempt(s); "
        f"last output: {result.stdout[:200]!r}"
    )


def tap_bounds(device: str, bounds: str) -> None:
    """Tap the center of a "[x1,y1][x2,y2]" bounds string, as read
    directly from a fresh dump_ui() - never a hardcoded coordinate, so
    taps stay correct across screen sizes/UI shifts (see module
    docstring)."""
    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
    if not m:
        raise AndroidUIElementNotFoundError(f"Malformed bounds string: {bounds!r}")
    x1, y1, x2, y2 = (int(g) for g in m.groups())
    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
    _run_adb(["shell", "input", "tap", str(cx), str(cy)], device=device)
    time.sleep(1)


def scroll_up_conversation(device: str, screen_height: int) -> None:
    """Swipe to reveal earlier messages (scroll up through history)."""
    x = 540
    y_start = int(screen_height * 0.8)
    y_end = int(screen_height * 0.25)
    _run_adb(["shell", "input", "swipe", str(x), str(y_start), str(x), str(y_end), "300"], device=device)
    time.sleep(1)


def navigate_back(device: str) -> None:
    _run_adb(["shell", "input", "keyevent", "4"], device=device)
    time.sleep(1)


def scroll_sidebar_to_top(device: str, max_steps: int = 30) -> None:
    """Swipe the sidebar downward (opposite direction of the reading
    scroll used elsewhere) until the visible conversation titles stop
    changing - i.e. reached the top of the list. Real bug this guards
    against: enumerate_conversations() always leaves the sidebar however
    it was last scrolled when it returns, so a second call (e.g. a
    second collection run in the same session) would otherwise start
    collecting from the middle of the list and silently miss the top
    entries - not a crash, just quietly wrong data, worse than a loud
    failure."""
    prev_xml = None
    for _ in range(max_steps):
        xml = dump_ui(device)
        if prev_xml is not None and _sidebar_titles(xml) <= _sidebar_titles(prev_xml):
            return
        prev_xml = xml
        _run_adb(["shell", "input", "swipe", "540", "600", "540", "1800", "300"], device=device)
        time.sleep(1)


def _sidebar_titles(xml: str) -> set:
    return {c["title"] for c in parse_conversation_list(xml)}


def open_sidebar(device: str, _retried: bool = False) -> None:
    """Idempotent: does nothing if the sidebar is already open. Detected
    via content-desc="Close navigation menu", which is part of the
    sidebar's fixed chrome (stays on screen regardless of scroll
    position) - NOT the "Chats" section header text, which can scroll
    out of view if the sidebar is already scrolled down, causing a
    false "not open" read and a failed re-tap. Real bug this guards
    against: enumerate_conversations() leaves the sidebar open (and
    possibly scrolled) when it returns - calling open_sidebar() again
    later (e.g. a second collection run) would otherwise fail outright,
    since the "Open menu" hamburger only exists in the closed/chat-view
    header, not the sidebar itself.

    Self-healing for a second real failure mode found during development:
    a stray extra BACK press (or the app's own behavior when BACK is
    pressed already at the sidebar) can exit Claude entirely, landing on
    the phone's home screen - neither the open nor closed sidebar signal
    exists there. One relaunch-and-retry (not a loop - a second failure
    after relaunch is a real problem worth surfacing, not silently
    retrying forever) before raising."""
    xml = dump_ui(device)
    if 'content-desc="Close navigation menu"' in xml:
        return  # already open

    m = re.search(r'<node[^>]*content-desc="Open menu"[^>]*bounds="(\[\d+,\d+\]\[\d+,\d+\])"', xml)
    if not m:
        if _retried:
            raise AndroidUIElementNotFoundError(
                'No "Open menu" element found even after relaunching Claude - '
                "the app may be on an unexpected screen (e.g. still on the "
                "home screen, or a permission dialog)."
            )
        logger.info('Sidebar not found and no "Open menu" element present - relaunching Claude and retrying once')
        launch_claude_app(device)
        return open_sidebar(device, _retried=True)

    tap_bounds(device, m.group(1))


# --- Top-level entry points ---------------------------------------------

def _find_conversation_bounds_by_title(device: str, title: str, max_scroll_steps: int = 50) -> str:
    """Open the sidebar (or confirm it's already open), scroll from the
    top until `title` is found, and return its current, fresh bounds.

    Real bug this fixes: enumerate_conversations()'s bounds go stale the
    moment the sidebar scrolls again for ANY reason (including this same
    function extracting an earlier conversation and returning to a
    differently-scrolled sidebar) - reusing them for a later tap can hit
    a completely different, unrelated conversation that happens to now
    occupy those same screen coordinates. Found via a real end-to-end
    run: a stale-bounds tap landed on and extracted the wrong
    conversation's content entirely (see CHANGELOG.md's 2026-08-06
    Android entries). Always re-locates by title text instead - slower
    (a fresh scroll-and-search per conversation) but correct.
    """
    open_sidebar(device)
    scroll_sidebar_to_top(device)

    for _ in range(max_scroll_steps):
        xml = dump_ui(device)
        for c in parse_conversation_list(xml):
            if c["title"] == title and c["bounds"] != "[0,0][0,0]":
                return c["bounds"]
        screen_height = _screen_height_from_dump(xml)
        scroll_up_conversation(device, screen_height)

    raise AndroidUIElementNotFoundError(f"Conversation titled {title!r} not found in sidebar after scrolling")


def extract_conversation(device: str, conversation: dict, max_scroll_steps: int = 200) -> dict:
    """Open one conversation (re-located fresh by title, not by
    previously-captured bounds - see _find_conversation_bounds_by_title's
    docstring for why), scroll to the top collecting every message along
    the way, and return a raw-export dict ready for normalize_session().
    """
    bounds = _find_conversation_bounds_by_title(device, conversation["title"])
    tap_bounds(device, bounds)

    first_xml = dump_ui(device)
    screen_width = _screen_width_from_dump(first_xml)
    screen_height = _screen_height_from_dump(first_xml)

    pages = [parse_message_bubbles(first_xml, screen_width)]
    for _ in range(max_scroll_steps):
        scroll_up_conversation(device, screen_height)
        xml = dump_ui(device)
        bubbles = parse_message_bubbles(xml, screen_width)
        if is_scroll_stalled(pages[-1], bubbles):
            break
        pages.append(bubbles)

    merged = merge_scroll_pages(pages)
    navigate_back(device)
    return messages_to_raw_export(conversation["title"], merged)


def enumerate_conversations(device: str, max_scroll_steps: int = 50) -> list[dict]:
    """Open the sidebar and collect every conversation's title + bounds,
    scrolling until no new titles appear. Returns deduplicated entries
    in the order first seen.

    Always starts by scrolling to the top of the list, regardless of
    where the sidebar happens to be scrolled to already - see
    scroll_sidebar_to_top()'s docstring for why this can't be skipped
    even when the sidebar is already open."""
    open_sidebar(device)
    scroll_sidebar_to_top(device)

    seen_titles: set = set()
    all_convos: list[dict] = []
    prev_titles: set = set()
    for _ in range(max_scroll_steps):
        xml = dump_ui(device)
        convos = parse_conversation_list(xml)
        curr_titles = {c["title"] for c in convos}
        for c in convos:
            if c["title"] not in seen_titles:
                seen_titles.add(c["title"])
                all_convos.append(c)
        if curr_titles <= prev_titles:
            break
        prev_titles = curr_titles
        screen_height = _screen_height_from_dump(xml)
        scroll_up_conversation(device, screen_height)

    return all_convos


def collect_from_claude_android(address: Optional[str] = None) -> list[dict]:
    """Top-level collector entry point, called from
    src/orchestration.py like every other collect_from_*() function.

    Connects to a device (own phone, or a spare/old Android device used
    purely as a bridge to the same cloud account - same code path either
    way, see module docstring), enumerates every conversation, extracts
    each one, and returns normalize_session()-ready dicts.

    Real, deliberate limitation: this drives a live UI end-to-end for
    every conversation on every run - meaningfully slower than the other
    collectors' plain file/cache reads, and depends on the device being
    reachable over WiFi right now. Not something to run on every
    `cli.py sync` call by default - see ROADMAP.md for how this should
    be scheduled/invoked once wired into orchestration.
    """
    from src.collector import normalize_session

    try:
        device = connect_device(address)
    except AndroidNotConnectedError:
        logger.warning("Android device not reachable; skipping claude-android collection")
        return []

    launch_claude_app(device)
    conversations = enumerate_conversations(device)

    sessions = []
    for conv in conversations:
        try:
            raw = extract_conversation(device, conv)
            sessions.append(normalize_session(raw, "claude-android", "android-bridge"))
        except AndroidUIElementNotFoundError as e:
            logger.warning("Failed to extract conversation %r: %s", conv["title"], e)
            continue

    return sessions

# Built with assistance from Claude Code by Anthropic.
