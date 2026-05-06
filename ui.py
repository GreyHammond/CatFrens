import discord
from pathlib import Path
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from discord.ext import commands
from config import TIER_COLORS, TIER_LABELS, TIER_EMOJIS, TIERS, CATCOIN_SELL_VALUES
from user_collections import get_collection_by_tier, completion_percent, rarest_card, get_duplicates, get_all_cards_sorted, sell_card_copies
from photos import total_card_count, find_photo_in_tier
import economy as econ_mod

# =============================================================================
#  RATE LIMITER
#  Tracks per-user click timestamps for views that do file uploads.
#  If a user exceeds RATE_LIMIT_MAX clicks in RATE_LIMIT_WINDOW seconds:
#    • Logs to console
#    • Sends an alert to RATE_LIMIT_LOG_CHANNEL_ID (if set)
#    • Disables all buttons on the view so they can't keep spamming
# =============================================================================
import time
from collections import defaultdict

_click_log: dict[int, list[float]] = defaultdict(list)


def _record_click(user_id: int) -> bool:
    """
    Record a button press for user_id and return True if the rate limit
    has been exceeded (too many clicks in the rolling window).
    """
    from config import RATE_LIMIT_MAX, RATE_LIMIT_WINDOW
    now = time.monotonic()
    log = _click_log[user_id]
    # Prune entries outside the window
    _click_log[user_id] = [t for t in log if now - t < RATE_LIMIT_WINDOW]
    _click_log[user_id].append(now)
    return len(_click_log[user_id]) > RATE_LIMIT_MAX


def _disable_all_buttons(view: discord.ui.View) -> None:
    """Disable every Button child on a view in-place."""
    for child in view.children:
        if isinstance(child, discord.ui.Button):
            child.disabled = True


async def _alert_rate_limit(interaction: discord.Interaction, view_name: str) -> None:
    """Print to console and, if configured, send a message to the log channel."""
    from config import RATE_LIMIT_LOG_CHANNEL_ID
    user  = interaction.user
    guild = interaction.guild
    loc   = f"{guild.name} ({guild.id})" if guild else "DM"

    console_msg = (
        f"[RateLimit] {user} (ID: {user.id}) in {loc} "
        f"— throttled on {view_name}"
    )
    print(console_msg)

    if RATE_LIMIT_LOG_CHANNEL_ID and _bot_ref:
        ch = _bot_ref.get_channel(RATE_LIMIT_LOG_CHANNEL_ID)
        if ch:
            try:
                embed = discord.Embed(
                    title="⚠️ Rate Limit Triggered",
                    color=0xFF6B6B,
                )
                embed.add_field(name="User",   value=f"{user.mention} (`{user.id}`)", inline=True)
                embed.add_field(name="Guild",  value=loc,                             inline=True)
                embed.add_field(name="View",   value=f"`{view_name}`",               inline=True)
                embed.set_footer(text="Buttons on that view have been disabled.")
                await ch.send(embed=embed)
            except discord.Forbidden:
                print(f"[RateLimit] Could not post to log channel {RATE_LIMIT_LOG_CHANNEL_ID}")


async def _throttle_guard(
    interaction: discord.Interaction,
    view: discord.ui.View,
    view_name: str,
) -> bool:
    """
    Call at the top of any button handler that involves file uploads.
    If the user is clicking too fast:
      - alerts console + log channel
      - disables all buttons on the view
      - sends an ephemeral-style edit telling the user to slow down
      - returns True  ← caller should `return` immediately

    If the rate is fine, returns False and does nothing.
    """
    if not _record_click(interaction.user.id):
        return False

    await _alert_rate_limit(interaction, view_name)
    _disable_all_buttons(view)
    await interaction.response.edit_message(
        content=(
            "⚠️ **You're navigating too fast!** "
            "Buttons have been disabled to prevent upload spam. "
            "Open a fresh `/bonuspack`, `/daily`, or `/weekly` to continue."
        ),
        view=view,
    )
    return True


# =============================================================================
#  COMMAND RATE LIMITER
#  Separate (more generous) window for prefix commands — tracks (user, command)
#  pairs so `!foto` spam is caught without affecting other commands.
# =============================================================================
_cmd_log: dict[tuple[int, str], list[float]] = defaultdict(list)


def _record_command(user_id: int, cmd_name: str) -> bool:
    """Return True if user has exceeded the command rate limit."""
    from config import CMD_RATE_MAX, CMD_RATE_WINDOW
    key = (user_id, cmd_name)
    now = time.monotonic()
    _cmd_log[key] = [t for t in _cmd_log[key] if now - t < CMD_RATE_WINDOW]
    _cmd_log[key].append(now)
    return len(_cmd_log[key]) > CMD_RATE_MAX


async def command_rate_guard(ctx: "commands.Context", cmd_name: str) -> bool:
    """
    Call at the top of any prefix command handler.
    If the user is spamming the same command:
      - alerts console + log channel
      - sends a single warning message in the channel
      - returns True  ← caller should `return` immediately

    If the rate is fine, returns False and does nothing.
    """
    if not _record_command(ctx.author.id, cmd_name):
        return False

    # Reuse the same alert infrastructure as the view rate limiter
    user  = ctx.author
    guild = ctx.guild
    loc   = f"{guild.name} ({guild.id})" if guild else "DM"

    console_msg = (
        f"[RateLimit/cmd] {user} (ID: {user.id}) in {loc} "
        f"— throttled on !{cmd_name}"
    )
    print(console_msg)

    from config import RATE_LIMIT_LOG_CHANNEL_ID
    if RATE_LIMIT_LOG_CHANNEL_ID and _bot_ref:
        ch = _bot_ref.get_channel(RATE_LIMIT_LOG_CHANNEL_ID)
        if ch:
            try:
                embed = discord.Embed(title="⚠️ Command Rate Limit Triggered", color=0xFF6B6B)
                embed.add_field(name="User",    value=f"{user.mention} (`{user.id}`)", inline=True)
                embed.add_field(name="Guild",   value=loc,                             inline=True)
                embed.add_field(name="Command", value=f"`!{cmd_name}`",               inline=True)
                embed.set_footer(text="Message was ignored.")
                await ch.send(embed=embed)
            except discord.Forbidden:
                print(f"[RateLimit] Could not post to log channel {RATE_LIMIT_LOG_CHANNEL_ID}")

    await ctx.send(
        f"⚠️ {ctx.author.mention} Slow down! You're using `!{cmd_name}` too quickly.",
        delete_after=5,
    )
    return True

# =============================================================================
#  Embeds
# =============================================================================
def fact_embed(fact: str, idx: int, label: str = "Cat Fact") -> discord.Embed:
    embed = discord.Embed(description=f"🐾  {fact}", color=0xF4A460)
    embed.set_author(name=f"CatFrens | {label}")
    embed.set_footer(text=f"Fact #{idx + 1}")
    return embed

def pull_embed(photo: Path, tier: str, message: str, is_gift: bool = False, is_dupe: bool = False, dupe_count: int = 1, has_daily: bool = False, has_weekly: bool = False, has_bonus: bool = False, image_url: str = None) -> discord.Embed:
    color = TIER_COLORS[tier]
    label = TIER_LABELS[tier]
    emoji = TIER_EMOJIS[tier]
    gift_tag = " 🎁 Gift!" if is_gift else ""
    embed = discord.Embed(
        title=message,
        color=color,
    )
    embed.set_author(name=f"CatFrens | {emoji} {label}{gift_tag}")
    # Use GitHub/CDN URL if available, else fall back to attachment
    if image_url:
        embed.set_image(url=image_url)
    else:
        embed.set_image(url=f"attachment://{photo.name}")
    footer = f"{label} • {photo.stem}"
    sell_val = CATCOIN_SELL_VALUES.get(tier, 0)
    if is_dupe:
        footer += f" • ⚠️ Duplicate! You now have {dupe_count}. Sell for {sell_val} 🪙 via /sell or /duplicates."

    # Pack nudge
    if has_daily and has_weekly:
        footer += "\n📦 Daily & 🎁 Weekly MOOSEter packs are waiting! Use /daily and /weekly to claim them."
    elif has_daily:
        footer += "\n📦 You have a daily MOOSEter pack waiting! Use /daily to claim it."
    elif has_weekly:
        footer += "\n🎁 You have a Weekly MOOSEter pack waiting! Use /weekly to claim it."
    if has_bonus:
        footer += "\n🎁 You have a bonus MOOSEter pack waiting! Use /bonuspack to claim it."

    embed.set_footer(text=footer)
    return embed

def info_embed(used: int, total_facts: int, total_photos: int) -> discord.Embed:
    embed = discord.Embed(title="🐱 CatFrens", color=0xF4A460)
    embed.add_field(name="📚 Facts", value=(
        "`!catfact` | `/catfact` — Display A Random Cat Fact!\n"
        "`/savedfacts` — View your 🐾 saved facts\n"
        "`/eventinfo` — See the current seasonal event\n"
        "`!catfrens` | `/catfrens` — This menu"
    ), inline=False)
    embed.add_field(name="🃏 Cards & Collection", value=(
        "`!random` | `/random` — Collect a Random Moose photo trading card!\n"
        "`/foto` — Specific photo (with autocomplete!!!)\n"
        "`/collection` — View your Moose card collection\n"
        "`/profile` — View your pull stats and streak\n"
        "`/duplicates` — View, gift, trade, or sell your duplicate cards\n"
        "`/gift @user <card>` — Quick-gift a duplicate card\n"
        "`/sell` — Sell cards for CatCoins\n"
        "`/balance` — Check your CatCoin balance\n"
        "`/compare` — Compare your collection with another user\n"
        "`/wishlist` — Manage your card wishlist"
    ), inline=False)
    embed.add_field(name="🎁 Packs & Rewards", value=(
        "`/daily` — Claim your daily MOOSEter pack\n"
        "`/weekly` — Claim your weekly MOOSEter pack\n"
        "`/bonuspack` — Claim a gifted bonus pack\n"
        "`/streak` — Check your daily streak and next milestone"
    ), inline=False)
    embed.add_field(name="🏆 Community", value=(
        "`/topmoose` — See the top Moose card collectors"
    ), inline=False)
    embed.add_field(name="⚙️ Server Admin", value=(
        "`/setup-catfren` — Configure this server"
    ), inline=False)
    embed.add_field(name="🐾 Moosifer Only", value=(
        "`!grab [n]` | `/grab` — Save images from last n messages\n"
        "`!grablink <url>` | `/grablink` — Save images from a message link"
    ), inline=False)
    embed.add_field(
        name="Statistics",
        value=(
            f"**Facts Delivered:** {used} / {total_facts}\n"
            f"**Moose Photos In Library:** {total_photos}"
        ),
        inline=False
    )
    embed.set_footer(text="Developed by Hammond Digital Studios | Dedicated to Ulbraxtika and Moosifur 🐾")
    return embed

