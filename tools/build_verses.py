"""Build versedesk/data/verses.json from tools/verse_plan.tsv and the official BSB text.

    python3 -I tools/bsb.py download        # once: fetch + verify the official files
    python3 -I tools/build_verses.py        # writes versedesk/data/verses.json
    python3 -I tools/build_verses.py --check  # verify the committed file is up to date

verse_plan.tsv: one line per calendar day, "MM-DD<TAB>Book C:V[-W]" (366 lines incl. 02-29).
Lines starting with '#' are comments.  Text is never typed by hand: it is looked up in
bsb.txt (see tools/bsb.py for the exact, verified rules).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
REPO = TOOLS_DIR.parent
sys.path.insert(0, str(TOOLS_DIR))  # needed under `python -I`, which does not add it

import bsb  # noqa: E402

PLAN = TOOLS_DIR / "verse_plan.tsv"
OUTPUT = REPO / "versedesk" / "data" / "verses.json"
RETRIEVED = "2026-11-12"
MAX_CHARS = 420
TRANSLATION_TAG = "BSB"


def all_date_keys() -> list[str]:
    import datetime as dt

    start = dt.date(2024, 1, 1)
    return [f"{(start + dt.timedelta(days=i)).month:02d}-{(start + dt.timedelta(days=i)).day:02d}" for i in range(366)]


def read_plan(path: Path) -> list[tuple[str, str]]:
    rows = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            raise SystemExit(f"{path.name}:{n}: expected 'MM-DD<TAB>reference'")
        rows.append((parts[0].strip(), parts[1].strip()))
    return rows


def build(plan_rows: list[tuple[str, str]], bible: bsb.Bible) -> tuple[dict, list[str]]:
    errors: list[str] = []
    keys = all_date_keys()
    seen_dates: dict[str, str] = {}
    passages: list[tuple[str, bsb.Passage]] = []
    entries = []
    for date, ref in plan_rows:
        if date not in keys:
            errors.append(f"{date}: not a valid MM-DD date")
            continue
        if date in seen_dates:
            errors.append(f"{date}: listed twice ({seen_dates[date]} and {ref})")
            continue
        seen_dates[date] = ref
        try:
            p = bsb.parse_reference(ref)
            text = bible.passage_text(p)
        except (bsb.ReferenceError_, bsb.SourceError) as e:
            errors.append(f"{date}: {e}")
            continue
        if not 1 <= p.verse_count <= 3:
            errors.append(f"{date}: {ref} has {p.verse_count} verses (allowed 1-3)")
        flags = bsb.quality_flags(text)
        if flags:
            errors.append(f"{date}: {ref} flagged {flags}")
        if len(text) > MAX_CHARS:
            errors.append(f"{date}: {ref} is {len(text)} characters (max {MAX_CHARS})")
        for other_date, other in passages:
            if p.overlaps(other):
                errors.append(f"{date}: {ref} overlaps {other.key} on {other_date}")
        passages.append((date, p))
        entries.append({"date": date, "reference": f"{p.display} ({TRANSLATION_TAG})", "text": text})
    missing = [k for k in keys if k not in seen_dates]
    if missing:
        errors.append(f"missing dates ({len(missing)}): {', '.join(missing[:20])}{' ...' if len(missing) > 20 else ''}")
    entries.sort(key=lambda e: keys.index(e["date"]))
    doc = {
        "format": 1,
        "translation": "Berean Standard Bible (BSB)",
        "license": "Public domain. bsb.txt header: \"" + bible.header[1].strip() + "\"",
        "source": {
            "file": bsb.SOURCES["bsb.txt"]["url"],
            "sha256": bsb.SOURCES["bsb.txt"]["sha256"],
            "superscriptions_from": bsb.SOURCES["bsb_usfm.zip"]["url"],
            "downloads_page": "https://berean.bible/downloads.htm",
            "retrieved": RETRIEVED,
        },
        "notes": (
            "Verse text is copied verbatim from bsb.txt. Psalm superscriptions (USFM \\d, e.g. "
            "'A Psalm of David.') are removed from the start of verse 1 only after checking the "
            "verse begins with exactly that text. Consecutive verses are joined with one space."
        ),
        "verses": entries,
    }
    return doc, errors


def render(doc: dict) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=1) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source-dir", type=Path, default=bsb.DEFAULT_SOURCE_DIR)
    ap.add_argument("--plan", type=Path, default=PLAN)
    ap.add_argument("--output", type=Path, default=OUTPUT)
    ap.add_argument("--check", action="store_true", help="fail if the output file differs from a fresh build")
    args = ap.parse_args(argv)

    bible = bsb.Bible(args.source_dir)
    doc, errors = build(read_plan(args.plan), bible)
    if errors:
        print("plan has problems:", file=sys.stderr)
        for e in errors:
            print("  " + e, file=sys.stderr)
        return 1
    text = render(doc)
    if args.check:
        current = args.output.read_text(encoding="utf-8") if args.output.exists() else ""
        if current != text:
            print(f"{args.output} is out of date; run tools/build_verses.py", file=sys.stderr)
            return 1
        print(f"{args.output} is up to date ({len(doc['verses'])} days)")
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {args.output} ({len(doc['verses'])} days)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
