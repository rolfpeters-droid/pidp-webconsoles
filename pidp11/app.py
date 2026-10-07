"""
PiDP-11 Web Console
FastAPI backend, naar het model van de PiDP-10 webconsole in deze repo.

Twee terminal-bruggen:
- /ws/console : pty -> `screen -x pidp11` = de simh operator-console
  (boot-meldingen, single-user prompts, alle OS-en).
- /ws/dz      : telnet-bridge naar 127.0.0.1:4000 = DZ11 terminallijn
  (login-terminal; alleen actief bij OS-en met `attach dz 4000` in hun
  boot.ini: 211bsd, rsx11mp, rsx11bq).

Boot/stop gaat via de standaard PiDP-11 toolchain: screen-sessie `pidp11`
draait /opt/pidp11/bin/pidp11.sh [bootnr]; met argument negeert die de
fysieke SR-draaischakelaars.
"""
import asyncio
import fcntl
import json
import os
import pty
import signal
import struct
import subprocess
import termios
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

APP_DIR = Path(__file__).parent
SYSTEMS_DIR = Path("/opt/pidp11/systems")
SELECTIONS_FILE = SYSTEMS_DIR / "selections"
SIMH_CMD_FILE = Path("/dev/shm/pidp11/tmpsimhcommand.txt")
PIDP11_SH = "/opt/pidp11/bin/pidp11.sh"
DZ_HOST, DZ_PORT = "127.0.0.1", 4000

# Volgorde + nette labels voor de boot-keuze. Alleen systemen die zowel in
# `selections` staan als een directory met boot.ini hebben komen in de lijst.
LABELS = {
    "211bsd":  "2.11BSD UNIX",
    "rt11":    "RT-11",
    "rsx11mp": "RSX-11M-Plus",
    "rsts7":   "RSTS/E V7",
    "dos11":   "DOS-11",
    "unix1":   "UNIX v1 (1972)",
    "unix5":   "UNIX v5",
    "unix6":   "UNIX v6",
    "unix7":   "UNIX v7",
    "sysiii":  "UNIX System III",
    "sysv":    "UNIX System V",
    "211bsd+": "2.11BSD+",
    "rsx11bq": "RSX-11M+ BQ",
    "blinky":  "Blinky (demo)",
    "idled":   "Idle (blinkenlights)",
}
DZ_SYSTEMS = {"211bsd", "211bsd+", "rsx11mp", "rsx11bq"}

app = FastAPI(title="PiDP-11 Web Console")


def read_systems():
    """selections-file -> geordende lijst {name, code, label, dz}."""
    by_name = {}
    if SELECTIONS_FILE.exists():
        for line in SELECTIONS_FILE.read_text().splitlines():
            parts = line.split()
            if len(parts) >= 2:
                code, name = parts[0], parts[1]
                if name not in by_name and (SYSTEMS_DIR / name / "boot.ini").exists():
                    by_name[name] = code
    ordered = [n for n in LABELS if n in by_name]
    ordered += [n for n in by_name if n not in LABELS]
    return [
        {"name": n, "code": by_name[n], "label": LABELS.get(n, n),
         "dz": n in DZ_SYSTEMS}
        for n in ordered
    ]


def current_system():
    """Het draaiende systeem staat in het simh-commandofile op de ramdisk:
    'cd /opt/pidp11/systems/<naam>'."""
    try:
        for line in SIMH_CMD_FILE.read_text().splitlines():
            line = line.strip()
            if line.startswith("cd "):
                return Path(line[3:]).name
    except OSError:
        pass
    return None


def is_running():
    try:
        out = subprocess.run(["screen", "-ls"], capture_output=True,
                             text=True, timeout=5).stdout
        return ".pidp11" in out
    except Exception:
        return False


@app.get("/api/status")
def api_status():
    return {"running": is_running(), "system": current_system()}


@app.get("/api/systems")
def api_systems():
    return {"systems": read_systems()}


@app.post("/api/boot")
async def api_boot(payload: dict):
    name = payload.get("system")
    systems = {s["name"]: s["code"] for s in read_systems()}
    if name not in systems:
        return JSONResponse({"error": f"onbekend systeem: {name}"}, status_code=400)
    # Bestaande sessie netjes weg (zelfde volgorde als pdp11control.sh do_stop)
    subprocess.run(["screen", "-S", "pidp11", "-X", "quit"], capture_output=True, timeout=10)
    await asyncio.sleep(1)
    for p in ("client11", "server11"):
        subprocess.run(["pkill", p], capture_output=True, timeout=10)
    await asyncio.sleep(1)
    result = subprocess.run(
        ["screen", "-dmS", "pidp11", PIDP11_SH, systems[name]],
        capture_output=True, text=True, timeout=15)
    return {"ok": result.returncode == 0, "output": result.stdout}


