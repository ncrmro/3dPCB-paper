"""Bambu LAN bridge.

One process holds the printer's MQTT subscription and orchestrates print
jobs (slice → upload → start). Clients (Astro, scripts) read state + POST
jobs over a Unix domain socket. Collapses N tabs to one Bambu auth and
keeps the access code out of any code that runs in the browser.

Env (printer creds + slicer config live in `.env`):

  BAMBU_IP             192.168.1.121
  BAMBU_SERIAL         22E…
  BAMBU_ACCESS_CODE    8-char LAN code from the printer screen
  BAMBU_BRIDGE_SOCK    absolute path to the listen socket
  BAMBU_BBL_SYS_DIR    Bambu Studio system profile dir
                       (default: ~/.config/BambuStudio/system/BBL)
  BAMBU_MACHINE        machine preset name
                       (default: "Bambu Lab P2S 0.4 nozzle")
  BAMBU_PROCESS        process preset name
                       (default: "0.20mm Standard @BBL P2S")
  BAMBU_FILAMENT       filament preset name
                       (default: "Bambu PLA Basic @BBL P2S")
"""
from __future__ import annotations

import asyncio
import ftplib
import json
import os
import re
import signal
import socket
import ssl
import sys
import tempfile
import time
from contextlib import suppress
from ftplib import FTP_TLS
from pathlib import Path

from aiohttp import web
import paho.mqtt.client as mqtt


def _required(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        sys.exit(f"bambu-bridge: missing required env var {name}")
    return v


IP = _required("BAMBU_IP")
SERIAL = _required("BAMBU_SERIAL")
CODE = _required("BAMBU_ACCESS_CODE")
SOCK = Path(_required("BAMBU_BRIDGE_SOCK"))

BBL_SYS = Path(
    os.environ.get("BAMBU_BBL_SYS_DIR", str(Path.home() / ".config/BambuStudio/system/BBL"))
)
MACHINE = os.environ.get("BAMBU_MACHINE", "Bambu Lab P2S 0.4 nozzle")
PROCESS = os.environ.get("BAMBU_PROCESS", "0.20mm Standard @BBL P2S")
FILAMENT = os.environ.get("BAMBU_FILAMENT", "Bambu PLA Basic @BBL P2S")
# CRITICAL: must match the plate physically installed on the printer.
# Bambu refuses to start if the sliced bed_type and the report's
# `plate.base` disagree. Default matches P2S code 4 (Textured PEI).
# Override per-machine via env.
BED_TYPE = os.environ.get("BAMBU_BED_TYPE", "Textured PEI Plate")

REPO_ROOT = Path(__file__).resolve().parents[2]
STL_DIR = REPO_ROOT / "code/web/public/models/cad"

REPORT_TOPIC = f"device/{SERIAL}/report"
REQUEST_TOPIC = f"device/{SERIAL}/request"

# Whitelist for board names to keep /print free of path-traversal: same
# shape as our CAD spec names (snake_case alphanumeric).
_BOARD_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_]{0,63}$")

# Single active print-job slot. The bridge orchestrates one job at a
# time end-to-end (slice + upload + MQTT start). Once started, MQTT
# pushes take over and the gallery's existing /printer page reflects
# live print state — this slot only tracks the *bridge-side* phases.
state: dict = {
    "connected": False,
    "last_update": None,
    "last_error": None,
    "print": {},
    "job": {
        "running": False,
        "board": None,
        "phase": None,        # slicing → uploading → starting → started | failed
        "phases_seen": [],
        "started_at": None,
        "completed_at": None,
        "error": None,
    },
}

# H-platform printers (P2S/H2D/H2C/H2S) expose the camera as RTSPS on
# port 322 — the legacy port-6000 MJPEG-with-custom-handshake used by
# P1/A1 doesn't apply. ffmpeg pulls H.264 from RTSPS and transcodes to
# MJPEG on stdout; the reader task slices into JPEG frames and caches
# the latest one. The /camera/stream.mjpg endpoint fans frames out to N
# browser tabs from this one cached buffer.
camera: dict = {
    "running": False,
    "started_at": None,
    "process": None,         # asyncio.subprocess.Process
    "reader_task": None,
    "latest_jpeg": None,
    "latest_at": None,
    "error": None,
    "subscribers": 0,
}
camera_lock = asyncio.Lock()


