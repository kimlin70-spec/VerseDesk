"""The Explorer window slot: settings, and the logical -> native arithmetic."""

import pytest

from versedesk.explorer_slot import (
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    MIN_HEIGHT,
    MIN_WIDTH,
    ScreenInfo,
    SlotSettings,
    close_enough,
    default_rect,
    fit_into,
    outer_rect,
    screen_for,
    slot_from_dict,
    slot_to_dict,
    to_native,
)
from versedesk.geometry import Rect


def test_defaults_are_off_and_unplaced():
    s, warnings = slot_from_dict(None)
    assert warnings == [] and s == SlotSettings()
    assert s.enabled is False and not s.has_position
    assert (s.width, s.height) == (DEFAULT_WIDTH, DEFAULT_HEIGHT)


def test_round_trip():
    data = {"enabled": True, "x": -1200, "y": 40, "width": 1000, "height": 700}
    s, warnings = slot_from_dict(data)
    assert warnings == [] and slot_to_dict(s) == data and s.has_position


def test_numbers_typed_as_text_are_accepted():
    s, warnings = slot_from_dict({"x": "100", "y": "50.4", "width": "800"})
    assert warnings == [] and (s.x, s.y, s.width) == (100, 50, 800)


@pytest.mark.parametrize("bad", [
    {"enabled": "yes"},
    {"x": 10, "y": None},  # only one of the two
    {"x": "left", "y": 5},
    {"width": MIN_WIDTH - 1},
    {"height": 99999},
    {"width": True},
    {"height": 1e400},
])
def test_invalid_values_keep_the_previous_ones(bad):
    prev = SlotSettings(True, 30, 40, 1000, 700)
    s, warnings = slot_from_dict({"enabled": True, "x": 30, "y": 40, "width": 1000, "height": 700, **bad}, prev)
    assert len(warnings) == 1
    assert s == prev


def test_not_an_object_keeps_everything():
    prev = SlotSettings(True, 1, 2, 800, 600)
    s, warnings = slot_from_dict([1, 2], prev)
    assert s == prev and len(warnings) == 1


def test_default_rect_is_centred_and_fits_small_screens():
    r = default_rect(Rect(0, 0, 1920, 1040), DEFAULT_WIDTH, DEFAULT_HEIGHT)
    assert (r.w, r.h) == (900, 600) and r.x == (1920 - 900) // 2 and r.y == (1040 - 600) // 2
    small = default_rect(Rect(0, 0, 1024, 728), DEFAULT_WIDTH, DEFAULT_HEIGHT)
    assert small.w == 900 and small.h == 600 and Rect(0, 0, 1024, 728).contains_rect(small)
    tiny = default_rect(Rect(0, 0, 800, 560), DEFAULT_WIDTH, DEFAULT_HEIGHT)
    assert (tiny.w, tiny.h) == (720, 480) and Rect(0, 0, 800, 560).contains_rect(tiny)
    assert default_rect(Rect(0, 0, 500, 300), 900, 600).w == MIN_WIDTH  # never below the minimum
    assert default_rect(Rect(0, 0, 500, 300), 900, 600).h == MIN_HEIGHT


def test_native_equals_logical_at_100_percent():
    screens = [ScreenInfo(Rect(0, 0, 1920, 1080), 1.0)]
    assert to_native(Rect(300, 120, 900, 600), screens) == (300, 120, 1200, 720)
    assert to_native(Rect(300, 120, 900, 600), []) is None


def test_native_on_a_scaled_main_screen():
    screens = [ScreenInfo(Rect(0, 0, 1536, 864), 1.25)]  # 1920x1080 at 125 %
    assert to_native(Rect(100, 80, 800, 600), screens) == (125, 100, 1125, 850)


def test_halves_round_up_like_qt_does():
    """At 125 % two logical pixels are 2.5 native ones: Qt shows the frame at 3, so must we."""
    screens = [ScreenInfo(Rect(0, 0, 1536, 864), 1.25)]
    assert to_native(Rect(2, 6, 482, 322), screens) == (3, 8, 3 + 603, 8 + 403)  # 2.5->3, 7.5->8, 602.5->603, 402.5->403


def test_native_on_a_second_monitor_with_another_scale():
    """The screen's corner is the same point in both spaces; distances from it are scaled."""
    main = ScreenInfo(Rect(0, 0, 1280, 720), 1.5)  # 1920x1080 at 150 %
    right = ScreenInfo(Rect(1920, 0, 2560, 1440), 1.0)  # starts at native x = 1920
    left = ScreenInfo(Rect(-1536, 0, 1536, 864), 1.25)  # 1920 wide at 125 %, left of the main screen
    screens = [main, right, left]
    assert to_native(Rect(2000, 100, 900, 600), screens) == (2000, 100, 2900, 700)
    assert to_native(Rect(100, 100, 800, 500), screens) == (150, 150, 1350, 900)
    assert to_native(Rect(-1436, 80, 800, 600), screens) == (-1536 + 125, 100, -1536 + 125 + 1000, 850)


def test_the_screen_is_chosen_by_the_centre_then_by_overlap():
    a, b = ScreenInfo(Rect(0, 0, 1000, 800), 1.0), ScreenInfo(Rect(1000, 0, 1000, 800), 2.0)
    assert screen_for(Rect(700, 100, 500, 400), [a, b]) is a  # centre x = 950
    assert screen_for(Rect(800, 100, 500, 400), [a, b]) is b  # centre x = 1050
    assert screen_for(Rect(-400, 900, 500, 400), [a, b]) is a  # centre off every screen: most overlap, else the first
    assert screen_for(Rect(5000, 5000, 500, 400), [a, b]) is a


def test_invisible_borders_are_added_around_the_slot():
    target = (300, 120, 1200, 720)
    window = (93, 100, 907, 607)  # GetWindowRect: 7 px wider left/right/bottom than what is seen
    visible = (100, 100, 900, 600)
    assert outer_rect(target, window, visible) == (293, 120, 1207, 727)
    assert outer_rect(target, visible, visible) == target  # no invisible border (e.g. measurement unavailable)
    assert outer_rect(target, (0, 0, 2000, 2000), visible) == target  # nonsense measurement: ignored


def test_a_slot_larger_than_the_screen_is_shrunk_to_fit():
    area = Rect(0, 0, 1366, 728)
    assert fit_into(Rect(100, 50, 1600, 1000), area) == Rect(0, 0, 1366, 728)
    assert fit_into(Rect(900, 50, 800, 500), area) == Rect(566, 50, 800, 500)  # only moved
    assert fit_into(Rect(100, 50, 800, 500), area) == Rect(100, 50, 800, 500)  # untouched


def test_rounding_is_qts_also_for_negative_values():
    from versedesk.explorer_slot import _qround

    assert [_qround(v) for v in (2.5, 3.5, -2.5, -0.4, 0.49)] == [3, 4, -3, 0, 0]


def test_close_enough():
    assert close_enough((0, 0, 100, 100), (1, -1, 100, 101))
    assert not close_enough((0, 0, 100, 100), (2, 0, 100, 100))
    assert close_enough((0, 0, 100, 100), (2, 0, 100, 100), tolerance=2)
