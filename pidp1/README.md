# PiDP-1 Web Console additions

![PiDP-1 web console running the Snowflake demo on the Type 30 CRT](../docs/screenshots/pidp1.jpg)

**Depends on Oscar Vermeulen's own PiDP-1 web kit software already being installed** — his Go server (`pdpsrv.go`) and front-end (`p7sim.js` for the Type 30 CRT WebGL point-stream display, `papertape.js`, `index.html`/"Control Panel" page). This folder does **not** redistribute that software; it adds a second, lighter console page plus a small READ IN helper service that sit alongside it.

If you don't already have Oscar's PiDP-1 kit software running, start there first: [obsolescence.dev](https://obsolescence.dev/).

## What's actually new here

- **`console.html`**: a compact single-page console — Type 30 CRT display, a grid of one-click program buttons (Spacewar!, Pong, Lunar Lander, Minskytron, Munching Squares, LISP, DDT, MACRO, etc.), and a simulated Soroban typewriter for text I/O. It reuses `p7sim.js` and `typewriter.js` from the existing kit install (loaded via relative `<script>` tags) rather than reimplementing the display/typewriter logic.
- **`readin_server.py`**: a tiny HTTP service (default port `8090`, CORS open) that simulates a press of the physical READ IN button. It pulses the `KEY_READIN` bit in the shared-memory panel segment (`/tmp/pdp1_panel`) that the hardware panel driver also writes to — written as a tight loop so the emulator (which samples once per instruction cycle) reliably sees the edge, since the panel driver keeps overwriting that byte with the real switch state. One-click "load this tape and run it" only works because of this: mounting a tape alone doesn't start it without the READ IN pulse.
- **`typewriter.js`**: includes a fix for an easy-to-miss focus/input issue — clicking the rendered paper often lands on the `<pre>` element inside it rather than the focusable container, and mobile on-screen keyboards only appear for a real `<input>`/`<textarea>`, not a `tabindex`-only `div`. An invisible `<textarea>` overlay captures focus/input instead.

## Requirements

- A working PiDP-1 kit with Oscar Vermeulen's own web software installed and running.
- Python 3 (standard library only for `readin_server.py`).

## Running it

`console.html` is static — serve it from the same directory as the existing kit's web files (so the relative `p7sim.js`/`typewriter.js` references resolve), or copy it alongside them.

```
python3 readin_server.py
```

See `systemd/pidp1-readin.crontab.example` for how this is scheduled to start at boot (a `@reboot` cron entry; adjust the path to match where you place the script).

## Notes

- `readin_server.py` listens on `0.0.0.0:8090` with CORS open — it's meant to sit on the same host as the web console, not be exposed beyond your own network.
- The Pi Zero 2W this was built against is slow enough that a boot can take a few seconds before points appear on the CRT — that's expected, not a hang.
