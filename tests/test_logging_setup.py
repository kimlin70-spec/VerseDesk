import logging

from versedesk import logging_setup


def test_crash_report_adopted_then_cleared_on_clean_exit(tmp_path):
    log_file = tmp_path / "log.txt"
    crash = tmp_path / "crash.txt"
    crash.write_text("Windows fatal exception: access violation\n", encoding="utf-8")
    logging_setup.setup_logging(log_file)
    logging_setup.enable_crash_report(crash)
    logging.getLogger("versedesk.test").info("hello")
    logging_setup.shutdown_logging(clean_exit=True)
    text = log_file.read_text(encoding="utf-8")
    assert "faulthandler output from the previous run" in text and "WARNING" in text
    assert crash.read_text(encoding="utf-8") == ""


def test_setup_without_crash_report_does_not_touch_crash_file(tmp_path):
    crash = tmp_path / "crash.txt"
    crash.write_text("from the running instance", encoding="utf-8")
    logging_setup.setup_logging(tmp_path / "log.txt")  # e.g. a duplicate launch
    logging_setup.shutdown_logging(clean_exit=False)
    assert crash.read_text(encoding="utf-8") == "from the running instance"
