"""Assemble a relocatable macOS runtime from a validated dependency environment.

DimOS source comes exclusively from the pinned GitHub archive. The configured
venv supplies installed third-party distributions, never its editable sources.
Run using that venv's Python. No credentials, caches or datasets are copied.
"""

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import sysconfig
import tarfile
import zipfile

SHA = "c1c3cdc9d2ee54ca72259465688395699d7d99a2"


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def ignore(directory, names):
    return [
        name
        for name in names
        if name == "__pycache__"
        or name.endswith(".pyc")
        or name.startswith("__editable__")
        or name in ("_virtualenv.pth", "_virtualenv.py")
    ]


def assemble(args):
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise SystemExit("This runtime builder currently supports macOS Apple Silicon only.")
    root = args.output.resolve()
    if root.exists():
        raise SystemExit(f"Output already exists: {root}. Choose a fresh directory.")
    root.mkdir(parents=True)
    print("Copying standalone Python and installed dependencies...", flush=True)
    shutil.copytree(sys.base_prefix, root / "python", ignore=ignore, symlinks=True)
    site = (
        root
        / "python/lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "site-packages"
    )
    source_site = Path(sysconfig.get_path("purelib"))
    shutil.copytree(source_site, site, dirs_exist_ok=True, ignore=ignore, symlinks=True)
    # Installed metadata may contain private build paths. Keep package licenses,
    # entry points and version metadata; remove install provenance and stale RECORDs.
    for metadata in site.glob("*.dist-info"):
        for name in ("direct_url.json", "RECORD"):
            (metadata / name).unlink(missing_ok=True)
    # Editable DimOS is replaced by upstream source, never the developer checkout.
    if (site / "dimos").exists():
        shutil.rmtree(site / "dimos")
    print("Installing pinned DimOS archive...", flush=True)
    with tarfile.open(args.dimos_archive) as archive:
        for member in archive.getmembers():
            parts = Path(member.name).parts[1:]
            if not parts or ".." in parts or not member.isfile():
                continue
            if parts[0] == "dimos":
                target = site.joinpath(*parts)
            elif len(parts) == 1 and parts[0] in ("LICENSE", "pyproject.toml"):
                target = root / parts[0]
            else:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as src, target.open("wb") as dest:
                shutil.copyfileobj(src, dest)
    bin_dir = root / ".venv/bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "python").symlink_to("../../python/bin/python3")
    # Rewrite entry points to locate Python relative to themselves after relocation.
    for name, module, function in (
        ("dimos", "dimos.cli.dimos", "cli_main"),
        ("rerun", "rerun_cli.__main__", "main"),
    ):
        launcher = bin_dir / name
        launcher.write_text(
            '#!/bin/sh\nexec "$(dirname "$0")/python" -c '
            f"'from {module} import {function}; {function}()' \"$@\"\n"
        )
        launcher.chmod(0o755)
    # Standalone Python may contain other absolute-shebang console tools. They
    # are not part of the application runtime contract.
    for entry in (root / "python/bin").iterdir():
        if entry.is_file() and not entry.is_symlink() and entry.read_bytes()[:2] == b"#!":
            entry.unlink()
    (root / "bin").mkdir()
    with zipfile.ZipFile(args.deno_archive) as archive:
        (root / "bin/deno").write_bytes(archive.read("deno"))
    (root / "bin/deno").chmod(0o755)
    # ctypes' JPEG loader also needs a library that isn't declared as a Mach-O
    # dependency. Its transitive dependencies are collected by relocate-native.py.
    lib = root / "lib"
    lib.mkdir()
    shutil.copy2(args.turbojpeg, lib / "libturbojpeg.dylib")
    packages = sorted(
        {
            f"{d.metadata['Name']}=={d.version}"
            for d in importlib.metadata.distributions()
            if d.metadata["Name"] and d.metadata["Name"].lower() != "go2-data-studio"
        }
    )
    manifest = {
        "format": 1,
        "dimos_sha": SHA,
        "platform": "darwin",
        "arch": "arm64",
        "python": platform.python_version(),
        "deno": run(str(root / "bin/deno"), "--version").splitlines()[0],
        "source_sha256": hashlib.sha256(args.dimos_archive.read_bytes()).hexdigest(),
        "deno_archive_sha256": hashlib.sha256(args.deno_archive.read_bytes()).hexdigest(),
        "packages": packages,
    }
    (root / "runtime.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Runtime assembled: {root}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dimos-archive", type=Path, required=True)
    parser.add_argument("--deno-archive", type=Path, required=True)
    parser.add_argument("--turbojpeg", type=Path, required=True)
    assemble(parser.parse_args())
