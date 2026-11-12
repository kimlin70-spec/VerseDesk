"""End-to-end checks of the app wiring with Qt's offscreen platform (no real desktop)."""

import datetime as dt
import json
import os

import pytest

N_BUILTIN = 5


@pytest.fixture
def embedded(tmp_path):
    p = tmp_path / "embedded.json"
    verses = [{"reference": f"Book {i + 1}:1 (BSB)", "text": f"Verse number {i + 1}."} for i in range(N_BUILTIN)]
    p.write_text(json.dumps({"verses": verses}), encoding="utf-8")
    return p


def at(hour, minute=0, day=12):
    return dt.datetime(2026, 11, day, hour, minute)


def slot_index(when, interval=120, count=N_BUILTIN):
    from versedesk.rotation import verse_index

    return verse_index(when, interval, count)


class FakeAutostart:
    supported = True

    def __init__(self):
        self.enabled = False
        self.calls = []

    def sync_at_startup(self, wanted):
        self.calls.append(("sync", wanted))
        self.enabled = wanted
        return self.enabled

    def enable(self):
        self.enabled = True
        return True

    def disable(self):
        self.enabled = False
        return True

    def is_enabled(self):
        return self.enabled


def make_app(qapp, home, embedded, when, autostart=None):
    from versedesk import paths
    from versedesk.app import VerseDeskApp
    from versedesk.settings import SettingsStore

    store = SettingsStore(paths.settings_path())
    result = store.load()
    clock = {"now": when}
    app = VerseDeskApp(
        qapp, store, result,
        autostart=autostart or FakeAutostart(),
        now=lambda: clock["now"],
        embedded_verses_path=embedded,
    )
    app.start()
    qapp.processEvents()
    return app, clock


def shutdown(app):
    if app._editor is not None:
        app._editor.close()
    app.rotation.stop()
    app._poll.stop()
    app.layer.stop()
    app.tray.hide()
    app.verse_widget.hide()
    app.verse_widget.deleteLater()


def test_first_start_shows_the_current_verse_top_right_and_writes_settings(qapp, home, embedded):
    auto = FakeAutostart()
    when = at(9, 30)
    app, _ = make_app(qapp, home, embedded, when, autostart=auto)
    try:
        w = app.verse_widget
        i = slot_index(when)
        assert w.isVisible()
        assert w.text == f"Verse number {i + 1}." and w.reference == f"Book {i + 1}:1 (BSB)"
        assert app.layer.is_click_through(w) is True
        assert (home / "settings.json").exists()
        assert json.loads((home / "settings.json").read_text(encoding="utf-8"))["verse"]["interval_minutes"] == 120
        assert auto.calls == [("sync", True)]  # autostart on by default
        avail = qapp.primaryScreen().availableGeometry()
        assert w.geometry().right() <= avail.right() and w.y() >= avail.y()
        assert w.x() > avail.center().x() - w.width()  # right-hand side
    finally:
        shutdown(app)


def test_the_next_verse_comes_in_order_and_wraps_around(qapp, home, embedded):
    app, clock = make_app(qapp, home, embedded, at(0, 0))
    try:
        seen = []
        for k in range(N_BUILTIN + 2):  # every 2 hours, past the end of the list
            clock["now"] = at(0, 0) + dt.timedelta(hours=2 * k, minutes=1)
            app.rotation.check()
            seen.append(int(app.verse_widget.reference.split()[1].split(":")[0]))
        first = seen[0]
        assert seen == [(first - 1 + k) % N_BUILTIN + 1 for k in range(N_BUILTIN + 2)]
        # a restart in the same time slot shows the same verse (nothing is saved for this)
        current = app.verse_widget.text
    finally:
        shutdown(app)
    app2, _ = make_app(qapp, home, embedded, clock["now"])
    try:
        assert app2.verse_widget.text == current
    finally:
        shutdown(app2)


def test_edit_mode_toggles_click_through_and_drag_saves_position(qapp, home, embedded):
    app, _ = make_app(qapp, home, embedded, at(10))
    try:
        app.set_edit_mode(True)
        assert app.layer.is_click_through(app.verse_widget) is False
        app.verse_widget.move(100, 120)
        app.verse_widget.moved.emit(100, 120)
        saved = json.loads((home / "settings.json").read_text(encoding="utf-8"))
        assert (saved["verse"]["x"], saved["verse"]["y"]) == (100, 120)
        app.set_edit_mode(False)
        assert app.layer.is_click_through(app.verse_widget) is True
    finally:
        shutdown(app)

    app2, _ = make_app(qapp, home, embedded, at(11))
    try:
        assert (app2.verse_widget.x(), app2.verse_widget.y()) == (100, 120)
    finally:
        shutdown(app2)


