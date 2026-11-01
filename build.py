#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Copyright (C) 2026 Phil Cifone
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# Additional permission under GNU GPL version 3 section 7:
#
# The pages this program generates are not covered by the GPL. As a
# special exception, you may use, modify and distribute the generated
# pages, including the HTML, CSS and JavaScript from this program that
# is copied into them, under any terms you choose. This exception covers
# only the generated output; this program itself, and any modified
# version of it, remain under the GPL.

"""
build.py — static archive browser
Drop into any directory. Run it. Writes an index.html into every folder.

Usage:
    python3 build.py                  # build the current directory
    python3 build.py /path/to/folder  # build a specific folder
    python3 build.py --serve          # build, then serve on http://localhost:8080
    python3 build.py --help           # all options

Needs only Python 3.9+. If libvips (`vipsthumbnail`) or ImageMagick is
installed, it also makes small thumbnails and viewable previews of TIFF,
RAW and HEIC files. Without them, it still works: rows show the original
images and TIFF/RAW files get an icon.
"""

import argparse
import hashlib
import html
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from urllib.parse import quote


# ── 0. Config ─────────────────────────────────────────────────────────────────
#
# We use Python sets ({}) here instead of lists ([]) for these collections.
# Sets have O(1) membership testing — `ext in RAW_EXTS` is a hash lookup,
# not a linear scan. That matters when classifying a million files.
#
GENERATOR = "staticarchive build.py"   # written into each page so we can recognise our own
THUMB_DIR = "_thumbs"                  # where thumbnails and previews go, at the top of the tree
THUMB_SIZE = 240                       # px, longest edge (rows show them at 44px; 240 is sharp on hi-dpi)
PREVIEW_SIZE = 2048                    # px, longest edge, for TIFF/RAW in the lightbox
SCRIPT = Path(__file__).resolve()      # so we never list this script itself

# Names that never show up in a listing. Dotfiles are skipped separately.
IGNORE = {"index.html", THUMB_DIR, ".DS_Store", "Thumbs.db", "desktop.ini", "__pycache__"}

# Images every browser can show directly.
WEB_IMAGE_EXTS = {"jpg", "jpeg", "png", "gif", "webp", "avif", "svg"}
# Images browsers can't show: we make a JPEG preview of these.
OTHER_IMAGE_EXTS = {"tif", "tiff", "heic", "heif", "jxl", "bmp"}
# Camera raw formats (the same list libvips/libraw understands).
RAW_EXTS = {"3fr", "ari", "arw", "cap", "cr2", "cr3", "crw", "dcr", "dng", "erf",
            "fff", "iiq", "k25", "kdc", "mdc", "mos", "mrw", "nef", "nrw", "orf",
            "ori", "pef", "raf", "raw", "rw2", "rwl", "sr2", "srf", "srw", "x3f"}
VIDEO_EXTS = {"mp4", "m4v", "mov", "webm", "mkv", "avi", "mts", "m2ts", "mpg", "mpeg"}
AUDIO_EXTS = {"mp3", "wav", "flac", "aac", "m4a", "ogg", "opus", "aif", "aiff"}
TEXT_EXTS = {"txt", "md", "markdown", "html", "css", "js", "json", "yaml", "yml",
             "log", "sh", "csv", "xml", "xmp", "toml", "ini"}
PDF_EXTS = {"pdf"}


# ── 1. File classification ─────────────────────────────────────────────────────
#
# `Path` objects (from pathlib) are the modern way to handle file paths in
# Python. `path.suffix` gives us ".jpg", so we strip the dot and lowercase it.
#
def extension(path: Path) -> str:
    return path.suffix.lstrip(".").lower()

def classify(path: Path) -> str:
    ext = extension(path)
    if ext in WEB_IMAGE_EXTS or ext in OTHER_IMAGE_EXTS: return "img"
    if ext in RAW_EXTS:   return "raw"
    if ext in VIDEO_EXTS: return "video"
    if ext in AUDIO_EXTS: return "audio"
    if ext in TEXT_EXTS:  return "txt"
    if ext in PDF_EXTS:   return "pdf"
    return "other"

TYPE_ICON = {
    "img": "▣", "raw": "◧", "video": "▶", "audio": "♪",
    "txt": "≡", "pdf": "◉", "other": "◈", "dir": "▷",
}

TYPE_LABEL = {
    "img": "image", "raw": "raw", "video": "video", "audio": "audio",
    "txt": "text", "pdf": "pdf", "other": "file", "dir": "dir",
}

# Filter buttons, in toolbar order. A button only appears if the folder
# has at least one file of that type.
FILTERS = [("img", "images"), ("raw", "raw"), ("video", "video"), ("audio", "audio"),
           ("txt", "text"), ("pdf", "pdf"), ("dir", "dirs"), ("other", "other")]

def plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"