# ---------------------------------------------------------------------------
# MQTT
# ---------------------------------------------------------------------------

def _on_connect(client, userdata, flags, rc, properties=None):
    rc_val = getattr(rc, "value", rc)
    state["connected"] = rc_val == 0
    if state["connected"]:
        client.subscribe(REPORT_TOPIC)
        client.publish(
            REQUEST_TOPIC,
            json.dumps({"pushing": {"sequence_id": "0", "command": "pushall"}}),
        )


def _on_disconnect(client, userdata, *args):
    state["connected"] = False


def _on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
    except Exception as exc:
        state["last_error"] = f"decode: {exc}"
        return
    p = payload.get("print")
    if isinstance(p, dict):
        state["print"].update(p)
        state["last_update"] = time.time()


def start_mqtt() -> mqtt.Client:
    c = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"bambu-bridge-{os.getpid()}",
    )
    c.username_pw_set("bblp", CODE)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    c.tls_set_context(ctx)
    c.tls_insecure_set(True)
    c.on_connect = _on_connect
    c.on_disconnect = _on_disconnect
    c.on_message = _on_message
    c.reconnect_delay_set(min_delay=2, max_delay=60)
    c.connect_async(IP, 8883, keepalive=30)
    c.loop_start()
    return c


# ---------------------------------------------------------------------------
# FTPS upload — Bambu uses implicit TLS on port 990 and requires the data
# channel's TLS session to be resumed from the control channel.
# ---------------------------------------------------------------------------

class ImplicitFTPS(FTP_TLS):
    def connect(self, host="", port=0, timeout=-999, source_address=None):
        if host:
            self.host = host
        if port:
            self.port = port
        if timeout != -999:
            self.timeout = timeout
        if source_address is not None:
            self.source_address = source_address
        sock = socket.create_connection(
            (self.host, self.port), self.timeout,
            source_address=self.source_address,
        )
        self.af = sock.family
        self.sock = self.context.wrap_socket(sock, server_hostname=self.host)
        self.file = self.sock.makefile("r", encoding=self.encoding)
        self.welcome = self.getresp()
        return self.welcome

    def ntransfercmd(self, cmd, rest=None):
        conn, size = ftplib.FTP.ntransfercmd(self, cmd, rest)
        if self._prot_p:
            # CRITICAL: data-channel TLS must resume the control session
            # or the printer rejects with `522 SSL session reuse required`.
            conn = self.context.wrap_socket(
                conn, server_hostname=self.host, session=self.sock.session,
            )
        return conn, size


def _upload_ftps(local: Path, remote_name: str) -> None:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ftp = ImplicitFTPS(context=ctx)
    ftp.encoding = "utf-8"
    ftp.connect(IP, 990, timeout=15)
    try:
        ftp.login("bblp", CODE)
        ftp.prot_p()
        with local.open("rb") as f:
            ftp.storbinary(f"STOR {remote_name}", f)
    finally:
        with suppress(Exception):
            ftp.quit()


# ---------------------------------------------------------------------------
# Print job orchestration
# ---------------------------------------------------------------------------

def _phase(name: str) -> None:
    job = state["job"]
    job["phase"] = name
    job["phases_seen"].append(name)


