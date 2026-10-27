"""Render assets/banner-{light,dark}.svg: the animated mlz. lockup.

Colours and the font come from https://mlz.no/brand/ (brand.json and the
font files listed there), so the banner follows the same tokens as mlz.no.
GitHub shows an SVG in a README as an image: it cannot load external fonts,
so Plex Mono 700 is subset to "mlz." and embedded as a data URI. The
background is transparent and the M is cut out with a mask, so the page
behind the banner shows through.

The animation loops every CYCLE seconds: the mark rises in, the M is traced
and cut out, "mlz" is typed behind a gliding cursor and the cursor settles
into the period. The lockup glitches like the letters on mlz.no; then the
period opens back into the cursor, which backspaces the word, the M closes,
the mark lifts away and it starts over. Every element shares the same
cycle, so the timeline below is in seconds and turned into keyframe
percentages. Without animation support (or with reduced motion) every
element sits in its final state.

Positions come from the font's glyph boxes: the ink of "mlz." is centred
on the mark, and the cursor stands on the baseline as tall as the "l", so
it shrinks straight down into the period.

    python3 -m venv .venv && .venv/bin/pip install fonttools brotli
    .venv/bin/python scripts/banner.py
"""

import base64
import io
import json
import urllib.request
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

BRAND = "https://mlz.no/brand/brand.json"
OUT = Path(__file__).resolve().parent.parent / "assets"

W, H = 1280, 240
WORD = "mlz"

# Lockup proportions from BRAND.md: text 0.85× the mark, gap 0.4× the mark.
MARK = 112
SIZE = round(MARK * 0.85)
GAP = round(MARK * 0.4)
ADVANCE = SIZE * (0.6 - 0.03)  # Plex Mono is 600 units wide, tracked -0.03em
LOCKUP = MARK + GAP + ADVANCE * (len(WORD) + 1)
X0 = round((W - LOCKUP) / 2)
Y0 = (H - MARK) // 2
TX = X0 + MARK + GAP
PX = MARK / 32  # one unit of the mark's 32 × 32 grid, in pixels

M_POINTS = "7,25 7,7 11.5,7 16,18.5 20.5,7 25,7 25,25"

# Timeline, in seconds from the start of a cycle.
CYCLE = 7.5
RISE_AT, RISE = 0.1, 0.9  # the mark rises in ("rise" on mlz.no)
TRACE_AT, TRACE = 0.45, 0.8  # the M is drawn ...
CUT_AT, CUT = 0.95, 0.4  # ... and filled while the line finishes
CURSOR_AT = 0.9  # the cursor fades in and blinks once
TYPED = (1.7, 1.84, 2.03)  # each letter; the gaps are uneven, like a hand
GLIDE = 0.07  # the cursor slides to the next cell
SETTLE_AT, SETTLE = 2.4, 0.45  # the cursor shrinks into the period
XFADE = 0.18  # cursor and period crossfade: the glyph is round, the cursor square
GLITCH_AT = 3.6
OPEN_AT = 5.0  # the period opens back into the cursor
GROW = 0.4
DEL_AT, DEL_STEP = 5.75, 0.1  # backspacing, at key-repeat pace
CURSOR_OUT = 6.1
CLOSE_AT = 6.2  # the M closes, then the mark lifts away
LEAVE_AT, LEAVE = 6.35, 0.45

FADE = 0.12  # a smooth blink edge
EASE = "cubic-bezier(0.2, 0.7, 0.2, 1)"  # var(--ease) on mlz.no
EASE_IN = "cubic-bezier(0.7, 0, 0.84, 0)"  # for exits
IN_OUT = "cubic-bezier(0.65, 0, 0.35, 1)"  # a pen stroke: starts and stops gently
HOLD = "step-end"


def fetch(url):
    with urllib.request.urlopen(url) as r:
        return r.read()


def load(url, text):
    """Subset a font to `text`; return a woff2 data URI and each glyph's ink
    box (xMin, yMin, xMax, yMax) in pixels at SIZE, y up from the baseline."""
    font = TTFont(io.BytesIO(fetch(url)))
    options = subset.Options()
    options.flavor = "woff2"
    sub = subset.Subsetter(options)
    sub.populate(text=text)
    sub.subset(font)
    scale = SIZE / font["head"].unitsPerEm
    cmap = font.getBestCmap()
    boxes = {}
    for ch in text:
        g = font["glyf"][cmap[ord(ch)]]
        boxes[ch] = tuple(v * scale for v in (g.xMin, g.yMin, g.xMax, g.yMax))
    buf = io.BytesIO()
    font.flavor = "woff2"
    font.save(buf)
    return "data:font/woff2;base64," + base64.b64encode(buf.getvalue()).decode(), boxes


def layout(boxes):
    """Baseline and cursor box (x offset in the cell, top, width, height)."""
    top = max(b[3] for b in boxes.values())  # the ascender of the l
    base = round(H / 2 + top / 2)  # the ink sits centred on the mark
    width = SIZE * 0.5
    centre = SIZE * 0.3  # the middle of a 600-unit glyph
    return {"base": base, "cursor": (centre - width / 2, base - top, width, top)}


