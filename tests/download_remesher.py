"""Exercise missing-install download without altering the existing install."""
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import external_remesher

with tempfile.TemporaryDirectory(prefix='autoremesher_download_test_') as folder:
    folder = Path(folder)
    external_remesher.__file__ = str(folder / 'external_remesher.py')
    executable = external_remesher.ensure_executable(folder / 'autoremesher/autoremesher.exe')
    assert executable.is_file()
    assert (executable.parent / 'Qt5Core.dll').is_file()
    assert external_remesher.ensure_executable(executable) == executable
print('PASS: download, checksum, extraction, dependencies and existing-install reuse')
