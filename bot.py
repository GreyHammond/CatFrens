import discord
import json
from discord.ext import commands, tasks
from discord import app_commands
import random
import re
import aiohttp
from pathlib import Path
from datetime import datetime, timezone

from config import (
    TOKEN, PREFIX, OWNER_ID, IMAGE_EXTS,
    MOOSE_MESSAGES, TIER_LABELS, TIER_EMOJIS, TIER_COLORS,
    DEFAULT_PULL_COOLDOWN_MINUTES, TRUSTED_USERS, GRABBABLE_TIERS,
    CATCOIN_SELL_VALUES,
)
import facts as facts_mod
import guild_settings as gs_mod
import user_collections as col_mod
from user_collections import add_pending_gift, pop_pending_gift, has_pending_gift, pending_gift_count, get_duplicates, can_claim_daily, can_claim_weekly, record_daily_claim, record_weekly_claim, add_bonus_pack, pop_bonus_pack, bonus_pack_count
from photos import (
    list_common_photos, list_all_photos, total_card_count,
    find_photo_in_tier, pick_photo_with_fallback, get_dir
)
from pull import determine_tier
import dashboard as dash
import economy as econ_mod
from ui import fact_embed, pull_embed, info_embed, profile_embed, CollectionView, DuplicatesView, moose_fact_embed, BoosterPackView, event_fact_embed, WishlistView, command_rate_guard

# =============================================================================
#  INIT
# =============================================================================
ALL_FACTS     = facts_mod.load_facts()
guild_cfg     = gs_mod.load_guild_settings()
col_data      = col_mod.load_collections()
econ_data     = econ_mod.load_economy()

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.members = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# =============================================================================
#  GUARDS
# =============================================================================
def _check_allowed(guild_id, channel_id, member):
    if member.id == OWNER_ID:
        return True, ""
    cfg = gs_mod.get_guild_cfg(guild_cfg, guild_id)
    if channel_id in cfg["excluded_channels"]:
        return False, "Commands are disabled in this channel."
    if cfg["command_channels"] and channel_id not in cfg["command_channels"]:
        ch = ", ".join(f"<#{c}>" for c in cfg["command_channels"])
        return False, f"Commands are only accepted in: {ch}"
    member_roles = {r.id for r in member.roles}
    if any(r in member_roles for r in cfg["excluded_roles"]):
        return False, "Your role is not permitted to use this bot."
    if cfg["allowed_roles"] and not any(r in member_roles for r in cfg["allowed_roles"]):
        roles = ", ".join(f"<@&{r}>" for r in cfg["allowed_roles"])
        return False, f"Only these roles can use this bot: {roles}"
    return True, ""

async def guard(interaction: discord.Interaction) -> bool:
    if interaction.user.id == OWNER_ID:
        return True
    if not interaction.guild:
        return True
    ok, reason = _check_allowed(interaction.guild_id, interaction.channel_id, interaction.user)
    if not ok:
        await interaction.response.send_message(f"🚫 {reason}", ephemeral=True)
    return ok

async def prefix_guard(ctx: commands.Context) -> bool:
    if ctx.author.id == OWNER_ID:
        return True
    if not ctx.guild:
        return True
    ok, reason = _check_allowed(ctx.guild.id, ctx.channel.id, ctx.author)
    if not ok:
        await ctx.send(f"🚫 {reason}")
    return ok

# =============================================================================
#  FACT SEND HELPER
# =============================================================================
async def _send_fact(channel, fact: str, idx: int, is_moose: bool, event: dict | None, send_fn=None, respond_fn=None):
    """
    Unified fact sender. Handles moose facts, event facts, and normal facts.
    send_fn: channel.send equivalent (for prefix commands and scheduled)
    respond_fn: interaction.response.send_message (for slash commands)
    If neither provided, uses channel.send.
    """
    from ui import moose_fact_embed, event_fact_embed
    surprise = Path("surprise.png")

    if is_moose:
        embed = moose_fact_embed(fact)
        file  = discord.File(surprise) if surprise.exists() else None
    elif event and idx == -1:
        embed = event_fact_embed(fact, event)
        file  = None
    else:
        embed = fact_embed(fact, idx, label="Scheduled Drop" if not send_fn and not respond_fn else "On Demand")
        file  = None

    kwargs = {"embed": embed}
    if file:
        kwargs["file"] = file

    if respond_fn:
        await respond_fn(**kwargs)
    elif send_fn:
        await send_fn(**kwargs)
    else:
        await channel.send(**kwargs)

# =============================================================================
#  SCHEDULED FACT TASK
# =============================================================================
@tasks.loop(minutes=1)
async def scheduled_fact_loop():
    now = datetime.now(timezone.utc)
    for guild_id_str, cfg in guild_cfg.items():
        if not cfg.get("fact_channels"):
            continue
        interval = cfg.get("fact_interval_hours", 12)
        last_str = cfg.get("last_fact_post")
        if last_str:
            elapsed = (now - datetime.fromisoformat(last_str)).total_seconds() / 3600
            if elapsed < interval:
                continue
        idx, fact, is_moose, event = facts_mod.next_fact_for_guild(guild_cfg, int(guild_id_str), ALL_FACTS, lambda: gs_mod.save_guild_settings(guild_cfg))
        for ch_id in cfg["fact_channels"]:
            ch = bot.get_channel(ch_id)
            if ch:
                try:
                    await _send_fact(ch, fact, idx, is_moose, event)
                except discord.Forbidden:
                    print(f"[CatFrens] No permission in channel {ch_id}")
        cfg["last_fact_post"] = now.isoformat()
        gs_mod.save_guild_settings(guild_cfg)

@scheduled_fact_loop.before_loop
async def before_loop():
    await bot.wait_until_ready()

# =============================================================================
#  SETUP COMMAND  (single slash, opens interactive menu)
# =============================================================================
@bot.tree.command(name="setup-catfren", description="Admin: configure CatFrens for this server.")
async def slash_setup(interaction: discord.Interaction):
    from ui import SetupMenuView, build_config_embed
    if not is_admin(interaction):
        await interaction.response.send_message("🚫 Admin only.", ephemeral=True)
        return
    view  = SetupMenuView(guild_cfg, interaction.guild_id)
    embed = build_config_embed(guild_cfg, interaction.guild_id)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

def is_admin(interaction: discord.Interaction) -> bool:
    if interaction.user.id == OWNER_ID:
        return True
    if not interaction.guild:
        return False
    m = interaction.guild.get_member(interaction.user.id)
    return m is not None and m.guild_permissions.administrator


# =============================================================================
#  !catfact / /catfact
# =============================================================================
@bot.command(name="catfact", aliases=["cf"])
async def prefix_catfact(ctx: commands.Context):
    if not await prefix_guard(ctx): return
    if await command_rate_guard(ctx, "catfact"): return
    guild_id = ctx.guild.id if ctx.guild else 0
    idx, fact, is_moose, event = facts_mod.next_fact_for_guild(guild_cfg, guild_id, ALL_FACTS, lambda: gs_mod.save_guild_settings(guild_cfg))
    await _send_fact(ctx.channel, fact, idx, is_moose, event, send_fn=ctx.send)

@bot.tree.command(name="catfact", description="Get a cat fact from CatFrens!")
async def slash_catfact(interaction: discord.Interaction):
    if not await guard(interaction): return
    guild_id = interaction.guild_id or 0
    idx, fact, is_moose, event = facts_mod.next_fact_for_guild(guild_cfg, guild_id, ALL_FACTS, lambda: gs_mod.save_guild_settings(guild_cfg))
    await _send_fact(interaction.channel, fact, idx, is_moose, event, respond_fn=interaction.response.send_message)

