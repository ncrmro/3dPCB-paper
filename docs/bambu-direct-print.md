# Bambu direct print

LAN-mode automation for sending a substrate STL straight to a Bambu Lab
printer: **slice → upload → start → live status**, all driven from the gallery
and run by a sidecar that holds the one Bambu auth on behalf of every
browser tab.

Initial work landed 2026-05-29.

## Why a sidecar and not "Astro talks to the printer"

Bambu's local protocols (MQTT/TLS on `:8883`, implicit FTPS on `:990`,
custom binary on `:6000` for the camera) each allow **one authenticated
client at a time**. If Astro opened a socket per request, every browser
refresh would force a fresh TLS+auth handshake, two open tabs would race
for the camera socket, and the printer access code would have to live on
the request path. Folding all of that into one long-lived process that
exposes localhost HTTP is the canonical fix.

The bridge speaks **only over a Unix domain socket** (`code/bambu/.run/bridge.sock`,
chmod `0600`). Astro proxies via `node:http`'s `socketPath`. Browser tabs
never see Bambu credentials and never re-handshake the printer.

```
browser ─► Astro /api/printer/{status,print,print/status}
                          │  node:http socketPath
                          ▼
                 code/bambu/.run/bridge.sock   (UDS, owner-only)
                          │  aiohttp UnixSite
                          ▼
                 bambu-bridge  (process-compose process)
                          │
                MQTT/TLS :8883  ←→  printer  ←→  FTPS :990  (implicit TLS,
                  paho-mqtt                       data-channel session reuse)
                          │
                  bambu-studio (CLI subprocess for slicing)
```

## What works end-to-end (verified 2026-05-29)

| Capability                                            | State |
| ----------------------------------------------------- | ----- |
| MQTT auth, status push, command publish               | OK    |
| FTPS implicit-TLS with session reuse; LIST + STOR     | OK    |
| Bambu Studio CLI slice (P2S 0.4, 0.20mm Std, PLA)     | OK    |
| Bridge `/status.json`, `/health`, `/print`, `/print/status` | OK |
| Astro proxies (UDS via `socketPath`)                  | OK    |
| `/printer` live status page (polls every 2 s)         | OK    |
| Print button on every CAD model page                  | OK    |
| Real print fired from MQTT and accepted by printer    | OK    |
| Camera via RTSPS port 322 (H.264 1080p → MJPEG)       | OK    |
| Pause / Resume / Stop print buttons                   | OK    |
| Chamber + work light control (on / off / flashing)    | OK    |
| Bed-type override threaded into the slice command     | OK    |

## Files

```
code/bambu/
  flake.nix          # python3 + paho-mqtt + aiohttp + bambu-studio
  flake.lock
  bridge.py          # MQTT + FTPS + slicer orchestration + aiohttp UDS server
  .env.example       # template for printer creds + slicer profile names
  .env               # actual creds (gitignored)
  .gitignore         # .env, .run/
  .run/bridge.sock   # owner-only UDS (gitignored, runtime artifact)

code/web/src/pages/
  api/printer/status.ts          # GET → bridge /status.json
  api/printer/print.ts           # POST → bridge /print (queue a job)
  api/printer/print/status.ts    # GET → bridge /print/status (phase)
  printer.astro                  # live status page
  model/[project]/[name].astro   # Print button + JS (CAD models only)

process-compose.yaml             # bambu-bridge process; BAMBU_BRIDGE_SOCK env_cmd
```

## Configuration

`code/bambu/.env` (gitignored — copy `.env.example`):

```
BAMBU_IP=192.168.1.121
BAMBU_SERIAL=22E8AJ5A1200281
BAMBU_ACCESS_CODE=...           # 8-char LAN code from printer Settings → LAN Mode
```

Optional slicer overrides (defaults shown):

```
BAMBU_BBL_SYS_DIR=~/.config/BambuStudio/system/BBL
BAMBU_MACHINE="Bambu Lab P2S 0.4 nozzle"
BAMBU_PROCESS="0.20mm Standard @BBL P2S"
BAMBU_FILAMENT="Bambu PLA Basic @BBL P2S"
BAMBU_BED_TYPE="Textured PEI Plate"
```

