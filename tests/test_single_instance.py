import subprocess
import sys
import textwrap

from versedesk.single_instance import SingleInstance


def test_second_instance_is_refused_and_lock_released(tmp_path):
    first = SingleInstance(tmp_path)
    assert first.acquire() is True
    code = textwrap.dedent(
        f"""
        import sys
        sys.path.insert(0, {str(__import__('pathlib').Path(__file__).resolve().parent.parent)!r})
        from versedesk.single_instance import SingleInstance
        print(SingleInstance({str(tmp_path)!r}).acquire())
        """
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True).stdout.strip()
    assert out == "False"
    first.release()
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True).stdout.strip()
    assert out == "True"
