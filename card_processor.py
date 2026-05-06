"""
card_processor.py
Processes raw grabbed images into framed cards using PIL.

Assets expected in ./assets/ folder:
  common.png        — Common frame
  rare.png          — Rare frame
  secretRare.png    — Secret Rare frame
  legendary.png     — Legendary frame
  mythicRare.png    — Mythic Rare frame
  secretMythic.gif  — Secret Mythic frame (first frame used as static)
  primodialRare.png — Primordial frame
  glow.png          — Optional embellishment: warm iridescent screen blend
  reflect.png       — Optional embellishment: holographic foil multiply blend

Naming conventions (auto-incremented per tier):
  Common:         original filename preserved (e.g. IMG_0252.jpg)
  Rare:           RareFoil001.jpg, RareFoil002.jpg, ...
  Secret Rare:    SecretRareFoil001.jpg, ...
  Legendary:      LegendFoil001.jpg, ...
  Mythic Rare:    MythicRareFoil001.jpg, ...
  Secret Mythic:  SecretMythicFoil001.jpg, ...
  Primordial:     PrimordialFoil001.jpg, ...

Embellishments (reflect / glow) are optional per-card flags passed at grab
time. They are baked into the output JPEG — nothing is stored in card data.
ultra_rare is legacy-read-only and cannot be targeted by grab/grablink.
"""
from pathlib import Path
from PIL import Image, ImageOps, ImageChops

ASSETS_DIR    = Path("assets")
TARGET_SIZE   = (600, 800)
ZOOM_FACTOR   = 1.25
GLOW_STRENGTH    = 100 / 255   # opacity of glow screen blend
REFLECT_STRENGTH = 155 / 255   # opacity of reflect multiply blend

# Maps tier → asset filename stem (no extension — loader handles that)
TIER_FRAME = {
    "common":        "common",
    "rare":          "rare",
    "ultra_rare":    "rare",          # legacy: same frame as rare
    "secret_rare":   "secretRare",
    "legendary":     "legendary",
    "mythic_rare":   "mythicRare",
    "secret_mythic": "secretMythic",  # GIF — first frame extracted as static
    "primordial":    "primodialRare", # note: matches filename typo in repo
}

# Auto-increment filename prefix per tier. Common keeps original filename.
TIER_PREFIX = {
    "rare":          "RareFoil",
    "ultra_rare":    "UltraRareFoil",  # legacy, kept for reference
    "secret_rare":   "SecretRareFoil",
    "legendary":     "LegendFoil",
    "mythic_rare":   "MythicRareFoil",
    "secret_mythic": "SecretMythicFoil",
    "primordial":    "PrimordialFoil",
}

# Asset cache — stores loaded + resized RGBA Images by stem name
_asset_cache: dict[str, Image.Image] = {}


# =============================================================================
#  Asset loading
# =============================================================================
def _load_asset(name: str) -> Image.Image | None:
    """
    Load an asset from assets/ by stem name. Tries .png first, then .gif
    (extracting the first frame for GIF assets). Resizes to TARGET_SIZE.
    Results are cached for the process lifetime.
    """
    if name in _asset_cache:
        return _asset_cache[name]

    # Try PNG first, then GIF
    for ext in (".png", ".gif"):
        path = ASSETS_DIR / f"{name}{ext}"
        if path.exists():
            img = Image.open(path)
            if ext == ".gif":
                # Extract first frame only (animated GIF support deferred)
                img.seek(0)
                img = img.convert("RGBA").copy()
            else:
                img = img.convert("RGBA")

            if img.size != TARGET_SIZE:
                img = ImageOps.fit(img, TARGET_SIZE, Image.Resampling.LANCZOS)

            _asset_cache[name] = img
            return img

    return None


def _clear_asset_cache():
    """Force reload of all assets on next use. Useful after asset updates."""
    _asset_cache.clear()


# =============================================================================
#  Blend helpers
# =============================================================================
def _apply_blend(
    base: Image.Image,
    overlay: Image.Image,
    mode: str,
    opacity: float,
) -> Image.Image:
    """
    Blend an overlay onto a base image.
    mode: 'screen' or 'multiply'
    opacity: 0.0–1.0
    Returns RGBA image.
    """
    base_rgb    = base.convert("RGB")
    overlay_rgb = overlay.convert("RGB")

    if mode == "screen":
        result = ImageChops.screen(base_rgb, overlay_rgb)
    elif mode == "multiply":
        result = ImageChops.multiply(base_rgb, overlay_rgb)
    else:
        result = base_rgb

    return Image.blend(base_rgb, result, opacity).convert("RGBA")


