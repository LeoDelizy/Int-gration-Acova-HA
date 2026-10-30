"""Tests de la couche BLE (device.py) avec un faux client GATT."""
import asyncio
import os
import sys
from contextlib import asynccontextmanager

import pytest
from bleak.exc import BleakError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

from acova_ble import const, device, protocol  # noqa: E402

VALUES = {(116, 3): 4, (116, 5): 40, (116, 4): 34}


class FakeBLEDevice:
    """Seule l'adresse intéresse la couche device."""

    def __init__(self, address: str = "D2:C9:8E:95:2D:22") -> None:
        self.address = address
        self.name = "TEMPO 3"


class FakeClient:
    """Simule le radiateur : répond aux lectures par notification et/ou lecture."""

    def __init__(self, *, notify=True, notify_fails=False, read_script=None, pair_fails=False):
        self.services = []
        self.is_connected = True
        self.paired = False
        self.disconnect_count = 0
        self._pair_fails = pair_fails
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

    async def pair(self):
        if self._pair_fails:
            raise BleakError("org.bluez.Error.AuthenticationCanceled")
        self.paired = True
        return True

    async def disconnect(self):
        self.disconnect_count += 1
        self.is_connected = False

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


class FlakyClient(FakeClient):
    """Perd le lien au milieu de la première opération."""

    def __init__(self):
        super().__init__(notify_fails=True)
        self.dropped = False

    async def write_gatt_char(self, uuid, data, response=False):
        if not self.dropped:
            self.dropped = True
            raise BleakError("Not connected")
        await super().write_gatt_char(uuid, data, response=response)


@pytest.fixture(autouse=True)
def fast_timings(monkeypatch):
    monkeypatch.setattr(const, "POST_CONNECT_DELAY", 0)
    monkeypatch.setattr(const, "ACK_RETRY_DELAY", 0)
    monkeypatch.setattr(const, "NOTIFY_WAIT", 0.05)


@pytest.fixture(autouse=True)
def agent_calls(monkeypatch):
    """Remplace l'agent BlueZ (bus système indisponible en test) et trace ses usages."""
    calls: list[str] = []

    @asynccontextmanager
    async def fake_agent(address):
        calls.append(address)
        yield

    monkeypatch.setattr(device, "pairing_agent", fake_agent)
    return calls


def make_device(monkeypatch, clients, provider=None):
    """Device branché sur un (ou plusieurs successifs) faux client(s)."""
    if not isinstance(clients, list):
        clients = [clients]
    connects: list[FakeClient] = []

    async def fake_connect(*_args, **_kwargs):
        client = clients.pop(0) if clients else FakeClient()
        connects.append(client)
        return client

    monkeypatch.setattr(device, "establish_connection", fake_connect)
    dev = device.AcovaDevice(FakeBLEDevice(), "test", ble_device_provider=provider)
    return dev, connects


# --- Lecture d'état ---------------------------------------------------------


def test_read_state_via_notification(monkeypatch):
    dev, _ = make_device(monkeypatch, FakeClient())
    state = asyncio.run(dev.async_read_state())
    assert (state.mode, state.comfort_temp) == (4, 20.0)


def test_read_state_falls_back_to_direct_read(monkeypatch):
    dev, _ = make_device(monkeypatch, FakeClient(notify=False))
    state = asyncio.run(dev.async_read_state())
    assert (state.mode, state.comfort_temp) == (4, 20.0)


def test_read_state_when_start_notify_fails(monkeypatch):
    dev, _ = make_device(monkeypatch, FakeClient(notify_fails=True))
    state = asyncio.run(dev.async_read_state())
    assert state.mode == 4


def test_connection_is_reused_between_operations(monkeypatch):
    client = FakeClient()
    dev, connects = make_device(monkeypatch, client)

    async def two_reads():
        await dev.async_read_state()
        await dev.async_read_state()

    asyncio.run(two_reads())
    assert len(connects) == 1            # le lien est maintenu entre opérations
    assert client.disconnect_count == 0


def test_reconnects_after_link_loss(monkeypatch):
    client1, client2 = FakeClient(), FakeClient()
    dev, connects = make_device(monkeypatch, [client1, client2])

    async def scenario():
        await dev.async_read_state()
        client1.is_connected = False    # lien tombé sans prévenir
        return await dev.async_read_state()

    state = asyncio.run(scenario())
    assert len(connects) == 2            # reconnexion transparente
    assert (state.mode, state.comfort_temp) == (4, 20.0)


def test_recovers_from_mid_operation_bleak_error(monkeypatch):
    flaky, ok = FlakyClient(), FakeClient()
    dev, connects = make_device(monkeypatch, [flaky, ok])
    state = asyncio.run(dev.async_read_state())
    assert (state.mode, state.comfort_temp) == (4, 20.0)
    assert len(connects) == 2            # l'opération a été rejouée après reconnexion
    assert flaky.disconnect_count == 1


