"""
PiDP-10 Web Console
FastAPI backend: REST status/boot/stop + WebSocket bridge naar telnet console (:1025)
+ WebSocket met periodieke grim-screenshots van de cage/tvcon Knight TV sessie.

FastAPI + xterm.js + telnet-IAC-strippende bridge, amber-on-dark frontend.
"""
import asyncio
import json
import os
import subprocess
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

APP_DIR = Path(__file__).parent
SYSTEMS_DIR = Path("/opt/pidp10/systems")
SELECTIONS_FILE = SYSTEMS_DIR / "selections"
STATE_FILE = APP_DIR / "state.json"
PDPCONTROL = "/usr/local/bin/pdpcontrol"
TELNET_HOST = "127.0.0.1"
TELNET_PORT = 1025
# DC10-terminallijn (login-lijn) uit tops10-603/boot.pi ("at dc 2020"), los van
# de operator-console op 1025 -- login gebeurt bewust niet op de Console-tab,
# zie de handleiding-modal in static/index.html voor de uitleg.
TERMINAL_PORT = 2020
XDG_RUNTIME_DIR = "/run/user/1000"


def current_wayland_display():
    """wlroots kiest niet altijd wayland-0 (bv. na een snelle herstart met een
    nog niet opgeruimd lock-bestand) — socketnaam dus live opzoeken i.p.v.
    hardcoden, anders breekt grim stil na elke compositor-herstart."""
    for entry in sorted(Path(XDG_RUNTIME_DIR).glob("wayland-*")):
        if not entry.name.endswith(".lock") and entry.is_socket():
            return entry.name
    return "wayland-0"

app = FastAPI(title="PiDP-10 Web Console")


# ---------------------------------------------------------------------------
# Helpers: systems list, running-state, boot/stop
# ---------------------------------------------------------------------------

def read_systems():
    """Parse /opt/pidp10/systems/selections -> [{number, name}]"""
    systems = []
    if SELECTIONS_FILE.exists():
        for line in SELECTIONS_FILE.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2:
                number, name = parts[0], parts[1]
                systems.append({"number": int(number, 8), "name": name})
    return systems


def read_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"system": None}


def write_state(system_name):
    STATE_FILE.write_text(json.dumps({"system": system_name}))


def is_running():
    """PiDP-10 draait als er een 'pidp10' screen-sessie actief is."""
    try:
        out = subprocess.run(
            ["screen", "-ls"], capture_output=True, text=True, timeout=5
        ).stdout
        return ".pidp10\t" in out or ".pidp10 " in out or "pidp10\t" in out
    except Exception:
        return False


# ---------------------------------------------------------------------------
# REST API
# ---------------------------------------------------------------------------

@app.get("/api/status")
def api_status():
    state = read_state()
    return {"running": is_running(), "system": state.get("system")}


@app.get("/api/systems")
def api_systems():
    return {"systems": read_systems()}


@app.post("/api/boot")
async def api_boot(payload: dict):
    name = payload.get("system")
    systems = {s["name"]: s["number"] for s in read_systems()}
    if name not in systems:
        return JSONResponse({"error": f"onbekend systeem: {name}"}, status_code=400)
    number = systems[name]
    # stop eventueel draaiende sessie eerst
    subprocess.run([PDPCONTROL, "stop"], capture_output=True, timeout=15)
    await asyncio.sleep(1)
    result = subprocess.run(
        [PDPCONTROL, "start", str(number)], capture_output=True, text=True, timeout=15
    )
    write_state(name)
    return {"ok": True, "output": result.stdout}


@app.post("/api/stop")
def api_stop():
    result = subprocess.run([PDPCONTROL, "stop"], capture_output=True, text=True, timeout=15)
    write_state(None)
    return {"ok": True, "output": result.stdout}


# ---------------------------------------------------------------------------
# WebSocket: console (xterm.js <-> telnet :1025), met telnet IAC-negotiation
# ---------------------------------------------------------------------------

