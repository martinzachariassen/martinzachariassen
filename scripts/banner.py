# /// script
# requires-python = ">=3.9"
# dependencies = ["fonttools", "brotli"]
# ///
"""Render assets/banner-{light,dark}.svg: the animated mlz. lockup.

GitHub shows an SVG in a README as an image, which runs no JavaScript and
loads no external fonts. So the animation is plain CSS inside the SVG, and
Plex Mono 700 is cut down to "mlz." and embedded. Colours and the font come
from https://mlz.no/brand/brand.json, the same tokens as mlz.no.

One loop of the animation:

  1. the mark rises in and its M is traced, then cut out of the square
  2. a cursor blinks, then types "mlz", gliding one cell per letter
  3. the cursor shrinks into the period and the lockup holds
  4. the period opens back into the cursor, which backspaces the word
  5. the M closes, the mark lifts away and the loop starts over

With reduced motion (or no animation support) the lockup sits still.

    uv run scripts/banner.py

or, without uv:

    python3 -m venv .venv && .venv/bin/pip install fonttools brotli
    .venv/bin/python scripts/banner.py
"""

import base64
import io
import json
import urllib.request
from pathlib import Path
from typing import NamedTuple

from fontTools import subset
from fontTools.ttLib import TTFont

BRAND_URL = "https://mlz.no/brand/brand.json"
OUT = Path(__file__).resolve().parent.parent / "assets"


# --- Layout, in pixels -------------------------------------------------------

WIDTH, HEIGHT = 1280, 240
WORD = "mlz"

# Lockup proportions from BRAND.md: text 0.85× the mark, gap 0.4× the mark.
MARK = 112
FONT_SIZE = round(MARK * 0.85)
GAP = round(MARK * 0.4)
ADVANCE = FONT_SIZE * (0.6 - 0.03)  # one cell: Plex Mono is 600 units wide, tracked -0.03em

# "mlz." plus the mark, centred in the banner.
LOCKUP = MARK + GAP + ADVANCE * (len(WORD) + 1)
MARK_X = round((WIDTH - LOCKUP) / 2)
MARK_Y = (HEIGHT - MARK) // 2
TEXT_X = MARK_X + MARK + GAP

# The mark is drawn on a 32 × 32 grid, scaled up to MARK pixels.
GRID = MARK / 32
M_POINTS = "7,25 7,7 11.5,7 16,18.5 20.5,7 25,7 25,25"
LIFT = 10 / GRID  # how far the mark rises in and lifts away: 10px, in grid units


# --- Timeline, in seconds from the start of a loop ---------------------------

LOOP = 6.1

RISE_AT, RISE = 0.1, 0.9  # the mark rises in ("rise" on mlz.no)
TRACE_AT, TRACE = 0.45, 0.8  # the M is drawn ...
TRACE_GONE = TRACE_AT + TRACE + 0.25  # ... and its line fades away
CUT_AT, CUT = 0.95, 0.4  # the M is cut out while the line finishes

CURSOR_AT, BLINK = 0.9, 0.35  # the cursor fades in and blinks once
TYPED = (1.7, 1.84, 2.03)  # each letter; the gaps are uneven, like a hand
CURSOR_BACK = TYPED[0] - 0.2  # the cursor is back just before the first letter
GLIDE = 0.07  # the cursor slides to the next cell

SETTLE_AT, SETTLE = 2.4, 0.45  # the cursor shrinks into the period
SETTLED = SETTLE_AT + SETTLE
XFADE = 0.18  # cursor and period crossfade: the glyph is round, the cursor square

OPEN_AT, GROW = 3.6, 0.4  # the period opens back into the cursor
GROWN = OPEN_AT + XFADE + GROW
DELETE_AT, DELETE_STEP = 4.35, 0.1  # backspacing, at key-repeat pace
CURSOR_OUT = 4.7

CLOSE_AT, CLOSE = 4.8, 0.25  # the M closes ...
LEAVE_AT, LEAVE = 4.95, 0.45  # ... and the mark lifts away

FADE = 0.12  # a soft blink edge
EASE = "cubic-bezier(0.2, 0.7, 0.2, 1)"  # var(--ease) on mlz.no
EASE_IN = "cubic-bezier(0.7, 0, 0.84, 0)"  # for exits
PEN = "cubic-bezier(0.65, 0, 0.35, 1)"  # a pen stroke: starts and stops gently


# --- Font --------------------------------------------------------------------


class Ink(NamedTuple):
    """A glyph's ink box in pixels, y up from the baseline."""

    left: float
    bottom: float
    right: float
    top: float


class Rect(NamedTuple):
    """A box in SVG pixels, y down."""

    x: float
    y: float
    width: float
    height: float


def fetch(url):
    with urllib.request.urlopen(url) as response:
        return response.read()


