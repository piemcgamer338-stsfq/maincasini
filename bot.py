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
        self.active_cases: dict[int, "CaseGame"] = {}
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
        race_amount=None,
    ):

        await self.db.record_game(
            user_id,
            bet,
            payout,
            game,
            race_amount=race_amount,
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
        race_amount=None,
    ):

        await self.db.record_game(
            user_id,
            bet,
            Decimal("0"),
            game,
            race_amount=race_amount,
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
# BOT INSTANCE
# ============================================================

bot = CasinoBot()


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
# BALANCE IMAGE
# ============================================================

def create_balance_image(
    user: discord.User | discord.Member,
    balance,
) -> Optional[discord.File]:

    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None

    # ========================================================
    # CANVAS
    # Same dark background used by Blackjack
    # ========================================================

    WIDTH = 1600
    HEIGHT = 600

    BACKGROUND = (35, 36, 38, 255)

    WHITE = (245, 245, 245, 255)

    GREY = (165, 165, 165, 255)

    YELLOW = (255, 205, 0, 255)

    DARK_BORDER = (15, 16, 18, 255)

    canvas = Image.new(
        "RGBA",
        (WIDTH, HEIGHT),
        BACKGROUND,
    )

    draw = ImageDraw.Draw(canvas)

    # ========================================================
    # FONT
    # ========================================================

    def load_font(
        size: int,
        bold: bool = False,
    ):

        if bold:

            paths = [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
            ]

        else:

            paths = [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
            ]

        for path in paths:

            try:

                return ImageFont.truetype(
                    path,
                    size,
                )

            except Exception:
                pass

        return ImageFont.load_default()

    name_font = load_font(
        70,
        True,
    )

    username_font = load_font(
        52,
        False,
    )

    balance_font = load_font(
        120,
        True,
    )

    brand_font = load_font(
        48,
        True,
    )

    # ========================================================
    # BORDER
    # ========================================================

    draw.rounded_rectangle(
        (
            18,
            18,
            WIDTH - 18,
            HEIGHT - 18,
        ),
        radius=40,
        fill=BACKGROUND,
        outline=DARK_BORDER,
        width=8,
    )

    # ========================================================
    # AVATAR
    # ========================================================

    avatar_size = 270

    avatar_x = 55
    avatar_y = 72

    try:

        avatar_url = str(
            user.display_avatar.with_size(
                256
            ).url
        )

        # Use the bot's existing aiohttp session.
        # This avoids needing another HTTP library.
        import asyncio

        async def download_avatar():

            try:

                async with bot.http_session.get(
                    avatar_url
                ) as response:

                    if response.status != 200:
                        return None

                    return await response.read()

            except Exception:

                return None

        # This function is synchronous, so run the
        # download in the existing event loop safely.
        # The actual avatar is handled below by the
        # asynchronous wrapper if available.

    except Exception:

        avatar_url = None

    # ========================================================
    # AVATAR PLACEHOLDER
    # ========================================================

    # We initially draw a simple circle.
    # The async balance function below replaces it
    # with the real Discord avatar.
    draw.ellipse(
        (
            avatar_x,
            avatar_y,
            avatar_x + avatar_size,
            avatar_y + avatar_size,
        ),
        fill=(55, 56, 59, 255),
        outline=YELLOW,
        width=8,
    )

    # ========================================================
    # USER TEXT
    # ========================================================

    name = user.display_name

    username = (
        f"@{user.name}"
    )

    # Name
    draw.text(
        (
            335,
            105,
        ),
        name,
        font=name_font,
        fill=WHITE,
    )

    # Username
    draw.text(
        (
            335,
            200,
        ),
        username,
        font=username_font,
        fill=GREY,
    )

    # ========================================================
    # BALANCE
    # ========================================================

    balance_text = money(
        balance
    )

    draw.text(
        (
            335,
            295,
        ),
        balance_text,
        font=balance_font,
        fill=YELLOW,
    )

    # ========================================================
    # CRYPTOBET BRAND
    # ========================================================

    brand = "CryptoBet"

    brand_bbox = draw.textbbox(
        (0, 0),
        brand,
        font=brand_font,
    )

    brand_width = (
        brand_bbox[2]
        - brand_bbox[0]
    )

    draw.text(
        (
            WIDTH - brand_width - 65,
            90,
        ),
        brand,
        font=brand_font,
        fill=YELLOW,
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
        filename="balance.png",
    )


# ============================================================
# ASYNC BALANCE IMAGE WITH REAL DISCORD AVATAR
# ============================================================

async def create_balance_image_async(
    user: discord.User | discord.Member,
    balance,
) -> Optional[discord.File]:

    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None

    WIDTH = 1600
    HEIGHT = 600

    BACKGROUND = (35, 36, 38, 255)

    WHITE = (245, 245, 245, 255)

    GREY = (165, 165, 165, 255)

    YELLOW = (255, 205, 0, 255)

    DARK_BORDER = (15, 16, 18, 255)

    canvas = Image.new(
        "RGBA",
        (
            WIDTH,
            HEIGHT,
        ),
        BACKGROUND,
    )

    draw = ImageDraw.Draw(
        canvas
    )

    # ========================================================
    # FONTS
    # ========================================================

    def load_font(
        size: int,
        bold: bool = False,
    ):

        if bold:

            paths = [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
            ]

        else:

            paths = [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
            ]

        for path in paths:

            try:

                return ImageFont.truetype(
                    path,
                    size,
                )

            except Exception:
                continue

        return ImageFont.load_default()

    name_font = load_font(
        70,
        True,
    )

    username_font = load_font(
        52,
        False,
    )

    balance_font = load_font(
        120,
        True,
    )

    brand_font = load_font(
        48,
        True,
    )

    # ========================================================
    # BORDER
    # ========================================================

    draw.rounded_rectangle(
        (
            18,
            18,
            WIDTH - 18,
            HEIGHT - 18,
        ),
        radius=40,
        fill=BACKGROUND,
        outline=DARK_BORDER,
        width=8,
    )

    # ========================================================
    # AVATAR
    # ========================================================

    avatar_size = 270

    avatar_x = 55
    avatar_y = 72

    avatar_data = None

    try:

        avatar_url = str(
            user.display_avatar.with_size(
                256
            ).url
        )

        async with bot.http_session.get(
            avatar_url
        ) as response:

            if response.status == 200:

                avatar_data = await response.read()

    except Exception as exc:

        print(
            f"[BALANCE IMAGE] Avatar error: {exc}"
        )

    if avatar_data:

        try:

            avatar = Image.open(
                io.BytesIO(
                    avatar_data
                )
            ).convert("RGBA")

            avatar = avatar.resize(
                (
                    avatar_size,
                    avatar_size,
                ),
                Image.Resampling.LANCZOS,
            )

            # Circular mask
            mask = Image.new(
                "L",
                (
                    avatar_size,
                    avatar_size,
                ),
                0,
            )

            mask_draw = ImageDraw.Draw(
                mask
            )

            mask_draw.ellipse(
                (
                    0,
                    0,
                    avatar_size,
                    avatar_size,
                ),
                fill=255,
            )

            # Avatar border
            draw.ellipse(
                (
                    avatar_x - 7,
                    avatar_y - 7,
                    avatar_x + avatar_size + 7,
                    avatar_y + avatar_size + 7,
                ),
                fill=YELLOW,
            )

            canvas.paste(
                avatar,
                (
                    avatar_x,
                    avatar_y,
                ),
                mask,
            )

        except Exception as exc:

            print(
                f"[BALANCE IMAGE] Avatar processing error: {exc}"
            )

            draw.ellipse(
                (
                    avatar_x,
                    avatar_y,
                    avatar_x + avatar_size,
                    avatar_y + avatar_size,
                ),
                fill=(55, 56, 59, 255),
                outline=YELLOW,
                width=8,
            )

    else:

        draw.ellipse(
            (
                avatar_x,
                avatar_y,
                avatar_x + avatar_size,
                avatar_y + avatar_size,
            ),
            fill=(55, 56, 59, 255),
            outline=YELLOW,
            width=8,
        )

    # ========================================================
    # USERNAME
    # ========================================================

    name = user.display_name

    username = (
        f"@{user.name}"
    )

    # ========================================================
    # NAME
    # ========================================================

    draw.text(
        (
            335,
            105,
        ),
        name,
        font=name_font,
        fill=WHITE,
    )

    # ========================================================
    # USERNAME
    # ========================================================

    draw.text(
        (
            335,
            200,
        ),
        username,
        font=username_font,
        fill=GREY,
    )

    # ========================================================
    # BALANCE
    # ========================================================

    balance_text = money(
        balance
    )

    draw.text(
        (
            335,
            295,
        ),
        balance_text,
        font=balance_font,
        fill=YELLOW,
    )

    # ========================================================
    # CRYPTOBET
    # ========================================================

    brand = "CryptoBet"

    brand_bbox = draw.textbbox(
        (0, 0),
        brand,
        font=brand_font,
    )

    brand_width = (
        brand_bbox[2]
        - brand_bbox[0]
    )

    draw.text(
        (
            WIDTH - brand_width - 65,
            90,
        ),
        brand,
        font=brand_font,
        fill=YELLOW,
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
        filename="balance.png",
    )


# ============================================================
# BALANCE IMAGE
# ============================================================

def create_balance_font(
    size: int,
    bold: bool = False,
):
    """
    Load a real scalable TTF font.
    Searches common Linux font locations so Railway
    does not fall back to Pillow's tiny default font.
    """

    font_candidates = []

    if bold:
        font_candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        ]
    else:
        font_candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        ]

    # Try known paths first
    for font_path in font_candidates:

        try:

            if Path(font_path).exists():

                return ImageFont.truetype(
                    font_path,
                    size,
                )

        except Exception:
            pass

    # Search system fonts as a fallback
    try:

        font_root = Path(
            "/usr/share/fonts"
        )

        if font_root.exists():

            all_fonts = list(
                font_root.rglob("*.ttf")
            )

            if bold:

                preferred = [
                    p
                    for p in all_fonts
                    if "bold" in p.name.lower()
                ]

            else:

                preferred = [
                    p
                    for p in all_fonts
                    if "bold" not in p.name.lower()
                ]

            search_fonts = (
                preferred
                if preferred
                else all_fonts
            )

            for font_path in search_fonts:

                try:

                    return ImageFont.truetype(
                        str(font_path),
                        size,
                    )

                except Exception:
                    continue

    except Exception:
        pass

    # Pillow versions with scalable default font support
    try:

        return ImageFont.load_default(
            size=size
        )

    except Exception:

        return ImageFont.load_default()


