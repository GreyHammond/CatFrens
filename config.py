import os

# ── Core ──────────────────────────────────────────────────────────────────────
TOKEN = "MTUwMTY2MTg5Mzk5MDAyMzIwOA.GdK994.1ycwZNDNsn2BSMULBI1TnpslSXR8KzvQTv8ouU"
PREFIX   = "!"
OWNER_ID = 196106852214243328

# Users allowed to use /grab and /grablink (to prevent folder abuse)
TRUSTED_USERS = {
    196106852214243328,   # Grey (owner)
    1491976975353647155,  # Ulbraxtika
}

# ── Files ─────────────────────────────────────────────────────────────────────
FACTS_FILE          = "facts.json"
STATE_FILE          = "state.json"
GUILD_SETTINGS_FILE = "guild_settings.json"
COLLECTIONS_FILE    = "collections.json"
ECONOMY_FILE        = "economy.json"

# ── Photos ────────────────────────────────────────────────────────────────────
# "photos" dir has been renamed to "common" on disk and GitHub.
# ultra_rare is legacy-read-only — no new cards are printed to it.
COMMON_DIR       = os.environ.get("COMMON_DIR",       "common")
RARE_DIR         = os.environ.get("RARE_DIR",          "rare")
ULTRA_DIR        = os.environ.get("ULTRA_DIR",         "ultra_rare")
SECRET_RARE_DIR  = os.environ.get("SECRET_RARE_DIR",   "secret_rare")
LEGENDARY_DIR    = os.environ.get("LEGENDARY_DIR",     "legendary")
MYTHIC_RARE_DIR  = os.environ.get("MYTHIC_RARE_DIR",   "mythic_rare")
SECRET_MYTHIC_DIR = os.environ.get("SECRET_MYTHIC_DIR","secret_mythic")
PRIMORDIAL_DIR   = os.environ.get("PRIMORDIAL_DIR",    "primordial")

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}

# ── GitHub image serving ───────────────────────────────────────────────────────
# Raw base URL for serving card images directly from the repo.
# Cards are served CDN-first (cached 24hr), then GitHub, then re-upload fallback.
GITHUB_RAW_BASE = "https://raw.githubusercontent.com/GreyHammond/CatFrens/main"

# ── Rarity ────────────────────────────────────────────────────────────────────
# Ordered lowest → highest. ultra_rare is legacy (readable, not printable).
TIERS = [
    "common",
    "rare",
    "ultra_rare",
    "secret_rare",
    "legendary",
    "mythic_rare",
    "secret_mythic",
    "primordial",
]

# Tiers that /grab and /grablink can target (ultra_rare removed — legacy only)
GRABBABLE_TIERS = [
    "common",
    "rare",
    "secret_rare",
    "legendary",
    "mythic_rare",
    "secret_mythic",
    "primordial",
]

# Pull weights out of 10,000. ultra_rare = 0 (no new pulls; existing cards
# remain in collections and can still be pulled from the folder if present).
TIER_WEIGHTS = {
    "common":        7200,
    "rare":          2582,
    "ultra_rare":       0,   # legacy only
    "secret_rare":    140,
    "legendary":       54,
    "mythic_rare":     11,
    "secret_mythic":    8,
    "primordial":       5,
}

# Thresholds for the SHA-256 roll (highest tier checked first).
# ultra_rare is excluded from the roll — it cannot be newly pulled.
# Total non-common weight: 2582+140+54+11+8+5 = 2800 → common fills 7200.
TIER_THRESHOLDS = {
    "primordial":    9995,   # 9995-9999  (5)
    "secret_mythic": 9987,   # 9987-9994  (8)
    "mythic_rare":   9976,   # 9976-9986  (11)
    "legendary":     9922,   # 9922-9975  (54)
    "secret_rare":   9782,   # 9782-9921  (140)
    "rare":          7200,   # 7200-9781  (2582) — ultra_rare skipped
    "common":           0,   # 0-7199     (7200)
}

