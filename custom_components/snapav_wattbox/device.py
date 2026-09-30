"""Stewart Wattbox Device."""

import asyncio
import logging
import re

from homeassistant.core import HomeAssistant, callback

from .const import WATTBOX_CONNECT_TIMEOUT, WATTBOX_PORT, WATTBOX_RESPONSE_TIMEOUT

_LOGGER = logging.getLogger(__name__)

DEVICE_MODEL = "Model"
DEVICE_ON = "ON"
DEVICE_OFF = "OFF"
DEVICE_RESET = "RESET"
DEVICE_OUTLET_COUNT = "OutletCount"
DEVICE_OUTLET_STATUS = "OutletStatus"
DEVICE_OUTLET_NAME = "OutletName"
DEVICE_OUTLET_SET = "OutletSet"
DEVICE_SERIAL = "Serial"
DEVICE_TOGGLE = "TOGGLE"
DEVICE_HOSTNAME = "Hostname"

class WattboxDevice:
    """Represents a single Wattbox device."""

    def __init__(self, hass: HomeAssistant, host: str, username: str, password: str) -> None:
        """Set up class."""

        self._hass = hass
        self._host = host
        self._username = username
        self._password = password
        self._device_id = f"WB@{host}"
        self._reader: asyncio.StreamReader
        self._writer: asyncio.StreamWriter
        self._init_event = asyncio.Event()
        self._online = False
        self._callback = None
        self._listener = None
        self._data = {}
        self._outlet_count = 0
        self._outlet_name = []
        self._outlet_status = []
        self._response_re = re.compile("(\\?|~)([^=]+)=(.+)")

    @property
    def device_id(self) -> str:
        """Use the mac."""
        return self._device_id

    @property
    def online(self) -> bool:
        """Return status."""
        return self._online

    def get_data_value(self, key: str) -> str:
        """Return a string value."""
        return self._data.get(key)

    async def open_connection(self, test: bool = False) -> bool:
        """Establish a connection."""
        if self.online:
            return True

        try:
            _LOGGER.debug("Establish new connection")
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, WATTBOX_PORT),
                timeout=WATTBOX_CONNECT_TIMEOUT,
            )
            await asyncio.wait_for(
                self._reader.readuntil(b"Username: "),
                timeout=WATTBOX_RESPONSE_TIMEOUT
            )
            self.write(self._username)
            await asyncio.wait_for(
                self._reader.readuntil(b"Password: "),
                timeout=WATTBOX_RESPONSE_TIMEOUT
            )
            self.write(self._password)
            await asyncio.wait_for(
                self._reader.readuntil(b"Successfully Logged In!"),
                timeout=WATTBOX_RESPONSE_TIMEOUT
            )
            if test:
                self._writer.close()
            else:
                self._online = True
                self._listener = asyncio.create_task(self.listener())

        except (TimeoutError, OSError, asyncio.IncompleteReadError) as err:
            self._online = False
            _LOGGER.error("Connect sequence error %s", err)
            raise ConnectionError("Connect sequence error") from err

        return True

    def write(self, reqstr: str) -> None:
        """Make an API call."""
        _LOGGER.debug("-> %s", reqstr)
        self._writer.write(reqstr.encode("ascii") + b"\n")

    async def send_query(self, method: str) -> None:
        """Format and send command."""
        if await self.open_connection():
            reqstr = f"?{method}"
            self.write(reqstr)

    async def send_command(self, method: str, data: str) -> None:
        """Format and send command."""
        if await self.open_connection():
            reqstr = f"!{method}={data}"
            self.write(reqstr)

    async def test_connection(self) -> bool:
        """Test a connect."""
        return await self.open_connection(test=True)

    async def update_data(self) -> None:
        """Stuff that has to be polled."""
        _LOGGER.debug("update data")
        await self.send_query(DEVICE_OUTLET_STATUS)

    async def async_init(self, data_callback: callback) -> None:
        """Query position and wait for response."""
        await self.send_query(DEVICE_MODEL)
        await self.send_query(DEVICE_HOSTNAME)
        await self.send_query(DEVICE_OUTLET_COUNT)
        await self.send_query(DEVICE_OUTLET_NAME)
        await asyncio.wait_for(
            self._init_event.wait(),
            timeout=WATTBOX_RESPONSE_TIMEOUT
        )
        _LOGGER.debug("initialized")
        self._callback = data_callback

    async def listener(self) -> None:
        """Listen for status updates from device."""

        _LOGGER.debug("listener started")
        try:
            while True:
                buf = await self._reader.readuntil(b"\n")
                if len(buf) == 0:
                    _LOGGER.error("Connection closed")
                    break
                buf = buf[:-1]
                respstr = buf.decode("ascii")
                _LOGGER.debug("<- %s", respstr)
                if respstr == "":
                    continue
                if respstr == "OK":
                    _LOGGER.debug("Command succeeded")
                    continue
                if respstr == "#Error":
                    _LOGGER.debug("Command error")
                    continue

                m = self._response_re.match(respstr)
                if m is None:
                    _LOGGER.error("Unrecognized response: %s", respstr)
                    continue
                method = m.group(2)
                data = m.group(3)
                self._data[method] = data
                if method == DEVICE_OUTLET_COUNT:
                    self._outlet_count = int(data)
                    self._outlet_name = [f"outlet {i+1}" for i in range(self._outlet_count)]
                elif method == DEVICE_OUTLET_NAME:
                    i = 0
                    while data is not None:
                        n = re.match("{([^}]+)}(,(.+))?", data)
                        _LOGGER.debug("%s %s", n.group(1), n.group(3))
                        if n is None:
                            break
                        self._outlet_name[i] = n.group(1)
                        data = n.group(3)
                        i += 1
                    self._init_event.set()
                elif method == DEVICE_OUTLET_STATUS:
                    self._outlet_status = [x == "1" for x in data.split(",")]
                elif method == DEVICE_SERIAL:
                    self._device_id = data
                elif method == DEVICE_HOSTNAME:
                    self._device_id = data

                if self._callback is not None:
                    self._callback(self._data)

        except Exception as exc:
            _LOGGER.error("Exception in listener: %s", exc)

        self._writer.close()
        self._online = False
        self._init_event.clear()

    def is_on(self, index: int) -> bool:
        """Property power."""
        return self._outlet_status[index]

    @property
    def outlet_names(self) -> list[str]:
        """Return source list."""
        return self._outlet_name

    async def async_outlet_set(self, index: int, op: str):
        """Set outlet status."""
        await self.send_command(DEVICE_OUTLET_SET,f"{index},{op}")

    async def async_turn_on(self, index: int):
        """Device turn on."""
        await self.async_outlet_set(index, DEVICE_ON)

    async def async_turn_off(self, index: int):
        """Device turn off."""
        await self.async_outlet_set(index, DEVICE_OFF)

    async def async_reset(self, index: int):
        """Device turn off then on."""
        await self.async_outlet_set(index, DEVICE_RESET)

    async def async_toggle(self, index: int):
        """Toggle device."""
        await self.async_outlet_set(index, DEVICE_TOGGLE)
