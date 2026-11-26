"""Synthetic demo images.

These are DRAWN pictures with known box positions. They exist only so the whole pipeline
(upload, label, freeze, train, analyse, report) can be tested before real labelled slides
are available. A model trained on them cannot detect real tuberculosis bacilli. Everything
made here is flagged synthetic=1 and models trained on it are flagged DEMO.
"""
import math
import random

import cv2
import numpy as np


def _noise(rng, shape, sigma):
    return rng.normal(0, sigma, shape)


def make_field(seed: int, size: int = 512, n_rods=None, tint=None):
    """Return (image BGR uint8, boxes [(cx, cy, w, h) normalised])."""
    r = random.Random(seed)
    rng = np.random.default_rng(seed)
    tint = tint or (r.uniform(-10, 10), r.uniform(-8, 8), r.uniform(-10, 10))
    bg = np.array([247 + tint[0], 238 + tint[1], 227 + tint[2]], dtype=np.float32)  # BGR, pale blue
    img = np.ones((size, size, 3), np.float32) * bg
    # uneven illumination
    yy, xx = np.mgrid[0:size, 0:size]
    cx0, cy0 = r.uniform(0.3, 0.7) * size, r.uniform(0.3, 0.7) * size
    falloff = 1 - 0.18 * (((xx - cx0) ** 2 + (yy - cy0) ** 2) / (size ** 2))
    img *= falloff[..., None]
    # large pale smudges (mucus / debris)
    for _ in range(r.randint(6, 12)):
        c = (int(r.uniform(0, size)), int(r.uniform(0, size)))
        ax = (r.randint(14, 46), r.randint(6, 20))
        col = (bg - np.array([r.uniform(14, 30), r.uniform(12, 24), r.uniform(8, 18)])).tolist()
        cv2.ellipse(img, c, ax, r.uniform(0, 180), 0, 360, col, -1, cv2.LINE_AA)
    img = cv2.GaussianBlur(img, (0, 0), 3)
    # hard negatives: round or squat red/purple particles that are NOT bacilli
    for _ in range(r.randint(2, 8)):
        c = (int(r.uniform(10, size - 10)), int(r.uniform(10, size - 10)))
        col = (r.randint(70, 110), r.randint(20, 60), r.randint(120, 170))
        if r.random() < 0.5:
            cv2.circle(img, c, r.randint(3, 6), col, -1, cv2.LINE_AA)
        else:
            cv2.ellipse(img, c, (r.randint(5, 8), r.randint(4, 6)), r.uniform(0, 180), 0, 360, col, -1, cv2.LINE_AA)
    # bacilli: slim, slightly curved red rods
    boxes = []
    count = n_rods if n_rods is not None else (0 if r.random() < 0.4 else r.randint(1, 9))
    placed = []
    for _ in range(count):
        for _try in range(30):
            c = (r.uniform(24, size - 24), r.uniform(24, size - 24))
            if all(math.hypot(c[0] - p[0], c[1] - p[1]) > 34 for p in placed):
                break
        placed.append(c)
        length = r.uniform(16, 30)
        thick = r.uniform(3.0, 4.6)
        ang = r.uniform(0, math.pi)
        bend = r.uniform(-0.18, 0.18)
        pts = []
        for t in np.linspace(-0.5, 0.5, 9):
            a = ang + bend * t * 2
            pts.append((c[0] + math.cos(ang) * t * length + math.sin(ang) * bend * length * (t * t) * 2,
                        c[1] + math.sin(ang) * t * length - math.cos(ang) * bend * length * (t * t) * 2))
        pts = np.array(pts, np.int32).reshape(-1, 1, 2)
        col = (r.randint(55, 85), r.randint(15, 40), r.randint(150, 190))   # carbol fuchsin red (BGR)
        cv2.polylines(img, [pts], False, col, int(round(thick)), cv2.LINE_AA)
        xs, ys = pts[:, 0, 0], pts[:, 0, 1]
        pad = 5
        x1, x2 = max(0, xs.min() - pad), min(size, xs.max() + pad)
        y1, y2 = max(0, ys.min() - pad), min(size, ys.max() + pad)
        boxes.append(((x1 + x2) / 2 / size, (y1 + y2) / 2 / size, (x2 - x1) / size, (y2 - y1) / size))
    img = cv2.GaussianBlur(img, (0, 0), 0.9)
    img += _noise(rng, img.shape, 2.2)
    return np.clip(img, 0, 255).astype(np.uint8), boxes


