#!/usr/bin/env python3
"""PiDP-1 READ IN service.

Simuleert een druk op de READ IN-knop door het KEY_READIN-bit (0o10) kort
in sw2 (byte-offset 8) van het gedeelde paneelsegment /tmp/pdp1_panel te
pulsen. De hardware-paneldriver overschrijft sw2 continu met de echte
schakelaarstand; daarom wordt het bit in een strakke lus geschreven zodat
de emulator (die per instructiecyclus samplet) de flank gegarandeerd ziet.

HTTP GET/POST /readin  ->  pulse; antwoord "ok".
Luistert op :8090. CORS open (webconsole draait op :8080).
"""
import mmap
import os
import signal
import subprocess
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

PANEL = "/tmp/pdp1_panel"
SW2_OFFSET = 8
KEY_READIN = 0o10
PULSE_S = 0.25


def panel_driver_pids():
    try:
        out = subprocess.run(["pgrep", "-x", "panel_pidp1"],
                             capture_output=True, text=True, timeout=5)
        return [int(p) for p in out.stdout.split()]
    except Exception:
        return []


def pulse_readin():
    # De hardware-paneldriver schrijft sw2 continu terug met de echte
    # schakelaarstand; zonder pauze flikkert het bit en herstart de read-in
    # telkens midden op de tape. Driver dus kort SIGSTOPpen zodat de
    # emulator precies één schone flank ziet.
    pids = panel_driver_pids()
    for pid in pids:
        os.kill(pid, signal.SIGSTOP)
    try:
        with open(PANEL, "r+b") as f:
            mm = mmap.mmap(f.fileno(), 60)
            try:
                sw2 = int.from_bytes(mm[SW2_OFFSET:SW2_OFFSET + 4], "little")
                mm[SW2_OFFSET:SW2_OFFSET + 4] = (sw2 | KEY_READIN).to_bytes(4, "little")
                time.sleep(PULSE_S)
                sw2 = int.from_bytes(mm[SW2_OFFSET:SW2_OFFSET + 4], "little")
                mm[SW2_OFFSET:SW2_OFFSET + 4] = (sw2 & ~KEY_READIN).to_bytes(4, "little")
                time.sleep(0.05)
            finally:
                mm.close()
    finally:
        for pid in pids:
            os.kill(pid, signal.SIGCONT)


class Handler(BaseHTTPRequestHandler):
    def _respond(self, code, body):
        self.send_response(code)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(body.encode())

    def do_GET(self):
        if self.path == "/readin":
            try:
                pulse_readin()
                self._respond(200, "ok")
            except Exception as e:
                self._respond(500, str(e))
        else:
            self._respond(404, "not found")

    do_POST = do_GET

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 8090), Handler).serve_forever()
