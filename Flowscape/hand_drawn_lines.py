"""
Hand-drawn (sketchy) line generator.

Big idea: a normal computer line is one crisp stroke. To make it look drawn by
hand, we walk from point A to point B and stamp lots of tiny dots along the way.
Each dot is nudged a little off the true line (position jitter) and drawn a little
bigger or smaller (size jitter). All those wobbly dots read as one organic stroke.

Two key concepts:
  - lerp(a, b, t): the point that is fraction `t` of the way from a to b.
                   t=0 -> a, t=1 -> b, t=0.5 -> midpoint.
  - jitter:        small random shifts added to each dot's position and size.
"""

import numpy as np
from PIL import Image, ImageDraw


def lerp(a, b, t):
    """Return the point `t` fraction of the way from a to b (t in 0..1)."""
    return a + (b - a) * t


def draw_textured_line(draw, p0, p1,
                       color=(25, 22, 20),
                       base_size=2.2,     # average dot radius (line thickness)
                       size_jitter=0.7,   # how much the thickness randomly varies
                       offset_jitter=1.3, # how much each dot wanders off the line
                       spacing=1.4):      # gap between stamped dots (smaller = denser)
    """Stamp a wobbly, hand-drawn line of dots from p0 to p1."""
    x0, y0 = p0
    x1, y1 = p1

    # How long is the line? Use it to decide how many dots to stamp.
    length = np.hypot(x1 - x0, y1 - y0)
    steps = max(int(length / spacing), 1)

    for i in range(steps + 1):
        t = i / steps                       # march t from 0 -> 1
        x = lerp(x0, x1, t)                 # true point on the line...
        y = lerp(y0, y1, t)

        # ...then wobble it off-course a little.
        x += np.random.normal(0, offset_jitter)
        y += np.random.normal(0, offset_jitter)

        # Randomly vary the dot size so the stroke thins and thickens.
        r = max(0.5, base_size + np.random.normal(0, size_jitter))

        draw.ellipse([x - r, y - r, x + r, y + r], fill=color)


def draw_square(draw, cx, cy, half, **line_kwargs):
    """Draw one hand-drawn square centered at (cx, cy), reaching `half` out."""
    corners = [
        (cx - half, cy - half),
        (cx + half, cy - half),
        (cx + half, cy + half),
        (cx - half, cy + half),
    ]
    for i in range(4):
        draw_textured_line(draw, corners[i], corners[(i + 1) % 4], **line_kwargs)


def draw_nested_squares(draw, cx, cy, outer_half, rings, gap, **line_kwargs):
    """Draw a set of concentric squares, like one tile in your reference image."""
    for k in range(rings):
        half = outer_half - k * gap
        if half <= 2:
            break
        draw_square(draw, cx, cy, half, **line_kwargs)


def make_background(width, height, path="old_paper_bg.png"):
    """Use the paper texture if it exists, otherwise a plain warm off-white."""
    try:
        bg = Image.open(path).convert("RGB").resize((width, height))
    except FileNotFoundError:
        bg = Image.new("RGB", (width, height), (238, 231, 210))
    return bg


def generate_grid(cols=6, rows=6, tile=170, margin=90, output_path="nested_squares.png"):
    """Recreate the grid-of-concentric-squares look from the reference image."""
    width = margin * 2 + cols * tile
    height = margin * 2 + rows * tile

    img = make_background(width, height)
    draw = ImageDraw.Draw(img)

    for r in range(rows):
        for c in range(cols):
            cx = margin + c * tile + tile // 2
            cy = margin + r * tile + tile // 2

            # Randomize each tile a touch so no two are identical.
            rings = np.random.randint(4, 8)
            outer_half = tile // 2 - np.random.randint(6, 18)
            gap = max(6, outer_half // (rings + 1))

            draw_nested_squares(
                draw, cx, cy, outer_half, rings, gap,
                base_size=1.8,
                size_jitter=0.6,
                offset_jitter=1.1,
                spacing=1.3,
            )

    img.save(output_path, "PNG")
    print(f"Saved: {output_path}  ({width}x{height})")


if __name__ == "__main__":
    generate_grid()