def encode_jpeg(img):
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 92])
    return buf.tobytes()


def _box(xs, ys, size, pad=4):
    x1, x2 = max(0, min(xs) - pad), min(size, max(xs) + pad)
    y1, y2 = max(0, min(ys) - pad), min(size, max(ys) + pad)
    return ((x1 + x2) / 2 / size, (y1 + y2) / 2 / size, (x2 - x1) / size, (y2 - y1) / size)


def _free_spot(r, placed, size, radius):
    for _try in range(40):
        c = (r.uniform(radius + 6, size - radius - 6), r.uniform(radius + 6, size - radius - 6))
        if all(math.hypot(c[0] - p[0], c[1] - p[1]) > radius + pr + 8 for p, pr in placed):
            placed.append((c, radius))
            return c
    return None


STOOL_DEMO_CLASSES = ["ascaris", "hookworm", "trichuris", "taenia", "s_mansoni"]


def make_field_stool(seed: int, size: int = 512, n_eggs=None):
    """Stool wet-mount look (saline or iodine): pale yellow-grey background, plant fibres, debris and air
    bubbles as hard negatives, and a few helminth eggs drawn with the shape cues a reader uses.
    Returns (image BGR uint8, [(label, cx, cy, w, h)])."""
    r = random.Random(seed)
    rng = np.random.default_rng(seed)
    iodine = r.random() < 0.5
    bg = np.array([150, 205, 225] if iodine else [205, 220, 222], np.float32) + np.array([r.uniform(-8, 8) for _ in range(3)])
    img = np.ones((size, size, 3), np.float32) * bg
    for _ in range(r.randint(20, 40)):                     # amorphous faecal debris
        c = (int(r.uniform(0, size)), int(r.uniform(0, size)))
        col = (bg * r.uniform(0.55, 0.85)).tolist()
        cv2.ellipse(img, c, (r.randint(3, 16), r.randint(2, 9)), r.uniform(0, 180), 0, 360, col, -1, cv2.LINE_AA)
    for _ in range(r.randint(2, 6)):                       # plant fibres
        p0 = (int(r.uniform(0, size)), int(r.uniform(0, size)))
        a, ln = r.uniform(0, math.pi), r.randint(40, 140)
        cv2.line(img, p0, (int(p0[0] + math.cos(a) * ln), int(p0[1] + math.sin(a) * ln)), (bg * 0.6).tolist(), r.randint(3, 7), cv2.LINE_AA)
    placed = []
    for _ in range(r.randint(1, 4)):                       # air bubbles: dark rim, clear middle (not eggs)
        rad = r.randint(10, 26)
        c = _free_spot(r, placed, size, rad)
        if c:
            cv2.circle(img, (int(c[0]), int(c[1])), rad, (60, 60, 60), 2, cv2.LINE_AA)
    img = cv2.GaussianBlur(img, (0, 0), 1.6)
    boxes = []
    count = n_eggs if n_eggs is not None else (0 if r.random() < 0.3 else r.randint(1, 4))
    for _ in range(count):
        kind = r.choice(STOOL_DEMO_CLASSES)
        if kind == "ascaris":
            rad = r.uniform(20, 28)
            c = _free_spot(r, placed, size, rad + 4)
            if not c:
                continue
            ci = (int(c[0]), int(c[1]))
            for k in range(28):                            # bumpy outer coat
                a = 2 * math.pi * k / 28
                cv2.circle(img, (int(c[0] + math.cos(a) * rad), int(c[1] + math.sin(a) * rad)), 4, (30, 75, 120), -1, cv2.LINE_AA)
            cv2.circle(img, ci, int(rad - 2), (45, 100, 150), -1, cv2.LINE_AA)
            cv2.circle(img, ci, int(rad - 8), (70, 135, 175), -1, cv2.LINE_AA)
            boxes.append(("ascaris", *_box([c[0] - rad - 4, c[0] + rad + 4], [c[1] - rad - 4, c[1] + rad + 4], size, 2)))
        elif kind == "hookworm":
            ax, ay = r.uniform(26, 32), r.uniform(16, 20)
            c = _free_spot(r, placed, size, ax)
            if not c:
                continue
            ang = r.uniform(0, 180)
            ci = (int(c[0]), int(c[1]))
            cv2.ellipse(img, ci, (int(ax), int(ay)), ang, 0, 360, (bg * 1.02).tolist(), -1, cv2.LINE_AA)
            cv2.ellipse(img, ci, (int(ax), int(ay)), ang, 0, 360, (80, 90, 95), 1, cv2.LINE_AA)
            for k in range(r.randint(4, 8)):               # cleaving embryo, clear space around it
                a = 2 * math.pi * k / 8
                cv2.circle(img, (int(c[0] + math.cos(a) * 6), int(c[1] + math.sin(a) * 5)), 6, (110, 130, 140), -1, cv2.LINE_AA)
            boxes.append(("hookworm", *_box([c[0] - ax, c[0] + ax], [c[1] - ax, c[1] + ax], size, 3)))
        elif kind == "trichuris":
            ax, ay = r.uniform(22, 26), r.uniform(11, 13)
            c = _free_spot(r, placed, size, ax + 4)
            if not c:
                continue
            a = r.uniform(0, math.pi)
            ci = (int(c[0]), int(c[1]))
            cv2.ellipse(img, ci, (int(ax), int(ay)), math.degrees(a), 0, 360, (35, 85, 140), -1, cv2.LINE_AA)
            for s in (-1, 1):                              # clear polar plugs
                cv2.circle(img, (int(c[0] + s * math.cos(a) * (ax + 1)), int(c[1] + s * math.sin(a) * (ax + 1))), 4, (200, 225, 235), -1, cv2.LINE_AA)
            boxes.append(("trichuris", *_box([c[0] - ax - 5, c[0] + ax + 5], [c[1] - ax - 5, c[1] + ax + 5], size, 0)))
        elif kind == "taenia":
            rad = r.uniform(14, 17)
            c = _free_spot(r, placed, size, rad)
            if not c:
                continue
            ci = (int(c[0]), int(c[1]))
            cv2.circle(img, ci, int(rad), (25, 60, 100), -1, cv2.LINE_AA)
            for k in range(24):                            # radial striations of the thick shell
                a = 2 * math.pi * k / 24
                cv2.line(img, (int(c[0] + math.cos(a) * (rad - 5)), int(c[1] + math.sin(a) * (rad - 5))),
                         (int(c[0] + math.cos(a) * rad), int(c[1] + math.sin(a) * rad)), (60, 110, 150), 1, cv2.LINE_AA)
            cv2.circle(img, ci, int(rad - 6), (90, 150, 180), -1, cv2.LINE_AA)
            boxes.append(("taenia", *_box([c[0] - rad, c[0] + rad], [c[1] - rad, c[1] + rad], size, 3)))
        else:                                              # Schistosoma mansoni, large with a lateral spine
            ax, ay = r.uniform(52, 62), r.uniform(22, 27)
            c = _free_spot(r, placed, size, ax + 10)
            if not c:
                continue
            a = r.uniform(0, math.pi)
            ci = (int(c[0]), int(c[1]))
            cv2.ellipse(img, ci, (int(ax), int(ay)), math.degrees(a), 0, 360, (150, 200, 215), -1, cv2.LINE_AA)
            cv2.ellipse(img, ci, (int(ax), int(ay)), math.degrees(a), 0, 360, (50, 90, 120), 2, cv2.LINE_AA)
            nx, ny = -math.sin(a), math.cos(a)             # side normal
            bx, by = c[0] + math.cos(a) * ax * 0.45 + nx * ay * 0.9, c[1] + math.sin(a) * ax * 0.45 + ny * ay * 0.9
            tip = (bx + nx * 16 + math.cos(a) * 6, by + ny * 16 + math.sin(a) * 6)
            pts = np.array([[bx - math.cos(a) * 6, by - math.sin(a) * 6], [bx + math.cos(a) * 6, by + math.sin(a) * 6], tip], np.int32)
            cv2.fillPoly(img, [pts], (50, 90, 120), cv2.LINE_AA)
            xs = [c[0] - ax - 2, c[0] + ax + 2, tip[0]]
            ys = [c[1] - ax * abs(math.sin(a)) - ay, c[1] + ax * abs(math.sin(a)) + ay, tip[1]]
            boxes.append(("s_mansoni", *_box(xs, ys, size, 2)))
    img = cv2.GaussianBlur(img, (0, 0), 0.8)
    img += _noise(rng, img.shape, 2.5)
    return np.clip(img, 0, 255).astype(np.uint8), boxes


