#!/usr/bin/env python3
"""Generate the MaluOS wallpapers: a quiet diagonal gradient with a soft glow.
Run from packages/maluos-branding: tools/make-wallpaper.py  (needs python3-pil)."""
from PIL import Image, ImageFilter
import os
W, H = 2560, 1600
OUT = os.path.join(os.path.dirname(__file__), "..", "files", "desktop", "backgrounds")

def gradient(c0, c1, c2):
    # Small diagonal gradient scaled up: smooth and cheap.
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

def glow(img, centre, radius, colour, alpha):
    layer = Image.new("RGB", (W, H), (0, 0, 0))
    mask = Image.new("L", (W, H), 0)
    from PIL import ImageDraw
    d = ImageDraw.Draw(mask)
    cx, cy = centre
    d.ellipse((cx - radius, cy - radius * 0.7, cx + radius, cy + radius * 0.7), fill=alpha)
    mask = mask.filter(ImageFilter.GaussianBlur(radius / 2))
    layer.paste(colour, (0, 0, W, H))
    return Image.composite(layer, img, mask)

os.makedirs(OUT, exist_ok=True)
dark = gradient((12, 18, 38), (22, 33, 58), (14, 70, 84))
dark = glow(dark, (int(W * 0.72), int(H * 0.68)), 900, (18, 120, 134), 110)
dark.save(os.path.join(OUT, "maluos-dark.png"), optimize=True)
light = gradient((226, 233, 240), (208, 222, 232), (176, 212, 218))
light = glow(light, (int(W * 0.72), int(H * 0.68)), 900, (150, 205, 210), 120)
light.save(os.path.join(OUT, "maluos-light.png"), optimize=True)
print("wrote", OUT)

# The boot splash watermark: plymouth-theme-spinner's watermark.png is a symlink
# to Ubuntu's logo; maluos-desktop-branding diverts it. Same size as Ubuntu's
# (187x72), white on transparent, drawn at 4x and downscaled.
from PIL import ImageDraw, ImageFont
S = 4
wm = Image.new("RGBA", (187 * S, 72 * S), (0, 0, 0, 0))
d = ImageDraw.Draw(wm)
white = (255, 255, 255, 255)
# the mark: four nodes and their edges, 48 px wide
ox, oy = 2 * S, 12 * S
nodes = [(8, 24), (24, 10), (24, 38), (40, 24)]
for a, b in [(0, 1), (0, 2), (1, 2), (1, 3), (2, 3)]:
    d.line([(ox + nodes[a][0] * S, oy + nodes[a][1] * S), (ox + nodes[b][0] * S, oy + nodes[b][1] * S)], fill=white, width=2 * S)
for i, (x, y) in enumerate(nodes):
    r = (5 if i in (0, 3) else 4) * S
    d.ellipse((ox + x * S - r, oy + y * S - r, ox + x * S + r, oy + y * S + r), fill=white)
try:
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 30 * S)
except OSError:
    font = ImageFont.load_default()
d.text((54 * S, 20 * S), "MaluOS", font=font, fill=white)
wm = wm.resize((187, 72), Image.LANCZOS)
wm.save(os.path.join(OUT, "..", "maluos-watermark.png"), optimize=True)
print("wrote watermark")
