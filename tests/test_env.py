import stat
import shutil
import subprocess
import sys
from pathlib import Path


def test_secret_generation_permissions_and_no_overwrite(tmp_path):
    (tmp_path/'scripts').mkdir()
    script = tmp_path/'scripts/init_env.py'
    shutil.copyfile(Path(__file__).resolve().parent.parent/'scripts/init_env.py', script)
    result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert result.returncode == 0
    env = tmp_path/'.env'
    original = env.read_text()
    token = original.split('ADMIN_TOKEN=')[1].splitlines()[0]
    assert len(token) >= 32 and token not in result.stdout
    if sys.platform != 'win32':
        assert stat.S_IMODE(env.stat().st_mode) == 0o600
    again = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert again.returncode == 1 and env.read_text() == original
