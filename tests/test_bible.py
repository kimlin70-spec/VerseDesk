"""References typed in the verse list editor, and lookups in the built-in BSB text."""

import sys
from pathlib import Path

import pytest

from versedesk.bible import (
    BOOKS,
    MAX_PASSAGE_VERSES,
    SINGLE_CHAPTER_BOOKS,
    Bible,
    ReferenceProblem,
    name_key,
    parse_reference,
    resolve_book,
    split_references,
)

TOOLS = Path(__file__).resolve().parent.parent / "tools"


@pytest.fixture(scope="module")
def bible():
    return Bible.load()


@pytest.mark.parametrize(
    "typed, label",
    [
        ("요 3:16", "John 3:16 (BSB)"),
        ("요3:16", "John 3:16 (BSB)"),
        ("요한복음 3장 16절", "John 3:16 (BSB)"),
        ("요한 복음 3:16-17", "John 3:16–17 (BSB)"),
        ("요 3:16~17", "John 3:16–17 (BSB)"),
        ("요 3：16", "John 3:16 (BSB)"),  # full-width colon (Korean keyboards)
        ("시 23:1-3", "Psalm 23:1–3 (BSB)"),
        ("시편 23편 1~3절", "Psalm 23:1–3 (BSB)"),
        ("시 23:1절", "Psalm 23:1 (BSB)"),
        ("John 3:16", "John 3:16 (BSB)"),
        ("Jn 3:16", "John 3:16 (BSB)"),
        ("john 3.16", "John 3:16 (BSB)"),
        ("psalm 23:1 (BSB)", "Psalm 23:1 (BSB)"),
        ("Psalms 23:1", "Psalm 23:1 (BSB)"),
        ("Ps. 23:1", "Psalm 23:1 (BSB)"),
        ("1 Cor 13:13", "1 Corinthians 13:13 (BSB)"),
        ("1Co 13:4-7", "1 Corinthians 13:4–7 (BSB)"),
        ("I John 4:8", "1 John 4:8 (BSB)"),
        ("First John 4:8", "1 John 4:8 (BSB)"),
        ("요일 4:8", "1 John 4:8 (BSB)"),
        ("요한1서 4:8", "1 John 4:8 (BSB)"),
        ("요한 일서 4:8", "1 John 4:8 (BSB)"),
        ("유 24-25", "Jude 1:24–25 (BSB)"),
        ("Jude 24", "Jude 1:24 (BSB)"),
        ("3 John 2", "3 John 1:2 (BSB)"),
        ("요삼 2", "3 John 1:2 (BSB)"),
        ("몬 6", "Philemon 1:6 (BSB)"),
        ("옵 1:15", "Obadiah 1:15 (BSB)"),
        ("아 2:11", "Song of Solomon 2:11 (BSB)"),
        ("Song of Songs 2:11", "Song of Solomon 2:11 (BSB)"),
        ("애 3:22-23", "Lamentations 3:22–23 (BSB)"),
        ("삼상 3:10", "1 Samuel 3:10 (BSB)"),
        ("Philip 4:13", "Philippians 4:13 (BSB)"),
        ("Phile 1:6", "Philemon 1:6 (BSB)"),
        ("Gen. 1:1", "Genesis 1:1 (BSB)"),
        ("요한계 21:4", "Revelation 21:4 (BSB)"),  # a clear beginning of a name is enough
        ("이사야서 40:31", "Isaiah 40:31 (BSB)"),  # 새번역 names
        ("역대지하 7:14", "2 Chronicles 7:14 (BSB)"),
        ("(롬 8:28)", "Romans 8:28 (BSB)"),  # as written in bulletins and sermon notes
        ("「롬 8:28」", "Romans 8:28 (BSB)"),
        ("시 23:1∼3", "Psalm 23:1–3 (BSB)"),  # KS X 1001 물결표 from Korean documents
        ("시 23:1‐3", "Psalm 23:1–3 (BSB)"),
        ("시 23:1−3", "Psalm 23:1–3 (BSB)"),
        # Korean Bibles number these two places differently from the BSB (English numbering)
        ("고후 13:13", "2 Corinthians 13:14 (BSB)"),  # the benediction (축도)
        ("고린도후서 13장 13절", "2 Corinthians 13:14 (BSB)"),
        ("고후 13:12", "2 Corinthians 13:12–13 (BSB)"),
        ("고후 13:11-13", "2 Corinthians 13:11–14 (BSB)"),
        ("2 Cor 13:13", "2 Corinthians 13:13 (BSB)"),  # English input keeps English numbers
        ("요삼 1:15", "3 John 1:14 (BSB)"),
        ("요한삼서 14-15", "3 John 1:14 (BSB)"),
        ("마 17:20-21", "Matthew 17:20–21 (BSB)"),  # 17:21 is empty in the BSB: skipped
    ],
)
def test_references_people_type(bible, typed, label):
    assert bible.lookup(typed).reference == label