def human_size(nbytes: float) -> str:
    # Loop through units, dividing by 1024 each time until we find a
    # value that fits. Small units get no decimals; big ones get one,
    # so a 5.7 MB scan doesn't round to "6 MB".
    for unit in ("B", "KB", "MB", "GB"):
        if nbytes < 1024:
            return f"{nbytes:.0f} {unit}" if unit in ("B", "KB") else f"{nbytes:.1f} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} TB"


# ── 2. Directory scanner ───────────────────────────────────────────────────────
#
# Returns a list of dicts, one per file or folder. Using dicts (rather than
# a custom class) keeps it easy to extend: add a key here, read it in the
# renderer.
#
def scan(root: Path) -> list:
    entries = []
    try:
        # Sort dirs first (is_file() is False → 0), then by name, ignoring case.
        items = sorted(root.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except OSError as err:
        print(f"  ! can't read {root}: {err.strerror}", file=sys.stderr)
        return entries

    for item in items:
        name = item.name
        if name in IGNORE or name.startswith("."):
            continue
        if name == SCRIPT.name and item.resolve() == SCRIPT:
            continue

        # quote() turns a filename into a safe URL piece: "#1.png" → "%231.png",
        # "a b.jpg" → "a%20b.jpg". safe="" means even "/" would be encoded.
        href = quote(name, safe="")

        if item.is_dir():
            entries.append({"name": name, "href": href + "/", "type": "dir"})
        elif item.is_file():
            try:
                stat = item.stat()   # one syscall for size + mtime
            except OSError:
                continue
            entries.append({
                "name":     name,
                "href":     href,
                "type":     classify(item),
                "ext":      extension(item),
                "bytes":    stat.st_size,
                "mtime":    stat.st_mtime,
                "thumb":    None,   # URL of the small row image, filled in below
                "view":     None,   # URL the lightbox shows, filled in below
            })
    return entries


# ── 3. Thumbnails and previews ─────────────────────────────────────────────────
#
# We don't do any image decoding in Python. Instead we call an image tool
# that's very good at it, if one is installed:
#
#   vipsthumbnail  (libvips)    fast, low memory, reads TIFF/RAW/HEIC
#   magick/convert (ImageMagick) slower fallback
#
# Everything we make goes in one folder, `_thumbs/`, at the top of the tree.
# The originals are never touched. Each file's thumbnail is named after a
# hash of its path, so odd filenames can't cause trouble and renaming a
# folder doesn't collide with anything.
#
# A thumbnail is "fresh" when its mtime equals the original's mtime (we copy
# the mtime across after making it). That makes re-runs fast — only new or
# changed files get processed — and also catches a file that was replaced
# by an older copy.

# Filenames that are safe to hand to vips/ImageMagick as-is. Both tools treat
# characters like "[" and "*" specially, so anything else goes through a
# temporary symlink with a boring name.
SAFE_NAME = re.compile(r"[\w .,()+-]+")

# vips prints harmless warnings about optional plugins; keep them quiet.
TOOL_ENV = {**os.environ, "VIPS_WARNING": "0"}

def find_image_tool():
    for tool in ("vipsthumbnail", "magick"):
        if shutil.which(tool):
            return tool
    # On Windows, "convert" is a disk utility, not ImageMagick.
    if os.name != "nt" and shutil.which("convert"):
        return "convert"
    return None

def make_jpeg(tool: str, src: Path, dst: Path, size: int, quality: int) -> bool:
    """Shrink `src` to fit within size×size and save it as JPEG at `dst`."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(f".{dst.stem}.tmp.jpg")   # write to a temp file, then rename
    link = None
    if not SAFE_NAME.fullmatch(src.name):
        suffix = re.sub(r"[^\w.]", "", src.suffix)
        link = dst.with_name(f".{dst.stem}.src{suffix}")
        try:
            link.unlink(missing_ok=True)
            os.symlink(src.resolve(), link)
        except OSError:
            link = None
    source = str(link or src)

    if tool == "vipsthumbnail":
        # "2048x2048>" = only ever shrink, never enlarge a small image.
        cmd = ["vipsthumbnail", source, "--size", f"{size}x{size}>",
               "-o", f"{tmp}[Q={quality},strip]"]
    else:
        # "[0]" = first page/frame only (multi-page TIFFs, GIFs).
        cmd = [tool, source + "[0]", "-auto-orient", "-thumbnail", f"{size}x{size}>",
               "-strip", "-quality", str(quality), str(tmp)]
    try:
        result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                env=TOOL_ENV, timeout=600)
        if result.returncode != 0 or not tmp.exists() or tmp.stat().st_size == 0:
            return False
        os.replace(tmp, dst)
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False
    finally:
        tmp.unlink(missing_ok=True)
        if link:
            link.unlink(missing_ok=True)

def is_fresh(path: Path, mtime: float) -> bool:
    try:
        return path.stat().st_mtime == mtime
    except OSError:
        return False

def make_derivatives(tool: str, src: Path, entry: dict, folder: Path, key: str) -> dict:
    """Make the thumbnail (and, for TIFF/RAW, a preview) for one file."""
    thumb = folder / f"{key}.jpg"
    preview = folder / f"{key}-preview.jpg"
    needs_preview = entry["ext"] not in WEB_IMAGE_EXTS
    made = 0

    if needs_preview:
        # Decode the big file once into a 2048px preview, then make the
        # small thumbnail from the preview. RAW and huge TIFFs are slow to
        # decode, so this halves the work.
        if not is_fresh(preview, entry["mtime"]):
            if not make_jpeg(tool, src, preview, PREVIEW_SIZE, 85):
                return {"thumb": None, "preview": None, "made": 0, "failed": True}
            os.utime(preview, (entry["mtime"], entry["mtime"]))
            made += 1
        thumb_source = preview
    else:
        thumb_source = src

    if not is_fresh(thumb, entry["mtime"]):
        if not make_jpeg(tool, thumb_source, thumb, THUMB_SIZE, 80):
            return {"thumb": None, "preview": preview if needs_preview else None,
                    "made": made, "failed": True}
        os.utime(thumb, (entry["mtime"], entry["mtime"]))
        made += 1

    return {"thumb": thumb, "preview": preview if needs_preview else None,
            "made": made, "failed": False}

def attach_images(root: Path, entries: list, site_root: Path, ctx: dict) -> None:
    """Fill in each entry's "thumb" and "view" URLs, making images if we can."""
    depth = len(root.relative_to(site_root).parts)
    to_top = "../" * depth   # relative URL from this page back up to site_root

    jobs = []
    for e in entries:
        if e["type"] not in ("img", "raw"):
            continue
        web = e["ext"] in WEB_IMAGE_EXTS
        if web:
            # Browsers can show these as-is: the lightbox opens the original.
            e["view"] = e["href"]
            e["thumb"] = e["href"]   # replaced below if we make a real thumbnail
        if ctx["tool"] and e["ext"] != "svg":
            jobs.append(e)

    if not jobs:
        return

    # Submit every file to the thread pool. Each job mostly waits on an
    # external process, so threads (not processes) are the right fit.
    futures = {}
    for e in jobs:
        rel = (root / e["name"]).relative_to(site_root).as_posix()
        key = hashlib.sha1(rel.encode("utf-8")).hexdigest()
        folder = site_root / THUMB_DIR / key[:2]
        fut = ctx["pool"].submit(make_derivatives, ctx["tool"], root / e["name"], e, folder, key)
        futures[fut] = (e, key)

    done = 0
    for fut in as_completed(futures):
        e, key = futures[fut]
        result = fut.result()
        url_dir = f"{to_top}{THUMB_DIR}/{key[:2]}/"
        if result["thumb"]:
            e["thumb"] = url_dir + result["thumb"].name
            ctx["keep"].add(result["thumb"])
        if result["preview"]:
            e["view"] = url_dir + result["preview"].name
            ctx["keep"].add(result["preview"])
        ctx["made"] += result["made"]
        ctx["failed"] += result["failed"]
        done += 1
        if ctx["tty"] and len(jobs) > 20:
            print(f"\r  images {done}/{len(jobs)}", end="", flush=True)
    if ctx["tty"] and len(jobs) > 20:
        print("\r\033[K", end="")   # clear the progress line

def remove_stale_images(site_root: Path, keep: set) -> int:
    """Delete thumbnails whose original was deleted or renamed."""
    removed = 0
    thumbs = site_root / THUMB_DIR
    if not thumbs.is_dir():
        return 0
    ours = re.compile(r"(\.)?[0-9a-f]{40}(-preview)?(\.tmp\.jpg|\.src.*|\.jpg)")
    for path in thumbs.glob("*/*"):
        if ours.fullmatch(path.name) and path not in keep:
            path.unlink(missing_ok=True)
            removed += 1
    for folder in thumbs.iterdir():
        if folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
    return removed


# ── 4. HTML row renderer ───────────────────────────────────────────────────────
#
# Every filename goes through html.escape() before it lands in the page, so
# a file called `say "hi" & <b>.txt` shows up as text instead of breaking
# the markup. URLs were already made safe by quote() in scan().
#
def render_row(e: dict, index: int) -> str:
    esc = html.escape   # short alias; escapes & < > " '
    is_dir = e["type"] == "dir"

    # Stagger each row's fade-in by 25ms so they cascade in, capped at 600ms.
    delay = min(index * 25, 600)

    if e.get("thumb"):
        # `loading="lazy"`: the browser only fetches images near the viewport.
        thumb = f'<img src="{esc(e["thumb"])}" alt="" loading="lazy" decoding="async" />'
    else:
        thumb = f'<span class="file-icon">{TYPE_ICON[e["type"]]}</span>'

    # Folders open in the same tab; files open in a new one.
    attrs = "" if is_dir else ' target="_blank" rel="noopener"'
    if e.get("view"):
        attrs += f' data-src="{esc(e["view"])}"'

    date = "" if is_dir else datetime.fromtimestamp(e["mtime"]).strftime("%Y-%m-%d")
    size = "" if is_dir else human_size(e["bytes"])

    return f"""
    <a class="row" href="{esc(e["href"])}" data-type="{e["type"]}" style="animation-delay:{delay}ms"{attrs}>
      <div class="thumb">{thumb}</div>
      <div class="name" title="{esc(e["name"])}">{esc(e["name"])}</div>
      <div class="date">{date}</div>
      <div class="size">{size}</div>
      <div class="badge {e["type"]}">{TYPE_LABEL[e["type"]]}</div>
    </a>"""


# ── 5. Page styles and script ──────────────────────────────────────────────────
#
# These are plain strings, not f-strings, so CSS and JS braces are written
# normally. build_html() drops them into the page.
#

# Runs in <head> before anything is drawn, so a dark-mode visitor never sees
# a flash of the light theme. Uses the saved choice, else the system setting.
THEME_INIT = """
    (function () {
      var t = null;
      try { t = localStorage.getItem("theme"); } catch (e) {}
      if (t === null) t = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
      if (t === "dark") document.documentElement.classList.add("dark");
    })();
"""

CSS = """
    :root {
      --color-olive:      #98971a;
      --bg:               #f5f5f5;
      --surface:          #ffffff;
      --border:           #282828;
      --text:             #282828;
      --muted:            #7c6f64;
      --green:            #98971a;
      --blue:             #458588;
      --red:              #cc241d;
      --yellow:           #d79921;
      --aqua:             #689d6a;
      --purple:           #b16286;
      --font-display:     'Young Serif', Georgia, serif;
      --font-sans:        'Courier Prime', 'Courier New', monospace;
      color-scheme: light;
    }
    html.dark {
      --color-olive:      #79740e;
      --bg:               #1d2021;
      --surface:          #282828;
      --border:           #ebdbb2;
      --text:             #ebdbb2;
      --muted:            #a89984;
      --green:            #98971a;
      --blue:             #83a598;
      --red:              #fb4934;
      --yellow:           #d79921;
      --aqua:             #8ec07c;
      --purple:           #d3869b;
      color-scheme: dark;
    }
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: var(--bg); color: var(--text); font-family: var(--font-sans);
      font-size: 13px; min-height: 100vh; padding: 2rem 2.5rem 6rem;
    }

    /* ── Header ── */
    header { margin-bottom: 2rem; padding-bottom: 1rem; border-bottom: 2px solid var(--border); }
    .header-row { display: flex; justify-content: space-between; align-items: center; gap: 1rem; }
    .dir-path { font-family: var(--font-display); font-size: 1.3rem; letter-spacing: -0.01em; overflow-wrap: anywhere; }
    .dir-path span { color: var(--muted); }
    .meta-line { margin-top: 0.35rem; color: var(--muted); font-size: 0.7rem; }
    .breadcrumb { display: flex; align-items: center; gap: 0.3rem; margin-bottom: 1.5rem; flex-wrap: wrap; }
    .crumb { font-size: 0.72rem; color: var(--muted); text-decoration: none; transition: color 0.1s; }
    .crumb:hover { color: var(--color-olive); }
    .crumb.current { color: var(--text); }
    .crumb-sep { color: var(--muted); font-size: 0.7rem; }

    /* ── Buttons: neobrutalist press + btn-swipe fill (see STYLE.md) ── */
    .toolbar { display: flex; align-items: center; gap: 0.5rem; margin-bottom: 1rem; flex-wrap: wrap; }
    .btn {
      font-family: var(--font-display); font-size: 0.7rem; letter-spacing: 0.04em;
      padding: 0.375rem 0.75rem; background: var(--bg);
      border: 2px solid var(--border); color: var(--text);
      border-radius: 0; cursor: pointer; transition: all 0.12s;
      box-shadow: 2px 2px 0 0 var(--color-olive);
      position: relative; overflow: hidden; isolation: isolate; z-index: 0;
    }
    .btn::before {
      content: ''; position: absolute; bottom: 0; left: 0; right: 0;
      height: 0%; background-color: var(--color-olive); z-index: -1;
      transition: height 0.3s ease-in-out;
    }
    @media (hover: hover) and (pointer: fine) {
      .btn:hover::before { height: 100%; bottom: 0; top: auto; }
      .btn:not(:hover)::before { height: 0%; bottom: auto; top: 0; transition: height 0.3s ease-in-out; }
      .btn:hover { color: #fff; translate: 1px 1px; box-shadow: 1px 1px 0 0 var(--color-olive); }
    }
    .btn:active { translate: 1px 1px; box-shadow: 1px 1px 0 0 var(--color-olive); background-color: var(--color-olive); color: #fff; }
    .btn.active { background: var(--color-olive); color: #fff; font-weight: 700; box-shadow: 1px 1px 0 0 var(--color-olive); translate: 1px 1px; }
    .btn .count { opacity: 0.65; margin-left: 0.35em; font-weight: 400; }
    .btn:focus-visible, .row:focus-visible, .crumb:focus-visible { outline: 2px solid var(--color-olive); outline-offset: 2px; }

    /* ── File list ── */
    .col-header, .row { display: grid; grid-template-columns: 44px 1fr 90px 70px 60px; gap: 1rem; }
    .col-header {
      padding: 0.4rem 1rem 0.4rem 0.5rem;
      color: var(--muted); font-size: 0.65rem; letter-spacing: 0.1em;
      font-family: var(--font-display);
      text-transform: uppercase; border-bottom: 2px solid var(--border); margin-bottom: 4px;
    }
    .row {
      align-items: center; padding: 0.45rem 1rem 0.45rem 0.5rem;
      border: 2px solid var(--border); border-radius: 0;
      text-decoration: none; color: var(--text); background: var(--surface);
      box-shadow: 4px 4px 0 0 var(--color-olive);
      opacity: 0; animation: fadeUp 0.25s ease forwards;
      transition: all 0.12s; margin-bottom: 4px;
      /* Lets the browser skip laying out rows that are off-screen. */
      content-visibility: auto; contain-intrinsic-size: auto 52px;
    }
    .row:hover, .row:active { translate: 2px 2px; box-shadow: 2px 2px 0 0 var(--color-olive); }
    .row[data-src] { cursor: zoom-in; }
    .thumb {
      width: 44px; height: 44px; display: flex; align-items: center;
      justify-content: center; overflow: hidden;
      background: var(--bg); border: 2px solid var(--border);
    }
    .thumb img { width: 100%; height: 100%; object-fit: cover; }
    .file-icon { font-size: 1.1rem; color: var(--muted); }
    .name { font-family: var(--font-display); font-size: 0.85rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .date, .size { color: var(--muted); font-size: 0.7rem; }
    .badge {
      font-family: var(--font-display); font-size: 0.6rem; letter-spacing: 0.08em; text-transform: uppercase;
      padding: 0.15rem 0.4rem; border: 2px solid var(--border); color: var(--muted); width: fit-content;
    }
    .badge.img   { color: var(--aqua);   border-color: var(--aqua);   }
    .badge.raw   { color: var(--purple); border-color: var(--purple); }
    .badge.video { color: var(--blue);   border-color: var(--blue);   }
    .badge.txt   { color: var(--green);  border-color: var(--green);  }
    .badge.pdf   { color: var(--red);    border-color: var(--red);    }
    .badge.dir   { color: var(--yellow); border-color: var(--yellow); }
    #empty { display: none; padding: 3rem 0; text-align: center; color: var(--muted); font-size: 0.75rem; font-family: var(--font-display); }

    /* ── Lightbox (always dark, whatever the theme) ── */
    #lightbox {
      display: none; position: fixed; inset: 0;
      background: rgba(0,0,0,0.93); z-index: 100;
      align-items: center; justify-content: center; overflow: hidden;
    }
    #lightbox.open { display: flex; }
    #lb-wrap { display: flex; align-items: center; justify-content: center; transform-origin: center center; will-change: transform; }
    #lightbox img { max-width: 90vw; max-height: 80vh; object-fit: contain; user-select: none; border: 2px solid #3c3836; }
    #lb-hint, #lightbox-caption {
      position: fixed; left: 50%; transform: translateX(-50%);
      color: #a89984; background: rgba(0,0,0,0.7); padding: 0.3rem 0.8rem;
      border: 2px solid #3c3836; white-space: nowrap; max-width: 95vw; overflow: hidden; text-overflow: ellipsis;
    }
    #lb-hint { bottom: 3.5rem; font-size: 0.6rem; letter-spacing: 0.05em; pointer-events: none; }
    #lightbox-caption { bottom: 1.5rem; font-size: 0.7rem; font-family: var(--font-display); }
    #lightbox-caption a { color: #ebdbb2; }
    #lb-close, #lb-prev, #lb-next {
      position: fixed; color: #a89984; background: rgba(0,0,0,0.5);
      border: 2px solid #3c3836; cursor: pointer; border-radius: 0; transition: all 0.12s; z-index: 101; line-height: 1;
    }
    #lb-close { top: 1rem; right: 1.5rem; font-size: 1.5rem; padding: 0.2rem 0.6rem; }
    #lb-prev, #lb-next { top: 50%; transform: translateY(-50%); font-size: 2rem; padding: 0.5rem 0.8rem; }
    #lb-prev { left: 1rem; }
    #lb-next { right: 1rem; }
    #lb-close:hover, #lb-prev:hover, #lb-next:hover { color: #ebdbb2; border-color: #ebdbb2; background: rgba(0,0,0,0.8); }

    footer { margin-top: 3rem; padding-top: 1rem; border-top: 2px solid var(--border); color: var(--muted); font-size: 0.65rem; }

    @keyframes fadeUp { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
    @media (prefers-reduced-motion: reduce) {
      .row { animation: none; opacity: 1; }
      .btn, .btn::before, .row { transition: none; }
    }
    /* Phones: drop the date and size columns. */
    @media (max-width: 640px) {
      body { padding: 1.25rem 1rem 4rem; }
      .col-header, .row { grid-template-columns: 44px 1fr 68px; gap: 0.75rem; }
      .date, .size, .col-date, .col-size { display: none; }
      #lb-hint { display: none; }
    }
"""

JS = """
    // ── Theme toggle (the starting theme was set in <head>) ──────────────────
    const root = document.documentElement;
    const themeBtn = document.getElementById("theme-toggle");
    function setTheme(dark, save) {
      root.classList.toggle("dark", dark);
      themeBtn.textContent = dark ? "light" : "dark";
      if (save) { try { localStorage.setItem("theme", dark ? "dark" : "light"); } catch (e) {} }
    }
    setTheme(root.classList.contains("dark"), false);
    themeBtn.addEventListener("click", () => setTheme(!root.classList.contains("dark"), true));

    // ── Filter buttons ───────────────────────────────────────────────────────
    const rows = Array.from(document.querySelectorAll(".row"));
    const empty = document.getElementById("empty");
    const filterBtns = document.querySelectorAll(".filter-btn");

    filterBtns.forEach(btn => {
      btn.addEventListener("click", () => {
        filterBtns.forEach(b => {
          b.classList.toggle("active", b === btn);
          b.setAttribute("aria-pressed", b === btn);
        });
        const f = btn.dataset.filter;
        let n = 0;
        rows.forEach(r => {
          const show = f === "all" || r.dataset.type === f;
          r.style.display = show ? "" : "none";
          if (show) n++;
        });
        empty.style.display = n === 0 ? "block" : "none";
      });
    });

    // ── Lightbox with zoom + pan ─────────────────────────────────────────────
    const lb      = document.getElementById("lightbox");
    const lbWrap  = document.getElementById("lb-wrap");
    const lbImg   = document.getElementById("lb-img");
    const lbName  = document.getElementById("lb-name");
    const lbOrig  = document.getElementById("lb-original");
    const lbClose = document.getElementById("lb-close");
    const lbPrev  = document.getElementById("lb-prev");
    const lbNext  = document.getElementById("lb-next");

    // State: current scale and translation of the image wrapper
    let scale = 1;
    let tx = 0, ty = 0;       // translation in px
    let dragging = false;
    let dragStartX, dragStartY, dragOriginX, dragOriginY;

    const SCALE_MIN = 1;
    const SCALE_MAX = 10;
    const SCALE_STEP = 0.12;  // how much each scroll tick zooms

    function applyTransform() {
      // Translate first, then scale: translate moves in screen space,
      // scale zooms in place.
      lbWrap.style.transform = `translate(${tx}px, ${ty}px) scale(${scale})`;
      lbWrap.style.cursor = scale > 1 ? (dragging ? "grabbing" : "grab") : "default";
    }

    function resetTransform() {
      scale = 1; tx = 0; ty = 0;
      applyTransform();
    }

    // Scroll to zoom, toward the cursor. If the cursor is at (mx, my)
    // relative to the wrapper centre and scale changes by factor k, the
    // translation must shift by (mx * (1 - k), my * (1 - k)) to keep the
    // point under the cursor still.
    lb.addEventListener("wheel", e => {
      e.preventDefault();
      const direction = e.deltaY < 0 ? 1 : -1;
      const newScale  = Math.min(SCALE_MAX, Math.max(SCALE_MIN, scale + direction * SCALE_STEP * scale));
      const k         = newScale / scale;

      const rect = lb.getBoundingClientRect();
      const mx   = e.clientX - rect.left - rect.width  / 2 - tx;
      const my   = e.clientY - rect.top  - rect.height / 2 - ty;

      tx    += mx * (1 - k);
      ty    += my * (1 - k);
      scale  = newScale;

      // Back at 1:1, snap to centre
      if (scale <= SCALE_MIN) { tx = 0; ty = 0; }
      applyTransform();
    }, { passive: false });

    // Drag to pan (only when zoomed in)
    lbWrap.addEventListener("mousedown", e => {
      if (scale <= 1) return;
      e.preventDefault();
      dragging    = true;
      dragStartX  = e.clientX;
      dragStartY  = e.clientY;
      dragOriginX = tx;
      dragOriginY = ty;
      applyTransform();
    });
    window.addEventListener("mousemove", e => {
      if (!dragging) return;
      tx = dragOriginX + (e.clientX - dragStartX);
      ty = dragOriginY + (e.clientY - dragStartY);
      applyTransform();
    });
    window.addEventListener("mouseup", () => {
      dragging = false;
      applyTransform();
    });
    lbWrap.addEventListener("dblclick", resetTransform);

    // ── Open / close / navigate ──────────────────────────────────────────────
    // `gallery` is the list of images you can arrow through: every row with
    // something to show, minus rows hidden by the current filter.
    let gallery = [];
    let current = 0;

    function showImage(i) {
      current = i;
      const row = gallery[i];
      const name = row.querySelector(".name").textContent;
      lbImg.src = row.dataset.src;
      lbImg.alt = name;
      lbName.textContent = name;
      lbOrig.href = row.href;
      resetTransform();
      lbPrev.style.visibility = i > 0 ? "" : "hidden";
      lbNext.style.visibility = i < gallery.length - 1 ? "" : "hidden";
      // Start loading the next image now so arrowing through feels instant.
      if (gallery[i + 1]) new Image().src = gallery[i + 1].dataset.src;
    }

    function openLightbox(row) {
      gallery = rows.filter(r => r.dataset.src && r.style.display !== "none");
      showImage(gallery.indexOf(row));
      lb.classList.add("open");
    }

    function closeLightbox() {
      lb.classList.remove("open");
      resetTransform();
      lbImg.removeAttribute("src");
    }

    function navPrev() { if (current > 0) showImage(current - 1); }
    function navNext() { if (current < gallery.length - 1) showImage(current + 1); }

    rows.forEach(row => {
      if (!row.dataset.src) return;
      row.addEventListener("click", e => {
        // Ctrl/cmd/shift/middle-click still open the original as a normal link.
        if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
        e.preventDefault();
        openLightbox(row);
      });
    });

    lbPrev.addEventListener("click", e => { e.stopPropagation(); navPrev(); });
    lbNext.addEventListener("click", e => { e.stopPropagation(); navNext(); });
    lbClose.addEventListener("click", closeLightbox);
    lb.addEventListener("click", e => { if (e.target === lb) closeLightbox(); });
    document.addEventListener("keydown", e => {
      if (!lb.classList.contains("open")) return;
      if (e.key === "Escape") closeLightbox();
      if (e.key === "0") resetTransform();
      if (e.key === "ArrowLeft") navPrev();
      if (e.key === "ArrowRight") navNext();
    });
"""


# ── 6. Full HTML builder ───────────────────────────────────────────────────────
#
# `site_root` is the top-level folder we were invoked on. We need it for the
# breadcrumb: how deep is `root` below where the whole site starts?
#
def build_html(root: Path, entries: list, site_root: Path) -> str:
    esc        = html.escape
    built_at   = datetime.now().strftime("%Y-%m-%d %H:%M")
    dir_name   = esc(root.name or str(root))
    files      = [e for e in entries if e["type"] != "dir"]
    n_dirs     = len(entries) - len(files)
    total      = human_size(sum(e["bytes"] for e in files))

    rows_html = "\n".join(render_row(e, i) for i, e in enumerate(entries))

    # ── Breadcrumb ─────────────────────────────────────────────────────────────
    # Example: site_root = /photos, root = /photos/2024/june
    #   crumbs → ["photos", "2024", "june"]
    #   hrefs  → ["../../", "../", (current, not a link)]
    rel_parts  = root.relative_to(site_root).parts
    crumb_dirs = [site_root.name or str(site_root)] + list(rel_parts)
    depth      = len(rel_parts)

    crumbs = []
    for i, part in enumerate(crumb_dirs):
        if i == len(crumb_dirs) - 1:
            crumbs.append(f'<span class="crumb current" aria-current="page">{esc(part)}/</span>')
        else:
            crumbs.append(f'<a class="crumb" href="{"../" * (depth - i)}">{esc(part)}/</a>')
    crumbs_html = '<span class="crumb-sep">›</span>'.join(crumbs)

    # ── Filter buttons: only for types this folder actually has ───────────────
    counts = Counter(e["type"] for e in entries)
    buttons = [f'<button class="btn filter-btn active" data-filter="all" aria-pressed="true">'
               f'all<span class="count">{len(entries)}</span></button>']
    for kind, label in FILTERS:
        if counts[kind]:
            buttons.append(f'<button class="btn filter-btn" data-filter="{kind}" aria-pressed="false">'
                           f'{label}<span class="count">{counts[kind]}</span></button>')
    buttons_html = "\n    ".join(buttons)

    meta = plural(len(files), "file")
    if n_dirs:
        meta += f" &nbsp;·&nbsp; {plural(n_dirs, 'folder')}"
    meta += f" &nbsp;·&nbsp; {total} &nbsp;·&nbsp; built {built_at}"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta name="generator" content="{GENERATOR}" />
  <title>{dir_name}/</title>
  <script>{THEME_INIT}</script>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Young+Serif&amp;family=Courier+Prime:wght@400;700&amp;display=swap" rel="stylesheet" />
  <style>{CSS}</style>
</head>
<body>

  <header>
    <div class="header-row">
      <div class="dir-path"><span>~/</span>{dir_name}/</div>
      <button class="btn" id="theme-toggle" type="button">dark</button>
    </div>
    <div class="meta-line">{meta}</div>
  </header>

  <nav class="breadcrumb" aria-label="Breadcrumb">
    {crumbs_html}
  </nav>

  <div class="toolbar">
    {buttons_html}
  </div>

  <div class="col-header" aria-hidden="true">
    <div></div><div>name</div><div class="col-date">modified</div><div class="col-size">size</div><div>type</div>
  </div>

  <main id="file-list">
    {rows_html}
  </main>
  <div id="empty">no files match this filter</div>

  <div id="lightbox" role="dialog" aria-modal="true" aria-label="Image viewer">
    <button id="lb-close" type="button" aria-label="Close">×</button>
    <button id="lb-prev" type="button" aria-label="Previous image">‹</button>
    <button id="lb-next" type="button" aria-label="Next image">›</button>
    <div id="lb-wrap">
      <img id="lb-img" alt="" />
    </div>
    <div id="lightbox-caption"><span id="lb-name"></span> &nbsp;·&nbsp; <a id="lb-original" target="_blank" rel="noopener">original ↗</a></div>
    <div id="lb-hint">scroll to zoom &nbsp;·&nbsp; drag to pan &nbsp;·&nbsp; dbl-click to reset &nbsp;·&nbsp; ← → to navigate</div>
  </div>

  <footer>{GENERATOR} &nbsp;·&nbsp; {dir_name}/ &nbsp;·&nbsp; {built_at}</footer>

  <script>{JS}</script>

</body>
</html>"""


# ── 7. Recursive builder ───────────────────────────────────────────────────────

def written_by_us(page: Path) -> bool:
    """True if an existing index.html was made by this script (or the old build.py)."""
    try:
        text = page.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return f'content="{GENERATOR}"' in text or "<footer>build.py &nbsp;" in text

def build_dir(root: Path, site_root: Path, ctx: dict) -> None:
    """Build index.html for one directory, then recurse into subdirs."""
    # A symlinked folder could point back up the tree; only visit each once.
    real = root.resolve()
    if real in ctx["seen"]:
        return
    ctx["seen"].add(real)

    entries = scan(root)
    attach_images(root, entries, site_root, ctx)

    out = root / "index.html"
    depth = len(root.relative_to(site_root).parts)
    indent = "  " * depth
    label = out.relative_to(site_root).as_posix()
    count = sum(1 for e in entries if e["type"] != "dir")

    if out.exists() and not ctx["force"] and not written_by_us(out):
        # Someone's own index.html (e.g. a website kept in the archive).
        print(f"{indent}skipped {label}  (an index.html that isn't ours is already there; --force overwrites)")
    else:
        try:
            out.write_text(build_html(root, entries, site_root), encoding="utf-8")
            print(f"{indent}built → {label}  ({plural(count, 'file')})")
            ctx["pages"] += 1
        except OSError as err:
            print(f"{indent}! couldn't write {label}: {err.strerror}", file=sys.stderr)
    ctx["files"] += count

    # Recurse into every subdirectory scan() found.
    for e in entries:
        if e["type"] == "dir":
            build_dir(root / e["name"], site_root, ctx)


# ── 8. Entry point ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Write a browsable index.html into every folder of a file archive.")
    parser.add_argument("folder", nargs="?", default=".", help="folder to build (default: current directory)")
    parser.add_argument("--serve", action="store_true", help="serve the result after building")
    parser.add_argument("--port", type=int, default=8080, help="port for --serve (default: 8080)")
    parser.add_argument("--no-thumbs", action="store_true",
                        help="don't make thumbnails or previews (rows show the original images)")
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 4,
                        help="how many images to process at once (default: number of CPUs)")
    parser.add_argument("--force", action="store_true",
                        help="overwrite index.html files this script didn't make")
    args = parser.parse_args()

    # `.resolve()` turns "." or "../photos" into a full absolute path,
    # which we need for correct relative links.
    site_root = Path(args.folder).resolve()
    if not site_root.is_dir():
        print(f"error: '{site_root}' is not a directory", file=sys.stderr)
        sys.exit(1)

    tool = None if args.no_thumbs else find_image_tool()
    print(f"building {site_root}/")
    if tool:
        print(f"images: {tool} → {THUMB_DIR}/")
    elif not args.no_thumbs:
        print("images: no vipsthumbnail or ImageMagick found, so no thumbnails or TIFF/RAW previews")

    started = time.time()
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        ctx = {
            "tool": tool, "pool": pool, "force": args.force, "tty": sys.stdout.isatty(),
            "seen": set(), "keep": set(), "made": 0, "failed": 0, "pages": 0, "files": 0,
        }
        build_dir(site_root, site_root, ctx)

    summary = f"\n{plural(ctx['pages'], 'page')}, {plural(ctx['files'], 'file')}"
    if tool:
        removed = remove_stale_images(site_root, ctx["keep"])
        summary += f", {plural(ctx['made'], 'image')} made"
        if ctx["failed"]:
            summary += f", {ctx['failed']} couldn't be read"
        if removed:
            summary += f", {removed} old ones removed"
    print(f"{summary}  ({time.time() - started:.1f}s)")

    if args.serve:
        print(f"\nserving at http://localhost:{args.port}  (ctrl-c to stop)")
        try:
            # `sys.executable` is the exact Python running this script.
            subprocess.run([sys.executable, "-m", "http.server", str(args.port),
                            "--directory", str(site_root)])
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
