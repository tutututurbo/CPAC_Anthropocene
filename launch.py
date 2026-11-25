#!/usr/bin/env python3
"""
ANTHROPOCENE - launcher

Starts the whole installation in the right order:

  1. SuperCollider  -> Sounds/GranularReceiver.scd  (audio engine, OSC :57120)
  2. QLC+           -> BRIDGE QLC-TD.qxw            (DMX lighting, Art-Net in)
  3. TouchDesigner  -> TouchDesigner/AnthropoceneCPAC.toe (visuals, OSC :12000)
  4. Python         -> Python/detection_controller.py (YOLO camera tracking,
                       sends /entropy_level + /coord, Syphon video out)

Usage:
  python3 launch.py --setup     # first time: create .venv and install deps
  python3 launch.py --check     # only verify apps / files / deps
  python3 launch.py             # launch everything
  python3 launch.py --skip qlc,td --ip 192.168.1.20

Ctrl+C (or pressing 'q' in the camera window) stops the managed processes.
Only stdlib is used here, so the launcher runs with any Python 3.8+.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"
REQUIREMENTS = ROOT / "Python" / "requirements.txt"

SC_SCRIPT = ROOT / "Sounds" / "GranularReceiver.scd"
SC_LAYERS = ROOT / "Sounds" / "Layers"
QLC_WORKSPACE = ROOT / "BRIDGE QLC-TD.qxw"
TD_DIR = ROOT / "TouchDesigner"
TD_DEFAULT_TOE = TD_DIR / "AnthropoceneCPAC.toe"
DETECTION_DIR = ROOT / "Python"
DETECTION_SCRIPT = DETECTION_DIR / "detection_controller.py"
YOLO_MODEL = DETECTION_DIR / "yolov8n-seg.pt"

SC_READY_MARKER = "SISTEMA CLOUD PRONTO"
SC_PORT = 57120
TD_PORT = 12000

# Python versions to try for the venv, newest first. torch/ultralytics
# wheels usually lag behind the newest CPython, so 3.14 is tried last.
VENV_PYTHONS = ["python3.13", "python3.12", "python3.11", "python3.10", "python3.14", "python3"]

IS_MAC = platform.system() == "Darwin"

# --------------------------------------------------------------------------- #
# Console helpers
# --------------------------------------------------------------------------- #
_USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
_COLORS = {"SC": "35", "QLC": "33", "TD": "36", "DET": "32", "LAUNCH": "1;37"}


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _USE_COLOR else text


def log(tag: str, msg: str) -> None:
    print(f"{_c(_COLORS.get(tag, '0'), f'[{tag:^6}]')} {msg}", flush=True)


def ok(msg: str) -> None:
    log("LAUNCH", _c("32", "OK   ") + msg)


def warn(msg: str) -> None:
    log("LAUNCH", _c("33", "WARN ") + msg)


def fail(msg: str) -> None:
    log("LAUNCH", _c("31", "FAIL ") + msg)


# --------------------------------------------------------------------------- #
# App discovery
# --------------------------------------------------------------------------- #
def _mdfind_app(app_name: str) -> Path | None:
    """Ask Spotlight for an .app bundle with this exact name."""
    if not IS_MAC or not shutil.which("mdfind"):
        return None
    try:
        out = subprocess.run(
            ["mdfind", f"kMDItemFSName == '{app_name}'"],
            capture_output=True, text=True, timeout=10,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return None
    for line in out.splitlines():
        p = Path(line.strip())
        if p.suffix == ".app" and p.is_dir() and "/Trash/" not in line:
            return p
    return None


def find_app(app_name: str, override: str | None, env_var: str) -> Path | None:
    for cand in (override, os.environ.get(env_var)):
        if cand:
            p = Path(cand).expanduser()
            return p if p.exists() else None
    for base in (Path("/Applications"), Path.home() / "Applications"):
        p = base / app_name
        if p.is_dir():
            return p
    return _mdfind_app(app_name)


def find_sclang(sc_app: Path | None) -> Path | None:
    if sc_app:
        p = sc_app / "Contents" / "MacOS" / "sclang"
        if p.exists():
            return p
    w = shutil.which("sclang")
    return Path(w) if w else None


def find_qlc_binary(qlc_app: Path | None) -> Path | None:
    if not qlc_app:
        w = shutil.which("qlcplus") or shutil.which("qlcplus-qml")
        return Path(w) if w else None
    macos = qlc_app / "Contents" / "MacOS"
    for name in ("qlcplus", "qlcplus-qml"):
        if (macos / name).exists():
            return macos / name
    return None


# --------------------------------------------------------------------------- #
# Python environment for the detection controller
# --------------------------------------------------------------------------- #
def venv_python() -> Path:
    return VENV_DIR / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def detection_python(override: str | None) -> Path:
    if override:
        return Path(override).expanduser()
    vp = venv_python()
    return vp if vp.exists() else Path(sys.executable)


def check_python_deps(py: Path) -> tuple[bool, str]:
    code = (
        "import importlib.util as u, sys\n"
        "mods=['cv2','numpy','ultralytics','pythonosc']\n"
        "miss=[m for m in mods if u.find_spec(m) is None]\n"
        "opt=[m for m in ['syphon','Metal'] if u.find_spec(m) is None]\n"
        "print(','.join(miss)+'|'+','.join(opt))\n"
    )
    try:
        out = subprocess.run([str(py), "-c", code], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"cannot run {py}: {e}"
    if out.returncode != 0:
        return False, out.stderr.strip().splitlines()[-1] if out.stderr else "unknown error"
    missing, optional = (out.stdout.strip().split("|") + [""])[:2]
    if missing:
        return False, f"missing modules: {missing}  (run: python3 launch.py --setup)"
    if optional and IS_MAC:
        return True, f"Syphon not available ({optional}) -> no video to TouchDesigner"
    return True, ""


def setup_venv() -> int:
    base = next((shutil.which(p) for p in VENV_PYTHONS if shutil.which(p)), None)
    if not base:
        fail("no python3 interpreter found to build the venv")
        return 1
    if not venv_python().exists():
        log("LAUNCH", f"Creating venv in {VENV_DIR} with {base}")
        r = subprocess.run([base, "-m", "venv", str(VENV_DIR)])
        if r.returncode != 0:
            fail("venv creation failed")
            return r.returncode
    py = str(venv_python())
    log("LAUNCH", "Installing Python dependencies (ultralytics pulls torch: may take a while)")
    subprocess.run([py, "-m", "pip", "install", "--upgrade", "pip"])
    r = subprocess.run([py, "-m", "pip", "install", "-r", str(REQUIREMENTS)])
    if r.returncode != 0:
        fail("pip install failed (see output above)")
        return r.returncode
    ok(f"venv ready: {py}")
    return 0


# --------------------------------------------------------------------------- #
# Misc checks
# --------------------------------------------------------------------------- #
def udp_port_busy(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind(("127.0.0.1", port))
        return False
    except OSError:
        return True
    finally:
        s.close()


def pids_of(name: str) -> set[int]:
    if not shutil.which("pgrep"):
        return set()
    out = subprocess.run(["pgrep", "-x", name], capture_output=True, text=True).stdout
    return {int(x) for x in out.split()}


def process_running(name: str) -> bool:
    return bool(pids_of(name))


# --------------------------------------------------------------------------- #
# Launcher
# --------------------------------------------------------------------------- #
class Launcher:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.skip = {s.strip().lower() for s in (args.skip or "").split(",") if s.strip()}
        self.procs: dict[str, subprocess.Popen] = {}
        self.stopping = threading.Event()
        self.sc_ready = threading.Event()
        self.scsynth_before: set[int] = set()

        self.sc_app = find_app("SuperCollider.app", args.sc_app, "SC_APP")
        self.sclang = find_sclang(self.sc_app)
        self.qlc_app = find_app("QLC+.app", args.qlc_app, "QLC_APP")
        self.qlc_bin = find_qlc_binary(self.qlc_app)
        self.td_app = find_app("TouchDesigner.app", args.td_app, "TD_APP")
        self.toe = Path(args.toe).expanduser().resolve() if args.toe else TD_DEFAULT_TOE
        self.py = detection_python(args.python)

    # ---------------- checks ---------------- #
    def preflight(self) -> bool:
        good = True
        log("LAUNCH", "Pre-flight checks")

        if "sc" not in self.skip:
            if not SC_SCRIPT.exists():
                fail(f"missing {SC_SCRIPT}"); good = False
            if not SC_LAYERS.is_dir():
                warn(f"missing {SC_LAYERS} (SuperCollider will have no sound)")
            if self.args.sc_ide:
                if self.sc_app: ok(f"SuperCollider IDE: {self.sc_app}")
                else: fail("SuperCollider.app not found (use --sc-app)"); good = False
            elif self.sclang:
                ok(f"sclang: {self.sclang}")
            else:
                fail("sclang not found (install SuperCollider or use --sc-app)"); good = False
            if udp_port_busy(SC_PORT):
                warn(f"UDP {SC_PORT} already in use: another sclang is probably running")

        if "qlc" not in self.skip:
            if not QLC_WORKSPACE.exists():
                fail(f"missing {QLC_WORKSPACE}"); good = False
            if self.qlc_bin: ok(f"QLC+: {self.qlc_bin}")
            else: fail("QLC+ not found (use --qlc-app or --skip qlc)"); good = False

        if "td" not in self.skip:
            if not self.toe.exists():
                fail(f"missing {self.toe}"); good = False
            else:
                ok(f"TouchDesigner project: {self.toe.relative_to(ROOT) if ROOT in self.toe.parents else self.toe}")
            if self.td_app: ok(f"TouchDesigner: {self.td_app}")
            else: fail("TouchDesigner.app not found (use --td-app or TD_APP=...)"); good = False

        if "detection" not in self.skip:
            if not DETECTION_SCRIPT.exists():
                fail(f"missing {DETECTION_SCRIPT}"); good = False
            if not YOLO_MODEL.exists():
                warn(f"{YOLO_MODEL.name} not in Python/: ultralytics will try to download it")
            deps_ok, msg = check_python_deps(self.py)
            if deps_ok:
                ok(f"detection Python: {self.py}")
                if msg: warn(msg)
            else:
                fail(f"detection Python {self.py}: {msg}"); good = False
            if udp_port_busy(TD_PORT) and "td" in self.skip:
                pass  # TD already running elsewhere: fine
        return good

    # ---------------- process plumbing ---------------- #
    def _pump(self, tag: str, stream, on_line=None) -> None:
        for raw in iter(stream.readline, ""):
            line = raw.rstrip()
            if line:
                log(tag, line)
                if on_line:
                    on_line(line)
        stream.close()

    def _spawn(self, tag: str, cmd: list[str], cwd: Path, on_line=None, stdin=None, quiet=False):
        log("LAUNCH", f"{tag}: {' '.join(cmd)}")
        p = subprocess.Popen(
            cmd, cwd=str(cwd),
            stdin=stdin if stdin is not None else subprocess.DEVNULL,
            stdout=subprocess.DEVNULL if quiet else subprocess.PIPE,
            stderr=subprocess.DEVNULL if quiet else subprocess.STDOUT,
            text=True, bufsize=1,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
            start_new_session=True,  # Ctrl+C is handled by us, not forwarded raw
        )
        if not quiet:
            threading.Thread(target=self._pump, args=(tag, p.stdout, on_line), daemon=True).start()
        self.procs[tag] = p
        return p

    # ---------------- components ---------------- #
    def start_supercollider(self) -> None:
        if self.args.sc_ide:
            # Opens the file in the IDE: the user must evaluate it (Cmd+A, Cmd+Enter).
            subprocess.run(["open", "-a", str(self.sc_app), str(SC_SCRIPT)])
            warn("SuperCollider IDE opened: select all and press Cmd+Enter to start the engine")
            return

        def on_line(line: str) -> None:
            if SC_READY_MARKER in line:
                self.sc_ready.set()

        # scsynth is spawned by sclang (and survives it): remember which ones
        # existed before, so on shutdown we only kill the one we caused.
        self.scsynth_before = pids_of("scsynth")
        # stdin kept open: sclang quits on EOF.
        self._spawn("SC", [str(self.sclang), str(SC_SCRIPT)], SC_SCRIPT.parent,
                    on_line=on_line, stdin=subprocess.PIPE)
        log("LAUNCH", f"waiting for SuperCollider (max {self.args.sc_timeout}s)...")
        deadline = time.monotonic() + self.args.sc_timeout
        while not (self.sc_ready.is_set() or self.stopping.is_set()) and time.monotonic() < deadline:
            self.sc_ready.wait(0.2)
        if self.sc_ready.is_set():
            ok("SuperCollider audio engine ready")
        elif not self.stopping.is_set():
            warn("SuperCollider ready message not seen, continuing anyway")

    def start_qlc(self) -> None:
        if process_running(self.qlc_bin.name):
            warn("QLC+ already running: not starting a second instance")
            return
        cmd = [str(self.qlc_bin), "--open", str(QLC_WORKSPACE)]
        if self.args.qlc_kiosk:
            cmd.append("--kiosk")
        self._spawn("QLC", cmd, ROOT, quiet=not self.args.verbose)
        time.sleep(2)
        ok("QLC+ started (check Art-Net input on 127.0.0.1 and DMX USB output)")

    def start_touchdesigner(self) -> None:
        # Same as double clicking the .toe: TouchDesigner opens the project.
        subprocess.run(["open", "-a", str(self.td_app), str(self.toe)], check=False)
        log("LAUNCH", f"TouchDesigner opening, waiting {self.args.td_wait}s for it to load...")
        self._sleep(self.args.td_wait)
        ok("TouchDesigner launched")

    def start_detection(self) -> None:
        cmd = [str(self.py), str(DETECTION_SCRIPT), "--ip", self.args.ip]
        self._spawn("DET", cmd, DETECTION_DIR)
        if IS_MAC:
            log("LAUNCH", "first run: macOS may ask Camera permission for your terminal app")

    # ---------------- lifecycle ---------------- #
    def _sleep(self, seconds: float) -> None:
        self.stopping.wait(seconds)

    def run(self) -> int:
        if not self.preflight():
            fail("pre-flight failed: fix the errors above or use --skip")
            return 1
        if self.args.check:
            ok("all checks passed")
            return 0

        signal.signal(signal.SIGINT, lambda *_: self.stopping.set())
        signal.signal(signal.SIGTERM, lambda *_: self.stopping.set())

        steps = [
            ("sc", self.start_supercollider),
            ("qlc", self.start_qlc),
            ("td", self.start_touchdesigner),
            ("detection", self.start_detection),
        ]
        try:
            for key, fn in steps:
                if self.stopping.is_set():
                    break
                if key in self.skip:
                    log("LAUNCH", f"skipping {key}")
                    continue
                fn()

            if not self.stopping.is_set():
                ok("ANTHROPOCENE running. Ctrl+C to stop.")
            self._watch()
        finally:
            self.shutdown()
        return 0

    def _watch(self) -> None:
        """Wait until Ctrl+C or until a critical process dies."""
        while not self.stopping.is_set():
            for tag in ("DET", "SC"):
                p = self.procs.get(tag)
                if p and p.poll() is not None:
                    warn(f"{tag} exited (code {p.returncode}): stopping everything")
                    self.stopping.set()
                    break
            self._sleep(0.5)

    def shutdown(self) -> None:
        log("LAUNCH", "shutting down...")
        det = self.procs.get("DET")
        if det and det.poll() is None:
            det.terminate()

        sc = self.procs.get("SC")
        if sc and sc.poll() is None:
            sc.terminate()

        qlc = self.procs.get("QLC")
        if qlc and qlc.poll() is None and self.args.close_apps:
            qlc.terminate()

        for tag, p in self.procs.items():
            if tag == "QLC" and not self.args.close_apps:
                continue
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                warn(f"{tag} not responding, killing")
                p.kill()

        if sc:
            for pid in pids_of("scsynth") - self.scsynth_before:
                try:
                    os.kill(pid, signal.SIGTERM)
                except OSError:
                    pass

        if self.args.close_apps and "td" not in self.skip and IS_MAC:
            subprocess.run(["osascript", "-e", 'quit app "TouchDesigner"'], check=False)
        elif "td" not in self.skip or "qlc" not in self.skip:
            log("LAUNCH", "TouchDesigner / QLC+ left open (use --close-apps to quit them too)")
        ok("bye")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Launch the ANTHROPOCENE installation.")
    p.add_argument("--setup", action="store_true", help="create .venv and install Python deps, then exit")
    p.add_argument("--check", action="store_true", help="only run pre-flight checks")
    p.add_argument("--skip", default="", help="comma list of components to skip: sc,qlc,td,detection")
    p.add_argument("--ip", default="127.0.0.1", help="OSC target IP for the detection controller")
    p.add_argument("--toe", help=f"TouchDesigner project (default {TD_DEFAULT_TOE.relative_to(ROOT)})")
    p.add_argument("--td-wait", type=float, default=15, help="seconds to wait for TouchDesigner to load")
    p.add_argument("--sc-timeout", type=float, default=30, help="max seconds to wait for SuperCollider")
    p.add_argument("--sc-ide", action="store_true", help="open .scd in the SuperCollider IDE instead of running sclang")
    p.add_argument("--qlc-kiosk", action="store_true", help="start QLC+ in kiosk mode (Virtual Console only)")
    p.add_argument("--close-apps", action="store_true", help="on exit also quit TouchDesigner and QLC+")
    p.add_argument("--python", help="Python interpreter for detection_controller.py (default .venv or current)")
    p.add_argument("--td-app", help="path to TouchDesigner.app (or env TD_APP)")
    p.add_argument("--sc-app", help="path to SuperCollider.app (or env SC_APP)")
    p.add_argument("--qlc-app", help="path to QLC+.app (or env QLC_APP)")
    p.add_argument("-v", "--verbose", action="store_true", help="show QLC+ output too")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.setup:
        return setup_venv()
    if not IS_MAC:
        warn("launcher written for macOS (Syphon, open -a); other OS may need --*-app paths")
    return Launcher(args).run()


if __name__ == "__main__":
    sys.exit(main())
