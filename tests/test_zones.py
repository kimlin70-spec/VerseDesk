import json

from versedesk.settings import Settings, settings_from_dict, settings_to_dict
from versedesk.zones import (
    DEFAULT_ZONE_NAME,
    MAX_ITEMS,
    NAME_MAX,
    Zone,
    clean_name,
    clean_path,
    display_name,
    path_key,
    zones_from_list,
    zones_to_list,
)


def test_same_windows_path_in_different_spellings_is_one_item():
    z = Zone(id="a")
    added = z.add_paths([
        r"C:\Users\Kim\Documents\보고서",
        r"c:\users\kim\documents\보고서",
        "C:/Users/Kim/Documents/보고서",
        "C:\\Users\\Kim\\Documents\\보고서\\",
        '"C:\\Users\\Kim\\Documents\\보고서"',
    ])
    assert added == [r"C:\Users\Kim\Documents\보고서"]
    assert z.items == [r"C:\Users\Kim\Documents\보고서"]


def test_different_paths_are_kept_in_order():
    z = Zone(id="a")
    assert z.add_paths([r"D:\b.txt", r"C:\a", r"\\server\share\plan.xlsx"]) == [
        r"D:\b.txt", r"C:\a", r"\\server\share\plan.xlsx"]
    assert z.add_paths([r"C:\A", r"C:\c"]) == [r"C:\c"]


def test_relative_or_broken_paths_are_rejected():
    for bad in ("", "   ", "relative\\path", "file.txt", "C:\\a\0b", None, 5):
        assert clean_path(bad) is None, bad
    assert clean_path("C:\\") == "C:\\"
    assert clean_path("C:/Users/") == r"C:\Users"


def test_remove_path_matches_like_windows():
    z = Zone(id="a", items=[r"C:\Data\Plan.xlsx", r"C:\Other"])
    assert z.remove_path("c:/data/plan.XLSX") is True
    assert z.items == [r"C:\Other"]
    assert z.remove_path(r"C:\missing") is False


def test_display_name_is_what_explorer_shows():
    assert display_name(r"C:\Users\Kim\Documents\보고서") == "보고서"
    assert display_name(r"D:\계획.xlsx") == "계획.xlsx"
    assert display_name("C:\\") == "C:"
    assert display_name(r"\\server\share") == r"\\server\share"


def test_zone_names_are_cleaned():
    assert clean_name("  업무   자료 ") == "업무 자료"
    assert clean_name("a\nb") == "a b"
    assert clean_name("") == DEFAULT_ZONE_NAME
    assert clean_name(None) == DEFAULT_ZONE_NAME
    assert len(clean_name("가" * 100)) == NAME_MAX


def test_item_limit():
    z = Zone(id="a")
    z.add_paths([f"C:\\f{i}" for i in range(MAX_ITEMS + 10)])
    assert len(z.items) == MAX_ITEMS


def test_zones_round_trip_through_settings_json():
    s = Settings()
    s.zones = [
        Zone(id="z1", name="업무", x=-1500, y=30, width=400, height=300, collapsed=True,
             items=[r"C:\Work", r"D:\계획.xlsx"]),
        Zone(id="z2", name="사진"),
    ]
    text = json.dumps(settings_to_dict(s), ensure_ascii=False)
    back, warnings = settings_from_dict(json.loads(text))
    assert warnings == []
    assert [(z.id, z.name, z.x, z.y, z.width, z.height, z.collapsed, z.items) for z in back.zones] == [
        ("z1", "업무", -1500, 30, 400, 300, True, [r"C:\Work", r"D:\계획.xlsx"]),
        ("z2", "사진", None, None, 340, 260, False, []),
    ]


def test_bad_zone_values_fall_back_with_warnings_and_never_raise():
    zones, warnings = zones_from_list([
        {"id": "dup", "name": 5, "x": "abc", "y": 3, "width": 10, "height": "9" * 400,
         "collapsed": "yes", "items": "C:\\x"},
        {"id": "dup", "items": [r"C:\ok", "relative", 7, r"C:\OK"]},
        "not an object",
        None,
    ])
    assert len(zones) == 2
    a, b = zones
    assert a.id != b.id  # duplicate ids are replaced
    assert a.name == DEFAULT_ZONE_NAME and a.x is None and a.width == 340 and a.height == 260
    assert a.collapsed is False and a.items == []
    assert b.items == [r"C:\ok"]
    assert len(warnings) >= 7


def test_zones_that_are_not_a_list_keep_the_previous_zones():
    prev = Settings()
    prev.zones = [Zone(id="keep", name="그대로", items=[r"C:\a"])]
    s, warnings = settings_from_dict({"zones": {"oops": 1}}, previous=prev)
    assert [z.id for z in s.zones] == ["keep"]
    assert any("zones must be a list" in w for w in warnings)


def test_unknown_zone_keys_are_preserved_for_newer_versions():
    zones, _ = zones_from_list([{"id": "z", "name": "a", "color": "#123456", "sort": {"by": "name"}}])
    out = zones_to_list(zones)[0]
    assert out["color"] == "#123456" and out["sort"] == {"by": "name"}


def test_path_key_handles_unc_and_roots():
    assert path_key(r"\\Server\Share\Folder\\") == path_key(r"\\server\share\folder")
    assert path_key("C:\\") == path_key("c:/")