STI_DEMO_CLASSES = ["gndc", "candida_yeast", "candida_hyphae", "pus_cell"]


def make_field_sti(seed: int, size: int = 512, n_items=None):
    """Gram-stained genital smear look: pale pink background, pink epithelial cells, pus cells with purple
    lobed nuclei, some with pink intracellular diplococci (gonorrhoea pattern), purple budding yeast and
    pseudohyphae (Candida). Returns (image BGR uint8, [(label, cx, cy, w, h)])."""
    r = random.Random(seed)
    rng = np.random.default_rng(seed)
    bg = np.array([228, 222, 240], np.float32) + np.array([r.uniform(-6, 6) for _ in range(3)])
    img = np.ones((size, size, 3), np.float32) * bg
    placed, boxes = [], []
    for _ in range(r.randint(1, 3)):                       # squamous epithelial cells (hard negatives)
        rad = r.randint(45, 70)
        c = _free_spot(r, placed, size, rad * 0.8)
        if not c:
            continue
        pts = [(c[0] + math.cos(t) * rad * r.uniform(0.75, 1.0), c[1] + math.sin(t) * rad * r.uniform(0.75, 1.0))
               for t in np.linspace(0, 2 * math.pi, 9)[:-1]]
        cv2.fillPoly(img, [np.array(pts, np.int32)], (205, 190, 235), cv2.LINE_AA)
        cv2.circle(img, (int(c[0]), int(c[1])), 6, (150, 90, 170), -1, cv2.LINE_AA)
    for _ in range(r.randint(40, 90)):                     # background bacteria (rods), not diagnostic
        p0 = (r.uniform(0, size), r.uniform(0, size))
        a = r.uniform(0, math.pi)
        cv2.line(img, (int(p0[0]), int(p0[1])), (int(p0[0] + math.cos(a) * 5), int(p0[1] + math.sin(a) * 5)),
                 (150, 110, 200), 2, cv2.LINE_AA)
    count = n_items if n_items is not None else r.randint(1, 6)
    for _ in range(count):
        kind = r.choice(STI_DEMO_CLASSES + ["pus_cell"])
        if kind in ("pus_cell", "gndc"):
            rad = r.uniform(13, 16)
            c = _free_spot(r, placed, size, rad)
            if not c:
                continue
            ci = (int(c[0]), int(c[1]))
            cv2.circle(img, ci, int(rad), (190, 165, 225), -1, cv2.LINE_AA)
            for k in range(r.randint(2, 4)):               # lobed nucleus
                a = 2 * math.pi * k / 4 + r.uniform(-0.3, 0.3)
                cv2.circle(img, (int(c[0] + math.cos(a) * 5), int(c[1] + math.sin(a) * 5)), 4, (140, 60, 120), -1, cv2.LINE_AA)
            if kind == "gndc":
                for _p in range(r.randint(2, 5)):          # pink-red diplococci inside the cell
                    a, d = r.uniform(0, 2 * math.pi), r.uniform(7, rad - 3)
                    px, py = c[0] + math.cos(a) * d, c[1] + math.sin(a) * d
                    o = r.uniform(0, math.pi)
                    for s in (-1, 1):
                        cv2.circle(img, (int(px + s * math.cos(o) * 2.2), int(py + s * math.sin(o) * 2.2)), 2, (70, 40, 200), -1, cv2.LINE_AA)
            boxes.append((kind, *_box([c[0] - rad, c[0] + rad], [c[1] - rad, c[1] + rad], size, 2)))
        elif kind == "candida_yeast":
            c = _free_spot(r, placed, size, 10)
            if not c:
                continue
            a = r.uniform(0, 180)
            cv2.ellipse(img, (int(c[0]), int(c[1])), (6, 4), a, 0, 360, (120, 40, 90), -1, cv2.LINE_AA)
            bx, by = c[0] + math.cos(math.radians(a)) * 8, c[1] + math.sin(math.radians(a)) * 8
            cv2.circle(img, (int(bx), int(by)), 3, (120, 40, 90), -1, cv2.LINE_AA)        # bud
            boxes.append(("candida_yeast", *_box([c[0] - 7, c[0] + 7, bx - 3, bx + 3], [c[1] - 7, c[1] + 7, by - 3, by + 3], size, 3)))
        else:                                              # pseudohyphae: a chain of stretched yeast cells
            c = _free_spot(r, placed, size, 45)
            if not c:
                continue
            a = r.uniform(0, math.pi)
            xs, ys = [], []
            x, y = c[0] - math.cos(a) * 40, c[1] - math.sin(a) * 40
            for _k in range(r.randint(5, 8)):
                cv2.ellipse(img, (int(x), int(y)), (7, 3), math.degrees(a), 0, 360, (120, 40, 90), -1, cv2.LINE_AA)
                xs += [x - 7, x + 7]; ys += [y - 7, y + 7]
                a += r.uniform(-0.25, 0.25)
                x, y = x + math.cos(a) * 13, y + math.sin(a) * 13
            boxes.append(("candida_hyphae", *_box(xs, ys, size, 3)))
    img = cv2.GaussianBlur(img, (0, 0), 0.9)
    img += _noise(rng, img.shape, 2.2)
    return np.clip(img, 0, 255).astype(np.uint8), boxes


