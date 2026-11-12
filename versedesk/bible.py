"""The whole Berean Standard Bible (BSB), built into the exe, and the Bible references
people type into the verse list editor ("요 3:16", "시편 23편 1-3절", "John 3:16-17").

* versedesk/data/bsb.txt.xz is the official bsb.txt (https://bereanbible.com/bsb.txt),
  byte for byte, LZMA-compressed (about 1 MB).  Its SHA-256 is pinned in tools/bsb.py and
  checked by the tests, so the text in the exe is exactly the published text.
* bsb.txt glues each psalm's superscription ("A Psalm of David.") to the front of verse 1.
  versedesk/data/psalm_titles.json, taken from the official USFM files by
  tools/build_verses.py, lists them so they can be removed exactly (as in the built-in list).

The text is loaded only when the editor needs it (about 0.1 s, ~15 MB) and is dropped
again when the editor closes, so the resident app stays light.  Pure Python, no Qt.
"""

from __future__ import annotations

import json
import lzma
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from versedesk import paths
from versedesk.verses import Verse

TRANSLATION_TAG = "BSB"
MAX_PASSAGE_VERSES = 10
VERSE_COUNT = 31102


class ReferenceProblem(ValueError):
    """A reference that cannot be used; ``str(e)`` is a short Korean explanation."""


class BibleUnavailable(Exception):
    """The built-in Bible text is missing or damaged."""


@dataclass(frozen=True)
class Book:
    name: str  # exactly as in bsb.txt, e.g. "Psalm", "1 Corinthians"
    korean: tuple[str, ...]  # first = 개역개정 full name, then its abbreviation, then other forms
    english: tuple[str, ...] = ()  # other English names and abbreviations

    @property
    def korean_name(self) -> str:
        return self.korean[0]


def _b(name: str, korean: str, english: str = "") -> Book:
    return Book(name, tuple(korean.split()), tuple(a.strip() for a in english.split(",") if a.strip()))


