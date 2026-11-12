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
