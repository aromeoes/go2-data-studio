from dataclasses import dataclass
from pathlib import Path
import os

MAIN_SHA = "c1c3cdc9d2ee54ca72259465688395699d7d99a2"


@dataclass
class Settings:
    root: Path = Path(os.environ.get("GO2_SPACES", str(Path.home() / "Go2Spaces")))
    runtime: Path = Path(
        os.environ.get(
            "DIMOS_RUNTIME", str(Path(__file__).resolve().parents[2] / "dimos-runtime")
        )
    )
    serial: str = os.environ.get("GO2_SERIAL", "")
    port: int = int(os.environ.get("GO2_SETUP_PORT", "8780"))
    runtime_port: int = int(os.environ.get("GO2_RUNTIME_PORT", "8781"))
    replay_only: bool = os.environ.get("GO2_REPLAY_ONLY") == "1"
    relay_port: int = int(os.environ.get("GO2_RELAY_PORT", "8782"))
    env_file: Path = Path(
        os.environ.get("GO2_ENV_FILE", str(Path(__file__).resolve().parents[1] / ".env"))
    )

    @property
    def python(self) -> str:
        return str(self.runtime / ".venv/bin/python")

    def initialize(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.root.chmod(0o700)
        (self.root / "spaces").mkdir(exist_ok=True)
