"""Turn a photo into the cartoon head used by the character.

    python -m buddy --make-avatar path/to/photo.jpg

Writes assets/head.png (transparent background, cartoon look) and assets/head.json
(where the eyes and mouth are, so the character can blink and talk). Everything runs
locally -- the photo never leaves your computer.
"""

from __future__ import annotations

import json
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets"
OUT_W = 480  # output width in px (the character is drawn much smaller; this keeps it crisp)


def make_head(photo: str | Path, out_dir: Path = ASSETS) -> Path:
    import cv2
    import numpy as np

    img = cv2.imread(str(photo))
    if img is None:
        raise SystemExit(f"Could not read image: {photo}")
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 1. find the face (largest detection); fall back to a centered box
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    faces = cascade.detectMultiScale(gray, 1.1, 5, minSize=(max(40, w // 20),) * 2)
    if len(faces):
        fx, fy, fw, fh = max(faces, key=lambda f: f[2] * f[3])
    else:
        fw = fh = int(min(w, h) * 0.4)
        fx, fy = (w - fw) // 2, (h - fh) // 3
        print("No face detected -- using the center of the image.")

    # 2. crop: a bit of hair above, chin and some neck below, small margin on the sides
    x0, x1 = int(fx - 0.45 * fw), int(fx + 1.45 * fw)
    y0, y1 = int(fy - 0.75 * fh), int(fy + 1.25 * fh)
    pad = max(0, -x0, -y0, x1 - w, y1 - h)
    if pad:
        img = cv2.copyMakeBorder(img, pad, pad, pad, pad, cv2.BORDER_REFLECT)
        x0, x1, y0, y1 = x0 + pad, x1 + pad, y0 + pad, y1 + pad
    crop = img[y0:y1, x0:x1]
    scale = OUT_W / crop.shape[1]
    crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    ch, cw = crop.shape[:2]

    # face box in crop coordinates
    bx, by, bw, bh = (fx + pad - x0) * scale, (fy + pad - y0) * scale, fw * scale, fh * scale

    # 3. painted-cartoon look: strong edge-preserving smoothing, a touch of sharpening and color
    smooth = crop
    for _ in range(3):
        smooth = cv2.bilateralFilter(smooth, 9, 40, 9)
    blur = cv2.GaussianBlur(smooth, (0, 0), 3)
    cartoon = cv2.addWeighted(smooth, 1.6, blur, -0.6, 0)  # unsharp mask -> crisp shapes
    hsv = cv2.cvtColor(cartoon, cv2.COLOR_BGR2HSV).astype("float32")
    hsv[..., 1] = np.clip(hsv[..., 1] * 1.18, 0, 255)
    hsv[..., 2] = np.clip(hsv[..., 2] * 1.10, 0, 255)
    cartoon = cv2.cvtColor(hsv.astype("uint8"), cv2.COLOR_HSV2BGR)

    # warm the colors: nudge the cheek tone towards a natural skin tone so cool lighting doesn't turn faces purple
    cheeks = _cheeks(np, cartoon, bx, by, bw, bh)
    target = np.array([0.66, 0.78, 1.0])  # BGR ratios of a typical skin tone
    gains = target / np.maximum(cheeks / max(cheeks.max(), 1), 0.05)
    gains = gains / gains.mean()
    gains = 1 + 0.75 * (gains - 1)
    cartoon = np.clip(cartoon.astype("float32") * gains, 0, 255).astype("uint8")

    # 4. cut out the head with GrabCut seeded from an ellipse around the face
    mask = np.full((ch, cw), cv2.GC_BGD, np.uint8)
    cx, cy = int(bx + bw / 2), int(by + bh * 0.24)
    cv2.ellipse(mask, (cx, cy), (int(bw * 0.75), int(bh * 0.86)), 0, 0, 360, cv2.GC_PR_FGD, -1)
    cv2.ellipse(mask, (int(bx + bw / 2), int(by + bh * 0.55)), (int(bw * 0.42), int(bh * 0.5)), 0, 0, 360, cv2.GC_FGD, -1)
    bgd, fgd = np.zeros((1, 65), "float64"), np.zeros((1, 65), "float64")
    try:
        cv2.grabCut(crop, mask, None, bgd, fgd, 6, cv2.GC_INIT_WITH_MASK)
    except cv2.error:
        pass
    alpha = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype("uint8")
    # keep only the connected blob that contains the face, close holes, smooth the edge
    n, labels = cv2.connectedComponents(alpha)
    if n > 1:
        alpha = np.where(labels == labels[min(ch - 1, int(by + bh / 2)), min(cw - 1, int(bx + bw / 2))], 255, 0).astype("uint8")
    shape = np.zeros((ch, cw), np.uint8)
    cv2.ellipse(shape, (cx, cy), (int(bw * 0.78), int(bh * 0.88)), 0, 0, 360, 255, -1)
    alpha = cv2.bitwise_and(alpha, shape)
    core = np.zeros((ch, cw), np.uint8)
    cv2.ellipse(core, (int(bx + bw / 2), int(by + bh * 0.55)), (int(bw * 0.50), int(bh * 0.56)), 0, 0, 360, 255, -1)
    alpha = cv2.bitwise_or(alpha, core)
    alpha = cv2.morphologyEx(alpha, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))
    alpha = cv2.GaussianBlur(alpha, (9, 9), 0)
    alpha = cv2.threshold(alpha, 127, 255, cv2.THRESH_BINARY)[1]

    # 5. sticker outline (dark, thick) so the head pops on any background
    outline = cv2.dilate(alpha, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (17, 17)))
    rgba = np.zeros((ch, cw, 4), np.uint8)
    rgba[..., :3] = (50, 35, 90)[::-1]  # BGR of a deep purple outline
    rgba[..., 3] = cv2.GaussianBlur(outline, (3, 3), 0)
    fg = alpha > 0
    rgba[fg, :3] = cartoon[fg]
    rgba[..., 3] = np.maximum(rgba[..., 3], cv2.GaussianBlur(alpha, (3, 3), 0))

    # 6. trim empty margins
    ys, xs = np.where(rgba[..., 3] > 10)
    ty0, ty1, tx0, tx1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    rgba = rgba[ty0:ty1, tx0:tx1]
    fbx, fby = bx, by  # face box in crop coordinates (before trimming)
    th, tw = rgba.shape[:2]

    out_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_dir / "head.png"), rgba)

    # 7. facial landmarks (fractions of the image) for blinking / talking overlays
    eyes = _find_eyes(cv2, cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), fbx, fby, bw, bh)
    eyes_ok = eyes is not None
    if eyes is None:  # typical proportions
        eyes = [(fbx + bw * 0.30, fby + bh * 0.40, bw * 0.13), (fbx + bw * 0.70, fby + bh * 0.40, bw * 0.13)]
    meta = {
        "eyes_ok": eyes_ok,
        "eyes": [[(ex - tx0) / tw, (ey - ty0) / th, er / tw] for ex, ey, er in eyes],
        "mouth": [(fbx + bw * 0.5 - tx0) / tw, (fby + bh * 0.80 - ty0) / th, bw * 0.34 / tw],
        # skin tone sampled from the cheeks (left and right of the nose, above the mustache)
        "skin": _skin(np, cartoon, fbx, fby, bw, bh),
    }
    (out_dir / "head.json").write_text(json.dumps(meta, indent=2))
    return out_dir / "head.png"