# Korean: 개역개정 name and abbreviation first, then 새번역 forms and common shorthand.
# Spaces inside names do not matter ("요한 복음" = "요한복음"), so they are written without.
# (가톨릭 성경 names are left out on purpose: it numbers many Old Testament verses differently,
# e.g. psalm titles count as verses, so its references would silently give other verses.)
BOOKS: tuple[Book, ...] = (
    _b("Genesis", "창세기 창", "Gen, Ge, Gn"),
    _b("Exodus", "출애굽기 출", "Exod, Exo, Ex"),
    _b("Leviticus", "레위기 레", "Lev, Le, Lv"),
    _b("Numbers", "민수기 민", "Num, Nu, Nm, Nb"),
    _b("Deuteronomy", "신명기 신", "Deut, Dt, De"),
    _b("Joshua", "여호수아 수 여호수아기", "Josh, Jos, Jsh"),
    _b("Judges", "사사기 삿", "Judg, Jdg, Jg, Jdgs"),
    _b("Ruth", "룻기 룻", "Rth, Ru"),
    _b("1 Samuel", "사무엘상 삼상 사무엘기상", "1 Sam, 1 Sa, 1 Sm"),
    _b("2 Samuel", "사무엘하 삼하 사무엘기하", "2 Sam, 2 Sa, 2 Sm"),
    _b("1 Kings", "열왕기상 왕상", "1 Kgs, 1 Ki, 1 Kin"),
    _b("2 Kings", "열왕기하 왕하", "2 Kgs, 2 Ki, 2 Kin"),
    _b("1 Chronicles", "역대상 대상 역대지상", "1 Chr, 1 Chron, 1 Ch"),
    _b("2 Chronicles", "역대하 대하 역대지하", "2 Chr, 2 Chron, 2 Ch"),
    _b("Ezra", "에스라 스 에스라기", "Ezr"),
    _b("Nehemiah", "느헤미야 느 느헤미야기", "Neh, Ne"),
    _b("Esther", "에스더 에 에스더기", "Esth, Est"),
    _b("Job", "욥기 욥", "Jb"),
    _b("Psalm", "시편 시", "Psalms, Ps, Psa, Pss, Psm"),
    _b("Proverbs", "잠언 잠", "Prov, Pro, Prv, Pr"),
    _b("Ecclesiastes", "전도서 전", "Eccl, Eccles, Ecc, Ec, Qoh"),
    _b("Song of Solomon", "아가 아 아가서", "Song of Songs, Song, Songs, SOS, Canticles"),
    _b("Isaiah", "이사야 사 이사야서", "Isa, Is"),
    _b("Jeremiah", "예레미야 렘 예레미야서 예레", "Jer, Je, Jr"),
    _b("Lamentations", "예레미야애가 애 애가", "Lam, La"),
    _b("Ezekiel", "에스겔 겔 에스겔서", "Ezek, Eze, Ezk"),
    _b("Daniel", "다니엘 단 다니엘서", "Dan, Da, Dn"),
    _b("Hosea", "호세아 호 호세아서", "Hos, Ho"),
    _b("Joel", "요엘 욜 요엘서", "Jl"),
    _b("Amos", "아모스 암 아모스서", "Am"),
    _b("Obadiah", "오바댜 옵 오바댜서", "Obad, Ob"),
    _b("Jonah", "요나 욘 요나서", "Jon, Jnh"),
    _b("Micah", "미가 미 미가서", "Mic, Mc"),
    _b("Nahum", "나훔 나 나훔서", "Nah, Na"),
    _b("Habakkuk", "하박국 합 하박국서", "Hab, Hb"),
    _b("Zephaniah", "스바냐 습 스바냐서", "Zeph, Zep, Zp"),
    _b("Haggai", "학개 학 학개서", "Hag, Hg"),
    _b("Zechariah", "스가랴 슥 스가랴서", "Zech, Zec, Zc"),
    _b("Malachi", "말라기 말 말라기서", "Mal, Ml"),
    _b("Matthew", "마태복음 마 마태복음서", "Matt, Mat, Mt"),
    _b("Mark", "마가복음 막 마가복음서", "Mrk, Mar, Mk, Mr"),
    _b("Luke", "누가복음 눅 누가복음서", "Luk, Lk"),
    _b("John", "요한복음 요 요한복음서 요한", "Jhn, Joh, Jn"),
    _b("Acts", "사도행전 행", "Act, Ac"),
    _b("Romans", "로마서 롬", "Rom, Ro, Rm"),
    _b("1 Corinthians", "고린도전서 고전", "1 Cor, 1 Co"),
    _b("2 Corinthians", "고린도후서 고후", "2 Cor, 2 Co"),
    _b("Galatians", "갈라디아서 갈", "Gal, Ga"),
    _b("Ephesians", "에베소서 엡", "Eph, Ephes"),
    _b("Philippians", "빌립보서 빌", "Phil, Php"),
    _b("Colossians", "골로새서 골", "Col"),
    _b("1 Thessalonians", "데살로니가전서 살전", "1 Thess, 1 Thes, 1 Th"),
    _b("2 Thessalonians", "데살로니가후서 살후", "2 Thess, 2 Thes, 2 Th"),
    _b("1 Timothy", "디모데전서 딤전", "1 Tim, 1 Ti"),
    _b("2 Timothy", "디모데후서 딤후", "2 Tim, 2 Ti"),
    _b("Titus", "디도서 딛", "Tit"),
    _b("Philemon", "빌레몬서 몬", "Philem, Phm"),
    _b("Hebrews", "히브리서 히", "Heb"),
    _b("James", "야고보서 약", "Jas, Jm"),
    _b("1 Peter", "베드로전서 벧전", "1 Pet, 1 Pe, 1 Pt"),
    _b("2 Peter", "베드로후서 벧후", "2 Pet, 2 Pe, 2 Pt"),
    _b("1 John", "요한일서 요일 요한1서", "1 Jn, 1 Jhn, 1 Joh, 1 Jo"),
    _b("2 John", "요한이서 요이 요한2서", "2 Jn, 2 Jhn, 2 Joh, 2 Jo"),
    _b("3 John", "요한삼서 요삼 요한3서", "3 Jn, 3 Jhn, 3 Joh, 3 Jo"),
    _b("Jude", "유다서 유", "Jd"),
    _b("Revelation", "요한계시록 계 계시록", "Rev, Re, Rv, Revelations"),
)

