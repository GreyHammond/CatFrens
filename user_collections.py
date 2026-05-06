"""
user_collections.py
User card collection storage, cooldown, pity, gifts, and CDN cache helpers.

Card entry schema (per card in user["cards"]):
{
  "tier":         str,        — rarity tier
  "count":        int,        — total copies owned
  "first_pulled": str,        — ISO 8601 UTC timestamp of first pull
  "cdn_url":      str | None, — cached Discord CDN URL (expires after 24hr)
  "cdn_expires":  str | None, — ISO 8601 UTC expiry for cdn_url
}

CDN cache logic:
  When a card is uploaded to Discord, the returned CDN URL is stored here.
  For 24 hours, that URL is used directly (no re-upload needed).
  After expiry, falls back to GitHub raw URL, then re-uploads and re-caches.
"""
import json
import os
from datetime import datetime, timezone, timedelta
from config import COLLECTIONS_FILE, DEFAULT_PULL_COOLDOWN_MINUTES, PITY_THRESHOLD, TIERS

# =============================================================================
#  Tier rank map — covers all 8 tiers, used for sorting (0 = rarest)
# =============================================================================
TIER_RANK = {
    "primordial":    0,
    "secret_mythic": 1,
    "mythic_rare":   2,
    "legendary":     3,
    "secret_rare":   4,
    "ultra_rare":    5,
    "rare":          6,
    "common":        7,
}