TIER_COLORS = {
    "common":        0x8B6914,  # warm bronze
    "rare":          0xA8A8A8,  # silver
    "ultra_rare":    0xC0C0C0,  # silver (legacy)
    "secret_rare":   0xB0C4DE,  # diamond blue-grey
    "legendary":     0xFFD700,  # gold
    "mythic_rare":   0xE8E8FF,  # pale marble white
    "secret_mythic": 0xFF69B4,  # prismatic pink (animated in future)
    "primordial":    0xFF2200,  # lava red
}

TIER_LABELS = {
    "common":        "Common",
    "rare":          "Rare",
    "ultra_rare":    "Ultra Rare",
    "secret_rare":   "✦ Secret Rare",
    "legendary":     "🌟 Legendary",
    "mythic_rare":   "💎 Mythic Rare",
    "secret_mythic": "🌈 Secret Mythic",
    "primordial":    "🔥 PRIMORDIAL 🔥",
}

TIER_EMOJIS = {
    "common":        "⬜",
    "rare":          "🔵",
    "ultra_rare":    "🟣",
    "secret_rare":   "✦",
    "legendary":     "🌟",
    "mythic_rare":   "💎",
    "secret_mythic": "🌈",
    "primordial":    "🔥",
}

# ── CatCoins sell values per card ─────────────────────────────────────────────
CATCOIN_SELL_VALUES = {
    "common":        1,
    "rare":          5,
    "ultra_rare":   15,
    "secret_rare":  40,
    "legendary":   100,
    "mythic_rare": 300,
    "secret_mythic": 500,
    "primordial":  1000,
}

# Max transaction log entries stored per user in economy.json
ECONOMY_TRANSACTION_LIMIT = 500

# ── Pity ─────────────────────────────────────────────────────────────────────
# After PITY_THRESHOLD consecutive commons, force a re-roll in the non-common
# pool. Higher tiers remain rare within that pool (proportional weights apply).
PITY_THRESHOLD = 40

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
    "secret_rare": [
        "✦ A Secret Rare has emerged from the shadows.",
        "Not many eyes have seen this one.",
        "Moosifur kept this one hidden. Until now.",
        "✦ Secret Rare acquired. You're one of the few.",
        "Something rare stirs... a Secret Rare appears!",
    ],
    "legendary": [
        "🌟 A LEGENDARY MOOSE HAS APPEARED. 🌟",
        "LEGENDARY. Moosifur transcends.",
        "You have been blessed by Moosifur herself.",
        "This moment will be remembered.",
        "THE RAREST OF MOOSE. WITNESS.",
    ],
    "mythic_rare": [
        "💎 MYTHIC RARE. The marble speaks.",
        "Ancient and powerful. Moosifur awakens.",
        "💎 You have pulled something extraordinary.",
        "The cosmos aligned for this moment.",
        "Mythic Rare — few will ever see this.",
    ],
    "secret_mythic": [
        "🌈 SECRET MYTHIC. Reality bends.",
        "The prismatic Moose reveals herself.",
        "🌈 This shouldn't even exist. And yet.",
        "Secret Mythic — beyond legend, beyond myth.",
        "You have witnessed the impossible.",
    ],
    "primordial": [
        "🔥 PRIMORDIAL. FROM THE BEGINNING OF TIME. 🔥",
        "THE PRIMORDIAL MOOSE AWAKENS. ALL TREMBLE.",
        "🔥 This is not a card. This is a relic.",
        "PRIMORDIAL. The rarest of all that exists.",
        "She was here before everything. She is Moosifur.",
    ],
}

# ── Booster pack odds ─────────────────────────────────────────────────────────
# Daily (3 cards): weighted heavily toward common/rare
# ultra_rare excluded — legacy cards not in new pack pools
DAILY_PACK_WEIGHTS = {
    "common":        8500,
    "rare":          1300,
    "secret_rare":    150,
    "legendary":       40,
    "mythic_rare":      7,
    "secret_mythic":    2,
    "primordial":       1,
}

# Weekly (5 cards): noticeably better odds than daily
WEEKLY_PACK_WEIGHTS = {
    "common":        6800,
    "rare":          2700,
    "secret_rare":    360,
    "legendary":      100,
    "mythic_rare":     25,
    "secret_mythic":   10,
    "primordial":       5,
}
