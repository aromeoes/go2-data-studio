import pytest


@pytest.fixture(autouse=True)
def no_external_relay_in_unit_tests(monkeypatch):
    from go2_setup.sdk_relay import ConsoleRelay

    monkeypatch.setattr(ConsoleRelay, "start", lambda self: None)