async def _run_print_job(client: mqtt.Client, board: str) -> None:
    job = state["job"]
    job["error"] = None
    job["phases_seen"] = []
    job["started_at"] = time.time()
    job["completed_at"] = None
    _phase("slicing")

    try:
        stl = STL_DIR / f"{board}.stl"
        if not stl.is_file():
            raise FileNotFoundError(f"STL not found: {stl}")

        machine_json = BBL_SYS / "machine" / f"{MACHINE}.json"
        process_json = BBL_SYS / "process" / f"{PROCESS}.json"
        filament_json = BBL_SYS / "filament" / f"{FILAMENT}.json"
        for p in (machine_json, process_json, filament_json):
            if not p.is_file():
                raise FileNotFoundError(f"profile not found: {p}")

        with tempfile.TemporaryDirectory(prefix="bambu-print-") as tmp:
            tmp_path = Path(tmp)
            three_mf_name = f"{board}.gcode.3mf"

            # Bambu Studio CLI rejects generic `--<setting>` overrides
            # ("setup params error"), so to control bed type we write a
            # copy of the process JSON with curr_bed_type injected and
            # hand the slicer that. Inheritance still resolves through
            # the system dir; we're only overriding the leaf.
            process_override = tmp_path / "process_override.json"
            process_data = json.loads(process_json.read_text())
            process_data["curr_bed_type"] = BED_TYPE
            process_override.write_text(json.dumps(process_data))

            cmd = [
                "bambu-studio",
                "--load-settings", f"{machine_json};{process_override}",
                "--load-filaments", str(filament_json),
                "--slice", "0",
                "--export-3mf", three_mf_name,
                "--outputdir", str(tmp_path),
                str(stl),
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await proc.communicate()
            three_mf = tmp_path / three_mf_name
            # bambu-studio CLI logs non-fatal errors to stderr (glfwInit,
            # nozzle_volume_type) but still produces the 3MF — trust the
            # file existing as the real success signal.
            if not three_mf.is_file():
                tail = stdout.decode(errors="replace")[-800:]
                raise RuntimeError(f"slice produced no 3MF (rc={proc.returncode}):\n{tail}")

            _phase("uploading")
            # FTPS is blocking; off-load to a thread so the event loop
            # stays free to serve /status polling.
            await asyncio.to_thread(_upload_ftps, three_mf, three_mf_name)

            _phase("starting")
            cmd_payload = {
                "print": {
                    "sequence_id": str(int(time.time())),
                    "command": "project_file",
                    "param": "Metadata/plate_1.gcode",
                    "url": f"ftp:///{three_mf_name}",
                    "subtask_name": board,
                    "use_ams": False,
                    "timelapse": False,
                    "bed_leveling": True,
                    "flow_cali": False,
                    "vibration_cali": False,
                    "layer_inspect": False,
                }
            }
            client.publish(REQUEST_TOPIC, json.dumps(cmd_payload), qos=1)
            _phase("started")

    except Exception as exc:
        job["error"] = f"{type(exc).__name__}: {exc}"
        _phase("failed")
    finally:
        job["completed_at"] = time.time()
        job["running"] = False


# ---------------------------------------------------------------------------
# HTTP handlers (Unix-domain only)
# ---------------------------------------------------------------------------

async def _status(request: web.Request) -> web.Response:
    now = time.time()
    return web.json_response({
        "connected": state["connected"],
        "last_update": state["last_update"],
        "stale_seconds": (
            now - state["last_update"] if state["last_update"] is not None else None
        ),
        "last_error": state["last_error"],
        "print": state["print"],
        "job": state["job"],
    })


async def _health(request: web.Request) -> web.Response:
    return web.Response(text="ok\n")


async def _start_print(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "bad_json"}, status=400)
    board = (body.get("board") or "").strip()
    if not _BOARD_RE.match(board):
        return web.json_response(
            {"error": "bad_board", "detail": "alphanumeric + underscore only"},
            status=400,
        )
    if state["job"]["running"]:
        return web.json_response(
            {"error": "already_running", "phase": state["job"]["phase"], "board": state["job"]["board"]},
            status=409,
        )
    state["job"]["running"] = True
    state["job"]["board"] = board
    state["job"]["phase"] = "queued"
    state["job"]["phases_seen"] = ["queued"]
    state["job"]["error"] = None

    client = request.app["mqtt"]
    asyncio.create_task(_run_print_job(client, board))
    return web.json_response({"status": "queued", "board": board})


async def _job_status(request: web.Request) -> web.Response:
    return web.json_response(state["job"])


# ---------------------------------------------------------------------------
# Printer control (MQTT command publish)
# ---------------------------------------------------------------------------

_PRINT_COMMANDS = {"stop", "pause", "resume"}
_LIGHT_NODES = {"chamber_light", "work_light"}
_LIGHT_MODES = {"on", "off", "flashing"}


