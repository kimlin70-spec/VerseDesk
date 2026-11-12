"""Read verses from the official Berean Standard Bible (BSB) distribution files.

Official downloads page: https://berean.bible/downloads.htm
  * "Berean Standard Bible - Text"  -> https://bereanbible.com/bsb.txt
      UTF-8 (with BOM), CRLF line endings, three header lines, then
      "<Book> <chapter>:<verse>\\t<text>" for all 31,102 verses.
  * "Berean Standard Bible - USFM"  -> https://bereanbible.com/bsb_usfm.zip
      Used only to identify psalm superscriptions (the ``\\d`` marker).  In
      bsb.txt the superscription ("A Psalm of David.") is glued to the front of
      verse 1; we strip exactly that string, and only after checking that the
      verse really starts with it.

The verse text itself is never typed by hand: every word comes from bsb.txt.

Command line (run with ``python3 -I``):
    python3 -I tools/bsb.py lookup "John 3:16" "Proverbs 3:5-6"
    python3 -I tools/bsb.py download          # fetch + verify the source files
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
DEFAULT_SOURCE_DIR = TOOLS_DIR / ".cache"

SOURCES = {
    "bsb.txt": {
        "url": "https://bereanbible.com/bsb.txt",
        "sha256": "2ac3af1de52d4e68261cba91d85c320b7eadc6560e830d99e591767b8ff5ca96",
        # bsb.txt carries no edition string; the publisher replaces it in place.  This copy:
        "last_modified": "Fri, 31 Jul 2026 14:02:14 GMT",
        "edition": ("text as of the official changelog entry of 7-31-2026 "
                    "(https://bereanbible.com/changelog.txt; e.g. 2 Timothy 1:15 'province')"),
    },
    "bsb_usfm.zip": {
        "url": "https://bereanbible.com/bsb_usfm.zip",
        "sha256": "f0c56438eb89c98e8f62c5c00461e25cc35b098ad5b179bc350cede759ee5f87",
    },
}

# Book names exactly as they appear in bsb.txt, in canonical order.
BOOKS = [
    "Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy", "Joshua", "Judges",
    "Ruth", "1 Samuel", "2 Samuel", "1 Kings", "2 Kings", "1 Chronicles",
    "2 Chronicles", "Ezra", "Nehemiah", "Esther", "Job", "Psalm", "Proverbs",
    "Ecclesiastes", "Song of Solomon", "Isaiah", "Jeremiah", "Lamentations",
    "Ezekiel", "Daniel", "Hosea", "Joel", "Amos", "Obadiah", "Jonah", "Micah",
    "Nahum", "Habakkuk", "Zephaniah", "Haggai", "Zechariah", "Malachi",
    "Matthew", "Mark", "Luke", "John", "Acts", "Romans", "1 Corinthians",
    "2 Corinthians", "Galatians", "Ephesians", "Philippians", "Colossians",
    "1 Thessalonians", "2 Thessalonians", "1 Timothy", "2 Timothy", "Titus",
    "Philemon", "Hebrews", "James", "1 Peter", "2 Peter", "1 John", "2 John",
    "3 John", "Jude", "Revelation",
]
OT_BOOKS = set(BOOKS[: BOOKS.index("Malachi") + 1])

BOOK_ALIASES = {
    "psalms": "Psalm",
    "ps": "Psalm",
    "song of songs": "Song of Solomon",
    "songs": "Song of Solomon",
    "song": "Song of Solomon",
}

_REF_RE = re.compile(
    r"^\s*(?P<book>(?:[1-3]\s+)?[A-Za-z][A-Za-z ]*?)\s+(?P<chapter>\d+):(?P<v1>\d+)"
    r"(?:\s*[-–—]\s*(?P<v2>\d+))?\s*$"
)


class SourceError(Exception):
    """The source files are missing, corrupt or not the pinned edition."""


class ReferenceError_(ValueError):
    """A reference could not be parsed or resolved."""


@dataclass(frozen=True)
class Passage:
    book: str
    chapter: int
    first: int
    last: int

    @property
    def verse_count(self) -> int:
        return self.last - self.first + 1

    @property
    def display(self) -> str:
        if self.first == self.last:
            return f"{self.book} {self.chapter}:{self.first}"
        return f"{self.book} {self.chapter}:{self.first}–{self.last}"

    @property
    def key(self) -> str:
        """ASCII form used in plan files: 'Book C:V' or 'Book C:V-W'."""
        if self.first == self.last:
            return f"{self.book} {self.chapter}:{self.first}"
        return f"{self.book} {self.chapter}:{self.first}-{self.last}"

    def verse_refs(self) -> list[str]:
        return [f"{self.book} {self.chapter}:{v}" for v in range(self.first, self.last + 1)]

    def overlaps(self, other: "Passage") -> bool:
        return (
            self.book == other.book
            and self.chapter == other.chapter
            and self.first <= other.last
            and other.first <= self.last
        )


def canonical_book(name: str) -> str:
    cleaned = re.sub(r"\s+", " ", name.strip())
    for book in BOOKS:
        if book.lower() == cleaned.lower():
            return book
    alias = BOOK_ALIASES.get(cleaned.lower())
    if alias:
        return alias
    raise ReferenceError_(f"unknown book name: {name!r}")


def parse_reference(ref: str) -> Passage:
    m = _REF_RE.match(ref)
    if not m:
        raise ReferenceError_(f"cannot parse reference: {ref!r}")
    book = canonical_book(m.group("book"))
    chapter = int(m.group("chapter"))
    first = int(m.group("v1"))
    last = int(m.group("v2") or first)
    if last < first:
        raise ReferenceError_(f"verse range goes backwards: {ref!r}")
    return Passage(book, chapter, first, last)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download_sources(source_dir: Path, allow_new: bool = False) -> None:
    source_dir.mkdir(parents=True, exist_ok=True)
    for name, info in SOURCES.items():
        target = source_dir / name
        print(f"downloading {info['url']} -> {target}")
        req = urllib.request.Request(info["url"], headers={"User-Agent": "VerseDesk-data-builder"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
        digest = hashlib.sha256(data).hexdigest()
        if digest != info["sha256"] and not allow_new:
            raise SourceError(
                f"{name}: SHA-256 {digest} does not match the pinned edition {info['sha256']}. "
                "The publisher may have released a new edition; review it and update SOURCES."
            )
        target.write_bytes(data)
        print(f"  ok sha256={digest}")


def verify_sources(source_dir: Path) -> None:
    for name, info in SOURCES.items():
        path = source_dir / name
        if not path.is_file():
            raise SourceError(f"missing {path}; run: python3 -I tools/bsb.py download")
        digest = sha256_of(path)
        if digest != info["sha256"]:
            raise SourceError(f"{path}: SHA-256 {digest} != pinned {info['sha256']}")


class Bible:
    """Verse lookup over bsb.txt with verified psalm-superscription stripping."""

    def __init__(self, source_dir: Path = DEFAULT_SOURCE_DIR, verify: bool = True):
        source_dir = Path(source_dir)
        if verify:
            verify_sources(source_dir)
        self.header: list[str] = []
        self.verses: dict[str, str] = {}
        self._load_text(source_dir / "bsb.txt")
        self.superscriptions = self._load_superscriptions(source_dir / "bsb_usfm.zip")

    def _load_text(self, path: Path) -> None:
        raw = path.read_bytes().decode("utf-8-sig")
        lines = raw.split("\r\n")
        self.header = [ln.rstrip("\t") for ln in lines[:3]]
        if not self.header[2].startswith("Verse\tBerean Standard Bible"):
            raise SourceError("unexpected bsb.txt header")
        for ln in lines[3:]:
            if not ln:
                continue
            ref, sep, text = ln.partition("\t")
            if not sep:
                raise SourceError(f"malformed line: {ln[:60]!r}")
            self.verses[ref] = text
        if len(self.verses) != 31102:
            raise SourceError(f"expected 31102 verses, found {len(self.verses)}")

    def _load_superscriptions(self, path: Path) -> dict[int, str]:
        """Map psalm number -> superscription text, verified against bsb.txt."""
        with zipfile.ZipFile(path) as z:
            usfm = z.read("bsb_usfm/PSA.usfm").decode("utf-8-sig")
        result: dict[int, str] = {}
        chapter = None
        for line in usfm.split("\n"):
            m = re.match(r"\\c (\d+)", line)
            if m:
                chapter = int(m.group(1))
                continue
            if chapter and line.startswith("\\d ") and "\\v 1 " in line:
                sup = line.split("\\v 1 ", 1)[1]
                sup = re.sub(r"\\f .*?\\f\*", "", sup)
                sup = re.sub(r"\\x .*?\\x\*", "", sup)
                sup = re.sub(r"\\\w+\*?", "", sup).strip()
                verse1 = self.verses.get(f"Psalm {chapter}:1", "")
                if not verse1.startswith(sup + " "):
                    raise SourceError(f"Psalm {chapter}: superscription {sup!r} not found at start of verse 1")
                result[chapter] = sup
        return result

    def verse_text(self, ref: str) -> str:
        if ref not in self.verses:
            raise ReferenceError_(f"no such verse in BSB: {ref}")
        text = self.verses[ref]
        m = re.fullmatch(r"Psalm (\d+):1", ref)
        if m and int(m.group(1)) in self.superscriptions:
            text = text[len(self.superscriptions[int(m.group(1))]) + 1 :]
        return text

    def passage_text(self, passage: Passage) -> str:
        parts = []
        for ref in passage.verse_refs():
            t = self.verse_text(ref)
            if not t.strip():
                raise ReferenceError_(f"{ref} is empty in the BSB (omitted textual variant)")
            parts.append(t)
        return " ".join(parts)

    def has_verse(self, ref: str) -> bool:
        return ref in self.verses


def quality_flags(text: str) -> list[str]:
    """Cheap heuristics for 'does this read as a complete thought?'."""
    flags = []
    first_alpha = next((c for c in text if c.isalpha()), "")
    if first_alpha and first_alpha.islower():
        flags.append("starts_lowercase")
    stripped = text.rstrip("”’\"') ")
    if not stripped or stripped[-1] not in ".!?":
        flags.append("open_ending")
    if re.search(r"\bSelah\b", text):
        flags.append("selah")  # a liturgical marker mid-text reads oddly on a desktop
    if "For the choirmaster" in text:
        flags.append("subscription")  # e.g. Habakkuk 3:19 ends with a musical note
    opens, closes = text.count("“"), text.count("”")
    if opens != closes:
        # A quotation that began in an earlier verse and closes inside this passage
        # ("... will not be broken," says the LORD) still reads naturally: the first quote
        # mark is a closing one and everything after it pairs up. A quote that opens and
        # never closes does not read as a complete thought.
        marks = [c for c in text if c in "“”"]
        dangling_close = closes == opens + 1 and marks and marks[0] == "”"
        if not dangling_close:
            flags.append("unbalanced_double_quotes")
    return flags


def lookup(bible: Bible, ref: str) -> dict:
    try:
        passage = parse_reference(ref)
        text = bible.passage_text(passage)
    except (ReferenceError_, SourceError) as e:
        return {"input": ref, "error": str(e)}
    return {
        "input": ref,
        "key": passage.key,
        "reference": passage.display,
        "verses": passage.verse_count,
        "chars": len(text),
        "flags": quality_flags(text),
        "text": text,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("lookup", help="print passages as JSON lines")
    sp.add_argument("refs", nargs="*")
    sp.add_argument("--file", type=Path, help="read references from a file (one per line)")
    dp = sub.add_parser("download", help="download and verify the official source files")
    dp.add_argument("--allow-new-source", action="store_true")
    args = ap.parse_args(argv)

    if args.cmd == "download":
        download_sources(args.source_dir, allow_new=args.allow_new_source)
        return 0

    bible = Bible(args.source_dir)
    refs = list(args.refs)
    if args.file:
        refs += [ln.strip() for ln in args.file.read_text(encoding="utf-8").splitlines() if ln.strip()]
    for ref in refs:
        print(json.dumps(lookup(bible, ref), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
