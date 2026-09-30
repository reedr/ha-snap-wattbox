"""A fake WattBox 800 that speaks the telnet Integration Protocol."""

from __future__ import annotations

import asyncio
import re


class FakeWattbox:
    """Serves login, identity queries, outlet control, meters, auto reboot and UPS."""

    def __init__(
        self,
        names: list[str] | None = None,
        hostname: str = "AV-Rack-1",
        service_tag: str = "ST000000000001",
        password: str = "pass",
    ) -> None:
        self.names = names or ["Switch", "Amp", "TV", "Roku", "Port", "Savant"]
        self.hostname = hostname
        self.service_tag = service_tag
        self.password = password
        self.model = "WB-800-IPVM-6"
        self.outlets = [True] * len(self.names)
        self.auto_reboot = False
        self.metering = True
        self.ups: str | None = None
        self.silent = False
        self.commands: list[str] = []
        self.clients: list[asyncio.StreamWriter] = []
        self._all: list[asyncio.StreamWriter] = []
        self.logins = 0
        self.port = 0
        self._server: asyncio.Server | None = None

    @property
    def open_clients(self) -> int:
        return sum(1 for w in self.clients if not w.is_closing())

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._client, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        for writer in self._all:
            writer.close()
        self._server.close()
        await self._server.wait_closed()

    def disconnect_all(self) -> None:
        for writer in self.clients:
            writer.close()

    def set_outlet(self, index: int, on: bool) -> None:
        """Change an outlet locally (front panel) and push the change."""
        self.outlets[index - 1] = on
        self._broadcast(f"~OutletStatus={self._status()}")

    def _status(self) -> str:
        return ",".join("1" if on else "0" for on in self.outlets)

    def _broadcast(self, line: str) -> None:
        for writer in self.clients:
            if not writer.is_closing():
                writer.write(line.encode() + b"\n")

    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._all.append(writer)
        try:
            while True:
                writer.write(b"Please Login to Continue\nUsername: ")
                await reader.readuntil(b"\n")
                writer.write(b"Password: ")
                password = (await reader.readuntil(b"\n")).strip().decode()
                if password == self.password:
                    break
                writer.write(b"Invalid Login\n")
            writer.write(b"Successfully Logged In!\n")
            self.logins += 1
            self.clients.append(writer)
            while True:
                line = (await reader.readuntil(b"\n")).strip().decode()
                self.commands.append(line)
                if line == "!Exit":
                    break
                if not self.silent:
                    for reply in self._handle(line):
                        writer.write(reply.encode() + b"\n")
        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        finally:
            writer.close()

    def _handle(self, line: str) -> list[str]:
        simple = {
            "?Model": self.model,
            "?Firmware": "2.8.0.0",
            "?Hostname": self.hostname,
            "?ServiceTag": self.service_tag,
            "?OutletCount": str(len(self.names)),
            "?OutletName": ",".join(f"{{{name}}}" for name in self.names),
            "?OutletStatus": self._status(),
            "?AutoReboot": "1" if self.auto_reboot else "0",
            "?UPSConnection": "1" if self.ups else "0",
        }
        if line in simple:
            return [f"{line}={simple[line]}"]
        if line == "?PowerStatus" and self.metering:
            return ["?PowerStatus=1.50,180.00,120.10,0"]
        if (m := re.fullmatch(r"\?OutletPowerStatus=(\d+)", line)) and self.metering:
            n = int(m.group(1))
            watts = 10.0 * n if self.outlets[n - 1] else 0.0
            return [f"?OutletPowerStatus={n},{watts:.2f},{watts / 120:.2f},120.10"]
        if line == "?UPSStatus" and self.ups:
            return [f"?UPSStatus={self.ups}"]
        if m := re.fullmatch(r"!OutletSet=(\d+),(ON|OFF|RESET)", line):
            n, action = int(m.group(1)), m.group(2)
            if not 1 <= n <= len(self.names):
                return ["#Error"]
            replies = ["OK"]
            if action != "RESET" and self.outlets[n - 1] != (action == "ON"):
                self.outlets[n - 1] = action == "ON"
                replies.append(f"~OutletStatus={self._status()}")
            return replies
        if m := re.fullmatch(r"!AutoReboot=([01])", line):
            self.auto_reboot = m.group(1) == "1"
            return ["OK"]
        return ["#Error"]
