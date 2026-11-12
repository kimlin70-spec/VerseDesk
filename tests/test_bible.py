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
        ("1요한 4:8", "1 John 4:8 (BSB)"),
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
        ("탈출기 3:14", "Exodus 3:14 (BSB)"),  # 가톨릭 성경 names work too
        ("루카 2:10", "Luke 2:10 (BSB)"),
        ("요한계 21:4", "Revelation 21:4 (BSB)"),  # a clear beginning of a name is enough
        ("마 17:20-21", "Matthew 17:20–21 (BSB)"),  # 17:21 is empty in the BSB: skipped
    ],
)
def test_references_people_type(bible, typed, label):
    assert bible.lookup(typed).reference == label


@pytest.mark.parametrize(
    "typed, says",
    [
        ("", "적어 주세요"),
        ("요 3", "장과 절을 함께"),
        ("시 23편", "장과 절을 함께"),
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
    assert split_references(" , ") == []


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
