"""手書き希望表の写真から × を読み取るモジュール（方式1）。
四隅の位置合わせマークで補正し、テンプレの枠数(行)・人数(列)に合わせて各セルの
黒インク量から × / 空欄 を判定する。氏名・枠・年度・希望はExcelテンプレ側で持つ。
"""
import cv2
import numpy as np

OW, OH = 1400, 1950
X0, X1 = 246, 1294        # メンバー列の左右（列数で等分）
HH, GG = 4.73, 1.37       # 7月較正から得た「ヘッダー分/下余白分」の行数換算
INK_THRESH = 0.06
DARK = 110
MARGIN = 0.18


def detect_corners(img):
    """四隅の■マークを検出。左右で分け、左の最上=TL・最下=BL、右の最上=TR・最下=BR。"""
    H, W = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, dark = cv2.threshold(gray, 80, 255, cv2.THRESH_BINARY_INV)
    n, lab, stats, cent = cv2.connectedComponentsWithStats(dark, 8)
    amin = 0.00003 * H * W
    amax = 0.0008 * H * W
    sq = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        cx, cy = cent[i]
        if amin < area < amax and 0.55 < w / max(h, 1) < 1.8:
            if (cx < W * 0.22 or cx > W * 0.78) and (cy < H * 0.28 or cy > H * 0.78):
                sq.append((cx, cy))
    left = [s for s in sq if s[0] < W * 0.5]
    right = [s for s in sq if s[0] > W * 0.5]
    if len(left) < 2 or len(right) < 2:
        raise ValueError("四隅の位置合わせマーク(■)を検出できませんでした。"
                         "マークの周りに白い余白がある用紙を、真上から撮影/スキャンしてください。")
    TL = min(left, key=lambda s: s[1]); BL = max(left, key=lambda s: s[1])
    TR = min(right, key=lambda s: s[1]); BR = max(right, key=lambda s: s[1])
    return TL, TR, BL, BR


def warp(img, corners):
    src = np.float32(list(corners))
    dst = np.float32([[0, 0], [OW, 0], [0, OH], [OW, OH]])
    M = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(img, M, (OW, OH))


def _yrange(n_rows):
    """行数からデータ帯の上端・下端(warped座標)を推定。"""
    T = HH + n_rows + GG
    return HH / T * OH, (HH + n_rows) / T * OH


def _cells(n_cols, n_rows):
    y0, y1 = _yrange(n_rows)
    xs = np.linspace(X0, X1, n_cols + 1)
    ys = np.linspace(y0, y1, n_rows + 1)
    return xs, ys


def read_grid(warped, n_cols, n_rows):
    g = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
    xs, ys = _cells(n_cols, n_rows)
    grid, ratios = [], []
    for r in range(n_rows):
        y0, y1 = int(ys[r]), int(ys[r + 1])
        row, rr = [], []
        for c in range(n_cols):
            x0, x1 = int(xs[c]), int(xs[c + 1])
            my = int((y1 - y0) * MARGIN); mx = int((x1 - x0) * MARGIN)
            cell = g[y0 + my:y1 - my, x0 + mx:x1 - mx]
            ratio = float((cell < DARK).mean()) if cell.size else 0.0
            row.append(1 if ratio > INK_THRESH else 0)
            rr.append(ratio)
        grid.append(row); ratios.append(rr)
    return grid, ratios


def annotate(warped, grid, n_cols, n_rows):
    ov = warped.copy()
    xs, ys = _cells(n_cols, n_rows)
    for r in range(n_rows):
        y0, y1 = int(ys[r]), int(ys[r + 1])
        for c in range(n_cols):
            if grid[r][c]:
                x0, x1 = int(xs[c]), int(xs[c + 1])
                sub = ov[y0:y1, x0:x1].copy()
                grn = np.zeros_like(sub); grn[:] = (0, 200, 0)
                ov[y0:y1, x0:x1] = cv2.addWeighted(sub, 0.6, grn, 0.4, 0)
    return ov


def read_photo(image_bytes, n_cols=12, n_rows=40):
    """PNG/JPEGのbytes → (grid, preview_bytes)。n_cols=人数, n_rows=枠数（テンプレ由来）。"""
    arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("画像を読み込めませんでした。")
    corners = detect_corners(img)
    w = warp(img, corners)
    grid, ratios = read_grid(w, n_cols, n_rows)
    prev = annotate(w, grid, n_cols, n_rows)
    ok, buf = cv2.imencode(".png", prev)
    return grid, (buf.tobytes() if ok else None)
