#!/usr/bin/env python3
"""
basicBuild.py — bare-minimum image index generator.

Walks a directory tree and writes an index.html in each folder
listing subdirectories and image files. No CSS, no JS, just HTML.

Usage:
    python3 basicBuild.py                  # scan current directory
    python3 basicBuild.py /path/to/folder  # scan a specific path
"""

import sys
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
#
# Names to skip when scanning directories.
# This is a set (curly braces) — checking "x in IGNORE" is fast.
#
IGNORE = {"index.html", "basicBuild.py", "build.py", ".git", ".DS_Store", "__pycache__"}

# Extensions we treat as images. Everything else gets skipped.
IMAGE_EXTS = {"jpg", "jpeg", "png", "gif", "webp", "avif", "svg"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def is_image(path: Path) -> bool:
    """Check if a file has an image extension."""
    # path.suffix returns ".jpg" — we strip the dot and lowercase it.
    return path.suffix.lstrip(".").lower() in IMAGE_EXTS


def scan(root: Path) -> tuple[list[dict], list[dict]]:
    """
    Scan one directory. Returns (dirs, images) — two separate lists.

    Each item is a dict with just a "name" key. That's all we need
    for the HTML. Keeping it as a dict (instead of a bare string)
    makes it easy to add more fields later if you want.
    """
    dirs = []
    images = []

    # sorted() with a key gives us alphabetical, case-insensitive order.
    # root.iterdir() yields one Path object per item in the directory.
    for item in sorted(root.iterdir(), key=lambda p: p.name.lower()):

        # Skip ignored names and hidden files (names starting with ".")
        if item.name in IGNORE or item.name.startswith("."):
            continue

        if item.is_dir():
            dirs.append({"name": item.name})

        elif item.is_file() and is_image(item):
            images.append({"name": item.name})

    return dirs, images


# ── HTML builder ──────────────────────────────────────────────────────────────
#
# This is where we turn our data into an HTML string.
#
# f-strings (f"...") let you embed Python variables directly:
#   name = "world"
#   f"hello {name}"  →  "hello world"
#
# Triple-quoted f-strings (f"""...""") let you write multi-line strings.
#

def build_html(root: Path, dirs: list[dict], images: list[dict], site_root: Path) -> str:
    """Build the complete HTML string for one directory."""
    dir_name = root.resolve().name

    # ── Breadcrumb ────────────────────────────────────────────────────────
    #
    # If site_root is /photos and root is /photos/2024/june, we want:
    #   photos/ > 2024/ > june/
    #
    # root.relative_to(site_root) gives PosixPath('2024/june')
    # .parts splits that into ('2024', 'june')
    #
    rel_parts = root.relative_to(site_root).parts  # empty tuple at top level
    crumb_names = [site_root.name] + list(rel_parts)
    depth = len(rel_parts)

    # Build breadcrumb links. Each crumb points "up" the right number
    # of directories using "../" repetition.
    crumb_links = []
    for i, name in enumerate(crumb_names):
        levels_up = depth - i
        href = "../" * levels_up  # "" for the current directory
        if i == len(crumb_names) - 1:
            # Last crumb = current dir, no link needed
            crumb_links.append(f"<b>{name}/</b>")
        else:
            crumb_links.append(f'<a href="{href}">{name}/</a>')

    breadcrumb = " &gt; ".join(crumb_links)

    # ── Directory list ────────────────────────────────────────────────────
    #
    # Each directory becomes a list item with a link.
    # The trailing "/" tells the browser it's a directory.
    #
    dir_items = ""
    for d in dirs:
        dir_items += f'  <li><a href="{d["name"]}/">{d["name"]}/</a></li>\n'

    # ── Image list ────────────────────────────────────────────────────────
    #
    # Each image gets a thumbnail (<img> tag) that links to the full file.
    # loading="lazy" tells the browser to only fetch images as they
    # scroll into view — free performance optimization.
    #
    image_items = ""
    for img in images:
        image_items += (
            f'  <li>\n'
            f'    <a href="{img["name"]}">\n'
            f'      <img src="{img["name"]}" alt="{img["name"]}" '
            f'width="200" loading="lazy">\n'
            f'    </a>\n'
            f'    <br>{img["name"]}\n'
            f'  </li>\n'
        )

    # ── Assemble the page ─────────────────────────────────────────────────
    #
    # This is one big f-string. Everything between {curly braces} gets
    # replaced with the Python variable's value. The rest is literal HTML.
    #
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>{dir_name}/</title>
</head>
<body>
  <p>{breadcrumb}</p>
  <h1>{dir_name}/</h1>

  <h2>Folders</h2>
  <ul>
{dir_items}  </ul>

  <h2>Images ({len(images)})</h2>
  <ul>
{image_items}  </ul>
</body>
</html>"""


# ── Recursive builder ─────────────────────────────────────────────────────────
#
# This is the key function: it builds the index.html for one directory,
# then calls itself for each subdirectory. This pattern is called
# "recursion" — a function that calls itself with a smaller problem.
#
# The call chain looks like:
#   build_dir(/photos)
#     → build_dir(/photos/cats)
#       → build_dir(/photos/cats/kittens)
#     → build_dir(/photos/dogs)
#

def build_dir(root: Path, site_root: Path) -> None:
    """Build index.html for `root`, then recurse into subdirectories."""
    dirs, images = scan(root)
    html = build_html(root, dirs, images, site_root)

    # Write the HTML string to a file called index-basic.html in this directory.
    # Path objects support the / operator for joining paths:
    #   Path("/photos") / "index.html"  →  Path("/photos/index.html")
    out = root / "index-basic.html"
    out.write_text(html, encoding="utf-8")

    # Print what we did (indented by depth so it looks like a tree)
    depth = len(root.relative_to(site_root).parts)
    print(f"{'  ' * depth}wrote {out.relative_to(site_root)}  ({len(images)} images)")

    # Now recurse into each subdirectory
    for d in dirs:
        build_dir(root / d["name"], site_root)


# ── Entry point ───────────────────────────────────────────────────────────────
#
# __name__ == "__main__" means "this script was run directly" (not imported).
# sys.argv is the list of command-line arguments:
#   python3 basicBuild.py /photos  →  sys.argv = ["basicBuild.py", "/photos"]
#

if __name__ == "__main__":
    # Use the first argument as the target directory, or current dir if none given
    target = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()

    if not target.is_dir():
        print(f"error: '{target}' is not a directory")
        sys.exit(1)

    print(f"scanning {target}/\n")
    build_dir(target, target)
    print("\ndone!")
