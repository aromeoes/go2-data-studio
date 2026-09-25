"""Bundle non-system Mach-O dependencies and rewrite them relative to each binary."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import argparse
import os
import shutil
import subprocess

MAGIC = {b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"}


def macho(path):
    if path.is_symlink() or not path.is_file():
        return False
    with path.open("rb") as stream:
        return stream.read(4) in MAGIC


def dependencies(path):
    output = subprocess.check_output(["otool", "-arch", "arm64", "-L", str(path)], text=True)
    ids = subprocess.check_output(
        ["otool", "-arch", "arm64", "-D", str(path)], text=True
    ).splitlines()[1:]
    return [
        line.strip().split(" (compatibility")[0]
        for line in output.splitlines()[1:]
        if " (compatibility" in line and line.strip().split(" (compatibility")[0] not in ids
    ]


def relocate(root):
    root = root.resolve()
    lib = root / "lib"
    lib.mkdir(exist_ok=True)
    paths = [path for path in root.rglob("*") if macho(path)]
    print(f"Inspecting {len(paths)} native binaries...", flush=True)
    copied = {}
    changed = []
    while paths:
        with ThreadPoolExecutor(max_workers=8) as pool:
            inspected = list(zip(paths, pool.map(dependencies, paths)))
        paths = []
        for binary, deps in inspected:
            updates = []
            for dep in deps:
                if not dep.startswith("/") or dep.startswith(("/usr/lib/", "/System/Library/")):
                    continue
                source = Path(dep)
                if source.is_relative_to(root):
                    target = source
                else:
                    if not source.exists():
                        raise RuntimeError(f"Missing native dependency {dep} for {binary}")
                    target = lib / source.name
                    if target == binary:
                        continue  # dylib install name, not an external dependency
                    if dep not in copied:
                        if target.exists() and target.read_bytes() != source.read_bytes():
                            raise RuntimeError(f"Conflicting native dependency: {source.name}")
                        if not target.exists():
                            shutil.copy2(source, target)
                            paths.append(target)
                        copied[dep] = str(target.relative_to(root))
                relative = "@loader_path/" + os.path.relpath(target, binary.parent)
                if target != binary:
                    updates += ["-change", dep, relative]
            if updates:
                binary.chmod(binary.stat().st_mode | 0o200)
                subprocess.run(
                    ["install_name_tool", *updates, str(binary)],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
                changed.append(binary)
    # Development/ad-hoc signatures restore integrity after changing load commands.
    # Distribution still requires Developer ID signing and notarization.
    for binary in [p for p in root.rglob("*") if macho(p)]:
        subprocess.run(
            ["codesign", "--force", "--sign", "-", str(binary)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    print(
        f"Bundled {len(copied)} native dependencies; relocated {len(changed)} binaries.", flush=True
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runtime", type=Path)
    relocate(parser.parse_args().runtime)
