"""
economy.py
CatCoins economy system for CatFrens.

Handles all coin storage, earn/spend operations, and transaction logging.
Data is stored in economy.json, separate from collections.json.

Schema per user:
{
  "user_id_str": {
    "catcoins":         int,   — current spendable balance
    "lifetime_earned":  int,   — total coins ever earned (never decremented)
    "lifetime_spent":   int,   — total coins ever spent (never decremented)
    "transactions": [          — capped at ECONOMY_TRANSACTION_LIMIT entries
      {
        "type":      str,      — "sell" | "spend" | "bonus" (future types)
        "card":      str,      — card stem (sell transactions)
        "tier":      str,      — card tier (sell transactions)
        "quantity":  int,      — number of cards sold
        "amount":    int,      — CatCoins delta (positive = earned, negative = spent)
        "timestamp": str,      — ISO 8601 UTC
      }
    ]
  }
}
"""
import json
import os
from datetime import datetime, timezone
from config import ECONOMY_FILE, ECONOMY_TRANSACTION_LIMIT, CATCOIN_SELL_VALUES


# =============================================================================
#  Storage
# =============================================================================
def load_economy() -> dict:
    """Load economy data from disk. Returns empty dict if file missing."""
    if os.path.exists(ECONOMY_FILE):
        with open(ECONOMY_FILE, "r") as f:
            return json.load(f)
    return {}


def save_economy(data: dict):
    """Persist economy data to disk."""
    with open(ECONOMY_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_user_economy(data: dict, user_id: int) -> dict:
    """
    Return the economy entry for a user, creating a blank one if absent.
    Mutates data in place — caller must save_economy() when done.
    """
    key = str(user_id)
    if key not in data:
        data[key] = {
            "catcoins":        0,
            "lifetime_earned": 0,
            "lifetime_spent":  0,
            "transactions":    [],
        }
    return data[key]


# =============================================================================
#  Balance helpers
# =============================================================================
def get_balance(data: dict, user_id: int) -> int:
    """Return current CatCoin balance for a user."""
    return get_user_economy(data, user_id)["catcoins"]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_transaction(user: dict, entry: dict):
    """
    Append a transaction entry and trim to ECONOMY_TRANSACTION_LIMIT,
    dropping the oldest entries first.
    """
    user["transactions"].append(entry)
    if len(user["transactions"]) > ECONOMY_TRANSACTION_LIMIT:
        user["transactions"] = user["transactions"][-ECONOMY_TRANSACTION_LIMIT:]


# =============================================================================
#  Earn / Spend operations
# =============================================================================
def sell_cards(
    data: dict,
    user_id: int,
    card: str,
    tier: str,
    quantity: int,
) -> tuple[bool, int, str]:
    """
    Award CatCoins for selling one or more copies of a card.

    Args:
        data:     Economy data dict (from load_economy()).
        user_id:  Discord user ID.
        card:     Card filename stem (e.g. 'IMG_0252').
        tier:     Card rarity tier string.
        quantity: Number of copies being sold (must be >= 1).

    Returns:
        (success, coins_awarded, message)
        success=False if tier is unknown or quantity < 1.
    """
    if quantity < 1:
        return False, 0, "Quantity must be at least 1."

    coin_value = CATCOIN_SELL_VALUES.get(tier)
    if coin_value is None:
        return False, 0, f"Unknown tier '{tier}' — cannot determine sell value."

    total = coin_value * quantity
    user  = get_user_economy(data, user_id)

    user["catcoins"]        += total
    user["lifetime_earned"] += total

    _append_transaction(user, {
        "type":      "sell",
        "card":      card,
        "tier":      tier,
        "quantity":  quantity,
        "amount":    total,
        "timestamp": _utc_now(),
    })

    save_economy(data)
    return True, total, f"Sold {quantity}x `{card}` for **{total} CatCoins**."


def spend_coins(
    data: dict,
    user_id: int,
    amount: int,
    reason: str = "purchase",
) -> tuple[bool, str]:
    """
    Deduct CatCoins from a user's balance.

    Args:
        data:    Economy data dict.
        user_id: Discord user ID.
        amount:  Coins to deduct (must be > 0).
        reason:  Short description for the transaction log.

    Returns:
        (success, message)
        success=False if balance is insufficient.
    """
    if amount <= 0:
        return False, "Spend amount must be greater than 0."

    user = get_user_economy(data, user_id)

    if user["catcoins"] < amount:
        return False, (
            f"Insufficient CatCoins. "
            f"You have **{user['catcoins']}** but need **{amount}**."
        )

    user["catcoins"]       -= amount
    user["lifetime_spent"] += amount

    _append_transaction(user, {
        "type":      "spend",
        "card":      None,
        "tier":      None,
        "quantity":  None,
        "amount":    -amount,
        "timestamp": _utc_now(),
        "reason":    reason,
    })

    save_economy(data)
    return True, f"Spent **{amount} CatCoins** on {reason}."


def award_bonus(
    data: dict,
    user_id: int,
    amount: int,
    reason: str = "bonus",
) -> int:
    """
    Award bonus CatCoins to a user (owner gifts, events, etc.).
    Returns new balance.
    """
    user = get_user_economy(data, user_id)

    user["catcoins"]        += amount
    user["lifetime_earned"] += amount

    _append_transaction(user, {
        "type":      "bonus",
        "card":      None,
        "tier":      None,
        "quantity":  None,
        "amount":    amount,
        "timestamp": _utc_now(),
        "reason":    reason,
    })

    save_economy(data)
    return user["catcoins"]


# =============================================================================
#  Query helpers
# =============================================================================
def get_transaction_history(
    data: dict,
    user_id: int,
    limit: int = 10,
) -> list[dict]:
    """
    Return the most recent N transactions for a user, newest first.
    """
    user = get_user_economy(data, user_id)
    return list(reversed(user["transactions"][-limit:]))


def sell_value_for(tier: str) -> int:
    """Return the CatCoin sell value for a tier, or 0 if unknown."""
    return CATCOIN_SELL_VALUES.get(tier, 0)


def leaderboard(data: dict, top_n: int = 10) -> list[tuple[int, int]]:
    """
    Return top N users by current balance as [(user_id, catcoins), ...].
    Sorted descending.
    """
    entries = [
        (int(uid), info["catcoins"])
        for uid, info in data.items()
        if info.get("catcoins", 0) > 0
    ]
    entries.sort(key=lambda x: x[1], reverse=True)
    return entries[:top_n]