def _seq() -> str:
    return str(int(time.time() * 1000))


async def _control_print(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "bad_json"}, status=400)
    cmd = body.get("command")
    if cmd not in _PRINT_COMMANDS:
        return web.json_response(
            {"error": "bad_command", "allowed": sorted(_PRINT_COMMANDS)},
            status=400,
        )
    payload = {"print": {"sequence_id": _seq(), "command": cmd}}
    request.app["mqtt"].publish(REQUEST_TOPIC, json.dumps(payload), qos=1)
    return web.json_response({"status": "sent", "command": cmd})


async def _control_light(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "bad_json"}, status=400)
    node = body.get("node")
    mode = body.get("mode")
    if node not in _LIGHT_NODES:
        return web.json_response(
            {"error": "bad_node", "allowed": sorted(_LIGHT_NODES)},
            status=400,
        )
    if mode not in _LIGHT_MODES:
        return web.json_response(
            {"error": "bad_mode", "allowed": sorted(_LIGHT_MODES)},
            status=400,
        )
    payload = {
        "system": {
            "sequence_id": _seq(),
            "command": "ledctrl",
            "led_node": node,
            "led_mode": mode,
            "led_on_time": 500,
            "led_off_time": 500,
            "loop_times": 0,
            "interval_time": 0,
        }
    }
    request.app["mqtt"].publish(REQUEST_TOPIC, json.dumps(payload), qos=1)
    return web.json_response({"status": "sent", "node": node, "mode": mode})


# ---------------------------------------------------------------------------
# Camera (RTSPS → MJPEG fan-out via ffmpeg)
# ---------------------------------------------------------------------------

def _camera_cmd() -> list[str]:
    # SECURITY: the access code rides in the URL — visible to the user
    # owning this process (and root). Bridge runs as the same user; the
    # process list isn't browser-reachable. Acceptable for dev.
    url = f"rtsps://bblp:{CODE}@{IP}:322/streaming/live/1"
    return [
        "ffmpeg",
        "-hide_banner", "-loglevel", "error",
        "-rtsp_transport", "tcp",
        "-i", url,
        "-f", "mjpeg",
        "-q:v", "5",
        "-r", "5",
        "pipe:1",
    ]


async def _camera_reader(proc: asyncio.subprocess.Process) -> None:
    """Slice ffmpeg's MJPEG stdout into individual JPEG frames.

    MJPEG over a pipe is just concatenated JPEGs; we split on the SOI
    (`FF D8`) → EOI (`FF D9`) markers. Each completed frame replaces
    `camera["latest_jpeg"]`; the stream/snapshot endpoints serve from
    that single cache.
    """
    buf = bytearray()
    try:
        while True:
            chunk = await proc.stdout.read(65536)
            if not chunk:
                break
            buf.extend(chunk)
            while True:
                soi = buf.find(b"\xff\xd8")
                if soi < 0:
                    buf.clear()
                    break
                eoi = buf.find(b"\xff\xd9", soi + 2)
                if eoi < 0:
                    if soi > 0:
                        del buf[:soi]  # discard pre-SOI garbage
                    break  # need more bytes for EOI
                frame = bytes(buf[soi:eoi + 2])
                del buf[:eoi + 2]
                camera["latest_jpeg"] = frame
                camera["latest_at"] = time.time()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        camera["error"] = f"reader: {type(exc).__name__}: {exc}"


async def _camera_teardown() -> None:
    proc = camera["process"]
    if proc is not None:
        with suppress(ProcessLookupError):
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=3)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
    task = camera["reader_task"]
    if task is not None and not task.done():
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    camera["process"] = None
    camera["reader_task"] = None
    camera["running"] = False
    camera["latest_jpeg"] = None
    camera["latest_at"] = None


