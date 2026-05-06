
## CatFrens — Economy I: New Tiers, Economy & Overhaul

### 🃏 New Card Tiers
Added four new rarity tiers to the card ladder, expanding from 4 tiers to 8:
- **Secret Rare** — above Ultra Rare, new standard for foil pulls
- **Mythic Rare** — cracked marble frame, serious pull
- **Secret Mythic** — prismatic animated-style frame, extremely rare
- **Primordial** — lava/lightning apex tier, the rarest card in existence

Ultra Rare is now **legacy** — existing cards remain in collections and can still be pulled from the pool, but no new Ultra Rare cards will be printed going forward. New cards that would have been Ultra Rare are now Secret Rare.

---

### 🎲 Reworked Pull Odds
Pull weights completely reworked across all 8 tiers with a 10,000-point system for precision:

| Tier | Odds |
|---|---|
| Common | ~72% |
| Rare | ~25.8% |
| Secret Rare | 1.4% |
| Legendary | 0.54% |
| Mythic Rare | 0.11% |
| Secret Mythic | 0.08% |
| Primordial | 0.05% |

Pity system unchanged — 40 consecutive commons guarantees a Rare or better, with higher tiers still possible at proportional odds.

---

### 🖼️ New Card Frames & Asset Pipeline
Each tier now has its own distinct frame asset:
- Common — bronze/copper metallic
- Rare — silver + gold trim
- Secret Rare — platinum with diamond jewels
- Legendary — clean gold
- Mythic Rare — cracked white marble + gold
- Secret Mythic — prismatic/rainbow (animated support planned)
- Primordial — dark cracked stone with red lava lightning

**Reflect** and **Glow** overlays are now optional per-card embellishments applied at grab time and baked into the card permanently.

---

### ⚙️ Grab & Grablink Overhaul
`/grab` and `/grablink` now support all 7 printable tiers via Discord's slash command autocomplete. Ultra Rare has been removed as a grab target. Both commands accept optional `reflect` and `glow` embellishment flags.

---

### 📁 Folder Restructure
- `photos/` renamed to `common/` across disk and GitHub
- New folders added: `secret_rare/`, `mythic_rare/`, `secret_mythic/`, `primordial/`
- `ultra_rare/` retained for legacy reads

---

### 🪙 CatCoins Economy (New)
Introducing CatCoins — the in-game currency of CatFrens.

- **`/sell`** — Sell any card from your collection for CatCoins. Any card is sellable including your last copy. Paginated view with category jump (by tier) and sort toggle (common→primordial or reverse). Confirmation screen with last-copy warning.
- **`/balance`** — Check your current CatCoin balance, lifetime earned, and lifetime spent.
- All existing players start at 0 coins automatically — no migration needed.
- Coins accumulate forever, no expiry.

**Sell values:**
| Tier | CatCoins |
|---|---|
| Common | 1 |
| Rare | 5 |
| Ultra Rare | 15 |
| Secret Rare | 40 |
| Legendary | 100 |
| Mythic Rare | 300 |
| Secret Mythic | 500 |
| Primordial | 1,000 |

Economy data stored in a new `economy.json` with full transaction history (last 500 entries per user).

---

### ♻️ Duplicates Overhaul
- Duplicate view now shows total sell value of all tradeable dupes
- **Sell Dupes** button added — launches the sell flow filtered to duplicates only
- Trade-up chain extended through all new tiers (Common → Rare → Secret Rare → Legendary → Mythic Rare → Secret Mythic → Primordial)
- Ultra Rare removed from the trade chain

---

### 🖼️ Image Serving
Cards now serve via GitHub raw URL or cached Discord CDN URL where available, reducing re-uploads and improving response time. Falls back to direct file upload if needed.

---

### 🐛 Fixes & Polish
- Sync error on startup no longer crashes or shows alarming error if the bot isn't in a force-sync server — logs a calm informational message instead and continues
- Pull odds corrected to sum exactly to 10,000 weight points
- Collection view updated to display all 8 tiers
- Profile breakdown updated to show all 8 tiers
- Daily and Weekly pack odds extended to include all new tiers with improved rates at Weekly

---

*Developed by Hammond Digital Studios. Dedicated to Ulbraxtika and Moosifur 🐾*

---