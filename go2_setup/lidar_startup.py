"""Enable the LiDAR stream explicitly for each physical WebRTC session."""

import asyncio

from dimos.robot.unitree.connection import UnitreeWebRTCConnection
from unitree_webrtc_connect.constants import RTC_TOPIC


async def _enable(publisher):
    # Match Unitree SDK2 and the current WebRTC UI: uppercase string "ON".
    # Repeat at 100 ms intervals because firmware may drop the first packet.
    for attempt in range(5):
        if publisher.channel.readyState != "open":
            raise ConnectionError("Cannot enable LiDAR: Go2 data channel is closed")
        publisher.publish_without_callback(RTC_TOPIC["ULIDAR_SWITCH"], "ON")
        if attempt < 4:
            await asyncio.sleep(0.1)


def enable_lidar(connection) -> bool:
    # ReplayConnection inherits from the real connection. Never send from replay.
    if type(connection) is not UnitreeWebRTCConnection:
        return False
    future = asyncio.run_coroutine_threadsafe(
        _enable(connection.conn.datachannel.pub_sub), connection.loop
    )
    try:
        future.result(timeout=3)
    except Exception:
        future.cancel()
        raise
    return True


def subscribe_lidar_status(connection, callback):
    if type(connection) is not UnitreeWebRTCConnection:
        return None
    return connection.unitree_sub_stream(RTC_TOPIC["ULIDAR_STATE"]).subscribe(callback)
