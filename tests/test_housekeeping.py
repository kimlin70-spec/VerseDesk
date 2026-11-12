from versedesk.housekeeping import clean_stale_extractions, stale_extraction_dirs


def _mei(tmp_path, name, ours=True):
    d = tmp_path / name
    (d / "versedesk" / "data").mkdir(parents=True)
    if ours:
        (d / "versedesk" / "data" / "verses.json").write_text("{}", encoding="utf-8")
    (d / "python3.dll").write_bytes(b"x")
    return d


def test_only_versedesk_extractions_other_than_current_are_removed(tmp_path):
    old = _mei(tmp_path, "_MEI1111")
    current = _mei(tmp_path, "_MEI2222")
    other_app = _mei(tmp_path, "_MEI3333", ours=False)
    unrelated = tmp_path / "SomeFolder"
    (unrelated / "versedesk" / "data").mkdir(parents=True)
    (unrelated / "versedesk" / "data" / "verses.json").write_text("{}", encoding="utf-8")

    assert stale_extraction_dirs(tmp_path, current) == [old]
    assert clean_stale_extractions(tmp_path, current) == 1
    assert not old.exists()
    assert current.exists() and other_app.exists() and unrelated.exists()
    assert not list(tmp_path.glob("*.versedesk-old"))


def test_missing_temp_dir_is_harmless(tmp_path):
    assert clean_stale_extractions(tmp_path / "nope", None) == 0
