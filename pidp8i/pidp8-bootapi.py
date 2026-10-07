#!/usr/bin/env python3
"""PiDP-8/I boot-API.

Kleine HTTP-API naast de statische web-UI (:8080) en ttyd (:7681):

  GET /api/status   -> {"running": bool, "script": "0"|"1"|...|null}
  GET /api/boot/N   -> stopt de simulator en herstart met N.script (N = 0-7)

Het herstarten volgt hetzelfde pad als het officiele pidp8i-beheerscript:
de systemd user-service wordt gestopt (die draait 'pidp8i stop', nette
shutdown van SIMH) en daarna wordt de simulator met het gekozen bootscript
in een screen-sessie 'pidp8i' gestart, zodat ttyd (screen -x pidp8i) er
gewoon weer aan kan hangen. Luistert op :8091, CORS open.
"""
import json
import os
import re
import subprocess
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

BOOTDIR = "/opt/pidp8i/share/boot"
SIM = "/opt/pidp8i/bin/pidp8i-sim"
WORKDIR = "/opt/pidp8i/share/media"
STATE = os.path.expanduser("~/.pidp8-current-boot")
ENV = dict(os.environ,
           XDG_RUNTIME_DIR="/run/user/1000",
           DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/1000/bus")


def sim_running():
    return subprocess.run(["pgrep", "-x", "pidp8i-sim"],
                          capture_output=True).returncode == 0


def current_script():
    try:
        with open(STATE) as f:
            return f.read().strip()
    except OSError:
        return None


def stop_all():
    subprocess.run(["systemctl", "--user", "stop", "pidp8i"],
                   env=ENV, capture_output=True, timeout=30)
    # Alle pidp8i-screensessies expliciet beëindigen: er kunnen er meerdere
    # (deels wees) zijn, en dan faalt ttyd's 'screen -x pidp8i' op ambiguïteit
    # — dat gaf de eindeloze reconnect-lus in de browser.
    out = subprocess.run(["screen", "-ls"], capture_output=True,
                         text=True).stdout
    for m in re.finditer(r"(\d+\.pidp8i)", out):
        subprocess.run(["screen", "-S", m.group(1), "-X", "quit"],
                       capture_output=True)
    for _ in range(10):
        if not sim_running():
            break
        time.sleep(0.5)
    if sim_running():
        subprocess.run(["pkill", "-9", "-x", "pidp8i-sim"], capture_output=True)
        time.sleep(0.5)
    subprocess.run(["screen", "-wipe"], capture_output=True)


def do_boot(n):
    stop_all()
    time.sleep(1)
    subprocess.run(["screen", "-dm", "-S", "pidp8i", SIM, f"{BOOTDIR}/{n}.script"],
                   cwd=WORKDIR, check=True, timeout=15)
    # ttyd vers herstarten: tijdens de wissel stapelen zich reconnect-pogingen
    # op (max-clients 5) en blijven stale screen-attaches hangen, wat in de
    # browser eindeloos "reconnecting"-geflikker geeft.
    subprocess.run(["sudo", "-n", "systemctl", "restart", "pidp8-ttyd"],
                   capture_output=True, timeout=15)
    with open(STATE, "w") as f:
        f.write(str(n))


class Handler(BaseHTTPRequestHandler):
    def _respond(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/status":
            self._respond(200, {"running": sim_running(),
                                "script": current_script()})
        elif self.path.startswith("/api/boot/"):
            n = self.path.rsplit("/", 1)[-1]
            if n not in "01234567" or len(n) != 1:
                self._respond(400, {"error": "boot number moet 0-7 zijn"})
                return
            try:
                do_boot(n)
                self._respond(200, {"ok": True, "script": n})
            except Exception as e:
                self._respond(500, {"error": str(e)})
        else:
            self._respond(404, {"error": "not found"})

    do_POST = do_GET

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 8091), Handler).serve_forever()