# =============================================================================
#  !random / /random  —  Pull a Moose card
# =============================================================================
async def _do_pull(user_id: int, channel_id: int, guild_id: int, member_roles: set) -> tuple:
    """
    Core pull logic. Returns (photo, actual_tier, message, error_str, is_gift).
    Pending gifted pulls are consumed first before a normal hash roll.
    Gifts bypass cooldown and do not update last_pull.
    """
    cfg  = gs_mod.get_guild_cfg(guild_cfg, guild_id)
    user = col_mod.get_user(col_data, user_id)

    # Check for pending gift first — gifts bypass cooldown entirely
    gift = pop_pending_gift(col_data, user_id)

    if not gift:
        # No gift — enforce cooldown for normal pulls
        cooldown = col_mod.get_cooldown_minutes(cfg, member_roles)
        ready, remaining = col_mod.check_cooldown(user, cooldown)
        if not ready:
            mins, secs = divmod(remaining, 60)
            return None, None, None, f"You're on cooldown! Try again in **{mins}m {secs}s**.", False

    if gift:
        tier     = gift["tier"]
        filename = gift.get("filename")  # specific card or None for random

        if filename:
            # Deliver exact card
            photo = find_photo_in_tier(filename, tier)
            if photo is None:
                # File missing from disk — put gift back
                add_pending_gift(col_data, user_id, tier, filename)
                return None, None, None, f"⚠️ Your gifted card `{filename}` couldn't be found on disk. Contact the Moose Overlord!", False
            actual_tier = tier
        else:
            # Random from tier with fallback
            photo, actual_tier = pick_photo_with_fallback(tier)
            if actual_tier != tier:
                add_pending_gift(col_data, user_id, tier, None)
                return None, None, None, f"⚠️ Your gifted **{TIER_LABELS[tier]}** pull is waiting but that folder has no photos yet. Ask the Moose Overlord to add some!", False

        if photo is None:
            return None, None, None, "No photos found in any folder yet!", False

        # Gift claim — does NOT touch last_pull or cooldown
        col_mod.record_gift_claim(col_data, user_id, photo.stem, actual_tier)
        message = random.choice(MOOSE_MESSAGES[actual_tier])

        # Check if it's a duplicate
        card_count = col_mod.get_user(col_data, user_id)["cards"].get(photo.stem, {}).get("count", 1)
        is_dupe    = card_count > 1
        return photo, actual_tier, message, None, True, is_dupe, card_count

    else:
        pity = user.get("pity_counter", 0)
        tier = determine_tier(user_id, channel_id, pity)
        photo, actual_tier = pick_photo_with_fallback(tier)
        if photo is None:
            return None, None, None, "No photos found in any folder yet!", False

        # Normal pull — updates last_pull
        col_mod.record_normal_pull(col_data, user_id, photo.stem, actual_tier)
        message = random.choice(MOOSE_MESSAGES[actual_tier])

        # Check if it's a duplicate
        card_count = col_mod.get_user(col_data, user_id)["cards"].get(photo.stem, {}).get("count", 1)
        is_dupe    = card_count > 1
        return photo, actual_tier, message, None, False, is_dupe, card_count

async def _get_card_image(user_id: int, photo, tier: str) -> tuple:
    """
    Image serving helper. Priority:
    1. Valid CDN URL cached in user collection (< 24hr)
    2. GitHub raw URL (permanent, no upload needed)
    3. Fallback: upload discord.File and cache the returned CDN URL

    Returns (url_or_none, file_or_none, use_url)
    use_url=True  → set embed image to url, no file kwarg needed
    use_url=False → use file= kwarg (fallback upload path)
    """
    from photos import github_url_for
    user_data = col_mod.get_user(col_data, user_id)

    # 1. CDN cache hit
    cdn = col_mod.get_cached_image_url(user_data, photo.stem)
    if cdn:
        return cdn, None, True

    # 2. GitHub raw URL — try head request to confirm file exists
    gh_url = github_url_for(tier, photo.name)
    return gh_url, None, True

@bot.command(name="random")
async def prefix_random(ctx: commands.Context):
    if not await prefix_guard(ctx): return
    if await command_rate_guard(ctx, "random"): return
    roles = {r.id for r in ctx.author.roles} if ctx.guild else set()
    result = await _do_pull(ctx.author.id, ctx.channel.id, ctx.guild.id if ctx.guild else 0, roles)
    photo, tier, message, error = result[0], result[1], result[2], result[3]
    is_gift = result[4] if len(result) > 4 else False
    is_dupe = result[5] if len(result) > 5 else False
    card_count = result[6] if len(result) > 6 else 1
    if error:
        await ctx.send(f"🚫 {error}"); return
    user_data    = col_mod.get_user(col_data, ctx.author.id)
    has_daily,  _ = col_mod.can_claim_daily(user_data)
    has_weekly, _ = col_mod.can_claim_weekly(user_data)
    has_bonus     = bonus_pack_count(col_data, ctx.author.id) > 0
    img_url, img_file, use_url = await _get_card_image(ctx.author.id, photo, tier)
    emb = pull_embed(photo, tier, message, is_gift=is_gift, is_dupe=is_dupe, dupe_count=card_count, has_daily=has_daily, has_weekly=has_weekly, has_bonus=has_bonus, image_url=img_url if use_url else None)
    if use_url:
        await ctx.send(embed=emb)
    else:
        await ctx.send(embed=emb, file=discord.File(photo))

@bot.tree.command(name="random", description="Pull a random Moose card!")
async def slash_random(interaction: discord.Interaction):
    if not await guard(interaction): return
    roles = {r.id for r in interaction.user.roles} if interaction.guild else set()
    result = await _do_pull(
        interaction.user.id, interaction.channel_id,
        interaction.guild_id or 0, roles
    )
    photo, tier, message, error = result[0], result[1], result[2], result[3]
    is_gift = result[4] if len(result) > 4 else False
    is_dupe = result[5] if len(result) > 5 else False
    card_count = result[6] if len(result) > 6 else 1
    if error:
        await interaction.response.send_message(f"🚫 {error}", ephemeral=True); return
    user_data    = col_mod.get_user(col_data, interaction.user.id)
    has_daily,  _ = col_mod.can_claim_daily(user_data)
    has_weekly, _ = col_mod.can_claim_weekly(user_data)
    has_bonus     = bonus_pack_count(col_data, interaction.user.id) > 0
    img_url, img_file, use_url = await _get_card_image(interaction.user.id, photo, tier)
    emb = pull_embed(photo, tier, message, is_gift=is_gift, is_dupe=is_dupe, dupe_count=card_count, has_daily=has_daily, has_weekly=has_weekly, has_bonus=has_bonus, image_url=img_url if use_url else None)
    if use_url:
        await interaction.response.send_message(embed=emb)
    else:
        await interaction.response.send_message(embed=emb, file=discord.File(photo))

# =============================================================================
#  !foto / /foto  —  Specific photo (common folder only, autocomplete)
# =============================================================================
@bot.command(name="foto")
async def prefix_foto(ctx: commands.Context, *, name: str):
    if not await prefix_guard(ctx): return
    if await command_rate_guard(ctx, "foto"): return
    from photos import find_photo
    photo, tier = find_photo(name)
    if photo is None:
        photos  = list_common_photos()
        listing = "\n".join(f"`{p.stem}`" for p in sorted(photos)[:20]) or "_none yet_"
        await ctx.send(
            f"No photo named **{name}** found.\n\n"
            f"**Available photos** (first 20):\n{listing}\n\n"
            f"Tip: use `/foto` for live autocomplete."
        ); return
    from ui import photo_embed_simple
    await ctx.send(embed=photo_embed_simple(photo, tier), file=discord.File(photo))

async def foto_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    photos = list_common_photos()
    cur    = current.lower()
    return [
        app_commands.Choice(name=p.stem, value=p.stem)
        for p in sorted(photos, key=lambda x: x.stem.lower())
        if cur in p.stem.lower()
    ][:25]

