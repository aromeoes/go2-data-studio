"""Open artifacts using the operating system's file manager."""

from pathlib import Path
import subprocess
import sys


def reveal_file(path: Path):
    if sys.platform == "darwin":
        command = ["open", "-R", str(path)]
    elif sys.platform.startswith("linux"):
        command = ["xdg-open", str(path.parent)]
    else:
        raise ValueError("Opening folders is supported on macOS and Linux")
    try:
        subprocess.run(command, check=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError(
            "Could not open the file manager. Copy the artifact path instead."
        ) from error
