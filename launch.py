#!/usr/bin/env python3
"""
ANTHROPOCENE - launcher (Windows + macOS)

Starts the whole installation in the right order:

  1. SuperCollider  -> Sounds/GranularReceiver.scd  (audio engine, OSC :57120)
  2. QLC+           -> BRIDGE QLC-TD.qxw            (DMX lighting, Art-Net in)
  3. TouchDesigner  -> TouchDesigner/AnthropoceneCPAC.toe (visuals, OSC :12000)
  4. Python         -> detection controller (YOLO camera tracking,
                       sends /entropy_level + /coord, video out via
                       Spout on Windows / Syphon on macOS)

Usage:
  python launch.py --setup     # first time: create .venv and install deps
  python launch.py --check     # only verify apps / files / deps
  python launch.py             # launch everything
  python launch.py --skip qlc,td --ip 192.168.1.20

Ctrl+C (or pressing 'q' in the camera window) stops the managed processes.
Only stdlib is used here, so the launcher runs with any Python 3.8+.
"""

from __future__ import annotations

import argparse
import csv
import glob
import io
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

IS_MAC = platform.system() == "Darwin"
IS_WIN = os.name == "nt"

if IS_WIN:
    os.system("")  # enables ANSI colour codes in the Windows console
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(errors="replace")  # never crash on emoji / accents
        except Exception:
            pass

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"
REQUIREMENTS = ROOT / "Python" / "requirements.txt"

SC_SCRIPT = ROOT / "Sounds" / "GranularReceiver.scd"
SC_LAYERS = ROOT / "Sounds" / "Layers"
QLC_WORKSPACE = ROOT / "BRIDGE QLC-TD.qxw"
TD_DIR = ROOT / "TouchDesigner"
TD_DEFAULT_TOE = TD_DIR / "AnthropoceneCPAC.toe"
DETECTION_DIR = ROOT / "Python"
DETECTION_SCRIPT = DETECTION_DIR / ("detection_controller_win.py" if IS_WIN else "detection_controller.py")
YOLO_MODEL = DETECTION_DIR / "yolov8n-seg.pt"

SC_READY_MARKER = "SISTEMA CLOUD PRONTO"
SC_PORT = 57120
TD_PORT = 12000

# Video bridge to TouchDesigner: import names (to check) and pip names (to install).
if IS_WIN:
    VIDEO_MODULES, VIDEO_PACKAGES, VIDEO_NAME = ["SpoutGL", "OpenGL"], ["SpoutGL", "PyOpenGL"], "Spout"
elif IS_MAC:
    VIDEO_MODULES, VIDEO_PACKAGES, VIDEO_NAME = ["syphon", "Metal"], [], "Syphon"
else:
    VIDEO_MODULES, VIDEO_PACKAGES, VIDEO_NAME = [], [], ""
# requirements.txt lines that only install on macOS (skipped elsewhere unless they carry a marker)
MAC_ONLY_PREFIXES = ("syphon", "pyobjc")

# Python versions to try for the venv, most compatible first: torch/ultralytics
# wheels usually lag behind the newest CPython.
VENV_VERSIONS = ["3.12", "3.11", "3.13", "3.10"]

# Default install locations on Windows (newest version wins).
WIN_SC_GLOBS = ["C:/Program Files/SuperCollider*/sclang.exe", "C:/Program Files (x86)/SuperCollider*/sclang.exe"]
WIN_QLC_GLOBS = ["C:/QLC+/qlcplus.exe", "C:/Program Files/QLC+/qlcplus.exe", "C:/Program Files (x86)/QLC+/qlcplus.exe"]
WIN_TD_GLOBS = ["C:/Program Files/Derivative/TouchDesigner*/bin/TouchDesigner.exe"]

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
    """macOS: ask Spotlight for an .app bundle with this exact name."""
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
    """macOS: locate an .app bundle."""
    for cand in (override, os.environ.get(env_var)):
        if cand:
            p = Path(cand).expanduser()
            return p if p.exists() else None
    for base in (Path("/Applications"), Path.home() / "Applications"):
        p = base / app_name
        if p.is_dir():
            return p
    return _mdfind_app(app_name)


def find_win_exe(exe_name: str, override: str | None, env_var: str, globs: list[str]) -> Path | None:
    """Windows: locate an .exe. --*-app / env var may point at the .exe or its folder."""
    for cand in (override, os.environ.get(env_var)):
        if cand:
            p = Path(cand).expanduser()
            if p.is_dir():
                for sub in (p / exe_name, p / "bin" / exe_name):
                    if sub.exists():
                        return sub
                return None
            return p if p.exists() else None
    w = shutil.which(exe_name)
    if w:
        return Path(w)
    for pattern in globs:
        hits = sorted(glob.glob(pattern), reverse=True)  # newest version first
        if hits:
            return Path(hits[0])
    return None


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
    return VENV_DIR / ("Scripts/python.exe" if IS_WIN else "bin/python")