async def _camera_start(request: web.Request) -> web.Response:
    async with camera_lock:
        if camera["running"]:
            return web.json_response({"status": "already_running"})
        camera["error"] = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *_camera_cmd(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            return web.json_response(
                {"error": "ffmpeg_missing", "detail": "ffmpeg not on PATH"},
                status=500,
            )
        camera["process"] = proc
        camera["started_at"] = time.time()
        camera["running"] = True
        camera["reader_task"] = asyncio.create_task(_camera_reader(proc))
        return web.json_response({"status": "started"})


async def _camera_stop(request: web.Request) -> web.Response:
    async with camera_lock:
        if not camera["running"]:
            return web.json_response({"status": "not_running"})
        await _camera_teardown()
        return web.json_response({"status": "stopped"})


async def _camera_status(request: web.Request) -> web.Response:
    now = time.time()
    return web.json_response({
        "running": camera["running"],
        "started_at": camera["started_at"],
        "frame_age": (
            now - camera["latest_at"] if camera["latest_at"] is not None else None
        ),
        "error": camera["error"],
        "subscribers": camera["subscribers"],
    })


async def _camera_snapshot(request: web.Request) -> web.Response:
    frame = camera["latest_jpeg"]
    if frame is None:
        return web.json_response(
            {"error": "no_frame", "running": camera["running"]},
            status=503,
        )
    return web.Response(
        body=frame,
        content_type="image/jpeg",
        headers={"cache-control": "no-store"},
    )


async def _camera_stream(request: web.Request) -> web.StreamResponse:
    if not camera["running"]:
        return web.json_response({"error": "camera_off"}, status=409)
    boundary = "bambuframe"
    response = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": f"multipart/x-mixed-replace; boundary={boundary}",
            "Cache-Control": "no-store",
        },
    )
    await response.prepare(request)
    camera["subscribers"] += 1
    last_at = 0.0
    try:
        # Wait for at least one frame so the browser doesn't render a
        # broken-image icon while ffmpeg is warming up the connection.
        deadline = time.time() + 5
        while camera["running"] and camera["latest_at"] is None and time.time() < deadline:
            await asyncio.sleep(0.05)
        while camera["running"]:
            at = camera["latest_at"]
            if at and at != last_at:
                frame = camera["latest_jpeg"]
                if frame is not None:
                    part = (
                        f"--{boundary}\r\n"
                        f"Content-Type: image/jpeg\r\n"
                        f"Content-Length: {len(frame)}\r\n\r\n"
                    ).encode() + frame + b"\r\n"
                    try:
                        await response.write(part)
                    except (ConnectionResetError, asyncio.CancelledError):
                        break
                    last_at = at
            await asyncio.sleep(0.1)  # ~10 fps wall ceiling
    finally:
        camera["subscribers"] -= 1
    return response


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

async def main() -> None:
    SOCK.parent.mkdir(parents=True, exist_ok=True)
    with suppress(FileNotFoundError):
        SOCK.unlink()

    client = start_mqtt()

    app = web.Application()
    app["mqtt"] = client
    app.router.add_get("/status.json", _status)
    app.router.add_get("/health", _health)
    app.router.add_post("/print", _start_print)
    app.router.add_get("/print/status", _job_status)
    app.router.add_post("/camera/start", _camera_start)
    app.router.add_post("/camera/stop", _camera_stop)
    app.router.add_get("/camera/status", _camera_status)
    app.router.add_get("/camera/snapshot.jpg", _camera_snapshot)
    app.router.add_get("/camera/stream.mjpg", _camera_stream)
    app.router.add_post("/control/print", _control_print)
    app.router.add_post("/control/light", _control_light)

    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.UnixSite(runner, str(SOCK))
    await site.start()
    # SECURITY: socket is fs-permission gated — owner-only.
    os.chmod(SOCK, 0o600)
    print(f"bambu-bridge: listening on {SOCK}", flush=True)
    print(f"bambu-bridge: mqtt target {IP}:8883 (serial {SERIAL})", flush=True)
    print(f"bambu-bridge: slicer profile {MACHINE} / {PROCESS} / {FILAMENT}", flush=True)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    try:
        await stop.wait()
    finally:
        await _camera_teardown()
        await runner.cleanup()
        client.loop_stop()
        client.disconnect()
        with suppress(FileNotFoundError):
            SOCK.unlink()


if __name__ == "__main__":
    asyncio.run(main())
