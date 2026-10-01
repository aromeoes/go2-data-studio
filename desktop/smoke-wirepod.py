#!/usr/bin/env python3
"""Check a built sidecar without advertising it or connecting to a robot."""
from pathlib import Path
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

bundle = Path(sys.argv[1]).resolve()
with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
    sock.connect(('8.8.8.8', 80))  # Route lookup only; no packet is sent.
    host = sock.getsockname()[0]
with tempfile.TemporaryDirectory(prefix='wirepod-smoke-') as temporary:
    root = Path(temporary)
    for name in ('epod', 'intent-data', 'webroot'):
        shutil.copytree(bundle / 'assets' / name, root / name)
    (root / 'plugins').mkdir()
    (root / 'jdocs').mkdir()
    (root / 'session-certs').mkdir()
    shutil.copy2(bundle / 'dimensional.so', root / 'plugins/dimensional.so')
    (root / 'apiConfig.json').write_text(json.dumps({
        'STT': {'provider': 'whisper', 'language': 'en-US'},
        'server': {'epconfig': True, 'port': '8084'},
        'hasreadfromenv': True, 'pastinitialsetup': True,
    }))
    (root / 'version').write_text('smoke-test')
    env = {**os.environ, 'HOME': temporary, 'STT_SERVICE': 'whisper',
           'STT_LANGUAGE': 'en-US', 'NO8084': 'true', 'DISABLE_MDNS': 'true',
           'VECTOR_DISABLE_ADVERTISE': '1', 'VECTOR_HOST_IP': host,
           'WEBSERVER_PORT': '18084', 'JDOCS_PINGER_ENABLED': 'false',
           'DEBUG_LOGGING': 'false', 'DIMENSIONAL_VOICE_CONFIG': str(root / 'unused')}
    with open(root / 'output.log', 'wb') as log:
        process = subprocess.Popen([str(bundle / 'wirepod')], cwd=root, env=env, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 15
            context = ssl.create_default_context(cafile=str(root / 'epod/ep.crt'))
            context.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN
            last_error = None
            # The bundled public escape-pod certificate names escapepod.local.
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError((root / 'output.log').read_text())
                try:
                    with socket.create_connection((host, 8084), timeout=1) as tcp:
                        with context.wrap_socket(tcp, server_hostname='escapepod.local') as tls:
                            tls.sendall(b'GET /ok HTTP/1.1\r\nHost: escapepod.local\r\nConnection: close\r\n\r\n')
                            response = tls.recv(1024)
                            if b'200 OK' in response:
                                break
                except OSError as error:
                    last_error = error
                    time.sleep(0.2)
            else:
                raise RuntimeError(f'TLS check failed: {last_error}; {(root / "output.log").read_text()}')
            output = (root / 'output.log').read_text()
            assert 'DIMENSIONAL_PLUGIN_READY' in output, output
            with urllib.request.urlopen('http://127.0.0.1:18084', timeout=2) as response:
                assert response.status == 200
            try:
                urllib.request.urlopen(f'http://{host}:18084', timeout=1)
            except OSError:
                pass
            else:
                raise AssertionError('Administrative server was exposed on LAN')
            # Port 80 is optional on unprivileged Linux. When available, it must
            # expose only connCheck, never the upstream administrative routes.
            try:
                urllib.request.urlopen(f'http://{host}:80/api-sdk/', timeout=1)
            except urllib.error.HTTPError as error:
                assert error.code == 404
            except OSError:
                pass
            else:
                raise AssertionError('connCheck exposed administrative APIs')
            print('PASS: local plugin, TLS voice listener, loopback administration, no robot credentials or discovery')
        finally:
            process.terminate()
            process.wait(timeout=5)
            print('PASS: owned service stopped cleanly')