@pytest.mark.parametrize(
    "typed, says",
    [
        ("", "적어 주세요"),
        ("요 3", "절도 함께"),
        ("시 23편", "절도 함께"),
        ("요 16절", "장도 함께"),
        ("몬 6장", "빌레몬서는 1장뿐입니다"),
        ("요 3 16", "':'를 넣어"),
        ("요한 3 5", "':'를 넣어"),  # not 3 John 1:5 by accident
        ("요 3:16 롬 8:28", "쉼표"),
        ("요 3:16 · 롬 8:28", "쉼표"),
        ("탈출기 3:14", "알 수 없는 책"),  # 가톨릭 성경 numbering differs, so its names are not taken
        ("루카 2:10", "'루카'는 알 수 없는"),
        ("3:16", "책 이름이 없습니다"),
        ("Hezekiah 1:1", "알 수 없는 책"),
        ("Jo 3:16", "여러 권"),
        ("사무엘 3:10", "여러 권"),
        ("요 3:16-4:2", "한 장 안의"),
        ("요 3:18-16", "거꾸로"),
        (f"요 3:1-{MAX_PASSAGE_VERSES + 1}", f"{MAX_PASSAGE_VERSES}절까지"),
        ("요 3:0", "1부터"),
        ("요 3:16a", "찾지 못했습니다"),
    ],
)
def test_problems_are_explained_in_korean(typed, says):
    with pytest.raises(ReferenceProblem) as e:
        parse_reference(typed)
    assert says in str(e.value)


@pytest.mark.parametrize(
    "typed, says",
    [
        ("요 22:1", "요한복음은 21장까지"),
        ("요 3:99", "요한복음 3장은 36절까지"),
        ("시 151:1", "시편은 150편까지"),
        ("사사기 22:1", "사사기는 21장까지"),
        ("유 2:1", "유다서는 1장까지"),
        ("마 17:21", "BSB 본문에 없습니다"),
    ],
)
def test_verses_that_do_not_exist(bible, typed, says):
    with pytest.raises(ReferenceProblem) as e:
        bible.lookup(typed)
    assert says in str(e.value)


def test_psalm_titles_are_not_part_of_verse_1(bible):
    assert bible.lookup("시 23:1").text == "The LORD is my shepherd; I shall not want."
    assert bible.lookup("시 51:1").text.startswith("Have mercy on me, O God")
    assert bible.lookup("시 1:1").text.startswith("Blessed is the man")  # psalm 1 has no title


def test_several_references_at_once():
    assert split_references("요 3:16, 롬 8:28; 시 23:1\n창 1:1，요일 4:8") == [
        "요 3:16", "롬 8:28", "시 23:1", "창 1:1", "요일 4:8"]
    assert split_references("요 3:16 · 롬 8:28 / 창 1:1") == ["요 3:16", "롬 8:28", "창 1:1"]
    assert split_references(" , ") == []


