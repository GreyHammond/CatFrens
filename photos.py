import random
from pathlib import Path
from config import (
    COMMON_DIR, RARE_DIR, ULTRA_DIR, SECRET_RARE_DIR,
    LEGENDARY_DIR, MYTHIC_RARE_DIR, SECRET_MYTHIC_DIR, PRIMORDIAL_DIR,
    IMAGE_EXTS, TIERS, GITHUB_RAW_BASE,
)

# Maps tier name → folder path string.
# ultra_rare is included for legacy reads; no new cards are written there.
TIER_DIRS = {
    "common":        COMMON_DIR,
    "rare":          RARE_DIR,
    "ultra_rare":    ULTRA_DIR,
    "secret_rare":   SECRET_RARE_DIR,
    "legendary":     LEGENDARY_DIR,
    "mythic_rare":   MYTHIC_RARE_DIR,
    "secret_mythic": SECRET_MYTHIC_DIR,
    "primordial":    PRIMORDIAL_DIR,
}

# Fallback order when a tier folder is empty — steps DOWN toward common.
# ultra_rare is skipped in the fallback chain (legacy, may be empty or sparse).
FALLBACK_ORDER = [
    "primordial",
    "secret_mythic",
    "mythic_rare",
    "legendary",
    "secret_rare",
    "rare",
    "common",
]

# =============================================================================
#  Directory helpers
# =============================================================================
def get_dir(tier: str) -> Path:
    """Return the Path for a tier folder, creating it if needed."""
    p = Path(TIER_DIRS[tier])
    p.mkdir(parents=True, exist_ok=True)
    return p

# =============================================================================
#  Listing helpers
# =============================================================================
def list_tier(tier: str) -> list[Path]:
    """All image files in a specific tier folder."""
    return [
        f for f in get_dir(tier).iterdir()
        if f.suffix.lower() in IMAGE_EXTS
    ]

def list_all_photos() -> list[Path]:
    """All image files across every tier folder."""
    photos = []
    for tier in TIER_DIRS:
        photos.extend(list_tier(tier))
    return photos

def list_common_photos() -> list[Path]:
    """Only common photos — used for /foto autocomplete."""
    return list_tier("common")

def total_card_count() -> int:
    """Total unique card images across all tiers."""
    return len(list_all_photos())

def tier_card_count() -> dict[str, int]:
    """Card count broken down by tier."""
    return {tier: len(list_tier(tier)) for tier in TIER_DIRS}

# =============================================================================
#  Search helpers
# =============================================================================
def find_photo(name: str) -> tuple[Path | None, str | None]:
    """
    Search all tier folders for a photo by stem or full filename.
    Returns (path, tier) or (None, None).
    """
    name_lower = name.lower()
    for tier in TIER_DIRS:
        for photo in get_dir(tier).iterdir():
            if photo.suffix.lower() not in IMAGE_EXTS:
                continue
            if photo.stem.lower() == name_lower or photo.name.lower() == name_lower:
                return photo, tier
    return None, None

def find_photo_in_tier(name: str, tier: str) -> Path | None:
    """Find a photo by stem or filename within a specific tier folder."""
    name_lower = name.lower()
    for photo in list_tier(tier):
        if photo.stem.lower() == name_lower or photo.name.lower() == name_lower:
            return photo
    return None

# =============================================================================
#  Random pick helpers
# =============================================================================
def random_from_tier(tier: str) -> Path | None:
    """Pick a random photo from a tier. Returns None if folder is empty."""
    photos = list_tier(tier)
    return random.choice(photos) if photos else None

def pick_photo_with_fallback(tier: str) -> tuple[Path | None, str]:
    """
    Try to pick a photo from the requested tier.
    If that folder is empty, step DOWN through FALLBACK_ORDER toward common.
    ultra_rare is intentionally excluded from the fallback chain.
    Returns (path, actual_tier_used).
    """
    if tier not in FALLBACK_ORDER:
        # ultra_rare or unknown — try it directly, then fall to common
        photo = random_from_tier(tier)
        if photo:
            return photo, tier
        photo = random_from_tier("common")
        return (photo, "common") if photo else (None, "common")

    start = FALLBACK_ORDER.index(tier)
    for t in FALLBACK_ORDER[start:]:
        photo = random_from_tier(t)
        if photo:
            return photo, t
    return None, "common"

# =============================================================================
#  GitHub URL helper
# =============================================================================
def github_url_for(tier: str, filename: str) -> str:
    """
    Build the raw GitHub URL for a card image.
    filename should include extension (e.g. 'IMG_0252.jpg').
    """
    folder = TIER_DIRS.get(tier, tier)
    return f"{GITHUB_RAW_BASE}/{folder}/{filename}"
