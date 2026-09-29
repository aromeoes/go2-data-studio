"""The only module that imports the optional wirepod-vector-sdk dependency."""

import threading
import time
from unittest.mock import patch

from go2_setup.vector.camera import prepare_camera
from go2_setup.vector.credentials import load_credentials, renew_credentials
from go2_setup.vector.errors import CONNECTION_ERRORS, DEFAULT_ERROR, report_startup_error
from go2_setup.vector.sensors import readings
from go2_setup.vector.control import resolve

EXPRESSIONS = {
    "greet": "GreetAfterLongTime",
    "happy": "ReactToGoodWord",
    "curious": "LookInPlaceForFaces",
}


class VectorDriver:
    def __init__(self, ip, serial, sdk_config, profile):
        self.ip, self.serial, self.sdk_config, self.profile = ip, serial, sdk_config, profile
        self.robot = None
        self.received = 0.0
        self.latest_image = None
        self.battery = None
        self.battery_received = None
        self.done = threading.Event()
        self.triggers = set()
        self.motion_error = None
        self.wheel_future = None
        self.wheel_sent_at = 0.0
        self.transport = {"commands": 0, "ack_ms": None, "acquire_ms": None}
        self.faces_ready = False

    def connect(self, *, _renewed=False):
        try:
            import anki_vector
            from anki_vector.events import Events
        except ImportError:
            raise ValueError(
                "Vector SDK is not installed. Install the application's vector dependency extra and rebuild the bundled runtime."
            ) from None
        config = load_credentials(self.sdk_config, self.serial)
        # SDK 0.8.1 reads the default config even when a complete config is passed.
        # Scope this compatibility shim to construction inside the Vector worker.
        with patch.object(anki_vector.util, "read_configuration", return_value=config):
            self.robot = anki_vector.AsyncRobot(
                serial=self.serial,
                ip=self.ip,
                config=config,
                default_logging=False,
                behavior_control_level=None,
                enable_face_detection="faces" in self.profile["enabled"],
            )
        try:
            self.robot.connect(timeout=10)
        except Exception as error:
            # Do not include raw gRPC details or credentials in logs. Failed SDK
            # startup has no viewer/camera components, so disconnect() is unsafe.
            robot, self.robot = self.robot, None
            try:
                self._close_failed_connection(robot)
            except Exception:
                pass  # Preserve the original error even if the SDK cleanup fails.
            if type(error).__name__ == "VectorUnauthenticatedException" and not _renewed:
                try:
                    renew_credentials(self.sdk_config, self.serial, self.ip)
                except Exception:
                    pass  # Only the fixed original error can reach logs/UI.
                else:
                    return self.connect(_renewed=True)
            report_startup_error(type(error).__name__)
            raise ValueError(CONNECTION_ERRORS.get(type(error).__name__, DEFAULT_ERROR)) from None
        self.robot.events.subscribe(self._state, Events.robot_state)
        if "camera" in self.profile["enabled"]:
            from anki_vector.messaging import protocol

            prepare_camera(self.robot.camera, protocol.CameraFeedRequest, self.robot.conn.run_coroutine,
                           enable_request=protocol.EnableImageStreamingRequest)
            self.robot.events.subscribe(self._image, Events.new_camera_image)
            # SDK init_camera_feed creates an asyncio task, so run it on its
            # connection loop rather than the DimOS RPC worker thread.
            resolve(self.robot.conn.run_coroutine(self.robot.camera.init_camera_feed), timeout=3)
        threading.Thread(target=self._slow_state, daemon=True).start()

    def _image(self, _robot, _event, data):
        self.latest_image = data.image

    def _state(self, *_):
        self.received = time.time()

    def _slow_state(self):
        try:
            self.triggers = set(self.robot.anim.anim_trigger_list)
        except Exception:
            pass
        while not self.done.is_set():
            try:
                self.battery = resolve(self.robot.get_battery_state(), timeout=3)
                self.battery_received = time.time()
            except Exception:
                pass
            self.done.wait(5)

    def sensor_state(self):
        if not self.robot or not self.received:
            return None
        state = readings(self.robot, self.received, self.battery, self.battery_received)
        if "camera" in self.profile["enabled"]:
            state["camera_stream"] = dict(getattr(self.robot.camera, "_studio_feed_status", {}))
        state["control_transport"] = dict(self.transport)
        if "faces" not in self.profile["enabled"]:
            state["faces"] = []
        return state

    def acquire(self):
        from anki_vector.connection import ControlPriorityLevel

        started = time.monotonic()
        # A fresh UI lease still stops old motion, but need not renegotiate an
        # SDK lease already granted to this connection. Native reactions retain
        # their priority; lost control always takes the normal acquisition path.
        granted = self.robot.conn.control_granted_event.is_set()
        if not granted:
            resolve(
                self.robot.conn.request_control(ControlPriorityLevel.DEFAULT_PRIORITY, timeout=3), 4
            )
            self.faces_ready = False
        self.motion_error = None
        if "faces" in self.profile["enabled"] and not self.faces_ready:
            try:
                resolve(self.robot.vision.enable_face_detection(detect_faces=True), 2)
                self.faces_ready = True
            except Exception:
                self.release()
                raise ValueError("Could not enable Vector native face detection") from None

        self.transport["acquire_ms"] = round((time.monotonic() - started) * 1000, 1)

    def has_control(self):
        return self.robot.conn.control_granted_event.is_set() and self.motion_error is None

    def release(self):
        self.faces_ready = False
        resolve(self.robot.conn.release_control(timeout=3), 4)

    def wheels(self, left, right):
        if self.motion_error:
            raise ValueError(self.motion_error)
        if self.wheel_future is not None and not self.wheel_future.done():
            # Never queue more motion behind an outstanding command. A short
            # network delay is normal; release/stop bypasses this path entirely.
            if time.monotonic() - self.wheel_sent_at < 0.2:
                return
            self.motion_error = "Tread command acknowledgement delayed; control stopped"
            self.wheel_future.cancel()
            raise ValueError(self.motion_error)
        self.wheel_sent_at = time.monotonic()
        sent_at = self.wheel_sent_at
        self.transport["commands"] += 1
        future = self.robot.motors.set_wheel_motors(left, right, 200, 200)

        def finished(f):
            if f.cancelled():
                return  # Intentional cancellation by stop is not a new drive fault.
            try:
                self.validate_motor_response(f.result())
                self.transport["ack_ms"] = round((time.monotonic() - sent_at) * 1000, 1)
            except Exception:
                self.motion_error = "Vector rejected a tread command"

        self.wheel_future = future
        future.add_done_callback(finished)

    def stop_motors(self):
        pending, self.wheel_future = self.wheel_future, None
        if pending is not None and not pending.done():
            pending.cancel()
        stop = self.robot.motors.stop_all_motors()
        try:
            self.validate_motor_response(resolve(stop, timeout=1))
        except Exception:
            # Cancel a queued stop so it cannot unexpectedly execute in a later
            # session. The controller retains stop_pending and retries while idle.
            if hasattr(stop, "cancel"):
                stop.cancel()
            raise

    @staticmethod
    def validate_motor_response(response):
        status = getattr(response, "status", None)
        if status is not None and hasattr(status, "DESCRIPTOR"):
            descriptor = status.DESCRIPTOR.fields_by_name.get("code")
            if descriptor and descriptor.enum_type:
                enum = descriptor.enum_type.values_by_number.get(status.code)
                # Motor RPC acknowledgement is distinct from an action result.
                # RECEIVED/PROCESSING acknowledge acceptance; neither proves
                # physical completion. Actual tread telemetry remains separate.
                if enum and enum.name in {"RESPONSE_RECEIVED", "REQUEST_PROCESSING", "OK"}:
                    return
        VectorDriver.validate_result(response)

    def action(self, name, args):
        from anki_vector.util import degrees

        if name == "set_head":
            return self.robot.behavior.set_head_angle(degrees(args["angle_deg"]))
        if name == "set_lift":
            return self.robot.behavior.set_lift_height(args["height"])
        if name == "speak":
            return self.robot.behavior.say_text(args["text"], use_vector_voice=True)
        if name == "play_expression":
            trigger = EXPRESSIONS[args["expression"]]
            if trigger not in self.triggers:
                raise ValueError("This expressive animation is unavailable on Vector's firmware")
            return self.robot.anim.play_animation_trigger(trigger, ignore_body_track=True)
        raise ValueError("Unsupported Vector action")

    @staticmethod
    def validate_result(response):
        # Responses use both nested ActionResult.code and direct enum results.
        for key in ("status", "result", "state"):
            value = getattr(response, key, None)
            if value is None:
                continue
            descriptor = response.DESCRIPTOR.fields_by_name.get(key)
            if hasattr(value, "DESCRIPTOR"):
                descriptor = value.DESCRIPTOR.fields_by_name.get("code")
                value = getattr(value, "code", None)
            if descriptor and descriptor.enum_type and value is not None:
                enum = descriptor.enum_type.values_by_number.get(value)
                if enum and enum.name not in {
                    "OK",
                    "ACTION_RESULT_SUCCESS",
                    "BEHAVIOR_COMPLETE_STATE",
                    "FINISHED",
                }:
                    raise ValueError("Vector reported " + enum.name)

    def close(self):
        self.done.set()
        robot, self.robot = self.robot, None
        if robot:
            robot.disconnect()

    @staticmethod
    def _close_failed_connection(robot):
        """Release a partially initialized SDK connection without masking its error."""
        conn = robot.conn
        loop = getattr(conn, "_loop", None)
        if loop is not None and loop.is_closed():
            # SDK 0.8.1 closes its asyncio loop on authentication failure but
            # leaves the wrapped synchronous gRPC channel open.
            channel = getattr(getattr(conn, "_channel", None), "_channel", None)
            if channel is not None:
                channel.close()
            thread = getattr(conn, "_thread", None)
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=1)
            return
        try:
            if getattr(robot, "_viewer", None) is not None:
                robot.disconnect()
        finally:
            conn.close()
