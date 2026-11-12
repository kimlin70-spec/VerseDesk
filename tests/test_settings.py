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
        "zones": [{"id": "z1", "name": "Work", "x": 10, "y": 20, "width": 300, "height": 200,
                   "collapsed": True, "items": ["C:\\Docs", "\\\\server\\share\\plan.xlsx"],
                   "color": "#112233"}],
        "future_feature": {"enabled": True, "list": [1, 2]},
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


def test_numeric_strings_are_accepted():
    s, warnings = settings_from_dict({"verse": {"font_size": "32", "width": " 600 ", "x": "10", "y": "20"}})
    assert warnings == []
    assert (s.verse.font_size, s.verse.width, s.verse.x, s.verse.y) == (32.0, 600, 10, 20)


def test_invalid_value_on_reload_keeps_the_previous_value(tmp_path):
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    store.load()
    store.update(lambda s: setattr(s.verse, "font_size", 30))
    data = json.loads(path.read_text(encoding="utf-8"))
    data["verse"]["font_size"] = 250  # out of range typed by the user
    path.write_text(json.dumps(data), encoding="utf-8")
    _bump_mtime(path)
    r = store.poll()
    assert r is not None and r.warnings
    assert store.settings.verse.font_size == 30  # not reset to the default 20


def test_utf16_files_are_read(tmp_path):
    path = tmp_path / "settings.json"
    path.write_bytes(json.dumps({"verse": {"font_size": 28}}).encode("utf-16"))  # with BOM
    assert SettingsStore(path).load().settings.verse.font_size == 28
    path.write_bytes(json.dumps({"verse": {"font_size": 27}}).encode("utf-16-le"))  # no BOM
    assert SettingsStore(path).load().settings.verse.font_size == 27


def test_transiently_locked_file_is_not_treated_as_broken_or_overwritten(tmp_path, monkeypatch):
    from pathlib import Path

    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"verse": {"font_size": 33, "x": 5, "y": 6}}), encoding="utf-8")
    real_read = Path.read_bytes
    locked = {"on": True}

    def flaky(self):
        if self == path and locked["on"]:
            raise PermissionError("in use by another process")
        return real_read(self)

    monkeypatch.setattr(Path, "read_bytes", flaky)
    store = SettingsStore(path)
    r = store.load()
    assert r.unreadable and r.error
    assert not (tmp_path / "settings.json.bad").exists()
    store.update(lambda s: setattr(s, "autostart", False))  # a save while still locked...
    assert json.loads(real_read(path))["verse"]["font_size"] == 33  # ...must not clobber the file
    locked["on"] = False
    reloaded = store.poll()  # the lock is gone: the user's settings come back
    assert reloaded is not None and reloaded.error is None
    assert store.settings.verse.font_size == 33 and store.settings.verse.x == 5


def test_change_made_while_the_file_was_locked_is_applied_on_top_of_it(tmp_path, monkeypatch):
    """The lock clears just as the user drags the verse: the drag must win, and the
    user's other settings must be kept (not replaced by defaults)."""
    from pathlib import Path

    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"verse": {"font_size": 33, "x": 100, "y": 6}}), encoding="utf-8")
    real_read = Path.read_bytes
    locked = {"on": True}

    def flaky(self):
        if self == path and locked["on"]:
            raise PermissionError("in use by another process")
        return real_read(self)

    monkeypatch.setattr(Path, "read_bytes", flaky)
    store = SettingsStore(path)
    assert store.load().unreadable
    monkeypatch.setattr(store, "changed_on_disk", lambda: False)  # poll() sees nothing new
    locked["on"] = False
    store.update(lambda s: setattr(s.verse, "x", 500))
    assert store.settings.verse.x == 500 and store.settings.verse.font_size == 33
    on_disk = json.loads(real_read(path))["verse"]
    assert on_disk["x"] == 500 and on_disk["font_size"] == 33


def test_absurd_numbers_never_stop_the_app(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"verse": {"font_size": ' + "9" * 400 + "}}", encoding="utf-8")
    r = SettingsStore(path).load()  # an int too large for float: a warning, not a crash
    assert r.error is None and r.settings.verse.font_size == VerseSettings().font_size and r.warnings
    path.write_text('{"verse": {"font_size": ' + "9" * 5000 + "}}", encoding="utf-8")
    r = SettingsStore(path).load()  # beyond Python's int digit limit: treated as a format error
    assert r.error and r.settings == Settings()


def test_deeply_nested_json_is_a_format_error_not_a_crash(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("[" * 100_000 + "]" * 100_000, encoding="utf-8")
    r = SettingsStore(path).load()
    assert r.error and r.settings == Settings()


def test_utf16_file_with_a_stray_odd_byte_does_not_stop_the_app(tmp_path):
    path = tmp_path / "settings.json"
    path.write_bytes(json.dumps({"verse": {"font_size": 28}}).encode("utf-16") + b"\n")
    r = SettingsStore(path).load()
    assert r.settings.verse.font_size in (28, VerseSettings().font_size)  # read, or reported
