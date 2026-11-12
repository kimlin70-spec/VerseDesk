"""The verse list: which verses are shown, in which order.

* Built-in list: versedesk/data/verses.json (about 40 well-known passages; the text is
  copied from the official BSB file by tools/build_verses.py, never typed by hand).
* The user's own list: %APPDATA%\\VerseDesk\\verses.json, written by the verse list editor
  (트레이 → 말씀 목록 편집).  When it exists it replaces the built-in list completely.

The verses are shown one after another in list order (see versedesk/rotation.py).

File format (UTF-8; a bare list is also accepted; other keys are ignored):

    {"verses": [
        {"reference": "John 3:16 (BSB)", "text": "For God so loved the world ..."},
        ...
    ]}

Earlier versions used one entry per calendar day ({"date": "12-25", ...}).  Such a file
is reported as ``dated`` so the app can put it aside; it is never used as the list.
Pure Python, no Qt.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from versedesk.settings import describe_json_error, read_text_lenient

log = logging.getLogger("versedesk.verses")

MAX_TEXT_CHARS = 3000  # the editor's longest possible passage (10 verses) is about 2,300 characters
MAX_REFERENCE_CHARS = 120
MAX_VERSES = 1000  # far more than anyone rotates through; protects against absurd files

FILE_NOTE = (
    "VerseDesk 말씀 목록입니다. 트레이 메뉴 '말씀 목록 편집'에서 고치면 자동으로 저장됩니다. "
    "위에서부터 차례대로 바탕화면에 표시됩니다. 이 파일을 지우면 기본 목록으로 돌아갑니다."
)


@dataclass(frozen=True)
class Verse:
    reference: str  # e.g. "John 3:16 (BSB)"; may be empty
    text: str
    source: str = "embedded"  # "embedded" | "user" | "fallback"

    def key(self) -> str:
        """Two entries are the same verse when their references match, ignoring case,
        spacing, the kind of dash and a trailing "(BSB)"; without a reference, by text."""
        ref = re.sub(r"\s*\([^()]*\)\s*$", "", self.reference)
        ref = re.sub(r"\s*[-~–—]\s*", "-", " ".join(ref.split())).casefold()
        return ref or "text:" + " ".join(self.text.split()).casefold()


FALLBACK = Verse("", "(VerseDesk: verse data is missing — see log.txt)", "fallback")


@dataclass
class VerseFile:
    verses: list[Verse] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None  # the whole file is unusable
    dated: bool = False  # the old one-verse-per-calendar-day format
    unreadable: bool = False  # could not be opened (e.g. another program had it locked): try again
    skipped: int = 0  # entries left out (no text, not an object, over MAX_VERSES)
    cut: int = 0  # texts shortened to MAX_TEXT_CHARS


def _clean(value: Any, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())  # no line breaks, tabs or double spaces
    return text[:limit] if text else None


def parse_list(data: Any, source: str) -> VerseFile:
    """Parsed JSON -> the verses in order. Invalid entries are skipped with a warning."""
    if isinstance(data, dict):
        items = data.get("verses")
        if not isinstance(items, list):
            return VerseFile(error='expected a list under "verses"')
    elif isinstance(data, list):
        items = data
    else:
        return VerseFile(error='expected an object with a "verses" list')
    if any(isinstance(item, dict) and "date" in item for item in items):
        return VerseFile(dated=True, error="one verse per date (format of an older VerseDesk)")

    out = VerseFile()
    for i, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            out.warnings.append(f"entry #{i}: not an object, skipped")
            out.skipped += 1
            continue
        text = _clean(item.get("text"), MAX_TEXT_CHARS)
        if text is None:
            out.warnings.append(f"entry #{i}: missing \"text\", skipped")
            out.skipped += 1
            continue
        if len(out.verses) >= MAX_VERSES:
            out.warnings.append(f"only the first {MAX_VERSES} verses are used")
            out.skipped += len(items) - i + 1
            break
        if len(text) == MAX_TEXT_CHARS and len(" ".join(str(item.get("text")).split())) > MAX_TEXT_CHARS:
            out.warnings.append(f"entry #{i}: text longer than {MAX_TEXT_CHARS} characters was cut")
            out.cut += 1
        out.verses.append(Verse(_clean(item.get("reference"), MAX_REFERENCE_CHARS) or "", text, source))
    return out


def load_verse_file(path: Path, source: str, attempts: int = 1) -> VerseFile:
    """``attempts`` > 1 retries a file that cannot be opened (antivirus, backup or sync tools
    may hold it briefly) with short pauses; the 2-second poll passes 1 and is itself the retry,
    so a file that stays locked never stalls the program."""
    text: str | None = None
    last_err: OSError | None = None
    for attempt in range(max(1, attempts)):
        try:
            text = read_text_lenient(path)
            break
        except OSError as e:
            last_err = e
            if attempt < attempts - 1:
                time.sleep(0.15 * (attempt + 1))
    if text is None:
        return VerseFile(error=f"{path.name}: cannot open the file: {last_err}", unreadable=True)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return VerseFile(error=describe_json_error(path.name, e))
    except (ValueError, RecursionError) as e:  # e.g. a number thousands of digits long
        return VerseFile(error=f"{path.name}: cannot be read ({type(e).__name__}: {e})"[:300])
    try:
        result = parse_list(data, source)
    except Exception as e:  # an odd entry must never keep the app from starting
        log.exception("%s: unexpected content", path.name)
        return VerseFile(error=f"{path.name}: unexpected content ({type(e).__name__})")
    if result.error and not result.dated:
        result.error = f"{path.name}: {result.error}"
    return result


def load_builtin(path: Path) -> list[Verse]:
    result = load_verse_file(path, "embedded")
    if result.error:
        log.error("built-in verse list unusable: %s", result.error)
    for w in result.warnings:
        log.error("built-in verse list: %s", w)
    return result.verses


def list_document(verses: list[Verse]) -> str:
    """The user's list as written to %APPDATA%\\VerseDesk\\verses.json."""
    doc = {
        "안내": FILE_NOTE,
        "verses": [{"reference": v.reference, "text": v.text} for v in verses],
    }
    return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
