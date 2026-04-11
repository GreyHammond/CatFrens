"""
card_processor.py
Processes raw grabbed images into framed cards using PIL.
Assets expected in ./assets/ folder:
  common.png   — Common frame
  rare.png     — Rare + Ultra Rare frame
  glow.png     — Legendary glow overlay (screen blend)
  reflect.png  — Ultra Rare / Legendary reflection overlay (multiply blend)
  legend.png   — Legendary frame

Naming conventions (auto-incremented):
  Rare:       RareFoil001, RareFoil002, ...
  Ultra Rare: UltraRareFoil001, UltraRareFoil002, ...
  Legendary:  LegendFoil001, LegendFoil002, ...
  Common:     original filename preserved
"""
from pathlib import Path
from PIL import Image, ImageOps, ImageChops

ASSETS_DIR    = Path("assets")
TARGET_SIZE   = (600, 800)
ZOOM_FACTOR   = 1.25
GLOW_STRENGTH    = 100 / 255
REFLECT_STRENGTH = 155 / 255

TIER_FRAME = {
    "common":     "common",
    "rare":       "rare",
    "ultra_rare": "rare",    # silver frame + reflect
    "legendary":  "legend",  # gold frame + reflect + glow
}

# Naming prefix per tier for auto-increment
TIER_PREFIX = {
    "rare":       "RareFoil",
    "ultra_rare": "UltraRareFoil",
    "legendary":  "LegendFoil",
}

_asset_cache: dict[str, Image.Image] = {}

def _load_asset(name: str) -> Image.Image | None:
    if name in _asset_cache:
        return _asset_cache[name]
    path = ASSETS_DIR / f"{name}.png"
    if not path.exists():
        return None
    img = Image.open(path).convert("RGBA")
    if img.size != TARGET_SIZE:
        img = ImageOps.fit(img, TARGET_SIZE, Image.Resampling.LANCZOS)
    _asset_cache[name] = img
    return img

def _apply_blend(base: Image.Image, overlay: Image.Image, mode: str, opacity: float) -> Image.Image:
    base_rgb    = base.convert("RGB")
    overlay_rgb = overlay.convert("RGB")
    if mode == "screen":
        result = ImageChops.screen(base_rgb, overlay_rgb)
    elif mode == "multiply":
        result = ImageChops.multiply(base_rgb, overlay_rgb)
    else:
        result = base_rgb
    return Image.blend(base_rgb, result, opacity).convert("RGBA")

def next_card_path(tier: str, tier_dir: Path) -> Path:
    """
    For non-common tiers, scan the tier folder and return the next
    auto-incremented filename, e.g. UltraRareFoil007.jpg
    Commons keep their original filename (handled by caller).
    """
    prefix = TIER_PREFIX.get(tier)
    if not prefix:
        return None  # common — caller handles naming

    # Find all existing files matching the prefix
    existing = []
    for f in tier_dir.iterdir():
        stem = f.stem
        if stem.startswith(prefix):
            suffix = stem[len(prefix):]
            if suffix.isdigit():
                existing.append(int(suffix))

    next_num = max(existing, default=0) + 1
    return tier_dir / f"{prefix}{next_num:03d}.jpg"

def process_card(source_path: Path, dest_path: Path, tier: str) -> tuple[bool, str]:
    """
    Process a single image into a framed card.
    For rare/ultra_rare/legendary, dest_path is used only for the folder —
    the filename is auto-incremented from the tier prefix.
    Returns (success: bool, message: str).
    """
    frame_name = TIER_FRAME.get(tier)
    if not frame_name:
        return False, f"Unknown tier '{tier}'"

    # For non-common tiers, override the destination filename
    if tier != "common":
        auto_path = next_card_path(tier, dest_path.parent)
        if auto_path is None:
            return False, f"Could not determine next filename for tier '{tier}'"
        dest_path = auto_path

    # Determine which overlay assets are needed
    needs_reflect = tier in ("ultra_rare", "legendary")
    needs_glow    = tier == "legendary"

    # Pre-check all needed assets
    frame = _load_asset(frame_name)
    if frame is None:
        return False, f"Missing asset: assets/{frame_name}.png"

    glow = reflect = None
    if needs_glow:
        glow = _load_asset("glow")
        if glow is None:
            return False, "Missing asset: assets/glow.png"
    if needs_reflect:
        reflect = _load_asset("reflect")
        if reflect is None:
            return False, "Missing asset: assets/reflect.png"

    try:
        with Image.open(source_path).convert("RGBA") as img:
            # 1. Zoom and crop to TARGET_SIZE
            img = ImageOps.fit(img, TARGET_SIZE, Image.Resampling.LANCZOS)
            w, h = img.size
            l = (w - w / ZOOM_FACTOR) / 2
            t = (h - h / ZOOM_FACTOR) / 2
            r = (w + w / ZOOM_FACTOR) / 2
            b = (h + h / ZOOM_FACTOR) / 2
            img = img.crop((l, t, r, b)).resize(TARGET_SIZE, Image.Resampling.LANCZOS)

            # 2. Reflect overlay (Ultra Rare + Legendary) — multiply blend
            if reflect:
                img = _apply_blend(img, reflect, "multiply", REFLECT_STRENGTH)

            # 3. Glow overlay (Legendary only) — screen blend on top of reflect
            if glow:
                img = _apply_blend(img, glow, "screen", GLOW_STRENGTH)

            # 4. Composite frame on top last
            img.alpha_composite(frame)

            # 5. Save as JPEG
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            img.convert("RGB").save(dest_path, "JPEG", quality=95)

        return True, f"Processed: {dest_path.name}"

    except Exception as e:
        try:
            import dashboard as dash
            dash.print_card_result(source_path.name, tier, False, str(e))
        except Exception:
            pass
        return False, f"Error on {source_path.name}: {e}"
