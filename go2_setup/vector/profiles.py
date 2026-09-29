"""Vector capabilities deliberately exclude Go2 mapping and navigation."""

import copy

CAPABILITIES = [
    dict(
        id="teleop",
        name="Manual driving",
        detail="Differential tread driving. No sideways motion.",
        requires=[],
        modules=["VectorConnection: guarded tread control"],
    ),
    dict(
        id="camera",
        name="Camera",
        detail="Live RGB camera over the DimOS Web SDK.",
        requires=[],
        modules=["VectorConnection: camera"],
    ),
    dict(
        id="faces",
        name="Native face recognition",
        detail="Read faces recognized by Vector. Names must already be enrolled on the robot.",
        requires=[],
        modules=["VectorConnection: onboard vision"],
    ),
    dict(
        id="humancli",
        name="HumanCLI",
        detail="Bounded movement, head, lift, speech and expressive animations.",
        requires=[],
        modules=["VectorSkills", "DimOS MCP agent worker"],
    ),
    dict(
        id="voice",
        name="Voice input",
        detail="Mac/Deck push to talk and paired wire-pod transcript input.",
        requires=["humancli"],
        modules=["Audio capture / wire-pod bridge"],
    ),
]
PRESETS = [
    dict(
        id="drive",
        name="Drive",
        description="Camera, sensors and manual tread controls.",
        enabled=["teleop", "camera", "faces"],
    ),
    dict(
        id="assistant",
        name="Agent assistant",
        description="Talk to Vector, use native faces and expressive actions.",
        enabled=["teleop", "camera", "faces", "humancli", "voice"],
    ),
]
REQUIRED = ["VectorConnection", "VectorTelemetry", "ConsoleSDK", "DimOS RelayBridgeModule"]


def catalog():
    return copy.deepcopy(
        dict(capabilities=CAPABILITIES, presets=PRESETS, required_modules=REQUIRED)
    )


def profile(preset="assistant", enabled=None):
    known = next((p for p in PRESETS if p["id"] == preset), None)
    if known is None and preset != "preview":
        raise ValueError("This preset is not available for Vector")
    values = known["enabled"] if known else ["camera"]
    if enabled is not None:
        values = enabled
    if not isinstance(values, list) or any(
        not isinstance(v, str) or v not in {c["id"] for c in CAPABILITIES} for v in values
    ):
        raise ValueError("Unsupported Vector capability")
    if "voice" in values and "humancli" not in values:
        raise ValueError("Voice input requires HumanCLI")
    if preset == "preview" and set(values) != {"camera"}:
        raise ValueError("Preview cannot enable control capabilities")
    return dict(
        kind="vector", preset=preset, enabled=[c["id"] for c in CAPABILITIES if c["id"] in values]
    )
