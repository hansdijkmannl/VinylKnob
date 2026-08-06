"""
Talking to the receiver over telnet (port 23).

Note: the receiver accepts **one** telnet session at a time. Once the panel is
running, it is the one holding that connection and this service must keep its
hands off. Before there is a panel — with nothing but a laptop — this is a
convenient way to try the protocol out.
"""

import asyncio


async def probe(host: str, port: int = 23, timeout: float = 3.0) -> dict:
    """Connect, ask for the current state, return whatever the receiver says."""
    if not host:
        return {"ok": False, "error": "no IP address or hostname set"}

    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout)
    except asyncio.TimeoutError:
        return {"ok": False, "error": f"no answer from {host}:{port} within {timeout:.0f}s"}
    except OSError as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    lines: list[str] = []
    try:
        # Spaced out: below about 50 ms the receiver drops commands.
        for query in ("PW?", "MV?", "SI?", "MU?"):
            writer.write((query + "\r").encode())
            await writer.drain()
            await asyncio.sleep(0.08)

        # Listen for a moment to whatever comes back.
        deadline = asyncio.get_event_loop().time() + 1.5
        buffer = b""
        while asyncio.get_event_loop().time() < deadline:
            try:
                chunk = await asyncio.wait_for(reader.read(256), timeout=0.4)
            except asyncio.TimeoutError:
                continue
            if not chunk:
                break
            buffer += chunk
        lines = [s for s in buffer.decode(errors="replace").replace("\n", "\r").split("\r") if s]
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:                                  # noqa: BLE001
            pass

    if not lines:
        return {"ok": False, "error": "connected, but no answer. Is Network "
                                      "Control set to 'Always On'?"}

    volume = None
    for line in lines:
        if line.startswith("MV") and not line.startswith("MVMAX") and line[2:4].isdigit():
            half = int(line[2:4]) * 2 + (1 if len(line) > 4 and line[4] == "5" else 0)
            volume = half / 2.0 - 80.0
    return {"ok": True, "lines": lines, "volumeDb": volume}


async def send(host: str, port: int, command: str) -> dict:
    """Send a single command, for example SIPHONO."""
    if not host:
        return {"ok": False, "error": "no IP address or hostname set"}
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=3.0)
        writer.write((command + "\r").encode())
        await writer.drain()
        await asyncio.sleep(0.3)
        writer.close()
        return {"ok": True}
    except Exception as exc:                               # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# A connection that stays open
#
# A one-shot connection is enough to test with, but for the web interface to
# actually drive the amplifier the connection has to stay up. It also has to
# stay up to catch what the receiver reports unasked: pick up the remote and an
# "MV52" arrives here on its own, and the arc follows immediately.
#
# Same shape as the firmware in luxe/crowpanel/: one connection, commands
# throttled, and the state tracked from whatever comes in.
# ---------------------------------------------------------------------------
import contextlib
import time as _time

MIN_INTERVAL = 0.06          # below ~50 ms the receiver drops commands


def _parse_half(digits: str):
    """MV and MVMAX share an encoding: '35' is 35, '695' is 69.5."""
    digits = digits.strip()
    if len(digits) < 2 or not digits[:2].isdigit():
        return None
    half = int(digits[:2]) * 2
    if len(digits) >= 3 and digits[2] == "5":
        half += 1
    return half


class AvrLink:
    """Holds one telnet session open and tracks the receiver's state."""

    def __init__(self):
        self.host = ""
        self.port = 23
        self.state = {
            "connected": False, "powered": False, "muted": False,
            "haveVolume": False, "volumeDb": None, "volMaxDb": 18.0,
            "input": "", "error": "",
        }
        self._writer = None
        self._task = None
        self._last_send = 0.0

    # -- connecting --------------------------------------------------------
    async def connect(self, host: str, port: int = 23) -> dict:
        await self.disconnect()
        self.host, self.port = host, port
        if not host:
            self.state["error"] = "no IP address or hostname"
            return self.state

        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=3.0)
        except Exception as exc:                           # noqa: BLE001
            self.state["error"] = f"{type(exc).__name__}: {exc}"
            return self.state

        self._writer = writer
        self.state.update(connected=True, error="")
        self._task = asyncio.create_task(self._read_loop(reader))

        for query in ("PW?", "ZM?", "MV?", "MU?", "SI?"):
            await self.send(query)
        return self.state

    async def disconnect(self) -> None:
        if self._task:
            self._task.cancel()
            # Not just CancelledError: if the receiver had already dropped the
            # connection, that error is sitting in the task waiting and surfaces
            # here instead. Disconnecting must never fail.
            with contextlib.suppress(BaseException):
                await self._task
            self._task = None
        if self._writer:
            self._writer.close()
            with contextlib.suppress(Exception):
                await self._writer.wait_closed()
            self._writer = None
        self.state["connected"] = False

    # -- traffic -----------------------------------------------------------
    async def send(self, command: str) -> bool:
        if not self._writer:
            return False
        gap = _time.monotonic() - self._last_send
        if gap < MIN_INTERVAL:
            await asyncio.sleep(MIN_INTERVAL - gap)
        try:
            self._writer.write((command + "\r").encode())
            await self._writer.drain()
        except Exception as exc:                           # noqa: BLE001
            self.state.update(connected=False, error=str(exc))
            return False
        self._last_send = _time.monotonic()
        return True

    async def set_volume_db(self, db: float) -> bool:
        db = max(-80.0, min(self.state["volMaxDb"], db))
        half = int(round((db + 80.0) * 2))
        whole, rest = divmod(half, 2)
        return await self.send(f"MV{whole:02d}5" if rest else f"MV{whole:02d}")

    async def _read_loop(self, reader) -> None:
        """Read until the connection goes away.

        That is not an edge case here but the normal course of events: the
        receiver lets a second client in and throws the first one out. Without
        catching it, `connected` stays true while nothing comes through any
        more — and then the web interface is lying about who holds the
        amplifier.
        """
        buffer = ""
        try:
            while True:
                chunk = await reader.read(256)
                if not chunk:
                    self.state.update(connected=False, error="connection closed")
                    return
                buffer += chunk.decode(errors="replace")
                while "\r" in buffer:
                    line, _, buffer = buffer.partition("\r")
                    self._apply(line.strip())
        except asyncio.CancelledError:
            raise
        except Exception as exc:                           # noqa: BLE001
            self.state.update(connected=False,
                              error=f"{type(exc).__name__}: {exc}")

    def _apply(self, line: str) -> None:
        if len(line) < 2:
            return
        # MVMAX first, or the MV branch reads "MA".
        if line.startswith("MVMAX"):
            half = _parse_half(line[5:])
            if half:
                self.state["volMaxDb"] = half / 2.0 - 80.0
        elif line.startswith("MV"):
            half = _parse_half(line[2:])
            if half is not None:
                self.state["volumeDb"] = half / 2.0 - 80.0
                self.state["haveVolume"] = True
        elif line.startswith("MU"):
            self.state["muted"] = line.endswith("ON")
        elif line.startswith(("ZM", "PW")):
            self.state["powered"] = line.endswith("ON")
        elif line.startswith("SI"):
            self.state["input"] = line[2:]


link = AvrLink()
