"""Generate the TripMind AI PWA icon set from the current brand mark.

Run:  python scripts/make_pwa_icons.py   (from the backend directory)
Writes frontend/img/{favicon-32,apple-touch-icon,icon-192,icon-512,
icon-maskable-512}.png.

Deep-ink tile with the paper-plane mark used across the site, a soft gold glow
behind it and a dashed route arc that echoes the logo lockup. A maskable
variant (full bleed, more padding) is generated so Android's adaptive-icon mask
cannot crop the mark.
"""
import os
from PIL import Image, ImageDraw, ImageFilter

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BACKEND, "..", "frontend", "img")
os.makedirs(OUT, exist_ok=True)

INK_TOP = (11, 53, 66)       # --ink lifted for a little depth
INK_BOTTOM = (6, 32, 43)     # --ink
GOLD = (240, 160, 30)        # --gold
GOLD_SOFT = (255, 212, 137)  # --gold-soft
PLANE_FOLD = (255, 233, 197)
SS = 8                       # supersample factor for smooth edges

# The brand plane (24x24 box) as used in the navbar and the splash screen.
PLANE = [(3, 11), (21, 4), (14, 22), (11.5, 14.5)]


def gradient(size, top=INK_TOP, bottom=INK_BOTTOM):
    img = Image.new("RGB", (1, size[1]))
    px = img.load()
    for y in range(size[1]):
        t = y / max(1, size[1] - 1)
        px[0, y] = tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
    return img.resize(size, Image.BICUBIC)


def plane_polygon(size, inset_ratio):
    """The brand plane, scaled into `size` with an inset on each side."""
    inner = size * (1 - 2 * inset_ratio)
    off = size * inset_ratio
    s = inner / 24.0
    return [(off + x * s, off + y * s) for x, y in PLANE]


def make(size, name, rounded=True, inset=0.22, bleed=False):
    big = size * SS
    base = gradient((big, big)).convert("RGBA")

    # Soft gold glow behind the mark so the tile is not a flat block at 32px.
    glow = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    cx, cy = big * 0.5, big * 0.46
    gd.ellipse([cx - big * 0.34, cy - big * 0.34, cx + big * 0.34, cy + big * 0.34],
               fill=GOLD + (54,))
    glow = glow.filter(ImageFilter.GaussianBlur(big * 0.07))
    base = Image.alpha_composite(base, glow)

    # Dashed route arc across the lower third.
    arc = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    ad = ImageDraw.Draw(arc)
    box = [big * 0.10, big * 0.60, big * 0.90, big * 0.98]
    steps = 26
    for i in range(steps):
        if i % 2:
            continue
        t0, t1 = i / steps, (i + 0.9) / steps
        x0 = box[0] + (box[2] - box[0]) * t0
        x1 = box[0] + (box[2] - box[0]) * t1
        ad.line([x0, box[3] - (x0 - box[0]) * 0.16, x1, box[3] - (x1 - box[0]) * 0.16],
                fill=GOLD + (120,), width=max(1, int(big * 0.012)))
    base = Image.alpha_composite(base, arc)

    mask = Image.new("L", (big, big), 0)
    md = ImageDraw.Draw(mask)
    if rounded and not bleed:
        md.rounded_rectangle([0, 0, big - 1, big - 1], radius=int(big * 0.22), fill=255)
    else:
        md.rectangle([0, 0, big - 1, big - 1], fill=255)
    base.putalpha(mask)

    # Paper plane, nudged up-left so it reads as flying (as in the navbar).
    draw = ImageDraw.Draw(base)
    poly = plane_polygon(big, inset)
    shift_x = -big * 0.02
    shift_y = -big * 0.03
    poly = [(x + shift_x, y + shift_y) for x, y in poly]
    draw.polygon(poly, fill=GOLD_SOFT + (255,))
    # Fold: a darker inner triangle gives the plane a little dimension.
    draw.polygon([poly[0], poly[3], (poly[1][0] * 0.62 + poly[0][0] * 0.38,
                                     poly[1][1] * 0.62 + poly[0][1] * 0.38)],
                 fill=GOLD + (255,))

    img = base.resize((size, size), Image.LANCZOS)
    path = os.path.join(OUT, name)
    img.save(path, "PNG", optimize=True)
    print("%-26s %4dx%-4d %6d bytes" % (name, size, size, os.path.getsize(path)))


make(32, "favicon-32.png")
# iOS masks apple-touch-icons itself, so it must be full-bleed (transparent
# corners render as black squares there).
make(180, "apple-touch-icon.png", rounded=False, inset=0.26, bleed=True)
make(192, "icon-192.png")
make(512, "icon-512.png")
# maskable: full-bleed background, smaller plane so the mask can crop freely
make(512, "icon-maskable-512.png", rounded=False, inset=0.30, bleed=True)