# ============================================================
# CREATE BALANCE IMAGE
# ============================================================

async def create_balance_image(
    user: discord.User | discord.Member,
    balance,
) -> Optional[discord.File]:

    try:

        from PIL import (
            Image,
            ImageDraw,
            ImageFont,
        )

    except ImportError:

        return None

    # ========================================================
    # SIZE
    # ========================================================

    WIDTH = 1600
    HEIGHT = 600

    # Same dark background as Blackjack
    BACKGROUND = (
        35,
        36,
        38,
        255,
    )

    WHITE = (
        245,
        245,
        245,
        255,
    )

    GREY = (
        165,
        165,
        165,
        255,
    )

    YELLOW = (
        255,
        205,
        0,
        255,
    )

    BORDER = (
        15,
        16,
        18,
        255,
    )

    # ========================================================
    # CANVAS
    # ========================================================

    canvas = Image.new(
        "RGBA",
        (
            WIDTH,
            HEIGHT,
        ),
        BACKGROUND,
    )

    draw = ImageDraw.Draw(
        canvas
    )

    # ========================================================
    # FONTS
    # ========================================================

    name_font = create_balance_font(
        76,
        True,
    )

    username_font = create_balance_font(
        48,
        False,
    )

    balance_font = create_balance_font(
        125,
        True,
    )

    brand_font = create_balance_font(
        46,
        True,
    )

    # ========================================================
    # OUTER BORDER
    # ========================================================

    draw.rounded_rectangle(
        (
            18,
            18,
            WIDTH - 18,
            HEIGHT - 18,
        ),
        radius=42,
        fill=BACKGROUND,
        outline=BORDER,
        width=8,
    )

    # ========================================================
    # AVATAR SETTINGS
    # ========================================================

    avatar_size = 270

    avatar_x = 55
    avatar_y = 70

    # ========================================================
    # DOWNLOAD DISCORD AVATAR
    # ========================================================

    avatar_data = None

    try:

        avatar_url = str(
            user.display_avatar.with_size(
                256
            ).url
        )

        async with bot.http_session.get(
            avatar_url
        ) as response:

            if response.status == 200:

                avatar_data = (
                    await response.read()
                )

    except Exception as exc:

        print(
            f"[BALANCE] Avatar download failed: {exc}"
        )

    # ========================================================
    # DRAW AVATAR
    # ========================================================

    if avatar_data:

        try:

            avatar = Image.open(
                io.BytesIO(
                    avatar_data
                )
            ).convert(
                "RGBA"
            )

            avatar = avatar.resize(
                (
                    avatar_size,
                    avatar_size,
                ),
                Image.Resampling.LANCZOS,
            )

            # -----------------------------------------------
            # Circular mask
            # -----------------------------------------------

            mask = Image.new(
                "L",
                (
                    avatar_size,
                    avatar_size,
                ),
                0,
            )

            mask_draw = ImageDraw.Draw(
                mask
            )

            mask_draw.ellipse(
                (
                    0,
                    0,
                    avatar_size,
                    avatar_size,
                ),
                fill=255,
            )

            # -----------------------------------------------
            # Yellow outer ring
            # -----------------------------------------------

            draw.ellipse(
                (
                    avatar_x - 8,
                    avatar_y - 8,
                    avatar_x + avatar_size + 8,
                    avatar_y + avatar_size + 8,
                ),
                fill=YELLOW,
            )

            # -----------------------------------------------
            # Avatar
            # -----------------------------------------------

            canvas.paste(
                avatar,
                (
                    avatar_x,
                    avatar_y,
                ),
                mask,
            )

        except Exception as exc:

            print(
                f"[BALANCE] Avatar processing failed: {exc}"
            )

            draw.ellipse(
                (
                    avatar_x,
                    avatar_y,
                    avatar_x + avatar_size,
                    avatar_y + avatar_size,
                ),
                fill=(
                    55,
                    56,
                    59,
                    255,
                ),
                outline=YELLOW,
                width=8,
            )

    else:

        draw.ellipse(
            (
                avatar_x,
                avatar_y,
                avatar_x + avatar_size,
                avatar_y + avatar_size,
            ),
            fill=(
                55,
                56,
                59,
                255,
            ),
            outline=YELLOW,
            width=8,
        )

    # ========================================================
    # USER INFORMATION
    # ========================================================

    name = str(
        user.display_name
    )

    username = (
        f"@{user.name}"
    )

    # ========================================================
    # NAME
    # ========================================================

    draw.text(
        (
            335,
            90,
        ),
        name,
        font=name_font,
        fill=WHITE,
    )

    # ========================================================
    # USERNAME
    # ========================================================

    draw.text(
        (
            335,
            185,
        ),
        username,
        font=username_font,
        fill=GREY,
    )

    # ========================================================
    # BALANCE
    # ========================================================

    balance_text = money(
        balance
    )

    draw.text(
        (
            335,
            275,
        ),
        balance_text,
        font=balance_font,
        fill=YELLOW,
    )

    # ========================================================
    # CRYPTOBET
    # ========================================================

    brand = "CryptoBet"

    brand_bbox = draw.textbbox(
        (
            0,
            0,
        ),
        brand,
        font=brand_font,
    )

    brand_width = (
        brand_bbox[2]
        - brand_bbox[0]
    )

    draw.text(
        (
            WIDTH - brand_width - 60,
            75,
        ),
        brand,
        font=brand_font,
        fill=YELLOW,
    )

    # ========================================================
    # SAVE IMAGE
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
        filename="balance.png",
    )


# ============================================================
# /BALANCE
# ============================================================

@prefix_command(name="balance", aliases=["b"])
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
# /HELP
# ============================================================

HELP_GENERAL = (
    "## General\n"
    "`.help` — Show this help menu\n"
    "`.balance` — View your wallet\n"
    "`.deposit` — Deposit cryptocurrency\n"
    "`.withdraw` — Withdraw funds\n"
    "`.stats` — View your player statistics\n"
    "`.history` — View recent game history\n"
    "`.howtoplay` — Learn how to play\n"
    "`.rewardinfo` — View rewards and perks\n"
    "`.affiliateinfo` — View affiliate rates\n"
    "`.verify` — Verify a completed game"
)

HELP_GAMES = (
    "## Games\n"
    "`.dice` — Select a dice game\n"
    "`.roll` — Roll your dice\n"
    "`.coinflip` — Play Red or Blue coinflip\n"
    "`.mines` — Play Mines\n"
    "`.tower` — Play Tower\n"
    "`.roulette` — Play Roulette\n"
    "`.case` — Play Deal or No Deal\n"
    "`.limbo` — Play Limbo\n"
    "`.blackjack` — Play Blackjack\n"
    "`.frog-run` — Play Frog Run\n"
    "`.retrigger` — Retrigger an unfinished game\n"
    "`.fix-dice` — Recover a dice game"
)

HELP_REWARDS = (
    "## Rewards\n"
    "`.rakeback` — Claim available rakeback\n"
    "`.ranks` — View rank progression\n"
    "`.rank-rewards` — Claim rank rewards\n"
    "`.affiliates` — View your affiliates\n"
    "`.affiliate-claim` — Claim affiliate earnings\n"
    "`.claim` — Claim a promo code\n"
    "`.leaderboard` — View top wagerers\n"
    "`.race` — View the active wager race"
)

HELP_SOCIAL = (
    "## Social\n"
    "`.tip` — Tip another player\n"
    "`.rain` — Start a rain event\n"
    "`.private-channel` — Manage a private gaming channel"
)

HELP_ADMIN = (
    "## Admin\n"
    "`.ranksetup` — Configure rank roles\n"
    "`.code` — Create a promotional code\n"
    "`.race start` — Start a wager race\n"
    "`.race end` — End a wager race\n"
    "`.winlogs` — Set the win-log channel"
)