def profile_embed(member: discord.Member, user_data: dict, total_cards: int) -> discord.Embed:
    pct         = completion_percent(user_data, total_cards)
    total_pulls = user_data.get("total_pulls", 0)
    pity        = user_data.get("pity_counter", 0)
    unique      = len(user_data.get("cards", {}))
    best, best_tier = rarest_card(user_data)

    by_tier = get_collection_by_tier(user_data)
    counts  = {t: len(by_tier[t]) for t in TIERS}

    embed = discord.Embed(
        title=f"🐾 {member.display_name}'s Moose Profile",
        color=0xF4A460
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="Total Pulls",       value=str(total_pulls),          inline=True)
    embed.add_field(name="Unique Cards",      value=f"{unique} / {total_cards}", inline=True)
    embed.add_field(name="Completion",        value=f"{pct}%",                 inline=True)
    embed.add_field(
        name="Collection Breakdown",
        value=(
            f"{TIER_EMOJIS['primordial']} Primordial: **{counts['primordial']}**\n"
            f"{TIER_EMOJIS['secret_mythic']} Secret Mythic: **{counts['secret_mythic']}**\n"
            f"{TIER_EMOJIS['mythic_rare']} Mythic Rare: **{counts['mythic_rare']}**\n"
            f"{TIER_EMOJIS['legendary']} Legendary: **{counts['legendary']}**\n"
            f"{TIER_EMOJIS['secret_rare']} Secret Rare: **{counts['secret_rare']}**\n"
            f"{TIER_EMOJIS['ultra_rare']} Ultra Rare: **{counts['ultra_rare']}**\n"
            f"{TIER_EMOJIS['rare']} Rare: **{counts['rare']}**\n"
            f"{TIER_EMOJIS['common']} Common: **{counts['common']}**"
        ),
        inline=False
    )
    if best:
        embed.add_field(
            name="Rarest Card",
            value=f"{TIER_EMOJIS[best_tier]} `{best}` ({TIER_LABELS[best_tier]})",
            inline=False
        )
    embed.add_field(name="Pity Counter", value=f"{pity} / 40 commons (guarantees Rare+ on hit)", inline=True)
    pending = len(user_data.get("pending_gifts", []))
    if pending:
        embed.add_field(name="🎁 Pending Gifts", value=str(pending), inline=True)

    # Streak info
    streak     = user_data.get("daily_streak", 0)
    daily_total  = user_data.get("total_daily_claims", 0)
    weekly_total = user_data.get("total_weekly_claims", 0)
    if streak > 0:
        embed.add_field(name="🔥 Daily Streak", value=f"{streak} day(s) in a row", inline=True)
    if daily_total or weekly_total:
        embed.add_field(
            name="📦 Packs Claimed",
            value=f"Daily: {daily_total} | Weekly: {weekly_total}",
            inline=True
        )

    # Duplicate stats
    from user_collections import get_duplicates, get_tradeable_count
    dupes      = get_duplicates(user_data)
    total_extra = sum(d["tradeable"] for d in dupes)
    if dupes:
        embed.add_field(
            name="♻️ Duplicates",
            value=f"{len(dupes)} card(s) ({total_extra} total extras)",
            inline=False
        )

    # Trade-up nudge
    nudges = []
    for tier, cost, result in [("common", 10, "Rare"), ("rare", 5, "Ultra Rare"), ("ultra_rare", 5, "Legendary")]:
        if get_tradeable_count(user_data, tier) >= cost:
            nudges.append(f"🔄 Enough {tier.replace('_',' ')}s to trade up to **{result}**!")
    if nudges:
        embed.add_field(name="Trade Up Available", value="\n".join(nudges), inline=False)

    return embed

# =============================================================================
#  Paginated Collection View
# =============================================================================
CARDS_PER_PAGE = 10

class CollectionView(discord.ui.View):
    def __init__(self, member: discord.Member, user_data: dict, total_cards: int, viewer_id: int):
        super().__init__(timeout=120)
        self.member      = member
        self.user_data   = user_data
        self.total_cards = total_cards
        self.viewer_id   = viewer_id

        # Build a flat sorted card list: rarest first across all 8 tiers
        self.cards = []
        all_sorted = get_all_cards_sorted(user_data, descending=True)
        for card in all_sorted:
            self.cards.append((card["filename"], card["tier"]))

        self.page      = 0
        self.total_pages = max(1, (len(self.cards) + CARDS_PER_PAGE - 1) // CARDS_PER_PAGE)

        self._refresh_buttons()

    def _refresh_buttons(self):
        self.prev_btn.disabled = self.page == 0
        self.next_btn.disabled = self.page >= self.total_pages - 1

    def build_embed(self) -> discord.Embed:
        pct    = completion_percent(self.user_data, self.total_cards)
        unique = len(self.user_data.get("cards", {}))
        embed  = discord.Embed(
            title=f"🐾 {self.member.display_name}'s Collection",
            description=f"**{unique} / {self.total_cards}** unique cards ({pct}% complete)",
            color=0xF4A460
        )
        start = self.page * CARDS_PER_PAGE
        page_cards = self.cards[start:start + CARDS_PER_PAGE]
        if page_cards:
            lines = []
            for i, (filename, tier) in enumerate(page_cards, start=start + 1):
                count = self.user_data.get("cards", {}).get(filename, {}).get("count", 1)
                dupe_str = f" (x{count})" if count > 1 else ""
                lines.append(f"`{i}.` {TIER_EMOJIS[tier]} `{filename}` — {TIER_LABELS[tier]}{dupe_str}")
            embed.add_field(name="Cards", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="Cards", value="_No cards yet. Use `!random` to pull!_", inline=False)
        embed.set_footer(text=f"Page {self.page + 1} of {self.total_pages} | Select a card number to view it")
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Anyone can browse collections
        return True

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await _throttle_guard(interaction, self, "CollectionView"): return
        self.page -= 1
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await _throttle_guard(interaction, self, "CollectionView"): return
        self.page += 1
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="🔍 View Card", style=discord.ButtonStyle.primary)
    async def view_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ViewCardModal(self.cards, self.total_cards, self.member))

class ViewCardModal(discord.ui.Modal, title="View a Card"):
    number = discord.ui.TextInput(
        label="Enter card number from the list",
        placeholder="e.g. 3",
        min_length=1,
        max_length=4,
    )

    def __init__(self, cards: list, total_cards: int, member: discord.Member):
        super().__init__()
        self.cards       = cards
        self.total_cards = total_cards
        self.member      = member

    async def on_submit(self, interaction: discord.Interaction):
        try:
            idx = int(self.number.value) - 1
            if idx < 0 or idx >= len(self.cards):
                await interaction.response.send_message(
                    f"Please enter a number between 1 and {len(self.cards)}.", ephemeral=True
                )
                return
        except ValueError:
            await interaction.response.send_message("Please enter a valid number.", ephemeral=True)
            return

        filename, tier = self.cards[idx]
        photo = find_photo_in_tier(filename, tier)
        if photo is None:
            await interaction.response.send_message(
                f"Could not find `{filename}` on disk.", ephemeral=True
            )
            return

        embed = discord.Embed(
            title=f"{TIER_EMOJIS[tier]} {filename}",
            color=TIER_COLORS[tier]
        )
        embed.set_image(url=f"attachment://{photo.name}")
        embed.set_footer(text=f"{TIER_LABELS[tier]} • From {self.member.display_name}'s collection")
        await interaction.response.send_message(
            embed=embed,
            file=discord.File(photo),
            ephemeral=True
        )

def photo_embed_simple(photo: Path, tier: str) -> discord.Embed:
    color = TIER_COLORS.get(tier, 0xF4A460)
    label = TIER_LABELS.get(tier, "Photo")
    emoji = TIER_EMOJIS.get(tier, "🐾")
    embed = discord.Embed(color=color)
    embed.set_author(name=f"CatFrens | {emoji} {label}")
    embed.set_image(url=f"attachment://{photo.name}")
    embed.set_footer(text=photo.name)
    return embed

# =============================================================================
#  SETUP MENU SYSTEM
# =============================================================================
import guild_settings as gs_mod
from datetime import datetime, timezone
from config import DEFAULT_PULL_COOLDOWN_MINUTES

def build_config_embed(guild_cfg: dict, guild_id: int) -> discord.Embed:
    cfg = gs_mod.get_guild_cfg(guild_cfg, guild_id)

    def fmt_ch(ids):  return " ".join(f"<#{c}>" for c in ids) or "_none_"
    def fmt_ro(ids):  return " ".join(f"<@&{r}>" for r in ids) or "_none_"

    last     = cfg.get("last_fact_post")
    next_str = "not yet scheduled"
    if last:
        elapsed  = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() / 3600
        next_in  = max(0, cfg["fact_interval_hours"] - elapsed)
        next_str = f"in ~{next_in:.1f}h" if next_in > 0 else "very soon"

    cd      = cfg.get("cooldowns", {})
    def_cd  = cd.get("default", DEFAULT_PULL_COOLDOWN_MINUTES)
    role_cd = cd.get("roles", {})
    cd_str  = f"{def_cd} min (default)"
    if role_cd:
        cd_str += "\n" + "\n".join(f"<@&{rid}>: {m}m" for rid, m in role_cd.items())

    embed = discord.Embed(title="⚙️ CatFrens Server Config", color=0xF4A460)
    embed.add_field(name="📢 Fact Channels",     value=fmt_ch(cfg["fact_channels"]),    inline=False)
    embed.add_field(name="🌅 MOTD Channels",     value=fmt_ch(cfg.get("motd_channels", [])) + (" _(uses fact channels if not set)_" if not cfg.get("motd_channels") else ""), inline=False)
    embed.add_field(name="⏱️ Fact Interval",     value=f"Every {cfg['fact_interval_hours']}h (next {next_str})", inline=False)
    embed.add_field(name="💬 Command Channels",  value=fmt_ch(cfg["command_channels"]) + (" _(allowlist)_" if cfg["command_channels"] else " _(everywhere)_"), inline=False)
    embed.add_field(name="🚫 Excluded Channels", value=fmt_ch(cfg["excluded_channels"]), inline=False)
    embed.add_field(name="👑 Allowed Roles",     value=fmt_ro(cfg["allowed_roles"]) + (" _(allowlist)_" if cfg["allowed_roles"] else " _(everyone)_"), inline=False)
    embed.add_field(name="🛑 Excluded Roles",    value=fmt_ro(cfg["excluded_roles"]),   inline=False)
    embed.add_field(name="⏳ Cooldowns",         value=cd_str,                          inline=False)
    embed.set_footer(text="Use the buttons below to edit settings.")
    return embed

# ── Admin guard ───────────────────────────────────────────────────────────────
async def _admin_check(interaction: discord.Interaction) -> bool:
    from config import OWNER_ID
    if interaction.user.id == OWNER_ID:
        return True
    m = interaction.guild.get_member(interaction.user.id) if interaction.guild else None
    if m and m.guild_permissions.administrator:
        return True
    await interaction.response.send_message("🚫 Admin only.", ephemeral=True)
    return False

# ── Fact Delay Modal (text input — only thing that needs typing) ──────────────
class FactDelayModal(discord.ui.Modal, title="⏱️ Fact Drop Interval"):
    hours = discord.ui.TextInput(label="Hours between drops (1–168)", placeholder="e.g. 12")

    def __init__(self, guild_cfg, guild_id, parent_view):
        super().__init__()
        self.guild_cfg   = guild_cfg
        self.guild_id    = guild_id
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        try:
            h = int(self.hours.value.strip())
            if h < 1 or h > 168: raise ValueError
        except ValueError:
            await interaction.response.send_message("❌ Enter a number between 1 and 168.", ephemeral=True)
            return
        cfg = gs_mod.get_guild_cfg(self.guild_cfg, self.guild_id)
        cfg["fact_interval_hours"] = h
        cfg["last_fact_post"]      = datetime.now(timezone.utc).isoformat()
        gs_mod.save_guild_cfg(self.guild_cfg, self.guild_id, cfg)
        await interaction.response.edit_message(
            embed=build_config_embed(self.guild_cfg, self.guild_id),
            view=SetupMenuView(self.guild_cfg, self.guild_id),
            content=f"✅ Fact interval set to every **{h}** hour(s)."
        )

