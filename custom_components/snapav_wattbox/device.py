"""SnapAV WattBox telnet client (Integration Protocol v3)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from collections import deque
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field, replace

from homeassistant.core import HomeAssistant

from . import const
from .const import WATTBOX_PORT

_LOGGER = logging.getLogger(__name__)

_LOGIN_OK = b"Successfully Logged In!"
_USERNAME_PROMPT = b"Username: "
_PASSWORD_PROMPT = b"Password: "
_REPLY_RE = re.compile(r"([?~])([^=]+)=(.*)")
_NAME_RE = re.compile(r"\{([^}]*)\}")
MAX_OUTLET_NAME = 31


class WattboxError(Exception):
    """Base error."""


class WattboxConnectionError(WattboxError):
    """The WattBox could not be reached, or stopped answering."""


class WattboxAuthError(WattboxError):
    """The WattBox rejected the username or password."""


class WattboxCommandError(WattboxError):
    """The WattBox answered #Error."""


@dataclass(frozen=True)
class WattboxInfo:
    """Fixed facts about a unit, read once per connection."""

    model: str
    firmware: str | None
    hostname: str
    service_tag: str
    outlet_names: list[str]
    has_ups: bool


@dataclass(frozen=True)
class OutletPower:
    """One outlet's meter reading."""

    watts: float
    amps: float
    volts: float


@dataclass(frozen=True)
class PowerStatus:
    """Whole-unit meter reading."""

    amps: float
    watts: float
    volts: float
    # The protocol document calls the last field "safe voltage status", but units on
    # firmware 2.5 report 0 at a normal 123 V, so anything but 0 is treated as a fault.
    voltage_fault: bool


@dataclass(frozen=True)
class UpsStatus:
    """Attached UPS state."""

    battery_charge: int
    battery_load: int
    battery_healthy: bool
    power_lost: bool
    runtime: int
    alarm_enabled: bool
    alarm_muted: bool


@dataclass(frozen=True)
class WattboxState:
    """A snapshot of everything that changes."""

    outlets_on: tuple[bool, ...] = ()
    outlet_power: dict[int, OutletPower] = field(default_factory=dict)
    power: PowerStatus | None = None
    auto_reboot: bool | None = None
    ups: UpsStatus | None = None


def parse_outlet_names(data: str, count: int) -> list[str]:
    """Parse ``{Name 1},{Name 2},...``, padded or cut to the outlet count."""
    names = [name.strip() for name in _NAME_RE.findall(data)]
    names += [""] * (count - len(names))
    return [name or f"Outlet {i + 1}" for i, name in enumerate(names[:count])]


def raw_outlet_names(data: str, count: int) -> list[str]:
    """The names exactly as the unit holds them, padded with defaults only if missing."""
    names = [name.strip() for name in _NAME_RE.findall(data)][:count]
    return names + [f"Outlet {i + 1}" for i in range(len(names), count)]


def is_metered(model: str) -> bool:
    """Whether the model has power metering (all but the WB-150 and WB-250)."""
    return re.match(r"WB-?(150|250)\b", model.strip(), re.IGNORECASE) is None


def validate_outlet_name(name: str) -> str:
    """Return the trimmed name, or raise ValueError if the unit can't store it."""
    name = name.strip()
    if not name:
        raise ValueError("the name is empty")
    if len(name) > MAX_OUTLET_NAME:
        raise ValueError(f"the name is longer than {MAX_OUTLET_NAME} characters")
    if not name.isascii() or any(c in name for c in "{},"):
        raise ValueError("the name can only use plain ASCII, without braces or commas")
    return name


def parse_outlet_status(data: str) -> tuple[bool, ...]:
    """Parse ``1,0,1,...``."""
    return tuple(part.strip() == "1" for part in data.split(","))


def parse_power_status(data: str) -> PowerStatus:
    """Parse ``amps,watts,volts,flag``."""
    amps, watts, volts, flag = (part.strip() for part in data.split(","))
    return PowerStatus(float(amps), float(watts), float(volts), flag != "0")


def parse_outlet_power(data: str) -> tuple[int, OutletPower]:
    """Parse ``outlet,watts,amps,volts``."""
    index, watts, amps, volts = (part.strip() for part in data.split(","))
    return int(index), OutletPower(float(watts), float(amps), float(volts))


