import math
import pytest

from go2_setup.control import Authority, bounded_velocity
from go2_setup.agent import local_goal


def test_mode_change_and_timeout_revoke_old_commands():
    now = [10.0]
    authority = Authority(lambda: now[0])
    old = authority.transition("explore")
    manual = authority.transition("teleop")
    assert not authority.valid(old, {"explore"})
    assert authority.valid(manual, {"teleop"})
    now[0] += 0.61
    assert not authority.renew(manual)
    fresh = authority.transition("explore")
    assert fresh != old
    assert not authority.valid(old, {"explore"})


def test_stop_is_latched_until_explicit_release():
    authority = Authority()
    old = authority.transition("agent")
    authority.halt(True)
    with pytest.raises(ValueError):
        authority.transition("teleop")
    authority.clear()
    new = authority.transition("teleop")
    assert authority.valid(new, {"teleop"})
    assert not authority.valid(old, {"agent"})


def test_mac_sleep_cannot_preserve_a_motion_lease():
    monotonic = [10.0]
    wall = [1000.0]
    authority = Authority(lambda: monotonic[0], lambda: wall[0])
    epoch = authority.transition("explore")
    wall[0] += 60
    assert not authority.valid(epoch, {"explore"})
    assert not authority.renew(epoch)


def test_velocity_limits_and_nonfinite_rejection():
    assert bounded_velocity(5, -8, 5) == (5, -0.2, 0.5)
    for value in [math.nan, math.inf, -math.inf]:
        with pytest.raises(ValueError):
            bounded_velocity(value, 0, 0)


def test_local_natural_language_stays_in_observed_corridor():
    grid = dict(width=100, height=100, resolution=0.1, origin=[-5, -5], cells=[0] * 10000)
    pose = dict(x=0, y=0, yaw=0)
    assert local_goal("avanzá 2 metros", pose, grid) == (2, 0)
    x, y = local_goal("andá a la izquierda", pose, grid)
    assert y == pytest.approx(1)
    assert x == pytest.approx(0)
    with pytest.raises(ValueError):
        local_goal("no avances 2 metros", pose, grid)
    with pytest.raises(ValueError):
        local_goal("andá 20 metros", pose, grid)
    grid["cells"] = [-1] * 10000
    with pytest.raises(ValueError):
        local_goal("andá hasta el fondo", pose, grid)


def test_english_prompts_preserve_bounds_and_reject_compound_instructions():
    grid = dict(width=200, height=200, resolution=0.1, origin=[-10, -10], cells=[0] * 40000)
    pose = dict(x=0, y=0, yaw=0)
    x, y = local_goal("walk one meter backward", pose, grid)
    assert x == pytest.approx(-1) and y == pytest.approx(0)
    assert local_goal("go to the far end", pose, grid) == (5, 0)
    assert local_goal("walk 2 meters", pose, grid) == (2, 0)
    for prompt in [
        "do not walk forward",
        "walk 2 meters then turn left",
        "walk 20 meters",
        "move left right",
    ]:
        with pytest.raises(ValueError):
            local_goal(prompt, pose, grid)