class CooldownModal(discord.ui.Modal, title="⏳ Pull Cooldowns"):
    default_cd = discord.ui.TextInput(label="Default cooldown (minutes)", placeholder="e.g. 60", required=False)
    role_cd    = discord.ui.TextInput(label="Custom role cooldown (minutes)", placeholder="e.g. 30", required=False)

    def __init__(self, guild_cfg, guild_id, selected_role_id=None):
        super().__init__()
        self.guild_cfg       = guild_cfg
        self.guild_id        = guild_id
        self.selected_role_id = selected_role_id

    async def on_submit(self, interaction: discord.Interaction):
        cfg  = gs_mod.get_guild_cfg(self.guild_cfg, self.guild_id)
        cfg.setdefault("cooldowns", {"default": DEFAULT_PULL_COOLDOWN_MINUTES, "roles": {}})
        msgs = []
        if self.default_cd.value.strip():
            try:
                m = int(self.default_cd.value.strip())
                if m < 1 or m > 1440: raise ValueError
                cfg["cooldowns"]["default"] = m
                msgs.append(f"✅ Default cooldown set to **{m}** min.")
            except ValueError:
                msgs.append("❌ Default must be 1–1440 minutes.")
        if self.selected_role_id and self.role_cd.value.strip():
            try:
                m = int(self.role_cd.value.strip())
                if m < 1 or m > 1440: raise ValueError
                cfg["cooldowns"]["roles"][str(self.selected_role_id)] = m
                msgs.append(f"✅ <@&{self.selected_role_id}> cooldown set to **{m}** min.")
            except ValueError:
                msgs.append("❌ Role cooldown must be 1–1440 minutes.")
        gs_mod.save_guild_cfg(self.guild_cfg, self.guild_id, cfg)
        await interaction.response.edit_message(
            embed=build_config_embed(self.guild_cfg, self.guild_id),
            view=SetupMenuView(self.guild_cfg, self.guild_id),
            content="\n".join(msgs) or None
        )

# ── Sub-views (channel/role selectors) ───────────────────────────────────────