BOOK_NAMES = tuple(b.name for b in BOOKS)
BOOKS_BY_NAME = {b.name: b for b in BOOKS}
SINGLE_CHAPTER_BOOKS = frozenset({"Obadiah", "Philemon", "2 John", "3 John", "Jude"})

_ROMAN = {"i": "1", "ii": "2", "iii": "3", "first": "1", "second": "2", "third": "3",
          "1st": "1", "2nd": "2", "3rd": "3"}
_NUMBER_WORD = re.compile(r"^(iii|ii|i|first|second|third|1st|2nd|3rd)[\s.]+(?=[a-z])")


def name_key(name: str) -> str:
    """Comparison key for a book name: no case, spaces or dots; 'I John' = '1 John'."""
    s = unicodedata.normalize("NFKC", name).casefold().strip()
    m = _NUMBER_WORD.match(s)
    if m:
        s = _ROMAN[m.group(1)] + s[m.end():]
    return re.sub(r"[\s.·]+", "", s)


def _build_index() -> tuple[dict[str, str], list[tuple[str, str]]]:
    exact: dict[str, str] = {}
    full: list[tuple[str, str]] = []  # (key of a full name, book) for prefix matching
    for b in BOOKS:
        names = [b.name, *b.english, *b.korean]
        for n in names:
            k = name_key(n)
            if exact.get(k, b.name) != b.name:
                raise AssertionError(f"book name {n!r} is used for {exact[k]} and {b.name}")
            exact[k] = b.name
        # full names (not abbreviations) take part in prefix matching: "요한계" -> 요한계시록
        for n in [b.name, *(k for k in b.korean if len(k) >= 3)]:
            full.append((name_key(n), b.name))
    return exact, full


_EXACT, _FULL = _build_index()


def _particle(word: str, with_final: str, without_final: str) -> str:
    """The particle that fits after ``word``: ('요한복음', 은, 는) -> 은; unknown ending -> 은(는)."""
    last = word.rstrip()[-1:]
    if "가" <= last <= "힣":
        return with_final if (ord(last) - 0xAC00) % 28 else without_final
    return f"{with_final}({without_final})"


def _korean_particle(word: str, with_final: str, without_final: str) -> str:
    """'요한복음' + 은/는 -> '요한복음은'."""
    return word + _particle(word, with_final, without_final)


def resolve_book(text: str) -> str:
    """The bsb.txt book name for what the user typed, or ReferenceProblem."""
    shown = " ".join(text.split())
    key = name_key(text)
    if not key:
        raise ReferenceProblem("책 이름이 없습니다. 예) 요 3:16, John 3:16")
    if key in _EXACT:
        return _EXACT[key]
    found: list[str] = []
    if len(key) >= 2:
        for full_key, book in _FULL:
            bare = full_key.lstrip("123")
            if (full_key.startswith(key) or bare.startswith(key)) and book not in found:
                found.append(book)
    if len(found) == 1:
        return found[0]
    if found:
        names = ", ".join(BOOKS_BY_NAME[b].korean_name for b in found[:6])
        raise ReferenceProblem(f"'{shown}'에 맞는 책이 여러 권입니다({names}). 조금 더 적어 주세요.")
    raise ReferenceProblem(f"'{shown}'{_particle(shown, '은', '는')} 알 수 없는 책 이름입니다. 예) 요, 요한복음, John")


@dataclass(frozen=True)
class Reference:
    book: str
    chapter: int
    first: int
    last: int
    note: str = ""  # e.g. "한글 성경 고후 13:13" when Korean numbering was translated to BSB's

    @property
    def verse_count(self) -> int:
        return self.last - self.first + 1

    @property
    def display(self) -> str:
        """'John 3:16' or 'Psalm 23:1–3' (en dash, like the built-in list)."""
        verses = str(self.first) if self.first == self.last else f"{self.first}–{self.last}"
        return f"{self.book} {self.chapter}:{verses}"

    @property
    def label(self) -> str:
        return f"{self.display} ({TRANSLATION_TAG})"


