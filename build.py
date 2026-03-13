#!/usr/bin/env python3
"""
build.py — static site generator
Drop into any directory. Run it. Writes index.html.

Usage:
    python3 build.py                  # scan current directory
    python3 build.py /path/to/folder  # scan a specific path
    python3 build.py --serve          # build + start local server on :8080
"""

import os
import sys
import subprocess
from pathlib import Path
from datetime import datetime


# ── 0. Config ─────────────────────────────────────────────────────────────────
#
# We use Python sets ({}) here instead of lists ([]) for both of these
# collections. Sets have O(1) membership testing — `ext in IMAGE_EXTS`
# is a hash lookup, not a linear scan. For small sets it doesn't matter
# much, but it's the correct tool and a good habit.
#
IGNORE = {
    "index.html", "build.py",
    ".DS_Store", "Thumbs.db",
    ".git", ".gitignore", "__pycache__",
}

IMAGE_EXTS = {"jpg", "jpeg", "png", "gif", "webp", "avif", "svg"}
TEXT_EXTS  = {"txt", "md", "markdown", "html", "css", "js", "json",
              "yaml", "yml", "log", "sh", "csv", "xml", "toml", "ini"}
PDF_EXTS   = {"pdf"}


# ── 1. File classification ─────────────────────────────────────────────────────
#
# `Path` objects (from pathlib) are the modern way to handle file paths in
# Python — they're objects with useful attributes instead of raw strings.
# `path.suffix` gives us ".jpg", so we strip the dot and lowercase it.
#
# The type hints (-> str) are optional but make the code self-documenting:
# this function always takes a Path and always returns a string.
#
def classify(path: Path) -> str:
    ext = path.suffix.lstrip(".").lower()
    if ext in IMAGE_EXTS: return "img"
    if ext in TEXT_EXTS:  return "txt"
    if ext in PDF_EXTS:   return "pdf"
    return "other"

TYPE_ICON = {
    "img":   "▣",
    "txt":   "≡",
    "pdf":   "◉",
    "other": "◈",
    "dir":   "▷",
}

TYPE_LABEL = {
    "img": "image", "txt": "text", "pdf": "pdf", "other": "file", "dir": "dir"
}

def human_size(nbytes: int) -> str:
    # Loop through units, dividing by 1024 each time until we find a
    # value that fits. The loop exits early via `return` — we only
    # reach the final `return` if the file is terabyte-scale.
    for unit in ("B", "KB", "MB", "GB"):
        if nbytes < 1024:
            return f"{nbytes:.0f} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} TB"


# ── 2. Directory scanner ───────────────────────────────────────────────────────
#
# `list[dict]` is a type hint saying this returns a list of dictionaries.
# Each dict is one file's worth of metadata — name, path, type, etc.
# Using dicts (rather than a custom class) keeps it simple and easy to
# extend: just add a new key and reference it in the renderer.
#
def scan(root: Path) -> list[dict]:
    entries = []

    # `root.iterdir()` yields Path objects for each item in the directory.
    # We wrap it in `sorted()` with a key function to control order:
    #   - `p.is_file()` returns True (1) for files, False (0) for dirs,
    #     so sorting by this puts dirs first (0 < 1).
    #   - `p.name.lower()` is the secondary sort key: alphabetical,
    #     case-insensitive within each group.
    #
    for item in sorted(root.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):

        # Skip ignored names and any dotfile (hidden files on Linux/macOS)
        if item.name in IGNORE or item.name.startswith("."):
            continue

        if item.is_dir():
            entries.append({
                "name":  item.name,
                "path":  item.name + "/",   # trailing slash = browser treats as dir link
                "type":  "dir",
                "ext":   "DIR",
                "size":  "",
                "mtime": "",
            })

        elif item.is_file():
            # `item.stat()` makes one syscall to get file metadata.
            # We store the result so we don't call it twice.
            stat = item.stat()
            entries.append({
                "name":  item.name,
                "path":  item.name,
                "type":  classify(item),
                "ext":   item.suffix.lstrip(".").upper() or "—",
                "size":  human_size(stat.st_size),
                # st_mtime is a Unix timestamp (float). fromtimestamp()
                # converts it to a datetime object so we can format it.
                "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d"),
            })

    return entries


