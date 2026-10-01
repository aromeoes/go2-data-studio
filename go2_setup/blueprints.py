"""Module catalog and blueprints for Start Session.

A session connects with the required modules only. When the user starts the
session, the selected modules are added to that same connection; nothing is
removed afterwards. Module ids are the DimOS (or app) class names shown in the UI.
"""

import copy

# Icons are names the UI maps to its icon set.
GO2_MODULES = [
    dict(id="GO2Connection", icons=["camera", "lidar"], summary="Camera, LiDAR and position from the Go2 over Wi-Fi.", official=True, capabilities=["camera", "lidar"], requires=[], required=True),
    dict(id="ControlGate", icons=["gamepad"], summary="Manual driving, with Stop and sensor checks.", official=False, capabilities=["teleop"], requires=[], required=True),
    dict(id="RelayBridgeModule", icons=["relay"], summary="Streams camera, map and status to this app.", official=True, capabilities=[], requires=[], required=True),
    dict(id="VoxelGridMapper", icons=["voxels"], summary="Builds a 3D map of the space from LiDAR.", official=True, capabilities=["mapping"], requires=["GO2Connection"]),
    dict(id="CostMapper", icons=["map"], summary="Turns the 3D map into a 2D map of where the robot can go.", official=True, capabilities=["mapping"], requires=["VoxelGridMapper"]),
    dict(id="ConsoleBridge", icons=["database"], summary="Records sensor data to datasets on this device.", official=False, capabilities=["recording"], requires=[]),
    dict(id="UnitreeSkillContainer", icons=["paw"], summary="Unitree actions such as stand up, sit and greet.", official=True, capabilities=[], requires=["ControlGate"]),
    dict(id="ReplanningAStarPlanner", icons=["route"], summary="Plans routes through the map and replans around obstacles.", official=True, capabilities=["navigation"], requires=["CostMapper"]),
    dict(id="McpClient", icons=["agent"], summary="HumanCLI: talk to the robot and let it use the skills below.", official=True, capabilities=["humancli"], requires=[]),
    dict(id="WavefrontFrontierExplorer", icons=["compass"], summary="Autonomous exploration. Start it from HumanCLI.", official=True, capabilities=["exploration"], requires=["ReplanningAStarPlanner", "McpClient"]),
    dict(id="PatrollingModule", icons=["footprints"], summary="Patrols the mapped area. Start it from HumanCLI.", official=True, capabilities=[], requires=["ReplanningAStarPlanner", "McpClient"]),
    dict(id="NavigationSkillContainer", icons=["pin"], summary="Tag places by name and go back to them.", official=True, capabilities=[], requires=["ReplanningAStarPlanner", "McpClient"]),
    dict(id="PersonFollowSkillContainer", icons=["person"], summary="Follow a person you describe.", official=True, capabilities=[], requires=["McpClient"]),
    dict(id="SpeakSkill", icons=["speaker"], summary="Speak through the Go2 speaker.", official=True, capabilities=[], requires=["McpClient"]),
    dict(id="PushToTalk", icons=["mic"], summary="Voice input to HumanCLI.", official=False, capabilities=["voice"], requires=["McpClient"]),
]

_NO_LIDAR = "No LiDAR"


def _go2_only(ident, reason="Go2 only"):
    item = copy.deepcopy(next(m for m in GO2_MODULES if m["id"] == ident))
    return {**item, "required": False, "unavailable": reason}


