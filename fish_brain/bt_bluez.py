"""BlueZ over D-Bus for bt.py (ADR 0031): imported only with FISH_BLUETOOTH=on.

dbus-fast is asyncio, the fish is threads: one thread runs a loop, and `call` is a blocking
facade over it, so the worker in bt.py stays a plain state machine. The agent's methods are async
because `ask` can wait 45 s for his answer: they run it in an executor and the loop stays free,
which is what lets a Cancel reach BlueZ while Pair is waiting.

The agent and the search belong to this connection and die with it. A lost connection is seen at
the next call, and the next call connects again; `register_agent` runs before every Pair, so a
restarted bluetoothd gets it back.
"""
import asyncio
import threading

from dbus_fast import BusType, DBusError, Message, MessageType, Variant
from dbus_fast.aio import MessageBus
from dbus_fast.service import ServiceInterface, method

from .bt import BusError, BusTimeout

BLUEZ = "org.bluez"
AGENT_PATH = "/fish/bt_agent"
AGENT_IFACE = "org.bluez.Agent1"
CAPABILITY = "DisplayYesNo"       # GNOME's choice; a plain speaker gets Just Works either way
OBJECTS_S = 5.0
CONNECT_RETRY_S = 5.0

SIGNATURES = {"SetDiscoveryFilter": "a{sv}", "RemoveDevice": "o", "ConnectProfile": "s"}


def _mac_of(path: str) -> str:
    return path.rsplit("dev_", 1)[-1].replace("_", ":").upper()


def plain(value):
    """Variants all the way down -> plain Python."""
    if isinstance(value, Variant):
        return plain(value.value)
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [plain(v) for v in value]
    return value


class Rejected(DBusError):
    def __init__(self):
        super().__init__("org.bluez.Error.Rejected", "rejected")


class Agent(ServiceInterface):
    def __init__(self, loop):
        super().__init__(AGENT_IFACE)
        self.ask = None
        self._loop = loop

    async def _asked(self, kind: str, device: str, number: str = ""):
        ask = self.ask
        if ask is None:
            raise Rejected()
        answer = await self._loop.run_in_executor(None, ask, kind, _mac_of(device), number)
        if answer is None or answer is False:
            raise Rejected()
        return answer

    @method()
    def Release(self):
        return None

    @method()
    async def RequestPinCode(self, device: "o") -> "s":
        return str(await self._asked("pin", device))

    @method()
    async def DisplayPinCode(self, device: "o", pincode: "s"):
        await self._asked("show", device, pincode)

    @method()
    async def RequestPasskey(self, device: "o") -> "u":
        return int(await self._asked("passkey", device))

    @method()
    async def DisplayPasskey(self, device: "o", passkey: "u", entered: "q"):
        await self._asked("show", device, f"{passkey:06d}")

    @method()
    async def RequestConfirmation(self, device: "o", passkey: "u"):
        await self._asked("confirm", device, f"{passkey:06d}")

    @method()
    async def RequestAuthorization(self, device: "o"):
        await self._asked("authorize", device)

    @method()
    async def AuthorizeService(self, device: "o", uuid: "s"):
        await self._asked("authorize", device)

    @method()
    def Cancel(self):
        ask = self.ask
        owner = getattr(ask, "__self__", None)
        if owner is not None:
            owner.agent_cancelled()


class DbusBus:
    def __init__(self):
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, name="bt-dbus", daemon=True)
        self._thread.start()
        self._bus: MessageBus | None = None
        self._agent = Agent(self._loop)
        self._lock = threading.Lock()

    def _run(self, coro, timeout: float):
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout)
        except TimeoutError:
            future.cancel()
            raise BusTimeout(getattr(coro, "__name__", "")) from None

    async def _connected(self) -> MessageBus:
        bus = self._bus
        if bus is not None and bus.connected:
            return bus
        bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        bus.export(AGENT_PATH, self._agent)
        self._bus = bus
        return bus

    async def _send(self, path, iface, member, signature="", body=None) -> list:
        bus = await self._connected()
        reply = await bus.call(Message(destination=BLUEZ, path=path, interface=iface, member=member,
                                       signature=signature, body=body or []))
        if reply.message_type == MessageType.ERROR:
            raise BusError(reply.error_name or "error", str(reply.body[0]) if reply.body else "")
        return reply.body

    def _do(self, coro, timeout: float):
        try:
            return self._run(coro, timeout)
        except BusError:
            raise
        except (OSError, EOFError, DBusError, ValueError) as e:
            self._bus = None
            raise BusError(type(e).__name__, str(e)[:200]) from None

    def objects(self) -> dict:
        body = self._do(self._send("/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects"),
                        OBJECTS_S)
        return plain(body[0])

    def register_agent(self, ask) -> None:
        self._agent.ask = ask
        try:
            self._do(self._send("/org/bluez", "org.bluez.AgentManager1", "RegisterAgent", "os",
                                [AGENT_PATH, CAPABILITY]), OBJECTS_S)
        except BusError as e:
            if "AlreadyExists" not in e.name:
                raise

    def set_prop(self, path, iface, name, value) -> None:
        self._do(self._send(path, "org.freedesktop.DBus.Properties", "Set", "ssv",
                            [iface, name, Variant("b", value)]), OBJECTS_S)

    def call(self, path, iface, method_name, *args, timeout=10.0):
        signature, body = SIGNATURES.get(method_name, ""), []
        if method_name == "SetDiscoveryFilter":
            body = [{k: Variant("s", v) for k, v in args[0].items()}]
        elif method_name == "RemoveDevice":
            body = [args[0][1]]
        elif args:
            body = list(args)
        return self._do(self._send(path, iface, method_name, signature, body), timeout)

    def close(self) -> None:
        bus, self._bus = self._bus, None
        if bus is not None:
            self._loop.call_soon_threadsafe(bus.disconnect)
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(1.0)
