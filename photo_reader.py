"""手書き希望表の写真から × を読み取るモジュール（方式1）。
固定テンプレ前提：四隅の位置合わせマークで補正し、較正済みのマス目座標で各セルの
黒インク量から × / 空欄 を判定する。氏名・枠・年度・希望はExcelテンプレ側で持つ。
"""
import cv2
import numpy as np

# ---- 較正値（OW×OH に補正した座標系でのマス目位置）----
OW, OH = 1400, 1950
GRID = dict(x0=246, x1=1294, y0=200, y1=1892)  # メンバー12列・データ40行の外枠
INK_THRESH = 0.06     # セル内の黒画素率がこれ以上なら ×
DARK = 110            # これ未満を黒インクとみなす
MARGIN = 0.18         # セル内側をこの割合だけ縮めて罫線を除外


def detect_corners(img):
    H, W = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, dark = cv2.threshold(gray, 80, 255, cv2.THRESH_BINARY_INV)
    n, lab, stats, cent = cv2.connectedComponentsWithStats(dark, 8)
    area_min = 0.00002 * H * W
    area_max = 0.0009 * H * W
    cands = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area_min < area < area_max and 0.55 < w / max(h, 1) < 1.8:
            cx, cy = cent[i]
            if (cx < W * 0.2 or cx > W * 0.8) and (cy < H * 0.15 or cy > H * 0.88):
                cands.append((cx, cy))
    if len(cands) < 4:
        raise ValueError("四隅の位置合わせマークが検出できませんでした。"
                         "マーク付きの用紙を、なるべく真上から撮影してください。")

    def pick(fx, fy):
        return min(cands, key=lambda p: (p[0] - fx) ** 2 + (p[1] - fy) ** 2)
    return pick(0, 0), pick(W, 0), pick(0, H), pick(W, H)


def warp(img, corners):
    src = np.float32(list(corners))
    dst = np.float32([[0, 0], [OW, 0], [0, OH], [OW, OH]])
    M = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(img, M, (OW, OH))


def _cells(n_cols=12):
    xs = np.linspace(GRID["x0"], GRID["x1"], n_cols + 1)
    ys = np.linspace(GRID["y0"], GRID["y1"], 41)
    return xs, ys


def read_grid(warped, n_cols=12):
    """warped画像から 40行×n_cols列 の×真偽（1=×）とインク率を返す。"""
    g = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
    xs, ys = _cells(n_cols)
    grid, ratios = [], []
    for r in range(40):
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


def annotate(warped, grid, n_cols=12):
    """×と判定したセルを緑で塗った確認用プレビューを返す。"""
    ov = warped.copy()
    xs, ys = _cells(n_cols)
    for r in range(40):
        y0, y1 = int(ys[r]), int(ys[r + 1])
        for c in range(n_cols):
            if grid[r][c]:
                x0, x1 = int(xs[c]), int(xs[c + 1])
                sub = ov[y0:y1, x0:x1].copy()
                grn = np.zeros_like(sub); grn[:] = (0, 200, 0)
                ov[y0:y1, x0:x1] = cv2.addWeighted(sub, 0.6, grn, 0.4, 0)
    return ov


def read_photo(image_bytes, n_cols=12):
    """PNG/JPEGのbytesを受け取り、(grid, preview_bytes) を返す。n_cols=メンバー人数。"""
    arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("画像を読み込めませんでした。")
    corners = detect_corners(img)
    w = warp(img, corners)
    grid, ratios = read_grid(w, n_cols)
    prev = annotate(w, grid, n_cols)
    ok, buf = cv2.imencode(".png", prev)
    return grid, (buf.tobytes() if ok else None)