@prefix_command(name="help")
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
@prefix_command(name="fair", aliases=["verify"])
async def fair_command(
    interaction: discord.Interaction,
    server_hash: str,
):
    if not await require_database(interaction):
        return

    server_hash = server_hash.strip()

    if not server_hash:
        await interaction.response.send_message(
            embed=error_embed(
                "Invalid Server Hash",
                "Please provide a valid server hash."
            ),
            ephemeral=False,
        )
        return

    try:
        row = await bot.db.pool.fetchrow(
            """
            SELECT
                id,
                user_id,
                game,
                bet,
                payout,
                profit,
                result,
                game_id,
                server_hash,
                server_seed,
                client_seed,
                nonce,
                created_at
            FROM game_history
            WHERE server_hash = $1
            ORDER BY id DESC
            LIMIT 1
            """,
            server_hash,
        )

    except Exception as e:
        print(f"[FAIR ERROR] {type(e).__name__}: {e}")

        await interaction.response.send_message(
            embed=error_embed(
                "Fair Verification Error",
                "The game database could not be searched."
            ),
            ephemeral=False,
        )
        return

    if not row:
        await interaction.response.send_message(
            embed=error_embed(
                "Game Not Found",
                "No completed game was found with that server hash."
            ),
            ephemeral=False,
        )
        return

    game = str(row["game"] or "Unknown").lower()
    bet = Decimal(str(row["bet"] or 0))
    payout = Decimal(str(row["payout"] or 0))
    profit = Decimal(str(row["profit"] or 0))
    result = str(row["result"] or "Unknown")
    game_id = row["game_id"]
    stored_hash = row["server_hash"]
    server_seed = row["server_seed"]
    client_seed = row["client_seed"]
    nonce = row["nonce"]

    # ---------------------------------------------------------
    # WINNING CHANCE
    # ---------------------------------------------------------

    if game in ("coinflip", "coin flip", "cf"):
        chance_text = "50.00% per side"
    elif game == "limbo":
        # If result is stored as something like "4.64x",
        # calculate the probability of reaching that target.
        try:
            target_text = result.lower().replace("x", "").strip()
            target = Decimal(target_text)

            if target > 0:
                chance = (
                    Decimal("0.99") / target * Decimal("100")
                )

                if chance > 100:
                    chance = Decimal("100")

                chance_text = f"{chance.quantize(Decimal('0.01'))}%"
            else:
                chance_text = "Game-specific"
        except Exception:
            chance_text = "Game-specific"
    elif game in ("mines", "mine"):
        chance_text = "Depends on mines and tiles selected"
    elif game in ("blackjack", "bj"):
        chance_text = "Depends on the game state"
    else:
        chance_text = "Game-specific"

    # ---------------------------------------------------------
    # RESULT
    # ---------------------------------------------------------

    if payout > 0:
        result_status = "WIN"
    else:
        result_status = "LOSS"

    embed = discord.Embed(
        title="Provably Fair Verification",
        description=(
            f"**Game:** `{row['game']}`\n"
            f"**Result:** `{result}`\n"
            f"**Status:** **{result_status}**"
        ),
        color=discord.Color.gold(),
    )

    embed.add_field(
        name="Game Details",
        value=(
            f"**Bet:** `{money(bet)}`\n"
            f"**Payout:** `{money(payout)}`\n"
            f"**Profit:** `{money(profit)}`\n"
            f"**Winning Chance:** `{chance_text}`"
        ),
        inline=False,
    )

    embed.add_field(
        name="Fairness Data",
        value=(
            f"**Server Hash:** `{stored_hash}`\n"
            f"**Client Seed:** `{client_seed or 'N/A'}`\n"
            f"**Nonce:** `{nonce if nonce is not None else 'N/A'}`\n"
            f"**Game ID:** `{game_id if game_id is not None else row['id']}`"
        ),
        inline=False,
    )

    # Do NOT expose the server seed before your normal
    # seed-reveal system is supposed to reveal it.
    if server_seed:
        embed.add_field(
            name="Server Seed",
            value="`Hidden until seed reveal`",
            inline=False,
        )

    embed.set_footer(
        text="CryptoBet • Provably Fair"
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=False,
    )
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
# /WITHDRAW
# ============================================================

