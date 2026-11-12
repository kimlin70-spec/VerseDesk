import datetime as dt
import json

import pytest

from versedesk.verses import (
    Verse,
    VerseLibrary,
    all_date_keys,
    date_key,
    load_verse_file,
    normalize_date_key,
    parse_entries,
)


def _embedded():
    return {k: Verse(k, f"Ref {k} (BSB)", f"Text for {k}.") for k in all_date_keys()}


def test_all_date_keys_has_366_days_including_feb_29():
    keys = all_date_keys()
    assert len(keys) == 366
    assert len(set(keys)) == 366
    assert keys[0] == "01-01" and keys[-1] == "12-31"
    assert "02-29" in keys


@pytest.mark.parametrize(
    "value, expected",
    [
        ("01-05", "01-05"),
        ("1-5", "01-05"),
        ("1/5", "01-05"),
        ("12.25", "12-25"),
        (" 02-29 ", "02-29"),
        ("02-30", None),
        ("13-01", None),
        ("00-10", None),
        ("2024-01-01", None),
        ("", None),
        (None, None),
        (101, None),
    ],
)
def test_normalize_date_key(value, expected):
    assert normalize_date_key(value) == expected


def test_same_date_same_verse_every_year():
    lib = VerseLibrary(_embedded())
    for year in (2025, 2026, 2027, 2030):
        assert lib.verse_for(dt.date(year, 3, 14)).text == "Text for 03-14."
        assert lib.verse_for(dt.date(year, 12, 31)).text == "Text for 12-31."


def test_feb_29_used_in_leap_years_and_feb_28_29_differ():
    lib = VerseLibrary(_embedded())
    assert lib.verse_for(dt.date(2028, 2, 29)).date == "02-29"
    assert lib.verse_for(dt.date(2027, 2, 28)).date == "02-28"
    assert lib.verse_for(dt.date(2027, 3, 1)).date == "03-01"


def test_every_day_of_two_years_has_a_verse():
    lib = VerseLibrary(_embedded())
    day = dt.date(2027, 1, 1)
    for _ in range(366 * 2):
        v = lib.verse_for(day)
        assert v.date == date_key(day)
        day += dt.timedelta(days=1)


def test_user_override_wins_only_for_its_dates():
    overrides, warnings = parse_entries(
        {"verses": [{"date": "3-14", "reference": "Mine 1:1", "text": "My  own\ntext"}]}, "user"
    )
    assert warnings == []
    lib = VerseLibrary(_embedded(), overrides)
    v = lib.verse_for(dt.date(2026, 3, 14))
    assert (v.text, v.reference, v.source) == ("My own text", "Mine 1:1", "user")
    assert lib.verse_for(dt.date(2026, 3, 15)).source == "embedded"


def test_override_accepts_bare_list_and_missing_reference():
    entries, warnings = parse_entries([{"date": "12/25", "text": "Hello"}], "user")
    assert warnings == []
    assert entries["12-25"].reference == ""


def test_invalid_override_entries_are_skipped_with_warnings():
    entries, warnings = parse_entries(
        {
            "verses": [
                {"date": "02-30", "text": "bad date"},
                {"date": "01-01"},
                "not an object",
                {"date": "01-02", "text": "   "},
                {"date": "01-03", "text": "ok", "reference": 5},
                {"date": "01-03", "text": "later wins"},
            ]
        },
        "user",
    )
    assert set(entries) == {"01-03"}
    assert entries["01-03"].text == "later wins"
    assert len(warnings) == 5


def test_wrong_top_level_shape():
    assert parse_entries({"days": []}, "user")[0] == {}
    assert parse_entries("text", "user")[0] == {}


def test_load_verse_file_reports_json_errors_with_position(tmp_path):
    p = tmp_path / "verses.json"
    p.write_text('{"verses": [ {"date": "01-01", "text": "a"} ', encoding="utf-8")
    entries, warnings, error = load_verse_file(p, "user")
    assert entries == {} and error is not None
    assert "line 1" in error


def test_load_verse_file_handles_utf8_bom_and_smart_quotes(tmp_path):
    p = tmp_path / "verses.json"
    data = {"verses": [{"date": "01-01", "reference": "X 1:1", "text": "“Hello” — world"}]}
    p.write_bytes(b"\xef\xbb\xbf" + json.dumps(data, ensure_ascii=False).encode("utf-8"))
    entries, warnings, error = load_verse_file(p, "user")
    assert error is None and warnings == []
    assert entries["01-01"].text == "“Hello” — world"


def test_missing_dates_fall_back_without_crashing():
    partial = {"01-01": Verse("01-01", "R", "T")}
    lib = VerseLibrary(partial)
    assert lib.verse_for(dt.date(2026, 6, 6)).text == "T"
    assert VerseLibrary({}).verse_for(dt.date(2026, 6, 6)).source == "fallback"


def test_odd_user_files_are_reported_not_raised(tmp_path):
    from versedesk.verses import load_verse_file

    cases = {
        "odd-utf16.json": json.dumps({"verses": [{"date": "1-1", "text": "x"}]}).encode("utf-16") + b"\n",
        "huge-number.json": ('{"verses": [{"date": "1-1", "text": "x", "n": ' + "9" * 5000 + "}]}").encode(),
        "nested.json": ("[" * 100_000 + "]" * 100_000).encode(),
    }
    for name, raw in cases.items():
        p = tmp_path / name
        p.write_bytes(raw)
        entries, warnings, error = load_verse_file(p, "user")  # must not raise
        assert error or entries or warnings, name
