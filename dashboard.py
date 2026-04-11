"""
dashboard.py
CatFren Bot — Full-screen terminal dashboard using Rich Live + Layout.
Replaces scrolling print() output with a persistent, updating dashboard.
"""
import time
import threading
from datetime import datetime, timezone
from collections import deque
from pathlib import Path

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, BarColumn, TextColumn
from rich import box

# =============================================================================
#  State — updated by bot events, read by renderer
# =============================================================================

_state = {
    "bot_user":      "...",
    "status":        "STARTING",
    "common_photos": 0,
    "total_cards":   0,
    "guilds":        [],
    "guild_cfg":     {},
    "active_event":  None,
    "uptime_start":  datetime.now(timezone.utc),
    "slash_count":   0,
    "pull_count":    0,
    "fact_count":    0,
}

# Scrolling log buffer — newest at top
_logs: deque = deque(maxlen=20)

# Current batch process state
_batch = {
    "active":    False,
    "label":     "",
    "completed": 0,
    "total":     0,
    "tier":      "",
}

_live: Live | None = None
_lock = threading.Lock()

TIER_COLORS = {
    "common":     "white",
    "rare":       "yellow",
    "ultra_rare": "bright_white",
    "legendary":  "gold1",
}

# =============================================================================
#  Log helpers (called from bot.py / card_processor.py)
# =============================================================================
def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")

def log_info(msg: str):
    _logs.appendleft(f"[dim]{_ts()}[/dim] [cyan]ℹ[/cyan] {msg}")

def log_ok(msg: str):
    _logs.appendleft(f"[dim]{_ts()}[/dim] [green]✔[/green] {msg}")

def log_warn(msg: str):
    _logs.appendleft(f"[dim]{_ts()}[/dim] [yellow]⚠[/yellow] {msg}")

def log_error(msg: str):
    _logs.appendleft(f"[dim]{_ts()}[/dim] [bold red]✘[/bold red] {msg}")

def log_pull(username: str, tier: str, filename: str, is_gift: bool = False, is_dupe: bool = False):
    color    = TIER_COLORS.get(tier, "white")
    label    = tier.replace("_", " ").title()
    tags     = (" [dim](gift)[/dim]" if is_gift else "") + (" [yellow](dupe)[/yellow]" if is_dupe else "")
    _logs.appendleft(f"[dim]{_ts()}[/dim] [{color}]▸ {label}[/{color}]{tags} [dim]{filename}[/dim] → [bold]{username}[/bold]")
    with _lock:
        _state["pull_count"] += 1

def log_fact_drop(guild_name: str, is_moose: bool, event: dict | None, idx: int):
    if is_moose:
        _logs.appendleft(f"[dim]{_ts()}[/dim] [gold1]✨ Moosifur fact[/gold1] → [magenta]{guild_name}[/magenta]")
    elif event:
        emoji = event.get("emoji", "🎉")
        name  = event.get("name", "Event")
        _logs.appendleft(f"[dim]{_ts()}[/dim] {emoji} [yellow]{name} fact[/yellow] → [magenta]{guild_name}[/magenta]")
    else:
        _logs.appendleft(f"[dim]{_ts()}[/dim] 📋 Fact #{idx + 1} → [magenta]{guild_name}[/magenta]")
    with _lock:
        _state["fact_count"] += 1

def log_rate_limit(username: str, user_id: int, cmd: str):
    _logs.appendleft(f"[dim]{_ts()}[/dim] [bold red]⚡ RATE LIMIT[/bold red] [bold]{username}[/bold] [dim]({user_id})[/dim] — [yellow]{cmd}[/yellow]")

def log_sync(count: int):
    log_ok(f"Synced [bold cyan]{count}[/bold cyan] slash command(s) globally")
    with _lock:
        _state["slash_count"] = count

def log_sync_error(e: Exception):
    log_error(f"Slash sync failed: {e}")

# =============================================================================
#  Batch process (card grab)
# =============================================================================
def batch_start(label: str, total: int, tier: str):
    with _lock:
        _batch.update({"active": True, "label": label, "completed": 0, "total": total, "tier": tier})