class FactChannelView(discord.ui.View):
    def __init__(self, guild_cfg, guild_id):
        super().__init__(timeout=120)
        self.guild_cfg = guild_cfg
        self.guild_id  = guild_id

    @discord.ui.select(cls=discord.ui.ChannelSelect, placeholder="Add a fact channel...", min_values=1, max_values=5)
    async def add_select(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        if not await _admin_check(interaction): return
        cfg = gs_mod.get_guild_cfg(self.guild_cfg, self.guild_id)
        added = []
        for ch in select.values:
            if ch.id not in cfg["fact_channels"]:
                cfg["fact_channels"].append(ch.id)
                added.append(ch.mention)
        gs_mod.save_guild_cfg(self.guild_cfg, self.guild_id, cfg)
        msg = f"✅ Added: {', '.join(added)}" if added else "⚠️ Already added."
        await interaction.response.edit_message(
            embed=build_config_embed(self.guild_cfg, self.guild_id),
            view=FactChannelView(self.guild_cfg, self.guild_id),
            content=msg
        )

    @discord.ui.select(cls=discord.ui.ChannelSelect, placeholder="Remove a fact channel...", min_values=1, max_values=5, row=1)
    async def remove_select(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        if not await _admin_check(interaction): return
        cfg = gs_mod.get_guild_cfg(self.guild_cfg, self.guild_id)
        removed = []
        for ch in select.values:
            if ch.id in cfg["fact_channels"]:
                cfg["fact_channels"].remove(ch.id)
                removed.append(ch.mention)
        gs_mod.save_guild_cfg(self.guild_cfg, self.guild_id, cfg)
        msg = f"✅ Removed: {', '.join(removed)}" if removed else "⚠️ Not in fact channels."
        await interaction.response.edit_message(
            embed=build_config_embed(self.guild_cfg, self.guild_id),
            view=FactChannelView(self.guild_cfg, self.guild_id),
            content=msg
        )

    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=build_config_embed(self.guild_cfg, self.guild_id),
            view=SetupMenuView(self.guild_cfg, self.guild_id),
            content=None
        )

class MOTDChannelView(discord.ui.View):
    """Configure dedicated Moose of the Day channels."""
    def __init__(self, guild_cfg, guild_id):
        super().__init__(timeout=120)
        self.guild_cfg = guild_cfg
        self.guild_id  = guild_id

    @discord.ui.select(cls=discord.ui.ChannelSelect, placeholder="Add a MOTD channel...", min_values=1, max_values=5)
    async def add_select(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        if not await _admin_check(interaction): return
        cfg = gs_mod.get_guild_cfg(self.guild_cfg, self.guild_id)
        cfg.setdefault("motd_channels", [])
        added = []
        for ch in select.values:
            if ch.id not in cfg["motd_channels"]:
                cfg["motd_channels"].append(ch.id)
                added.append(ch.mention)
        gs_mod.save_guild_cfg(self.guild_cfg, self.guild_id, cfg)
        msg = f"✅ Added: {', '.join(added)}" if added else "⚠️ Already added."
        await interaction.response.edit_message(
            embed=build_config_embed(self.guild_cfg, self.guild_id),
            view=MOTDChannelView(self.guild_cfg, self.guild_id),
            content=msg
        )

    @discord.ui.select(cls=discord.ui.ChannelSelect, placeholder="Remove a MOTD channel...", min_values=1, max_values=5, row=1)
    async def remove_select(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        if not await _admin_check(interaction): return
        cfg = gs_mod.get_guild_cfg(self.guild_cfg, self.guild_id)
        cfg.setdefault("motd_channels", [])
        removed = []
        for ch in select.values:
            if ch.id in cfg["motd_channels"]:
                cfg["motd_channels"].remove(ch.id)
                removed.append(ch.mention)
        gs_mod.save_guild_cfg(self.guild_cfg, self.guild_id, cfg)
        msg = f"✅ Removed: {', '.join(removed)}" if removed else "⚠️ Not in MOTD channels."
        await interaction.response.edit_message(
            embed=build_config_embed(self.guild_cfg, self.guild_id),
            view=MOTDChannelView(self.guild_cfg, self.guild_id),
            content=msg
        )

    @discord.ui.button(label="🗑️ Clear All MOTD Channels", style=discord.ButtonStyle.danger, row=2)
    async def clear(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _admin_check(interaction): return
        cfg = gs_mod.get_guild_cfg(self.guild_cfg, self.guild_id)
        cfg["motd_channels"] = []
        gs_mod.save_guild_cfg(self.guild_cfg, self.guild_id, cfg)
        await interaction.response.edit_message(
            embed=build_config_embed(self.guild_cfg, self.guild_id),
            view=MOTDChannelView(self.guild_cfg, self.guild_id),
            content="✅ MOTD channels cleared — will fall back to fact channels."
        )

    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.secondary, row=3)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=build_config_embed(self.guild_cfg, self.guild_id),
            view=SetupMenuView(self.guild_cfg, self.guild_id),
            content=None
        )

class CommandChannelView(discord.ui.View):
    def __init__(self, guild_cfg, guild_id):
        super().__init__(timeout=120)
        self.guild_cfg = guild_cfg
        self.guild_id  = guild_id

    @discord.ui.select(cls=discord.ui.ChannelSelect, placeholder="Allowlist a channel (commands only here)...", min_values=1, max_values=5)
    async def allow_select(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        if not await _admin_check(interaction): return
        cfg = gs_mod.get_guild_cfg(self.guild_cfg, self.guild_id)
        for ch in select.values:
            if ch.id not in cfg["command_channels"]:
                cfg["command_channels"].append(ch.id)
            cfg["excluded_channels"] = [c for c in cfg["excluded_channels"] if c != ch.id]
        gs_mod.save_guild_cfg(self.guild_cfg, self.guild_id, cfg)
        names = ", ".join(ch.mention for ch in select.values)
        await interaction.response.edit_message(
            embed=build_config_embed(self.guild_cfg, self.guild_id),
            view=CommandChannelView(self.guild_cfg, self.guild_id),
            content=f"✅ Allowlisted: {names}"
        )

    @discord.ui.select(cls=discord.ui.ChannelSelect, placeholder="Exclude a channel (no commands here)...", min_values=1, max_values=5, row=1)
    async def exclude_select(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        if not await _admin_check(interaction): return
        cfg = gs_mod.get_guild_cfg(self.guild_cfg, self.guild_id)
        for ch in select.values:
            if ch.id not in cfg["excluded_channels"]:
                cfg["excluded_channels"].append(ch.id)
            cfg["command_channels"] = [c for c in cfg["command_channels"] if c != ch.id]
        gs_mod.save_guild_cfg(self.guild_cfg, self.guild_id, cfg)
        names = ", ".join(ch.mention for ch in select.values)
        await interaction.response.edit_message(
            embed=build_config_embed(self.guild_cfg, self.guild_id),
            view=CommandChannelView(self.guild_cfg, self.guild_id),
            content=f"✅ Excluded: {names}"
        )

    @discord.ui.button(label="🗑️ Clear All Channel Restrictions", style=discord.ButtonStyle.danger, row=2)
    async def clear(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _admin_check(interaction): return
        cfg = gs_mod.get_guild_cfg(self.guild_cfg, self.guild_id)
        cfg["command_channels"]  = []
        cfg["excluded_channels"] = []
        gs_mod.save_guild_cfg(self.guild_cfg, self.guild_id, cfg)
        await interaction.response.edit_message(
            embed=build_config_embed(self.guild_cfg, self.guild_id),
            view=CommandChannelView(self.guild_cfg, self.guild_id),
            content="✅ All channel restrictions cleared."
        )

    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.secondary, row=3)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=build_config_embed(self.guild_cfg, self.guild_id),
            view=SetupMenuView(self.guild_cfg, self.guild_id),
            content=None
        )

class RolesView(discord.ui.View):
    def __init__(self, guild_cfg, guild_id):
        super().__init__(timeout=120)
        self.guild_cfg = guild_cfg
        self.guild_id  = guild_id

    @discord.ui.select(cls=discord.ui.RoleSelect, placeholder="Allowlist a role (only they can use bot)...", min_values=1, max_values=5)
    async def allow_select(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        if not await _admin_check(interaction): return
        cfg = gs_mod.get_guild_cfg(self.guild_cfg, self.guild_id)
        for role in select.values:
            if role.id not in cfg["allowed_roles"]:
                cfg["allowed_roles"].append(role.id)
            cfg["excluded_roles"] = [r for r in cfg["excluded_roles"] if r != role.id]
        gs_mod.save_guild_cfg(self.guild_cfg, self.guild_id, cfg)
        names = ", ".join(r.mention for r in select.values)
        await interaction.response.edit_message(
            embed=build_config_embed(self.guild_cfg, self.guild_id),
            view=RolesView(self.guild_cfg, self.guild_id),
            content=f"✅ Allowlisted: {names}"
        )

    @discord.ui.select(cls=discord.ui.RoleSelect, placeholder="Exclude a role (block from commands)...", min_values=1, max_values=5, row=1)
    async def exclude_select(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        if not await _admin_check(interaction): return
        cfg = gs_mod.get_guild_cfg(self.guild_cfg, self.guild_id)
        for role in select.values:
            if role.id not in cfg["excluded_roles"]:
                cfg["excluded_roles"].append(role.id)
            cfg["allowed_roles"] = [r for r in cfg["allowed_roles"] if r != role.id]
        gs_mod.save_guild_cfg(self.guild_cfg, self.guild_id, cfg)
        names = ", ".join(r.mention for r in select.values)
        await interaction.response.edit_message(
            embed=build_config_embed(self.guild_cfg, self.guild_id),
            view=RolesView(self.guild_cfg, self.guild_id),
            content=f"✅ Excluded: {names}"
        )

    @discord.ui.button(label="🗑️ Clear All Role Restrictions", style=discord.ButtonStyle.danger, row=2)
    async def clear(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _admin_check(interaction): return
        cfg = gs_mod.get_guild_cfg(self.guild_cfg, self.guild_id)
        cfg["allowed_roles"]  = []
        cfg["excluded_roles"] = []
        gs_mod.save_guild_cfg(self.guild_cfg, self.guild_id, cfg)
        await interaction.response.edit_message(
            embed=build_config_embed(self.guild_cfg, self.guild_id),
            view=RolesView(self.guild_cfg, self.guild_id),
            content="✅ All role restrictions cleared."
        )

    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.secondary, row=3)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=build_config_embed(self.guild_cfg, self.guild_id),
            view=SetupMenuView(self.guild_cfg, self.guild_id),
            content=None
        )

class CooldownRoleView(discord.ui.View):
    """Pick a role then open the cooldown modal."""
    def __init__(self, guild_cfg, guild_id):
        super().__init__(timeout=120)
        self.guild_cfg       = guild_cfg
        self.guild_id        = guild_id
        self.selected_role_id = None

    @discord.ui.select(cls=discord.ui.RoleSelect, placeholder="Select role for custom cooldown (optional)...", min_values=0, max_values=1)
    async def role_select(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        if not await _admin_check(interaction): return
        self.selected_role_id = select.values[0].id if select.values else None
        await interaction.response.defer()

    @discord.ui.button(label="⏳ Set Cooldowns", style=discord.ButtonStyle.primary, row=1)
    async def open_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _admin_check(interaction): return
        await interaction.response.send_modal(
            CooldownModal(self.guild_cfg, self.guild_id, self.selected_role_id)
        )

    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=build_config_embed(self.guild_cfg, self.guild_id),
            view=SetupMenuView(self.guild_cfg, self.guild_id),
            content=None
        )

# ── Reset Confirm ─────────────────────────────────────────────────────────────
class ResetConfirmView(discord.ui.View):
    def __init__(self, guild_cfg, guild_id):
        super().__init__(timeout=30)
        self.guild_cfg = guild_cfg
        self.guild_id  = guild_id

    @discord.ui.button(label="Yes, reset everything", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _admin_check(interaction): return
        key = str(self.guild_id)
        if key in self.guild_cfg:
            del self.guild_cfg[key]
            gs_mod.save_guild_settings(self.guild_cfg)
        await interaction.response.edit_message(
            embed=build_config_embed(self.guild_cfg, self.guild_id),
            view=SetupMenuView(self.guild_cfg, self.guild_id),
            content="✅ Server config has been reset to defaults."
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=build_config_embed(self.guild_cfg, self.guild_id),
            view=SetupMenuView(self.guild_cfg, self.guild_id),
            content=None
        )

# ── Main Menu View ────────────────────────────────────────────────────────────
class SetupMenuView(discord.ui.View):
    def __init__(self, guild_cfg, guild_id):
        super().__init__(timeout=300)
        self.guild_cfg = guild_cfg
        self.guild_id  = guild_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await _admin_check(interaction)

    @discord.ui.button(label="📢 Fact Channels", style=discord.ButtonStyle.primary, row=0)
    async def btn_fact_channels(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=build_config_embed(self.guild_cfg, self.guild_id),
            view=FactChannelView(self.guild_cfg, self.guild_id),
            content="**📢 Fact Channels** — select channels to add or remove:"
        )

    @discord.ui.button(label="🌅 MOTD Channel", style=discord.ButtonStyle.primary, row=0)
    async def btn_motd_channels(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=build_config_embed(self.guild_cfg, self.guild_id),
            view=MOTDChannelView(self.guild_cfg, self.guild_id),
            content="**🌅 MOTD Channels** — where Moose of the Day posts (falls back to fact channels if not set):"
        )

    @discord.ui.button(label="⏱️ Fact Delay", style=discord.ButtonStyle.primary, row=0)
    async def btn_fact_delay(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            FactDelayModal(self.guild_cfg, self.guild_id, self)
        )

    @discord.ui.button(label="💬 Command Channels", style=discord.ButtonStyle.primary, row=0)
    async def btn_cmd_channels(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=build_config_embed(self.guild_cfg, self.guild_id),
            view=CommandChannelView(self.guild_cfg, self.guild_id),
            content="**💬 Command Channels** — allowlist or exclude channels:"
        )

    @discord.ui.button(label="👑 Roles", style=discord.ButtonStyle.primary, row=1)
    async def btn_roles(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=build_config_embed(self.guild_cfg, self.guild_id),
            view=RolesView(self.guild_cfg, self.guild_id),
            content="**👑 Roles** — allowlist or exclude roles:"
        )

    @discord.ui.button(label="⏳ Cooldowns", style=discord.ButtonStyle.primary, row=1)
    async def btn_cooldowns(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=build_config_embed(self.guild_cfg, self.guild_id),
            view=CooldownRoleView(self.guild_cfg, self.guild_id),
            content="**⏳ Cooldowns** — optionally select a role, then click Set Cooldowns:"
        )

    @discord.ui.button(label="👁️ Refresh Config", style=discord.ButtonStyle.secondary, row=1)
    async def btn_view(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=build_config_embed(self.guild_cfg, self.guild_id),
            view=self,
            content=None
        )

    @discord.ui.button(label="🔄 Reset Server Config", style=discord.ButtonStyle.danger, row=2)
    async def btn_reset(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=build_config_embed(self.guild_cfg, self.guild_id),
            view=ResetConfirmView(self.guild_cfg, self.guild_id),
            content="⚠️ Are you sure you want to reset ALL settings for this server?"
        )

# =============================================================================
#  OWNER PANEL
# =============================================================================
from user_collections import (
    add_pending_gift, pending_gift_count, save_collections
)

# Set once at startup by bot.py so back-navigation keeps bot access

# =============================================================================
#  SELL VIEW  — /sell command UI
# =============================================================================
SELL_PER_PAGE = 8

class SellView(discord.ui.View):
    """
    Paginated sell interface. Shows all cards (or dupes only) sorted by tier.
    Category jump dropdown + sort toggle + pagination.
    Entry points: /sell, /duplicates Sell Dupes button, /collection sell button.
    """
    def __init__(
        self,
        member,
        user_data: dict,
        col_data: dict,
        econ_data: dict,
        dupes_only: bool = False,
        back_view=None,
        start_tier: str = None,
    ):
        super().__init__(timeout=180)
        self.member      = member
        self.user_data   = user_data
        self.col_data    = col_data
        self.econ_data   = econ_data
        self.dupes_only  = dupes_only
        self.back_view   = back_view
        self.descending  = False   # False = common first; True = rarest first
        self.filter_tier = start_tier  # None = all tiers
        self.page        = 0

        self._build_card_list()
        self._refresh_buttons()

    def _build_card_list(self):
        """Build the working card list from user_data respecting current filters."""
        all_cards = get_all_cards_sorted(self.user_data, descending=self.descending)
        if self.dupes_only:
            all_cards = [c for c in all_cards if c.get("count", 1) > 1]
        if self.filter_tier:
            all_cards = [c for c in all_cards if c.get("tier") == self.filter_tier]
        self.cards       = all_cards
        self.total_pages = max(1, (len(self.cards) + SELL_PER_PAGE - 1) // SELL_PER_PAGE)
        self.page        = min(self.page, self.total_pages - 1)

    def _refresh_buttons(self):
        self.prev_btn.disabled = self.page == 0
        self.next_btn.disabled = self.page >= self.total_pages - 1
        self.sort_btn.label = "⬇️ Rarest First" if not self.descending else "⬆️ Common First"

    def build_embed(self) -> discord.Embed:
        mode = "Duplicates" if self.dupes_only else "All Cards"
        tier_label = TIER_LABELS.get(self.filter_tier, "All Tiers") if self.filter_tier else "All Tiers"
        econ_user = econ_mod.get_user_economy(self.econ_data, self.member.id)
        balance   = econ_user["catcoins"]

        embed = discord.Embed(
            title=f"🪙 Sell Cards — {self.member.display_name}",
            description=(
                f"**Balance:** {balance:,} CatCoins  |  **Showing:** {mode} / {tier_label}\nSelect a card number below to sell it."
            ),
            color=0xFFD700
        )

        start      = self.page * SELL_PER_PAGE
        page_cards = self.cards[start:start + SELL_PER_PAGE]

        if page_cards:
            lines = []
            for i, card in enumerate(page_cards, start=start + 1):
                filename  = card["filename"]
                tier      = card.get("tier", "common")
                count     = card.get("count", 1)
                sell_val  = CATCOIN_SELL_VALUES.get(tier, 0)
                count_str = f" (x{count})" if count > 1 else ""
                lines.append(
                    f"`{i}.` {TIER_EMOJIS[tier]} `{filename}`{count_str} "
                    f"— {TIER_LABELS[tier]} • **{sell_val} 🪙 ea**"
                )
            embed.add_field(name="Cards", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="Cards", value="_No cards match this filter._", inline=False)

        embed.set_footer(text=f"Page {self.page + 1} of {self.total_pages} | Use 🔢 Sell Card to choose")
        return embed

    # ── Category jump ──────────────────────────────────────────────────────────
    @discord.ui.select(
        placeholder="Jump to tier...",
        options=[
            discord.SelectOption(label="All Tiers",     value="all"),
            discord.SelectOption(label="Common",        value="common"),
            discord.SelectOption(label="Rare",          value="rare"),
            discord.SelectOption(label="Ultra Rare",    value="ultra_rare"),
            discord.SelectOption(label="Secret Rare",   value="secret_rare"),
            discord.SelectOption(label="Legendary",     value="legendary"),
            discord.SelectOption(label="Mythic Rare",   value="mythic_rare"),
            discord.SelectOption(label="Secret Mythic", value="secret_mythic"),
            discord.SelectOption(label="Primordial",    value="primordial"),
        ],
        row=0,
    )
    async def category_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        val = select.values[0]
        self.filter_tier = None if val == "all" else val
        self.page = 0
        self._build_card_list()
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    # ── Sort toggle ────────────────────────────────────────────────────────────
    @discord.ui.button(label="⬇️ Rarest First", style=discord.ButtonStyle.secondary, row=1)
    async def sort_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.descending = not self.descending
        self.page = 0
        self._build_card_list()
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    # ── Sell card ──────────────────────────────────────────────────────────────
    @discord.ui.button(label="🔢 Sell Card", style=discord.ButtonStyle.primary, row=1)
    async def sell_card_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.cards:
            await interaction.response.send_message("No cards to sell.", ephemeral=True); return
        await interaction.response.send_modal(SellCardModal(self))

    # ── Pagination ─────────────────────────────────────────────────────────────
    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary, row=2)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page -= 1
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary, row=2)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    # ── Back ───────────────────────────────────────────────────────────────────
    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.secondary, row=3)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.back_view:
            await interaction.response.edit_message(
                embed=self.back_view.build_embed(), view=self.back_view
            )
        else:
            await interaction.response.edit_message(
                content="Sell menu closed.", embed=None, view=None
            )


class SellCardModal(discord.ui.Modal, title="Sell a Card"):
    number = discord.ui.TextInput(
        label="Card number from the list",
        placeholder="e.g. 3",
        min_length=1, max_length=4,
    )
    quantity = discord.ui.TextInput(
        label="How many to sell?",
        placeholder="e.g. 1",
        min_length=1, max_length=4,
        default="1",
    )

    def __init__(self, parent_view: SellView):
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        # Parse and validate card number
        try:
            idx = int(self.number.value.strip()) - 1
        except ValueError:
            await interaction.response.send_message("❌ Enter a valid card number.", ephemeral=True); return

        cards = self.parent_view.cards
        if idx < 0 or idx >= len(cards):
            await interaction.response.send_message(
                f"❌ Number must be between 1 and {len(cards)}.", ephemeral=True
            ); return

        # Parse quantity
        try:
            qty = int(self.quantity.value.strip())
            if qty < 1:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("❌ Quantity must be a positive number.", ephemeral=True); return

        card     = cards[idx]
        filename = card["filename"]
        tier     = card.get("tier", "common")
        owned    = card.get("count", 1)
        sell_val = CATCOIN_SELL_VALUES.get(tier, 0)
        total_coins = sell_val * qty

        if qty > owned:
            await interaction.response.send_message(
                f"❌ You only own **{owned}** of `{filename}`.", ephemeral=True
            ); return

        # Build confirmation view
        confirm = SellConfirmView(self.parent_view, filename, tier, qty, owned, total_coins)
        embed   = confirm.build_embed()
        await interaction.response.send_message(embed=embed, view=confirm, ephemeral=True)


class SellConfirmView(discord.ui.View):
    """One-shot confirmation before executing a sell."""

    def __init__(
        self,
        parent_view: SellView,
        filename: str,
        tier: str,
        quantity: int,
        owned: int,
        total_coins: int,
    ):
        super().__init__(timeout=60)
        self.parent_view = parent_view
        self.filename    = filename
        self.tier        = tier
        self.quantity    = quantity
        self.owned       = owned
        self.total_coins = total_coins

    def build_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🪙 Confirm Sale",
            color=TIER_COLORS.get(self.tier, 0xFFD700),
        )
        embed.add_field(name="Card",     value=f"`{self.filename}`",                      inline=True)
        embed.add_field(name="Tier",     value=TIER_LABELS.get(self.tier, self.tier),     inline=True)
        embed.add_field(name="Selling",  value=f"**{self.quantity}** of {self.owned}",    inline=True)
        embed.add_field(name="You'll Receive", value=f"**{self.total_coins:,} 🪙 CatCoins**", inline=False)
        if self.quantity == self.owned:
            embed.add_field(
                name="⚠️ Last Copy Warning",
                value="You are selling your **only copy** of this card. It will be permanently removed from your collection.",
                inline=False,
            )
        embed.set_footer(text="This action cannot be undone.")
        return embed

    @discord.ui.button(label="✅ Confirm Sell", style=discord.ButtonStyle.success, row=0)
    async def confirm_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Execute sale
        ok, err = sell_card_copies(
            self.parent_view.col_data,
            interaction.user.id,
            self.filename,
            self.quantity,
        )
        if not ok:
            await interaction.response.edit_message(
                content=f"❌ {err}", embed=None, view=None
            ); return

        # Award coins
        econ_ok, coins_awarded, msg = econ_mod.sell_cards(
            self.parent_view.econ_data,
            interaction.user.id,
            self.filename,
            self.tier,
            self.quantity,
        )

        # Refresh parent view card list
        self.parent_view.user_data = self.parent_view.col_data.get(
            str(interaction.user.id),
            self.parent_view.user_data
        )
        self.parent_view._build_card_list()
        self.parent_view._refresh_buttons()

        new_balance = econ_mod.get_balance(self.parent_view.econ_data, interaction.user.id)
        await interaction.response.edit_message(
            content=(
                f"✅ Sold **{self.quantity}x** `{self.filename}` for "
                f"**{self.total_coins:,} 🪙 CatCoins**!\nNew balance: **{new_balance:,} CatCoins**"
            ),
            embed=None,
            view=None,
        )

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.secondary, row=0)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="Sale cancelled.", embed=None, view=None
        )

