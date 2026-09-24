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
    color: int = 0x00E676,
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
        color=0x5865F2,
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
                ephemeral=True,
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
            ephemeral=True,
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
                ephemeral=True,
            )
            return False

        return True

    @discord.ui.button(
        label="LTC",
        style=discord.ButtonStyle.secondary,
        emoji="Ł",
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
        emoji="◎",
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
                ephemeral=True,
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
                ephemeral=True,
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
                range(25),
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


class MinesView(ButtonView):

    def __init__(
        self,
        game: MinesGame,
    ):
        super().__init__(timeout=300)

        self.game = game

        for index in range(25):

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

    async def cashout(
        self,
        interaction: discord.Interaction,
    ):

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

        self.http: Optional[aiohttp.ClientSession] = None

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

    async def get_user(
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

        row = await self.get_user(
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

        self.http = aiohttp.ClientSession()

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

        if self.http:
            await self.http.close()

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
                ephemeral=True,
            )

            return

        await self.safe_send(
            interaction,
            embed=error_embed(
                "Something went wrong",
                "Please try again in a moment.",
            ),
            ephemeral=True,
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
                ephemeral=True,
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
                ephemeral=True,
            )

        except discord.Forbidden:

            await interaction.response.send_message(
                "I couldn't DM you. Please enable DMs "
                "from this server and try again.",
                ephemeral=True,
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
                ephemeral=True,
            )

            return

        if amount is None:

            await interaction.response.send_message(
                "Enter a valid withdrawal amount.",
                ephemeral=True,
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
                ephemeral=True,
            )

            return

        if not self.valid_withdraw_address(
            currency,
            address,
        ):

            await interaction.response.send_message(
                "That withdrawal address is invalid.",
                ephemeral=True,
            )

            return

        balance = await self.get_balance(
            user_id
        )

        if amount > balance:

            await interaction.response.send_message(
                "You Dont Have Enough Crypto\n"
                "-# use /deposit to top-up Funds",
                ephemeral=True,
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
                    ephemeral=True,
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
                    ephemeral=True,
                )

                return

        await interaction.response.send_message(
            f"## Withdrawal Requested\n\n"
            f"**Amount:** {money(amount)}\n"
            f"**Currency:** {currency}\n"
            f"**Address:** `{address}`\n\n"
            "Your withdrawal is pending processing.",
            ephemeral=True,
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

        if not self.http:
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

        async with self.http.get(
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
            ephemeral=True,
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
            ephemeral=True,
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
            ephemeral=True,
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
        ephemeral=True,
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
        ephemeral=True,
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
    "`/race end` — End a wager race"
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
        ephemeral=True,
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
        ephemeral=True,
    )


# ============================================================
# /REWARDINFO
# ============================================================

@bot.tree.command(
    name="rewardinfo",
    description="View rewards and perks.",
)
async def rewardinfo_command(
    interaction: discord.Interaction,
):

    description = (
        "## Rakeback\n"
        "Receive **1% rakeback on losses**. "
        "Winning bets do not generate rakeback.\n\n"

        "## Lossback\n"
        "Promotional lossback may be provided during selected events.\n\n"

        "## Affiliates\n"
        "Earn a percentage from eligible referred-player activity. "
        "Use `/affiliateinfo` for the current rates.\n\n"

        "## Promo Codes\n"
        "Promo codes may require a deposit or wagering requirement. "
        "Each user can claim a code only once.\n\n"

        "## Wager Race\n"
        "Wager races track eligible wagering during the active race period. "
        "Race rankings are separate from lifetime wagering.\n\n"

        "## Deposits\n"
        "Promotional deposit bonuses may include 50%, 100%, or 200% offers. "
        "Each promotion can have its own wagering multiplier and maximum cashout.\n\n"

        "## Betting Limits\n"
        "The minimum standard bet is **$0.10**. "
        "Some games may use different minimums or limits.\n\n"

        "## Restrictions\n"
        "Withdrawal, tipping, and PvP restrictions may apply to promotional "
        "funds and accounts under review."
    )

    embed = base_embed(
        title="Rewards & Perks",
        description=description,
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True,
    )


# ============================================================
# /AFFILIATEINFO
# ============================================================

@bot.tree.command(
    name="affiliateinfo",
    description="View affiliate commission rates.",
)
async def affiliateinfo_command(
    interaction: discord.Interaction,
):

    description = (
        "## Affiliate Commission Rates\n\n"
        "**1+ referred players:** 0.10%\n"
        "**10+ referred players:** 0.20%\n"
        "**25+ referred players:** 0.35%\n"
        "**100+ referred players:** 0.50%\n\n"
        "Use `/affiliates` to view your referrals.\n"
        "Use `/affiliate-claim` to claim available earnings."
    )

    embed = base_embed(
        title="Affiliate Information",
        description=description,
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True,
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

    row = await bot.get_user(
        interaction.user.id
    )

    if not row:

        await interaction.response.send_message(
            "Your account could not be found.",
            ephemeral=True,
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
        ephemeral=True,
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


# ============================================================
# /HISTORY
# ============================================================

@bot.tree.command(
    name="history",
    description="View your last 10 games.",
)
async def history_command(
    interaction: discord.Interaction,
):

    if not await require_database(interaction):
        return

    rows = []

    if hasattr(
        bot.db,
        "game_history",
    ):

        rows = await bot.db.game_history(
            interaction.user.id,
            10,
        )

    elif hasattr(
        bot.db,
        "history",
    ):

        rows = await bot.db.history(
            interaction.user.id,
            10,
        )

    if not rows:

        description = (
            "You have no recorded games yet."
        )

    else:

        description = "\n".join(
            format_history_row(row)
            for row in rows
        )

    embed = base_embed(
        title="Game History",
        description=description,
    )

    embed.set_footer(
        text="last 10 Games history"
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True,
    )


# ============================================================
# /RANKS
# ============================================================

@bot.tree.command(
    name="ranks",
    description="View rank progression and rewards.",
)
async def ranks_command(
    interaction: discord.Interaction,
):

    lines = [
        "## Rank Progression",
        "",
    ]

    for rank in RANKS:

        label = rank_label(
            rank
        )

        lines.append(
            f"**{label}** · "
            f"Wager: {money(rank['wager'])} · "
            f"Reward: {money(rank['reward'])}"
        )

    embed = base_embed(
        title="Ranks",
        description="\n".join(lines),
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True,
    )


# ============================================================
# /RANK-REWARDS
# ============================================================

@bot.tree.command(
    name="rank-rewards",
    description="Claim an available rank reward.",
)
async def rank_rewards_command(
    interaction: discord.Interaction,
):

    if not await require_database(interaction):
        return

    if hasattr(
        bot.db,
        "claim_rank_reward",
    ):

        reward = await bot.db.claim_rank_reward(
            interaction.user.id,
            RANKS,
        )

        if reward:

            amount = D(
                reward
            )

            await interaction.response.send_message(
                embed=success_embed(
                    "Rank Reward Claimed",
                    f"You received **{money(amount)}**.",
                ),
                ephemeral=True,
            )

            return

    await interaction.response.send_message(
        embed=neutral_embed(
            "Rank Rewards",
            "You have no unclaimed rank rewards.",
        ),
        ephemeral=True,
    )


# ============================================================
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
        ephemeral=True,
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
                ephemeral=True,
            )

            return

    await interaction.response.send_message(
        embed=neutral_embed(
            "Affiliate Earnings",
            "You have $0 to claim.",
        ),
        ephemeral=True,
    )


# ============================================================
# END OF PART 2
# ============================================================

# ============================================================
# bot.py — PART 3 / 10
# ============================================================

# ============================================================
# /HELP
# ============================================================

@bot.tree.command(
    name="help",
    description="View all available commands."
)
async def help_command(
    interaction: discord.Interaction,
):

    text = (
        "## Commands\n\n"

        "### Games\n"
        "`/dice` — Start a dice game\n"
        "`/roll` — Roll your dice\n"
        "`/coinflip` — Play Red vs Blue coinflip\n"
        "`/mines` — Play Mines\n"
        "`/frog-run` — Play Frog Run\n"
        "`/bj` — Play Blackjack\n"
        "`/blackjack` — Play Blackjack\n\n"

        "### Wallet\n"
        "`/balance` — View your wallet\n"
        "`/deposit` — Deposit crypto\n"
        "`/withdraw` — Withdraw crypto\n"
        "`/tip` — Tip another user\n"
        "`/history` — View your game history\n\n"

        "### Rewards\n"
        "`/rakeback` — Claim your 1% loss rakeback\n"
        "`/ranks` — View ranks and rewards\n"
        "`/rank-rewards` — View or claim rank rewards\n"
        "`/affiliate` — View your affiliate information\n"
        "`/affiliates` — View affiliate information\n"
        "`/affiliate-claim` — Claim affiliate earnings\n"
        "`/claim` — Claim a promo code\n"
        "`/leaderboard` — View top wagerers\n"
        "`/race` — View the wager race\n\n"

        "### Rain\n"
        "`/rain` — Start a rain\n\n"

        "### Information\n"
        "`/stats` — View your stats\n"
        "`/howtoplay` — Learn how to play\n"
        "`/rewardinfo` — View rewards and perks\n"
        "`/affiliateinfo` — View affiliate rates\n"
        "`/fair` — View provably fair information\n"
        "`/provably-fair` — Verify a game\n\n"

        "### Private Channels\n"
        "`/private-channel` — Create a private channel\n\n"

        "### Utilities\n"
        "`/retrigger` — Retrigger a stuck game\n"
        "`/fix-dice` — Recover a dice game"
    )

    await interaction.response.send_message(
        embed=base_embed(
            "Help",
            text,
            0x00E676,
        ),
        ephemeral=True,
    )


# ============================================================
# /HOWTOPLAY
# ============================================================

@bot.tree.command(
    name="howtoplay",
    description="Learn how the casino works."
)
async def howtoplay(
    interaction: discord.Interaction,
):

    text = (
        "## How To Play\n\n"

        "### Getting Started\n"
        "Fund your wallet using `/deposit`.\n"
        "Supported crypto networks include **LTC, ETH, USDT and SOL** "
        "where available.\n\n"

        "Use `/balance` to view your current USD balance.\n\n"

        "### Dice\n"
        "Use `/dice <amount>` to select your dice mode.\n"
        "Then use `/roll` to roll your selected dice.\n\n"
        "Available modes:\n"
        "• Normal Dice — highest total wins\n"
        "• Crazy Dice — lowest total wins\n"
        "• 1 Dice\n"
        "• 2 Dice\n"
        "• 3 Dice\n\n"

        "### Coinflip\n"
        "Use `/coinflip <amount> <color>`.\n"
        "Choose **Red** or **Blue**.\n"
        "A winning side pays **1.92x** the stake.\n\n"

        "### Mines\n"
        "Use `/mines <amount> <mines>`.\n"
        "Open tiles to increase your multiplier.\n"
        "Find a gem to continue.\n"
        "Hit a bomb and the game ends.\n"
        "You can cash out before hitting a bomb.\n\n"

        "### Frog Run\n"
        "Use `/frog-run` to start Frog Run.\n"
        "Advance through the board while avoiding losing positions.\n"
        "Cash out before the run ends.\n\n"

        "### Blackjack\n"
        "Blackjack uses standard blackjack gameplay.\n"
        "Get closer to 21 than the dealer without going over.\n"
        "Natural blackjack pays according to the configured game rules.\n\n"
        "Optional side bets:\n"
        "• 21+3\n"
        "• Perfect Pairs\n"
        "• Insurance\n\n"
        "Games that remain inactive for one hour may be auto-closed.\n"
        "Use `/retrigger` if a game message needs to be restored.\n\n"

        "### Withdrawals\n"
        "Use `/withdraw` to request a crypto withdrawal.\n"
        "Always verify the address and network before submitting.\n\n"

        "### Rain\n"
        "Rains distribute a specified amount between eligible users.\n"
        "You must have the required verified role and wager at least "
        "**$1 daily** to participate.\n\n"

        "### Private Channels\n"
        "Private channels require a **$25 balance**.\n"
        "A private channel may automatically close if the balance remains "
        "below $25 for 10 minutes.\n\n"

        "### Handy Commands\n"
        "`/stats` — Your account statistics\n"
        "`/history` — Your recent games\n"
        "`/leaderboard` — Top wagerers\n"
        "`/fair` — Provably fair verification"
    )

    await interaction.response.send_message(
        embed=base_embed(
            "How To Play",
            text,
            0x00E676,
        ),
        ephemeral=True,
    )


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
        ephemeral=True,
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
        ephemeral=True,
    )


# ============================================================
# /BALANCE
# ============================================================

@bot.tree.command(
    name="balance",
    description="View your wallet balance."
)
async def balance_command(
    interaction: discord.Interaction,
):

    user_id = interaction.user.id

    await bot.db.ensure(
        user_id
    )

    balance = await bot.get_balance(
        user_id
    )

    text = (
        f"## {interaction.user.display_name}'s Wallet\n\n"
        f"**Balance:** {money(balance)}"
    )

    await interaction.response.send_message(
        content=text,
        view=WalletView(
            bot,
            user_id,
        ),
    )


# ============================================================
# /DEPOSIT
# ============================================================

@bot.tree.command(
    name="deposit",
    description="Choose a cryptocurrency to deposit."
)
async def deposit_command(
    interaction: discord.Interaction,
):

    await bot.db.ensure(
        interaction.user.id
    )

    await interaction.response.send_message(
        content="Choose a currency Below",
        view=DepositCurrencyView(
            bot,
            interaction.user.id,
        ),
        ephemeral=True,
    )


# ============================================================
# /STATS
# ============================================================

@bot.tree.command(
    name="stats",
    description="View your account statistics."
)
async def stats_command(
    interaction: discord.Interaction,
):

    user_id = interaction.user.id

    row = await bot.get_user(
        user_id
    )

    if not row:
        await bot.db.ensure(
            user_id
        )
        row = await bot.get_user(
            user_id
        )

    balance = D(row["balance"])
    wagered = D(row["wagered"])
    deposited = D(
        row["lifetime_deposit"]
    )

    withdrawn = Decimal("0")

    if hasattr(
        bot.db,
        "total_withdrawn",
    ):
        withdrawn = D(
            await bot.db.total_withdrawn(
                user_id
            )
        )

    rank_index = 0

    for index, rank in enumerate(RANKS):

        if wagered >= rank["wager"]:
            rank_index = index

    current_rank = RANKS[
        rank_index
    ]

    if rank_index + 1 < len(RANKS):

        next_rank = RANKS[
            rank_index + 1
        ]

        needed = max(
            Decimal("0"),
            next_rank["wager"] - wagered,
        )

        next_stage = (
            f"wager {money(needed)} more "
            f"to reach **{next_rank['name']}"
        )

        if next_rank["stage"]:
            next_stage += (
                f" Stage {next_rank['stage']}"
            )

        next_stage += "**"

    else:

        next_stage = (
            "You have reached the highest rank."
        )

    stage_text = (
        f"{current_rank['name']}"
    )

    if current_rank["stage"]:
        stage_text += (
            f" **Stage {current_rank['stage']}**"
        )

    text = (
        f"## {interaction.user.display_name}'s Stats\n\n"
        f"**Balance:** {money(balance)}\n"
        f"**Rank:** **{stage_text}**\n"
        f"**Total Wagered:** {money(wagered)}\n"
        f"**Total Deposited:** {money(deposited)}\n"
        f"**Total Withdrawn:** {money(withdrawn)}\n"
        f"**Next Stage:** {next_stage}"
    )

    await interaction.response.send_message(
        embed=base_embed(
            None,
            text,
            0x00E676,
        ),
        ephemeral=True,
    )


# ============================================================
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
        ephemeral=True,
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
            ephemeral=True,
        )
        return

    if user.id == sender_id:
        await interaction.response.send_message(
            "You cannot tip yourself.",
            ephemeral=True,
        )
        return

    value = normalize_amount(
        amount
    )

    if value is None:
        await interaction.response.send_message(
            "Enter a valid amount such as `1`, `1$`, `0.10`, or `0.10$`.",
            ephemeral=True,
        )
        return

    if value <= 0:
        await interaction.response.send_message(
            "The tip must be greater than $0.",
            ephemeral=True,
        )
        return

    sender_balance = await bot.get_balance(
        sender_id
    )

    if value > sender_balance:
        await interaction.response.send_message(
            "You Dont Have Enough Crypto\n"
            "-# use /deposit to top-up Funds",
            ephemeral=True,
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
                    ephemeral=True,
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
# /RAKEBACK
# ============================================================

@bot.tree.command(
    name="rakeback",
    description="Claim your available 1% loss rakeback."
)
async def rakeback_command(
    interaction: discord.Interaction,
):

    user_id = interaction.user.id

    row = await bot.get_user(
        user_id
    )

    available = (
        D(row["rakeback"])
        if row
        else Decimal("0")
    )

    if available <= 0:

        await interaction.response.send_message(
            "You Dont have any rakeback avalable . "
            "try again later",
            ephemeral=True,
        )

        return

    if hasattr(
        bot.db,
        "claim_rakeback",
    ):

        claimed = D(
            await bot.db.claim_rakeback(
                user_id
            )
        )

    else:

        async with bot.db.pool.acquire() as connection:

            async with connection.transaction():

                row = await connection.fetchrow(
                    """
                    UPDATE users
                    SET rakeback = 0,
                        balance = balance + $2
                    WHERE user_id = $1
                      AND rakeback > 0
                    RETURNING rakeback
                    """,
                    user_id,
                    available,
                )

                if not row:
                    claimed = Decimal("0")
                else:
                    claimed = available

                if claimed > 0:

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
                            'rakeback',
                            $2,
                            'Rakeback claim'
                        )
                        """,
                        user_id,
                        claimed,
                    )

    if claimed <= 0:

        await interaction.response.send_message(
            "You Dont have any rakeback avalable . "
            "try again later",
            ephemeral=True,
        )

        return

    await interaction.response.send_message(
        embed=success_embed(
            "Rakeback Claimed",
            f"You claimed **{money(claimed)}** "
            "in rakeback.",
        ),
        ephemeral=True,
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
        ephemeral=True,
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

    row = await bot.get_user(
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
            ephemeral=True,
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
        ephemeral=True,
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
                ephemeral=True,
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
                rank["reward"],
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
                ephemeral=True,
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
            ephemeral=True,
        )

        return

    if index in game.opened:

        await interaction.response.send_message(
            "That tile is already open.",
            ephemeral=True,
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
            ephemeral=True,
        )

        return

    if not game.opened:

        await interaction.response.send_message(
            "Open at least one safe tile before cashing out.",
            ephemeral=True,
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
            ephemeral=True,
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
            ephemeral=True,
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
            ephemeral=True,
        )

        return

    if interaction.user.id in bot.active_mines:

        await bot.safe_send(
            interaction,
            content=(
                "You already have an active Mines game."
            ),
            ephemeral=True,
        )

        return

    if mines >= 25:
        await bot.safe_send(
            interaction,
            content="Choose between 1 and 20 mines.",
            ephemeral=True,
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
            ephemeral=True,
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
# COINFLIP
# ============================================================

def coinflip_roll(
    bot_instance: CasinoBot,
    server_seed: str,
    client_seed: str,
    nonce: int,
) -> Decimal:

    return bot_instance.fair_roll(
        server_seed,
        client_seed,
        nonce,
        "coinflip",
    )


async def coinflip_finish(
    bot_instance: CasinoBot,
    interaction: discord.Interaction,
    *,
    user_id: int,
    bet: Decimal,
    choice: str,
    game_id: int,
    server_seed: str,
    server_hash: str,
    client_seed: str,
    nonce: int,
):

    roll = coinflip_roll(
        bot_instance,
        server_seed,
        client_seed,
        nonce,
    )

    result = (
        "red"
        if roll < Decimal("50")
        else "blue"
    )

    won = (
        result == choice
    )

    if won:

        payout = (
            bet * COINFLIP_MULTIPLIER
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_DOWN,
        )

        await bot_instance.settle_win(
            user_id,
            bet,
            payout,
            "coinflip",
        )

        color = 0x57F287

        title = (
            f"## Coinflip — "
            f"{result.title()} wins!"
        )

        description = (
            f"**Roll:** `{roll:.2f}`\n"
            f"**Result:** **{result.title()}**\n"
            f"**Bet:** {money(bet)}\n"
            f"**Payout:** {money(payout)} "
            f"({COINFLIP_MULTIPLIER:.2f}x)"
        )

    else:

        await bot_instance.settle_loss(
            user_id,
            bet,
            "coinflip",
        )

        color = 0xED4245

        title = (
            f"## Coinflip — "
            f"{result.title()} wins!"
        )

        description = (
            f"**Roll:** `{roll:.2f}`\n"
            f"**Result:** **{result.title()}**\n"
            f"**Bet:** {money(bet)}\n"
            f"**Lost:** {money(bet)}"
        )

    embed = base_embed(
        title,
        description,
        color,
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

    embed.add_field(
        name="Game",
        value=f"`#{game_id}`",
        inline=True,
    )

    await interaction.edit_original_response(
        embed=embed,
    )

    await bot_instance.check_rank_up(
        user_id
    )


@bot.tree.command(
    name="coinflip",
    description="Bet on Red or Blue in a coinflip.",
)
@app_commands.describe(
    amount="Bet amount in USD.",
    color="Choose red or blue.",
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
async def coinflip_command(
    interaction: discord.Interaction,
    amount: str,
    color: app_commands.Choice[str],
):

    cooldown = bot.check_game_cooldown(
        interaction.user.id,
        "coinflip",
    )

    if cooldown:

        await bot.safe_send(
            interaction,
            content=(
                f"Please wait **{cooldown:.1f}s**."
            ),
            ephemeral=True,
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
            ephemeral=True,
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
            ephemeral=True,
        )

        return

    deducted = await bot.deduct_bet(
        interaction.user.id,
        bet,
        "coinflip",
    )

    if not deducted:

        await bot.safe_send(
            interaction,
            content="Your balance changed. Please try again.",
            ephemeral=True,
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

    selected = color.value.lower()

    embed = base_embed(
        "## Flipping…",
        (
            f"{interaction.user.mention} "
            f"({selected.title()}) vs Bot "
            f"({('Blue' if selected == 'red' else 'Red')})\n\n"
            f"**Bet:** {money(bet)} · "
            f"**Game #{game_id}**"
        ),
        0x5865F2,
    )

    embed.add_field(
        name="Provably Fair",
        value=(
            f"Server Hash: `{server_hash}`"
        ),
        inline=False,
    )

    await interaction.response.send_message(
        embed=embed
    )

    await asyncio.sleep(2)

    await coinflip_finish(
        bot,
        interaction,
        user_id=interaction.user.id,
        bet=bet,
        choice=selected,
        game_id=game_id,
        server_seed=server_seed,
        server_hash=server_hash,
        client_seed=client_seed,
        nonce=nonce,
    )


# ============================================================
# COINFLIP STICKER CONFIG
# ============================================================

@bot.tree.command(
    name="cfred",
    description="Configure the Red coinflip sticker ID.",
)
@app_commands.describe(
    sticker_id="Discord sticker ID.",
)
async def cfred_command(
    interaction: discord.Interaction,
    sticker_id: str,
):

    if interaction.user.id not in config.ADMIN_USER_IDS:

        await bot.safe_send(
            interaction,
            content="You are not authorized to use this command.",
            ephemeral=True,
        )

        return

    await bot.db.set_setting(
        "coinflip_sticker_red",
        sticker_id.strip(),
    )

    await bot.safe_send(
        interaction,
        content=(
            f"Red coinflip sticker saved: `{sticker_id}`"
        ),
        ephemeral=True,
    )


@bot.tree.command(
    name="cfblue",
    description="Configure the Blue coinflip sticker ID.",
)
@app_commands.describe(
    sticker_id="Discord sticker ID.",
)
async def cfblue_command(
    interaction: discord.Interaction,
    sticker_id: str,
):

    if interaction.user.id not in config.ADMIN_USER_IDS:

        await bot.safe_send(
            interaction,
            content="You are not authorized to use this command.",
            ephemeral=True,
        )

        return

    await bot.db.set_setting(
        "coinflip_sticker_blue",
        sticker_id.strip(),
    )

    await bot.safe_send(
        interaction,
        content=(
            f"Blue coinflip sticker saved: `{sticker_id}`"
        ),
        ephemeral=True,
    )


# ============================================================
# DICE
# ============================================================

def dice_mode_name(
    mode: str,
    count: int,
) -> str:

    if mode == "crazy":
        return f"{count} Roll{'s' if count != 1 else ''} (Crazy)"

    return f"{count} Roll{'s' if count != 1 else ''} (Normal)"


def dice_game_embed(
    game: dict,
    *,
    final: bool = False,
) -> discord.Embed:

    player_rolls = game.get(
        "player_rolls",
        [],
    )

    bot_rolls = game.get(
        "bot_rolls",
        [],
    )

    player_text = " + ".join(
        "?" if value is None else str(value)
        for value in player_rolls
    )

    bot_text = " + ".join(
        "?" if value is None else str(value)
        for value in bot_rolls
    )

    player_total = (
        sum(
            value
            for value in player_rolls
            if value is not None
        )
        if player_rolls
        else 0
    )

    bot_total = (
        sum(
            value
            for value in bot_rolls
            if value is not None
        )
        if bot_rolls
        else 0
    )

    title = (
        "## Dice"
        if not final
        else "## Dice — Result"
    )

    if final:

        if player_total > bot_total:
            result = (
                f"🎉 {game['user_mention']} wins!"
            )
            color = 0x57F287

        elif player_total < bot_total:
            result = "❌ Bot wins!"
            color = 0xED4245

        else:
            result = "🤝 Tie!"
            color = 0xFEE75C

    else:

        result = (
            f"**{game['user_mention']}** vs Bot"
        )

        color = 0x5865F2

    description = (
        f"**Mode:** "
        f"{dice_mode_name(game['mode'], game['count'])}\n"
        f"**Bet:** {money(game['bet'])}\n\n"
        f"{game['user_mention']}: "
        f"{player_text} = **{player_total}**\n"
        f"Bot: {bot_text} = **{bot_total}**"
    )

    if final:
        description += (
            f"\n\n{result}\n"
            f"**Bet:** {money(game['bet'])}"
        )

        if player_total > bot_total:
            description += (
                f"\n**Payout:** "
                f"{money(game['payout'])}"
            )

        elif player_total < bot_total:
            description += (
                f"\n**Lost:** "
                f"{money(game['bet'])}"
            )

    embed = base_embed(
        title,
        description,
        color,
    )

    embed.set_footer(
        text=(
            f"Game #{game['game_id']} • "
            "Provably fair"
        )
    )

    if game.get("server_hash"):
        embed.add_field(
            name="Provably Fair",
            value=(
                f"Server hash: "
                f"`{game['server_hash']}`"
            ),
            inline=False,
        )

    return embed


@bot.tree.command(
    name="dice",
    description="Set up a Dice game.",
)
@app_commands.describe(
    amount="Bet amount in USD.",
)
async def dice_command(
    interaction: discord.Interaction,
    amount: str,
):

    bet = normalize_amount(amount)

    if bet is None or bet < MIN_BET:

        await bot.safe_send(
            interaction,
            content=(
                f"Minimum bet is {money(MIN_BET)}."
            ),
            ephemeral=True,
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
            ephemeral=True,
        )

        return

    await interaction.response.send_message(
        (
            "**Choose Dice Mode**\n\n"
            "**Crazy Dice**\n"
            "Lowest Wins\n\n"
            "**Dice**\n"
            "Highest Wins"
        ),
        view=DiceSetupView(
            bot,
            interaction.user.id,
            bet,
        ),
        ephemeral=True,
    )


async def start_dice_game(
    self: CasinoBot,
    interaction: discord.Interaction,
    user_id: int,
    amount: Decimal,
    mode: str,
    count: int,
):

    if user_id in self.active_dice:

        await interaction.followup.send(
            "You already have an active Dice game.",
            ephemeral=True,
        )

        return

    deducted = await self.deduct_bet(
        user_id,
        amount,
        "dice",
    )

    if not deducted:

        await interaction.followup.send(
            "Your balance changed. Please try again.",
            ephemeral=True,
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

    game = {
        "user_id": user_id,
        "user_mention": interaction.user.mention,
        "bet": amount,
        "mode": mode,
        "count": count,
        "game_id": game_id,
        "server_seed": server_seed,
        "server_hash": server_hash,
        "client_seed": client_seed,
        "nonce": 0,
        "player_rolls": [None] * count,
        "bot_rolls": [None] * count,
        "current_roll": 0,
        "channel_id": interaction.channel_id,
        "message_id": None,
        "payout": Decimal("0"),
    }

    self.active_dice[user_id] = game

    await interaction.followup.send(
        embed=dice_game_embed(game),
        view=DiceRollView(
            self,
            user_id,
        ),
    )

    message = await interaction.original_response()

    game["message_id"] = message.id


CasinoBot.start_dice_game = start_dice_game


class DiceRollView(ButtonView):

    def __init__(
        self,
        bot_instance: CasinoBot,
        user_id: int,
    ):

        super().__init__(timeout=300)

        self.bot_instance = bot_instance
        self.user_id = user_id

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:

        if interaction.user.id != self.user_id:

            await interaction.response.send_message(
                "This Dice game belongs to another player.",
                ephemeral=True,
            )

            return False

        return True

    @discord.ui.button(
        label="Roll",
        style=discord.ButtonStyle.success,
        custom_id="dice_roll_button",
    )
    async def roll(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await self.bot_instance.roll_dice_game(
            interaction,
            self.user_id,
        )


async def roll_dice_game(
    self: CasinoBot,
    interaction: discord.Interaction,
    user_id: int,
):

    game = self.active_dice.get(
        user_id
    )

    if not game:

        await interaction.response.send_message(
            "You don't have an active Dice game.",
            ephemeral=True,
        )

        return

    await interaction.response.defer()

    index = game["current_roll"]

    if index >= game["count"]:
        return

    player_roll = self.fair_int(
        game["server_seed"],
        game["client_seed"],
        game["nonce"] + index,
        1,
        6,
        "dice-player",
    )

    game["player_rolls"][index] = player_roll

    game["current_roll"] += 1

    if game["current_roll"] < game["count"]:

        await interaction.edit_original_response(
            embed=dice_game_embed(game),
            view=DiceRollView(
                self,
                user_id,
            ),
        )

        return

    for bot_index in range(
        game["count"]
    ):

        game["bot_rolls"][bot_index] = self.fair_int(
            game["server_seed"],
            game["client_seed"],
            game["nonce"] + 100 + bot_index,
            1,
            6,
            "dice-bot",
        )

    player_total = sum(
        game["player_rolls"]
    )

    bot_total = sum(
        game["bot_rolls"]
    )

    if game["mode"] == "crazy":

        won = player_total < bot_total

    else:

        won = player_total > bot_total

    if player_total == bot_total:
        won = False

    if won:

        payout = (
            game["bet"]
            * DICE_MULTIPLIER
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_DOWN,
        )

        game["payout"] = payout

        await self.settle_win(
            user_id,
            game["bet"],
            payout,
            "dice",
        )

    else:

        await self.settle_loss(
            user_id,
            game["bet"],
            "dice",
        )

    game["finished"] = True

    self.active_dice.pop(
        user_id,
        None,
    )

    await interaction.edit_original_response(
        embed=dice_game_embed(
            game,
            final=True,
        ),
        view=None,
    )

    await self.check_rank_up(
        user_id
    )


CasinoBot.roll_dice_game = roll_dice_game


@bot.tree.command(
    name="roll",
    description="Roll your active Dice game.",
)
async def roll_command(
    interaction: discord.Interaction,
):

    await bot.roll_dice_game(
        interaction,
        interaction.user.id,
    )


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

    row = await bot_instance.get_user(
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
            ephemeral=True,
        )

        return

    if not await has_rain_role(
        interaction
    ):

        await interaction.response.send_message(
            "You need the verified role to join rain.",
            ephemeral=True,
        )

        return

    wagered = await rain_daily_wager(
        self,
        interaction.user.id,
    )

    if wagered < Decimal("1"):

        await interaction.response.send_message(
            "You need at least **$1** wagered today to join rain.",
            ephemeral=True,
        )

        return

    if interaction.user.id in rain["players"]:

        await interaction.response.send_message(
            "You already joined this rain.",
            ephemeral=True,
        )

        return

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
            ephemeral=True,
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
            ephemeral=True,
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
            ephemeral=True,
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