def _find_eyes(cv2, gray, bx, by, bw, bh):
    """Return [(x, y, radius), (x, y, radius)] left-to-right, or None."""
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye.xml")
    x, y, w, h = int(bx), int(by + bh * 0.15), int(bw), int(bh * 0.45)
    roi = gray[max(0, y): y + h, max(0, x): x + w]
    eyes = cascade.detectMultiScale(roi, 1.05, 4, minSize=(int(bw * 0.15),) * 2)
    if len(eyes) < 2:
        return None
    eyes = sorted(sorted(eyes, key=lambda e: -e[2] * e[3])[:2], key=lambda e: e[0])
    if eyes[1][0] - eyes[0][0] < bw * 0.25:
        return None
    return [(x + ex + ew / 2, y + ey + eh / 2, ew * 0.4) for ex, ey, ew, eh in eyes]


def _cheeks(np, img, bx, by, bw, bh):
    """Mean BGR of the two cheek patches (left and right of the nose, above the mustache)."""
    parts = []
    for fx in (0.18, 0.72):
        x, y = int(bx + bw * fx), int(by + bh * 0.52)
        parts.append(img[y: y + max(2, int(bh * 0.12)), x: x + max(2, int(bw * 0.1))].reshape(-1, 3))
    return np.vstack(parts).mean(axis=0)


def _skin(np, img, bx, by, bw, bh):
    return [int(v) for v in _cheeks(np, img, bx, by, bw, bh)[::-1]]