_bot_ref = None
def set_bot_ref(bot): global _bot_ref; _bot_ref = bot

TIER_CHOICES = ["roll", "common", "rare", "ultra_rare", "legendary"]
TIER_DISPLAY = {
    "roll":       "Normal Roll (hash-based)",
    "common":     "⬜ Common",
    "rare":       "🔵 Rare",
    "ultra_rare": "🟣 Ultra Rare",
    "legendary":  "🌟 Legendary",
}

def build_owner_embed() -> discord.Embed:
    embed = discord.Embed(
        title="👑 Moose Overlord Panel",
        description=(
            "Private owner controls. All actions are ephemeral — only you see this.\n\n"
            "**🗑️ Clear Profile** — wipe a user's collection, pulls, pity, and pending gifts.\n"
            "**🎁 Gift a Pull** — queue a guaranteed tier pull for a user's next `/random`.\n"
            "**📦 Gift a Pack** — gift a Daily (3 cards) or Weekly (5 cards) MOOSEter pack, independent of their normal cooldowns.\n"
            "**📦 Mass Gift** — gift packs to a whole server at once (active users or everyone).\n"
            "**🐾 Post Moosifur Fact** — instantly drop a random Moosifur fact into any channel."
        ),
        color=0xF59E0B
    )
    embed.set_footer(text="With great power comes great Moose responsibility. 🐾")
    return embed

class ClearUserIDModal(discord.ui.Modal, title="Enter User ID to Clear"):
    user_id_input = discord.ui.TextInput(
        label="User ID",
        placeholder="e.g. 196106852214243328",
        min_length=10, max_length=20
    )

    def __init__(self, col_data):
        super().__init__()
        self.col_data = col_data

    async def on_submit(self, interaction: discord.Interaction):
        try:
            uid = int(self.user_id_input.value.strip())
        except ValueError:
            await interaction.response.send_message("❌ Invalid user ID.", ephemeral=True)
            return
        key = str(uid)
        if key in self.col_data:
            del self.col_data[key]
            save_collections(self.col_data)
            msg = f"✅ Profile for user ID `{uid}` wiped — collection, pulls, pity, and pending gifts all cleared."
        else:
            msg = f"⚠️ No profile found for user ID `{uid}`. Nothing to clear."
        from ui import build_owner_embed, OwnerPanelView
        await interaction.response.edit_message(
            content=msg,
            embed=build_owner_embed(),
            view=OwnerPanelView(self.col_data, None)
        )

class ClearProfileView(discord.ui.View):
    """Pick a member via dropdown or enter a user ID manually."""
    def __init__(self, col_data):
        super().__init__(timeout=120)
        self.col_data       = col_data
        self.selected_id    = None
        self.selected_name  = None

    @discord.ui.select(
        cls=discord.ui.UserSelect,
        placeholder="Select a user to clear...",
        min_values=1, max_values=1
    )
    async def user_select(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        self.selected_id   = select.values[0].id
        self.selected_name = select.values[0].display_name
        self.confirm_btn.disabled = False
        await interaction.response.edit_message(
            content=f"⚠️ Ready to wipe **{self.selected_name}**'s profile. Press Confirm to proceed.",
            view=self
        )

    @discord.ui.button(label="🔢 Enter User ID Instead", style=discord.ButtonStyle.secondary, row=1)
    async def id_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ClearUserIDModal(self.col_data))

    @discord.ui.button(label="✅ Confirm Clear", style=discord.ButtonStyle.danger, disabled=True, row=1)
    async def confirm_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        key = str(self.selected_id)
        if key in self.col_data:
            del self.col_data[key]
            save_collections(self.col_data)
        from ui import build_owner_embed, OwnerPanelView
        await interaction.response.edit_message(
            content=f"✅ **{self.selected_name}**'s profile wiped — collection, pulls, pity, and pending gifts all cleared.",
            embed=build_owner_embed(),
            view=OwnerPanelView(self.col_data, None)
        )

    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        from ui import build_owner_embed, OwnerPanelView
        await interaction.response.edit_message(
            content=None,
            embed=build_owner_embed(),
            view=OwnerPanelView(self.col_data, None)
        )

class GiftUserIDModal(discord.ui.Modal, title="Enter User ID to Gift"):
    user_id_input = discord.ui.TextInput(
        label="User ID",
        placeholder="e.g. 196106852214243328",
        min_length=10, max_length=20
    )

    def __init__(self, gift_view):
        super().__init__()
        self.gift_view = gift_view

    async def on_submit(self, interaction: discord.Interaction):
        try:
            uid = int(self.user_id_input.value.strip())
        except ValueError:
            await interaction.response.send_message("❌ Invalid user ID.", ephemeral=True)
            return
        self.gift_view.selected_id   = uid
        self.gift_view.selected_name = f"User `{uid}`"
        await interaction.response.edit_message(
            content=self.gift_view._status(),
            view=self.gift_view
        )

class GiftPullView(discord.ui.View):
    """Pick a user via dropdown or ID, pick a tier, queue the gift."""
    def __init__(self, col_data, guild_cfg):
        super().__init__(timeout=120)
        self.col_data      = col_data
        self.guild_cfg     = guild_cfg
        self.selected_id   = None
        self.selected_name = None
        self.selected_tier = "roll"

    @discord.ui.select(
        cls=discord.ui.UserSelect,
        placeholder="Select a user to gift...",
        min_values=1, max_values=1,
        row=0
    )
    async def user_select(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        self.selected_id   = select.values[0].id
        self.selected_name = select.values[0].display_name
        await interaction.response.edit_message(
            content=self._status(),
            view=self
        )

    @discord.ui.button(label="🔢 Enter User ID Instead", style=discord.ButtonStyle.secondary, row=1)
    async def id_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(GiftUserIDModal(self))

    @discord.ui.select(
        placeholder="Select guaranteed tier (or leave as Normal Roll)...",
        options=[
            discord.SelectOption(label=v, value=k)
            for k, v in TIER_DISPLAY.items()
        ],
        row=2
    )
    async def tier_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.selected_tier = select.values[0]
        await interaction.response.edit_message(
            content=self._status(),
            view=self
        )

    @discord.ui.button(label="🎁 Queue Gift", style=discord.ButtonStyle.success, row=3)
    async def gift_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.selected_id:
            await interaction.response.edit_message(content="⚠️ Please select a user first.", view=self)
            return

        # For "roll" we queue a random tier pre-determined now using hash
        if self.selected_tier == "roll":
            from pull import determine_tier
            from user_collections import get_user
            user_data = get_user(self.col_data, self.selected_id)
            pity      = user_data.get("pity_counter", 0)
            tier      = determine_tier(self.selected_id, 0, pity)
        else:
            tier = self.selected_tier

        add_pending_gift(self.col_data, self.selected_id, tier)
        count = pending_gift_count(self.col_data, self.selected_id)

        from ui import build_owner_embed, OwnerPanelView
        await interaction.response.edit_message(
            content=(
                f"✅ Gift queued for **{self.selected_name}**!\n"
                f"Tier: **{TIER_DISPLAY[tier if self.selected_tier == 'roll' else self.selected_tier]}**\n"
                f"They now have **{count}** pending gift(s). It will deliver on their next `/random`."
            ),
            embed=build_owner_embed(),
            view=OwnerPanelView(self.col_data, self.guild_cfg)
        )

    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.secondary, row=3)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        from ui import build_owner_embed, OwnerPanelView
        await interaction.response.edit_message(
            content=None,
            embed=build_owner_embed(),
            view=OwnerPanelView(self.col_data, self.guild_cfg)
        )

    def _status(self) -> str:
        user_str = f"**{self.selected_name}**" if self.selected_name else "_no user selected_"
        tier_str = TIER_DISPLAY.get(self.selected_tier, "Normal Roll")
        return f"User: {user_str} | Tier: **{tier_str}**"

class OwnerPanelView(discord.ui.View):
    def __init__(self, col_data, guild_cfg, bot_ref=None):
        super().__init__(timeout=300)
        self.col_data  = col_data
        self.guild_cfg = guild_cfg
        # Fall back to module-level ref so back-navigation always works
        self.bot_ref   = bot_ref or _bot_ref

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        from config import OWNER_ID
        if interaction.user.id == OWNER_ID:
            return True
        await interaction.response.send_message("🚫 Owner only.", ephemeral=True)
        return False

    @discord.ui.button(label="🗑️ Clear Profile", style=discord.ButtonStyle.danger, row=0)
    async def btn_clear(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**🗑️ Clear Profile** — select a user to wipe:",
            embed=None,
            view=ClearProfileView(self.col_data)
        )

    @discord.ui.button(label="🎁 Gift a Pull", style=discord.ButtonStyle.success, row=0)
    async def btn_gift(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**🎁 Gift a Pull** — select a user and tier:",
            embed=None,
            view=GiftPullView(self.col_data, self.guild_cfg)
        )

    @discord.ui.button(label="📦 Gift a Pack", style=discord.ButtonStyle.primary, row=1)
    async def btn_gift_pack(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**📦 Gift a Pack** — select a user and pack type:",
            embed=None,
            view=GiftPackView(self.col_data)
        )

    @discord.ui.button(label="📦 Mass Gift", style=discord.ButtonStyle.primary, row=1)
    async def btn_mass_gift(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.bot_ref:
            await interaction.response.send_message(
                "❌ Bot reference unavailable. Re-open `/owner` and try again.", ephemeral=True
            )
            return
        await interaction.response.edit_message(
            content="**📦 Mass Gift** — configure your gift drop:",
            embed=None,
            view=MassGiftStep1View(self.col_data, self.bot_ref),
        )

    @discord.ui.button(label="🐾 Post Moosifur Fact", style=discord.ButtonStyle.secondary, row=1)
    async def btn_moose_fact(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**🐾 Post Moosifur Fact** — select a channel:",
            embed=None,
            view=PostMooseFactView()
        )


class PostMooseFactView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        placeholder="Select channel to post in...",
        min_values=1, max_values=1
    )
    async def channel_select(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        import facts as facts_mod
        from pathlib import Path
        moose_facts = facts_mod.load_moose_facts()
        if not moose_facts:
            await interaction.response.edit_message(
                content="⚠️ No Moosifur facts found! Add some with `!fact`.",
                view=self
            ); return
        import random
        fact    = random.choice(moose_facts)
        channel  = select.values[0].resolve()
        surprise = Path("surprise.png")
        try:
            if surprise.exists():
                await channel.send(embed=moose_fact_embed(fact), file=discord.File(surprise))
            else:
                await channel.send(embed=moose_fact_embed(fact))
            await interaction.response.edit_message(
                content=f"✅ Moosifur fact posted to {channel.mention}!",
                embed=build_owner_embed(),
                view=OwnerPanelView(None, None)
            )
        except discord.Forbidden:
            await interaction.response.edit_message(
                content=f"❌ No permission to post in {channel.mention}.",
                view=self
            )

    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content=None,
            embed=build_owner_embed(),
            view=OwnerPanelView(None, None)
        )

