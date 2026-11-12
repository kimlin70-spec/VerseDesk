"""The data built into the exe: the default verse list, the whole BSB text, the psalm titles.

Everything here is checked offline: the compressed Bible must be the official bsb.txt byte for
byte (its SHA-256 is pinned in tools/bsb.py), and every built-in verse must be what the app's own
lookup finds in it.  (The CI "data" job also rebuilds all three files from the official download.)
"""

import hashlib
import json
import lzma
import re
import sys
from pathlib import Path

import pytest

from versedesk import paths
from versedesk.bible import Bible, parse_reference
from versedesk.verses import load_builtin

TOOLS = Path(__file__).resolve().parent.parent / "tools"
REF_RE = re.compile(r"^(?:[1-3] )?[A-Z][A-Za-z ]+ \d+:\d+(?:–\d+)? \(BSB\)$")


@pytest.fixture(scope="module")
def doc():
    return json.loads(paths.embedded_verses_path().read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def bible():
    return Bible.load()


def _pinned(name):
    sys.path.insert(0, str(TOOLS))
    try:
        import bsb
    finally:
        sys.path.remove(str(TOOLS))
    return bsb.SOURCES[name]["sha256"]


def test_the_built_in_bible_is_the_official_file_byte_for_byte():
    raw = lzma.decompress(paths.embedded_bible_path().read_bytes())
    assert hashlib.sha256(raw).hexdigest() == _pinned("bsb.txt")


def test_psalm_titles_come_from_the_pinned_usfm_and_sit_at_the_start_of_verse_1(bible):
    titles = json.loads(paths.embedded_psalm_titles_path().read_text(encoding="utf-8"))
    assert titles["source"]["sha256"] == _pinned("bsb_usfm.zip")
    assert len(titles["titles"]) == 116
    for number, title in titles["titles"].items():
        assert bible.verses[f"Psalm {number}:1"].startswith(title + " "), number
    assert bible.verse_text("Psalm", 23, 1) == "The LORD is my shepherd; I shall not want."


def test_the_default_list_has_30_to_50_unique_verses(doc):
    verses = load_builtin(paths.embedded_verses_path())
    assert 30 <= len(verses) <= 50
    assert [v.reference for v in verses] == [e["reference"] for e in doc["verses"]]
    refs = [v.reference for v in verses]
    assert len(set(refs)) == len(refs)
    for r in refs:
        assert REF_RE.match(r), r


def test_every_default_verse_is_exactly_what_the_lookup_finds(doc, bible):
    for e in doc["verses"]:
        ref = parse_reference(e["reference"])
        assert 1 <= ref.verse_count <= 3, e["reference"]
        found = bible.passage(ref)
        assert (found.reference, found.text) == (e["reference"], e["text"])


def test_texts_read_as_complete_thoughts(doc):
    for e in doc["verses"]:
        t = e["text"]
        assert t == t.strip() and "  " not in t, e["reference"]
        assert 20 <= len(t) <= 420, (e["reference"], len(t))
        first = next(c for c in t if c.isalpha())
        assert first.isupper(), (e["reference"], t[:30])
        assert t.rstrip("”’\"') ")[-1] in ".!?", (e["reference"], t[-30:])


def test_provenance_is_recorded(doc):
    assert doc["format"] == 2
    assert doc["source"]["file"] == "https://bereanbible.com/bsb.txt"
    assert doc["source"]["sha256"] == _pinned("bsb.txt")
    assert "public domain" in doc["license"].lower()


def test_matches_official_source_when_available():
    """If the official files are present (tools/.cache), rebuilding must give the same files."""
    import subprocess

    if not (TOOLS / ".cache" / "bsb.txt").exists():
        pytest.skip("official BSB source not downloaded (python3 -I tools/bsb.py download)")
    r = subprocess.run([sys.executable, "-I", str(TOOLS / "build_verses.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