# Korean Protestant Bibles (개역개정, 새번역) number two places differently from the BSB (and
# other English Bibles); everywhere else the numbers agree.  Korean verse -> BSB verses:
#   2 Corinthians 13: 12 = BSB 12-13 ("Greet one another..." + "All the saints..."),
#                     13 = BSB 14 (the benediction, 축도 "고후 13:13")
#   3 John 1:         15 = the end of BSB 14 ("Peace to you...")
KOREAN_NUMBERING = {
    ("2 Corinthians", 13): {12: (12, 13), 13: (14, 14)},
    ("3 John", 1): {15: (14, 14)},
}
KOREAN_LAST_VERSE = {("2 Corinthians", 13): 13, ("3 John", 1): 15}  # where the Korean count differs


def korean_to_bsb(book: str, chapter: int, first: int, last: int) -> tuple[int, int]:
    table = KOREAN_NUMBERING.get((book, chapter), {})
    return table.get(first, (first, first))[0], table.get(last, (last, last))[1]


_DASH = r"(?:-|~|–|—|‒|―|〜|∼|‐|−|⁓)"  # incl. the KS X 1001 물결표 ∼ from Korean documents
_SEP = r"(?::|\.|장|편)"
_TAIL_CHAPTER_VERSE = re.compile(
    rf"(?P<ch>\d{{1,3}})\s*{_SEP}\s*(?P<v1>\d{{1,3}})\s*절?"
    rf"(?:\s*{_DASH}\s*(?:(?P<ch2>\d{{1,3}})\s*{_SEP}\s*)?(?P<v2>\d{{1,3}})\s*절?)?\s*$"
)
_TAIL_VERSE_ONLY = re.compile(rf"(?P<v1>\d{{1,3}})\s*(?P<unit>장|편|절)?(?:\s*{_DASH}\s*(?P<v2>\d{{1,3}})\s*절?)?\s*$")
_TRAILING_NOTE = re.compile(r"\s*[(\[][^()\[\]]*[)\]]\s*$")  # "John 3:16 (BSB)"
_OPENERS = "([{<「『《〈【“‘\"'"
_CLOSERS = ")]}>」』》〉】”’\"'"
_HANGUL = re.compile(r"[가-힣]")
_ANOTHER_REFERENCE = re.compile(r"\d\s*[:.장편]\s*\d")
EXAMPLE = "예) 요 3:16, 시 23:1-3, John 3:16"
SEVERAL = "여러 구절은 쉼표(,)로 나눠 주세요. 예) 요 3:16, 롬 8:28"


def _unwrap(s: str) -> str:
    """'(롬 8:28)', '「롬 8:28」' -> '롬 8:28'; 'John 3:16 (BSB)' -> 'John 3:16'."""
    s = s.strip()
    while len(s) >= 2 and s[0] in _OPENERS and s[-1] in _CLOSERS:
        s = s[1:-1].strip()
    stripped = _TRAILING_NOTE.sub("", s).strip()
    return stripped or s


def _book_part(text: str) -> str:
    book_text = text.strip(" ,")
    if _ANOTHER_REFERENCE.search(book_text):  # "요 3:16 롬 8:28": two references without a comma
        raise ReferenceProblem(SEVERAL)
    return book_text