# =============================================================================
#  GIFT A PACK FLOW (owner only)
# =============================================================================
class GiftPackUserIDModal(discord.ui.Modal, title="Enter Recipient User ID"):
    user_id_input = discord.ui.TextInput(label="User ID", placeholder="e.g. 196106852214243328", min_length=10, max_length=20)

    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        try:
            uid = int(self.user_id_input.value.strip())
        except ValueError:
            await interaction.response.send_message("❌ Invalid user ID.", ephemeral=True); return
        self.parent_view.selected_user_id   = uid
        self.parent_view.selected_user_name = f"User {uid}"
        await interaction.response.edit_message(content=self.parent_view._status(), view=self.parent_view)

class GiftPackView(discord.ui.View):
    def __init__(self, col_data):
        super().__init__(timeout=120)
        self.col_data           = col_data
        self.selected_user_id   = None
        self.selected_user_name = None
        self.selected_pack_type = None

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="Select recipient...", min_values=1, max_values=1, row=0)
    async def user_select(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        self.selected_user_id   = select.values[0].id
        self.selected_user_name = select.values[0].display_name
        await interaction.response.edit_message(content=self._status(), view=self)

    @discord.ui.select(
        placeholder="Select pack type...",
        options=[
            discord.SelectOption(label="📦 Daily Pack (3 cards, common odds)", value="daily",  emoji="📦"),
            discord.SelectOption(label="🎁 Weekly Pack (5 cards, better odds)", value="weekly", emoji="🎁"),
        ],
        row=1
    )
    async def pack_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.selected_pack_type = select.values[0]
        await interaction.response.edit_message(content=self._status(), view=self)

    @discord.ui.button(label="🔢 Enter User ID Instead", style=discord.ButtonStyle.secondary, row=2)
    async def id_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(GiftPackUserIDModal(self))

    @discord.ui.button(label="✅ Gift Pack", style=discord.ButtonStyle.success, row=2)
    async def confirm_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.selected_user_id or not self.selected_pack_type:
            await interaction.response.edit_message(content="⚠️ Please select both a user and a pack type.", view=self); return
        from user_collections import add_bonus_pack, bonus_pack_count
        add_bonus_pack(self.col_data, self.selected_user_id, self.selected_pack_type)
        count = bonus_pack_count(self.col_data, self.selected_user_id)
        pack_label = "Daily" if self.selected_pack_type == "daily" else "Weekly"
        await interaction.response.edit_message(
            content=(
                f"✅ **{pack_label} MOOSEter Pack** gifted to **{self.selected_user_name}**!\n"
                f"They now have **{count}** bonus pack(s) waiting. They can claim with `/bonuspack`."
            ),
            embed=build_owner_embed(),
            view=OwnerPanelView(self.col_data, None)
        )

    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.secondary, row=3)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content=None,
            embed=build_owner_embed(),
            view=OwnerPanelView(self.col_data, None)
        )

    def _status(self):
        user_str = f"**{self.selected_user_name}**" if self.selected_user_name else "_none_"
        pack_str = self.selected_pack_type.capitalize() if self.selected_pack_type else "_none_"
        return f"Recipient: {user_str} | Pack: **{pack_str}**"

# =============================================================================
#  MASS GIFT FLOW (owner only)
# =============================================================================

class MassGiftAmountModal(discord.ui.Modal, title="Mass Gift — Amount Per User"):
    amount_input = discord.ui.TextInput(
        label="Packs per user (1–20)",
        placeholder="e.g. 1",
        min_length=1,
        max_length=2,
        default="1",
    )

    def __init__(self, step1_view: "MassGiftStep1View"):
        super().__init__()
        self.step1_view = step1_view

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount = int(self.amount_input.value.strip())
            if not (1 <= amount <= 20):
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "❌ Please enter a whole number between 1 and 20.", ephemeral=True
            )
            return
        self.step1_view.amount = amount
        confirm_view = MassGiftConfirmView(self.step1_view)
        await interaction.response.edit_message(
            content=confirm_view._summary(),
            view=confirm_view,
        )


class MassGiftStep1View(discord.ui.View):
    """
    Step 1 of 2 — pick server, audience filter, pack type.
    Amount is collected via a Modal, then we move to MassGiftConfirmView.
    """

    def __init__(self, col_data: dict, bot_ref):
        super().__init__(timeout=180)
        self.col_data   = col_data
        self.bot_ref    = bot_ref
        self.guild_id   = None
        self.guild_name = None
        self.audience   = "active"   # "active" | "everyone"
        self.pack_type  = "daily"    # "daily"  | "weekly"
        self.amount     = 1

        # Populate server dropdown from live guild list (max 25 options)
        guilds = sorted(bot_ref.guilds, key=lambda g: g.name.lower())[:25]
        self.server_select.options = [
            discord.SelectOption(
                label=g.name[:100],
                value=str(g.id),
                description=f"{g.member_count or '?'} members",
            )
            for g in guilds
        ]

    # ── Row 0: server ─────────────────────────────────────────────────────────
    @discord.ui.select(placeholder="1️⃣  Pick a server…", row=0)
    async def server_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.guild_id   = int(select.values[0])
        guild           = self.bot_ref.get_guild(self.guild_id)
        self.guild_name = guild.name if guild else f"Guild {self.guild_id}"
        await interaction.response.edit_message(content=self._status(), view=self)

    # ── Row 1: audience ───────────────────────────────────────────────────────
    @discord.ui.select(
        placeholder="2️⃣  Who receives the gift?",
        options=[
            discord.SelectOption(
                label="🟢 Active users only (last 30 days)",
                value="active",
                default=True,
            ),
            discord.SelectOption(
                label="👥 Everyone in server (non-bot members)",
                value="everyone",
            ),
        ],
        row=1,
    )
    async def audience_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.audience = select.values[0]
        for opt in self.audience_select.options:
            opt.default = (opt.value == self.audience)
        await interaction.response.edit_message(content=self._status(), view=self)

    # ── Row 2: pack type ──────────────────────────────────────────────────────
    @discord.ui.select(
        placeholder="3️⃣  Pack type?",
        options=[
            discord.SelectOption(
                label="📦 Daily Pack  (3 cards, common odds)",
                value="daily",
                emoji="📦",
                default=True,
            ),
            discord.SelectOption(
                label="🎁 Weekly Pack (5 cards, better odds)",
                value="weekly",
                emoji="🎁",
            ),
        ],
        row=2,
    )
    async def pack_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.pack_type = select.values[0]
        for opt in self.pack_select.options:
            opt.default = (opt.value == self.pack_type)
        await interaction.response.edit_message(content=self._status(), view=self)

    # ── Row 3: navigation ─────────────────────────────────────────────────────
    @discord.ui.button(label="Next: Set Amount →", style=discord.ButtonStyle.primary, row=3)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.guild_id:
            await interaction.response.edit_message(
                content="⚠️ Please select a server first.", view=self
            )
            return
        await interaction.response.send_modal(MassGiftAmountModal(self))

    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.secondary, row=3)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content=None,
            embed=build_owner_embed(),
            view=OwnerPanelView(self.col_data, None),
        )

    def _status(self) -> str:
        server_str   = f"**{self.guild_name}**" if self.guild_name else "_none selected_"
        audience_str = "Active users (last 30 days)" if self.audience == "active" else "Everyone in server"
        pack_str     = "📦 Daily (3 cards)"          if self.pack_type == "daily"  else "🎁 Weekly (5 cards)"
        return (
            "**📦 Mass Gift — Step 1 of 2**\n\n"
            f"Server ➜ {server_str}\n"
            f"Who    ➜ **{audience_str}**\n"
            f"Pack   ➜ **{pack_str}**\n\n"
            "_Pick all three, then click **Next** to set the amount._"
        )


class MassGiftConfirmView(discord.ui.View):
    """
    Step 2 of 2 — sanity-check count, then execute.
    Uses defer + edit_original_response to handle large member lists safely.
    """

    def __init__(self, step1: MassGiftStep1View):
        super().__init__(timeout=180)
        self.col_data    = step1.col_data
        self.bot_ref     = step1.bot_ref
        self.guild_id    = step1.guild_id
        self.guild_name  = step1.guild_name
        self.audience    = step1.audience
        self.pack_type   = step1.pack_type
        self.amount      = step1.amount
        self._user_count: int | None = None   # filled by Count Users

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _summary(self, footer: str = "") -> str:
        audience_str = "Active users (last 30 days)" if self.audience == "active" else "Everyone in server"
        pack_str     = "Daily (3 cards)"             if self.pack_type == "daily"  else "Weekly (5 cards)"
        lines = [
            "**📦 Mass Gift — Confirm**\n",
            f"Server     ➜ **{self.guild_name}**",
            f"Who        ➜ **{audience_str}**",
            f"Pack type  ➜ **{pack_str}**",
            f"Per user   ➜ **{self.amount}** pack(s)",
        ]
        if self._user_count is not None:
            total = self._user_count * self.amount
            lines.append(
                f"\n✅ **{self._user_count}** eligible user(s) → "
                f"**{total}** total pack(s) will be queued"
            )
        if footer:
            lines.append(f"\n{footer}")
        lines.append("\n_Use **Count Users** first, then **🚀 Execute** when ready._")
        return "\n".join(lines)

    async def _resolve_eligible_ids(self) -> list[int]:
        """
        Fetch guild members and apply the audience filter.
        Active = any of last_pull / last_daily_claim / last_weekly_claim
                 within the past 30 days.
        """
        from datetime import timedelta

        guild = self.bot_ref.get_guild(self.guild_id)
        if not guild:
            return []

        all_ids: set[int] = set()
        async for member in guild.fetch_members(limit=None):
            if not member.bot:
                all_ids.add(member.id)

        if self.audience == "everyone":
            return list(all_ids)

        # Active filter — any bot interaction within the last 30 days
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        active: list[int] = []
        for uid in all_ids:
            udata = self.col_data.get(str(uid))
            if not udata:
                continue
            stamps = [
                udata.get("last_pull"),
                udata.get("last_daily_claim"),
                udata.get("last_weekly_claim"),
            ]
            if any(t and t >= cutoff for t in stamps):
                active.append(uid)
        return active

    # ── Row 0: count + execute ────────────────────────────────────────────────
    @discord.ui.button(label="🔍 Count Users", style=discord.ButtonStyle.secondary, row=0)
    async def count_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Deferred: safe for large servers with many members to fetch."""
        await interaction.response.defer()
        uids = await self._resolve_eligible_ids()
        self._user_count = len(uids)
        await interaction.edit_original_response(content=self._summary())

    @discord.ui.button(label="🚀 Execute", style=discord.ButtonStyle.success, row=0)
    async def execute_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Deferred: batch-writes all gifts with a single save_collections() call."""
        # Disable both action buttons immediately to prevent accidental double-fire
        button.disabled         = True
        self.count_btn.disabled = True
        await interaction.response.defer()

        uids = await self._resolve_eligible_ids()
        if not uids:
            await interaction.edit_original_response(
                content=self._summary("⚠️ No eligible users found — nothing was gifted."),
                view=self,
            )
            return

        # Batch-write: manipulate col_data directly, one save at the end
        from user_collections import get_user, save_collections
        for uid in uids:
            user = get_user(self.col_data, uid)
            user.setdefault("bonus_packs", []).extend([self.pack_type] * self.amount)
        save_collections(self.col_data)

        pack_label = "Daily" if self.pack_type == "daily" else "Weekly"
        total      = len(uids) * self.amount
        await interaction.edit_original_response(
            content=(
                f"✅ **Mass Gift Complete!**\n\n"
                f"🎁 **{total}** × {pack_label} pack(s) queued for "
                f"**{len(uids)}** user(s) in **{self.guild_name}**.\n"
                f"They can claim at any time with `/bonuspack`."
            ),
            view=self,
        )

    # ── Row 1: back ───────────────────────────────────────────────────────────
    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content=None,
            embed=build_owner_embed(),
            view=OwnerPanelView(self.col_data, None),
        )


