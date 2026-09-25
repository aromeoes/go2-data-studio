"""Add the installed application to the active Steam profile while Steam is closed.

Requires the small ValvePython `vdf` package in the installation tool environment.
Never edits credentials or changes the client's global controller configuration.
"""

import argparse
import os
import shutil
import subprocess
import time
import zlib
from pathlib import Path

import vdf


def install(application: Path, steam: Path):
    if subprocess.run(["pgrep", "-x", "steam"], stdout=subprocess.DEVNULL, check=False).returncode == 0:
        raise SystemExit("Exit Steam before updating its non-Steam library.")
    executable = application / "launch.sh"
    if not executable.is_file():
        raise SystemExit("Install the application first.")
    users = vdf.load((steam / "config/loginusers.vdf").open())["users"]
    recent = [
        (ident, {k.lower(): value for k, value in user.items()}) for ident, user in users.items()
    ]
    recent.sort(
        key=lambda pair: (
            str(pair[1].get("autologin", "0")).lower() in ("1", "true"),
            int(pair[1].get("timestamp", 0)),
        ),
        reverse=True,
    )
    if not recent:
        raise SystemExit("Sign into Steam before installing its library entry.")
    profile = steam / "userdata" / str(int(recent[0][0]) & 0xFFFFFFFF) / "config"
    profile.mkdir(parents=True, exist_ok=True)
    shortcuts = profile / "shortcuts.vdf"
    data = vdf.binary_load(shortcuts.open("rb")) if shortcuts.exists() else {"shortcuts": {}}
    records = data.setdefault("shortcuts", {})
    name = "Go2 Data Studio"
    exe = f'"{executable}"'
    appid = zlib.crc32((exe + name).encode()) | 0x80000000
    index = next(
        (
            key
            for key, value in records.items()
            if value.get("appname", value.get("AppName")) == name
        ),
        str(max([int(key) for key in records] + [-1]) + 1),
    )
    record = dict(records.get(index, {}))
    record.update(
        {
            "appid": appid - 0x100000000,
            "appname": name,
            "exe": exe,
            "StartDir": f'"{application}"',
            "icon": str(application / "icon.png"),
            "ShortcutPath": "",
            "LaunchOptions": "--steam",
            "IsHidden": 0,
            "AllowDesktopConfig": 0,
            "AllowOverlay": 1,
            "OpenVR": 0,
            "Devkit": 0,
            "DevkitGameID": "",
            "DevkitOverrideAppID": 0,
            "LastPlayTime": record.get("LastPlayTime", 0),
            "FlatpakAppID": "",
            "tags": record.get("tags", {"0": "Robotics"}),
        }
    )
    records[index] = record
    if shortcuts.exists():
        shutil.copy2(shortcuts, profile / f"shortcuts.vdf.go2-backup-{time.time_ns()}")
    temporary = shortcuts.with_suffix(".go2-new")
    with temporary.open("wb") as file:
        vdf.binary_dump(data, file)
    os.replace(temporary, shortcuts)
    grid = profile / "grid"
    grid.mkdir(exist_ok=True)
    for filename, source in (
        (f"{appid}.png", "grid"),
        (f"{appid}p.png", "cover"),
        (f"{appid}_hero.png", "hero"),
    ):
        shutil.copy2(application / "artwork" / f"{source}.png", grid / filename)
    gameid = (appid << 32) | 0x02000000
    print(f"Steam library entry installed. App ID: {appid}; launch: steam://rungameid/{gameid}")
    (application / "steam-game-id").write_text(str(gameid) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("application", type=Path)
    parser.add_argument("--steam", type=Path, default=Path.home() / ".local/share/Steam")
    args = parser.parse_args()
    install(args.application.resolve(), args.steam)
