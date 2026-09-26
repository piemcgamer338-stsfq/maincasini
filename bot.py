# ============================================================
# bot.py — PART 1 / 10
# ZETHER CASINO — REGENERATED SLASH-COMMAND BOT
# ============================================================

from __future__ import annotations

import asyncio
import hashlib
import hmac
import io
import json
import os
import random
import secrets
import string
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from pathlib import Path
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
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

COINFLIP_MULTIPLIER = Decimal("1.92")
DICE_MULTIPLIER = Decimal("1.92")

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
    {
        "name": "Bronze",
        "stage": "I",
        "wager": Decimal("50"),
        "reward": Decimal("1"),
    },
    {
        "name": "Bronze",
        "stage": "II",
        "wager": Decimal("150"),
        "reward": Decimal("2"),
    },
    {
        "name": "Bronze",
        "stage": "III",
        "wager": Decimal("300"),
        "reward": Decimal("3"),
    },
    {
        "name": "Silver",
        "stage": "I",
        "wager": Decimal("400"),
        "reward": Decimal("5"),
    },
    {
        "name": "Silver",
        "stage": "II",
        "wager": Decimal("500"),
        "reward": Decimal("8"),
    },
    {
        "name": "Silver",
        "stage": "III",
        "wager": Decimal("600"),
        "reward": Decimal("10"),
    },
    {
        "name": "Diamond",
        "stage": None,
        "wager": Decimal("1000"),
        "reward": Decimal("15"),
    },
    {
        "name": "Amethyst",
        "stage": None,
        "wager": Decimal("1200"),
        "reward": Decimal("20"),
    },
    {
        "name": "Celestial",
        "stage": None,
        "wager": Decimal("1500"),
        "reward": Decimal("30"),
    },
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

    if value == "all":
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

    @discord.ui.button(
        label="Withdraw",
        style=discord.ButtonStyle.secondary,
        custom_id="wallet_withdraw",
    )
    async def withdraw_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await interaction.response.send_modal(
            WithdrawModal(
                self.bot,
                interaction.user.id,
            )
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
        label="LTC",
        style=discord.ButtonStyle.secondary,
        custom_id="deposit_ltc",
    )
    async def ltc_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await self.bot.send_deposit_dm(
            interaction,
            "LTC",
        )

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


class WithdrawModal(discord.ui.Modal):

    def __init__(
        self,
        bot: "CasinoBot",
        user_id: int,
    ):
        super().__init__(
            title="Withdraw",
            timeout=300,
        )

        self.bot = bot
        self.user_id = user_id

        self.currency = discord.ui.TextInput(
            label="Currency",
            placeholder="LTC / SOL / ETH / USDT",
            required=True,
            max_length=10,
        )

        self.address = discord.ui.TextInput(
            label="Withdrawal Address",
            placeholder="Enter your wallet address",
            required=True,
            max_length=150,
        )

        self.amount = discord.ui.TextInput(
            label="Amount",
            placeholder="Example: 10.00",
            required=True,
            max_length=30,
        )

        self.add_item(self.currency)
        self.add_item(self.address)
        self.add_item(self.amount)

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ):

        await self.bot.handle_withdrawal(
            interaction=interaction,
            user_id=self.user_id,
            currency=self.currency.value,
            address=self.address.value,
            amount_text=self.amount.value,
        )


# ============================================================
# DICE SETUP VIEW
# ============================================================