def keyframes(name, frames, timing=None):
    """@keyframes from (seconds, css) pairs; `timing` holds each value by default."""
    rules = []
    for t, css in frames:
        if timing and "animation-timing-function" not in css:
            css += f"; animation-timing-function: {timing}"
        rules.append(f"  {t / CYCLE * 100:.3f}% {{ {css}; }}")
    return f"@keyframes {name} {{\n" + "\n".join(rules) + "\n}"


def ease(css, curve=EASE):
    return f"{css}; animation-timing-function: {curve}"


def fade(t, start, end, dur=FADE, curve="ease-in-out"):
    """Opacity from `start` to `end` over `dur` seconds from `t`."""
    return [(t, ease(f"opacity: {start}", curve)), (t + dur, f"opacity: {end}")]


def letters(base):
    return "".join(
        f'<text class="ch{i}" x="{TX + i * ADVANCE:.2f}" y="{base}">{ch}</text>'
        for i, ch in enumerate(WORD)
    )


def animations(boxes, geo):
    n = len(WORD)
    # Backspacing removes the letters from the end.
    deleted = [DEL_AT + (n - 1 - i) * DEL_STEP for i in range(n)]
    settled = SETTLE_AT + SETTLE
    grown = OPEN_AT + XFADE + GROW

    def at(cell):
        return f"transform: translate({cell * ADVANCE:.2f}px, 0) scale(1, 1)"

    # The cursor's box mapped onto the period glyph (transform-origin 0 0).
    cx, cy, cw, ch = geo["cursor"]
    x0, y0, x1, y1 = boxes["."]
    dot = (f"transform: translate({n * ADVANCE + x0 - cx:.2f}px, {geo['base'] - y1 - cy:.2f}px) "
           f"scale({(x1 - x0) / cw:.4f}, {(y1 - y0) / ch:.4f})")

    lift = 10 / PX  # the mark's transforms are in grid units
    below = f"opacity: 0; transform: translateY({lift:.2f}px) scale(0.96)"
    above = f"opacity: 0; transform: translateY({-lift:.2f}px) scale(0.96)"
    rest = "opacity: 1; transform: translateY(0) scale(1)"

    css = [
        keyframes(
            "mark",
            [
                (0, below),
                (RISE_AT, ease(below)),
                (RISE_AT + RISE, rest),
                (LEAVE_AT, ease(rest, EASE_IN)),
                (LEAVE_AT + LEAVE, above),
                (CYCLE, above),
            ],
            timing=HOLD,
        ),
        keyframes(
            "cut",
            [(0, "opacity: 0")]
            + fade(CUT_AT, 0, 1, CUT, "ease-out")
            + fade(CLOSE_AT, 1, 0, 0.25, EASE)
            + [(CYCLE, "opacity: 0")],
            timing=HOLD,
        ),
        keyframes(
            "trace",
            [
                (0, "opacity: 0; stroke-dashoffset: 100"),
                (TRACE_AT, ease("opacity: 1; stroke-dashoffset: 100", IN_OUT)),
                (TRACE_AT + TRACE, ease("opacity: 1; stroke-dashoffset: 0", "ease-out")),
                (TRACE_AT + TRACE + 0.25, "opacity: 0; stroke-dashoffset: 0"),
                (CYCLE, "opacity: 0; stroke-dashoffset: 0"),
            ],
            timing=HOLD,
        ),
        keyframes(
            "period",
            [(0, "opacity: 0")]
            + fade(settled - XFADE, 0, 1, XFADE, "linear")
            + fade(OPEN_AT, 1, 0, XFADE, "linear")
            + [(CYCLE, "opacity: 0")],
            timing=HOLD,
        ),
        keyframes(
            "cursor-move",
            [(0, at(0))]
            # Each letter appears under the cursor as it glides off it.
            + [f for i, t in enumerate(TYPED) for f in ((t, ease(at(i))), (t + GLIDE, at(i + 1)))]
            + [(SETTLE_AT, ease(at(n))), (settled, dot)]
            + [(OPEN_AT + XFADE, ease(dot)), (grown, at(n))]
            + [
                f
                for k in range(n)
                for f in ((DEL_AT + k * DEL_STEP, ease(at(n - k))), (DEL_AT + k * DEL_STEP + GLIDE, at(n - 1 - k)))
            ]
            + [(CYCLE, at(0))],
            timing=HOLD,
        ),
        keyframes(
            "cursor-blink",
            [(0, "opacity: 0")]
            + fade(CURSOR_AT, 0, 1)
            + fade(CURSOR_AT + 0.35, 1, 0)
            + fade(TYPED[0] - 0.2, 0, 1)
            + fade(settled - XFADE, 1, 0, XFADE, "linear")
            + fade(OPEN_AT, 0, 1, XFADE, "linear")
            + fade(CURSOR_OUT, 1, 0)
            + [(CYCLE, "opacity: 0")],
            timing=HOLD,
        ),
    ]

    # The glitch from mlz.no (hero.css), 1.5× for the banner's size: six
    # stepped frames over 0.4s with a colour split, then a smaller echo.
    burst = [
        (0.0, (-3, -1.5), 3, 1),
        (0.064, (3, 1.5), 3, 1),
        (0.128, (-1.5, 0), 3, 0.75),
        (0.192, (3, -1.5), -3, 1),
        (0.256, (-1.5, 1.5), 1.5, 1),
        (0.32, (0, 0), 0, 1),
        (0.62, (2, -1), -2, 1),
        (0.68, (-1, 0), 1.5, 1),
        (0.74, (0, 0), 0, 1),
    ]
    still = "opacity: 1; transform: translate(0, 0)"
    css.append(
        keyframes(
            "jitter",
            [(0, still)]
            + [(GLITCH_AT + t, f"opacity: {o}; transform: translate({x}px, {y}px)") for t, (x, y), _, o in burst]
            + [(CYCLE, still)],
            timing=HOLD,
        )
    )
    for name, sign in (("ghost-a", 1), ("ghost-b", -1)):
        css.append(
            keyframes(
                name,
                [(0, "opacity: 0; transform: translateX(0)")]
                + [
                    (GLITCH_AT + t, f"opacity: {int(bool(s))}; transform: translateX({s * sign}px)")
                    for t, _, s, _ in burst
                ]
                + [(CYCLE, "opacity: 0; transform: translateX(0)")],
                timing=HOLD,
            )
        )

    for i in range(n):
        css.append(
            keyframes(
                f"ch{i}",
                [(0, "opacity: 0"), (TYPED[i], "opacity: 1"), (deleted[i], "opacity: 0"), (CYCLE, "opacity: 0")],
                timing=HOLD,
            )
        )
        css.append(f".ch{i} {{ animation: ch{i} {CYCLE}s infinite; }}")
    return "\n".join(css)