@prefix_command(name="withdraw")
async def withdraw_command(
    interaction: discord.Interaction,
    address: str,
    amount: str,
):

    # ========================================================
    # DATABASE
    # ========================================================

    if not await require_database(interaction):
        return

    user_id = interaction.user.id
    address = address.strip()

    # ========================================================
    # AMOUNT
    # ========================================================

    value = normalize_amount(amount)

    if value is None or value <= 0:

        await interaction.response.send_message(
            embed=error_embed(
                "Invalid Amount",
                "Enter a valid withdrawal amount.",
            ),
            ephemeral=False,
        )

        return

    # ========================================================
    # MINIMUM $0.50
    # ========================================================

    if value < Decimal("0.50"):

        await interaction.response.send_message(
            embed=error_embed(
                "Minimum Withdrawal",
                "The minimum withdrawal is **$0.50**.",
            ),
            ephemeral=False,
        )

        return

    # ========================================================
    # DETECT LTC
    # ========================================================

    is_ltc = (
        address.lower().startswith("ltc1")
        or (
            address.startswith(("L", "M", "m"))
            and 26 <= len(address) <= 35
        )
    )

    # ========================================================
    # DETECT SOL
    # ========================================================

    is_sol = (
        32 <= len(address) <= 44
        and not address.lower().startswith("ltc1")
    )

    # ========================================================
    # DETERMINE CURRENCY
    # ========================================================

    if is_ltc:

        currency = "LTC"

    elif is_sol:

        currency = "SOL"

    else:

        await interaction.response.send_message(
            embed=error_embed(
                "Invalid Address",
                (
                    "Please enter a valid **LTC** or **SOL** "
                    "withdrawal address."
                ),
            ),
            ephemeral=False,
        )

        return

    # ========================================================
    # LIFETIME DEPOSIT
    # ========================================================

    lifetime_deposit = await bot.db.pool.fetchval(
        """
        SELECT lifetime_deposit
        FROM users
        WHERE user_id=$1
        """,
        user_id,
    )

    lifetime_deposit = Decimal(
        str(lifetime_deposit or 0)
    )

    if lifetime_deposit < Decimal("1"):

        await interaction.response.send_message(
            embed=error_embed(
                "Withdrawal Unavailable",
                (
                    "You must have deposited at least "
                    "**$1.00 lifetime** before withdrawing."
                ),
            ),
            ephemeral=False,
        )

        return

    # ========================================================
    # BALANCE
    # ========================================================

    balance = await bot.get_balance(
        user_id
    )

    if value > balance:

        await interaction.response.send_message(
            embed=error_embed(
                "Insufficient Balance",
                (
                    f"Your balance is **{money(balance)}**.\n"
                    f"You cannot withdraw **{money(value)}**."
                ),
            ),
            ephemeral=False,
        )

        return

    # ========================================================
    # CREATE WITHDRAWAL
    #
    # create_withdrawal() handles the balance deduction.
    # DO NOT call change_balance() here.
    # ========================================================

    created = await bot.db.create_withdrawal(
        user_id=user_id,
        currency=currency,
        address=address,
        amount=value,
    )

    if not created:

        await interaction.response.send_message(
            embed=error_embed(
                "Withdrawal Failed",
                (
                    "The withdrawal could not be created. "
                    "Your balance was not changed."
                ),
            ),
            ephemeral=False,
        )

        return

    # ========================================================
    # WITHDRAWAL LOG
    # ========================================================

    log_channel = None

    channel_id = getattr(
        bot,
        "withdraw_log_channel_id",
        None,
    )

    if channel_id:

        log_channel = bot.get_channel(
            channel_id
        )

    if log_channel:

        try:

            await log_channel.send(
                embed=base_embed(
                    "CryptoBet Withdrawal",
                    (
                        f"**User:** {interaction.user.mention}\n"
                        f"**User ID:** `{user_id}`\n\n"
                        f"**Amount:** {money(value)}\n"
                        f"**Currency:** `{currency}`\n"
                        f"**Address:** `{address}`\n\n"
                        "**Status:** `Pending`"
                    ),
                )
            )

        except Exception as exc:

            print(
                f"[WITHDRAW] Log error: {exc}"
            )

    # ========================================================
    # SUCCESS
    # ========================================================

    await interaction.response.send_message(
        embed=success_embed(
            "Withdrawal Requested",
            (
                f"**Amount:** {money(value)}\n"
                f"**Currency:** `{currency}`\n\n"
                f"**Address:** `{address}`\n\n"
                "Your withdrawal has been created and is "
                "**pending processing**."
            ),
        ),
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
# /WITHDRAWLOG
# ============================================================

@prefix_command(name="withdrawlog")
async def withdrawlog_command(
    interaction: discord.Interaction,
):

    if not allowed_admin(interaction):
        await interaction.response.send_message(
            "You do not have permission to use this command.",
            ephemeral=True,
        )
        return

    bot.withdraw_log_channel_id = interaction.channel.id

    await interaction.response.send_message(
        f"Withdrawal logs will now be sent to {interaction.channel.mention}.",
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

    # Brand lockup: same upper-left placement as the supplied sample, renamed CryptoBet.
    draw.line((315, 100, 315, 233), fill=(0, 113, 255, 190), width=2)
    # Spade-style brand mark.
    draw.ellipse((133, 52, 224, 126), fill=(224, 240, 255, 245))
    draw.polygon([(178, 34), (133, 89), (151, 119), (178, 103), (205, 119), (224, 89)], fill=(224, 240, 255, 245))
    draw.ellipse((151, 67, 205, 117), fill=(9, 28, 52, 255))
    draw.polygon([(178, 102), (159, 137), (176, 128), (188, 141), (198, 132)], fill=(224, 240, 255, 245))
    brand_font = _race_font(47, True)
    tagline_font = _race_font(12, False)
    _draw_centered(draw, (178, 174), "CryptoBet", brand_font, (225, 241, 255, 255))
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
                await ctx.send("**CryptoBet Race Reset**\nA new race has started and the leaderboard has been reset.")
                return
            if action == "end":
                if hasattr(bot.db, "finish_race"):
                    await bot.db.finish_race()
                await bot.db.set_setting("race_active", "0")
                await ctx.send("**CryptoBet Race Ended**\nThe current race has ended.")
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

    bet = normalize_amount(amount)

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


class RouletteView(ButtonView):
    def __init__(self, game: RouletteGame):
        super().__init__(timeout=300)
        self.game = game
        self._build_buttons()

    def _build_buttons(self):
        buttons = [
            # Discord allows a maximum of 5 buttons per row.
            # Keep the 10 roulette bets across two full rows.
            ("red", "RED", discord.ButtonStyle.danger, 0),
            ("black", "BLACK", discord.ButtonStyle.secondary, 0),
            ("low", "1-19", discord.ButtonStyle.secondary, 0),
            ("high", "20-36", discord.ButtonStyle.secondary, 0),
            ("col1", "COL 1", discord.ButtonStyle.secondary, 0),
            ("col2", "COL 2", discord.ButtonStyle.secondary, 1),
            ("col3", "COL 3", discord.ButtonStyle.secondary, 1),
            ("zero", "0", discord.ButtonStyle.secondary, 1),
            ("odd", "ODD", discord.ButtonStyle.secondary, 1),
            ("even", "EVEN", discord.ButtonStyle.secondary, 1),
        ]

        for key, label, style, row in buttons:
            button = discord.ui.Button(
                label=label,
                style=(
                    discord.ButtonStyle.success
                    if key in self.game.selected
                    else style
                ),
                custom_id=f"roulette_bet:{key}",
                row=row,
                disabled=self.game.started,
            )
            button.callback = self.make_bet_callback(key)
            self.add_item(button)

        start = discord.ui.Button(
            label="START",
            style=discord.ButtonStyle.primary,
            custom_id="roulette_start",
            row=2,
            disabled=self.game.started,
        )
        start.callback = self.start
        self.add_item(start)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.game.user_id:
            await interaction.response.send_message(
                "This Roulette game belongs to another player.",
                ephemeral=False,
            )
            return False
        return True

    def make_bet_callback(self, key: str):
        async def callback(interaction: discord.Interaction):
            if self.game.started:
                await interaction.response.send_message(
                    "Roulette has already started.",
                    ephemeral=False,
                )
                return

            if key in self.game.selected:
                self.game.selected.remove(key)
            else:
                self.game.selected.append(key)

            await interaction.response.edit_message(
                embed=roulette_embed(self.game),
                view=RouletteView(self.game),
            )

        return callback

    async def start(self, interaction: discord.Interaction):
        if self.game.started:
            await interaction.response.send_message(
                "Roulette has already started.",
                ephemeral=False,
            )
            return

        if not self.game.selected:
            await interaction.response.send_message(
                "Select at least one bet before pressing START.",
                ephemeral=False,
            )
            return

        balance = await self.game.bot.get_balance(self.game.user_id)
        if self.game.total_cost > balance:
            await interaction.response.send_message(
                "You Dont Have Enough Crypto\n"
                "-# use .deposit to top-up Funds",
                ephemeral=False,
            )
            return

        self.game.started = True
        self.game.finished = False

        # Deduct the complete cost once. Each selected button represents one bet.
        deducted = await self.game.bot.deduct_bet(
            self.game.user_id,
            self.game.total_cost,
            "roulette",
        )
        if not deducted:
            self.game.started = False
            await interaction.response.send_message(
                "Your balance changed. Please try again or deposit funds.",
                ephemeral=False,
            )
            return

        await interaction.response.defer()

        spinning_embed = base_embed(
            "Spinning Roulette",
            (
                f"**Total Bet Amount :** {money(self.game.total_cost)}\n"
                f"**Your Bet :** {roulette_display_bets(self.game.selected)}\n\n"
                "The wheel is spinning..."
            ),
            0x2B2D31,
        )
        spinning_embed.set_image(url="attachment://roulette.jpg")

        spin_file = create_roulette_image()
        await interaction.edit_original_response(
            embed=spinning_embed,
            view=None,
            attachments=[spin_file],
        )

        await asyncio.sleep(1.5)
        await finish_roulette(self.game.bot, interaction, self.game)

    async def on_timeout(self):
        if not self.game.started:
            for item in self.children:
                item.disabled = True


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
    await interaction.edit_original_response(
        embed=roulette_embed(game, title="Roulette", result=True),
        view=None,
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

    bet = normalize_amount(amount)
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
    try:
        await interaction.response.send_message(
            embed=roulette_embed(game),
            view=RouletteView(game),
            file=file,
        )
    except Exception:
        bot.active_roulette.pop(user_id, None)
        raise

    message = await interaction.original_response()
    game.message_id = message.id
    game.channel_id = interaction.channel_id



# ============================================================
# DEAL OR NO DEAL / CASE
# ============================================================

CASE_SMALL_MULTIPLIERS = [
    Decimal("0.10"),
    Decimal("0.20"),
    Decimal("0.30"),
    Decimal("0.50"),
    Decimal("0.70"),
    Decimal("0.90"),
]

CASE_BIG_MULTIPLIERS = [
    Decimal("1.50"),
    Decimal("2.00"),
    Decimal("5.00"),
    Decimal("10.00"),
]

CASE_TOTAL_BOXES = 10
CASE_ROUNDS = 4
CASE_BACKGROUND_B64 = "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"


def case_font(size: int, bold: bool = False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"
        if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
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


def _case_background():
    try:
        raw = base64.b64decode(CASE_BACKGROUND_B64)
        image = Image.open(io.BytesIO(raw)).convert("RGBA")
    except Exception:
        image = Image.new("RGBA", (1000, 700), (25, 10, 30, 255))
    return image.resize((1000, 690), Image.Resampling.LANCZOS)


def _case_prize_text(value: Decimal, bet: Decimal) -> str:
    multiplier = (value / bet).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    if multiplier < Decimal("1.00"):
        return money(value)
    return f"{multiplier:.2f}x  {money(value)}"


def create_case_image(game: "CaseGame"):
    image = _case_background()
    overlay = Image.new("RGBA", image.size, (9, 6, 18, 95))
    image = Image.alpha_composite(image, overlay)
    draw = ImageDraw.Draw(image)

    WHITE = (255, 255, 255, 255)
    MUTED = (215, 208, 220, 255)
    RED = (224, 38, 30, 255)
    RED_DARK = (126, 17, 20, 255)
    BLUE = (32, 68, 145, 255)
    GOLD = (255, 205, 70, 255)
    GREEN = (62, 214, 129, 255)
    BLACK = (20, 16, 22, 220)
    GREY = (75, 72, 82, 255)

    # Main title/header.
    draw.rounded_rectangle((24, 18, 976, 95), radius=18, fill=(19, 13, 28, 220), outline=GOLD, width=3)
    draw.text((50, 31), "DEAL OR NO DEAL", font=case_font(36, True), fill=WHITE)
    stake_text = f"STAKE  {money(game.amount)}"
    bbox = draw.textbbox((0, 0), stake_text, font=case_font(29, True))
    draw.text((950 - (bbox[2] - bbox[0]), 37), stake_text, font=case_font(29, True), fill=GOLD)

    # Small instruction/status line.
    if not game.confirmed:
        status = "PICK A BOX"
    elif not game.started:
        status = f"BOX {game.selected_box + 1} LOCKED  •  PRESS START"
    elif game.finished:
        status = "GAME OVER"
    else:
        status = f"BANK OFFER  •  {money(game.bank_offer)}" if game.bank_offer else "ELIMINATE 2 BOXES"
    draw.text((50, 105), status, font=case_font(23, True), fill=MUTED)

    # Prize board at the top/right: values are hidden until the game starts.
    prize_values = []
    if game.started:
        remaining = [i for i in range(CASE_TOTAL_BOXES) if i not in game.eliminated]
        for i in remaining:
            prize_values.append(game.prizes[i])
        prize_values.sort()
    else:
        prize_values = [game.amount * m for m in CASE_SMALL_MULTIPLIERS + CASE_BIG_MULTIPLIERS]
        prize_values.sort()

    board_x = 650
    board_y = 120
    board_w = 320
    board_h = 300
    draw.rounded_rectangle((board_x, board_y, board_x + board_w, board_y + board_h), radius=18, fill=(17, 15, 25, 220), outline=(105, 91, 115, 255), width=2)
    draw.text((board_x + 18, board_y + 12), "PRIZE BOARD", font=case_font(22, True), fill=WHITE)
    for idx, value in enumerate(prize_values):
        col = 0 if idx < 5 else 1
        row = idx if idx < 5 else idx - 5
        x = board_x + 18 + col * 154
        y = board_y + 52 + row * 45
        fill = GREEN if value >= game.amount else (BLUE if value == game.amount else RED_DARK)
        draw.rounded_rectangle((x, y, x + 140, y + 35), radius=8, fill=fill, outline=(230, 230, 230, 90), width=1)
        text = _case_prize_text(value, game.amount)
        bb = draw.textbbox((0, 0), text, font=case_font(17, True))
        draw.text((x + 70 - (bb[2] - bb[0]) / 2, y + 7), text, font=case_font(17, True), fill=WHITE)

    # Ten red cases in two rows of five.
    positions = []
    start_x = 55
    box_w = 104
    box_h = 110
    gap_x = 16
    row_y = [235, 380]
    for row in range(2):
        for col in range(5):
            positions.append((start_x + col * (box_w + gap_x), row_y[row]))

    for index, (x, y) in enumerate(positions):
        selected = game.selected_box == index
        eliminated = index in game.eliminated
        revealed = game.started or game.finished
        if eliminated:
            fill = (45, 40, 48, 225)
            outline = GREY
        elif selected:
            fill = (185, 24, 26, 255)
            outline = GOLD
        else:
            fill = RED
            outline = GOLD

        draw.rounded_rectangle((x, y, x + box_w, y + box_h), radius=12, fill=fill, outline=outline, width=5 if selected else 3)
        draw.rectangle((x + 10, y + 12, x + box_w - 10, y + 28), fill=RED_DARK)
        draw.rectangle((x + 10, y + box_h - 28, x + box_w - 10, y + box_h - 12), fill=BLUE)

        if eliminated:
            label = "X"
            font = case_font(48, True)
            bb = draw.textbbox((0, 0), label, font=font)
            draw.text((x + box_w / 2 - (bb[2] - bb[0]) / 2, y + 30), label, font=font, fill=MUTED)
        elif revealed:
            if index == game.selected_box and game.finished and game.final_result is not None:
                label = "YOUR BOX"
            else:
                label = f"{index + 1}"
            font = case_font(28, True)
            bb = draw.textbbox((0, 0), label, font=font)
            draw.text((x + box_w / 2 - (bb[2] - bb[0]) / 2, y + 36), label, font=font, fill=WHITE)
            prize = game.prizes[index]
            ptxt = _case_prize_text(prize, game.amount)
            pfont = case_font(16, True)
            pb = draw.textbbox((0, 0), ptxt, font=pfont)
            draw.text((x + box_w / 2 - (pb[2] - pb[0]) / 2, y + 77), ptxt, font=pfont, fill=GOLD if prize >= game.amount else WHITE)
        else:
            label = "??"
            font = case_font(34, True)
            bb = draw.textbbox((0, 0), label, font=font)
            draw.text((x + box_w / 2 - (bb[2] - bb[0]) / 2, y + 36), label, font=font, fill=WHITE)

    # Bottom banner.
    if game.finished:
        result = f"FINAL  •  {money(game.final_result or Decimal('0'))}"
        fill = (28, 115, 68, 235) if game.final_result and game.final_result >= game.amount else (130, 28, 36, 235)
    elif game.started:
        result = f"REMAINING BOXES  {len([i for i in range(10) if i not in game.eliminated])}"
        fill = (20, 31, 58, 235)
    else:
        result = "PICK A BOX  •  CONFIRM YOUR CHOICE"
        fill = (20, 31, 58, 235)
    draw.rounded_rectangle((220, 545, 780, 675), radius=22, fill=fill, outline=WHITE, width=2)
    bb = draw.textbbox((0, 0), result, font=case_font(25, True))
    draw.text((500 - (bb[2] - bb[0]) / 2, 573), result, font=case_font(25, True), fill=WHITE)
    if game.started and not game.finished:
        info = f"BANK  {money(game.bank_offer)}" if game.bank_offer else "BANK IS WATCHING"
        ib = draw.textbbox((0, 0), info, font=case_font(21, True))
        draw.text((500 - (ib[2] - ib[0]) / 2, 617), info, font=case_font(21, True), fill=GOLD)

    output = io.BytesIO()
    image.convert("RGB").save(output, format="JPEG", quality=92, optimize=True)
    output.seek(0)
    return discord.File(output, filename="case.jpg")


class CaseGame:
    def __init__(self, bot: CasinoBot, user_id: int, amount: Decimal, game_id: int, server_seed: str, client_seed: str):
        self.bot = bot
        self.user_id = user_id
        self.amount = amount
        self.game_id = game_id
        self.server_seed = server_seed
        self.server_hash = bot.server_hash(server_seed)
        self.client_seed = client_seed
        self.nonce = 0
        self.selected_box: Optional[int] = None
        self.confirmed = False
        self.started = False
        self.finished = False
        self.eliminated: set[int] = set()
        self.prizes: dict[int, Decimal] = {}
        self.bank_offer = Decimal("0")
        self.final_result: Optional[Decimal] = None
        self.message_id = None
        self.channel_id = None

    def build_prizes(self):
        values = [self.amount * m for m in CASE_SMALL_MULTIPLIERS + CASE_BIG_MULTIPLIERS]
        # Deterministic Fisher-Yates using the existing provably-fair digest.
        order = list(range(CASE_TOTAL_BOXES))
        for i in range(len(order) - 1, 0, -1):
            digest = self.bot.fair_digest(self.server_seed, self.client_seed, self.nonce + i, "case")
            j = int.from_bytes(digest[:8], "big") % (i + 1)
            order[i], order[j] = order[j], order[i]
        for pos, value_index in enumerate(order):
            self.prizes[pos] = values[value_index]

    @property
    def remaining_boxes(self):
        return [i for i in range(CASE_TOTAL_BOXES) if i not in self.eliminated]

    @property
    def remaining_prizes(self):
        return [self.prizes[i] for i in self.remaining_boxes]

    def make_bank_offer(self):
        values = self.remaining_prizes
        if not values:
            self.bank_offer = Decimal("0")
            return self.bank_offer
        average = sum(values, Decimal("0")) / Decimal(len(values))
        round_no = len(self.eliminated) // 2
        percentages = {
            1: Decimal("0.64"),
            2: Decimal("0.72"),
            3: Decimal("0.84"),
            4: Decimal("0.95"),
        }
        pct = percentages.get(round_no, Decimal("0.95"))
        offer = (average * pct).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        self.bank_offer = max(Decimal("0.01"), offer)
        return self.bank_offer



def case_embed(game: CaseGame, title="Deal or No Deal", result: Optional[str] = None):
    if game.finished:
        color = 0x2ECC71 if game.final_result is not None and game.final_result >= game.amount else 0xE74C3C
    elif game.bank_offer:
        color = 0xF1C40F
    else:
        color = 0x2B2D31

    lines = [f"**Stake :** {money(game.amount)}"]
    if game.selected_box is not None:
        if game.confirmed:
            lines.append(f"**Your Box :** {game.selected_box + 1}")
        else:
            lines.append("**Your Box :** `??` — select and confirm")
    if game.started:
        lines.append(f"**Boxes Remaining :** {len(game.remaining_boxes)}")
    if game.bank_offer and not game.finished:
        lines.append(f"**Bank Offer :** {money(game.bank_offer)}")
    if result:
        lines.extend(["", result])

    embed = base_embed(title, "\n".join(lines), color)
    embed.set_image(url="attachment://case.jpg")
    embed.set_footer(text=f"Game #{game.game_id} • Deal or No Deal • Provably fair")
    return embed


class CaseView(ButtonView):
    def __init__(self, game: CaseGame):
        super().__init__(timeout=600)
        self.game = game
        if not game.confirmed:
            for i in range(CASE_TOTAL_BOXES):
                button = discord.ui.Button(
                    label="??",
                    style=discord.ButtonStyle.danger if game.selected_box != i else discord.ButtonStyle.success,
                    custom_id=f"case_pick:{i}",
                    row=i // 5,
                )
                button.callback = self.make_pick(i)
                self.add_item(button)
            confirm = discord.ui.Button(
                label="CONFIRM SELECTION",
                style=discord.ButtonStyle.primary,
                custom_id="case_confirm",
                row=2,
                disabled=game.selected_box is None,
            )
            confirm.callback = self.confirm
            self.add_item(confirm)
        elif not game.started:
            start = discord.ui.Button(
                label="START",
                style=discord.ButtonStyle.primary,
                custom_id="case_start",
                row=0,
            )
            start.callback = self.start
            self.add_item(start)
        elif not game.finished and not game.bank_offer:
            eliminate = discord.ui.Button(
                label="ELIMINATE 2 BOXES",
                style=discord.ButtonStyle.danger,
                custom_id="case_eliminate",
                row=0,
            )
            eliminate.callback = self.eliminate
            self.add_item(eliminate)
        elif not game.finished and game.bank_offer:
            accept = discord.ui.Button(
                label=f"ACCEPT {money(game.bank_offer)}",
                style=discord.ButtonStyle.success,
                custom_id="case_accept",
                row=0,
            )
            accept.callback = self.accept_offer
            self.add_item(accept)

            if len(game.remaining_boxes) > 2:
                reject = discord.ui.Button(
                    label="REJECT & CONTINUE",
                    style=discord.ButtonStyle.secondary,
                    custom_id="case_reject",
                    row=0,
                )
                reject.callback = self.reject_offer
                self.add_item(reject)
            else:
                stay = discord.ui.Button(
                    label="STAY",
                    style=discord.ButtonStyle.secondary,
                    custom_id="case_stay",
                    row=0,
                )
                stay.callback = self.stay_final
                self.add_item(stay)
                swap = discord.ui.Button(
                    label="SWAP",
                    style=discord.ButtonStyle.primary,
                    custom_id="case_swap",
                    row=1,
                )
                swap.callback = self.swap_final
                self.add_item(swap)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.game.user_id:
            await interaction.response.send_message("This Deal or No Deal game belongs to another player.", ephemeral=False)
            return False
        return True

    def make_pick(self, index: int):
        async def callback(interaction: discord.Interaction):
            if self.game.started:
                return
            if self.game.selected_box == index:
                self.game.selected_box = None
            else:
                self.game.selected_box = index
            await interaction.response.edit_message(
                embed=case_embed(self.game),
                view=CaseView(self.game),
                attachments=[create_case_image(self.game)],
            )
        return callback

    async def confirm(self, interaction: discord.Interaction):
        if self.game.selected_box is None:
            await interaction.response.send_message("Pick a box first.", ephemeral=False)
            return
        self.game.confirmed = True
        await interaction.response.edit_message(
            embed=case_embed(self.game, result="Your box is locked. Press START to cut the balance and begin."),
            view=CaseView(self.game),
            attachments=[create_case_image(self.game)],
        )

    async def start(self, interaction: discord.Interaction):
        if self.game.selected_box is None or not self.game.confirmed:
            await interaction.response.send_message("Confirm your box first.", ephemeral=False)
            return
        balance = await self.game.bot.get_balance(self.game.user_id)
        if self.game.amount > balance:
            await interaction.response.send_message("You Dont Have Enough Crypto\n-# use .deposit to top-up Funds", ephemeral=False)
            return
        deducted = await self.game.bot.deduct_bet(self.game.user_id, self.game.amount, "case")
        if not deducted:
            await interaction.response.send_message("Your balance changed. Please deposit funds and try again.", ephemeral=False)
            return
        self.game.build_prizes()
        self.game.started = True
        await interaction.response.defer()
        await interaction.edit_original_response(
            embed=case_embed(self.game, result="Deal or No Deal has started. Eliminate two boxes."),
            view=CaseView(self.game),
            attachments=[create_case_image(self.game)],
        )

    async def eliminate(self, interaction: discord.Interaction):
        if not self.game.started or self.game.finished or self.game.bank_offer:
            return
        choices = [i for i in self.game.remaining_boxes if i != self.game.selected_box]
        if len(choices) <= 1:
            return
        # Two fair eliminations, never touching the player's chosen box.
        first_index = self.game.bot.fair_int(self.game.server_seed, self.game.client_seed, len(self.game.eliminated) + 1, 0, len(choices) - 1, "case_eliminate")
        first = choices[first_index]
        remaining = [i for i in choices if i != first]
        second_index = self.game.bot.fair_int(self.game.server_seed, self.game.client_seed, len(self.game.eliminated) + 2, 0, len(remaining) - 1, "case_eliminate")
        second = remaining[second_index]
        self.game.eliminated.update({first, second})
        self.game.make_bank_offer()
        await interaction.response.edit_message(
            embed=case_embed(self.game, result=f"Boxes **{first + 1}** and **{second + 1}** were eliminated. The Banker offers **{money(self.game.bank_offer)}**."),
            view=CaseView(self.game),
            attachments=[create_case_image(self.game)],
        )

    async def accept_offer(self, interaction: discord.Interaction):
        await finish_case(self.game.bot, interaction, self.game, self.game.bank_offer, f"Bank offer accepted: **{money(self.game.bank_offer)}**.")

    async def reject_offer(self, interaction: discord.Interaction):
        self.game.bank_offer = Decimal("0")
        await interaction.response.edit_message(
            embed=case_embed(self.game, result="No deal. Eliminate two more boxes."),
            view=CaseView(self.game),
            attachments=[create_case_image(self.game)],
        )

    async def stay_final(self, interaction: discord.Interaction):
        prize = self.game.prizes[self.game.selected_box]
        await finish_case(self.game.bot, interaction, self.game, prize, f"You stayed with Box **{self.game.selected_box + 1}** and won **{money(prize)}**.")

    async def swap_final(self, interaction: discord.Interaction):
        other = [i for i in self.game.remaining_boxes if i != self.game.selected_box][0]
        prize = self.game.prizes[other]
        await finish_case(self.game.bot, interaction, self.game, prize, f"You swapped to Box **{other + 1}** and won **{money(prize)}**.")


async def finish_case(bot_instance: CasinoBot, interaction: discord.Interaction, game: CaseGame, payout: Decimal, result: str):
    if game.finished:
        return
    game.finished = True
    game.bank_offer = Decimal("0")
    game.final_result = D(payout)
    await bot_instance.settle_win(game.user_id, game.amount, game.final_result, "case")
    bot_instance.active_cases.pop(game.user_id, None)
    await interaction.response.edit_message(
        embed=case_embed(game, result=result),
        view=None,
        attachments=[create_case_image(game)],
    )
    await bot_instance.check_rank_up(game.user_id)


@prefix_command(name="case", aliases=["deal"])
async def case_command(interaction: discord.Interaction, amount: str):
    user_id = interaction.user.id
    if not await require_database(interaction):
        return
    cooldown = bot.check_game_cooldown(user_id, "case")
    if cooldown:
        await bot.safe_send(interaction, content=f"Please wait **{cooldown:.1f}s** before starting another game.", ephemeral=False)
        return
    if user_id in bot.active_cases:
        await bot.safe_send(interaction, content="You already have an active Deal or No Deal game.", ephemeral=False)
        return
    bet = normalize_amount(amount)
    if bet is None or bet < MIN_BET:
        await bot.safe_send(interaction, embed=error_embed("Invalid Bet", f"Minimum bet is {money(MIN_BET)}."), ephemeral=False)
        return
    balance = await bot.get_balance(user_id)
    if bet > balance:
        await bot.safe_send(interaction, content="You Dont Have Enough Crypto\n-# use .deposit to top-up Funds", ephemeral=False)
        return

    game = CaseGame(
        bot=bot,
        user_id=user_id,
        amount=bet,
        game_id=bot.next_game_id(),
        server_seed=bot.create_server_seed(),
        client_seed=bot.create_client_seed(user_id),
    )
    bot.active_cases[user_id] = game
    try:
        await interaction.response.send_message(
            embed=case_embed(game),
            view=CaseView(game),
            file=create_case_image(game),
        )
        message = await interaction.original_response()
        game.message_id = message.id
        game.channel_id = interaction.channel_id
    except Exception:
        bot.active_cases.pop(user_id, None)
        raise

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

@prefix_command(name="rain")
async def rain_command(
    interaction: discord.Interaction,
    amount: str,
    duration: app_commands.Choice[int],
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

    seconds = RAIN_DURATIONS.get(
        duration.value,
        60,
    )

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

COINFLIP_MULTIPLIER = Decimal("1.92")


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

@prefix_command(
    name="coinflip",
    aliases=["cf"],
)
async def coinflip(
    ctx,
    amount: str,
    choice: str = "heads",
):

    # ========================================================
    # USER
    # ========================================================

    user = ctx.author
    user_id = user.id

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

    flipping_embed = neutral_embed(
        "## Flipping...",
        (
            f"**{user.display_name}** "
            f"betted **{money(bet)}** on "
            f"**{selected_name}**\n\n"
            f"**Game #{game_id}**"
        ),
    )

    flipping_message = await ctx.send(
        embed=flipping_embed
    )

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
    # RESULT EMBED
    # ========================================================

    result_embed = base_embed(
        title="",
        description="",
        color=(
            0x57F287
            if won
            else 0xED4245
        ),
    )

    result_embed.set_image(
        url="attachment://coinflip_result.png"
    )

    # ========================================================
    # PROVABLY FAIR
    # ========================================================

    result_embed.add_field(
        name="Provably Fair",
        value=(
            f"**Server Hash:** "
            f"`{game['server_hash']}`\n"
            f"**Client Seed:** "
            f"`{game['client_seed']}`\n"
            f"**Nonce:** "
            f"`{game['nonce']}`"
        ),
        inline=False,
    )

    # ========================================================
    # GAME ID
    # ========================================================

    result_embed.add_field(
        name="Game",
        value=f"`#{game_id}`",
        inline=True,
    )

    # ========================================================
    # PAYOUT
    # ========================================================

    if won:

        result_embed.add_field(
            name="Payout",
            value=(
                f"`{money(payout)}` "
                f"**1.92x**"
            ),
            inline=True,
        )

    else:

        result_embed.add_field(
            name="Lost",
            value=money(bet),
            inline=True,
        )

    # ========================================================
    # FOOTER
    # ========================================================

    result_embed.set_footer(
        text="Verify this result with .verify"
    )

    # ========================================================
    # SEND RESULT
    # ========================================================

    await flipping_message.edit(
        embed=result_embed,
        attachments=[image_file],
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
# LTC ADDRESS
# ============================================================

async def get_ltc_deposit_address(
    user_id: int,
):
    """
    Get or create the unique LTC deposit address
    belonging to this Discord user.

    The actual xpub derivation and database storage
    are handled by database.py.
    """

    try:

        if not config.LTC_XPUB:
            print(
                "[DEPOSIT] LTC_XPUB is missing."
            )

            return None

        if not hasattr(
            bot.db,
            "get_or_create_ltc_address",
        ):

            print(
                "[DEPOSIT] "
                "database.get_or_create_ltc_address() "
                "is missing."
            )

            return None

        address = await bot.db.get_or_create_ltc_address(
            user_id,
            config.LTC_XPUB,
            getattr(
                config,
                "LTC_DERIVATION_PATH",
                "m/0",
            ),
        )

        return address

    except Exception as e:

        print(
            f"[DEPOSIT] LTC address generation error: {e}"
        )

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

    # ========================================================
    # USDT
    # ========================================================

    @discord.ui.button(
        label="USDT",
        style=discord.ButtonStyle.secondary,
        custom_id="deposit_usdt_new",
    )
    async def usdt_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        embed = base_embed(
            "Tether USDT: Select Network",
            (
                "Choose the network you want to use "
                "for your USDT deposit."
            ),
        )

        await interaction.response.edit_message(
            content=None,
            embed=embed,
            view=USDTNetworkView(
                self.user_id
            ),
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
            "**Litecoin (LTC)** and **Solana (SOL)** "
            "are native and faster, while the rest of the "
            "cryptocurrencies require automatic conversion "
            "to Litecoin which may take longer and have "
            "network fees."
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
`.dice` `.roll`
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
`.fix-dice`
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
# /AFFILIATE / /AFFILIATES
# ============================================================

@prefix_command(name="affiliate")
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
                " Affiliate\n\n"
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

@prefix_command(name="fix-dice")
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

@prefix_command(name="claim")
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

@prefix_command(name="winlogs")
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

@prefix_command(name="code")
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
# /ADDBAL
# ============================================================

@prefix_command(name="addbal")
@owner_only()
async def addbal_command(
    interaction: discord.Interaction,
    user: discord.Member,
    amount: str,
):

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


@prefix_command(name="frog-run")
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
# DICE GAME — COMPLETE
# ============================================================

DICE_STICKERS = {
    1: 1553656486637338714,
    2: 1553656882361794712,
    3: 1553656975206649967,
    4: 1553657070547378237,
    5: 1553657144384163870,
    6: 1553657240077209672,
}


# ============================================================
# DICE SETUP — MODE
# ============================================================

class DiceSetupView(discord.ui.View):

    def __init__(
        self,
        user_id: int,
        amount: Decimal,
    ):
        super().__init__(timeout=120)

        self.user_id = user_id
        self.amount = amount

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:

        if interaction.user.id != self.user_id:

            await interaction.response.send_message(
                "This Dice setup belongs to another player.",
                ephemeral=False,
            )

            return False

        return True

    @discord.ui.button(
        label="Normal Dice",
        style=discord.ButtonStyle.secondary,
        custom_id="dice_normal",
    )
    async def normal(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await interaction.response.edit_message(
            content=(
                "## Dice\n\n"
                "**Normal Dice** selected.\n\n"
                "Choose how many dice you want to roll:"
            ),
            view=DiceCountView(
                self.user_id,
                self.amount,
                "normal",
            ),
        )

    @discord.ui.button(
        label="Crazy Dice",
        style=discord.ButtonStyle.primary,
        custom_id="dice_crazy",
    )
    async def crazy(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await interaction.response.edit_message(
            content=(
                "## Dice\n\n"
                "**Crazy Dice** selected.\n\n"
                "Choose how many dice you want to roll:"
            ),
            view=DiceCountView(
                self.user_id,
                self.amount,
                "crazy",
            ),
        )


# ============================================================
# DICE SETUP — NUMBER OF DICE
# ============================================================

class DiceCountView(discord.ui.View):

    def __init__(
        self,
        user_id: int,
        amount: Decimal,
        mode: str,
    ):
        super().__init__(timeout=120)

        self.user_id = user_id
        self.amount = amount
        self.mode = mode

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:

        if interaction.user.id != self.user_id:

            await interaction.response.send_message(
                "This Dice setup belongs to another player.",
                ephemeral=False,
            )

            return False

        return True

    async def choose(
        self,
        interaction: discord.Interaction,
        dice_count: int,
    ):

        await interaction.response.defer()

        await bot.start_dice_game(
            interaction,
            self.user_id,
            self.amount,
            self.mode,
            dice_count,
        )

    @discord.ui.button(
        label="1",
        style=discord.ButtonStyle.secondary,
        custom_id="dice_count_1",
    )
    async def one(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await self.choose(
            interaction,
            1,
        )

    @discord.ui.button(
        label="2",
        style=discord.ButtonStyle.secondary,
        custom_id="dice_count_2",
    )
    async def two(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await self.choose(
            interaction,
            2,
        )

    @discord.ui.button(
        label="3",
        style=discord.ButtonStyle.secondary,
        custom_id="dice_count_3",
    )
    async def three(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await self.choose(
            interaction,
            3,
        )


# ============================================================
# /DICE
# ============================================================

@prefix_command(name="dice")
async def dice(
    interaction: discord.Interaction,
    amount: str,
):

    if not await require_database(interaction):
        return

    value = normalize_amount(amount)

    if value is None or value <= Decimal("0"):

        await interaction.response.send_message(
            "Please enter a valid bet amount.",
            ephemeral=False,
        )

        return

    balance = await bot.get_balance(
        interaction.user.id
    )

    if value > balance:

        await interaction.response.send_message(
            "You Dont Have Enough Crypto",
            ephemeral=False,
        )

        return

    embed = base_embed(
        title="Dice",
        description=(
            f"**Bet:** {money(value)}\n\n"
            "Choose an Gamemode below\n\n"
            "**Normal Dice**\n"
            "Highest total wins.\n\n"
            "**Crazy Dice**\n"
            "Lowest total wins."
        ),
    )

    await interaction.response.send_message(
        embed=embed,
        view=DiceSetupView(
            interaction.user.id,
            value,
        ),
        ephemeral=False,
    )


# ============================================================
# START DICE GAME
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
            embed=None,
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

    self.active_dice[user_id] = {
        "user_id": user_id,
        "amount": amount,
        "mode": mode,
        "dice_count": dice_count,
        "game_id": game_id,
        "server_seed": server_seed,
        "server_hash": server_hash,
        "client_seed": client_seed,
        "nonce": 0,
        "player_rolls": [],
        "bot_rolls": [],
        "message_id": None,
        "channel_id": (
            interaction.channel.id
            if interaction.channel
            else None
        ),
    }

    mode_name = (
        "Normal"
        if mode == "normal"
        else "Crazy"
    )

    embed = base_embed(
        title="Dice — Game Started",
        description=(
            f"**Mode:** {mode_name}\n"
            f"**Dice:** {dice_count}\n"
            f"**Bet:** {money(amount)}\n\n"
            f"**{interaction.user.display_name}:** "
            + " + ".join(
                "?"
                for _ in range(dice_count)
            )
            + " = ?\n"
            f"**Bot:** "
            + " + ".join(
                "?"
                for _ in range(dice_count)
            )
            + " = ?\n\n"
            "Use `.roll` to roll your next die."
        ),
    )

    embed.add_field(
        name="Game",
        value=f"`#{game_id}`",
        inline=True,
    )

    embed.add_field(
        name="Provably Fair",
        value=(
            f"Server Hash: `{server_hash}`"
        ),
        inline=False,
    )

    await interaction.edit_original_response(
        content=None,
        embed=embed,
        view=None,
    )

    # Save the actual Discord message.
    try:

        message = (
            await interaction.original_response()
        )

        self.active_dice[user_id][
            "message_id"
        ] = message.id

    except Exception as e:

        print(
            f"[DICE] Failed to save "
            f"message ID: {e}"
        )


CasinoBot.start_dice_game = _start_dice_game


# ============================================================
# SEND DICE STICKER
# ============================================================

async def send_dice_roll(
    interaction: discord.Interaction,
    game: dict,
    player_roll: int,
):

    sticker = None

    try:

        sticker_id = DICE_STICKERS.get(
            player_roll
        )

        if sticker_id:

            sticker = await bot.fetch_sticker(
                sticker_id
            )

    except Exception as e:

        print(
            f"[DICE STICKER] Fetch failed: {e}"
        )

    text = (
        f"🎲 **{interaction.user.display_name} "
        f"rolled `{player_roll}`**"
    )

    # --------------------------------------------------------
    # Try replying directly to the original Dice message.
    # --------------------------------------------------------

    if (
        game.get("channel_id")
        and game.get("message_id")
    ):

        try:

            channel = bot.get_channel(
                game["channel_id"]
            )

            if channel is None:

                channel = await bot.fetch_channel(
                    game["channel_id"]
                )

            game_message = (
                await channel.fetch_message(
                    game["message_id"]
                )
            )

            # Send sticker + text directly in channel.
            if sticker:

                try:

                    return await channel.send(
                        content=text,
                        stickers=[sticker],
                        reference=game_message,
                        mention_author=False,
                    )

                except Exception as e:

                    print(
                        f"[DICE STICKER] "
                        f"Sticker send failed: {e}"
                    )

            # Text fallback.
            return await channel.send(
                content=text,
                reference=game_message,
                mention_author=False,
            )

        except Exception as e:

            print(
                f"[DICE] Direct reply failed: {e}"
            )

    # --------------------------------------------------------
    # Final fallback.
    # --------------------------------------------------------

    if sticker:

        try:

            return await interaction.followup.send(
                content=text,
                stickers=[sticker],
                wait=True,
            )

        except Exception as e:

            print(
                f"[DICE] Followup sticker failed: {e}"
            )

    return await interaction.followup.send(
        content=text,
        wait=True,
    )


# ============================================================
# /ROLL
# ============================================================

@prefix_command(name="roll")
async def roll(
    interaction: discord.Interaction,
):

    user_id = interaction.user.id

    game = bot.active_dice.get(
        user_id
    )

    if not game:

        await interaction.response.send_message(
            "You don't have an active Dice game.",
            ephemeral=False,
        )

        return

    # --------------------------------------------------------
    # Prevent extra rolls.
    # --------------------------------------------------------

    if len(
        game["player_rolls"]
    ) >= game["dice_count"]:

        await interaction.response.send_message(
            "You have already rolled all your dice.",
            ephemeral=False,
        )

        return

    # --------------------------------------------------------
    # Acknowledge /roll immediately.
    # --------------------------------------------------------

    try:

        await interaction.response.defer()

    except Exception as e:

        print(
            f"[DICE] Defer failed: {e}"
        )

        return

    # --------------------------------------------------------
    # Generate fair player roll.
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Send the roll BEFORE consuming it.
    # --------------------------------------------------------

    try:

        await send_dice_roll(
            interaction,
            game,
            player_roll,
        )

    except Exception as e:

        print(
            f"[DICE] Roll send failed: {e}"
        )

        try:

            await interaction.followup.send(
                "⚠️ I couldn't send your roll. "
                "Your roll was not consumed. "
                "Try `.roll` again.",
                ephemeral=False,
            )

        except Exception:
            pass

        return

    # --------------------------------------------------------
    # Roll successfully sent.
    # Now consume it.
    # --------------------------------------------------------

    game["player_rolls"].append(
        player_roll
    )

    # --------------------------------------------------------
    # More player rolls required.
    # --------------------------------------------------------

    if len(
        game["player_rolls"]
    ) < game["dice_count"]:

        total = sum(
            game["player_rolls"]
        )

        await interaction.followup.send(
            content=(
                f"**Current total:** `{total}`\n"
                f"**Rolls:** "
                f"`{len(game['player_rolls'])}/"
                f"{game['dice_count']}`"
            ),
            ephemeral=False,
        )

        return

    # ========================================================
    # ALL PLAYER DICE ROLLED
    # ========================================================

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

    # --------------------------------------------------------
    # Determine winner.
    # --------------------------------------------------------

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

    # ========================================================
    # SETTLEMENT
    # ========================================================

    if result == "Win":

        payout = (
            game["amount"]
            * DICE_MULTIPLIER
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_DOWN,
        )

        # settle_win already credits payout.
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

        # Push = return original bet.
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

    # ========================================================
    # FINAL RESULT
    # ========================================================

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

    result_embed = base_embed(
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

    try:

        await interaction.followup.send(
            embed=result_embed,
            ephemeral=False,
        )

    except Exception as e:

        print(
            f"[DICE] Final result failed: {e}"
        )

    # Game finished.
    bot.active_dice.pop(
        user_id,
        None,
    )



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

        await self.db.record_game(
            game["user_id"],
            game["bet"],
            Decimal("0"),
            "blackjack_push",
        )

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

    value = normalize_amount(
        amount
    )

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
    # DECK
    # ========================================================

    deck = blackjack_deck()

    player = [
        deck.pop(),
        deck.pop(),
    ]

    dealer = [
        deck.pop(),
        "hidden",
    ]

    # ========================================================
    # PROVABLY FAIR
    # ========================================================

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

    bot.active_games[
        interaction.user.id
    ] = game

    # ========================================================
    # VIEW
    # ========================================================

    view = BlackjackView(
        bot,
        interaction.user.id,
        game,
    )

    # ========================================================
    # IMAGE
    # ========================================================

    file = create_blackjack_image(
        player,
        dealer,
        bet=value,
        hidden=True,
    )

    # ========================================================
    # EMBED
    # ========================================================

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


# ============================================================
# /BJ ALIAS
# ============================================================


# ============================================================
# /HOUSEBAL
# ============================================================

HOUSE_BALANCE = "$00.00"
HOUSE_LTC = "$00.00"
HOUSE_SOL = "$00.00"
HOUSE_USDT = "$00.00"


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


@prefix_command(name="housebal")
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

def create_limbo_image(
    result: Decimal,
    target: Decimal,
    won: bool,
):
    """
    Creates the Limbo result card.

    Visual style:
    - Dark Stake-inspired casino interface
    - Clean blue/navy background
    - Large multiplier
    - Target at top
    - Progress bar
    - Result indicator
    - Provably fair footer
    """

    WIDTH = 1100
    HEIGHT = 650

    # --------------------------------------------------------
    # COLORS
    # --------------------------------------------------------

    BG = (18, 23, 30)
    PANEL = (23, 29, 38)
    BORDER = (47, 59, 73)

    WHITE = (245, 247, 250)
    MUTED = (145, 154, 166)
    BLUE = (65, 145, 255)

    GREEN = (0, 220, 130)
    RED = (245, 75, 75)

    BAR_BG = (45, 53, 64)

    # --------------------------------------------------------
    # CANVAS
    # --------------------------------------------------------

    image = Image.new(
        "RGB",
        (WIDTH, HEIGHT),
        BG,
    )

    draw = ImageDraw.Draw(
        image
    )

    # --------------------------------------------------------
    # OUTER PANEL
    # --------------------------------------------------------

    draw.rounded_rectangle(
        (
            20,
            20,
            WIDTH - 20,
            HEIGHT - 20,
        ),
        radius=22,
        fill=PANEL,
        outline=BORDER,
        width=2,
    )

    # --------------------------------------------------------
    # FONTS
    # --------------------------------------------------------

    brand_font = limbo_font(
        30,
        bold=True,
    )

    small_font = limbo_font(
        24,
        bold=False,
    )

    small_bold = limbo_font(
        24,
        bold=True,
    )

    label_font = limbo_font(
        28,
        bold=True,
    )

    result_font = limbo_font(
        112,
        bold=True,
    )

    footer_font = limbo_font(
        20,
        bold=False,
    )

    # --------------------------------------------------------
    # HEADER
    # --------------------------------------------------------

    draw.text(
        (
            55,
            48,
        ),
        "CRYPTOBET",
        font=brand_font,
        fill=BLUE,
    )

    target_text = (
        f"Target: {target:.2f}x"
    )

    target_box = draw.textbbox(
        (
            0,
            0,
        ),
        target_text,
        font=small_bold,
    )

    target_width = (
        target_box[2]
        - target_box[0]
    )

    draw.text(
        (
            WIDTH - 55 - target_width,
            54,
        ),
        target_text,
        font=small_bold,
        fill=WHITE,
    )

    # --------------------------------------------------------
    # CENTER LABEL
    # --------------------------------------------------------

    crashed_text = (
        "CRASHED AT"
    )

    crashed_box = draw.textbbox(
        (
            0,
            0,
        ),
        crashed_text,
        font=label_font,
    )

    crashed_width = (
        crashed_box[2]
        - crashed_box[0]
    )

    draw.text(
        (
            (WIDTH - crashed_width) / 2,
            150,
        ),
        crashed_text,
        font=label_font,
        fill=MUTED,
    )

    # --------------------------------------------------------
    # RESULT MULTIPLIER
    # --------------------------------------------------------

    result_text = (
        f"{result:.2f}x"
    )

    result_box = draw.textbbox(
        (
            0,
            0,
        ),
        result_text,
        font=result_font,
    )

    result_width = (
        result_box[2]
        - result_box[0]
    )

    result_height = (
        result_box[3]
        - result_box[1]
    )

    result_color = (
        GREEN
        if won
        else RED
    )

    draw.text(
        (
            (WIDTH - result_width) / 2,
            205,
        ),
        result_text,
        font=result_font,
        fill=result_color,
    )

    # --------------------------------------------------------
    # PROGRESS BAR
    # --------------------------------------------------------
    #
    # Logarithmic scale keeps both small and very large
    # multipliers visually useful.
    # --------------------------------------------------------

    bar_x1 = 85
    bar_x2 = WIDTH - 85
    bar_y1 = 390
    bar_y2 = 412

    draw.rounded_rectangle(
        (
            bar_x1,
            bar_y1,
            bar_x2,
            bar_y2,
        ),
        radius=11,
        fill=BAR_BG,
    )

    try:
        import math

        # Display scale:
        # 1x -> start
        # 1,000,000x -> end
        result_float = max(
            1.0,
            float(result),
        )

        max_float = float(
            LIMBO_MAX_RESULT
        )

        log_min = math.log10(
            1.0
        )

        log_max = math.log10(
            max_float
        )

        log_value = math.log10(
            min(
                result_float,
                max_float,
            )
        )

        ratio = (
            (log_value - log_min)
            / (log_max - log_min)
        )

    except Exception:
        ratio = 0.0

    ratio = max(
        0.0,
        min(
            1.0,
            ratio,
        ),
    )

    marker_x = int(
        bar_x1
        + (
            (bar_x2 - bar_x1)
            * ratio
        )
    )

    # Green/red progress line.
    draw.rounded_rectangle(
        (
            bar_x1,
            bar_y1,
            marker_x,
            bar_y2,
        ),
        radius=11,
        fill=result_color,
    )

    # Marker.
    marker_radius = 15

    draw.ellipse(
        (
            marker_x - marker_radius,
            bar_y1 - 8,
            marker_x + marker_radius,
            bar_y2 + 8,
        ),
        fill=result_color,
        outline=WHITE,
        width=3,
    )

    # --------------------------------------------------------
    # RESULT STATUS
    # --------------------------------------------------------

    status_text = (
        "TARGET HIT"
        if won
        else "TARGET MISSED"
    )

    status_box = draw.textbbox(
        (
            0,
            0,
        ),
        status_text,
        font=small_bold,
    )

    status_width = (
        status_box[2]
        - status_box[0]
    )

    draw.text(
        (
            (WIDTH - status_width) / 2,
            455,
        ),
        status_text,
        font=small_bold,
        fill=result_color,
    )

    # --------------------------------------------------------
    # PROVABLY FAIR
    # --------------------------------------------------------

    fair_text = (
        "Provably fair result"
    )

    fair_box = draw.textbbox(
        (
            0,
            0,
        ),
        fair_text,
        font=footer_font,
    )

    fair_width = (
        fair_box[2]
        - fair_box[0]
    )

    draw.text(
        (
            (WIDTH - fair_width) / 2,
            525,
        ),
        fair_text,
        font=footer_font,
        fill=MUTED,
    )

    # --------------------------------------------------------
    # FOOTER
    # --------------------------------------------------------

    footer_text = (
        "CRYPTOBET LIMBO"
    )

    footer_box = draw.textbbox(
        (
            0,
            0,
        ),
        footer_text,
        font=footer_font,
    )

    footer_width = (
        footer_box[2]
        - footer_box[0]
    )

    draw.text(
        (
            (WIDTH - footer_width) / 2,
            580,
        ),
        footer_text,
        font=footer_font,
        fill=BORDER,
    )

    # --------------------------------------------------------
    # EXPORT
    # --------------------------------------------------------

    buffer = io.BytesIO()

    image.save(
        buffer,
        format="PNG",
        optimize=True,
    )

    buffer.seek(0)

    return discord.File(
        buffer,
        filename="limbo.png",
    )


# ============================================================
# /LIMBO
# ============================================================

@prefix_command(name="limbo")
async def limbo(
    interaction: discord.Interaction,
    amount: str,
    multi: str,
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

    # --------------------------------------------------------
    # GENERATE RESULT
    # --------------------------------------------------------

    result = limbo_result(
        server_seed,
        client_seed,
        nonce,
    )

    won = (
        result >= target
    )

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
    # RESULT EMBED
    # --------------------------------------------------------

    embed = base_embed(
        title=title,
        description=description,
        color=color,
    )

    embed.add_field(
        name="Game",
        value=f"`#{game_id}`",
        inline=True,
    )

    embed.add_field(
        name="RTP",
        value="**99.00%**",
        inline=True,
    )

    embed.add_field(
        name="House Edge",
        value="**1.00%**",
        inline=True,
    )

    embed.add_field(
        name="Provably Fair",
        value=(
            f"**Server Hash:** `{server_hash}`\n"
            f"**Client Seed:** `{client_seed}`\n"
            f"**Nonce:** `{nonce}`"
        ),
        inline=False,
    )

    embed.set_footer(
        text="Verify this result with .verify"
    )

    # --------------------------------------------------------
    # SEND
    # --------------------------------------------------------

    await interaction.response.send_message(
        embed=embed,
        file=file,
        ephemeral=False,
    )


# ============================================================
# END LIMBO
# ============================================================

# ============================================================
# /HOUSEADDFUND
# ============================================================

@prefix_command(name="houseaddfund")
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
