"""
Extract the Hachette 'Tableau de cotation des millésimes' (sélection 2018)
into data/hachette_millesime.json.

Method (whole-page OCR + grid assignment — best recall, cross-verified):
  1. Render pages 3 & 4 at high resolution.
  2. OCR each page; 4-digit numbers in the page's year range = ROW y-centers,
     1-2 digit numbers (0..20) = scores.
  3. Learn 17 evenly-spaced COLUMN x-centers from the dense page 4 (k-means).
  4. Assign each score to nearest (row, column); reject if >0.55 col-width away
     (orphan) or if the (row,col) is already taken (conflict -> keep first).
"""
import json
from pathlib import Path
import numpy as np
import fitz
from rapidocr_onnxruntime import RapidOCR

ROOT = Path(__file__).resolve().parent.parent
PDF = ROOT / "tmp_hachette_millesime.pdf"
MAT = 6

COLUMNS = [
    "Alsace", "Beaujolais", "Bordeaux rouge", "Bordeaux liquoreux",
    "Bordeaux sec", "Bourgogne rouge", "Bourgogne blanc", "Champagne",
    "Jura (vin jaune)", "Languedoc-Roussillon", "Provence rouge",
    "Sud-Ouest rouge", "Sud-Ouest blanc liquoreux", "Loire rouge",
    "Loire blanc liquoreux", "Rhône (nord)", "Rhône (sud)",
]

ocr = RapidOCR()

def ocr_page(page_index):
    d = fitz.open(PDF)
    pix = d[page_index].get_pixmap(matrix=fitz.Matrix(MAT, MAT))
    png = ROOT / f"_ocr_p{page_index+1}.png"
    pix.save(png)
    res, _ = ocr(str(png))
    years, scores = [], []
    for box, text, conf in (res or []):
        t = text.strip()
        if not t.isdigit():
            continue
        v = int(t)
        cx = sum(p[0] for p in box) / 4.0
        cy = sum(p[1] for p in box) / 4.0
        if len(t) == 4 and 1900 <= v <= 2020:
            years.append((cy, v))
        elif len(t) <= 2 and 0 <= v <= 20:
            scores.append({"x": cx, "y": cy, "v": v, "conf": float(conf)})
    years.sort()
    return years, scores

def kmeans_1d(xs, k, iters=200):
    xs = np.sort(np.array(xs, dtype=float))
    centers = np.linspace(xs.min(), xs.max(), k)
    for _ in range(iters):
        a = np.argmin(np.abs(xs[:, None] - centers[None, :]), axis=1)
        new = np.array([xs[a == j].mean() if np.any(a == j) else centers[j] for j in range(k)])
        if np.allclose(new, centers):
            break
        centers = new
    return np.sort(centers)

def build(years, scores, col_centers):
    yy = np.array([y for y, _ in years]); yv = [v for _, v in years]
    cw = float(np.median(np.diff(col_centers)))
    mat = {v: {c: None for c in COLUMNS} for v in yv}
    low = []
    n_conf = n_orph = 0
    for s in sorted(scores, key=lambda z: -z["conf"]):  # high-conf first wins
        ci = int(np.argmin(np.abs(col_centers - s["x"])))
        ri = int(np.argmin(np.abs(yy - s["y"])))
        if abs(col_centers[ci] - s["x"]) > cw * 0.55:
            n_orph += 1; continue
        yr, col = yv[ri], COLUMNS[ci]
        if mat[yr][col] is not None:
            n_conf += 1; continue
        mat[yr][col] = s["v"]
        if s["conf"] < 0.6:
            low.append({"year": yr, "col": col, "v": s["v"], "conf": round(s["conf"], 3)})
    return mat, low, n_conf, n_orph

y4, s4 = ocr_page(3)
col_centers = kmeans_1d([s["x"] for s in s4], 17)
y3, s3 = ocr_page(2)

m3, low3, c3, o3 = build(y3, s3, col_centers)
m4, low4, c4, o4 = build(y4, s4, col_centers)
full = {**m3, **m4}

out = {
    "source": "Le Guide Hachette des Vins — Mini-guide des millésimes (sélection 2018)",
    "source_url": "https://www.hachette-vins.com/mini-guide-ghv/GUIDE%20HACHETTE%20MILLESIME%20WEB.pdf",
    "scale": "/20",
    "columns": COLUMNS,
    "col_centers": [round(c) for c in col_centers],
    "matrix": {str(y): full[y] for y in sorted(full)},
    "low_confidence": low3 + low4,
}
(ROOT / "scripts" / "seed-data" / "hachette_millesime.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

filled = sum(1 for y in full for c in COLUMNS if full[y][c] is not None)
print(f"years p3={len(y3)} p4={len(y4)} total={len(full)}")
print(f"cells filled: {filled}/{len(full)*17}  conflicts={c3+c4} orphans={o3+o4} low_conf={len(low3)+len(low4)}")
empty_rows = [y for y in sorted(full) if all(full[y][c] is None for c in COLUMNS)]
print(f"fully-empty year rows: {empty_rows}")
