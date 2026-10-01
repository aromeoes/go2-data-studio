#!/usr/bin/env python3
"""Build a pinned native wire-pod sidecar. Requires Go 1.22.4 and static libopus.

Runs only at build time. No compiler, Docker, brew or pacman is needed by users.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile

SHA = '347c45f7a4dba9adba7fa003c08248d301f19393'
ROOT = Path(__file__).resolve().parent.parent


def run(*args, **kwargs):
    result = subprocess.run(args, text=True, stdout=subprocess.PIPE, **kwargs)
    if result.returncode:
        print(result.stdout)
        raise SystemExit(result.returncode)
    return result.stdout.strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--go', default='go')
    parser.add_argument('--output', type=Path, default=ROOT / 'desktop/runtime/wirepod')
    parser.add_argument('--source', type=Path, help='Clean pinned checkout, otherwise fetched into temporary storage')
    options = parser.parse_args()
    go = shutil.which(options.go)
    if not go or ' go1.22.4 ' not in run(go, 'version'):
        raise SystemExit('Build the server and plugin with Go 1.22.4')
    system = {'Darwin': 'darwin', 'Linux': 'linux'}.get(platform.system())
    arch = {'aarch64': 'arm64', 'arm64': 'arm64', 'x86_64': 'x64'}.get(platform.machine())
    if (system, arch) not in {('darwin', 'arm64'), ('linux', 'x64')}:
        raise SystemExit('Supported builds: Apple Silicon macOS and x64 Linux')
    with tempfile.TemporaryDirectory(prefix='build-wirepod-') as temp:
        temp = Path(temp)
        source = temp / 'source'
        if options.source:
            run('git', 'clone', '--no-local', str(options.source), str(source))
        else:
            run('git', 'clone', 'https://github.com/kercre123/wire-pod.git', str(source))
        run('git', '-C', str(source), 'checkout', '--detach', SHA)
        run('python3', str(ROOT / 'integrations/wirepod/patch-runtime.py'), str(source))
        work = source / 'chipper'
        (work / 'cmd/dimensional').mkdir()
        shutil.copy2(ROOT / 'integrations/wirepod/local-main.go', work / 'cmd/dimensional/main.go')
        # Link opus statically, avoiding Homebrew/Linux runtime library dependencies.
        lib = Path(run('pkg-config', '--variable=libdir', 'opus')) / 'libopus.a'
        if not lib.is_file():
            raise SystemExit('Install the libopus development package with libopus.a')
        includes = run('pkg-config', '--cflags', 'opus')
        pkg = temp / 'pkgconfig'
        pkg.mkdir()
        (pkg / 'opus.pc').write_text(f'Name: opus\nDescription: Static bundled Opus\nVersion: 1.3.1\nLibs: {lib} -lm\nCflags: {includes}\n')
        env = {**os.environ, 'CGO_ENABLED': '1', 'PKG_CONFIG_PATH': str(pkg)}
        if system == 'linux':
            # Debian's static Opus is not PIC. Bundle the SONAME and use a relative rpath.
            env.pop('PKG_CONFIG_PATH', None)
            env['CGO_LDFLAGS'] = '-Wl,-rpath,$ORIGIN/lib'
        output = temp / 'bundle'
        output.mkdir()
        if system == 'linux':
            (output / 'lib').mkdir()
            shutil.copyfile(lib.parent / 'libopus.so.0', output / 'lib/libopus.so.0')
        flags = ['-tags', 'nolibopusfile', '-trimpath']
        if system == 'darwin':
            flags += ['-ldflags=-linkmode=external']  # LC_UUID required by current macOS dyld.
        run(go, 'build', *flags, '-o', str(output / 'wirepod'), './cmd/dimensional', cwd=work, env=env)
        plugin = work / 'cmd/dimensionalplugin'
        plugin.mkdir()
        shutil.copy2(ROOT / 'integrations/wirepod/dimensional.go', plugin / 'main.go')
        shutil.copy2(ROOT / 'integrations/wirepod/dimensional_test.go', plugin / 'main_test.go')
        run(go, 'test', *flags, './cmd/dimensionalplugin', cwd=work, env=env)
        run(go, 'build', *flags, '-buildmode=plugin', '-o', str(output / 'dimensional.so'), './cmd/dimensionalplugin', cwd=work, env=env)
        for name in ('epod', 'intent-data', 'webroot'):
            shutil.copytree(work / name, output / 'assets' / name)
        licenses = output / 'licenses'
        licenses.mkdir()
        shutil.copy2(work / 'LICENSE', licenses / 'wire-pod-LICENSE')
        # Preserve exact modified corresponding source for this bundled GPL service.
        shutil.copytree(ROOT / 'integrations/wirepod', source / 'dimensional-integration', ignore=shutil.ignore_patterns('*.so'))
        shutil.copy2(__file__, source / 'dimensional-integration/build-wirepod.py')
        run('tar', '--exclude=.git', '-czf', str(output / 'corresponding-source.tar.gz'), '-C', str(temp), 'source')
        (licenses / 'NOTICE.txt').write_text('wire-pod source: https://github.com/kercre123/wire-pod\nPinned revision: '+SHA+'\nModified corresponding source and Dimensional integration are included in corresponding-source.tar.gz.\nOpus: https://opus-codec.org/ (BSD-3-Clause).\nGo: https://go.dev/ (BSD-3-Clause).\n')
        # Include Go dependency licenses as well as compiler/runtime notices.
        modules = run(go, 'list', '-m', '-f', '{{.Dir}}', 'all', cwd=work, env=env).splitlines()
        for i, directory in enumerate(modules):
            if not directory:
                continue
            for file in Path(directory).glob('*'):
                if file.is_file() and (file.name.lower().startswith(('license', 'copying', 'notice'))):
                    shutil.copy2(file, licenses / (str(i) + '-' + file.name))
        shutil.copy2(Path(run(go, 'env', 'GOROOT')) / 'LICENSE', licenses / 'Go-LICENSE')
        opus_license = ROOT / 'integrations/wirepod/opus-LICENSE'
        shutil.copy2(opus_license, licenses / 'Opus-LICENSE')
        if system == 'darwin':
            for binary in ('wirepod', 'dimensional.so'):
                run('codesign', '--force', '--sign', '-', str(output / binary))
        checksums = {name: hashlib.sha256((output/name).read_bytes()).hexdigest() for name in ('wirepod', 'dimensional.so')}
        (output / 'runtime.json').write_text(json.dumps(dict(format=1, sha=SHA, platform=system, arch=arch, go='1.22.4', sha256=checksums), indent=2)+'\n')
        options.output.parent.mkdir(parents=True, exist_ok=True)
        staging = options.output.with_name(options.output.name + '.building')
        if staging.exists():
            shutil.rmtree(staging)
        shutil.copytree(output, staging)
        if options.output.exists():
            shutil.rmtree(options.output)
        staging.rename(options.output)
        print(f'Built {system}/{arch}: {options.output}')

if __name__ == '__main__':
    main()
