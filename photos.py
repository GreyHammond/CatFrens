from pathlib import Path
from config import (
    PHOTOS_DIR, RARE_DIR, ULTRA_DIR, LEGENDARY_DIR, IMAGE_EXTS
)

TIER_DIRS = {
    "common":     PHOTOS_DIR,
    "rare":       RARE_DIR,
    "ultra_rare": ULTRA_DIR,
    "legendary":  LEGENDARY_DIR,
}

def get_dir(tier: str) -> Path:
    p = Path(TIER_DIRS[tier])
    p.mkdir(parents=True, exist_ok=True)
    return p

def list_tier(tier: str) -> list[Path]:
    """All image files in a specific tier folder."""
    return [f for f in get_dir(tier).iterdir() if f.suffix.lower() in IMAGE_EXTS]

def list_all_photos() -> list[Path]:
    """All image files across all tiers."""
    photos = []
    for tier in TIER_DIRS:
        photos.extend(list_tier(tier))
    return photos

def list_common_photos() -> list[Path]:
    """Only common photos — used for /foto autocomplete."""
    return list_tier("common")

def total_card_count() -> int:
    return len(list_all_photos())

def tier_card_count() -> dict[str, int]:
    return {tier: len(list_tier(tier)) for tier in TIER_DIRS}

def find_photo(name: str) -> tuple[Path | None, str | None]:
    """
    Search all tier folders for a photo by stem or full filename.
    Returns (path, tier) or (None, None).
    """
    name_lower = name.lower()
    for tier, folder in TIER_DIRS.items():
        for photo in get_dir(tier).iterdir():
            if photo.suffix.lower() not in IMAGE_EXTS:
                continue
            if photo.stem.lower() == name_lower or photo.name.lower() == name_lower:
                return photo, tier
    return None, None

def find_photo_in_tier(name: str, tier: str) -> Path | None:
    """Find a photo by name within a specific tier folder."""
    name_lower = name.lower()
    for photo in list_tier(tier):
        if photo.stem.lower() == name_lower or photo.name.lower() == name_lower:
            return photo
    return None

def random_from_tier(tier: str) -> Path | None:
    """Pick a random photo from a tier, returns None if folder is empty."""
    import random
    photos = list_tier(tier)
    return random.choice(photos) if photos else None

def pick_photo_with_fallback(tier: str) -> tuple[Path | None, str]:
    """
    Try to pick a photo from the given tier.
    If empty, fall back to next tier down until common.
    Returns (path, actual_tier).
    """
    from config import TIERS
    tier_order = TIERS[::-1]  # legendary -> ultra_rare -> rare -> common
    start = tier_order.index(tier)
    for t in tier_order[start:]:
        photo = random_from_tier(t)
        if photo:
            return photo, t
    return None, "common"