**`BAMBU_BED_TYPE` is load-bearing.** The printer refuses to start
(`PAUSE → stg_cur 11 → print_error 0x05007091`) if the sliced bed type
disagrees with the plate it physically has installed. Bambu Studio CLI
rejects generic `--<setting>` overrides ("setup params error"), so the
bridge writes a per-job copy of the process JSON with `curr_bed_type`
injected, then loads that. Common values (string, exact case):

- `Bambu Cool Plate` (plate code 1)
- `Bambu Engineering Plate` (2)
- `Bambu High Temperature Plate` (3)
- `Textured PEI Plate` (4) — P2S default
- `Bambu Supertack Plate` (5)

Verify with `plate.base` in the printer's MQTT report — it carries the
integer code for whatever the printer currently has installed.

`BAMBU_BRIDGE_SOCK` is set centrally in `process-compose.yaml`'s
`env_cmds` block so the bridge and the web process resolve to the same
absolute path.

## Bridge endpoints

All UDS-only.

**Status + readiness**
- `GET /health` — `ok` (cheap readiness probe).
- `GET /status.json` — `{ connected, last_update, stale_seconds, last_error, print, job }`. `print` is the full latest MQTT push merged in-place (pushall + diffs); ~98 fields including `gcode_state`, `mc_percent`, `layer_num`, `total_layer_num`, `nozzle_temper`, `bed_temper`, `mc_remaining_time`, `stg_cur`, `subtask_name`.

**Print job**
- `POST /print` `{ board: "<name>" }` — validates against `^[a-zA-Z0-9][a-zA-Z0-9_]{0,63}$`, queues a print job (slice → upload → MQTT publish), returns `{ status: "queued", board }` immediately. Returns `409 already_running` if a job is in-flight.
- `GET /print/status` — `{ running, board, phase, phases_seen, started_at, completed_at, error }`. Phase machine: `queued → slicing → uploading → starting → started | failed`. Polled by the print button.

**Control (MQTT publish)**
- `POST /control/print` `{ command: "pause" | "resume" | "stop" }` — fires a print job command at the running print. `stop` is gated by `confirm()` on the page side.
- `POST /control/light` `{ node: "chamber_light" | "work_light", mode: "on" | "off" | "flashing" }` — drives the printer's `ledctrl` MQTT command.

**Camera (RTSPS:322 via ffmpeg)**
- `POST /camera/start` — spawns ffmpeg pulling `rtsps://bblp:<code>@<ip>:322/streaming/live/1`, transcoding H.264 → MJPEG on stdout. Bridge cache fills with the latest JPEG.
- `POST /camera/stop` — terminates the ffmpeg subprocess; clears the frame cache.
- `GET /camera/status` — `{ running, started_at, frame_age, error, subscribers }`.
- `GET /camera/snapshot.jpg` — latest cached JPEG (single response).
- `GET /camera/stream.mjpg` — `multipart/x-mixed-replace; boundary=bambuframe`. Many tabs share one ffmpeg subprocess by fanning out from the cache; each tab's read just selects newer-than-last-sent frames.

Browser-visible Astro proxies mirror these one-to-one under `/api/printer/{status,print,print/status,control/print,control/light,camera/...}`.

## Read the error codes; don't guess from symptoms

Every MQTT push during a failed/paused print carries machine-readable
fault codes. **Decode them on sight — the hex is the diagnosis.** Burned
~90 minutes during the build session anchoring on "the printer is
asking for filament confirmation" when the print kept failing at
`stg_cur 11`, with three explicit codes in every push that named the
real problem (bed-type mismatch):

```
err:           3005008051
print_error:   83918929   = 0x05007091   ← print module / wrong-plate code
fail_reason:   83918929   = 0x05007091
HMS code:      131184     = 0x00020070   ← user-facing maintenance flag
```

