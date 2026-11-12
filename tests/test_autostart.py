import sys
from pathlib import Path

import pytest

from versedesk.autostart import (
    APPROVED_KEY,
    RUN_KEY,
    VALUE_NAME,
    Autostart,
    approved_flag_enabled,
    launch_command,
)


class FakeRegistry:
    def __init__(self):
        self.values = {}

    def get(self, key, name):
        return self.values.get((key, name))

    def set_string(self, key, name, value):
        self.values[(key, name)] = value

    def delete(self, key, name):
        self.values.pop((key, name), None)


EXE = Path("C:/Users/Kim/Documents/VerseDesk/VerseDesk.exe")


def test_launch_command_is_quoted():
    assert launch_command(Path("C:/Program Files/X/VerseDesk.exe")).startswith('"')
    assert launch_command(Path("C:/Program Files/X/VerseDesk.exe")).endswith('VerseDesk.exe"')


@pytest.mark.parametrize(
    "value, enabled",
    [(None, True), (b"\x02" + b"\x00" * 11, True), (b"\x06" + b"\x00" * 11, True),
     (b"\x03" + b"\x00" * 11, False), (b"\x07" + b"\x00" * 11, False), (b"", True), ("text", True)],
)
def test_startup_approved_flag(value, enabled):
    assert approved_flag_enabled(value) is enabled


def test_first_run_registers_and_reports_enabled():
    reg = FakeRegistry()
    a = Autostart(reg, EXE)
    assert a.sync_at_startup(True) is True
    assert reg.get(RUN_KEY, VALUE_NAME) == launch_command(EXE)


def test_moved_exe_updates_the_path():
    reg = FakeRegistry()
    reg.set_string(RUN_KEY, VALUE_NAME, '"D:/old/VerseDesk.exe"')
    assert Autostart(reg, EXE).sync_at_startup(True) is True
    assert reg.get(RUN_KEY, VALUE_NAME) == launch_command(EXE)


def test_task_manager_disable_is_respected_at_startup_but_menu_reenables():
    reg = FakeRegistry()
    a = Autostart(reg, EXE)
    a.enable()
    reg.values[(APPROVED_KEY, VALUE_NAME)] = b"\x03" + b"\x00" * 11  # user disabled it in Task Manager
    assert a.sync_at_startup(True) is False
    assert (APPROVED_KEY, VALUE_NAME) in reg.values
    assert a.enable() is True and a.is_enabled() is True
    assert (APPROVED_KEY, VALUE_NAME) not in reg.values


def test_unwanted_entry_is_removed():
    reg = FakeRegistry()
    reg.set_string(RUN_KEY, VALUE_NAME, launch_command(EXE))
    assert Autostart(reg, EXE).sync_at_startup(False) is False
    assert reg.get(RUN_KEY, VALUE_NAME) is None


def test_development_checkout_never_touches_registry():
    reg = FakeRegistry()
    a = Autostart(reg, None)  # not a frozen exe
    assert a.supported is False
    assert a.sync_at_startup(True) is False
    assert a.enable() is False
    assert reg.values == {}


@pytest.mark.skipif(sys.platform != "win32", reason="real registry only on Windows")
def test_real_registry_roundtrip():
    from versedesk import autostart as mod

    backend = mod.WinRegBackend()
    test_key = r"Software\VerseDeskTest\Run"
    try:
        backend.set_string(test_key, "X", '"C:\\a b\\c.exe"')
        assert backend.get(test_key, "X") == '"C:\\a b\\c.exe"'
        backend.delete(test_key, "X")
        assert backend.get(test_key, "X") is None
        backend.delete(test_key, "X")  # deleting twice is fine
    finally:
        import winreg

        for k in (r"Software\VerseDeskTest\Run", r"Software\VerseDeskTest"):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, k)
            except OSError:
                pass


def test_startup_never_clears_a_task_manager_disable_even_when_re_registering():
    reg = FakeRegistry()
    reg.values[(APPROVED_KEY, VALUE_NAME)] = b"\x03" + b"\x00" * 11  # disabled in Task Manager
    a = Autostart(reg, EXE)
    assert a.sync_at_startup(True) is False  # Run value written, but the user's "off" stays
    assert reg.get(RUN_KEY, VALUE_NAME) == launch_command(EXE)
    assert (APPROVED_KEY, VALUE_NAME) in reg.values


def test_paths_differing_only_in_case_or_quotes_are_not_rewritten():
    from versedesk.autostart import same_command

    reg = FakeRegistry()
    reg.set_string(RUN_KEY, VALUE_NAME, launch_command(EXE).upper() if sys.platform == "win32" else launch_command(EXE))
    writes = []
    original = reg.set_string
    reg.set_string = lambda *a: writes.append(a) or original(*a)
    Autostart(reg, EXE).sync_at_startup(True)
    assert writes == []
    assert same_command('"C:/A/B.exe"', "C:/A/B.exe")
    assert not same_command('"C:/A/B.exe"', '"C:/A/C.exe"')
    assert not same_command(None, '"C:/A/B.exe"')
