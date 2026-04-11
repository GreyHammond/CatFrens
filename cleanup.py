"""
cleanup_duplicates.py
Run this from your CatFrens folder:
    python cleanup_duplicates.py

It will find any files in photos/ that also exist in rare/, ultra_rare/, or legendary/
and delete them from photos/. Prints a summary before doing anything.
"""

from pathlib import Path

BASE      = Path(__file__).parent
PHOTOS    = BASE / "photos"
TIERED    = [BASE / "rare", BASE / "ultra_rare", BASE / "legendary"]

# Collect all filenames in tiered folders
tiered_files = set()
for folder in TIERED:
    if folder.exists():
        for f in folder.iterdir():
            if f.is_file():
                tiered_files.add(f.name)

# Find duplicates in photos/
duplicates = [f for f in PHOTOS.iterdir() if f.is_file() and f.name in tiered_files]

if not duplicates:
    print("No duplicates found. photos/ is already clean.")
else:
    print(f"Found {len(duplicates)} duplicate(s) in photos/ that exist in a tiered folder:\n")
    for f in sorted(duplicates):
        print(f"  {f.name}")

    confirm = input(f"\nDelete these {len(duplicates)} file(s) from photos/? (yes/no): ").strip().lower()
    if confirm == "yes":
        for f in duplicates:
            f.unlink()
            print(f"  Deleted: {f.name}")
        print("\nDone. photos/ is now clean.")
    else:
        print("Aborted. Nothing deleted.")