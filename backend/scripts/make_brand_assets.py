"""Generate TripMind AI brand artwork (no external image dependencies).

Run:  python scripts/make_brand_assets.py   (from the backend directory)

Writes
  frontend/img/hero-journey.jpg          2400x1350 cinematic landing hero
  frontend/img/pagehead-journey.jpg      2000x900  quiet backdrop for inner pages
  frontend/img/splash/splash-*.jpg       iOS launch images (portrait, branded)

Everything is drawn procedurally with Pillow so the look is consistent, the
repo stays self-contained/offline, and the assets are reproducible.

Art direction: first light over a mountain road — the "journey begins" moment.
Deep indigo sky, amber horizon, atmospheric ridge layers, a lit road curving
into the distance, and a dotted flight path.
"""
import math
import os
import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG = os.path.join(BACKEND, "..", "frontend", "img")
SPLASH = os.path.join(IMG, "splash")
os.makedirs(SPLASH, exist_ok=True)

FONT_DIR = r"C:\Windows\Fonts"
FONT_BOLD = os.path.join(FONT_DIR, "segoeuib.ttf")
FONT_SEMI = os.path.join(FONT_DIR, "seguisb.ttf")


def font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


# ----------------------------------------------------------------- gradients
def vgrad(size, stops):
    """Vertical gradient. stops = [(pos 0..1, (r,g,b)), ...]"""
    w, h = size
    strip = Image.new("RGB", (1, h))
    px = strip.load()
    stops = sorted(stops, key=lambda s: s[0])
    for y in range(h):
        t = y / max(1, h - 1)
        lo, hi = stops[0], stops[-1]
        for i in range(len(stops) - 1):
            if stops[i][0] <= t <= stops[i + 1][0]:
                lo, hi = stops[i], stops[i + 1]
                break
        span = max(1e-6, hi[0] - lo[0])
        k = min(1.0, max(0.0, (t - lo[0]) / span))
        k = k * k * (3 - 2 * k)  # smoothstep
        px[0, y] = tuple(round(lo[1][i] + (hi[1][i] - lo[1][i]) * k) for i in range(3))
    return strip.resize((w, h), Image.BICUBIC)


def glow(size, center, radius, color, strength=1.0):
    """Soft radial light, returned as an RGBA layer to be alpha-composited."""
    layer = Image.new("L", size, 0)
    d = ImageDraw.Draw(layer)
    cx, cy = center
    steps = 26
    for i in range(steps, 0, -1):
        r = radius * i / steps
        a = int(255 * strength * (1 - i / steps) ** 2.1)
        d.ellipse([cx - r, cy - r * 0.86, cx + r, cy + r * 0.86], fill=a)
    layer = layer.filter(ImageFilter.GaussianBlur(radius * 0.12))
    out = Image.new("RGBA", size, color + (0,))
    out.putalpha(layer)
    return out


def ridge(size, base_y, amp, seed, fill, blur=0.0, octaves=4):
    """A mountain silhouette: summed sines with a deterministic seed."""
    w, h = size
    rnd = random.Random(seed)
    phases = [rnd.uniform(0, math.tau) for _ in range(octaves)]
    freqs = [1.1 + i * 0.85 for i in range(octaves)]
    weights = [1.0 / (i + 1.35) for i in range(octaves)]
    total = sum(weights)
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pts = []
    for x in range(0, w + 8, 8):
        u = x / w
        y = base_y
        for f, p, wt in zip(freqs, phases, weights):
            y -= amp * wt / total * math.sin(u * math.tau * f + p)
        # taper the ridge toward the edges so it sits inside the frame
        pts.append((x, y))
    poly = pts + [(w, h), (0, h)]
    d.polygon(poly, fill=fill)
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(blur))
    return img


def bezier(p0, p1, p2, steps=260):
    out = []
    for i in range(steps + 1):
        t = i / steps
        u = 1 - t
        out.append((u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
                    u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1]))
    return out


def light_road(size, pts, width_start, width_end, color, blur=1.2):
    """A tapering lit road: draw as many short segments to fake perspective."""
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    n = len(pts)
    for i in range(n - 1):
        t = i / (n - 1)
        wdt = width_start + (width_end - width_start) * t
        x0, y0 = pts[i]
        x1, y1 = pts[i + 1]
        a = int(30 + 150 * (1 - t) ** 1.4)
        d.line([x0, y0, x1, y1], fill=color + (a,), width=max(1, int(wdt)))
    if blur:
        layer = layer.filter(ImageFilter.GaussianBlur(blur))
    return layer