# =============================================================================
#  DUPLICATES VIEW
# =============================================================================
DUPES_PER_PAGE = 10

class DuplicatesView(discord.ui.View):
    def __init__(self, member, user_data: dict, col_data: dict, all_facts_count: int):
        super().__init__(timeout=120)
        self.member          = member
        self.user_data       = user_data
        self.col_data        = col_data
        self.all_facts_count = all_facts_count
        self.dupes           = get_duplicates(user_data)
        self.page            = 0
        self.total_pages     = max(1, (len(self.dupes) + DUPES_PER_PAGE - 1) // DUPES_PER_PAGE)
        self._refresh_buttons()

    def _refresh_buttons(self):
        self.prev_btn.disabled = self.page == 0
        self.next_btn.disabled = self.page >= self.total_pages - 1

    def build_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=f"♻️ {self.member.display_name}'s Duplicates",
            description=f"**{len(self.dupes)}** card(s) with duplicates",
            color=0xF4A460
        )
        start      = self.page * DUPES_PER_PAGE
        page_dupes = self.dupes[start:start + DUPES_PER_PAGE]
        if page_dupes:
            lines = []
            for i, d in enumerate(page_dupes, start=start + 1):
                lines.append(
                    f"`{i}.` {TIER_EMOJIS[d['tier']]} `{d['filename']}` — "
                    f"**{d['count']}x** ({d['tradeable']} tradeable)"
                )
            embed.add_field(name="Cards", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="Cards", value="_No duplicates yet._", inline=False)

        # Sell nudge — show total dupes and coin value
        from user_collections import get_tradeable_count
        total_tradeable = sum(d["tradeable"] for d in self.dupes)
        if total_tradeable > 0:
            coin_total = sum(
                d["tradeable"] * CATCOIN_SELL_VALUES.get(d["tier"], 0)
                for d in self.dupes
            )
            embed.add_field(
                name="🪙 Sell Your Duplicates",
                value=(
                    f"You have **{total_tradeable}** tradeable duplicate(s) worth up to "
                    f"**{coin_total} CatCoins**.\nUse **Sell Dupes** below or `/sell` to sell any card."
                ),
                inline=False
            )

        embed.set_footer(text=f"Page {self.page + 1} of {self.total_pages}")
        return embed

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary, row=0)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await _throttle_guard(interaction, self, "DuplicatesView"): return
        self.page -= 1
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary, row=0)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await _throttle_guard(interaction, self, "DuplicatesView"): return
        self.page += 1
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)
    async def gift_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.dupes:
            await interaction.response.send_message("You have no duplicates to gift.", ephemeral=True); return
        await interaction.response.edit_message(
            embed=self.build_embed(),
            view=GiftDuplicateView(self.member, self.user_data, self.col_data, self.dupes)
        )

    @discord.ui.button(label="🔄 Trade Up", style=discord.ButtonStyle.success, row=1)
    async def trade_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=self.build_embed(),
            view=TradeUpView(self.member, self.user_data, self.col_data)
        )

    @discord.ui.button(label="🪙 Sell Dupes", style=discord.ButtonStyle.primary, row=1)
    async def sell_dupes_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.dupes:
            await interaction.response.send_message("You have no duplicates to sell.", ephemeral=True); return
        view = SellView(
            self.member, self.user_data, self.col_data,
            econ_mod.load_economy(),
            dupes_only=True,
            back_view=DuplicatesView(self.member, self.user_data, self.col_data, self.all_facts_count)
        )
        await interaction.response.edit_message(embed=view.build_embed(), view=view)

# =============================================================================
#  GIFT A DUPLICATE FLOW
# =============================================================================
class GiftDuplicateView(discord.ui.View):
    def __init__(self, member, user_data: dict, col_data: dict, dupes: list):
        super().__init__(timeout=120)
        self.member    = member
        self.user_data = user_data
        self.col_data  = col_data
        self.dupes     = dupes
        self.selected_card   = None
        self.selected_user_id   = None
        self.selected_user_name = None

        # Build card select options (max 25)
        options = [
            discord.SelectOption(
                label=f"{d['filename']} ({TIER_LABELS[d['tier']]})",
                value=f"{d['filename']}|{d['tier']}",
                description=f"You have {d['count']}x ({d['tradeable']} available to gift)",
                emoji=TIER_EMOJIS[d['tier']]
            )
            for d in dupes[:25]
        ]
        self.card_select.options = options

    @discord.ui.select(placeholder="Select a duplicate card to gift...", row=0)
    async def card_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.selected_card = select.values[0]
        await interaction.response.edit_message(content=self._status(), view=self)

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="Select recipient...", min_values=1, max_values=1, row=1)
    async def user_select(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        self.selected_user_id   = select.values[0].id
        self.selected_user_name = select.values[0].display_name
        await interaction.response.edit_message(content=self._status(), view=self)

    @discord.ui.button(label="🔢 Enter User ID Instead", style=discord.ButtonStyle.secondary, row=2)
    async def id_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(GiftDupeUserIDModal(self))

    @discord.ui.button(label="✅ Confirm Gift", style=discord.ButtonStyle.success, row=2)
    async def confirm_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.selected_card or not self.selected_user_id:
            await interaction.response.edit_message(content="⚠️ Please select both a card and a recipient.", view=self)
            return
        if self.selected_user_id == interaction.user.id:
            await interaction.response.edit_message(content="⚠️ You can't gift a card to yourself.", view=self)
            return

        filename, tier = self.selected_card.split("|")

        # Verify still has a duplicate
        card_info = self.user_data.get("cards", {}).get(filename, {})
        if card_info.get("count", 0) < 2:
            await interaction.response.edit_message(content="⚠️ You no longer have a duplicate of that card.", view=self)
            return

        # Consume one copy
        self.user_data["cards"][filename]["count"] -= 1
        from user_collections import save_collections
        save_collections(self.col_data)

        # Add to recipient's pending gifts as specific card
        from user_collections import add_pending_gift
        add_pending_gift(self.col_data, self.selected_user_id, tier, filename)

        from ui import DuplicatesView
        new_dupes = get_duplicates(self.user_data)
        await interaction.response.edit_message(
            content=f"✅ `{filename}` gifted to **{self.selected_user_name}**! It will deliver on their next `/random`, bypassing their cooldown.",
            view=DuplicatesView(self.member, self.user_data, self.col_data, 0)
        )

    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.secondary, row=3)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from ui import DuplicatesView
        await interaction.response.edit_message(
            content=None,
            view=DuplicatesView(self.member, self.user_data, self.col_data, 0)
        )

    def _status(self):
        card_str = f"`{self.selected_card.split('|')[0]}`" if self.selected_card else "_none_"
        user_str = f"**{self.selected_user_name}**" if self.selected_user_name else "_none_"
        return f"Card: {card_str} | Recipient: {user_str}"

class GiftDupeUserIDModal(discord.ui.Modal, title="Enter Recipient User ID"):
    user_id_input = discord.ui.TextInput(label="User ID", placeholder="e.g. 196106852214243328", min_length=10, max_length=20)

    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        try:
            uid = int(self.user_id_input.value.strip())
        except ValueError:
            await interaction.response.send_message("❌ Invalid user ID.", ephemeral=True); return
        self.parent_view.selected_user_id   = uid
        self.parent_view.selected_user_name = f"User {uid}"
        await interaction.response.edit_message(content=self.parent_view._status(), view=self.parent_view)

# =============================================================================
#  TRADE-UP FLOW
# =============================================================================
# Trade-up rates — costs are in tradeable duplicate cards
# ultra_rare removed as a trade target (legacy, no new prints)
TRADE_RATES = {
    "common":        {"cost": 10, "result": "rare"},
    "rare":          {"cost": 5,  "result": "secret_rare"},
    "secret_rare":   {"cost": 5,  "result": "legendary"},
    "legendary":     {"cost": 3,  "result": "mythic_rare"},
    "mythic_rare":   {"cost": 3,  "result": "secret_mythic"},
    "secret_mythic": {"cost": 3,  "result": "primordial"},
}
TRADE_LABELS = {
    "common":        "10 Common dupes → ✦ Secret Rare pull",
    "rare":          "5 Rare dupes → ✦ Secret Rare pull",
    "secret_rare":   "5 Secret Rare dupes → 🌟 Legendary pull",
    "legendary":     "3 Legendary dupes → 💎 Mythic Rare pull",
    "mythic_rare":   "3 Mythic Rare dupes → 🌈 Secret Mythic pull",
    "secret_mythic": "3 Secret Mythic dupes → 🔥 Primordial pull",
}

class TradeUpView(discord.ui.View):
    def __init__(self, member, user_data: dict, col_data: dict):
        super().__init__(timeout=120)
        self.member        = member
        self.user_data     = user_data
        self.col_data      = col_data
        self.selected_tier = None

        from user_collections import get_tradeable_count
        options = []
        for tier, info in TRADE_RATES.items():
            count = get_tradeable_count(user_data, tier)
            if count >= info["cost"]:
                options.append(discord.SelectOption(
                    label=TRADE_LABELS[tier],
                    value=tier,
                    description=f"You have {count} tradeable {tier.replace('_', ' ')} cards",
                    emoji=TIER_EMOJIS[tier]
                ))

        if options:
            self.trade_select.options = options
        else:
            self.trade_select.options = [discord.SelectOption(label="No trades available", value="none")]
            self.trade_select.disabled = True
            self.confirm_btn.disabled  = True

    @discord.ui.select(placeholder="Select a trade...", row=0)
    async def trade_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.selected_tier = select.values[0] if select.values[0] != "none" else None
        await interaction.response.edit_message(content=self._status(), view=self)

    @discord.ui.button(label="✅ Confirm Trade", style=discord.ButtonStyle.success, row=1)
    async def confirm_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.selected_tier:
            await interaction.response.edit_message(content="⚠️ Please select a trade first.", view=self); return

        rate        = TRADE_RATES[self.selected_tier]
        cost        = rate["cost"]
        result_tier = rate["result"]

        from user_collections import consume_duplicates_for_trade, add_pending_gift, get_tradeable_count
        if get_tradeable_count(self.user_data, self.selected_tier) < cost:
            await interaction.response.edit_message(content="⚠️ You no longer have enough duplicates for this trade.", view=self); return

        success = consume_duplicates_for_trade(self.col_data, self.member.id, self.selected_tier, cost)
        if not success:
            await interaction.response.edit_message(content="❌ Trade failed. Please try again.", view=self); return

        # Reload user_data after consumption
        from user_collections import get_user
        self.user_data = get_user(self.col_data, self.member.id)

        add_pending_gift(self.col_data, self.member.id, result_tier, None)

        await interaction.response.edit_message(
            content=(
                f"✅ Trade complete!\n"
                f"Consumed **{cost}** {self.selected_tier.replace('_', ' ')} duplicate(s).\n"
                f"**{TIER_LABELS[result_tier]}** pull added to your pending gifts — claim it on your next `/random`!"
            ),
            view=DuplicatesView(self.member, self.user_data, self.col_data, 0)
        )

    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content=None,
            view=DuplicatesView(self.member, self.user_data, self.col_data, 0)
        )

    def _status(self):
        if not self.selected_tier:
            return "Select a trade above."
        rate = TRADE_RATES[self.selected_tier]
        return (
            f"Trade: **{TRADE_LABELS[self.selected_tier]}**\n"
            f"This will consume **{rate['cost']}** duplicate {self.selected_tier.replace('_', ' ')} cards "
            f"and add a **{TIER_LABELS[rate['result']]}** pull to your pending gifts."
        )

