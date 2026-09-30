"""Fixtures for SnapAV WattBox tests."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from .fake_wattbox import FakeWattbox

pytest_plugins = ("pytest_homeassistant_custom_component",)

HOST = "127.0.0.1"
DATA = {"host": HOST, "username": "wattbox", "password": "pass"}
TAG = "ST000000000001"


@pytest.fixture(autouse=True)
def enable_wattbox_integration(enable_custom_integrations):
    """Allow Home Assistant to load the custom integration under test."""


@pytest.fixture(autouse=True)
def fast_timing():
    """Shrink the client's timeouts."""
    module = "custom_components.snapav_wattbox.const"
    with (
        patch(f"{module}.WATTBOX_CONNECT_TIMEOUT", 0.5),
        patch(f"{module}.WATTBOX_LOGIN_TIMEOUT", 0.5),
        patch(f"{module}.WATTBOX_RESPONSE_TIMEOUT", 0.3),
    ):
        yield


@pytest.fixture
async def wattbox(socket_enabled):
    """A fake WattBox; the integration connects to it on 127.0.0.1."""
    server = FakeWattbox()
    await server.start()
    with patch("custom_components.snapav_wattbox.device.WATTBOX_PORT", server.port):
        yield server
    await server.stop()
