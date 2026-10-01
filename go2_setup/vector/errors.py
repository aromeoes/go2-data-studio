"""Fixed, credential-free startup diagnostics shared by worker and supervisor."""

import json
import os
from pathlib import Path

CONNECTION_ERRORS = {
    "VectorUnauthenticatedException": "Vector rejected its SDK pairing token. Restore this computer's wire-pod pairing and restart Vector on its charger.",
    "VectorNotFoundException": "Vector is not responding. Check its Wi-Fi IP and that it is powered on.",
    "VectorInvalidVersionException": "Vector firmware and the installed SDK are incompatible.",
}
DEFAULT_ERROR = "Vector authentication/connection failed. Check IP, SDK pairing and certificate on this computer."


def report_startup_error(code):
    filename = os.environ.get("VECTOR_STARTUP_ERROR_FILE")
    if not filename or code not in CONNECTION_ERRORS:
        return
    try:
        path = Path(filename)
        temp = path.with_suffix(".tmp")
        with open(temp, "w", opener=lambda p, f: os.open(p, f, 0o600)) as stream:
            json.dump({"code": code}, stream)
        temp.replace(path)
    except OSError:
        pass  # Reporting must not mask the original connection error.


def read_startup_error(path):
    try:
        data = json.loads(path.read_text())
        return CONNECTION_ERRORS.get(data.get("code")) if isinstance(data, dict) else None
    except (OSError, ValueError, TypeError):
        return None
