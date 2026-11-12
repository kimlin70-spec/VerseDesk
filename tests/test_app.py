"""End-to-end checks of the app wiring with Qt's offscreen platform (no real desktop)."""

import datetime as dt
import json
import os

import pytest

from versedesk.verses import all_date_keys


@pytest.fixture
def embedded(tmp_path):
    p = tmp_path / "embedded.json"
    verses = [{"date": k, "reference": f"Book {i + 1}:1 (BSB)", "text": f"Verse number {i + 1} for {k}."}
              for i, k in enumerate(all_date_keys())]
    p.write_text(json.dumps({"verses": verses}), encoding="utf-8")
    return p


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


def make_app(qapp, home, embedded, day, autostart=None):
    from versedesk import paths
    from versedesk.app import VerseDeskApp
    from versedesk.settings import SettingsStore

    store = SettingsStore(paths.settings_path())
    result = store.load()
    today = {"d": day}
    app = VerseDeskApp(
        qapp, store, result,
        autostart=autostart or FakeAutostart(),
        today=lambda: today["d"],
        embedded_verses_path=embedded,
    )
    app.start()
    qapp.processEvents()
    return app, today


def shutdown(app):
    app.day_watch.stop()
    app._poll.stop()
    app.layer.stop()
    app.tray.hide()
    app.verse_widget.hide()
    app.verse_widget.deleteLater()


def test_first_start_shows_todays_verse_top_right_and_writes_settings(qapp, home, embedded):
    auto = FakeAutostart()
    app, _ = make_app(qapp, home, embedded, dt.date(2026, 1, 3), autostart=auto)
    try:
        w = app.verse_widget
        assert w.isVisible()
        assert w.text == "Verse number 3 for 01-03." and w.reference == "Book 3:1 (BSB)"
        assert app.layer.is_click_through(w) is True
        assert (home / "settings.json").exists()
        assert auto.calls == [("sync", True)]  # autostart on by default
        avail = qapp.primaryScreen().availableGeometry()
        assert w.geometry().right() <= avail.right() and w.y() >= avail.y()
        assert w.x() > avail.center().x() - w.width()  # right-hand side
    finally:
        shutdown(app)


def test_date_change_replaces_the_verse(qapp, home, embedded):
    app, today = make_app(qapp, home, embedded, dt.date(2026, 2, 28))
    try:
        today["d"] = dt.date(2026, 3, 1)
        app.day_watch.check()
        assert app.verse_widget.text.endswith("for 03-01.")
        today["d"] = dt.date(2028, 2, 29)  # leap day
        app.day_watch.check()
        assert app.verse_widget.text.endswith("for 02-29.")
    finally:
        shutdown(app)


def test_edit_mode_toggles_click_through_and_drag_saves_position(qapp, home, embedded):
    app, _ = make_app(qapp, home, embedded, dt.date(2026, 5, 5))
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

    app2, _ = make_app(qapp, home, embedded, dt.date(2026, 5, 6))
    try:
        assert (app2.verse_widget.x(), app2.verse_widget.y()) == (100, 120)
    finally:
        shutdown(app2)


def test_off_screen_position_is_brought_back(qapp, home, embedded):
    home.mkdir(parents=True, exist_ok=True)
    (home / "settings.json").write_text(json.dumps({"verse": {"x": 9000, "y": 9000}}), encoding="utf-8")
    app, _ = make_app(qapp, home, embedded, dt.date(2026, 7, 1))
    try:
        avail = qapp.primaryScreen().availableGeometry()
        assert avail.contains(app.verse_widget.geometry())
        # the saved value is kept, so the widget returns if that monitor comes back
        assert json.loads((home / "settings.json").read_text(encoding="utf-8"))["verse"]["x"] == 9000
    finally:
        shutdown(app)


def test_user_verses_file_overrides_and_reloads(qapp, home, embedded):
    app, _ = make_app(qapp, home, embedded, dt.date(2026, 12, 25))
    try:
        user = home / "verses.json"
        user.write_text(json.dumps({"verses": [{"date": "12-25", "reference": "Mine (KJV)", "text": "Custom text."}]}),
                        encoding="utf-8")
        app._poll_files()
        assert app.verse_widget.text == "Custom text." and app.verse_widget.reference == "Mine (KJV)"
        user.write_text("{ broken", encoding="utf-8")
        st = user.stat()
        os.utime(user, ns=(st.st_atime_ns, st.st_mtime_ns + 3_000_000_000))
        app._poll_files()  # broken file: keep showing what we had, no crash
        assert app.verse_widget.text == "Custom text."
        user.unlink()
        app._poll_files()
        assert app.verse_widget.text.endswith("for 12-25.")
    finally:
        shutdown(app)


def test_settings_edited_outside_are_applied(qapp, home, embedded):
    app, _ = make_app(qapp, home, embedded, dt.date(2026, 4, 4))
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
    app, _ = make_app(qapp, home, embedded, dt.date(2026, 4, 4), autostart=auto)
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
    app, _ = make_app(qapp, home, embedded, dt.date(2026, 4, 4))
    try:
        texts = [a.text() for a in app.tray.menu.actions() if not a.isSeparator()]
        assert texts[0].startswith("배치 편집")
        assert any("새 구역" in t for t in texts)
        assert any("자동 실행" in t for t in texts)
        assert texts[-1] == "종료"
        app.tray.edit_mode_toggled.emit(True)
        assert app.edit_mode is True and "끄기" in app.tray.act_edit.text()
    finally:
        shutdown(app)
