"""Version string, plus the CI build number when the exe was built by GitHub Actions."""

from versedesk import __version__

try:  # written by the CI workflow right before PyInstaller runs; absent in development
    from versedesk._build_info import BUILD  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - depends on build environment
    BUILD = "dev"


def version_string() -> str:
    return f"{__version__} ({BUILD})"
