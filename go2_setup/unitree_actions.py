"""Operator action adapter using the pinned DimOS registry and skill dispatcher."""

from functools import lru_cache
from types import SimpleNamespace

# The upstream skill only dispatches a name, without an argument payload.
# Show these entries, but do not issue incomplete parameterized requests.
PARAMETERIZED = {
    "SwitchGait",
    "Trigger",
    "BodyHeight",
    "FootRaiseHeight",
    "SpeedLevel",
    "TrajectoryFollow",
    "ContinuousGait",
    "SwitchJoystick",
    "Pose",
    "EconomicGait",
}
DYNAMIC = {
    "Wallow",
    "Dance1",
    "Dance2",
    "FrontFlip",
    "FrontJump",
    "FrontPounce",
    "FingerHeart",
    "Handstand",
    "CrossStep",
    "OnesidedStep",
    "Bound",
    "MoonWalk",
    "LeftFlip",
    "RightFlip",
    "Backflip",
}


@lru_cache(maxsize=1)
def catalog():
    from dimos.robot.unitree.unitree_skill_container import UNITREE_WEBRTC_CONTROLS

    return [
        dict(
            name=name,
            api_id=ident,
            description=description,
            category="Settings"
            if name in PARAMETERIZED
            else "Status"
            if name.startswith("Get")
            else "Dynamic"
            if name in DYNAMIC
            else "Posture & gestures",
            available=name not in PARAMETERIZED,
            reason="Requires arguments not exposed by DimOS's name-only sport skill."
            if name in PARAMETERIZED
            else None,
        )
        for name, ident, description in UNITREE_WEBRTC_CONTROLS
    ]


def execute(connection, name, *, control, epoch, confirmed, replay=False):
    from dimos.robot.unitree.unitree_skill_container import UnitreeSkillContainer

    entry = next((a for a in catalog() if a["name"] == name), None)
    if not entry:
        raise ValueError("Unknown Unitree action")
    if not entry["available"]:
        raise ValueError(entry["reason"])
    if confirmed != name:
        raise ValueError("Confirm the selected action before running it")
    if replay:
        raise ValueError("Unitree actions are unavailable during replay")
    if control.get("mode") != "idle" or control.get("estop") or control.get("epoch") != epoch:
        raise ValueError("Pause movement and release Emergency stop before running an action")
    responses, failures = [], []

    class CheckedConnection:
        def publish_request(self, topic, body):
            try:
                response = connection.publish_request(topic, body)
                code = response.get("data", {}).get("header", {}).get("status", {}).get("code")
                if code is None:
                    raise ValueError(
                        "No robot acknowledgement. Outcome unknown; do not automatically retry."
                    )
                if code != 0:
                    raise ValueError(
                        f"Go2 rejected {name} (code {code}). The firmware may not support it."
                    )
                responses.append(code)
                return response
            except Exception as error:
                failures.append(
                    str(error)
                    if isinstance(error, ValueError)
                    else "Action transport failed. Outcome unknown; do not automatically retry."
                )
                raise ValueError(failures[-1]) from None

    # Reuse the real DimOS skill, supplying only its connection dependency.
    # Its success text alone is insufficient: require the robot's status code.
    UnitreeSkillContainer.execute_sport_command(
        SimpleNamespace(_connection=CheckedConnection()), name
    )
    if failures or not responses:
        raise ValueError(failures[0] if failures else "DimOS did not dispatch the action")
    return {
        "ok": True,
        "action": name,
        "message": f"{name} acknowledged by Go2. Completion is not confirmed.",
    }
