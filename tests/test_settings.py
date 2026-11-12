import json
import os
import time

from versedesk.settings import (
    Settings,
    SettingsStore,
    VerseSettings,
    dumps,
    settings_from_dict,
    settings_to_dict,
)


def test_defaults():
    s = Settings()
    assert s.autostart is True
    assert s.desktop_mode == "bottom"
    assert s.verse.font_family == "Georgia"
    assert s.verse.x is None and not s.verse.has_custom_position
    assert s.verse.effective_reference_font_size() == 13.0


def test_round_trip_preserves_everything_including_unknown_keys():
    data = {
        "version": 1,
        "autostart": False,
        "desktop_mode": "owner",
        "debug_log": True,
        "verse": {"x": -1200, "y": 35, "width": 600, "font_family": "Segoe UI", "font_size": 18.5,
                  "reference_font_size": 12, "color": "#FFEEDD", "shadow": False, "align": "left"},
        "zones": [{"name": "Work", "items": ["C:\\\\Docs"]}],
    }
    s, warnings = settings_from_dict(data)
    assert warnings == []
    out = settings_to_dict(s)
    assert out == data


def test_invalid_values_fall_back_to_defaults_with_warnings():
    s, warnings = settings_from_dict(
        {
            "autostart": "yes",
            "desktop_mode": "floating",
            "debug_log": "on",
            "verse": {"x": 10, "y": None, "width": 5, "font_size": True, "color": "white",
                      "align": "justify", "shadow": 1, "font_family": "", "reference_font_size": "big"},
        }
    )
    d = VerseSettings()
    assert s.autostart is True and s.desktop_mode == "bottom"
    assert (s.verse.x, s.verse.y) == (None, None)
    assert s.verse.width == d.width and s.verse.font_size == d.font_size
    assert s.verse.color == d.color and s.verse.align == d.align and s.verse.shadow is True
    assert s.verse.font_family == "Georgia" and s.verse.reference_font_size is None
    assert s.debug_log is False
    assert len(warnings) == 11


def test_non_object_top_level():
    s, warnings = settings_from_dict([1, 2])
    assert s == Settings() and warnings


def test_first_run_then_save_and_reload(tmp_path):
    path = tmp_path / "VerseDesk" / "settings.json"
    store = SettingsStore(path)
    r = store.load()
    assert r.first_run and r.error is None
    store.update(lambda s: setattr(s.verse, "font_size", 24))
    assert path.exists()
    r2 = SettingsStore(path).load()
    assert not r2.first_run and r2.settings.verse.font_size == 24
    assert not list(path.parent.glob("*.tmp"))


def test_broken_file_is_backed_up_and_defaults_used(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"verse": {"font_size": 30,}}', encoding="utf-8")
    store = SettingsStore(path)
    r = store.load()
    assert r.error and "line 1" in r.error
    assert r.settings == Settings()
    assert (tmp_path / "settings.json.bad").read_text(encoding="utf-8").startswith('{"verse"')


def _bump_mtime(path):
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))


def test_poll_detects_outside_edit(tmp_path):
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    store.load()
    store.save()
    assert store.poll() is None  # our own write is not an outside change
    data = json.loads(path.read_text(encoding="utf-8"))
    data["verse"]["font_size"] = 31
    path.write_text(json.dumps(data), encoding="utf-8")
    _bump_mtime(path)
    r = store.poll()
    assert r is not None and r.error is None
    assert store.settings.verse.font_size == 31
    assert store.poll() is None


def test_touch_without_change_is_ignored(tmp_path):
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    store.load()
    store.save()
    _bump_mtime(path)
    assert store.poll() is None


def test_poll_keeps_settings_when_outside_edit_is_broken(tmp_path):
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    store.load()
    store.update(lambda s: setattr(s.verse, "font_size", 22))
    path.write_text('{"verse": ', encoding="utf-8")
    _bump_mtime(path)
    r = store.poll()
    assert r is not None and r.error
    assert store.settings.verse.font_size == 22
    assert store.poll() is None  # reported once per broken version


def test_update_merges_outside_edits_before_saving(tmp_path):
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    store.load()
    store.save()
    data = json.loads(path.read_text(encoding="utf-8"))
    data["verse"]["font_size"] = 28  # user edits the file...
    path.write_text(json.dumps(data), encoding="utf-8")
    _bump_mtime(path)
    reloaded = store.update(lambda s: setattr(s.verse, "x", 100) or setattr(s.verse, "y", 200))  # ...app moves widget
    assert reloaded is not None
    final = json.loads(path.read_text(encoding="utf-8"))
    assert final["verse"]["font_size"] == 28 and (final["verse"]["x"], final["verse"]["y"]) == (100, 200)


def test_saving_over_a_broken_file_keeps_a_backup(tmp_path):
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    store.load()
    store.save()
    path.write_text("{oops", encoding="utf-8")
    _bump_mtime(path)
    store.update(lambda s: setattr(s, "autostart", False))
    assert (tmp_path / "settings.json.bad").read_text(encoding="utf-8") == "{oops"
    assert json.loads(path.read_text(encoding="utf-8"))["autostart"] is False


def test_ansi_encoded_file_is_still_read(tmp_path):
    path = tmp_path / "settings.json"
    path.write_bytes('{"verse": {"font_family": "Caf\xe9"}}'.encode("cp1252"))
    r = SettingsStore(path).load()
    assert r.error is None and r.settings.verse.font_family.startswith("Caf")


def test_dumps_is_pretty_and_ends_with_newline():
    text = dumps(Settings())
    assert text.endswith("\n") and '\n  "verse": {' in text
    json.loads(text)


def test_deleted_file_is_recreated_on_next_save(tmp_path):
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    store.load()
    store.save()
    path.unlink()
    assert store.poll() is None
    store.update(lambda s: None)
    assert path.exists()
    time.sleep(0)  # keep linters quiet about unused import on some platforms