def parse_reference(text: str) -> Reference:
    """Read one reference such as '요 3:16', '시편 23편 1-3절', '1 Cor 13:13', 'Jude 24'.
    Korean book names use Korean verse numbers (see KOREAN_NUMBERING)."""
    s = _unwrap(unicodedata.normalize("NFKC", text or ""))
    if not s:
        raise ReferenceProblem(f"구절 주소를 적어 주세요. {EXAMPLE}")
    m = _TAIL_CHAPTER_VERSE.search(s)
    if m:
        book_text = _book_part(s[: m.start()])
        book = resolve_book(book_text)
        chapter, first = int(m.group("ch")), int(m.group("v1"))
        last = int(m.group("v2")) if m.group("v2") else first
        if m.group("ch2") and int(m.group("ch2")) != chapter:
            raise ReferenceProblem("한 장 안의 구절만 넣을 수 있습니다. 예) 요 3:16-18")
    else:
        m = _TAIL_VERSE_ONLY.search(s)
        if not m or not s[: m.start()].strip(" ,"):
            raise ReferenceProblem(f"장과 절을 찾지 못했습니다. {EXAMPLE}")
        book_text = _book_part(s[: m.start()])
        if book_text[-1:].isdigit():  # "요 3 16": a space instead of ':'
            raise ReferenceProblem("장과 절 사이에 ':'를 넣어 주세요. 예) 요 3:16")
        book = resolve_book(book_text)
        number, unit = int(m.group("v1")), m.group("unit")
        ko = BOOKS_BY_NAME[book].korean[1]
        if book in SINGLE_CHAPTER_BOOKS and unit in ("장", "편"):
            whole = _korean_particle(BOOKS_BY_NAME[book].korean_name, "은", "는")
            raise ReferenceProblem(f"{whole} 1장뿐입니다. 절 번호만 적어 주세요. 예) {ko} 1:{max(number, 1)}")
        if book not in SINGLE_CHAPTER_BOOKS:
            if unit == "절":
                raise ReferenceProblem(f"장도 함께 적어 주세요. {EXAMPLE}")
            raise ReferenceProblem(f"절도 함께 적어 주세요. 예) {ko} {max(number, 1)}:1")
        chapter, first = 1, number
        last = int(m.group("v2")) if m.group("v2") else first
    if chapter < 1 or first < 1:
        raise ReferenceProblem("장과 절은 1부터 셉니다.")
    if last < first:
        raise ReferenceProblem(f"범위가 거꾸로입니다: {first}-{last} → {last}-{first}")
    if last - first + 1 > MAX_PASSAGE_VERSES:
        raise ReferenceProblem(f"한 번에 {MAX_PASSAGE_VERSES}절까지 넣을 수 있습니다.")
    note = ""
    if _HANGUL.search(book_text):
        korean_last = KOREAN_LAST_VERSE.get((book, chapter))
        if korean_last is not None and last > korean_last:
            where = f"{BOOKS_BY_NAME[book].korean_name} {chapter}장"
            raise ReferenceProblem(f"{_korean_particle(where, '은', '는')} {korean_last}절까지 있습니다(한글 성경).")
        bsb_first, bsb_last = korean_to_bsb(book, chapter, first, last)
        if (bsb_first, bsb_last) != (first, last):
            typed = str(first) if first == last else f"{first}-{last}"
            note = f"한글 성경 {BOOKS_BY_NAME[book].korean[1]} {chapter}:{typed}"
            first, last = bsb_first, bsb_last
    return Reference(book, chapter, first, last, note)


_SEPARATORS = set(",;，；、·・/\n\r")
_BRACKETS = {"(": ")", "[": "]", "{": "}", "（": "）", "［": "］", "「": "」", "『": "』", "《": "》", "〈": "〉", "【": "】"}


def _split(text: str, mind_brackets: bool) -> tuple[list[str], bool]:
    """Split at separators outside brackets. Returns (pieces, brackets balanced)."""
    pieces, current, closers = [], [], []
    for ch in text:
        if mind_brackets and ch in _BRACKETS:
            closers.append(_BRACKETS[ch])
        elif mind_brackets and closers and ch == closers[-1]:
            closers.pop()
        elif ch in _SEPARATORS and not closers:
            pieces.append("".join(current))
            current = []
            continue
        current.append(ch)
    pieces.append("".join(current))
    return pieces, not closers


def _without_enclosing_brackets(text: str) -> str:
    """'(롬 8:28, 요 3:16)' -> '롬 8:28, 요 3:16', but '(롬 8:28), (요 3:16)' is left as it is."""
    s = text.strip()
    while len(s) >= 2 and s[0] in _BRACKETS:
        closers = []
        for i, ch in enumerate(s):
            if ch in _BRACKETS:
                closers.append(_BRACKETS[ch])
            elif closers and ch == closers[-1]:
                closers.pop()
                if not closers:
                    break
        if closers or i != len(s) - 1:  # unbalanced, or the first bracket closes before the end
            return s
        s = s[1:-1].strip()
    return s


def split_references(text: str) -> list[str]:
    """Several references typed or pasted at once: '요 3:16, 롬 8:28; 시 23:1 / 창 1:1'.
    Separators inside brackets belong to a note: '요 3:16 (개역개정/새번역)' stays one piece."""
    s = _without_enclosing_brackets(text or "")
    pieces, balanced = _split(s, mind_brackets=True)
    if not balanced:  # a bracket that never closes must not swallow the rest
        pieces, _ = _split(s, mind_brackets=False)
    return [p.strip() for p in pieces if p.strip()]