# ── 3. HTML row renderer ───────────────────────────────────────────────────────
#
# This function takes one file's metadata dict and returns an HTML string
# for that row. Keeping it separate from build_html() means we can reason
# about one row at a time and test it in isolation if needed.
#
def render_row(e: dict, index: int) -> str:
    icon  = TYPE_ICON[e["type"]]
    badge = TYPE_LABEL[e["type"]]

    # Stagger each row's fade-in animation by 25ms so they cascade in
    # rather than all appearing at once. index comes from enumerate() below.
    delay = min(index * 25, 600)

    if e["type"] == "img":
        # `loading="lazy"` is a native browser attribute — the browser won't
        # fetch this image until it's close to the viewport. Free performance.
        thumb = f'<img src="{e["path"]}" alt="{e["name"]}" loading="lazy" decoding="async" />'
        extra = 'data-lightbox="true"'
    else:
        thumb = f'<span class="file-icon">{icon}</span>'
        extra = ""

    # f-strings (f"...") let us embed expressions directly in strings.
    # The triple-quote version (f"""...""") lets us write multi-line strings
    # without concatenation. Note: inside an f-string, literal braces
    # in CSS/JS must be escaped as {{ and }} — but we have no CSS here,
    # so we're fine.
    return f"""
    <a class="row" href="{e["path"]}" data-type="{e["type"]}"
       style="animation-delay:{delay}ms" target="_blank" rel="noopener" {extra}>
      <div class="thumb">{thumb}</div>
      <div class="name">{e["name"]}</div>
      <div class="date">{e["mtime"]}</div>
      <div class="size">{e["size"]}</div>
      <div class="badge {e['type']}">{badge}</div>
    </a>"""


