"""The verse list file: reading it safely, writing it back, telling an old date file apart."""

import json

from versedesk.verses import (
    MAX_VERSES,
    Verse,
    list_document,
    load_verse_file,
    parse_list,
)


def test_a_list_keeps_its_order_and_accepts_a_bare_list():
    data = {"verses": [{"reference": "B 2:2", "text": "Second?"}, {"reference": "A 1:1", "text": "First?"}]}
    r = parse_list(data, "user")
    assert r.error is None and r.warnings == []
    assert [v.reference for v in r.verses] == ["B 2:2", "A 1:1"]
    assert [v.source for v in r.verses] == ["user", "user"]
    assert [v.text for v in parse_list([{"text": "Only text."}], "user").verses] == ["Only text."]


def test_invalid_entries_are_skipped_with_warnings():
    data = {"verses": [
        "not an object",
        {"reference": "No text"},
        {"reference": "Empty", "text": "   "},
        {"reference": 5, "text": "Bad reference is dropped,\n text kept."},
        {"text": "x" * 5000},
    ]}
    r = parse_list(data, "user")
    assert len(r.warnings) == 4 and r.error is None
    assert r.verses[0] == Verse("", "Bad reference is dropped, text kept.", "user")
    assert len(r.verses[1].text) == 3000 and "was cut" in r.warnings[-1]
    assert (r.skipped, r.cut) == (3, 1)


def test_wrong_top_level_shape_is_an_error():
    assert parse_list({"days": []}, "user").error
    assert parse_list("text", "user").error


def test_the_old_one_verse_per_date_format_is_recognised():
    old = {"안내": "...", "verses": [{"date": "01-01", "reference": "R", "text": "T"}]}
    r = parse_list(old, "user")
    assert r.dated and r.verses == []


def test_too_many_verses_are_capped():
    r = parse_list([{"text": f"v{i}"} for i in range(MAX_VERSES + 5)], "user")
    assert len(r.verses) == MAX_VERSES and r.warnings


def test_round_trip_through_the_saved_file(tmp_path):
    verses = [Verse("John 3:16 (BSB)", "For God so loved the world …", "user"), Verse("", "“내 묵상” 본문", "user")]
    p = tmp_path / "verses.json"
    p.write_text(list_document(verses), encoding="utf-8")
    data = json.loads(p.read_text(encoding="utf-8"))
    assert "안내" in data and data["verses"][0] == {"reference": "John 3:16 (BSB)", "text": "For God so loved the world …"}
    back = load_verse_file(p, "user")
    assert back.error is None and back.verses == verses


def test_a_locked_file_is_reported_as_unreadable_not_broken(tmp_path, monkeypatch):
    import versedesk.verses as verses_module

    p = tmp_path / "verses.json"
    p.write_text(list_document([Verse("A 1:1", "Alpha.", "user")]), encoding="utf-8")
    calls = []

    def locked(path):
        calls.append(path)
        raise PermissionError("being used by another process")

    monkeypatch.setattr(verses_module, "read_text_lenient", locked)
    monkeypatch.setattr(verses_module.time, "sleep", lambda s: None)
    r = load_verse_file(p, "user", attempts=3)
    assert r.unreadable and r.error and r.verses == [] and len(calls) == 3  # tried three times
    calls.clear()
    assert load_verse_file(p, "user").unreadable and len(calls) == 1  # the poll tries once, no pause


def test_json_errors_are_reported_with_their_position(tmp_path):
    p = tmp_path / "verses.json"
    p.write_text('{"verses": [ {"text": "a"} ', encoding="utf-8")
    r = load_verse_file(p, "user")
    assert r.verses == [] and r.error and "line 1" in r.error


def test_utf8_bom_and_smart_quotes(tmp_path):
    p = tmp_path / "verses.json"
    data = {"verses": [{"reference": "X 1:1", "text": "“Hello” — world"}]}
    p.write_bytes(b"\xef\xbb\xbf" + json.dumps(data, ensure_ascii=False).encode("utf-8"))
    r = load_verse_file(p, "user")
    assert r.error is None and r.verses[0].text == "“Hello” — world"


def test_odd_user_files_are_reported_not_raised(tmp_path):
    cases = {
        "odd-utf16.json": json.dumps({"verses": [{"text": "x"}]}).encode("utf-16") + b"\n",
        "huge-number.json": ('{"verses": [{"text": "x", "n": ' + "9" * 5000 + "}]}").encode(),
        "nested.json": ("[" * 100_000 + "]" * 100_000).encode(),
    }
    for name, raw in cases.items():
        p = tmp_path / name
        p.write_bytes(raw)
        r = load_verse_file(p, "user")  # must not raise
        assert r.error or r.verses or r.warnings, name


def test_same_verse_is_recognised_however_the_reference_is_written():
    a = Verse("John 3:16–17 (BSB)", "x")
    assert a.key() == Verse("john 3:16-17", "y").key() == Verse("John  3:16 - 17 (KJV)", "z").key()
    assert a.key() != Verse("John 3:16", "x").key()
    assert Verse("", "Same  text").key() == Verse("", "same text").key()