def dotted_path(size, pts, color, width=3, gap=26, dash=10):
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    acc, on = 0.0, True
    for i in range(len(pts) - 1):
        x0, y0 = pts[i]
        x1, y1 = pts[i + 1]
        seg = math.hypot(x1 - x0, y1 - y0)
        if seg == 0:
            continue
        steps = max(1, int(seg / 3))
        for s in range(steps):
            t0 = s / steps
            t1 = (s + 1) / steps
            acc += seg / steps
            if on:
                d.line([x0 + (x1 - x0) * t0, y0 + (y1 - y0) * t0,
                        x0 + (x1 - x0) * t1, y0 + (y1 - y0) * t1], fill=color, width=width)
            if acc >= gap:
                on = not on
                acc = 0
    return layer


def stars(size, count, seed, y_max_ratio=0.55):
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    rnd = random.Random(seed)
    w, h = size
    for _ in range(count):
        x = rnd.uniform(0, w)
        y = rnd.uniform(0, h * y_max_ratio)
        r = rnd.choice([1, 1, 1, 1.6, 2.1])
        a = int(rnd.uniform(40, 165) * (1 - y / (h * y_max_ratio)) ** 0.6)
        d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 246, 232, a))
    return layer.filter(ImageFilter.GaussianBlur(0.4))


def cloud_bands(size, bands, seed):
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    rnd = random.Random(seed)
    w, h = size
    for y_ratio, thick, color, alpha in bands:
        y = h * y_ratio
        for _ in range(7):
            cy = y + rnd.uniform(-thick, thick)
            cx = rnd.uniform(-0.1 * w, 1.1 * w)
            rw = rnd.uniform(0.14, 0.42) * w
            rh = thick * rnd.uniform(0.35, 1.0)
            d.ellipse([cx - rw, cy - rh, cx + rw, cy + rh],
                      fill=color + (int(alpha * rnd.uniform(0.5, 1.0)),))
    return layer.filter(ImageFilter.GaussianBlur(size[0] * 0.012))


def birds(size, spots, seed):
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    rnd = random.Random(seed)
    w, h = size
    for (bx, by, s) in spots:
        for k in range(3):
            jx = bx + rnd.uniform(-w * 0.05, w * 0.05)
            jy = by + rnd.uniform(-h * 0.05, h * 0.05)
            ww = s * rnd.uniform(0.7, 1.3)
            hh = ww * 0.55
            d.arc([jx - ww, jy - hh, jx, jy + hh * 0.35], 200, 340, fill=(12, 26, 34, 190), width=2)
            d.arc([jx, jy - hh, jx + ww, jy + hh * 0.35], 200, 340, fill=(12, 26, 34, 190), width=2)
    return layer