def test_off_screen_position_is_brought_back(qapp, home, embedded):
    home.mkdir(parents=True, exist_ok=True)
    (home / "settings.json").write_text(json.dumps({"verse": {"x": 9000, "y": 9000}}), encoding="utf-8")
    app, _ = make_app(qapp, home, embedded, at(12))
    try:
        avail = qapp.primaryScreen().availableGeometry()
        assert avail.contains(app.verse_widget.geometry())
        # the saved value is kept, so the widget returns if that monitor comes back
        assert json.loads((home / "settings.json").read_text(encoding="utf-8"))["verse"]["x"] == 9000
    finally:
        shutdown(app)


def _touch_later(path):
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 3_000_000_000))


def test_the_users_list_replaces_the_built_in_one_and_reloads(qapp, home, embedded):
    app, _ = make_app(qapp, home, embedded, at(14))
    try:
        user = home / "verses.json"
        user.write_text(json.dumps({"verses": [{"reference": "Mine (KJV)", "text": "Custom text."}]}),
                        encoding="utf-8")
        app._poll_files()
        assert app.verse_widget.text == "Custom text." and app.verse_widget.reference == "Mine (KJV)"
        user.write_text("{ broken", encoding="utf-8")
        _touch_later(user)
        app._poll_files()  # broken file: keep showing what we had, no crash
        assert app.verse_widget.text == "Custom text."
        user.write_text(json.dumps({"verses": []}), encoding="utf-8")
        _touch_later(user)
        app._poll_files()  # an emptied list falls back to the built-in verses
        assert app.verse_widget.text.startswith("Verse number")
        user.unlink()
        app._poll_files()
        assert app.verse_widget.text == f"Verse number {slot_index(at(14)) + 1}."
    finally:
        shutdown(app)


def test_an_old_date_based_file_is_put_aside_not_used(qapp, home, embedded):
    home.mkdir(parents=True, exist_ok=True)
    old = {"verses": [{"date": f"01-{d:02d}", "reference": "Old", "text": f"Old {d}."} for d in range(1, 29)]}
    (home / "verses.json").write_text(json.dumps(old), encoding="utf-8")
    app, _ = make_app(qapp, home, embedded, at(9))
    try:
        assert app.verse_widget.text.startswith("Verse number")  # the built-in list
        assert not (home / "verses.json").exists()
        backups = list(home.glob("verses.backup-*.json"))
        assert len(backups) == 1 and json.loads(backups[0].read_text(encoding="utf-8")) == old
        assert app.user_list is None
    finally:
        shutdown(app)


def test_settings_edited_outside_are_applied(qapp, home, embedded):
    app, _ = make_app(qapp, home, embedded, at(8))
    try:
        h_before = app.verse_widget.height()
        path = home / "settings.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["verse"]["font_size"] = 40
        path.write_text(json.dumps(data), encoding="utf-8")
        st = path.stat()
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 3_000_000_000))
        app._poll_files()
        assert app.verse_widget.height() > h_before
    finally:
        shutdown(app)


def test_autostart_toggle_persists(qapp, home, embedded):
    auto = FakeAutostart()
    app, _ = make_app(qapp, home, embedded, at(8), autostart=auto)
    try:
        app.set_autostart(False)
        assert auto.enabled is False
        assert json.loads((home / "settings.json").read_text(encoding="utf-8"))["autostart"] is False
        assert app.tray.act_autostart.isChecked() is False
        app.set_autostart(True)
        assert app.tray.act_autostart.isChecked() is True
    finally:
        shutdown(app)


def test_tray_menu_items(qapp, home, embedded):
    app, _ = make_app(qapp, home, embedded, at(8))
    try:
        texts = [a.text() for a in app.tray.menu.actions() if not a.isSeparator()]
        assert texts[0].startswith("배치 편집")
        assert any("새 구역" in t for t in texts)
        assert any("말씀 목록 편집" in t for t in texts)
        assert any("자동 실행" in t for t in texts)
        assert texts[-1] == "종료"
        app.tray.edit_mode_toggled.emit(True)
        assert app.edit_mode is True and "끄기" in app.tray.act_edit.text()
    finally:
        shutdown(app)


