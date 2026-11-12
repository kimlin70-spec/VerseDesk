from versedesk.geometry import Rect, clamp_into, place_on_screens, top_right

PRIMARY = Rect(0, 0, 1920, 1040)  # 1080p minus taskbar
LEFT = Rect(-1280, 0, 1280, 984)  # second monitor to the left
SCREENS = [PRIMARY, LEFT]


def test_inside_a_screen_is_unchanged():
    r = Rect(100, 100, 500, 200)
    assert place_on_screens(r, SCREENS, PRIMARY) == r
    r2 = Rect(-1000, 50, 500, 200)
    assert place_on_screens(r2, SCREENS, PRIMARY) == r2


def test_mostly_on_a_screen_is_nudged_onto_it():
    r = Rect(1700, 100, 500, 200)  # 280px hang off the right edge
    assert place_on_screens(r, SCREENS, PRIMARY) == Rect(1420, 100, 500, 200)


def test_far_off_screen_moves_to_primary():
    r = Rect(5000, 3000, 500, 200)
    placed = place_on_screens(r, SCREENS, PRIMARY)
    assert PRIMARY.contains_rect(placed)


def test_monitor_unplugged_moves_to_primary():
    r = Rect(-1000, 50, 500, 200)  # was on LEFT
    placed = place_on_screens(r, [PRIMARY], PRIMARY)
    assert PRIMARY.contains_rect(placed)
    assert placed.y == 50  # vertical position kept when possible


def test_straddling_two_screens_goes_to_the_one_showing_more():
    r = Rect(-100, 100, 500, 200)  # 100 on LEFT, 400 on PRIMARY
    assert place_on_screens(r, SCREENS, PRIMARY) == Rect(0, 100, 500, 200)


def test_taller_than_screen_aligns_top():
    r = Rect(10, 500, 300, 5000)
    assert clamp_into(r, PRIMARY) == Rect(10, 0, 300, 5000)


def test_no_screens_at_all_falls_back_to_primary_rect():
    r = Rect(9999, 9999, 100, 100)
    assert PRIMARY.contains_rect(place_on_screens(r, [], PRIMARY))


def test_top_right_default():
    r = top_right(PRIMARY, 520, 230, 40, 40)
    assert r == Rect(1920 - 520 - 40, 40, 520, 230)


def test_top_right_on_tiny_screen_stays_inside():
    small = Rect(0, 0, 400, 300)
    r = top_right(small, 520, 230, 40, 40)
    assert r.x == 0 and r.y == 40


def test_top_right_respects_screen_origin():
    r = top_right(LEFT, 520, 230, 40, 40)
    assert r.x == -1280 + 1280 - 520 - 40 and r.y == 40
