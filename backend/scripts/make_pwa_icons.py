"""Generate the TripMind AI PWA icon set from the existing brand mark.

Run:  python scripts/make_pwa_icons.py   (from the backend directory)
Writes frontend/img/{favicon-32,apple-touch-icon,icon-192,icon-512,
icon-maskable-512}.png.

Rounded amber gradient tile with the paper-plane path already used in the
navbar, plus a maskable variant (extra padding, full-bleed background) so the
icon is not cropped by Android's adaptive-icon mask.
"""
import os
from PIL import Image, ImageDraw

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BACKEND, "..", "frontend", "img")
os.makedirs(OUT, exist_ok=True)

START = (245, 158, 11)    # --primary
END = (180, 83, 9)        # --gradient-end
SS = 8                     # supersample factor for smooth edges

# navbar brand mark: <path d="M3 11l18-7-7 18-2.5-7.5L3 11z"> in a 24x24 box
PLANE = [(3, 11), (21, 4), (14, 22), (11.5, 14.5)]


def gradient(size, top=START, bottom=END):
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
    draw.polygon(poly, fill=(255, 255, 255, 255))

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
