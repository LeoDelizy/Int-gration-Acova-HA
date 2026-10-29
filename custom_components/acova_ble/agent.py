"""Agent BlueZ temporaire pour l'appairage d'un radiateur ACOVA.

Le TEMPO 3 demande une confirmation d'appairage (« request type 2 »). Sur Android,
c'est la boîte « Accepter la demande d'association » ; sous BlueZ, sans agent
enregistré, la demande est refusée (`No agent available for request type 2`).

Cet agent est enregistré uniquement pendant l'appairage, accepte la confirmation pour
le seul radiateur visé et refuse toute autre demande. La validation physique reste
faite sur le radiateur (bouton 2H).

Note : pas de `from __future__ import annotations` ici, dbus_fast lit les signatures
D-Bus directement dans les annotations des méthodes.
"""
import logging
from contextlib import asynccontextmanager

from dbus_fast import BusType, Message, MessageType
from dbus_fast.aio import MessageBus
from dbus_fast.errors import DBusError
from dbus_fast.service import ServiceInterface, method

_LOGGER = logging.getLogger(__name__)

AGENT_PATH = "/org/homeassistant/acova_ble/agent"
AGENT_CAPABILITY = "DisplayYesNo"
_REJECTED = "org.bluez.Error.Rejected"


class PairingAgentError(Exception):
    """Impossible d'enregistrer l'agent d'appairage auprès de BlueZ."""


def device_path_suffix(address: str) -> str:
    """AA:BB:CC:DD:EE:FF -> dev_AA_BB_CC_DD_EE_FF (fin du chemin D-Bus BlueZ)."""
    return "dev_" + address.upper().replace(":", "_")


class PairingAgent(ServiceInterface):
    """org.bluez.Agent1 : accepte la confirmation pour un seul appareil."""

    def __init__(self, address: str) -> None:
        super().__init__("org.bluez.Agent1")
        self._suffix = device_path_suffix(address)

    def _check(self, device: str) -> None:
        if not device.upper().endswith(self._suffix.upper()):
            _LOGGER.debug("Demande d'appairage refusée pour %s", device)
            raise DBusError(_REJECTED, "appareil non attendu")

    @method()
    def Release(self):  # noqa: N802 - nom imposé par org.bluez.Agent1
        pass

    @method()
    def RequestConfirmation(self, device: "o", passkey: "u"):  # noqa: N802, F821
        self._check(device)
        _LOGGER.debug("Confirmation d'appairage acceptée pour %s", device)

    @method()
    def RequestAuthorization(self, device: "o"):  # noqa: N802, F821
        self._check(device)

    @method()
    def AuthorizeService(self, device: "o", uuid: "s"):  # noqa: N802, F821
        self._check(device)

    @method()
    def RequestPinCode(self, device: "o") -> "s":  # noqa: N802, F821
        raise DBusError(_REJECTED, "code PIN non supporté")

    @method()
    def RequestPasskey(self, device: "o") -> "u":  # noqa: N802, F821
        raise DBusError(_REJECTED, "passkey non supportée")

    @method()
    def DisplayPinCode(self, device: "o", pincode: "s"):  # noqa: N802, F821
        pass

    @method()
    def DisplayPasskey(self, device: "o", passkey: "u", entered: "q"):  # noqa: N802, F821
        pass

    @method()
    def Cancel(self):  # noqa: N802
        _LOGGER.debug("Appairage annulé par BlueZ")


async def _call_agent_manager(bus: MessageBus, member: str, signature: str, body: list) -> None:
    reply = await bus.call(
        Message(
            destination="org.bluez",
            path="/org/bluez",
            interface="org.bluez.AgentManager1",
            member=member,
            signature=signature,
            body=body,
        )
    )
    if reply.message_type == MessageType.ERROR:
        raise PairingAgentError(f"{member} : {reply.error_name} {reply.body}")


@asynccontextmanager
async def pairing_agent(address: str):
    """Enregistre l'agent (agent par défaut) le temps du bloc, puis le retire."""
    try:
        bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    except Exception as err:  # noqa: BLE001 - bus système indisponible
        raise PairingAgentError(f"bus D-Bus système indisponible : {err}") from err
    bus.export(AGENT_PATH, PairingAgent(address))
    try:
        await _call_agent_manager(bus, "RegisterAgent", "os", [AGENT_PATH, AGENT_CAPABILITY])
        try:
            await _call_agent_manager(bus, "RequestDefaultAgent", "o", [AGENT_PATH])
            yield
        finally:
            try:
                await _call_agent_manager(bus, "UnregisterAgent", "o", [AGENT_PATH])
            except PairingAgentError as err:
                _LOGGER.debug("Désenregistrement de l'agent : %s", err)
    finally:
        bus.unexport(AGENT_PATH)
        bus.disconnect()