def load_font(url, text):
    """Cut the font down to `text`. Return it as a woff2 data URI, with the
    ink box of each character at FONT_SIZE."""
    # Keep the font's own timestamp, so rerunning the script changes nothing.
    font = TTFont(io.BytesIO(fetch(url)), recalcTimestamp=False)
    options = subset.Options()
    options.flavor = "woff2"
    subsetter = subset.Subsetter(options)
    subsetter.populate(text=text)
    subsetter.subset(font)

    scale = FONT_SIZE / font["head"].unitsPerEm
    cmap = font.getBestCmap()
    ink = {}
    for char in text:
        glyph = font["glyf"][cmap[ord(char)]]
        ink[char] = Ink(*(v * scale for v in (glyph.xMin, glyph.yMin, glyph.xMax, glyph.yMax)))

    buf = io.BytesIO()
    font.flavor = "woff2"
    font.save(buf)
    return "data:font/woff2;base64," + base64.b64encode(buf.getvalue()).decode(), ink


def place_text(ink):
    """The baseline that centres the ink of the word on the mark, and the
    cursor: as tall as the "l", standing on the baseline in the first cell
    (its x is relative to TEXT_X)."""
    tallest = max(box.top for box in ink.values())  # the ascender of the l
    baseline = round(HEIGHT / 2 + tallest / 2)
    width = FONT_SIZE * 0.5
    centre = FONT_SIZE * 0.3  # the middle of a 600-unit cell
    return baseline, Rect(centre - width / 2, baseline - tallest, width, tallest)


# --- CSS keyframes -----------------------------------------------------------
#
# Frames are (seconds, css) pairs. A frame holds its value until the next one,
# unless it is wrapped in ease() or fade(), which animate towards the next one.


def ease(css, curve=EASE):
    return f"{css}; animation-timing-function: {curve}"


def fade(t, start, end, duration=FADE, curve="ease-in-out"):
    """Opacity from `start` to `end`, over `duration` seconds from `t`."""
    return [(t, ease(f"opacity: {start}", curve)), (t + duration, f"opacity: {end}")]


def keyframes(name, frames):
    rules = []
    for t, css in frames:
        if "animation-timing-function" not in css:
            css += "; animation-timing-function: step-end"
        rules.append(f"  {t / LOOP * 100:.3f}% {{ {css}; }}")
    return f"@keyframes {name} {{\n" + "\n".join(rules) + "\n}"


def animations(ink, baseline, cursor):
    """The frames of every animation in the banner, by name."""
    n = len(WORD)

    # The mark.
    below = f"opacity: 0; transform: translateY({LIFT:.2f}px) scale(0.96)"
    above = f"opacity: 0; transform: translateY({-LIFT:.2f}px) scale(0.96)"
    rest = "opacity: 1; transform: translateY(0) scale(1)"
    mark = [
        (0, below),
        (RISE_AT, ease(below)),
        (RISE_AT + RISE, rest),
        (LEAVE_AT, ease(rest, EASE_IN)),
        (LEAVE_AT + LEAVE, above),
        (LOOP, above),
    ]

    # The M: a line is traced around it, then the shape is cut out.
    trace = [
        (0, "opacity: 0; stroke-dashoffset: 100"),
        (TRACE_AT, ease("opacity: 1; stroke-dashoffset: 100", PEN)),
        (TRACE_AT + TRACE, ease("opacity: 1; stroke-dashoffset: 0", "ease-out")),
        (TRACE_GONE, "opacity: 0; stroke-dashoffset: 0"),
        (LOOP, "opacity: 0; stroke-dashoffset: 0"),
    ]
    cut = [
        (0, "opacity: 0"),
        *fade(CUT_AT, 0, 1, CUT, "ease-out"),
        *fade(CLOSE_AT, 1, 0, CLOSE, EASE),
        (LOOP, "opacity: 0"),
    ]

    # Each letter shows from the moment it is typed until it is backspaced,
    # which removes the letters from the end.
    letters = {
        f"ch{i}": [
            (0, "opacity: 0"),
            (TYPED[i], "opacity: 1"),
            (DELETE_AT + (n - 1 - i) * DELETE_STEP, "opacity: 0"),
            (LOOP, "opacity: 0"),
        ]
        for i in range(n)
    }

    # The cursor moves from cell to cell, and squeezes into the period's ink.
    def at(cell):
        return f"transform: translate({cell * ADVANCE:.2f}px, 0) scale(1, 1)"

    def glide(t, src, dst):
        return [(t, ease(at(src))), (t + GLIDE, at(dst))]

    dot = ink["."]
    on_dot = (
        f"transform: translate({n * ADVANCE + dot.left - cursor.x:.2f}px, {baseline - dot.top - cursor.y:.2f}px) "
        f"scale({(dot.right - dot.left) / cursor.width:.4f}, {(dot.top - dot.bottom) / cursor.height:.4f})"
    )
    cursor_move = [
        (0, at(0)),
        # Each letter appears under the cursor as it glides off it.
        *[frame for i, t in enumerate(TYPED) for frame in glide(t, i, i + 1)],
        (SETTLE_AT, ease(at(n))),
        (SETTLED, on_dot),
        (OPEN_AT + XFADE, ease(on_dot)),
        (GROWN, at(n)),
        *[frame for k in range(n) for frame in glide(DELETE_AT + k * DELETE_STEP, n - k, n - 1 - k)],
        (LOOP, at(0)),
    ]

    # The cursor and the period crossfade where one turns into the other.
    cursor_blink = [
        (0, "opacity: 0"),
        *fade(CURSOR_AT, 0, 1),
        *fade(CURSOR_AT + BLINK, 1, 0),
        *fade(CURSOR_BACK, 0, 1),
        *fade(SETTLED - XFADE, 1, 0, XFADE, "linear"),
        *fade(OPEN_AT, 0, 1, XFADE, "linear"),
        *fade(CURSOR_OUT, 1, 0),
        (LOOP, "opacity: 0"),
    ]
    period = [
        (0, "opacity: 0"),
        *fade(SETTLED - XFADE, 0, 1, XFADE, "linear"),
        *fade(OPEN_AT, 1, 0, XFADE, "linear"),
        (LOOP, "opacity: 0"),
    ]

    return {
        "mark": mark,
        "cut": cut,
        "trace": trace,
        "period": period,
        "cursor-move": cursor_move,
        "cursor-blink": cursor_blink,
        **letters,
    }