Bambu's error-code layout is **`0xMMMM_EEEE`** — high half is the module
(`0x0500` = print machine, `0x0700` = AMS / filament, `0x0300` = toolhead),
low half is the specific code. So `0x05007091` is "print module · code
0x7091 (build plate)". HMS codes use the same packing in a separate
`hms[]` array.

**Rule:** when `gcode_state` flips to `PAUSE` or `FAILED` while the
bridge's `/print/status` shows `phase: started, error: null`, read
`print.print_error` (and `print.err`, and any `print.hms[].code`) as
hex and identify the module *before* hypothesizing from behavioral
symptoms. The codes are stable, public, and almost always specific
enough to point at one root cause.

Concrete look-up paths:

- The Bambu HMS database in the community wiki and `pybambu`'s source
  carry the most current code → label mappings.
- Cross-reference with `print.plate.base` (plate code), `print.vt_tray`
  (single virtual tray), `print.ams.tray_exist_bits` (which AMS slots
  actually hold filament) to localize whether the fault is plate,
  filament, or hardware.

A future bridge addition should decode the high half on the way out so
`/status.json` includes `print_error_decoded: { module: "0x0500",
code: "0x7091" }` and `/printer` can render a one-line plain label
instead of a 9-digit decimal.

## Caveats and gotchas

- **Bambu Studio CLI needs a GUI-initialized data dir.** `~/.config/BambuStudio/` must be populated by opening the GUI once. CLI alone can't materialize the `*_full/` flattened profiles. The bridge calls the CLI directly; on a fresh machine the slice step will fail until the GUI runs once.
- **Stderr noise from the slicer is normal.** `nozzle_volume_type not found` and `glfwInit return error` are non-fatal — the 3MF still gets produced (`return_code: 0`, `error_string: "Success."`). The bridge treats "file exists" as the success signal.
- **Implicit FTPS quirks.**
  - Port 990 is implicit TLS; `ftplib.FTP_TLS` only does explicit TLS — the bridge subclasses to wrap the socket pre-handshake.
  - **Data channel must resume the control TLS session** or the printer answers `522 SSL session reuse required`. The override is in `ImplicitFTPS.ntransfercmd`.
- **One-print-at-a-time on the bridge.** Second click while a job is running returns `409`. The printer-side state is independent of the bridge's slot, so a 200 from `/print` only means the bridge accepted the work — not that the printer accepted the resulting MQTT `project_file` command. Watch the MQTT `gcode_state` to confirm.
- **Single-client camera.** Even once the camera works, only one process can hold the port-6000 socket. The bridge will own it; tabs consume via the proxy.
- **Dev-server-only auth surface.** The Astro proxies don't authenticate. Fine for localhost; do not expose the dev server publicly without adding auth on the proxy paths.
- **Bambu firmware fragility.** Bambu's 2025 "authorization control" update broke the local MQTT/FTPS path for third-party tools once already; expect future firmware to do it again.

## Camera

**Working.** The H-platform P2S moved the camera off the legacy P1/A1
port-6000 protocol entirely and serves it as **RTSPS on port 322**
(`rtsps://bblp:<access-code>@<ip>:322/streaming/live/1`, 1920×1080
H.264, 30 fps source). The URL is announced in the printer's own MQTT
report under `print.ipcam.rtsp_url`.

The bridge runs `ffmpeg` as a subprocess to pull the RTSPS stream and
transcode to MJPEG on stdout. A reader task slices the stream on
JPEG `FF D8` / `FF D9` markers and caches the latest frame; the
`/camera/stream.mjpg` endpoint fans that single cache out to any
number of browser tabs as `multipart/x-mixed-replace`. ~5 fps wall
ceiling in the current ffmpeg invocation (`-r 5`) to keep CPU
and per-viewer bandwidth modest; raise it by editing `_camera_cmd()`.

### Why the original port-6000 hypothesis failed