@bot.tree.command(name="foto", description="Post a specific Moose photo by name.")
@app_commands.describe(name="Start typing to search the photo library.")
@app_commands.autocomplete(name=foto_autocomplete)
async def slash_foto(interaction: discord.Interaction, name: str):
    if not await guard(interaction): return
    from photos import find_photo
    photo, tier = find_photo(name)
    if photo is None:
        await interaction.response.send_message(
            f"No photo named **{name}** found. Try `/foto` again and pick from the suggestions.",
            ephemeral=True
        ); return
    from ui import photo_embed_simple
    await interaction.response.send_message(embed=photo_embed_simple(photo, tier), file=discord.File(photo))

# =============================================================================
#  !grab / /grab
# =============================================================================
# Tier targets for grab/grablink — driven by config.GRABBABLE_TIERS (ultra_rare excluded)
VALID_TIERS = GRABBABLE_TIERS

WORK_DIR = Path("work")

async def _grab_from_channel(channel, limit: int, tier: str = "common") -> tuple[list, list]:
    from card_processor import process_card
    WORK_DIR.mkdir(exist_ok=True)
    saved, skipped = [], []
    async for message in channel.history(limit=limit):
        for att in message.attachments:
            ext = Path(att.filename).suffix.lower()
            if ext not in IMAGE_EXTS: continue
            filename  = re.sub(r'[<>:"/\\|?*]', "_", att.filename)
            stem      = Path(filename).stem
            if tier == 'common':
                dest = get_dir(tier) / (stem + '.jpg')
            else:
                dest = get_dir(tier) / 'placeholder.jpg'  # overridden by next_card_path
            if tier == 'common' and dest.exists():
                skipped.append(filename); continue
            if dest.exists():
                skipped.append(filename); continue
            work_file = WORK_DIR / filename
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.get(att.url) as r:
                        r.raise_for_status()
                        work_file.write_bytes(await r.read())
                ok, msg = process_card(work_file, dest, tier)
                if ok:
                    saved.append(dest)
                else:
                    skipped.append(f"{filename} (card error: {msg})")
            except Exception as e:
                skipped.append(f"{filename} (error: {e})")
            finally:
                if work_file.exists():
                    work_file.unlink()
    return saved, skipped

@bot.command(name="grab")
async def prefix_grab(ctx: commands.Context, n: int = 50, tier: str = "common"):
    if ctx.author.id not in TRUSTED_USERS:
        await ctx.send("🚫 You don't have permission to use this command."); return
    if not await prefix_guard(ctx): return
    if n < 1 or n > 500:
        await ctx.send("Please provide a number between 1 and 500."); return
    if tier not in VALID_TIERS:
        await ctx.send(f"Invalid tier. Use: {', '.join(VALID_TIERS)}"); return
    msg = await ctx.send(f"Scanning last {n} messages... saving to **{tier}**")
    saved, skipped = await _grab_from_channel(ctx.channel, n, tier)
    summary = f"Saved **{len(saved)}** image(s) to `{tier}/`"
    if skipped: summary += f" | Skipped **{len(skipped)}** (already saved or error)"
    await msg.edit(content=summary)

@bot.tree.command(name="grab", description="Save images from the last N messages in this channel.")
@app_commands.describe(n="How many messages to scan (default 50, max 500).", tier="Rarity folder to save into (default: common).")
@app_commands.choices(tier=[
    app_commands.Choice(name="Common",        value="common"),
    app_commands.Choice(name="Rare",          value="rare"),
    app_commands.Choice(name="Secret Rare",   value="secret_rare"),
    app_commands.Choice(name="Legendary",     value="legendary"),
    app_commands.Choice(name="Mythic Rare",   value="mythic_rare"),
    app_commands.Choice(name="Secret Mythic", value="secret_mythic"),
    app_commands.Choice(name="Primordial",    value="primordial"),
])
async def slash_grab(interaction: discord.Interaction, n: int = 50, tier: str = "common"):
    if interaction.user.id not in TRUSTED_USERS:
        await interaction.response.send_message("🚫 You don't have permission to use this command.", ephemeral=True); return
    if not await guard(interaction): return
    if n < 1 or n > 500:
        await interaction.response.send_message("Please provide a number between 1 and 500.", ephemeral=True); return
    await interaction.response.defer(thinking=True)
    saved, skipped = await _grab_from_channel(interaction.channel, n, tier)
    summary = f"Saved **{len(saved)}** image(s) to `{tier}/` from the last {n} messages"
    if skipped: summary += f"\nSkipped **{len(skipped)}** (already saved or error)"
    await interaction.followup.send(summary)

# =============================================================================
#  !grablink / /grablink
# =============================================================================
async def _grab_from_link(url: str, tier: str = "common") -> tuple[list, list, str | None]:
    from card_processor import process_card
    WORK_DIR.mkdir(exist_ok=True)
    m = re.search(r"https?://(?:ptb\.|canary\.)?discord(?:app)?\.com/channels/(\d+)/(\d+)/(\d+)", url)
    if not m: return [], [], "That does not look like a valid Discord message link."
    channel = bot.get_channel(int(m.group(2)))
    if not channel: return [], [], "Could not find that channel."
    try:
        message = await channel.fetch_message(int(m.group(3)))
    except discord.NotFound: return [], [], "Message not found."
    except discord.Forbidden: return [], [], "No permission to read that channel."
    if not message.attachments: return [], [], "That message has no attachments."
    saved, skipped = [], []
    for att in message.attachments:
        ext = Path(att.filename).suffix.lower()
        if ext not in IMAGE_EXTS: continue
        filename  = re.sub(r'[<>:"/\\|?*]', "_", att.filename)
        stem      = Path(filename).stem
        if tier == 'common':
            dest = get_dir(tier) / (stem + '.jpg')
        else:
            dest = get_dir(tier) / 'placeholder.jpg'  # overridden by next_card_path
        if tier == 'common' and dest.exists():
            skipped.append(filename); continue
        if dest.exists():
            skipped.append(filename); continue
        work_file = WORK_DIR / filename
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(att.url) as r:
                    r.raise_for_status()
                    work_file.write_bytes(await r.read())
            ok, msg = process_card(work_file, dest, tier)
            if ok:
                saved.append(dest)
            else:
                skipped.append(f"{filename} (card error: {msg})")
        except Exception as e:
            skipped.append(f"{filename} (error: {e})")
        finally:
            if work_file.exists():
                work_file.unlink()
    if not saved and not skipped: return [], [], "No image attachments found."
    return saved, skipped, None

@bot.command(name="grablink")
async def prefix_grablink(ctx: commands.Context, url: str, tier: str = "common"):
    if ctx.author.id not in TRUSTED_USERS:
        await ctx.send("🚫 You don't have permission to use this command."); return
    if not await prefix_guard(ctx): return
    if tier not in VALID_TIERS:
        await ctx.send(f"Invalid tier. Use: {', '.join(VALID_TIERS)}"); return
    saved, skipped, error = await _grab_from_link(url, tier)
    if error:
        await ctx.send(f"Error: {error}"); return
    summary = f"Saved **{len(saved)}** image(s) to `{tier}/`"
    if skipped: summary += f" | Skipped **{len(skipped)}** (already saved)"
    await ctx.send(summary)