def batch_update(completed: int, msg: str = ""):
    with _lock:
        _batch["completed"] = completed
    if msg:
        color = TIER_COLORS.get(_batch["tier"], "white")
        _logs.appendleft(f"[dim]{_ts()}[/dim] [{color}]✔[/{color}] {msg}")

def batch_end(saved: int, skipped: int, tier: str):
    color = TIER_COLORS.get(tier, "white")
    label = tier.replace("_", " ").title()
    _logs.appendleft(
        f"[dim]{_ts()}[/dim] [{color}]■ {label} grab complete[/{color}] — "
        f"[green]{saved} saved[/green]  [{'red' if skipped else 'dim'}]{skipped} skipped[/{'red' if skipped else 'dim'}]"
    )
    with _lock:
        _batch["active"] = False

def print_card_result(filename: str, tier: str, success: bool, msg: str = ""):
    color = TIER_COLORS.get(tier, "white")
    label = tier.replace("_", " ").title()
    if success:
        _logs.appendleft(f"[dim]{_ts()}[/dim] [{color}]✔ {label}[/{color}] [dim]{filename}[/dim]")
    else:
        log_error(f"{filename} — {msg}")

# =============================================================================
#  Startup (called before Live starts)
# =============================================================================
def print_startup(bot_user, common_count: int, total_count: int, guild_count: int, active_event: dict | None = None):
    with _lock:
        _state["bot_user"]      = str(bot_user)
        _state["status"]        = "ONLINE"
        _state["common_photos"] = common_count
        _state["total_cards"]   = total_count
        _state["active_event"]  = active_event
    log_info(f"Logged in as [bold magenta]{bot_user}[/bold magenta]")
    log_info(f"📸 Common photos: [bold]{common_count}[/bold] | Total cards: [bold]{total_count}[/bold]")
    if active_event:
        emoji = active_event.get("emoji", "🎉")
        name  = active_event.get("name", "Event")
        log_info(f"{emoji} Active Event: [bold yellow]{name}[/bold yellow]")

def print_sync(count: int, guild_ids: list):
    log_sync(count)

def print_sync_error(e: Exception):
    log_sync_error(e)

def print_server_table(guilds, guild_cfg: dict):
    with _lock:
        _state["guilds"]   = list(guilds)
        _state["guild_cfg"] = guild_cfg
    log_info(f"🌐 Connected to [bold cyan]{len(guilds)}[/bold cyan] server(s)")

# =============================================================================
#  Layout renderer
# =============================================================================
def _uptime() -> str:
    delta = datetime.now(timezone.utc) - _state["uptime_start"]
    h, rem = divmod(int(delta.total_seconds()), 3600)
    m, s   = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