def test_bleak_errors_are_wrapped(monkeypatch):
    async def failing_connect(*_args, **_kwargs):
        raise BleakError("Not Connected")

    monkeypatch.setattr(device, "establish_connection", failing_connect)
    dev = device.AcovaDevice(FakeBLEDevice(), "test")
    with pytest.raises(device.AcovaConnectionError):
        asyncio.run(dev.async_read_state())


# --- Écritures ---------------------------------------------------------------


def test_write_retries_acks_and_commits(monkeypatch):
    client = FakeClient(
        read_script=[
            [116, 3, 1, 4],    # écho périmé -> relecture
            [116, 5, 1, 42],   # écho payload OK
            [116, 5, 1, 42],   # ack commit pas encore prêt -> relecture
            [0, 0, 0],         # ack commit OK
        ]
    )
    dev, _ = make_device(monkeypatch, client)
    asyncio.run(dev.async_set_heating(True, device.AcovaState(mode=4, comfort_temp=15.0)))
    data_writes = [w for w in client.writes if w[0] == const.UUID_CHAR_DATA]
    cmd_writes = [w for w in client.writes if w[0] == const.UUID_CHAR_CMD]
    assert data_writes[0][1][:4] == bytes([116, 5, 1, 42])
    assert len(data_writes[0][1]) == const.PAYLOAD_SIZE
    assert cmd_writes == [(const.UUID_CHAR_CMD, bytes([1, 116, 5]))]


def test_write_fails_when_ack_never_matches(monkeypatch):
    client = FakeClient(read_script=[[1, 1, 0]] * (const.ACK_RETRIES + 1))
    dev, connects = make_device(monkeypatch, client)
    with pytest.raises(device.AcovaProtocolError):
        asyncio.run(dev.async_set_heating(True, None))
    assert len(connects) == 1    # erreur de protocole : pas de reconnexion/rejeu


def test_empty_answers_hint_at_missing_pairing(monkeypatch):
    client = FakeClient(notify_fails=True, read_script=[bytes(72)] * const.ACK_RETRIES)
    dev, connects = make_device(monkeypatch, client)
    with pytest.raises(device.AcovaProtocolError, match="2H"):
        asyncio.run(dev.async_read_state())
    assert len(connects) == 1    # pas de réessai : le problème n'est pas la liaison


# --- Appairage -----------------------------------------------------------------


def test_pair_then_verifies_with_a_read(monkeypatch, agent_calls):
    client = FakeClient()
    dev, _ = make_device(monkeypatch, client)
    state = asyncio.run(dev.async_pair())
    assert client.paired is True
    assert len(agent_calls) == 1
    assert state.mode == 4


def test_regular_read_does_not_pair(monkeypatch, agent_calls):
    dev, _ = make_device(monkeypatch, FakeClient())
    asyncio.run(dev.async_read_state())
    assert agent_calls == []


def _broken_agent():
    @asynccontextmanager
    async def broken_agent(address):
        raise device.PairingAgentError("RegisterAgent refused")
        yield

    return broken_agent


def test_pairing_proceeds_without_agent(monkeypatch):
    """Sans agent BlueZ (proxy ESPHome, pas de D-Bus), pair() est tout de même tenté."""
    monkeypatch.setattr(device, "pairing_agent", _broken_agent())
    client = FakeClient()
    dev, _ = make_device(monkeypatch, client)
    state = asyncio.run(dev.async_pair())
    assert client.paired is True
    assert state.mode == 4


def test_pairing_without_agent_still_reports_pair_failure(monkeypatch):
    monkeypatch.setattr(device, "pairing_agent", _broken_agent())
    dev, _ = make_device(
        monkeypatch, [FakeClient(pair_fails=True), FakeClient(pair_fails=True)]
    )
    with pytest.raises(device.AcovaError):
        asyncio.run(dev.async_pair())


def test_pair_failure_is_wrapped(monkeypatch):
    dev, _ = make_device(
        monkeypatch, [FakeClient(pair_fails=True), FakeClient(pair_fails=True)]
    )
    with pytest.raises(device.AcovaError):
        asyncio.run(dev.async_pair())


# --- Chauffe on/off (switch) -------------------------------------------------


def _writes_by_dp(client):
    """Liste des (objectId, dataId, valeur) écrits via payload sur la caract. Données."""
    return [
        (data[0], data[1], data[3])
        for uuid, data in client.writes
        if uuid == const.UUID_CHAR_DATA
    ]


DAY_AT_OFF_TEMP = device.AcovaState(mode=const.MODE_DAY, comfort_temp=const.HEAT_OFF_TEMP)


