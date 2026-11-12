"""Verse of the day: pick the passage for a calendar date.

* The embedded file (versedesk/data/verses.json, built from the official BSB text by
  tools/build_verses.py) has one entry for every day of a leap year: "01-01" ... "12-31",
  including "02-29".
* If %APPDATA%\\VerseDesk\\verses.json exists, every date it contains wins over the
  embedded entry; dates it does not mention keep the embedded verse.

Override file format (UTF-8; a bare list is also accepted):

    {"verses": [
        {"date": "12-25", "reference": "Book 1:2 (BSB)", "text": "the verse text ..."}
    ]}

"date" accepts "12-25", "12/25", "1-5" etc.  "text" is required; "reference" may be empty.
Pure Python, no Qt.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from versedesk.settings import describe_json_error, read_text_lenient

log = logging.getLogger("versedesk.verses")

_DATE_RE = re.compile(r"^\s*(\d{1,2})\s*[-/.]\s*(\d{1,2})\s*$")
MAX_TEXT_CHARS = 2000


@dataclass(frozen=True)
class Verse:
    date: str  # "MM-DD"
    reference: str  # e.g. "John 3:16 (BSB)"
    text: str
    source: str = "embedded"  # "embedded" | "user"


def date_key(d: _dt.date) -> str:
    return f"{d.month:02d}-{d.day:02d}"


def all_date_keys() -> list[str]:
    """All 366 keys in calendar order (uses leap year 2024)."""
    start = _dt.date(2024, 1, 1)
    return [date_key(start + _dt.timedelta(days=i)) for i in range(366)]


def normalize_date_key(value: Any) -> str | None:
    """'1-5', '01/05', '1.5' -> '01-05'. Returns None if not a real month/day (Feb 29 allowed)."""
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value)
    if not m:
        return None
    month, day = int(m.group(1)), int(m.group(2))
    try:
        _dt.date(2024, month, day)  # 2024 is a leap year, so 02-29 is valid
    except ValueError:
        return None
    return f"{month:02d}-{day:02d}"


def _clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())  # collapse newlines/tabs/double spaces
    if not text:
        return None
    return text[:MAX_TEXT_CHARS]


def parse_entries(data: Any, source: str) -> tuple[dict[str, Verse], list[str]]:
    """Turn parsed JSON into {date_key: Verse}. Invalid entries are skipped with a warning."""
    warnings: list[str] = []
    if isinstance(data, dict):
        items = data.get("verses")
        if not isinstance(items, list):
            return {}, ['expected a list under "verses"']
    elif isinstance(data, list):
        items = data
    else:
        return {}, ["expected an object with a \"verses\" list"]

    out: dict[str, Verse] = {}
    for i, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            warnings.append(f"entry #{i}: not an object, skipped")
            continue
        key = normalize_date_key(item.get("date"))
        if key is None:
            warnings.append(f"entry #{i}: bad or missing \"date\" {item.get('date')!r}, skipped")
            continue
        text = _clean_text(item.get("text"))
        if text is None:
            warnings.append(f"entry #{i} ({key}): missing \"text\", skipped")
            continue
        ref = item.get("reference", "")
        ref = " ".join(ref.split()) if isinstance(ref, str) else ""
        if key in out:
            warnings.append(f"entry #{i}: date {key} appears more than once; the later entry wins")
        out[key] = Verse(key, ref, text, source)
    return out, warnings


def load_verse_file(path: Path, source: str) -> tuple[dict[str, Verse], list[str], str | None]:
    """Returns (entries, warnings, error). ``error`` is set when the whole file is unusable."""
    try:
        text = read_text_lenient(path)
    except OSError as e:
        return {}, [], f"{path.name}: cannot read: {e}"
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return {}, [], describe_json_error(path.name, e)
    except (ValueError, RecursionError) as e:  # e.g. a number thousands of digits long
        return {}, [], f"{path.name}: cannot be read ({type(e).__name__}: {e})"[:300]
    try:
        entries, warnings = parse_entries(data, source)
    except Exception as e:  # an odd entry must never keep the app from starting
        log.exception("%s: unexpected content", path.name)
        return {}, [], f"{path.name}: unexpected content ({type(e).__name__})"
    return entries, warnings, None


class VerseLibrary:
    def __init__(self, embedded: dict[str, Verse], overrides: dict[str, Verse] | None = None):
        self.embedded = dict(embedded)
        self.overrides = dict(overrides or {})

    def missing_embedded_dates(self) -> list[str]:
        return [k for k in all_date_keys() if k not in self.embedded]

    def verse_for_key(self, key: str) -> Verse:
        v = self.overrides.get(key) or self.embedded.get(key)
        if v is not None:
            return v
        # Should never happen with the shipped data; degrade gracefully instead of crashing.
        if self.embedded:
            log.error("no verse for %s; using the first embedded entry", key)
            return next(iter(self.embedded.values()))
        return Verse(key, "", "(VerseDesk: verse data is missing — see log.txt)", "fallback")

    def verse_for(self, day: _dt.date) -> Verse:
        return self.verse_for_key(date_key(day))

    def with_overrides(self, overrides: dict[str, Verse]) -> "VerseLibrary":
        return VerseLibrary(self.embedded, overrides)


def load_embedded(path: Path) -> dict[str, Verse]:
    entries, warnings, error = load_verse_file(path, "embedded")
    if error:
        log.error("embedded verse data unusable: %s", error)
    for w in warnings:
        log.error("embedded verse data: %s", w)
    return entries


def iter_dates(start: _dt.date, days: int) -> Iterable[_dt.date]:
    for i in range(days):
        yield start + _dt.timedelta(days=i)
