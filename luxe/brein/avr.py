"""
Praten met de Marantz over telnet (poort 23), voor de testknop.

Let op: de receiver accepteert **een** telnet-sessie tegelijk. Zodra het
CrowPanel er is, is dat de partij die de verbinding vasthoudt en moet dit
dienstje ervan afblijven. Voor nu, met alleen een Mac, is het juist handig om
het protocol vanaf hier te kunnen uitproberen.
"""

import asyncio


async def probe(host: str, port: int = 23, timeout: float = 3.0) -> dict:
    """Verbindt, vraagt de stand op, en geeft terug wat de AVR meldt."""
    if not host:
        return {"ok": False, "error": "geen IP of hostnaam ingesteld"}

    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout)
    except asyncio.TimeoutError:
        return {"ok": False, "error": f"geen antwoord van {host}:{port} binnen {timeout:.0f}s"}
    except OSError as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    lines: list[str] = []
    try:
        # Uitgesmeerd versturen: onder ~50 ms laat de receiver commando's vallen.
        for query in ("PW?", "MV?", "SI?", "MU?"):
            writer.write((query + "\r").encode())
            await writer.drain()
            await asyncio.sleep(0.08)

        # Even luisteren naar wat er terugkomt.
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
        return {"ok": False, "error": "verbonden, maar geen antwoord. Staat "
                                      "Netwerkbesturing op 'Altijd aan'?"}

    volume = None
    for line in lines:
        if line.startswith("MV") and not line.startswith("MVMAX") and line[2:4].isdigit():
            half = int(line[2:4]) * 2 + (1 if len(line) > 4 and line[4] == "5" else 0)
            volume = half / 2.0 - 80.0
    return {"ok": True, "lines": lines, "volumeDb": volume}


async def send(host: str, port: int, command: str) -> dict:
    """Stuurt een enkel commando, bijvoorbeeld SIPHONO."""
    if not host:
        return {"ok": False, "error": "geen IP of hostnaam ingesteld"}
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
# Blijvende verbinding
#
# Voor de testknop is een losse verbinding genoeg, maar om het schermpje in de
# webinterface de versterker echt te laten bedienen moet de verbinding open
# blijven staan. Dat is ook nodig om mee te krijgen wat de receiver ongevraagd
# meldt: pak iemand de afstandsbediening, dan komt hier spontaan een "MV52"
# binnen en loopt de boog meteen mee.
#
# Zelfde opbouw als de firmware in luxe/crowpanel/: één verbinding, commando's
# gethrottled, en de toestand bijhouden uit wat er binnenkomt.
# ---------------------------------------------------------------------------
import contextlib
import time as _time

MIN_INTERVAL = 0.06          # onder ~50 ms laat de receiver commando's vallen


def _parse_half(digits: str):
    """MV en MVMAX delen dezelfde codering: '35' is 35, '695' is 69,5."""
    digits = digits.strip()
    if len(digits) < 2 or not digits[:2].isdigit():
        return None
    half = int(digits[:2]) * 2
    if len(digits) >= 3 and digits[2] == "5":
        half += 1
    return half


class AvrLink:
    """Houdt één telnet-sessie open en volgt de toestand van de receiver."""

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

    # -- verbinding --------------------------------------------------------
    async def connect(self, host: str, port: int = 23) -> dict:
        await self.disconnect()
        self.host, self.port = host, port
        if not host:
            self.state["error"] = "geen IP of hostnaam"
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
            # Niet alleen CancelledError: als de receiver de verbinding al had
            # verbroken, ligt die fout in de taak te wachten en komt hij hier
            # alsnog naar buiten. Loskoppelen mag nooit falen.
            with contextlib.suppress(BaseException):
                await self._task
            self._task = None
        if self._writer:
            self._writer.close()
            with contextlib.suppress(Exception):
                await self._writer.wait_closed()
            self._writer = None
        self.state["connected"] = False

    # -- verkeer -----------------------------------------------------------
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
        """Leest tot de verbinding weggaat.

        Dat wegvallen is hier geen randgeval maar de normale gang van zaken: de
        SR7015 laat een tweede client toe en gooit de eerste eruit. Vangen we
        dat niet, dan blijft `connected` op true staan terwijl er niets meer
        doorkomt — en dan liegt de webinterface over wie de versterker heeft.
        """
        buffer = ""
        try:
            while True:
                chunk = await reader.read(256)
                if not chunk:
                    self.state.update(connected=False, error="verbinding gesloten")
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
        # MVMAX eerst, anders leest de MV-tak "MA".
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
