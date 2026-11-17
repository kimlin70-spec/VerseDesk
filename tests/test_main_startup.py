"""What the start-up lines in log.txt say about the system."""

import re
import sys

from versedesk import main


def test_the_windows_build_is_named_with_its_update_number():
    text = main._windows_build()
    if sys.platform == "win32":  # (the CI runs this on real Windows)
        assert re.fullmatch(r"Windows \S+, build \d+\.\d+", text), text
    else:
        assert text == ""
