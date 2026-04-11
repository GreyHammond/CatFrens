import hashlib
import random
from datetime import datetime, timezone
from config import (
    TOKEN, TIER_THRESHOLDS, PITY_THRESHOLD, TIERS
)

def _token_value() -> int:
    """Convert TOKEN to a number by summing ASCII values of each character."""
    return sum(ord(c) for c in TOKEN)

def determine_tier(user_id: int, channel_id: int, pity_counter: int) -> str:
    """
    Determine the rarity tier for a pull using:
      - SHA-256 hash of (token_value * channel_id, user_id, timestamp)
      - Pity system: forces Rare or better after PITY_THRESHOLD consecutive commons

    Returns a tier string: "common", "rare", "ultra_rare", or "legendary"
    """
    token_val  = _token_value()
    salt_val   = token_val * channel_id
    timestamp  = int(datetime.now(timezone.utc).timestamp())

    hash_input = f"{user_id}_{timestamp}_{salt_val}"
    digest     = hashlib.sha256(hash_input.encode()).hexdigest()

    # Take last 8 hex chars → integer → 0-9999
    roll = int(digest[-8:], 16) % 10000

    # Map roll to tier
    if roll >= TIER_THRESHOLDS["legendary"]:
        tier = "legendary"
    elif roll >= TIER_THRESHOLDS["ultra_rare"]:
        tier = "ultra_rare"
    elif roll >= TIER_THRESHOLDS["rare"]:
        tier = "rare"
    else:
        tier = "common"

    # Pity override — after PITY_THRESHOLD commons, force Rare or better
    if tier == "common" and pity_counter >= PITY_THRESHOLD:
        # Re-roll within the non-common range (8000-9999)
        pity_roll = int(digest[-16:-8], 16) % 2000 + 8000
        if pity_roll >= TIER_THRESHOLDS["legendary"]:
            tier = "legendary"
        elif pity_roll >= TIER_THRESHOLDS["ultra_rare"]:
            tier = "ultra_rare"
        else:
            tier = "rare"

    return tier

def roll_booster_tier(weights: dict) -> str:
    """Roll a tier using a weights dict {tier: weight out of 10000}."""
    roll = int(hashlib.sha256(
        f"{random.random()}_{datetime.now(timezone.utc).timestamp()}".encode()
    ).hexdigest()[-8:], 16) % 10000

    cumulative = 0
    order = ["common", "rare", "ultra_rare", "legendary"]
    thresholds = {}
    total = sum(weights.values())
    for tier in order:
        cumulative += int(weights.get(tier, 0) * 10000 / total)
        thresholds[tier] = cumulative

    if roll >= thresholds["ultra_rare"]:
        return "legendary"
    elif roll >= thresholds["rare"]:
        return "ultra_rare"
    elif roll >= thresholds["common"]:
        return "rare"
    return "common"