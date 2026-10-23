"""Generate clearly marked synthetic images for browser tests, never production data."""

import sys
from pathlib import Path
from PIL import Image, ImageDraw

root = Path(sys.argv[1])
for n in range(12):
    cam = f"camera_{n//4+1:02d}"
    folder = root / cam
    folder.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (960, 600), (34 + n * 3, 58 + n * 2, 69 + n))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 959, 100), fill=(47, 67, 79))
    draw.polygon([(410, 80), (550, 80), (850, 600), (100, 600)], fill=(67, 77, 86))
    for y in range(130, 600, 80):
        draw.rectangle((475, y, 485, y + 40), fill=(210, 215, 198))
    for k in range(3 + (n % 3)):
        x = 220 + (k % 2) * 300 + k * 13
        y = 240 + (k // 2) * 105
        draw.rounded_rectangle(
            (x, y, x + 68, y + 45),
            radius=7,
            fill=[
                (90, 165, 152),
                (208, 177, 124),
                (151, 173, 209),
                (195, 126, 131),
                (162, 142, 190),
            ][k % 5],
        )
        draw.rectangle((x + 10, y + 7, x + 55, y + 16), fill=(50, 73, 88))
    draw.text(
        (28, 25),
        f"SYNTHETIC UI TEST | {cam} | FRAME {n:02d}",
        fill="white",
        font_size=24,
    )
    name = f"frame_202610{22+n%2}_1200{n:02d}.png"
    image.save(folder / name)
    if n % 4 != 3:
        (folder / Path(name).with_suffix(".txt")).write_text(
            "1 0.30 0.50 0.10 0.15\n3 0.60 0.68 0.08 0.12\n", encoding="utf-8"
        )
(root / "duplicate.png").write_bytes(next(root.rglob("*.png")).read_bytes())
(root / "corrupt.jpg").write_bytes(b"not a valid image")
print(str(root))
