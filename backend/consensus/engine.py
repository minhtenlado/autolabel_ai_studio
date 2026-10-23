import math
from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class Detection:
    class_name: str
    box: list[float]
    score: float
    source: str
    ambiguous: bool = False
    mask: Optional[dict] = None


def iou(a, b):
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    aa = max(0, a[2] - a[0]) * max(0, a[3] - a[1])
    bb = max(0, b[2] - b[0]) * max(0, b[3] - b[1])
    return inter / max(1e-9, aa + bb - inter)


def match_and_score(yolo, dino, width, height, match_iou=0.4, min_area=0.00015):
    def valid(d):
        return (
            len(d.box) == 4
            and all(math.isfinite(v) for v in d.box)
            and math.isfinite(d.score)
            and d.box[2] > max(0, d.box[0])
            and d.box[3] > max(0, d.box[1])
            and d.box[0] < width
            and d.box[1] < height
        )

    yolo = [d for d in yolo if valid(d)]
    dino = [d for d in dino if valid(d)]
    # Greedy one-to-one matching: each detection can participate in one pair only.
    edges = sorted(
        (
            (iou(a.box, b.box), i, j)
            for i, a in enumerate(yolo)
            for j, b in enumerate(dino)
        ),
        reverse=True,
    )
    pairs = {}
    used_y = set()
    used_d = set()
    for ov, i, j in edges:
        if ov < match_iou:
            break
        if i not in used_y and j not in used_d:
            pairs[i] = (j, ov)
            used_y.add(i)
            used_d.add(j)
    out = []

    def add(box, cls, score, source, quality, heuristic, meta, accept=False):
        x1, y1, x2, y2 = map(float, box)
        warnings = []
        if not all(map(lambda v: v == v and abs(v) != float("inf"), (x1, y1, x2, y2))):
            warnings.append("tọa độ không hữu hạn")
        if x2 <= x1 or y2 <= y1:
            warnings.append("box có kích thước không hợp lệ")
        else:
            if x1 < 0 or y1 < 0 or x2 > width or y2 > height:
                warnings.append("box vượt biên ảnh")
            if (x2 - x1) * (y2 - y1) / (width * height) < min_area:
                warnings.append("đối tượng rất nhỏ")
        meta = dict(meta)
        meta["warnings"] = warnings
        if warnings and quality == "high_agreement":
            quality = "needs_review"
        out.append(
            {
                "class_name": cls,
                "box": [max(0, x1), max(0, y1), min(width, x2), min(height, y2)],
                "score": float(score),
                "source": source,
                "quality": quality,
                "heuristic_score": round(max(0, min(1, float(heuristic))), 3),
                "metadata": meta,
                "accepted": bool(
                    accept and not warnings and quality == "high_agreement"
                ),
            }
        )

    for i, a in enumerate(yolo):
        if i in pairs:
            j, ov = pairs[i]
            b = dino[j]
            if a.class_name == b.class_name and not a.ambiguous and not b.ambiguous:
                # Keep YOLO geometry as the baseline; record both independent predictions.
                add(
                    a.box,
                    a.class_name,
                    a.score,
                    "yolo+dino",
                    "high_agreement",
                    0.55 * a.score + 0.25 * b.score + 0.2 * ov,
                    {
                        "yolo": asdict(a),
                        "dino": asdict(b),
                        "iou": round(ov, 4),
                        "agreement": "same_class",
                    },
                )
            else:
                add(
                    a.box,
                    a.class_name,
                    a.score,
                    "yolo+dino",
                    "high_risk",
                    0.25 * a.score + 0.2 * b.score + 0.2 * ov,
                    {
                        "yolo": asdict(a),
                        "dino": asdict(b),
                        "iou": round(ov, 4),
                        "agreement": "class_conflict",
                        "conflict_class": b.class_name,
                    },
                )
        else:
            add(
                a.box,
                a.class_name,
                a.score,
                "yolo_only",
                "needs_review",
                0.45 * a.score,
                {"yolo": asdict(a), "agreement": "unmatched_yolo"},
            )
    for j, b in enumerate(dino):
        if j not in used_d:
            add(
                b.box,
                b.class_name,
                b.score,
                "dino_only",
                "high_risk" if b.ambiguous else "needs_review",
                0.3 * b.score,
                {
                    "dino": asdict(b),
                    "agreement": "potential_missed_by_yolo",
                    "ambiguous": b.ambiguous,
                },
            )
    return out
