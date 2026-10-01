"""Load local pairing material without exposing it through API responses or logs."""

import configparser
import base64
import os
from pathlib import Path


def load_credentials(filename, serial):
    if not serial or not serial.strip():
        raise ValueError("Vector serial is required to select its paired SDK configuration")
    path = Path(filename or "~/.anki_vector/sdk_config.ini").expanduser()
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(path.read_text())
        section = next((s for s in parser.sections() if s.lower() == serial.lower()), None)
        if section is None:
            raise ValueError("Vector serial was not found in the SDK configuration")
        conf = dict(parser[section])
        if not all(conf.get(k) for k in ("name", "cert", "guid")):
            raise ValueError("Vector pairing configuration is incomplete")
        cert = Path(conf["cert"]).expanduser()
        if not cert.is_absolute():
            cert = path.parent / cert
        if not cert.is_file():
            raise ValueError("Vector certificate file was not found on this computer")
        return {"name": conf["name"], "cert": str(cert.resolve()), "guid": conf["guid"]}
    except (OSError, configparser.Error):
        raise ValueError("Cannot read Vector SDK configuration on this computer") from None


def validate_reference(filename, serial):
    filename = str(Path(filename or "~/.anki_vector/sdk_config.ini").expanduser().resolve())
    load_credentials(filename, serial)
    return filename


def renew_credentials(filename, serial, ip):
    """Renew an existing pairing through the robot's normal SDK auth RPC.

    TLS stays pinned to the paired robot certificate. No shared fallback token,
    behavior control, motion, activation or factory reset is used.
    """
    import grpc
    from anki_vector.messaging import client, protocol

    current = load_credentials(filename, serial)
    creds = grpc.ssl_channel_credentials(root_certificates=Path(current["cert"]).read_bytes())
    with grpc.secure_channel(ip + ":443", creds,
                             options=(("grpc.ssl_target_name_override", current["name"]),)) as channel:
        response = client.ExternalInterfaceStub(channel).UserAuthentication(
            protocol.UserAuthenticationRequest(user_session_id=current["guid"].encode(),
                                               client_name=b"Go2 Data Studio"), timeout=15)
    if response.code != protocol.UserAuthenticationResponse.AUTHORIZED:
        raise ValueError("Vector did not authorize SDK pairing renewal")
    token = response.client_token_guid
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    if not isinstance(token, str) or len(base64.b64decode(token, validate=True)) != 16:
        raise ValueError("Vector returned an invalid SDK pairing token")
    path = Path(filename or "~/.anki_vector/sdk_config.ini").expanduser()
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(path.read_text())
    section = next(s for s in parser.sections() if s.lower() == serial.lower())
    if parser[section]["guid"] != current["guid"]:
        # Another explicit pairing update won the race. Do not replace it.
        return load_credentials(filename, serial)
    parser[section]["guid"] = token
    temp = path.with_suffix(path.suffix + ".tmp")
    with open(temp, "w", opener=lambda p, f: os.open(p, f, 0o600)) as stream:
        parser.write(stream)
    temp.chmod(0o600)
    temp.replace(path)
    return load_credentials(filename, serial)
