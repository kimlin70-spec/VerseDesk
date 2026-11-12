"""Build VerseDesk's verse data from the official BSB files.

    python3 -I tools/bsb.py download          # once: fetch + verify the official files
    python3 -I tools/build_verses.py          # writes the three files below
    python3 -I tools/build_verses.py --check  # verify the committed files are up to date

Outputs (all in versedesk/data/):
  * verses.json       the built-in verse list, in the order of tools/default_list.txt
                      (one reference per line; '#' starts a comment).  Text is never typed
                      by hand: it is looked up in bsb.txt (see tools/bsb.py for the rules).
  * bsb.txt.xz        the official bsb.txt, byte for byte, LZMA-compressed: the verse list
                      editor looks up any reference the user types in it (offline).
  * psalm_titles.json the psalm superscriptions from the official USFM files, so the app
                      can strip "A Psalm of David." from verse 1 exactly like this script.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import lzma
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
REPO = TOOLS_DIR.parent
sys.path.insert(0, str(TOOLS_DIR))  # needed under `python -I`, which does not add it

import bsb  # noqa: E402

LIST = TOOLS_DIR / "default_list.txt"
DATA = REPO / "versedesk" / "data"
OUTPUT = DATA / "verses.json"
BIBLE_OUT = DATA / "bsb.txt.xz"
TITLES_OUT = DATA / "psalm_titles.json"
RETRIEVED = "2026-11-12"
MAX_CHARS = 420
MIN_COUNT, MAX_COUNT = 30, 50
TRANSLATION_TAG = "BSB"


def read_list(path: Path) -> list[str]:
    refs = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            refs.append(line)
    return refs


def source_info() -> dict:
    return {
        "file": bsb.SOURCES["bsb.txt"]["url"],
        "sha256": bsb.SOURCES["bsb.txt"]["sha256"],
        "last_modified": bsb.SOURCES["bsb.txt"]["last_modified"],
        "edition": bsb.SOURCES["bsb.txt"]["edition"],
        "superscriptions_from": bsb.SOURCES["bsb_usfm.zip"]["url"],
        "downloads_page": "https://berean.bible/downloads.htm",
        "retrieved": RETRIEVED,
    }


def build(refs: list[str], bible: bsb.Bible) -> tuple[dict, list[str]]:
    errors: list[str] = []
    passages: list[bsb.Passage] = []
    entries = []
    if not MIN_COUNT <= len(refs) <= MAX_COUNT:
        errors.append(f"the list has {len(refs)} passages (expected {MIN_COUNT}-{MAX_COUNT})")
    for n, ref in enumerate(refs, start=1):
        try:
            p = bsb.parse_reference(ref)
            text = bible.passage_text(p)
        except (bsb.ReferenceError_, bsb.SourceError) as e:
            errors.append(f"#{n}: {e}")
            continue
        if not 1 <= p.verse_count <= 3:
            errors.append(f"#{n}: {ref} has {p.verse_count} verses (allowed 1-3)")
        flags = bsb.quality_flags(text)
        if flags:
            errors.append(f"#{n}: {ref} flagged {flags}")
        if len(text) > MAX_CHARS:
            errors.append(f"#{n}: {ref} is {len(text)} characters (max {MAX_CHARS})")
        for other in passages:
            if p.overlaps(other):
                errors.append(f"#{n}: {ref} overlaps {other.key}")
        passages.append(p)
        entries.append({"reference": f"{p.display} ({TRANSLATION_TAG})", "text": text})
    doc = {
        "format": 2,
        "translation": "Berean Standard Bible (BSB)",
        "license": "Public domain. bsb.txt header: \"" + bible.header[1].strip() + "\"",
        "source": source_info(),
        "notes": (
            "Verse text is copied verbatim from bsb.txt. Psalm superscriptions (USFM \\d, e.g. "
            "'A Psalm of David.') are removed from the start of verse 1 only after checking the "
            "verse begins with exactly that text. Consecutive verses are joined with one space. "
            "Shown in this order, one after another (settings.json verse.interval_minutes)."
        ),
        "verses": entries,
    }
    return doc, errors


def titles_doc(bible: bsb.Bible) -> dict:
    return {
        "source": {
            "file": bsb.SOURCES["bsb_usfm.zip"]["url"],
            "sha256": bsb.SOURCES["bsb_usfm.zip"]["sha256"],
            "member": "bsb_usfm/PSA.usfm",
            "marker": "\\d (text before \\v 1)",
        },
        "notes": "In bsb.txt each of these is glued to the front of the psalm's verse 1, followed by one space.",
        "titles": {str(k): v for k, v in sorted(bible.superscriptions.items())},
    }


def render(doc: dict) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=1) + "\n"


def compressed_matches(path: Path, raw: bytes) -> bool:
    try:
        return hashlib.sha256(lzma.decompress(path.read_bytes())).digest() == hashlib.sha256(raw).digest()
    except (OSError, lzma.LZMAError):
        return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source-dir", type=Path, default=bsb.DEFAULT_SOURCE_DIR)
    ap.add_argument("--list", type=Path, default=LIST)
    ap.add_argument("--check", action="store_true", help="fail if the committed files differ from a fresh build")
    args = ap.parse_args(argv)

    bible = bsb.Bible(args.source_dir)
    doc, errors = build(read_list(args.list), bible)
    if errors:
        print("the list has problems:", file=sys.stderr)
        for e in errors:
            print("  " + e, file=sys.stderr)
        return 1
    raw = (Path(args.source_dir) / "bsb.txt").read_bytes()
    outputs = {OUTPUT: render(doc), TITLES_OUT: render(titles_doc(bible))}

    if args.check:
        stale = [p for p, text in outputs.items() if not p.exists() or p.read_text(encoding="utf-8") != text]
        if not compressed_matches(BIBLE_OUT, raw):
            stale.append(BIBLE_OUT)
        if stale:
            for p in stale:
                print(f"{p} is out of date; run tools/build_verses.py", file=sys.stderr)
            return 1
        print(f"up to date: {len(doc['verses'])} verses, bsb.txt.xz = official bsb.txt, "
              f"{len(bible.superscriptions)} psalm titles")
        return 0

    DATA.mkdir(parents=True, exist_ok=True)
    for p, text in outputs.items():
        p.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {p}")
    if compressed_matches(BIBLE_OUT, raw):
        print(f"{BIBLE_OUT} already holds the official bsb.txt")
    else:
        BIBLE_OUT.write_bytes(lzma.compress(raw, format=lzma.FORMAT_XZ, preset=9 | lzma.PRESET_EXTREME))
        print(f"wrote {BIBLE_OUT} ({BIBLE_OUT.stat().st_size:,} bytes)")
    print(f"{len(doc['verses'])} verses in the built-in list")
    return 0


if __name__ == "__main__":
    sys.exit(main())
