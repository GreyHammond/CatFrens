import os

# ── Core ──────────────────────────────────────────────────────────────────────
TOKEN    = os.environ.get("DISCORD_TOKEN", "YOUR_TOKEN_HERE")
PREFIX   = "!"
OWNER_ID = 196106852214243328

# Users allowed to use !grab and !grablink (to prevent folder abuse)
TRUSTED_USERS = {
    196106852214243328,   # Grey (owner)
    1491976975353647155,  # Ulbraxtika
}

# ── Files ─────────────────────────────────────────────────────────────────────
FACTS_FILE          = "facts.json"
STATE_FILE          = "state.json"
GUILD_SETTINGS_FILE = "guild_settings.json"
COLLECTIONS_FILE    = "collections.json"

# ── Photos ────────────────────────────────────────────────────────────────────
PHOTOS_DIR    = os.environ.get("PHOTOS_DIR", "photos")
RARE_DIR      = os.environ.get("RARE_DIR",       "rare")
ULTRA_DIR     = os.environ.get("ULTRA_DIR",      "ultra_rare")
LEGENDARY_DIR = os.environ.get("LEGENDARY_DIR",  "legendary")
IMAGE_EXTS    = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}

# ── Rarity ────────────────────────────────────────────────────────────────────
TIERS = ["common", "rare", "ultra_rare", "legendary"]

TIER_WEIGHTS = {
    "common":     8000,   # 0    - 7999
    "rare":       1300,   # 8000 - 9299
    "ultra_rare":  500,   # 9300 - 9799
    "legendary":   200,   # 9800 - 9999
}

TIER_THRESHOLDS = {
    "legendary":   9800,
    "ultra_rare":  9300,
    "rare":        8000,
    "common":      0,
}

TIER_COLORS = {
    "common":     0x1C1C1C,  # near black
    "rare":       0xCD7F32,  # bronze
    "ultra_rare": 0xC0C0C0,  # silver
    "legendary":  0xFFD700,  # gold
}

TIER_LABELS = {
    "common":     "Common",
    "rare":       "Rare",
    "ultra_rare": "Ultra Rare",
    "legendary":  "✨ LEGENDARY ✨",
}

TIER_EMOJIS = {
    "common":     "⬜",
    "rare":       "🔵",
    "ultra_rare": "🟣",
    "legendary":  "🌟",
}

# ── Pity ─────────────────────────────────────────────────────────────────────
PITY_THRESHOLD = 40   # consecutive commons before forcing Rare or better

# ── Rate limiting ─────────────────────────────────────────────────────────────
# Set to a channel ID to receive alerts when a user triggers the rate limiter.
# Leave as None to only log to console.
RATE_LIMIT_LOG_CHANNEL_ID = None   # e.g. 1234567890123456789

# Max file-upload interactions per window before the user is throttled
RATE_LIMIT_MAX    = 3     # clicks
RATE_LIMIT_WINDOW = 1.5   # seconds

# Max identical prefix command uses per window before the user is throttled
CMD_RATE_MAX    = 2    # uses of the same command
CMD_RATE_WINDOW = 5.0  # seconds

# ── Scheduling ────────────────────────────────────────────────────────────────
DEFAULT_FACT_INTERVAL_HOURS   = 12
DEFAULT_PULL_COOLDOWN_MINUTES = 60

# ── Moose messages per tier ───────────────────────────────────────────────────
MOOSE_MESSAGES = {
    "common": [
        "You have summoned Moosifur!",
        "Here's a random Moose pic!",
        "Random Moose Photo!",
        "Moose has entered the chat.",
        "A wild Moose appears!",
        "Moosifur demands your attention.",
        "Today's Moose forecast: 100% adorable.",
        "Presenting... the Moose.",
        "Moose spotted in the wild!",
        "This is Moose. Say hi to Moose.",
        "Moosifur has graced us with her presence.",
        "Another day, another Moose.",
        "Moose o'clock. You're welcome.",
        "Breaking news: Moose is very good.",
        "Moosifur would like to be perceived.",
        "She's here. She's fluffy. It's Moose.",
        "Daily Moose delivery, as requested.",
        "One (1) Moose, freshly summoned.",
        "Moosifur says hello. Probably.",
        "Behold: Her Royal Fluffiness, Moosifur.",
    ],
    "rare": [
        "A Rare Moose has been spotted!",
        "Not everyone gets to see this side of Moose.",
        "Moosifur is feeling fancy today.",
        "This one doesn't come around often.",
        "A Rare pull! Moosifur approves.",
    ],
    "ultra_rare": [
        "ULTRA RARE MOOSE DETECTED.",
        "Moosifur has chosen you. You are worthy.",
        "This is not a drill. Ultra Rare Moose incoming.",
        "Few have witnessed this. You are one of the few.",
        "The stars have aligned. Moosifur appears.",
    ],
    "legendary": [
        "🌟 A LEGENDARY MOOSE HAS APPEARED. 🌟",
        "LEGENDARY. Moosifur transcends.",
        "You have been blessed by Moosifur herself.",
        "This moment will be remembered.",
        "THE RAREST OF MOOSE. WITNESS.",
    ],
}

# ── Booster pack odds ─────────────────────────────────────────────────────────
# Daily (3 cards): overwhelmingly common
DAILY_PACK_WEIGHTS = {
    "common":     9200,
    "rare":        700,
    "ultra_rare":   90,
    "legendary":    10,
}

# Weekly (5 cards): better odds
WEEKLY_PACK_WEIGHTS = {
    "common":     7500,
    "rare":       2000,
    "ultra_rare":  450,
    "legendary":    50,
}
