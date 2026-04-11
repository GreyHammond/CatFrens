import json
import random
import os
from datetime import datetime, timezone, timedelta
from config import FACTS_FILE

MOOSE_FACTS_FILE  = "moose_facts.json"
EVENTS_FILE       = "events.json"
MOOSE_FACT_CHANCE = 25   # 1 in 25 outside of events
BIRTHDAY_MMDD     = "09-05"

# =============================================================================
#  Loaders
# =============================================================================
def load_facts() -> list[str]:
    with open(FACTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def load_moose_facts() -> list[str]:
    if os.path.exists(MOOSE_FACTS_FILE):
        with open(MOOSE_FACTS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []

def save_moose_facts(facts: list[str]):
    with open(MOOSE_FACTS_FILE, "w", encoding="utf-8") as f:
        json.dump(facts, f, indent=2)

def add_moose_fact(fact: str) -> int:
    facts = load_moose_facts()
    facts.append(fact)
    save_moose_facts(facts)
    return len(facts)

def load_events() -> list[dict]:
    if os.path.exists(EVENTS_FILE):
        with open(EVENTS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []

def load_event_facts(fact_file: str) -> list[str]:
    if os.path.exists(fact_file):
        with open(fact_file, encoding="utf-8") as f:
            return json.load(f)
    return []

# =============================================================================
#  Event detection
# =============================================================================
def _pacific_now() -> datetime:
    """Current time in US/Pacific (UTC-8 standard, UTC-7 DST — approximated)."""
    # Approximate: use UTC-8 for simplicity; close enough for daily events
    return datetime.now(timezone.utc) - timedelta(hours=8)

def _mmdd(dt: datetime) -> str:
    return dt.strftime("%m-%d")

def get_active_event(dt: datetime = None) -> dict | None:
    """
    Returns the highest-priority active event for the given datetime.
    Birthday always wins. Otherwise first matching event wins.
    """
    if dt is None:
        dt = _pacific_now()
    mmdd   = _mmdd(dt)
    events = load_events()

    # Birthday hardcoded priority
    for event in events:
        if event.get("start") == BIRTHDAY_MMDD and mmdd == BIRTHDAY_MMDD:
            return event

    # Check all other events
    for event in events:
        start = event.get("start", "")
        end   = event.get("end", "")
        if not start or not end:
            continue
        # Handle year wrap (e.g. Dec 15 - Jan 15) — not needed yet but safe
        if start <= end:
            if start <= mmdd <= end:
                return event
        else:
            if mmdd >= start or mmdd <= end:
                return event
    return None

def is_exclusive_date(event: dict, dt: datetime = None) -> bool:
    """True if today is the exclusive_date of the event."""
    if not event or not event.get("exclusive_date"):
        return False
    if dt is None:
        dt = _pacific_now()
    return _mmdd(dt) == event["exclusive_date"]

def get_pull_boost(event: dict | None) -> dict | None:
    """Returns modified tier weights if event has pull_boost, else None."""
    if not event or not event.get("pull_boost"):
        return None
    from config import TIER_THRESHOLDS
    # Boost: shift 500 points from common to rare/ultra_rare/legendary
    return {
        "common":     7500,
        "rare":       1600,
        "ultra_rare":  650,
        "legendary":   250,
    }

# =============================================================================
#  Fact selection
# =============================================================================
def get_guild_fact_state(guild_settings: dict, guild_id: int) -> dict:
    key = str(guild_id)
    if key not in guild_settings:
        guild_settings[key] = {}
    cfg = guild_settings[key]
    if "fact_queue" not in cfg:
        cfg["fact_queue"] = []
        cfg["fact_used"]  = []
    return cfg

def next_fact_for_guild(
    guild_settings: dict,
    guild_id: int,
    all_facts: list[str],
    save_fn
) -> tuple[int, str, bool, dict | None]:
    """
    Pull the next fact for a guild.
    Returns (idx, fact_text, is_moose_fact, active_event).

    Priority:
    1. Exclusive date → only event facts
    2. Active event → event facts at event["fact_rate"], Moosifur at 1/25
    3. No event → Moosifur at 1/25, else normal queue
    """
    now   = _pacific_now()
    event = get_active_event(now)

    # ── Exclusive date: only event facts ─────────────────────────────────────
    if event and is_exclusive_date(event, now):
        event_facts = load_event_facts(event["fact_file"])
        if event_facts:
            return -1, random.choice(event_facts), False, event

    # ── Active event: boosted event fact rate ─────────────────────────────────
    if event:
        event_facts = load_event_facts(event["fact_file"])
        rate        = event.get("fact_rate", 25)
        if event_facts and random.randint(1, rate) == 1:
            return -1, random.choice(event_facts), False, event
        # Still allow Moosifur facts during events
        moose_facts = load_moose_facts()
        if moose_facts and random.randint(1, MOOSE_FACT_CHANCE) == 1:
            return -1, random.choice(moose_facts), True, event
    else:
        # ── No event: normal Moosifur chance ─────────────────────────────────
        moose_facts = load_moose_facts()
        if moose_facts and random.randint(1, MOOSE_FACT_CHANCE) == 1:
            return -1, random.choice(moose_facts), True, None

    # ── Normal fact queue ─────────────────────────────────────────────────────
    cfg = get_guild_fact_state(guild_settings, guild_id)
    if not cfg["fact_queue"]:
        pool = list(range(len(all_facts)))
        random.shuffle(pool)
        cfg["fact_queue"] = pool
        cfg["fact_used"]  = []

    idx = cfg["fact_queue"].pop(0)
    cfg["fact_used"].append(idx)
    save_fn()
    return idx, all_facts[idx], False, event

def get_random_fact(all_facts: list[str]) -> tuple[str, bool, dict | None]:
    """
    Pull a completely random fact outside the shuffle cycle.
    Respects event/Moosifur chances.
    Returns (fact_text, is_moose_fact, active_event).
    """
    now   = _pacific_now()
    event = get_active_event(now)

    if event and is_exclusive_date(event, now):
        event_facts = load_event_facts(event["fact_file"])
        if event_facts:
            return random.choice(event_facts), False, event

    if event:
        event_facts = load_event_facts(event["fact_file"])
        rate = event.get("fact_rate", 25)
        if event_facts and random.randint(1, rate) == 1:
            return random.choice(event_facts), False, event

    moose_facts = load_moose_facts()
    if moose_facts and random.randint(1, MOOSE_FACT_CHANCE) == 1:
        return random.choice(moose_facts), True, event

    return random.choice(all_facts), False, event

def guild_facts_delivered(guild_settings: dict, guild_id: int) -> int:
    cfg = guild_settings.get(str(guild_id), {})
    return len(cfg.get("fact_used", []))

# =============================================================================
#  Birthday helpers
# =============================================================================
def is_birthday_today() -> bool:
    return _mmdd(_pacific_now()) == BIRTHDAY_MMDD

def get_moose_of_the_day_time() -> datetime:
    """Returns today's Moose of the Day time: 12:00 PM Pacific."""
    now     = _pacific_now()
    noon_pt = now.replace(hour=12, minute=0, second=0, microsecond=0)
    return noon_pt

def get_special_day_bonus(dt: datetime = None) -> str | None:
    """
    Returns the bonus pack type ('daily' or 'weekly') if today is a
    special_day_bonus date for any active event, else None.
    Birthday always wins.
    """
    if dt is None:
        dt = _pacific_now()
    event = get_active_event(dt)
    if not event:
        return None
    if is_exclusive_date(event, dt):
        return event.get("special_day_bonus")
    return None