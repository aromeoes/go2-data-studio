"""Reap the private runtime group if its supervising application disappears."""

import os
import signal
import threading
import time


def start_parent_guard(expected_parent: int) -> None:
    def watch():
        while os.getppid() == expected_parent:
            time.sleep(0.25)
        # The supervisor starts this runtime in a new session. Never signal a
        # broader shell/user process group if somebody launches it differently.
        pid = os.getpid()
        if os.getpgrp() == pid:
            os.killpg(pid, signal.SIGTERM)
            time.sleep(2)
            os.killpg(pid, signal.SIGKILL)
        else:
            os.kill(pid, signal.SIGTERM)

    threading.Thread(target=watch, daemon=True, name="supervisor-guard").start()
