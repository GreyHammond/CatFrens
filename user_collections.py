import json
import os
from datetime import datetime, timezone
from config import COLLECTIONS_FILE, DEFAULT_PULL_COOLDOWN_MINUTES, PITY_THRESHOLD

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
    now = datetime.now(timezone.utc).isoformat()
    if filename not in user["cards"]:
        user["cards"][filename] = {
            "tier":         tier,
            "count":        1,
            "first_pulled": now,
        }
    else:
        user["cards"][filename]["count"] += 1

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
    Returns cards with count > 1, sorted by tier rank then first_pulled.
    Each entry: {"filename": str, "tier": str, "count": int, "tradeable": int}
    tradeable = count - 1 (must keep at least one)
    """
    tier_rank = {"legendary": 0, "ultra_rare": 1, "rare": 2, "common": 3}
    dupes = []
    for filename, info in user_data.get("cards", {}).items():
        if info.get("count", 1) > 1:
            dupes.append({
                "filename":   filename,
                "tier":       info["tier"],
                "count":      info["count"],
                "tradeable":  info["count"] - 1,
                "first_pulled": info.get("first_pulled", ""),
            })
    dupes.sort(key=lambda x: (tier_rank.get(x["tier"], 9), x["first_pulled"]))
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

    # Sort cards of this tier by first_pulled, consume oldest dupes first
    tier_cards = [
        (fn, info) for fn, info in user["cards"].items()
        if info.get("tier") == tier and info.get("count", 1) > 1
    ]
    tier_cards.sort(key=lambda x: x[1].get("first_pulled", ""))

    remaining = amount
    for filename, info in tier_cards:
        if remaining <= 0:
            break
        available = info["count"] - 1  # keep at least 1
        consume   = min(available, remaining)
        user["cards"][filename]["count"] -= consume
        remaining -= consume

    save_collections(data)
    return True

# =============================================================================
#  Collection queries
# =============================================================================
def get_collection_by_tier(user_data: dict) -> dict[str, list[dict]]:
    tiers = {"legendary": [], "ultra_rare": [], "rare": [], "common": []}
    for filename, info in user_data.get("cards", {}).items():
        tier = info.get("tier", "common")
        if tier in tiers:
            tiers[tier].append({"filename": filename, **info})
    for tier in tiers:
        tiers[tier].sort(key=lambda x: x["first_pulled"])
    return tiers

def completion_percent(user_data: dict, total_cards: int) -> float:
    if total_cards == 0:
        return 0.0
    unique = len(user_data.get("cards", {}))
    return round((unique / total_cards) * 100, 1)

def rarest_card(user_data: dict) -> tuple[str | None, str | None]:
    tier_rank = {"legendary": 0, "ultra_rare": 1, "rare": 2, "common": 3}
    best = None
    best_tier = None
    for filename, info in user_data.get("cards", {}).items():
        tier = info.get("tier", "common")
        if best is None or tier_rank[tier] < tier_rank[best_tier]:
            best      = filename
            best_tier = tier
    return best, best_tier

# =============================================================================
#  Daily / Weekly booster claim tracking
# =============================================================================
from datetime import timezone

def _utc_now():
    return datetime.now(timezone.utc)

def _next_utc_midnight() -> datetime:
    now = _utc_now()
    return now.replace(hour=0, minute=0, second=0, microsecond=0).replace(
        day=now.day + 1
    ) if now.hour > 0 or now.minute > 0 or now.second > 0 else now

def _next_monday_midnight() -> datetime:
    now   = _utc_now()
    days  = (7 - now.weekday()) % 7 or 7  # days until next Monday
    reset = now.replace(hour=0, minute=0, second=0, microsecond=0)
    from datetime import timedelta
    return reset + timedelta(days=days)

def can_claim_daily(user_data: dict) -> tuple[bool, int]:
    """Returns (can_claim, seconds_until_reset)."""
    last = user_data.get("last_daily_claim")
    if not last:
        return True, 0
    last_dt    = datetime.fromisoformat(last)
    now        = _utc_now()
    # Reset at UTC midnight
    last_midnight = last_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    from datetime import timedelta
    next_midnight = last_midnight + timedelta(days=1)
    if now >= next_midnight:
        return True, 0
    remaining = int((next_midnight - now).total_seconds())
    return False, remaining

def can_claim_weekly(user_data: dict) -> tuple[bool, int]:
    """Returns (can_claim, seconds_until_reset). Resets Monday UTC midnight."""
    last = user_data.get("last_weekly_claim")
    if not last:
        return True, 0
    last_dt = datetime.fromisoformat(last)
    now     = _utc_now()
    # Find the most recent Monday midnight UTC
    days_since_monday = now.weekday()  # 0=Monday
    from datetime import timedelta
    last_reset = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_since_monday)
    if last_dt < last_reset:
        return True, 0
    next_monday = last_reset + timedelta(days=7)
    remaining   = int((next_monday - now).total_seconds())
    return False, remaining

def record_daily_claim(data: dict, user_id: int):
    user = get_user(data, user_id)
    user["last_daily_claim"]    = _utc_now().isoformat()
    user["total_daily_claims"]  = user.get("total_daily_claims", 0) + 1
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