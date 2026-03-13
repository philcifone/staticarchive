# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A zero-dependency, single-file Python static site generator (`build.py`) that creates HTML index pages for file archives. Features directory browsing, image lightbox with zoom/pan, file type filtering, and light/dark theme toggle. All CSS and JS are embedded inline in generated HTML.

## Commands

```bash
# Build index pages recursively from current directory
python3 build.py

# Build from a specific directory
python3 build.py /path/to/folder

# Build and serve locally on http://localhost:8080
python3 build.py --serve
```

There are no tests, linter, or package manager. Output is `index.html` files written into each directory.

## Architecture

Everything lives in `build.py` (~700 lines), organized as:

1. **Config** — `IGNORE` set (dotfiles, system files, build artifacts), file type extension maps
2. **Classification** — `classify(path)` returns `"img"/"txt"/"pdf"/"other"`; `human_size()` for formatting
3. **Scanner** — `scan(root)` collects sorted file/directory metadata dicts
4. **Row renderer** — `render_row(entry, index)` produces one HTML table row with staggered animation
5. **HTML builder** — `build_html(root, entries, site_root)` assembles the full HTML document (breadcrumbs, filter bar, file table, lightbox, theme toggle) with all CSS/JS inlined via Python f-strings
6. **Recursive builder** — `build_dir(root, site_root)` walks subdirectories writing `index.html` in each
7. **Entry point** — `main()` parses CLI args, calls `build_dir()`, optionally starts `http.server`

## Design System

See `STYLE.md` for the full spec. Key points:

- **Neobrutalist** style: no border-radius, 4px offset shadows, border-2 outlines
- **Gruvbox** color palette with CSS variables for light/dark modes
- **Fonts**: Young Serif (headings), Courier Prime (body/mono) — loaded from Google Fonts
- **Interactions**: shadow shrink + translate on hover/active; `.btn-swipe` bottom-fill animation
- CSS braces in f-strings are doubled (`{{`, `}}`) since the HTML is built with Python f-strings

## Key Patterns

- **Single-file deployment**: no dependencies, no build step beyond running the script
- **Breadcrumb paths**: computed from directory depth relative to `site_root`
- **Lightbox zoom**: scroll-toward-cursor math keeps the cursor point fixed during zoom; drag-to-pan only activates when zoomed beyond 1×
- **Lazy loading**: images use native `loading="lazy"`
- **Client-side filtering**: JS shows/hides rows by `data-type` attribute, no server round-trip