class Bible:
    def __init__(self, verses: dict[str, str], titles: dict[int, str] | None = None):
        self.verses = verses  # "John 3:16" -> text, as in bsb.txt
        self.titles = dict(titles or {})  # psalm number -> superscription at the start of verse 1
        self.last_verse: dict[tuple[str, int], int] = {}
        self.last_chapter: dict[str, int] = {}
        for ref in verses:
            book, _, cv = ref.rpartition(" ")
            c, _, v = cv.partition(":")
            ch, vn = int(c), int(v)
            if vn > self.last_verse.get((book, ch), 0):
                self.last_verse[(book, ch)] = vn
            if ch > self.last_chapter.get(book, 0):
                self.last_chapter[book] = ch

    @classmethod
    def load(cls, text_path: Path | None = None, titles_path: Path | None = None) -> "Bible":
        text_path = text_path or paths.embedded_bible_path()
        titles_path = titles_path or paths.embedded_psalm_titles_path()
        try:
            raw = lzma.decompress(Path(text_path).read_bytes())
            titles_doc = json.loads(Path(titles_path).read_text(encoding="utf-8"))
        except (OSError, lzma.LZMAError, ValueError) as e:
            raise BibleUnavailable(f"built-in Bible text unreadable: {type(e).__name__}: {e}") from e
        return cls(*parse_bsb_text(raw, titles_doc))

    def verse_text(self, book: str, chapter: int, verse: int) -> str:
        text = self.verses.get(f"{book} {chapter}:{verse}", "")
        title = self.titles.get(chapter) if book == "Psalm" and verse == 1 else None
        if title and text.startswith(title + " "):
            text = text[len(title) + 1:]
        return text

    def passage(self, ref: Reference) -> Verse:
        b = BOOKS_BY_NAME[ref.book]
        last_ch = self.last_chapter.get(ref.book, 0)
        if ref.chapter > last_ch:
            unit = "편" if ref.book == "Psalm" else "장"
            raise ReferenceProblem(f"{_korean_particle(b.korean_name, '은', '는')} {last_ch}{unit}까지 있습니다.")
        last_v = self.last_verse[(ref.book, ref.chapter)]
        if ref.last > last_v:
            unit = "편" if ref.book == "Psalm" else "장"
            where = f"{b.korean_name} {ref.chapter}{unit}"
            raise ReferenceProblem(f"{_korean_particle(where, '은', '는')} {last_v}절까지 있습니다.")
        parts = [t for t in (self.verse_text(ref.book, ref.chapter, v) for v in range(ref.first, ref.last + 1))
                 if t.strip()]
        if not parts:
            raise ReferenceProblem("이 절은 BSB 본문에 없습니다(사본에 따라 빠진 절).")
        return Verse(ref.label, " ".join(parts), "user")

    def lookup(self, text: str) -> Verse:
        return self.passage(parse_reference(text))


def parse_bsb_text(raw: bytes, titles_doc: dict) -> tuple[dict[str, str], dict[int, str]]:
    """bsb.txt (UTF-8 with BOM, CRLF, three header lines, 'Book C:V<TAB>text')."""
    text = raw.decode("utf-8-sig")
    lines = text.split("\r\n")
    if len(lines) < 4 or not lines[2].startswith("Verse\tBerean Standard Bible"):
        raise BibleUnavailable("built-in Bible text has an unexpected header")
    verses: dict[str, str] = {}
    names = set(BOOK_NAMES)
    for ln in lines[3:]:
        if not ln:
            continue
        ref, sep, verse = ln.partition("\t")
        book, _, cv = ref.rpartition(" ")
        if not sep or book not in names or not re.fullmatch(r"\d+:\d+", cv):
            raise BibleUnavailable(f"built-in Bible text has a malformed line: {ln[:40]!r}")
        verses[ref] = verse
    if len(verses) != VERSE_COUNT:
        raise BibleUnavailable(f"built-in Bible text has {len(verses)} verses, expected {VERSE_COUNT}")
    titles = {int(k): v for k, v in (titles_doc.get("titles") or {}).items()}
    return verses, titles
