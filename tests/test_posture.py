from threading import RLock, Thread
from unittest.mock import Mock

import pytest

from go2_setup.posture import perform_posture


def setup():
    connection = Mock()
    connection.publish_request.return_value = {"data": {"header": {"status": {"code": 0}}}}
    state = {"mode": "idle", "epoch": 1, "estop": False}
    return connection, state, RLock()


def ids(connection):
    return [call.args[1]["api_id"] for call in connection.publish_request.call_args_list]


def test_stand_settles_then_balances_and_stays_idle():
    connection, state, lock = setup()
    slept = []

    def sleep(seconds):
        slept.append(seconds)
        assert ids(connection) == [1004]
        acquired = []

        def stop_can_access_lock():
            with lock:
                acquired.append(True)

        thread = Thread(target=stop_can_access_lock)
        thread.start()
        thread.join(1)
        assert acquired, "Stop cannot be blocked while posture settles"

    result = perform_posture(connection, "stand", lambda: 1, lambda: state, lock, sleep=sleep)
    assert ids(connection) == [1004, 1002]
    assert slept == [3]
    assert result == {"ok": True, "mode": "idle", "epoch": 1}


def test_stop_during_stand_cancels_balance():
    connection, state, lock = setup()

    def stop(seconds):
        state.update(epoch=2, estop=True)

    with pytest.raises(ValueError, match="interrupted"):
        perform_posture(connection, "stand", lambda: 1, lambda: state, lock, sleep=stop)
    assert ids(connection) == [1004]


def test_posture_rejection_does_not_continue_to_balance():
    connection, state, lock = setup()
    connection.publish_request.return_value = {"data": {"header": {"status": {"code": 3103}}}}
    sleep = Mock()
    with pytest.raises(ValueError, match="3103"):
        perform_posture(connection, "stand", lambda: 1, lambda: state, lock, sleep=sleep)
    assert ids(connection) == [1004]
    sleep.assert_not_called()


def test_lie_does_not_reenable_balance():
    connection, state, lock = setup()
    perform_posture(connection, "lie", lambda: 1, lambda: state, lock)
    assert ids(connection) == [1005]


def test_replay_does_not_publish_physical_posture_commands():
    connection, state, lock = setup()
    perform_posture(connection, "stand", lambda: 1, lambda: state, lock, replay=True)
    connection.publish_request.assert_not_called()


def test_estop_prevents_stand_and_invalid_action_does_not_halt():
    connection, state, lock = setup()
    state["estop"] = True
    with pytest.raises(ValueError, match="stop"):
        perform_posture(connection, "stand", lambda: 1, lambda: state, lock)
    connection.publish_request.assert_not_called()
    halt = Mock()
    with pytest.raises(ValueError, match="Invalid"):
        perform_posture(connection, "invalid", halt, lambda: state, lock)
    halt.assert_not_called()
