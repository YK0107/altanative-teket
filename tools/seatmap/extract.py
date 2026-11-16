"""東京芸術劇場コンサートホール座席表PDFから座席JSONを生成する。

usage: python tools/seatmap/extract.py <座席表.pdf> <出力.json>

- 座席形状(白塗りの角丸四角)を座席として抽出し、最寄りの数字グリフを座席番号に割当
- 番号が連続し相互に最近傍な座席を連結して「列」を作り、延長線上の列記号(A〜T)を割当
- 公式内訳表(1階676/2階683/3階640/計1,999)と一致することを検証
"""

import collections
import json
import math
import sys
from typing import Any

import pdfplumber

pdf_path, out_path = sys.argv[1], sys.argv[2]
pg = pdfplumber.open(pdf_path).pages[0]
W, H = pg.width, pg.height
WHITE = (0.0, 0.0, 0.0, 0.0)

# ---- 座席形状 ----
shapes = []
for o in pg.curves + pg.rects:
    w, h = o["x1"] - o["x0"], o["bottom"] - o["top"]
    if o.get("fill") and 6 <= w <= 9.5 and 6 <= h <= 9.5 and o.get("non_stroking_color") == WHITE:
        cx, cy = (o["x0"] + o["x1"]) / 2, (o["top"] + o["bottom"]) / 2
        if not any(abs(cx - x) < 1.5 and abs(cy - y) < 1.5 for x, y in shapes):
            shapes.append((cx, cy))


def glyph_center(c):
    a, b, cc, d, e, f = c["matrix"]
    return (e + 0.27 * a + 0.35 * cc, H - (f + 0.27 * b + 0.35 * d))


groups = collections.defaultdict(list)
for c in pg.chars:
    if not c["text"].isdigit():
        continue
    x, y = glyph_center(c)
    i = min(range(len(shapes)), key=lambda i: math.dist(shapes[i], (x, y)))
    if math.dist(shapes[i], (x, y)) < 6:
        groups[i].append((x * c["matrix"][0] - y * c["matrix"][1], c["text"]))

seats: list[dict[str, Any]] = []
for i, (x, y) in enumerate(shapes):
    if i in groups:
        num = int("".join(t for _, t in sorted(groups[i])))
        seats.append(dict(i=len(seats), x=x, y=y, num=num))

# ---- 列記号 ----
labels: list[dict[str, Any]] = []
for c in pg.chars:
    if "A" <= c["text"] <= "T" and len(c["text"]) == 1 and "Myriad" in c["fontname"]:
        p = glyph_center(c)
        if not any(o is not c and not o["text"].isdigit() and math.dist(glyph_center(o), p) < 7.5 for o in pg.chars):
            labels.append(dict(t=c["text"], x=p[0], y=p[1]))


def nearest(s, num):
    cand = [o for o in seats if o["num"] == num]
    if not cand:
        return None
    o = min(cand, key=lambda o: math.dist((s["x"], s["y"]), (o["x"], o["y"])))
    return o if math.dist((s["x"], s["y"]), (o["x"], o["y"])) < 13 else None


nxt = {}
for s in seats:
    o = nearest(s, s["num"] + 1)
    if o and nearest(o, s["num"]) is s:
        nxt[s["i"]] = o["i"]
has_prev = set(nxt.values())
chains = []
for s in seats:
    if s["i"] in has_prev:
        continue
    ch = [s["i"]]
    while ch[-1] in nxt:
        ch.append(nxt[ch[-1]])
    chains.append(ch)


def region(x, y):
    if y < 480:
        if x < 265:
            return "2LB"
        if x > W - 265:
            return "2RB"
        return "1LB" if x < 310 else "1RB" if x > W - 310 else "1"
    if y < 885:
        if x < 265 and y > 705:
            return "3LB"
        if x > W - 265 and y > 705:
            return "3RB"
        return "2"
    return "3"


row_labels = {}
for ch in chains:
    a, b = seats[ch[0]], seats[ch[-1]]
    ang = 0.0
    if len(ch) > 1:
        dx, dy = b["x"] - a["x"], b["y"] - a["y"]
        L = math.hypot(dx, dy)
        ux, uy = dx / L, dy / L
        ang = math.degrees(math.atan2(dy, dx))
    best = None
    for lab in labels:
        for end, sgn in ((a, -1), (b, 1)):
            vx, vy = lab["x"] - end["x"], lab["y"] - end["y"]
            if len(ch) > 1:
                along, perp = (vx * ux + vy * uy) * sgn, abs(-vx * uy + vy * ux)
                if 0 < along < 22 and perp < 4.5 and (best is None or along + perp * 3 < best[0]):
                    best = (along + perp * 3, lab)
            else:
                d = math.hypot(vx, vy)
                if d < 16 and abs(vy) < 4.5 and (best is None or d < best[0]):
                    best = (d, lab)
    # 2階バルコニーA列は扉で分断され列記号が途中にしかないため A 扱い
    row = best[1]["t"] if best else "A"
    mx = sum(seats[i]["x"] for i in ch) / len(ch)
    my = sum(seats[i]["y"] for i in ch) / len(ch)
    area = region(mx, my)
    if best:
        row_labels[(area, row, round(best[1]["x"]), round(best[1]["y"]))] = best[1]
    for i in ch:
        seats[i].update(row=row, area=area, rot=round(ang, 1))