def test_heating_on_writes_only_the_setpoint(monkeypatch):
    client = FakeClient(read_script=[[116, 5, 1, 42], [0, 0, 0]])
    dev, _ = make_device(monkeypatch, client)
    asyncio.run(dev.async_set_heating(True, DAY_AT_OFF_TEMP))
    assert _writes_by_dp(client) == [(116, 5, 42)]       # 21 °C, mode déjà Jour


def test_heating_off_writes_low_setpoint(monkeypatch):
    client = FakeClient(read_script=[[116, 5, 1, 30], [0, 0, 0]])
    dev, _ = make_device(monkeypatch, client)
    on = device.AcovaState(mode=const.MODE_DAY, comfort_temp=const.HEAT_ON_TEMP)
    asyncio.run(dev.async_set_heating(False, on))
    assert _writes_by_dp(client) == [(116, 5, 30)]       # 15 °C


def test_heating_forces_day_mode_after_setpoint(monkeypatch):
    client = FakeClient(
        read_script=[[116, 5, 1, 42], [0, 0, 0], [116, 3, 1, 4], [0, 0, 0]]
    )
    dev, _ = make_device(monkeypatch, client)
    auto = device.AcovaState(mode=const.MODE_AUTO, comfort_temp=19.0)
    asyncio.run(dev.async_set_heating(True, auto))
    assert _writes_by_dp(client) == [(116, 5, 42), (116, 3, const.MODE_DAY)]


def test_heating_noop_when_already_in_target_state(monkeypatch):
    client = FakeClient()
    dev, _ = make_device(monkeypatch, client)
    asyncio.run(dev.async_set_heating(False, DAY_AT_OFF_TEMP))
    assert _writes_by_dp(client) == []


def test_heating_never_sends_standby_or_frost(monkeypatch):
    for on in (True, False):
        client = FakeClient(
            read_script=[[116, 5, 1, 42], [0, 0, 0], [116, 3, 1, 4], [0, 0, 0]] * 2
        )
        dev, _ = make_device(monkeypatch, client)
        asyncio.run(dev.async_set_heating(on, None))
        modes = [v for obj, dat, v in _writes_by_dp(client) if (obj, dat) == (116, 3)]
        assert modes == [const.MODE_DAY]


# --- Déconnexion propre ---------------------------------------------------------


def test_stop_disconnects_cleanly(monkeypatch):
    client = FakeClient()
    dev, _ = make_device(monkeypatch, client)

    async def scenario():
        await dev.async_read_state()
        await dev.async_stop()

    asyncio.run(scenario())
    assert client.disconnect_count == 1
    assert client.is_connected is False


# --- Robustesse ------------------------------------------------------------------


def test_late_disconnect_callback_of_old_client_keeps_current_link(monkeypatch):
    old, new = FakeClient(), FakeClient()
    dev, connects = make_device(monkeypatch, [old, new])

    async def scenario():
        await dev.async_read_state()
        old.is_connected = False
        await dev.async_read_state()       # reconnexion sur `new`
        dev._on_disconnect(old)            # rappel tardif de l'ancien client
        await dev.async_read_state()

    asyncio.run(scenario())
    assert connects == [old, new]          # pas de reconnexion superflue


def test_stale_notification_is_not_taken_as_answer(monkeypatch):
    client = FakeClient()
    dev, _ = make_device(monkeypatch, client)

    async def scenario():
        await dev.async_read_state()
        # Réponse tardive d'une lecture précédente, restée dans la file.
        dev._notifications.put_nowait(bytes([116, 3, 1, const.MODE_FROST]))
        return await dev.async_read_state()

    state = asyncio.run(scenario())
    assert state.mode == VALUES[(116, 3)]


def test_devices_for_same_address_never_connect_concurrently(monkeypatch):
    """Entrée HA + config flow (ou deux flows) : pas de connexions simultanées."""
    active = 0
    max_active = 0

    class SlowClient(FakeClient):
        async def write_gatt_char(self, uuid, data, response=False):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.01)
            active -= 1
            await super().write_gatt_char(uuid, data, response=response)

    async def fake_connect(*_args, **_kwargs):
        return SlowClient()

    monkeypatch.setattr(device, "establish_connection", fake_connect)
    flow_dev = device.AcovaDevice(FakeBLEDevice(), "flow")
    entry_dev = device.AcovaDevice(
        None,
        "entry",
        ble_device_provider=FakeBLEDevice,
        address=FakeBLEDevice().address.lower(),
    )

    async def scenario():
        await asyncio.gather(flow_dev.async_read_state(), entry_dev.async_read_state())

    asyncio.run(scenario())
    assert max_active == 1
