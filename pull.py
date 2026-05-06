"""
pull.py
Tier determination for card pulls and booster packs.

determine_tier()   — main pull roll using SHA-256 + pity system
roll_booster_tier() — booster pack roll using weighted random

Tier weights and thresholds are driven entirely by config.py.
ultra_rare has weight 0 and is excluded from all new pulls.
The pity system guarantees rare-or-better after PITY_THRESHOLD consecutive
commons, preserving proportional odds among all non-common tiers.
"""
import hashlib
import random
from datetime import datetime, timezone
from config import (
    TOKEN, TIER_THRESHOLDS, TIER_WEIGHTS, PITY_THRESHOLD, TIERS
)

# Pull order for threshold checks — highest tier first so we drop through
# correctly. ultra_rare is excluded (weight 0, legacy only).
_PULL_ORDER = [
    "primordial",
    "secret_mythic",
    "mythic_rare",
    "legendary",
    "secret_rare",
    "rare",
    "common",
]

# Non-common tiers available for pity re-rolls, proportional weights preserved
_PITY_TIERS = [t for t in _PULL_ORDER if t != "common"]


def _token_value() -> int:
    """Convert TOKEN to a stable integer salt by summing ASCII values."""
    return sum(ord(c) for c in TOKEN)


def _sha256_roll(input_str: str, hex_slice: tuple[int, int]) -> int:
    """
    SHA-256 hash of input_str, take a hex slice, return int % 10000.
    hex_slice: (start, end) indices into the 64-char hex digest.
    """
    digest = hashlib.sha256(input_str.encode()).hexdigest()
    start, end = hex_slice
    return int(digest[start:end], 16) % 10000


def _roll_to_tier(roll: int) -> str:
    """
    Map a 0–9999 roll to a tier using TIER_THRESHOLDS.
    Checks highest tier first, falls through to common.
    ultra_rare is intentionally absent from _PULL_ORDER so it can never
    be newly pulled.
    """
    for tier in _PULL_ORDER:
        if roll >= TIER_THRESHOLDS[tier]:
            return tier
    return "common"


def _pity_roll(digest: str) -> str:
    """
    Force a non-common result using a secondary hex slice of the same digest.
    Distributes across non-common tiers proportionally to their weights.
    """
    total_weight = sum(TIER_WEIGHTS[t] for t in _PITY_TIERS)
    # Use hex chars 48–56 (different from the main roll's last 8 chars)
    raw = int(digest[48:56], 16) % total_weight

    cumulative = 0
    for tier in reversed(_PITY_TIERS):  # common→primordial, check lowest first
        cumulative += TIER_WEIGHTS[tier]
        if raw < cumulative:
            return tier
    return "rare"  # safe fallback


def determine_tier(user_id: int, channel_id: int, pity_counter: int) -> str:
    """
    Determine the rarity tier for a standard card pull.

    Uses SHA-256 of (user_id, timestamp, token*channel) for unpredictability.
    Applies pity: after PITY_THRESHOLD consecutive commons, forces a
    non-common result with proportional odds among all non-common tiers.

    Args:
        user_id:      Discord user ID.
        channel_id:   Discord channel ID (adds per-channel entropy).
        pity_counter: Number of consecutive commons this user has pulled.

    Returns:
        Tier string — never returns "ultra_rare" for new pulls.
    """
    token_val  = _token_value()
    salt_val   = token_val * channel_id
    timestamp  = int(datetime.now(timezone.utc).timestamp())

    hash_input = f"{user_id}_{timestamp}_{salt_val}"
    digest     = hashlib.sha256(hash_input.encode()).hexdigest()

    # Primary roll: last 8 hex chars → 0-9999
    roll = int(digest[-8:], 16) % 10000
    tier = _roll_to_tier(roll)

    # Pity override: if common and threshold hit, force non-common
    if tier == "common" and pity_counter >= PITY_THRESHOLD:
        tier = _pity_roll(digest)

    return tier


def roll_booster_tier(weights: dict) -> str:
    """
    Roll a tier for booster pack cards using an explicit weights dict.
    Weights do not need to sum to 10000 — they are normalised internally.
    ultra_rare should not be present in pack weight dicts (excluded by config).

    Args:
        weights: {tier_str: int_weight, ...} e.g. DAILY_PACK_WEIGHTS

    Returns:
        Tier string.
    """
    total = sum(weights.values())
    if total == 0:
        return "common"

    # Fresh entropy per booster roll
    entropy = f"{random.random()}_{datetime.now(timezone.utc).timestamp()}"
    digest  = hashlib.sha256(entropy.encode()).hexdigest()
    roll    = int(digest[-8:], 16) % total

    # Walk tiers from rarest to most common — first tier whose cumulative
    # weight exceeds the roll wins. Order matches _PULL_ORDER (rarest first).
    pull_order = [t for t in _PULL_ORDER if t in weights]
    cumulative = 0
    for tier in reversed(pull_order):   # common → primordial
        cumulative += weights[tier]
        if roll < cumulative:
            return tier

    return "common"  # safe fallback
