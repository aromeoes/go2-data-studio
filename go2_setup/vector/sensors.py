"""Normalize SDK measurements. Unsupported readings stay explicitly null."""

import math
import time


def xyz(value, scale=1):
    return [getattr(value, axis) * scale for axis in ("x", "y", "z")] if value else None


def readings(robot, received, battery=None, battery_received=None):
    status = robot.status
    proximity = robot.proximity.last_sensor_reading
    touch = robot.touch.last_sensor_reading
    pose = robot.pose
    return {
        "received": received,
        "cliff": {"any_detected": status.is_cliff_detected, "individual": None},
        "proximity": None
        if proximity is None
        else {
            "distance_mm": proximity.distance.distance_mm,
            "signal_quality": proximity.signal_quality,
            "found_object": proximity.found_object,
            "unobstructed": proximity.unobstructed,
            "lift_in_fov": proximity.is_lift_in_fov,
        },
        # Preserve SDK units until confirmed against the paired firmware.
        "imu": {"accel": xyz(robot.accel), "gyro": xyz(robot.gyro), "units": "SDK raw"},
        "touch": None
        if touch is None
        else {"detected": touch.is_being_touched, "raw": touch.raw_touch_value},
        "power": None
        if battery is None
        else {
            "volts": battery.battery_volts,
            "level": {0: "unknown", 1: "low", 2: "nominal", 3: "full"}.get(
                battery.battery_level, "unknown"
            ),
            "charging": battery.is_charging,
            "on_charger": battery.is_on_charger_platform,
            "received": battery_received,
            "percent": None,
        },
        "temperature": {"head_c": None, "body_c": None, "reason": "Not exposed by the Vector SDK"},
        "head_deg": math.degrees(robot.head_angle_rad)
        if robot.head_angle_rad is not None
        else None,
        "lift_mm": robot.lift_height_mm,
        "wheel_mmps": [robot.left_wheel_speed_mmps, robot.right_wheel_speed_mmps],
        "picked_up": status.is_picked_up,
        "falling": status.is_falling,
        "pose": None
        if pose is None
        else {
            "x": pose.position.x / 1000,
            "y": pose.position.y / 1000,
            "yaw": robot.pose_angle_rad,
            "origin_id": pose.origin_id,
        },
        "faces": [
            {"id": f.face_id, "name": f.name or None, "last_seen": f.last_observed_time}
            for f in robot.world.visible_faces
            if time.time() - f.last_observed_time < 2
        ],
    }