class DiceSetupView(ButtonView):

    def __init__(
        self,
        bot: "CasinoBot",
        user_id: int,
        amount: Decimal,
    ):
        super().__init__(timeout=120)

        self.bot = bot
        self.user_id = user_id
        self.amount = amount
        self.mode = None
        self.dice_count = None

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:

        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This dice setup belongs to another player.",
                ephemeral=False,
            )
            return False

        return True

    @discord.ui.button(
        label="Crazy Dice",
        style=discord.ButtonStyle.primary,
        custom_id="dice_mode_crazy",
    )
    async def crazy(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        self.mode = "crazy"
        await self._choose_dice(interaction)

    @discord.ui.button(
        label="Normal Dice",
        style=discord.ButtonStyle.secondary,
        custom_id="dice_mode_normal",
    )
    async def normal(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        self.mode = "normal"
        await self._choose_dice(interaction)

    async def _choose_dice(
        self,
        interaction: discord.Interaction,
    ):

        view = DiceCountView(
            self.bot,
            self.user_id,
            self.amount,
            self.mode,
        )

        await interaction.response.edit_message(
            content=(
                "**Choose Number of Dice**\n\n"
                "Select 1, 2, or 3 dice."
            ),
            view=view,
        )


class DiceCountView(ButtonView):

    def __init__(
        self,
        bot: "CasinoBot",
        user_id: int,
        amount: Decimal,
        mode: str,
    ):
        super().__init__(timeout=120)

        self.bot = bot
        self.user_id = user_id
        self.amount = amount
        self.mode = mode

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:

        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This dice setup belongs to another player.",
                ephemeral=False,
            )
            return False

        return True

    async def choose(
        self,
        interaction: discord.Interaction,
        count: int,
    ):

        await interaction.response.defer()

        await self.bot.start_dice_game(
            interaction,
            self.user_id,
            self.amount,
            self.mode,
            count,
        )

    @discord.ui.button(
        label="1 Dice",
        style=discord.ButtonStyle.secondary,
        custom_id="dice_count_1",
    )
    async def one(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await self.choose(interaction, 1)

    @discord.ui.button(
        label="2 Dice",
        style=discord.ButtonStyle.secondary,
        custom_id="dice_count_2",
    )
    async def two(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await self.choose(interaction, 2)

    @discord.ui.button(
        label="3 Dice",
        style=discord.ButtonStyle.secondary,
        custom_id="dice_count_3",
    )
    async def three(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await self.choose(interaction, 3)


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

        self.bombs = set(
            random.sample(
                range(24),
                mines,
            )
        )

        self.opened: set[int] = set()
        self.finished = False

    @property
    def multiplier(self) -> Decimal:

        opened = len(self.opened)

        if opened <= 0:
            return Decimal("1.00")

        value = (
            Decimal("24")
            / Decimal(str(24 - self.mines))
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


class MinesView(ButtonView):

    def __init__(
        self,
        game: MinesGame,
    ):
        super().__init__(timeout=300)

        self.game = game

        for index in range(24):

            button = discord.ui.Button(
                label="?",
                style=discord.ButtonStyle.secondary,
                custom_id=f"mine:{index}",
                row=index // 5,
            )

            button.callback = self.make_callback(index)

            self.add_item(button)

        cashout = discord.ui.Button(
            label="Cashout",
            emoji="💰",
            style=discord.ButtonStyle.success,
            custom_id="mine_cashout",
            row=4,
        )

        cashout.callback = self.cashout

        self.add_item(cashout)

    def make_callback(self, index: int):

        async def callback(
            interaction: discord.Interaction,
        ):

            if interaction.user.id != self.game.user_id:
                await interaction.response.send_message(
                    "This Mines game belongs to another player.",
                    ephemeral=False,
                )
                return

            await self.game.bot.mines_click(
                interaction,
                self.game,
                index,
                self,
            )

        return callback

    async def cashout(
        self,
        interaction: discord.Interaction,
    ):

        if interaction.user.id != self.game.user_id:
            await interaction.response.send_message(
                "This Mines game belongs to another player.",
                ephemeral=False,
            )
            return

        await self.game.bot.mines_cashout(
            interaction,
            self.game,
            self,
        )


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

        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            help_command=None,
        )

        self.db: Optional[Database] = None

        self.http_session: Optional[aiohttp.ClientSession] = None

        self.started_at = datetime.now(timezone.utc)

        self.active_games: dict[int, dict] = {}
        self.active_mines: dict[int, MinesGame] = {}
        self.active_rains: dict[str, dict] = {}
        self.active_dice: dict[int, dict] = {}

        self.game_counter = random.randint(
            1000,
            9999,
        )

        self._cooldowns: dict[
            tuple[int, str],
            float,
        ] = {}

        self.ltc_watcher_task = None

    # ========================================================
    # GAME IDS
    # ========================================================

    def next_game_id(self) -> int:

        self.game_counter += 1

        if self.game_counter > 999999:
            self.game_counter = 1000

        return self.game_counter

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
        """Send a public win notification to the configured win-log channel."""
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

            multiplier = (
                payout / bet
            ).quantize(Decimal("0.01"), rounding=ROUND_DOWN)

            game_name = str(game).replace("_", " ").title()
            tick = getattr(config, "E", {}).get("win", "<:Tick:1550062215220961370>")

            await channel.send(
                f"{tick} <@{user_id}> has won **{money(payout)}** "
                f"in **{game_name}** **{multiplier:.2f}x**"
            )
        except Exception as exc:
            print(f"[WIN LOG] {exc}")

    async def settle_win(
        self,
        user_id: int,
        bet: Decimal,
        payout: Decimal,
        game: str,
    ):

        await self.db.record_game(
            user_id,
            bet,
            payout,
            game,
        )

        await self.send_win_log(
            user_id,
            payout,
            bet,
            game,
        )

    async def settle_loss(
        self,
        user_id: int,
        bet: Decimal,
        game: str,
    ):

        await self.db.record_game(
            user_id,
            bet,
            Decimal("0"),
            game,
        )

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

        # Compatibility migrations for databases created by older bot versions.
        # These are idempotent and keep existing balances/data intact.
        async with self.db.pool.acquire() as connection:
            await connection.execute("""
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ
                NOT NULL DEFAULT NOW()
            """)
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS house (
                    id INTEGER PRIMARY KEY,
                    balance NUMERIC(20,4) NOT NULL DEFAULT 0
                )
            """)
            await connection.execute("""
                INSERT INTO house(id, balance)
                VALUES(1, 0)
                ON CONFLICT(id) DO NOTHING
            """)

        self.http_session = aiohttp.ClientSession()

        self.add_view(
            RainView(
                self,
                "persistent",
            )
        )

        try:
            synced = await self.tree.sync()

            print(
                f"[BOT] Synced {len(synced)} slash commands."
            )

        except Exception as exc:
            print(
                f"[BOT] Slash command sync failed: {exc}"
            )

        self.ltc_watcher_task = asyncio.create_task(
            self.ltc_deposit_watcher()
        )

    async def close(self):

        if self.ltc_watcher_task:
            self.ltc_watcher_task.cancel()

            try:
                await self.ltc_watcher_task
            except asyncio.CancelledError:
                pass

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
                name="/help"
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

        if currency == "LTC":

            return await self.generate_ltc_address(
                user_id
            )

        return None

    # ========================================================
    # LTC ADDRESS PLACEHOLDER
    # ========================================================

    async def generate_ltc_address(
        self,
        user_id: int,
    ) -> Optional[str]:

        if hasattr(
            self.db,
            "get_or_create_ltc_address",
        ):

            return await self.db.get_or_create_ltc_address(
                user_id,
                config.LTC_XPUB,
                config.LTC_DERIVATION_PATH,
            )

        return None

    # ========================================================
    # WITHDRAWAL
    # ========================================================

    async def handle_withdrawal(
        self,
        interaction: discord.Interaction,
        user_id: int,
        currency: str,
        address: str,
        amount_text: str,
    ):

        currency = currency.strip().upper()
        address = address.strip()

        amount = normalize_amount(
            amount_text
        )

        if currency not in {
            "LTC",
            "SOL",
            "ETH",
            "USDT",
        }:

            await interaction.response.send_message(
                "Supported currencies: LTC, SOL, ETH, USDT.",
                ephemeral=False,
            )

            return

        if amount is None:

            await interaction.response.send_message(
                "Enter a valid withdrawal amount.",
                ephemeral=False,
            )

            return

        minimum = D(
            config.MIN_WITHDRAW.get(
                currency,
                0,
            )
        )

        if minimum and amount < minimum:

            await interaction.response.send_message(
                f"Minimum {currency} withdrawal is "
                f"{money(minimum)}.",
                ephemeral=False,
            )

            return

        if not self.valid_withdraw_address(
            currency,
            address,
        ):

            await interaction.response.send_message(
                "That withdrawal address is invalid.",
                ephemeral=False,
            )

            return

        balance = await self.get_balance(
            user_id
        )

        if amount > balance:

            await interaction.response.send_message(
                "You Dont Have Enough Crypto\n"
                "-# use /deposit to top-up Funds",
                ephemeral=False,
            )

            return

        if hasattr(
            self.db,
            "create_withdrawal",
        ):

            created = await self.db.create_withdrawal(
                user_id=user_id,
                currency=currency,
                address=address,
                amount=amount,
            )

            if not created:

                await interaction.response.send_message(
                    "Your withdrawal could not be created.",
                    ephemeral=False,
                )

                return

        else:

            deducted = await self.db.change_balance(
                user_id,
                -amount,
                kind="withdraw",
                note=f"{currency}:{address}",
            )

            if not deducted:

                await interaction.response.send_message(
                    "Your withdrawal could not be processed.",
                    ephemeral=False,
                )

                return

        await interaction.response.send_message(
            f"## Withdrawal Requested\n\n"
            f"**Amount:** {money(amount)}\n"
            f"**Currency:** {currency}\n\n"
            "Your withdrawal is pending processing.",
            ephemeral=False,
        )

    def valid_withdraw_address(
        self,
        currency: str,
        address: str,
    ) -> bool:

        if not address:
            return False

        if currency == "LTC":
            return (
                address.startswith(
                    (
                        "ltc1",
                        "M",
                        "m",
                        "L",
                    )
                )
                and len(address) >= 26
            )

        if currency == "SOL":
            return 32 <= len(address) <= 50

        if currency in {
            "ETH",
            "USDT",
        }:
            return (
                address.startswith("0x")
                and len(address) == 42
            )

        return False

    # ========================================================
    # BLOCKCHAIN WATCHER
    # ========================================================

    async def ltc_deposit_watcher(self):

        await self.wait_until_ready()

        while not self.is_closed():

            try:

                await self.check_ltc_deposits()

            except asyncio.CancelledError:

                raise

            except Exception as exc:

                print(
                    f"[LTC WATCHER] {exc}"
                )

            await asyncio.sleep(60)

    async def check_ltc_deposits(self):

        endpoint = os.getenv(
            "LTC_PROVIDER_DEPOSIT_URL",
            "",
        ).strip()

        if not endpoint:
            return

        if not self.http_session:
            return

        headers = {}

        api_key = getattr(
            config,
            "PAYMENT_PROVIDER_API_KEY",
            "",
        )

        if api_key:
            headers["Authorization"] = (
                f"Bearer {api_key}"
            )

        async with self.http_session.get(
            endpoint,
            headers=headers,
            timeout=aiohttp.ClientTimeout(
                total=20
            ),
        ) as response:

            if response.status != 200:
                return

            data = await response.json()

        if not isinstance(data, list):
            return

        for deposit in data:

            if not isinstance(deposit, dict):
                continue

            await self.process_ltc_deposit(
                deposit
            )

    async def process_ltc_deposit(
        self,
        deposit: dict,
    ):

        if not hasattr(
            self.db,
            "process_deposit",
        ):
            return

        await self.db.process_deposit(
            deposit
        )


# ============================================================
# BOT INSTANCE
# ============================================================

bot = CasinoBot()


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


async def _embed_ir_send(self, *args, **kwargs):
    if "embed" not in kwargs and "embeds" not in kwargs:
        content = kwargs.get("content")
        if content is None and args:
            content = args[0]
            args = args[1:]
        if content is not None:
            kwargs["embed"] = _plain_response_embed(content)
            kwargs.pop("content", None)
    return await _original_ir_send(self, *args, **kwargs)


async def _embed_ir_edit(self, *args, **kwargs):
    if "embed" not in kwargs and "embeds" not in kwargs:
        content = kwargs.get("content")
        if content is None and args:
            content = args[0]
            args = args[1:]
        if content is not None:
            kwargs["embed"] = _plain_response_embed(content)
            kwargs.pop("content", None)
    return await _original_ir_edit(self, *args, **kwargs)


async def _embed_original_edit(self, *args, **kwargs):
    if "embed" not in kwargs and "embeds" not in kwargs:
        content = kwargs.get("content")
        if content is not None:
            kwargs["embed"] = _plain_response_embed(content)
            kwargs.pop("content", None)
    return await _original_interaction_edit_original(self, *args, **kwargs)


async def _embed_messageable_send(self, *args, **kwargs):
    if "embed" not in kwargs and "embeds" not in kwargs:
        content = kwargs.get("content")
        if content is None and args:
            content = args[0]
            args = args[1:]
        if content is not None:
            # V2 LayoutViews cannot be combined with legacy embeds.
            view = kwargs.get("view")
            layout_cls = getattr(discord.ui, "LayoutView", None)
            if layout_cls is None or not isinstance(view, layout_cls):
                kwargs["embed"] = _plain_response_embed(content)
                kwargs.pop("content", None)
    return await _original_messageable_send(self, *args, **kwargs)


async def _embed_webhook_send(self, *args, **kwargs):
    if "embed" not in kwargs and "embeds" not in kwargs:
        content = kwargs.get("content")
        if content is None and args:
            content = args[0]
            args = args[1:]
        if content is not None:
            view = kwargs.get("view")
            layout_cls = getattr(discord.ui, "LayoutView", None)
            if layout_cls is None or not isinstance(view, layout_cls):
                kwargs["embed"] = _plain_response_embed(content)
                kwargs.pop("content", None)
    return await _original_webhook_send(self, *args, **kwargs)


discord.InteractionResponse.send_message = _embed_ir_send
discord.InteractionResponse.edit_message = _embed_ir_edit
discord.Interaction.edit_original_response = _embed_original_edit
discord.abc.Messageable.send = _embed_messageable_send
discord.Webhook.send = _embed_webhook_send


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
# /BALANCE
# ============================================================

@bot.tree.command(
    name="balance",
    description="View your wallet balance.",
)
async def balance_command(
    interaction: discord.Interaction,
):

    if not await require_database(interaction):
        return

    balance = await bot.get_balance(
        interaction.user.id
    )

    embed = base_embed(
        title=f"## {interaction.user.display_name}'s Wallet",
        description=(
            f"**Balance:** {money(balance)}"
        ),
    )

    await interaction.response.send_message(
        embed=embed,
        view=WalletView(
            bot,
            interaction.user.id,
        ),
        ephemeral=False,
    )


# ============================================================
# /DEPOSIT
# ============================================================

@bot.tree.command(
    name="deposit",
    description="Get your cryptocurrency deposit address.",
)
async def deposit_command(
    interaction: discord.Interaction,
):

    await interaction.response.send_message(
        "Choose a currency Below",
        view=DepositCurrencyView(
            bot,
            interaction.user.id,
        ),
        ephemeral=False,
    )


# ============================================================
# /WITHDRAW
# ============================================================

@bot.tree.command(
    name="withdraw",
    description="Withdraw funds to a cryptocurrency address.",
)
async def withdraw_command(
    interaction: discord.Interaction,
):

    await interaction.response.send_modal(
        WithdrawModal(
            bot,
            interaction.user.id,
        )
    )


# ============================================================
# /HELP
# ============================================================

HELP_GENERAL = (
    "## General\n"
    "`/help` — Show this help menu\n"
    "`/balance` — View your wallet\n"
    "`/deposit` — Deposit cryptocurrency\n"
    "`/withdraw` — Withdraw funds\n"
    "`/stats` — View your player statistics\n"
    "`/history` — View recent game history\n"
    "`/howtoplay` — Learn how to play\n"
    "`/rewardinfo` — View rewards and perks\n"
    "`/affiliateinfo` — View affiliate rates\n"
    "`/fair` — View provably-fair information"
)

HELP_GAMES = (
    "## Games\n"
    "`/dice` — Select a dice game\n"
    "`/roll` — Roll your dice\n"
    "`/coinflip` — Play Red or Blue coinflip\n"
    "`/mines` — Play Mines\n"
    "`/blackjack` — Play Blackjack\n"
    "`/frog-run` — Play Frog Run\n"
    "`/retrigger` — Retrigger an unfinished game\n"
    "`/fix-dice` — Recover a dice game"
)

HELP_REWARDS = (
    "## Rewards\n"
    "`/rakeback` — Claim available rakeback\n"
    "`/ranks` — View rank progression\n"
    "`/rank-rewards` — Claim rank rewards\n"
    "`/affiliates` — View your affiliates\n"
    "`/affiliate-claim` — Claim affiliate earnings\n"
    "`/claim` — Claim a promo code\n"
    "`/leaderboard` — View top wagerers\n"
    "`/race` — View the active wager race"
)

HELP_SOCIAL = (
    "## Social\n"
    "`/tip` — Tip another player\n"
    "`/rain` — Start a rain event\n"
    "`/private-channel` — Manage a private gaming channel"
)

HELP_ADMIN = (
    "## Admin\n"
    "`/ranksetup` — Configure rank roles\n"
    "`/code` — Create a promotional code\n"
    "`/race start` — Start a wager race\n"
    "`/race end` — End a wager race\n"
    "`/winlogs` — Set the win-log channel"
)


@bot.tree.command(
    name="help",
    description="View all available commands.",
)
async def help_command(
    interaction: discord.Interaction,
):

    embed = base_embed(
        title="Help",
        description=(
            f"{HELP_GENERAL}\n\n"
            f"{HELP_GAMES}\n\n"
            f"{HELP_REWARDS}\n\n"
            f"{HELP_SOCIAL}"
        ),
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=False,
    )


# ============================================================
# /HOWTOPLAY
# ============================================================

@bot.tree.command(
    name="howtoplay",
    description="Learn how to use the bot.",
)
async def howtoplay_command(
    interaction: discord.Interaction,
):

    description = (
        "## Funding Your Account\n"
        "Use `/deposit` to receive a supported deposit address. "
        "Deposits are credited only after blockchain confirmation.\n\n"

        "## Dice\n"
        "Use `/dice` to select your mode and number of dice. "
        "Use `/roll` to roll your dice. "
        "Normal Dice uses the highest total. "
        "Crazy Dice uses the lowest total.\n\n"

        "## Coinflip\n"
        "Use `/coinflip` with an amount and your color. "
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
        "Unfinished games can be recovered with `/retrigger`.\n\n"

        "## Withdrawals\n"
        "Use `/withdraw` to request a withdrawal. "
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
        "`/stats` — View your progress\n"
        "`/history` — View your last 10 games\n"
        "`/fair` — Verify game information\n"
        "`/rakeback` — Claim rakeback\n"
        "`/leaderboard` — View the top wagerers"
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
# /STATS
# ============================================================

@bot.tree.command(
    name="stats",
    description="View your player statistics.",
)
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

@bot.tree.command(
    name="affiliates",
    description="View your affiliate statistics.",
)
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
        "Use `/affiliate-claim` to claim your earnings."
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

@bot.tree.command(
    name="affiliate-claim",
    description="Claim your affiliate earnings.",
)
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

@bot.tree.command(
    name="rewardinfo",
    description="View rewards and perks."
)
async def rewardinfo(
    interaction: discord.Interaction,
):

    text = (
        "## Rewards & Perks\n\n"

        "### Rakeback\n"
        "You receive **1% rakeback on losses**.\n"
        "Winning wagers do not generate rakeback.\n"
        "Use `/rakeback` to claim available rakeback.\n\n"

        "### Lossback\n"
        "Eligible promotional lossback may be distributed according "
        "to active promotions.\n\n"

        "### Affiliates\n"
        "Earn a percentage from qualifying referred-player activity.\n"
        "Use `/affiliateinfo` for the current affiliate rates.\n\n"

        "### Promo Codes\n"
        "Promo codes may require a deposit or wagering requirement.\n"
        "Use `/claim <code>` to claim an eligible code.\n\n"

        "### Wager Race\n"
        "The wager race tracks qualifying wager during the active race.\n"
        "Use `/race` to view the current race.\n\n"

        "### Tips & Rain\n"
        "Users can send tips with `/tip`.\n"
        "Eligible users can participate in `/rain` events.\n\n"

        "### Rank Rewards\n"
        "Ranks progress through wager milestones.\n"
        "Rank rewards can be claimed using `/rank-rewards`.\n\n"

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
# /AFFILIATEINFO
# ============================================================

@bot.tree.command(
    name="affiliateinfo",
    description="View affiliate rates."
)
async def affiliateinfo(
    interaction: discord.Interaction,
):

    text = (
        "## Affiliate Program\n\n"
        "**1+ referred players:** 0.10%\n"
        "**10+ referred players:** 0.20%\n"
        "**25+ referred players:** 0.35%\n"
        "**100+ referred players:** 0.50%\n\n"

        "Use `/affiliates` to view your referral information.\n"
        "Use `/affiliate-claim` to claim available affiliate earnings."
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

@bot.tree.command(
    name="history",
    description="View your last 10 games."
)
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
# /TIP
# ============================================================

@bot.tree.command(
    name="tip",
    description="Tip another user."
)
@app_commands.describe(
    user="The user receiving the tip.",
    amount="Amount to tip.",
)
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

    value = normalize_amount(
        amount
    )

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

@bot.tree.command(
    name="ranks",
    description="View all ranks and wager requirements."
)
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

@bot.tree.command(
    name="rank-rewards",
    description="View and claim available rank rewards."
)
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

@bot.tree.command(
    name="leaderboard",
    description="View the top 10 wagerers."
)
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
        f"{24 - game.mines}",
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

    for item in view.children:

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

    for item in view.children:

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
                for item in view.children
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

        await interaction.edit_original_response(
            embed=embed,
            view=view,
        )

        return

    game.opened.add(index)

    button = next(
        (
            item
            for item in view.children
            if isinstance(item, discord.ui.Button)
            and item.custom_id == f"mine:{index}"
        ),
        None,
    )

    if button:
        button.label = "💎"
        button.style = discord.ButtonStyle.success
        button.disabled = True

    safe_count = 24 - game.mines

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

        await interaction.edit_original_response(
            embed=embed,
            view=view,
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

    await interaction.edit_original_response(
        embed=embed,
        view=view,
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


@bot.tree.command(
    name="mines",
    description="Play Mines.",
)
@app_commands.describe(
    amount="Bet amount in USD.",
    mines="Number of mines (1-20).",
)
async def mines_command(
    interaction: discord.Interaction,
    amount: str,
    mines: app_commands.Range[int, 1, 20],
):

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

    bet = normalize_amount(amount)

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

    if mines >= 24:
        await bot.safe_send(
            interaction,
            content="Choose between 1 and 20 mines.",
            ephemeral=False,
        )
        return

    deducted = await bot.deduct_bet(
        interaction.user.id,
        bet,
        "mines",
    )

    if not deducted:

        await bot.safe_send(
            interaction,
            content="Your balance changed. Please try again.",
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

    bot.active_mines[
        interaction.user.id
    ] = game

    view = MinesView(game)

    await interaction.response.send_message(
        embed=mines_embed(game),
        view=view,
    )

    message = await interaction.original_response()

    game.message_id = message.id
    game.channel_id = interaction.channel_id



# ============================================================
# RAIN
# ============================================================

async def rain_daily_wager(
    bot_instance: CasinoBot,
    user_id: int,
) -> Decimal:

    if hasattr(
        bot_instance.db,
        "get_daily_wager",
    ):

        return D(
            await bot_instance.db.get_daily_wager(
                user_id
            )
        )

    row = await bot_instance.get_db_user(
        user_id
    )

    if not row:
        return Decimal("0")

    return D(
        row["wagered"]
    )


async def has_rain_role(
    interaction: discord.Interaction,
) -> bool:

    role_id = getattr(
        config,
        "RAIN_ROLE_ID",
        0,
    )

    if not role_id:
        return True

    if not isinstance(
        interaction.user,
        discord.Member,
    ):
        return False

    return any(
        role.id == role_id
        for role in interaction.user.roles
    )


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
            ephemeral=False,
        )

        return

    if not await has_rain_role(
        interaction
    ):

        await interaction.response.send_message(
            "You need the verified role to join rain.",
            ephemeral=False,
        )

        return

    wagered = await rain_daily_wager(
        self,
        interaction.user.id,
    )

    if wagered < Decimal("1"):

        await interaction.response.send_message(
            "You need at least **$1** wagered today to join rain.",
            ephemeral=False,
        )

        return

    if interaction.user.id in rain["players"]:

        await interaction.response.send_message(
            "You already joined this rain.",
            ephemeral=False,
        )

        return

    rain["players"].add(
        interaction.user.id
    )

    await interaction.response.send_message(
        "You joined the rain.",
        ephemeral=False,
    )


CasinoBot.join_rain = join_rain


async def finish_rain(
    self: CasinoBot,
    rain_id: str,
):

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

    channel = self.get_channel(
        rain["channel_id"]
    )

    if not channel:
        return

    if not players:

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

        return

    share = (
        amount
        / Decimal(len(players))
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_DOWN,
    )

    distributed = share * len(players)

    remainder = (
        amount - distributed
    ).quantize(
        Decimal("0.01")
    )

    if remainder > 0:

        share += (
            remainder
            / Decimal(len(players))
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_DOWN,
        )

    successful = []

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

        except Exception:
            continue

    count = len(successful)

    if count <= 0:

        await self.db.change_balance(
            rain["user_id"],
            amount,
            kind="rain_refund",
            note=rain_id,
        )

        await channel.send(
            f"## Rain Ended — {money(amount)}\n"
            "Nobody could be credited, so the rain "
            "was refunded."
        )

        return

    mention_text = " ".join(
        f"<@{uid}>"
        for uid in successful
    )

    await channel.send(
        f"## Rain Ended — {money(amount)}\n"
        f"## **{rain['owner_mention']}** rained on "
        f"**{count}** players — **{money(share)}** each!\n\n"
        f"{mention_text}"
    )


CasinoBot.finish_rain = finish_rain


@bot.tree.command(
    name="rain",
    description="Start a rain giveaway.",
)
@app_commands.describe(
    amount="Total amount to rain.",
    duration="Rain duration in minutes: 1, 2, 5, or 10.",
)
@app_commands.choices(
    duration=[
        app_commands.Choice(
            name="1 minute",
            value=1,
        ),
        app_commands.Choice(
            name="2 minutes",
            value=2,
        ),
        app_commands.Choice(
            name="5 minutes",
            value=5,
        ),
        app_commands.Choice(
            name="10 minutes",
            value=10,
        ),
    ]
)
async def rain_command(
    interaction: discord.Interaction,
    amount: str,
    duration: app_commands.Choice[int],
):

    bet = normalize_amount(
        amount
    )

    if bet is None:

        await bot.safe_send(
            interaction,
            content="Enter a valid rain amount.",
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

    deducted = await bot.db.change_balance(
        interaction.user.id,
        -bet,
        kind="rain_start",
        note="rain",
    )

    if not deducted:

        await bot.safe_send(
            interaction,
            content="Your balance changed. Please try again.",
            ephemeral=False,
        )

        return

    rain_id = secrets.token_hex(8)

    bot.active_rains[rain_id] = {
        "amount": bet,
        "user_id": interaction.user.id,
        "owner_mention": interaction.user.mention,
        "channel_id": interaction.channel_id,
        "players": set(),
    }

    await interaction.response.send_message(
        f"## Rain Started — **{money(bet)}**\n"
        f"**{interaction.user.mention}** rained — "
        f"**{money(bet)}**\n\n"
        "Click on Button Below to Join",
        view=RainView(
            bot,
            rain_id,
        ),
    )

    seconds = RAIN_DURATIONS[
        duration.value
    ]

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

    await asyncio.sleep(
        seconds
    )

    await bot_instance.finish_rain(
        rain_id
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

COINFLIP_RED_STICKER_ID = 1553360108682084382
COINFLIP_BLUE_STICKER_ID = 1553360311933734913


@bot.tree.command(
    name="coinflip",
    description="Flip a coin against the bot.",
)
@app_commands.describe(
    amount="Amount to bet",
    color="Choose Red or Blue",
)
@app_commands.choices(
    color=[
        app_commands.Choice(
            name="Red",
            value="red",
        ),
        app_commands.Choice(
            name="Blue",
            value="blue",
        ),
    ]
)
async def coinflip(
    interaction: discord.Interaction,
    amount: str,
    color: app_commands.Choice[str],
):
    user_id = interaction.user.id

    cooldown = bot.check_game_cooldown(
        user_id,
        "coinflip",
    )

    if cooldown:
        await bot.safe_send(
            interaction,
            content=(
                f"Please wait **{cooldown:.1f}s** "
                "before playing again."
            ),
            ephemeral=False,
        )
        return

    balance = await bot.get_balance(user_id)

    bet = amount_or_all(
        amount,
        balance,
    )

    if bet is None:
        await bot.safe_send(
            interaction,
            embed=error_embed(
                "Invalid Amount",
                "Enter a valid amount such as `$1`, `1`, or `0.10`.",
            ),
            ephemeral=False,
        )
        return

    if bet < MIN_BET:
        await bot.safe_send(
            interaction,
            embed=error_embed(
                "Minimum Bet",
                f"The minimum bet is **{money(MIN_BET)}**.",
            ),
            ephemeral=False,
        )
        return

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

    selected = color.value

    game_id = bot.next_game_id()

    server_seed = bot.create_server_seed()
    server_hash = bot.server_hash(
        server_seed
    )

    client_seed = bot.create_client_seed(
        user_id
    )

    nonce = 0

    # Deduct the bet exactly once.
    if not await bot.deduct_bet(
        user_id,
        bet,
        "coinflip",
    ):
        await bot.safe_send(
            interaction,
            content="Your balance changed. Please try again.",
            ephemeral=False,
        )
        return

    bot.active_games[user_id] = {
        "type": "coinflip",
        "game_id": game_id,
        "bet": bet,
        "selected": selected,
        "server_seed": server_seed,
        "server_hash": server_hash,
        "client_seed": client_seed,
        "nonce": nonce,
    }

    selected_name = (
        "Red"
        if selected == "red"
        else "Blue"
    )

    opponent_name = (
        "Blue"
        if selected == "red"
        else "Red"
    )

    await interaction.response.send_message(
        embed=neutral_embed(
            "## Flipping…",
            (
                f"**{interaction.user.display_name}** "
                f"({selected_name}) vs Bot "
                f"({opponent_name})\n\n"
                f"**Bet:** {money(bet)} · "
                f"**Game #{game_id}**"
            ),
        )
    )

    await asyncio.sleep(2)

    game = bot.active_games.pop(
        user_id,
        None,
    )

    if not game:
        return

    roll = bot.fair_roll(
        game["server_seed"],
        game["client_seed"],
        game["nonce"],
        "coinflip",
    )

    result = (
        "red"
        if roll < Decimal("50")
        else "blue"
    )

    won = result == selected

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

        result_title = (
            f"## Coinflip — "
            f"{result.title()} wins!"
        )

        result_color = 0x57F287

        result_text = (
            f"**Result:** {result.title()}\n"
            f"**Roll:** {roll}\n"
            f"**Bet:** {money(bet)}\n"
            f"**Payout:** {money(payout)} "
            f"**(1.92x)**"
        )

    else:
        payout = Decimal("0")

        await bot.settle_loss(
            user_id,
            bet,
            "coinflip",
        )

        result_title = (
            f"## Coinflip — "
            f"{result.title()} wins!"
        )

        result_color = 0xED4245

        result_text = (
            f"**Result:** {result.title()}\n"
            f"**Roll:** {roll}\n"
            f"**Bet:** {money(bet)}\n"
            f"**Lost:** {money(bet)}"
        )

    embed = base_embed(
        title=result_title,
        description=result_text,
        color=result_color,
    )

    embed.add_field(
        name="Provably Fair",
        value=(
            f"**Server Hash:** `{game['server_hash']}`\n"
            f"**Client Seed:** `{game['client_seed']}`\n"
            f"**Nonce:** `{game['nonce']}`"
        ),
        inline=False,
    )

    embed.add_field(
        name="Game",
        value=f"`#{game_id}`",
        inline=True,
    )

    embed.set_footer(
        text="Verify this result with /provably-fair"
    )

    await interaction.edit_original_response(
        embed=embed
    )

    # ========================================================
    # SEND RESULT STICKER
    # ========================================================

    sticker_id = (
        COINFLIP_RED_STICKER_ID
        if result == "red"
        else COINFLIP_BLUE_STICKER_ID
    )

    try:
        sticker = await bot.fetch_sticker(
            sticker_id
        )

        await interaction.followup.send(
            stickers=[sticker]
        )

    except Exception as sticker_error:
        print(
            f"[COINFLIP STICKER] "
            f"Failed to send sticker {sticker_id}: "
            f"{sticker_error}"
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

    safe_tiles = 24 - mines

    multiplier = (
        Decimal("24")
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
            title="## Mines — Bomb!",
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
        title="## Mines — Cashed Out",
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

        embed.title = "## Mines — All Safe Tiles!"

    await interaction.response.edit_message(
        embed=embed,
        view=view,
    )


# Attach the methods to the bot instance.
CasinoBot.mines_click = mines_click
CasinoBot.mines_cashout = mines_cashout


# ============================================================
# END PART 5
# ============================================================

# ============================================================
# bot.py — PARTS 6 / 7 / 8 / 9 / 10
# ============================================================


# ============================================================
# /BALANCE
# ============================================================



# ============================================================
# /DEPOSIT
# ============================================================



# ============================================================
# /WITHDRAW
# ============================================================



# ============================================================
# /HELP
# ============================================================

HELP_TEXT = """
## Games
`/dice` `/roll`
`/coinflip`
`/mines`
`/frog-run`
`/bj` `/blackjack`

## Wallet
`/balance`
`/deposit`
`/withdraw`
`/tip`

## Rewards
`/rakeback`
`/ranks`
`/rank-rewards`
`/rewardinfo`

## Rain & Affiliates
`/rain`
`/affiliate`
`/affiliates`
`/affiliate-claim`
`/affiliateinfo`

## Competition
`/leaderboard`
`/race`

## Information
`/howtoplay`
`/stats`
`/history`
`/fair`
`/provably-fair`

## Other
`/claim`
`/private-channel`
`/retrigger`
`/fix-dice`
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

    if rank["stage"]:
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

@bot.tree.command(
    name="rakeback",
    description="Claim your available 1% loss rakeback.",
)
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
# /AFFILIATE / /AFFILIATES
# ============================================================

@bot.tree.command(
    name="affiliate",
    description="View your affiliate information.",
)
async def affiliate(
    interaction: discord.Interaction,
):

    user_id = interaction.user.id

    if hasattr(
        bot.db,
        "affiliate_stats",
    ):

        data = await bot.db.affiliate_stats(
            user_id
        )

        referrals = int(
            data.get("referrals", 0)
        )

        earnings = D(
            data.get("earnings", 0)
        )

        commission = D(
            data.get("rate", 0)
        )

    else:

        referrals = 0
        earnings = Decimal("0")
        commission = Decimal("0")

    percent = (
        commission * Decimal("100")
    )

    await interaction.response.send_message(
        embed=base_embed(
            description=(
                "## Affiliate\n\n"
                f"**Referrals:** {referrals}\n"
                f"**Commission:** {percent:.2f}%\n"
                f"**Available:** {money(earnings)}"
            )
        )
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
            "## 3 Day Race — On GOING",
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
            "## 3 Day Race — Winners!",
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


@bot.tree.command(
    name="race",
    description="View the current wager race.",
)
async def race(
    interaction: discord.Interaction,
):

    await send_race_message(
        interaction
    )


# ============================================================
# OWNER RACE COMMANDS
# ============================================================

def owner_only():
    async def predicate(
        interaction: discord.Interaction,
    ):

        if interaction.user.id not in config.ADMIN_USER_IDS:

            raise app_commands.CheckFailure(
                "Owner only"
            )

        return True

    return app_commands.check(
        predicate
    )


race_group = app_commands.Group(
    name="raceadmin",
    description="Race administration.",
)


@race_group.command(
    name="start",
    description="Start a new wager race.",
)
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


@race_group.command(
    name="end",
    description="End the current wager race.",
)
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
        "Winners are now available through `/race`."
    )


bot.tree.add_command(
    race_group
)


# ============================================================
# /RETRIGGER
# ============================================================

@bot.tree.command(
    name="retrigger",
    description="Restore a recoverable unfinished game.",
)
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

    if user_id in bot.active_dice:

        await interaction.response.send_message(
            "Your Dice game is still active.",
            ephemeral=False,
        )

        return

    await interaction.response.send_message(
        "No recoverable game was found.",
        ephemeral=False,
    )


# ============================================================
# /FIX-DICE
# ============================================================

@bot.tree.command(
    name="fix-dice",
    description="Recover an interrupted dice game.",
)
async def fix_dice(
    interaction: discord.Interaction,
):

    game = bot.active_dice.get(
        interaction.user.id
    )

    if not game:

        await interaction.response.send_message(
            "No active Dice game was found.",
            ephemeral=False,
        )

        return

    await interaction.response.send_message(
        "Your active Dice game is available again.",
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


@bot.tree.command(
    name="private-channel",
    description="Create a private channel.",
)
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

@bot.tree.command(
    name="claim",
    description="Claim a promo code.",
)
@app_commands.describe(
    code="Promo code.",
)
async def claim(
    interaction: discord.Interaction,
    code: str,
):

    code = code.strip().upper()

    if hasattr(
        bot.db,
        "claim_code",
    ):

        result = await bot.db.claim_code(
            interaction.user.id,
            code,
        )

        if not result:

            await interaction.response.send_message(
                "That code is invalid, expired, or already claimed.",
                ephemeral=False,
            )

            return

        amount = D(
            result["amount"]
        )

    else:

        row = await bot.db.pool.fetchrow(
            """
            SELECT
                code,
                amount,
                max_uses,
                uses,
                active
            FROM codes
            WHERE code = $1
            """,
            code,
        )

        if not row:

            await interaction.response.send_message(
                "Invalid promo code.",
                ephemeral=False,
            )

            return

        if not row["active"] or row["uses"] >= row["max_uses"]:

            await interaction.response.send_message(
                "That code has expired.",
                ephemeral=False,
            )

            return

        already = await bot.db.pool.fetchval(
            """
            SELECT 1
            FROM code_claims
            WHERE code = $1
              AND user_id = $2
            """,
            code,
            interaction.user.id,
        )

        if already:

            await interaction.response.send_message(
                "You already claimed this code.",
                ephemeral=False,
            )

            return

        amount = D(
            row["amount"]
        )

        async with bot.db.pool.acquire() as conn:

            async with conn.transaction():

                await conn.execute(
                    """
                    INSERT INTO code_claims(
                        code,
                        user_id
                    )
                    VALUES($1, $2)
                    """,
                    code,
                    interaction.user.id,
                )

                await conn.execute(
                    """
                    UPDATE codes
                    SET uses = uses + 1
                    WHERE code = $1
                    """,
                    code,
                )

    await bot.db.change_balance(
        interaction.user.id,
        amount,
        kind="promo",
        note=code,
    )

    await interaction.response.send_message(
        embed=success_embed(
            "Promo Claimed",
            f"You received **{money(amount)}**."
        )
    )


# ============================================================
# /WINLOGS
# ============================================================

@bot.tree.command(
    name="winlogs",
    description="Set the channel where all wins are logged.",
)
@app_commands.describe(
    channel="The server channel to receive win logs.",
)
@owner_only()
async def winlogs_command(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
):

    if interaction.guild is None:
        await interaction.response.send_message(
            "This command can only be used in a server.",
            ephemeral=False,
        )
        return

    await bot.db.set_setting(
        "winlog_channel_id",
        str(channel.id),
    )

    await interaction.response.send_message(
        f"Win logs are now enabled in {channel.mention}.",
        ephemeral=False,
    )


# ============================================================
# /CODE
# ============================================================

@bot.tree.command(
    name="code",
    description="Create a promotional code.",
)
@app_commands.describe(
    amount="Amount each person receives.",
    max_uses="Maximum number of claims.",
    requirement="Requirement number: 1, 2, or 3.",
)
@owner_only()
async def code_command(
    interaction: discord.Interaction,
    amount: str,
    max_uses: int,
    requirement: int,
):

    value = normalize_amount(
        amount
    )

    if value is None:

        await interaction.response.send_message(
            "Invalid amount.",
            ephemeral=False,
        )

        return

    if max_uses <= 0:

        await interaction.response.send_message(
            "Max uses must be greater than zero.",
            ephemeral=False,
        )

        return

    if requirement not in CODE_REQUIREMENTS:

        await interaction.response.send_message(
            "Requirement must be 1, 2, or 3.",
            ephemeral=False,
        )

        return

    code = (
        "GOOSE-"
        + "".join(
            secrets.choice(
                string.ascii_uppercase
                + string.digits
            )
            for _ in range(8)
        )
    )

    await bot.db.pool.execute(
        """
        INSERT INTO codes(
            code,
            max_uses,
            amount
        )
        VALUES($1, $2, $3)
        """,
        code,
        max_uses,
        value,
    )

    requirement_data = CODE_REQUIREMENTS[
        requirement
    ]

    await interaction.response.send_message(
        embed=success_embed(
            "Promo Code Created",
            (
                f"**Code:** `{code}`\n"
                f"**Amount:** {money(value)} per person\n"
                f"**Max Uses:** {max_uses}\n"
                f"**Requirement:** "
                f"{requirement_data['name']}"
            ),
        ),
        ephemeral=False,
    )


# ============================================================
# /RAIN
# ============================================================



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
        await interaction.response.edit_message(
            embed=frog_embed(
                self,
                "🐸 Frog Run — Cashed Out",
                0x57F287,
                f"**Payout:** {money(payout)}",
            ),
            view=self,
        )


async def _frog_step(self, interaction: discord.Interaction, view: FrogRunView, lane: int):
    if view.finished:
        await interaction.response.send_message("This game has ended.", ephemeral=False)
        return

    row_index = view.position
    safe_lane = random.randrange(FROG_COLS)

    if lane != safe_lane:
        view.finished = True
        view.board[row_index][safe_lane] = "safe"
        view.board[row_index][lane] = "lost"
        for child in view.children:
            child.disabled = True
        await self.settle_loss(view.user_id, view.amount, "frog-run")
        await interaction.response.edit_message(
            embed=frog_embed(
                view,
                "🐸 Frog Run — Lost",
                0xED4245,
                f"You chose the wrong lane.\n**Lost:** {money(view.amount)}",
            ),
            view=view,
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
        await interaction.response.edit_message(
            embed=frog_embed(view, "🐸 Frog Run — Finished!", 0x57F287, f"**Payout:** {money(payout)}"),
            view=view,
        )
        return

    await interaction.response.edit_message(
        embed=frog_embed(view),
        view=view,
    )


CasinoBot.frog_step = _frog_step


@bot.tree.command(name="frog-run", description="Play Frog Run.")
@app_commands.describe(amount="Amount to bet.")
async def frog_run(interaction: discord.Interaction, amount: str):
    value = normalize_amount(amount)
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
    view = FrogRunView(bot, interaction.user.id, value, game_id)
    await interaction.response.send_message(
        embed=frog_embed(view, extra="Choose a lane to jump. 🐸"),
        view=view,
    )


# ============================================================
# /DICE
# ============================================================

@bot.tree.command(
    name="dice",
    description="Create a Dice game.",
)
@app_commands.describe(
    amount="Amount to bet.",
)
async def dice(
    interaction: discord.Interaction,
    amount: str,
):

    value = normalize_amount(
        amount
    )

    if value is None or value < MIN_BET:

        await interaction.response.send_message(
            "Minimum bet is **$0.10**.",
            ephemeral=False,
        )

        return

    balance_value = await bot.get_balance(
        interaction.user.id
    )

    if value > balance_value:

        await interaction.response.send_message(
            "You Dont Have Enough Crypto",
            ephemeral=False,
        )

        return

    await interaction.response.send_message(
        content=(
            "**Choose Dice Mode**\n\n"
            "**Crazy Dice**\n"
            "Lowest Wins\n\n"
            "**Dice**\n"
            "Highest Wins"
        ),
        view=DiceSetupView(
            bot,
            interaction.user.id,
            value,
        ),
    )


# ============================================================
# DICE GAME
# ============================================================

async def _start_dice_game(
    self,
    interaction: discord.Interaction,
    user_id: int,
    amount: Decimal,
    mode: str,
    dice_count: int,
):

    success = await self.deduct_bet(
        user_id,
        amount,
        "dice",
    )

    if not success:

        await interaction.edit_original_response(
            content="You Dont Have Enough Crypto",
            view=None,
        )

        return

    game_id = self.next_game_id()

    server_seed = self.create_server_seed()
    server_hash = self.server_hash(
        server_seed
    )

    client_seed = self.create_client_seed(
        user_id
    )

    nonce = 0

    self.active_dice[user_id] = {
        "user_id": user_id,
        "amount": amount,
        "mode": mode,
        "dice_count": dice_count,
        "game_id": game_id,
        "server_seed": server_seed,
        "server_hash": server_hash,
        "client_seed": client_seed,
        "nonce": nonce,
        "player_rolls": [],
        "bot_rolls": [],
        "message_id": None,
        "channel_id": interaction.channel.id,
    }

    mode_name = (
        "Crazy"
        if mode == "crazy"
        else "Normal"
    )

    await interaction.edit_original_response(
        content=(
            f"## Dice - /roll to proceed\n\n"
            f"Mode: **{dice_count} Rolls "
            f"({mode_name})** · "
            f"Bet: **{money(amount)}**\n"
            f"{interaction.user.mention} vs Bot\n\n"
            f"{interaction.user.display_name}: "
            + " + ".join("?" for _ in range(dice_count))
            + " = ?\n"
            f"Bot: "
            + " + ".join("?" for _ in range(dice_count))
            + " = ?\n\n"
            f"Game #{game_id} · Provably fair.\n"
            f"Server hash: `{server_hash}`"
        ),
        view=None,
    )


CasinoBot.start_dice_game = _start_dice_game


@bot.tree.command(
    name="roll",
    description="Roll your active Dice game.",
)
async def roll(
    interaction: discord.Interaction,
):

    game = bot.active_dice.get(
        interaction.user.id
    )

    if not game:

        await interaction.response.send_message(
            "You don't have an active Dice game.",
            ephemeral=False,
        )

        return

    if len(
        game["player_rolls"]
    ) >= game["dice_count"]:

        await interaction.response.send_message(
            "You have already rolled all your dice.",
            ephemeral=False,
        )

        return

    index = len(
        game["player_rolls"]
    )

    player_roll = bot.fair_int(
        game["server_seed"],
        game["client_seed"],
        game["nonce"] + index,
        1,
        6,
        "dice-player",
    )

    game["player_rolls"].append(
        player_roll
    )

    if len(
        game["player_rolls"]
    ) < game["dice_count"]:

        player_text = " + ".join(
            str(x)
            for x in game["player_rolls"]
        )

        player_text += " + ?"

        await interaction.response.send_message(
            f"🎲 You rolled **{player_roll}**\n"
            f"Current total: **{sum(game['player_rolls'])}**"
        )

        return

    game["bot_rolls"] = [
        bot.fair_int(
            game["server_seed"],
            game["client_seed"],
            game["nonce"] + 100 + i,
            1,
            6,
            "dice-bot",
        )
        for i in range(
            game["dice_count"]
        )
    ]

    player_total = sum(
        game["player_rolls"]
    )

    bot_total = sum(
        game["bot_rolls"]
    )

    if game["mode"] == "crazy":

        player_wins = (
            player_total < bot_total
        )

    else:

        player_wins = (
            player_total > bot_total
        )

    if player_total == bot_total:
        result = "Push"
    elif player_wins:
        result = "Win"
    else:
        result = "Loss"

    if result == "Win":

        payout = (
            game["amount"]
            * DICE_MULTIPLIER
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_DOWN,
        )

        await bot.settle_win(
            game["user_id"],
            game["amount"],
            payout,
            "dice",
        )

    elif result == "Loss":

        payout = Decimal("0")

        await bot.settle_loss(
            game["user_id"],
            game["amount"],
            "dice",
        )

    else:

        payout = game["amount"]

        await bot.db.change_balance(
            game["user_id"],
            game["amount"],
            kind="game_push",
            note="dice",
        )

        await bot.db.record_game(
            game["user_id"],
            game["amount"],
            Decimal("0"),
            "dice_push",
        )

    player_values = " + ".join(
        str(x)
        for x in game["player_rolls"]
    )

    bot_values = " + ".join(
        str(x)
        for x in game["bot_rolls"]
    )

    if result == "Win":
        color = 0x57F287
    elif result == "Loss":
        color = 0xED4245
    else:
        color = 0xFEE75C

    await interaction.response.send_message(
        embed=base_embed(
            title=f"Dice — {result}!",
            description=(
                f"**{interaction.user.display_name}:** "
                f"{player_values} = **{player_total}**\n"
                f"**Bot:** "
                f"{bot_values} = **{bot_total}**\n\n"
                f"**Bet:** {money(game['amount'])}\n"
                f"**Payout:** {money(payout)}\n\n"
                f"Game #{game['game_id']}\n"
                f"Server hash: `{game['server_hash']}`\n"
                f"Client seed: `{game['client_seed']}`\n"
                f"Nonce: `{game['nonce']}`"
            ),
            color=color,
        )
    )

    bot.active_dice.pop(
        interaction.user.id,
        None,
    )





# ============================================================
# /MINES
# ============================================================



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
            ephemeral=False,
        )

        return

    if index in game.opened:

        await interaction.response.send_message(
            "That tile is already open.",
            ephemeral=False,
        )

        return

    game.opened.add(
        index
    )

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

                elif tile_index in game.opened:
                    item.label = "💎"

        await self.settle_loss(
            game.user_id,
            game.amount,
            "mines",
        )

        await interaction.response.edit_message(
            content=(
                "## Mines — Boom!\n\n"
                f"Bet: **{money(game.amount)}**\n"
                f"Lost: **{money(game.amount)}**\n\n"
                f"Game #{game.game_id}"
            ),
            view=view,
        )

        self.active_mines.pop(
            game.user_id,
            None,
        )

        return

    if button:

        button.label = "💎"
        button.style = (
            discord.ButtonStyle.success
        )
        button.disabled = True

    if len(game.opened) >= (
        24 - game.mines
    ):

        game.finished = True

        payout = game.payout

        await self.settle_win(
            game.user_id,
            game.amount,
            payout,
            "mines",
        )

        for item in view.children:
            item.disabled = True

        await interaction.response.edit_message(
            content=(
                "## Mines — Cleared!\n\n"
                f"Bet: **{money(game.amount)}**\n"
                f"Multiplier: **{game.multiplier:.2f}x**\n"
                f"Payout: **{money(payout)}**"
            ),
            view=view,
        )

        self.active_mines.pop(
            game.user_id,
            None,
        )

        return

    await interaction.response.edit_message(
        content=(
            "## Mines\n\n"
            f"Bet: **{money(game.amount)}**\n"
            f"Opened: **{len(game.opened)}**\n"
            f"Multiplier: **{game.multiplier:.2f}x**\n"
            f"Cashout: **{money(game.payout)}**"
        ),
        view=view,
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
            ephemeral=False,
        )

        return

    if not game.opened:

        await interaction.response.send_message(
            "Open at least one tile before cashing out.",
            ephemeral=False,
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

    for item in view.children:
        item.disabled = True

    await interaction.response.edit_message(
        content=(
            "## Mines — Cashed Out\n\n"
            f"Bet: **{money(game.amount)}**\n"
            f"Opened: **{len(game.opened)}**\n"
            f"Multiplier: **{game.multiplier:.2f}x**\n"
            f"Payout: **{money(payout)}**"
        ),
        view=view,
    )

    self.active_mines.pop(
        game.user_id,
        None,
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


def blackjack_deck() -> list[str]:
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

    random.shuffle(cards)

    return cards


def card_path(card: str) -> Path:
    return BASE_DIR / f"{card}.png"


def _fit_blackjack_card(
    image: Image.Image,
    max_width: int = 210,
    max_height: int = 300,
) -> Image.Image:

    image = image.convert("RGBA")

    ratio = min(
        max_width / image.width,
        max_height / image.height,
    )

    new_size = (
        max(1, int(image.width * ratio)),
        max(1, int(image.height * ratio)),
    )

    return image.resize(
        new_size,
        Image.Resampling.LANCZOS,
    )


def _create_blackjack_card_back(
    width: int,
    height: int,
) -> Image.Image:

    card = Image.new(
        "RGBA",
        (width, height),
        (15, 45, 30, 255),
    )

    draw = ImageDraw.Draw(card)

    # Outer border
    draw.rounded_rectangle(
        (
            0,
            0,
            width - 1,
            height - 1,
        ),
        radius=14,
        fill=(235, 235, 235, 255),
    )

    # Inner card
    draw.rounded_rectangle(
        (
            7,
            7,
            width - 8,
            height - 8,
        ),
        radius=10,
        fill=(30, 80, 55, 255),
        outline=(10, 35, 25, 255),
        width=4,
    )

    # Diamond pattern
    spacing = 28

    for y in range(
        18,
        height - 18,
        spacing,
    ):

        for x in range(
            18,
            width - 18,
            spacing,
        ):

            cx = x
            cy = y

            draw.polygon(
                [
                    (cx, cy - 8),
                    (cx + 8, cy),
                    (cx, cy + 8),
                    (cx - 8, cy),
                ],
                fill=(45, 110, 75, 255),
            )

    return card


def create_blackjack_image(
    player_cards: list[str],
    dealer_cards: list[str],
    hidden: bool = True,
) -> Optional[discord.File]:

    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None

    # --------------------------------------------------------
    # GREEN CASINO TABLE
    # --------------------------------------------------------

    CARD_WIDTH = 190
    CARD_HEIGHT = 275

    TABLE_WIDTH = 1100
    TABLE_HEIGHT = 650

    canvas = Image.new(
        "RGBA",
        (
            TABLE_WIDTH,
            TABLE_HEIGHT,
        ),
        (18, 105, 63, 255),
    )

    draw = ImageDraw.Draw(canvas)

    # Dark outer table border
    draw.rounded_rectangle(
        (
            8,
            8,
            TABLE_WIDTH - 8,
            TABLE_HEIGHT - 8,
        ),
        radius=28,
        fill=(10, 55, 35, 255),
    )

    # Green felt
    draw.rounded_rectangle(
        (
            18,
            18,
            TABLE_WIDTH - 18,
            TABLE_HEIGHT - 18,
        ),
        radius=22,
        fill=(20, 125, 75, 255),
    )

    # Subtle inner felt border
    draw.rounded_rectangle(
        (
            32,
            32,
            TABLE_WIDTH - 32,
            TABLE_HEIGHT - 32,
        ),
        radius=18,
        outline=(65, 160, 105, 255),
        width=3,
    )

    # --------------------------------------------------------
    # LOAD PLAYER CARDS
    # --------------------------------------------------------

    player_images = []

    for card in player_cards:

        if card == "hidden":
            continue

        path = card_path(card)

        if not path.exists():
            continue

        try:
            image = Image.open(path).convert("RGBA")

            image = _fit_blackjack_card(
                image,
                CARD_WIDTH,
                CARD_HEIGHT,
            )

            player_images.append(image)

        except Exception:
            continue

    # --------------------------------------------------------
    # LOAD DEALER CARDS
    # --------------------------------------------------------

    dealer_images = []

    for index, card in enumerate(dealer_cards):

        if card == "hidden":
            if hidden:

                dealer_images.append(
                    _create_blackjack_card_back(
                        CARD_WIDTH,
                        CARD_HEIGHT,
                    )
                )

            continue

        path = card_path(card)

        if not path.exists():
            continue

        try:
            image = Image.open(path).convert("RGBA")

            image = _fit_blackjack_card(
                image,
                CARD_WIDTH,
                CARD_HEIGHT,
            )

            dealer_images.append(image)

        except Exception:
            continue

    if not player_images and not dealer_images:
        return None

    # --------------------------------------------------------
    # CARD PLACEMENT
    # --------------------------------------------------------

    def place_cards(
        images: list[Image.Image],
        y: int,
    ):

        if not images:
            return

        spacing = 18

        total_width = (
            sum(image.width for image in images)
            + spacing * (len(images) - 1)
        )

        start_x = (
            TABLE_WIDTH - total_width
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
                    5,
                    7,
                    image.width - 1,
                    image.height - 1,
                ),
                radius=10,
                fill=(0, 0, 0, 80),
            )

            canvas.alpha_composite(
                shadow,
                (
                    x + 4,
                    y + 7,
                ),
            )

            canvas.alpha_composite(
                image,
                (
                    x,
                    y,
                ),
            )

            x += image.width + spacing

    # Dealer cards at top
    place_cards(
        dealer_images,
        55,
    )

    # Player cards at bottom
    place_cards(
        player_images,
        TABLE_HEIGHT - CARD_HEIGHT - 55,
    )

    # --------------------------------------------------------
    # CENTER DIVIDER
    # --------------------------------------------------------

    center_y = TABLE_HEIGHT // 2

    draw.line(
        (
            110,
            center_y,
            TABLE_WIDTH - 110,
            center_y,
        ),
        fill=(100, 180, 130, 110),
        width=2,
    )

    # --------------------------------------------------------
    # EXPORT
    # --------------------------------------------------------

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


class BlackjackView(ButtonView):

    def __init__(
        self,
        bot_instance: CasinoBot,
        user_id: int,
        game: dict,
    ):

        super().__init__(
            timeout=3600
        )

        self.bot = bot_instance
        self.user_id = user_id
        self.game = game

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:

        if interaction.user.id != self.user_id:

            await interaction.response.send_message(
                embed=base_embed(
                    title="Blackjack",
                    description=(
                        "This Blackjack game belongs "
                        "to another player."
                    ),
                    color=0xED4245,
                ),
            )

            return False

        return True

    @discord.ui.button(
        label="Hit",
        style=discord.ButtonStyle.primary,
    )
    async def hit(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await self.bot.blackjack_hit(
            interaction,
            self,
        )

    @discord.ui.button(
        label="Stand",
        style=discord.ButtonStyle.success,
    )
    async def stand(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await self.bot.blackjack_stand(
            interaction,
            self,
        )

    @discord.ui.button(
        label="Double",
        style=discord.ButtonStyle.secondary,
    )
    async def double(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await self.bot.blackjack_double(
            interaction,
            self,
        )


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

    elif result == "push":

        payout = game["bet"]

        await self.db.change_balance(
            game["user_id"],
            payout,
            kind="blackjack_push",
            note="blackjack",
        )

        await self.db.record_game(
            game["user_id"],
            game["bet"],
            Decimal("0"),
            "blackjack_push",
        )

        title = "Blackjack — Push"
        color = 0xFEE75C

    else:

        payout = Decimal("0")

        await self.settle_loss(
            game["user_id"],
            game["bet"],
            "blackjack",
        )

        title = "Blackjack — Lost"
        color = 0xED4245

    view.clear_items()

    file = create_blackjack_image(
        game["player"],
        game["dealer"],
        hidden=False,
    )

    embed = base_embed(
        title=title,
        description=(
            f"**Blackjack**\n\n"
            f"Bet: **{money(game['bet'])}**\n"
            f"Result: **{title.split('—')[-1].strip()}**\n\n"
            f"Player: **{player_total}**\n"
            f"Dealer: **{dealer_total}**\n\n"
            f"Game #{game['game_id']}\n"
            f"Server hash: `{game['server_hash']}`\n"
            f"Client seed: `{game['client_seed']}`\n"
            f"Nonce: `{game['nonce']}`"
        ),
        color=color,
    )

    # IMPORTANT:
    # edit_message DOES NOT accept file=
    # It must use attachments=[file].

    if file:

        embed.set_image(
            url="attachment://blackjack.png"
        )

        await interaction.response.edit_message(
            embed=embed,
            view=view,
            attachments=[file],
        )

    else:

        await interaction.response.edit_message(
            embed=embed,
            view=view,
            attachments=[],
        )

    self.active_games.pop(
        game["user_id"],
        None,
    )


CasinoBot.blackjack_finish = _blackjack_finish


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

    if total > 21:

        await self.blackjack_finish(
            interaction,
            view,
            "loss",
        )

        return

    file = create_blackjack_image(
        game["player"],
        game["dealer"],
        hidden=True,
    )

    embed = base_embed(
        title="Blackjack",
        description=(
            f"Player total: **{total}**\n"
            f"Dealer: **?**\n\n"
            "Choose **Hit**, **Stand**, or **Double**."
        ),
    )

    if file:

        embed.set_image(
            url="attachment://blackjack.png"
        )

        await interaction.response.edit_message(
            embed=embed,
            view=view,
            attachments=[file],
        )

    else:

        await interaction.response.edit_message(
            embed=embed,
            view=view,
            attachments=[],
        )


CasinoBot.blackjack_hit = _blackjack_hit


async def _blackjack_stand(
    self,
    interaction: discord.Interaction,
    view: BlackjackView,
):

    game = view.game

    if game["finished"]:
        return

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


async def _blackjack_double(
    self,
    interaction: discord.Interaction,
    view: BlackjackView,
):

    game = view.game

    if game["finished"]:
        return

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

    game["bet"] += extra_bet

    game["player"].append(
        game["deck"].pop()
    )

    if blackjack_hand_total(
        game["player"]
    ) > 21:

        await self.blackjack_finish(
            interaction,
            view,
            "loss",
        )

        return

    await self.blackjack_stand(
        interaction,
        view,
    )


CasinoBot.blackjack_double = _blackjack_double


@bot.tree.command(
    name="blackjack",
    description="Play Blackjack.",
)
@app_commands.describe(
    amount="Blackjack bet.",
    side_21_3="21+3 side bet.",
    pairs="Perfect Pairs side bet.",
)
async def blackjack(
    interaction: discord.Interaction,
    amount: str,
    side_21_3: Optional[str] = None,
    pairs: Optional[str] = None,
):

    value = normalize_amount(
        amount
    )

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

    deck = blackjack_deck()

    player = [
        deck.pop(),
        deck.pop(),
    ]

    dealer = [
        deck.pop(),
        "hidden",
    ]

    server_seed = bot.create_server_seed()

    game = {
        "user_id": interaction.user.id,
        "bet": value,
        "deck": deck,
        "player": player,
        "dealer": dealer,
        "game_id": bot.next_game_id(),
        "server_seed": server_seed,
        "server_hash": bot.server_hash(
            server_seed
        ),
        "client_seed": bot.create_client_seed(
            interaction.user.id
        ),
        "nonce": 0,
        "finished": False,
        "side_21_3": (
            normalize_amount(side_21_3)
            if side_21_3
            else Decimal("0")
        ),
        "pairs": (
            normalize_amount(pairs)
            if pairs
            else Decimal("0")
        ),
    }

    bot.active_games[
        interaction.user.id
    ] = game

    view = BlackjackView(
        bot,
        interaction.user.id,
        game,
    )

    file = create_blackjack_image(
        player,
        dealer,
        hidden=True,
    )

    embed = base_embed(
        title="Blackjack",
        description=(
            f"Bet: **{money(value)}**\n"
            f"Player: **{blackjack_hand_total(player)}**\n"
            f"Dealer: **?**\n\n"
            f"Game #{game['game_id']}\n"
            f"Server hash: `{game['server_hash']}`"
        ),
    )

    if file:

        embed.set_image(
            url="attachment://blackjack.png"
        )

        await interaction.response.send_message(
            embed=embed,
            view=view,
            file=file,
        )

    else:

        await interaction.response.send_message(
            embed=embed,
            view=view,
        )


bot.tree.add_command(
    app_commands.Command(
        name="bj",
        description="Play Blackjack.",
        callback=blackjack.callback,
    )
)

# ============================================================
# /HOUSEBAL
# ============================================================

HOUSE_BALANCE = "$48.50"
HOUSE_LTC = "$0.00"
HOUSE_SOL = "$38.29"
HOUSE_USDT = "$10.21"


class HouseBalanceView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Add Funds",
        style=discord.ButtonStyle.success,
        custom_id="house_add_funds",
    )
    async def add_funds(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await interaction.response.send_message(
            embed=house_add_funds_embed(),
            ephemeral=False,
        )


@bot.tree.command(
    name="housebal",
    description="View the current house balance.",
)
async def housebal(
    interaction: discord.Interaction,
):
    embed = base_embed(
        title="## CryptoBet — House",
        description=(
            "> .live reserves & player-fund held\n\n"
            f"> .house balance · **`{HOUSE_BALANCE}`** ·\n"
            f"> .LTC · **`{HOUSE_LTC}`**\n"
            f"> .SOL · **`{HOUSE_SOL}`**\n"
            f"> .USDT · **`{HOUSE_USDT}`**"
        ),
    )

    await interaction.response.send_message(
        embed=embed,
        view=HouseBalanceView(),
    )

# ============================================================
# HOUSE ADD FUNDS EMBED
# ============================================================

def house_add_funds_embed():
    return base_embed(
        title="Housebalance Credit",
        description=(
            "<:ltc:1550062603693457430> "
            "`ltc1qcq2l6h5r0drx0hsg3796rk0phdtmq2fmjhh80s`\n\n"
            "<:Solana:1550062641081356348> "
            "`Cannot Generate an Deposit address Message Owner for Manual Deposit`\n\n"
            "<:usdt:1550062695380819978> "
            "`Cannot Generate an Deposit address Message Owner for Manual Deposit`"
        ),
    )


# ============================================================
# /HOUSEADDFUND
# ============================================================

@bot.tree.command(
    name="houseaddfund",
    description="View house deposit addresses.",
)
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

@bot.tree.command(
    name="ranksetup",
    description="Create/update casino rank roles.",
)
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
# COMMAND ERROR HANDLER
# ============================================================

@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
):

    print(
        f"[APP COMMAND ERROR] "
        f"{interaction.command}: {error}"
    )

    if isinstance(
        error,
        app_commands.CheckFailure,
    ):

        await bot.safe_send(
            interaction,
            content="You do not have permission to use this command.",
            ephemeral=False,
        )

        return

    if isinstance(
        error,
        app_commands.TransformerError,
    ):

        await bot.safe_send(
            interaction,
            content="One of the supplied values is invalid.",
            ephemeral=False,
        )

        return

    await bot.safe_send(
        interaction,
        embed=error_embed(
            "Something went wrong",
            "Please try again.",
        ),
        ephemeral=False,
    )


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
