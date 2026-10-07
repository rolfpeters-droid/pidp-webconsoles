# PiDP-10 Web Console

FastAPI backend + xterm.js frontend for the PiDP-10 (KLH10-based emulation). Runs alongside the physical front panel, not instead of it.

## What it does

- **Operator console** over a WebSocket bridge to the existing telnet console port (default `1025`), with telnet IAC byte-stripping so raw control sequences don't leak into the terminal.
- **Login/terminal line** bridge to the OS's own terminal port (e.g. TOPS-10's DC10 line on `2020`), separate from the operator console — some OSes multiplex login prompts on a different port than the boot/operator stream, so the UI exposes both as separate tabs.
- **Knight TV / Type 340 display mirror**: a WebSocket periodically pushes a screenshot of the `cage`/`tvcon` display session so the display panel is visible in the browser too, without needing a full remote-desktop session for just that.
- Boot/stop goes through the same `pdpcontrol` script the physical kit already uses — this is a thin wrapper, not a second control path.

## Requirements

- A working PiDP-10 kit (KLH10 + `pdpcontrol`), per Oscar Vermeulen's own setup.
- Python 3, FastAPI, uvicorn (`pip install fastapi uvicorn[standard]` in a venv under this directory).
- `sway-headless.conf`: an optional headless Sway config if you want the Knight TV and Type 340 display windows tiled side-by-side for the screenshot source, instead of floating/overlapping. Only needed if you use that screenshot feature.

## Running it

```
cd pidp10
python3 -m venv venv
venv/bin/pip install fastapi "uvicorn[standard]"
venv/bin/python -m uvicorn app:app --host 0.0.0.0 --port 8080
```

See `systemd/pidp10-webconsole.service` for a systemd unit example (edit `User=`/`WorkingDirectory=` to match your setup — this one assumes a `pi` user and an install under `/opt/pidp10/webconsole`).

## Notes

- `TELNET_PORT` / `TERMINAL_PORT` / `SYSTEMS_DIR` / `PDPCONTROL` at the top of `app.py` are the only paths you should need to adjust for a different install layout.
- The frontend loads xterm.js from a CDN (`jsdelivr`) rather than vendoring it, to avoid bundling a third-party minified library in this repo. If you run fully offline, swap that `<script>`/`<link>` tag in `static/index.html` for a local copy of [xterm.js](https://github.com/xtermjs/xterm.js) (MIT licensed).