def svg(c, font, boxes):
    geo = layout(boxes)
    base = geo["base"]
    cx, cy, cw, ch = geo["cursor"]
    period_x = TX + len(WORD) * ADVANCE
    loop = f"{CYCLE}s infinite"
    word = f'{letters(base)}<text class="period" x="{period_x:.2f}" y="{base}">.</text>'
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="mlz.">
<style>
@font-face {{ font-family: "Plex"; font-weight: 700; src: url({font}) format("woff2"); }}
svg {{ shape-rendering: geometricPrecision; text-rendering: geometricPrecision; }}
text {{ font-family: "Plex", ui-monospace, Menlo, monospace; font-weight: 700; font-size: {SIZE}px; fill: {c["fg"]}; }}
.period {{ fill: {c["accent-deep"]}; }}
.ghost-a text {{ fill: {c["accent"]}; }}
.ghost-b text {{ fill: {c["glitch-2"]}; }}
.trace {{ opacity: 0; fill: none; stroke: #000; stroke-width: 1.4; stroke-linejoin: round; stroke-linecap: round; stroke-dasharray: 100; }}
.cursor {{ opacity: 0; fill: {c["accent-deep"]}; transform-box: fill-box; transform-origin: 0 0; }}
.ghost-a, .ghost-b {{ opacity: 0; }}

.mark {{ transform-box: fill-box; transform-origin: center; animation: mark {loop}; }}
.cut {{ animation: cut {loop}; }}
.trace {{ animation: trace {loop}; }}
.period {{ animation: period {loop}; }}
.cursor {{ animation: cursor-move {loop}, cursor-blink {loop}; }}
.glitch {{ animation: jitter {loop}; }}
.ghost-a {{ animation: ghost-a {loop}; }}
.ghost-b {{ animation: ghost-b {loop}; }}

{animations(boxes, geo)}

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

<g transform="translate({X0} {Y0}) scale({PX})">
  <g class="mark">
    <rect x="1" y="1" width="30" height="30" rx="6" fill="{c["fg"]}" mask="url(#m)"/>
  </g>
</g>

<!-- The colour-split layers sit behind the word and jitter with it. -->
<g class="glitch">
  <g class="ghost-a">{word}</g>
  <g class="ghost-b">{word}</g>
  <g class="word">{word}</g>
</g>
<rect class="cursor" x="{TX + cx:.2f}" y="{cy:.2f}" width="{cw:.2f}" height="{ch:.2f}"/>
</svg>
"""


def main():
    brand = json.loads(fetch(BRAND))
    font, boxes = load(brand["fonts"]["mono"]["files"][1], WORD + ".")
    OUT.mkdir(exist_ok=True)
    for theme in ("light", "dark"):
        path = OUT / f"banner-{theme}.svg"
        path.write_text(svg(brand["colors"][theme], font, boxes))
        print(f"{path.relative_to(OUT.parent)}  {path.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