IAC = 255
DONT = 254
DO = 253
WONT = 252
WILL = 251
SB = 250
SE = 240


async def telnet_to_ws(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, ws: WebSocket):
    """Leest ruwe bytes van de telnet-console, filtert IAC-negotiation eruit,
    beantwoordt elk verzoek met een weigering (DONT/WONT), en stuurt de
    overgebleven schone data door naar de websocket (xterm.js)."""
    in_sb = False
    while True:
        chunk = await reader.read(4096)
        if not chunk:
            break
        clean = bytearray()
        i = 0
        n = len(chunk)
        while i < n:
            b = chunk[i]
            if in_sb:
                if b == IAC and i + 1 < n and chunk[i + 1] == SE:
                    in_sb = False
                    i += 2
                    continue
                i += 1
                continue
            if b == IAC and i + 1 < n:
                cmd = chunk[i + 1]
                if cmd in (DO, DONT, WILL, WONT) and i + 2 < n:
                    opt = chunk[i + 2]
                    reply = WONT if cmd == DO else (DONT if cmd == WILL else None)
                    if reply is not None:
                        writer.write(bytes([IAC, reply, opt]))
                        await writer.drain()
                    i += 3
                    continue
                if cmd == SB:
                    in_sb = True
                    i += 2
                    continue
                if cmd == IAC:
                    clean.append(IAC)
                    i += 2
                    continue
                # onbekend commando, sla over
                i += 2
                continue
            clean.append(b)
            i += 1
        if clean:
            await ws.send_bytes(bytes(clean))


async def ws_to_telnet(ws: WebSocket, writer: asyncio.StreamWriter):
    try:
        while True:
            data = await ws.receive_text()
            payload = data.encode("utf-8", errors="ignore")
            # escape losse IAC-bytes conform telnet-protocol
            payload = payload.replace(bytes([IAC]), bytes([IAC, IAC]))
            writer.write(payload)
            await writer.drain()
    except WebSocketDisconnect:
        pass


async def telnet_bridge(ws: WebSocket, port: int, label: str):
    """Generieke telnet<->websocket bridge, gedeeld door Console (:1025) en
    Terminal (:2020). label wordt alleen gebruikt in de foutmelding."""
    await ws.accept()
    try:
        reader, writer = await asyncio.open_connection(TELNET_HOST, port)
    except OSError:
        await ws.send_text(f"\r\n[console] Geen actieve PDP-10 sessie ({label} poort {port} niet bereikbaar).\r\n")
        await ws.close()
        return

    to_ws = asyncio.create_task(telnet_to_ws(reader, writer, ws))
    to_telnet = asyncio.create_task(ws_to_telnet(ws, writer))
    try:
        done, pending = await asyncio.wait(
            {to_ws, to_telnet}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
    finally:
        writer.close()


@app.websocket("/ws/console")
async def ws_console(ws: WebSocket):
    await telnet_bridge(ws, TELNET_PORT, "console")


@app.websocket("/ws/terminal")
async def ws_terminal(ws: WebSocket):
    await telnet_bridge(ws, TERMINAL_PORT, "terminal")


# ---------------------------------------------------------------------------
# WebSocket: desktop (grim screenshots van de cage/tvcon Knight TV sessie)
# ---------------------------------------------------------------------------

@app.websocket("/ws/desktop")
async def ws_desktop(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            env = {**os.environ, "XDG_RUNTIME_DIR": XDG_RUNTIME_DIR, "WAYLAND_DISPLAY": current_wayland_display()}
            proc = await asyncio.create_subprocess_exec(
                "/usr/bin/grim", "-",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env=env,
            )
            img, _ = await proc.communicate()
            if img:
                await ws.send_bytes(img)
            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Static frontend
# ---------------------------------------------------------------------------

app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")


@app.get("/")
def index():
    return FileResponse(str(APP_DIR / "static" / "index.html"))