def detection_python(override: str | None) -> Path:
    if override:
        return Path(override).expanduser()
    vp = venv_python()
    return vp if vp.exists() else Path(sys.executable)


def check_python_deps(py: Path) -> tuple[bool, str]:
    code = (
        "import importlib.util as u\n"
        "mods=['cv2','numpy','ultralytics','pythonosc']\n"
        f"vid={VIDEO_MODULES!r}\n"
        "miss=[m for m in mods if u.find_spec(m) is None]\n"
        "opt=[m for m in vid if u.find_spec(m) is None]\n"
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
        return False, f"missing modules: {missing}  (run: python launch.py --setup)"
    if optional:
        return True, f"{VIDEO_NAME} not available ({optional}) -> no video to TouchDesigner (run --setup)"
    return True, ""


def find_base_python() -> list[str] | None:
    """Interpreter used to create the venv, as a command list."""
    if IS_WIN and shutil.which("py"):
        for v in VENV_VERSIONS:
            cmd = ["py", f"-{v}"]
            if subprocess.run(cmd + ["-c", "import sys"], capture_output=True).returncode == 0:
                return cmd
    for v in VENV_VERSIONS:
        w = shutil.which(f"python{v}")
        if w:
            return [w]
    w = shutil.which("python3") or shutil.which("python")
    return [w] if w else [sys.executable]


def filtered_requirements() -> Path:
    """requirements.txt without macOS-only packages when not on macOS."""
    if IS_MAC or not REQUIREMENTS.exists():
        return REQUIREMENTS
    keep, dropped = [], []
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        name = line.strip().lower()
        if name.startswith(MAC_ONLY_PREFIXES) and ";" not in name:
            dropped.append(line.strip())
            continue
        keep.append(line)
    if not dropped:
        return REQUIREMENTS
    warn(f"skipping macOS-only requirements: {', '.join(dropped)}")
    tmp = VENV_DIR / "requirements.filtered.txt"
    tmp.write_text("\n".join(keep) + "\n", encoding="utf-8")
    return tmp


def setup_venv() -> int:
    base = find_base_python()
    if not base:
        fail("no Python interpreter found to build the venv")
        return 1
    if not venv_python().exists():
        log("LAUNCH", f"Creating venv in {VENV_DIR} with {' '.join(base)}")
        r = subprocess.run(base + ["-m", "venv", str(VENV_DIR)])
        if r.returncode != 0:
            fail("venv creation failed")
            return r.returncode
    py = str(venv_python())
    log("LAUNCH", "Installing Python dependencies (ultralytics pulls torch: may take a while)")
    subprocess.run([py, "-m", "pip", "install", "--upgrade", "pip"])
    if REQUIREMENTS.exists():
        r = subprocess.run([py, "-m", "pip", "install", "-r", str(filtered_requirements())])
    else:
        warn(f"{REQUIREMENTS} not found: installing the core packages directly")
        r = subprocess.run([py, "-m", "pip", "install", "opencv-python", "numpy", "ultralytics", "python-osc"])
    if r.returncode != 0:
        fail("pip install failed (see output above)")
        return r.returncode
    if VIDEO_PACKAGES:
        log("LAUNCH", f"Installing {VIDEO_NAME} video bridge: {' '.join(VIDEO_PACKAGES)}")
        r = subprocess.run([py, "-m", "pip", "install", *VIDEO_PACKAGES])
        if r.returncode != 0:
            fail(f"{VIDEO_NAME} install failed (see output above)")
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
    if IS_WIN:
        exe = name if name.lower().endswith(".exe") else name + ".exe"
        try:
            out = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {exe}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=10,
            ).stdout
        except (OSError, subprocess.SubprocessError):
            return set()
        pids = set()
        for row in csv.reader(io.StringIO(out)):
            if len(row) > 1 and row[0].lower() == exe.lower() and row[1].isdigit():
                pids.add(int(row[1]))
        return pids
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
        self.detection_script = (Path(args.detection_script).expanduser().resolve()
                                 if args.detection_script else DETECTION_SCRIPT)

        if IS_WIN:
            self.sc_app = None
            self.sclang = find_win_exe("sclang.exe", args.sc_app, "SC_APP", WIN_SC_GLOBS)
            self.qlc_app = None
            self.qlc_bin = find_win_exe("qlcplus.exe", args.qlc_app, "QLC_APP", WIN_QLC_GLOBS)
            self.td_app = find_win_exe("TouchDesigner.exe", args.td_app, "TD_APP", WIN_TD_GLOBS)
        else:
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
        log("LAUNCH", f"Pre-flight checks ({'Windows' if IS_WIN else 'macOS' if IS_MAC else platform.system()})")

        if "sc" not in self.skip:
            if not SC_SCRIPT.exists():
                fail(f"missing {SC_SCRIPT}"); good = False
            if not SC_LAYERS.is_dir():
                warn(f"missing {SC_LAYERS} (SuperCollider will have no sound)")
            if self.args.sc_ide:
                ide = self._sc_ide_path()
                if ide: ok(f"SuperCollider IDE: {ide}")
                else: fail("SuperCollider IDE not found (use --sc-app)"); good = False
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
            elif IS_WIN: warn("TouchDesigner.exe not found: the .toe will open with its default app (or use --td-app)")
            else: fail("TouchDesigner.app not found (use --td-app or TD_APP=...)"); good = False

        if "detection" not in self.skip:
            if not self.detection_script.exists():
                fail(f"missing {self.detection_script} (use --detection-script)"); good = False
            if not YOLO_MODEL.exists():
                warn(f"{YOLO_MODEL.name} not in Python/: ultralytics will try to download it")
            deps_ok, msg = check_python_deps(self.py)
            if deps_ok:
                ok(f"detection Python: {self.py}")
                if msg: warn(msg)
            else:
                fail(f"detection Python {self.py}: {msg}"); good = False
        return good

    def _sc_ide_path(self) -> Path | None:
        if IS_WIN:
            if self.sclang:
                ide = self.sclang.parent / "scide.exe"
                return ide if ide.exists() else None
            return None
        return self.sc_app

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
        kw = {}
        if IS_WIN:
            # Own process group: Ctrl+C is handled by us, not forwarded raw
            kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kw["start_new_session"] = True
        p = subprocess.Popen(
            cmd, cwd=str(cwd),
            stdin=stdin if stdin is not None else subprocess.DEVNULL,
            stdout=subprocess.DEVNULL if quiet else subprocess.PIPE,
            stderr=subprocess.DEVNULL if quiet else subprocess.STDOUT,
            text=True, bufsize=1, encoding="utf-8", errors="replace",
            # PYTHONIOENCODING: the detection script prints emoji; on Windows a piped
            # stdout defaults to cp1252 and would crash on them.
            env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"},
            **kw,
        )
        if not quiet:
            threading.Thread(target=self._pump, args=(tag, p.stdout, on_line), daemon=True).start()
        self.procs[tag] = p
        return p

    # ---------------- components ---------------- #
    def start_supercollider(self) -> None:
        if self.args.sc_ide:
            # Opens the file in the IDE: the user must evaluate it.
            if IS_WIN:
                subprocess.Popen([str(self._sc_ide_path()), str(SC_SCRIPT)])
                warn("SuperCollider IDE opened: select all and press Ctrl+Enter to start the engine")
            else:
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
        # Not added to self.procs, so shutdown never kills it unless --close-apps.
        if IS_WIN:
            if self.td_app:
                subprocess.Popen([str(self.td_app), str(self.toe)], cwd=str(self.toe.parent))
            else:
                os.startfile(str(self.toe))  # .toe file association
        else:
            subprocess.run(["open", "-a", str(self.td_app), str(self.toe)], check=False)
        log("LAUNCH", f"TouchDesigner opening, waiting {self.args.td_wait}s for it to load...")
        self._sleep(self.args.td_wait)
        ok("TouchDesigner launched")

    def start_detection(self) -> None:
        cmd = [str(self.py), str(self.detection_script), "--ip", self.args.ip]
        self._spawn("DET", cmd, self.detection_script.parent)
        if IS_MAC:
            log("LAUNCH", "first run: macOS may ask Camera permission for your terminal app")
        if IS_WIN:
            log("LAUNCH", "the webcam must be free: no Video Device In TOP on it in TouchDesigner")

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
        if IS_WIN and hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, lambda *_: self.stopping.set())  # console window closed

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

        if self.args.close_apps and "td" not in self.skip:
            if IS_MAC:
                subprocess.run(["osascript", "-e", 'quit app "TouchDesigner"'], check=False)
            elif IS_WIN:
                # no /F: asks TD to close normally (it may prompt to save)
                subprocess.run(["taskkill", "/IM", "TouchDesigner.exe"], check=False,
                               capture_output=True)
        elif "td" not in self.skip or "qlc" not in self.skip:
            log("LAUNCH", "TouchDesigner / QLC+ left open (use --close-apps to quit them too)")
        ok("bye")


def parse_args() -> argparse.Namespace:
    app = ".exe or its folder" if IS_WIN else ".app"
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
    p.add_argument("--python", help="Python interpreter for the detection script (default .venv or current)")
    p.add_argument("--detection-script", help=f"detection script (default Python/{DETECTION_SCRIPT.name})")
    p.add_argument("--td-app", help=f"path to TouchDesigner {app} (or env TD_APP)")
    p.add_argument("--sc-app", help=f"path to SuperCollider {'sclang.exe or its folder' if IS_WIN else '.app'} (or env SC_APP)")
    p.add_argument("--qlc-app", help=f"path to QLC+ {app} (or env QLC_APP)")
    p.add_argument("-v", "--verbose", action="store_true", help="show QLC+ output too")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.setup:
        return setup_venv()
    if not (IS_MAC or IS_WIN):
        warn("launcher written for Windows and macOS; other OS may need --*-app paths")
    return Launcher(args).run()


if __name__ == "__main__":
    sys.exit(main())