def parse_ups_status(data: str) -> UpsStatus:
    """Parse ``charge,load,health,power_lost,runtime,alarm_enabled,alarm_muted``."""
    charge, load, health, lost, runtime, alarm, muted = (
        part.strip() for part in data.split(",")
    )
    return UpsStatus(
        battery_charge=int(float(charge)),
        battery_load=int(float(load)),
        battery_healthy=health.lower() == "good",
        power_lost=lost.lower() == "true",
        runtime=int(float(runtime)),
        alarm_enabled=alarm.lower() == "true",
        alarm_muted=muted.lower() == "true",
    )


@dataclass
class _Pending:
    """A request waiting for its reply: ``?Key=...`` for queries, ``OK`` for commands."""

    key: str | None
    future: asyncio.Future[str]


class WattboxDevice:
    """One WattBox over a single long-lived telnet session.

    Requests are pipelined; the unit answers them in order. Outlet changes are
    also pushed unsolicited (``~OutletStatus``) and reported through the push
    callback, which receives ``None`` when the connection drops.
    """

    def __init__(self, hass: HomeAssistant, host: str, username: str, password: str) -> None:
        """Set up the client; nothing connects until first use."""
        self._hass = hass
        self.host = host
        self._username = username
        self._password = password
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._listener: asyncio.Task | None = None
        self._connect_lock = asyncio.Lock()
        self._rename_lock = asyncio.Lock()
        self._pending: deque[_Pending] = deque()
        self._push: Callable[[WattboxState | None], None] | None = None
        self._closed = False
        self._logged_in = False
        self._publish_count = 0
        self.info: WattboxInfo | None = None
        self.state = WattboxState()

    @property
    def connected(self) -> bool:
        """Whether a logged-in session is open."""
        return self._writer is not None and not self._writer.is_closing()

    def set_push_callback(self, callback: Callable[[WattboxState | None], None]) -> None:
        """Receive pushed state changes, or None when the connection drops."""
        self._push = callback

    async def _read_until_any(self, *markers: bytes) -> bytes:
        """Read until one of the markers arrives; return that marker."""
        assert self._reader is not None
        buf = b""
        while True:
            chunk = await self._reader.read(1024)
            if not chunk:
                raise WattboxConnectionError("connection closed during login")
            buf += chunk
            for marker in markers:
                if marker in buf:
                    return marker

    async def _login(self) -> None:
        """Answer the username and password prompts."""
        assert self._writer is not None
        await self._read_until_any(_USERNAME_PROMPT)
        try:
            self._write(self._username)
            await self._read_until_any(_PASSWORD_PROMPT)
            self._write(self._password)
        except UnicodeEncodeError as err:
            raise WattboxAuthError("the unit only accepts ASCII usernames and passwords") from err
        # A bad login is answered with the username prompt again.
        if await self._read_until_any(_LOGIN_OK, _USERNAME_PROMPT) != _LOGIN_OK:
            raise WattboxAuthError("username or password rejected")

    async def _async_connect(self) -> None:
        """Open and log in to a new session, unless one is already open."""
        async with self._connect_lock:
            if self._closed:
                raise WattboxConnectionError(f"{self.host}: client closed")
            if self.connected:
                return
            _LOGGER.debug("%s: connecting", self.host)
            try:
                self._reader, self._writer = await asyncio.wait_for(
                    asyncio.open_connection(self.host, WATTBOX_PORT),
                    timeout=const.WATTBOX_CONNECT_TIMEOUT,
                )
            except (TimeoutError, OSError) as err:
                self._reader = self._writer = None
                raise WattboxConnectionError(f"cannot connect to {self.host}: {err!r}") from err
            try:
                async with asyncio.timeout(const.WATTBOX_LOGIN_TIMEOUT):
                    await self._login()
            except WattboxAuthError:
                await self._async_drop()
                raise
            except (TimeoutError, OSError, WattboxConnectionError) as err:
                await self._async_drop()
                raise WattboxConnectionError(f"login to {self.host} failed: {err!r}") from err
            if self._closed or self._reader is None:
                # Closed while logging in (entry unloading): don't leave a session behind.
                await self._async_drop()
                raise WattboxConnectionError(f"{self.host}: client closed")
            self._logged_in = True
            self._listener = self._hass.async_create_background_task(
                self._listen(self._reader), f"snapav_wattbox listener {self.host}"
            )
            _LOGGER.debug("%s: logged in", self.host)

    def _write(self, line: str) -> None:
        assert self._writer is not None
        _LOGGER.debug("%s -> %s", self.host, line if line != self._password else "********")
        self._writer.write(line.encode("ascii") + b"\n")

    async def _request(self, line: str, key: str | None) -> str:
        """Send one line and wait for its reply; return the reply's value."""
        await self._async_connect()
        future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self._pending.append(_Pending(key, future))
        try:
            self._write(line)
            async with asyncio.timeout(const.WATTBOX_RESPONSE_TIMEOUT):
                return await future
        except TimeoutError as err:
            # A unit that stops answering is treated as gone; the next request reconnects.
            await self._async_drop()
            raise WattboxConnectionError(f"{self.host} did not answer {line}") from err
        except OSError as err:
            await self._async_drop()
            raise WattboxConnectionError(f"write to {self.host} failed: {err!r}") from err

    async def _query(self, key: str, arg: str | None = None) -> str:
        return await self._request(f"?{key}" if arg is None else f"?{key}={arg}", key)

    async def _command(self, key: str, value: str) -> None:
        await self._request(f"!{key}={value}", None)

    def _resolve(self, key: str | None, value: str) -> None:
        """Hand a reply to the oldest request waiting for that kind of reply."""
        for i, pending in enumerate(self._pending):
            if pending.key == key:
                # Anything queued ahead of it was skipped by the unit.
                for _ in range(i):
                    skipped = self._pending.popleft()
                    if not skipped.future.done():
                        skipped.future.set_exception(WattboxCommandError("no reply"))
                self._pending.popleft()
                if not pending.future.done():
                    pending.future.set_result(value)
                return
        _LOGGER.debug("%s: unexpected reply %s=%s", self.host, key, value)

    def _handle_line(self, line: str) -> None:
        if not line or line == _LOGIN_OK.decode():
            return
        if line == "OK":
            self._resolve(None, "")
            return
        if line.startswith("#"):
            if self._pending:
                pending = self._pending.popleft()
                if not pending.future.done():
                    pending.future.set_exception(WattboxCommandError(line))
            return
        if (match := _REPLY_RE.fullmatch(line)) is None:
            _LOGGER.debug("%s: ignoring %r", self.host, line)
            return
        kind, key, value = match.groups()
        if kind == "?":
            self._resolve(key, value)
        elif key == "OutletStatus":
            self._publish(replace(self.state, outlets_on=parse_outlet_status(value)))

    def _publish(self, state: WattboxState) -> None:
        self._publish_count += 1
        self.state = state
        if self._push is not None:
            self._push(state)

    async def _listen(self, reader: asyncio.StreamReader) -> None:
        """Read replies and pushes until the connection closes."""
        try:
            while line := await reader.readline():
                text = line.decode("ascii", errors="replace").strip()
                _LOGGER.debug("%s <- %s", self.host, text)
                try:
                    self._handle_line(text)
                except ValueError:
                    _LOGGER.warning("%s: could not parse %r", self.host, text)
                except Exception:
                    _LOGGER.exception("%s: error handling %r", self.host, text)
        except (OSError, ValueError, asyncio.IncompleteReadError) as err:
            # ValueError: a line longer than the stream limit.
            _LOGGER.debug("%s: read failed: %r", self.host, err)
        finally:
            if self._reader is reader:
                _LOGGER.info("%s: connection closed", self.host)
                await self._async_drop(from_listener=True)
                if self._push is not None:
                    self._push(None)

    async def _async_drop(self, from_listener: bool = False) -> None:
        """Forget the current session and fail whatever was waiting on it."""
        writer, listener = self._writer, self._listener
        self._reader = self._writer = self._listener = None
        self._logged_in = False
        while self._pending:
            pending = self._pending.popleft()
            if not pending.future.done():
                pending.future.set_exception(WattboxConnectionError("connection closed"))
        if listener is not None and not from_listener:
            listener.cancel()
        if writer is not None:
            writer.close()
            try:
                async with asyncio.timeout(1):
                    await writer.wait_closed()
            except (TimeoutError, OSError):
                pass

    async def async_close(self) -> None:
        """Log out and close the session; the client can't reconnect afterwards."""
        self._closed = True
        if self.connected and self._logged_in:
            with contextlib.suppress(OSError):
                self._write("!Exit")
        self._push = None
        await self._async_drop()

    async def _optional_query(self, key: str, arg: str | None = None) -> str | None:
        """Query something older firmware or smaller models may not support."""
        try:
            return await self._query(key, arg)
        except WattboxCommandError:
            return None

    async def _gather(self, *requests: Coroutine[None, None, str | None]) -> list[str | None]:
        """Pipeline requests on one session; raise the first failure once all finish."""
        try:
            await self._async_connect()
        except BaseException:
            for request in requests:
                request.close()
            raise
        results = await asyncio.gather(*requests, return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                raise result
        return results  # type: ignore[return-value]

    async def async_get_info(self) -> WattboxInfo:
        """Read the unit's identity and outlet layout."""
        model, firmware, hostname, tag, count, names, ups = await self._gather(
            self._query("Model"),
            self._optional_query("Firmware"),
            self._query("Hostname"),
            self._query("ServiceTag"),
            self._query("OutletCount"),
            self._query("OutletName"),
            self._optional_query("UPSConnection"),
        )
        try:
            outlet_count = int(count)
        except ValueError as err:
            raise WattboxConnectionError(f"bad outlet count {count!r}") from err
        self.info = WattboxInfo(
            model=model.strip(),
            firmware=firmware.strip() if firmware else None,
            hostname=hostname.strip(),
            service_tag=tag.strip(),
            outlet_names=parse_outlet_names(names, outlet_count),
            has_ups=(ups or "").strip() == "1",
        )
        return self.info

    async def async_update(self, outlet_metering: bool) -> WattboxState:
        """Poll everything that changes."""
        if self.info is None:
            await self.async_get_info()
        assert self.info is not None
        requests = {
            "outlets": self._query("OutletStatus"),
            "auto_reboot": self._optional_query("AutoReboot"),
        }
        if self.metered:
            requests["power"] = self._optional_query("PowerStatus")
            if outlet_metering:
                for i in range(1, len(self.info.outlet_names) + 1):
                    requests[f"outlet{i}"] = self._optional_query("OutletPowerStatus", str(i))
        if self.info.has_ups:
            requests["ups"] = self._optional_query("UPSStatus")
        published = self._publish_count
        values = dict(zip(requests, await self._gather(*requests.values()), strict=True))
        try:
            outlet_power = dict(
                parse_outlet_power(value)
                for name, value in values.items()
                if name.startswith("outlet") and name != "outlets" and value
            )
            outlets_on = parse_outlet_status(values["outlets"])
            if self._publish_count != published:
                # A push or command result arrived while this poll was in
                # flight; it's newer than the poll's answer.
                outlets_on = self.state.outlets_on
            state = WattboxState(
                outlets_on=outlets_on,
                outlet_power=outlet_power,
                power=parse_power_status(values["power"]) if values.get("power") else None,
                auto_reboot=(
                    values["auto_reboot"].strip() == "1" if values["auto_reboot"] else None
                ),
                ups=parse_ups_status(values["ups"]) if values.get("ups") else None,
            )
        except ValueError as err:
            raise WattboxConnectionError(f"unexpected reply from {self.host}: {err}") from err
        self.state = state
        return state

    async def _refresh_outlets(self) -> None:
        outlets_on = parse_outlet_status(await self._query("OutletStatus"))
        self._publish(replace(self.state, outlets_on=outlets_on))

    async def async_set_outlet(self, outlet: int, action: str) -> None:
        """Send ON, OFF or RESET to an outlet (1-based) and report the result."""
        await self._command("OutletSet", f"{outlet},{action}")
        await self._refresh_outlets()

    async def async_set_auto_reboot(self, enabled: bool) -> None:
        """Turn auto reboot on or off."""
        await self._command("AutoReboot", "1" if enabled else "0")
        auto_reboot = (await self._query("AutoReboot")).strip() == "1"
        self._publish(replace(self.state, auto_reboot=auto_reboot))

    async def async_set_outlet_name(self, outlet: int, name: str) -> None:
        """Rename an outlet (1-based) on the unit."""
        name = validate_outlet_name(name)
        if self.info is None:
            await self.async_get_info()
        assert self.info is not None
        count = len(self.info.outlet_names)
        # The unit only takes spaces through OutletNameSetAll, so re-read the
        # current names and send them all back with this one changed.
        async with self._rename_lock:
            # Unnamed outlets go back as the unit had them, not as our defaults.
            names = raw_outlet_names(await self._query("OutletName"), count)
            names[outlet - 1] = name
            await self._command("OutletNameSetAll", ",".join(f"{{{n}}}" for n in names))
            names = parse_outlet_names(await self._query("OutletName"), count)
        self.info = replace(self.info, outlet_names=names)

    @property
    def metered(self) -> bool:
        """Whether the unit has power metering, judged by its model."""
        return self.info is not None and is_metered(self.info.model)

    async def async_test_connection(self) -> WattboxInfo:
        """Log in, read the unit's identity, and disconnect."""
        try:
            return await self.async_get_info()
        finally:
            await self.async_close()