@app.post("/api/stop")
async def api_stop():
    subprocess.run(["screen", "-S", "pidp11", "-X", "quit"], capture_output=True, timeout=10)
    await asyncio.sleep(1)
    for p in ("client11", "server11"):
        subprocess.run(["pkill", p], capture_output=True, timeout=10)
    return {"ok": True}


# ---------------------------------------------------------------------------
# /ws/console : pty <-> `screen -x pidp11` (gedeelde operator-console)
# ---------------------------------------------------------------------------

RESIZE_PREFIX = "\x01"  # frontend stuurt "\x01{\"cols\":80,\"rows\":24}"


@app.websocket("/ws/console")
async def ws_console(ws: WebSocket):
    await ws.accept()
    if not is_running():
        await ws.send_text("\r\n[console] Geen actieve PDP-11 sessie (screen 'pidp11' draait niet). Kies een OS en druk op BOOT.\r\n")
        await ws.close()
        return

    pid, fd = pty.fork()
    if pid == 0:  # kind: word de screen-client
        env = dict(os.environ, TERM="xterm-256color", HOME="/home/pi", LANG="C.UTF-8")
        os.execvpe("screen", ["screen", "-x", "pidp11"], env)

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def on_readable():
        try:
            data = os.read(fd, 4096)
        except OSError:
            data = b""
        queue.put_nowait(data)

    loop.add_reader(fd, on_readable)

    async def pty_to_ws():
        while True:
            data = await queue.get()
            if not data:
                break
            await ws.send_bytes(data)

    async def ws_to_pty():
        try:
            while True:
                text = await ws.receive_text()
                if text.startswith(RESIZE_PREFIX):
                    try:
                        dims = json.loads(text[1:])
                        winsz = struct.pack("HHHH", int(dims["rows"]), int(dims["cols"]), 0, 0)
                        fcntl.ioctl(fd, termios.TIOCSWINSZ, winsz)
                    except (ValueError, KeyError, OSError):
                        pass
                    continue
                os.write(fd, text.encode("utf-8", errors="ignore"))
        except WebSocketDisconnect:
            pass

    t1 = asyncio.create_task(pty_to_ws())
    t2 = asyncio.create_task(ws_to_pty())
    try:
        done, pending = await asyncio.wait({t1, t2}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
    finally:
        loop.remove_reader(fd)
        try:
            os.kill(pid, signal.SIGHUP)
        except ProcessLookupError:
            pass
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            await loop.run_in_executor(None, os.waitpid, pid, 0)
        except ChildProcessError:
            pass
        try:
            await ws.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# /ws/dz : telnet-bridge naar de DZ11-mux (127.0.0.1:4000), IAC gefilterd
# ---------------------------------------------------------------------------

IAC, DONT, DO, WONT, WILL, SB, SE = 255, 254, 253, 252, 251, 250, 240


async def telnet_to_ws(reader, writer, ws):
    in_sb = False
    while True:
        chunk = await reader.read(4096)
        if not chunk:
            break
        clean = bytearray()
        i, n = 0, len(chunk)
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
                i += 2
                continue
            clean.append(b)
            i += 1
        if clean:
            await ws.send_bytes(bytes(clean))


async def ws_to_telnet(ws, writer):
    try:
        while True:
            data = await ws.receive_text()
            payload = data.encode("utf-8", errors="ignore")
            payload = payload.replace(bytes([IAC]), bytes([IAC, IAC]))
            writer.write(payload)
            await writer.drain()
    except WebSocketDisconnect:
        pass


@app.websocket("/ws/dz")
async def ws_dz(ws: WebSocket):
    await ws.accept()
    try:
        reader, writer = await asyncio.open_connection(DZ_HOST, DZ_PORT)
    except OSError:
        await ws.send_text(
            "\r\n[console] DZ-terminallijn niet bereikbaar (poort 4000).\r\n"
            "Het draaiende OS heeft geen DZ11-mux, of simh draait niet.\r\n"
            "DZ-lijnen zijn beschikbaar onder: 2.11BSD, RSX-11M-Plus, RSX-11M+ BQ.\r\n")
        await ws.close()
        return
    t1 = asyncio.create_task(telnet_to_ws(reader, writer, ws))
    t2 = asyncio.create_task(ws_to_telnet(ws, writer))
    try:
        done, pending = await asyncio.wait({t1, t2}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
    finally:
        writer.close()


app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")


@app.get("/")
def index():
    # Geen Cache-Control betekent dat de browser zelf een heuristiek kiest
    # voor hoelang deze pagina "vers" blijft -- een gewone refresh pakt dan
    # niet gegarandeerd een net gedeployde wijziging op (precies wat er
    # gebeurde tijdens het debuggen van de terminal-scrollbar, 28 aug 2026).
    # no-cache dwingt de browser altijd te revalideren bij de server.
    return FileResponse(
        str(APP_DIR / "static" / "index.html"),
        headers={"Cache-Control": "no-cache"},
    )