@bot.tree.command(name="grablink", description="Save images from a specific Discord message link.")
@app_commands.describe(url="Paste the full Discord message link here.", tier="Rarity folder to save into (default: common).")
@app_commands.choices(tier=[
    app_commands.Choice(name="Common",        value="common"),
    app_commands.Choice(name="Rare",          value="rare"),
    app_commands.Choice(name="Secret Rare",   value="secret_rare"),
    app_commands.Choice(name="Legendary",     value="legendary"),
    app_commands.Choice(name="Mythic Rare",   value="mythic_rare"),
    app_commands.Choice(name="Secret Mythic", value="secret_mythic"),
    app_commands.Choice(name="Primordial",    value="primordial"),
])
async def slash_grablink(interaction: discord.Interaction, url: str, tier: str = "common"):
    if interaction.user.id not in TRUSTED_USERS:
        await interaction.response.send_message("🚫 You don't have permission to use this command.", ephemeral=True); return
    if not await guard(interaction): return
    await interaction.response.defer(thinking=True)
    saved, skipped, error = await _grab_from_link(url, tier)
    if error:
        await interaction.followup.send(f"Error: {error}", ephemeral=True); return
    summary = f"Saved **{len(saved)}** image(s) to `{tier}/`"
    if skipped: summary += f"\nSkipped **{len(skipped)}** (already saved)"
    await interaction.followup.send(summary)


# =============================================================================
#  /collection  —  View a user's card collection
# =============================================================================
@bot.tree.command(name="collection", description="View a user's Moose card collection.")
@app_commands.describe(
    member="Select a user in this server.",
    user_id="Or paste a User ID directly (overrides member selection)."
)
async def slash_collection(interaction: discord.Interaction, member: discord.Member = None, user_id: str = None):
    if user_id:
        try:
            uid = int(user_id.strip())
        except ValueError:
            await interaction.response.send_message("❌ Invalid user ID.", ephemeral=True)
            return
        try:
            target = await bot.fetch_user(uid)
        except discord.NotFound:
            await interaction.response.send_message(f"❌ Could not find a user with ID `{uid}`.", ephemeral=True)
            return
    else:
        target = member or interaction.user

    user_data = col_mod.get_user(col_data, target.id)
    total     = total_card_count()
    view      = CollectionView(target, user_data, total, interaction.user.id)
    await interaction.response.send_message(embed=view.build_embed(), view=view, ephemeral=True)

# =============================================================================
#  /profile  —  View pull stats
# =============================================================================
@bot.tree.command(name="profile", description="View a user's Moose pull profile.")
@app_commands.describe(
    member="Select a user in this server.",
    user_id="Or paste a User ID directly (overrides member selection)."
)
async def slash_profile(interaction: discord.Interaction, member: discord.Member = None, user_id: str = None):
    if user_id:
        try:
            uid = int(user_id.strip())
        except ValueError:
            await interaction.response.send_message("❌ Invalid user ID.", ephemeral=True)
            return
        try:
            target = await bot.fetch_user(uid)
        except discord.NotFound:
            await interaction.response.send_message(f"❌ Could not find a user with ID `{uid}`.", ephemeral=True)
            return
    else:
        target = member or interaction.user

    user_data = col_mod.get_user(col_data, target.id)
    total     = total_card_count()
    await interaction.response.send_message(
        embed=profile_embed(target, user_data, total), ephemeral=True
    )

# =============================================================================
#  !catfrens / /catfrens / /info-catfren / /help-catfren
# =============================================================================
def _info_embed(guild_id: int = 0):
    used  = facts_mod.guild_facts_delivered(guild_cfg, guild_id)
    total = total_card_count()
    return info_embed(used, len(ALL_FACTS), total)

@bot.command(name="catfrens")
async def prefix_catfrens(ctx: commands.Context):
    if await command_rate_guard(ctx, "catfrens"): return
    await ctx.send(embed=_info_embed(ctx.guild.id if ctx.guild else 0))

@bot.tree.command(name="catfrens", description="Show CatFrens commands and stats.")
async def slash_catfrens(interaction: discord.Interaction):
    await interaction.response.send_message(embed=_info_embed(interaction.guild_id or 0))

@bot.tree.command(name="info-catfren", description="Show CatFrens commands and stats.")
async def slash_info(interaction: discord.Interaction):
    await interaction.response.send_message(embed=_info_embed(interaction.guild_id or 0))

@bot.tree.command(name="help-catfren", description="Show CatFrens commands and stats.")
async def slash_help(interaction: discord.Interaction):
    await interaction.response.send_message(embed=_info_embed(interaction.guild_id or 0))

# =============================================================================
#  OWNER PANEL  (Grey only — ephemeral menu)
# =============================================================================
def owner_only(interaction: discord.Interaction) -> bool:
    return interaction.user.id == OWNER_ID

@bot.tree.command(name="owner", description="Owner-only CatFrens control panel.")
async def slash_owner(interaction: discord.Interaction):
    if not owner_only(interaction):
        await interaction.response.send_message("🚫 Owner only.", ephemeral=True)
        return
    from ui import OwnerPanelView, build_owner_embed
    await interaction.response.send_message(
        embed=build_owner_embed(),
        view=OwnerPanelView(col_data, guild_cfg, bot_ref=bot),
        ephemeral=True
    )

@bot.tree.command(name="servers", description="[Owner] List all servers CatFren is in.")
async def slash_servers(interaction: discord.Interaction):
    if not owner_only(interaction):
        await interaction.response.send_message("🚫 Owner only.", ephemeral=True)
        return
    guilds = sorted(bot.guilds, key=lambda g: g.name.lower())
    lines  = []
    for g in guilds:
        cfg          = gs_mod.get_guild_cfg(guild_cfg, g.id)
        fact_chs     = len(cfg.get("fact_channels", []))
        delivered    = facts_mod.guild_facts_delivered(guild_cfg, g.id)
        members      = g.member_count
        lines.append(f"**{g.name}** `{g.id}`\n┗ {members} members • {fact_chs} fact channel(s) • {delivered} facts delivered")
    embed = discord.Embed(
        title=f"🌐 CatFren is in {len(guilds)} server(s)",
        description="\n\n".join(lines) or "_No servers found._",
        color=0xF4A460
    )
    embed.set_footer(text="Only you can see this.")
    await interaction.response.send_message(embed=embed, ephemeral=True)


