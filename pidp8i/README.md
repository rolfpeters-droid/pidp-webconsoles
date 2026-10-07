# PiDP-8/I Web Console additions

The PiDP-8/I kit already ships with a web terminal (ttyd attached to the `pidp8i` screen session). This folder adds a small boot-select HTTP API and a status/boot-picker page on top of that — it does not replace the existing ttyd terminal.

## What it does

- **`pidp8-bootapi.py`**: a small HTTP API (default port `8091`, CORS open) with two endpoints:
  - `GET /api/status` → `{"running": bool, "script": "0".."7"|null}`
  - `GET /api/boot/N` → stops the simulator and restarts it with boot script `N` (0–7: OS/8 RK05, RIM loader, TSS/8, OS/8 DECtape, Spacewar!, Blinkenlights, ETOS V5B, OS/8 default)
  
  It follows the same restart path the official `pidp8i` management script uses — stop the systemd user service (clean SIMH shutdown), then start the simulator with the chosen boot script in a `screen -S pidp8i` session so ttyd can reattach via `screen -x pidp8i`. It also makes sure to kill any orphaned `pidp8i` screen sessions first, since `screen -x` fails ambiguously if more than one matches.
- **`index.html`**: the existing amber web terminal page, extended with boot-select buttons that call the API above and a small status bar.
- **`console-cmd` / `start-console.sh` / `ttyd-port` / `web-port`**: the existing install's config for what command ttyd attaches to and which ports it and the web UI listen on.

## Requirements

- A working PiDP-8/I kit (SimH-based `pidp8i`), per Oscar Vermeulen's own setup, with its existing ttyd web terminal already running.
- Python 3 (standard library only — no extra packages needed for `pidp8-bootapi.py`).

## Running it

The boot API is a standalone script:

```
python3 pidp8-bootapi.py
```

See `systemd/pidp8-bootapi.service` for a systemd unit example (edit `User=`/paths to match your setup — this one assumes a `pi` user with the script in their home directory).

## Notes

- `index.html` derives the ttyd/API host from `window.location.hostname` at runtime, so it works regardless of how you reach the Pi (direct IP, reverse proxy, VPN) — there's no hardcoded address to edit.