# --- SVG ---------------------------------------------------------------------


def svg(colors, font, ink):
    """The banner in one theme's `colors`."""
    baseline, cursor = place_text(ink)
    loop = f"{LOOP}s infinite"
    css = "\n".join(keyframes(name, frames) for name, frames in animations(ink, baseline, cursor).items())

    cells = [(f"ch{i}", char) for i, char in enumerate(WORD)] + [("period", ".")]
    word = "".join(
        f'<text class="{cls}" x="{TEXT_X + i * ADVANCE:.2f}" y="{baseline}">{char}</text>'
        for i, (cls, char) in enumerate(cells)
    )
    letters = "\n".join(f".ch{i} {{ animation: ch{i} {loop}; }}" for i in range(len(WORD)))

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" width="{WIDTH}" height="{HEIGHT}" role="img" aria-label="mlz.">
<style>
@font-face {{ font-family: "Plex"; font-weight: 700; src: url({font}) format("woff2"); }}
svg {{ shape-rendering: geometricPrecision; text-rendering: geometricPrecision; }}
text {{ font-family: "Plex", ui-monospace, Menlo, monospace; font-weight: 700; font-size: {FONT_SIZE}px; fill: {colors["fg"]}; }}
.period {{ fill: {colors["accent-deep"]}; }}
.trace {{ opacity: 0; fill: none; stroke: #000; stroke-width: 1.4; stroke-linejoin: round; stroke-linecap: round; stroke-dasharray: 100; }}
.cursor {{ opacity: 0; fill: {colors["accent-deep"]}; transform-box: fill-box; transform-origin: 0 0; }}

.mark {{ transform-box: fill-box; transform-origin: center; animation: mark {loop}; }}
.cut {{ animation: cut {loop}; }}
.trace {{ animation: trace {loop}; }}
.period {{ animation: period {loop}; }}
.cursor {{ animation: cursor-move {loop}, cursor-blink {loop}; }}
{letters}

{css}

@media (prefers-reduced-motion: reduce) {{
  * {{ animation: none !important; }}
}}
</style>
<defs>
  <!-- White keeps the square, black cuts it: the M and its tracing line. -->
  <mask id="m" maskUnits="userSpaceOnUse" x="0" y="0" width="32" height="32">
    <rect x="1" y="1" width="30" height="30" rx="6" fill="#fff"/>
    <polygon class="cut" points="{M_POINTS}" fill="#000"/>
    <polygon class="trace" points="{M_POINTS}" pathLength="100"/>
  </mask>
</defs>

<g transform="translate({MARK_X} {MARK_Y}) scale({GRID})">
  <g class="mark">
    <rect x="1" y="1" width="30" height="30" rx="6" fill="{colors["fg"]}" mask="url(#m)"/>
  </g>
</g>

<g class="word">{word}</g>
<rect class="cursor" x="{TEXT_X + cursor.x:.2f}" y="{cursor.y:.2f}" width="{cursor.width:.2f}" height="{cursor.height:.2f}"/>
</svg>
"""


def main():
    brand = json.loads(fetch(BRAND_URL))
    font, ink = load_font(brand["fonts"]["mono"]["files"][1], WORD + ".")
    OUT.mkdir(exist_ok=True)
    for theme in ("light", "dark"):
        path = OUT / f"banner-{theme}.svg"
        path.write_text(svg(brand["colors"][theme], font, ink))
        print(f"{path.relative_to(OUT.parent)}  {path.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
