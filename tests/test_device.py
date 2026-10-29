"""Tests de la couche BLE (device.py) avec un faux client GATT."""
import asyncio
import os
import sys

import pytest
from bleak.exc import BleakError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

from acova_ble import const, device  # noqa: E402

VALUES = {(116, 3): 4, (116, 5): 40, (116, 4): 34}


class FakeClient:
    """Simule le radiateur : répond aux demandes de lecture par notification et/ou lecture."""

    def __init__(self, *, notify=True, notify_fails=False, read_script=None):
        self.services = []
        self.writes: list[tuple[str, bytes]] = []
        self._cb = None
        self._notify = notify
        self._notify_fails = notify_fails
        self._last = None
        self._read_script = [bytes(r) for r in (read_script or [])]

    async def start_notify(self, uuid, cb):
        if self._notify_fails:
            raise BleakError("notify not permitted")
        self._cb = cb

    async def stop_notify(self, uuid):
        pass

    async def disconnect(self):
        pass

    async def write_gatt_char(self, uuid, data, response=False):
        data = bytes(data)
        self.writes.append((uuid, data))
        if uuid == const.UUID_CHAR_CMD and data[0] == const.OP_READ:
            self._last = (data[1], data[2])
            if self._notify and self._cb:
                self._cb(None, bytearray([data[1], data[2], 1, VALUES[self._last]]))

    async def read_gatt_char(self, uuid):
        if self._read_script:
            return bytearray(self._read_script.pop(0))
        obj, dat = self._last
        return bytearray([obj, dat, 1, VALUES[self._last]])


@pytest.fixture(autouse=True)
def fast_timings(monkeypatch):
    monkeypatch.setattr(const, "POST_CONNECT_DELAY", 0)
    monkeypatch.setattr(const, "ACK_RETRY_DELAY", 0)
    monkeypatch.setattr(const, "NOTIFY_WAIT", 0.05)


def make_device(monkeypatch, client):
    async def fake_connect(*_args, **_kwargs):
        return client

    monkeypatch.setattr(device, "establish_connection", fake_connect)
    return device.AcovaDevice(None, "test")


def test_read_state_via_notification(monkeypatch):
    dev = make_device(monkeypatch, FakeClient())
    state = asyncio.run(dev.async_read_state())
    assert (state.mode, state.comfort_temp, state.eco_temp) == (4, 20.0, 17.0)


def test_read_state_falls_back_to_direct_read(monkeypatch):
    dev = make_device(monkeypatch, FakeClient(notify=False))
    state = asyncio.run(dev.async_read_state())
    assert (state.mode, state.comfort_temp, state.eco_temp) == (4, 20.0, 17.0)


def test_read_state_when_start_notify_fails(monkeypatch):
    dev = make_device(monkeypatch, FakeClient(notify_fails=True))
    state = asyncio.run(dev.async_read_state())
    assert state.mode == 4


def test_write_retries_acks_and_commits(monkeypatch):
    client = FakeClient(
        read_script=[
            [116, 3, 1, 4],    # écho périmé -> relecture
            [116, 5, 1, 43],   # écho payload OK
            [116, 5, 1, 43],   # ack commit pas encore prêt -> relecture
            [0, 0, 0],         # ack commit OK
        ]
    )
    dev = make_device(monkeypatch, client)
    asyncio.run(dev.async_set_comfort_temp(21.5))
    data_writes = [w for w in client.writes if w[0] == const.UUID_CHAR_DATA]
    cmd_writes = [w for w in client.writes if w[0] == const.UUID_CHAR_CMD]
    assert data_writes[0][1][:4] == bytes([116, 5, 1, 43])
    assert len(data_writes[0][1]) == const.PAYLOAD_SIZE
    assert cmd_writes == [(const.UUID_CHAR_CMD, bytes([1, 116, 5]))]


def test_write_fails_when_ack_never_matches(monkeypatch):
    client = FakeClient(read_script=[[1, 1, 0]] * (const.ACK_RETRIES + 1))
    dev = make_device(monkeypatch, client)
    with pytest.raises(device.AcovaError):
        asyncio.run(dev.async_set_mode(const.MODE_DAY))


def test_bleak_errors_are_wrapped(monkeypatch):
    async def failing_connect(*_args, **_kwargs):
        raise BleakError("Not Connected")

    monkeypatch.setattr(device, "establish_connection", failing_connect)
    dev = device.AcovaDevice(None, "test")
    with pytest.raises(device.AcovaError):
        asyncio.run(dev.async_read_state())
