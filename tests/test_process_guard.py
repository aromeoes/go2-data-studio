import os
from pathlib import Path
import subprocess
import sys
import time


def test_private_runtime_exits_when_supervisor_disappears(tmp_path):
    ready = tmp_path / "ready"
    child_code = """
import os,sys,time
from pathlib import Path
from go2_setup.process_guard import start_parent_guard
start_parent_guard(int(sys.argv[1]))
Path(sys.argv[2]).write_text(str(os.getpid()))
time.sleep(30)
"""
    parent_code = """
import os,subprocess,sys,time
from pathlib import Path
child=subprocess.Popen([sys.executable,'-c',sys.argv[1],str(os.getpid()),sys.argv[2]],start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
for _ in range(100):
    if Path(sys.argv[2]).exists():break
    time.sleep(.02)
else:raise RuntimeError('Child did not initialize')
"""
    environment = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parent.parent)}
    subprocess.run(
        [sys.executable, "-c", parent_code, child_code, str(ready)],
        env=environment,
        check=True,
        timeout=5,
    )
    pid = int(ready.read_text())
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        os.kill(pid, 9)
        raise AssertionError("The orphan runtime did not exit")