def _build_layout() -> Layout:
    layout = Layout()
    layout.split(
        Layout(name="header",  size=3),
        Layout(name="middle",  size=14),
        Layout(name="logs"),
    )
    layout["middle"].split_row(
        Layout(name="status",  ratio=60),
        Layout(name="process", ratio=40),
    )

    # ── Header ──────────────────────────────────────────────────────────────
    status_color = "bold green" if _state["status"] == "ONLINE" else "bold yellow"
    event        = _state.get("active_event")
    event_tag    = ""
    if event:
        emoji    = event.get("emoji", "")
        name     = event.get("name", "")
        event_tag = f"  {emoji} {name}"

    header_text = (
        f"[bold cyan]CATFREN BOT[/bold cyan] [dim][v2.4.1][/dim] "
        f"[{status_color}]\\[{_state['status']}][/{status_color}]"
        f"  🐾"
        f"  [dim]uptime: {_uptime()}[/dim]"
        + (f"  {event.get('emoji','')} [yellow]{event.get('name','')}[/yellow]" if event else "")
        + f"  [dim]pulls: {_state['pull_count']}  facts: {_state['fact_count']}  cmds: {_state['slash_count']}[/dim]"
    )
    layout["header"].update(Panel(header_text, title="[dim]Hammond Digital Studios • CatFren Bot Dashboard[/dim]", border_style="cyan", padding=(0, 1)))

    # ── Status table ─────────────────────────────────────────────────────────
    table = Table(title="BOT STATUS OVERVIEW", title_justify="left", expand=True, box=box.SIMPLE_HEAVY, border_style="dim")
    table.add_column("Server",    style="magenta", no_wrap=True)
    table.add_column("Members",   justify="right", style="green")
    table.add_column("Fact Ch.",  justify="center")
    table.add_column("MOTD Ch.",  justify="center")
    table.add_column("Facts",     justify="right", style="yellow")

    guilds   = _state["guilds"]
    cfg_data = _state["guild_cfg"]
    for g in sorted(guilds, key=lambda x: x.name.lower()):
        cfg      = cfg_data.get(str(g.id), {})
        fact_chs = len(cfg.get("fact_channels", []))
        motd_chs = len(cfg.get("motd_channels", []))
        delivered = len(cfg.get("fact_used", []))
        table.add_row(g.name, str(g.member_count), str(fact_chs), str(motd_chs), str(delivered))

    if not guilds:
        table.add_row("[dim]No servers yet[/dim]", "", "", "", "")

    # Module status rows
    table.add_section()
    table.add_row("[dim]Module[/dim]", "[dim]Status[/dim]", "", "", "[dim]Ping[/dim]")
    table.add_row("Discord API",   "[green]Connected[/green]", "", "", "[dim]—[/dim]")
    table.add_row("Card Database", "[green]Active[/green]",    "", "", "[dim]—[/dim]")
    table.add_row("Image Engine",  f"[{'green' if _batch['active'] else 'dim'}]{'Processing' if _batch['active'] else 'Idle'}[/{'green' if _batch['active'] else 'dim'}]", "", "", "[dim]—[/dim]")

    layout["status"].update(Panel(table, border_style="dim", padding=(0, 0)))

    # ── Batch process panel ──────────────────────────────────────────────────
    if _batch["active"] and _batch["total"] > 0:
        pct      = _batch["completed"] / _batch["total"]
        bar_len  = 20
        filled   = int(bar_len * pct)
        bar      = "█" * filled + "░" * (bar_len - filled)
        color    = TIER_COLORS.get(_batch["tier"], "white")
        tier_lbl = _batch["tier"].replace("_", " ").title()
        process_content = (
            f"[bold]BATCH PROCESS:[/bold]\n"
            f"[{color}]{tier_lbl} tier[/{color}]\n\n"
            f"[bold]{int(pct*100)}% Complete[/bold]\n\n"
            f"[{color}][{bar}][/{color}]\n\n"
            f"[dim]{_batch['completed']} of {_batch['total']} cards[/dim]"
        )
    else:
        photos = _state["total_cards"]
        common = _state["common_photos"]
        process_content = (
            f"[bold]LIBRARY[/bold]\n\n"
            f"[dim]Total cards:[/dim] [bold white]{photos}[/bold white]\n"
            f"[dim]Common photos:[/dim] [bold white]{common}[/bold white]\n\n"
            f"[dim]Image Engine:[/dim] [dim green]Idle[/dim green]"
        )
    layout["process"].update(Panel(process_content, title="BATCH PROCESS", border_style="magenta", padding=(1, 1)))

    # ── Log panel ────────────────────────────────────────────────────────────
    log_lines = list(_logs)
    log_text  = "\n".join(log_lines) if log_lines else "[dim]No events yet...[/dim]"
    layout["logs"].update(Panel(log_text, title="REAL-TIME LOGS", title_align="left", border_style="white", expand=True))

    return layout

# =============================================================================
#  Live dashboard runner — call start() once, runs in background thread
# =============================================================================
_live_thread = None

def _run_live():
    global _live
    console = Console(force_terminal=True, color_system="truecolor")
    with Live(
        _build_layout(),
        refresh_per_second=4,
        screen=True,
        console=console,
        transient=False,
        vertical_overflow="visible",
    ) as live:
        _live = live
        while True:
            live.update(_build_layout(), refresh=True)
            time.sleep(0.25)

def start():
    """Start the live dashboard in a background thread. Call once at bot startup."""
    global _live_thread
    _live_thread = threading.Thread(target=_run_live, daemon=True)
    _live_thread.start()