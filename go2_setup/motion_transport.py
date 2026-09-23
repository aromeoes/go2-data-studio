"""Compatibility adapter for the pinned DimOS WebRTC Move implementation.

The MCF driver sends Move through a `msg` envelope with policy.noreply. Keep
DimOS's timed move/automatic zero watchdog, replacing only its wire publisher.
Source: legion1581/unitree_webrtc_connect, commit 9bad111, sportmode_mcf.py.
"""

import json
from types import MethodType

from dimos.robot.unitree.connection import UnitreeWebRTCConnection
from unitree_webrtc_connect.constants import RTC_TOPIC


def publish_velocity(connection, x: float, y: float, yaw: float) -> None:
    publisher = connection.conn.datachannel.pub_sub
    # The driver's publisher silently drops messages when the channel is closed.
    # Raise here so the caller records a failure instead of reporting them sent.
    if publisher.channel.readyState != "open":
        raise ConnectionError("The Go2 control channel is closed")
    publisher.publish_without_callback(
        RTC_TOPIC["SPORT_MOD"],
        data={
            "header": {
                "identity": {"id": connection._move_ids.next() + 1, "api_id": 1008},
                "policy": {"priority": 0, "noreply": True},
            },
            "parameter": json.dumps({"x": x, "y": y, "z": yaw}),
            "binary": [],
        },
        msg_type="msg",
    )


def install_velocity_transport(connection) -> bool:
    # ReplayConnection inherits from this class too. Only adapt real WebRTC;
    # never turn a replay into a hardware sender or change a joystick session.
    if type(connection) is not UnitreeWebRTCConnection or not connection._velocity_api:
        return False
    connection._publish_movement = MethodType(publish_velocity, connection)
    return True
