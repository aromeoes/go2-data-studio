"""Validated Vector actions shared by MCP and the runtime boundary."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class Empty(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Move(Empty):
    direction: Literal["forward", "backward"]
    distance_m: float = Field(ge=0.03, le=0.5, allow_inf_nan=False)


class Head(Empty):
    angle_deg: float = Field(ge=-22, le=45, allow_inf_nan=False)


class Lift(Empty):
    height: float = Field(ge=0, le=1, allow_inf_nan=False)


class Speak(Empty):
    text: str = Field(min_length=1, max_length=300)


class Person(Empty):
    name: str = Field(min_length=1, max_length=80)


class Animate(Empty):
    expression: Literal["greet", "happy", "curious"]


TOOLS = [
    (
        "move_relative",
        Move,
        "Drive 0.03–0.5 m forward or backward using Vector odometry. Not path planning. One move per message; never chain moves. Acceptance is not arrival.",
        "Move 30 centimeters forward.",
    ),
    ("set_head", Head, "Set Vector head angle in degrees, from -22 to 45.", "Look up."),
    (
        "set_lift",
        Lift,
        "Set Vector lift height from 0 (lowered) to 1 (raised).",
        "Raise your lift.",
    ),
    ("speak", Speak, "Say the requested text using Vector's own synthesized voice.", "Say hello."),
    (
        "play_expression",
        Animate,
        "Play a native expressive animation with tread motion suppressed. Availability depends on firmware.",
        "Act curious.",
    ),
    (
        "find_person",
        Person,
        "Look for an already enrolled person by their exact name, using Vector's onboard face recognition during a head-only scan. No roaming or photo identification. Ask for the person's enrolled name if unknown.",
        "Look for Tule.",
    ),
    (
        "visible_faces",
        Empty,
        "Read faces and enrolled names currently recognized by Vector onboard. Do not infer a name from camera pixels.",
        "Who do you recognize?",
    ),
]
SCHEMAS = {name: schema for name, schema, _, _ in TOOLS}


def validate(name, args):
    if name not in SCHEMAS:
        raise ValueError("Unsupported Vector action")
    return SCHEMAS[name].model_validate(args).model_dump()
