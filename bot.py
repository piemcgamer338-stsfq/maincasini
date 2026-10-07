# ============================================================
# bot.py — PART 1 / 10
# ZETHER CASINO — REGENERATED SLASH-COMMAND BOT
# ============================================================

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import inspect
import io
import json
import os
import random
import re
import secrets
import string
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from pathlib import Path
from typing import Optional, Union, get_args, get_origin, get_type_hints

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

import config

# ============================================================
# OWNER CONFIGURATION
# ============================================================
# Canonical bot owner. This is intentionally defined here so the
# owner ID works even if Railway/config.py is missing or stale.
BOT_OWNER_ID = 1519015243710201927
config.OWNER_ID = BOT_OWNER_ID
_existing_admin_ids = list(getattr(config, "ADMIN_USER_IDS", []) or [])
config.ADMIN_USER_IDS = list(dict.fromkeys([*(_existing_admin_ids), BOT_OWNER_ID]))

from database import Database
from PIL import Image, ImageDraw, ImageFont


# ============================================================
# PATHS / CONSTANTS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

BOT_TOKEN = config.TOKEN
DATABASE_URL = config.DATABASE_URL

MIN_BET = Decimal("0.10")
MIN_MINES_BET = Decimal("0.10")
MIN_FROG_BET = Decimal("0.10")
MIN_WITHDRAWAL = Decimal("1.00")
WITHDRAW_LOG_CHANNEL_ID = 1554847422008795268
PROMO_TEMPLATE_PATH = BASE_DIR / "promocode.webp"

COINFLIP_MULTIPLIER = Decimal("1.96")
DICE_MULTIPLIER = Decimal("3.30")

MAX_MINES = 20
MAX_MINES_TILES = 25

GAME_COOLDOWN = max(0, int(getattr(config, "GAME_COOLDOWN_SECONDS", 3)))

RAKEBACK_RATE = Decimal("0.01")

RAIN_DURATIONS = {
    1: 60,
    2: 120,
    5: 300,
    10: 600,
}

RANKS = [
    {"name": "Bronze", "wager": Decimal("5"), "color": 0xCD7F32},
    {"name": "Silver", "wager": Decimal("50"), "color": 0xC0C0C0},
    {"name": "Gold", "wager": Decimal("100"), "color": 0xFFD700},
    {"name": "Platinum", "wager": Decimal("200"), "color": 0xE5E4E2},
    {"name": "Ruby", "wager": Decimal("250"), "color": 0xE0115F},
    {"name": "Emerald", "wager": Decimal("500"), "color": 0x50C878},
    {"name": "Amethyst", "wager": Decimal("1000"), "color": 0x00FFFF},
]

AFFILIATE_TIERS = [
    (1, Decimal("0.0010")),
    (10, Decimal("0.0020")),
    (25, Decimal("0.0035")),
    (100, Decimal("0.0050")),
]

CODE_REQUIREMENTS = {
    1: {
        "name": "$1 Deposit",
        "type": "deposit",
        "amount": Decimal("1"),
    },
    2: {
        "name": "$25 Deposit",
        "type": "deposit",
        "amount": Decimal("25"),
    },
    3: {
        "name": "$10 Wagered",
        "type": "wager",
        "amount": Decimal("10"),
    },
}


# ============================================================
# MONEY HELPERS
# ============================================================

def D(value) -> Decimal:
    if isinstance(value, Decimal):
        return value

    if value is None:
        return Decimal("0")

    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def money(value) -> str:
    amount = D(value).quantize(
        Decimal("0.01"),
        rounding=ROUND_DOWN,
    )
    return f"${amount:,.2f}"


def plain_money(value) -> str:
    amount = D(value).quantize(
        Decimal("0.01"),
        rounding=ROUND_DOWN,
    )
    return f"{amount:,.2f}"


def parse_money(value: str | int | float | Decimal) -> Optional[Decimal]:
    if value is None:
        return None

    if isinstance(value, Decimal):
        amount = value
    else:
        raw = str(value).strip().replace(",", "").replace("$", "")

        if raw.lower() in {"all", "half"}:
            return None

        try:
            amount = Decimal(raw)
        except InvalidOperation:
            return None

    if amount <= 0:
        return None

    return amount.quantize(
        Decimal("0.01"),
        rounding=ROUND_DOWN,
    )


def normalize_amount(value: str) -> Optional[Decimal]:
    raw = str(value).strip().lower()

    if raw.endswith("$"):
        raw = raw[:-1]

    return parse_money(raw)


def amount_or_all(
    raw: str,
    balance: Decimal,
) -> Optional[Decimal]:

    value = str(raw).strip().lower()

    if value in {"all", "max"}:
        return balance

    if value == "half":
        return (
            balance / Decimal("2")
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_DOWN,
        )

    return normalize_amount(value)


def valid_bet(amount: Decimal) -> bool:
    return amount >= MIN_BET


# ============================================================
# EMBEDS
# ============================================================

def base_embed(
    title: Optional[str] = None,
    description: Optional[str] = None,
    color: int = 0xB8BCC2,
) -> discord.Embed:

    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=datetime.now(timezone.utc),
    )

    return embed


def success_embed(
    title: str,
    description: str,
) -> discord.Embed:

    return base_embed(
        title=title,
        description=description,
        color=0x57F287,
    )


def error_embed(
    title: str,
    description: str,
) -> discord.Embed:

    return base_embed(
        title=title,
        description=description,
        color=0xED4245,
    )


def neutral_embed(
    title: str,
    description: str,
) -> discord.Embed:

    return base_embed(
        title=title,
        description=description,
        color=0xB8BCC2,
    )


# ============================================================
# COMPONENTS V2 HELPERS
# ============================================================

def components_v2_available() -> bool:
    return all(
        hasattr(discord.ui, name)
        for name in (
            "LayoutView",
            "Container",
            "TextDisplay",
            "ActionRow",
        )
    )


def make_text_display(
    text: str,
):
    return discord.ui.TextDisplay(text)


def make_container(
    *items,
    accent_color: Optional[int] = None,
):
    kwargs = {}

    if accent_color is not None:
        kwargs["accent_color"] = accent_color

    return discord.ui.Container(
        *items,
        **kwargs,
    )



# ============================================================
# CASINO COMPONENTS V2 GAME UI
# ============================================================

DIVIDER_B64 = """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"""

COINFLIP_HEADS_IMAGE_URL = "https://media4.giphy.com/media/v1.Y2lkPTZjMDliOTUyc3ZlcnlhbW9ldGZ6dnJ6bDZwcHVheXFxbzltb2FlM3ZidDZuZG53aCZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/hMv7XGIvkhDgM7ndUk/giphy.gif"
COINFLIP_TAILS_IMAGE_URL = "https://media0.giphy.com/media/v1.Y2lkPTZjMDliOTUybjF0aGJyOXhzeWdxeWdxeHdhaG53cWNqNTFxcHFseXEwZjNiNHE5NHEyNyZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/fMZXR1uZntQgpzidwj/giphy.gif"

def _divider_file():
    try:
        raw = base64.b64decode(DIVIDER_B64)
        return discord.File(io.BytesIO(raw), filename="casino_divider.png")
    except Exception:
        return None

def _v2_container(title, body, *, accent=0x7C4DFF, buttons=None, image=None, footer=None, thumbnail_url=None):
    items = [discord.ui.TextDisplay(title)]
    if body:
        items.append(discord.ui.TextDisplay(body))
    if image:
        gallery = discord.ui.MediaGallery(discord.MediaGalleryItem(media=image))
        items.append(gallery)
    if footer:
        items.append(discord.ui.TextDisplay(f"-# {footer}"))
    if buttons:
        row = discord.ui.ActionRow(*buttons)
        items.append(row)
    return discord.ui.Container(*items, accent_color=accent)

class CasinoV2View(discord.ui.LayoutView):
    def __init__(self, *, timeout=300):
        super().__init__(timeout=timeout)

class SimpleGameV2View(CasinoV2View):
    def __init__(self, title, body, buttons, *, accent=0x7C4DFF, image=None, footer=None):
        super().__init__()
        self.add_item(_v2_container(title, body, accent=accent, buttons=buttons, image=image, footer=footer))


def _server_logo_url(interaction):
    guild = getattr(interaction, "guild", None)
    icon = getattr(guild, "icon", None) if guild else None
    return icon.url if icon else None


# ============================================================
# CUSTOM COMPONENTS
# ============================================================

class V2LayoutView(discord.ui.LayoutView):

    def __init__(
        self,
        *,
        timeout: Optional[float] = 180,
    ):
        super().__init__(timeout=timeout)


class ButtonView(discord.ui.View):

    def __init__(
        self,
        *,
        timeout: Optional[float] = 180,
    ):
        super().__init__(timeout=timeout)


class WalletView(ButtonView):

    def __init__(
        self,
        bot: "CasinoBot",
        user_id: int,
    ):
        super().__init__(timeout=180)

        self.bot = bot
        self.user_id = user_id

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:

        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This wallet belongs to another user.",
                ephemeral=False,
            )
            return False

        return True

    @discord.ui.button(
        label="Deposit",
        style=discord.ButtonStyle.success,
        custom_id="wallet_deposit",
    )
    async def deposit_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await interaction.response.send_message(
            "Choose a currency Below",
            view=DepositCurrencyView(
                self.bot,
                interaction.user.id,
            ),
            ephemeral=False,
        )


class DepositCurrencyView(ButtonView):

    def __init__(
        self,
        bot: "CasinoBot",
        user_id: int,
    ):
        super().__init__(timeout=180)

        self.bot = bot
        self.user_id = user_id

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:

        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This deposit menu belongs to another user.",
                ephemeral=False,
            )
            return False

        return True

    @discord.ui.button(
        label="SOL",
        style=discord.ButtonStyle.secondary,
        custom_id="deposit_sol",
    )
    async def sol_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await self.bot.send_deposit_dm(
            interaction,
            "SOL",
        )


class MainWalletV2(V2LayoutView):

    def __init__(
        self,
        bot: "CasinoBot",
        user: discord.User | discord.Member,
    ):
        super().__init__(timeout=180)

        self.bot = bot
        self.user_id = user.id

        text = make_text_display(
            "## Wallet\n"
            f"**Balance:** {money(0)}"
        )

        row = discord.ui.ActionRow()

        row.add_item(
            discord.ui.Button(
                label="Deposit",
                style=discord.ButtonStyle.success,
                custom_id=f"wallet_v2_deposit:{user.id}",
            )
        )

        row.add_item(
            discord.ui.Button(
                label="Withdraw",
                style=discord.ButtonStyle.secondary,
                custom_id=f"wallet_v2_withdraw:{user.id}",
            )
        )

        container = make_container(
            text,
            row,
            accent_color=0x00E676,
        )

        self.add_item(container)


class WithdrawCurrencyView(ButtonView):

    def __init__(
        self,
        bot: "CasinoBot",
        user_id: int,
    ):
        super().__init__(timeout=180)

        self.bot = bot
        self.user_id = user_id

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:

        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This withdrawal menu belongs to another user.",
                ephemeral=False,
            )
            return False

        return True

    @discord.ui.button(
        label="LTC",
        style=discord.ButtonStyle.secondary,
        custom_id="withdraw_ltc",
    )
    async def ltc(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await interaction.response.send_modal(
            WithdrawModal(
                self.bot,
                self.user_id,
                "LTC",
            )
        )

    @discord.ui.button(
        label="SOL",
        style=discord.ButtonStyle.secondary,
        custom_id="withdraw_sol",
    )
    async def sol(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await interaction.response.send_modal(
            WithdrawModal(
                self.bot,
                self.user_id,
                "SOL",
            )
        )

    @discord.ui.button(
        label="USDT",
        style=discord.ButtonStyle.secondary,
        custom_id="withdraw_usdt",
    )
    async def usdt(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await interaction.response.send_modal(
            WithdrawModal(
                self.bot,
                self.user_id,
                "USDT",
            )
        )


class WithdrawModal(discord.ui.Modal):

    def __init__(
        self,
        bot: "CasinoBot",
        user_id: int,
        currency: str,
    ):
        super().__init__(
            title=f"Withdraw {currency}",
            timeout=300,
        )

        self.bot = bot
        self.user_id = user_id
        self.currency_name = currency

        self.address = discord.ui.TextInput(
            label=f"{currency} Withdrawal Address",
            placeholder="Enter your wallet address",
            required=True,
            max_length=150,
        )

        self.amount = discord.ui.TextInput(
            label="Amount in USD",
            placeholder="Example: 1.00",
            required=True,
            max_length=30,
        )

        self.add_item(self.address)
        self.add_item(self.amount)

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ):

        await self.bot.handle_withdrawal(
            interaction=interaction,
            user_id=self.user_id,
            currency=self.currency_name,
            address=self.address.value,
            amount_text=self.amount.value,
        )


# ============================================================
# COINFLIP VIEW
# ============================================================

class CoinflipView(ButtonView):

    def __init__(
        self,
        bot: "CasinoBot",
        user_id: int,
        amount: Decimal,
        color: str,
        game_id: int,
        server_hash: str,
        client_seed: str,
        nonce: int,
    ):
        super().__init__(timeout=15)

        self.bot = bot
        self.user_id = user_id
        self.amount = amount
        self.color = color
        self.game_id = game_id
        self.server_hash = server_hash
        self.client_seed = client_seed
        self.nonce = nonce

    async def on_timeout(self):

        for item in self.children:
            item.disabled = True


# ============================================================
# MINES GAME STATE
# ============================================================

class MinesGame:
    def __init__(
        self,
        bot: "CasinoBot",
        user_id: int,
        amount: Decimal,
        mines: int,
        game_id: int,
        server_hash: str,
        server_seed: str,
        client_seed: str,
        nonce: int,
    ):

        self.bot = bot
        self.user_id = user_id
        self.amount = amount
        self.mines = mines
        self.game_id = game_id

        self.server_hash = server_hash
        self.server_seed = server_seed
        self.client_seed = client_seed
        self.nonce = nonce

        # Mines are derived from the committed server seed, not Python's random module.
        positions = list(range(25))
        positions = bot.fair_shuffle(
            positions, server_seed, client_seed, nonce, "mines"
        )
        self.bombs = set(positions[:mines])

        self.opened: set[int] = set()
        self.finished = False

    @property
    def multiplier(self) -> Decimal:

        opened = len(self.opened)

        if opened <= 0:
            return Decimal("1.00")

        value = (
            Decimal("25")
            / Decimal(str(25 - self.mines))
        ) ** opened

        value *= Decimal("0.96")

        return value.quantize(
            Decimal("0.01"),
            rounding=ROUND_DOWN,
        )

    @property
    def payout(self) -> Decimal:
        return (
            self.amount * self.multiplier
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_DOWN,
        )


class MinesView(CasinoV2View):
    """Components V2 Mines board. The board and controls live inside one Container."""

    def __init__(self, game: MinesGame):
        super().__init__(timeout=300)
        self.game = game
        self.result_text = None
        self.rebuild()

    def _buttons(self):
        for child in self.walk_children():
            if isinstance(child, discord.ui.Button):
                yield child

    def rebuild(self):
        self.clear_items()

        if self.result_text:
            title, body, accent = self.result_text
        else:
            title = f"## Mines — {money(self.game.amount)} Bet"
            body = (
                f"> ﹒**{self.game.mines}** mines on a 5×5 board · more mines = bigger multiplier\n"
                f"> ﹒**{len(self.game.opened)}** safe tiles · current **{self.game.multiplier:.2f}×**"
            )
            accent = 0x7C4DFF

        rows = []
        for row_index in range(5):
            row = discord.ui.ActionRow()
            for col_index in range(5):
                index = row_index * 5 + col_index
                button = discord.ui.Button(
                    label="·",
                    style=discord.ButtonStyle.secondary,
                    custom_id=f"mine:{index}",
                    disabled=bool(self.result_text),
                )

                if index in self.game.opened:
                    button.label = " "
                    button.emoji = discord.PartialEmoji(name="diamond", id=1557392170875617362)
                    button.style = discord.ButtonStyle.success
                    button.disabled = True
                elif self.result_text and index in self.game.bombs:
                    button.label = " "
                    button.emoji = discord.PartialEmoji(name="BombBomb", id=1557392249975738448)
                    button.style = discord.ButtonStyle.danger
                    button.disabled = True

                button.callback = self.make_callback(index)
                row.add_item(button)
            rows.append(row)

        cashout = discord.ui.Button(
            label="Cashout",
            style=discord.ButtonStyle.success,
            custom_id=f"mine_cashout:{self.game.game_id}",
            disabled=bool(self.result_text),
            emoji=discord.PartialEmoji(name="money_bag", id=1557393182956847226),
        )
        cashout.callback = self.cashout

        children = [
            discord.ui.TextDisplay(title),
            discord.ui.TextDisplay(body),
            discord.ui.Separator(visible=True),
            discord.ui.MediaGallery(
                discord.MediaGalleryItem(media="attachment://casino_divider.png")
            ),
            *rows,
            discord.ui.ActionRow(cashout),
        ]
        self.add_item(discord.ui.Container(*children, accent_color=accent))

    def set_result(self, title: str, body: str, *, won: bool):
        self.result_text = (
            title,
            body,
            0x57F287 if won else 0xED4245,
        )
        self.rebuild()

    def make_callback(self, index: int):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.game.user_id:
                await interaction.response.send_message(
                    "This Mines game belongs to another player.",
                    ephemeral=True,
                )
                return
            await self.game.bot.mines_click(
                interaction,
                self.game,
                index,
                self,
            )
        return callback

    async def cashout(self, interaction: discord.Interaction):
        if interaction.user.id != self.game.user_id:
            await interaction.response.send_message(
                "This Mines game belongs to another player.",
                ephemeral=True,
            )
            return
        await self.game.bot.mines_cashout(
            interaction,
            self.game,
            self,
        )

    def add_header(self):
        pass


def mines_result_v2(
    game: MinesGame,
    result_label: str,
    payout: Decimal,
    multiplier: Decimal,
):
    won = payout > 0
    net = payout - game.amount
    player = game.bot.get_user(game.user_id)
    username = player.display_name if player else "Player"
    if won:
        text = (
            f"## WIN\n\n"
            f"> ﹒{username} · **+{money(payout)} (`+{money(net)}` net)** at "
            f"`{multiplier:.4f}×` ﹒mines · **{game.mines} mines** · "
            f"**{len(game.opened)}** · **{multiplier:.2f}×** · stake `{money(game.amount)}`\n\n"
            f"`Bet ID {game.game_id}` · hit a big one? drop a vouch"
        )
    else:
        text = (
            f"## LOSE\n\n"
            f"> ﹒{username} · **-{money(game.amount)} (`-{money(game.amount)}` net)** at "
            f"`{multiplier:.4f}×` ﹒mines · **{game.mines} mines** · "
            f"**{len(game.opened)}** · **{multiplier:.2f}×** · stake `{money(game.amount)}`\n\n"
            f"`Bet ID {game.game_id}` · hit a mine"
        )
    view = CasinoV2View(timeout=300)
    view.add_item(
        discord.ui.Container(
            discord.ui.TextDisplay(text),
            accent_color=0x57F287 if won else 0xED4245,
        )
    )
    return view


# ============================================================
# RAIN VIEW
# ============================================================

class RainView(ButtonView):

    def __init__(
        self,
        bot: "CasinoBot",
        rain_id: str,
    ):
        super().__init__(timeout=None)

        self.bot = bot
        self.rain_id = rain_id

    @discord.ui.button(
        label="Join Rain",
        style=discord.ButtonStyle.success,
        custom_id="rain_join",
    )
    async def join(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await self.bot.join_rain(
            interaction,
            self.rain_id,
        )



# ============================================================
# BOT
# ============================================================

class CasinoBot(commands.Bot):

    def __init__(self):

        intents = discord.Intents.default()

        intents.guilds = True
        intents.members = True
        intents.messages = True
        intents.message_content = True
        intents.presences = True

        super().__init__(
            command_prefix=[".", ","],
            intents=intents,
            help_command=None,
        )

        self.db: Optional[Database] = None

        self.http_session: Optional[aiohttp.ClientSession] = None

        self.started_at = datetime.now(timezone.utc)

        self.active_games: dict[int, dict] = {}
        self.active_mines: dict[int, MinesGame] = {}
        self.active_towers: dict[int, TowerGame] = {}
        self.active_roulette: dict[int, "RouletteGame"] = {}
        self.active_rains: dict[str, dict] = {}

        self.live_247_task: Optional[asyncio.Task] = None
        self.live_247_game: Optional[Live247BlackjackGame] = None
        self.live_247_channel_id: Optional[int] = None

        # Game numbers are intentionally sequential for the current bot session.
        # First completed/started casino game is Game #1, then #2, #3, etc.
        self.game_counter = 0

        # user_id -> the exact provably-fair data used by the active game.
        self.fair_games: dict[int, dict] = {}

        self._cooldowns: dict[
            tuple[int, str],
            float,
        ] = {}


    # ========================================================
    # GAME IDS
    # ========================================================

    def next_game_id(self) -> int:
        self.game_counter += 1
        return self.game_counter

    def register_fair_game(
        self,
        user_id: int,
        game: str,
        game_id: int,
        server_seed: str,
        client_seed: str,
        nonce: int = 0,
        winning_chance: str = "Game-specific",
        details: str = "",
    ):
        """Register the exact fairness inputs used by a live game.

        Settlement automatically writes these values into game_history, so
        `.verify <game_number>` can retrieve the exact completed round.
        """
        self.fair_games[user_id] = {
            "game": str(game),
            "game_id": int(game_id),
            "server_seed": str(server_seed),
            "server_hash": self.server_hash(server_seed),
            "client_seed": str(client_seed),
            "nonce": int(nonce),
            "winning_chance": str(winning_chance),
            "details": str(details or ""),
            "started_at": datetime.now(timezone.utc),
        }

    def get_fair_game(self, user_id: int):
        return self.fair_games.get(user_id)

    def clear_fair_game(self, user_id: int):
        self.fair_games.pop(user_id, None)

    # ========================================================
    # RANDOM / PROVABLY FAIR
    # ========================================================

    def create_server_seed(self) -> str:
        return secrets.token_hex(32)

    def server_hash(
        self,
        server_seed: str,
    ) -> str:

        return hashlib.sha256(
            server_seed.encode()
        ).hexdigest()

    def create_client_seed(
        self,
        user_id: int,
    ) -> str:

        return (
            f"{user_id}-"
            f"{secrets.token_hex(16)}"
        )

    def fair_digest(
        self,
        server_seed: str,
        client_seed: str,
        nonce: int,
        game: str = "",
    ) -> bytes:

        message = (
            f"{client_seed}:"
            f"{nonce}:"
            f"{game}"
        ).encode()

        return hmac.new(
            server_seed.encode(),
            message,
            hashlib.sha256,
        ).digest()

    def fair_roll(
        self,
        server_seed: str,
        client_seed: str,
        nonce: int,
        game: str = "",
    ) -> Decimal:

        digest = self.fair_digest(
            server_seed,
            client_seed,
            nonce,
            game,
        )

        number = int.from_bytes(
            digest[:8],
            "big",
        )

        value = (
            Decimal(number)
            / Decimal(2**64)
        ) * Decimal("100")

        return value.quantize(
            Decimal("0.01")
        )

    def fair_int(
        self,
        server_seed: str,
        client_seed: str,
        nonce: int,
        minimum: int,
        maximum: int,
        game: str = "",
    ) -> int:

        digest = self.fair_digest(
            server_seed,
            client_seed,
            nonce,
            game,
        )

        number = int.from_bytes(
            digest[:8],
            "big",
        )

        return minimum + (
            number % (
                maximum - minimum + 1
            )
        )

    def fair_shuffle(self, items, server_seed: str, client_seed: str, nonce: int, game: str):
        """Deterministically shuffle a list using the same HMAC fairness source."""
        items = list(items)
        for i in range(len(items) - 1, 0, -1):
            j = self.fair_int(server_seed, client_seed, nonce + (len(items) - i), 0, i, game)
            items[i], items[j] = items[j], items[i]
        return items

    # ========================================================
    # COOLDOWN
    # ========================================================

    def check_game_cooldown(
        self,
        user_id: int,
        command_name: str,
    ) -> float:

        if GAME_COOLDOWN <= 0:
            return 0

        key = (
            user_id,
            command_name,
        )

        now = time.monotonic()

        last = self._cooldowns.get(
            key,
            0,
        )

        remaining = (
            GAME_COOLDOWN
            - (now - last)
        )

        if remaining > 0:
            return remaining

        self._cooldowns[key] = now

        return 0

    # ========================================================
    # USER / BALANCE
    # ========================================================

    async def get_db_user(
        self,
        user_id: int,
    ):

        if self.db is None:
            raise RuntimeError(
                "Database is not connected."
            )

        return await self.db.user(
            user_id
        )

    async def get_balance(
        self,
        user_id: int,
    ) -> Decimal:

        row = await self.get_db_user(
            user_id
        )

        if not row:
            return Decimal("0")

        return D(
            row.get("balance", 0)
            if hasattr(row, "get")
            else row["balance"]
        )

    async def deduct_bet(
        self,
        user_id: int,
        amount: Decimal,
        game: str,
    ) -> bool:

        if amount < MIN_BET:
            return False

        return await self.db.change_balance(
            user_id,
            -amount,
            kind="bet",
            note=game,
        )

    # ========================================================
    # DATABASE GAME SETTLEMENT
    # ========================================================

    async def send_win_log(
        self,
        user_id: int,
        payout: Decimal,
        bet: Decimal,
        game: str,
    ):
        """Send a public WIN log to the configured game-log channel."""
        if payout <= 0 or bet <= 0 or self.db is None:
            return
        try:
            channel_id = await self.db.setting("winlog_channel_id", "0")
            if not channel_id:
                return
            channel = self.get_channel(int(channel_id))
            if channel is None:
                try:
                    channel = await self.fetch_channel(int(channel_id))
                except Exception:
                    return
            multiplier = (payout / bet).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
            player = self.get_user(user_id)
            username = player.display_name if player else f"User {user_id}"
            game_name = str(game).replace("_", " ").lower()
            net = payout - bet
            text = (
                f"<:Party:1557392288131584001>  — successful result\n\n## WIN\n\n"
                f"> ﹒{username} · **+{money(payout)} (`+{money(net)}` net)** at `{multiplier:.4f}×` · {game_name} · stake `{money(bet)}`\n\n"
                f"`Bet ID {self.get_fair_game(user_id).get('game_id') if self.get_fair_game(user_id) else '—'}` · hit a big one? drop a vouch"
            )
            await channel.send(text)
        except Exception as exc:
            print(f"[WIN LOG] {exc}")

    async def send_loss_log(
        self,
        user_id: int,
        bet: Decimal,
        game: str,
    ):
        """Send a public LOSE log to the same channel as WIN logs."""
        if bet <= 0 or self.db is None:
            return
        try:
            channel_id = await self.db.setting("winlog_channel_id", "0")
            if not channel_id:
                return
            channel = self.get_channel(int(channel_id))
            if channel is None:
                try:
                    channel = await self.fetch_channel(int(channel_id))
                except Exception:
                    return
            fair = self.get_fair_game(user_id)
            game_id = fair.get("game_id") if fair else "—"
            player = self.get_user(user_id)
            username = player.display_name if player else f"User {user_id}"
            game_name = str(game).replace("_", " ").lower()
            text = (
                f"<:BombBomb:1557392249975738448>  — loss\n\n## LOSE\n\n"
                f"> ﹒{username} · **-{money(bet)} (`-{money(bet)}` net)** · {game_name} · stake `{money(bet)}`\n\n"
                f"`Bet ID {game_id}` · better luck next time"
            )
            await channel.send(text)
        except Exception as exc:
            print(f"[LOSS LOG] {exc}")

    async def _persist_fair_metadata(self, user_id: int, fair: Optional[dict]):
        if not fair or self.db is None:
            return
        try:
            await self.db.pool.execute(
                """
                UPDATE game_history
                SET winning_chance = $1, fair_details = $2
                WHERE id = (
                    SELECT id FROM game_history
                    WHERE user_id = $3 AND game_id = $4
                    ORDER BY id DESC LIMIT 1
                )
                """,
                fair.get("winning_chance", "Game-specific"),
                fair.get("details", ""),
                user_id,
                fair.get("game_id"),
            )
        except Exception as exc:
            print(f"[FAIR META] {type(exc).__name__}: {exc}")

    async def settle_win(
        self,
        user_id: int,
        bet: Decimal,
        payout: Decimal,
        game: str,
        race_amount=None,
        *,
        result: str = "WIN",
    ):
        fair = self.get_fair_game(user_id)
        await self.db.record_game(
            user_id,
            bet,
            payout,
            game,
            result=result,
            game_id=fair.get("game_id") if fair else None,
            server_hash=fair.get("server_hash") if fair else None,
            server_seed=fair.get("server_seed") if fair else None,
            client_seed=fair.get("client_seed") if fair else None,
            nonce=fair.get("nonce") if fair else None,
            race_amount=race_amount,
        )
        await self.send_win_log(user_id, payout, bet, game)
        await self._persist_fair_metadata(user_id, fair)
        self.clear_fair_game(user_id)

    async def settle_loss(
        self,
        user_id: int,
        bet: Decimal,
        game: str,
        race_amount=None,
        *,
        result: str = "LOSS",
    ):
        fair = self.get_fair_game(user_id)
        await self.db.record_game(
            user_id,
            bet,
            Decimal("0"),
            game,
            result=result,
            game_id=fair.get("game_id") if fair else None,
            server_hash=fair.get("server_hash") if fair else None,
            server_seed=fair.get("server_seed") if fair else None,
            client_seed=fair.get("client_seed") if fair else None,
            nonce=fair.get("nonce") if fair else None,
            race_amount=race_amount,
        )
        await self._persist_fair_metadata(user_id, fair)
        await self.send_loss_log(user_id, bet, game)
        self.clear_fair_game(user_id)

    # ========================================================
    # DISCORD STARTUP
    # ========================================================

    async def setup_hook(self):

        if not DATABASE_URL:
            raise RuntimeError(
                "DATABASE_URL is missing."
            )

        self.db = Database(
            DATABASE_URL
        )

        await self.db.connect()
        try:
            stored_voucher = await self.db.setting("voucher_channel_id", "")
            self.voucher_channel_id = int(stored_voucher) if stored_voucher else None
            stored_min_withdrawal = await self.db.setting("min_withdrawal", str(MIN_WITHDRAWAL))
            try:
                self.min_withdrawal = D(stored_min_withdrawal)
            except Exception:
                self.min_withdrawal = MIN_WITHDRAWAL
            if self.min_withdrawal <= 0:
                self.min_withdrawal = MIN_WITHDRAWAL
        except Exception:
            self.voucher_channel_id = None

        # Compatibility migrations for databases created by older bot versions.
        # These are idempotent and keep existing balances/data intact.
        async with self.db.pool.acquire() as connection:
            await connection.execute("""
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ
                NOT NULL DEFAULT NOW()
            """)
            await connection.execute("""
                ALTER TABLE game_history
                ADD COLUMN IF NOT EXISTS winning_chance TEXT
            """)
            await connection.execute("""
                ALTER TABLE game_history
                ADD COLUMN IF NOT EXISTS fair_details TEXT
            """)
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS house (
                    id INTEGER PRIMARY KEY,
                    balance NUMERIC(20,4) NOT NULL DEFAULT 87.00,
                    ltc_balance NUMERIC(20,4) NOT NULL DEFAULT 52.20,
                    sol_balance NUMERIC(20,4) NOT NULL DEFAULT 26.10,
                    usdt_balance NUMERIC(20,4) NOT NULL DEFAULT 8.70
                )
            """)
            await connection.execute("""
                ALTER TABLE house
                ADD COLUMN IF NOT EXISTS ltc_balance
                NUMERIC(20,4) NOT NULL DEFAULT 52.20
            """)
            await connection.execute("""
                ALTER TABLE house
                ADD COLUMN IF NOT EXISTS sol_balance
                NUMERIC(20,4) NOT NULL DEFAULT 26.10
            """)
            await connection.execute("""
                ALTER TABLE house
                ADD COLUMN IF NOT EXISTS usdt_balance
                NUMERIC(20,4) NOT NULL DEFAULT 8.70
            """)
            await connection.execute("""
                INSERT INTO house(id, balance, ltc_balance, sol_balance, usdt_balance)
                VALUES(1, 87.00, 52.20, 26.10, 8.70)
                ON CONFLICT(id) DO NOTHING
            """)
            await connection.execute("""
                UPDATE house
                SET balance=87.00, ltc_balance=52.20, sol_balance=26.10, usdt_balance=8.70
                WHERE id=1 AND balance=9.87 AND ltc_balance=5.00 AND sol_balance=3.00 AND usdt_balance=1.87
            """)
            await connection.execute("ALTER TABLE withdrawals ADD COLUMN IF NOT EXISTS owner_override BOOLEAN NOT NULL DEFAULT FALSE")
            await connection.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS bonus_wager_remaining NUMERIC(20,8) NOT NULL DEFAULT 0")
            await connection.execute("ALTER TABLE game_history ADD COLUMN IF NOT EXISTS choice TEXT")

        self.http_session = aiohttp.ClientSession()

        self.add_view(
            RainView(
                self,
                "persistent",
            )
        )

        # Restore pending withdrawal admin buttons after a restart.
        try:
            pending_withdrawals = await self.db.pool.fetch(
                """
                SELECT id
                FROM withdrawals
                WHERE status = 'pending'
                ORDER BY id DESC
                LIMIT 100
                """
            )
            for row in pending_withdrawals:
                self.add_view(
                    WithdrawalAdminView(
                        self,
                        int(row["id"]),
                    )
                )
        except Exception as exc:
            print(f"[WITHDRAW] Could not restore admin buttons: {exc}")

        print("[BOT] Prefix commands loaded with . and , prefixes.")

    async def close(self):
        
        if self.http_session:
            await self.http_session.close()
            self.http_session = None

        if self.db:
            await self.db.close()

        await super().close()

    async def on_ready(self):

        print(
            f"[BOT] Logged in as {self.user} "
            f"({self.user.id})"
        )

        print(
            f"[BOT] Servers: {len(self.guilds)}"
        )

        await self.change_presence(
            activity=discord.Game(
                name=".help"
            )
        )

    # ========================================================
    # ERROR HELPERS
    # ========================================================

    async def safe_send(
        self,
        interaction: discord.Interaction,
        *,
        content: Optional[str] = None,
        embed: Optional[discord.Embed] = None,
        view: Optional[discord.ui.View] = None,
        ephemeral: bool = False,
    ):

        # Normal bot responses are rendered as embeds.
        # Components-V2 LayoutViews are kept as-is because Discord does not
        # allow legacy embeds/content together with Components-V2.
        if content is not None and embed is None:
            if not isinstance(view, getattr(discord.ui, "LayoutView", ())):
                embed = base_embed(
                    "Message",
                    str(content),
                    0xB8BCC2,
                )
                content = None

        kwargs = {
            "content": content,
            "embed": embed,
            "view": view,
            "ephemeral": ephemeral,
        }

        kwargs = {
            key: value
            for key, value in kwargs.items()
            if value is not None
        }

        if interaction.response.is_done():

            return await interaction.followup.send(
                **kwargs
            )

        return await interaction.response.send_message(
            **kwargs
        )

    async def command_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
    ):

        print(
            f"[COMMAND ERROR] "
            f"{interaction.command}: {error}"
        )

        if isinstance(
            error,
            app_commands.CommandOnCooldown,
        ):

            await self.safe_send(
                interaction,
                content=(
                    f"Please wait "
                    f"**{error.retry_after:.1f}s**."
                ),
                ephemeral=False,
            )

            return

        await self.safe_send(
            interaction,
            embed=error_embed(
                "Something went wrong",
                "Please try again in a moment.",
            ),
            ephemeral=False,
        )
        
    # ========================================================
    # DEPOSIT DM
    # ========================================================

    async def send_deposit_dm(
        self,
        interaction: discord.Interaction,
        currency: str,
    ):

        currency = currency.upper()

        address = await self.get_deposit_address(
            interaction.user.id,
            currency,
        )

        if not address:

            await interaction.response.send_message(
                "A deposit address is not available yet.",
                ephemeral=False,
            )

            return

        try:

            await interaction.user.send(
                f"## {currency} Deposit\n\n"
                f"**Deposit Address:**\n"
                f"`{address}`\n\n"
                "Deposits are credited only after "
                "blockchain confirmation."
            )

            await interaction.response.send_message(
                "Your deposit address is sent to your DMs. "
                "Deposits are credited only after blockchain confirmation.",
                ephemeral=False,
            )

        except discord.Forbidden:

            await interaction.response.send_message(
                "I couldn't DM you. Please enable DMs "
                "from this server and try again.",
                ephemeral=False,
            )

    async def get_deposit_address(
        self,
        user_id: int,
        currency: str,
    ) -> Optional[str]:

        currency = currency.upper()

        if hasattr(
            self.db,
            "get_deposit_address",
        ):

            return await self.db.get_deposit_address(
                user_id,
                currency,
            )

        if currency == "SOL":

            return os.getenv(
                "SOL_DEPOSIT_ADDRESS",
                "",
            ) or None
            
        return None
        

# ============================================================
# BONUS FUNDS / 2X WAGER LOCK
# ============================================================

_original_db_change_balance = Database.change_balance
_original_db_record_game = Database.record_game

async def _change_balance_with_bonus_lock(self, user_id, amount, kind="adjustment", note=""):
    ok = await _original_db_change_balance(self, user_id, amount, kind=kind, note=note)
    if ok and D(amount) > 0 and str(kind).lower() in {"promo", "rain", "credit"}:
        await self.pool.execute(
            "UPDATE users SET bonus_wager_remaining=bonus_wager_remaining+$2 WHERE user_id=$1",
            user_id, D(amount) * Decimal("2"),
        )
    return ok

async def _record_game_with_bonus_unlock(self, user_id, bet, payout, game, **kwargs):
    result = await _original_db_record_game(self, user_id, bet, payout, game, **kwargs)
    wager = D(bet)
    if wager > 0:
        await self.pool.execute(
            "UPDATE users SET bonus_wager_remaining=GREATEST(0, bonus_wager_remaining-$2) WHERE user_id=$1",
            user_id, wager,
        )
    return result

Database.change_balance = _change_balance_with_bonus_lock
Database.record_game = _record_game_with_bonus_unlock

_original_db_claim_code = Database.claim_code
async def _claim_code_with_bonus_lock(self, user_id, code):
    result = await _original_db_claim_code(self, user_id, code)
    if isinstance(result, tuple) and len(result) >= 3 and result[0] and D(result[2]) > 0:
        await self.pool.execute(
            "UPDATE users SET bonus_wager_remaining=bonus_wager_remaining+$2 WHERE user_id=$1",
            user_id, D(result[2]) * Decimal("2"),
        )
    return result
Database.claim_code = _claim_code_with_bonus_lock

# ============================================================
# BOT INSTANCE
# ============================================================

bot = CasinoBot()
bot.withdraw_log_channel_id = WITHDRAW_LOG_CHANNEL_ID
bot.withdraw_admin_channel_id = WITHDRAW_LOG_CHANNEL_ID
bot.withdraw_sessions = {}
bot.voucher_channel_id = None
bot.min_withdrawal = MIN_WITHDRAWAL
bot.disabled_commands = set()


# ============================================================
# PREFIX COMMAND BRIDGE
# ============================================================

class _PrefixResponse:
    def __init__(self, interaction): self.interaction=interaction; self._done=False
    def is_done(self): return self._done
    async def send_message(self, content=None, *, embed=None, embeds=None, view=None, file=None, files=None, ephemeral=False, allowed_mentions=None, **kwargs):
        self._done=True
        kw={"content":content,"embed":embed,"embeds":embeds,"view":view,"file":file,"files":files,"allowed_mentions":allowed_mentions}; kw.update(kwargs)
        kw={k:v for k,v in kw.items() if v is not None}
        self.interaction._last_message=await self.interaction._ctx.send(**kw); return self.interaction._last_message
    async def edit_message(self, **kwargs):
        self._done=True
        if self.interaction._last_message is None: self.interaction._last_message=await self.interaction._ctx.send(**kwargs)
        else: await self.interaction._last_message.edit(**kwargs)
        return self.interaction._last_message
    async def defer(self, *, ephemeral=False, thinking=False, **kwargs):
        self._done=True
        if self.interaction._last_message is None: self.interaction._last_message=await self.interaction._ctx.send("Processing...")
        return self.interaction._last_message

class _PrefixFollowup:
    def __init__(self, interaction): self.interaction=interaction
    async def send(self, content=None, *, embed=None, embeds=None, view=None, file=None, files=None, ephemeral=False, wait=False, allowed_mentions=None, **kwargs):
        kw={"content":content,"embed":embed,"embeds":embeds,"view":view,"file":file,"files":files,"allowed_mentions":allowed_mentions}; kw.update(kwargs)
        kw={k:v for k,v in kw.items() if v is not None}
        message=await self.interaction._ctx.send(**kw); self.interaction._last_message=message; return message

class PrefixInteraction:
    def __init__(self, ctx: commands.Context):
        self._ctx=ctx; self._last_message=None; self.response=_PrefixResponse(self); self.followup=_PrefixFollowup(self)
        self.user=ctx.author; self.guild=ctx.guild; self.channel=ctx.channel; self.client=ctx.bot; self.command=ctx.command
    @property
    def channel_id(self): return getattr(self.channel,"id",None)
    async def original_response(self):
        if self._last_message is None: self._last_message=await self._ctx.send("Processing...")
        return self._last_message
    async def edit_original_response(self, **kwargs):
        if self._last_message is None: self._last_message=await self._ctx.send(**kwargs)
        else: await self._last_message.edit(**kwargs)
        return self._last_message
    async def delete_original_response(self):
        if self._last_message is not None: await self._last_message.delete()
    def __getattr__(self,name): return getattr(self._ctx,name)

class _PrefixChoice:
    def __init__(self,value): self.value=value; self.name=str(value)

def _strip_optional(annotation):
    origin=get_origin(annotation)
    if origin is Union:
        args=[a for a in get_args(annotation) if a is not type(None)]
        if len(args)==1: return args[0]
    return annotation

async def _convert_prefix_argument(ctx, raw, annotation):
    annotation=_strip_optional(annotation)
    origin=get_origin(annotation)
    if origin is __import__('typing').Annotated:
        annotation=get_args(annotation)[0]; origin=get_origin(annotation)
    if annotation is inspect._empty or annotation is str: return raw
    if annotation is int: return int(raw)
    if annotation is float: return float(raw)
    if annotation is Decimal: return Decimal(raw)
    if annotation is discord.Member: return await commands.MemberConverter().convert(ctx,raw)
    if annotation is discord.User: return await commands.UserConverter().convert(ctx,raw)
    if annotation is discord.TextChannel: return await commands.TextChannelConverter().convert(ctx,raw)
    if origin is app_commands.Choice:
        args=get_args(annotation); target=args[0] if args else str
        # Friendly duration input for .rain
        if target is int and str(raw).lower().replace(' ','') in {'1minute','1m'}: raw='1'
        elif target is int and str(raw).lower().replace(' ','') in {'2minutes','2m'}: raw='2'
        elif target is int and str(raw).lower().replace(' ','') in {'5minutes','5m'}: raw='5'
        elif target is int and str(raw).lower().replace(' ','') in {'10minutes','10m'}: raw='10'
        value=await _convert_prefix_argument(ctx,raw,target); return _PrefixChoice(value)
    if 'app_commands.commands.Range' in str(annotation) or 'discord.app_commands.Range' in str(annotation):
        return int(raw)
    return raw

def prefix_owner_only():
    def decorator(func): func.__prefix_owner_only__=True; return func
    return decorator

def bot_owner_only():
    """Strict owner-only decorator: only config.OWNER_ID may use it."""
    def decorator(func):
        func.__prefix_bot_owner_only__=True
        return func
    return decorator

def owner_only():
    return prefix_owner_only()


def prefix_command(*, name=None, aliases=None):
    aliases=list(aliases or [])
    def decorator(func):
        command_name=name or func.__name__.replace('_','-')
        sig=inspect.signature(func)
        try: hints=get_type_hints(func,globalns=globals(),localns=locals())
        except Exception: hints={}
        params=list(sig.parameters.values())[1:]
        required=[p for p in params if p.default is inspect._empty]
        async def wrapper(ctx: commands.Context,*raw_args):
            disabled = getattr(bot, 'disabled_commands', set())
            if command_name not in {'disable','enable'} and (command_name in disabled or any(alias in disabled for alias in aliases)):
                await ctx.send(embed=error_embed('Command Disabled', f'`{command_name}` is currently disabled.'))
                return
            if getattr(wrapper,'__prefix_bot_owner_only__',False):
                owner_id=getattr(config,'OWNER_ID',None)
                try:
                    owner_id=int(owner_id) if owner_id is not None else 0
                except (TypeError, ValueError):
                    owner_id=0
                if not owner_id or ctx.author.id != owner_id:
                    await ctx.send(embed=error_embed('Permission Denied','Only the bot owner can use this command.'))
                    return

            if getattr(wrapper,'__prefix_owner_only__',False):
                admin_ids=set(getattr(config,'ADMIN_USER_IDS',[]) or [])
                owner_id=getattr(config,'OWNER_ID',None)
                if owner_id:
                    try: admin_ids.add(int(owner_id))
                    except Exception: pass
                if ctx.author.id not in admin_ids:
                    await ctx.send(embed=error_embed('Permission Denied','You do not have permission to use this command.')); return
            if len(raw_args)<len(required):
                usage=f"{ctx.prefix}{command_name} "+' '.join(f'<{p.name}>' for p in required)
                await ctx.send(embed=error_embed('Missing Arguments',f'Usage: `{usage.strip()}`')); return
            if len(raw_args)>len(params):
                usage=f"{ctx.prefix}{command_name} "+' '.join(f'<{p.name}>' for p in params)
                await ctx.send(embed=error_embed('Too Many Arguments',f'Usage: `{usage.strip()}`')); return
            converted=[]
            for i,p in enumerate(params):
                if i>=len(raw_args): converted.append(p.default); continue
                try: converted.append(await _convert_prefix_argument(ctx,raw_args[i],hints.get(p.name,p.annotation)))
                except Exception:
                    await ctx.send(embed=error_embed('Invalid Argument',f'`{raw_args[i]}` is not valid for `{p.name}`.')); return
            return await func(PrefixInteraction(ctx),*converted)
        wrapper.__name__=func.__name__; wrapper.__doc__=func.__doc__
        bot.command(name=command_name,aliases=aliases)(wrapper)
        return wrapper
    return decorator


# ============================================================
# EMBED RESPONSE COMPATIBILITY LAYER
# ============================================================
# Some older command/view callbacks in this full source still call Discord's
# low-level send/edit methods directly. Convert those plain-text responses to
# the same light-grey embed style without changing their game/accounting logic.

def _plain_response_embed(content):
    if content is None:
        return None
    return base_embed("Message", str(content), 0xB8BCC2)


_original_ir_send = discord.InteractionResponse.send_message
_original_ir_edit = discord.InteractionResponse.edit_message
_original_interaction_edit_original = discord.Interaction.edit_original_response
_original_messageable_send = discord.abc.Messageable.send
_original_webhook_send = discord.Webhook.send


def _legacy_view_to_v2(view):
    if view is None:
        return None
    layout_cls = getattr(discord.ui, "LayoutView", None)
    if layout_cls and isinstance(view, layout_cls):
        return view
    if not isinstance(view, discord.ui.View):
        return view
    items = list(getattr(view, "children", []))
    try:
        view.clear_items()
    except Exception:
        pass
    v2 = CasinoV2View(timeout=getattr(view, "timeout", 180))
    for i in range(0, len(items), 5):
        row = discord.ui.ActionRow(*items[i:i+5])
        v2.add_item(row)
    return v2


def _embed_to_v2_view(embed, legacy_view=None):
    if embed is None:
        return _legacy_view_to_v2(legacy_view)

    layout_cls = getattr(discord.ui, "LayoutView", None)
    if layout_cls and isinstance(legacy_view, layout_cls):
        view = legacy_view
        old_items = []
    elif isinstance(legacy_view, discord.ui.View):
        old_items = list(getattr(legacy_view, "children", []))
        try:
            legacy_view.clear_items()
        except Exception:
            pass
        view = CasinoV2View(timeout=getattr(legacy_view, "timeout", 180))
    else:
        view = CasinoV2View(timeout=300)
        old_items = []

    data = embed.to_dict()
    children = [discord.ui.TextDisplay(f"## {data.get('title') or 'Message'}")]
    if data.get("description"):
        children.append(discord.ui.TextDisplay(str(data["description"])))
    for field in data.get("fields", []):
        children.append(discord.ui.TextDisplay(f"**{field.get('name','')}**\n{field.get('value','')}"))
    footer = (data.get("footer") or {}).get("text")
    if footer:
        children.append(discord.ui.TextDisplay(f"-# {footer}"))
    image_url = (data.get("image") or {}).get("url") or (data.get("thumbnail") or {}).get("url")
    if image_url:
        children.append(discord.ui.MediaGallery(discord.MediaGalleryItem(media=image_url)))
    for i in range(0, len(old_items), 5):
        children.append(discord.ui.ActionRow(*old_items[i:i+5]))

    color_data = data.get("color")
    color = int(color_data.get("value", 0x5865F2)) if isinstance(color_data, dict) else 0x5865F2
    view.clear_items()
    view.add_item(discord.ui.Container(*children, accent_color=color))
    return view


async def _embed_ir_send(self, *args, **kwargs):
    if "embed" in kwargs or "embeds" in kwargs:
        embed = kwargs.get("embed") or (kwargs.get("embeds") or [None])[0]
        if embed is not None:
            kwargs["view"] = _embed_to_v2_view(embed, kwargs.get("view"))
            kwargs.pop("embed", None); kwargs.pop("embeds", None)
    elif kwargs.get("content") is not None and not isinstance(kwargs.get("view"), CasinoV2View):
        kwargs["view"] = _embed_to_v2_view(_plain_response_embed(kwargs["content"]), kwargs.get("view"))
        kwargs.pop("content", None)
    return await _original_ir_send(self, *args, **kwargs)


async def _embed_ir_edit(self, *args, **kwargs):
    if "embed" in kwargs or "embeds" in kwargs:
        embed = kwargs.get("embed") or (kwargs.get("embeds") or [None])[0]
        if embed is not None:
            kwargs["view"] = _embed_to_v2_view(embed, kwargs.get("view"))
            kwargs.pop("embed", None); kwargs.pop("embeds", None)
    elif kwargs.get("content") is not None and not isinstance(kwargs.get("view"), CasinoV2View):
        kwargs["view"] = _embed_to_v2_view(_plain_response_embed(kwargs["content"]), kwargs.get("view"))
        kwargs.pop("content", None)
    return await _original_ir_edit(self, *args, **kwargs)


async def _embed_original_edit(self, *args, **kwargs):
    if "embed" in kwargs or "embeds" in kwargs:
        embed = kwargs.get("embed") or (kwargs.get("embeds") or [None])[0]
        if embed is not None:
            kwargs["view"] = _embed_to_v2_view(embed, kwargs.get("view"))
            kwargs.pop("embed", None); kwargs.pop("embeds", None)
    elif kwargs.get("content") is not None and not isinstance(kwargs.get("view"), CasinoV2View):
        kwargs["view"] = _embed_to_v2_view(_plain_response_embed(kwargs["content"]), kwargs.get("view"))
        kwargs.pop("content", None)
    return await _original_interaction_edit_original(self, *args, **kwargs)


async def _embed_messageable_send(self, *args, **kwargs):
    if "embed" in kwargs or "embeds" in kwargs:
        embed = kwargs.get("embed") or (kwargs.get("embeds") or [None])[0]
        if embed is not None:
            kwargs["view"] = _embed_to_v2_view(embed, kwargs.get("view"))
            kwargs.pop("embed", None); kwargs.pop("embeds", None)
    else:
        content = kwargs.get("content")
        if content is None and args:
            content = args[0]; args = args[1:]
        if content is not None and not isinstance(kwargs.get("view"), CasinoV2View):
            kwargs["view"] = _embed_to_v2_view(_plain_response_embed(content), kwargs.get("view"))
            kwargs.pop("content", None)
    return await _original_messageable_send(self, *args, **kwargs)


async def _embed_webhook_send(self, *args, **kwargs):
    if "embed" in kwargs or "embeds" in kwargs:
        embed = kwargs.get("embed") or (kwargs.get("embeds") or [None])[0]
        if embed is not None:
            kwargs["view"] = _embed_to_v2_view(embed, kwargs.get("view"))
            kwargs.pop("embed", None); kwargs.pop("embeds", None)
    else:
        content = kwargs.get("content")
        if content is None and args:
            content = args[0]; args = args[1:]
        if content is not None and not isinstance(kwargs.get("view"), CasinoV2View):
            kwargs["view"] = _embed_to_v2_view(_plain_response_embed(content), kwargs.get("view"))
            kwargs.pop("content", None)
    return await _original_webhook_send(self, *args, **kwargs)


discord.InteractionResponse.send_message = _embed_ir_send
discord.InteractionResponse.edit_message = _embed_ir_edit
discord.Interaction.edit_original_response = _embed_original_edit
discord.abc.Messageable.send = _embed_messageable_send
discord.Webhook.send = _embed_webhook_send


# ============================================================
# WITHDRAW DM WIZARD
# ============================================================

def _withdraw_address_valid(currency: str, address: str) -> bool:
    address = str(address).strip()
    currency = currency.upper()
    if currency == "LTC":
        return (
            address.lower().startswith("ltc1")
            or (
                address.startswith(("L", "M", "m"))
                and 26 <= len(address) <= 35
            )
        )
    if currency == "SOL":
        return 32 <= len(address) <= 44
    if currency == "USDT":
        return (
            (address.startswith("0x") and len(address) == 42)
            or (len(address) in {34, 35} and address.upper().startswith("T"))
        )
    return False


async def _finish_withdrawal_request(user, amount_text: str, crypto: str, address: str, source_ctx=None):
    user_id = user.id
    crypto = str(crypto).strip().upper()
    if crypto not in {"LTC", "SOL", "USDT"}:
        return await user.send("﹒choose `LTC`, `SOL`, or `USDT`.")

    if not _withdraw_address_valid(crypto, address):
        return await user.send(f"﹒that does not look like a valid `{crypto}` address.")

    # Lifetime deposit requirement: $1.00 minimum before any withdrawal.
    lifetime_deposit = await bot.db.pool.fetchval(
        "SELECT lifetime_deposit FROM users WHERE user_id=$1",
        user_id,
    )
    lifetime_deposit = D(lifetime_deposit or 0)
    if lifetime_deposit < Decimal("1.00"):
        return await user.send(
            "﹒you must have deposited at least **$1.00 lifetime** before withdrawing."
        )

    bonus_remaining = await bot.db.pool.fetchval(
        "SELECT bonus_wager_remaining FROM users WHERE user_id=$1",
        user_id,
    )
    bonus_remaining = D(bonus_remaining or 0)
    if bonus_remaining > Decimal("0.00"):
        return await user.send(
            f"﹒you must wager another **{money(bonus_remaining)}** before withdrawing bonus/rain/code funds."
        )

    balance = await bot.get_balance(user_id)
    raw = str(amount_text).strip().lower()

    try:
        if raw == "all":
            value = balance
        elif raw == "half":
            value = (balance / Decimal("2")).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        elif raw.endswith("ltc"):
            ltc = Decimal(raw[:-3].replace("$", "").strip())
            price = await get_crypto_usd_price("LTC")
            if not price or price <= 0:
                return await user.send("﹒LTC price is unavailable right now.")
            value = (ltc * price).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        else:
            value = normalize_amount(raw)
    except Exception:
        value = None

    if value is None or value <= 0:
        return await user.send("﹒enter a valid amount, `all`, or `half`.")

    min_withdrawal = D(getattr(bot, "min_withdrawal", MIN_WITHDRAWAL))
    if value < min_withdrawal:
        return await user.send(f"﹒minimum withdrawal is `{money(min_withdrawal)}`.")

    is_owner = user_id == int(getattr(config, "OWNER_ID", BOT_OWNER_ID))
    if not is_owner and value > balance:
        return await user.send(f"﹒insufficient balance · you have **{money(balance)}**.")
    price = await get_crypto_usd_price(crypto)
    if not price or price <= 0:
        return await user.send(f"﹒I couldn't get the current {crypto} price.")

    crypto_amount = (value / price).quantize(Decimal("0.00000001"))
    wid = await bot.db.create_withdrawal_request(
        user_id,
        crypto,
        address,
        value,
        owner_override=is_owner,
    )
    if not wid:
        return await user.send("﹒the withdrawal could not be created. Please try again.")

    log_channel_id = int(getattr(bot, "withdraw_log_channel_id", WITHDRAW_LOG_CHANNEL_ID))
    log_channel = bot.get_channel(log_channel_id)
    if log_channel is None:
        try:
            log_channel = await bot.fetch_channel(log_channel_id)
        except Exception:
            log_channel = None

    if log_channel:
        pending_view = WithdrawalAdminView(bot, wid)
        pending_view.request_text = (
            f"> **<@{user_id}>** requested **{money(value)}** · `{crypto_amount:.8f} {crypto}`\n"
            f"> address `{address}`\n"
            f"> status `pending admin approval`"
        )
        pending_view.rebuild()
        try:
            await log_channel.send(view=pending_view)
        except Exception as exc:
            print(f"[WITHDRAW] admin log failed: {exc}")

    try:
        confirm_view = CasinoV2View(timeout=120)
        confirm_view.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay("## Withdraw"),
                discord.ui.TextDisplay(
                    f"> ﹒request created · **{money(value)}** · `{crypto_amount:.8f} {crypto}`\n"
                    "> ﹒your request is waiting for an admin to process it"
                ),
                accent_color=0x5865F2,
            )
        )
        await user.send(view=confirm_view)
    except Exception as exc:
        print(f"[WITHDRAW] confirmation DM failed: {exc}")

    bot.withdraw_sessions.pop(user_id, None)


async def _withdraw_dm_on_message(message: discord.Message):
    if message.author.bot:
        return

    # Normal command processing still happens for DMs that are not in a withdrawal session.
    if message.guild is not None:
        await bot.process_commands(message)
        return

    session = getattr(bot, "withdraw_sessions", {}).get(message.author.id)
    if not session:
        await bot.process_commands(message)
        return

    if time.monotonic() > session.get("expires_at", 0):
        bot.withdraw_sessions.pop(message.author.id, None)
        await message.channel.send("﹒withdraw session expired · run `.withdraw` again.")
        return

    session["expires_at"] = time.monotonic() + 120
    step = int(session.get("step", 1))
    text = message.content.strip()

    if step == 1:
        balance = await bot.get_balance(message.author.id)
        raw = text.lower()
        try:
            if raw == "all":
                value = balance
            elif raw == "half":
                value = (balance / Decimal("2")).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
            elif raw.endswith("ltc"):
                ltc = Decimal(raw[:-3].replace("$", "").strip())
                price = await get_crypto_usd_price("LTC")
                value = (ltc * price).quantize(Decimal("0.01"), rounding=ROUND_DOWN) if price and price > 0 else None
            else:
                value = normalize_amount(raw)
        except Exception:
            value = None

        if value is None or value <= 0:
            await message.channel.send("﹒enter a valid amount, `all`, or `half`.")
            return
        min_withdrawal = D(getattr(bot, "min_withdrawal", MIN_WITHDRAWAL))
        if value < min_withdrawal:
            await message.channel.send(f"﹒minimum withdrawal is `{money(min_withdrawal)}`.")
            return
        if value > balance:
            await message.channel.send(f"﹒insufficient balance · you have **{money(balance)}**.")
            return

        session["amount"] = str(value)
        session["step"] = 2
        view = CasinoV2View(timeout=120)
        view.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay("## Withdraw"),
                discord.ui.TextDisplay(
                    f"> ﹒**step 2/3**  ·  Choose Crypto Type\n\n"
                    f"amount · **{money(value)}**\n\n"
                    "type `LTC`, `SOL`, or `USDT`"
                ),
                accent_color=0x5865F2,
            )
        )
        await message.channel.send(view=view)
        return

    if step == 2:
        crypto = text.upper()
        if crypto not in {"LTC", "SOL", "USDT"}:
            await message.channel.send("﹒choose `LTC`, `SOL`, or `USDT`.")
            return

        session["crypto"] = crypto
        session["step"] = 3
        view = CasinoV2View(timeout=120)
        view.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay("## Withdraw"),
                discord.ui.TextDisplay(
                    f"> ﹒**step 3/3**  · Send your {crypto} address\n\n"
                    f"amount · **{money(Decimal(session['amount']))}**\n"
                    f"crypto · `{crypto}`\n\n"
                    "send your wallet address in this DM"
                ),
                accent_color=0x5865F2,
            )
        )
        await message.channel.send(view=view)
        return

    if step == 3:
        amount_text = session.get("amount")
        crypto = session.get("crypto")
        await _finish_withdrawal_request(
            message.author,
            amount_text,
            crypto,
            text,
        )
        return


bot.on_message = _withdraw_dm_on_message


# ============================================================
# PART 1 COMMAND REGISTRATION CONTINUES IN PART 2
# ============================================================

# ============================================================
# bot.py — PART 2 / 10
# SLASH COMMANDS — WALLET, HELP, GUIDES, STATS
# ============================================================


# ============================================================
# BASIC COMMAND CHECKS
# ============================================================

def slash_command_available(
    interaction: discord.Interaction,
) -> bool:

    return interaction.guild is not None


async def require_database(
    interaction: discord.Interaction,
) -> bool:

    if bot.db is None:

        await bot.safe_send(
            interaction,
            content="Database is not ready yet.",
            ephemeral=False,
        )

        return False

    return True


async def require_bet_amount(
    interaction: discord.Interaction,
    amount: Decimal,
) -> bool:

    if amount < MIN_BET:

        await bot.safe_send(
            interaction,
            embed=error_embed(
                "Invalid Bet",
                f"The minimum bet is **{money(MIN_BET)}**.",
            ),
            ephemeral=False,
        )

        return False

    return True


async def require_sufficient_balance(
    interaction: discord.Interaction,
    amount: Decimal,
) -> bool:

    balance = await bot.get_balance(
        interaction.user.id
    )

    if amount > balance:

        await bot.safe_send(
            interaction,
            embed=error_embed(
                "Insufficient Balance",
                "You Dont Have Enough Crypto\n"
                "-# use /deposit to top-up Funds",
            ),
            ephemeral=False,
        )

        return False

    return True


# ============================================================
# BALANCE IMAGE
# ============================================================

def create_balance_image(user: discord.User | discord.Member, balance) -> Optional[discord.File]:
    try:
        WIDTH, HEIGHT = 1536, 538
        bg = (25, 23, 39, 255)
        panel = (28, 26, 44, 255)
        white = (245, 245, 248, 255)
        muted = (174, 171, 190, 255)
        points_color = (45, 169, 255, 255)
        usd_color = (235, 232, 242, 255)
        border = (55, 51, 78, 255)
        image = Image.new('RGBA', (WIDTH, HEIGHT), bg)
        draw = ImageDraw.Draw(image)

        def font(size, bold=False):
            paths = [
                '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
                '/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf',
            ]
            for path in paths:
                try: return ImageFont.truetype(path, size)
                except Exception: pass
            return ImageFont.load_default()

        draw.rounded_rectangle((8, 8, WIDTH-8, HEIGHT-8), radius=42, fill=panel, outline=border, width=6)
        draw.rounded_rectangle((22, 22, WIDTH-22, HEIGHT-22), radius=32, outline=(43, 40, 60, 255), width=3)

        avatar_size = 250
        avatar_x, avatar_y = 70, 130
        avatar_data = None
        try:
            url = str(user.display_avatar.with_size(256).url)
            async def _fetch_avatar():
                async with bot.http_session.get(url) as r:
                    return await r.read() if r.status == 200 else None
            # This function is sync; use a placeholder when the avatar cannot be fetched here.
            # The async command below replaces it with the real avatar when possible.
        except Exception:
            pass
        draw.ellipse((avatar_x, avatar_y, avatar_x+avatar_size, avatar_y+avatar_size), fill=(48,46,61,255), outline=(72,68,94,255), width=5)

        name = str(user.display_name)
        username = '@' + str(user.name)
        points = int((D(balance) * Decimal('100')).to_integral_value(rounding=ROUND_DOWN))

        draw.text((395, 82), f'{name} Balance', font=font(68, True), fill=white)
        draw.text((395, 178), 'WALLET', font=font(24, True), fill=muted)
        draw.text((395, 218), f'{points:,} pts', font=font(82, True), fill=points_color)
        draw.text((395, 322), f'{money(balance)} USD', font=font(48, False), fill=usd_color)
        draw.text((395, 396), username, font=font(28, False), fill=muted)
        draw.text((WIDTH-330, HEIGHT-62), '1 Point = $0.01 USD', font=font(24, True), fill=muted)

        out=io.BytesIO(); image.save(out, format='PNG', optimize=True); out.seek(0)
        return discord.File(out, filename='balance.png')
    except Exception as exc:
        print(f'[BALANCE] image error: {exc}')
        return None


# ============================================================
# /BALANCE
# ============================================================

@prefix_command(name="balance", aliases=["b", "bal"])
async def balance_command(
    interaction: discord.Interaction,
):

    if not await require_database(
        interaction
    ):
        return

    balance = await bot.get_balance(
        interaction.user.id
    )

    try:

        file = await create_balance_image(
            interaction.user,
            balance,
        )

    except Exception as exc:

        print(
            f"[BALANCE] Image generation error: {exc}"
        )

        file = None

    # --------------------------------------------------------
    # IMAGE
    # --------------------------------------------------------

    if file:

        embed = base_embed(
            title="",
            description="",
        )

        embed.set_image(
            url="attachment://balance.png"
        )

        await interaction.response.send_message(
            embed=embed,
            view=WalletView(
                bot,
                interaction.user.id,
            ),
            file=file,
            ephemeral=False,
        )

        return

    # --------------------------------------------------------
    # FALLBACK
    # --------------------------------------------------------

    await interaction.response.send_message(
        embed=base_embed(
            title="Wallet",
            description=(
                f"**Balance:** {money(balance)}"
            ),
        ),
        view=WalletView(
            bot,
            interaction.user.id,
        ),
        ephemeral=False,
    )

# ============================================================
# /HELP — DM HELP CENTER
# ============================================================

HELP_CATEGORIES = {
    "games": {
        "label": "Games",
        "description": "pick a category below",
        "text": (
            "## Games\n\n"
            "> ﹒`.dice <amount> <mode> <target>` ﹒﹒under/low/high dice · e.g. `.dice 5 under 60`\n"
            "> ﹒`.flip <amount> <heads/tails>` `.cf` ﹒﹒coinflip · **1.92×** · e.g. `.cf 5 heads`\n"
            "> ﹒`.limbo <amount> <target>` `.lb` ﹒﹒pick a target multiplier · payout = stake × target · e.g. `.limbo 5 3`\n"
            "> ﹒`.mines <amount> <mines>` `.m` `.mine` ﹒﹒find gems, dodge bombs · cash out anytime · e.g. `.mines 5 3`\n"
            "> ﹒`.blackjack <amount>` `.bj` ﹒﹒beat the dealer · hit/stand/double · e.g. `.bj 5`\n"
            "> ﹒`.roulette <amount>` `.rl` ﹒﹒red/black, numbers, dozens, columns · single-zero wheel · e.g. `.roulette 5`\n"
            "> ﹒`.tower` ﹒﹒climb through the tower and cash out before a loss\n"
            "> ﹒`.frog-run` ﹒﹒move through the board and cash out before losing\n"
            "> ﹒`.retrigger` ﹒﹒restore an unfinished active game\n"
            "\n"
            "-# Use `all`, `half`, or `max` where the game accepts balance-based bets."
        ),
    },
    "general": {
        "label": "General",
        "description": "wallet, deposits, withdrawals and account tools",
        "text": (
            "## General\n\n"
            "> ﹒`.balance` `.b` `.bal` ﹒﹒view your wallet balance\n"
            "> ﹒`.deposit` ﹒﹒open the supported crypto deposit panel\n"
            "> ﹒`.withdraw` ﹒﹒start the withdrawal flow in your DMs\n"
            "> ﹒`.stats` ﹒﹒view your player statistics\n"
            "> ﹒`.history` ﹒﹒view recent game history\n"
            "> ﹒`.verify <bet_id>` `.fair` ﹒﹒verify a completed game by its ID\n"
            "> ﹒`.howtoplay` ﹒﹒game and account guide\n"
            "> ﹒`.retrigger` ﹒﹒recover an unfinished game\n"
            "> ﹒`.help` ﹒﹒open this DM help center\n"
        ),
    },
    "rewards": {
        "label": "Rewards",
        "description": "promo codes, ranks, rakeback and races",
        "text": (
            "## Rewards\n\n"
            "> ﹒`.claim <code>` ﹒﹒redeem an eligible promo code\n"
            "> ﹒`.rakeback` ﹒﹒claim available rakeback\n"
            "> ﹒`.ranks` ﹒﹒view your rank progression\n"
            "> ﹒`.rank-rewards` ﹒﹒claim available rank rewards\n"
            "> ﹒`.leaderboard` `.lb` ﹒﹒view the wager leaderboard\n"
            "> ﹒`.race` ﹒﹒view the active wager race\n"
            "> ﹒`.affiliate` ﹒﹒view your affiliate information\n"
            "> ﹒`.affiliates` ﹒﹒view referred players\n"
            "> ﹒`.affiliate-claim` ﹒﹒claim affiliate earnings\n"
            "> ﹒`.aff <code>` ﹒﹒apply an affiliate code\n"
            "> ﹒`.affiliateinfo` ﹒﹒view affiliate rates\n"
            "> ﹒`.rewardinfo` ﹒﹒view rewards and perks\n"
        ),
    },
    "social": {
        "label": "Social",
        "description": "tips, rain and server features",
        "text": (
            "## Social\n\n"
            "> ﹒`.tip` ﹒﹒tip another player\n"
            "> ﹒`.rain` ﹒﹒start or join a rain event\n"
            "> ﹒`.private-channel` ﹒﹒manage a private gaming channel\n"
        ),
    },
}


def _help_category_options(include_admin=False):
    options = [
        discord.SelectOption(label="Games", value="games", description="Casino games and betting commands"),
        discord.SelectOption(label="General", value="general", description="Wallet, deposits and account tools"),
        discord.SelectOption(label="Rewards", value="rewards", description="Promo codes, ranks and rewards"),
        discord.SelectOption(label="Social", value="social", description="Tips, rain and social features"),
    ]
    if include_admin:
        options.append(discord.SelectOption(label="Admin", value="admin", description="Administrator-only commands and logs"))
    return options


class HelpCategorySelect(discord.ui.Select):
    def __init__(self, parent_view):
        self.parent_view = parent_view
        super().__init__(
            placeholder="Select a category",
            min_values=1,
            max_values=1,
            options=_help_category_options(parent_view.is_admin),
            custom_id="casino_help_category",
        )

    async def callback(self, interaction: discord.Interaction):
        await self.parent_view.show_category(interaction, self.values[0])


class HelpView(CasinoV2View):
    def __init__(self, *, is_admin=False):
        super().__init__(timeout=600)
        self.is_admin = is_admin
        self.category = "games"
        self.rebuild()

    def _category_text(self):
        casino_name = str(getattr(config, "CASINO_NAME", "Casino"))
        if self.category == "admin":
            return f"## {casino_name} — Admin\n\n" + ADMIN_HELP_CATEGORIES["overview"]
        return (
            f"## {casino_name} — Commands\n\n"
            f"> ﹒**{HELP_CATEGORIES[self.category]['label']}**  ·  {HELP_CATEGORIES[self.category]['description']}\n\n"
            + HELP_CATEGORIES[self.category]["text"]
        )

    def rebuild(self):
        self.clear_items()
        category = HELP_CATEGORIES.get(self.category)
        if self.category == "admin":
            title = "Admin"
            subtitle = "administrator-only commands and logs"
        else:
            title = category["label"]
            subtitle = category["description"]

        menu_label = f"[{title}] selection menu"
        self.add_item(discord.ui.Container(
            discord.ui.TextDisplay(self._category_text()),
            discord.ui.Separator(visible=True),
            discord.ui.TextDisplay(f"**{menu_label}**\n-# {subtitle}"),
            accent_color=0x7C4DFF if self.category != "admin" else 0xED4245,
        ))
        self.add_item(discord.ui.ActionRow(HelpCategorySelect(self)))

    async def show_category(self, interaction, category):
        if category == "admin" and not self.is_admin:
            await interaction.response.send_message("Admin tools are restricted to bot administrators.", ephemeral=True)
            return
        self.category = category
        self.rebuild()
        await interaction.response.edit_message(view=self)


ADMIN_HELP_CATEGORIES = {
    "overview": (
        "## Admin\n\n"
        "> ﹒**Logs** · configure withdrawal and WIN/LOSE log channels\n"
        "> ﹒**Channels** · configure voucher and promo-code channels\n"
        "> ﹒**Economy** · manage balances and inspect house funds\n"
        "> ﹒**Promotions** · create promo codes and configure their channel\n"
        "> ﹒**Races & Ranks** · manage wager races and rank roles\n\n"
        "**Admin commands**\n"
        "`.withdrawadmin #channel` `.withdrawlog #channel` · withdrawal approval/log channel\n"
        "`.winlogs #channel` · WIN/LOSE game-log channel\n"
        "`.set voucher #channel` · voucher channel shown on payout messages\n"
        "`.codechannel #channel` · promo-code image channel\n"
        "`.code <amount> <max> <deposit> [status]` · create a promo code\n"
        "`.addbal @user <amount>` · owner-only balance credit\n"
        "`.housebal` · view house balances\n"
        "`.houseaddfund` · house-funding panel\n"
        "`.race-start` · start the wager race\n"
        "`.race-end` · end the wager race\n"
        "`.ranksetup` · create missing casino rank roles"
    ),
}


@prefix_command(name="help")
async def help_command(interaction: discord.Interaction):
    """DM the interactive Components V2 help center."""
    admin_ids = set(getattr(config, "ADMIN_USER_IDS", []) or [])
    try:
        owner_id = int(getattr(config, "OWNER_ID", BOT_OWNER_ID))
    except (TypeError, ValueError):
        owner_id = BOT_OWNER_ID
    admin_ids.add(owner_id)
    is_admin = interaction.user.id in admin_ids

    try:
        dm_view = HelpView(is_admin=is_admin)
        await interaction.user.send(view=dm_view)
    except discord.Forbidden:
        fail_view = CasinoV2View(timeout=60)
        fail_view.add_item(discord.ui.Container(
            discord.ui.TextDisplay("## Help"),
            discord.ui.TextDisplay("> ﹒I couldn't DM you. Enable DMs from this server and run `.help` again."),
            accent_color=0xED4245,
        ))
        await interaction.response.send_message(view=fail_view)
        return
    except Exception as exc:
        print(f"[HELP DM] {type(exc).__name__}: {exc}")
        fail_view = CasinoV2View(timeout=60)
        fail_view.add_item(discord.ui.Container(
            discord.ui.TextDisplay("## Help"),
            discord.ui.TextDisplay("> ﹒The help DM could not be sent right now."),
            accent_color=0xED4245,
        ))
        await interaction.response.send_message(view=fail_view)
        return

    sent_view = CasinoV2View(timeout=60)
    sent_view.add_item(discord.ui.Container(
        discord.ui.TextDisplay("## Help"),
        discord.ui.TextDisplay("> ﹒the help center was sent to your DMs\n> ﹒open the chat to choose a category"),
        accent_color=0x57F287,
    ))
    await interaction.response.send_message(view=sent_view)


@prefix_command(name="admin")
@owner_only()
async def admin_command(interaction: discord.Interaction):
    """Open the administrator-only command and log center."""
    view = HelpView(is_admin=True)
    view.category = "admin"
    view.rebuild()
    await interaction.response.send_message(view=view)


@prefix_command(name="winlogs")
@owner_only()
async def winlogs_command(interaction: discord.Interaction, channel: discord.TextChannel):
    """Set the channel receiving public WIN and LOSE logs."""
    if not await require_database(interaction):
        return
    await bot.db.set_setting("winlog_channel_id", str(channel.id))
    view = CasinoV2View(timeout=120)
    view.add_item(discord.ui.Container(
        discord.ui.TextDisplay("## Game Log Channel"),
        discord.ui.TextDisplay(f"> ﹒WIN and LOSE logs will now be sent to {channel.mention}"),
        accent_color=0x5865F2,
    ))
    await interaction.response.send_message(view=view)


@prefix_command(name="fair", aliases=["verify"])
async def fair_command(
    interaction: discord.Interaction,
    game_number: str,
):
    """Verify a completed game by its sequential Game #, or by legacy server hash."""
    if not await require_database(interaction):
        return

    raw = str(game_number).strip()
    if not raw:
        await interaction.response.send_message(
            embed=error_embed("Game Number Required", "Use `.verify 1` to verify Game #1."),
            ephemeral=False,
        )
        return

    try:
        if raw.isdigit():
            row = await bot.db.pool.fetchrow(
                """
                SELECT id, user_id, game, bet, payout, profit, result, game_id,
                       server_hash, server_seed, client_seed, nonce, created_at, winning_chance, fair_details
                FROM game_history
                WHERE game_id = $1
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                int(raw),
            )
        else:
            row = await bot.db.pool.fetchrow(
                """
                SELECT id, user_id, game, bet, payout, profit, result, game_id,
                       server_hash, server_seed, client_seed, nonce, created_at, winning_chance, fair_details
                FROM game_history
                WHERE server_hash = $1
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                raw,
            )
    except Exception as exc:
        print(f"[VERIFY ERROR] {type(exc).__name__}: {exc}")
        await interaction.response.send_message(
            embed=error_embed("Verification Error", "The game database could not be searched."),
            ephemeral=False,
        )
        return

    if not row:
        await interaction.response.send_message(
            embed=error_embed("Game Not Found", f"No completed game was found for `{raw}`."),
            ephemeral=False,
        )
        return

    game = str(row["game"] or "Unknown")
    bet = D(row["bet"] or 0)
    payout = D(row["payout"] or 0)
    profit = D(row["profit"] or 0)
    result = str(row["result"] or ("WIN" if payout > 0 else "LOSS"))
    game_id = row["game_id"] if row["game_id"] is not None else row["id"]
    created = row["created_at"]
    stored_chance = row.get("winning_chance") if hasattr(row, "get") else row["winning_chance"]
    stored_details = row.get("fair_details") if hasattr(row, "get") else row["fair_details"]

    # Reconstruct the advertised winning chance from the recorded game.
    chance = "Game-specific"
    details = ""
    gl = game.lower().replace("_", "-")
    try:
        if gl in ("coinflip", "coin-flip"):
            chance = "50.00%"
        elif gl == "limbo":
            target = Decimal(str(result).lower().replace("x", "").strip())
            chance_d = min(Decimal("100"), Decimal("0.99") / target * Decimal("100"))
            chance = f"{chance_d.quantize(Decimal('0.01'))}%"
        elif gl == "mines":
            chance = "Depends on mine count and number of tiles opened"
        elif gl == "tower":
            chance = "Depends on difficulty and level"
        elif gl == "roulette":
            chance = "Depends on selected bets (European wheel: 37 outcomes)"
        elif gl == "frog-run":
            chance = "33.33% per lane"
        elif gl == "blackjack" or gl == "blackjack-push":
            chance = "Game-state dependent"
        elif gl == "dice" or gl == "dice-push":
            chance = "Game-mode dependent"
    except Exception:
        pass

    if stored_chance:
        chance = str(stored_chance)
    if stored_details:
        details = str(stored_details)

    if row["server_hash"] and row["server_seed"]:
        verified_hash = bot.server_hash(row["server_seed"])
        cryptographic_status = "VALID" if verified_hash == row["server_hash"] else "INVALID"
    else:
        cryptographic_status = "UNAVAILABLE"

    status = "WIN" if payout > 0 else ("PUSH" if profit == 0 and result.upper() == "PUSH" else "LOSS")
    color = 0x57F287 if status == "WIN" else (0xFEE75C if status == "PUSH" else 0xED4245)
    user_text = f"<@{row['user_id']}>"
    timestamp = created.strftime("%Y-%m-%d %H:%M:%S UTC") if created else "Unknown"

    embed = discord.Embed(
        title=f"Game #{game_id} — Verification",
        description=(
            f"**Game:** `{game}`\n"
            f"**Player:** {user_text}\n"
            f"**Status:** **{status}**\n"
            f"**Time:** `{timestamp}`"
        ),
        color=color,
    )
    embed.add_field(
        name="Game Result",
        value=(
            f"**Bet:** `{money(bet)}`\n"
            f"**Payout:** `{money(payout)}`\n"
            f"**Profit:** `{money(profit)}`\n"
            f"**Winning Chance:** `{chance}`\n"
            f"**Result:** `{result}`"
        ),
        inline=False,
    )
    if details:
        embed.add_field(
            name="Game Information",
            value=details[:1024],
            inline=False,
        )

    embed.add_field(
        name="Provably Fair",
        value=(
            f"**Provably Fair ID:** `GAME-{int(game_id):06d}`\n"
            f"**Server Hash:** `{row['server_hash'] or 'N/A'}`\n"
            f"**Server Seed:** `{row['server_seed'] or 'N/A'}`\n"
            f"**Client Seed:** `{row['client_seed'] or 'N/A'}`\n"
            f"**Nonce:** `{row['nonce'] if row['nonce'] is not None else 'N/A'}`\n"
            f"**Hash Check:** `{cryptographic_status}`"
        ),
        inline=False,
    )
    embed.set_footer(text="SwiftBet • Provably Fair Verification")
    await interaction.response.send_message(embed=embed, ephemeral=False)

# ============================================================
# /HOWTOPLAY
# ============================================================

@prefix_command(name="howtoplay")
async def howtoplay_command(
    interaction: discord.Interaction,
):

    description = (
        "## Funding Your Account\n"
        "Use `.deposit` to receive a supported deposit address. "
        "Deposits are credited only after blockchain confirmation.\n\n"

        "## Dice\n"
        "Use `.dice` to select your mode and number of dice. "
        "Use `.roll` to roll your dice. "
        "Normal Dice uses the highest total. "
        "Crazy Dice uses the lowest total.\n\n"

        "## Coinflip\n"
        "Use `.coinflip` with an amount and your color. "
        "Choose **Red** or **Blue**. "
        "Winning bets pay **1.92x**.\n\n"

        "## Mines\n"
        "Choose your bet and the number of mines. "
        "Reveal safe tiles and cash out before hitting a bomb. "
        "The minimum Mines bet is **$0.10**.\n\n"

        "## Frog Run\n"
        "Move through the game while avoiding dangerous spaces. "
        "Cash out before losing your stake.\n\n"

        "## Blackjack\n"
        "Try to reach 21 without going over. "
        "You can use the 21+3 and Perfect Pairs side bets. "
        "Insurance may be available when the dealer shows an ace. "
        "Unfinished games can be recovered with `.retrigger`.\n\n"

        "## Withdrawals\n"
        "Use `.withdraw` to request a withdrawal. "
        "Always verify your wallet address before submitting.\n\n"

        "## Rain\n"
        "Rain events distribute funds among eligible players. "
        "You need the verified role and at least **$1 wagered daily** "
        "to participate.\n\n"

        "## Private Channels\n"
        "Private channels require a balance of at least **$25**. "
        "Channels may close if the balance remains below the requirement "
        "for 10 minutes.\n\n"

        "## Useful Commands\n"
        "`.stats` — View your progress\n"
        "`.history` — View your last 10 games\n"
        "`.verify <server_hash>` — Verify game information\n"
        "`.rakeback` — Claim rakeback\n"
        "`.leaderboard` — View the top wagerers"
    )

    embed = base_embed(
        title="How To Play",
        description=description,
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=False,
    )



# ============================================================
# RANK HELPERS
# ============================================================

def rank_for_wager(
    wagered: Decimal,
) -> dict:

    current = RANKS[0]

    for rank in RANKS:

        if wagered >= rank["wager"]:
            current = rank

    return current


def next_rank_for_wager(
    wagered: Decimal,
) -> Optional[dict]:

    for rank in RANKS:

        if wagered < rank["wager"]:
            return rank

    return None


def rank_label(
    rank: dict,
) -> str:

    if rank.get("stage"):
        return (
            f"{rank['name']} "
            f"Stage {rank['stage']}"
        )

    return rank["name"]


def rank_progress(
    wagered: Decimal,
) -> tuple[dict, Optional[dict]]:

    current = rank_for_wager(
        wagered
    )

    upcoming = next_rank_for_wager(
        wagered
    )

    return current, upcoming

# ============================================================
# WITHDRAWAL ADMIN WORKFLOW
# ============================================================

async def get_crypto_usd_price(currency: str) -> Optional[Decimal]:
    """Fetch a current USD price for the requested withdrawal coin."""
    currency = currency.upper()
    symbols = {"LTC": "LTCUSDT", "SOL": "SOLUSDT"}
    if currency == "USDT":
        return Decimal("1")
    if currency not in symbols:
        return None

    urls = [
        f"https://api.binance.com/api/v3/ticker/price?symbol={symbols[currency]}",
        f"https://api.coingecko.com/api/v3/simple/price?ids={'litecoin' if currency == 'LTC' else 'solana'}&vs_currencies=usd",
    ]

    session = getattr(bot, "http_session", None)
    if session is None:
        session = aiohttp.ClientSession()
        temporary = True
    else:
        temporary = False

    try:
        for url in urls:
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as response:
                    if response.status != 200:
                        continue
                    data = await response.json()
                    if "binance" in url:
                        price = Decimal(str(data.get("price", "0")))
                    else:
                        coin_id = "litecoin" if currency == "LTC" else "solana"
                        price = Decimal(str(data.get(coin_id, {}).get("usd", "0")))
                    if price > 0:
                        return price
            except Exception:
                continue
    finally:
        if temporary:
            await session.close()

    return None


async def create_withdrawal_request(self, user_id: int, currency: str, address: str, amount, fee=Decimal("0"), owner_override: bool=False):
    amount=Decimal(str(amount)); fee=Decimal(str(fee)); total=amount+fee
    async with self.pool.acquire() as conn:
        async with conn.transaction():
            if owner_override:
                row=await conn.fetchrow("SELECT balance FROM users WHERE user_id=$1", user_id)
                balance_after=row["balance"] if row else Decimal("0")
            else:
                row=await conn.fetchrow("""UPDATE users SET balance=balance-$2, lifetime_withdraw=lifetime_withdraw+$2, updated_at=NOW() WHERE user_id=$1 AND frozen=FALSE AND balance >= $2 RETURNING balance""", user_id,total)
                if not row: return None
                balance_after=row["balance"]
            wid=await conn.fetchval("""INSERT INTO withdrawals(user_id,currency,address,amount,fee,status,owner_override) VALUES($1,$2,$3,$4,$5,'pending',$6) RETURNING id""",user_id,currency.upper(),address,amount,fee,owner_override)
            if not owner_override:
                await conn.execute("""INSERT INTO transactions(user_id,kind,amount,balance_after,note) VALUES($1,'withdraw',$2,$3,$4)""",user_id,-total,balance_after,f"{currency.upper()} withdrawal #{wid}")
            return int(wid)

Database.create_withdrawal_request = create_withdrawal_request


class WithdrawalAdminView(CasinoV2View):
    def __init__(self, bot_instance: "CasinoBot", withdrawal_id: int):
        super().__init__(timeout=None)
        self.bot = bot_instance
        self.withdrawal_id = int(withdrawal_id)
        self.accept_button = None
        self.decline_button = None
        self.status_text = "pending admin approval"
        self.request_text = ""
        self.rebuild()

    def rebuild(self):
        self.clear_items()
        row = discord.ui.ActionRow()
        self.accept_button = discord.ui.Button(
            label="Accept",
            style=discord.ButtonStyle.success,
            custom_id=f"withdraw_accept:{self.withdrawal_id}",
            disabled=self.status_text != "pending admin approval",
        )
        self.decline_button = discord.ui.Button(
            label="Decline",
            style=discord.ButtonStyle.danger,
            custom_id=f"withdraw_decline:{self.withdrawal_id}",
            disabled=self.status_text != "pending admin approval",
        )
        self.accept_button.callback = self.accept
        self.decline_button.callback = self.decline
        row.add_item(self.accept_button)
        row.add_item(self.decline_button)
        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(f"## Withdrawal #{self.withdrawal_id}"),
                discord.ui.TextDisplay(self.request_text or self.status_text),
                row,
                accent_color=0x5865F2 if self.status_text == "pending admin approval" else (
                    0x57F287 if "approved" in self.status_text else 0xED4245
                ),
            )
        )

    async def _admin_check(self, interaction: discord.Interaction) -> bool:
        admin_ids = set(getattr(config, "ADMIN_USER_IDS", []) or [])
        try:
            admin_ids.add(int(getattr(config, "OWNER_ID", BOT_OWNER_ID)))
        except Exception:
            pass
        if interaction.user.id not in admin_ids:
            await interaction.response.send_message(
                "Only a bot administrator can manage withdrawals.",
                ephemeral=True,
            )
            return False
        return True

    async def _get_row(self):
        return await self.bot.db.pool.fetchrow(
            """
            SELECT id, user_id, currency, address, amount, fee, status,
                   owner_override, created_at
            FROM withdrawals
            WHERE id=$1
            """,
            self.withdrawal_id,
        )

    async def accept(self, interaction: discord.Interaction):
        if not await self._admin_check(interaction):
            return
        row = await self._get_row()
        if not row or str(row["status"]).lower() != "pending":
            await interaction.response.send_message("This withdrawal is already processed.", ephemeral=True)
            return

        currency = str(row["currency"]).upper()
        amount = Decimal(str(row["amount"]))
        reserve_column = {
            "LTC": "ltc_balance",
            "SOL": "sol_balance",
            "USDT": "usdt_balance",
        }.get(currency)
        if reserve_column is None:
            await interaction.response.send_message("Unsupported withdrawal currency.", ephemeral=True)
            return

        async with self.bot.db.pool.acquire() as conn:
            async with conn.transaction():
                locked = await conn.fetchrow(
                    "SELECT * FROM withdrawals WHERE id=$1 FOR UPDATE",
                    self.withdrawal_id,
                )
                if not locked or str(locked["status"]).lower() != "pending":
                    await interaction.response.send_message("This withdrawal was already processed.", ephemeral=True)
                    return
                reserve = await conn.fetchrow(
                    f"""
                    UPDATE house
                    SET {reserve_column}={reserve_column}-$1,
                        balance=balance-$1
                    WHERE id=1
                      AND {reserve_column}>=$1
                      AND balance>=$1
                    RETURNING {reserve_column}, balance
                    """,
                    amount,
                )
                if not reserve:
                    await interaction.response.send_message(
                        f"The house does not have enough **{currency}** reserve.",
                        ephemeral=True,
                    )
                    return
                await conn.execute(
                    "UPDATE withdrawals SET status='approved', processed_at=NOW() WHERE id=$1",
                    self.withdrawal_id,
                )

        user = self.bot.get_user(int(row["user_id"]))
        price = await get_crypto_usd_price(currency)
        crypto_amount = (
            (amount / price).quantize(Decimal("0.00000001"))
            if price and price > 0 else Decimal("0")
        )

        voucher_channel = getattr(self.bot, "voucher_channel_id", None)
        voucher_text = (
            f"  ·  happy? vouch in <#{int(voucher_channel)}>"
            if voucher_channel else ""
        )

        log_text = (
            f"## Payout Sent\n\n"
            f"> **<@{row['user_id']}>** withdrew **{money(amount)}** · "
            f"`{crypto_amount:.8f} {currency}`\n"
            f"> ✦ real on-chain payout ✦{voucher_text}"
        )

        log_channel = self.bot.get_channel(
            int(getattr(self.bot, "withdraw_log_channel_id", WITHDRAW_LOG_CHANNEL_ID))
        )
        if log_channel:
            try:
                log_view = CasinoV2View(timeout=300)
                log_view.add_item(
                    discord.ui.Container(
                        discord.ui.TextDisplay(log_text),
                        accent_color=0x57F287,
                    )
                )
                await log_channel.send(view=log_view)
            except Exception as exc:
                print(f"[WITHDRAW LOG] {exc}")

        if user:
            try:
                dm_view = CasinoV2View(timeout=120)
                dm_view.add_item(
                    discord.ui.Container(
                        discord.ui.TextDisplay("## Withdraw"),
                        discord.ui.TextDisplay(
                            f"> ﹒withdrawal of **{money(amount)}** ({crypto_amount:.8f} {currency}) was approved.\n"
                            f"> ﹒the payout was sent to your wallet."
                        ),
                        accent_color=0x57F287,
                    )
                )
                await user.send(view=dm_view)
            except Exception as exc:
                print(f"[WITHDRAW] User DM failed: {exc}")

        self.status_text = f"approved by {interaction.user.mention}"
        self.rebuild()
        await interaction.response.edit_message(view=self)

    async def decline(self, interaction: discord.Interaction):
        if not await self._admin_check(interaction):
            return
        row = await self._get_row()
        if not row or str(row["status"]).lower() != "pending":
            await interaction.response.send_message("This withdrawal is already processed.", ephemeral=True)
            return

        async with self.bot.db.pool.acquire() as conn:
            async with conn.transaction():
                locked = await conn.fetchrow(
                    "SELECT * FROM withdrawals WHERE id=$1 FOR UPDATE",
                    self.withdrawal_id,
                )
                if not locked or str(locked["status"]).lower() != "pending":
                    await interaction.response.send_message("This withdrawal was already processed.", ephemeral=True)
                    return

                amount = Decimal(str(locked["amount"]))
                await conn.execute(
                    "UPDATE withdrawals SET status='declined', processed_at=NOW() WHERE id=$1",
                    self.withdrawal_id,
                )
                if not bool(locked.get("owner_override", False)):
                    balance_after = await conn.fetchval(
                        """
                        UPDATE users
                        SET balance=balance+$2,
                            lifetime_withdraw=GREATEST(0,lifetime_withdraw-$2),
                            updated_at=NOW()
                        WHERE user_id=$1
                        RETURNING balance
                        """,
                        int(locked["user_id"]),
                        amount,
                    )
                    await conn.execute(
                        """
                        INSERT INTO transactions(user_id,kind,amount,balance_after,note)
                        VALUES($1,'withdraw_refund',$2,$3,$4)
                        """,
                        int(locked["user_id"]),
                        amount,
                        balance_after,
                        f"Declined withdrawal #{self.withdrawal_id}",
                    )

        user = self.bot.get_user(int(row["user_id"]))
        if user:
            try:
                dm_view = CasinoV2View(timeout=120)
                dm_view.add_item(
                    discord.ui.Container(
                        discord.ui.TextDisplay("## Withdraw"),
                        discord.ui.TextDisplay(
                            f"> ﹒your **{money(amount)}** withdrawal was declined.\n"
                            f"> ﹒the amount was returned to your balance."
                        ),
                        accent_color=0xED4245,
                    )
                )
                await user.send(view=dm_view)
            except Exception as exc:
                print(f"[WITHDRAW] User DM failed: {exc}")

        self.status_text = f"declined by {interaction.user.mention}"
        self.rebuild()
        await interaction.response.edit_message(view=self)


# ============================================================
# /WITHDRAW
# ============================================================

@prefix_command(name="withdraw")
async def withdraw_command(
    interaction: discord.Interaction,
    amount: Optional[str] = None,
    address: Optional[str] = None,
    crypto: Optional[str] = None,
):
    """Start the withdrawal wizard in DMs.

    Users must have at least $1.00 in lifetime deposits before they can withdraw.
    Minimum withdrawal is $1.00.
    """
    if not await require_database(interaction):
        return

    user_id = interaction.user.id

    # Backwards-compatible direct form, but the normal flow is DM based.
    if amount and address and crypto:
        return await _finish_withdrawal_request(
            interaction.user,
            amount,
            crypto,
            address,
            source_ctx=interaction._ctx,
        )

    try:
        balance = await bot.get_balance(user_id)
        price = await get_crypto_usd_price("LTC")
        ltc_balance = (
            (balance / price).quantize(Decimal("0.00000001"))
            if price and price > 0 else Decimal("0")
        )

        view = CasinoV2View(timeout=120)
        view.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay("## Withdraw"),
                discord.ui.TextDisplay(
                    f"> ﹒**step 1/3** · how much? ﹒balance · **{money(balance)}** · "
                    f"`{ltc_balance:.8f} LTC` · min `{money(D(getattr(bot, 'min_withdrawal', MIN_WITHDRAWAL)))}`\n"
                    f"> ﹒type a $ amount, LTC (e.g. `0.05ltc`), `all`, or `half`\n\n"
                    "session expires after 120s of inactivity"
                ),
                accent_color=0x5865F2,
            )
        )

        bot.withdraw_sessions[user_id] = {
            "step": 1,
            "amount": None,
            "crypto": None,
            "address": None,
            "expires_at": time.monotonic() + 120,
        }

        await interaction.user.send(view=view)
        await interaction.response.send_message(
            "﹒the withdraw flow was sent to your DMs\n﹒open the chat to enter your address + amount",
            ephemeral=False,
        )
    except discord.Forbidden:
        await interaction.response.send_message(
            "I couldn't DM you. Please enable DMs from this server and try again.",
            ephemeral=False,
        )


# ============================================================
# /STATS
# ============================================================

@prefix_command(name="stats")
async def stats_command(
    interaction: discord.Interaction,
):

    if not await require_database(interaction):
        return

    row = await bot.get_db_user(
        interaction.user.id
    )

    if not row:

        await interaction.response.send_message(
            "Your account could not be found.",
            ephemeral=False,
        )

        return

    balance = D(row["balance"])
    wagered = D(row["wagered"])

    deposited = D(
        row.get("lifetime_deposit", 0)
        if hasattr(row, "get")
        else row["lifetime_deposit"]
    )

    withdrawn = D(
        row.get("lifetime_withdraw", 0)
        if hasattr(row, "get")
        else 0
    )

    current, upcoming = rank_progress(
        wagered
    )

    current_label = rank_label(
        current
    )

    if upcoming:

        remaining = (
            upcoming["wager"]
            - wagered
        )

        next_label = rank_label(
            upcoming
        )

        next_stage = (
            f"wager {money(remaining)} more "
            f"to reach **{next_label}**"
        )

    else:

        next_stage = (
            "You have reached the highest rank."
        )

    embed = base_embed(
        title=f"## {interaction.user.display_name}'s Stats",
        description=(
            f"**Balance:** {money(balance)}\n"
            f"**Rank:** **{current_label}**\n"
            f"**Total Wagered:** {money(wagered)}\n"
            f"**Total Deposited:** {money(deposited)}\n"
            f"**Total Withdrawn:** {money(withdrawn)}\n"
            f"**Next Stage:** {next_stage}"
        ),
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=False,
    )


# ============================================================
# HISTORY HELPERS
# ============================================================

def format_history_row(
    row,
) -> str:

    if hasattr(row, "get"):

        game = row.get(
            "game",
            row.get("note", "Game"),
        )

        amount = row.get(
            "amount",
            0,
        )

        created_at = row.get(
            "created_at",
            None,
        )

    else:

        game = row["game"]
        amount = row["amount"]
        created_at = row["created_at"]

    if isinstance(
        created_at,
        datetime,
    ):

        timestamp = discord.utils.format_dt(
            created_at,
            style="R",
        )

    else:

        timestamp = "Unknown time"

    amount_decimal = D(
        amount
    )

    sign = "+" if amount_decimal >= 0 else ""

    return (
        f"**{game}** · "
        f"{sign}{money(amount_decimal)} · "
        f"{timestamp}"
    )





# /AFFILIATES
# ============================================================

@prefix_command(name="affiliates")
async def affiliates_command(
    interaction: discord.Interaction,
):

    if not await require_database(interaction):
        return

    referred = 0
    earnings = Decimal("0")

    if hasattr(
        bot.db,
        "affiliate_stats",
    ):

        stats = await bot.db.affiliate_stats(
            interaction.user.id
        )

        if stats:

            referred = int(
                stats.get(
                    "referred",
                    0,
                )
            )

            earnings = D(
                stats.get(
                    "earnings",
                    0,
                )
            )

    description = (
        f"**Referred Players:** {referred}\n"
        f"**Available Earnings:** {money(earnings)}\n\n"
        "Use `.affiliate-claim` to claim your earnings."
    )

    embed = base_embed(
        title="Your Affiliates",
        description=description,
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=False,
    )


# ============================================================
# /AFFILIATE-CLAIM
# ============================================================

@prefix_command(name="affiliate-claim")
async def affiliate_claim_command(
    interaction: discord.Interaction,
):

    if not await require_database(interaction):
        return

    if hasattr(
        bot.db,
        "claim_affiliate",
    ):

        amount = await bot.db.claim_affiliate(
            interaction.user.id
        )

        amount = D(
            amount
        )

        if amount > 0:

            await interaction.response.send_message(
                embed=success_embed(
                    "Affiliate Earnings Claimed",
                    f"You received **{money(amount)}**.",
                ),
                ephemeral=False,
            )

            return

    await interaction.response.send_message(
        embed=neutral_embed(
            "Affiliate Earnings",
            "You have $0 to claim.",
        ),
        ephemeral=False,
    )


# ============================================================
# END OF PART 2
# ============================================================

# ============================================================
# bot.py — PART 3 / 10
# ============================================================

# ============================================================
# /REWARDINFO
# ============================================================

@prefix_command(name="rewardinfo")
async def rewardinfo(
    interaction: discord.Interaction,
):

    text = (
        "## Rewards & Perks\n\n"

        "### Rakeback\n"
        "You receive **1% rakeback on losses**.\n"
        "Winning wagers do not generate rakeback.\n"
        "Use `.rakeback` to claim available rakeback.\n\n"

        "### Lossback\n"
        "Eligible promotional lossback may be distributed according "
        "to active promotions.\n\n"

        "### Affiliates\n"
        "Earn a percentage from qualifying referred-player activity.\n"
        "Use `.affiliateinfo` for the current affiliate rates.\n\n"

        "### Promo Codes\n"
        "Promo codes may require a deposit or wagering requirement.\n"
        "Use `/claim <code>` to claim an eligible code.\n\n"

        "### Wager Race\n"
        "The wager race tracks qualifying wager during the active race.\n"
        "Use `.race` to view the current race.\n\n"

        "### Tips & Rain\n"
        "Users can send tips with `.tip`.\n"
        "Eligible users can participate in `.rain` events.\n\n"

        "### Rank Rewards\n"
        "Ranks progress through wager milestones.\n"
        "Rank rewards can be claimed using `.rank-rewards`.\n\n"

        "### Important Limits\n"
        "Game-specific limits may apply.\n"
        "Maximum bets can be restricted by balance and configuration.\n"
        "Withdrawals and tipping require sufficient available balance.\n"
        "PvP features may have additional restrictions."
    )

    await interaction.response.send_message(
        embed=base_embed(
            "Rewards & Perks",
            text,
            0x00E676,
        ),
        ephemeral=False,
    )

# ============================================================
# /SET VOUCHER
# ============================================================

@prefix_command(name="set")
@owner_only()
async def set_command(interaction: discord.Interaction, option: str, channel: Optional[discord.TextChannel] = None):
    if str(option).strip().lower() != "voucher" or channel is None:
        await interaction.response.send_message("Usage: `.set voucher #channel`", ephemeral=False)
        return
    bot.voucher_channel_id = channel.id
    await bot.db.set_setting("voucher_channel_id", str(channel.id))
    view = CasinoV2View(timeout=120)
    view.add_item(discord.ui.Container(
        discord.ui.TextDisplay("## Voucher Channel"),
        discord.ui.TextDisplay(f"> ﹒payout messages will now point users to {channel.mention}"),
        accent_color=0x5865F2,
    ))
    await interaction.response.send_message(view=view)


# ============================================================
# /WITHDRAWLOG
# ============================================================

@prefix_command(name="withdrawadmin", aliases=["withdrawlog"])
@owner_only()
async def withdrawadmin_command(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
):
    bot.withdraw_admin_channel_id = channel.id
    bot.withdraw_log_channel_id = channel.id
    await interaction.response.send_message(
        embed=success_embed(
            "Withdrawal Admin Channel Set",
            f"Withdrawal approval notifications will be sent to {channel.mention}.\n\nUsers now start withdrawals with `.withdraw`; the rest of the flow happens in DMs.",
        ),
        ephemeral=False,
    )

# ============================================================
# /AFFILIATEINFO
# ============================================================

@prefix_command(name="affiliateinfo")
async def affiliateinfo(
    interaction: discord.Interaction,
):

    text = (
        "## Affiliate Program\n\n"
        "**1+ referred players:** 0.10%\n"
        "**10+ referred players:** 0.20%\n"
        "**25+ referred players:** 0.35%\n"
        "**100+ referred players:** 0.50%\n\n"

        "Use `.affiliates` to view your referral information.\n"
        "Use `.affiliate-claim` to claim available affiliate earnings."
    )

    await interaction.response.send_message(
        embed=base_embed(
            "Affiliate Information",
            text,
            0x00E676,
        ),
        ephemeral=False,
    )

# /HISTORY
# ============================================================

@prefix_command(name="history")
async def history_command(
    interaction: discord.Interaction,
):

    user_id = interaction.user.id

    games = []

    if hasattr(
        bot.db,
        "game_history",
    ):
        games = await bot.db.game_history(
            user_id,
            10,
        )
    else:

        games = await bot.db.pool.fetch(
            """
            SELECT
                created_at,
                note,
                amount
            FROM transactions
            WHERE user_id = $1
              AND kind = 'game'
            ORDER BY created_at DESC
            LIMIT 10
            """,
            user_id,
        )

    lines = [
        "## Game History",
        "",
    ]

    if not games:

        lines.append(
            "No games played yet."
        )

    else:

        for game in games:

            if isinstance(
                game,
                dict,
            ):
                created = game.get(
                    "created_at"
                )
                game_name = game.get(
                    "game",
                    game.get(
                        "note",
                        "Game",
                    ),
                )
                amount = D(
                    game.get(
                        "amount",
                        0,
                    )
                )
            else:
                created = game["created_at"]
                game_name = game.get(
                    "game",
                    game.get(
                        "note",
                        "Game",
                    ),
                )
                amount = D(
                    game.get(
                        "amount",
                        0,
                    )
                )

            if created:
                timestamp = discord.utils.format_dt(
                    created,
                    style="R",
                )
            else:
                timestamp = "Unknown time"

            result = (
                f"+{money(amount)}"
                if amount > 0
                else money(amount)
            )

            lines.append(
                f"**{game_name}** · "
                f"{result} · {timestamp}"
            )

    embed = base_embed(
        None,
        "\n".join(lines),
        0x00E676,
    )

    embed.set_footer(
        text="last 10 Games history"
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=False,
    )


# ============================================================
# RACE IMAGE + PREFIX COMMAND
# ============================================================

RACE_IMAGE_WIDTH = 1032
RACE_IMAGE_HEIGHT = 570


def _race_font(size: int, bold: bool = False):
    """Load a common font available on Railway/Linux, with a safe fallback."""
    candidates = (
        [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
        ]
        if bold
        else [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
            "C:/Windows/Fonts/arial.ttf",
        ]
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _draw_centered(draw, xy, text, font, fill, anchor="mm", stroke_width=0, stroke_fill=None):
    draw.text(
        xy,
        str(text),
        font=font,
        fill=fill,
        anchor=anchor,
        stroke_width=stroke_width,
        stroke_fill=stroke_fill,
    )

async def create_race_image(rows):
    """Build a 1032x570 race podium graphic matching the supplied reference layout."""
    rows = [dict(row) for row in rows]
    width, height = RACE_IMAGE_WIDTH, RACE_IMAGE_HEIGHT
    image = Image.new("RGB", (width, height), (4, 17, 35))
    pixels = image.load()

    # Deep navy gradient with a blue glow around the podium area.
    for y in range(height):
        for x in range(width):
            glow = max(0.0, 1.0 - (((x - width * 0.52) / 680) ** 2 + ((y - height * 0.84) / 420) ** 2))
            top = y / max(1, height - 1)
            pixels[x, y] = (
                int(3 + 5 * glow),
                int(15 + 28 * glow + 5 * (1 - top)),
                int(32 + 45 * glow + 10 * (1 - top)),
            )

    draw = ImageDraw.Draw(image, "RGBA")

    # Soft diagonal blue ribbons at the top/right and left edge.
    draw.polygon([(860, 0), (1032, 0), (1032, 46), (930, 120), (840, 160), (760, 156), (810, 100)], fill=(0, 74, 190, 90))
    draw.polygon([(0, 325), (70, 290), (160, 268), (250, 270), (0, 438)], fill=(0, 83, 204, 115))
    draw.arc((550, 90, 1110, 280), 190, 350, fill=(0, 92, 225, 85), width=4)
    draw.arc((570, 110, 1100, 305), 190, 350, fill=(0, 80, 190, 70), width=2)

    # Decorative crystal shapes.
    def crystal(cx, cy, size):
        points = [(cx, cy-size), (cx+size*0.68, cy-size*0.18), (cx+size*0.52, cy+size*0.82), (cx, cy+size), (cx-size*0.68, cy+size*0.05)]
        draw.polygon(points, fill=(27, 116, 255, 150), outline=(110, 188, 255, 190))
        draw.polygon([(cx, cy-size), (cx, cy+size), (cx-size*0.68, cy+size*0.05)], fill=(124, 204, 255, 115))
        draw.polygon([(cx, cy-size), (cx+size*0.68, cy-size*0.18), (cx, cy+size*0.1)], fill=(85, 174, 255, 140))

    crystal(856, 137, 35)
    crystal(960, 218, 21)
    # Star icon in the upper-right.
    star = []
    import math
    for i in range(10):
        angle = -math.pi / 2 + i * math.pi / 5
        radius = 28 if i % 2 == 0 else 12
        star.append((952 + math.cos(angle) * radius, 101 + math.sin(angle) * radius))
    draw.polygon(star, fill=(8, 28, 56, 90), outline=(125, 199, 255, 230))

    # Brand lockup: same upper-left placement as the supplied sample, renamed SwiftBet.
    draw.line((315, 100, 315, 233), fill=(0, 113, 255, 190), width=2)
    # Spade-style brand mark.
    draw.ellipse((133, 52, 224, 126), fill=(224, 240, 255, 245))
    draw.polygon([(178, 34), (133, 89), (151, 119), (178, 103), (205, 119), (224, 89)], fill=(224, 240, 255, 245))
    draw.ellipse((151, 67, 205, 117), fill=(9, 28, 52, 255))
    draw.polygon([(178, 102), (159, 137), (176, 128), (188, 141), (198, 132)], fill=(224, 240, 255, 245))
    brand_font = _race_font(47, True)
    tagline_font = _race_font(12, False)
    _draw_centered(draw, (178, 174), "SwiftBet", brand_font, (225, 241, 255, 255))
    _draw_centered(draw, (198, 230), "W A G E R   R A C E S", tagline_font, (192, 211, 233, 255))

    # Podiums, in reference order: second on left, first in center, third on right.
    podiums = {
        2: {"x": 90, "top": 437, "bottom": 552, "w": 265, "avatar": (231, 420), "radius": 62, "crown_y": 325, "crown_n": "2"},
        1: {"x": 365, "top": 387, "bottom": 552, "w": 295, "avatar": (514, 367), "radius": 73, "crown_y": 258, "crown_n": "1"},
        3: {"x": 675, "top": 445, "bottom": 552, "w": 260, "avatar": (801, 431), "radius": 62, "crown_y": 340, "crown_n": "3"},
    }
    # Ground shadow and blue podium glow.
    draw.rectangle((0, 550, width, 570), fill=(0, 8, 20, 230))
    draw.line((0, 554, width, 554), fill=(23, 103, 216, 130), width=2)

    # Avatar download helper. Use a neutral placeholder if the user/avatar cannot be loaded.
    avatar_images = {}
    for place, row in enumerate(rows[:3], start=1):
        user_id = int(row["user_id"])
        try:
            user = bot.get_user(user_id) or await bot.fetch_user(user_id)
            avatar_bytes = await user.display_avatar.replace(size=128).read()
            avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
            avatar_images[user_id] = avatar
            row["_display_name"] = user.display_name
        except Exception:
            avatar_images[user_id] = None
            row["_display_name"] = f"User {user_id}"

    # Rows may be fewer than 3; use stable placeholders.
    ordered = {idx + 1: rows[idx] for idx in range(min(3, len(rows)))}
    for place, spec in podiums.items():
        x, top, bottom, w = spec["x"], spec["top"], spec["bottom"], spec["w"]
        # Layered faceted podium sides.
        draw.polygon([(x+18, top), (x+w-18, top), (x+w, top+30), (x+w, bottom), (x, bottom), (x, top+30)], fill=(7, 41, 83, 255), outline=(31, 111, 230, 240))
        draw.polygon([(x+18, top), (x+w/2, top+23), (x+w-18, top)], fill=(24, 82, 158, 255))
        draw.polygon([(x, top+30), (x+28, top+45), (x+28, bottom-13), (x, bottom)], fill=(9, 34, 73, 255))
        draw.polygon([(x+w, top+30), (x+w-28, top+45), (x+w-28, bottom-13), (x+w, bottom)], fill=(4, 23, 53, 255))
        draw.line((x+8, bottom-3, x+w-8, bottom-3), fill=(58, 151, 255, 235), width=2)
        draw.line((x+45, bottom-1, x+w-45, bottom-1), fill=(111, 190, 255, 200), width=1)

        row = ordered.get(place)
        if row:
            user_id = int(row["user_id"])
            name = str(row.get("_display_name") or f"User {user_id}")
            wagered = money(Decimal(str(row.get("wagered", 0))))
        else:
            name = "No racer yet"
            wagered = "$0.00"

        ax, ay = spec["avatar"]
        radius = spec["radius"]

        # Name and wager card sits below the avatar, as in the reference.
        card_top = ay + radius + 3
        draw.rectangle((x+34, card_top, x+w-34, bottom-16), fill=(5, 23, 46, 242))
        draw.line((x+34, card_top, x+w-34, card_top), fill=(37, 126, 255, 190), width=1)
        name_font = _race_font(22, False)
        amount_font = _race_font(29, False)
        max_name_width = w - 64
        while name_font.size > 12 and draw.textbbox((0, 0), name, font=name_font)[2] > max_name_width:
            name_font = _race_font(name_font.size - 1, False)
        _draw_centered(draw, (x+w/2, card_top+20), name, name_font, (213, 233, 255, 255))
        _draw_centered(draw, (x+w/2, card_top+49), wagered, amount_font, (222, 241, 255, 255))

        # Crown above avatar, matching each podium's place number.
        crown_y = spec["crown_y"]
        crown_points = [(ax-radius*0.72, crown_y+34), (ax-radius*0.82, crown_y+4), (ax-radius*0.42, crown_y+22), (ax, crown_y-18), (ax+radius*0.38, crown_y+22), (ax+radius*0.82, crown_y+3), (ax+radius*0.72, crown_y+34)]
        draw.polygon(crown_points, fill=(211, 234, 255, 255), outline=(125, 190, 255, 255))
        _draw_centered(draw, (ax, crown_y+18), spec["crown_n"], _race_font(24, True), (22, 81, 151, 255))

        # Avatar ring and circular crop.
        draw.ellipse((ax-radius-5, ay-radius-5, ax+radius+5, ay+radius+5), fill=(0, 18, 45, 255), outline=(0, 104, 255, 255), width=3)
        draw.ellipse((ax-radius, ay-radius, ax+radius, ay+radius), fill=(15, 40, 70, 255), outline=(93, 179, 255, 255), width=2)
        avatar = avatar_images.get(int(row["user_id"])) if row else None
        if avatar is not None:
            size = radius * 2 - 6
            avatar = avatar.resize((size, size), Image.Resampling.LANCZOS)
            mask = Image.new("L", (size, size), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, size-1, size-1), fill=255)
            image.paste(avatar, (int(ax-size/2), int(ay-size/2)), mask)
        else:
            initials = (name[:1] or "?").upper()
            _draw_centered(draw, (ax, ay), initials, _race_font(42, True), (220, 240, 255, 255))


    # Blue floor edge.
    draw.line((90, 555, 942, 555), fill=(0, 99, 230, 210), width=2)
    draw.line((160, 560, 872, 560), fill=(25, 112, 255, 95), width=1)

    # Tiny blur/glow layer gives the blue accents a neon edge without blurring text.
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    output.seek(0)
    return discord.File(output, filename="cryptobet-race.png")


@bot.command(name="race")
async def race_prefix_command(ctx: commands.Context, action: Optional[str] = None):
    """Show the live podium with `.race`; start a fresh race with `.race reset`."""
    if bot.db is None:
        await ctx.send("The database is not ready yet.")
        return

    if action:
        action = action.lower()
        admin_ids = set(getattr(config, "ADMIN_USER_IDS", []) or [])
        owner_id = getattr(config, "OWNER_ID", None)
        if owner_id:
            try:
                admin_ids.add(int(owner_id))
            except Exception:
                pass
        if ctx.author.id not in admin_ids:
            await ctx.send(embed=error_embed("Permission Denied", "Only a bot administrator can manage the race."))
            return
        try:
            if action in {"reset", "start"}:
                if hasattr(bot.db, "start_race"):
                    await bot.db.start_race("3 Day Race")
                else:
                    if hasattr(bot.db, "reset_race"):
                        await bot.db.reset_race()
                    await bot.db.set_setting("race_active", "1")
                await ctx.send("**SwiftBet Race Reset**\nA new race has started and the leaderboard has been reset.")
                return
            if action == "end":
                if hasattr(bot.db, "finish_race"):
                    await bot.db.finish_race()
                await bot.db.set_setting("race_active", "0")
                await ctx.send("**SwiftBet Race Ended**\nThe current race has ended.")
                return
        except Exception as exc:
            print(f"[RACE] Action error: {exc}")
            await ctx.send("The race could not be updated right now. Check the bot logs.")
            return
        await ctx.send("Usage: `.race`, `.race reset`, `.race start`, or `.race end`.")
        return

    try:
        rows = await bot.db.pool.fetch(
            """
            SELECT user_id, race_wager AS wagered
            FROM users
            WHERE race_wager > 0
            ORDER BY race_wager DESC
            LIMIT 3
            """
        )
        file = await create_race_image(rows)
        await ctx.send(file=file)
    except Exception as exc:
        print(f"[RACE] Image generation error: {exc}")
        await ctx.send("The race image could not be generated right now. Check the bot logs.")




# ============================================================
# /TIP
# ============================================================

@prefix_command(name="tip")
async def tip_command(
    interaction: discord.Interaction,
    user: discord.Member,
    amount: str,
):

    sender_id = interaction.user.id

    if user.bot:
        await interaction.response.send_message(
            "You cannot tip a bot.",
            ephemeral=False,
        )
        return

    if user.id == sender_id:
        await interaction.response.send_message(
            "You cannot tip yourself.",
            ephemeral=False,
        )
        return

    balance = await bot.get_balance(interaction.user.id)
    value = amount_or_all(amount, balance)

    if value is None:
        await interaction.response.send_message(
            "Enter a valid amount such as `1`, `1$`, `0.10`, or `0.10$`.",
            ephemeral=False,
        )
        return

    if value <= 0:
        await interaction.response.send_message(
            "The tip must be greater than $0.",
            ephemeral=False,
        )
        return

    sender_balance = await bot.get_balance(
        sender_id
    )

    if value > sender_balance:
        await interaction.response.send_message(
            "You Dont Have Enough Crypto\n"
            "-# use /deposit to top-up Funds",
            ephemeral=False,
        )
        return

    async with bot.db.pool.acquire() as connection:

        async with connection.transaction():

            await connection.execute(
                """
                INSERT INTO users(user_id)
                VALUES($1)
                ON CONFLICT(user_id) DO NOTHING
                """,
                sender_id,
            )

            await connection.execute(
                """
                INSERT INTO users(user_id)
                VALUES($1)
                ON CONFLICT(user_id) DO NOTHING
                """,
                user.id,
            )

            changed = await connection.fetchrow(
                """
                UPDATE users
                SET balance = balance - $2
                WHERE user_id = $1
                  AND balance >= $2
                RETURNING balance
                """,
                sender_id,
                value,
            )

            if not changed:

                await interaction.response.send_message(
                    "You Dont Have Enough Crypto",
                    ephemeral=False,
                )
                return

            await connection.execute(
                """
                UPDATE users
                SET
                    balance = balance + $2,
                    tips_received = tips_received + $2
                WHERE user_id = $1
                """,
                user.id,
                value,
            )

            await connection.execute(
                """
                UPDATE users
                SET tips_sent = tips_sent + $2
                WHERE user_id = $1
                """,
                sender_id,
                value,
            )

            await connection.execute(
                """
                INSERT INTO transactions(
                    user_id,
                    kind,
                    amount,
                    note
                )
                VALUES(
                    $1,
                    'tip',
                    $2,
                    $3
                )
                """,
                sender_id,
                -value,
                f"Tip to {user.id}",
            )

            await connection.execute(
                """
                INSERT INTO transactions(
                    user_id,
                    kind,
                    amount,
                    note
                )
                VALUES(
                    $1,
                    'tip',
                    $2,
                    $3
                )
                """,
                user.id,
                value,
                f"Tip from {sender_id}",
            )

    await interaction.response.send_message(
        f"## Tip Sent\n"
        f"{interaction.user.mention} tipped "
        f"**{money(value)}** to "
        f"**{user.display_name}**.",
    )



    
# ============================================================
# /RANKS
# ============================================================

@prefix_command(name="ranks")
async def ranks_command(
    interaction: discord.Interaction,
):

    lines = [
        "## Ranks & Rewards",
        "",
    ]

    for rank in RANKS:

        label = rank["name"]

        if rank["stage"]:
            label += (
                f" Stage {rank['stage']}"
            )

        lines.append(
            f"**{label}** — "
            f"Wager {money(rank['wager'])} "
            f"· Reward {money(rank['reward'])}"
        )

    await interaction.response.send_message(
        embed=base_embed(
            None,
            "\n".join(lines),
            0x00E676,
        ),
        ephemeral=False,
    )


# ============================================================
# /RANK-REWARDS
# ============================================================

@prefix_command(name="rank-rewards")
async def rank_rewards_command(
    interaction: discord.Interaction,
):

    user_id = interaction.user.id

    row = await bot.get_db_user(
        user_id
    )

    wagered = D(
        row["wagered"]
    ) if row else Decimal("0")

    claimed_index = 0

    if hasattr(
        bot.db,
        "get_claimed_rank",
    ):
        claimed_index = int(
            await bot.db.get_claimed_rank(
                user_id
            )
        )

    available = []

    for index, rank in enumerate(RANKS):

        if (
            wagered >= rank["wager"]
            and index >= claimed_index
        ):
            available.append(
                (
                    index,
                    rank,
                )
            )

    if not available:

        await interaction.response.send_message(
            "You have no rank rewards available.",
            ephemeral=False,
        )

        return

    lines = [
        "## Available Rank Rewards",
        "",
    ]

    for index, rank in available:

        label = rank["name"]

        if rank["stage"]:
            label += (
                f" Stage {rank['stage']}"
            )

        lines.append(
            f"**{label}** — {money(rank['reward'])}"
        )

    lines.append(
        "",
    )

    lines.append(
        "Use the claim button below to claim "
        "the next available reward."
    )

    await interaction.response.send_message(
        embed=base_embed(
            None,
            "\n".join(lines),
            0x00E676,
        ),
        view=RankRewardView(
            bot,
            user_id,
            available[0][0],
        ),
        ephemeral=False,
    )


class RankRewardView(ButtonView):

    def __init__(
        self,
        bot_instance: CasinoBot,
        user_id: int,
        rank_index: int,
    ):

        super().__init__(timeout=120)

        self.bot = bot_instance
        self.user_id = user_id
        self.rank_index = rank_index

    @discord.ui.button(
        label="Claim Reward",
        style=discord.ButtonStyle.success,
    )
    async def claim(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        if interaction.user.id != self.user_id:

            await interaction.response.send_message(
                "This reward belongs to another user.",
                ephemeral=False,
            )

            return

        rank = RANKS[
            self.rank_index
        ]

        if hasattr(
            self.bot.db,
            "claim_rank_reward",
        ):

            success = await self.bot.db.claim_rank_reward(
                self.user_id,
                self.rank_index,
            )

        else:

            success = await self.bot.db.change_balance(
                self.user_id,
                rank["reward"],
                kind="rank_reward",
                note=(
                    f"{rank['name']} "
                    f"Stage {rank['stage']}"
                ),
            )

        if not success:

            await interaction.response.send_message(
                "This reward has already been claimed "
                "or is not available.",
                ephemeral=False,
            )

            return

        await interaction.response.edit_message(
            content=(
                f"**Rank Reward Claimed!**\n"
                f"You received **{money(rank['reward'])}**."
            ),
            embed=None,
            view=None,
        )


# ============================================================
# /LEADERBOARD
# ============================================================

@prefix_command(name="leaderboard", aliases=["lb"])
async def leaderboard_command(
    interaction: discord.Interaction,
):

    if hasattr(
        bot.db,
        "leaderboard",
    ):

        rows = await bot.db.leaderboard()

    else:

        rows = await bot.db.pool.fetch(
            """
            SELECT user_id, wagered
            FROM users
            ORDER BY wagered DESC
            LIMIT 10
            """
        )

    lines = [
        "## Top Wagerers",
        "Top 10 by total wagered",
        "",
    ]

    if not rows:

        lines.append(
            "No wagerers yet."
        )

    else:

        for row in rows:

            user_id = int(
                row["user_id"]
            )

            member = interaction.guild.get_member(
                user_id
            ) if interaction.guild else None

            name = (
                member.mention
                if member
                else f"<@{user_id}>"
            )

            lines.append(
                f"{name}: "
                f"{money(row['wagered'])}"
            )

    await interaction.response.send_message(
        embed=base_embed(
            None,
            "\n".join(lines),
            0x00E676,
        ),
    )

# ============================================================
# bot.py — PART 4 / 10
# ============================================================

# ============================================================
# GENERIC GAME RESULT IMAGE
# ============================================================

def create_game_result_image(game_name: str, result: str, bet: Decimal, payout: Decimal, details: str = ""):
    """Fallback/result card used by games that do not need a custom board image."""
    width, height = 1000, 360
    image = Image.new("RGB", (width, height), (8, 16, 27))
    draw = ImageDraw.Draw(image)

    def font(size, bold=False):
        path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            return ImageFont.load_default()

    title_font = font(38, True)
    result_font = font(34, True)
    body_font = font(24, False)
    small_font = font(20, False)

    won = str(result).upper() in {"WIN", "WON", "CASHED OUT", "FINISHED"}
    push = str(result).upper() == "PUSH"
    result_color = (65, 220, 135) if won else ((250, 205, 80) if push else (255, 70, 95))

    draw.rounded_rectangle((24, 24, width - 24, height - 24), radius=24,
                           fill=(12, 25, 39), outline=(48, 74, 96), width=2)
    draw.text((55, 52), game_name.upper(), font=title_font, fill=(245, 247, 250))
    bb = draw.textbbox((0, 0), str(result).upper(), font=result_font)
    draw.text((width - 55 - (bb[2] - bb[0]), 56), str(result).upper(), font=result_font, fill=result_color)

    draw.text((55, 132), f"Bet     {money(bet)}", font=body_font, fill=(180, 193, 207))
    draw.text((55, 180), f"Payout  {money(payout)}", font=body_font, fill=(245, 247, 250))
    profit = payout - bet
    draw.text((55, 228), f"Profit  {('+' if profit >= 0 else '')}{money(profit)}", font=body_font, fill=result_color)
    if details:
        draw.text((55, 285), details[:75], font=small_font, fill=(150, 168, 184))

    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    output.seek(0)
    return discord.File(output, filename="game_result.png")


# ============================================================
# MINES
# ============================================================

def mines_embed(
    game: MinesGame,
    *,
    revealed: bool = False,
    result: Optional[str] = None,
) -> discord.Embed:

    if game.finished:
        title = "💣 Mines — Game Over"
    else:
        title = "💣 Mines"

    lines = [
        f"**Bet:** {money(game.amount)}",
        f"**Mines:** {game.mines}",
        f"**Safe Tiles:** {len(game.opened)}/"
        f"{25 - game.mines}",
        f"**Multiplier:** {game.multiplier:.2f}x",
    ]

    if not game.finished and len(game.opened) > 0:
        lines.append(
            f"**Cashout:** {money(game.payout)}"
        )

    if result:
        lines.append("")
        lines.append(result)

    embed = base_embed(
        title,
        "\n".join(lines),
        0x00E676 if not game.finished else 0xED4245,
    )

    embed.set_footer(
        text=(
            f"Game #{game.game_id} • "
            "Provably fair"
        )
    )

    return embed


async def mines_reveal_all(
    game: MinesGame,
    view: MinesView,
):

    for item in view.walk_children():

        if not isinstance(
            item,
            discord.ui.Button,
        ):
            continue

        custom_id = item.custom_id or ""

        if not custom_id.startswith("mine:"):
            continue

        try:
            index = int(
                custom_id.split(":")[1]
            )
        except (ValueError, IndexError):
            continue

        if index in game.bombs:
            item.label = "💣"
            item.style = discord.ButtonStyle.danger
        elif index in game.opened:
            item.label = "💎"
            item.style = discord.ButtonStyle.success
        else:
            item.label = "·"
            item.style = discord.ButtonStyle.secondary

        item.disabled = True

    for item in view.walk_children():

        if (
            isinstance(item, discord.ui.Button)
            and item.custom_id == "mine_cashout"
        ):
            item.disabled = True


async def mines_click_impl(
    bot_instance: CasinoBot,
    interaction: discord.Interaction,
    game: MinesGame,
    index: int,
    view: MinesView,
):

    if game.finished:

        await interaction.response.send_message(
            "This Mines game has already ended.",
            ephemeral=False,
        )

        return

    if index in game.opened:

        await interaction.response.send_message(
            "That tile is already open.",
            ephemeral=False,
        )

        return

    await interaction.response.defer()

    if index in game.bombs:

        game.finished = True

        button = next(
            (
                item
                for item in view.walk_children()
                if isinstance(item, discord.ui.Button)
                and item.custom_id == f"mine:{index}"
            ),
            None,
        )

        if button:
            button.label = "💣"
            button.style = discord.ButtonStyle.danger
            button.disabled = True

        await mines_reveal_all(
            game,
            view,
        )

        await bot_instance.settle_loss(
            game.user_id,
            game.amount,
            "mines",
        )

        bot_instance.active_mines.pop(
            game.user_id,
            None,
        )

        embed = mines_embed(
            game,
            revealed=True,
            result=(
                f"💥 You hit a mine and lost "
                f"**{money(game.amount)}**."
            ),
        )

        result_file = create_game_result_image("Mines", "LOSS", game.amount, Decimal("0"), "Mine hit")
        await interaction.edit_original_response(
            view=mines_result_v2(game, "LOSS", Decimal("0"), game.multiplier),
            attachments=[result_file],
        )

        return

    game.opened.add(index)

    button = next(
        (
            item
            for item in view.walk_children()
            if isinstance(item, discord.ui.Button)
            and item.custom_id == f"mine:{index}"
        ),
        None,
    )

    if button:
        button.label = "💎"
        button.style = discord.ButtonStyle.success
        button.disabled = True

    safe_count = 25 - game.mines

    if len(game.opened) >= safe_count:

        game.finished = True

        payout = game.payout

        await bot_instance.settle_win(
            game.user_id,
            game.amount,
            payout,
            "mines",
        )

        bot_instance.active_mines.pop(
            game.user_id,
            None,
        )

        await mines_reveal_all(
            game,
            view,
        )

        embed = mines_embed(
            game,
            revealed=True,
            result=(
                f"🎉 All safe tiles cleared!\n"
                f"**Won:** {money(payout)}"
            ),
        )

        result_file = create_game_result_image("Mines", "WIN", game.amount, payout, "All safe tiles cleared")
        await interaction.edit_original_response(
            view=mines_result_v2(game, "WIN", payout, game.multiplier),
            attachments=[result_file],
        )

        await bot_instance.check_rank_up(
            game.user_id,
        )

        return

    embed = mines_embed(
        game
    )

    await interaction.edit_original_response(
        embed=embed,
        view=view,
    )


async def mines_cashout_impl(
    bot_instance: CasinoBot,
    interaction: discord.Interaction,
    game: MinesGame,
    view: MinesView,
):

    if game.finished:

        await interaction.response.send_message(
            "This Mines game has already ended.",
            ephemeral=False,
        )

        return

    if not game.opened:

        await interaction.response.send_message(
            "Open at least one safe tile before cashing out.",
            ephemeral=False,
        )

        return

    await interaction.response.defer()

    game.finished = True

    payout = game.payout

    await bot_instance.settle_win(
        game.user_id,
        game.amount,
        payout,
        "mines",
    )

    bot_instance.active_mines.pop(
        game.user_id,
        None,
    )

    await mines_reveal_all(
        game,
        view,
    )

    embed = mines_embed(
        game,
        revealed=True,
        result=(
            f"💰 Cashed out for **{money(payout)}**."
        ),
    )

    result_file = create_game_result_image("Mines", "CASHED OUT", game.amount, payout, "Player cashed out")
    await interaction.edit_original_response(
        view=mines_result_v2(game, "CASHED OUT", payout, game.multiplier),
        attachments=[result_file],
    )

    await bot_instance.check_rank_up(
        game.user_id,
    )


async def mines_timeout(
    game: MinesGame,
    view: MinesView,
):

    if game.finished:
        return

    game.finished = True

    await mines_reveal_all(
        game,
        view,
    )

    game.bot.active_mines.pop(
        game.user_id,
        None,
    )


async def casino_mines_click(
    self: CasinoBot,
    interaction: discord.Interaction,
    game: MinesGame,
    index: int,
    view: MinesView,
):

    await mines_click_impl(
        self,
        interaction,
        game,
        index,
        view,
    )


async def casino_mines_cashout(
    self: CasinoBot,
    interaction: discord.Interaction,
    game: MinesGame,
    view: MinesView,
):

    await mines_cashout_impl(
        self,
        interaction,
        game,
        view,
    )


CasinoBot.mines_click = casino_mines_click
CasinoBot.mines_cashout = casino_mines_cashout


class MinesSetModal(discord.ui.Modal, title="Set Mines"):
    mines_input = discord.ui.TextInput(label="Number of mines", placeholder="1-20", max_length=2)

    def __init__(self, view):
        super().__init__()
        self.lobby = view

    async def on_submit(self, interaction: discord.Interaction):
        try:
            value = int(str(self.mines_input.value).strip())
        except ValueError:
            await interaction.response.send_message("Enter a number from 1 to 20.", ephemeral=True)
            return
        if not 1 <= value <= 20:
            await interaction.response.send_message("Enter a number from 1 to 20.", ephemeral=True)
            return
        game = self.lobby.game
        game.mines = value
        positions = list(range(25))
        positions = game.bot.fair_shuffle(positions, game.server_seed, game.client_seed, game.nonce, "mines")
        game.bombs = set(positions[:value])
        game.bot.register_fair_game(
            game.user_id,
            "mines",
            game.game_id,
            game.server_seed,
            game.client_seed,
            game.nonce,
            f"{(Decimal(25 - value) / Decimal(25) * Decimal(100)).quantize(Decimal('0.01'))}% initial safe-tile chance",
            f"{value} mines on 25 tiles; exact mine positions are derived from the HMAC fair shuffle.",
        )
        self.lobby.rebuild()
        await interaction.response.edit_message(view=self.lobby)


class MinesLobbyView(CasinoV2View):
    def __init__(self, game: MinesGame):
        super().__init__(timeout=300)
        self.game = game
        self.rebuild()

    def rebuild(self):
        self.clear_items()
        start = discord.ui.Button(label="Start", style=discord.ButtonStyle.success, custom_id=f"mines_start:{self.game.game_id}")
        set_mines = discord.ui.Button(label="Set Mines", style=discord.ButtonStyle.secondary, custom_id=f"mines_set:{self.game.game_id}")
        start.callback = self.start_game
        set_mines.callback = self.set_mines
        row = discord.ui.ActionRow(start, set_mines)
        divider = discord.ui.MediaGallery(discord.MediaGalleryItem(media="attachment://casino_divider.png"))
        self.add_item(discord.ui.Container(
            discord.ui.TextDisplay(f"## Mines — {money(self.game.amount)} Bet"),
            discord.ui.TextDisplay(f"> ﹒**{self.game.mines}** mine{'s' if self.game.mines != 1 else ''} on a 5×5 board · more mines = bigger multiplier"),
            discord.ui.Separator(visible=True),
            divider,
            row,
            accent_color=0x7C4DFF,
        ))

    async def on_timeout(self):
        if not getattr(self.game, "started", False):
            self.game.bot.active_mines.pop(self.game.user_id, None)
            self.game.bot.clear_fair_game(self.game.user_id)
        for child in self.walk_children():
            if isinstance(child, discord.ui.Button):
                child.disabled = True

    async def set_mines(self, interaction: discord.Interaction):
        if interaction.user.id != self.game.user_id:
            await interaction.response.send_message("This Mines game belongs to another player.", ephemeral=True)
            return
        await interaction.response.send_modal(MinesSetModal(self))

    async def start_game(self, interaction: discord.Interaction):
        if interaction.user.id != self.game.user_id:
            await interaction.response.send_message("This Mines game belongs to another player.", ephemeral=True)
            return
        if getattr(self.game, "started", False):
            await interaction.response.send_message("This Mines game has already started.", ephemeral=True)
            return

        deducted = await bot.deduct_bet(
            self.game.user_id,
            self.game.amount,
            "mines",
        )
        if not deducted:
            await interaction.response.send_message(
                "Your balance changed before the game started. Please try again.",
                ephemeral=True,
            )
            return

        self.game.started = True
        divider = _divider_file()
        await interaction.response.edit_message(
            view=MinesView(self.game),
            attachments=[divider] if divider else [],
        )


@prefix_command(name="mines")
async def mines_command(
    interaction: discord.Interaction,
    amount: str,
    mines: app_commands.Range[int, 1, 20],
):

    # Prefix commands do not get Discord's slash-command Range validation.
    # Always normalize the mines count before doing numeric comparisons.
    try:
        mines = int(str(mines).strip())
    except (TypeError, ValueError):
        await bot.safe_send(
            interaction,
            content="Choose between 1 and 20 mines.",
            ephemeral=False,
        )
        return

    if mines < 1 or mines > 20:
        await bot.safe_send(
            interaction,
            content="Choose between 1 and 20 mines.",
            ephemeral=False,
        )
        return

    cooldown = bot.check_game_cooldown(
        interaction.user.id,
        "mines",
    )

    if cooldown:
        await bot.safe_send(
            interaction,
            content=(
                f"Please wait **{cooldown:.1f}s** "
                "before starting another game."
            ),
            ephemeral=False,
        )
        return

    balance = await bot.get_balance(interaction.user.id)
    bet = amount_or_all(amount, balance)

    if bet is None or bet < MIN_MINES_BET:

        await bot.safe_send(
            interaction,
            embed=error_embed(
                "Invalid Bet",
                f"Minimum bet is {money(MIN_MINES_BET)}.",
            ),
            ephemeral=False,
        )

        return

    balance = await bot.get_balance(
        interaction.user.id
    )

    if bet > balance:

        await bot.safe_send(
            interaction,
            content=(
                "You Dont Have Enough Crypto\n"
                "-# use /deposit to top-up Funds"
            ),
            ephemeral=False,
        )

        return

    if interaction.user.id in bot.active_mines:

        await bot.safe_send(
            interaction,
            content=(
                "You already have an active Mines game."
            ),
            ephemeral=False,
        )

        return

    game_id = bot.next_game_id()

    server_seed = bot.create_server_seed()
    server_hash = bot.server_hash(
        server_seed
    )
    client_seed = bot.create_client_seed(
        interaction.user.id
    )

    nonce = 0

    game = MinesGame(
        bot=bot,
        user_id=interaction.user.id,
        amount=bet,
        mines=int(mines),
        game_id=game_id,
        server_hash=server_hash,
        server_seed=server_seed,
        client_seed=client_seed,
        nonce=nonce,
    )
    game.started = False

    bot.register_fair_game(
        interaction.user.id, "mines", game_id, server_seed, client_seed, nonce,
        f"{(Decimal(25 - mines) / Decimal(25) * Decimal(100)).quantize(Decimal('0.01'))}% initial safe-tile chance",
        f"{mines} mines on 25 tiles; exact mine positions are derived from the HMAC fair shuffle."
    )

    bot.active_mines[
        interaction.user.id
    ] = game

    view = MinesLobbyView(game)
    divider_file = _divider_file()
    kwargs = {"view": view}
    if divider_file:
        kwargs["file"] = divider_file
    await interaction.response.send_message(**kwargs)

    message = await interaction.original_response()

    game.message_id = message.id
    game.channel_id = interaction.channel_id


# ============================================================
# TOWER
# ============================================================

TOWER_LEVELS = 10
TOWER_HOUSE_EDGE = Decimal("0.99")
TOWER_CONFIG = {
    "easy": {
        "tiles": 4,
        "label": "Easy",
    },
    "mid": {
        "tiles": 3,
        "label": "Mid",
    },
    "hard": {
        "tiles": 2,
        "label": "Hard",
    },
}


def tower_font(size: int, bold: bool = False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
    ]

    for path in candidates:
        try:
            if Path(path).exists():
                return ImageFont.truetype(path, size)
        except Exception:
            pass

    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def create_tower_image(game):
    """Create a dark tower board inspired by the supplied reference image."""

    WIDTH = 900
    HEIGHT = 1100

    BG = (11, 17, 24)
    PANEL = (24, 34, 45)
    PANEL_2 = (29, 41, 53)
    BORDER = (58, 75, 91)
    TILE = (54, 67, 80)
    TILE_BORDER = (79, 96, 112)
    TILE_OPEN = (43, 91, 75)
    TILE_BOMB = (119, 38, 45)
    WHITE = (238, 243, 247)
    MUTED = (151, 164, 176)
    BLUE = (88, 173, 255)
    GREEN = (61, 220, 143)
    RED = (245, 79, 88)
    GOLD = (238, 192, 84)

    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)

    # Outer tower body.
    draw.rounded_rectangle(
        (35, 35, WIDTH - 35, HEIGHT - 30),
        radius=28,
        fill=PANEL,
        outline=BORDER,
        width=4,
    )

    # Header.
    draw.text(
        (70, 62),
        "TOWER",
        font=tower_font(42, True),
        fill=BLUE,
    )
    draw.text(
        (70, 112),
        f"{game.difficulty.title()} • {game.tiles} tiles • 1 bomb",
        font=tower_font(23),
        fill=MUTED,
    )

    multiplier = game.multiplier
    cashout = game.payout

    right_text = f"{multiplier:.2f}x"
    rb = draw.textbbox((0, 0), right_text, font=tower_font(40, True))
    draw.text(
        (WIDTH - 70 - (rb[2] - rb[0]), 66),
        right_text,
        font=tower_font(40, True),
        fill=GREEN if game.opened else WHITE,
    )
    draw.text(
        (WIDTH - 70 - 190, 116),
        f"Cashout {money(cashout)}",
        font=tower_font(23),
        fill=GOLD,
    )

    # Simple dark tower/monster silhouette to echo the supplied artwork.
    cx = WIDTH // 2
    draw.polygon(
        [(cx - 170, 180), (cx - 115, 135), (cx - 65, 155),
         (cx, 125), (cx + 65, 155), (cx + 115, 135),
         (cx + 170, 180), (cx + 115, 205), (cx + 75, 190),
         (cx + 50, 230), (cx - 50, 230), (cx - 75, 190),
         (cx - 115, 205)],
        fill=(28, 42, 55),
    )
    draw.ellipse((cx - 36, 145, cx + 36, 217), fill=(65, 81, 94))
    draw.ellipse((cx - 18, 170, cx - 7, 181), fill=BLUE)
    draw.ellipse((cx + 7, 170, cx + 18, 181), fill=BLUE)
    draw.polygon([(cx - 20, 190), (cx, 220), (cx + 20, 190)], fill=(31, 53, 65))

    # Tower levels. Bottom = first level; current level is highlighted.
    rows_visible = TOWER_LEVELS
    top_y = 250
    bottom_y = HEIGHT - 80
    row_gap = 9
    row_h = (bottom_y - top_y - row_gap * (rows_visible - 1)) // rows_visible

    tile_gap = 16
    total_tile_width = min(650, WIDTH - 160)
    tile_w = (total_tile_width - tile_gap * (game.tiles - 1)) // game.tiles
    start_x = (WIDTH - (tile_w * game.tiles + tile_gap * (game.tiles - 1))) // 2

    for level in range(rows_visible):
        # Draw the next level at the top, so climbing moves upward visually.
        y = bottom_y - row_h - level * (row_h + row_gap)
        current = level == game.level
        completed = level < game.level

        # Level number.
        draw.text(
            (60, y + row_h // 2 - 13),
            str(level + 1),
            font=tower_font(22, True),
            fill=GOLD if current else MUTED,
        )

        for tile_index in range(game.tiles):
            x1 = start_x + tile_index * (tile_w + tile_gap)
            x2 = x1 + tile_w
            y1 = y
            y2 = y + row_h

            state = game.revealed.get(level, {}).get(tile_index)

            fill = TILE
            outline = TILE_BORDER
            if state == "safe":
                fill = TILE_OPEN
                outline = GREEN
            elif state == "bomb":
                fill = TILE_BOMB
                outline = RED
            elif current:
                fill = PANEL_2
                outline = BLUE
            elif completed:
                fill = (39, 52, 63)

            draw.rounded_rectangle(
                (x1, y1, x2, y2),
                radius=12,
                fill=fill,
                outline=outline,
                width=3,
            )

            if state == "safe":
                # Diamond/safe marker.
                mx = (x1 + x2) // 2
                my = (y1 + y2) // 2
                draw.polygon(
                    [(mx, my - 18), (mx + 18, my),
                     (mx, my + 18), (mx - 18, my)],
                    fill=GREEN,
                )
            elif state == "bomb":
                mx = (x1 + x2) // 2
                my = (y1 + y2) // 2
                draw.ellipse(
                    (mx - 17, my - 17, mx + 17, my + 17),
                    fill=RED,
                )
                draw.line((mx - 23, my - 23, mx + 23, my + 23), fill=WHITE, width=5)
                draw.line((mx + 23, my - 23, mx - 23, my + 23), fill=WHITE, width=5)

    # Footer.
    footer = f"Level {min(game.level + 1, TOWER_LEVELS)}/{TOWER_LEVELS}"
    if game.finished:
        footer = "GAME OVER"
    fb = draw.textbbox((0, 0), footer, font=tower_font(24, True))
    draw.text(
        ((WIDTH - (fb[2] - fb[0])) / 2, HEIGHT - 55),
        footer,
        font=tower_font(24, True),
        fill=WHITE,
    )

    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    output.seek(0)
    return discord.File(output, filename="tower.png")


class TowerGame:
    def __init__(
        self,
        bot: CasinoBot,
        user_id: int,
        amount: Decimal,
        difficulty: str,
        game_id: int,
        server_hash: str,
        server_seed: str,
        client_seed: str,
        nonce: int,
    ):
        self.bot = bot
        self.user_id = user_id
        self.amount = amount
        self.difficulty = difficulty
        self.tiles = int(TOWER_CONFIG[difficulty]["tiles"])
        self.game_id = game_id
        self.server_hash = server_hash
        self.server_seed = server_seed
        self.client_seed = client_seed
        self.nonce = nonce
        self.level = 0
        self.opened = 0
        self.finished = False
        self.message_id = None
        self.channel_id = None
        self.bombs: dict[int, int] = {}
        self.revealed: dict[int, dict[int, str]] = {}

        # One bomb per level. The position is derived from the same
        # provably-fair seed system already used by the casino.
        for level in range(TOWER_LEVELS):
            self.bombs[level] = self.bot.fair_int(
                server_seed,
                client_seed,
                nonce + level,
                0,
                self.tiles - 1,
                "tower",
            )

    @property
    def safe_probability(self) -> Decimal:
        return Decimal(self.tiles - 1) / Decimal(self.tiles)

    @property
    def multiplier(self) -> Decimal:
        if self.opened <= 0:
            return Decimal("1.00")

        value = (
            Decimal("1") / (self.safe_probability ** self.opened)
        ) * TOWER_HOUSE_EDGE

        return value.quantize(Decimal("0.01"), rounding=ROUND_DOWN)

    @property
    def payout(self) -> Decimal:
        return (
            self.amount * self.multiplier
        ).quantize(Decimal("0.01"), rounding=ROUND_DOWN)


class TowerDifficultyView(ButtonView):
    def __init__(self, bot: CasinoBot, user_id: int, amount: Decimal):
        super().__init__(timeout=120)
        self.bot = bot
        self.user_id = user_id
        self.amount = amount

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This Tower setup belongs to another player.",
                ephemeral=False,
            )
            return False
        return True

    async def choose(self, interaction: discord.Interaction, difficulty: str):
        await start_tower_game(
            self.bot,
            interaction,
            self.user_id,
            self.amount,
            difficulty,
        )

    @discord.ui.button(label="Easy", style=discord.ButtonStyle.success, custom_id="tower_easy")
    async def easy(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.choose(interaction, "easy")

    @discord.ui.button(label="Mid", style=discord.ButtonStyle.primary, custom_id="tower_mid")
    async def mid(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.choose(interaction, "mid")

    @discord.ui.button(label="Hard", style=discord.ButtonStyle.danger, custom_id="tower_hard")
    async def hard(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.choose(interaction, "hard")


def tower_embed(game: TowerGame, result: Optional[str] = None) -> discord.Embed:
    color = 0x00E676 if not game.finished else 0xED4245
    lines = [
        f"**Bet:** {money(game.amount)}",
        f"**Difficulty:** {game.difficulty.title()}",
        f"**Level:** {game.level}/{TOWER_LEVELS}",
        f"**Multiplier:** {game.multiplier:.2f}x",
    ]

    if game.opened > 0 and not game.finished:
        lines.append(f"**Cashout:** {money(game.payout)}")

    if result:
        lines.extend(["", result])

    embed = base_embed(
        "Tower",
        "\n".join(lines),
        color,
    )
    embed.set_image(url="attachment://tower.png")
    embed.set_footer(text=f"Game #{game.game_id} • Provably fair")
    return embed


def tower_view(game: TowerGame) -> "TowerView":
    return TowerView(game)


class TowerView(ButtonView):
    def __init__(self, game: TowerGame):
        super().__init__(timeout=300)
        self.game = game

        # Tile choices for the current level.
        for index in range(game.tiles):
            button = discord.ui.Button(
                label=str(index + 1),
                style=discord.ButtonStyle.secondary,
                custom_id=f"tower:{index}",
                row=0,
            )
            button.callback = self.make_tile_callback(index)
            self.add_item(button)

        if game.opened > 0 and not game.finished:
            cashout = discord.ui.Button(
                label=f"Cash Out {money(game.payout)}",
                style=discord.ButtonStyle.success,
                custom_id="tower_cashout",
                row=1,
            )
            cashout.callback = self.cashout
            self.add_item(cashout)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.game.user_id:
            await interaction.response.send_message(
                "This Tower game belongs to another player.",
                ephemeral=False,
            )
            return False
        return True

    def make_tile_callback(self, index: int):
        async def callback(interaction: discord.Interaction):
            await tower_click_impl(
                self.game.bot,
                interaction,
                self.game,
                index,
            )
        return callback

    async def cashout(self, interaction: discord.Interaction):
        await tower_cashout_impl(
            self.game.bot,
            interaction,
            self.game,
        )


async def send_tower_state(
    interaction: discord.Interaction,
    game: TowerGame,
    result: Optional[str] = None,
):
    file = create_tower_image(game)
    await interaction.edit_original_response(
        embed=tower_embed(game, result=result),
        view=None if game.finished else tower_view(game),
        attachments=[file],
    )


async def start_tower_game(
    bot_instance: CasinoBot,
    interaction: discord.Interaction,
    user_id: int,
    amount: Decimal,
    difficulty: str,
):
    difficulty = str(difficulty).lower().strip()
    if difficulty not in TOWER_CONFIG:
        await bot_instance.safe_send(
            interaction,
            embed=error_embed(
                "Invalid Difficulty",
                "Choose **easy**, **mid**, or **hard**.",
            ),
            ephemeral=False,
        )
        return

    if user_id in bot_instance.active_towers:
        await bot_instance.safe_send(
            interaction,
            content="You already have an active Tower game.",
            ephemeral=False,
        )
        return

    balance = await bot_instance.get_balance(user_id)
    if amount > balance:
        await bot_instance.safe_send(
            interaction,
            content="You Dont Have Enough Crypto\n-# use .deposit to top-up Funds",
            ephemeral=False,
        )
        return

    deducted = await bot_instance.deduct_bet(
        user_id,
        amount,
        "tower",
    )
    if not deducted:
        await bot_instance.safe_send(
            interaction,
            content="Your balance changed. Please try again.",
            ephemeral=False,
        )
        return

    game_id = bot_instance.next_game_id()
    server_seed = bot_instance.create_server_seed()
    server_hash = bot_instance.server_hash(server_seed)
    client_seed = bot_instance.create_client_seed(user_id)

    game = TowerGame(
        bot=bot_instance,
        user_id=user_id,
        amount=amount,
        difficulty=difficulty,
        game_id=game_id,
        server_hash=server_hash,
        server_seed=server_seed,
        client_seed=client_seed,
        nonce=0,
    )

    bot_instance.register_fair_game(
        user_id, "tower", game_id, server_seed, client_seed, 0,
        f"{(Decimal(game.tiles - 1) / Decimal(game.tiles) * Decimal(100)).quantize(Decimal('0.01'))}% per level",
        f"{game.difficulty.title()} difficulty; {game.tiles} tiles with 1 bomb per level."
    )

    bot_instance.active_towers[user_id] = game

    file = create_tower_image(game)
    await interaction.response.send_message(
        embed=tower_embed(game),
        view=TowerView(game),
        file=file,
    )

    message = await interaction.original_response()
    game.message_id = message.id
    game.channel_id = interaction.channel_id


async def tower_click_impl(
    bot_instance: CasinoBot,
    interaction: discord.Interaction,
    game: TowerGame,
    index: int,
):
    if game.finished:
        await interaction.response.send_message(
            "This Tower game has already ended.",
            ephemeral=False,
        )
        return

    if index < 0 or index >= game.tiles:
        return

    await interaction.response.defer()

    bomb = game.bombs[game.level]
    game.revealed.setdefault(game.level, {})

    if index == bomb:
        game.revealed[game.level][index] = "bomb"
        game.finished = True
        await bot_instance.settle_loss(
            game.user_id,
            game.amount,
            "tower",
        )
        bot_instance.active_towers.pop(game.user_id, None)

        file = create_tower_image(game)
        await interaction.edit_original_response(
            embed=tower_embed(
                game,
                result=f"You hit the bomb and lost **{money(game.amount)}**.",
            ),
            view=None,
            attachments=[file],
        )
        return

    game.revealed[game.level][index] = "safe"
    game.opened += 1
    game.level += 1

    # Clearing all levels wins the game automatically.
    if game.level >= TOWER_LEVELS:
        game.finished = True
        payout = game.payout
        await bot_instance.settle_win(
            game.user_id,
            game.amount,
            payout,
            "tower",
        )
        bot_instance.active_towers.pop(game.user_id, None)

        file = create_tower_image(game)
        await interaction.edit_original_response(
            embed=tower_embed(
                game,
                result=f"All levels cleared! You won **{money(payout)}**.",
            ),
            view=None,
            attachments=[file],
        )
        await bot_instance.check_rank_up(game.user_id)
        return

    # Safe tile: player can now cash out or continue to the next level.
    file = create_tower_image(game)
    await interaction.edit_original_response(
        embed=tower_embed(
            game,
            result=(
                f"Safe! Choose **Cash Out** for {money(game.payout)} "
                "or pick a tile on the next level."
            ),
        ),
        view=TowerView(game),
        attachments=[file],
    )


async def tower_cashout_impl(
    bot_instance: CasinoBot,
    interaction: discord.Interaction,
    game: TowerGame,
):
    if game.finished:
        await interaction.response.send_message(
            "This Tower game has already ended.",
            ephemeral=False,
        )
        return

    if game.opened <= 0:
        await interaction.response.send_message(
            "Open at least one safe tile before cashing out.",
            ephemeral=False,
        )
        return

    await interaction.response.defer()

    game.finished = True
    payout = game.payout

    await bot_instance.settle_win(
        game.user_id,
        game.amount,
        payout,
        "tower",
    )
    bot_instance.active_towers.pop(game.user_id, None)

    file = create_tower_image(game)
    await interaction.edit_original_response(
        embed=tower_embed(
            game,
            result=f"Cashed out for **{money(payout)}** at **{game.multiplier:.2f}x**.",
        ),
        view=None,
        attachments=[file],
    )
    await bot_instance.check_rank_up(game.user_id)


@prefix_command(name="tower")
async def tower_command(
    interaction: discord.Interaction,
    amount: str,
    difficulty: Optional[str] = None,
):
    cooldown = bot.check_game_cooldown(
        interaction.user.id,
        "tower",
    )

    if cooldown:
        await bot.safe_send(
            interaction,
            content=(
                f"Please wait **{cooldown:.1f}s** "
                "before starting another game."
            ),
            ephemeral=False,
        )
        return

    balance = await bot.get_balance(interaction.user.id)
    bet = amount_or_all(amount, balance)

    if bet is None or bet < MIN_BET:
        await bot.safe_send(
            interaction,
            embed=error_embed(
                "Invalid Bet",
                f"Minimum bet is {money(MIN_BET)}.",
            ),
            ephemeral=False,
        )
        return

    if interaction.user.id in bot.active_towers:
        await bot.safe_send(
            interaction,
            content="You already have an active Tower game.",
            ephemeral=False,
        )
        return

    if difficulty is None or not str(difficulty).strip():
        await bot.safe_send(
            interaction,
            embed=base_embed(
                "Choose Difficulty Level",
                f"**Bet:** {money(bet)}\n\nChoose how many tiles you want on each level.",
                0x4B8BFF,
            ),
            view=TowerDifficultyView(
                bot,
                interaction.user.id,
                bet,
            ),
            ephemeral=False,
        )
        return

    await start_tower_game(
        bot,
        interaction,
        interaction.user.id,
        bet,
        str(difficulty),
    )



# ============================================================
# ROULETTE
# ============================================================

# The supplied roulette artwork is embedded so Railway only needs bot.py.
ROULETTE_IMAGE_B64 = """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"""

ROULETTE_WHEEL_ORDER = [
    0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27,
    13, 36, 11, 30, 8, 23, 10, 5, 24, 16, 33, 1,
    20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26,
]

ROULETTE_RED = {
    1, 3, 5, 7, 9, 12, 14, 16, 18,
    19, 21, 23, 25, 27, 30, 32, 34, 36,
}

ROULETTE_BETS = {
    "red": {"label": "RED", "payout": Decimal("1.95")},
    "black": {"label": "BLACK", "payout": Decimal("1.95")},
    "low": {"label": "1-19", "payout": Decimal("1.95")},
    "high": {"label": "20-36", "payout": Decimal("1.95")},
    "col1": {"label": "COL 1", "payout": Decimal("2.95")},
    "col2": {"label": "COL 2", "payout": Decimal("2.95")},
    "col3": {"label": "COL 3", "payout": Decimal("2.95")},
    "zero": {"label": "0", "payout": Decimal("36.00")},
    "odd": {"label": "ODD", "payout": Decimal("1.95")},
    "even": {"label": "EVEN", "payout": Decimal("1.95")},
}


def roulette_font(size: int, bold: bool = False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"
        if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
    ]
    for candidate in candidates:
        try:
            if Path(candidate).exists():
                return ImageFont.truetype(candidate, size)
        except Exception:
            pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _roulette_base_image():
    try:
        raw = base64.b64decode(ROULETTE_IMAGE_B64)
        return Image.open(io.BytesIO(raw)).convert("RGBA")
    except Exception:
        return Image.new("RGBA", (740, 740), (18, 72, 28, 255))


def create_roulette_image(number: int | None = None):
    """Return the supplied roulette artwork, optionally marked at the result."""
    image = _roulette_base_image()

    if number is not None and number in ROULETTE_WHEEL_ORDER:
        draw = ImageDraw.Draw(image)
        center_x = image.width / 2
        center_y = image.height / 2

        index = ROULETTE_WHEEL_ORDER.index(number)
        angle = (-90.0 + index * (360.0 / 37.0)) * 3.141592653589793 / 180.0

        # The ball sits on the green track just inside the numbered ring.
        radius = min(image.width, image.height) * 0.250
        x = center_x + radius * __import__("math").cos(angle)
        y = center_y + radius * __import__("math").sin(angle)

        # Soft shadow + white ball with a clean outline.
        draw.ellipse(
            (x - 14, y - 14, x + 14, y + 14),
            fill=(0, 0, 0, 100),
        )
        draw.ellipse(
            (x - 10, y - 10, x + 10, y + 10),
            fill=(255, 255, 255, 255),
            outline=(225, 225, 225, 255),
            width=2,
        )

    output = io.BytesIO()
    image.convert("RGB").save(output, format="JPEG", quality=94, optimize=True)
    output.seek(0)
    return discord.File(output, filename="roulette.jpg")


def roulette_color(number: int) -> str:
    if number == 0:
        return "green"
    return "red" if number in ROULETTE_RED else "black"


def roulette_column(number: int) -> str | None:
    if number == 0:
        return None
    remainder = number % 3
    return {1: "col1", 2: "col2", 0: "col3"}[remainder]


def roulette_winning_bets(number: int) -> list[str]:
    if number == 0:
        return ["zero"]

    winning = ["red" if number in ROULETTE_RED else "black"]
    winning.append("odd" if number % 2 else "even")
    winning.append("low" if number <= 19 else "high")
    column = roulette_column(number)
    if column:
        winning.append(column)
    return winning


def roulette_display_bets(selected: list[str]) -> str:
    if not selected:
        return "None"
    return ", ".join(ROULETTE_BETS[key]["label"] for key in selected)


def roulette_embed(
    game: "RouletteGame",
    *,
    title: str = "Roulette",
    result: bool = False,
) -> discord.Embed:
    if result:
        color = 0x57F287 if game.total_win > 0 else 0xED4245
    else:
        color = 0x2B2D31

    if result:
        winning_labels = ", ".join(
            ROULETTE_BETS[key]["label"]
            for key in game.winning_bets
        )
        description = (
            f"**Total Bet Amount :** {money(game.total_cost)}\n"
            f"**Total Win :** {money(game.total_win)}\n"
            f"**Landed On :** {game.result_number}\n"
            f"**Winning Bets :** {winning_labels}\n"
            f"**Your Bet :** {roulette_display_bets(game.selected)}"
        )
    else:
        description = (
            f"**Per Bet Cost :** {money(game.per_bet)}\n"
            f"**BETS :** {roulette_display_bets(game.selected)}\n\n"
            "Select one or more bets, then press **START**."
        )

    embed = base_embed(title, description, color)
    embed.set_image(url="attachment://roulette.jpg")
    embed.set_footer(text=f"Game #{game.game_id} • European Roulette • Provably fair")
    return embed


class RouletteGame:
    def __init__(
        self,
        bot: CasinoBot,
        user_id: int,
        per_bet: Decimal,
        game_id: int,
        server_hash: str,
        server_seed: str,
        client_seed: str,
        nonce: int,
    ):
        self.bot = bot
        self.user_id = user_id
        self.per_bet = per_bet
        self.game_id = game_id
        self.server_hash = server_hash
        self.server_seed = server_seed
        self.client_seed = client_seed
        self.nonce = nonce
        self.selected: list[str] = []
        self.started = False
        self.finished = False
        self.result_number: int | None = None
        self.winning_bets: list[str] = []
        self.total_win = Decimal("0")
        self.message_id = None
        self.channel_id = None

    @property
    def total_cost(self) -> Decimal:
        return (
            self.per_bet * Decimal(len(self.selected))
        ).quantize(Decimal("0.01"), rounding=ROUND_DOWN)


class RouletteView(CasinoV2View):
    def __init__(self, game: RouletteGame):
        super().__init__(timeout=300)
        self.game = game
        self.build()

    def build(self, *, title="◆ SWOOSH ROULETTE ◆", spinning=False, result=False):
        self.clear_items()
        if spinning:
            self.add_item(discord.ui.Container(
                discord.ui.TextDisplay("## Spinning Roulette"),
                discord.ui.TextDisplay(f"> ﹒total bet **{money(self.game.total_cost)}**\n> ﹒your bets **{roulette_display_bets(self.game.selected)}**\n> ﹒the wheel is spinning..."),
                discord.ui.MediaGallery(discord.MediaGalleryItem(media="attachment://roulette.jpg")),
                accent_color=0x7C4DFF,
            ))
            return
        if result:
            winning_labels = ", ".join(ROULETTE_BETS[key]["label"] for key in self.game.winning_bets)
            self.add_item(discord.ui.Container(
                discord.ui.TextDisplay("## Roulette — Result"),
                discord.ui.TextDisplay(f"> ﹒landed on **{self.game.result_number}** · winning bets **{winning_labels or 'None'}**\n> ﹒total bet **{money(self.game.total_cost)}** · total win **{money(self.game.total_win)}**"),
                discord.ui.MediaGallery(discord.MediaGalleryItem(media="attachment://roulette.jpg")),
                discord.ui.TextDisplay(f"-# Bet ID {self.game.game_id} · verify with `.verify {self.game.game_id}`"),
                accent_color=0x57F287 if self.game.total_win > 0 else 0xED4245,
            ))
            return
        buttons=[
            ("red","RED",discord.ButtonStyle.danger,0),("black","BLACK",discord.ButtonStyle.secondary,0),("low","1-19",discord.ButtonStyle.secondary,0),("high","20-36",discord.ButtonStyle.secondary,0),("col1","COL 1",discord.ButtonStyle.secondary,0),
            ("col2","COL 2",discord.ButtonStyle.secondary,1),("col3","COL 3",discord.ButtonStyle.secondary,1),("zero","0",discord.ButtonStyle.secondary,1),("odd","ODD",discord.ButtonStyle.secondary,1),("even","EVEN",discord.ButtonStyle.secondary,1),
        ]
        rows=[]
        for row_index in (0,1):
            row=discord.ui.ActionRow()
            for key,label,style,r in buttons:
                if r!=row_index: continue
                b=discord.ui.Button(label=label, style=discord.ButtonStyle.success if key in self.game.selected else style, custom_id=f"roulette_bet:{key}")
                b.callback=self.make_bet_callback(key)
                row.add_item(b)
            rows.append(row)
        start_button=discord.ui.Button(label="START",style=discord.ButtonStyle.primary,custom_id="roulette_start")
        start_button.callback=self.start
        rows.append(discord.ui.ActionRow(start_button))
        body=f"> ﹒per bet **{money(self.game.per_bet)}** × **{len(self.game.selected)}** = total **{money(self.game.total_cost)}**\n> ﹒select your bets, then press **START**"
        children=[discord.ui.TextDisplay(f"## {title}"),discord.ui.TextDisplay(body),discord.ui.Separator(visible=True),discord.ui.MediaGallery(discord.MediaGalleryItem(media="attachment://casino_divider.png")),discord.ui.MediaGallery(discord.MediaGalleryItem(media="attachment://roulette.jpg"))]
        children.extend(rows)
        children.append(discord.ui.TextDisplay("-# European Roulette · provably fair"))
        self.add_item(discord.ui.Container(*children,accent_color=0x7C4DFF))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.game.user_id:
            await interaction.response.send_message("This Roulette game belongs to another player.", ephemeral=True)
            return False
        return True

    def make_bet_callback(self,key):
        async def callback(interaction):
            if self.game.started:
                await interaction.response.send_message("Roulette has already started.",ephemeral=True); return
            if key in self.game.selected: self.game.selected.remove(key)
            else: self.game.selected.append(key)
            self.build()
            await interaction.response.edit_message(view=self)
        return callback

    async def start(self,interaction):
        if self.game.started:
            await interaction.response.send_message("Roulette has already started.",ephemeral=True); return
        if not self.game.selected:
            await interaction.response.send_message("Select at least one bet before pressing START.",ephemeral=True); return
        balance=await self.game.bot.get_balance(self.game.user_id)
        if self.game.total_cost>balance:
            await interaction.response.send_message("You Dont Have Enough Crypto",ephemeral=True); return
        self.game.started=True
        deducted=await self.game.bot.deduct_bet(self.game.user_id,self.game.total_cost,"roulette")
        if not deducted:
            self.game.started=False
            await interaction.response.send_message("Your balance changed. Please try again.",ephemeral=True); return
        covered=set()
        for key in self.game.selected:
            if key=="0": covered.add(0)
            elif key in ("red","black","odd","even","low","high"):
                if key=="low": covered.update(range(1,20))
                elif key=="high": covered.update(range(20,37))
                elif key=="odd": covered.update(n for n in range(1,37) if n%2)
                elif key=="even": covered.update(n for n in range(1,37) if n%2==0)
                else: covered.update(n for n in range(1,37) if roulette_color(n)==key)
            elif key.startswith("col"):
                col=int(key[-1]); covered.update(n for n in range(1,37) if ((n-1)%3)+1==col)
        chance=(Decimal(len(covered))/Decimal(37)*Decimal(100)).quantize(Decimal("0.01"))
        self.game.bot.register_fair_game(self.game.user_id,"roulette",self.game.game_id,self.game.server_seed,self.game.client_seed,0,f"{chance}% for selected covered numbers",f"European roulette; {len(covered)} of 37 numbers covered by the selected bets.")
        await interaction.response.defer()
        self.build(spinning=True)
        spin_file=create_roulette_image()
        await interaction.edit_original_response(view=self,attachments=[spin_file])
        await asyncio.sleep(1.5)
        await finish_roulette(self.game.bot,interaction,self.game)

    async def on_timeout(self):
        if not self.game.started:
            for child in self.walk_children():
                if isinstance(child,discord.ui.Button): child.disabled=True


async def finish_roulette(
    bot_instance: CasinoBot,
    interaction: discord.Interaction,
    game: RouletteGame,
):
    if game.finished:
        return

    game.result_number = bot_instance.fair_int(
        game.server_seed,
        game.client_seed,
        game.nonce,
        0,
        36,
        "roulette",
    )
    game.winning_bets = roulette_winning_bets(game.result_number)

    game.total_win = Decimal("0")
    for selected_key in game.selected:
        if selected_key in game.winning_bets:
            game.total_win += (
                game.per_bet
                * ROULETTE_BETS[selected_key]["payout"]
            )

    game.total_win = game.total_win.quantize(
        Decimal("0.01"),
        rounding=ROUND_DOWN,
    )
    game.finished = True

    if game.total_win > 0:
        await bot_instance.settle_win(
            game.user_id,
            game.total_cost,
            game.total_win,
            "roulette",
        )
    else:
        await bot_instance.settle_loss(
            game.user_id,
            game.total_cost,
            "roulette",
        )

    bot_instance.active_roulette.pop(game.user_id, None)

    file = create_roulette_image(game.result_number)
    result_view = RouletteView(game)
    result_view.build(result=True)
    await interaction.edit_original_response(
        view=result_view,
        attachments=[file],
    )
    await bot_instance.check_rank_up(game.user_id)


@prefix_command(name="roulette", aliases=["rl"])
async def roulette_command(
    interaction: discord.Interaction,
    amount: str,
):
    user_id = interaction.user.id

    if not await require_database(interaction):
        return

    cooldown = bot.check_game_cooldown(user_id, "roulette")
    if cooldown:
        await bot.safe_send(
            interaction,
            content=(
                f"Please wait **{cooldown:.1f}s** "
                "before starting another game."
            ),
            ephemeral=False,
        )
        return

    if user_id in bot.active_roulette:
        await bot.safe_send(
            interaction,
            content="You already have an active Roulette game.",
            ephemeral=False,
        )
        return

    balance = await bot.get_balance(user_id)
    bet = amount_or_all(amount, balance)
    if bet is None or bet < MIN_BET:
        await bot.safe_send(
            interaction,
            embed=error_embed(
                "Invalid Bet",
                f"Minimum bet is {money(MIN_BET)}. Use `all`, `half`, or `max` for balance-based bets.",
            ),
            ephemeral=False,
        )
        return

    game_id = bot.next_game_id()
    server_seed = bot.create_server_seed()
    server_hash = bot.server_hash(server_seed)
    client_seed = bot.create_client_seed(user_id)

    game = RouletteGame(
        bot=bot,
        user_id=user_id,
        per_bet=bet,
        game_id=game_id,
        server_hash=server_hash,
        server_seed=server_seed,
        client_seed=client_seed,
        nonce=0,
    )
    bot.active_roulette[user_id] = game

    file = create_roulette_image()
    divider = _divider_file()
    try:
        view = RouletteView(game)
        files = [file]
        if divider:
            files.append(divider)
        await interaction.response.send_message(view=view, files=files)
    except Exception:
        bot.active_roulette.pop(user_id, None)
        raise

    message = await interaction.original_response()
    game.message_id = message.id
    game.channel_id = interaction.channel_id



# ============================================================
# RAIN
# ============================================================

async def join_rain(
    self: CasinoBot,
    interaction: discord.Interaction,
    rain_id: str,
):

    rain = self.active_rains.get(
        rain_id
    )

    if not rain:

        await interaction.response.send_message(
            "This rain has already ended.",
            ephemeral=True,
        )

        return

    # --------------------------------------------------------
    # OWNER CANNOT JOIN OWN RAIN
    # --------------------------------------------------------

    if interaction.user.id == rain["user_id"]:

        await interaction.response.send_message(
            "You cannot join your own rain.",
            ephemeral=True,
        )

        return

    # --------------------------------------------------------
    # ALREADY JOINED
    # --------------------------------------------------------

    if interaction.user.id in rain["players"]:

        await interaction.response.send_message(
            "You already joined this rain.",
            ephemeral=True,
        )

        return

    # --------------------------------------------------------
    # JOIN
    # --------------------------------------------------------

    rain["players"].add(
        interaction.user.id
    )

    await interaction.response.send_message(
        "You joined the rain.",
        ephemeral=True,
    )


CasinoBot.join_rain = join_rain


async def finish_rain(
    self: CasinoBot,
    rain_id: str,
):

    # --------------------------------------------------------
    # REMOVE FROM ACTIVE RAINS
    # --------------------------------------------------------

    rain = self.active_rains.pop(
        rain_id,
        None,
    )

    if not rain:
        return

    amount = D(
        rain["amount"]
    )

    players = list(
        rain["players"]
    )

    # --------------------------------------------------------
    # GET CHANNEL
    # --------------------------------------------------------

    channel = self.get_channel(
        rain["channel_id"]
    )

    if not channel:

        try:

            await self.db.change_balance(
                rain["user_id"],
                amount,
                kind="rain_refund",
                note=rain_id,
            )

        except Exception as e:

            print(
                f"[RAIN] Refund error: {e}"
            )

        return

    # --------------------------------------------------------
    # NOBODY JOINED
    # --------------------------------------------------------

    if not players:

        try:

            await self.db.change_balance(
                rain["user_id"],
                amount,
                kind="rain_refund",
                note=rain_id,
            )

            await channel.send(
                f"## Rain Ended — {money(amount)}\n"
                "Nobody joined the rain, so the full "
                "amount was refunded."
            )

        except Exception as e:

            print(
                f"[RAIN] Refund error: {e}"
            )

            await channel.send(
                "## Rain Ended\n"
                "Nobody joined the rain."
            )

        return

    # --------------------------------------------------------
    # CALCULATE SHARE
    # --------------------------------------------------------

    player_count = len(players)

    share = (
        amount
        / Decimal(player_count)
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_DOWN,
    )

    if share <= Decimal("0"):

        await self.db.change_balance(
            rain["user_id"],
            amount,
            kind="rain_refund",
            note=rain_id,
        )

        await channel.send(
            f"## Rain Ended — {money(amount)}\n"
            "The amount was too small to distribute "
            "between the players, so it was refunded."
        )

        return

    # --------------------------------------------------------
    # PAY PLAYERS
    # --------------------------------------------------------

    successful = []
    failed = []

    for user_id in players:

        try:

            credited = await self.db.change_balance(
                user_id,
                share,
                kind="rain",
                note=rain_id,
            )

            if credited:

                successful.append(
                    user_id
                )

            else:

                failed.append(
                    user_id
                )

        except Exception as e:

            print(
                f"[RAIN] Failed to credit {user_id}: {e}"
            )

            failed.append(
                user_id
            )

    # --------------------------------------------------------
    # NOBODY COULD BE CREDITED
    # --------------------------------------------------------

    if not successful:

        try:

            await self.db.change_balance(
                rain["user_id"],
                amount,
                kind="rain_refund",
                note=rain_id,
            )

        except Exception as e:

            print(
                f"[RAIN] Refund error: {e}"
            )

        await channel.send(
            f"## Rain Ended — {money(amount)}\n"
            "Nobody could be credited, so the rain "
            "was refunded."
        )

        return

    # --------------------------------------------------------
    # CALCULATE UNUSED AMOUNT
    # --------------------------------------------------------

    distributed = (
        share
        * Decimal(len(successful))
    )

    remainder = (
        amount
        - distributed
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_DOWN,
    )

    # --------------------------------------------------------
    # RETURN FAILED PLAYER SHARES + ROUNDING REMAINDER
    # TO THE RAIN OWNER
    # --------------------------------------------------------

    if failed:

        failed_amount = (
            share
            * Decimal(len(failed))
        )

        remainder += failed_amount

    if remainder > Decimal("0"):

        try:

            await self.db.change_balance(
                rain["user_id"],
                remainder,
                kind="rain_remainder_refund",
                note=rain_id,
            )

        except Exception as e:

            print(
                f"[RAIN] Remainder refund error: {e}"
            )

    # --------------------------------------------------------
    # PLAYER MENTIONS
    # --------------------------------------------------------

    mention_text = " ".join(
        f"<@{user_id}>"
        for user_id in successful
    )

    # --------------------------------------------------------
    # RESULT
    # --------------------------------------------------------

    await channel.send(
        f"## Rain Ended — {money(amount)}\n"
        f"## **{rain['owner_mention']}** rained on "
        f"**{len(successful)}** players!\n\n"
        f"**{money(share)}** each\n\n"
        f"{mention_text}"
    )


CasinoBot.finish_rain = finish_rain


# ============================================================
# RAIN COMMAND
# ============================================================

def parse_rain_duration(raw: str):
    """Parse rain duration such as 30s, 1m, 5m, or 1h."""
    text = str(raw).strip().lower()
    if not text:
        return None

    units = {
        "s": 1,
        "sec": 1,
        "secs": 1,
        "second": 1,
        "seconds": 1,
        "m": 60,
        "min": 60,
        "mins": 60,
        "minute": 60,
        "minutes": 60,
        "h": 3600,
        "hr": 3600,
        "hrs": 3600,
        "hour": 3600,
        "hours": 3600,
    }

    if text.isdigit():
        # Bare numbers are treated as minutes for convenience.
        seconds = int(text) * 60
    else:
        match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([a-z]+)", text)
        if not match:
            return None
        value = Decimal(match.group(1))
        multiplier = units.get(match.group(2))
        if multiplier is None:
            return None
        seconds = int(value * multiplier)

    if seconds < 10 or seconds > 86400:
        return None
    return seconds


@prefix_command(name="rain")
async def rain_command(
    interaction: discord.Interaction,
    amount: str,
    duration: str,
):

    # --------------------------------------------------------
    # PARSE AMOUNT
    # --------------------------------------------------------

    bet = normalize_amount(
        amount
    )

    if bet is None:

        await bot.safe_send(
            interaction,
            content="Enter a valid rain amount.",
            ephemeral=True,
        )

        return

    if bet <= Decimal("0"):

        await bot.safe_send(
            interaction,
            content="Rain amount must be greater than 0.",
            ephemeral=True,
        )

        return

    # --------------------------------------------------------
    # PARSE DURATION
    # --------------------------------------------------------

    seconds = parse_rain_duration(duration)

    if seconds is None:
        await bot.safe_send(
            interaction,
            content=(
                "Enter a valid rain time. Examples: `30s`, `1m`, `5m`. "
                "Duration must be between 10 seconds and 24 hours."
            ),
            ephemeral=True,
        )
        return

    # --------------------------------------------------------
    # CHECK BALANCE
    # --------------------------------------------------------

    balance = await bot.get_balance(
        interaction.user.id
    )

    if bet > balance:

        await bot.safe_send(
            interaction,
            content=(
                "You Dont Have Enough Crypto\n"
                "-# use /deposit to top-up Funds"
            ),
            ephemeral=True,
        )

        return

    # --------------------------------------------------------
    # DEDUCT RAIN AMOUNT
    # --------------------------------------------------------

    deducted = await bot.db.change_balance(
        interaction.user.id,
        -bet,
        kind="rain_start",
        note="rain",
    )

    if not deducted:

        await bot.safe_send(
            interaction,
            content=(
                "Your balance changed. "
                "Please try again."
            ),
            ephemeral=True,
        )

        return

    # --------------------------------------------------------
    # CREATE RAIN
    # --------------------------------------------------------

    rain_id = secrets.token_hex(8)

    bot.active_rains[rain_id] = {
        "amount": bet,
        "user_id": interaction.user.id,
        "owner_mention": interaction.user.mention,
        "channel_id": interaction.channel_id,
        "players": set(),
    }

    # --------------------------------------------------------
    # SEND RAIN MESSAGE
    # --------------------------------------------------------

    try:

        await interaction.response.send_message(
            f"## Rain Started — **{money(bet)}**\n"
            f"**{interaction.user.mention}** rained — "
            f"**{money(bet)}**\n\n"
            "Click the button below to join.",
            view=RainView(
                bot,
                rain_id,
            ),
        )

    except Exception as e:

        print(
            f"[RAIN] Failed to send rain message: {e}"
        )

        bot.active_rains.pop(
            rain_id,
            None,
        )

        try:

            await bot.db.change_balance(
                interaction.user.id,
                bet,
                kind="rain_refund",
                note=rain_id,
            )

        except Exception as refund_error:

            print(
                f"[RAIN] Failed to refund rain: {refund_error}"
            )

        return

    # --------------------------------------------------------
    # START TIMER
    # --------------------------------------------------------

    asyncio.create_task(
        rain_timer(
            bot,
            rain_id,
            seconds,
        )
    )


async def rain_timer(
    bot_instance: CasinoBot,
    rain_id: str,
    seconds: int,
):

    try:

        await asyncio.sleep(
            seconds
        )

        await bot_instance.finish_rain(
            rain_id
        )

    except asyncio.CancelledError:

        return

    except Exception as e:

        print(
            f"[RAIN] Timer error for {rain_id}: {e}"
        )
# ============================================================
# PART 4 END
# ============================================================

# ============================================================
# bot.py — PART 5 / 10
# COMMANDS: COINFLIP / MINES / RAIN
# ============================================================


# ============================================================
# COINFLIP
# ============================================================

COINFLIP_MULTIPLIER = Decimal("1.96")


# ============================================================
# COINFLIP RESULT IMAGE
# ============================================================

def generate_coinflip_result_image(
    username: str,
    bet: Decimal,
    choice: str,
    result: str,
    won: bool,
):
    import io
    import math

    from PIL import (
        Image,
        ImageDraw,
        ImageFont,
        ImageFilter,
    )

    # ========================================================
    # IMAGE SIZE
    # ========================================================

    WIDTH = 1600
    HEIGHT = 1200

    image = Image.new(
        "RGBA",
        (WIDTH, HEIGHT),
        (5, 6, 14, 255),
    )

    draw = ImageDraw.Draw(image)

    # ========================================================
    # FONTS
    # ========================================================

    def load_font(size, bold=False):

        if bold:
            paths = [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
                "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
                "C:/Windows/Fonts/arialbd.ttf",
                "C:/Windows/Fonts/segoeuib.ttf",
            ]
        else:
            paths = [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
                "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
                "C:/Windows/Fonts/arial.ttf",
                "C:/Windows/Fonts/segoeui.ttf",
            ]

        for path in paths:
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue

        return ImageFont.load_default()

    font_user = load_font(48, True)
    font_bet = load_font(56, True)
    font_result = load_font(82, True)
    font_landed = load_font(40, True)

    # Large coin text
    font_coin = load_font(105, True)

    # ========================================================
    # BACKGROUND
    # ========================================================

    for y in range(HEIGHT):

        ratio = y / HEIGHT

        r = int(5 + ratio * 4)
        g = int(6 + ratio * 5)
        b = int(14 + ratio * 10)

        draw.line(
            [(0, y), (WIDTH, y)],
            fill=(r, g, b, 255),
        )

    # ========================================================
    # DIAGONAL LINES
    # ========================================================

    line_layer = Image.new(
        "RGBA",
        (WIDTH, HEIGHT),
        (0, 0, 0, 0),
    )

    line_draw = ImageDraw.Draw(
        line_layer
    )

    for offset in range(
        -HEIGHT,
        WIDTH,
        60,
    ):

        line_draw.line(
            [
                (offset, 0),
                (offset + HEIGHT, HEIGHT),
            ],
            fill=(70, 75, 110, 40),
            width=2,
        )

    image.alpha_composite(
        line_layer
    )

    draw = ImageDraw.Draw(image)

    # ========================================================
    # CENTER
    # ========================================================

    center_x = WIDTH // 2
    center_y = 600

    # ========================================================
    # HEXAGON
    # ========================================================

    hex_radius = 520

    def hex_points(radius):

        points = []

        for i in range(6):

            angle = math.radians(
                (60 * i) - 30
            )

            x = (
                center_x
                + radius * math.cos(angle)
            )

            y = (
                center_y
                + radius * math.sin(angle)
            )

            points.append(
                (x, y)
            )

        return points

    outer_hex = hex_points(
        hex_radius
    )

    # ========================================================
    # HEXAGON GLOW
    # ========================================================

    glow = Image.new(
        "RGBA",
        (WIDTH, HEIGHT),
        (0, 0, 0, 0),
    )

    glow_draw = ImageDraw.Draw(
        glow
    )

    for size in range(
        70,
        0,
        -2,
    ):

        points = hex_points(
            hex_radius + size
        )

        alpha = max(
            5,
            int(100 - size * 1.3),
        )

        glow_draw.line(
            points + [points[0]],
            fill=(
                255,
                255,
                255,
                alpha,
            ),
            width=10,
            joint="curve",
        )

    glow = glow.filter(
        ImageFilter.GaussianBlur(15)
    )

    image.alpha_composite(
        glow
    )

    draw = ImageDraw.Draw(image)

    # ========================================================
    # HEXAGON FILL
    # ========================================================

    draw.polygon(
        outer_hex,
        fill=(10, 12, 24, 250),
    )

    # ========================================================
    # HEXAGON BORDER
    # ========================================================

    draw.line(
        outer_hex + [outer_hex[0]],
        fill=(
            255,
            255,
            255,
            255,
        ),
        width=7,
        joint="curve",
    )

    inner_hex = hex_points(
        hex_radius - 14
    )

    draw.line(
        inner_hex + [inner_hex[0]],
        fill=(
            255,
            255,
            255,
            210,
        ),
        width=4,
        joint="curve",
    )

    # ========================================================
    # CENTERED TEXT
    # ========================================================

    def centered_text(
        text,
        y,
        font,
        fill,
    ):

        bbox = draw.textbbox(
            (0, 0),
            text,
            font=font,
        )

        text_width = (
            bbox[2] - bbox[0]
        )

        draw.text(
            (
                center_x - text_width / 2,
                y,
            ),
            text,
            font=font,
            fill=fill,
        )

    # ========================================================
    # USERNAME
    # ========================================================

    safe_username = str(
        username
    ).strip()

    if len(safe_username) > 26:

        safe_username = (
            safe_username[:23]
            + "..."
        )

    choice_text = str(
        choice
    ).upper()

    centered_text(
        f"@{safe_username} BETTED",
        105,
        font_user,
        (
            255,
            255,
            255,
            255,
        ),
    )

    centered_text(
        f"{money(bet)} ON {choice_text}",
        165,
        font_bet,
        (
            255,
            255,
            255,
            255,
        ),
    )

    # ========================================================
    # COIN POSITION
    # ========================================================

    coin_x = center_x
    coin_y = 565

    # BIG COIN
    coin_radius = 285

    # ========================================================
    # DETERMINE COIN SIDE
    # ========================================================

    result_lower = str(
        result
    ).strip().lower()

    if result_lower in (
        "heads",
        "head",
        "h",
    ):

        coin_color = (
            92,
            88,
            165,
            255,
        )

        coin_dark = (
            70,
            67,
            135,
            255,
        )

        coin_border = (
            180,
            175,
            230,
            255,
        )

        coin_text = "HEADS"

        glow_color = (
            125,
            120,
            255,
        )

    else:

        coin_color = (
            240,
            65,
            145,
            255,
        )

        coin_dark = (
            205,
            45,
            115,
            255,
        )

        coin_border = (
            255,
            150,
            205,
            255,
        )

        coin_text = "TAILS"

        glow_color = (
            255,
            75,
            165,
        )

    # ========================================================
    # COIN GLOW
    # ========================================================

    coin_glow = Image.new(
        "RGBA",
        (WIDTH, HEIGHT),
        (0, 0, 0, 0),
    )

    coin_glow_draw = ImageDraw.Draw(
        coin_glow
    )

    for extra in range(
        100,
        0,
        -4,
    ):

        alpha = max(
            5,
            int(110 - extra),
        )

        coin_glow_draw.ellipse(
            (
                coin_x
                - coin_radius
                - extra,

                coin_y
                - coin_radius
                - extra,

                coin_x
                + coin_radius
                + extra,

                coin_y
                + coin_radius
                + extra,
            ),
            outline=(
                glow_color[0],
                glow_color[1],
                glow_color[2],
                alpha,
            ),
            width=12,
        )

    coin_glow = coin_glow.filter(
        ImageFilter.GaussianBlur(20)
    )

    image.alpha_composite(
        coin_glow
    )

    draw = ImageDraw.Draw(image)

    # ========================================================
    # COIN SHADOW
    # ========================================================

    shadow = Image.new(
        "RGBA",
        (WIDTH, HEIGHT),
        (0, 0, 0, 0),
    )

    shadow_draw = ImageDraw.Draw(
        shadow
    )

    shadow_draw.ellipse(
        (
            coin_x - coin_radius + 35,
            coin_y - coin_radius + 45,
            coin_x + coin_radius + 45,
            coin_y + coin_radius + 65,
        ),
        fill=(
            0,
            0,
            0,
            230,
        ),
    )

    shadow = shadow.filter(
        ImageFilter.GaussianBlur(25)
    )

    image.alpha_composite(
        shadow
    )

    draw = ImageDraw.Draw(image)

    # ========================================================
    # OUTER COIN
    # ========================================================

    draw.ellipse(
        (
            coin_x - coin_radius,
            coin_y - coin_radius,
            coin_x + coin_radius,
            coin_y + coin_radius,
        ),
        fill=coin_border,
        outline=(
            255,
            255,
            255,
            255,
        ),
        width=8,
    )

    # ========================================================
    # COIN MAIN BODY
    # ========================================================

    edge = coin_radius - 12

    draw.ellipse(
        (
            coin_x - edge,
            coin_y - edge,
            coin_x + edge,
            coin_y + edge,
        ),
        fill=coin_dark,
        outline=(
            255,
            255,
            255,
            90,
        ),
        width=4,
    )

    # ========================================================
    # COIN FACE
    # ========================================================

    face = coin_radius - 25

    draw.ellipse(
        (
            coin_x - face,
            coin_y - face,
            coin_x + face,
            coin_y + face,
        ),
        fill=coin_color,
        outline=(
            255,
            255,
            255,
            130,
        ),
        width=5,
    )

    # ========================================================
    # INNER COIN BORDER
    # ========================================================

    inner = coin_radius - 42

    draw.ellipse(
        (
            coin_x - inner,
            coin_y - inner,
            coin_x + inner,
            coin_y + inner,
        ),
        outline=(
            255,
            255,
            255,
            100,
        ),
        width=4,
    )

    # ========================================================
    # COIN TEXT
    # ========================================================

    bbox = draw.textbbox(
        (0, 0),
        coin_text,
        font=font_coin,
    )

    text_width = (
        bbox[2] - bbox[0]
    )

    text_height = (
        bbox[3] - bbox[1]
    )

    text_x = (
        coin_x
        - text_width / 2
    )

    text_y = (
        coin_y
        - text_height / 2
        - 10
    )

    # --------------------------------------------------------
    # TEXT SHADOW
    # --------------------------------------------------------

    draw.text(
        (
            text_x + 7,
            text_y + 9,
        ),
        coin_text,
        font=font_coin,
        fill=(
            40,
            20,
            40,
            180,
        ),
    )

    # --------------------------------------------------------
    # WHITE TEXT
    # --------------------------------------------------------

    draw.text(
        (
            text_x,
            text_y,
        ),
        coin_text,
        font=font_coin,
        fill=(
            255,
            255,
            255,
            255,
        ),
    )

    # ========================================================
    # COIN TOP HIGHLIGHT
    # ========================================================

    draw.arc(
        (
            coin_x - face + 15,
            coin_y - face + 15,
            coin_x + face - 15,
            coin_y + face - 15,
        ),
        200,
        320,
        fill=(
            255,
            255,
            255,
            170,
        ),
        width=8,
    )

    # ========================================================
    # YOU WON / YOU LOST
    # ========================================================

    if won:

        result_text = "YOU WON"

        result_color = (
            80,
            255,
            150,
            255,
        )

    else:

        result_text = "YOU LOST"

        result_color = (
            255,
            75,
            95,
            255,
        )

    centered_text(
        result_text,
        850,
        font_result,
        result_color,
    )

    # ========================================================
    # LANDED ON
    # ========================================================

    centered_text(
        f"LANDED ON {coin_text}",
        955,
        font_landed,
        (
            255,
            255,
            255,
            235,
        ),
    )

    # ========================================================
    # WIN / LOSS AMOUNT
    # ========================================================

    if won:

        bottom_text = (
            f"You won "
            f"{money(bet * COINFLIP_MULTIPLIER)}"
        )

        bottom_color = (
            90,
            255,
            155,
            255,
        )

    else:

        bottom_text = (
            f"You lost "
            f"{money(bet)}"
        )

        bottom_color = (
            255,
            90,
            110,
            255,
        )

    centered_text(
        bottom_text,
        1015,
        font_landed,
        bottom_color,
    )

    # ========================================================
    # EXPORT
    # ========================================================

    buffer = io.BytesIO()

    image.save(
        buffer,
        format="PNG",
        optimize=True,
    )

    buffer.seek(0)

    return buffer


# ============================================================
# COINFLIP COMMAND
# ============================================================

class CoinflipLobbyView(CasinoV2View):
    def __init__(self, ctx, amount):
        super().__init__(timeout=180)
        self.ctx = ctx
        self.amount = amount
        self._build()

    def _build(self):
        heads = discord.ui.Button(label="Heads", style=discord.ButtonStyle.primary, custom_id="cf_heads")
        tails = discord.ui.Button(label="Tails", style=discord.ButtonStyle.secondary, custom_id="cf_tails")
        heads.callback = self.pick_heads
        tails.callback = self.pick_tails
        self.add_item(discord.ui.Container(
            discord.ui.TextDisplay("## Coinflip — demo"),
            discord.ui.TextDisplay(f"> ﹒pick a side · win pays ≈ **{COINFLIP_MULTIPLIER:.2f}×**\n> ﹒bet **{money(self.amount)}**"),
            discord.ui.Separator(visible=True),
            discord.ui.MediaGallery(discord.MediaGalleryItem(media="attachment://casino_divider.png")),
            discord.ui.MediaGallery(
                discord.MediaGalleryItem(media=COINFLIP_HEADS_IMAGE_URL),
                discord.MediaGalleryItem(media=COINFLIP_TAILS_IMAGE_URL),
            ),
            discord.ui.ActionRow(heads, tails),
            accent_color=0x5865F2,
        ))

    async def _pick(self, interaction, choice):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("This Coinflip menu belongs to another player.", ephemeral=True)
            return
        await interaction.response.defer()
        try:
            await interaction.message.delete()
        except Exception:
            pass
        await coinflip(self.ctx, str(self.amount), choice)

    async def pick_heads(self, interaction):
        await self._pick(interaction, "heads")

    async def pick_tails(self, interaction):
        await self._pick(interaction, "tails")


@prefix_command(
    name="coinflip",
    aliases=["cf"],
)
async def coinflip(
    ctx,
    amount: str,
    choice: str = "",
):

    # ========================================================
    # USER
    # ========================================================

    user = ctx.author
    user_id = user.id

    # No choice supplied: show the new Components V2 selector.
    if not str(choice).strip():
        balance = await bot.get_balance(user_id)
        bet_preview = amount_or_all(amount, balance)
        if bet_preview is None or bet_preview < MIN_BET:
            await ctx.send(embed=error_embed("Invalid Amount", f"Minimum bet is **{money(MIN_BET)}**."))
            return
        divider = _divider_file()
        kwargs = {"view": CoinflipLobbyView(ctx, bet_preview)}
        if divider:
            kwargs["file"] = divider
        await ctx.send(**kwargs)
        return

    # ========================================================
    # NORMALIZE CHOICE
    # ========================================================

    choice = (
        str(choice)
        .strip()
        .lower()
    )

    choice_aliases = {
        "h": "heads",
        "head": "heads",
        "heads": "heads",

        "t": "tails",
        "tail": "tails",
        "tails": "tails",
    }

    choice = choice_aliases.get(
        choice
    )

    if choice is None:

        await ctx.send(
            embed=error_embed(
                "Invalid Choice",
                (
                    "Choose either **heads** "
                    "or **tails**.\n\n"
                    "Examples:\n"
                    "`.cf 1 heads`\n"
                    "`.cf 1 tails`"
                ),
            )
        )

        return

    selected_name = (
        "Heads"
        if choice == "heads"
        else "Tails"
    )

    # ========================================================
    # COOLDOWN
    # ========================================================

    cooldown = bot.check_game_cooldown(
        user_id,
        "coinflip",
    )

    if cooldown:

        await ctx.send(
            embed=error_embed(
                "Cooldown",
                (
                    f"Please wait **{cooldown:.1f}s** "
                    "before playing again."
                ),
            )
        )

        return

    # ========================================================
    # BALANCE
    # ========================================================

    balance = await bot.get_balance(
        user_id
    )

    bet = amount_or_all(
        amount,
        balance,
    )

    if bet is None:

        await ctx.send(
            embed=error_embed(
                "Invalid Amount",
                (
                    "Enter a valid amount.\n\n"
                    "Examples:\n"
                    "`.cf 1 heads`\n"
                    "`.cf 0.50 tails`\n"
                    "`.cf all heads`"
                ),
            )
        )

        return

    bet = Decimal(str(bet))

    # ========================================================
    # MINIMUM BET
    # ========================================================

    if bet < MIN_BET:

        await ctx.send(
            embed=error_embed(
                "Minimum Bet",
                (
                    f"The minimum bet is "
                    f"**{money(MIN_BET)}**."
                ),
            )
        )

        return

    # ========================================================
    # BALANCE CHECK
    # ========================================================

    if bet > balance:

        await ctx.send(
            embed=error_embed(
                "Insufficient Balance",
                (
                    "You don't have enough balance "
                    "for this bet."
                ),
            )
        )

        return

    # ========================================================
    # GAME DATA
    # ========================================================

    game_id = bot.next_game_id()

    server_seed = (
        bot.create_server_seed()
    )

    server_hash = (
        bot.server_hash(
            server_seed
        )
    )

    client_seed = (
        bot.create_client_seed(
            user_id
        )
    )

    nonce = 0

    # ========================================================
    # DEDUCT BET
    # ========================================================

    deducted = await bot.deduct_bet(
        user_id,
        bet,
        "coinflip",
    )

    if not deducted:

        await ctx.send(
            embed=error_embed(
                "Bet Failed",
                (
                    "Your balance changed "
                    "before the bet could be placed. "
                    "Please try again."
                ),
            )
        )

        return

    # ========================================================
    # ACTIVE GAME
    # ========================================================

    bot.register_fair_game(
        user_id, "coinflip", game_id, server_seed, client_seed, nonce,
        "50.00%", f"Selected side: {choice}"
    )

    bot.active_games[user_id] = {
        "type": "coinflip",
        "game_id": game_id,
        "bet": bet,
        "selected": choice,
        "server_seed": server_seed,
        "server_hash": server_hash,
        "client_seed": client_seed,
        "nonce": nonce,
    }

    # ========================================================
    # FLIPPING MESSAGE
    # ========================================================

    flipping_view = CasinoV2View(timeout=30)
    flipping_view.add_item(discord.ui.Container(
        discord.ui.TextDisplay("## Coinflip — Flipping"),
        discord.ui.TextDisplay(f"> ﹒{user.display_name} · **{money(bet)}** on **{selected_name}**\n> ﹒game `#{game_id}`"),
        accent_color=0x5865F2,
    ))
    flipping_message = await ctx.send(view=flipping_view)

    # ========================================================
    # FLIP DELAY
    # ========================================================

    await asyncio.sleep(2)

    # ========================================================
    # GET ACTIVE GAME
    # ========================================================

    game = bot.active_games.pop(
        user_id,
        None,
    )

    if not game:

        try:

            await bot.settle_win(
                user_id,
                bet,
                bet,
                "coinflip_recovery",
            )

        except Exception:
            pass

        await flipping_message.edit(
            embed=error_embed(
                "Game Error",
                (
                    "The game state could not be found. "
                    "Your bet was protected from being lost."
                ),
            )
        )

        return

    # ========================================================
    # PROVABLY FAIR ROLL
    # ========================================================

    try:

        roll = bot.fair_roll(
            game["server_seed"],
            game["client_seed"],
            game["nonce"],
            "coinflip",
        )

    except Exception:

        try:

            await bot.settle_win(
                user_id,
                bet,
                bet,
                "coinflip_recovery",
            )

        except Exception:
            pass

        await flipping_message.edit(
            embed=error_embed(
                "Game Error",
                (
                    "The fair result could not be generated. "
                    "Your bet was refunded."
                ),
            )
        )

        return

    # ========================================================
    # RESULT
    # ========================================================

    result = (
        "heads"
        if roll < Decimal("50")
        else "tails"
    )

    won = (
        result == choice
    )

    # ========================================================
    # SETTLEMENT
    # ========================================================

    try:

        if won:

            payout = (
                bet * COINFLIP_MULTIPLIER
            ).quantize(
                Decimal("0.01"),
                rounding=ROUND_DOWN,
            )

            await bot.settle_win(
                user_id,
                bet,
                payout,
                "coinflip",
            )

        else:

            payout = Decimal("0")

            await bot.settle_loss(
                user_id,
                bet,
                "coinflip",
            )

    except Exception:

        await flipping_message.edit(
            embed=error_embed(
                "Game Error",
                (
                    "The result was generated, "
                    "but the balance settlement failed. "
                    "Please contact an administrator."
                ),
            )
        )

        return

    # ========================================================
    # GENERATE IMAGE
    # ========================================================

    try:

        image_buffer = (
            generate_coinflip_result_image(
                username=user.display_name,
                bet=bet,
                choice=selected_name,
                result=result,
                won=won,
            )
        )

    except Exception:

        await flipping_message.edit(
            embed=error_embed(
                "Image Error",
                (
                    "The game finished successfully, "
                    "but the result image could not "
                    "be generated."
                ),
            )
        )

        return

    # ========================================================
    # DISCORD FILE
    # ========================================================

    image_file = discord.File(
        image_buffer,
        filename="coinflip_result.png",
    )

    # ========================================================
    # COMPONENTS V2 RESULT
    # ========================================================

    result_title = "## Coinflip — WIN" if won else "## Coinflip — LOSE"
    result_body = (
        f"> ﹒**{user.display_name}** · **{money(bet)}** on **{selected_name}**\n"
        f"> ﹒landed on **{result.title()}** · {'+' if won else '-'}{money(payout if won else bet)}\n\n"
        f"**Bet ID:** `#{game_id}`\n"
        f"**Payout:** `{money(payout)}` · **{COINFLIP_MULTIPLIER:.2f}×**\n"
        f"-# Verify this result with `.verify {game_id}`"
    )
    result_view = CasinoV2View(timeout=300)
    result_view.add_item(discord.ui.Container(
        discord.ui.TextDisplay(result_title),
        discord.ui.TextDisplay(result_body),
        discord.ui.Separator(visible=True),
        discord.ui.MediaGallery(discord.MediaGalleryItem(media=COINFLIP_HEADS_IMAGE_URL if result == "heads" else COINFLIP_TAILS_IMAGE_URL)),
        discord.ui.TextDisplay(
            f"-# Provably fair · server hash `{game['server_hash']}` · client seed `{game['client_seed']}` · nonce `{game['nonce']}`"
        ),
        accent_color=0x57F287 if won else 0xED4245,
    ))

    await flipping_message.edit(
        embed=None,
        view=result_view,
        attachments=[],
    )

# ============================================================
# MINES
# ============================================================

def mines_multiplier(
    mines: int,
    opened: int,
) -> Decimal:

    if opened <= 0:
        return Decimal("1.00")

    safe_tiles = 25 - mines

    multiplier = (
        Decimal("25")
        / Decimal(str(safe_tiles))
    ) ** opened

    multiplier *= Decimal("0.96")

    return multiplier.quantize(
        Decimal("0.01"),
        rounding=ROUND_DOWN,
    )


def mines_embed(
    game: MinesGame,
) -> discord.Embed:

    current = mines_multiplier(
        game.mines,
        len(game.opened),
    )

    payout = (
        game.amount * current
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_DOWN,
    )

    embed = base_embed(
        title="## Mines",
        description=(
            f"**Bet:** {money(game.amount)}\n"
            f"**Mines:** {game.mines}\n"
            f"**Opened:** {len(game.opened)}/"
            f"{24 - game.mines}\n"
            f"**Multiplier:** {current:.2f}x\n"
            f"**Current Payout:** {money(payout)}"
        ),
        color=0x00E676,
    )

    embed.add_field(
        name="Game",
        value=f"`#{game.game_id}`",
        inline=True,
    )

    embed.add_field(
        name="Provably Fair",
        value=(
            f"Server Hash: `{game.server_hash}`"
        ),
        inline=False,
    )

    return embed

# ============================================================
# MINES CLICK
# ============================================================

async def mines_click(
    self,
    interaction: discord.Interaction,
    game: MinesGame,
    index: int,
    view: MinesView,
):

    if game.finished:

        await interaction.response.send_message(
            "This Mines game has ended.",
            ephemeral=False,
        )
        return

    if index in game.opened:

        await interaction.response.send_message(
            "That tile is already open.",
            ephemeral=False,
        )
        return

    game.opened.add(index)

    button = next(
        (
            item
            for item in view.children
            if getattr(
                item,
                "custom_id",
                None,
            ) == f"mine:{index}"
        ),
        None,
    )

    if index in game.bombs:

        game.finished = True

        for item in view.children:

            custom_id = getattr(
                item,
                "custom_id",
                "",
            )

            if (
                custom_id.startswith(
                    "mine:"
                )
            ):

                tile_index = int(
                    custom_id.split(":")[1]
                )

                item.disabled = True

                if tile_index in game.bombs:
                    item.label = "💣"
                    item.style = (
                        discord.ButtonStyle.danger
                    )

                elif tile_index in game.opened:
                    item.label = "💎"
                    item.style = (
                        discord.ButtonStyle.success
                    )

        await bot.settle_loss(
            game.user_id,
            game.amount,
            "mines",
        )

        embed = base_embed(
            title="Mines — Bomb!",
            description=(
                f"You hit a bomb.\n\n"
                f"**Bet:** {money(game.amount)}\n"
                f"**Lost:** {money(game.amount)}"
            ),
            color=0xED4245,
        )

        embed.add_field(
            name="Game",
            value=f"`#{game.game_id}`",
            inline=True,
        )

        embed.add_field(
            name="Server Hash",
            value=f"`{game.server_hash}`",
            inline=False,
        )

        bot.active_mines.pop(
            game.user_id,
            None,
        )

        await interaction.response.edit_message(
            embed=embed,
            view=view,
        )

        return

    if button:

        button.label = "💎"
        button.style = (
            discord.ButtonStyle.success
        )
        button.disabled = True

    safe_tiles = 24 - game.mines

    if len(game.opened) >= safe_tiles:

        await mines_cashout(
            self,
            interaction,
            game,
            view,
            automatic=True,
        )

        return

    await interaction.response.edit_message(
        embed=mines_embed(game),
        view=view,
    )


# ============================================================
# MINES CASHOUT
# ============================================================

async def mines_cashout(
    self,
    interaction: discord.Interaction,
    game: MinesGame,
    view: MinesView,
    automatic: bool = False,
):

    if game.finished:

        await interaction.response.send_message(
            "This Mines game has already ended.",
            ephemeral=False,
        )
        return

    if len(game.opened) <= 0:

        await interaction.response.send_message(
            "Open at least one tile before cashing out.",
            ephemeral=False,
        )
        return

    game.finished = True

    multiplier = mines_multiplier(
        game.mines,
        len(game.opened),
    )

    payout = (
        game.amount * multiplier
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_DOWN,
    )

    await bot.settle_win(
        game.user_id,
        game.amount,
        payout,
        "mines",
    )

    for item in view.children:

        custom_id = getattr(
            item,
            "custom_id",
            "",
        )

        if custom_id.startswith("mine:"):

            tile_index = int(
                custom_id.split(":")[1]
            )

            item.disabled = True

            if tile_index in game.bombs:
                item.label = "💣"
                item.style = (
                    discord.ButtonStyle.danger
                )

            elif tile_index in game.opened:
                item.label = "💎"
                item.style = (
                    discord.ButtonStyle.success
                )

    bot.active_mines.pop(
        game.user_id,
        None,
    )

    embed = base_embed(
        title=" Mines — Cashed Out",
        description=(
            f"**Bet:** {money(game.amount)}\n"
            f"**Multiplier:** {multiplier:.2f}x\n"
            f"**Payout:** {money(payout)}"
        ),
        color=0x57F287,
    )

    embed.add_field(
        name="Tiles Opened",
        value=str(len(game.opened)),
        inline=True,
    )

    embed.add_field(
        name="Game",
        value=f"`#{game.game_id}`",
        inline=True,
    )

    embed.add_field(
        name="Provably Fair",
        value=(
            f"Server Hash: `{game.server_hash}`\n"
            f"Client Seed: `{game.client_seed}`\n"
            f"Nonce: `{game.nonce}`"
        ),
        inline=False,
    )

    if automatic:

        embed.title = " Mines — All Safe Tiles!"

    await interaction.response.edit_message(
        embed=embed,
        view=view,
    )


# Attach the methods to the bot instance.
CasinoBot.mines_click = mines_click
CasinoBot.mines_cashout = mines_cashout

# ============================================================
# DEPOSIT SYSTEM
# ============================================================

SOL_DEPOSIT_ADDRESS = (
    "HKn9yAXBBUhPpgTrgnxndLL5QCqocpn8nHjNeWTB7Kv6"
)

USDT_DEPOSIT_ADDRESSES = {
    "Polygon": "0xc21F13F95afb0d53D54ccCa378E177F50f41ECF2",
    "Solana": "HKn9yAXBBUhPpgTrgnxndLL5QCqocpn8nHjNeWTB7Kv6",
    "Tron": "TLmtud4AMeZy5VqetHW9VEGp8dfQCLu5Bp",
    "ETH": "0xc21F13F95afb0d53D54ccCa378E177F50f41ECF2",
}

LTC_MINIMUM_DEPOSIT_USD = Decimal("0.10")


# ============================================================
# DEPOSIT DM HELPER
# ============================================================

async def send_deposit_dm(
    interaction: discord.Interaction,
    currency: str,
    address: str,
    network: str | None = None,
):
    currency = currency.upper()

    if currency == "LTC":

        dm_message = (
            f"**{interaction.user.mention}**, "
            f"deposit **LTC** only:\n\n"
            f"`{address}`\n\n"
            f"Minimum: **$0.10 LTC**"
        )

        server_message = (
            "Your **LTC** deposit address has been "
            "sent to your DMs."
        )

    elif currency == "SOL":

        dm_message = (
            f"**{interaction.user.mention}**, "
            f"deposit **SOL** only:\n\n"
            f"`{address}`"
        )

        server_message = (
            "Your **SOL** deposit address has been "
            "sent to your DMs."
        )

    elif currency == "USDT":

        if not network:
            network = "Unknown"

        dm_message = (
            f"**{interaction.user.mention}**, "
            f"deposit **USDT ({network})** only:\n\n"
            f"`{address}`"
        )

        server_message = (
            f"Your **USDT ({network})** deposit address "
            "has been sent to your DMs."
        )

    else:

        await interaction.response.send_message(
            embed=base_embed(
                "Deposit Error",
                "Unsupported cryptocurrency.",
            ),
            ephemeral=False,
        )

        return

    try:

        await interaction.user.send(
            dm_message
        )

    except discord.Forbidden:

        await interaction.response.send_message(
            embed=base_embed(
                "DMs Disabled",
                (
                    "I couldn't send you a DM.\n\n"
                    "Please enable Direct Messages "
                    "from this server and try again."
                ),
            ),
            ephemeral=False,
        )

        return

    except Exception as e:

        print(
            f"[DEPOSIT] DM error: {e}"
        )

        await interaction.response.send_message(
            embed=base_embed(
                "Deposit Error",
                "Something went wrong while sending your deposit address.",
            ),
            ephemeral=False,
        )

        return

    await interaction.response.send_message(
        embed=base_embed(
            "Deposit Address Sent",
            server_message,
        ),
        ephemeral=False,
    )


# ============================================================
# LTC ADDRESS GENERATION — BIP32 XPUB, NO EXTERNAL PACKAGE REQUIRED
# ============================================================

_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _b58decode(value: str) -> bytes:
    n = 0
    for char in value:
        n = n * 58 + _B58_ALPHABET.index(char)
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    pad = len(value) - len(value.lstrip("1"))
    return b"\x00" * pad + raw


def _b58encode(raw: bytes) -> str:
    n = int.from_bytes(raw, "big")
    out = ""
    while n:
        n, rem = divmod(n, 58)
        out = _B58_ALPHABET[rem] + out
    pad = len(raw) - len(raw.lstrip(b"\x00"))
    return "1" * pad + (out or "1")


def _hash160(data: bytes) -> bytes:
    sha = hashlib.sha256(data).digest()
    try:
        ripemd = hashlib.new("ripemd160")
    except ValueError as exc:
        raise RuntimeError("Python/OpenSSL does not provide RIPEMD160; LTC address generation cannot run.") from exc
    ripemd.update(sha)
    return ripemd.digest()


def _base58check(version: bytes, payload: bytes) -> str:
    body = version + payload
    checksum = hashlib.sha256(hashlib.sha256(body).digest()).digest()[:4]
    return _b58encode(body + checksum)

# secp256k1 parameters for public BIP32 child derivation.
_SECP_P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
_SECP_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
_SECP_G = (
    55066263022277343669578718895168534326250603453777594175500187360389116729240,
    32670510020758816978083085130507043184471273380659243275938904335757337482424,
)


def _point_add(p1, p2):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2 and (y1 + y2) % _SECP_P == 0:
        return None
    if p1 == p2:
        lam = ((3 * x1 * x1) * pow(2 * y1, _SECP_P - 2, _SECP_P)) % _SECP_P
    else:
        lam = ((y2 - y1) * pow((x2 - x1) % _SECP_P, _SECP_P - 2, _SECP_P)) % _SECP_P
    x3 = (lam * lam - x1 - x2) % _SECP_P
    y3 = (lam * (x1 - x3) - y1) % _SECP_P
    return x3, y3


def _point_mul(k: int, point=_SECP_G):
    if k % _SECP_N == 0 or point is None:
        return None
    result = None
    addend = point
    k = int(k)
    while k:
        if k & 1:
            result = _point_add(result, addend)
        addend = _point_add(addend, addend)
        k >>= 1
    return result


def _compress_point(point) -> bytes:
    x, y = point
    return bytes([2 + (y & 1)]) + x.to_bytes(32, "big")


def _decompress_point(data: bytes):
    if len(data) != 33 or data[0] not in (2, 3):
        raise ValueError("Invalid compressed secp256k1 public key")
    x = int.from_bytes(data[1:], "big")
    alpha = (pow(x, 3, _SECP_P) + 7) % _SECP_P
    beta = pow(alpha, (_SECP_P + 1) // 4, _SECP_P)
    y = beta if (beta & 1) == (data[0] & 1) else _SECP_P - beta
    return x, y


def _decode_xpub(xpub: str):
    raw = _b58decode(xpub.strip())
    if len(raw) != 82:
        raise ValueError("Invalid extended public key length")
    body, checksum = raw[:-4], raw[-4:]
    if hashlib.sha256(hashlib.sha256(body).digest()).digest()[:4] != checksum:
        raise ValueError("Invalid extended public key checksum")
    version = body[:4]
    # xpub/tpub and Litecoin public variants are accepted. The key is still
    # interpreted as a BIP32 extended public key; address encoding below is LTC.
    allowed = {
        bytes.fromhex("0488B21E"),  # xpub
        bytes.fromhex("043587CF"),  # tpub
        bytes.fromhex("019DA462"),  # Litecoin Ltub
        bytes.fromhex("0436F6E1"),  # Litecoin Mtub
    }
    if version not in allowed:
        raise ValueError("Configured LTC_XPUB is not a supported extended public key")
    depth = body[4]
    parent_fp = body[5:9]
    child_num = int.from_bytes(body[9:13], "big")
    chain_code = body[13:45]
    pubkey = body[45:78]
    _decompress_point(pubkey)
    return depth, parent_fp, child_num, chain_code, pubkey


def _derive_xpub_child(chain_code: bytes, pubkey: bytes, index: int):
    if not 0 <= index < 2**31:
        raise ValueError("XPUB child index must be non-hardened")
    data = pubkey + index.to_bytes(4, "big")
    digest = hmac.new(chain_code, data, hashlib.sha512).digest()
    il, ir = digest[:32], digest[32:]
    scalar = int.from_bytes(il, "big")
    if scalar >= _SECP_N:
        raise ValueError("Invalid BIP32 child scalar")
    parent_point = _decompress_point(pubkey)
    child_point = _point_add(_point_mul(scalar), parent_point)
    if child_point is None:
        raise ValueError("Invalid BIP32 child point")
    return ir, _compress_point(child_point)


def _ltc_p2pkh_from_pubkey(pubkey: bytes) -> str:
    # Litecoin mainnet P2PKH version = 0x30.
    return _base58check(b"\x30", _hash160(pubkey))


def _ltc_index_for_user(user_id: int) -> int:
    # Deterministic, non-hardened BIP32 child index. This avoids a race-prone
    # global counter while keeping one stable address per Discord user.
    raw = hashlib.sha256(f"cryptobet-ltc:{int(user_id)}".encode()).digest()
    index = int.from_bytes(raw[:4], "big") % (2**31 - 1)
    return max(0, index)


def derive_ltc_address_from_xpub(xpub: str, user_id: int, derivation_path: str = "m/0") -> tuple[str, int]:
    """Derive a unique Litecoin P2PKH address from an XPUB.

    `derivation_path` is relative to the configured XPUB. Only non-hardened
    child steps are allowed because an XPUB cannot derive hardened children.
    The user-specific final index is appended to the configured path.
    """
    depth, _, _, chain_code, pubkey = _decode_xpub(xpub)
    path = str(derivation_path or "m/0").strip()
    if path in ("m", "M", ""):
        steps = []
    else:
        if path.startswith("m/") or path.startswith("M/"):
            path = path[2:]
        steps = [x for x in path.split("/") if x]

    for step in steps:
        if step.endswith(("'", "h", "H")):
            raise ValueError("LTC_DERIVATION_PATH contains a hardened step; XPUB cannot derive it")
        idx = int(step)
        if idx < 0 or idx >= 2**31:
            raise ValueError("Invalid LTC derivation index")
        chain_code, pubkey = _derive_xpub_child(chain_code, pubkey, idx)

    final_index = _ltc_index_for_user(user_id)
    # In the extremely unlikely event of an invalid child, walk forward.
    for offset in range(1000):
        idx = (final_index + offset) % (2**31 - 1)
        try:
            cc, pk = _derive_xpub_child(chain_code, pubkey, idx)
            return _ltc_p2pkh_from_pubkey(pk), idx
        except ValueError:
            continue
    raise RuntimeError("Unable to derive an LTC address from the configured XPUB")


async def get_ltc_deposit_address(user_id: int):
    """Get or create one unique LTC address for the Discord user."""
    if bot.db is None:
        print("[DEPOSIT] Database is not ready")
        return None

    xpub = str(getattr(config, "LTC_XPUB", "") or "").strip()
    if not xpub:
        print("[DEPOSIT] LTC_XPUB is missing from config")
        return None

    try:
        existing = await bot.db.get_deposit_address(user_id, "LTC")
        if existing:
            return existing

        path = getattr(config, "LTC_DERIVATION_PATH", "m/0")
        address, index = derive_ltc_address_from_xpub(xpub, user_id, path)

        # Save atomically through the existing UNIQUE(user_id,currency) and
        # UNIQUE(currency,address) constraints. If another request won the
        # race, return the already stored address.
        saved = await bot.db.save_deposit_address(
            user_id,
            "LTC",
            address,
            index,
        )
        if saved and saved.get("address"):
            return saved["address"]

        existing = await bot.db.get_deposit_address(user_id, "LTC")
        if existing:
            return existing

        print("[DEPOSIT] LTC address was derived but could not be saved")
        return None

    except Exception as exc:
        print(f"[DEPOSIT] LTC address generation error: {type(exc).__name__}: {exc}")
        return None


# ============================================================
# MAIN DEPOSIT MENU
# ============================================================

class DepositCurrencyView(
    discord.ui.View
):

    def __init__(
        self,
        user_id: int,
    ):
        super().__init__(
            timeout=180
        )

        self.user_id = user_id

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:

        if interaction.user.id != self.user_id:

            await interaction.response.send_message(
                embed=base_embed(
                    "Deposit Menu",
                    "This deposit menu belongs to another user.",
                ),
                ephemeral=False,
            )

            return False

        return True

    # ========================================================
    # LTC
    # ========================================================

    @discord.ui.button(
        label="LTC",
        style=discord.ButtonStyle.secondary,
        custom_id="deposit_ltc_new",
    )
    async def ltc_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        address = await get_ltc_deposit_address(
            interaction.user.id
        )

        if not address:

            await interaction.response.send_message(
                embed=base_embed(
                    "LTC Deposit",
                    (
                        "Your LTC deposit address "
                        "could not be generated right now."
                    ),
                ),
                ephemeral=False,
            )

            return

        await send_deposit_dm(
            interaction,
            "LTC",
            address,
        )

    # ========================================================
    # SOL
    # ========================================================

    @discord.ui.button(
        label="SOL",
        style=discord.ButtonStyle.secondary,
        custom_id="deposit_sol_new",
    )
    async def sol_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await send_deposit_dm(
            interaction,
            "SOL",
            SOL_DEPOSIT_ADDRESS,
        )


# ============================================================
# USDT NETWORK MENU
# ============================================================

class USDTNetworkView(
    discord.ui.View
):

    def __init__(
        self,
        user_id: int,
    ):
        super().__init__(
            timeout=180
        )

        self.user_id = user_id

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:

        if interaction.user.id != self.user_id:

            await interaction.response.send_message(
                embed=base_embed(
                    "USDT Deposit",
                    "This deposit menu belongs to another user.",
                ),
                ephemeral=False,
            )

            return False

        return True

    # ========================================================
    # POLYGON
    # ========================================================

    @discord.ui.button(
        label="Polygon",
        style=discord.ButtonStyle.secondary,
        custom_id="deposit_usdt_polygon_new",
        row=0,
    )
    async def polygon_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await send_deposit_dm(
            interaction,
            "USDT",
            USDT_DEPOSIT_ADDRESSES["Polygon"],
            "Polygon",
        )

    # ========================================================
    # SOLANA
    # ========================================================

    @discord.ui.button(
        label="Solana",
        style=discord.ButtonStyle.secondary,
        custom_id="deposit_usdt_solana_new",
        row=0,
    )
    async def solana_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await send_deposit_dm(
            interaction,
            "USDT",
            USDT_DEPOSIT_ADDRESSES["Solana"],
            "Solana",
        )

    # ========================================================
    # TRON
    # ========================================================

    @discord.ui.button(
        label="Tron",
        style=discord.ButtonStyle.secondary,
        custom_id="deposit_usdt_tron_new",
        row=1,
    )
    async def tron_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await send_deposit_dm(
            interaction,
            "USDT",
            USDT_DEPOSIT_ADDRESSES["Tron"],
            "Tron",
        )

    # ========================================================
    # ETH
    # ========================================================

    @discord.ui.button(
        label="ETH",
        style=discord.ButtonStyle.secondary,
        custom_id="deposit_usdt_eth_new",
        row=1,
    )
    async def eth_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await send_deposit_dm(
            interaction,
            "USDT",
            USDT_DEPOSIT_ADDRESSES["ETH"],
            "ETH",
        )


# ============================================================
# /DEPOSIT
# ============================================================

@prefix_command(name="deposit")
async def deposit_command(
    interaction: discord.Interaction,
):

    embed = base_embed(
        "New Deposit: Select Crypto",
        (
            "Choose the cryptocurrency you want to deposit.\n\n"
            "**Litecoin (LTC)** and **Solana (SOL)** are supported."
        ),
    )

    await interaction.response.send_message(
        embed=embed,
        view=DepositCurrencyView(
            interaction.user.id
        ),
        ephemeral=False,
    )
    
# ============================================================
# /HELP
# ============================================================

HELP_TEXT = """
 Games
`.dice <amount> under <number>`
`.dice <amount> low`
`.dice <amount> high`
`.coinflip`
`.mines`
`.frog-run`
`/bj` `.blackjack`

 Wallet
`.balance`
`.deposit`
`.withdraw`
`.tip`

 Rewards
`.rakeback`
`.ranks`
`.rank-rewards`
`.rewardinfo`

 Rain & Affiliates
`.rain`
`.affiliate`
`.aff <code>`
`.affiliates`
`.affiliate-claim`
`.affiliateinfo`

 Competition
`.leaderboard`
`.race`

 Information
`.howtoplay`
`.stats`
`.history`
`.fair`
`.verify`

 Other
`.claim`
`.private-channel`
`.retrigger`
"""




# ============================================================
# /HOWTOPLAY
# ============================================================



# ============================================================
# /REWARDINFO
# ============================================================



# ============================================================
# /AFFILIATEINFO
# ============================================================



# ============================================================
# /STATS
# ============================================================



# ============================================================
# RANK HELPERS
# ============================================================

def _rank_index(
    self,
    wagered: Decimal,
) -> int:

    result = 0

    for index, rank in enumerate(RANKS):

        if wagered >= rank["wager"]:
            result = index

    return result


def _rank_label(
    self,
    rank: dict,
) -> str:

    if rank.get('stage'):
        return (
            f"{rank['name']} "
            f"Stage {rank['stage']}"
        )

    return rank["name"]


CasinoBot.get_rank_index = _rank_index
CasinoBot.rank_label = _rank_label


# ============================================================
# /RANKS
# ============================================================




# ============================================================
# /RAKEBACK
# ============================================================

@prefix_command(name="rakeback")
async def rakeback(
    interaction: discord.Interaction,
):

    row = await bot.get_db_user(
        interaction.user.id
    )

    available = D(
        row["rakeback"]
    )

    if available <= 0:

        await interaction.response.send_message(
            "You Dont have any rakeback avalable . "
            "try again later",
            ephemeral=False,
        )

        return

    if hasattr(
        bot.db,
        "claim_rakeback",
    ):

        amount = D(
            await bot.db.claim_rakeback(
                interaction.user.id
            )
        )

    else:

        amount = available

        await bot.db.pool.execute(
            """
            UPDATE users
            SET rakeback = 0
            WHERE user_id = $1
            """,
            interaction.user.id,
        )

    if amount <= 0:

        await interaction.response.send_message(
            "You Dont have any rakeback avalable . "
            "try again later",
            ephemeral=False,
        )

        return

    await bot.db.change_balance(
        interaction.user.id,
        amount,
        kind="rakeback",
        note="1% loss rakeback",
    )

    await interaction.response.send_message(
        embed=success_embed(
            "Rakeback Claimed",
            f"You received **{money(amount)}**."
        )
    )



# ============================================================
# AFFILIATE CARD IMAGE
# ============================================================

async def create_affiliate_image(
    user: discord.User | discord.Member,
    referrals: int,
    code: str,
    earnings: Decimal,
    commission: Decimal,
) -> discord.File:
    """Create the SwiftBet affiliate card shown by `.affiliate`."""
    width, height = 1500, 620
    bg = (7, 9, 14, 255)
    panel = (17, 20, 28, 255)
    panel2 = (22, 26, 36, 255)
    white = (245, 247, 250, 255)
    muted = (157, 165, 179, 255)
    accent = (160, 95, 255, 255)
    accent2 = (103, 63, 210, 255)

    image = Image.new("RGBA", (width, height), bg)
    draw = ImageDraw.Draw(image, "RGBA")

    # Background glow / subtle casino-card geometry.
    for i in range(9):
        alpha = max(0, 48 - i * 5)
        draw.rounded_rectangle(
            (18 + i * 8, 18 + i * 8, width - 18 - i * 8, height - 18 - i * 8),
            radius=42,
            outline=(*accent2[:3], alpha),
            width=2,
        )

    draw.rounded_rectangle(
        (28, 28, width - 28, height - 28),
        radius=42,
        fill=panel,
        outline=(*accent[:3], 120),
        width=3,
    )

    # Accent strip.
    draw.rounded_rectangle(
        (28, 28, 48, height - 28),
        radius=10,
        fill=accent,
    )

    title_font = create_balance_font(58, True)
    name_font = create_balance_font(54, True)
    label_font = create_balance_font(25, True)
    value_font = create_balance_font(42, True)
    small_font = create_balance_font(25, False)
    code_font = create_balance_font(38, True)

    # Avatar.
    avatar_size = 220
    avatar_x, avatar_y = 92, 105
    try:
        avatar_bytes = await user.display_avatar.replace(size=256).read()
        avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
    except Exception:
        avatar = Image.new("RGBA", (avatar_size, avatar_size), (55, 59, 70, 255))

    avatar = avatar.resize((avatar_size, avatar_size), Image.Resampling.LANCZOS)
    mask = Image.new("L", (avatar_size, avatar_size), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.ellipse((0, 0, avatar_size - 1, avatar_size - 1), fill=255)
    image.paste(avatar, (avatar_x, avatar_y), mask)
    draw.ellipse(
        (avatar_x - 7, avatar_y - 7, avatar_x + avatar_size + 7, avatar_y + avatar_size + 7),
        outline=accent,
        width=7,
    )

    draw.text((360, 88), "SwiftBet", font=title_font, fill=white)
    draw.text((360, 158), "AFFILIATE PROGRAM", font=label_font, fill=accent)
    draw.text((360, 205), str(user.display_name)[:24], font=name_font, fill=white)

    # Code card.
    draw.rounded_rectangle(
        (360, 285, 1000, 405),
        radius=24,
        fill=panel2,
        outline=(*accent[:3], 110),
        width=2,
    )
    draw.text((395, 310), "AFFILIATE CODE", font=small_font, fill=muted)
    draw.text((395, 347), code, font=code_font, fill=white)

    # Stats.
    cards = [
        (1040, 100, 1408, 220, "REFERRED", str(referrals)),
        (1040, 250, 1408, 370, "EARNINGS", money(earnings)),
        (1040, 400, 1408, 520, "COMMISSION", f"{commission:.2f}%"),
    ]
    for x1, y1, x2, y2, label, value in cards:
        draw.rounded_rectangle(
            (x1, y1, x2, y2),
            radius=24,
            fill=panel2,
            outline=(54, 61, 78, 255),
            width=2,
        )
        draw.text((x1 + 24, y1 + 18), label, font=small_font, fill=muted)
        draw.text((x1 + 24, y1 + 58), value, font=value_font, fill=white)

    draw.text(
        (360, 470),
        "Share your code with friends and earn from qualifying activity.",
        font=small_font,
        fill=muted,
    )

    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    output.seek(0)
    return discord.File(output, filename="affiliate.png")


# ============================================================
# /AFFILIATE / /AFFILIATES
# ============================================================

@prefix_command(name="affiliate")
async def affiliate(
    interaction: discord.Interaction,
):
    """Generate the user's SwiftBet affiliate card."""
    if not await require_database(interaction):
        return

    user_id = interaction.user.id

    try:
        row = await bot.db.affiliate(user_id)

        if not row:
            # Generate a short, readable unique affiliate code.
            for _ in range(10):
                code = "SWIFT-" + secrets.token_hex(3).upper()
                try:
                    row = await bot.db.create_affiliate(user_id, code)
                    break
                except Exception as exc:
                    if "unique" not in str(exc).lower():
                        raise
                    row = None

            if not row:
                raise RuntimeError("Could not create a unique affiliate code.")

        stats = await bot.db.pool.fetchrow(
            """
            SELECT
                a.code,
                a.referrals,
                a.earnings
            FROM affiliates a
            WHERE a.user_id = $1
            """,
            user_id,
        )

        if not stats:
            raise RuntimeError("Affiliate record was not found after creation.")

        referrals = int(stats["referrals"] or 0)
        earnings = D(stats["earnings"] or 0)
        rate = Decimal("0")
        for minimum, tier_rate in AFFILIATE_TIERS:
            if referrals >= minimum:
                rate = tier_rate
        commission = rate * Decimal("100")

        file = await create_affiliate_image(
            interaction.user,
            referrals,
            str(stats["code"]),
            earnings,
            commission,
        )

        embed = base_embed(
            title="",
            description="",
        )
        embed.set_image(url="attachment://affiliate.png")

        await interaction.response.send_message(
            embed=embed,
            file=file,
            ephemeral=False,
        )

    except Exception as exc:
        print(f"[AFFILIATE] {type(exc).__name__}: {exc}")
        await interaction.response.send_message(
            embed=error_embed(
                "Affiliate Error",
                "Your affiliate information could not be generated right now.",
            ),
            ephemeral=False,
        )


@prefix_command(name="aff")
async def aff_command(
    interaction: discord.Interaction,
    code: str,
):
    """Apply another player's affiliate code."""
    if not await require_database(interaction):
        return

    code = str(code).strip().upper()
    if not code:
        await interaction.response.send_message(
            embed=error_embed("Invalid Code", "Please provide an affiliate code."),
            ephemeral=False,
        )
        return

    try:
        row = await bot.db.pool.fetchrow(
            """
            SELECT user_id, code
            FROM affiliates
            WHERE UPPER(code) = UPPER($1)
            LIMIT 1
            """,
            code,
        )

        if not row:
            await interaction.response.send_message(
                embed=error_embed("Invalid Affiliate Code", "That affiliate code does not exist."),
                ephemeral=False,
            )
            return

        affiliate_id = int(row["user_id"])

        if affiliate_id == interaction.user.id:
            await interaction.response.send_message(
                embed=error_embed("Invalid Referral", "You cannot use your own affiliate code."),
                ephemeral=False,
            )
            return

        # set_referrer() is transactional and refuses duplicate referrals/self-referrals.
        applied = await bot.db.set_referrer(
            interaction.user.id,
            affiliate_id,
        )

        if not applied:
            await interaction.response.send_message(
                embed=error_embed(
                    "Referral Already Set",
                    "Your account already has an affiliate/referrer and cannot be changed.",
                ),
                ephemeral=False,
            )
            return

        await interaction.response.send_message(
            embed=success_embed(
                "Affiliate Code Applied",
                f"You are now referred by affiliate code **{row['code']}**.",
            ),
            ephemeral=False,
        )

    except Exception as exc:
        print(f"[AFF CODE] {type(exc).__name__}: {exc}")
        await interaction.response.send_message(
            embed=error_embed(
                "Affiliate Error",
                "The affiliate code could not be applied right now.",
            ),
            ephemeral=False,
        )




# ============================================================
# /TIP
# ============================================================



# ============================================================
# /LEADERBOARD
# ============================================================



# ============================================================
# RACE
# ============================================================

async def send_race_message(
    interaction: discord.Interaction,
):

    ongoing = await bot.db.setting(
        "race_active",
        "0",
    )

    rows = []

    if ongoing == "1":

        if hasattr(
            bot.db,
            "race_leaderboard",
        ):
            rows = await bot.db.race_leaderboard(
                3
            )

        lines = [
            " 3 Day Race — On GOING",
            "",
        ]

        for row in rows:

            lines.append(
                f"<@{row['user_id']}> : "
                f"{money(row['wagered'])} wagared"
            )

        if not rows:
            lines.append(
                "No wagerers yet."
            )

    else:

        if hasattr(
            bot.db,
            "race_winners",
        ):

            rows = await bot.db.race_winners(
                3
            )

        lines = [
            " 3 Day Race — Winners!",
            "",
        ]

        prizes = [
            Decimal("70"),
            Decimal("50"),
            Decimal("30"),
        ]

        for index, row in enumerate(rows[:3]):

            prize = prizes[index]

            lines.append(
                f"**{index + 1}.** "
                f"<@{row['user_id']}> — "
                f"{money(prize)}"
            )

        lines.extend(
            [
                "",
                "Winners Open Ticket",
            ]
        )

    await interaction.response.send_message(
        embed=base_embed(
            description="\n".join(lines)
        )
    )




# ============================================================
# OWNER RACE COMMANDS
# ============================================================

def owner_only():
    return prefix_owner_only()





@prefix_command(name="race-start")
@owner_only()
async def race_start(
    interaction: discord.Interaction,
):

    await bot.db.set_setting(
        "race_active",
        "1",
    )

    if hasattr(
        bot.db,
        "reset_race",
    ):
        await bot.db.reset_race()

    await interaction.response.send_message(
        "## 3 Day Race — Started\n\n"
        "The wager race has started."
    )


@prefix_command(name="race-end")
@owner_only()
async def race_end(
    interaction: discord.Interaction,
):

    if hasattr(
        bot.db,
        "finish_race",
    ):

        await bot.db.finish_race()

    await bot.db.set_setting(
        "race_active",
        "0",
    )

    await interaction.response.send_message(
        "## 3 Day Race — Ended\n\n"
        "Winners are now available through `.race`."
    )




# ============================================================
# /RETRIGGER
# ============================================================

@prefix_command(name="retrigger")
async def retrigger(
    interaction: discord.Interaction,
):

    user_id = interaction.user.id

    game = bot.active_games.get(
        user_id
    )

    if game:

        await interaction.response.send_message(
            "Your active game has been restored.",
            ephemeral=False,
        )

        return

    if user_id in bot.active_mines:

        await interaction.response.send_message(
            "Your Mines game is still active.",
            ephemeral=False,
        )

        return

    await interaction.response.send_message(
        "No recoverable game was found.",
        ephemeral=False,
    )


# ============================================================
# /PRIVATE-CHANNEL
# ============================================================

class PrivateChannelView(ButtonView):

    def __init__(
        self,
        bot_instance: CasinoBot,
        owner_id: int,
    ):

        super().__init__(
            timeout=600
        )

        self.bot = bot_instance
        self.owner_id = owner_id

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:

        if interaction.user.id != self.owner_id:

            await interaction.response.send_message(
                "Only the channel owner can use these controls.",
                ephemeral=False,
            )

            return False

        return True

    @discord.ui.button(
        label="Add Member",
        style=discord.ButtonStyle.success,
    )
    async def add_member(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await interaction.response.send_modal(
            PrivateMemberModal(
                self.bot,
                interaction.channel.id,
                add=True,
            )
        )

    @discord.ui.button(
        label="Remove Member",
        style=discord.ButtonStyle.secondary,
    )
    async def remove_member(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await interaction.response.send_modal(
            PrivateMemberModal(
                self.bot,
                interaction.channel.id,
                add=False,
            )
        )

    @discord.ui.button(
        label="Delete",
        style=discord.ButtonStyle.danger,
    )
    async def delete_channel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        channel = interaction.channel

        await interaction.response.send_message(
            "Deleting this private channel.",
            ephemeral=False,
        )

        await channel.delete(
            reason="Private channel deleted by owner."
        )


class PrivateMemberModal(discord.ui.Modal):

    def __init__(
        self,
        bot_instance: CasinoBot,
        channel_id: int,
        add: bool,
    ):

        super().__init__(
            title=(
                "Add Member"
                if add
                else "Remove Member"
            )
        )

        self.bot = bot_instance
        self.channel_id = channel_id
        self.add_member_mode = add

        self.user_id_input = discord.ui.TextInput(
            label="User ID",
            placeholder="Discord user ID",
            required=True,
            max_length=25,
        )

        self.add_item(
            self.user_id_input
        )

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ):

        channel = interaction.guild.get_channel(
            self.channel_id
        )

        if not channel:

            await interaction.response.send_message(
                "Channel not found.",
                ephemeral=False,
            )

            return

        try:

            user_id = int(
                self.user_id_input.value.strip()
            )

        except ValueError:

            await interaction.response.send_message(
                "Invalid user ID.",
                ephemeral=False,
            )

            return

        member = interaction.guild.get_member(
            user_id
        )

        if not member:

            try:
                member = await interaction.guild.fetch_member(
                    user_id
                )
            except discord.HTTPException:

                await interaction.response.send_message(
                    "Member not found.",
                    ephemeral=False,
                )

                return

        overwrite = channel.overwrites_for(
            member
        )

        overwrite.view_channel = (
            self.add_member_mode
        )

        await channel.set_permissions(
            member,
            overwrite=overwrite,
        )

        await interaction.response.send_message(
            (
                f"{member.mention} was added."
                if self.add_member_mode
                else f"{member.mention} was removed."
            ),
            ephemeral=False,
        )


@prefix_command(name="private-channel")
async def private_channel(
    interaction: discord.Interaction,
):

    balance_value = await bot.get_balance(
        interaction.user.id
    )

    if balance_value < Decimal("25"):

        await interaction.response.send_message(
            "You need at least **$25.00** balance "
            "to create a private channel.",
            ephemeral=False,
        )

        return

    guild = interaction.guild

    if guild is None:

        await interaction.response.send_message(
            "This command can only be used in a server.",
            ephemeral=False,
        )

        return

    category = interaction.channel.category

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=False
        ),
        interaction.user: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
        ),
    }

    channel = await guild.create_text_channel(
        name=f"private-{interaction.user.name}",
        category=category,
        overwrites=overwrites,
        reason="Private channel created.",
    )

    await channel.send(
        f"## Private Channel\n"
        f"Owner: {interaction.user.mention}\n\n"
        "This channel requires a **$25 balance**.\n"
        "If your balance stays below $25 for 10 minutes, "
        "the channel may be closed.",
        view=PrivateChannelView(
            bot,
            interaction.user.id,
        ),
    )

    await interaction.response.send_message(
        f"Private channel created: {channel.mention}",
        ephemeral=False,
    )


# ============================================================
# PRIVATE CHANNEL BALANCE MONITOR
# ============================================================

@tasks.loop(minutes=1)
async def private_channel_monitor():

    if not bot.db:
        return

    for guild in bot.guilds:

        for channel in guild.text_channels:

            if not channel.name.startswith(
                "private-"
            ):
                continue

            owner_id = None

            try:

                owner_name = channel.name[
                    len("private-"):
                ]

                member = discord.utils.find(
                    lambda m:
                    m.name == owner_name
                    and m.guild.id == guild.id,
                    guild.members,
                )

                if member:
                    owner_id = member.id

            except Exception:
                continue

            if not owner_id:
                continue

            balance_value = await bot.get_balance(
                owner_id
            )

            if balance_value >= Decimal("25"):
                continue

            marker = (
                f"private_low_balance:"
                f"{channel.id}"
            )

            since = await bot.db.setting(
                marker,
                "",
            )

            if not since:

                await bot.db.set_setting(
                    marker,
                    datetime.now(
                        timezone.utc
                    ).isoformat(),
                )

                continue

            try:

                started = datetime.fromisoformat(
                    since
                )

                elapsed = (
                    datetime.now(
                        timezone.utc
                    )
                    - started
                ).total_seconds()

            except Exception:

                elapsed = 0

            if elapsed >= 600:

                try:
                    await channel.delete(
                        reason=(
                            "Private channel balance "
                            "below $25 for 10 minutes."
                        )
                    )
                except discord.HTTPException:
                    pass


# ============================================================
# /CLAIM
# ============================================================

# ============================================================
# PROMO CODE HELPERS
# ============================================================

def _member_has_status(member: discord.Member, required: str) -> bool:
    required = str(required or "").strip().casefold()
    if not required:
        return True
    for activity in getattr(member, "activities", ()) or ():
        if isinstance(activity, discord.CustomActivity):
            values = [getattr(activity, "name", ""), getattr(activity, "state", "")]
            haystack = " ".join(str(v or "") for v in values).casefold()
            if required in haystack:
                return True
        else:
            values = [getattr(activity, "name", ""), getattr(activity, "state", "")]
            haystack = " ".join(str(v or "") for v in values).casefold()
            if required in haystack:
                return True
    return False


def _find_member_with_status(user_id: int, required: str):
    for guild in bot.guilds:
        member = guild.get_member(user_id)
        if member and _member_has_status(member, required):
            return member
    return None


def create_promo_image(code: str, reward: Decimal, max_uses: int, deposit_requirement: Decimal, required_status: str) -> discord.File:
    """Render the supplied promo-card design with the newly generated values."""
    try:
        image = Image.open(PROMO_TEMPLATE_PATH).convert("RGBA")
    except Exception:
        image = Image.new("RGBA", (880, 398), (20, 24, 50, 255))

    # Blue-tinted ad background while preserving the card layout.
    overlay = Image.new("RGBA", image.size, (0, 110, 255, 45))
    image = Image.alpha_composite(image, overlay)
    draw = ImageDraw.Draw(image)

    def font(size, bold=False):
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        ]
        for path in candidates:
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
        return ImageFont.load_default()

    # Clear dynamic areas from the template, leaving the card and logo intact.
    draw.rounded_rectangle((295, 82, 590, 145), radius=8, fill=(22, 17, 38, 255))
    draw.rounded_rectangle((300, 150, 585, 205), radius=8, fill=(22, 17, 38, 255))
    draw.rounded_rectangle((50, 245, 835, 315), radius=8, fill=(22, 17, 38, 255))

    code_font = font(43, True)
    reward_font = font(34, True)
    chip_font = font(15, True)

    def centered(text, y, f, fill):
        box = draw.textbbox((0, 0), text, font=f)
        x = (image.width - (box[2] - box[0])) / 2
        draw.text((x, y), text, font=f, fill=fill)

    centered(code, 88, code_font, (184, 90, 255, 255))
    centered(f"+{money(reward)}", 153, reward_font, (78, 230, 135, 255))

    requirements = [f"max claims · {max_uses}", f"deposited ≥ {money(deposit_requirement)}"]
    if required_status:
        requirements.append(f"status: {required_status}")
    x = 56
    y = 251
    for text_value in requirements:
        width = draw.textbbox((0, 0), text_value, font=chip_font)[2] + 26
        if x + width > 824:
            x = 56
            y += 31
        draw.rounded_rectangle((x, y, x + width, y + 27), radius=14, fill=(57, 38, 91, 255))
        draw.text((x + 13, y + 5), text_value, font=chip_font, fill=(235, 228, 250, 255))
        x += width + 9

    out = io.BytesIO()
    image.convert("RGB").save(out, format="WEBP", quality=92, method=6)
    out.seek(0)
    return discord.File(out, filename="promo_code.webp")


# ============================================================
# /CLAIM
# ============================================================

@prefix_command(name="claim")
async def claim(interaction: discord.Interaction, code: str):
    code = code.strip().upper()
    promo = await bot.db.pool.fetchrow(
        """
        SELECT code, amount, max_uses, uses, active, required_deposit, required_status
        FROM promo_codes
        WHERE code=$1
        """,
        code,
    )
    if not promo or not promo["active"]:
        await interaction.response.send_message("That promo code is invalid or expired.", ephemeral=False)
        return
    if promo["uses"] >= promo["max_uses"]:
        await interaction.response.send_message("That promo code has reached its maximum uses.", ephemeral=False)
        return

    required_deposit = D(promo["required_deposit"])
    if required_deposit > 0:
        lifetime = await bot.db.pool.fetchval(
            "SELECT lifetime_deposit FROM users WHERE user_id=$1",
            interaction.user.id,
        )
        if D(lifetime) < required_deposit:
            await interaction.response.send_message(
                f"You need at least **{money(required_deposit)} deposited** to claim this code.",
                ephemeral=False,
            )
            return

    required_status = str(promo["required_status"] or "").strip()
    if required_status:
        member = _find_member_with_status(interaction.user.id, required_status)
        if not member:
            await interaction.response.send_message(
                f"Your Discord status must contain **{required_status}** to claim this code.",
                ephemeral=False,
            )
            return

    result = await bot.db.claim_code(interaction.user.id, code)
    # Database.claim_code returns (ok, message, amount).
    if not isinstance(result, tuple):
        await interaction.response.send_message("The promo code could not be claimed.", ephemeral=False)
        return
    ok, message, amount = result
    if not ok:
        await interaction.response.send_message(str(message), ephemeral=False)
        return

    view = CasinoV2View(timeout=120)
    view.add_item(
        discord.ui.Container(
            discord.ui.TextDisplay("## Promo Claimed"),
            discord.ui.TextDisplay(f"> ﹒you received **{money(amount)}**\n> ﹒code `{code}`"),
            accent_color=0x57F287,
        )
    )
    await interaction.response.send_message(view=view)


# ============================================================
# /CODECHANNEL
# ============================================================

@prefix_command(name="codechannel")
@owner_only()
async def codechannel_command(interaction: discord.Interaction, channel: discord.TextChannel):
    await bot.db.set_setting("code_channel_id", str(channel.id))
    view = CasinoV2View(timeout=120)
    view.add_item(
        discord.ui.Container(
            discord.ui.TextDisplay("## Promo Code Channel"),
            discord.ui.TextDisplay(f"> ﹒new promo cards will be posted in {channel.mention}"),
            accent_color=0x5865F2,
        )
    )
    await interaction.response.send_message(view=view)


# ============================================================
# /CODE
# ============================================================

@prefix_command(name="code")
@owner_only()
async def code_command(
    interaction: discord.Interaction,
    amount: str,
    max_uses: int,
    deposited: str,
    status: str = "",
):
    if max_uses <= 0:
        await interaction.response.send_message("Max claims must be greater than zero.", ephemeral=False)
        return

    reward = normalize_amount(amount)
    deposit_requirement = normalize_amount(deposited)
    if reward is None or reward <= 0:
        await interaction.response.send_message("Invalid reward amount.", ephemeral=False)
        return
    if deposit_requirement is None or deposit_requirement < 0:
        await interaction.response.send_message("Invalid deposit requirement.", ephemeral=False)
        return

    channel_id = await bot.db.setting("code_channel_id", "")
    if not channel_id:
        await interaction.response.send_message("Set the promo channel first with `.codechannel #channel`.", ephemeral=False)
        return
    try:
        channel = bot.get_channel(int(channel_id)) or await bot.fetch_channel(int(channel_id))
    except Exception:
        channel = None
    if channel is None:
        await interaction.response.send_message("The configured promo channel could not be found.", ephemeral=False)
        return

    code = "GOOSE-" + "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
    await bot.db.create_code(
        code,
        reward,
        max_uses,
        requirement=0,
        created_by=interaction.user.id,
        required_deposit=deposit_requirement,
        required_status=status.strip(),
    )

    file = create_promo_image(
        code,
        reward,
        max_uses,
        deposit_requirement,
        status.strip(),
    )
    try:
        await channel.send(file=file)
    except Exception as exc:
        print(f"[PROMO IMAGE] {exc}")
        await interaction.response.send_message("The promo code was created, but the image could not be posted.", ephemeral=False)
        return

    view = CasinoV2View(timeout=120)
    req = f"deposit ≥ {money(deposit_requirement)}"
    if status.strip():
        req += f" · status contains `{status.strip()}`"
    view.add_item(
        discord.ui.Container(
            discord.ui.TextDisplay("## Promo Code Created"),
            discord.ui.TextDisplay(
                f"> ﹒code `{code}` · **{money(reward)}** per person\n"
                f"> ﹒max claims **{max_uses}** · {req}\n"
                f"> ﹒posted in {channel.mention}"
            ),
            accent_color=0x5865F2,
        )
    )
    await interaction.response.send_message(view=view)

# ============================================================
# /ADDBAL
# ============================================================

@prefix_command(name="addbal")
@bot_owner_only()
async def addbal_command(
    interaction: discord.Interaction,
    user: discord.Member,
    amount: str,
):

    # .addbal is STRICTLY owner-only. Do not allow ADMIN_USER_IDS or
    # Discord permissions to bypass the bot owner check.
    owner_id = getattr(config, "OWNER_ID", None)
    try:
        owner_id = int(owner_id) if owner_id is not None else None
    except (TypeError, ValueError):
        owner_id = None

    if owner_id is None or interaction.user.id != owner_id:
        await interaction.response.send_message(
            embed=error_embed(
                "Permission Denied",
                "Only the bot owner can use `.addbal`.",
            ),
            ephemeral=False,
        )
        return

    if not await require_database(interaction):
        return

    value = normalize_amount(amount)

    if value is None:
        await interaction.response.send_message(
            embed=error_embed(
                "Invalid Amount",
                "Please enter a valid amount greater than **$0.00**.",
            ),
            ephemeral=False,
        )
        return

    success = await bot.db.change_balance(
        user.id,
        value,
        kind="admin_addbal",
        note=f"Added by {interaction.user.id}",
    )

    if not success:
        await interaction.response.send_message(
            embed=error_embed(
                "Failed",
                "The balance could not be updated.",
            ),
            ephemeral=False,
        )
        return

    new_balance = await bot.get_balance(user.id)

    await interaction.response.send_message(
        embed=success_embed(
            "Balance Added",
            (
                f"**User:** {user.mention}\n"
                f"**Added:** {money(value)}\n"
                f"**New Balance:** {money(new_balance)}"
            ),
        ),
        ephemeral=False,
    )




# ============================================================
# /FROG-RUN
# ============================================================

FROG_ROWS = 6
FROG_COLS = 3


def frog_board_text(view: "FrogRunView") -> str:
    rows = []
    for row_index in range(FROG_ROWS):
        cells = []
        for col in range(FROG_COLS):
            state = view.board[row_index][col]
            if (
                not view.finished
                and row_index == view.position
                and state == "unknown"
                and col == 1
            ):
                cells.append("🐸")
            elif state == "frog":
                cells.append("🐸")
            elif state == "safe":
                cells.append("🟩")
            elif state == "lost":
                cells.append("🟥")
            else:
                cells.append("🟫")
        rows.append(" ".join(cells))
    return "\n".join(rows)


def frog_embed(view: "FrogRunView", title="🐸 Frog Run", color=0xB8BCC2, extra=""):
    description = (
        f"{frog_board_text(view)}\n\n"
        f"**Bet:** {money(view.amount)}\n"
        f"**Stage:** {view.position}/{FROG_ROWS}\n"
        f"**Multiplier:** {view.multiplier:.2f}x\n"
        f"**Current Payout:** {money(view.amount * view.multiplier)}"
    )
    if extra:
        description += f"\n\n{extra}"
    return base_embed(title, description, color)


class FrogRunView(ButtonView):

    def __init__(self, bot_instance: CasinoBot, user_id: int, amount: Decimal, game_id: int):
        super().__init__(timeout=300)
        self.bot = bot_instance
        self.user_id = user_id
        self.amount = amount
        self.game_id = game_id
        self.server_seed = ""
        self.server_hash = ""
        self.client_seed = ""
        self.nonce = 0
        self.position = 0
        self.multiplier = Decimal("1.00")
        self.finished = False
        self.board = [["unknown" for _ in range(FROG_COLS)] for _ in range(FROG_ROWS)]
        self.make_buttons()

    def make_buttons(self):
        self.clear_items()
        for index in range(FROG_COLS):
            button = discord.ui.Button(
                label=f"Lane {index + 1}",
                style=discord.ButtonStyle.secondary,
                custom_id=f"frog:{index}",
                row=0,
            )
            button.callback = self.make_callback(index)
            self.add_item(button)
        cashout = discord.ui.Button(
            label="Cashout",
            emoji="💰",
            style=discord.ButtonStyle.success,
            custom_id="frog_cashout",
            row=1,
        )
        cashout.callback = self.cashout
        self.add_item(cashout)

    def make_callback(self, lane: int):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message(
                    "This Frog Run belongs to another player.",
                    ephemeral=False,
                )
                return
            await self.bot.frog_step(interaction, self, lane)
        return callback

    async def cashout(self, interaction: discord.Interaction):
        if self.finished:
            await interaction.response.send_message("This game has ended.", ephemeral=False)
            return
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This game belongs to another player.", ephemeral=False)
            return
        self.finished = True
        payout = (self.amount * self.multiplier).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        await self.bot.settle_win(self.user_id, self.amount, payout, "frog-run")
        for child in self.children:
            child.disabled = True
        result_file = create_game_result_image("Frog Run", "CASHED OUT", self.amount, payout, f"Stage {self.position}/{FROG_ROWS}")
        result_embed = frog_embed(
            self,
            "🐸 Frog Run — Cashed Out",
            0x57F287,
            f"**Payout:** {money(payout)}",
        )
        result_embed.set_image(url="attachment://game_result.png")
        await interaction.response.edit_message(
            embed=result_embed,
            view=self,
            attachments=[result_file],
        )


async def _frog_step(self, interaction: discord.Interaction, view: FrogRunView, lane: int):
    if view.finished:
        await interaction.response.send_message("This game has ended.", ephemeral=False)
        return

    row_index = view.position
    safe_lane = self.fair_int(
        view.server_seed, view.client_seed, view.nonce + view.position,
        0, FROG_COLS - 1, "frog-run"
    )

    if lane != safe_lane:
        view.finished = True
        view.board[row_index][safe_lane] = "safe"
        view.board[row_index][lane] = "lost"
        for child in view.children:
            child.disabled = True
        await self.settle_loss(view.user_id, view.amount, "frog-run")
        result_file = create_game_result_image("Frog Run", "LOSS", view.amount, Decimal("0"), f"Wrong lane at stage {view.position + 1}")
        result_embed = frog_embed(
            view,
            "🐸 Frog Run — Lost",
            0xED4245,
            f"You chose the wrong lane.\n**Lost:** {money(view.amount)}",
        )
        result_embed.set_image(url="attachment://game_result.png")
        await interaction.response.edit_message(
            embed=result_embed,
            view=view,
            attachments=[result_file],
        )
        return

    view.board[row_index][safe_lane] = "safe"
    view.position += 1
    view.multiplier = (Decimal("1.20") ** view.position).quantize(Decimal("0.01"))

    if view.position >= FROG_ROWS:
        view.finished = True
        payout = (view.amount * view.multiplier).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        await self.settle_win(view.user_id, view.amount, payout, "frog-run")
        for child in view.children:
            child.disabled = True
        result_file = create_game_result_image("Frog Run", "FINISHED", view.amount, payout, "All rows cleared")
        result_embed = frog_embed(view, "🐸 Frog Run — Finished!", 0x57F287, f"**Payout:** {money(payout)}")
        result_embed.set_image(url="attachment://game_result.png")
        await interaction.response.edit_message(
            embed=result_embed,
            view=view,
            attachments=[result_file],
        )
        return

    await interaction.response.edit_message(
        embed=frog_embed(view),
        view=view,
    )


CasinoBot.frog_step = _frog_step


@prefix_command(name="frog-run")
async def frog_run(interaction: discord.Interaction, amount: str):
    balance = await bot.get_balance(interaction.user.id)
    value = amount_or_all(amount, balance)
    if value is None or value < MIN_FROG_BET:
        await interaction.response.send_message("Minimum Frog Run bet is $0.10.", ephemeral=False)
        return

    remaining = bot.check_game_cooldown(interaction.user.id, "frog-run")
    if remaining:
        await interaction.response.send_message(f"Please wait **{remaining:.1f}s**.", ephemeral=False)
        return

    success = await bot.deduct_bet(interaction.user.id, value, "frog-run")
    if not success:
        await interaction.response.send_message("You Dont Have Enough Crypto", ephemeral=False)
        return

    game_id = bot.next_game_id()
    server_seed = bot.create_server_seed()
    client_seed = bot.create_client_seed(interaction.user.id)
    bot.register_fair_game(
        interaction.user.id, "frog-run", game_id, server_seed, client_seed, 0,
        "33.33% per lane on each row",
        f"{FROG_COLS} lanes; the safe lane is derived from HMAC-SHA256."
    )
    view = FrogRunView(bot, interaction.user.id, value, game_id)
    view.server_seed = server_seed
    view.server_hash = bot.server_hash(server_seed)
    view.client_seed = client_seed
    view.nonce = 0
    await interaction.response.send_message(
        embed=frog_embed(view, extra="Choose a lane to jump. 🐸"),
        view=view,
    )

# ============================================================
# DICE — UNDER / LOW / HIGH
# ============================================================

def create_dice_result_image(
    roll: Decimal,
    target: Decimal,
    mode: str,
    won: bool,
    bet: Decimal,
    payout: Decimal,
    chance: Decimal,
    username: str,
):
    """Create the Dice result image with the red losing zone and blue roll marker."""
    width, height = 1100, 420
    image = Image.new("RGB", (width, height), (8, 16, 27))
    draw = ImageDraw.Draw(image)

    def font(size, bold=False):
        paths = (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            if bold else
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        )
        try:
            return ImageFont.truetype(paths, size)
        except Exception:
            return ImageFont.load_default()

    title_font = font(34, True)
    value_font = font(30, True)
    small_font = font(22, False)
    tiny_font = font(18, False)

    # Header.
    draw.text((42, 28), "DICE", font=title_font, fill=(245, 247, 250))
    result_text = "WIN" if won else "LOSE"
    result_color = (65, 220, 135) if won else (255, 70, 95)
    draw.text((width - 185, 30), result_text, font=title_font, fill=result_color)

    draw.text((42, 78), f"{username}  •  Bet {money(bet)}", font=small_font, fill=(170, 184, 199))

    # Slider matching the supplied visual: red area is the losing area.
    x0, x1 = 55, width - 55
    track_y = 205
    track_h = 42
    radius = track_h // 2
    draw.rounded_rectangle((x0, track_y, x1, track_y + track_h), radius=radius,
                           fill=(34, 51, 66), outline=(67, 88, 105), width=2)

    # Losing zone: for under N, N..100 loses; for low, 51..100 loses;
    # for high, 0..49 loses. The boundary is represented by target.
    if mode == "under":
        boundary = max(0, min(100, float(target)))
        red_start = x0 + (boundary / 100.0) * (x1 - x0)
        draw.rounded_rectangle((red_start, track_y + 8, x1, track_y + track_h - 8),
                               radius=12, fill=(237, 29, 67))
        condition = f"UNDER {target.quantize(Decimal('0.01'))}"
    elif mode == "low":
        boundary = 50.0
        red_start = x0 + 0.51 * (x1 - x0)
        draw.rectangle((red_start, track_y + 8, x1, track_y + track_h - 8), fill=(237, 29, 67))
        condition = "LOW ≤ 50"
    else:
        boundary = 50.0
        red_end = x0 + 0.49 * (x1 - x0)
        draw.rectangle((x0, track_y + 8, red_end, track_y + track_h - 8), fill=(237, 29, 67))
        condition = "HIGH ≥ 50"

    # Scale labels.
    for n in (0, 25, 50, 75, 100):
        px = x0 + (n / 100.0) * (x1 - x0)
        text = str(n)
        bb = draw.textbbox((0, 0), text, font=tiny_font)
        draw.text((px - (bb[2] - bb[0]) / 2, 158), text, font=tiny_font, fill=(155, 170, 184))

    # Roll marker.
    roll_f = max(0.0, min(100.0, float(roll)))
    marker_x = x0 + (roll_f / 100.0) * (x1 - x0)
    marker_w = 56
    draw.rounded_rectangle(
        (marker_x - marker_w / 2, track_y - 9, marker_x + marker_w / 2, track_y + track_h + 9),
        radius=10,
        fill=(42, 142, 238),
    )
    draw.line((marker_x, track_y + 2, marker_x, track_y + track_h - 2), fill=(215, 235, 255), width=4)

    # Roll bubble.
    bubble = f"{roll.quantize(Decimal('0.01'))}"
    bb = draw.textbbox((0, 0), bubble, font=tiny_font)
    bw = (bb[2] - bb[0]) + 24
    bh = (bb[3] - bb[1]) + 16
    bx = max(8, min(width - bw - 8, marker_x - bw / 2))
    by = 112
    draw.rounded_rectangle((bx, by, bx + bw, by + bh), radius=9, fill=(235, 245, 239))
    draw.text((bx + 12, by + 8), bubble, font=tiny_font, fill=(32, 50, 41))

    # Result details.
    draw.text((42, 288), condition, font=value_font, fill=(245, 247, 250))
    chance_text = f"Winning chance: {chance.quantize(Decimal('0.01'))}%"
    draw.text((42, 335), chance_text, font=small_font, fill=(170, 184, 199))

    payout_text = f"Payout: {money(payout)}   •   {'+' if won else '-'}{money((payout - bet) if won else bet)}"
    bb = draw.textbbox((0, 0), payout_text, font=small_font)
    draw.text((width - 42 - (bb[2] - bb[0]), 335), payout_text, font=small_font,
              fill=(65, 220, 135) if won else (255, 70, 95))

    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    output.seek(0)
    return discord.File(output, filename="dice_result.png")


@prefix_command(name="dice")
async def dice_command(
    interaction: discord.Interaction,
    amount: str,
    mode: str,
    number: Optional[str] = None,
):
    """Play Dice with an exact 30% player win probability.

    .dice <amount> under <number>
    .dice <amount> low
    .dice <amount> high

    The first provably-fair HMAC value decides the 30% win/loss outcome.
    A second HMAC value chooses a roll inside the corresponding winning or
    losing region, so the displayed roll always matches the selected rule.
    """
    if not await require_database(interaction):
        return

    user_id = interaction.user.id
    cooldown = bot.check_game_cooldown(user_id, "dice")
    if cooldown:
        await bot.safe_send(
            interaction,
            content=f"Please wait **{cooldown:.1f}s** before starting another game.",
            ephemeral=False,
        )
        return

    balance = await bot.get_balance(user_id)
    bet = amount_or_all(amount, balance)
    if bet is None or bet < MIN_BET:
        await bot.safe_send(
            interaction,
            embed=error_embed("Invalid Bet", f"Minimum bet is {money(MIN_BET)}. Use `all`, `half`, or `max` for balance-based bets."),
            ephemeral=False,
        )
        return

    mode = str(mode).strip().lower()
    target = None

    if mode == "under":
        if number is None:
            await bot.safe_send(
                interaction,
                embed=error_embed("Missing Number", "Use `.dice 1 under 45` for example."),
                ephemeral=False,
            )
            return
        try:
            target = Decimal(str(number))
        except (InvalidOperation, ValueError):
            target = None
        if target is None or target <= 0 or target >= 100:
            await bot.safe_send(
                interaction,
                embed=error_embed("Invalid Number", "The target must be greater than 0 and less than 100."),
                ephemeral=False,
            )
            return
    elif mode in {"low", "high"}:
        if number is not None:
            await bot.safe_send(
                interaction,
                embed=error_embed("Invalid Command", "Use `.dice <amount> low` or `.dice <amount> high`."),
                ephemeral=False,
            )
            return
        target = Decimal("50")
    else:
        await bot.safe_send(
            interaction,
            embed=error_embed(
                "Invalid Dice Mode",
                "Use `.dice <amount> under <number>`, `.dice <amount> low`, or `.dice <amount> high`.",
            ),
            ephemeral=False,
        )
        return

    balance = await bot.get_balance(user_id)
    if bet > balance:
        await bot.safe_send(
            interaction,
            content="You Dont Have Enough Crypto\n-# use .deposit to top-up Funds",
            ephemeral=False,
        )
        return

    WIN_CHANCE = Decimal("30")
    multiplier = DICE_MULTIPLIER

    game_id = bot.next_game_id()
    server_seed = bot.create_server_seed()
    client_seed = bot.create_client_seed(user_id)
    nonce = 0

    if not await bot.deduct_bet(user_id, bet, "dice"):
        await bot.safe_send(
            interaction,
            content="Your balance changed. Please try again or deposit funds.",
            ephemeral=False,
        )
        return

    bot.register_fair_game(
        user_id,
        "dice",
        game_id,
        server_seed,
        client_seed,
        nonce,
        "30%",
        f"Mode={mode}; target={target}; weighted result generated from HMAC-SHA256."
    )

    # --------------------------------------------------------
    # PROVABLY FAIR 30% RESULT
    # --------------------------------------------------------
    # One deterministic HMAC decides whether the player wins.
    # A second deterministic HMAC chooses the displayed roll inside the
    # appropriate region, ensuring the image and result always agree.
    outcome_digest = bot.fair_digest(
        server_seed,
        client_seed,
        nonce,
        "dice-outcome",
    )
    position_digest = bot.fair_digest(
        server_seed,
        client_seed,
        nonce,
        "dice-position",
    )

    outcome_number = int.from_bytes(outcome_digest[:8], "big")
    position_number = int.from_bytes(position_digest[:8], "big")
    outcome_unit = Decimal(outcome_number) / Decimal(2**64)
    position_unit = Decimal(position_number) / Decimal(2**64)

    won = outcome_unit < (WIN_CHANCE / Decimal("100"))

    if mode == "under":
        winning_min = Decimal("0")
        winning_max = target
        losing_min = target
        losing_max = Decimal("100")
    elif mode == "low":
        winning_min = Decimal("0")
        winning_max = Decimal("50")
        losing_min = Decimal("50.01")
        losing_max = Decimal("100")
    else:
        winning_min = Decimal("50")
        winning_max = Decimal("100")
        losing_min = Decimal("0")
        losing_max = Decimal("49.99")

    region_min = winning_min if won else losing_min
    region_max = winning_max if won else losing_max
    roll = region_min + ((region_max - region_min) * position_unit)
    roll = roll.quantize(Decimal("0.01"), rounding=ROUND_DOWN)

    # Keep the exact boundary semantics after quantization.
    if mode == "under":
        if won and roll >= target:
            roll = max(Decimal("0.00"), target - Decimal("0.01"))
        elif not won and roll < target:
            roll = target
    elif mode == "low":
        if won and roll > Decimal("50"):
            roll = Decimal("50.00")
        elif not won and roll <= Decimal("50"):
            roll = Decimal("50.01")
    else:
        if won and roll < Decimal("50"):
            roll = Decimal("50.00")
        elif not won and roll >= Decimal("50"):
            roll = Decimal("49.99")

    payout = (bet * multiplier).quantize(Decimal("0.01"), rounding=ROUND_DOWN) if won else Decimal("0")

    try:
        if won:
            await bot.settle_win(user_id, bet, payout, "dice")
        else:
            await bot.settle_loss(user_id, bet, "dice")
    except Exception:
        try:
            await bot.db.change_balance(user_id, bet, kind="game_refund", note="dice_settlement_error")
        except Exception:
            pass
        bot.clear_fair_game(user_id)
        await bot.safe_send(
            interaction,
            embed=error_embed(
                "Game Error",
                "The result was generated but settlement failed. Your bet was refunded if possible.",
            ),
            ephemeral=False,
        )
        return

    result = "WIN" if won else "LOSS"
    try:
        file = create_dice_result_image(
            roll=roll,
            target=target,
            mode=mode,
            won=won,
            bet=bet,
            payout=payout,
            chance=WIN_CHANCE,
            username=interaction.user.display_name,
        )
    except Exception as exc:
        print(f"[DICE IMAGE] {type(exc).__name__}: {exc}")
        file = None

    condition = (
        f"UNDER {target.quantize(Decimal('0.01'))}"
        if mode == "under"
        else "LOW ≤ 50"
        if mode == "low"
        else "HIGH ≥ 50"
    )

    embed = base_embed(
        title=f"Dice — {result}",
        description=(
            f"**Game:** `#{game_id}`\n"
            f"**Roll:** `{roll.quantize(Decimal('0.01'))}`\n"
            f"**Condition:** `{condition}`\n"
            f"**Winning Chance:** `30%`\n"
            f"**Bet:** `{money(bet)}`\n"
            f"**Payout:** `{money(payout)}`\n"
            f"**Multiplier:** `{multiplier}x`"
        ),
        color=0x57F287 if won else 0xED4245,
    )
    embed.add_field(
        name="Provably Fair",
        value=(
            f"**ID:** `GAME-{game_id:06d}`\n"
            f"**Server Hash:** `{bot.server_hash(server_seed)}`\n"
            f"**Client Seed:** `{client_seed}`\n"
            f"**Nonce:** `{nonce}`"
        ),
        inline=False,
    )
    embed.set_footer(text="Verify this result with .verify <game_number>")

    if file:
        embed.set_image(url="attachment://dice_result.png")
        await interaction.response.send_message(embed=embed, file=file, ephemeral=False)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=False)


# ============================================================
# MINES CLICK
# ============================================================

async def _mines_click(
    self,
    interaction: discord.Interaction,
    game: MinesGame,
    index: int,
    view: MinesView,
):
    if game.finished:
        await interaction.response.send_message(
            "This game has ended.",
            ephemeral=True,
        )
        return

    button = next(
        (
            child for child in view.walk_children()
            if isinstance(child, discord.ui.Button)
            and child.custom_id == f"mine:{index}"
        ),
        None,
    )

    if index in game.bombs:
        game.finished = True

        # Reveal the board in-place. Do not replace the message with a new
        # result embed/message.
        for child in view.walk_children():
            if not isinstance(child, discord.ui.Button):
                continue
            cid = child.custom_id or ""
            if not cid.startswith("mine:"):
                continue
            tile_index = int(cid.split(":")[1])
            child.disabled = True
            if tile_index in game.bombs:
                child.label = "×"
                child.style = discord.ButtonStyle.danger
            elif tile_index in game.opened:
                child.label = "✓"
                child.style = discord.ButtonStyle.success

        await self.settle_loss(game.user_id, game.amount, "mines")
        self.active_mines.pop(game.user_id, None)

        player = self.get_user(game.user_id)
        username = player.display_name if player else "Player"
        view.set_result(
            "## Mines — LOSE",
            (
                f"> ﹒**{username}** · **-{money(game.amount)}** at "
                f"`{game.multiplier:.4f}×` · mines · **{game.mines} mines** · "
                f"**{len(game.opened)}** safe · stake `{money(game.amount)}`\n\n"
                f"`Bet ID {game.game_id}` · hit a mine"
            ),
            won=False,
        )
        await interaction.response.edit_message(
            view=view,
            attachments=[_divider_file()] if _divider_file() else [],
        )
        return

    game.opened.add(index)

    if button:
        button.label = "✓"
        button.style = discord.ButtonStyle.success
        button.disabled = True

    safe_count = 25 - game.mines

    if len(game.opened) >= safe_count:
        game.finished = True
        payout = game.payout
        await self.settle_win(
            game.user_id,
            game.amount,
            payout,
            "mines",
        )
        self.active_mines.pop(game.user_id, None)

        player = self.get_user(game.user_id)
        username = player.display_name if player else "Player"
        net = payout - game.amount
        view.set_result(
            "## Mines — WIN",
            (
                f"> ﹒{username} · **+{money(payout)} (`+{money(net)}` net)** at "
                f"`{game.multiplier:.4f}×` ﹒mines · **{game.mines} mines** · "
                f"**{len(game.opened)}** · **{game.multiplier:.2f}×** · "
                f"stake `{money(game.amount)}`\n\n"
                f"`Bet ID {game.game_id}` · hit a big one? drop a vouch"
            ),
            won=True,
        )
        await interaction.response.edit_message(
            view=view,
            attachments=[_divider_file()] if _divider_file() else [],
        )
        return

    view.rebuild()
    await interaction.response.edit_message(
        view=view,
        attachments=[_divider_file()] if _divider_file() else [],
    )


CasinoBot.mines_click = _mines_click


# ============================================================
# MINES CASHOUT
# ============================================================

async def _mines_cashout(
    self,
    interaction: discord.Interaction,
    game: MinesGame,
    view: MinesView,
):
    if game.finished:
        await interaction.response.send_message(
            "This game has ended.",
            ephemeral=True,
        )
        return

    if not game.opened:
        await interaction.response.send_message(
            "Open at least one tile before cashing out.",
            ephemeral=True,
        )
        return

    game.finished = True
    payout = game.payout
    await self.settle_win(
        game.user_id,
        game.amount,
        payout,
        "mines",
    )

    # Reveal remaining bombs and keep the same V2 panel/message.
    for child in view.walk_children():
        if not isinstance(child, discord.ui.Button):
            continue
        cid = child.custom_id or ""
        if not cid.startswith("mine:"):
            continue
        idx = int(cid.split(":")[1])
        child.disabled = True
        if idx in game.bombs:
            child.label = "×"
            child.style = discord.ButtonStyle.danger
        elif idx in game.opened:
            child.label = "✓"
            child.style = discord.ButtonStyle.success

    self.active_mines.pop(game.user_id, None)
    player = self.get_user(game.user_id)
    username = player.display_name if player else "Player"
    net = payout - game.amount

    view.set_result(
        "## Mines — WIN",
        (
            f"> ﹒{username} · **+{money(payout)} (`+{money(net)}` net)** at "
            f"`{game.multiplier:.4f}×` ﹒mines · **{game.mines} mines** · "
            f"**{len(game.opened)}** · **{game.multiplier:.2f}×** · "
            f"stake `{money(game.amount)}`\n\n"
            f"`Bet ID {game.game_id}` · hit a big one? drop a vouch"
        ),
        won=True,
    )
    await interaction.response.edit_message(
        view=view,
        attachments=[_divider_file()] if _divider_file() else [],
    )


CasinoBot.mines_cashout = _mines_cashout

# ============================================================
# /BLACKJACK / /BJ
# ============================================================

def blackjack_card_value(card: str) -> int:
    value = card.split("_")[0].lower()

    if value in {
        "jack",
        "queen",
        "king",
    }:
        return 10

    if value == "ace":
        return 11

    try:
        return int(value)
    except ValueError:
        return 10


def blackjack_hand_total(cards: list[str]) -> int:
    total = sum(
        blackjack_card_value(card)
        for card in cards
        if card != "hidden"
    )

    aces = sum(
        1
        for card in cards
        if card.startswith("ace_")
    )

    while total > 21 and aces:
        total -= 10
        aces -= 1

    return total


def blackjack_deck(
    server_seed: Optional[str] = None,
    client_seed: Optional[str] = None,
    nonce: int = 0,
    fair_bot: Optional[CasinoBot] = None,
) -> list[str]:
    suits = [
        "clubs",
        "diamonds",
        "hearts",
        "spades",
    ]

    ranks = [
        "2",
        "3",
        "4",
        "5",
        "6",
        "7",
        "8",
        "9",
        "10",
        "jack",
        "queen",
        "king",
        "ace",
    ]

    cards = [
        f"{rank}_of_{suit}"
        for suit in suits
        for rank in ranks
    ]

    if server_seed and client_seed and fair_bot is not None:
        return fair_bot.fair_shuffle(cards, server_seed, client_seed, nonce, "blackjack")

    # Kept only as a compatibility fallback for non-game utility calls.
    random.shuffle(cards)
    return cards


def card_path(card: str) -> Path:
    return BASE_DIR / f"{card}.png"


# ============================================================
# BLACKJACK IMAGE
# ============================================================

def create_blackjack_image(
    player_cards: list[str],
    dealer_cards: list[str],
    bet=0,
    hidden: bool = True,
    result: Optional[str] = None,
) -> Optional[discord.File]:

    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None

    # ========================================================
    # CANVAS
    # ========================================================

    WIDTH = 940
    HEIGHT = 650

    BACKGROUND = (35, 36, 38, 255)
    WHITE = (235, 235, 235, 255)
    RED = (190, 25, 25, 255)

    canvas = Image.new(
        "RGBA",
        (WIDTH, HEIGHT),
        BACKGROUND,
    )

    draw = ImageDraw.Draw(canvas)

    # ========================================================
    # FONTS
    # ========================================================

    def load_font(size: int, bold: bool = False):

        if bold:
            font_paths = [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
            ]
        else:
            font_paths = [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
            ]

        for font_path in font_paths:
            try:
                return ImageFont.truetype(
                    font_path,
                    size,
                )
            except Exception:
                continue

        return ImageFont.load_default()

    title_font = load_font(
        27,
        True,
    )

    result_font = load_font(
        39,
        True,
    )

    bet_font = load_font(
        19,
        True,
    )

    side_font = load_font(
        18,
        True,
    )

    chip_font = load_font(
        21,
        True,
    )

    # ========================================================
    # TEXT HELPER
    # ========================================================

    def centered_text(
        text: str,
        y: int,
        font,
        fill,
    ):

        bbox = draw.textbbox(
            (0, 0),
            text,
            font=font,
        )

        width = bbox[2] - bbox[0]

        draw.text(
            (
                (WIDTH - width) // 2,
                y,
            ),
            text,
            font=font,
            fill=fill,
        )

    # ========================================================
    # LOAD CARD
    # ========================================================

    def load_card(card: str):

        if card == "hidden":
            return None

        path = card_path(card)

        if not path.exists():
            return None

        try:

            image = Image.open(
                path
            ).convert("RGBA")

            max_width = 125
            max_height = 190

            ratio = min(
                max_width / image.width,
                max_height / image.height,
            )

            new_size = (
                max(
                    1,
                    int(image.width * ratio),
                ),
                max(
                    1,
                    int(image.height * ratio),
                ),
            )

            return image.resize(
                new_size,
                Image.Resampling.LANCZOS,
            )

        except Exception:
            return None

    # ========================================================
    # CARD BACK
    # ========================================================

    def create_card_back():

        card_width = 125
        card_height = 190

        card = Image.new(
            "RGBA",
            (
                card_width,
                card_height,
            ),
            (45, 46, 49, 255),
        )

        card_draw = ImageDraw.Draw(
            card
        )

        # Outer border
        card_draw.rounded_rectangle(
            (
                0,
                0,
                card_width - 1,
                card_height - 1,
            ),
            radius=7,
            fill=(48, 49, 52, 255),
            outline=(180, 180, 180, 255),
            width=2,
        )

        # Inner border
        card_draw.rounded_rectangle(
            (
                7,
                7,
                card_width - 8,
                card_height - 8,
            ),
            radius=5,
            outline=(100, 101, 104, 255),
            width=2,
        )

        # Diamond pattern
        for y in range(
            20,
            card_height - 15,
            20,
        ):

            for x in range(
                20,
                card_width - 15,
                20,
            ):

                card_draw.polygon(
                    [
                        (x, y - 5),
                        (x + 5, y),
                        (x, y + 5),
                        (x - 5, y),
                    ],
                    fill=(75, 76, 79, 255),
                )

        return card

    # ========================================================
    # DRAW CARDS
    # ========================================================

    def draw_cards(
        cards: list[str],
        y: int,
        hide_hidden: bool = False,
    ):

        images = []

        for card in cards:

            if card == "hidden":

                if hide_hidden:
                    images.append(
                        create_card_back()
                    )

                continue

            image = load_card(card)

            if image:
                images.append(image)

        if not images:
            return

        spacing = 12

        total_width = (
            sum(
                image.width
                for image in images
            )
            + spacing * (
                len(images) - 1
            )
        )

        start_x = (
            WIDTH - total_width
        ) // 2

        x = start_x

        for image in images:

            # Shadow
            shadow = Image.new(
                "RGBA",
                image.size,
                (0, 0, 0, 0),
            )

            shadow_draw = ImageDraw.Draw(
                shadow
            )

            shadow_draw.rounded_rectangle(
                (
                    3,
                    5,
                    image.width - 1,
                    image.height - 1,
                ),
                radius=7,
                fill=(0, 0, 0, 100),
            )

            canvas.alpha_composite(
                shadow,
                (
                    x + 3,
                    y + 5,
                ),
            )

            canvas.alpha_composite(
                image,
                (
                    x,
                    y,
                ),
            )

            x += (
                image.width
                + spacing
            )

    # ========================================================
    # DEALER TOTAL
    # ========================================================

    if hidden:

        dealer_text = "DEALER — ?"

    else:

        dealer_total = (
            blackjack_hand_total(
                dealer_cards
            )
        )

        dealer_text = (
            f"DEALER — {dealer_total}"
        )

    centered_text(
        dealer_text,
        16,
        title_font,
        WHITE,
    )

    # ========================================================
    # DEALER CARDS
    # ========================================================

    draw_cards(
        dealer_cards,
        49,
        hide_hidden=hidden,
    )

    # ========================================================
    # RESULT BANNER
    # ========================================================

    if result:

        result = result.lower().strip()

        if result == "win":
            result_text = "PLAYER WINS"

        elif result == "loss":
            result_text = "DEALER WINS"

        elif result == "push":
            result_text = "PUSH"

        else:
            result_text = result.upper()

        # Dark horizontal strip
        draw.rectangle(
            (
                0,
                232,
                WIDTH,
                294,
            ),
            fill=(24, 25, 27, 255),
        )

        centered_text(
            result_text,
            245,
            result_font,
            RED,
        )

    # ========================================================
    # PLAYER CARDS
    # ========================================================

    draw_cards(
        player_cards,
        303,
        hide_hidden=False,
    )

    # ========================================================
    # BET CHIP
    # ========================================================

    def draw_chip(amount):

        try:
            amount_text = (
                f"${float(amount):.2f}"
            )
        except Exception:
            amount_text = "$0.00"

        cx = WIDTH // 2
        cy = 548

        # Shadow
        draw.ellipse(
            (
                cx - 48 + 3,
                cy - 48 + 5,
                cx + 48 + 3,
                cy + 48 + 5,
            ),
            fill=(0, 0, 0, 100),
        )

        # Main chip
        draw.ellipse(
            (
                cx - 48,
                cy - 48,
                cx + 48,
                cy + 48,
            ),
            fill=(38, 50, 70, 255),
            outline=(175, 185, 200, 255),
            width=3,
        )

        # Inner circle
        draw.ellipse(
            (
                cx - 39,
                cy - 39,
                cx + 39,
                cy + 39,
            ),
            outline=(200, 205, 215, 255),
            width=2,
        )

        # Chip marks
        import math

        for angle in range(
            0,
            360,
            45,
        ):

            radians = math.radians(
                angle
            )

            x1 = cx + int(
                math.cos(radians) * 34
            )

            y1 = cy + int(
                math.sin(radians) * 34
            )

            x2 = cx + int(
                math.cos(radians) * 43
            )

            y2 = cy + int(
                math.sin(radians) * 43
            )

            draw.line(
                (
                    x1,
                    y1,
                    x2,
                    y2,
                ),
                fill=(225, 228, 235, 255),
                width=5,
            )

        # Amount
        bbox = draw.textbbox(
            (0, 0),
            amount_text,
            font=chip_font,
        )

        text_width = (
            bbox[2] - bbox[0]
        )

        text_height = (
            bbox[3] - bbox[1]
        )

        draw.text(
            (
                cx - text_width // 2,
                cy - text_height // 2 - 1,
            ),
            amount_text,
            font=chip_font,
            fill=(240, 240, 240, 255),
        )

    draw_chip(
        bet
    )

    # ========================================================
    # BET TEXT
    # ========================================================

    centered_text(
        "BET",
        601,
        bet_font,
        WHITE,
    )

    # ========================================================
    # SIDE BET LABELS
    # ========================================================

    draw.text(
        (
            164,
            608,
        ),
        "21+3",
        font=side_font,
        fill=(115, 115, 115, 255),
    )

    pairs_text = "PAIRS"

    pairs_bbox = draw.textbbox(
        (0, 0),
        pairs_text,
        font=side_font,
    )

    pairs_width = (
        pairs_bbox[2]
        - pairs_bbox[0]
    )

    draw.text(
        (
            WIDTH - 164 - pairs_width,
            608,
        ),
        pairs_text,
        font=side_font,
        fill=(115, 115, 115, 255),
    )

    # ========================================================
    # EXPORT
    # ========================================================

    output = io.BytesIO()

    canvas.save(
        output,
        format="PNG",
        optimize=True,
    )

    output.seek(0)

    return discord.File(
        output,
        filename="blackjack.png",
    )


# ============================================================
# BLACKJACK VIEW
# ============================================================

class BlackjackView(CasinoV2View):
    def __init__(self, bot_instance: CasinoBot, user_id: int, game: dict, dealt: bool = False):
        super().__init__(timeout=3600)
        self.bot = bot_instance
        self.user_id = user_id
        self.game = game
        self.dealt = dealt
        self.rebuild()

    def rebuild(self, image_name="blackjack.png", result_text=None):
        self.clear_items()
        game = self.game
        player_total = blackjack_hand_total(game["player"])
        dealer_total = "?" if "hidden" in game["dealer"] else blackjack_hand_total(game["dealer"])
        title = "## Blackjack" if result_text is None else f"## Blackjack — {result_text}"
        body = (
            f"> ﹒**{money(game['bet'])} bet** · ﹒player **{player_total}** · dealer **{dealer_total}**\n"
            f"> ﹒game `#{game['game_id']}` · hit **Deal** when you're ready" if not self.dealt and result_text is None else
            f"> ﹒**{money(game['bet'])} bet** · ﹒player **{player_total}** · dealer **{dealer_total}**\n"
            f"> ﹒game `#{game['game_id']}`"
        )
        icon_url = game.get("guild_icon_url")
        if icon_url:
            children=[
                discord.ui.Section(
                    discord.ui.TextDisplay(title),
                    accessory=discord.ui.Thumbnail(icon_url),
                ),
                discord.ui.TextDisplay(body),
                discord.ui.Separator(visible=True),
            ]
        else:
            children=[discord.ui.TextDisplay(title), discord.ui.TextDisplay(body), discord.ui.Separator(visible=True)]
        media_name = "casino_divider.png" if (not self.dealt and result_text is None) else image_name
        if media_name:
            children.append(discord.ui.MediaGallery(discord.MediaGalleryItem(media=f"attachment://{media_name}")))
        if result_text is None and not self.game.get("finished"):
            if not self.dealt:
                deal = discord.ui.Button(label="Deal", style=discord.ButtonStyle.success, custom_id=f"bj_deal:{game['game_id']}")
                deal.callback = self.deal
                children.append(discord.ui.ActionRow(deal))
            else:
                hit = discord.ui.Button(label="Hit", style=discord.ButtonStyle.primary)
                stand = discord.ui.Button(label="Stand", style=discord.ButtonStyle.success)
                double = discord.ui.Button(label="Double", style=discord.ButtonStyle.secondary)
                hit.callback = self.hit; stand.callback = self.stand; double.callback = self.double
                children.append(discord.ui.ActionRow(hit, stand, double))
        children.append(discord.ui.TextDisplay(f"-# Provably fair · verify with `.verify {game['game_id']}`"))
        self.add_item(discord.ui.Container(*children, accent_color=0x7C4DFF if result_text is None else (0x57F287 if result_text == "Won" else 0xED4245 if result_text == "Lost" else 0xFEE75C)))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This Blackjack game belongs to another player.", ephemeral=True)
            return False
        return True

    async def deal(self, interaction: discord.Interaction):
        self.dealt = True
        file = create_blackjack_image(self.game["player"], self.game["dealer"], bet=self.game["bet"], hidden=True)
        self.rebuild()
        await interaction.response.edit_message(view=self, attachments=[file] if file else [])

    async def hit(self, interaction: discord.Interaction):
        await self.bot.blackjack_hit(interaction, self)

    async def stand(self, interaction: discord.Interaction):
        await self.bot.blackjack_stand(interaction, self)

    async def double(self, interaction: discord.Interaction):
        await self.bot.blackjack_double(interaction, self)


# ============================================================
# BLACKJACK FINISH
# ============================================================

async def _blackjack_finish(
    self,
    interaction: discord.Interaction,
    view: BlackjackView,
    result: str,
):

    game = view.game

    if game["finished"]:
        return

    game["finished"] = True

    player_total = blackjack_hand_total(
        game["player"]
    )

    dealer_total = blackjack_hand_total(
        game["dealer"]
    )

    # ========================================================
    # WIN
    # ========================================================

    if result == "win":

        payout = (
            game["bet"]
            * Decimal("2")
        )

        await self.settle_win(
            game["user_id"],
            game["bet"],
            payout,
            "blackjack",
        )

        title = "Blackjack — Won"
        color = 0x57F287

    # ========================================================
    # PUSH
    # ========================================================

    elif result == "push":

        payout = game["bet"]

        await self.db.change_balance(
            game["user_id"],
            payout,
            kind="blackjack_push",
            note="blackjack",
        )

        fair = self.get_fair_game(game["user_id"])
        await self.db.record_game(
            game["user_id"], game["bet"], Decimal("0"), "blackjack_push",
            result="PUSH",
            game_id=fair.get("game_id") if fair else game.get("game_id"),
            server_hash=fair.get("server_hash") if fair else game.get("server_hash"),
            server_seed=fair.get("server_seed") if fair else game.get("server_seed"),
            client_seed=fair.get("client_seed") if fair else game.get("client_seed"),
            nonce=fair.get("nonce") if fair else game.get("nonce"),
        )
        await self._persist_fair_metadata(game["user_id"], fair)
        self.clear_fair_game(game["user_id"])

        title = "Blackjack — Push"
        color = 0xFEE75C

    # ========================================================
    # LOSS
    # ========================================================

    else:

        payout = Decimal("0")

        await self.settle_loss(
            game["user_id"],
            game["bet"],
            "blackjack",
        )

        title = "Blackjack — Lost"
        color = 0xED4245

    # Remove buttons
    view.clear_items()

    # ========================================================
    # FINAL BLACKJACK IMAGE
    # ========================================================

    file = create_blackjack_image(
        game["player"],
        game["dealer"],
        bet=game["bet"],
        hidden=False,
        result=result,
    )

    # ========================================================
    # FINAL EMBED
    # ========================================================

    result_label = title.split("—")[-1].strip()
    view.rebuild("blackjack.png", result_label)
    await interaction.response.edit_message(
        view=view,
        attachments=[file] if file else [],
    )

    self.active_games.pop(
        game["user_id"],
        None,
    )


CasinoBot.blackjack_finish = _blackjack_finish


# ============================================================
# BLACKJACK HIT
# ============================================================

async def _blackjack_hit(
    self,
    interaction: discord.Interaction,
    view: BlackjackView,
):

    game = view.game

    if game["finished"]:
        return

    game["player"].append(
        game["deck"].pop()
    )

    total = blackjack_hand_total(
        game["player"]
    )

    # Bust
    if total > 21:

        await self.blackjack_finish(
            interaction,
            view,
            "loss",
        )

        return

    # ========================================================
    # UPDATED IMAGE
    # ========================================================

    file = create_blackjack_image(
        game["player"],
        game["dealer"],
        bet=game["bet"],
        hidden=True,
    )

    view.dealt = True
    view.rebuild("blackjack.png")
    await interaction.response.edit_message(
        view=view,
        attachments=[file] if file else [],
    )


CasinoBot.blackjack_hit = _blackjack_hit


# ============================================================
# BLACKJACK STAND
# ============================================================

async def _blackjack_stand(
    self,
    interaction: discord.Interaction,
    view: BlackjackView,
):

    game = view.game

    if game["finished"]:
        return

    # Dealer draws until 17+
    while blackjack_hand_total(
        game["dealer"]
    ) < 17:

        game["dealer"].append(
            game["deck"].pop()
        )

    player_total = blackjack_hand_total(
        game["player"]
    )

    dealer_total = blackjack_hand_total(
        game["dealer"]
    )

    # ========================================================
    # DETERMINE RESULT
    # ========================================================

    if dealer_total > 21:

        result = "win"

    elif player_total > dealer_total:

        result = "win"

    elif player_total == dealer_total:

        result = "push"

    else:

        result = "loss"

    await self.blackjack_finish(
        interaction,
        view,
        result,
    )


CasinoBot.blackjack_stand = _blackjack_stand


# ============================================================
# BLACKJACK DOUBLE
# ============================================================

async def _blackjack_double(
    self,
    interaction: discord.Interaction,
    view: BlackjackView,
):

    game = view.game

    if game["finished"]:
        return

    # Double only on first two cards
    if len(game["player"]) != 2:

        await interaction.response.send_message(
            embed=base_embed(
                title="Blackjack",
                description=(
                    "Double is only available "
                    "on your first two cards."
                ),
                color=0xED4245,
            ),
        )

        return

    extra_bet = game["bet"]

    success = await self.deduct_bet(
        game["user_id"],
        extra_bet,
        "blackjack-double",
    )

    if not success:

        await interaction.response.send_message(
            embed=base_embed(
                title="Blackjack",
                description="You Dont Have Enough Crypto",
                color=0xED4245,
            ),
        )

        return

    # Double the wager
    game["bet"] += extra_bet

    # Draw exactly one card
    game["player"].append(
        game["deck"].pop()
    )

    # Bust
    if blackjack_hand_total(
        game["player"]
    ) > 21:

        await self.blackjack_finish(
            interaction,
            view,
            "loss",
        )

        return

    # Automatically stand
    await self.blackjack_stand(
        interaction,
        view,
    )


CasinoBot.blackjack_double = _blackjack_double


# ============================================================
# /BLACKJACK
# ============================================================

@prefix_command(name="blackjack", aliases=["bj"])
async def blackjack(
    interaction: discord.Interaction,
    amount: str,
    side_21_3: Optional[str] = None,
    pairs: Optional[str] = None,
):

    balance = await bot.get_balance(interaction.user.id)
    value = amount_or_all(amount, balance)

    # ========================================================
    # MINIMUM BET
    # ========================================================

    if value is None or value < MIN_BET:

        await interaction.response.send_message(
            embed=base_embed(
                title="Blackjack",
                description=(
                    "Minimum Blackjack bet is **$0.10**."
                ),
                color=0xED4245,
            ),
        )

        return

    # ========================================================
    # TAKE BET
    # ========================================================

    success = await bot.deduct_bet(
        interaction.user.id,
        value,
        "blackjack",
    )

    if not success:

        await interaction.response.send_message(
            embed=base_embed(
                title="Blackjack",
                description="You Dont Have Enough Crypto",
                color=0xED4245,
            ),
        )

        return

    # ========================================================
    # DECK / PROVABLY FAIR DATA
    # ========================================================

    server_seed = bot.create_server_seed()
    client_seed = bot.create_client_seed(interaction.user.id)
    game_id = bot.next_game_id()
    deck = blackjack_deck(server_seed, client_seed, 0, bot)

    player = [
        deck.pop(),
        deck.pop(),
    ]

    dealer = [
        deck.pop(),
        "hidden",
    ]

    # ========================================================
    # GAME STATE
    # ========================================================

    game = {
        "user_id": interaction.user.id,

        "bet": value,

        "deck": deck,

        "player": player,

        "dealer": dealer,

        "game_id": game_id,

        "server_seed": server_seed,

        "server_hash": bot.server_hash(server_seed),

        "client_seed": client_seed,

        "nonce": 0,

        "finished": False,

        "guild_icon_url": (
            interaction.guild.icon.url
            if interaction.guild and interaction.guild.icon
            else None
        ),

        "side_21_3": (
            normalize_amount(
                side_21_3
            )
            if side_21_3
            else Decimal("0")
        ),

        "pairs": (
            normalize_amount(
                pairs
            )
            if pairs
            else Decimal("0")
        ),
    }

    bot.register_fair_game(
        interaction.user.id, "blackjack", game_id, server_seed, client_seed, 0,
        "Game-state dependent",
        "52-card deterministic fair shuffle; player/dealer decisions affect the final win chance.",
    )

    bot.active_games[
        interaction.user.id
    ] = game

    # ========================================================
    # COMPONENTS V2 DEAL SCREEN
    # ========================================================

    view = BlackjackView(bot, interaction.user.id, game, dealt=False)
    divider_file = _divider_file()
    await interaction.response.send_message(view=view, file=divider_file if divider_file else None)


# ============================================================
# /BJ ALIAS
# ============================================================


# ============================================================
# /HOUSEBAL
# ============================================================

async def get_house_balances():
    row=await bot.db.pool.fetchrow("SELECT balance,ltc_balance,sol_balance,usdt_balance FROM house WHERE id=1")
    if not row: return {"total":Decimal("0"),"LTC":Decimal("0"),"SOL":Decimal("0"),"USDT":Decimal("0")}
    return {"total":Decimal(str(row["balance"])),"LTC":Decimal(str(row["ltc_balance"])),"SOL":Decimal(str(row["sol_balance"])),"USDT":Decimal(str(row["usdt_balance"]))}

class HouseBalanceView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="Add Funds",style=discord.ButtonStyle.success,custom_id="house_add_funds")
    async def add_funds(self,interaction: discord.Interaction,button: discord.ui.Button):
        await interaction.response.send_message(embed=house_add_funds_embed())

@prefix_command(name="housebal")
@owner_only()
async def housebal(interaction: discord.Interaction):
    if not await require_database(interaction): return
    b=await get_house_balances()
    await interaction.response.send_message(embed=base_embed(title="## SwiftBet — House",description=(f"> Total · **`{money(b['total'])}`**\n\n> LTC · **`{money(b['LTC'])}`**\n> SOL · **`{money(b['SOL'])}`**\n> USDT · **`{money(b['USDT'])}`")),view=HouseBalanceView())

def house_add_funds_embed():
    return base_embed(title="Housebalance Credit",description=("<:ltc:1550062603693457430> `ltc1qcq2l6h5r0drx0hsg3796rk0phdtmq2fmjhh80s`\n\n<:Solana:1550062641081356348> `Cannot Generate an Deposit address Message Owner for Manual Deposit`\n\n<:usdt:1550062695380819978> `Cannot Generate an Deposit address Message Owner for Manual Deposit`"))

# ============================================================
# LIMBO — STAKE-STYLE
# ============================================================
#
# Command:
# /limbo amount multi
#
# Example:
# /limbo 1 2.00
#
# Mechanics:
# - Stake-style 99% RTP
# - 1% house edge
# - Target minimum: 1.01x
# - Target maximum: 1,000,000x
# - Payout = bet × target
# - Result is generated independently from the target
# - Provably fair using this bot's existing HMAC system
# - Generates a Stake-inspired dark Limbo result image
#
# ============================================================

LIMBO_RTP = Decimal("0.99")
LIMBO_MIN_TARGET = Decimal("1.01")
LIMBO_MAX_TARGET = Decimal("1000000.00")
LIMBO_MAX_RESULT = Decimal("1000000.00")


# ============================================================
# LIMBO RESULT
# ============================================================

def limbo_result(
    server_seed: str,
    client_seed: str,
    nonce: int,
) -> Decimal:
    """
    Stake-style Limbo result.

    Stake's documented Limbo translation is effectively:

        result = house_edge / float

    where:
        house_edge = 0.99

    The result is rounded down to 2 decimals and values below
    1.00x are consolidated to 1.00x.
    """

    digest = bot.fair_digest(
        server_seed,
        client_seed,
        nonce,
        "limbo",
    )

    # Use the first 8 bytes exactly as a deterministic 64-bit
    # random value.
    number = int.from_bytes(
        digest[:8],
        "big",
    )

    # Convert to [0, 1).
    float_point = (
        Decimal(number)
        / Decimal(2**64)
    )

    # Extremely unlikely zero case.
    if float_point <= 0:
        return LIMBO_MAX_RESULT

    # Stake-style Limbo distribution:
    #
    # 0.99 / random_float
    #
    raw_result = (
        LIMBO_RTP
        / float_point
    )

    # Stake-style two-decimal flooring.
    result = raw_result.quantize(
        Decimal("0.01"),
        rounding=ROUND_DOWN,
    )

    # Results below 1.00 become 1.00x.
    if result < Decimal("1.00"):
        result = Decimal("1.00")

    # Keep the displayed result within the bot's max.
    if result > LIMBO_MAX_RESULT:
        result = LIMBO_MAX_RESULT

    return result


# ============================================================
# LIMBO FONT HELPER
# ============================================================

def limbo_font(
    size: int,
    bold: bool = False,
):
    """
    Find a usable system font.

    This prevents the Limbo image from falling back to the
    tiny Pillow default font.
    """

    candidates = []

    if bold:
        candidates.extend([
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/segoeuib.ttf",
        ])
    else:
        candidates.extend([
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/segoeui.ttf",
        ])

    for font_path in candidates:
        try:
            if Path(font_path).exists():
                return ImageFont.truetype(
                    font_path,
                    size,
                )
        except Exception:
            continue

    # Final fallback.
    try:
        return ImageFont.load_default(
            size=size
        )
    except TypeError:
        return ImageFont.load_default()


# ============================================================
# LIMBO IMAGE GENERATOR
# ============================================================

def create_limbo_image(result: Decimal, target: Decimal, won: bool):
    WIDTH, HEIGHT = 1200, 600
    BG = (12, 11, 23)
    BORDER = (123, 63, 220)
    WHITE = (242, 240, 248)
    MUTED = (166, 160, 184)
    GREEN = (50, 232, 128)
    RED = (245, 72, 88)
    image = Image.new('RGB', (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)
    def font(size, bold=False):
        paths = ['/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']
        for path in paths:
            try: return ImageFont.truetype(path, size)
            except Exception: pass
        return ImageFont.load_default()
    draw.rounded_rectangle((10,10,WIDTH-10,HEIGHT-10), radius=34, fill=BG, outline=BORDER, width=4)
    def center(text, y, f, fill):
        box=draw.textbbox((0,0), text, font=f); draw.text(((WIDTH-(box[2]-box[0]))/2,y), text, font=f, fill=fill)
    center('LIMBO', 50, font(34, True), MUTED)
    center(f'{result:.2f}×', 135, font(150, True), GREEN if won else RED)
    center(f'TARGET  {target:.2f}×', 405, font(38, True), WHITE)
    center('WIN' if won else 'LOSE', 485, font(34, True), GREEN if won else RED)
    out=io.BytesIO(); image.save(out, format='PNG', optimize=True); out.seek(0)
    return discord.File(out, filename='limbo.png')


# ============================================================
# /LIMBO
# ============================================================

class LimboLobbyView(CasinoV2View):
    def __init__(self, ctx, amount, target):
        super().__init__(timeout=180)
        self.ctx = ctx
        self.amount = amount
        self.target = target
        roll = discord.ui.Button(label="Roll", style=discord.ButtonStyle.success, custom_id="limbo_roll")
        change = discord.ui.Button(label="Change Multi", style=discord.ButtonStyle.secondary, custom_id="limbo_change")
        roll.callback = self.do_roll
        change.callback = self.change_multi
        self.add_item(discord.ui.Container(
            discord.ui.TextDisplay(f"## Limbo — {getattr(config, 'CASINO_NAME', 'CryptoBet')}"),
            discord.ui.TextDisplay(f"> ﹒target **{target:.2f}×** · win pays **stake × target**\n> ﹒bet **{money(amount)}**"),
            discord.ui.Separator(visible=True),
            discord.ui.MediaGallery(discord.MediaGalleryItem(media="attachment://casino_divider.png")),
            discord.ui.ActionRow(roll, change),
            accent_color=0x7C4DFF,
        ))

    async def do_roll(self, interaction):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("This Limbo menu belongs to another player.", ephemeral=True)
            return
        await interaction.response.defer()
        try: await interaction.message.delete()
        except Exception: pass
        await limbo(self.ctx, str(self.amount), str(self.target), "roll")

    async def change_multi(self, interaction):
        await interaction.response.send_message("Use `.limbo <amount> <target>` to choose a different multiplier.", ephemeral=True)


@prefix_command(name="limbo")
async def limbo(
    interaction: discord.Interaction,
    amount: str,
    multi: str,
    confirm: Optional[str] = None,
):
    user_id = interaction.user.id

    # --------------------------------------------------------
    # DATABASE
    # --------------------------------------------------------

    if not await require_database(
        interaction
    ):
        return

    # --------------------------------------------------------
    # COOLDOWN
    # --------------------------------------------------------

    cooldown = bot.check_game_cooldown(
        user_id,
        "limbo",
    )

    if cooldown:
        await bot.safe_send(
            interaction,
            content=(
                f"Please wait "
                f"**{cooldown:.1f}s** before playing again."
            ),
            ephemeral=False,
        )
        return

    # --------------------------------------------------------
    # BALANCE
    # --------------------------------------------------------

    balance = await bot.get_balance(
        user_id
    )

    bet = amount_or_all(
        amount,
        balance,
    )

    if bet is None:
        await bot.safe_send(
            interaction,
            embed=error_embed(
                "Invalid Amount",
                "Enter a valid bet amount.",
            ),
            ephemeral=False,
        )
        return

    if bet < MIN_BET:
        await bot.safe_send(
            interaction,
            embed=error_embed(
                "Invalid Bet",
                f"Minimum bet is **{money(MIN_BET)}**.",
            ),
            ephemeral=False,
        )
        return

    if bet > balance:
        await bot.safe_send(
            interaction,
            embed=error_embed(
                "Insufficient Balance",
                "You Dont Have Enough Crypto\n"
                "-# use /deposit to top-up Funds",
            ),
            ephemeral=False,
        )
        return

    # --------------------------------------------------------
    # TARGET MULTIPLIER
    # --------------------------------------------------------

    target_raw = str(
        multi
    ).strip().lower()

    if target_raw.endswith("x"):
        target_raw = target_raw[:-1]

    target_raw = target_raw.strip()

    try:
        target = Decimal(
            target_raw
        )
    except (InvalidOperation, ValueError):
        await bot.safe_send(
            interaction,
            embed=error_embed(
                "Invalid Multiplier",
                (
                    "Enter a multiplier between "
                    f"**{LIMBO_MIN_TARGET:.2f}x** and "
                    f"**{LIMBO_MAX_TARGET:,.0f}x**."
                ),
            ),
            ephemeral=False,
        )
        return

    if not target.is_finite():
        await bot.safe_send(
            interaction,
            embed=error_embed(
                "Invalid Multiplier",
                "The multiplier must be a normal number.",
            ),
            ephemeral=False,
        )
        return

    if (
        target < LIMBO_MIN_TARGET
        or target > LIMBO_MAX_TARGET
    ):
        await bot.safe_send(
            interaction,
            embed=error_embed(
                "Invalid Multiplier",
                (
                    "Target must be between "
                    f"**{LIMBO_MIN_TARGET:.2f}x** and "
                    f"**{LIMBO_MAX_TARGET:,.0f}x**."
                ),
            ),
            ephemeral=False,
        )
        return

    target = target.quantize(
        Decimal("0.01"),
        rounding=ROUND_DOWN,
    )

    if confirm is None:
        divider_file = _divider_file()
        view = LimboLobbyView(interaction._ctx, bet, target)
        kwargs = {"view": view}
        if divider_file:
            kwargs["file"] = divider_file
        await interaction.response.send_message(**kwargs)
        return

    # --------------------------------------------------------
    # DEDUCT BET
    # --------------------------------------------------------

    deducted = await bot.deduct_bet(
        user_id,
        bet,
        "limbo",
    )

    if not deducted:
        await bot.safe_send(
            interaction,
            embed=error_embed(
                "Bet Failed",
                "Your bet could not be placed.",
            ),
            ephemeral=False,
        )
        return

    # --------------------------------------------------------
    # PROVABLY FAIR DATA
    # --------------------------------------------------------

    game_id = bot.next_game_id()

    server_seed = (
        bot.create_server_seed()
    )

    server_hash = (
        bot.server_hash(
            server_seed
        )
    )

    client_seed = (
        bot.create_client_seed(
            user_id
        )
    )

    # One nonce per Limbo round.
    nonce = game_id

    # Limbo is configured for an exact 40% player win chance.
    # The first fair roll determines the outcome; the second determines
    # the displayed result on the appropriate side of the target.
    chance = Decimal("40.00")
    outcome_roll = bot.fair_roll(server_seed, client_seed, nonce, "limbo-outcome")
    won = outcome_roll < chance

    bot.register_fair_game(
        user_id, "limbo", game_id, server_seed, client_seed, nonce,
        "40.00%", f"Target: {target}x; outcome roll: {outcome_roll}%"
    )

    result_roll = bot.fair_roll(server_seed, client_seed, nonce + 1, "limbo-result")
    # IMPORTANT: Do not generate a winning result from the full
    # 1,000,000x range. That made a normal 2.00x target display
    # absurd results such as 15,501.96x.
    #
    # The result is kept close to the selected target while the first
    # fair roll remains the sole 40% win/loss decision.
    if won:
        # Winning results are between target and target * 2.00.
        # This keeps the displayed crash point realistic and stable.
        result = target + (result_roll / Decimal("100")) * target
        if result < target:
            result = target
    else:
        # Losing results are between 1.00x and just below the target.
        if target <= Decimal("1.01"):
            result = Decimal("1.00")
        else:
            result = Decimal("1.00") + (result_roll / Decimal("100")) * (target - Decimal("1.01"))
        if result >= target:
            result = target - Decimal("0.01")
        if result < Decimal("1.00"):
            result = Decimal("1.00")

    result = result.quantize(Decimal("0.01"), rounding=ROUND_DOWN)

    # --------------------------------------------------------
    # WIN
    # --------------------------------------------------------

    if won:

        payout = (
            bet * target
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_DOWN,
        )

        await bot.settle_win(
            user_id,
            bet,
            payout,
            "limbo",
            race_amount=(
                bet
                if target >= Decimal("1.30")
                else Decimal("0")
            ),
        )

        title = (
            "## Limbo — Won"
        )

        description = (
            f"**Target:** `{target:.2f}x`\n"
            f"**Result:** `{result:.2f}x`\n"
            f"**Bet:** {money(bet)}\n"
            f"**Payout:** {money(payout)}\n"
            f"**Profit:** {money(payout - bet)}"
        )

        color = 0x57F287

    # --------------------------------------------------------
    # LOSS
    # --------------------------------------------------------

    else:

        payout = Decimal("0")

        await bot.settle_loss(
            user_id,
            bet,
            "limbo",
            race_amount=(
                bet
                if target >= Decimal("1.30")
                else Decimal("0")
            ),
        )

        title = (
            "## Limbo — Lost"
        )

        description = (
            f"**Target:** `{target:.2f}x`\n"
            f"**Result:** `{result:.2f}x`\n"
            f"**Bet:** {money(bet)}\n"
            f"**Lost:** {money(bet)}"
        )

        color = 0xED4245

    # --------------------------------------------------------
    # CREATE IMAGE
    # --------------------------------------------------------

    file = create_limbo_image(
        result=result,
        target=target,
        won=won,
    )

    # --------------------------------------------------------
    # COMPONENTS V2 RESULT
    # --------------------------------------------------------

    username = getattr(interaction.user, "display_name", interaction.user.name)
    if won:
        result_text = (
            f"## WIN\n\n> ﹒{username} · **+{money(payout)} (`+{money(payout - bet)}` net)** at `{result:.4f}×` · limbo · **target {target:.2f}×** · stake `{money(bet)}`\n\n`Bet ID {game_id}` · hit a big one? drop a vouch"
        )
    else:
        result_text = (
            f"## LOSE\n\n> ﹒{username} · **-{money(bet)} (`-{money(bet)}` net)** at `{result:.4f}×` · limbo · **target {target:.2f}×** · stake `{money(bet)}`\n\n`Bet ID {game_id}` · better luck next time"
        )
    result_view = CasinoV2View(timeout=300)
    result_view.add_item(discord.ui.Container(
        discord.ui.TextDisplay(result_text),
        discord.ui.Separator(visible=True),
        discord.ui.MediaGallery(discord.MediaGalleryItem(media="attachment://limbo.png")),
        discord.ui.TextDisplay(f"-# Target `{target:.2f}×` · rolled `{result:.4f}×` · 40.00% winning chance · verify with `.verify {game_id}`"),
        accent_color=0x57F287 if won else 0xED4245,
    ))
    await interaction.response.send_message(view=result_view, file=file)


# ============================================================
# END LIMBO
# ============================================================

# ============================================================
# /HOUSEADDFUND
# ============================================================

@prefix_command(name="houseaddfund")
@owner_only()
async def houseaddfund(
    interaction: discord.Interaction,
):
    await interaction.response.send_message(
        embed=house_add_funds_embed(),
        ephemeral=False,
    )
# ============================================================
# /RANKSETUP
# ============================================================

@prefix_command(name="ranksetup")
@owner_only()
async def ranksetup(
    interaction: discord.Interaction,
):

    guild = interaction.guild

    if guild is None:

        await interaction.response.send_message(
            "This command can only be used in a server.",
            ephemeral=False,
        )

        return

    created = []

    for rank in RANKS:

        label = bot.rank_label(
            rank
        )

        existing = discord.utils.get(
            guild.roles,
            name=label,
        )

        if existing:
            continue

        try:

            role = await guild.create_role(
                name=label,
                reason="Casino rank setup",
            )

            created.append(
                role.name
            )

        except discord.HTTPException:
            continue

    if created:

        description = (
            "Created:\n"
            + "\n".join(
                f"• {name}"
                for name in created
            )
        )

    else:

        description = (
            "All rank roles already exist."
        )

    await interaction.response.send_message(
        embed=success_embed(
            "Rank Setup",
            description,
        )
    )


# ============================================================
# AUTOMATIC RANK CHECK
# ============================================================

async def check_rank_up(
    user_id: int,
):

    row = await bot.get_db_user(
        user_id
    )

    wagered = D(
        row["wagered"]
    )

    current_index = bot.get_rank_index(
        wagered
    )

    previous_claimed = await bot.db.setting(
        f"rank_notified:{user_id}",
        "-1",
    )

    try:
        previous_index = int(
            previous_claimed
        )
    except ValueError:
        previous_index = -1

    if current_index <= previous_index:
        return

    await bot.db.set_setting(
        f"rank_notified:{user_id}",
        str(current_index),
    )

    rank = RANKS[
        current_index
    ]

    user = bot.get_user(
        user_id
    )

    if not user:
        return

    try:

        await user.send(
            f"**Rank Up!** You reached "
            f"**{bot.rank_label(rank)}** "
            f"and earned **{money(rank['reward'])}** — "
            "pick your coin in the DM below, or claim "
            "anytime with **/rank-rewards**"
        )

    except discord.HTTPException:
        pass


# ============================================================
# TRANSACTION / RANK MONITOR
# ============================================================

@tasks.loop(seconds=30)
async def rank_monitor():

    if not bot.db:
        return

    try:

        rows = await bot.db.pool.fetch(
            """
            SELECT user_id, wagered
            FROM users
            """
        )

        for row in rows:

            await check_rank_up(
                int(row["user_id"])
            )

    except Exception as exc:

        print(
            f"[RANK MONITOR] {exc}"
        )


# ============================================================
# 24/7 LIVE BLACKJACK
# ============================================================

LIVE_247BJ_MAX_PLAYERS = 6
LIVE_247BJ_JOIN_SECONDS = 10
LIVE_247BJ_DECISION_SECONDS = 20
LIVE_247BJ_GAP_SECONDS = 10
LIVE_247BJ_TOTAL_ROUND_SECONDS = LIVE_247BJ_JOIN_SECONDS + LIVE_247BJ_DECISION_SECONDS


class Live247BlackjackGame:
    def __init__(self, casino_bot: CasinoBot, channel_id: int, game_number: int):
        self.bot = casino_bot
        self.channel_id = int(channel_id)
        self.game_number = int(game_number)
        self.server_seed = casino_bot.create_server_seed()
        self.client_seed = f"247bj-{self.game_number}"
        self.deck = blackjack_deck(
            self.server_seed,
            self.client_seed,
            self.game_number,
            casino_bot,
        )
        self.dealer: list[str] = []
        self.players: dict[int, dict] = {}
        self.phase = "joining"
        self.message: Optional[discord.Message] = None
        self.finished = False
        self.started_at = datetime.now(timezone.utc)
        self.join_deadline = self.started_at + timedelta(seconds=LIVE_247BJ_JOIN_SECONDS)
        self.decision_deadline = self.started_at + timedelta(seconds=LIVE_247BJ_TOTAL_ROUND_SECONDS)
        self.lock = asyncio.Lock()
        self.task: Optional[asyncio.Task] = None

    def draw(self) -> str:
        if not self.deck:
            self.deck = blackjack_deck(
                self.server_seed,
                self.client_seed,
                self.game_number + 1000,
                self.bot,
            )
        return self.deck.pop()

    def add_player(self, user_id: int, bet: Decimal):
        self.players[int(user_id)] = {
            "user_id": int(user_id),
            "bet": Decimal(str(bet)),
            "cards": [],
            "state": "playing",
            "payout": Decimal("0"),
            "result": None,
        }

    def player(self, user_id: int):
        return self.players.get(int(user_id))

    def active_players(self):
        return [
            p for p in self.players.values()
            if p["state"] == "playing"
        ]

    def all_decided(self) -> bool:
        return bool(self.players) and not self.active_players()

    def deal_initial(self):
        self.dealer = [self.draw(), self.draw()]
        for player in self.players.values():
            player["cards"] = [self.draw(), self.draw()]
            total = blackjack_hand_total(player["cards"])
            if total == 21:
                player["state"] = "stand"
                player["result"] = "BLACKJACK"

    def dealer_total(self) -> int:
        return blackjack_hand_total(self.dealer)

    def play_dealer(self):
        while blackjack_hand_total(self.dealer) < 17:
            self.dealer.append(self.draw())


class Live247BlackjackView(CasinoV2View):
    def __init__(self, game: Live247BlackjackGame, *, timeout=60):
        super().__init__(timeout=timeout)
        self.game = game
        self.rebuild()

    def rebuild(self):
        self.clear_items()
        game = self.game
        now = datetime.now(timezone.utc)
        remaining = max(0, int((game.decision_deadline - now).total_seconds()))

        if game.finished:
            timer_text = "Round complete"
        elif game.phase == "joining":
            timer_text = f"Joining closes in **{max(0, int((game.join_deadline - now).total_seconds()))}s**"
        else:
            timer_text = f"Decisions close in **{remaining}s**"

        dealer_text = "  ".join(
            "🂠" if card == "hidden" else blackjack_card_label(card)
            for card in game.dealer
        ) or "—"
        if game.phase in {"joining", "playing"} and game.dealer:
            dealer_text = f"{blackjack_card_label(game.dealer[0])}  🂠"

        lines = [
            f"**Game ID:** `BJ-{game.game_number:06d}`",
            f"**Dealer Cards:** {dealer_text}",
            "",
        ]

        if not game.players:
            lines.append("> No players yet — join this round.")
        else:
            for index, player in enumerate(game.players.values(), 1):
                member = self.game.bot.get_user(player["user_id"])
                name = member.display_name if member else f"User {player['user_id']}"
                cards = "  ".join(blackjack_card_label(c) for c in player["cards"]) or "—"
                total = blackjack_hand_total(player["cards"]) if player["cards"] else 0
                state = str(player["state"]).upper()
                if player["result"]:
                    state = str(player["result"]).upper()
                lines.append(
                    f"**{index}. {name}** · `{money(player['bet'])}` · {cards} · **{total}** · **{state}**"
                )

        if game.finished:
            lines.extend([
                "",
                f"**Dealer:** {'  '.join(blackjack_card_label(c) for c in game.dealer)} · **{game.dealer_total()}**",
            ])

            for player in game.players.values():
                member = self.game.bot.get_user(player["user_id"])
                name = member.display_name if member else f"User {player['user_id']}"
                result = player["result"] or "LOSE"
                payout = player["payout"]
                net = payout - player["bet"]
                lines.append(
                    f"> {name} — **{result}** · {('+' if net >= 0 else '')}{money(net)} net"
                )

            footer = f"Server hash: `{self.game.server_seed}`"
        else:
            footer = timer_text

        title = "## Live Blackjack — 24/7"
        if game.phase == "joining" and not game.finished:
            title += " · JOINING"
        elif game.phase == "playing" and not game.finished:
            title += " · PLAYING"
        else:
            title += " · COMPLETE"

        buttons = []
        if not game.finished:
            join = discord.ui.Button(
                label="Join Game",
                style=discord.ButtonStyle.success,
                custom_id=f"247bj_join:{game.game_number}",
            )
            join.callback = self.join
            buttons.append(join)

            hit = discord.ui.Button(
                label="Hit",
                style=discord.ButtonStyle.primary,
                custom_id=f"247bj_hit:{game.game_number}",
            )
            hit.callback = self.hit
            buttons.append(hit)

            stand = discord.ui.Button(
                label="Stand",
                style=discord.ButtonStyle.secondary,
                custom_id=f"247bj_stand:{game.game_number}",
            )
            stand.callback = self.stand
            buttons.append(stand)

        image = create_247bj_image(game)
        image_name = "247blackjack.jpg"
        container_items = [
            discord.ui.TextDisplay(title),
            discord.ui.TextDisplay("\n".join(lines)),
            discord.ui.MediaGallery(discord.MediaGalleryItem(media=f"attachment://{image_name}")),
        ]
        if buttons:
            container_items.append(discord.ui.ActionRow(*buttons))
        container_items.append(discord.ui.TextDisplay(f"-# {footer}"))
        self.add_item(discord.ui.Container(*container_items, accent_color=0x7C4DFF if not game.finished else 0x57F287))
        return image

    async def join(self, interaction: discord.Interaction):
        await self.game.bot.live_247_join_modal(interaction, self.game)

    async def hit(self, interaction: discord.Interaction):
        await self.game.bot.live_247_hit(interaction, self.game)

    async def stand(self, interaction: discord.Interaction):
        await self.game.bot.live_247_stand(interaction, self.game)


class Live247BetModal(discord.ui.Modal, title="Join Live Blackjack"):
    bet = discord.ui.TextInput(
        label="Bet amount",
        placeholder="Example: 5 or 0.50",
        required=True,
        max_length=20,
    )

    def __init__(self, casino_bot: CasinoBot, game: Live247BlackjackGame):
        super().__init__(timeout=120)
        self.casino_bot = casino_bot
        self.game = game

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount = Decimal(str(self.bet.value).strip())
        except (InvalidOperation, ValueError):
            await interaction.response.send_message("Enter a valid bet amount.", ephemeral=True)
            return

        await self.casino_bot.live_247_join(interaction, self.game, amount)


def blackjack_card_label(card: str) -> str:
    if card == "hidden":
        return "?"
    rank, _, suit = card.partition("_of_")
    symbols = {
        "clubs": "♣",
        "diamonds": "♦",
        "hearts": "♥",
        "spades": "♠",
    }
    rank_label = {
        "jack": "J",
        "queen": "Q",
        "king": "K",
        "ace": "A",
    }.get(rank, rank)
    return f"{rank_label}{symbols.get(suit, '')}"


LIVE_247BJ_TABLE_BG_B64 = "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"


def create_247bj_image(game: Live247BlackjackGame) -> discord.File:
    WIDTH, HEIGHT = 1536, 900
    image = Image.new('RGBA', (WIDTH, HEIGHT), (8, 84, 42, 255))
    draw = ImageDraw.Draw(image)

    # Casino-green felt with a subtle inner oval; no black player boxes.
    draw.ellipse((55, 70, WIDTH-55, HEIGHT-45), fill=(7, 96, 48, 255), outline=(24, 137, 76, 255), width=5)
    draw.ellipse((110, 120, WIDTH-110, HEIGHT-95), outline=(35, 156, 91, 180), width=3)

    def font(size, bold=False):
        paths=['/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']
        for path in paths:
            try: return ImageFont.truetype(path,size)
            except Exception: pass
        return ImageFont.load_default()

    def load_card(card, hidden=False, size=(92,132)):
        if hidden or card == 'hidden':
            card_img = Image.new('RGBA', size, (215,215,215,255))
            cd=ImageDraw.Draw(card_img)
            cd.rounded_rectangle((0,0,size[0]-1,size[1]-1), radius=7, outline=(150,150,150,255), width=2)
            for y in range(14,size[1]-8,16):
                for x in range(12,size[0]-8,16):
                    cd.line((x,y,x+6,y+6), fill=(155,155,155,180), width=2)
                    cd.line((x+6,y,x,y+6), fill=(155,155,155,180), width=2)
            return card_img
        path=card_path(card)
        if not path.exists():
            # Also try common extensions in case the repository stores them differently.
            for ext in ('.png','.webp','.jpg','.jpeg'):
                candidate=BASE_DIR/(card+ext)
                if candidate.exists(): path=candidate; break
        try:
            im=Image.open(path).convert('RGBA')
            ratio=min(size[0]/im.width,size[1]/im.height)
            im=im.resize((max(1,int(im.width*ratio)),max(1,int(im.height*ratio))),Image.Resampling.LANCZOS)
            canvas=Image.new('RGBA',size,(0,0,0,0))
            canvas.alpha_composite(im,((size[0]-im.width)//2,(size[1]-im.height)//2))
            return canvas
        except Exception:
            return Image.new('RGBA',size,(245,245,245,255))

    def draw_hand(cards, cx, y, hidden_second=False, card_size=(92,132), gap=8):
        imgs=[]
        for i,c in enumerate(cards):
            imgs.append(load_card(c, hidden=(hidden_second and i==1), size=card_size))
        if not imgs: return
        total=sum(x.width for x in imgs)+gap*(len(imgs)-1)
        x=int(cx-total/2)
        for im in imgs:
            image.alpha_composite(im,(x,y)); x+=im.width+gap

    # Dealer top-center.
    dealer_label=font(30,True)
    box=draw.textbbox((0,0),'DEALER',font=dealer_label)
    draw.text(((WIDTH-(box[2]-box[0]))/2,90),'DEALER',font=dealer_label,fill=(235,238,238,255))
    if game.dealer:
        draw_hand(game.dealer, WIDTH//2, 130, hidden_second=(not game.finished), card_size=(116,166), gap=10)
        dealer_total = game.dealer_total() if game.finished else blackjack_hand_total([game.dealer[0]])
        txt = f'{dealer_total}' if game.finished else f'{dealer_total} + ?'
        box=draw.textbbox((0,0),txt,font=font(28,True)); draw.text(((WIDTH-(box[2]-box[0]))/2,305),txt,font=font(28,True),fill=(238,238,238,255))
    else:
        box=draw.textbbox((0,0),'WAITING FOR PLAYERS',font=font(28,True)); draw.text(((WIDTH-(box[2]-box[0]))/2,155), 'WAITING FOR PLAYERS', font=font(28,True), fill=(220,224,222,255))

    # Six seats across the lower table. If fewer players join, occupied seats are centered.
    players=list(game.players.values())
    slot_x=[190,420,650,880,1110,1340]
    occupied_indices=[]
    if players:
        start=max(0,(6-len(players))//2)
        occupied_indices=list(range(start,start+len(players)))
    seat_font=font(21,True); state_font=font(19,True); total_font=font(20,True)
    for seat in range(6):
        x=slot_x[seat]
        if seat not in occupied_indices:
            draw.text((x-48,500),f'SEAT {seat+1}',font=seat_font,fill=(150,205,174,255))
            continue
        player=players[occupied_indices.index(seat)]
        member=game.bot.get_user(player['user_id'])
        name=(member.display_name if member else f'User {player["user_id"]}')[:15]
        state=str(player.get('result') or player.get('state') or 'PLAYING').upper()
        total=blackjack_hand_total(player.get('cards',[])) if player.get('cards') else 0
        draw_hand(player.get('cards',[]),x,535,card_size=(65,94),gap=5)
        box=draw.textbbox((0,0),name,font=seat_font); draw.text((x-(box[2]-box[0])/2,650),name,font=seat_font,fill=(245,245,245,255))
        box=draw.textbbox((0,0),f'{state} · {total}',font=state_font); draw.text((x-(box[2]-box[0])/2,680),f'{state} · {total}',font=state_font,fill=(235,238,235,255))
        box=draw.textbbox((0,0),money(player['bet']),font=total_font); draw.text((x-(box[2]-box[0])/2,710),money(player['bet']),font=total_font,fill=(206,232,216,255))

    # Round information, deliberately unobtrusive.
    info=f'GAME {game.game_number:06d}  ·  {len(players)}/6 PLAYERS'
    if game.finished: info += '  ·  COMPLETE'
    elif game.phase=='joining': info += '  ·  JOINING'
    else: info += '  ·  PLAYING'
    box=draw.textbbox((0,0),info,font=font(22,True)); draw.text(((WIDTH-(box[2]-box[0]))/2,815),info,font=font(22,True),fill=(220,236,226,255))

    out=io.BytesIO(); image.convert('RGB').save(out,format='JPEG',quality=93,optimize=True); out.seek(0)
    return discord.File(out,filename='247blackjack.jpg')


async def _247bj_edit_message(game: Live247BlackjackGame):
    if game.message is None:
        return
    view = Live247BlackjackView(game, timeout=LIVE_247BJ_TOTAL_ROUND_SECONDS + 30)
    file = view.rebuild()
    try:
        await game.message.edit(view=view, attachments=[file])
    except Exception as exc:
        print(f"[247BJ] Message update failed for game {game.game_number}: {exc}")


async def _247bj_settle_game(game: Live247BlackjackGame):
    async with game.lock:
        if game.finished:
            return
        game.phase = "settling"
        for player in game.active_players():
            player["state"] = "stand"

        game.play_dealer()
        dealer_total = game.dealer_total()
        dealer_blackjack = len(game.dealer) == 2 and dealer_total == 21

        for player in game.players.values():
            cards = player["cards"]
            total = blackjack_hand_total(cards)
            natural = len(cards) == 2 and total == 21

            if total > 21:
                result = "LOSE"
                payout = Decimal("0")
            elif natural and not dealer_blackjack:
                result = "BLACKJACK"
                payout = (player["bet"] * Decimal("2.5")).quantize(Decimal("0.01"))
            elif dealer_total > 21:
                result = "WIN"
                payout = player["bet"] * Decimal("2")
            elif total > dealer_total:
                result = "WIN"
                payout = player["bet"] * Decimal("2")
            elif total == dealer_total:
                result = "PUSH"
                payout = player["bet"]
            else:
                result = "LOSE"
                payout = Decimal("0")

            player["result"] = result
            player["payout"] = payout

            try:
                if result == "WIN" or result == "BLACKJACK":
                    await game.bot.db.record_game(
                        player["user_id"],
                        player["bet"],
                        payout,
                        "247blackjack",
                        result=result,
                        game_id=game.game_number,
                        server_hash=game.bot.server_hash(game.server_seed),
                        server_seed=game.server_seed,
                        client_seed=game.client_seed,
                        nonce=game.game_number,
                    )
                    await game.bot.send_win_log(player["user_id"], payout, player["bet"], "247blackjack")
                elif result == "PUSH":
                    await game.bot.db.record_game(
                        player["user_id"],
                        player["bet"],
                        payout,
                        "247blackjack",
                        result="PUSH",
                        game_id=game.game_number,
                        server_hash=game.bot.server_hash(game.server_seed),
                        server_seed=game.server_seed,
                        client_seed=game.client_seed,
                        nonce=game.game_number,
                    )
                else:
                    await game.bot.db.record_game(
                        player["user_id"],
                        player["bet"],
                        Decimal("0"),
                        "247blackjack",
                        result="LOSS",
                        game_id=game.game_number,
                        server_hash=game.bot.server_hash(game.server_seed),
                        server_seed=game.server_seed,
                        client_seed=game.client_seed,
                        nonce=game.game_number,
                    )
                    await game.bot.send_loss_log(player["user_id"], player["bet"], "247blackjack")
            except Exception as exc:
                print(f"[247BJ] Settlement error for {player['user_id']}: {exc}")

        game.finished = True
        game.phase = "finished"


async def _247bj_game_loop(game: Live247BlackjackGame):
    try:
        await _247bj_edit_message(game)
        await asyncio.sleep(LIVE_247BJ_JOIN_SECONDS)

        async with game.lock:
            if game.finished:
                return
            game.phase = "playing"
            if game.players:
                game.deal_initial()

        await _247bj_edit_message(game)

        # Decision phase: up to 20 seconds. A round with no players still ends normally.
        decision_end = asyncio.get_running_loop().time() + LIVE_247BJ_DECISION_SECONDS
        while asyncio.get_running_loop().time() < decision_end:
            if game.all_decided():
                break
            await asyncio.sleep(1)
            await _247bj_edit_message(game)

        await _247bj_settle_game(game)
        await _247bj_edit_message(game)
        await asyncio.sleep(LIVE_247BJ_GAP_SECONDS)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        print(f"[247BJ] Game {game.game_number} crashed: {type(exc).__name__}: {exc}")


async def _247bj_join_modal(self, interaction: discord.Interaction, game: Live247BlackjackGame):
    if game.finished or game.phase != "joining":
        await interaction.response.send_message("This game is no longer accepting players.", ephemeral=True)
        return
    if interaction.user.id in game.players:
        await interaction.response.send_message("You are already in this game.", ephemeral=True)
        return
    if len(game.players) >= LIVE_247BJ_MAX_PLAYERS:
        await interaction.response.send_message("This game is full (6 players maximum).", ephemeral=True)
        return
    await interaction.response.send_modal(Live247BetModal(self, game))


async def _247bj_join(self, interaction: discord.Interaction, game: Live247BlackjackGame, amount: Decimal):
    if amount < MIN_BET:
        await interaction.response.send_message(f"Minimum bet is {money(MIN_BET)}.", ephemeral=True)
        return
    if amount.as_tuple().exponent < -2:
        await interaction.response.send_message("Use a maximum of 2 decimal places.", ephemeral=True)
        return

    async with game.lock:
        if game.finished or game.phase != "joining":
            await interaction.response.send_message("This game is no longer accepting players.", ephemeral=True)
            return
        if interaction.user.id in game.players:
            await interaction.response.send_message("You are already in this game.", ephemeral=True)
            return
        if len(game.players) >= LIVE_247BJ_MAX_PLAYERS:
            await interaction.response.send_message("This game is full (6 players maximum).", ephemeral=True)
            return
        if not await self.deduct_bet(interaction.user.id, amount, "247blackjack"):
            await interaction.response.send_message("You do not have enough balance for that bet.", ephemeral=True)
            return
        game.add_player(interaction.user.id, amount)
        self.register_fair_game(
            interaction.user.id,
            "247blackjack",
            game.game_number,
            game.server_seed,
            game.client_seed,
            nonce=game.game_number,
            details="24/7 live blackjack shared shoe; player hand vs dealer hand",
        )

    await interaction.response.send_message(
        f"Joined **BJ-{game.game_number:06d}** with **{money(amount)}**.",
        ephemeral=True,
    )
    await _247bj_edit_message(game)


async def _247bj_hit(self, interaction: discord.Interaction, game: Live247BlackjackGame):
    async with game.lock:
        if game.finished or game.phase != "playing":
            await interaction.response.send_message("This round is not accepting Hit decisions.", ephemeral=True)
            return
        player = game.player(interaction.user.id)
        if not player:
            await interaction.response.send_message("You are not playing in this round.", ephemeral=True)
            return
        if player["state"] != "playing":
            await interaction.response.send_message("Your decision is locked. You already stood or finished.", ephemeral=True)
            return

        player["cards"].append(game.draw())
        total = blackjack_hand_total(player["cards"])
        if total > 21:
            player["state"] = "bust"
            player["result"] = "BUST"
        elif total == 21:
            player["state"] = "stand"
            player["result"] = "21"

    await interaction.response.edit_message(view=Live247BlackjackView(game, timeout=LIVE_247BJ_DECISION_SECONDS + 30), attachments=[create_247bj_image(game)])


async def _247bj_stand(self, interaction: discord.Interaction, game: Live247BlackjackGame):
    async with game.lock:
        if game.finished or game.phase != "playing":
            await interaction.response.send_message("This round is not accepting Stand decisions.", ephemeral=True)
            return
        player = game.player(interaction.user.id)
        if not player:
            await interaction.response.send_message("You are not playing in this round.", ephemeral=True)
            return
        if player["state"] != "playing":
            await interaction.response.send_message("Your decision is already locked.", ephemeral=True)
            return
        player["state"] = "stand"
        player["result"] = "STAND"

    await interaction.response.edit_message(view=Live247BlackjackView(game, timeout=LIVE_247BJ_DECISION_SECONDS + 30), attachments=[create_247bj_image(game)])


CasinoBot.live_247_join_modal = _247bj_join_modal
CasinoBot.live_247_join = _247bj_join
CasinoBot.live_247_hit = _247bj_hit
CasinoBot.live_247_stand = _247bj_stand


async def _247bj_start(self, channel_id: int, *, reset_counter: bool = False):
    if self.live_247_task and not self.live_247_task.done():
        self.live_247_task.cancel()
        try:
            await self.live_247_task
        except asyncio.CancelledError:
            pass

    if reset_counter:
        await self.db.set_setting("247bj_game_number", "0")

    await self.db.set_setting("247bj_channel_id", str(channel_id))
    await self.db.set_setting("247bj_enabled", "1")
    self.live_247_channel_id = int(channel_id)
    self.live_247_task = asyncio.create_task(_247bj_scheduler(self))


async def _247bj_stop(self):
    task = getattr(self, "live_247_task", None)
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    self.live_247_task = None


async def _247bj_scheduler(self):
    bot_instance = self
    while True:
        try:
            enabled = await bot_instance.db.setting("247bj_enabled", "0")
            if enabled != "1":
                return

            channel_id = int(await bot_instance.db.setting("247bj_channel_id", "0"))
            if not channel_id:
                return

            channel = bot_instance.get_channel(channel_id)
            if channel is None:
                try:
                    channel = await bot_instance.fetch_channel(channel_id)
                except Exception as exc:
                    print(f"[247BJ] Could not fetch channel {channel_id}: {exc}")
                    await asyncio.sleep(10)
                    continue

            current = int(await bot_instance.db.setting("247bj_game_number", "0"))
            game_number = current + 1
            await bot_instance.db.set_setting("247bj_game_number", str(game_number))

            game = Live247BlackjackGame(bot_instance, channel.id, game_number)
            bot_instance.live_247_game = game

            view = Live247BlackjackView(game, timeout=LIVE_247BJ_TOTAL_ROUND_SECONDS + 30)
            file = view.rebuild()
            game.message = await channel.send(view=view, file=file)

            await _247bj_game_loop(game)
            bot_instance.live_247_game = None
        except asyncio.CancelledError:
            return
        except Exception as exc:
            print(f"[247BJ] Scheduler error: {type(exc).__name__}: {exc}")
            await asyncio.sleep(5)


CasinoBot.live_247_start = _247bj_start
CasinoBot.live_247_stop = _247bj_stop


@prefix_command(name="247bj")
@owner_only()
async def blackjack_247_command(interaction: PrefixInteraction, action: Optional[str] = None):
    raw = str(action or "").strip()

    if raw.lower() == "reset":
        channel_id = getattr(interaction.channel, "id", None)
        saved = await bot.db.setting("247bj_channel_id", "0")
        if saved and saved != "0":
            channel_id = int(saved)
        if not channel_id:
            await interaction.response.send_message(
                embed=error_embed("24/7 Blackjack", "Set a channel first: `.247bj #channel`")
            )
            return
        await bot.live_247_start(channel_id, reset_counter=True)
        await interaction.response.send_message(
            embed=success_embed("24/7 Blackjack Reset", f"The live table restarted from **Game 1** in <#{channel_id}>.")
        )
        return

    if not raw:
        await interaction.response.send_message(
            embed=error_embed("24/7 Blackjack", "Usage: `.247bj #channel` or `.247bj reset`")
        )
        return

    channel_id = None
    match = re.fullmatch(r"<#(\d+)>", raw)
    if match:
        channel_id = int(match.group(1))
    elif raw.isdigit():
        channel_id = int(raw)
    else:
        for channel in getattr(interaction.guild, "text_channels", []):
            if channel.name.lower() == raw.lower():
                channel_id = channel.id
                break

    if not channel_id:
        await interaction.response.send_message(
            embed=error_embed("24/7 Blackjack", "I couldn't find that text channel. Use a channel mention like `#blackjack`.")
        )
        return

    channel = bot.get_channel(channel_id)
    if channel is None or not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message(
            embed=error_embed("24/7 Blackjack", "That channel is not available to the bot.")
        )
        return

    await bot.live_247_start(channel.id)
    await interaction.response.send_message(
        embed=success_embed("24/7 Blackjack Started", f"Live blackjack is now running continuously in {channel.mention}.\n\n**5 players max** · **10s join** · **20s decisions** · **10s between rounds**")
    )


async def _247bj_restore_on_ready():
    try:
        enabled = await bot.db.setting("247bj_enabled", "0")
        channel_id = await bot.db.setting("247bj_channel_id", "0")
        if enabled == "1" and channel_id and int(channel_id) > 0:
            if not getattr(bot, "live_247_task", None) or bot.live_247_task.done():
                bot.live_247_channel_id = int(channel_id)
                bot.live_247_task = asyncio.create_task(_247bj_scheduler(bot))
                print(f"[247BJ] Restored live table in channel {channel_id}.")
    except Exception as exc:
        print(f"[247BJ] Restore failed: {exc}")


@bot.listen("on_ready")
async def _247bj_ready_listener():
    await _247bj_restore_on_ready()


# ============================================================
# MARKET PRICE / ADDRESS COMMANDS
# ============================================================
# Prefix commands:
#   .ltc
#   .sol
#   .usdt
#   .addy <address>
#
# These commands deliberately use multiple public endpoints with fallbacks.
# That prevents a CoinGecko rate-limit/API outage from making .usdt or .addy
# appear completely broken.

COIN_MARKET_IDS = {
    "ltc": "litecoin",
    "sol": "solana",
    "usdt": "tether",
}

COIN_DISPLAY_NAMES = {
    "ltc": "Litecoin (LTC)",
    "sol": "Solana (SOL)",
    "usdt": "Tether (USDT)",
}


def _market_price_headers():
    key = os.getenv("COINGECKO_API_KEY", "").strip()
    return {"x-cg-demo-api-key": key} if key else {}


def _fmt_price(value):
    value = D(value)
    if value >= Decimal("1000"):
        return f"${value:,.2f}"
    if value >= Decimal("1"):
        return f"${value:,.4f}"
    return f"${value:,.8f}"


def _chart_file(symbol: str, points: list[float], current: float, change: float):
    width, height = 1200, 520
    image = Image.new("RGB", (width, height), (12, 14, 18))
    draw = ImageDraw.Draw(image)
    try:
        font_big = ImageFont.truetype("DejaVuSans-Bold.ttf", 34)
        font_small = ImageFont.truetype("DejaVuSans.ttf", 20)
        font_tiny = ImageFont.truetype("DejaVuSans.ttf", 16)
    except Exception:
        font_big = font_small = font_tiny = ImageFont.load_default()

    draw.text((40, 25), f"{symbol.upper()} · 24H", fill=(240, 240, 245), font=font_big)
    draw.text((40, 72), _fmt_price(current), fill=(220, 225, 235), font=font_small)
    change_text = f"24h {change:+.2f}%"
    draw.text((220, 72), change_text, fill=(100, 220, 145) if change >= 0 else (245, 100, 100), font=font_small)

    left, top, right, bottom = 40, 130, width - 40, height - 45
    draw.rectangle((left, top, right, bottom), outline=(45, 49, 58), width=1)
    if len(points) < 2:
        draw.text((left + 20, top + 20), "Chart data unavailable", fill=(180, 185, 195), font=font_small)
    else:
        lo, hi = min(points), max(points)
        if hi == lo:
            hi = lo + 1e-12
        pad = (hi - lo) * 0.08
        lo -= pad
        hi += pad
        coords = []
        n = len(points)
        for i, value in enumerate(points):
            x = left + (right - left) * i / (n - 1)
            y = bottom - (value - lo) / (hi - lo) * (bottom - top)
            coords.append((int(x), int(y)))
        for i in range(1, 5):
            y = top + (bottom - top) * i / 5
            draw.line((left, y, right, y), fill=(27, 30, 37), width=1)
        draw.line(coords, fill=(104, 170, 255), width=4, joint="curve")
        draw.ellipse((coords[-1][0]-5, coords[-1][1]-5, coords[-1][0]+5, coords[-1][1]+5), fill=(235, 240, 250))
        draw.text((left, bottom + 10), f"Low {_fmt_price(min(points))}", fill=(145, 150, 160), font=font_tiny)
        text = f"High {_fmt_price(max(points))}"
        bbox = draw.textbbox((0, 0), text, font=font_tiny)
        draw.text((right - (bbox[2] - bbox[0]), bottom + 10), text, fill=(145, 150, 160), font=font_tiny)

    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    output.seek(0)
    return discord.File(output, filename=f"{symbol}-24h.png")


async def _fetch_json(url: str, *, params=None, headers=None, method="GET"):
    session = bot.http_session
    owns_session = False
    if session is None or session.closed:
        session = aiohttp.ClientSession()
        owns_session = True
    try:
        timeout = aiohttp.ClientTimeout(total=12)
        if method.upper() == "POST":
            async with session.post(url, params=params, headers=headers, timeout=timeout) as response:
                data = await response.json(content_type=None)
                if response.status >= 400:
                    raise RuntimeError(f"HTTP {response.status}")
                return data
        async with session.get(url, params=params, headers=headers, timeout=timeout) as response:
            data = await response.json(content_type=None)
            if response.status >= 400:
                raise RuntimeError(f"HTTP {response.status}")
            return data
    finally:
        if owns_session:
            await session.close()


async def _fetch_market_data(symbol: str):
    coin_id = COIN_MARKET_IDS[symbol]
    errors = []

    # Primary: CoinGecko.
    try:
        headers = _market_price_headers()
        price_data = await _fetch_json(
            "https://api.coingecko.com/api/v3/simple/price",
            params={
                "ids": coin_id,
                "vs_currencies": "usd",
                "include_24hr_change": "true",
            },
            headers=headers,
        )
        entry = price_data.get(coin_id, {})
        price = float(entry.get("usd"))
        change = float(entry.get("usd_24h_change") or 0)

        chart_data = await _fetch_json(
            f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart",
            params={"vs_currency": "usd", "days": "1", "interval": "hourly"},
            headers=headers,
        )
        points = [float(row[1]) for row in chart_data.get("prices", []) if len(row) >= 2]
        if price > 0 and len(points) >= 2:
            return price, change, points
        errors.append("CoinGecko returned incomplete data")
    except Exception as exc:
        errors.append(f"CoinGecko: {type(exc).__name__}: {exc}")

    # Fallback: Binance for LTC/SOL. USDT is intentionally $1 when the
    # market API is unavailable; it is a USD-pegged token, so this keeps the
    # command useful instead of failing outright.
    if symbol in {"ltc", "sol"}:
        pair = f"{symbol.upper()}USDT"
        try:
            ticker = await _fetch_json("https://api.binance.com/api/v3/ticker/24hr", params={"symbol": pair})
            current = float(ticker["lastPrice"])
            change = float(ticker.get("priceChangePercent", 0))
            klines = await _fetch_json("https://api.binance.com/api/v3/klines", params={"symbol": pair, "interval": "1h", "limit": 24})
            points = [float(k[4]) for k in klines]
            return current, change, points
        except Exception as exc:
            errors.append(f"Binance: {type(exc).__name__}: {exc}")
    else:
        # Last-resort USDT display. We still try CoinGecko above first so the
        # 24h change is real whenever the API is available.
        points = [1.0] * 24
        return 1.0, 0.0, points

    raise RuntimeError("; ".join(errors))


async def _send_market_command(interaction: PrefixInteraction, symbol: str):
    try:
        price, change, points = await _fetch_market_data(symbol)
    except Exception as exc:
        print(f"[MARKET] {symbol.upper()} error: {type(exc).__name__}: {exc}")
        await interaction.response.send_message(
            embed=error_embed(
                f"{symbol.upper()} Price",
                "Market data is temporarily unavailable. Please try again in a moment.",
            )
        )
        return

    file = _chart_file(symbol, points, price, change)
    direction = "▲" if change >= 0 else "▼"
    embed = base_embed(
        title=COIN_DISPLAY_NAMES[symbol],
        description=(
            f"> Current price · **{_fmt_price(price)}**\n"
            f"> 24h change · **{direction} {change:+.2f}%**\n"
            f"> 24h high · **{_fmt_price(max(points))}**\n"
            f"> 24h low · **{_fmt_price(min(points))}**\n\n"
            "Live market data · 24 hour chart"
        ),
    )
    embed.set_image(url=f"attachment://{symbol}-24h.png")
    await interaction.response.send_message(embed=embed, file=file)


@prefix_command(name="ltc", aliases=["litecoin"])
async def ltc_market(interaction: PrefixInteraction):
    await _send_market_command(interaction, "ltc")


@prefix_command(name="sol", aliases=["solana"])
async def sol_market(interaction: PrefixInteraction):
    await _send_market_command(interaction, "sol")


@prefix_command(name="usdt", aliases=["tether"])
async def usdt_market(interaction: PrefixInteraction):
    await _send_market_command(interaction, "usdt")


async def _rpc_json(url: str, method: str, params: list):
    session = bot.http_session
    owns_session = False
    if session is None or session.closed:
        session = aiohttp.ClientSession()
        owns_session = True
    try:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=12)) as response:
            data = await response.json(content_type=None)
            if response.status != 200 or "error" in data:
                raise RuntimeError(f"RPC HTTP {response.status}: {data.get('error', '')}")
            return data.get("result")
    finally:
        if owns_session:
            await session.close()


async def _sol_address_details(address: str):
    rpc_urls = [
        "https://api.mainnet-beta.solana.com",
        "https://solana-rpc.publicnode.com",
    ]
    last_error = None
    for rpc in rpc_urls:
        try:
            balance_result = await _rpc_json(rpc, "getBalance", [address, {"commitment": "confirmed"}])
            signatures = await _rpc_json(rpc, "getSignaturesForAddress", [address, {"limit": 5, "commitment": "confirmed"}])
            lamports = int((balance_result or {}).get("value", 0))
            return lamports / 1_000_000_000, signatures or []
        except Exception as exc:
            last_error = exc
    raise RuntimeError(str(last_error or "Solana RPC unavailable"))


async def _ltc_address_details(address: str):
    endpoints = [
        f"https://api.blockchair.com/litecoin/dashboards/address/{address}",
        f"https://litecoinspace.org/api/address/{address}",
    ]
    last_error = None
    for url in endpoints:
        try:
            data = await _fetch_json(url)
            if "blockchair" in url:
                row = data.get("data", {}).get(address)
                if not row:
                    raise RuntimeError("Address not found")
                return {
                    "balance": D(row.get("address", {}).get("balance", 0)) / Decimal("100000000"),
                    "received": D(row.get("address", {}).get("received", 0)) / Decimal("100000000"),
                    "spent": D(row.get("address", {}).get("spent", 0)) / Decimal("100000000"),
                    "tx_count": int(row.get("address", {}).get("transaction_count", 0)),
                    "txs": row.get("transactions", [])[:5],
                }
            chain_stats = data.get("chain_stats", {})
            mempool_stats = data.get("mempool_stats", {})
            funded = int(chain_stats.get("funded_txo_sum", 0)) + int(mempool_stats.get("funded_txo_sum", 0))
            spent = int(chain_stats.get("spent_txo_sum", 0)) + int(mempool_stats.get("spent_txo_sum", 0))
            tx_count = int(chain_stats.get("tx_count", 0)) + int(mempool_stats.get("tx_count", 0))
            return {
                "balance": Decimal(funded - spent) / Decimal("100000000"),
                "received": Decimal(funded) / Decimal("100000000"),
                "spent": Decimal(spent) / Decimal("100000000"),
                "tx_count": tx_count,
                "txs": [],
            }
        except Exception as exc:
            last_error = exc
    raise RuntimeError(str(last_error or "Litecoin explorer unavailable"))


async def _evm_usdt_details(address: str, network: str):
    # Blockscout token endpoint is used for token balances and recent txs;
    # RPC is only used for native balance. This avoids explorer API-key limits.
    if network == "bsc":
        rpc = "https://bsc-dataseed.binance.org"
        blockscout = "https://bsc.blockscout.com/api/v2"
        usdt_contract = "0x55d398326f99059ff775485246999027b3197955"
    else:
        rpc = "https://ethereum-rpc.publicnode.com"
        blockscout = "https://eth.blockscout.com/api/v2"
        usdt_contract = "0xdAC17F958D2ee523a2206206994597C13D831ec7"

    token_balance = Decimal("0")
    native_balance = Decimal("0")
    txs = []

    try:
        native = await _rpc_json(rpc, "eth_getBalance", [address, "latest"])
        native_balance = Decimal(int(native or "0x0", 16)) / Decimal(10**18)
    except Exception:
        pass

    try:
        tokens = await _fetch_json(f"{blockscout}/addresses/{address}/tokens", params={"type": "ERC-20", "limit": 50})
        for item in tokens.get("items", []):
            token = item.get("token", {}) or {}
            contract = str(token.get("address", "")).lower()
            symbol = str(token.get("symbol", "")).upper()
            if contract == usdt_contract.lower() or symbol == "USDT":
                raw = item.get("value", item.get("balance", "0"))
                decimals = int(token.get("decimals") or 6)
                token_balance = Decimal(str(raw)) / (Decimal(10) ** decimals)
                break
    except Exception as exc:
        print(f"[ADDY] {network} token endpoint: {exc}")

    try:
        tx_data = await _fetch_json(f"{blockscout}/addresses/{address}/transactions", params={"limit": 5})
        txs = tx_data.get("items", [])[:5]
    except Exception:
        pass

    return token_balance, native_balance, txs


async def _tron_address_details(address: str):
    data = await _fetch_json(f"https://api.trongrid.io/v1/accounts/{address}")
    account = (data.get("data") or [{}])[0]
    trx = Decimal(int(account.get("balance", 0))) / Decimal(10**6)
    usdt = Decimal("0")
    for token in account.get("trc20", []) or []:
        for contract, raw in token.items():
            # USDT TRC20 contract.
            if contract.lower() == "41a614f803b6fd780986a42c78ec9c7f77e6b2b1" or contract.lower() == "0xa614f803b6fd780986a42c78ec9c7f77e6b2b1":
                usdt = Decimal(str(raw)) / Decimal(10**6)
    return trx, usdt


@prefix_command(name="addy", aliases=["address"])
async def address_details(interaction: PrefixInteraction, address: str):
    address = str(address).strip().strip("<>")
    if not address:
        await interaction.response.send_message(embed=error_embed("Address", "Usage: `.addy <address>`"))
        return

    # Litecoin: ltc1, M/m, L, or legacy 3-prefix addresses.
    if address.lower().startswith(("ltc1", "m", "n", "l", "3")):
        try:
            row = await _ltc_address_details(address)
            recent = "\n".join(f"• `{str(tx)[:18]}…`" for tx in row.get("txs", [])) or "No transaction IDs returned."
            embed = base_embed(
                title="Litecoin Address",
                description=(
                    f"**Address**\n`{address}`\n\n"
                    f"**Balance:** `{row['balance']:.8f} LTC`\n"
                    f"**Received:** `{row['received']:.8f} LTC`\n"
                    f"**Spent:** `{row['spent']:.8f} LTC`\n"
                    f"**Transactions:** `{row['tx_count']}`\n\n"
                    f"**Recent transactions**\n{recent}"
                ),
            )
            await interaction.response.send_message(embed=embed)
        except Exception as exc:
            print(f"[ADDY] LTC error: {type(exc).__name__}: {exc}")
            await interaction.response.send_message(embed=error_embed("LTC Address", "That Litecoin address could not be looked up right now."))
        return

    # TRON / TRC20 USDT.
    if re.fullmatch(r"T[1-9A-HJ-NP-Za-km-z]{33}", address):
        try:
            trx, usdt = await _tron_address_details(address)
            embed = base_embed(
                title="TRON / USDT Address",
                description=(
                    f"**Address**\n`{address}`\n\n"
                    f"**TRX balance:** `{trx:.6f}`\n"
                    f"**USDT (TRC20):** `{usdt:.6f}`"
                ),
            )
            await interaction.response.send_message(embed=embed)
        except Exception as exc:
            print(f"[ADDY] TRON error: {type(exc).__name__}: {exc}")
            await interaction.response.send_message(embed=error_embed("TRON Address", "That TRON address could not be looked up right now."))
        return

    # EVM: check Ethereum and BSC USDT without requiring an API key.
    if re.fullmatch(r"0x[a-fA-F0-9]{40}", address):
        results = []
        for network in ("ethereum", "bsc"):
            try:
                token_balance, native_balance, txs = await _evm_usdt_details(address, network)
                results.append((network, token_balance, native_balance, txs))
            except Exception as exc:
                print(f"[ADDY] {network} error: {type(exc).__name__}: {exc}")
        if not results:
            await interaction.response.send_message(embed=error_embed("EVM Address", "The Ethereum/BSC address could not be looked up right now."))
            return
        sections = []
        for network, token_balance, native_balance, txs in results:
            recent = "\n".join(f"• `{str(item.get('hash', ''))[:18]}…`" for item in txs) or "No recent transactions returned."
            native = "ETH" if network == "ethereum" else "BNB"
            sections.append(
                f"**{network.title()}**\n"
                f"USDT: `{token_balance:.6f}`\n"
                f"{native}: `{native_balance:.6f}`\n"
                f"Recent txs: `{len(txs)}`\n{recent}"
            )
        embed = base_embed(
            title="EVM / USDT Address",
            description=f"**Address**\n`{address}`\n\n" + "\n\n".join(sections),
        )
        await interaction.response.send_message(embed=embed)
        return

    # Solana: conservative base58 detection.
    if not address.startswith("0x") and 32 <= len(address) <= 44 and all(c in "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz" for c in address):
        try:
            sol_balance, signatures = await _sol_address_details(address)
            recent = "\n".join(f"• `{item.get('signature', '')[:18]}…`" for item in signatures) or "No transactions returned."
            embed = base_embed(
                title="Solana Address",
                description=(
                    f"**Address**\n`{address}`\n\n"
                    f"**Balance:** `{sol_balance:.9f} SOL`\n"
                    f"**Recent transactions:** `{len(signatures)}` returned\n\n{recent}"
                ),
            )
            await interaction.response.send_message(embed=embed)
        except Exception as exc:
            print(f"[ADDY] SOL error: {type(exc).__name__}: {exc}")
            await interaction.response.send_message(embed=error_embed("Solana Address", "That Solana address could not be looked up right now."))
        return

    await interaction.response.send_message(
        embed=error_embed(
            "Unsupported Address",
            "Supported formats: Litecoin, Solana, TRON/TRC20, or 0x Ethereum/BSC addresses.",
        )
    )


# COMMAND ERROR HANDLER
# ============================================================

# ============================================================
# PREFIX COMMAND ERROR HANDLER
# ============================================================

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    print(f"[COMMAND ERROR] {getattr(ctx.command, 'name', 'unknown')}: {type(error).__name__}: {error}")
    if isinstance(error, commands.CheckFailure):
        await ctx.send(embed=error_embed("Permission Denied", "You do not have permission to use this command."))
        return
    if isinstance(error, (commands.BadArgument, commands.MissingRequiredArgument)):
        await ctx.send(embed=error_embed("Invalid Arguments", "Please check the command arguments and try again."))
        return
    await ctx.send(embed=error_embed("Something went wrong", "Please try again."))



# ============================================================
# FINAL COMMAND SET / REPLACEMENTS
# ============================================================

REMOVED_COMMANDS = {
    "howtoplay", "affiliates", "affiliate-claim", "affiliate", "aff",
    "affiliateinfo", "rewardinfo", "code", "codechannel", "frog-run",
    "race-start", "race-end", "retrigger", "ranks", "rank-rewards",
    "usdt", "housebal",
}
for _name in list(REMOVED_COMMANDS):
    try:
        bot.remove_command(_name)
    except Exception:
        pass

# Remove commands that are redefined below.
for _name in ["balance", "stats", "history", "leaderboard", "lb", "help", "admin", "ranksetup", "private-channel", "privatechannel", "rakeback", "rb"]:
    try:
        bot.remove_command(_name)
    except Exception:
        pass

@prefix_command(name="balance", aliases=["b", "bal"])
async def balance_command_final(interaction: PrefixInteraction):
    balance = await bot.get_balance(interaction.user.id)
    file = create_balance_image(interaction.user, balance)
    if file:
        view = CasinoV2View(timeout=300)
        view.add_item(discord.ui.Container(
            discord.ui.TextDisplay(f"## {interaction.user.display_name} Balance"),
            discord.ui.MediaGallery(discord.MediaGalleryItem(media="attachment://balance.png")),
            discord.ui.TextDisplay(f"> :Wallet: **{int((balance*100).to_integral_value(rounding=ROUND_DOWN)):,} Points**\n> :PL_Money: **{money(balance)} USD**"),
            discord.ui.TextDisplay("-# 1 Point = $0.01 USD"),
            accent_color=0x2F3136,
        ))
        await interaction.response.send_message(view=view, file=file)
    else:
        await interaction.response.send_message(
            embed=base_embed(f"{interaction.user.display_name} Balance", f":Wallet: **{int((balance*100).to_integral_value(rounding=ROUND_DOWN)):,} Points**\n:PL_Money: **{money(balance)} USD**", 0x2F3136)
        )

@prefix_command(name="stats")
async def stats_command_final(interaction: PrefixInteraction):
    row = await bot.get_db_user(interaction.user.id)
    if not row:
        await interaction.response.send_message("Account not found.")
        return
    wagered=D(row.get("wagered",0)); deposited=D(row.get("lifetime_deposit",0)); withdrawn=D(row.get("lifetime_withdraw",0)); balance=D(row.get("balance",0))
    rank = rank_for_wager(wagered)
    embed=base_embed(f"{interaction.user.display_name} stats", "", 0x5865F2)
    embed.add_field(name=":Wallet: Balance :", value=f"**{money(balance)}**", inline=False)
    embed.add_field(name="Deposited :", value=f"**{money(deposited)}**", inline=False)
    embed.add_field(name="Withdrawed :", value=f"**{money(withdrawn)}**", inline=False)
    embed.add_field(name="Wagared :", value=f"**{money(wagered)}**", inline=False)
    embed.add_field(name="Rank :", value=f"**{rank['name']}**", inline=False)
    try: embed.set_thumbnail(url=str(interaction.user.display_avatar.url))
    except Exception: pass
    await interaction.response.send_message(embed=embed)

@prefix_command(name="history")
async def history_command_final(interaction: PrefixInteraction):
    rows=await bot.db.pool.fetch("SELECT game,bet,result,created_at,choice,fair_details,payout,game_id FROM game_history WHERE user_id=$1 ORDER BY created_at DESC LIMIT 10", interaction.user.id)
    lines=[f"## :Wallet: Bet History - {interaction.user.display_name}"]
    if not rows: lines.append("> No games played yet.")
    for row in rows:
        result=str(row['result'] or '').upper()
        icon='✓' if result in {'WIN','WON','BLACKJACK'} or D(row['payout'])>D(row['bet']) else '✕'
        game=str(row['game']).replace('_',' ').title()
        choice=str(row['choice'] or '')
        if not choice:
            details=str(row['fair_details'] or '')
            m=re.search(r'Selected side:\s*([^\n]+)', details, re.I)
            choice=m.group(1).strip() if m else ('—' if game.lower() not in {'mines'} else 'mines')
        outcome='won' if icon=='✓' else ('push' if result=='PUSH' else 'lose')
        lines.append(f"> {icon} **{game}** · **{money(row['bet'])}** · `{choice}` · **{outcome}**")
    view=CasinoV2View(timeout=180)
    view.add_item(discord.ui.Container(discord.ui.TextDisplay("\n".join(lines)),accent_color=0x57F287))
    await interaction.response.send_message(view=view)

class LeaderboardView(CasinoV2View):
    def __init__(self, rows, page=0):
        super().__init__(timeout=180); self.rows=rows; self.page=page; self.rebuild()
    def rebuild(self):
        self.clear_items(); start=self.page*10; rows=self.rows[start:start+10]
        lines=["## :PL_Money: Leaderboard", "> Top wagerers by total wagered", ""]
        for i,row in enumerate(rows,start+1):
            member=bot.get_user(int(row['user_id'])); name=member.display_name if member else f"User {row['user_id']}"
            lines.append(f"**{i}. {name}** — `{money(row['wagered'])}`")
        prev=discord.ui.Button(label="Previous",style=discord.ButtonStyle.secondary,disabled=self.page<=0)
        nxt=discord.ui.Button(label="Next",style=discord.ButtonStyle.secondary,disabled=(start+10>=len(self.rows)))
        async def previous(interaction):
            if interaction.user.id != self._owner_id: return await interaction.response.send_message("This leaderboard belongs to another user.",ephemeral=True)
            self.page=max(0,self.page-1); self.rebuild(); await interaction.response.edit_message(view=self)
        async def next_page(interaction):
            if interaction.user.id != self._owner_id: return await interaction.response.send_message("This leaderboard belongs to another user.",ephemeral=True)
            self.page+=1; self.rebuild(); await interaction.response.edit_message(view=self)
        prev.callback=previous; nxt.callback=next_page
        self.add_item(discord.ui.Container(discord.ui.TextDisplay("\n".join(lines)),discord.ui.ActionRow(prev,nxt),accent_color=0x5865F2))
    def set_owner(self,user_id): self._owner_id=user_id

@prefix_command(name="leaderboard", aliases=["lb"])
async def leaderboard_command_final(interaction: PrefixInteraction):
    rows=await bot.db.pool.fetch("SELECT user_id,wagered FROM users ORDER BY wagered DESC LIMIT 100")
    view=LeaderboardView(rows); view.set_owner(interaction.user.id); await interaction.response.send_message(view=view)

@prefix_command(name="help")
async def help_command_final(interaction: PrefixInteraction):
    text=(
        "## CryptoBet — Commands\n\n"
        "### Games\n"
        "> `.bj <amount> [sidebet1] [sidebet2]` · blackjack\n"
        "> `.cf <amount> <heads/tails>` · coinflip\n"
        "> `.mines <amount> <mines>` · mines\n"
        "> `.tower` · tower\n"
        "> `.roulette <amount>` · roulette\n"
        "> `.limbo <amount> <target>` · limbo\n\n"
        "### Wallet\n"
        "> `.b` `.bal` `.balance` · wallet\n"
        "> `.deposit` · LTC / SOL deposit\n"
        "> `.withdraw` · withdrawal wizard\n"
        "> `.tip` · tip another player\n"
        "> `.claim <code>` · claim a code\n"
        "> `.rb` `.rakeback` · rakeback\n\n"
        "### Account\n"
        "> `.stats` · account stats\n"
        "> `.history` · last 10 games\n"
        "> `.verify <game id>` `.fair` · verify a game\n"
        "> `.lb` `.leaderboard` · leaderboard\n"
        "> `.privatechannel` · private channel\n"
        "> `.thread` · private thread tools\n\n"
        "### Rewards\n"
        "> `.rain` · rain\n"
        "> `.create <code> <amount> <max users>` · create a claim code\n"
    )
    view=CasinoV2View(timeout=300); view.add_item(discord.ui.Container(discord.ui.TextDisplay(text),accent_color=0x5865F2))
    try: await interaction.user.send(view=view); await interaction.response.send_message("> ﹒the help center was sent to your DMs")
    except discord.Forbidden: await interaction.response.send_message("I couldn't DM you. Please enable DMs.")

@prefix_command(name="admin")
@bot_owner_only()
async def admin_command_final(interaction: PrefixInteraction):
    text=(
        "## Admin\n\n"
        "> `.winlogs <channel>` · set WIN/LOSE log channel\n"
        "> `.withdrawlog <channel>` · set withdrawal log channel\n"
        "> `.minwithdraw <amount>` · set minimum withdrawal\n"
        "> `.depositadmin <user> <amount>` · admin deposit\n"
        "> `.credit <user> <amount>` · promotional credit (2× wagering)\n"
        "> `.create <code> <amount> <max users>` · create claim code\n"
        "> `.disable <command>` / `.enable <command>` · command control\n"
        "> `.ranksetup` · create rank roles\n"
        "> `.247bj <channel>` / `.247bj reset` · live blackjack table\n"
        "> `.addbal` · owner balance adjustment\n"
    )
    view=CasinoV2View(timeout=300); view.add_item(discord.ui.Container(discord.ui.TextDisplay(text),accent_color=0xED4245)); await interaction.response.send_message(view=view)

@prefix_command(name="minwithdraw")
@bot_owner_only()
async def minwithdraw_command(interaction: PrefixInteraction, amount: str):
    value=normalize_amount(amount)
    if value is None or value <= 0:
        await interaction.response.send_message("Enter a valid minimum withdrawal amount."); return
    bot.min_withdrawal=value; await bot.db.set_setting("min_withdrawal",str(value))
    await interaction.response.send_message(f"> ﹒minimum withdrawal is now **{money(value)}**")

@prefix_command(name="credit")
@bot_owner_only()
async def credit_command(interaction: PrefixInteraction, user: discord.Member, amount: str):
    value=normalize_amount(amount)
    if value is None or value<=0: await interaction.response.send_message("Invalid amount."); return
    ok=await bot.db.change_balance(user.id,value,kind="credit",note="Admin promotional credit")
    if not ok: await interaction.response.send_message("Credit failed."); return
    await interaction.response.send_message(f"**{user.display_name}** credited **{money(value)}**. They must wager **{money(value*2)}** before withdrawing it.")

@prefix_command(name="create")
@bot_owner_only()
async def create_command(interaction: PrefixInteraction, code: str, amount: str, max_users: int):
    value=normalize_amount(amount)
    if value is None or value<=0 or max_users<=0:
        await interaction.response.send_message("Usage: `.create <code> <amount> <max users>`"); return
    code=code.strip().upper()
    try:
        await bot.db.create_code(code,value,max_users,created_by=interaction.user.id)
    except Exception as exc:
        if 'duplicate' in str(exc).lower() or 'unique' in str(exc).lower(): await interaction.response.send_message("That code already exists."); return
        raise
    await interaction.response.send_message(f"**{code}** created · **{money(value)}** per person · **{max_users}** users.")

@prefix_command(name="depositadmin")
@bot_owner_only()
async def depositadmin_command(interaction: PrefixInteraction, user: discord.Member, amount: str):
    value=normalize_amount(amount)
    if value is None or value<=0: await interaction.response.send_message("Invalid USD amount."); return
    price=await get_crypto_usd_price('LTC')
    if not price or price<=0: await interaction.response.send_message("Could not get the current LTC price."); return
    ltc=(value/price).quantize(Decimal('0.00000001'),rounding=ROUND_DOWN)
    points=int((value*Decimal('100')).to_integral_value(rounding=ROUND_DOWN))
    async with bot.db.pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("INSERT INTO users(user_id) VALUES($1) ON CONFLICT(user_id) DO NOTHING",user.id)
            await conn.execute("UPDATE users SET balance=balance+$2,lifetime_deposit=lifetime_deposit+$2,updated_at=NOW() WHERE user_id=$1",user.id,value)
            await conn.execute("INSERT INTO transactions(user_id,kind,amount,note) VALUES($1,'depositadmin',$2,$3)",user.id,value,'Admin LTC deposit')
    channel_id=await bot.db.setting('winlog_channel_id','0')
    if channel_id:
        channel=bot.get_channel(int(channel_id))
        if channel:
            await channel.send(f"**{user.display_name}** deposited **{ltc:.8f} LTC** → **{points} pts**")
    await interaction.response.send_message(f"**{user.display_name}** deposited **{ltc:.8f} LTC** → **{points} pts**")

@prefix_command(name="disable")
@bot_owner_only()
async def disable_command(interaction: PrefixInteraction, command: str):
    name=str(command).strip().lstrip('.').lower()
    cmd=bot.get_command(name)
    if not cmd: await interaction.response.send_message(f"Unknown command: `{name}`"); return
    bot.disabled_commands.add(cmd.name); [bot.disabled_commands.add(a) for a in cmd.aliases]
    await interaction.response.send_message(f"Disabled `.{cmd.name}`.")

@prefix_command(name="enable")
@bot_owner_only()
async def enable_command(interaction: PrefixInteraction, command: str):
    name=str(command).strip().lstrip('.').lower()
    cmd=bot.get_command(name)
    if cmd:
        bot.disabled_commands.discard(cmd.name); [bot.disabled_commands.discard(a) for a in cmd.aliases]
        await interaction.response.send_message(f"Enabled `.{cmd.name}`.")
    else:
        bot.disabled_commands.discard(name); await interaction.response.send_message(f"Enabled `.{name}`.")

@prefix_command(name="ranksetup")
@bot_owner_only()
async def ranksetup_command_final(interaction: PrefixInteraction):
    guild=interaction.guild
    if not guild: await interaction.response.send_message("Use this in a server."); return
    created=[]
    for rank in RANKS:
        role=discord.utils.get(guild.roles,name=rank['name'])
        if not role:
            try: role=await guild.create_role(name=rank['name'],colour=discord.Colour(rank['color']),reason='CryptoBet rank setup'); created.append(role.name)
            except Exception: continue
        else:
            try: await role.edit(colour=discord.Colour(rank['color']))
            except Exception: pass
    await interaction.response.send_message("Created/updated ranks: " + ', '.join(r['name'] for r in RANKS))

async def _auto_assign_rank(user_id:int):
    row=await bot.get_db_user(user_id)
    if not row: return
    wagered=D(row['wagered']); eligible=[r for r in RANKS if wagered>=r['wager']]
    if not eligible: return
    rank=eligible[-1]
    for guild in bot.guilds:
        member=guild.get_member(user_id)
        if not member: continue
        rank_roles={r['name']:discord.utils.get(guild.roles,name=r['name']) for r in RANKS}
        target=rank_roles.get(rank['name'])
        if not target: continue
        remove=[role for name,role in rank_roles.items() if role and role in member.roles and role.id!=target.id]
        try:
            if remove: await member.remove_roles(*remove,reason='Automatic wager rank update')
            if target not in member.roles: await member.add_roles(target,reason='Automatic wager rank update')
        except Exception as exc: print(f'[RANK] {exc}')

# Replace the old rank checker with role assignment.
check_rank_up = _auto_assign_rank
bot.check_rank_up = _auto_assign_rank

@prefix_command(name="privatechannel", aliases=["private-channel"])
async def privatechannel_command(interaction: PrefixInteraction):
    balance=await bot.get_balance(interaction.user.id)
    if balance<Decimal('25'): await interaction.response.send_message('You need at least **$25.00** balance to create a private channel.'); return
    guild=interaction.guild
    if not guild: await interaction.response.send_message('Use this in a server.'); return
    category=interaction.channel.category
    overwrites={guild.default_role:discord.PermissionOverwrite(view_channel=False),interaction.user:discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True)}
    channel=await guild.create_text_channel(name=f'private-{interaction.user.name}',category=category,overwrites=overwrites,reason='Private channel created')
    await channel.send(f'## Private Channel\nOwner: {interaction.user.mention}\n\nThis channel requires a **$25 balance**.',view=PrivateChannelView(bot,interaction.user.id))
    await interaction.response.send_message(f'Private channel created: {channel.mention}')

@prefix_command(name="thread")
async def thread_command(interaction: PrefixInteraction, action: str = "", member: Optional[discord.Member] = None):
    action=str(action or '').lower().strip(); user_id=interaction.user.id; key=f'thread_owner:{user_id}'
    saved=await bot.db.setting(key,'')
    thread=None
    if saved:
        try: thread=interaction.guild.get_thread(int(saved)) if interaction.guild else None
        except Exception: thread=None
    if action in {'','show'}:
        await interaction.response.send_message(f'Your thread: {thread.mention if thread else "none"}')
        return
    if action=='create':
        if thread and not thread.archived: await interaction.response.send_message(f'You already have a thread: {thread.mention}'); return
        if thread: await bot.db.set_setting(key,'')
        thread=await interaction.channel.create_thread(name=f'{interaction.user.display_name} thread',type=discord.ChannelType.private_thread,auto_archive_duration=1440)
        await thread.add_user(interaction.user); await bot.db.set_setting(key,str(thread.id)); await interaction.response.send_message(f'Thread created: {thread.mention}'); return
    if not thread: await interaction.response.send_message('You do not have an active thread. Use `.thread create`.'); return
    if action=='add' and member:
        await thread.add_user(member); await interaction.response.send_message(f'{member.mention} added to {thread.mention}'); return
    if action=='remove' and member:
        await thread.remove_user(member); await interaction.response.send_message(f'{member.mention} removed from {thread.mention}'); return
    if action=='delete':
        await thread.delete(reason='Thread owner deleted thread'); await bot.db.set_setting(key,''); await interaction.response.send_message('Thread deleted.'); return
    await interaction.response.send_message('Use `.thread`, `.thread create`, `.thread add @user`, `.thread remove @user`, or `.thread delete`.')

# Rakeback alias.
@prefix_command(name="rakeback", aliases=["rb"])
async def rakeback_final(interaction: PrefixInteraction):
    amount=await bot.db.rakeback(interaction.user.id)
    if amount<=0: await interaction.response.send_message('No rakeback available.'); return
    claimed=await bot.db.claim_rakeback(interaction.user.id)
    if claimed<=0: await interaction.response.send_message('No rakeback available.'); return
    await interaction.response.send_message(f'> ﹒rakeback claimed **{money(claimed)}**')

# ============================================================
# TASK STARTUP
# ============================================================

@rank_monitor.before_loop
async def before_rank_monitor():

    await bot.wait_until_ready()


@private_channel_monitor.before_loop
async def before_private_monitor():

    await bot.wait_until_ready()


# ============================================================
# START TASKS AFTER READY
# ============================================================

_original_on_ready = bot.on_ready


async def _final_on_ready():

    await _original_on_ready()

    if not rank_monitor.is_running():
        rank_monitor.start()

    if not private_channel_monitor.is_running():
        private_channel_monitor.start()


bot.on_ready = _final_on_ready


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    if not BOT_TOKEN:

        raise RuntimeError(
            "DISCORD_TOKEN is not configured."
        )

    bot.run(
        BOT_TOKEN
    )