# =============================================================================
#  /duplicates  —  View duplicate cards
# =============================================================================
@bot.tree.command(name="duplicates", description="View your duplicate Moose cards and trade or gift them.")
async def slash_duplicates(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    user_data = col_mod.get_user(col_data, interaction.user.id)
    total     = total_card_count()
    view      = DuplicatesView(interaction.user, user_data, col_data, total)
    await interaction.followup.send(embed=view.build_embed(), view=view, ephemeral=True)

# =============================================================================
#  -fact  —  Add a Moosifur fact (trusted users only)
# =============================================================================
@bot.command(name="fact")
async def prefix_add_moose_fact(ctx: commands.Context, *, fact: str):
    if ctx.author.id not in TRUSTED_USERS:
        await ctx.send("🚫 You don't have permission to add Moosifur facts."); return
    total = facts_mod.add_moose_fact(fact.strip())
    await ctx.send(f"✅ Moosifur fact added! She now has **{total}** facts in her collection.\n> {fact.strip()}")

# =============================================================================
#  /daily  —  Daily booster pack (3 cards)
# =============================================================================
@bot.tree.command(name="daily", description="Claim your daily booster pack of 3 Moose cards!")
async def slash_daily(interaction: discord.Interaction):
    if not await guard(interaction): return
    user_data = col_mod.get_user(col_data, interaction.user.id)
    can, remaining = col_mod.can_claim_daily(user_data)
    if not can:
        h, rem = divmod(remaining, 3600)
        m      = (rem % 3600) // 60
        await interaction.response.send_message(
            f"⏳ Your daily pack resets at UTC midnight! Come back in **{h}h {m}m**.", ephemeral=True
        ); return

    from config import DAILY_PACK_WEIGHTS
    from pull import roll_booster_tier
    cards = []
    for _ in range(3):
        tier          = roll_booster_tier(DAILY_PACK_WEIGHTS)
        photo, actual = pick_photo_with_fallback(tier)
        if photo:
            cards.append((photo, actual))
            col_mod.record_gift_claim(col_data, interaction.user.id, photo.stem, actual)

    if not cards:
        await interaction.response.send_message("❌ No photos available for your pack yet.", ephemeral=True); return

    col_mod.record_daily_claim(col_data, interaction.user.id)
    streak, rewards = check_and_award_streak(interaction.user.id)

    # Event: double streak milestone rewards if active event
    active_event = facts_mod.get_active_event()
    if active_event and rewards:
        for pack_type, count in rewards:
            for _ in range(count):  # one extra of each
                add_bonus_pack(col_data, interaction.user.id, pack_type)

    # Special day bonus pack
    special_bonus = facts_mod.get_special_day_bonus()
    special_msg   = ""
    if special_bonus:
        add_bonus_pack(col_data, interaction.user.id, special_bonus)
        event_name  = active_event.get("name", "today's event") if active_event else "today"
        event_emoji = active_event.get("emoji", "🎉") if active_event else "🎉"
        special_msg = f"\n{event_emoji} **{event_name} bonus!** A bonus {special_bonus.capitalize()} pack added to your `/bonuspack`!"

    streak_msg = ""
    if rewards:
        reward_str = ", ".join(f"{count}x {pt.capitalize()} pack" for pt, count in rewards)
        event_extra = " (×2 — event active!)" if active_event else ""
        if streak >= 29:
            streak_msg = f"\n🏆 **29-day streak complete!** You conquered the full cycle! Bonus: {reward_str}{event_extra} — streak reset, go again!"
        else:
            streak_msg  = f"\n🔥 **{streak}-day streak!** Bonus: {reward_str}{event_extra} added to your `/bonuspack`!"
    elif streak > 1:
        next_milestone = next((m for m in sorted(STREAK_MILESTONES) if m > streak), None)
        if next_milestone:
            streak_msg = f"\n🔥 **{streak}-day streak!** Next milestone: Day {next_milestone}!"

    from ui import BoosterPackView
    view = BoosterPackView(interaction.user, cards, col_data, "daily")
    await interaction.response.send_message(
        content=f"📦 **Daily MOOSEter Pack!** Flip through your 3 cards — they've been added to your collection!{streak_msg}{special_msg}",
        embed=view.build_embed(),
        file=view.current_file(),
        view=view,
        ephemeral=True
    )

# =============================================================================
#  /weekly  —  Weekly booster pack (5 cards)
# =============================================================================
@bot.tree.command(name="weekly", description="Claim your weekly booster pack of 5 Moose cards!")
async def slash_weekly(interaction: discord.Interaction):
    if not await guard(interaction): return
    user_data = col_mod.get_user(col_data, interaction.user.id)
    can, remaining = col_mod.can_claim_weekly(user_data)
    if not can:
        h, rem = divmod(remaining, 3600)
        m      = (rem % 3600) // 60
        await interaction.response.send_message(
            f"⏳ Your weekly pack resets Monday at UTC midnight! Come back in **{h}h {m}m**.", ephemeral=True
        ); return

    from config import WEEKLY_PACK_WEIGHTS
    from pull import roll_booster_tier
    cards = []
    for _ in range(5):
        tier          = roll_booster_tier(WEEKLY_PACK_WEIGHTS)
        photo, actual = pick_photo_with_fallback(tier)
        if photo:
            cards.append((photo, actual))
            col_mod.record_gift_claim(col_data, interaction.user.id, photo.stem, actual)

    if not cards:
        await interaction.response.send_message("❌ No photos available for your pack yet.", ephemeral=True); return

    col_mod.record_weekly_claim(col_data, interaction.user.id)
    from ui import BoosterPackView
    view = BoosterPackView(interaction.user, cards, col_data, "weekly")
    await interaction.response.send_message(
        content="🎁 **Weekly MOOSEter Pack!** Flip through your 5 cards — they've been added to your collection!",
        embed=view.build_embed(),
        file=view.current_file(),
        view=view,
        ephemeral=True
    )

# =============================================================================
#  /bonuspack  —  Claim a gifted bonus pack
# =============================================================================
@bot.tree.command(name="bonuspack", description="Claim a bonus MOOSEter pack gifted to you!")
async def slash_bonuspack(interaction: discord.Interaction):
    if not await guard(interaction): return
    user_data = col_mod.get_user(col_data, interaction.user.id)
    pack_type = pop_bonus_pack(col_data, interaction.user.id)
    if not pack_type:
        remaining = bonus_pack_count(col_data, interaction.user.id)
        await interaction.response.send_message(
            "🎁 You have no bonus packs waiting. Ask the Moose Overlord nicely!",
            ephemeral=True
        ); return

    from config import DAILY_PACK_WEIGHTS, WEEKLY_PACK_WEIGHTS
    from pull import roll_booster_tier
    from ui import BoosterPackView

    weights   = DAILY_PACK_WEIGHTS if pack_type == "daily" else WEEKLY_PACK_WEIGHTS
    card_count = 3 if pack_type == "daily" else 5
    pack_label = "Daily" if pack_type == "daily" else "Weekly"

    cards = []
    for _ in range(card_count):
        tier          = roll_booster_tier(weights)
        photo, actual = pick_photo_with_fallback(tier)
        if photo:
            cards.append((photo, actual))
            col_mod.record_gift_claim(col_data, interaction.user.id, photo.stem, actual)

    if not cards:
        await interaction.response.send_message("❌ No photos available yet.", ephemeral=True); return

    remaining  = bonus_pack_count(col_data, interaction.user.id)
    extra_msg  = f"\n📦 You have **{remaining}** more bonus pack(s) waiting!" if remaining > 0 else ""
    view = BoosterPackView(interaction.user, cards, col_data, pack_type)
    await interaction.response.send_message(
        content=f"🎁 **Bonus {pack_label} MOOSEter Pack!** Flip through your {card_count} cards — added to your collection!{extra_msg}",
        embed=view.build_embed(),
        file=view.current_file(),
        view=view,
        ephemeral=True
    )

# =============================================================================
#  MOOSE OF THE DAY  (12:00 PM Pacific daily)
# =============================================================================
@tasks.loop(minutes=1)
async def moose_of_the_day_loop():
    now_pt   = facts_mod._pacific_now()
    now_utc  = datetime.now(timezone.utc)

    # Only fire at noon Pacific
    if not (now_pt.hour == 12 and now_pt.minute == 0):
        return

    # Check birthday
    is_bday = facts_mod.is_birthday_today()

    photos      = list_all_photos()
    moose_facts = facts_mod.load_moose_facts()
    if not photos:
        return

    photo = random.choice(photos)
    fact  = random.choice(moose_facts) if moose_facts else None

    for guild_id_str, cfg in guild_cfg.items():
        # Skip if already posted today
        last = cfg.get("last_motd")
        if last:
            last_dt = datetime.fromisoformat(last)
            if (now_utc - last_dt).total_seconds() < 3600 * 23:
                continue
        for ch_id in cfg.get("motd_channels") or cfg.get("fact_channels", []):
            ch = bot.get_channel(ch_id)
            if not ch:
                continue
            try:
                if is_bday:
                    embed = discord.Embed(
                        title="🎂 Happy Birthday, Moosifur! 🎂",
                        description=(
                            "Today is the birthday of Her Royal Fluffiness, Moosifur!\n"
                            "Born September 5, 2013 — a true autumn queen. 👑\n\n"
                            f"*{fact}*" if fact else ""
                        ),
                        color=0xFFD700
                    )
                    embed.set_image(url=f"attachment://{photo.name}")
                    embed.set_footer(text="🎂 Moosifur's Birthday • Give her your best birthday wishes!")
                    await ch.send(embed=embed, file=discord.File(photo))
                    # Gift everyone a bonus pack
                    members_gifted = 0
                    async for member in ch.guild.fetch_members():
                        if not member.bot:
                            add_bonus_pack(col_data, member.id, "weekly")
                            members_gifted += 1
                    await ch.send(f"🎁 Everyone gets a Weekly MOOSEter pack in honor of Moosifur's birthday! Use `/bonuspack` to claim yours! ({members_gifted} members gifted)")
                else:
                    embed = discord.Embed(
                        title="🌅 Moose of the Day",
                        description=f"*{fact}*" if fact else "Good morning from Moosifur!",
                        color=0xF4A460
                    )
                    embed.set_image(url=f"attachment://{photo.name}")
                    embed.set_footer(text="🐾 Daily Moose • Good morning!")
                    await ch.send(embed=embed, file=discord.File(photo))
            except discord.Forbidden:
                print(f"[CatFrens] No permission for MOTD in {ch_id}")
        cfg["last_motd"] = now_utc.isoformat()
        gs_mod.save_guild_settings(guild_cfg)

@moose_of_the_day_loop.before_loop
async def before_motd():
    await bot.wait_until_ready()

# =============================================================================
#  STREAK SYSTEM
#  Prime milestones: 2, 5, 10, 17 consecutive daily claims
#  Prizes: 1 daily, 2 daily, 1 daily + 1 weekly, 2 weekly
# =============================================================================
STREAK_MILESTONES = {
    2:  [("daily",  1)],
    3:  [("daily",  2)],
    5:  [("daily",  2)],
    7:  [("daily",  1), ("weekly", 1)],
    11: [("daily",  2), ("weekly", 1)],
    13: [("daily",  2), ("weekly", 1)],
    17: [("daily",  1), ("weekly", 2)],
    19: [("daily",  1), ("weekly", 2)],
    23: [("daily",  2), ("weekly", 2)],
    29: [("weekly", 3)],  # full cycle complete — resets to 0
}

def check_and_award_streak(user_id: int):
    """Check streak after a daily claim and award bonus packs at milestones.
    Resets to 0 after day 29 (full prime cycle complete)."""
    user = col_mod.get_user(col_data, user_id)
    streak = user.get("daily_streak", 0) + 1
    user["daily_streak"] = streak
    col_mod.save_collections(col_data)

    rewards = STREAK_MILESTONES.get(streak, [])
    for pack_type, count in rewards:
        for _ in range(count):
            add_bonus_pack(col_data, user_id, pack_type)

    # Full cycle complete — reset streak
    if streak >= 29:
        user["daily_streak"] = 0
        col_mod.save_collections(col_data)

    return streak, rewards

def reset_streak(user_id: int):
    user = col_mod.get_user(col_data, user_id)
    user["daily_streak"] = 0
    col_mod.save_collections(col_data)

# =============================================================================
#  /topmoose  —  Leaderboard
# =============================================================================
@bot.tree.command(name="topmoose", description="See the top Moose card collectors!")
@app_commands.choices(sort=[
    app_commands.Choice(name="Completion %",  value="completion"),
    app_commands.Choice(name="Total Cards",   value="cards"),
    app_commands.Choice(name="Rarest Card",   value="rarest"),
])
@app_commands.describe(sort="How to rank the leaderboard (default: completion %)")
async def slash_topmoose(interaction: discord.Interaction, sort: str = "completion"):
    total = total_card_count()
    tier_rank = {"legendary": 0, "ultra_rare": 1, "rare": 2, "common": 3, None: 4}

    entries = []
    for uid_str, user_data in col_data.items():
        if not user_data.get("cards"):
            continue
        unique  = len(user_data["cards"])
        pct     = col_mod.completion_percent(user_data, total)
        best, best_tier = col_mod.rarest_card(user_data)
        entries.append({
            "uid":       int(uid_str),
            "unique":    unique,
            "pct":       pct,
            "best":      best,
            "best_tier": best_tier,
        })

    if sort == "completion":
        entries.sort(key=lambda x: x["pct"], reverse=True)
    elif sort == "cards":
        entries.sort(key=lambda x: x["unique"], reverse=True)
    elif sort == "rarest":
        entries.sort(key=lambda x: tier_rank.get(x["best_tier"], 9))

    embed = discord.Embed(title="🏆 Top Moose Collectors", color=0xFFD700)
    lines = []
    medals = ["🥇", "🥈", "🥉"]
    for i, e in enumerate(entries[:10]):
        try:
            user = await bot.fetch_user(e["uid"])
            name = user.display_name
        except Exception:
            name = f"User {e['uid']}"
        medal    = medals[i] if i < 3 else f"`{i+1}.`"
        rarest   = f"{TIER_EMOJIS.get(e['best_tier'], '')} `{e['best']}`" if e["best"] else "_none_"
        lines.append(f"{medal} **{name}** — {e['pct']}% ({e['unique']}/{total}) • Rarest: {rarest}")

    embed.description = "\n".join(lines) or "_No collectors yet!_"
    embed.set_footer(text=f"Sorted by: {sort.replace('_', ' ').title()}")
    await interaction.response.send_message(embed=embed)

# =============================================================================
#  /compare  —  Compare two collections
# =============================================================================
@bot.tree.command(name="compare", description="Compare your collection with another user's.")
@app_commands.describe(
    member="Select a user to compare with.",
    user_id="Or paste a User ID directly."
)
async def slash_compare(interaction: discord.Interaction, member: discord.Member = None, user_id: str = None):
    if not await guard(interaction): return

    if user_id:
        try:
            uid = int(user_id.strip())
        except ValueError:
            await interaction.response.send_message("❌ Invalid user ID.", ephemeral=True); return
        try:
            target = await bot.fetch_user(uid)
        except discord.NotFound:
            await interaction.response.send_message(f"❌ No user found with ID `{uid}`.", ephemeral=True); return
    else:
        target = member
        if not target:
            await interaction.response.send_message("❌ Please select a user or provide a user ID.", ephemeral=True); return

    if target.id == interaction.user.id:
        await interaction.response.send_message("❌ You can't compare with yourself!", ephemeral=True); return

    my_data    = col_mod.get_user(col_data, interaction.user.id)
    their_data = col_mod.get_user(col_data, target.id)
    total      = total_card_count()

    from ui import CompareView
    view = CompareView(interaction.user, target, my_data, their_data, total)
    await interaction.response.send_message(embed=view.build_embed(), view=view, ephemeral=True)

# =============================================================================
#  WISHLIST SYSTEM
# =============================================================================
def get_wishlist(user_id: int) -> list[str]:
    user = col_mod.get_user(col_data, user_id)
    return user.get("wishlist", [])

def set_wishlist(user_id: int, wishlist: list[str]):
    user = col_mod.get_user(col_data, user_id)
    user["wishlist"] = wishlist
    col_mod.save_collections(col_data)

@bot.tree.command(name="wishlist", description="View or manage your Moose card wishlist.")
@app_commands.describe(
    member="View another user's wishlist (leave blank for your own).",
    user_id="Or paste a User ID to view their wishlist."
)
async def slash_wishlist(interaction: discord.Interaction, member: discord.Member = None, user_id: str = None):
    if not await guard(interaction): return

    # Viewing someone else's wishlist
    if member or user_id:
        if user_id:
            try:
                uid = int(user_id.strip())
                target = await bot.fetch_user(uid)
            except (ValueError, discord.NotFound):
                await interaction.response.send_message("❌ Invalid or unknown user ID.", ephemeral=True); return
        else:
            target = member
        wishlist = get_wishlist(target.id)
        if not wishlist:
            await interaction.response.send_message(
                f"**{target.display_name}** has no cards on their wishlist yet.", ephemeral=True
            ); return
        lines = []
        for fn in wishlist:
            # Find tier from their collection or all photos
            their_data = col_mod.get_user(col_data, target.id)
            info       = their_data.get("cards", {}).get(fn, {})
            tier       = info.get("tier", "common")
            owned      = fn in their_data.get("cards", {})
            status     = "✅" if owned else "🔲"
            lines.append(f"{status} {TIER_EMOJIS.get(tier,'')} `{fn}`")
        embed = discord.Embed(
            title=f"🎯 {target.display_name}'s Wishlist",
            description="\n".join(lines),
            color=0xF4A460
        )
        embed.set_footer(text="✅ = already owned  🔲 = still wanted")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # Managing your own wishlist
    user_data = col_mod.get_user(col_data, interaction.user.id)
    wishlist  = get_wishlist(interaction.user.id)
    from ui import WishlistView
    view  = WishlistView(interaction.user, user_data, col_data, wishlist)
    await interaction.response.send_message(embed=view.build_embed(), view=view, ephemeral=True)

# =============================================================================
#  FACT REACTIONS  —  React 🐾 to save a fact
# =============================================================================
SAVED_FACTS_FILE = "saved_facts.json"

def load_saved_facts() -> dict:
    import os
    if os.path.exists(SAVED_FACTS_FILE):
        with open(SAVED_FACTS_FILE) as f:
            return json.load(f)
    return {}

def save_saved_facts(data: dict):
    with open(SAVED_FACTS_FILE, "w") as f:
        json.dump(data, f, indent=2)

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    # Only track 🐾 reactions
    if str(payload.emoji) != "🐾":
        return
    if payload.user_id == bot.user.id:
        return

    channel = bot.get_channel(payload.channel_id)
    if not channel:
        return
    try:
        message = await channel.fetch_message(payload.message_id)
    except (discord.NotFound, discord.Forbidden):
        return

    # Only save facts from CatFren bot embeds
    if message.author.id != bot.user.id:
        return
    if not message.embeds:
        return

    embed = message.embeds[0]
    fact_text = embed.description
    if not fact_text:
        return

    # Strip the leading emoji prefix if present
    fact_text = fact_text.strip().lstrip("🐾 ").strip()

    saved = load_saved_facts()
    uid   = str(payload.user_id)
    if uid not in saved:
        saved[uid] = []
    if fact_text not in saved[uid]:
        saved[uid].append(fact_text)
        save_saved_facts(saved)

@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    """Remove a saved fact when the 🐾 reaction is removed."""
    if str(payload.emoji) != "🐾":
        return
    if payload.user_id == bot.user.id:
        return

    channel = bot.get_channel(payload.channel_id)
    if not channel:
        return
    try:
        message = await channel.fetch_message(payload.message_id)
    except (discord.NotFound, discord.Forbidden):
        return

    if message.author.id != bot.user.id or not message.embeds:
        return

    embed     = message.embeds[0]
    fact_text = embed.description
    if not fact_text:
        return
    fact_text = fact_text.strip().lstrip("🐾 ").strip()

    saved = load_saved_facts()
    uid   = str(payload.user_id)
    if uid in saved and fact_text in saved[uid]:
        saved[uid].remove(fact_text)
        save_saved_facts(saved)

@bot.tree.command(name="savedfacts", description="View the cat facts you've saved with 🐾 reactions.")
@app_commands.describe(member="View another user's saved facts (leave blank for your own).")
async def slash_savedfacts(interaction: discord.Interaction, member: discord.Member = None):
    if not await guard(interaction): return
    target = member or interaction.user
    saved  = load_saved_facts()
    facts  = saved.get(str(target.id), [])

    if not facts:
        msg = "You haven't saved any facts yet! React with 🐾 on any CatFren fact to save it."
        if member:
            msg = f"**{target.display_name}** hasn't saved any facts yet."
        await interaction.response.send_message(msg, ephemeral=True); return

    # Paginate if many facts
    FACTS_PER_PAGE = 5
    pages = [facts[i:i+FACTS_PER_PAGE] for i in range(0, len(facts), FACTS_PER_PAGE)]
    page  = pages[0]
    lines = [f"`{i+1}.` {f}" for i, f in enumerate(page)]
    embed = discord.Embed(
        title=f"🐾 {target.display_name}'s Saved Facts",
        description="\n\n".join(lines),
        color=0xF4A460
    )
    embed.set_footer(text=f"{len(facts)} saved fact(s) • React 🐾 on any fact to save or unsave it")
    await interaction.response.send_message(embed=embed, ephemeral=True)

# =============================================================================
#  /addseasonfact  —  Add a fact to a seasonal event (Moosifer Only)
# =============================================================================
class SeasonFactModal(discord.ui.Modal, title="Add a Seasonal Fact"):
    fact_text = discord.ui.TextInput(
        label="Fact or message",
        style=discord.TextStyle.paragraph,
        placeholder="Type the fact or message here...",
        min_length=5,
        max_length=500
    )

    def __init__(self, event: dict):
        super().__init__()
        self.event = event

    async def on_submit(self, interaction: discord.Interaction):
        import json, os
        fact_file = self.event["fact_file"]
        facts = []
        if os.path.exists(fact_file):
            with open(fact_file) as f:
                facts = json.load(f)
        facts.append(self.fact_text.value.strip())
        with open(fact_file, "w") as f:
            json.dump(facts, f, indent=2)
        await interaction.response.send_message(
            f"✅ Fact added to **{self.event['name']}**! ({len(facts)} total)\n> {self.fact_text.value.strip()}",
            ephemeral=True
        )

class SeasonSelectView(discord.ui.View):
    def __init__(self, events: list[dict]):
        super().__init__(timeout=60)
        self.events = events
        options = [
            discord.SelectOption(
                label=e["name"],
                value=str(i),
                emoji=e.get("emoji", "🐾"),
                description=f"{e['start']} → {e['end']}"
            )
            for i, e in enumerate(events)
        ]
        self.event_select.options = options

    @discord.ui.select(placeholder="Select an event to add a fact to...", row=0)
    async def event_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        event = self.events[int(select.values[0])]
        await interaction.response.send_modal(SeasonFactModal(event))

@bot.tree.command(name="addseasonfact", description="Add a fact to a seasonal event.")
async def slash_addseasonfact(interaction: discord.Interaction):
    if interaction.user.id not in TRUSTED_USERS:
        await interaction.response.send_message("🚫 Moosifer Only.", ephemeral=True); return
    events = facts_mod.load_events()
    if not events:
        await interaction.response.send_message("❌ No events found in events.json.", ephemeral=True); return
    view = SeasonSelectView(events)
    await interaction.response.send_message(
        "**🌟 Add a Seasonal Fact** — select an event:",
        view=view,
        ephemeral=True
    )

# =============================================================================
#  /streak  —  View current streak and next milestone
# =============================================================================
@bot.tree.command(name="streak", description="Check your current daily claim streak and next milestone.")
async def slash_streak(interaction: discord.Interaction):
    if not await guard(interaction): return
    user_data = col_mod.get_user(col_data, interaction.user.id)
    streak    = user_data.get("daily_streak", 0)
    next_ms   = next((m for m in sorted(STREAK_MILESTONES) if m > streak), None)

    embed = discord.Embed(title="🔥 Your Streak", color=0xF4A460)
    if streak == 0:
        embed.description = "You don't have an active streak. Claim your `/daily` to start one!"
    else:
        embed.description = f"You're on a **{streak}-day streak!**"
        if next_ms:
            rewards = STREAK_MILESTONES[next_ms]
            reward_str = ", ".join(f"{count}x {pt.capitalize()} pack" for pt, count in rewards)
            embed.add_field(name=f"Next milestone — Day {next_ms}", value=reward_str, inline=False)
        else:
            embed.add_field(name="You've hit all milestones!", value="Keep going to reset the cycle on day 29.", inline=False)

    # Show full milestone table
    lines = []
    for day in sorted(STREAK_MILESTONES):
        rewards    = STREAK_MILESTONES[day]
        reward_str = ", ".join(f"{count}x {pt.capitalize()}" for pt, count in rewards)
        marker     = "👉 " if day == next_ms else ("✅ " if day <= streak else "   ")
        lines.append(f"{marker}Day **{day}** — {reward_str}")
    embed.add_field(name="All Milestones", value="\n".join(lines), inline=False)
    embed.set_footer(text="Miss a day and the streak resets. Cycle completes at day 29.")
    await interaction.response.send_message(embed=embed, ephemeral=True)

# =============================================================================
#  /eventinfo  —  Show current seasonal event info
# =============================================================================
@bot.tree.command(name="eventinfo", description="See what seasonal event is currently active.")
async def slash_eventinfo(interaction: discord.Interaction):
    if not await guard(interaction): return
    event = facts_mod.get_active_event()
    if not event:
        await interaction.response.send_message(
            "🗓️ No seasonal event is active right now. Check back later!", ephemeral=True
        ); return

    try:
        color = int(event.get("color", "F4A460"), 16)
    except ValueError:
        color = 0xF4A460

    emoji       = event.get("emoji", "🎉")
    name        = event.get("name", "Event")
    start       = event.get("start", "?")
    end         = event.get("end", "?")
    excl        = event.get("exclusive_date")
    bonus       = event.get("special_day_bonus")
    pull_boost  = event.get("pull_boost", False)
    is_excl     = facts_mod.is_exclusive_date(event)

    embed = discord.Embed(
        title=f"{emoji} {name}",
        color=color
    )
    embed.add_field(name="Window", value=f"{start} → {end}", inline=True)
    if excl:
        embed.add_field(name="Exclusive Date", value=excl, inline=True)
    if pull_boost:
        embed.add_field(name="Pull Boost", value="✅ Active — slightly better odds!", inline=False)
    if excl and bonus:
        embed.add_field(name=f"Bonus on {excl}", value=f"+1 {bonus.capitalize()} pack when you claim `/daily`", inline=False)
    if is_excl:
        embed.add_field(name="🚨 Today is the Exclusive Date!", value="Only event facts will drop today.", inline=False)
    else:
        fact_rate = event.get("fact_rate", 25)
        embed.add_field(name="Fact Rate", value=f"1 in {fact_rate} drops will be an event fact", inline=False)

    embed.set_footer(text="Seasonal events are configured in events.json")
    await interaction.response.send_message(embed=embed)

# =============================================================================
#  /gift  —  Quick gift a duplicate card to another user
# =============================================================================
@bot.tree.command(name="gift", description="Gift a duplicate card to another user.")
@app_commands.describe(
    member="The user to gift to.",
    card="The exact card filename (without extension).",
    user_id="Or paste a User ID instead of selecting a member."
)
async def slash_gift(interaction: discord.Interaction, card: str, member: discord.Member = None, user_id: str = None):
    if not await guard(interaction): return

    # Resolve recipient
    if user_id:
        try:
            uid = int(user_id.strip())
            target = await bot.fetch_user(uid)
        except (ValueError, discord.NotFound):
            await interaction.response.send_message("❌ Invalid or unknown user ID.", ephemeral=True); return
    elif member:
        uid    = member.id
        target = member
    else:
        await interaction.response.send_message("❌ Please select a user or provide a user ID.", ephemeral=True); return

    if uid == interaction.user.id:
        await interaction.response.send_message("❌ You can't gift a card to yourself.", ephemeral=True); return

    # Check sender owns a duplicate
    my_data   = col_mod.get_user(col_data, interaction.user.id)
    card_info = my_data.get("cards", {}).get(card)
    if not card_info:
        await interaction.response.send_message(f"❌ You don't own a card named `{card}`.", ephemeral=True); return
    if card_info.get("count", 1) < 2:
        await interaction.response.send_message(f"❌ You only have 1 copy of `{card}` — you need at least 2 to gift one.", ephemeral=True); return

    tier = card_info.get("tier", "common")

    # Consume one copy
    my_data["cards"][card]["count"] -= 1
    col_mod.save_collections(col_data)

    # Queue as pending gift
    add_pending_gift(col_data, uid, tier, card)

    embed = discord.Embed(
        title="🎁 Card Gifted!",
        description=(
            f"`{card}` ({TIER_LABELS.get(tier, tier)}) has been sent to **{target.display_name}**!\n"
            f"It will deliver on their next `/random`, bypassing their cooldown."
        ),
        color=TIER_COLORS.get(tier, 0xF4A460)
    )
    embed.set_footer(text=f"You have {my_data['cards'][card]['count']} of this card remaining.")
    await interaction.response.send_message(embed=embed)


# =============================================================================
#  /sell  —  Sell cards for CatCoins
# =============================================================================
@bot.tree.command(name="sell", description="Sell your Moose cards for CatCoins.")
async def slash_sell(interaction: discord.Interaction):
    if not await guard(interaction): return
    await interaction.response.defer(ephemeral=True)
    user_data = col_mod.get_user(col_data, interaction.user.id)
    from ui import SellView
    view = SellView(interaction.user, user_data, col_data, econ_data)
    await interaction.followup.send(embed=view.build_embed(), view=view, ephemeral=True)

# =============================================================================
#  /balance  —  Check CatCoin balance
# =============================================================================
@bot.tree.command(name="balance", description="Check your CatCoin balance.")
async def slash_balance(interaction: discord.Interaction):
    if not await guard(interaction): return
    await interaction.response.defer(ephemeral=True)
    data    = econ_mod.load_economy()
    user    = econ_mod.get_user_economy(data, interaction.user.id)
    balance = user["catcoins"]
    earned  = user["lifetime_earned"]
    spent   = user["lifetime_spent"]
    embed   = discord.Embed(
        title="🪙 CatCoin Balance",
        color=0xFFD700
    )
    embed.add_field(name="Current Balance", value=f"**{balance:,} CatCoins**", inline=False)
    embed.add_field(name="Lifetime Earned", value=f"{earned:,}", inline=True)
    embed.add_field(name="Lifetime Spent",  value=f"{spent:,}",  inline=True)
    embed.set_footer(text="Earn CatCoins by selling cards with /sell")
    await interaction.followup.send(embed=embed, ephemeral=True)

# =============================================================================
#  ON READY
# =============================================================================
@bot.event
async def on_ready():
    import ui as ui_mod
    ui_mod.set_bot_ref(bot)
    active_event = facts_mod.get_active_event()
    # Start full-screen dashboard before populating state
    dash.start()
    dash.print_startup(bot.user, len(list_common_photos()), total_card_count(), len(bot.guilds), active_event)
    dash.print_server_table(bot.guilds, guild_cfg)
    synced = await bot.tree.sync()
    force_ids = [1488753938223333520, 1450923847686557698]
    force_synced = []
    force_skipped = []
    for guild_id in force_ids:
        try:
            await bot.tree.sync(guild=discord.Object(id=guild_id))
            force_synced.append(guild_id)
        except discord.Forbidden:
            force_skipped.append(guild_id)
            dash.log_info(
                f"[Sync] Skipped guild {guild_id} — bot not present or lacks access. "
                f"Commands will propagate globally within ~1 hour."
            )
        except Exception as e:
            force_skipped.append(guild_id)
            dash.log_info(f"[Sync] Could not force-sync guild {guild_id}: {e}")
    dash.print_sync(len(synced), force_synced)
    scheduled_fact_loop.start()
    moose_of_the_day_loop.start()
    dash.log_info("Ready. 🐾")

# =============================================================================
#  RUN
# =============================================================================
if __name__ == "__main__":
    bot.run(TOKEN)