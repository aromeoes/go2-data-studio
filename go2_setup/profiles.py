"""Validated product capabilities compiled into a DimOS session configuration.

The UI chooses capabilities; the runtime selects real modules. No arbitrary
Python/module names are accepted from clients. Sensor toggles control application
consumption, never the physical LiDAR's power or onboard localization.
"""

import copy
import json
import os

CAPABILITIES = [
    dict(
        id="teleop",
        name="Manual driving",
        detail="Keyboard or controller driving.",
        requires=[],
        modules=["SDK Teleop"],
    ),
    dict(
        id="camera",
        name="Camera",
        detail="Live camera and optional visual questions.",
        requires=[],
        modules=["PassiveGo2Connection: camera"],
    ),
    dict(
        id="lidar",
        name="LiDAR data",
        detail="Receive LiDAR in this app. Does not switch off the robot's sensor.",
        requires=[],
        modules=["PassiveGo2Connection: LiDAR"],
    ),
    dict(
        id="mapping",
        name="Live mapping",
        detail="Build the 3D map and 2D costmap.",
        requires=["lidar"],
        modules=["VoxelGridMapper", "CostMapper"],
    ),
    dict(
        id="navigation",
        name="Navigation",
        detail="Plan movement through mapped space.",
        requires=["mapping"],
        modules=["ReplanningAStarPlanner"],
    ),
    dict(
        id="exploration",
        name="Autonomous exploration",
        detail="Choose unexplored areas and navigate to them.",
        requires=["navigation"],
        modules=["ConsoleExplorer"],
    ),
    dict(
        id="recording",
        name="Recording",
        detail="Enable recording of selected sensors, position and transforms. Start recording separately.",
        requires=[],
        modules=["ConsoleBridge: SessionWriter / SqliteStore"],
    ),
    dict(
        id="humancli",
        name="HumanCLI",
        detail="Chat with the robot using tools enabled in this session. Requires a configured model.",
        requires=[],
        modules=["DimOS MCP agent worker (application service)"],
    ),
    dict(
        id="voice",
        name="Voice input",
        detail="Push to talk. Requires microphone access and configured OpenAI transcription.",
        requires=["humancli"],
        modules=["Audio capture / transcription (application service)"],
    ),
]
INDEX = {item["id"]: item for item in CAPABILITIES}
REQUIRED_MODULES = [
    "PassiveGo2Connection",
    "ControlGate",
    "ConsoleBridge",
    "ConsoleSDK",
    "DimOS RelayBridgeModule",
]
PRESETS = [
    dict(
        id="map-record",
        name="Teleop + Recording",
        description="Drive manually, map your space and record sensor data.",
        enabled=["teleop", "camera", "lidar", "mapping", "recording"],
    ),
    dict(
        id="assistant",
        name="Full mode agent",
        description="All capabilities, including exploration, HumanCLI and voice.",
        enabled=list(INDEX),
    ),
]


def profile(preset="map-record", enabled=None, kind="go2", modules=None):
    if modules is not None:
        # Blueprint sessions: the module list is the source of truth.
        from go2_setup.blueprints import session_profile

        return session_profile(kind, preset, modules)
    if kind == "vector":
        from go2_setup.vector.profiles import profile as vector_profile
        return vector_profile(preset, enabled)
    if kind != "go2":
        raise ValueError("Unsupported robot type")
    # Preserve the capability selection in older saved Drive profiles.
    if preset == "drive":
        preset = "map-record"
        if enabled is None:
            enabled = ["teleop", "camera"]
    known = next((p for p in PRESETS if p["id"] == preset), None)
    if known is None and preset not in {"preview", "legacy"}:
        raise ValueError("Unknown session preset")
    if enabled is None:
        enabled = (
            known["enabled"] if known else (["camera"] if preset == "preview" else list(INDEX))
        )
    if not isinstance(enabled, list) or any(
        not isinstance(x, str) or x not in INDEX for x in enabled
    ):
        raise ValueError("Unknown capability")
    selected = set(enabled)
    for item in CAPABILITIES:
        if item["id"] in selected:
            missing = set(item["requires"]) - selected
            if missing:
                raise ValueError(
                    item["name"]
                    + " requires "
                    + ", ".join(INDEX[x]["name"] for x in sorted(missing))
                )
    if preset == "preview" and selected != {"camera"}:
        raise ValueError("Preview cannot enable control capabilities")
    return {"preset": preset, "enabled": [x for x in INDEX if x in selected]}


def from_env():
    raw = os.environ.get("GO2_SESSION_PROFILE")
    if not raw:
        return profile("legacy")
    value = json.loads(raw)
    return profile(**value)


def enabled(config, capability):
    return capability in config["enabled"]


def require(config, capability):
    if not enabled(config, capability):
        raise ValueError(INDEX.get(capability, {"name": capability})["name"] + " is disabled in this session")


def module_plan(config):
    if config.get("modules") is not None:
        return list(config["modules"])
    if config.get("kind") == "vector":
        from go2_setup.vector.profiles import REQUIRED
        return [*REQUIRED, *(["VectorSkills"] if enabled(config, "humancli") else [])]
    modules = list(REQUIRED_MODULES)
    for capability in ("mapping", "navigation", "exploration"):
        if enabled(config, capability):
            modules.extend(INDEX[capability]["modules"])
    return modules


def catalog():
    return copy.deepcopy(
        dict(capabilities=CAPABILITIES, presets=PRESETS, required_modules=REQUIRED_MODULES)
    )