# ── 4. Full HTML builder ───────────────────────────────────────────────────────
#
# This is the only function that knows what the final HTML looks like.
# It calls render_row() for each entry and joins them into one big string,
# then drops everything into a template f-string.
#
# CSS curly braces inside an f-string must be doubled: { → {{ and } → }}
# because single braces are reserved for variable interpolation.
# It's ugly but it's the tradeoff for keeping everything in one file.
#
# `site_root` is the top-level directory we were originally invoked on.
# We need it to build the breadcrumb: how deep is `root` relative to
# where the whole site starts?
#
def build_html(root: Path, entries: list[dict], site_root: Path) -> str:
    built_at   = datetime.now().strftime("%Y-%m-%d %H:%M")
    dir_name   = root.resolve().name
    file_count = sum(1 for e in entries if e["type"] != "dir")

    # `enumerate()` gives us (index, item) pairs so render_row knows
    # its position in the list (used for the staggered animation delay).
    rows_html = "\n".join(render_row(e, i) for i, e in enumerate(entries))

    # ── Breadcrumb ─────────────────────────────────────────────────────────────
    #
    # We walk from site_root down to root, building one clickable crumb
    # per directory. Each crumb needs a relative href that points back up
    # the right number of levels.
    #
    # Example: site_root = /photos, root = /photos/2024/june
    #   parts      → ["photos", "2024", "june"]
    #   depths     → [2 levels up, 1 level up, current]
    #   hrefs      → ["../../", "../", ""]
    #
    # `root.relative_to(site_root)` gives us the path from site_root to
    # root as a relative Path object, e.g. PosixPath('2024/june').
    # `.parts` splits that into a tuple: ('2024', 'june').
    #
    rel_parts  = root.relative_to(site_root).parts   # () if we're at root
    crumb_dirs = [site_root.name] + list(rel_parts)   # prepend the root dir name
    depth      = len(rel_parts)                        # how many levels deep we are

    crumbs_html = ""
    for i, part in enumerate(crumb_dirs):
        levels_up = depth - i                          # how many "../" we need
        href      = "../" * levels_up                  # "" means current dir
        is_last   = (i == len(crumb_dirs) - 1)

        if is_last:
            crumbs_html += f'<span class="crumb current">{part}/</span>'
        else:
            crumbs_html += f'<a class="crumb" href="{href}">{part}/</a>'
        if not is_last:
            crumbs_html += '<span class="crumb-sep">›</span>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{dir_name}/</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link href="https://fonts.googleapis.com/css2?family=Young+Serif&family=Courier+Prime:wght@400;700&display=swap" rel="stylesheet" />
  <style>
    :root {{
      --color-olive:      #98971a;
      --theme-light:      #98971a;
      --theme-dark:       #79740e;
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
      --font-display:     'Young Serif', serif;
      --font-sans:        'Courier Prime', monospace;
    }}
    html.dark {{
        --color-olive:    #79740e;
        --theme-light:    #98971a;
        --theme-dark:     #79740e;
        --bg:             #1d2021;
        --surface:        #282828;
        --border:         #ebdbb2;
        --text:           #ebdbb2;
        --muted:          #a89984;
        --green:          #79740e;
        --blue:           #076678;
        --red:            #9d0006;
        --yellow:         #b57614;
        --aqua:           #427b58;
        --purple:         #8f3f71;
    }}
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: var(--bg); color: var(--text); font-family: var(--font-sans);
      font-size: 13px; min-height: 100vh; padding: 2rem 2.5rem 6rem;
    }}
    header {{
      margin-bottom: 2rem; padding-bottom: 1rem;
      border-bottom: 2px solid var(--border);
    }}
    .dir-path {{ font-family: var(--font-display); font-size: 1.3rem; color: var(--text); letter-spacing: -0.01em; }}
    .dir-path span {{ color: var(--muted); }}
    .meta-line {{ margin-top: 0.35rem; color: var(--muted); font-size: 0.7rem; }}
    .breadcrumb {{ display: flex; align-items: center; gap: 0.3rem; margin-bottom: 1.5rem; flex-wrap: wrap; }}
    .crumb {{ font-family: var(--font-sans); font-size: 0.72rem; color: var(--muted); text-decoration: none; transition: color 0.1s; }}
    .crumb:hover {{ color: var(--color-olive); }}
    .crumb.current {{ color: var(--text); cursor: default; }}
    .crumb-sep {{ color: var(--muted); font-size: 0.7rem; }}
    .toolbar {{ display: flex; align-items: center; gap: 0.5rem; margin-bottom: 1rem; flex-wrap: wrap; }}
    .filter-btn {{
      font-family: var(--font-display); font-size: 0.7rem; letter-spacing: 0.04em;
      padding: 0.375rem 0.75rem; background: var(--bg);
      border: 2px solid var(--border); color: var(--text);
      border-radius: 0; cursor: pointer; transition: all 0.12s;
      shadow: 2px 2px 0 0 var(--color-olive);
      box-shadow: 2px 2px 0 0 var(--color-olive);
      position: relative; overflow: hidden; isolation: isolate; z-index: 0;
    }}
    .filter-btn::before {{
      content: ''; position: absolute; bottom: 0; left: 0; right: 0;
      height: 0%; background-color: var(--color-olive); z-index: -1;
      transition: height 0.3s ease-in-out;
    }}
    @media (hover: hover) and (pointer: fine) {{
      .filter-btn:hover::before {{ height: 100%; bottom: 0; top: auto; }}
      .filter-btn:not(:hover)::before {{ height: 0%; bottom: auto; top: 0; transition: height 0.3s ease-in-out; }}
      .filter-btn:hover {{
        color: #fff;
        translate: 1px 1px; box-shadow: 1px 1px 0 0 var(--color-olive);
      }}
    }}
    .filter-btn:active {{
      translate: 1px 1px; box-shadow: 1px 1px 0 0 var(--color-olive);
      background-color: var(--color-olive); color: #fff;
    }}
    .filter-btn.active {{ background: var(--color-olive); color: #fff; border-color: var(--border); font-weight: 700; box-shadow: 1px 1px 0 0 var(--color-olive); translate: 1px 1px; }}
    .col-header {{
      display: grid; grid-template-columns: 44px 1fr 90px 70px 60px;
      gap: 1rem; padding: 0.4rem 1rem 0.4rem 0.5rem;
      color: var(--muted); font-size: 0.65rem; letter-spacing: 0.1em;
      font-family: var(--font-display);
      text-transform: uppercase; border-bottom: 2px solid var(--border); margin-bottom: 4px;
    }}
    .row {{
      display: grid; grid-template-columns: 44px 1fr 90px 70px 60px;
      align-items: center; gap: 1rem; padding: 0.45rem 1rem 0.45rem 0.5rem;
      border: 2px solid var(--border); border-radius: 0;
      text-decoration: none; color: var(--text); background: var(--surface);
      box-shadow: 4px 4px 0 0 var(--color-olive);
      opacity: 0; animation: fadeUp 0.25s ease forwards;
      transition: all 0.12s; margin-bottom: 4px;
      content-visibility: auto; contain-intrinsic-size: auto 52px;
    }}
    .row:hover {{
      translate: 2px 2px;
      box-shadow: 2px 2px 0 0 var(--color-olive);
    }}
    .row:active {{
      translate: 2px 2px;
      box-shadow: 2px 2px 0 0 var(--color-olive);
    }}
    .row[data-lightbox="true"] {{ cursor: zoom-in; }}
    .thumb {{
      width: 44px; height: 44px; display: flex; align-items: center;
      justify-content: center; overflow: hidden; border-radius: 0;
      background: var(--bg); border: 2px solid var(--border); flex-shrink: 0;
    }}
    .thumb img {{ width: 100%; height: 100%; object-fit: cover; }}
    .file-icon {{ font-size: 1.1rem; color: var(--muted); }}
    .name {{ font-family: var(--font-display); font-size: 0.85rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
    .date, .size {{ color: var(--muted); font-size: 0.7rem; }}
    .badge {{
      font-family: var(--font-display); font-size: 0.6rem; letter-spacing: 0.08em; text-transform: uppercase;
      padding: 0.15rem 0.4rem; border-radius: 0;
      border: 2px solid var(--border); color: var(--muted); width: fit-content;
    }}
    .badge.img {{ color: var(--aqua);   border-color: var(--aqua);   }}
    .badge.txt {{ color: var(--green);  border-color: var(--green);  }}
    .badge.pdf {{ color: var(--red);    border-color: var(--red);    }}
    .badge.dir {{ color: var(--yellow); border-color: var(--yellow); }}
    #empty {{ display: none; padding: 3rem 0; text-align: center; color: var(--muted); font-size: 0.75rem; font-family: var(--font-display); }}
    #lightbox {{
      display: none; position: fixed; inset: 0;
      background: rgba(0,0,0,0.93); z-index: 100;
      align-items: center; justify-content: center;
    }}
    #lightbox.open {{ display: flex; }}
    #lb-wrap {{
      display: flex; align-items: center; justify-content: center;
      transform-origin: center center;
      will-change: transform;
    }}
    #lightbox img {{ max-width: 90vw; max-height: 90vh; object-fit: contain; border-radius: 0; user-select: none; border: 2px solid var(--border); }}
    #lb-hint {{
      position: fixed; bottom: 3.5rem; left: 50%; transform: translateX(-50%);
      font-size: 0.6rem; color: #a89984; letter-spacing: 0.05em;
      background: rgba(0,0,0,0.7); padding: 0.3rem 0.8rem; border-radius: 0;
      border: 2px solid #3c3836;
      pointer-events: none;
    }}
    #lightbox-caption {{
      position: fixed; bottom: 1.5rem; left: 50%; transform: translateX(-50%);
      font-size: 0.7rem; color: #a89984; font-family: var(--font-display);
      background: rgba(0,0,0,0.7); padding: 0.3rem 0.8rem; border-radius: 0;
      border: 2px solid #3c3836;
    }}
    #lb-close {{
      position: fixed; top: 1rem; right: 1.5rem; font-size: 1.5rem; color: #a89984;
      background: none; border: 2px solid #3c3836; cursor: pointer;
      padding: 0.2rem 0.6rem; border-radius: 0; transition: all 0.12s;
    }}
    #lb-close:hover {{ color: #ebdbb2; border-color: #ebdbb2; }}
    #lb-prev, #lb-next {{
      position: fixed; top: 50%; transform: translateY(-50%);
      font-size: 2rem; color: #a89984; background: rgba(0,0,0,0.5);
      border: 2px solid #3c3836; cursor: pointer;
      padding: 0.5rem 0.8rem; border-radius: 0; transition: all 0.12s;
      z-index: 101; line-height: 1;
    }}
    #lb-prev {{ left: 1rem; }}
    #lb-next {{ right: 1rem; }}
    #lb-prev:hover, #lb-next:hover {{ color: #ebdbb2; border-color: #ebdbb2; background: rgba(0,0,0,0.8); }}
    .header-row {{ display: flex; justify-content: space-between; align-items: center; }}
    #theme-toggle {{
      font-family: var(--font-display); font-size: 0.7rem;
      padding: 0.375rem 0.75rem; background: var(--bg);
      border: 2px solid var(--border); color: var(--text);
      border-radius: 0; cursor: pointer; transition: all 0.12s;
      box-shadow: 2px 2px 0 0 var(--color-olive);
      position: relative; overflow: hidden; isolation: isolate; z-index: 0;
    }}
    #theme-toggle::before {{
      content: ''; position: absolute; bottom: 0; left: 0; right: 0;
      height: 0%; background-color: var(--color-olive); z-index: -1;
      transition: height 0.3s ease-in-out;
    }}
    @media (hover: hover) and (pointer: fine) {{
      #theme-toggle:hover::before {{ height: 100%; bottom: 0; top: auto; }}
      #theme-toggle:not(:hover)::before {{ height: 0%; bottom: auto; top: 0; transition: height 0.3s ease-in-out; }}
      #theme-toggle:hover {{ color: #fff; translate: 1px 1px; box-shadow: 1px 1px 0 0 var(--color-olive); }}
    }}
    #theme-toggle:active {{ translate: 1px 1px; box-shadow: 1px 1px 0 0 var(--color-olive); }}
    footer {{
      margin-top: 3rem; padding-top: 1rem;
      border-top: 2px solid var(--border); color: var(--muted); font-size: 0.65rem;
    }}
    @keyframes fadeUp {{ from {{ opacity: 0; transform: translateY(4px); }} to {{ opacity: 1; transform: translateY(0); }} }}
  </style>
