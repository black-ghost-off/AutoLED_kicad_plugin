"""Autoroute the board with Freerouting: DSN export -> freerouting.jar -> SES import."""

import glob
import os
import re
import shutil
import subprocess
import sys
import time

import pcbnew


def _java_major(java):
    try:
        out = subprocess.run([java, "-version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             timeout=20).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return 0
    m = re.search(r'version "(\d+)(?:\.(\d+))?', out)
    if not m:
        return 0
    major = int(m.group(1))
    return int(m.group(2) or 0) if major == 1 else major


def find_java(configured=""):
    exe = "java.exe" if sys.platform.startswith("win") else "java"
    cands = [configured] if configured else []
    if os.environ.get("JAVA_HOME"):
        cands.append(os.path.join(os.environ["JAVA_HOME"], "bin", exe))
    cands += [shutil.which("java") or "",
              "/opt/homebrew/opt/openjdk/bin/java", "/usr/local/opt/openjdk/bin/java"]
    # JRE downloaded by the Freerouting KiCad plugin
    for base in (os.path.expanduser("~/Library/Caches"), os.path.expanduser("~/.cache"),
                 os.environ.get("LOCALAPPDATA", "")):
        if base:
            cands += sorted(glob.glob(os.path.join(base, "freerouting*", "jre", "*", "bin", exe)) +
                            glob.glob(os.path.join(base, "freerouting*", "jre", "*", "Contents",
                                                   "Home", "bin", exe)), reverse=True)
    for c in cands:
        if c and os.path.isfile(c) and _java_major(c) >= 17:
            return c
    return None


def _version_key(path):
    return [int(x) for x in re.findall(r"\d+", os.path.basename(path))]


def find_jar(configured=""):
    if configured:
        return configured if os.path.isfile(configured) else None
    home = os.path.expanduser("~")
    patterns = []
    for docs in (os.path.join(home, "Documents", "KiCad"), os.path.join(home, ".local", "share", "kicad")):
        patterns.append(os.path.join(docs, "*", "3rdparty", "plugins", "*freerouting*", "jar", "*.jar"))
        patterns.append(os.path.join(docs, "*", "scripting", "plugins", "*freerouting*", "jar", "*.jar"))
    patterns.append(os.path.join(home, "freerouting*.jar"))
    patterns.append(os.path.join(home, "Downloads", "freerouting*.jar"))
    jars = [j for p in patterns for j in glob.glob(p)]
    return max(jars, key=_version_key) if jars else None


def board_has_outline(board):
    return any(d.GetLayer() == pcbnew.Edge_Cuts for d in board.GetDrawings())


def _call_board_fn(fn, board, path):
    try:
        return fn(board, path)
    except TypeError:
        return fn(path)  # older signature, works on the board open in the editor


def route(board, work_dir, cfg, log=print, keep_going=None):
    """Route all unrouted nets of board in place.

    keep_going() is polled while Freerouting runs; returning False cancels.
    """
    java = find_java(cfg.get("java_path", ""))
    if not java:
        raise RuntimeError("Java 17+ not found. Install a JRE (Freerouting 2.x needs Java 21+) "
                           "or set 'Java executable'.")
    jar = find_jar(cfg.get("freerouting_jar", ""))
    if not jar:
        raise RuntimeError("freerouting.jar not found. Install the Freerouting KiCad plugin "
                           "or set 'Freerouting jar'.")
    if not board_has_outline(board):
        raise RuntimeError("Freerouting needs a board outline on Edge.Cuts "
                           "(set 'Board outline' to Rectangle or Follow image shape).")

    base = os.path.join(work_dir, "autoled_route")
    dsn, ses = base + ".dsn", base + ".ses"
    if os.path.exists(ses):
        os.remove(ses)
    if not _call_board_fn(pcbnew.ExportSpecctraDSN, board, dsn):
        raise RuntimeError("Specctra DSN export failed")

    cmd = [java, "-jar", jar, "-de", dsn, "-do", ses, "-mp", str(int(cfg.get("route_passes", 20)))]
    if "2." in os.path.basename(jar) or _version_key(jar)[:1] >= [2]:
        cmd += ["--gui.enabled=false", "--api_server.enabled=false", "--mcp_server.enabled=false"]
    log("Routing with " + os.path.basename(jar) + " ...")
    timeout = float(cfg.get("route_timeout", 600))
    logf = open(base + ".log", "w")
    try:
        proc = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT, cwd=work_dir)
        start = time.time()
        while proc.poll() is None:
            if keep_going is not None and not keep_going():
                proc.kill()
                raise RuntimeError("Routing cancelled")
            if time.time() - start > timeout:
                proc.kill()
                raise RuntimeError("Freerouting timed out after %d s" % timeout)
            time.sleep(0.2)
    finally:
        logf.close()
    if not os.path.isfile(ses):
        raise RuntimeError("Freerouting produced no result (exit code %s), see %s.log"
                           % (proc.returncode, base))
    if not _call_board_fn(pcbnew.ImportSpecctraSES, board, ses):
        raise RuntimeError("Importing %s failed" % ses)
    try:
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())  # refill planes around the new tracks
    except Exception:
        pass
    tracks = sum(1 for t in board.GetTracks() if t.GetClass() in ("PCB_TRACK", "PCB_VIA"))
    log("Routing done: %d tracks/vias on the board" % tracks)
    return tracks