Five candidate auth headers against `:6000` — including obvious decoys
like all-zeros — every single one received the byte-identical 24-byte
error response (`08 00 00 00  3f 01 03 00 …`). Identical responses for
valid and bogus headers meant the camera service was rejecting the
connection wholesale, not failing on auth. The wire format was never
the bug; the camera simply isn't on port 6000 on H-platform firmware.

The lesson maps directly to the error-code lesson above: when every
hypothesis returns the same error fingerprint, **the error itself is
data** — the printer was effectively telling us "there's no service
here," which should have been read as "check what service this printer
*does* expose," not "try more variants of the assumed protocol."

## Next steps

When picking this up:

1. **Decode print errors in the bridge.** Add a tiny `_decode_error()`
   that splits a 32-bit code into `(module, code)` hex pair and maps
   known prefixes (`0x0500` print, `0x0700` AMS, `0x0300` toolhead) to a
   short label. Surface in `/status.json` so the `/printer` page renders
   a plain label instead of a 9-digit decimal. Removes the entire class
   of misdiagnosis the bed-type confusion fell into.
2. **SSE push instead of 2 s polling** on `/printer` once polling proves
   stable. The bridge already holds the freshest state in memory; just
   add an SSE generator on the same UDS.
3. **`bin/print <board>` shell wrapper** that does the same flow without
   the gallery: useful for headless / CI / quick smoke prints.
4. **Tune the slicer profile for substrate-specific geometry** — current
   defaults (PLA Basic, 0.20 mm Standard) are generic. Channels are wider
   than typical part walls; bed adhesion and first-layer cooling probably
   want adjustment.
5. **Per-model bed type / material override.** Plumb the spec YAML →
   process JSON so a board can request its own filament/process/bed if it
   needs something other than the defaults (e.g. an ABS substrate would
   want `Bambu Engineering Plate` + ABS filament + the matching process).
6. **Camera quality knobs.** Current `-r 5` MJPEG is monitoring-grade;
   `-r 15 -q:v 3` is closer to liveview. Worth a settings page once
   we care.
7. **Per-model thumbnails from the camera stream.** Save a snapshot at
   start, mid, and end of each print, attached to the gallery entry.

## Verification log

Session 2026-05-29, all artifacts in `/tmp/` (none committed):

- `bambu_lan_test.py` — TCP, MQTT auth + status push + pushall round-trip,
  FTPS LIST. All green.
- `bambu_get_version.py` — Confirmed P2S identity (`AP02` AP, `MC06`
  motion controller, `TH03` toolhead, single extruder, 0.4 nozzle).
- `bambu_full_report.py` — Dumped full MQTT report; observed
  `extruder.info` length 1 (single ext), `fourth_axis` + `laser` fields
  present (H-platform features, not connected).
- `bambu_upload.py` — STOR of `substrate_p2s.gcode.3mf` (152 464 B); size
  matched in LIST.
- `bambu_print_start.py` — `print.command: project_file` accepted
  (`result=SUCCESS`); `gcode_state FINISH → RUNNING` in 2.7 s.
- `bambu_cam_probe.py` — 5 candidate camera auth headers against the
  legacy `:6000` port, all identical 503-equivalent response. Mooted
  once `print.ipcam.rtsp_url` in the MQTT report revealed the
  H-platform camera was on `rtsps://...:322/streaming/live/1`.
- ffmpeg one-frame probe of the RTSPS URL — 1920×1080 H.264 @ 30 fps
  decoded cleanly, 36 KB JPEG written. Bridge then wired with
  `ffmpeg` subprocess + MJPEG fan-out via `multipart/x-mixed-replace`.

### Errors not caught fast enough

- First failed print sat at `gcode_state=PAUSE, stg_cur=11` with
  `print_error=83918929` (=`0x05007091`). Hypothesized as a filament
  confirmation prompt; actual cause was build-plate mismatch
  (`plate.base: 4` Textured PEI vs. slicer-default Cool Plate). Fixed
  by injecting `curr_bed_type` into a per-job copy of the process
  JSON before slicing, since Bambu Studio CLI rejects generic
  `--<setting>` overrides with `setup params error`.