def test_notes_in_brackets_keep_their_separators():
    assert split_references("요 3:16 (개역개정/새번역)") == ["요 3:16 (개역개정/새번역)"]
    assert split_references("John 3:16 (NIV/ESV), Rom 8:28") == ["John 3:16 (NIV/ESV)", "Rom 8:28"]
    assert split_references("(롬 8:28, 요 3:16)") == ["롬 8:28", "요 3:16"]
    assert split_references("(롬 8:28), (요 3:16)") == ["(롬 8:28)", "(요 3:16)"]
    assert split_references("요 3:16 (not closed, 롬 8:28") == ["요 3:16 (not closed", "롬 8:28"]


@pytest.mark.parametrize("typed, says", [
    ("고후 13:14", "고린도후서 13장은 13절까지 있습니다(한글 성경)"),
    ("요삼 1:16", "요한삼서 1장은 15절까지 있습니다(한글 성경)"),
])
def test_korean_verse_counts_where_they_differ(typed, says):
    with pytest.raises(ReferenceProblem) as e:
        parse_reference(typed)
    assert says in str(e.value)
    assert parse_reference("2 Cor 13:14").last == 14  # English numbers are BSB's


def test_korean_numbering_is_noted():
    ref = parse_reference("고후 13:13")
    assert (ref.first, ref.last, ref.note) == (14, 14, "한글 성경 고후 13:13")
    assert parse_reference("2 Cor 13:13").note == ""
    assert parse_reference("고후 13:10").note == ""  # unaffected verses keep their numbers


def test_the_longest_passage_survives_a_round_trip_through_the_file(bible):
    """10 verses can be ~2,300 characters (e.g. 2 Kings 23:2-11): nothing may be cut on reload."""
    from versedesk.verses import list_document, parse_list
    import json

    v = bible.lookup("왕하 23:2-11")
    assert len(v.text) > 2000
    back = parse_list(json.loads(list_document([v])), "user")
    assert back.warnings == [] and back.verses[0].text == v.text


def test_every_book_has_a_unique_korean_and_english_form():
    assert len(BOOKS) == 66
    seen = {}
    for b in BOOKS:
        for name in (b.name, *b.korean, *b.english):
            k = name_key(name)
            assert seen.setdefault(k, b.name) == b.name, (name, seen[k], b.name)
        assert resolve_book(b.name) == b.name
        assert resolve_book(b.korean_name) == b.name
        assert resolve_book(b.korean[1]) == b.name  # 개역개정 abbreviation


def test_book_list_matches_the_text(bible):
    assert set(bible.last_chapter) == {b.name for b in BOOKS}
    assert {b for b, n in bible.last_chapter.items() if n == 1} == SINGLE_CHAPTER_BOOKS
    assert bible.last_chapter["Psalm"] == 150 and bible.last_verse[("John", 3)] == 36


def test_whole_bible_matches_the_build_tools_when_the_source_is_available(bible):
    """The app's own reader must give exactly the text the data tools give (31,102 verses)."""
    if not (TOOLS / ".cache" / "bsb.txt").exists():
        pytest.skip("official BSB source not downloaded (python3 -I tools/bsb.py download)")
    sys.path.insert(0, str(TOOLS))
    try:
        import bsb
    finally:
        sys.path.remove(str(TOOLS))
    tools_bible = bsb.Bible()
    for ref in tools_bible.verses:
        book, _, cv = ref.rpartition(" ")
        c, _, v = cv.partition(":")
        assert bible.verse_text(book, int(c), int(v)) == tools_bible.verse_text(ref), ref


def test_a_damaged_file_is_reported(tmp_path):
    from versedesk.bible import BibleUnavailable

    bad = tmp_path / "bsb.txt.xz"
    bad.write_bytes(b"not lzma")
    with pytest.raises(BibleUnavailable):
        Bible.load(bad)
