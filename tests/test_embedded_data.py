"""The shipped versedesk/data/verses.json must cover every day with a sane BSB passage."""

import json
import re
from pathlib import Path

import pytest

from versedesk import paths
from versedesk.verses import all_date_keys, load_embedded

DATA = paths.embedded_verses_path()
REF_RE = re.compile(r"^(?:[1-3] )?[A-Z][A-Za-z ]+ \d+:\d+(?:–\d+)? \(BSB\)$")


@pytest.fixture(scope="module")
def doc():
    return json.loads(DATA.read_text(encoding="utf-8"))


def test_file_is_valid_and_complete(doc):
    entries = load_embedded(DATA)
    assert sorted(entries) == sorted(all_date_keys())
    assert len(doc["verses"]) == 366


def test_entries_are_in_calendar_order(doc):
    assert [v["date"] for v in doc["verses"]] == all_date_keys()


def test_references_look_right_and_are_unique(doc):
    refs = [v["reference"] for v in doc["verses"]]
    for r in refs:
        assert REF_RE.match(r), r
    assert len(set(refs)) == len(refs)


def test_texts_are_reasonable(doc):
    for v in doc["verses"]:
        t = v["text"]
        assert t == t.strip() and "  " not in t, v["date"]
        assert 20 <= len(t) <= 420, (v["date"], len(t))
        first = next(c for c in t if c.isalpha())
        assert first.isupper(), (v["date"], t[:30])
        assert t.rstrip("”’\"') ")[-1] in ".!?", (v["date"], t[-30:])
        assert not t.startswith(("A Psalm", "For the choirmaster", "A song of ascents", "Of David")), v["date"]


def test_provenance_is_recorded(doc):
    assert doc["source"]["file"] == "https://bereanbible.com/bsb.txt"
    assert len(doc["source"]["sha256"]) == 64
    assert "public domain" in doc["license"].lower()


def test_matches_official_source_when_available():
    """If the official files are present (tools/.cache), rebuilding must give the same file."""
    import subprocess
    import sys

    tools = Path(__file__).resolve().parent.parent / "tools"
    if not (tools / ".cache" / "bsb.txt").exists():
        pytest.skip("official BSB source not downloaded (python3 -I tools/bsb.py download)")
    r = subprocess.run([sys.executable, "-I", str(tools / "build_verses.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


# Special days keep their chosen passage (tools/seasonal.py and the review tools never move them).
SPECIAL_DAYS = {
    "01-01": "Lamentations 3:22",  # New Year: His mercies are new every morning
    "01-02": "Isaiah 43:19",
    "02-14": "1 Corinthians 13:4",
    "02-29": "Psalm 118:24",
    "03-01": "Galatians 5:1",
    "03-20": "Song of Solomon 2:11",
    "05-05": "Matthew 19:14",
    "05-08": "Exodus 20:12",
    "08-15": "John 8:36",
    "10-31": "Ephesians 2:8",
    "11-25": "Psalm 100:4",
    "12-24": "Isaiah 9:6",
    "12-25": "Luke 2:10",
    "12-31": "Psalm 90:12",
}


def test_special_days_keep_their_passages(doc):
    by_date = {v["date"]: v["reference"] for v in doc["verses"]}
    for date, start in SPECIAL_DAYS.items():
        ref = by_date[date]
        assert ref == f"{start} (BSB)" or ref.startswith(start + "–"), (date, ref)


def test_seasonal_arrangement_is_applied(tmp_path, monkeypatch):
    """tools/seasonal.py must not change the shipped plan: run it after every plan edit."""
    import importlib.util
    import sys

    tools = Path(__file__).resolve().parent.parent / "tools"
    plan = tools / "verse_plan.tsv"
    copy = tmp_path / "verse_plan.tsv"
    copy.write_bytes(plan.read_bytes())
    spec = importlib.util.spec_from_file_location("versedesk_seasonal", tools / "seasonal.py")
    seasonal = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seasonal)
    monkeypatch.setattr(sys, "argv", ["seasonal.py", str(copy)])
    seasonal.main()
    # compare lines, not bytes: a Windows checkout may use CRLF line endings
    assert copy.read_text(encoding="utf-8").splitlines() == plan.read_text(encoding="utf-8").splitlines()
    assert set(SPECIAL_DAYS) == seasonal.FIXED
