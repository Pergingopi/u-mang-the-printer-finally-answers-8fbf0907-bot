"""The Printer Finally Answers — make.fun entry.

One line, the office printer's comeback to everyone staring at it,
written to /output/entry.txt (or $MAKEFUN_OUTPUT_DIR/entry.txt).

ENTRY_LINE is the whole entry. The rest of this file is the machinery
that gets it onto disk intact: gate the text, resolve the output
directory, stage the payload in a temp file inside that directory,
install it atomically, and read it back to prove it landed.
"""

import os
import stat
import sys
import tempfile
import time
import unicodedata

ENTRY_LINE = (
    "Error 41: paper jam. I have printed 12,000 pages without complaint; "
    "you cannot load one tray without a crisis."
)

MAX_CHARS = 240
STALE_TMP_SECONDS = 60
TMP_PREFIX = ".entry-"
TMP_SUFFIX = ".tmp"
OUTPUT_FILENAME = "entry.txt"


def _is_noncharacter(code):
    """True for Unicode noncharacters: U+FDD0-U+FDEF and xFFFE/xFFFF."""
    if 0xFDD0 <= code <= 0xFDEF:
        return True
    return (code & 0xFFFE) == 0xFFFE


def _is_banned_character(ch):
    """True when a character must never appear in the entry."""
    code = ord(ch)
    category = unicodedata.category(ch)
    if category == "Cs":
        return True  # lone surrogates cannot encode as UTF-8
    if category in ("Cc", "Cf", "Zl", "Zp"):
        return True  # controls, format chars, line/paragraph separators
    if category == "Zs" and ch != " ":
        return True  # NBSP and other exotic spaces
    if _is_noncharacter(code):
        return True
    return False


def _gate_shape(text):
    """Shape checks: a real single line of 1-240 characters."""
    if not isinstance(text, str):
        return False
    if not 1 <= len(text) <= MAX_CHARS:
        return False
    if not text.strip():
        return False
    if text != text.strip():
        return False  # no leading or trailing whitespace
    if "\n" in text or "\r" in text:
        return False
    return True


def _gate_characters(text):
    """Character checks: every codepoint must be clean UTF-8 text."""
    if any(_is_banned_character(ch) for ch in text):
        return False
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _passes_gate(text):
    """The full gate: shape and characters both have to pass."""
    return _gate_shape(text) and _gate_characters(text)


def _output_directory():
    """Output directory from $MAKEFUN_OUTPUT_DIR, else /output."""
    raw = os.environ.get("MAKEFUN_OUTPUT_DIR", "")
    path = raw.strip() if raw else "/output"
    if not path:
        raise ValueError("MAKEFUN_OUTPUT_DIR is empty")
    if os.path.islink(path) and os.path.realpath(path) == "/":
        raise ValueError("output directory must not be a symlink to /")
    if os.path.exists(path) and not os.path.isdir(path):
        raise ValueError("output path exists and is not a directory")
    os.makedirs(path, exist_ok=True)
    return path


def _clear_abandoned_staging_files(output_dir):
    """Remove staging temps older than STALE_TMP_SECONDS."""
    now = time.time()
    for name in os.listdir(output_dir):
        if not (name.startswith(TMP_PREFIX) and name.endswith(TMP_SUFFIX)):
            continue
        full = os.path.join(output_dir, name)
        try:
            if os.path.isfile(full) and now - os.path.getmtime(full) > STALE_TMP_SECONDS:
                os.unlink(full)
        except OSError:
            pass


def _drain_to_file(fd, data):
    """Write every byte, coping with short writes."""
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        view = view[written:]


def _sync_directory(path):
    """Best-effort fsync of a directory so the rename survives a crash."""
    try:
        dfd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dfd)
    except OSError:
        pass
    finally:
        os.close(dfd)


def _prepare_payload(text):
    """Validate the text and encode the bytes to publish."""
    if not _passes_gate(text):
        raise ValueError("entry text fails the gate")
    return text.encode("utf-8")


def _write_staging_file(output_dir, payload):
    """Stage the payload in a temp file inside the output directory."""
    fd, tmp_path = tempfile.mkstemp(
        dir=output_dir, prefix=TMP_PREFIX, suffix=TMP_SUFFIX
    )
    try:
        _drain_to_file(fd, payload)
        os.fsync(fd)
        os.fchmod(fd, 0o644)
        os.close(fd)
        fd = None
        with open(tmp_path, "rb") as handle:
            if handle.read() != payload:
                raise ValueError("staged entry does not match the payload")
    finally:
        if fd is not None:
            os.close(fd)
    return tmp_path


def _install_staged(output_dir, tmp_path):
    """Atomically move the staged file onto entry.txt."""
    target = os.path.join(output_dir, OUTPUT_FILENAME)
    os.replace(tmp_path, target)
    _sync_directory(output_dir)
    return target


def _verify_published_bytes(path, expected):
    """Read the published file back; it must match byte for byte."""
    with open(path, "rb") as handle:
        actual = handle.read()
    if actual != expected:
        raise ValueError("published entry does not match the payload")
    mode = stat.S_IMODE(os.stat(path).st_mode)
    if mode != 0o644:
        raise ValueError("published entry mode is not 0644")


def hand_in_entry(text):
    """Publish one entry line through staging, install, and verify."""
    payload = _prepare_payload(text)
    output_dir = _output_directory()
    _clear_abandoned_staging_files(output_dir)
    tmp_path = _write_staging_file(output_dir, payload)
    try:
        target = _install_staged(output_dir, tmp_path)
        tmp_path = None
    finally:
        if tmp_path is not None and os.path.exists(tmp_path):
            os.unlink(tmp_path)
    _verify_published_bytes(target, payload)
    return target


def main():
    hand_in_entry(ENTRY_LINE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