def finish(img, size, out_path, vignette=0.5, grain=7, quality=88):
    """Vignette + fine grain, then save."""
    w, h = size
    if vignette:
        vig = Image.new("L", (w, h), 0)
        dv = ImageDraw.Draw(vig)
        steps = 30
        for i in range(steps):
            t = i / steps
            inset = -int(min(w, h) * 0.34 * (1 - t))
            dv.ellipse([inset, inset, w - inset, h - inset],
                       outline=int(255 * (t ** 2.2) * vignette), width=int(min(w, h) * 0.012) + 2)
        vig = vig.filter(ImageFilter.GaussianBlur(min(w, h) * 0.05))
        dark = Image.new("RGBA", (w, h), (4, 14, 20, 255))
        dark.putalpha(vig)
        img = Image.alpha_composite(img, dark)
    if grain:
        noise = Image.effect_noise((w, h), grain).convert("L")
        noise = noise.point(lambda v: 128 + (v - 128) // 2)
        img = Image.blend(img.convert("RGB"), Image.merge("RGB", (noise, noise, noise)), 0.045)
    path = os.path.join(IMG, out_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.convert("RGB").save(path, "JPEG", quality=quality, optimize=True, progressive=True)
    print("%-34s %5dx%-5d %8d bytes" % (out_path, w, h, os.path.getsize(path)))


# --------------------------------------------------------------------- hero
def build_hero(w=2400, h=1350):
    size = (w, h)
    horizon = h * 0.615

    sky = vgrad(size, [
        (0.00, (9, 21, 42)),
        (0.26, (16, 47, 74)),
        (0.44, (33, 86, 104)),
        (0.56, (128, 106, 88)),
        (0.615, (240, 160, 30)),
        (0.66, (255, 206, 128)),
        (0.78, (24, 52, 62)),
        (1.00, (6, 24, 32)),
    ]).convert("RGBA")

    img = Image.alpha_composite(sky, stars(size, 260, seed=7))

    # sun sitting just above the ridge line
    img = Image.alpha_composite(img, glow(size, (w * 0.68, horizon - h * 0.035), w * 0.30, (255, 208, 120), 0.95))
    img = Image.alpha_composite(img, glow(size, (w * 0.68, horizon - h * 0.03), w * 0.055, (255, 246, 226), 1.0))
    sun = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(sun).ellipse([w * 0.655, horizon - h * 0.085, w * 0.705, horizon - h * 0.035],
                                fill=(255, 250, 238, 240))
    img = Image.alpha_composite(img, sun.filter(ImageFilter.GaussianBlur(2.5)))

    img = Image.alpha_composite(img, cloud_bands(size, [
        (0.30, h * 0.020, (255, 196, 140), 70),
        (0.40, h * 0.026, (255, 224, 178), 60),
        (0.50, h * 0.018, (255, 176, 120), 55),
        (0.575, h * 0.012, (255, 236, 205), 70),
    ], seed=11))

    # atmospheric ridge layers, far -> near
    img = Image.alpha_composite(img, ridge(size, horizon + h * 0.005, h * 0.075, 11, (58, 96, 116, 205), blur=1.6))
    img = Image.alpha_composite(img, ridge(size, horizon + h * 0.055, h * 0.085, 23, (34, 68, 88, 235), blur=1.0))
    img = Image.alpha_composite(img, ridge(size, horizon + h * 0.115, h * 0.070, 37, (17, 42, 58, 250), blur=0.6))
    img = Image.alpha_composite(img, ridge(size, h * 0.86, h * 0.055, 51, (9, 26, 36, 255), blur=0.4))

    # the lit road, curving from the bottom-left into the sunrise
    road = bezier((w * 0.16, h * 1.04), (w * 0.52, h * 0.80), (w * 0.665, horizon - h * 0.012))
    img = Image.alpha_composite(img, light_road(size, road, 3, 26, (255, 214, 150), blur=2.0))
    img = Image.alpha_composite(img, light_road(size, road, 2, 7, (255, 246, 228), blur=1.0))

    # dotted flight path arcing across the sky + a small plane glyph
    arc = bezier((w * 0.06, h * 0.30), (w * 0.36, h * 0.03), (w * 0.90, h * 0.20))
    img = Image.alpha_composite(img, dotted_path(size, arc, (255, 226, 186, 120), width=3, gap=30, dash=1))
    plane = Image.new("RGBA", size, (0, 0, 0, 0))
    dp = ImageDraw.Draw(plane)
    px, py = w * 0.585, h * 0.145
    s = w * 0.017
    dp.polygon([(px + s * 2.0, py), (px - s * 1.4, py + s * 0.85), (px - s * 1.05, py - s * 0.28),
                (px - s * 0.2, py - s * 0.2)], fill=(255, 248, 236, 235))
    img = Image.alpha_composite(img, plane.filter(ImageFilter.GaussianBlur(0.7)))

    img = Image.alpha_composite(img, birds(size, [
        (w * 0.20, h * 0.20, w * 0.011), (w * 0.245, h * 0.245, w * 0.009), (w * 0.29, h * 0.185, w * 0.008),
    ], seed=3))
    return img


# --------------------------------------------------------------- page head
def build_pagehead(w=2000, h=900):
    size = (w, h)
    horizon = h * 0.70
    sky = vgrad(size, [
        (0.00, (7, 26, 40)),
        (0.34, (12, 52, 70)),
        (0.60, (26, 84, 98)),
        (0.70, (86, 132, 138)),
        (0.78, (14, 40, 52)),
        (1.00, (6, 20, 28)),
    ]).convert("RGBA")
    img = Image.alpha_composite(sky, stars(size, 120, seed=5, y_max_ratio=0.5))
    img = Image.alpha_composite(img, glow(size, (w * 0.24, horizon - h * 0.10), w * 0.34, (255, 198, 128), 0.7))
    img = Image.alpha_composite(img, cloud_bands(size, [
        (0.28, h * 0.030, (214, 236, 240), 46),
        (0.44, h * 0.022, (255, 220, 180), 40),
    ], seed=19))
    # coastline / headland layers
    img = Image.alpha_composite(img, ridge(size, horizon, h * 0.10, 71, (40, 82, 96, 190), blur=2.2))
    img = Image.alpha_composite(img, ridge(size, horizon + h * 0.09, h * 0.08, 83, (18, 48, 62, 235), blur=1.2))
    img = Image.alpha_composite(img, ridge(size, h * 0.95, h * 0.06, 97, (7, 22, 32, 255), blur=0.5))
    # water sheen under the light
    water = Image.new("RGBA", size, (0, 0, 0, 0))
    dw = ImageDraw.Draw(water)
    for i in range(70):
        y = horizon + h * 0.02 + i * (h * 0.30 / 70)
        t = i / 70
        ln = w * (0.05 + 0.20 * t) * (0.4 + 0.6 * ((i * 37) % 11) / 11)
        x = w * 0.24 - ln / 2 + (w * 0.012 if i % 2 else 0)
        dw.line([x, y, x + ln, y], fill=(255, 224, 178, int(46 * (1 - t))), width=2)
    img = Image.alpha_composite(img, water.filter(ImageFilter.GaussianBlur(1.4)))
    arc = bezier((w * 0.10, h * 0.34), (w * 0.50, h * 0.06), (w * 0.94, h * 0.26))
    img = Image.alpha_composite(img, dotted_path(size, arc, (226, 240, 244, 84), width=3, gap=34, dash=1))
    return img


# ------------------------------------------------------------------ splash
def build_splash(w, h, name):
    size = (w, h)
    img = vgrad(size, [
        (0.0, (11, 48, 64)),
        (0.45, (8, 34, 47)),
        (1.0, (6, 24, 33)),
    ]).convert("RGBA")
    img = Image.alpha_composite(img, glow(size, (w * 0.5, h * 0.34), w * 0.85, (240, 160, 30), 0.28))
    img = Image.alpha_composite(img, stars(size, 90, seed=13, y_max_ratio=0.4))
    img = Image.alpha_composite(img, ridge(size, h * 0.88, h * 0.05, 29, (10, 32, 44, 220), blur=1.4))

    d = ImageDraw.Draw(img)
    cx, cy = w / 2, h * 0.40
    r = w * 0.135
    d.rounded_rectangle([cx - r, cy - r, cx + r, cy + r], radius=r * 0.30, fill=(240, 160, 30, 255))
    d.polygon([(cx + r * 0.52, cy - r * 0.04), (cx - r * 0.40, cy + r * 0.36),
               (cx - r * 0.30, cy - r * 0.12), (cx - r * 0.06, cy - r * 0.07)], fill=(255, 255, 255, 255))

    f1 = font(FONT_BOLD, int(w * 0.088))
    f2 = font(FONT_SEMI, int(w * 0.030))
    txt = "TripMind AI"
    box = d.textbbox((0, 0), txt, font=f1)
    d.text((cx - (box[2] - box[0]) / 2, cy + r * 1.55), txt, font=f1, fill=(255, 255, 255, 255))
    tag = "T R A V E L I N G   U N I Q U E L Y"
    box = d.textbbox((0, 0), tag, font=f2)
    d.text((cx - (box[2] - box[0]) / 2, cy + r * 1.55 + (w * 0.088) * 1.35), tag, font=f2, fill=(255, 212, 137, 255))

    route = bezier((cx - w * 0.20, cy + r * 3.0), (cx, cy + r * 2.5), (cx + w * 0.20, cy + r * 3.05))
    img = Image.alpha_composite(img, dotted_path(size, route, (255, 226, 186, 150), width=4, gap=34, dash=1))

    path = os.path.join(SPLASH, name)
    img.convert("RGB").save(path, "JPEG", quality=82, optimize=True, progressive=True)
    print("%-34s %5dx%-5d %8d bytes" % ("splash/" + name, w, h, os.path.getsize(path)))


hero = build_hero()
finish(hero, hero.size, "hero-journey.jpg", vignette=0.55, grain=8, quality=88)
head = build_pagehead()
finish(head, head.size, "pagehead-journey.jpg", vignette=0.42, grain=6, quality=86)
build_splash(1290, 2796, "splash-1290x2796.jpg")
build_splash(1170, 2532, "splash-1170x2532.jpg")
build_splash(828, 1792, "splash-828x1792.jpg")
print("brand assets done")