def test_broken_user_verses_at_startup_is_notified_with_the_tray_visible(qapp, home, embedded):
    home.mkdir(parents=True, exist_ok=True)
    (home / "verses.json").write_text("{ not json", encoding="utf-8")
    from versedesk.ui.tray import TrayController

    seen = []
    original = TrayController.notify

    def spy(self, title, message, warning=False, msecs=8000):
        seen.append((title, self.tray.isVisible()))
        return original(self, title, message, warning, msecs)

    TrayController.notify = spy
    try:
        app, _ = make_app(qapp, home, embedded, at(8))
    finally:
        TrayController.notify = original
    try:
        errors = [s for s in seen if "verses.json" in s[0]]
        assert errors and all(visible for _title, visible in errors)
    finally:
        shutdown(app)


def _fake_bible():
    from versedesk.bible import Bible

    return Bible({"John 3:16": "For God so loved the world.", "John 3:17": "For God did not send His Son.",
                  "Psalm 23:1": "A Psalm of David. The LORD is my shepherd.", "Psalm 23:2": "Green pastures."},
                 {23: "A Psalm of David."})


def test_the_editor_saves_every_change_and_the_desktop_follows(qapp, home, embedded, monkeypatch):
    from versedesk import paths
    from versedesk.ui import verse_editor

    monkeypatch.setattr(verse_editor.Bible, "load", staticmethod(_fake_bible))
    app, clock = make_app(qapp, home, embedded, at(16))
    try:
        app.tray.edit_verses_requested.emit()
        ed = app._editor
        assert ed is not None and ed.isVisible()
        assert [v.text for v in ed.verses()] == [f"Verse number {i + 1}." for i in range(N_BUILTIN)]
        app.open_verse_editor()  # a second request brings the same window to the front
        assert app._editor is ed
        assert not paths.user_verses_path().exists()  # nothing is written until something changes

        ed.input.setText("요 3:16-17")
        ed.add_from_input()
        saved = json.loads(paths.user_verses_path().read_text(encoding="utf-8"))["verses"]
        assert len(saved) == N_BUILTIN + 1
        assert saved[-1] == {"reference": "John 3:16–17 (BSB)",
                             "text": "For God so loved the world. For God did not send His Son."}
        assert app.user_list is not None and len(app.user_list) == N_BUILTIN + 1

        # keep only the new verse: it is shown whatever the time
        ed.tree.selectAll()
        ed.tree.topLevelItem(N_BUILTIN).setSelected(False)
        ed.delete_selected()
        assert app.verse_widget.text == "For God so loved the world. For God did not send His Son."
        assert app.verse_widget.reference == "John 3:16–17 (BSB)"

        # the interval goes to settings.json and takes effect at once
        ed.interval.setCurrentIndex(ed.interval.findData(30))
        assert json.loads((home / "settings.json").read_text(encoding="utf-8"))["verse"]["interval_minutes"] == 30
        assert app.rotation.interval == 30

        ed.close()
        qapp.processEvents()
        assert app._editor is None
        app.open_verse_editor()  # opens again, now with the user's list
        assert [v.reference for v in app._editor.verses()] == ["John 3:16–17 (BSB)"]
    finally:
        shutdown(app)


def test_editing_the_file_while_the_editor_is_open_updates_it(qapp, home, embedded):
    from versedesk import paths

    app, _ = make_app(qapp, home, embedded, at(16))
    try:
        app.open_verse_editor()
        path = paths.user_verses_path()
        path.write_text(json.dumps({"verses": [{"reference": "A 1:1", "text": "Alpha."}]}), encoding="utf-8")
        app._poll_files()
        assert [v.text for v in app._editor.verses()] == ["Alpha."]
    finally:
        shutdown(app)


def test_a_save_that_fails_is_reported_and_nothing_crashes(qapp, home, embedded, monkeypatch):
    import versedesk.app as app_module

    app, _ = make_app(qapp, home, embedded, at(16))
    try:
        app.open_verse_editor()

        def fail(*_a, **_k):
            raise PermissionError("denied")

        monkeypatch.setattr(app_module, "atomic_write_text", fail)
        app._editor.delete_selected()  # nothing selected: no change
        app._editor.tree.topLevelItem(0).setSelected(True)
        app._editor.delete_selected()
        assert "저장하지 못했습니다" in app._editor.count_label.text()
        assert app.user_list is None  # still the built-in list on screen
    finally:
        shutdown(app)


def _builtin_count(app):
    return len(app.builtin)