VECTOR_MODULES = [
    dict(id="VectorConnection", icons=["camera", "gamepad"], summary="Camera and tread driving over Wi-Fi, with face recognition.", official=False, capabilities=["camera", "teleop", "faces"], requires=[], required=True),
    dict(id="RelayBridgeModule", icons=["relay"], summary="Streams camera and status to this app.", official=True, capabilities=[], requires=[], required=True),
    dict(id="VectorTelemetry", icons=["alert"], summary="Cliff, fall, touch and proximity sensors, battery and temperature.", official=False, capabilities=[], requires=["VectorConnection"], required=True),
    dict(id="McpClient", icons=["agent"], summary="HumanCLI: talk to Vector and let it use the skills below.", official=True, capabilities=["humancli"], requires=[]),
    dict(id="VectorSkills", icons=["agent"], summary="Head, lift, speech and expressive animations.", official=False, capabilities=[], requires=["McpClient"]),
    dict(id="PushToTalk", icons=["mic"], summary="Voice input to HumanCLI.", official=False, capabilities=["voice"], requires=["McpClient"]),
    _go2_only("VoxelGridMapper", _NO_LIDAR),
    _go2_only("CostMapper", _NO_LIDAR),
    _go2_only("ReplanningAStarPlanner", _NO_LIDAR),
    _go2_only("WavefrontFrontierExplorer", _NO_LIDAR),
    _go2_only("PatrollingModule", _NO_LIDAR),
    _go2_only("NavigationSkillContainer", _NO_LIDAR),
    _go2_only("ConsoleBridge", "Not on Vector yet"),
    _go2_only("UnitreeSkillContainer"),
]

MODULES = {"go2": GO2_MODULES, "vector": VECTOR_MODULES}


def _required(kind):
    return [m["id"] for m in MODULES[kind] if m.get("required")]


BLUEPRINTS = {
    "go2": [
        dict(id="teleop", name="Teleop", summary="Drive manually, map the space and record everything.", recommended=True, locked=True,
             modules=_required("go2") + ["VoxelGridMapper", "CostMapper", "ConsoleBridge", "UnitreeSkillContainer"]),
        dict(id="custom", name="Custom", summary="Choose the modules for this session.", recommended=False, locked=False, modules=[]),
    ],
    "vector": [
        dict(id="teleop", name="Teleop", summary="Drive manually with the camera and all sensors.", recommended=True, locked=True,
             modules=_required("vector")),
        dict(id="custom", name="Custom", summary="Choose the modules for this session.", recommended=False, locked=False, modules=[]),
    ],
}

SESSION_PRESETS = {"base", "teleop", "custom"}


def catalog(kind):
    return copy.deepcopy(dict(modules=MODULES[kind], blueprints=BLUEPRINTS[kind]))


def capabilities(kind, modules):
    chosen = set(modules)
    return sorted({c for m in MODULES[kind] if m["id"] in chosen for c in m["capabilities"]})


def validate_modules(kind, preset, modules):
    """Checked module list for a session. Raises ValueError with a readable reason."""
    if kind not in MODULES:
        raise ValueError("Unsupported robot type")
    if preset not in SESSION_PRESETS:
        raise ValueError("Unknown blueprint")
    if not isinstance(modules, list) or any(not isinstance(m, str) for m in modules):
        raise ValueError("Unknown module")
    index = {m["id"]: m for m in MODULES[kind]}
    chosen = set(modules)
    for ident in chosen:
        if ident not in index:
            raise ValueError(f"Unknown module: {ident}")
        if index[ident].get("unavailable"):
            raise ValueError(f"{ident} is not available on this robot: {index[ident]['unavailable']}")
        missing = [r for r in index[ident]["requires"] if r not in chosen]
        if missing:
            raise ValueError(f"{ident} requires {', '.join(missing)}")
    missing = [r for r in _required(kind) if r not in chosen]
    if missing:
        raise ValueError(f"Required modules are missing: {', '.join(missing)}")
    if preset == "base" and chosen != set(_required(kind)):
        raise ValueError("The base connection loads only the required modules")
    if preset == "teleop":
        fixed = next(b for b in BLUEPRINTS[kind] if b["id"] == "teleop")["modules"]
        if chosen != set(fixed):
            raise ValueError("The Teleop blueprint cannot be changed. Choose Custom instead.")
    return [m["id"] for m in MODULES[kind] if m["id"] in chosen]


def session_profile(kind, preset, modules):
    """A capability profile plus the exact module list, accepted by profiles.profile."""
    ordered = validate_modules(kind, preset, modules)
    result = dict(preset=preset, enabled=capabilities(kind, ordered), modules=ordered)
    # Vector profiles are marked so modules and tools pick the Vector variants.
    return {**result, "kind": "vector"} if kind == "vector" else result


def base_profile(kind):
    return session_profile(kind, "base", _required(kind))


def has_module(config, ident):
    """Profiles without a module list predate blueprints and allow everything they enable."""
    modules = (config or {}).get("modules")
    return True if modules is None else ident in modules