</head>
<body>

  <header>
    <div class="header-row">
      <div class="dir-path"><span>~/</span>{dir_name}/</div>
      <button id="theme-toggle">dark</button>
    </div>
    <div class="meta-line">{file_count} files &nbsp;·&nbsp; built {built_at}</div>
  </header>

  <div class="breadcrumb">
    {crumbs_html}
  </div>

  <div class="toolbar">
    <button class="filter-btn active" data-filter="all">all</button>
    <button class="filter-btn" data-filter="img">images</button>
    <button class="filter-btn" data-filter="txt">text</button>
    <button class="filter-btn" data-filter="pdf">pdf</button>
    <button class="filter-btn" data-filter="dir">dirs</button>
    <button class="filter-btn" data-filter="other">other</button>
  </div>

  <div class="col-header">
    <div></div><div>name</div><div>modified</div><div>size</div><div>type</div>
  </div>

  <div id="file-list">
    {rows_html}
  </div>
  <div id="empty">no files match this filter</div>

  <div id="lightbox">
    <button id="lb-close">×</button>
    <button id="lb-prev" aria-label="Previous image">‹</button>
    <button id="lb-next" aria-label="Next image">›</button>
    <div id="lb-wrap">
      <img id="lb-img" src="" alt="" />
    </div>
    <div id="lightbox-caption"></div>
    <div id="lb-hint">scroll to zoom &nbsp;·&nbsp; drag to pan &nbsp;·&nbsp; dbl-click to reset &nbsp;·&nbsp; ← → to navigate</div>
  </div>

  <footer>build.py &nbsp;·&nbsp; {dir_name}/ &nbsp;·&nbsp; {built_at}</footer>

  <script>
    // ── Filter buttons ──────────────────────────────────────────────────────
    const rows  = Array.from(document.querySelectorAll(".row"));
    const empty = document.getElementById("empty");

    document.querySelectorAll(".filter-btn").forEach(btn => {{
      btn.addEventListener("click", () => {{
        document.querySelectorAll(".filter-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        const f = btn.dataset.filter;
        let n = 0;
        rows.forEach(r => {{
          const show = f === "all" || r.dataset.type === f;
          r.style.display = show ? "" : "none";
          if (show) n++;
        }});
        empty.style.display = n === 0 ? "block" : "none";
      }});
    }});

    // ── Lightbox with zoom + pan ────────────────────────────────────────────
    const lb      = document.getElementById("lightbox");
    const lbWrap  = document.getElementById("lb-wrap");
    const lbImg   = document.getElementById("lb-img");
    const lbCap   = document.getElementById("lightbox-caption");
    const lbClose = document.getElementById("lb-close");

    // State: current scale and translation of the image wrapper
    let scale = 1;
    let tx = 0, ty = 0;       // translation in px
    let dragging = false;
    let dragStartX, dragStartY, dragOriginX, dragOriginY;

    const SCALE_MIN = 1;
    const SCALE_MAX = 10;
    const SCALE_STEP = 0.12;  // how much each scroll tick zooms

    function applyTransform() {{
      // CSS transform: translate first, then scale.
      // Order matters — translate moves in screen space, scale zooms in place.
      lbWrap.style.transform = `translate(${{tx}}px, ${{ty}}px) scale(${{scale}})`;
      // Show grab cursor when zoomed in
      lbWrap.style.cursor = scale > 1 ? (dragging ? "grabbing" : "grab") : "default";
    }}

    function resetTransform() {{
      scale = 1; tx = 0; ty = 0;
      applyTransform();
    }}

    // ── Scroll to zoom ──────────────────────────────────────────────────────
    //
    // The goal is "zoom toward the cursor" — the point under the mouse
    // should stay fixed as scale changes. To do this we need to adjust
    // the translation so the image appears to grow/shrink around the
    // cursor position rather than around the wrapper's top-left corner.
    //
    // Math: if the cursor is at (mx, my) relative to the wrapper center,
    // and scale changes by factor `k`, the translation must shift by
    // (mx * (1 - k), my * (1 - k)) to keep that point stationary.
    //
    lb.addEventListener("wheel", e => {{
      e.preventDefault();

      const direction = e.deltaY < 0 ? 1 : -1;
      const newScale  = Math.min(SCALE_MAX, Math.max(SCALE_MIN, scale + direction * SCALE_STEP * scale));
      const k         = newScale / scale;

      // Cursor position relative to the lightbox center
      const rect = lb.getBoundingClientRect();
      const mx   = e.clientX - rect.left - rect.width  / 2 - tx;
      const my   = e.clientY - rect.top  - rect.height / 2 - ty;

      tx    += mx * (1 - k);
      ty    += my * (1 - k);
      scale  = newScale;

      // If we've zoomed back to 1:1, snap translation back to center
      if (scale <= SCALE_MIN) {{ tx = 0; ty = 0; }}

      applyTransform();
    }}, {{ passive: false }});

    // ── Drag to pan ─────────────────────────────────────────────────────────
    lbWrap.addEventListener("mousedown", e => {{
      if (scale <= 1) return;   // no point panning at 1:1
      e.preventDefault();
      dragging    = true;
      dragStartX  = e.clientX;
      dragStartY  = e.clientY;
      dragOriginX = tx;
      dragOriginY = ty;
      applyTransform();
    }});

    window.addEventListener("mousemove", e => {{
      if (!dragging) return;
      tx = dragOriginX + (e.clientX - dragStartX);
      ty = dragOriginY + (e.clientY - dragStartY);
      applyTransform();
    }});

    window.addEventListener("mouseup", () => {{
      dragging = false;
      applyTransform();
    }});

    // ── Double-click to reset ───────────────────────────────────────────────
    lbWrap.addEventListener("dblclick", resetTransform);

    // ── Open / close / navigate ─────────────────────────────────────────────
    const lbPrev    = document.getElementById("lb-prev");
    const lbNext    = document.getElementById("lb-next");
    const imgRows   = Array.from(document.querySelectorAll('.row[data-lightbox="true"]'));
    let currentIdx  = 0;

    function showImage(idx) {{
      currentIdx = idx;
      const row = imgRows[idx];
      lbImg.src = row.href;
      lbCap.textContent = row.querySelector(".name").textContent;
      resetTransform();
      lbPrev.style.display = idx > 0 ? "" : "none";
      lbNext.style.display = idx < imgRows.length - 1 ? "" : "none";
    }}

    function openLightbox(idx) {{
      showImage(idx);
      lb.classList.add("open");
    }}

    function closeLightbox() {{
      lb.classList.remove("open");
      resetTransform();
      lbImg.src = "";
    }}

    function navPrev() {{ if (currentIdx > 0) showImage(currentIdx - 1); }}
    function navNext() {{ if (currentIdx < imgRows.length - 1) showImage(currentIdx + 1); }}

    imgRows.forEach((row, i) => {{
      row.addEventListener("click", e => {{
        e.preventDefault();
        openLightbox(i);
      }});
    }});

    lbPrev.addEventListener("click", e => {{ e.stopPropagation(); navPrev(); }});
    lbNext.addEventListener("click", e => {{ e.stopPropagation(); navNext(); }});
    lbClose.addEventListener("click", closeLightbox);
    lb.addEventListener("click", e => {{ if (e.target === lb) closeLightbox(); }});
    document.addEventListener("keydown", e => {{
      if (e.key === "Escape") closeLightbox();
      if (e.key === "0" && lb.classList.contains("open")) resetTransform();
      if (lb.classList.contains("open") && e.key === "ArrowLeft") navPrev();
      if (lb.classList.contains("open") && e.key === "ArrowRight") navNext();
    }});

    // ── Theme toggle ─────────────────────────────────────────────────────
    const themeBtn = document.getElementById("theme-toggle");
    function setTheme(dark) {{
      document.documentElement.classList.toggle("dark", dark);
      themeBtn.textContent = dark ? "light" : "dark";
      localStorage.setItem("theme", dark ? "dark" : "light");
    }}
    // Init: check localStorage, fall back to light
    setTheme(localStorage.getItem("theme") === "dark");
    themeBtn.addEventListener("click", () => {{
      setTheme(!document.documentElement.classList.contains("dark"));
    }});
  </script>

</body>
</html>"""


# ── 5. Entry point ─────────────────────────────────────────────────────────────
#
# `if __name__ == "__main__"` is Python's way of saying "only run this
# block if the script was executed directly" — not if it was imported
# as a module by another script. It's boilerplate you'll see everywhere.
#
# `sys.argv` is a list of command-line arguments. sys.argv[0] is always
# the script name itself, so we slice from [1:] to get the real args.
#
def build_dir(root: Path, site_root: Path) -> None:
    """Build index.html for one directory, then recurse into subdirs."""
    entries = scan(root)
    html    = build_html(root, entries, site_root)

    out = root / "index.html"
    out.write_text(html, encoding="utf-8")

    # Indent the output based on depth so the terminal output reads like
    # a tree — purely cosmetic but makes recursive builds easy to follow.
    depth  = len(root.relative_to(site_root).parts)
    indent = "  " * depth
    count  = sum(1 for e in entries if e["type"] != "dir")
    print(f"{indent}built → {out.relative_to(site_root)}  ({count} files)")

    # Recurse into every subdirectory that scan() found.
    # We reuse the entries list rather than hitting the filesystem again.
    for e in entries:
        if e["type"] == "dir":
            subdir = root / e["name"]
            build_dir(subdir, site_root)


def main():
    args  = sys.argv[1:]
    serve = "--serve" in args
    args  = [a for a in args if not a.startswith("--")]  # strip flags, keep paths

    # `Path.cwd()` is the current working directory — equivalent to `pwd`.
    # `.resolve()` converts a relative path like "." or "../photos" to
    # its full absolute path, which we need for correct relative hrefs.
    site_root = Path(args[0]).resolve() if args else Path.cwd()

    if not site_root.is_dir():
        print(f"error: '{site_root}' is not a directory")
        sys.exit(1)

    print(f"building {site_root}/")
    build_dir(site_root, site_root)

    if serve:
        print(f"\nserving at http://localhost:8080")
        os.chdir(site_root)
        # `subprocess.run()` spawns a child process. We pass
        # `sys.executable` instead of the string "python3" so it always
        # uses the exact same Python that's running this script.
        subprocess.run([sys.executable, "-m", "http.server", "8080"])

if __name__ == "__main__":
    main()