def test_a_broken_list_is_kept_as_a_backup_before_the_editor_saves(qapp, home, embedded):
    """The user's own verses.json with a stray comma must never be lost by an editor change."""
    from versedesk import paths

    home.mkdir(parents=True, exist_ok=True)
    path = paths.user_verses_path()
    broken = '{"verses": [{"reference": "Mine 1:1", "text": "My own verse."},]}'
    path.write_text(broken, encoding="utf-8")
    app, _ = make_app(qapp, home, embedded, at(10))
    try:
        assert app.user_list is None and app.verse_widget.text.startswith("Verse number")
        app.open_verse_editor()
        assert "기본 말씀을 보여 줍니다" in app._editor.message.text()  # says why, and that the file is kept
        app._editor._select_rows([0])
        app._editor.delete_selected()
        backups = list(home.glob("verses.backup-*.json"))
        assert len(backups) == 1 and backups[0].read_text(encoding="utf-8") == broken
        saved = json.loads(path.read_text(encoding="utf-8"))["verses"]
        assert len(saved) == _builtin_count(app) - 1
        app._editor.delete_selected()  # later saves overwrite our own file: no more backups
        assert len(list(home.glob("verses.backup-*.json"))) == 1
    finally:
        shutdown(app)


def test_an_edit_made_outside_moments_before_a_save_is_kept(qapp, home, embedded):
    """Notepad saved verses.json and the 2 s poll has not seen it yet: back it up, don't lose it."""
    from versedesk import paths

    app, _ = make_app(qapp, home, embedded, at(10))
    try:
        app.open_verse_editor()
        app._editor._select_rows([0])
        app._editor.delete_selected()  # our own file now
        path = paths.user_verses_path()
        outside = json.dumps({"verses": [{"reference": "X 1:1", "text": "Typed in Notepad."}]})
        path.write_text(outside, encoding="utf-8")
        _touch_later(path)
        app._editor._select_rows([0])
        app._editor.delete_selected()  # before any poll
        backups = list(home.glob("verses.backup-*.json"))
        assert len(backups) == 1 and backups[0].read_text(encoding="utf-8") == outside
    finally:
        shutdown(app)


def test_each_editor_session_keeps_the_list_from_before_it(qapp, home, embedded):
    from versedesk import paths

    app, _ = make_app(qapp, home, embedded, at(10))
    try:
        previous = home / "verses.previous.json"
        app.open_verse_editor()
        app._editor._select_rows([0])
        app._editor.delete_selected()  # first save ever: there was no file before, nothing to keep
        assert not previous.exists()
        app._editor.close()
        qapp.processEvents()
        before = paths.user_verses_path().read_text(encoding="utf-8")
        app.open_verse_editor()
        app._editor.tree.selectAll()
        app._editor.delete_selected()  # oops: everything gone...
        app._editor._changed()  # (a second save in the same session must not replace the copy)
        assert previous.read_text(encoding="utf-8") == before  # ...but the list from before is kept
    finally:
        shutdown(app)


def test_a_locked_list_is_read_again_once_it_can_be_opened(qapp, home, embedded, monkeypatch):
    import versedesk.verses as verses_module
    from versedesk import paths

    home.mkdir(parents=True, exist_ok=True)
    path = paths.user_verses_path()
    path.write_text(json.dumps({"verses": [{"reference": "Mine 1:1", "text": "My own verse."}]}), encoding="utf-8")
    original = verses_module.read_text_lenient
    state = {"locked": True}

    def maybe_locked(p):
        if state["locked"]:
            raise PermissionError("being used by another process")
        return original(p)

    monkeypatch.setattr(verses_module, "read_text_lenient", maybe_locked)
    monkeypatch.setattr(verses_module.time, "sleep", lambda s: None)
    app, _ = make_app(qapp, home, embedded, at(10))
    try:
        assert app.user_list is None
        state["locked"] = False
        app._poll_files()  # the same file, now readable: no change in size or time needed
        assert app.verse_widget.text == "My own verse."
    finally:
        shutdown(app)


def test_old_date_files_get_their_own_backup_names(qapp, home, embedded):
    home.mkdir(parents=True, exist_ok=True)
    old = {"verses": [{"date": "01-01", "reference": "Old", "text": "Old."}]}
    stamp_taken = home / "verses.backup-x.json"
    stamp_taken.write_text("keep me", encoding="utf-8")
    (home / "verses.json").write_text(json.dumps(old), encoding="utf-8")
    app, _ = make_app(qapp, home, embedded, at(9))
    try:
        assert stamp_taken.read_text(encoding="utf-8") == "keep me"
        assert len(list(home.glob("verses.backup-*.json"))) == 2
    finally:
        shutdown(app)


