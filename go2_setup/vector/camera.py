"""Scoped camera RPC cleanup for the pinned wirepod-vector-sdk 0.8.1.

The SDK cancels its asyncio task but can leave aiogrpc's blocking stream reader
alive while waiting for the robot's global streaming flag. Scope the RPC itself
and close only this client's subscription. Decoding and events remain SDK-owned.
"""

import asyncio
import logging
import time
from concurrent.futures import TimeoutError


def prepare_camera(camera, request, run_coroutine, *, enable_request=None, frame_timeout=5.0, first_frame_timeout=15.0, retry_delay=0.5):
    """Install an instance-local compatibility shim before init_camera_feed()."""
    status = camera._studio_feed_status = {"state": "starting", "attempts": 0, "frames": 0, "received": 0, "error": None}
    async def receive():
        # Escape-pod firmware requires EnableImageStreaming before CameraFeed.
        # This is an image-only RPC; no behavior or motor control is requested.
        while camera._enabled:
            try:
                status.update(state="enabling", attempts=status["attempts"] + 1)
                if enable_request is not None:
                    await asyncio.wait_for(camera.grpc_interface.EnableImageStreaming(enable_request(enable=True)), timeout=3)
                status["state"] = "waiting"
                async with camera.grpc_interface.CameraFeed.with_scope(request()) as stream:
                    iterator = stream.__aiter__()
                    pending = None
                    timeout = first_frame_timeout
                    try:
                        while camera._enabled:
                            pending = asyncio.create_task(anext(iterator))
                            message = await asyncio.wait_for(asyncio.shield(pending), timeout=timeout)
                            pending = None
                            timeout = frame_timeout
                            if camera._enabled:
                                camera._unpack_image(message)
                                status.update(state="streaming", frames=status["frames"] + 1, received=time.time(), error=None)
                    finally:
                        if pending is not None:
                            # Let gRPC finish the pending read before aiogrpc's
                            # scope destructor cancels its executor future.
                            cancel_rpc = getattr(stream, "cancel", None)
                            if callable(cancel_rpc):
                                cancel_rpc()
                            else:
                                pending.cancel()
                            try:
                                await asyncio.wait_for(asyncio.shield(pending), timeout=0.5)
                            except (Exception, asyncio.CancelledError):
                                pending.cancel()
                                await asyncio.gather(pending, return_exceptions=True)
            except asyncio.CancelledError:
                status["state"] = "stopped"
                raise
            except (TimeoutError, StopAsyncIteration):
                status.update(state="retrying", error="No camera frame received before timeout")
                logging.getLogger(__name__).info("Reopening idle Vector camera stream")
            except Exception as error:
                status.update(state="retrying", error=type(error).__name__)
                logging.getLogger(__name__).warning("Vector camera stream ended (%s)", type(error).__name__)
            if camera._enabled:
                await asyncio.sleep(retry_delay)

    async def cancel():
        camera._enabled = False
        task = camera._camera_feed_task
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            finally:
                camera._camera_feed_task = None

    def close():
        future = run_coroutine(cancel())
        try:
            future.result(timeout=3)
        except TimeoutError:
            future.cancel()
            # Robot.disconnect subsequently closes the whole authenticated channel.

    camera._request_and_handle_images = receive
    camera.close_camera_feed = close
