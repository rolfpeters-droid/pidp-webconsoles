# PiDP-11 Web Console

FastAPI backend + xterm.js frontend for the PiDP-11 (SimH-based emulation). Modeled on the PiDP-10 console in this repo. Runs alongside the physical front panel, not instead of it.

## What it does

- **Operator console** bridge: a pty attached to the same `screen -x pidp11` session the front panel driver uses, so boot messages, single-user prompts, and every supported OS show up in the browser exactly as they do on a serial terminal.
- **DZ11 login-terminal** bridge: a separate telnet connection to the DZ11 terminal multiplexer (default `127.0.0.1:4000`), only meaningful for OSes that actually attach a DZ line in their boot config (2.11BSD, 2.11BSD+, RSX-11M-Plus, RSX-11M+ BQ). The UI only shows this tab as useful for those OSes.
- **OS picker**: boot/stop goes through the standard PiDP-11 toolchain script (`pidp11.sh <bootnr>`), reading the available boot numbers from the kit's own `selections` file — this doesn't introduce a second boot mechanism, it drives the existing one.
- Passing a boot number explicitly overrides the physical SR (switch register) rockers, same as it would from the console directly.

## Requirements

- A working PiDP-11 kit (SimH + the standard `pidp11.sh` toolchain), per Oscar Vermeulen's own setup.
- Python 3, FastAPI, uvicorn (`pip install fastapi uvicorn[standard]` in a venv under this directory).

## Running it

```
cd pidp11
python3 -m venv venv
venv/bin/pip install fastapi "uvicorn[standard]"
venv/bin/python -m uvicorn app:app --host 0.0.0.0 --port 8080
```

See `systemd/pidp11-webconsole.service` for a systemd unit example (edit `User=`/`WorkingDirectory=` to match your setup).

## Notes

- Boot times vary a lot by OS: RT-11 and the smaller Unix versions boot in seconds; 2.11BSD(+) needs 1–2 minutes (fsck + multiuser) before the DZ line gives you a login prompt — the UI's help panel explains this so it's not mistaken for a hang.
- The frontend loads xterm.js and the fit addon from the `jsdelivr` CDN rather than vendoring them.
