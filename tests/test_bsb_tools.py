"""Tests for the data tools (tools/bsb.py). Source-dependent tests skip when the official
files have not been downloaded (python3 -I tools/bsb.py download)."""

import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))

import bsb  # noqa: E402

HAVE_SOURCE = (TOOLS / ".cache" / "bsb.txt").exists() and (TOOLS / ".cache" / "bsb_usfm.zip").exists()


@pytest.mark.parametrize(
    "ref, key, display",
    [
        ("John 3:16", "John 3:16", "John 3:16"),
        ("Proverbs 3:5-6", "Proverbs 3:5-6", "Proverbs 3:5–6"),
        ("Psalms 23:1", "Psalm 23:1", "Psalm 23:1"),
        ("1 John 4:7–8", "1 John 4:7-8", "1 John 4:7–8"),
        ("Song of Songs 2:11-12", "Song of Solomon 2:11-12", "Song of Solomon 2:11–12"),
    ],
)
def test_parse_reference(ref, key, display):
    p = bsb.parse_reference(ref)
    assert (p.key, p.display) == (key, display)


@pytest.mark.parametrize("bad", ["Hezekiah 1:1", "John 3", "John 3:16-15", ""])
def test_parse_reference_rejects(bad):
    with pytest.raises(bsb.ReferenceError_):
        bsb.parse_reference(bad)


def test_overlap():
    a = bsb.parse_reference("John 3:16-17")
    assert a.overlaps(bsb.parse_reference("John 3:17"))
    assert not a.overlaps(bsb.parse_reference("John 3:18"))
    assert not a.overlaps(bsb.parse_reference("John 4:16"))


@pytest.mark.parametrize(
    "text, flags",
    [
        ("Trust in the LORD.", []),
        ("in all your ways acknowledge Him.", ["starts_lowercase"]),
        ("Trust in the LORD;", ["open_ending"]),
        ("“Come to Me, all you who are weary.”", []),
        ("Be strong; the LORD is with you.”", []),  # quote that began in an earlier verse
        ("My covenant will not be broken,” says the LORD.", []),  # ...and closes mid-passage
        ("“For as the heavens are higher than the earth.", ["unbalanced_double_quotes"]),
        ("He said, “Do not be afraid! I bring good news.", ["unbalanced_double_quotes"]),
        ("You are my hiding place. Selah I will instruct you.", ["selah"]),
        ("He makes my feet like those of a deer. For the choirmaster.", ["subscription"]),
    ],
)
def test_quality_flags(text, flags):
    assert bsb.quality_flags(text) == flags


@pytest.mark.skipif(not HAVE_SOURCE, reason="official BSB source not downloaded")
def test_official_text_and_superscriptions():
    b = bsb.Bible()
    assert len(b.verses) == 31102
    assert "public domain" in b.header[1]
    assert b.verse_text("Psalm 23:1") == "The LORD is my shepherd; I shall not want."
    assert b.verses["Psalm 23:1"].startswith("A Psalm of David. ")
    assert len(b.superscriptions) == 116
    with pytest.raises(bsb.ReferenceError_):
        b.passage_text(bsb.parse_reference("Matthew 17:21"))  # omitted variant: empty in BSB