def test_the_open_editor_follows_an_interval_changed_in_settings_json(qapp, home, embedded):
    app, _ = make_app(qapp, home, embedded, at(16))
    try:
        app.open_verse_editor()
        reported = []
        app._editor.interval_changed.connect(reported.append)
        path = home / "settings.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["verse"]["interval_minutes"] = 30
        path.write_text(json.dumps(data), encoding="utf-8")
        _touch_later(path)
        app._poll_files()
        assert app.rotation.interval == 30 and app._editor.interval.currentData() == 30
        assert reported == []  # shown, not sent back as a new choice
    finally:
        shutdown(app)


def test_a_list_read_only_in_part_is_kept_before_the_editor_saves(qapp, home, embedded, monkeypatch):
    """Entries the app had to skip or cut exist only in the user's file: copy it aside first."""
    from versedesk import paths
    from versedesk.ui.tray import TrayController

    notices = []
    monkeypatch.setattr(TrayController, "notify", lambda self, title, msg, warning=False, msecs=8000: notices.append(msg))
    home.mkdir(parents=True, exist_ok=True)
    path = paths.user_verses_path()
    original = json.dumps({"verses": [{"reference": "Mine 1:1", "text": "Kept."},
                                      {"reference": "Typo", "txt": "Be still, and know."},
                                      {"reference": "Long", "text": "x " * 2000}]})
    path.write_text(original, encoding="utf-8")
    app, _ = make_app(qapp, home, embedded, at(10))
    try:
        assert [v.reference for v in app.user_list] == ["Mine 1:1", "Long"]
        assert any("1개 항목을 건너뛰었습니다" in n and "1개 본문이" in n for n in notices)  # said at startup
        app.open_verse_editor()
        app._editor._select_rows([0])
        app._editor.move_selected(1)
        backups = list(home.glob("verses.backup-*.json"))
        assert len(backups) == 1 and backups[0].read_text(encoding="utf-8") == original
    finally:
        shutdown(app)


def test_deleting_a_list_that_could_not_be_opened_is_still_noticed(qapp, home, embedded, monkeypatch):
    import versedesk.verses as verses_module
    from versedesk import paths

    app, _ = make_app(qapp, home, embedded, at(10))
    try:
        path = paths.user_verses_path()
        path.write_text(json.dumps({"verses": [{"reference": "Mine 1:1", "text": "Mine."}]}), encoding="utf-8")
        app._poll_files()
        assert app.verse_widget.text == "Mine."
        original = verses_module.read_text_lenient
        monkeypatch.setattr(verses_module, "read_text_lenient", lambda p: (_ for _ in ()).throw(PermissionError("locked")))
        sleeps = []
        monkeypatch.setattr(verses_module.time, "sleep", sleeps.append)
        path.write_text(json.dumps({"verses": [{"text": "Changed."}]}), encoding="utf-8")
        _touch_later(path)
        app._poll_files()  # locked: keep what is shown, try again later...
        assert sleeps == []  # ...without pausing the program at every poll
        monkeypatch.setattr(verses_module, "read_text_lenient", original)
        path.unlink()
        app._poll_files()
        assert app.user_list is None and app.verse_widget.text.startswith("Verse number")
    finally:
        shutdown(app)


def test_a_read_only_spare_copy_does_not_block_saving(qapp, home, embedded):
    import os
    import stat

    from versedesk import paths

    app, _ = make_app(qapp, home, embedded, at(10))
    try:
        app.open_verse_editor()
        app._editor._select_rows([0])
        app._editor.delete_selected()  # our own verses.json now exists
        app._editor.close()
        qapp.processEvents()
        previous = home / "verses.previous.json"
        previous.write_text("old spare copy", encoding="utf-8")
        os.chmod(previous, stat.S_IREAD)  # e.g. copied from a read-only verses.json
        app.open_verse_editor()
        app._editor._select_rows([0])
        app._editor.delete_selected()
        assert "저장하지 못했습니다" not in app._editor.count_label.text()
        assert previous.read_text(encoding="utf-8") != "old spare copy"
        assert os.stat(previous).st_mode & stat.S_IWRITE  # the new copy does not inherit read-only
        saved = json.loads(paths.user_verses_path().read_text(encoding="utf-8"))["verses"]
        assert len(saved) == _builtin_count(app) - 2
    finally:
        shutdown(app)
