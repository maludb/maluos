#!/usr/bin/env python3
"""Generate the MaluOS desktop assets from the logo in files/desktop/src:
the wallpapers (light and dark), the login-screen logo, the distributor icon
sizes and the boot-splash watermark. Run from packages/maluos-branding:
tools/make-branding.py  (needs python3-pil). Outputs are committed."""
from PIL import Image, ImageFilter, ImageDraw
import os

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.join(HERE, "..", "files", "desktop")
SRC = os.path.join(FILES, "src", "maluos-logo-full.png")
BG = os.path.join(FILES, "backgrounds")
ICONS = os.path.join(FILES, "icons")
NAVY = (22, 33, 58)
W, H = 2560, 1600

logo = Image.open(SRC).convert("RGBA")
alpha = logo.split()[3]
# The emblem (the ring with the hexagons) is left of the first empty column;
# the wordmark is everything to its right.
split = next(x for x in range(600, logo.width)
             if alpha.crop((x, 0, x + 1, logo.height)).getbbox() is None)
emblem = logo.crop(alpha.crop((0, 0, split, logo.height)).getbbox())


def recolour_white(img, colour, x_from):
    """White parts of the wordmark (the Malu letters and the tagline) become
    `colour`, for a light background. The emblem keeps its white disc."""
    out = img.copy()
    px = out.load()
    for y in range(out.height):
        for x in range(x_from, out.width):
            r, g, b, a = px[x, y]
            if a and min(r, g, b) > 170:
                px[x, y] = colour + (a,)
    return out


def gradient(c0, c1, c2):
    small = Image.new("RGB", (64, 40))
    px = small.load()
    for y in range(40):
        for x in range(64):
            t = (x / 63 * 0.6 + y / 39 * 0.4)
            if t < 0.5:
                a, b, u = c0, c1, t / 0.5
            else:
                a, b, u = c1, c2, (t - 0.5) / 0.5
            px[x, y] = tuple(int(a[i] + (b[i] - a[i]) * u) for i in range(3))
    return small.resize((W, H), Image.BICUBIC)


def glow(img, centre, radius, colour, a):
    layer = Image.new("RGB", (W, H), colour)
    mask = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(mask)
    cx, cy = centre
    d.ellipse((cx - radius, cy - radius * 0.7, cx + radius, cy + radius * 0.7), fill=a)
    mask = mask.filter(ImageFilter.GaussianBlur(radius / 2))
    return Image.composite(layer, img, mask)


def place(bg, mark, width, cy_frac):
    mark = mark.resize((width, round(mark.height * width / mark.width)), Image.LANCZOS)
    out = bg.convert("RGBA")
    out.alpha_composite(mark, ((W - mark.width) // 2, int(H * cy_frac) - mark.height // 2))
    return out.convert("RGB")


os.makedirs(BG, exist_ok=True)
dark = gradient((12, 18, 38), (22, 33, 58), (14, 70, 84))
dark = glow(dark, (int(W * 0.72), int(H * 0.68)), 900, (18, 120, 134), 110)
place(dark, logo, 1000, 0.46).save(os.path.join(BG, "maluos-dark.png"), optimize=True)
light = gradient((226, 233, 240), (208, 222, 232), (176, 212, 218))
light = glow(light, (int(W * 0.72), int(H * 0.68)), 900, (150, 205, 210), 120)
place(light, recolour_white(logo, NAVY, split), 1000, 0.46).save(
    os.path.join(BG, "maluos-light.png"), optimize=True)
print("wrote wallpapers")

# Login screen logo (org.gnome.login-screen logo): shown at pixel size on the
# greeter's dark background.
lw = 260
logo.resize((lw, round(logo.height * lw / logo.width)), Image.LANCZOS).save(
    os.path.join(FILES, "maluos-logo-text.png"), optimize=True)

# Distributor icon (LOGO=maluos-logo in os-release, Settings > About): the
# emblem, square, in the hicolor sizes.
side = max(emblem.size)
square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
square.alpha_composite(emblem, ((side - emblem.width) // 2, (side - emblem.height) // 2))
for s in (16, 24, 32, 48, 64, 128, 256, 512):
    d = os.path.join(ICONS, f"{s}x{s}", "apps")
    os.makedirs(d, exist_ok=True)
    square.resize((s, s), Image.LANCZOS).save(os.path.join(d, "maluos-logo.png"), optimize=True)

# Boot splash watermark: plymouth-theme-spinner's watermark.png is a symlink
# to Ubuntu's logo (187x72); maluos-desktop-branding diverts it. Ours is a
# little larger; plymouth blits it at pixel size near the bottom of the screen.
ww = 280
logo.resize((ww, round(logo.height * ww / logo.width)), Image.LANCZOS).save(
    os.path.join(FILES, "maluos-watermark.png"), optimize=True)
print("wrote login logo, icons, watermark")
