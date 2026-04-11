"""
Run from your CatFrens folder:
    python check_photos.py
"""
from pathlib import Path

FOLDERS = {
    "common":     "photos",
    "rare":       "rare",
    "ultra_rare": "ultra_rare",
    "legendary":  "legendary",
}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}

total = 0
for tier, folder in FOLDERS.items():
    p = Path(folder)
    if not p.exists():
        print(f"{tier:12} — folder '{folder}' NOT FOUND")
        continue
    files = [f for f in p.iterdir() if f.suffix.lower() in IMAGE_EXTS]
    total += len(files)
    print(f"{tier:12} — {len(files)} files in '{folder}/'")

print(f"\nTotal: {total}")
