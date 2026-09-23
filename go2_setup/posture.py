"""Explicit operator posture actions. Never run as part of connection startup."""

import time


def perform_posture(connection, action, halt, control_state, lock, replay=False, sleep=time.sleep):
    if action not in {"stand", "lie"}:
        raise ValueError("Invalid posture")

    def command(api_id):
        if replay:
            return
        response = connection.publish_request("rt/api/sport/request", {"api_id": api_id})
        code = response.get("data", {}).get("header", {}).get("status", {}).get("code")
        if code != 0:
            raise ValueError(f"Go2 did not confirm posture (API {api_id}, code {code})")

    with lock:
        epoch = halt()
        if action == "stand" and control_state().get("estop"):
            raise ValueError("Release stop before standing Go2 up")
        command(1004 if action == "stand" else 1005)
    if action == "stand":
        # Match the framework's explicit StandUp -> settle -> BalanceStand sequence.
        # StandUp alone can leave the joints locked and Move commands ineffective.
        # Do not hold the HTTP control lock while settling: Parar must remain usable.
        if not replay:
            sleep(3)
        with lock:
            state = control_state()
            if state["epoch"] != epoch or state.get("estop") or state["mode"] != "idle":
                raise ValueError("Stand up was interrupted; walking was not enabled")
            command(1002)
    return {"ok": True, "mode": "idle", "epoch": epoch}