# =============================================================================
#  Filename helpers
# =============================================================================
def next_card_path(tier: str, tier_dir: Path) -> Path | None:
    """
    For non-common tiers, scan the tier folder and return the next
    auto-incremented output path, e.g. SecretRareFoil007.jpg.
    Returns None for common (caller preserves original filename).
    """
    prefix = TIER_PREFIX.get(tier)
    if not prefix:
        return None  # common — caller handles naming

    existing = []
    for f in tier_dir.iterdir():
        stem = f.stem
        if stem.startswith(prefix):
            suffix = stem[len(prefix):]
            if suffix.isdigit():
                existing.append(int(suffix))

    next_num = max(existing, default=0) + 1
    return tier_dir / f"{prefix}{next_num:03d}.jpg"


# =============================================================================
#  Main processing entry point
# =============================================================================
def process_card(
    source_path: Path,
    dest_path: Path,
    tier: str,
    embellishments: list[str] | None = None,
) -> tuple[bool, str]:
    """
    Process a single raw image into a framed card JPEG.

    Args:
        source_path:    Path to the raw source image.
        dest_path:      For common — the exact output path.
                        For all other tiers — only the parent folder is used;
                        filename is auto-incremented from the tier prefix.
        tier:           Rarity tier string (must be in TIER_FRAME).
        embellishments: Optional list of overlay names to apply, e.g.
                        ['reflect'], ['glow'], ['reflect', 'glow'].
                        Overlays are applied in order: reflect first, glow second.

    Returns:
        (True, "Processed: filename.jpg") on success.
        (False, "Error message") on failure.
    """
    if embellishments is None:
        embellishments = []

    frame_name = TIER_FRAME.get(tier)
    if not frame_name:
        return False, f"Unknown tier '{tier}'"

    # Non-common tiers: override dest filename with auto-incremented name
    if tier != "common":
        auto_path = next_card_path(tier, dest_path.parent)
        if auto_path is None:
            return False, f"Could not determine next filename for tier '{tier}'"
        dest_path = auto_path

    # Load frame asset (required)
    frame = _load_asset(frame_name)
    if frame is None:
        return False, f"Missing frame asset: assets/{frame_name}[.png/.gif]"

    # Load optional embellishment assets (pre-check before processing)
    reflect = glow = None
    if "reflect" in embellishments:
        reflect = _load_asset("reflect")
        if reflect is None:
            return False, "Missing asset: assets/reflect.png (needed for reflect embellishment)"
    if "glow" in embellishments:
        glow = _load_asset("glow")
        if glow is None:
            return False, "Missing asset: assets/glow.png (needed for glow embellishment)"

    try:
        with Image.open(source_path).convert("RGBA") as img:
            # 1. Fit and zoom-crop to TARGET_SIZE
            img = ImageOps.fit(img, TARGET_SIZE, Image.Resampling.LANCZOS)
            w, h = img.size
            l = (w - w / ZOOM_FACTOR) / 2
            t = (h - h / ZOOM_FACTOR) / 2
            r = (w + w / ZOOM_FACTOR) / 2
            b = (h + h / ZOOM_FACTOR) / 2
            img = img.crop((l, t, r, b)).resize(TARGET_SIZE, Image.Resampling.LANCZOS)

            # 2. Reflect embellishment — holographic foil (multiply blend)
            if reflect:
                img = _apply_blend(img, reflect, "multiply", REFLECT_STRENGTH)

            # 3. Glow embellishment — iridescent wash (screen blend)
            if glow:
                img = _apply_blend(img, glow, "screen", GLOW_STRENGTH)

            # 4. Composite frame on top (always last)
            img.alpha_composite(frame)

            # 5. Save as JPEG
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            img.convert("RGB").save(dest_path, "JPEG", quality=95)

        embellishment_note = f" [{', '.join(embellishments)}]" if embellishments else ""
        return True, f"Processed: {dest_path.name}{embellishment_note}"

    except Exception as e:
        try:
            import dashboard as dash
            dash.print_card_result(source_path.name, tier, False, str(e))
        except Exception:
            pass
        return False, f"Error on {source_path.name}: {e}"