# =============================================================================
#  MOOSIFUR FACT EMBED
# =============================================================================
def moose_fact_embed(fact: str) -> discord.Embed:
    embed = discord.Embed(
        description=f"🐾  {fact}",
        color=0xFFD700
    )
    embed.set_author(name="CatFrens | ✨ Moosifur Fact ✨")
    embed.set_thumbnail(url="attachment://surprise.png")
    embed.set_footer(text="A fact about Her Royal Fluffiness, Moosifur 👑")
    return embed

def event_fact_embed(fact: str, event: dict) -> discord.Embed:
    """Embed for seasonal/event facts."""
    emoji = event.get("emoji", "🐾")
    name  = event.get("name", "Event")
    try:
        color = int(event.get("color", "F4A460"), 16)
    except ValueError:
        color = 0xF4A460
    embed = discord.Embed(description=f"{emoji}  {fact}", color=color)
    embed.set_author(name=f"CatFrens | {emoji} {name} Fact")
    embed.set_footer(text=f"{name} • Limited time fact!")
    return embed

# =============================================================================
#  BOOSTER PACK UI
# =============================================================================
class BoosterPackView(discord.ui.View):
    """
    Flip through booster pack cards one at a time.
    Cards are pre-rolled and passed in as a list of (photo, tier) tuples.
    All cards are added directly to the user's collection.
    """
    def __init__(self, member, cards: list[tuple], col_data: dict, pack_type: str):
        super().__init__(timeout=180)
        self.member    = member
        self.cards     = cards  # list of (Path, tier)
        self.col_data  = col_data
        self.pack_type = pack_type
        self.index     = 0
        self.claimed   = False
        self._refresh_buttons()

    def _refresh_buttons(self):
        self.prev_btn.disabled = self.index == 0
        self.next_btn.disabled = self.index >= len(self.cards) - 1

    def build_embed(self) -> discord.Embed:
        photo, tier = self.cards[self.index]
        color = TIER_COLORS[tier]
        label = TIER_LABELS[tier]
        emoji = TIER_EMOJIS[tier]
        pack_label = "Daily Pack 📦" if self.pack_type == "daily" else "Weekly Pack 🎁"
        embed = discord.Embed(
            title=f"Card {self.index + 1} of {len(self.cards)}",
            color=color
        )
        embed.set_author(name=f"CatFrens | {pack_label} | {emoji} {label}")
        embed.set_image(url=f"attachment://{photo.name}")
        embed.set_footer(text=f"{label} • {photo.stem} • Added to your collection")
        return embed

    def current_file(self) -> discord.File:
        photo, _ = self.cards[self.index]
        return discord.File(photo)

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary, row=0)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await _throttle_guard(interaction, self, "BoosterPackView"): return
        self.index -= 1
        self._refresh_buttons()
        await interaction.response.edit_message(
            embed=self.build_embed(),
            attachments=[self.current_file()],
            view=self
        )

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary, row=0)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await _throttle_guard(interaction, self, "BoosterPackView"): return
        self.index += 1
        self._refresh_buttons()
        await interaction.response.edit_message(
            embed=self.build_embed(),
            attachments=[self.current_file()],
            view=self
        )

# =============================================================================
#  WISHLIST VIEW
# =============================================================================
class WishlistView(discord.ui.View):
    """Manage your personal wishlist — add/remove cards you want."""
    def __init__(self, member, user_data: dict, col_data: dict, wishlist: list[str]):
        super().__init__(timeout=120)
        self.member    = member
        self.user_data = user_data
        self.col_data  = col_data
        self.wishlist  = list(wishlist)

    def build_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=f"🎯 {self.member.display_name}'s Wishlist",
            color=0xF4A460
        )
        if self.wishlist:
            lines = []
            for fn in self.wishlist:
                info   = self.user_data.get("cards", {}).get(fn, {})
                tier   = info.get("tier", "common")
                owned  = fn in self.user_data.get("cards", {})
                status = "✅" if owned else "🔲"
                lines.append(f"{status} {TIER_EMOJIS.get(tier,'')} `{fn}`")
            embed.description = "\n".join(lines)
        else:
            embed.description = "_Your wishlist is empty. Add cards you want using the button below!_"
        embed.set_footer(text="✅ = already owned  🔲 = still wanted • Others can see this with /wishlist @you")
        return embed

    @discord.ui.button(label="➕ Add Card", style=discord.ButtonStyle.success, row=0)
    async def add_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(WishlistAddModal(self))

    @discord.ui.button(label="➖ Remove Card", style=discord.ButtonStyle.danger, row=0)
    async def remove_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.wishlist:
            await interaction.response.send_message("Your wishlist is already empty.", ephemeral=True); return
        await interaction.response.send_modal(WishlistRemoveModal(self))

    @discord.ui.button(label="🗑️ Clear All", style=discord.ButtonStyle.secondary, row=0)
    async def clear_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.wishlist = []
        self._save()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    def _save(self):
        from user_collections import get_user, save_collections
        user = get_user(self.col_data, self.member.id)
        user["wishlist"] = self.wishlist
        save_collections(self.col_data)

class WishlistAddModal(discord.ui.Modal, title="Add to Wishlist"):
    card_name = discord.ui.TextInput(
        label="Card filename (without extension)",
        placeholder="e.g. IMG_2349",
        min_length=1, max_length=50
    )

    def __init__(self, parent_view: WishlistView):
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        name = self.card_name.value.strip()
        if name in self.parent_view.wishlist:
            await interaction.response.edit_message(
                content=f"⚠️ `{name}` is already on your wishlist.",
                embed=self.parent_view.build_embed(), view=self.parent_view
            ); return
        self.parent_view.wishlist.append(name)
        self.parent_view._save()
        await interaction.response.edit_message(
            content=f"✅ `{name}` added to your wishlist!",
            embed=self.parent_view.build_embed(), view=self.parent_view
        )

class WishlistRemoveModal(discord.ui.Modal, title="Remove from Wishlist"):
    card_name = discord.ui.TextInput(
        label="Card filename to remove",
        placeholder="e.g. IMG_2349",
        min_length=1, max_length=50
    )

    def __init__(self, parent_view: WishlistView):
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        name = self.card_name.value.strip()
        if name not in self.parent_view.wishlist:
            await interaction.response.edit_message(
                content=f"⚠️ `{name}` is not on your wishlist.",
                embed=self.parent_view.build_embed(), view=self.parent_view
            ); return
        self.parent_view.wishlist.remove(name)
        self.parent_view._save()
        await interaction.response.edit_message(
            content=f"✅ `{name}` removed from your wishlist.",
            embed=self.parent_view.build_embed(), view=self.parent_view
        )

# =============================================================================
#  COMPARE VIEW  —  Paginated collection comparison
# =============================================================================
COMPARE_PER_PAGE = 12

class CompareView(discord.ui.View):
    def __init__(self, user_a, user_b, data_a: dict, data_b: dict, total_cards: int):
        super().__init__(timeout=120)
        self.user_a      = user_a
        self.user_b      = user_b
        self.total_cards = total_cards

        cards_a = set(data_a.get("cards", {}).keys())
        cards_b = set(data_b.get("cards", {}).keys())

        def card_list(filenames, source_data):
            result = []
            for fn in sorted(filenames):
                info = source_data.get("cards", {}).get(fn, {})
                tier = info.get("tier", "common")
                result.append((fn, tier))
            return result

        self.pages = [
            {"title": "📊 Overview",               "cards": None},
            {"title": f"✅ You have, {user_b.display_name} doesn't", "cards": card_list(cards_a - cards_b, data_a)},
            {"title": f"❌ {user_b.display_name} has, you don't",    "cards": card_list(cards_b - cards_a, data_b)},
            {"title": "🤝 Both have",              "cards": card_list(cards_a & cards_b, data_a)},
        ]

        # Store for overview
        self.pct_a   = completion_percent(data_a, total_cards)
        self.pct_b   = completion_percent(data_b, total_cards)
        self.count_a = len(cards_a)
        self.count_b = len(cards_b)
        self.shared  = len(cards_a & cards_b)
        self.only_a  = len(cards_a - cards_b)
        self.only_b  = len(cards_b - cards_a)

        self.page     = 0
        self.subpage  = 0
        self._refresh()

    def _refresh(self):
        self.prev_page_btn.disabled = self.page == 0
        self.next_page_btn.disabled = self.page >= len(self.pages) - 1
        cards = self.pages[self.page]["cards"]
        if cards:
            total_sub = max(1, (len(cards) + COMPARE_PER_PAGE - 1) // COMPARE_PER_PAGE)
            self.prev_sub_btn.disabled = self.subpage == 0
            self.next_sub_btn.disabled = self.subpage >= total_sub - 1
            self.prev_sub_btn.label   = "◀"
            self.next_sub_btn.label   = "▶"
        else:
            self.prev_sub_btn.disabled = True
            self.next_sub_btn.disabled = True

    def build_embed(self) -> discord.Embed:
        page_data = self.pages[self.page]
        title     = page_data["title"]
        cards     = page_data["cards"]
        color     = 0xF4A460

        embed = discord.Embed(
            title=f"🔍 {self.user_a.display_name} vs {self.user_b.display_name}",
            color=color
        )

        if cards is None:
            # Overview page
            embed.add_field(name=f"📈 {self.user_a.display_name}", value=f"{self.pct_a}% complete ({self.count_a}/{self.total_cards})", inline=True)
            embed.add_field(name=f"📈 {self.user_b.display_name}", value=f"{self.pct_b}% complete ({self.count_b}/{self.total_cards})", inline=True)
            embed.add_field(name="\u200b", value="\u200b", inline=True)
            embed.add_field(name="Stats", value=(
                f"✅ Only you have: **{self.only_a}** cards\n"
                f"❌ Only they have: **{self.only_b}** cards\n"
                f"🤝 Both have: **{self.shared}** cards"
            ), inline=False)
            embed.set_footer(text="Page 1 of 4 — use ◀▶ to navigate pages")
        else:
            start     = self.subpage * COMPARE_PER_PAGE
            page_cards = cards[start:start + COMPARE_PER_PAGE]
            total_sub  = max(1, (len(cards) + COMPARE_PER_PAGE - 1) // COMPARE_PER_PAGE)

            if page_cards:
                lines = [f"{TIER_EMOJIS.get(tier,'')} `{fn}`" for fn, tier in page_cards]
                embed.add_field(name=f"{title} ({len(cards)} total)", value="\n".join(lines), inline=False)
            else:
                embed.add_field(name=title, value="_None_", inline=False)

            embed.set_footer(text=f"Page {self.page + 1} of {len(self.pages)} • Cards {start+1}–{min(start+COMPARE_PER_PAGE, len(cards))} of {len(cards)}")

        return embed

    @discord.ui.button(label="⬅ Prev Tab", style=discord.ButtonStyle.primary, row=0)
    async def prev_page_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page    = max(0, self.page - 1)
        self.subpage = 0
        self._refresh()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Next Tab ➡", style=discord.ButtonStyle.primary, row=0)
    async def next_page_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page    = min(len(self.pages) - 1, self.page + 1)
        self.subpage = 0
        self._refresh()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary, row=1)
    async def prev_sub_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.subpage = max(0, self.subpage - 1)
        self._refresh()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary, row=1)
    async def next_sub_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        cards = self.pages[self.page]["cards"]
        if cards:
            total_sub    = max(1, (len(cards) + COMPARE_PER_PAGE - 1) // COMPARE_PER_PAGE)
            self.subpage = min(total_sub - 1, self.subpage + 1)
        self._refresh()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)