# ---- 車椅子スペース(1階O列脇の常設2箇所×2台) ----
wheel = [(325.7, 400.65), (335.9, 403.45), (W - 335.9, 403.45), (W - 325.7, 400.65)]
for k, (x, y) in enumerate(wheel, 1):
    seats.append(dict(x=x, y=y, num=k, row="車椅子", area="1", rot=15.0 if x < W / 2 else -15.0, wc=True))

# ---- 階ごとの配置変換 ----
# 2階バルコニーは紙面上1階(舞台)の両脇に描かれている。舞台との位置関係は紙面どおりに保ち、
# 2階本体との間(1階客席ぶん)だけ縦に詰める
BALCONY_DY = 120
SHIFT = {"2LB": (0, BALCONY_DY), "2RB": (0, BALCONY_DY)}
# 舞台の外形(紙面のピンクの台形)。2階の図でバルコニーの間に描く
stage_shapes = [
    o
    for o in pg.curves
    if o.get("fill") and o.get("non_stroking_color") == (0.0, 0.1, 0.05, 0.0) and o["x1"] - o["x0"] > 150
]
assert len(stage_shapes) == 1, len(stage_shapes)
stage_pts: list[tuple[float, float]] = []
for px, py in stage_shapes[0]["pts"]:
    if (px, py) not in stage_pts:
        stage_pts.append((px, py))
STAGE = {2: [[round(px, 1), round(py + BALCONY_DY, 1)] for px, py in stage_pts]}
AREA_NAME = {
    "1": "1階", "1LB": "1階LB", "1RB": "1階RB",
    "2": "2階", "2LB": "2階LB", "2RB": "2階RB",
    "3": "3階", "3LB": "3階LB", "3RB": "3階RB",
}  # fmt: skip

out_seats, ids = [], set()
for s in seats:
    area = s["area"]
    floor = int(area[0])
    dx, dy = SHIFT.get(area, (0, 0))
    if s.get("wc"):
        sid, cat = f"WC-{s['num']}", "W"
    else:
        sid = f"{area}-{s['row']}-{s['num']}"
        cat = "A" if floor == 3 else "S"
    assert sid not in ids, sid
    ids.add(sid)
    out_seats.append(
        dict(
            id=sid,
            f=floor,
            a=AREA_NAME[area],
            r=s["row"],
            n=s["num"],
            x=round(s["x"] + dx, 1),
            y=round(s["y"] + dy, 1),
            rot=s["rot"],
            c=cat,
        )
    )

out_labels = []
for (area, row, _, _), lab in row_labels.items():
    dx, dy = SHIFT.get(area, (0, 0))
    out_labels.append(dict(f=int(area[0]), t=row, x=round(lab["x"] + dx, 1), y=round(lab["y"] + dy, 1)))

cnt = collections.Counter(s["f"] for s in out_seats if s["c"] != "W")
assert (cnt[1], cnt[2], cnt[3]) == (676, 683, 640), cnt
floors = []
for f in (1, 2, 3):
    xs = [s["x"] for s in out_seats if s["f"] == f]
    ys = [s["y"] for s in out_seats if s["f"] == f]
    pad = 18
    # 舞台の外形を描かない階は、上端に「ステージ方向」の帯を置く余白を足す
    top = 0 if f in STAGE else 25
    view_box = [
        round(min(xs) - pad),
        round(min(ys) - pad - top),
        round(max(xs) - min(xs) + 2 * pad),
        round(max(ys) - min(ys) + 2 * pad + top),
    ]
    floor_def: dict[str, Any] = dict(f=f, name=f"{f}階", viewBox=view_box)
    if f in STAGE:
        floor_def["stage"] = STAGE[f]
    floors.append(floor_def)
with open(out_path, "w") as fp:
    json.dump(
        dict(venue="東京芸術劇場 コンサートホール", floors=floors, seats=out_seats, labels=out_labels),
        fp,
        ensure_ascii=False,
        separators=(",", ":"),
    )
print("seats", len(out_seats), dict(cnt), "labels", len(out_labels))