def make_labelled(modality, seed):
    """One synthetic field for any test type: (image, [(label, cx, cy, w, h)])."""
    if modality == "stl":
        return make_field_stool(seed)
    if modality == "sti":
        return make_field_sti(seed)
    img, boxes = (make_field_fm if modality == "fm" else make_field)(seed)
    return img, [("afb", *b) for b in boxes]


def make_field_fm(seed: int, size: int = 512, n_rods=None):
    """Fluorescence (auramine) look: near-black background, bright yellow-green rods with a glow,
    dim round or fibre-like debris as hard negatives. Returns (image BGR uint8, boxes)."""
    r = random.Random(seed)
    rng = np.random.default_rng(seed)
    img = np.ones((size, size, 3), np.float32) * np.array([14, 10, 9], np.float32)
    yy, xx = np.mgrid[0:size, 0:size]
    img *= (1 + 0.5 * np.exp(-(((xx - size / 2) ** 2 + (yy - size / 2) ** 2) / (2 * (size * 0.45) ** 2))))[..., None]
    layer = np.zeros_like(img)
    # dim autofluorescent debris (not bacilli): blue-green blobs and short fibres
    for _ in range(r.randint(3, 10)):
        c = (int(r.uniform(8, size - 8)), int(r.uniform(8, size - 8)))
        col = (r.randint(60, 110), r.randint(55, 95), r.randint(15, 40))
        if r.random() < 0.6:
            cv2.circle(layer, c, r.randint(2, 6), col, -1, cv2.LINE_AA)
        else:
            a = r.uniform(0, math.pi)
            ln = r.randint(14, 40)
            cv2.line(layer, c, (int(c[0] + math.cos(a) * ln), int(c[1] + math.sin(a) * ln)), col, 1, cv2.LINE_AA)
    boxes, placed = [], []
    count = n_rods if n_rods is not None else (0 if r.random() < 0.4 else r.randint(1, 9))
    for _ in range(count):
        for _try in range(30):
            c = (r.uniform(24, size - 24), r.uniform(24, size - 24))
            if all(math.hypot(c[0] - p[0], c[1] - p[1]) > 34 for p in placed):
                break
        placed.append(c)
        length, thick = r.uniform(16, 30), r.uniform(2.6, 4.0)
        ang, bend = r.uniform(0, math.pi), r.uniform(-0.18, 0.18)
        pts = []
        for t in np.linspace(-0.5, 0.5, 9):
            pts.append((c[0] + math.cos(ang) * t * length + math.sin(ang) * bend * length * (t * t) * 2,
                        c[1] + math.sin(ang) * t * length - math.cos(ang) * bend * length * (t * t) * 2))
        pts = np.array(pts, np.int32).reshape(-1, 1, 2)
        col = (r.randint(40, 90), r.randint(215, 250), r.randint(170, 215))      # auramine yellow-green (BGR)
        cv2.polylines(layer, [pts], False, col, int(round(thick)), cv2.LINE_AA)
        xs, ys = pts[:, 0, 0], pts[:, 0, 1]
        pad = 5
        x1, x2 = max(0, xs.min() - pad), min(size, xs.max() + pad)
        y1, y2 = max(0, ys.min() - pad), min(size, ys.max() + pad)
        boxes.append(((x1 + x2) / 2 / size, (y1 + y2) / 2 / size, (x2 - x1) / size, (y2 - y1) / size))
    glow = cv2.GaussianBlur(layer, (0, 0), 5) * 0.8
    img += cv2.GaussianBlur(layer, (0, 0), 0.8) + glow
    img += _noise(rng, img.shape, 3.0)
    return np.clip(img, 0, 255).astype(np.uint8), boxes