# =============================================================================
#  Storage
# =============================================================================
def load_collections() -> dict:
    if os.path.exists(COLLECTIONS_FILE):
        with open(COLLECTIONS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_collections(data: dict):
    with open(COLLECTIONS_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_user(data: dict, user_id: int) -> dict:
    """
    Return user entry, creating a blank one for new or grandfathered users.
    All fields default safely so existing collections.json entries are
    compatible without migration.
    """
    key = str(user_id)
    if key not in data:
        data[key] = {
            "cards":          {},
            "total_pulls":    0,
            "pity_counter":   0,
            "last_pull":      None,
            "pending_gifts":  [],
        }
    return data[key]

# =============================================================================
#  Cooldown
# =============================================================================
def get_cooldown_minutes(guild_cfg: dict, member_role_ids: set[int]) -> int:
    role_cooldowns = guild_cfg.get("cooldowns", {}).get("roles", {})
    applicable = [
        minutes for role_id_str, minutes in role_cooldowns.items()
        if int(role_id_str) in member_role_ids
    ]
    if applicable:
        return min(applicable)
    return guild_cfg.get("cooldowns", {}).get("default", DEFAULT_PULL_COOLDOWN_MINUTES)

def check_cooldown(user_data: dict, cooldown_minutes: int) -> tuple[bool, int]:
    last = user_data.get("last_pull")
    if not last:
        return True, 0
    last_dt   = datetime.fromisoformat(last)
    elapsed   = (datetime.now(timezone.utc) - last_dt).total_seconds()
    remaining = (cooldown_minutes * 60) - elapsed
    if remaining <= 0:
        return True, 0
    return False, int(remaining)

# =============================================================================
#  Recording pulls
#  record_normal_pull  — updates last_pull (touches cooldown)
#  record_gift_claim   — does NOT update last_pull (cooldown untouched)
# =============================================================================
def _add_card(user: dict, filename: str, tier: str):
    """Add a card to the user's collection or increment its count."""
    now = datetime.now(timezone.utc).isoformat()
    if filename not in user["cards"]:
        user["cards"][filename] = {
            "tier":        tier,
            "count":       1,
            "first_pulled": now,
            "cdn_url":     None,
            "cdn_expires": None,
        }
    else:
        user["cards"][filename]["count"] += 1
        # Ensure cdn fields exist on older entries (backwards compatibility)
        user["cards"][filename].setdefault("cdn_url",     None)
        user["cards"][filename].setdefault("cdn_expires", None)

def _update_pity(user: dict, tier: str):
    if tier == "common":
        user["pity_counter"] = user.get("pity_counter", 0) + 1
    else:
        user["pity_counter"] = 0

def record_normal_pull(data: dict, user_id: int, filename: str, tier: str):
    """Full pull record — updates last_pull, touches cooldown."""
    user = get_user(data, user_id)
    _add_card(user, filename, tier)
    _update_pity(user, tier)
    user["total_pulls"] = user.get("total_pulls", 0) + 1
    user["last_pull"]   = datetime.now(timezone.utc).isoformat()
    save_collections(data)

def record_gift_claim(data: dict, user_id: int, filename: str, tier: str):
    """Gift claim — adds card and updates pity, but does NOT touch last_pull."""
    user = get_user(data, user_id)
    _add_card(user, filename, tier)
    _update_pity(user, tier)
    user["total_pulls"] = user.get("total_pulls", 0) + 1
    # last_pull intentionally NOT updated
    save_collections(data)

# Keep old name as alias for any remaining references
def record_pull(data: dict, user_id: int, filename: str, tier: str):
    record_normal_pull(data, user_id, filename, tier)

# =============================================================================
#  CDN URL cache
# =============================================================================
def get_cached_image_url(user_data: dict, filename: str) -> str | None:
    """
    Return a valid cached Discord CDN URL for a card, or None if expired/absent.
    CDN URLs are valid for 24 hours from when they were cached.
    """
    card = user_data.get("cards", {}).get(filename)
    if not card:
        return None
    cdn_url     = card.get("cdn_url")
    cdn_expires = card.get("cdn_expires")
    if not cdn_url or not cdn_expires:
        return None
    try:
        expires_dt = datetime.fromisoformat(cdn_expires)
        if datetime.now(timezone.utc) < expires_dt:
            return cdn_url
    except (ValueError, TypeError):
        pass
    return None

def set_cached_image_url(
    data: dict,
    user_id: int,
    filename: str,
    cdn_url: str,
    ttl_hours: int = 24,
):
    """
    Store a Discord CDN URL for a card with a TTL expiry.
    Called after a successful file upload to Discord so subsequent
    serves can use the URL directly without re-uploading.
    """
    user = get_user(data, user_id)
    card = user.get("cards", {}).get(filename)
    if not card:
        return  # card not in collection — nothing to cache
    expires = (datetime.now(timezone.utc) + timedelta(hours=ttl_hours)).isoformat()
    user["cards"][filename]["cdn_url"]     = cdn_url
    user["cards"][filename]["cdn_expires"] = expires
    save_collections(data)

def clear_cached_image_url(data: dict, user_id: int, filename: str):
    """Invalidate a card's CDN cache (e.g. after a known expiry)."""
    user = get_user(data, user_id)
    card = user.get("cards", {}).get(filename)
    if card:
        card["cdn_url"]     = None
        card["cdn_expires"] = None
        save_collections(data)

# =============================================================================
#  Pending gifts
#  Each gift is {"tier": str, "filename": str | None}
#  filename=None means random from that tier
#  filename=str  means deliver that exact card
# =============================================================================
def add_pending_gift(data: dict, user_id: int, tier: str, filename: str = None):
    user = get_user(data, user_id)
    user.setdefault("pending_gifts", []).append({
        "tier":     tier,
        "filename": filename,
    })
    save_collections(data)

def pop_pending_gift(data: dict, user_id: int) -> dict | None:
    """Remove and return the next pending gift, or None if empty.
    Handles both old string format and new dict format for backwards compatibility."""
    user  = get_user(data, user_id)
    gifts = user.get("pending_gifts", [])
    if not gifts:
        return None
    gift = gifts.pop(0)
    user["pending_gifts"] = gifts
    save_collections(data)
    # Backwards compatibility: old format was just a tier string
    if isinstance(gift, str):
        return {"tier": gift, "filename": None}
    return gift

def has_pending_gift(data: dict, user_id: int) -> bool:
    return bool(get_user(data, user_id).get("pending_gifts", []))

def pending_gift_count(data: dict, user_id: int) -> int:
    return len(get_user(data, user_id).get("pending_gifts", []))

# =============================================================================
#  Duplicate helpers
# =============================================================================
def get_duplicates(user_data: dict) -> list[dict]:
    """
    Returns cards with count > 1, sorted by tier rank (rarest first)
    then first_pulled. Covers all 8 tiers.
    Each entry: {filename, tier, count, tradeable, first_pulled}
    tradeable = count - 1 (always keep at least one copy)
    """
    dupes = []
    for filename, info in user_data.get("cards", {}).items():
        if info.get("count", 1) > 1:
            dupes.append({
                "filename":    filename,
                "tier":        info["tier"],
                "count":       info["count"],
                "tradeable":   info["count"] - 1,
                "first_pulled": info.get("first_pulled", ""),
            })
    dupes.sort(key=lambda x: (
        TIER_RANK.get(x["tier"], 99),
        x["first_pulled"]
    ))
    return dupes

def get_tradeable_count(user_data: dict, tier: str) -> int:
    """Total tradeable duplicates of a specific tier (count-1 per card, summed)."""
    total = 0
    for info in user_data.get("cards", {}).values():
        if info.get("tier") == tier and info.get("count", 1) > 1:
            total += info["count"] - 1
    return total

def consume_duplicates_for_trade(data: dict, user_id: int, tier: str, amount: int) -> bool:
    """
    Consume `amount` duplicate cards of `tier` (oldest first, keeping 1 of each).
    Returns True if successful, False if not enough duplicates.
    """
    user = get_user(data, user_id)
    if get_tradeable_count(user, tier) < amount:
        return False

    tier_cards = [
        (fn, info) for fn, info in user["cards"].items()
        if info.get("tier") == tier and info.get("count", 1) > 1
    ]
    tier_cards.sort(key=lambda x: x[1].get("first_pulled", ""))

    remaining = amount
    for filename, info in tier_cards:
        if remaining <= 0:
            break
        available = info["count"] - 1
        consume   = min(available, remaining)
        user["cards"][filename]["count"] -= consume
        remaining -= consume

    save_collections(data)
    return True

def sell_card_copies(
    data: dict,
    user_id: int,
    filename: str,
    quantity: int,
) -> tuple[bool, str]:
    """
    Remove `quantity` copies of a card from the user's collection.
    Any quantity is allowed including selling the last copy.
    Returns (success, error_message_or_empty).
    """
    user = get_user(data, user_id)
    card = user.get("cards", {}).get(filename)

    if not card:
        return False, f"You don't own a card named `{filename}`."
    if quantity < 1:
        return False, "Quantity must be at least 1."
    if card["count"] < quantity:
        return False, (
            f"You only have **{card['count']}** of `{filename}` "
            f"but tried to sell **{quantity}**."
        )

    card["count"] -= quantity
    if card["count"] == 0:
        # Remove card entirely if last copy sold
        del user["cards"][filename]
    save_collections(data)
    return True, ""

# =============================================================================
#  Collection queries
# =============================================================================
def get_collection_by_tier(user_data: dict) -> dict[str, list[dict]]:
    """
    Returns cards grouped by tier, each tier sorted by first_pulled.
    All 8 tiers included. ultra_rare retained for legacy collections.
    """
    tiers = {t: [] for t in TIERS}
    for filename, info in user_data.get("cards", {}).items():
        tier = info.get("tier", "common")
        if tier in tiers:
            tiers[tier].append({"filename": filename, **info})
    for tier in tiers:
        tiers[tier].sort(key=lambda x: x.get("first_pulled", ""))
    return tiers

def get_all_cards_sorted(user_data: dict, descending: bool = False) -> list[dict]:
    """
    Returns all cards as a flat list sorted by tier rank then first_pulled.
    descending=True puts rarest cards first (primordial → common).
    descending=False puts common first (common → primordial).
    Each entry includes filename and all card info fields.
    """
    cards = []
    for filename, info in user_data.get("cards", {}).items():
        cards.append({"filename": filename, **info})

    # TIER_RANK: 0=primordial (rarest), 7=common.
    # descending=False → common first  → sort rank descending (7→0)
    # descending=True  → rarest first  → sort rank ascending  (0→7)
    cards.sort(key=lambda x: (
        TIER_RANK.get(x.get("tier", "common"), 99),
        x.get("first_pulled", "")
    ), reverse=not descending)
    return cards

def completion_percent(user_data: dict, total_cards: int) -> float:
    if total_cards == 0:
        return 0.0
    unique = len(user_data.get("cards", {}))
    return round((unique / total_cards) * 100, 1)

def rarest_card(user_data: dict) -> tuple[str | None, str | None]:
    """Return (filename, tier) of the rarest card owned, or (None, None)."""
    best      = None
    best_rank = 999
    best_tier = None
    for filename, info in user_data.get("cards", {}).items():
        tier = info.get("tier", "common")
        rank = TIER_RANK.get(tier, 99)
        if rank < best_rank:
            best      = filename
            best_rank = rank
            best_tier = tier
    return best, best_tier

# =============================================================================
#  Daily / Weekly booster claim tracking
# =============================================================================
def _utc_now():
    return datetime.now(timezone.utc)

def can_claim_daily(user_data: dict) -> tuple[bool, int]:
    """Returns (can_claim, seconds_until_reset). Resets at UTC midnight."""
    last = user_data.get("last_daily_claim")
    if not last:
        return True, 0
    last_dt       = datetime.fromisoformat(last)
    now           = _utc_now()
    last_midnight = last_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    next_midnight = last_midnight + timedelta(days=1)
    if now >= next_midnight:
        return True, 0
    return False, int((next_midnight - now).total_seconds())

def can_claim_weekly(user_data: dict) -> tuple[bool, int]:
    """Returns (can_claim, seconds_until_reset). Resets Monday UTC midnight."""
    last = user_data.get("last_weekly_claim")
    if not last:
        return True, 0
    last_dt           = datetime.fromisoformat(last)
    now               = _utc_now()
    days_since_monday = now.weekday()
    last_reset        = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_since_monday)
    if last_dt < last_reset:
        return True, 0
    next_monday = last_reset + timedelta(days=7)
    return False, int((next_monday - now).total_seconds())

def record_daily_claim(data: dict, user_id: int):
    user = get_user(data, user_id)
    user["last_daily_claim"]   = _utc_now().isoformat()
    user["total_daily_claims"] = user.get("total_daily_claims", 0) + 1
    save_collections(data)

def record_weekly_claim(data: dict, user_id: int):
    user = get_user(data, user_id)
    user["last_weekly_claim"]   = _utc_now().isoformat()
    user["total_weekly_claims"] = user.get("total_weekly_claims", 0) + 1
    save_collections(data)

# =============================================================================
#  Bonus pack gifting (owner-gifted, independent of daily/weekly)
# =============================================================================
def add_bonus_pack(data: dict, user_id: int, pack_type: str):
    """Queue a bonus pack ('daily' or 'weekly') for a user. Stacks."""
    user = get_user(data, user_id)
    user.setdefault("bonus_packs", []).append(pack_type)
    save_collections(data)

def pop_bonus_pack(data: dict, user_id: int) -> str | None:
    """Remove and return the next bonus pack type, or None if none waiting."""
    user  = get_user(data, user_id)
    packs = user.get("bonus_packs", [])
    if not packs:
        return None
    pack_type = packs.pop(0)
    user["bonus_packs"] = packs
    save_collections(data)
    return pack_type

def bonus_pack_count(data: dict, user_id: int) -> int:
    return len(get_user(data, user_id).get("bonus_packs", []))
