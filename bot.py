# ============================================================
# BOT.PY
# PART 1 / 6
# ============================================================

from __future__ import annotations

import asyncio
import hashlib
import io
import os
import random
import secrets
import time

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import aiohttp
import discord

from discord.ext import commands

from PIL import Image, ImageDraw, ImageFont

import config

from database import Database

from games import (
    card_value,
    deck,
    hand_total,
    parse_amount,
    provably_fair,
)


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent


# ============================================================
# BASIC HELPERS
# ============================================================

def money(value) -> str:
    return f"{float(value):,.2f}"


def usd(points) -> str:
    return (
        f"${float(points) * config.POINT_USD:,.2f}"
    )


def brand(
    title: str,
    description: str = "",
    colour=0x2B2D31,
):
    return discord.Embed(
        title=f"{config.CASINO_NAME} — {title}",
        description=description,
        colour=colour,
        timestamp=datetime.now(timezone.utc),
    )


def allowed_admin(ctx) -> bool:
    return (
        ctx.author.id in config.ADMIN_USER_IDS
        or ctx.author.guild_permissions.administrator
    )


# ============================================================
# GAME SETTINGS
# ============================================================

MINIMUM_BET = Decimal("20")

COINFLIP_MULTIPLIER = Decimal("1.96")

CRAZY_DICE_HIGH_LOW_MULTIPLIER = Decimal("1.96")

CRAZY_DICE_TIE_MULTIPLIERS = {
    1: Decimal("5"),
    3: Decimal("7"),
    6: Decimal("9"),
}


# ============================================================
# IMAGE HELPERS
# ============================================================

def image_file(
    image: Image.Image,
    filename: str,
) -> discord.File:

    output = io.BytesIO()

    image.save(
        output,
        "PNG",
    )

    output.seek(0)

    return discord.File(
        output,
        filename=filename,
    )


def load_font(
    size: int = 42,
    bold: bool = False,
):

    if bold:

        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
            str(
                BASE_DIR / "DejaVuSans-Bold.ttf"
            ),
        ]

    else:

        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
            str(
                BASE_DIR / "DejaVuSans.ttf"
            ),
        ]

    for path in candidates:

        try:

            return ImageFont.truetype(
                path,
                size,
            )

        except OSError:
            continue

    return ImageFont.load_default()


# ============================================================
# COINFLIP IMAGE URLS
# ============================================================

COINFLIP_IMAGES = {
    "heads": (
        "https://cdn.bloxjack.com/assets/"
        "chip-heads-v2.webp?v=20260826-1"
    ),

    "tails": (
        "https://cdn.bloxjack.com/assets/"
        "chip-tails-v2.webp?v=20260826-1"
    ),
}


# ============================================================
# COINFLIP RESULT IMAGE
# ============================================================

def create_coinflip_image(
    result: str,
) -> discord.File:

    result = result.lower()

    WIDTH = 1000
    HEIGHT = 500

    image = Image.new(
        "RGB",
        (WIDTH, HEIGHT),
        "#0a0d14",
    )

    draw = ImageDraw.Draw(image)

    # --------------------------------------------------------
    # Background
    # --------------------------------------------------------

    for y in range(HEIGHT):

        ratio = y / HEIGHT

        r = int(10 + 10 * ratio)
        g = int(13 + 12 * ratio)
        b = int(20 + 18 * ratio)

        draw.line(
            [
                (0, y),
                (WIDTH, y),
            ],
            fill=(r, g, b),
        )

    # --------------------------------------------------------
    # Decorative lines
    # --------------------------------------------------------

    for x in range(-HEIGHT, WIDTH, 80):

        draw.line(
            [
                (x, HEIGHT),
                (x + HEIGHT, 0),
            ],
            fill=(28, 34, 48),
            width=2,
        )

    # --------------------------------------------------------
    # Main card
    # --------------------------------------------------------

    draw.rounded_rectangle(
        (
            50,
            40,
            WIDTH - 50,
            HEIGHT - 40,
        ),
        radius=35,
        fill="#151b28",
        outline="#39445a",
        width=3,
    )

    # --------------------------------------------------------
    # Title
    # --------------------------------------------------------

    title_font = load_font(
        42,
        True,
    )

    title = result.upper()

    bbox = draw.textbbox(
        (0, 0),
        title,
        font=title_font,
    )

    title_width = (
        bbox[2] - bbox[0]
    )

    draw.text(
        (
            (WIDTH - title_width) // 2,
            65,
        ),
        title,
        font=title_font,
        fill="#f1f5f9",
    )

    # --------------------------------------------------------
    # Coin image
    # --------------------------------------------------------

    coin_url = COINFLIP_IMAGES.get(
        result
    )

    # The actual remote image is downloaded later by the
    # async image function. This function creates the fallback
    # visual if the remote image is unavailable.
    #
    # Keep the result image generation self-contained.

    center_x = WIDTH // 2
    center_y = 275

    radius = 120

    draw.ellipse(
        (
            center_x - radius,
            center_y - radius,
            center_x + radius,
            center_y + radius,
        ),
        fill="#d6ad54",
        outline="#f6e7b2",
        width=6,
    )

    coin_font = load_font(
        60,
        True,
    )

    coin_text = (
        "H"
        if result == "heads"
        else "T"
    )

    bbox = draw.textbbox(
        (0, 0),
        coin_text,
        font=coin_font,
    )

    text_width = (
        bbox[2] - bbox[0]
    )

    text_height = (
        bbox[3] - bbox[1]
    )

    draw.text(
        (
            center_x - text_width // 2,
            center_y - text_height // 2 - 8,
        ),
        coin_text,
        font=coin_font,
        fill="#171717",
    )

    # --------------------------------------------------------
    # Bottom text
    # --------------------------------------------------------

    bottom_font = load_font(
        22,
        False,
    )

    bottom = (
        "HEADS"
        if result == "heads"
        else "TAILS"
    )

    bbox = draw.textbbox(
        (0, 0),
        bottom,
        font=bottom_font,
    )

    bottom_width = (
        bbox[2] - bbox[0]
    )

    draw.text(
        (
            (WIDTH - bottom_width) // 2,
            425,
        ),
        bottom,
        font=bottom_font,
        fill="#aeb8ca",
    )

    return image_file(
        image,
        f"coinflip_{result}.png",
    )


# ============================================================
# COINFLIP REMOTE IMAGE
# ============================================================

async def download_coin_image(
    result: str,
) -> discord.File | None:

    url = COINFLIP_IMAGES.get(
        result
    )

    if not url:
        return None

    try:

        timeout = aiohttp.ClientTimeout(
            total=10
        )

        async with aiohttp.ClientSession(
            timeout=timeout
        ) as session:

            async with session.get(
                url
            ) as response:

                if response.status != 200:
                    return None

                data = await response.read()

        image = Image.open(
            io.BytesIO(data)
        ).convert("RGBA")

        # ----------------------------------------------------
        # Put remote coin image onto a clean canvas.
        # ----------------------------------------------------

        WIDTH = 1000
        HEIGHT = 500

        canvas = Image.new(
            "RGBA",
            (WIDTH, HEIGHT),
            "#0a0d14",
        )

        draw = ImageDraw.Draw(
            canvas
        )

        # Background lines.

        for x in range(
            -HEIGHT,
            WIDTH,
            80,
        ):

            draw.line(
                [
                    (x, HEIGHT),
                    (x + HEIGHT, 0),
                ],
                fill="#1c2230",
                width=2,
            )

        # Card.

        draw.rounded_rectangle(
            (
                50,
                40,
                WIDTH - 50,
                HEIGHT - 40,
            ),
            radius=35,
            fill="#151b28",
            outline="#39445a",
            width=3,
        )

        # Title.

        title_font = load_font(
            42,
            True,
        )

        title = result.upper()

        bbox = draw.textbbox(
            (0, 0),
            title,
            font=title_font,
        )

        title_width = (
            bbox[2] - bbox[0]
        )

        draw.text(
            (
                (WIDTH - title_width) // 2,
                65,
            ),
            title,
            font=title_font,
            fill="#f1f5f9",
        )

        # Resize remote image.

        image.thumbnail(
            (260, 260),
            Image.Resampling.LANCZOS,
        )

        x = (
            WIDTH - image.width
        ) // 2

        y = 130

        canvas.alpha_composite(
            image,
            (
                x,
                y,
            ),
        )

        # Bottom text.

        bottom_font = load_font(
            22,
            False,
        )

        bottom = result.upper()

        bbox = draw.textbbox(
            (0, 0),
            bottom,
            font=bottom_font,
        )

        bottom_width = (
            bbox[2] - bbox[0]
        )

        draw.text(
            (
                (WIDTH - bottom_width) // 2,
                425,
            ),
            bottom,
            font=bottom_font,
            fill="#aeb8ca",
        )

        output = io.BytesIO()

        canvas.convert(
            "RGB"
        ).save(
            output,
            "PNG",
        )

        output.seek(0)

        return discord.File(
            output,
            filename=f"coinflip_{result}.png",
        )

    except Exception as error:

        print(
            "[Coinflip Image Error]",
            repr(error),
        )

        return None


# ============================================================
# COINFLIP RESULT IMAGE
# ============================================================

async def coinflip_result_image(
    result: str,
) -> discord.File:

    remote = await download_coin_image(
        result
    )

    if remote is not None:
        return remote

    return create_coinflip_image(
        result
    )


# ============================================================
# GLOBAL GAME HELPERS
# ============================================================

def minimum_bet_error() -> str:

    return (
        "The minimum bet is "
        "**20 points ($0.10)**."
    )


def valid_bet(
    amount,
) -> bool:

    return (
        Decimal(str(amount))
        >= MINIMUM_BET
    )


async def resolve_bet(
    user_id: int,
    bet: str,
):

    bet = bet.strip().lower()

    if bet in (
        "half",
        "all",
        "max",
    ):

        row = await bot.db.user(
            user_id
        )

        if not row:
            raise ValueError(
                "Your account could not be found."
            )

        balance = row["balance"]

        if bet in (
            "all",
            "max",
        ):

            amount = parse_amount(
                str(balance)
            )

        else:

            half = (
                Decimal(str(balance))
                / Decimal("2")
            )

            amount = parse_amount(
                str(half)
            )

    else:

        amount = parse_amount(
            bet
        )

    if not valid_bet(amount):

        raise ValueError(
            minimum_bet_error()
        )

    return amount


# ============================================================
# CASINO BOT
# ============================================================

class CasinoBot(commands.Bot):

    def __init__(self):

        intents = discord.Intents.default()

        intents.message_content = True
        intents.members = True

        super().__init__(
            command_prefix=lambda bot, message: (
                ".",
                ",",
            ),
            intents=intents,
            help_command=None,
        )

        self.db = (
            Database(
                config.DATABASE_URL
            )
            if config.DATABASE_URL
            else None
        )

        self.cooldowns: dict[
            int,
            float,
        ] = {}

        self.winlog_channel_id = None

    # --------------------------------------------------------
    # STARTUP
    # --------------------------------------------------------

    async def setup_hook(self):

        if not self.db:

            raise RuntimeError(
                "DATABASE_URL is missing "
                "from Railway variables."
            )

        await self.db.connect()

        # ----------------------------------------------------
        # Load win log channel.
        # ----------------------------------------------------

        try:

            saved_channel = await self.db.setting(
                "winlog_channel_id",
                "",
            )

            if saved_channel:

                self.winlog_channel_id = int(
                    saved_channel
                )

        except Exception as error:

            print(
                "[WinLog Load Error]",
                repr(error),
            )

    # --------------------------------------------------------
    # CLOSE
    # --------------------------------------------------------

    async def close(self):

        if self.db:

            await self.db.close()

        await super().close()

    # --------------------------------------------------------
    # GAME COOLDOWN
    # --------------------------------------------------------

    async def game_allowed(
        self,
        ctx,
    ) -> bool:

        try:

            frozen = await self.db.setting(
                "frozen",
                "0",
            )

            if frozen == "1":

                await ctx.send(
                    embed=brand(
                        "Games Frozen",
                        "Games are temporarily unavailable.",
                        0xED4245,
                    )
                )

                return False

        except Exception:
            pass

        now = time.monotonic()

        previous = self.cooldowns.get(
            ctx.author.id,
            0,
        )

        elapsed = now - previous

        if (
            elapsed
            < config.GAME_COOLDOWN_SECONDS
        ):

            remaining = (
                config.GAME_COOLDOWN_SECONDS
                - elapsed
            )

            await ctx.send(
                (
                    f"{config.E['lose']} "
                    f"Please wait "
                    f"{remaining:.1f}s before "
                    f"another game."
                ),
                delete_after=4,
            )

            return False

        self.cooldowns[
            ctx.author.id
        ] = now

        return True


# ============================================================
# CREATE BOT
# ============================================================

bot = CasinoBot()


# ============================================================
# WIN LOG SYSTEM
# ============================================================

async def send_win_log(
    user,
    game: str,
    bet,
    payout,
    multiplier,
    details: str = "",
):

    try:

        channel_id = (
            bot.winlog_channel_id
        )

        if not channel_id:
            return

        channel = bot.get_channel(
            int(channel_id)
        )

        if channel is None:

            try:

                channel = await bot.fetch_channel(
                    int(channel_id)
                )

            except Exception:

                return

        profit = (
            Decimal(str(payout))
            - Decimal(str(bet))
        )

        description = (
            f"**Player:** {user.mention}\n"
            f"**Game:** {game}\n"
            f"**Bet:** {money(bet)} points\n"
            f"**Payout:** {money(payout)} points\n"
            f"**Multiplier:** {multiplier}x\n"
            f"**Profit:** {money(profit)} points"
        )

        if details:

            description += (
                f"\n{details}"
            )

        embed = brand(
            "Win Log",
            description,
            0x57F287,
        )

        embed.set_thumbnail(
            url=user.display_avatar.url
        )

        await channel.send(
            embed=embed
        )

    except Exception as error:

        print(
            "[WinLog Error]",
            repr(error),
        )


# ============================================================
# WINLOG COMMAND
# ============================================================

@bot.command()
@commands.guild_only()
@commands.has_permissions(
    administrator=True
)
async def winlog(
    ctx,
    channel: discord.TextChannel,
):

    bot.winlog_channel_id = (
        channel.id
    )

    try:

        await bot.db.set_setting(
            "winlog_channel_id",
            str(channel.id),
        )

    except Exception as error:

        print(
            "[WinLog Save Error]",
            repr(error),
        )

    embed = brand(
        "Win Logs Updated",
        (
            f"All future game wins will be "
            f"logged in {channel.mention}."
        ),
        0x57F287,
    )

    await ctx.send(
        embed=embed
    )


# ============================================================
# WINLOG ERROR
# ============================================================

@winlog.error
async def winlog_error(
    ctx,
    error,
):

    if isinstance(
        error,
        commands.MissingRequiredArgument,
    ):

        await ctx.send(
            embed=brand(
                "Usage",
                "Use `.winlog #channel`.",
                0xED4245,
            )
        )

        return

    if isinstance(
        error,
        commands.ChannelNotFound,
    ):

        await ctx.send(
            embed=brand(
                "Invalid Channel",
                "Please provide a valid text channel.",
                0xED4245,
            )
        )

        return

    if isinstance(
        error,
        commands.MissingPermissions,
    ):

        await ctx.send(
            embed=brand(
                "Permission Denied",
                "Administrator permission is required.",
                0xED4245,
            )
        )

        return

    print(
        "[WinLog Command Error]",
        repr(error),
    )


# ============================================================
# OWNER / GAME VIEW BASE
# ============================================================

class OwnerView(
    discord.ui.View
):

    def __init__(
        self,
        owner_id: int,
        timeout=180,
    ):

        super().__init__(
            timeout=timeout
        )

        self.owner_id = owner_id

    async def interaction_check(
        self,
        interaction,
    ):

        if (
            interaction.user.id
            != self.owner_id
        ):

            await interaction.response.send_message(
                "This menu belongs to another user.",
                ephemeral=True,
            )

            return False

        return True


# ============================================================
# BASIC ERROR HANDLER
# ============================================================

@bot.event
async def on_command_error(
    ctx,
    error,
):

    if isinstance(
        error,
        commands.CommandNotFound,
    ):
        return

    if isinstance(
        error,
        commands.MissingRequiredArgument,
    ):

        await ctx.send(
            embed=brand(
                "Missing Argument",
                (
                    "You are missing a required "
                    "argument.\n\n"
                    f"Use `{config.PREFIX}help` "
                    "to see the command usage."
                ),
                0xED4245,
            )
        )

        return

    if isinstance(
        error,
        commands.BadArgument,
    ):

        await ctx.send(
            embed=brand(
                "Invalid Argument",
                "Please check your command arguments.",
                0xED4245,
            )
        )

        return

    print(
        "[Command Error]",
        repr(error),
    )


# ============================================================
# READY EVENT
# ============================================================

@bot.event
async def on_ready():

    print(
        "=================================================="
    )

    print(
        f"Logged in as: {bot.user}"
    )

    print(
        f"Bot ID: {bot.user.id}"
    )

    print(
        f"Casino: {config.CASINO_NAME}"
    )

    print(
        "Minimum bet: 20 points ($0.10)"
    )

    print(
        "Prefixes: . and ,"
    )

    print(
        "Win logs:",
        bot.winlog_channel_id,
    )

    print(
        "=================================================="
    )
# =========================================================
# PART 2/10
# DATABASE HELPERS + GAME UTILITIES
# =========================================================

from typing import Optional


# =========================================================
# DATABASE SAFETY HELPERS
# =========================================================

async def db_balance(user_id: int) -> Decimal:
    """
    Return the user's current point balance.
    """
    try:
        value = await bot.db.get_balance(user_id)
        return Decimal(str(value or 0))
    except AttributeError:
        try:
            value = await bot.db.balance(user_id)
            return Decimal(str(value or 0))
        except AttributeError:
            return Decimal("0")


async def db_change_balance(
    user_id: int,
    amount: Decimal,
    reason: str = "",
    reference: Optional[str] = None,
):
    """
    Change a user's balance using the Database API.
    """
    amount = Decimal(str(amount))

    try:
        return await bot.db.change_balance(
            user_id,
            amount,
            reason,
            reference,
        )
    except TypeError:
        try:
            return await bot.db.change_balance(
                user_id,
                amount,
                reason=reason,
                reference=reference,
            )
        except TypeError:
            return await bot.db.change_balance(user_id, amount)


async def ensure_user(user: discord.abc.User):
    """
    Make sure a Discord user exists in the database.
    """
    try:
        return await bot.db.get_user(user.id)
    except AttributeError:
        pass

    try:
        return await bot.db.ensure_user(
            user.id,
            str(user),
        )
    except AttributeError:
        return None


async def get_user_stats(user_id: int):
    """
    Safely retrieve player statistics.
    """
    try:
        return await bot.db.get_stats(user_id)
    except AttributeError:
        return {}


# =========================================================
# BET VALIDATION
# =========================================================

async def validate_bet(
    ctx: commands.Context,
    amount: Decimal,
) -> bool:
    """
    Validate every game's minimum bet and balance.
    """

    amount = Decimal(str(amount))

    if amount < MINIMUM_BET:
        await ctx.send(
            embed=brand(
                "Invalid Bet",
                (
                    f"Minimum bet is **{MINIMUM_BET:,.0f} Points** "
                    f"({usd(MINIMUM_BET)})."
                ),
                0xED4245,
            )
        )
        return False

    balance = await db_balance(ctx.author.id)

    if balance < amount:
        await ctx.send(
            embed=brand(
                "Insufficient Balance",
                (
                    f"You need **{amount:,.0f} Points** "
                    f"({usd(amount)}).\n\n"
                    f"Your balance: **{balance:,.0f} Points** "
                    f"({usd(balance)})."
                ),
                0xED4245,
            )
        )
        return False

    return True


async def take_bet(
    user_id: int,
    amount: Decimal,
    game: str,
) -> bool:
    """
    Deduct a bet from the player's balance.

    Returns True if successful.
    """

    amount = Decimal(str(amount))

    balance = await db_balance(user_id)

    if balance < amount:
        return False

    await db_change_balance(
        user_id,
        -amount,
        reason=f"{game} bet",
        reference=f"{game}:{user_id}:{time.time_ns()}",
    )

    return True


async def payout(
    user_id: int,
    amount: Decimal,
    game: str,
):
    """
    Credit winnings to the player's balance.
    """

    amount = Decimal(str(amount))

    if amount <= 0:
        return

    await db_change_balance(
        user_id,
        amount,
        reason=f"{game} win",
        reference=f"{game}:win:{user_id}:{time.time_ns()}",
    )


# =========================================================
# WIN LOG FORMAT
# =========================================================

async def game_win(
    ctx: commands.Context,
    game: str,
    bet: Decimal,
    multiplier: Decimal,
    payout_amount: Decimal,
    details: str = "",
):
    """
    Credit winnings and send the configured win log.
    """

    await payout(
        ctx.author.id,
        payout_amount,
        game,
    )

    await send_win_log(
        ctx,
        game=game,
        bet=bet,
        multiplier=multiplier,
        payout_amount=payout_amount,
        details=details,
    )


# =========================================================
# COMMON GAME EMBEDS
# =========================================================

def game_bet_embed(
    game: str,
    user: discord.abc.User,
    bet: Decimal,
    description: str,
    colour: int = 0x2B2D31,
):
    return brand(
        game,
        (
            f"**Player:** {user.mention}\n"
            f"**Bet:** {bet:,.0f} Points ({usd(bet)})\n\n"
            f"{description}"
        ),
        colour,
    )


def game_result_embed(
    game: str,
    user: discord.abc.User,
    bet: Decimal,
    result: str,
    payout_amount: Decimal = Decimal("0"),
    details: str = "",
    won: bool = False,
):
    if won:
        colour = 0x57F287
        status = "WIN"
    else:
        colour = 0xED4245
        status = "LOSS"

    description = (
        f"**Player:** {user.mention}\n"
        f"**Bet:** {bet:,.0f} Points ({usd(bet)})\n"
        f"**Result:** {result}\n"
    )

    if details:
        description += f"\n{details}\n"

    if won:
        description += (
            f"\n**Payout:** {payout_amount:,.0f} Points "
            f"({usd(payout_amount)})"
        )
    else:
        description += "\n**Payout:** 0 Points"

    return brand(
        f"{game} — {status}",
        description,
        colour,
    )


# =========================================================
# BALANCE DISPLAY
# =========================================================

async def balance_embed(
    user: discord.abc.User,
):
    balance = await db_balance(user.id)

    return brand(
        "Balance",
        (
            f"**{user.mention}**\n\n"
            f"Points: **{balance:,.0f}**\n"
            f"USD Value: **{usd(balance)}**"
        ),
        0x2B2D31,
    )


# =========================================================
# RANDOM GAME HELPERS
# =========================================================

def random_coin_side() -> str:
    return random.choice(("heads", "tails"))


def normalize_coin_choice(choice: str) -> Optional[str]:
    choice = choice.lower().strip()

    aliases = {
        "h": "heads",
        "head": "heads",
        "heads": "heads",
        "t": "tails",
        "tail": "tails",
        "tails": "tails",
    }

    return aliases.get(choice)


def roll_dice(count: int) -> list[int]:
    return [
        random.randint(1, 6)
        for _ in range(count)
    ]


def dice_total(dice: list[int]) -> int:
    return sum(dice)


# =========================================================
# CRAZY DICE CALCULATIONS
# =========================================================

def crazy_dice_multiplier(
    prediction: str,
    dice_count: int,
) -> Decimal:

    prediction = prediction.lower()

    if prediction == "tie":
        return Decimal(
            str(CRAZY_DICE_TIE_MULTIPLIERS[dice_count])
        )

    return CRAZY_DICE_HIGH_LOW_MULTIPLIER


def crazy_dice_result(
    prediction: str,
    dice: list[int],
) -> tuple[bool, str]:
    """
    Returns:
        (won, result_type)
    """

    total = dice_total(dice)

    if prediction == "tie":
        return total == (3 * len(dice)), "tie"

    if prediction == "higher":
        return total > (3 * len(dice)), "higher"

    if prediction == "lower":
        return total < (3 * len(dice)), "lower"

    return False, "unknown"


# =========================================================
# SAFE DISCORD SEND
# =========================================================

async def safe_send(
    destination,
    *,
    embed=None,
    file=None,
    view=None,
    content=None,
    ephemeral=False,
):
    """
    Small wrapper that prevents a game from crashing
    because one optional Discord parameter failed.
    """

    kwargs = {
        "embed": embed,
        "file": file,
        "view": view,
        "content": content,
    }

    if isinstance(destination, discord.Interaction):
        if not destination.response.is_done():
            return await destination.response.send_message(
                ephemeral=ephemeral,
                **kwargs,
            )

        return await destination.followup.send(
            ephemeral=ephemeral,
            **kwargs,
        )

    return await destination.send(**kwargs)


# =========================================================
# PLAYER LOCK
# =========================================================

_ACTIVE_GAMES: set[int] = set()


def player_game_locked(user_id: int) -> bool:
    return user_id in _ACTIVE_GAMES


def lock_player(user_id: int) -> bool:
    if user_id in _ACTIVE_GAMES:
        return False

    _ACTIVE_GAMES.add(user_id)
    return True


def unlock_player(user_id: int):
    _ACTIVE_GAMES.discard(user_id)


# =========================================================
# GAME LOCK CONTEXT
# =========================================================

class GameLock:
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.locked = False

    async def __aenter__(self):
        self.locked = lock_player(self.user_id)
        return self.locked

    async def __aexit__(self, exc_type, exc, tb):
        unlock_player(self.user_id)


# =========================================================
# CRAZY DICE VIEW
# =========================================================

class CrazyDicePredictionView(OwnerView):

    def __init__(
        self,
        owner_id: int,
        bet: Decimal,
    ):
        super().__init__(owner_id, timeout=60)

        self.bet = bet
        self.prediction = None

    @discord.ui.button(
        label="Higher Wins",
        style=discord.ButtonStyle.primary,
        custom_id="crazydice_higher",
    )
    async def higher(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        self.prediction = "higher"
        await self.choose_prediction(interaction)

    @discord.ui.button(
        label="Lower Wins",
        style=discord.ButtonStyle.primary,
        custom_id="crazydice_lower",
    )
    async def lower(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        self.prediction = "lower"
        await self.choose_prediction(interaction)

    @discord.ui.button(
        label="Tie Wins",
        style=discord.ButtonStyle.success,
        custom_id="crazydice_tie",
    )
    async def tie(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        self.prediction = "tie"
        await self.choose_prediction(interaction)

    async def choose_prediction(
        self,
        interaction: discord.Interaction,
    ):
        for item in self.children:
            item.disabled = True

        if self.prediction == "higher":
            title = "Higher Wins"
        elif self.prediction == "lower":
            title = "Lower Wins"
        else:
            title = "Tie Wins"

        view = CrazyDiceDiceView(
            owner_id=self.owner_id,
            bet=self.bet,
            prediction=self.prediction,
        )

        await interaction.response.edit_message(
            embed=brand(
                "Crazy Dice",
                (
                    f"**Bet:** {self.bet:,.0f} Points "
                    f"({usd(self.bet)})\n"
                    f"**Prediction:** {title}\n\n"
                    "Now choose how many dice to roll."
                ),
            ),
            view=view,
        )


# =========================================================
# CRAZY DICE DICE SELECTION VIEW
# =========================================================

class CrazyDiceDiceView(OwnerView):

    def __init__(
        self,
        owner_id: int,
        bet: Decimal,
        prediction: str,
    ):
        super().__init__(owner_id, timeout=60)

        self.bet = bet
        self.prediction = prediction
        self.finished = False

    @discord.ui.button(
        label="1 Dice",
        style=discord.ButtonStyle.primary,
        custom_id="crazydice_1",
    )
    async def one_dice(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await self.start_game(interaction, 1)

    @discord.ui.button(
        label="3 Dice",
        style=discord.ButtonStyle.primary,
        custom_id="crazydice_3",
    )
    async def three_dice(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await self.start_game(interaction, 3)

    @discord.ui.button(
        label="6 Dice",
        style=discord.ButtonStyle.primary,
        custom_id="crazydice_6",
    )
    async def six_dice(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await self.start_game(interaction, 6)

    async def start_game(
        self,
        interaction: discord.Interaction,
        dice_count: int,
    ):
        if self.finished:
            return

        self.finished = True

        for item in self.children:
            item.disabled = True

        # IMPORTANT:
        # Respond immediately so Discord never leaves
        # the user stuck waiting on the interaction.
        await interaction.response.send_message(
            content="<a:m_Loading1:1550866495641223188>",
        )

        loading_message = await interaction.original_response()

        try:
            await asyncio.sleep(3)

            dice = roll_dice(dice_count)

            won, result_type = crazy_dice_result(
                self.prediction,
                dice,
            )

            multiplier = crazy_dice_multiplier(
                self.prediction,
                dice_count,
            )

            if won:
                payout_amount = (
                    self.bet * multiplier
                ).quantize(Decimal("1"))

                await payout(
                    interaction.user.id,
                    payout_amount,
                    "Crazy Dice",
                )

                dice_text = " ".join(
                    f"`{value}`"
                    for value in dice
                )

                result_embed = game_result_embed(
                    "Crazy Dice",
                    interaction.user,
                    self.bet,
                    result_type.title(),
                    payout_amount,
                    (
                        f"**Prediction:** "
                        f"{self.prediction.title()}\n"
                        f"**Dice:** {dice_text}\n"
                        f"**Multiplier:** {multiplier}x"
                    ),
                    won=True,
                )

                await loading_message.edit(
                    content=None,
                    embed=result_embed,
                    view=None,
                )

                await send_win_log(
                    interaction,
                    game="Crazy Dice",
                    bet=self.bet,
                    multiplier=multiplier,
                    payout_amount=payout_amount,
                    details=(
                        f"{dice_count} dice | "
                        f"{self.prediction.title()} | "
                        f"{dice}"
                    ),
                )

            else:
                dice_text = " ".join(
                    f"`{value}`"
                    for value in dice
                )

                result_embed = game_result_embed(
                    "Crazy Dice",
                    interaction.user,
                    self.bet,
                    result_type.title(),
                    Decimal("0"),
                    (
                        f"**Prediction:** "
                        f"{self.prediction.title()}\n"
                        f"**Dice:** {dice_text}\n"
                        f"**Multiplier:** {multiplier}x"
                    ),
                    won=False,
                )

                await loading_message.edit(
                    content=None,
                    embed=result_embed,
                    view=None,
                )

        except Exception as exc:
            await loading_message.edit(
                content=None,
                embed=brand(
                    "Crazy Dice Error",
                    (
                        "The game could not be completed.\n\n"
                        f"`{type(exc).__name__}`"
                    ),
                    0xED4245,
                ),
                view=None,
            )


# =========================================================
# CRAZY DICE START FUNCTION
# =========================================================

async def start_crazy_dice(
    ctx: commands.Context,
    bet: Decimal,
):
    """
    Starts Crazy Dice after validating and deducting
    the player's bet.
    """

    if not await validate_bet(ctx, bet):
        return

    if not lock_player(ctx.author.id):
        await ctx.send(
            embed=brand(
                "Game Already Running",
                "Finish your current game before starting another one.",
                0xED4245,
            )
        )
        return

    try:
        if not await take_bet(
            ctx.author.id,
            bet,
            "Crazy Dice",
        ):
            await ctx.send(
                embed=brand(
                    "Bet Failed",
                    "Your balance changed before the bet could be placed.",
                    0xED4245,
                )
            )
            return

        view = CrazyDicePredictionView(
            owner_id=ctx.author.id,
            bet=bet,
        )

        await ctx.send(
            embed=brand(
                "Crazy Dice",
                (
                    f"**Bet:** {bet:,.0f} Points "
                    f"({usd(bet)})\n\n"
                    "Choose your prediction."
                ),
            ),
            view=view,
        )

    except Exception:
        # If anything fails after deduction, refund the bet.
        try:
            await payout(
                ctx.author.id,
                bet,
                "Crazy Dice Refund",
            )
        except Exception:
            pass

        raise

    finally:
        # The interaction itself lasts beyond this function,
        # so do not unlock here.
        pass
# =========================================================
# PART 3/10
# COINFLIP + CRAZY DICE COMMANDS
# =========================================================


# =========================================================
# COINFLIP VIEW
# =========================================================

class CoinflipConfirmView(OwnerView):

    def __init__(
        self,
        owner_id: int,
        bet: Decimal,
        choice: str,
    ):
        super().__init__(owner_id, timeout=60)

        self.bet = bet
        self.choice = choice
        self.finished = False

    @discord.ui.button(
        label="Confirm Bet",
        style=discord.ButtonStyle.success,
        custom_id="coinflip_confirm",
    )
    async def confirm(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if self.finished:
            return

        self.finished = True

        for item in self.children:
            item.disabled = True

        if not await take_bet(
            interaction.user.id,
            self.bet,
            "Coinflip",
        ):
            await interaction.response.edit_message(
                embed=brand(
                    "Coinflip",
                    "Your balance is no longer high enough for this bet.",
                    0xED4245,
                ),
                view=None,
            )
            return

        await interaction.response.edit_message(
            embed=brand(
                "Coinflip",
                (
                    f"**Bet:** {self.bet:,.0f} Points "
                    f"({usd(self.bet)})\n"
                    f"**Choice:** {self.choice.title()}\n\n"
                    "<a:m_Loading1:1550866495641223188>"
                ),
                0x2B2D31,
            ),
            view=None,
        )

        message = await interaction.original_response()

        try:
            await asyncio.sleep(2)

            result = random_coin_side()

            won = result == self.choice

            if won:
                payout_amount = (
                    self.bet * COINFLIP_MULTIPLIER
                ).quantize(Decimal("1"))

                await payout(
                    interaction.user.id,
                    payout_amount,
                    "Coinflip",
                )

                embed = game_result_embed(
                    "Coinflip",
                    interaction.user,
                    self.bet,
                    result.title(),
                    payout_amount,
                    (
                        f"**Your Choice:** "
                        f"{self.choice.title()}\n"
                        f"**Result:** "
                        f"{result.title()}\n"
                        f"**Multiplier:** "
                        f"{COINFLIP_MULTIPLIER}x"
                    ),
                    won=True,
                )

                file = await coinflip_result_image(
                    result
                )

                await message.edit(
                    content=None,
                    embed=embed,
                    attachments=[file],
                    view=None,
                )

                await send_win_log(
                    interaction,
                    game="Coinflip",
                    bet=self.bet,
                    multiplier=COINFLIP_MULTIPLIER,
                    payout_amount=payout_amount,
                    details=(
                        f"Choice: {self.choice.title()} | "
                        f"Result: {result.title()}"
                    ),
                )

            else:
                embed = game_result_embed(
                    "Coinflip",
                    interaction.user,
                    self.bet,
                    result.title(),
                    Decimal("0"),
                    (
                        f"**Your Choice:** "
                        f"{self.choice.title()}\n"
                        f"**Result:** "
                        f"{result.title()}\n"
                        f"**Multiplier:** "
                        f"{COINFLIP_MULTIPLIER}x"
                    ),
                    won=False,
                )

                file = await coinflip_result_image(
                    result
                )

                await message.edit(
                    content=None,
                    embed=embed,
                    attachments=[file],
                    view=None,
                )

        except Exception as exc:
            # Refund if the game failed after the bet
            # was successfully deducted.
            try:
                await payout(
                    interaction.user.id,
                    self.bet,
                    "Coinflip Refund",
                )
            except Exception:
                pass

            await message.edit(
                content=None,
                embed=brand(
                    "Coinflip Error",
                    (
                        "The game could not be completed.\n\n"
                        "Your bet has been refunded."
                    ),
                    0xED4245,
                ),
                view=None,
            )


    @discord.ui.button(
        label="Cancel",
        style=discord.ButtonStyle.secondary,
        custom_id="coinflip_cancel",
    )
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if self.finished:
            return

        self.finished = True

        await interaction.response.edit_message(
            embed=brand(
                "Coinflip Cancelled",
                "The bet was not placed.",
            ),
            view=None,
        )


# =========================================================
# COINFLIP COMMAND
# =========================================================

@bot.command(
    name="cf",
    aliases=["coinflip"],
)
async def coinflip(
    ctx: commands.Context,
    amount: str = None,
    choice: str = None,
):
    """
    .cf <amount> <heads/tails>
    Example:
    .cf 50 heads
    """

    if amount is None or choice is None:
        await ctx.send(
            embed=brand(
                "Coinflip",
                (
                    "**Usage:**\n"
                    "`.cf <amount> <heads/tails>`\n\n"
                    "**Example:**\n"
                    "`.cf 50 heads`\n"
                    "`.cf 100 tails`"
                ),
            )
        )
        return

    try:
        bet = resolve_bet(
            amount,
            await db_balance(ctx.author.id),
        )
    except Exception:
        await ctx.send(
            embed=brand(
                "Invalid Bet",
                "Enter a valid point amount.",
                0xED4245,
            )
        )
        return

    normalized_choice = normalize_coin_choice(
        choice
    )

    if normalized_choice is None:
        await ctx.send(
            embed=brand(
                "Invalid Choice",
                (
                    "Choose either **heads** or **tails**.\n\n"
                    "Example:\n"
                    "`.cf 50 heads`"
                ),
                0xED4245,
            )
        )
        return

    if not await validate_bet(ctx, bet):
        return

    if not lock_player(ctx.author.id):
        await ctx.send(
            embed=brand(
                "Game Already Running",
                "Finish your current game before starting another one.",
                0xED4245,
            )
        )
        return

    view = CoinflipConfirmView(
        owner_id=ctx.author.id,
        bet=bet,
        choice=normalized_choice,
    )

    await ctx.send(
        embed=brand(
            "Coinflip",
            (
                f"**Bet:** {bet:,.0f} Points "
                f"({usd(bet)})\n"
                f"**Choice:** {normalized_choice.title()}\n"
                f"**Win Multiplier:** "
                f"{COINFLIP_MULTIPLIER}x\n\n"
                "Press **Confirm Bet** to play."
            ),
        ),
        view=view,
    )


# =========================================================
# CRAZY DICE COMMAND
# =========================================================

@bot.command(
    name="crazydice",
    aliases=["cd"],
)
async def crazydice(
    ctx: commands.Context,
    amount: str = None,
):
    """
    .crazydice <bet>
    .cd <bet>
    """

    if amount is None:
        await ctx.send(
            embed=brand(
                "Crazy Dice",
                (
                    "**Usage:**\n"
                    "`.crazydice <bet>`\n\n"
                    "**Alias:**\n"
                    "`.cd <bet>`\n\n"
                    "**Example:**\n"
                    "`.cd 100`"
                ),
            )
        )
        return

    try:
        balance = await db_balance(
            ctx.author.id
        )

        bet = resolve_bet(
            amount,
            balance,
        )

    except Exception:
        await ctx.send(
            embed=brand(
                "Invalid Bet",
                "Enter a valid point amount.",
                0xED4245,
            )
        )
        return

    if not await validate_bet(
        ctx,
        bet,
    ):
        return

    await start_crazy_dice(
        ctx,
        bet,
    )


# =========================================================
# CRAZY DICE VIEW TIMEOUTS
# =========================================================

async def _prediction_timeout(
    self,
):
    if self.message:
        try:
            await self.message.edit(
                embed=brand(
                    "Crazy Dice",
                    "This game menu expired.",
                    0xED4245,
                ),
                view=None,
            )
        except Exception:
            pass


async def _dice_timeout(
    self,
):
    if self.message:
        try:
            await self.message.edit(
                embed=brand(
                    "Crazy Dice",
                    "This game menu expired.",
                    0xED4245,
                ),
                view=None,
            )
        except Exception:
            pass


# =========================================================
# UNLOCK PLAYER WHEN VIEWS FINISH
# =========================================================

_original_prediction_on_timeout = (
    CrazyDicePredictionView.on_timeout
)


async def crazy_prediction_timeout(
    self,
):
    unlock_player(self.owner_id)

    try:
        await _original_prediction_on_timeout(
            self
        )
    except Exception:
        pass


CrazyDicePredictionView.on_timeout = (
    crazy_prediction_timeout
)


_original_dice_on_timeout = (
    CrazyDiceDiceView.on_timeout
)


async def crazy_dice_timeout(
    self,
):
    unlock_player(self.owner_id)

    try:
        await _original_dice_on_timeout(
            self
        )
    except Exception:
        pass


CrazyDiceDiceView.on_timeout = (
    crazy_dice_timeout
)


_original_coinflip_on_timeout = (
    CoinflipConfirmView.on_timeout
)


async def coinflip_timeout(
    self,
):
    unlock_player(self.owner_id)

    try:
        await _original_coinflip_on_timeout(
            self
        )
    except Exception:
        pass


CoinflipConfirmView.on_timeout = (
    coinflip_timeout
)
# =========================================================
# PART 4/10
# BLACKJACK
# =========================================================


# =========================================================
# BLACKJACK HELPERS
# =========================================================

def blackjack_card_value(card: str) -> int:
    rank = card[:-1]

    if rank in ("J", "Q", "K"):
        return 10

    if rank == "A":
        return 11

    try:
        return int(rank)
    except ValueError:
        return 0


def blackjack_hand_value(cards: list[str]) -> int:
    total = sum(
        blackjack_card_value(card)
        for card in cards
    )

    aces = sum(
        1
        for card in cards
        if card[:-1] == "A"
    )

    while total > 21 and aces:
        total -= 10
        aces -= 1

    return total


def blackjack_is_bust(cards: list[str]) -> bool:
    return blackjack_hand_value(cards) > 21


def blackjack_is_natural(cards: list[str]) -> bool:
    return (
        len(cards) == 2
        and blackjack_hand_value(cards) == 21
    )


def blackjack_draw(
    shoe: list[str],
) -> str:
    if not shoe:
        shoe.extend(deck())

    return shoe.pop()


# =========================================================
# BLACKJACK GAME STATE
# =========================================================

class BlackjackGame:

    def __init__(
        self,
        user_id: int,
        bet: Decimal,
    ):
        self.user_id = user_id
        self.bet = bet

        self.shoe = deck()

        random.shuffle(self.shoe)

        self.player: list[str] = []
        self.dealer: list[str] = []

        self.finished = False
        self.doubled = False

    def deal_initial(self):
        self.player = [
            blackjack_draw(self.shoe),
            blackjack_draw(self.shoe),
        ]

        self.dealer = [
            blackjack_draw(self.shoe),
            blackjack_draw(self.shoe),
        ]

    def hit_player(self):
        self.player.append(
            blackjack_draw(self.shoe)
        )

    def dealer_play(self):
        while blackjack_hand_value(
            self.dealer
        ) < 17:
            self.dealer.append(
                blackjack_draw(self.shoe)
            )

    def player_total(self) -> int:
        return blackjack_hand_value(
            self.player
        )

    def dealer_total(self) -> int:
        return blackjack_hand_value(
            self.dealer
        )


# =========================================================
# BLACKJACK EMBED
# =========================================================

def blackjack_embed(
    game: BlackjackGame,
    reveal: bool = False,
    status: str = "",
):
    player_total = game.player_total()

    if reveal:
        dealer_total = game.dealer_total()

        dealer_text = (
            f"{dealer_total}\n"
            + " ".join(
                f"`{card}`"
                for card in game.dealer
            )
        )
    else:
        dealer_text = (
            "?\n"
            f"`{game.dealer[0]}` `?`"
        )

    player_text = (
        f"{player_total}\n"
        + " ".join(
            f"`{card}`"
            for card in game.player
        )
    )

    description = (
        f"**Bet:** {game.bet:,.0f} Points "
        f"({usd(game.bet)})\n\n"
        f"**Dealer**\n"
        f"{dealer_text}\n\n"
        f"**Player**\n"
        f"{player_text}"
    )

    if status:
        description += f"\n\n{status}"

    return brand(
        "Blackjack",
        description,
    )


# =========================================================
# BLACKJACK VIEW
# =========================================================

class BlackjackView(OwnerView):

    def __init__(
        self,
        owner_id: int,
        game: BlackjackGame,
    ):
        super().__init__(
            owner_id,
            timeout=180,
        )

        self.game = game
        self.message = None

    async def disable_buttons(self):
        for item in self.children:
            item.disabled = True

    async def finish_game(
        self,
        interaction: discord.Interaction,
        result: str,
        multiplier: Decimal = Decimal("0"),
    ):
        if self.game.finished:
            return

        self.game.finished = True

        await self.disable_buttons()

        payout_amount = Decimal("0")

        if multiplier > 0:
            payout_amount = (
                self.game.bet * multiplier
            ).quantize(Decimal("1"))

            await payout(
                self.owner_id,
                payout_amount,
                "Blackjack",
            )

        if result == "You Win":
            colour = 0x57F287
        elif result == "Push":
            colour = 0xFEE75C
        else:
            colour = 0xED4245

        description = (
            f"**Bet:** {self.game.bet:,.0f} Points "
            f"({usd(self.game.bet)})\n\n"
            f"**Dealer:** "
            f"{self.game.dealer_total()}\n"
            + " ".join(
                f"`{card}`"
                for card in self.game.dealer
            )
            + "\n\n"
            f"**Player:** "
            f"{self.game.player_total()}\n"
            + " ".join(
                f"`{card}`"
                for card in self.game.player
            )
        )

        if result == "You Win":
            description += (
                f"\n\n**Payout:** "
                f"{payout_amount:,.0f} Points "
                f"({usd(payout_amount)})"
            )
        elif result == "Push":
            description += (
                f"\n\n**Refund:** "
                f"{payout_amount:,.0f} Points "
                f"({usd(payout_amount)})"
            )
        else:
            description += "\n\n**Payout:** 0 Points"

        embed = brand(
            f"Blackjack — {result}",
            description,
            colour,
        )

        try:
            await interaction.response.edit_message(
                embed=embed,
                view=self,
            )
        except discord.InteractionResponded:
            try:
                await interaction.edit_original_response(
                    embed=embed,
                    view=self,
                )
            except Exception:
                pass

        if result == "You Win":
            await send_win_log(
                interaction,
                game="Blackjack",
                bet=self.game.bet,
                multiplier=multiplier,
                payout_amount=payout_amount,
                details=(
                    f"Player {self.game.player_total()} "
                    f"vs Dealer {self.game.dealer_total()}"
                ),
            )

        self.stop()

    @discord.ui.button(
        label="Hit",
        style=discord.ButtonStyle.primary,
        custom_id="blackjack_hit",
    )
    async def hit(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if self.game.finished:
            return

        self.game.hit_player()

        total = self.game.player_total()

        if total > 21:
            await self.finish_game(
                interaction,
                "You Lose",
                Decimal("0"),
            )
            return

        if total == 21:
            self.game.dealer_play()

            dealer_total = self.game.dealer_total()

            if dealer_total > 21:
                await self.finish_game(
                    interaction,
                    "You Win",
                    Decimal("1.96"),
                )
            elif dealer_total < 21:
                await self.finish_game(
                    interaction,
                    "You Win",
                    Decimal("1.96"),
                )
            else:
                await self.finish_game(
                    interaction,
                    "Push",
                    Decimal("1"),
                )

            return

        await interaction.response.edit_message(
            embed=blackjack_embed(
                self.game,
                reveal=False,
                status="Choose **Hit** or **Stand**.",
            ),
            view=self,
        )

    @discord.ui.button(
        label="Stand",
        style=discord.ButtonStyle.success,
        custom_id="blackjack_stand",
    )
    async def stand(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if self.game.finished:
            return

        self.game.dealer_play()

        player_total = self.game.player_total()
        dealer_total = self.game.dealer_total()

        if dealer_total > 21:
            result = "You Win"
            multiplier = Decimal("1.96")

        elif player_total > dealer_total:
            result = "You Win"
            multiplier = Decimal("1.96")

        elif player_total == dealer_total:
            result = "Push"
            multiplier = Decimal("1")

        else:
            result = "You Lose"
            multiplier = Decimal("0")

        await self.finish_game(
            interaction,
            result,
            multiplier,
        )

    @discord.ui.button(
        label="Double",
        style=discord.ButtonStyle.secondary,
        custom_id="blackjack_double",
    )
    async def double(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if self.game.finished:
            return

        if len(self.game.player) != 2:
            await interaction.response.send_message(
                "Double is only available on your first two cards.",
                ephemeral=True,
            )
            return

        extra_bet = self.game.bet

        balance = await db_balance(
            self.owner_id
        )

        if balance < extra_bet:
            await interaction.response.send_message(
                "You do not have enough balance to double.",
                ephemeral=True,
            )
            return

        if not await take_bet(
            self.owner_id,
            extra_bet,
            "Blackjack Double",
        ):
            await interaction.response.send_message(
                "The additional bet could not be placed.",
                ephemeral=True,
            )
            return

        self.game.bet *= 2
        self.game.doubled = True

        self.game.hit_player()

        if self.game.player_total() > 21:
            await self.finish_game(
                interaction,
                "You Lose",
                Decimal("0"),
            )
            return

        self.game.dealer_play()

        player_total = self.game.player_total()
        dealer_total = self.game.dealer_total()

        if dealer_total > 21:
            result = "You Win"
            multiplier = Decimal("1.96")

        elif player_total > dealer_total:
            result = "You Win"
            multiplier = Decimal("1.96")

        elif player_total == dealer_total:
            result = "Push"
            multiplier = Decimal("1")

        else:
            result = "You Lose"
            multiplier = Decimal("0")

        await self.finish_game(
            interaction,
            result,
            multiplier,
        )

    async def on_timeout(self):
        if self.game.finished:
            unlock_player(self.owner_id)
            return

        self.game.finished = True

        try:
            if self.message:
                await self.message.edit(
                    embed=brand(
                        "Blackjack Expired",
                        "The game timed out. Your bet has been refunded.",
                        0xED4245,
                    ),
                    view=None,
                )
        except Exception:
            pass

        try:
            await payout(
                self.owner_id,
                self.game.bet,
                "Blackjack Timeout Refund",
            )
        except Exception:
            pass

        unlock_player(self.owner_id)


# =========================================================
# BLACKJACK COMMAND
# =========================================================

@bot.command(
    name="bj",
    aliases=["blackjack"],
)
async def blackjack(
    ctx: commands.Context,
    amount: str = None,
):
    """
    .bj <bet>
    .blackjack <bet>
    """

    if amount is None:
        await ctx.send(
            embed=brand(
                "Blackjack",
                (
                    "**Usage:**\n"
                    "`.bj <bet>`\n\n"
                    "**Example:**\n"
                    "`.bj 100`"
                ),
            )
        )
        return

    try:
        balance = await db_balance(
            ctx.author.id
        )

        bet = resolve_bet(
            amount,
            balance,
        )

    except Exception:
        await ctx.send(
            embed=brand(
                "Invalid Bet",
                "Enter a valid point amount.",
                0xED4245,
            )
        )
        return

    if not await validate_bet(
        ctx,
        bet,
    ):
        return

    if not lock_player(
        ctx.author.id
    ):
        await ctx.send(
            embed=brand(
                "Game Already Running",
                "Finish your current game before starting another one.",
                0xED4245,
            )
        )
        return

    try:
        if not await take_bet(
            ctx.author.id,
            bet,
            "Blackjack",
        ):
            unlock_player(ctx.author.id)

            await ctx.send(
                embed=brand(
                    "Bet Failed",
                    "Your balance changed before the bet could be placed.",
                    0xED4245,
                )
            )
            return

        game = BlackjackGame(
            ctx.author.id,
            bet,
        )

        game.deal_initial()

        # Natural blackjack handling.
        player_blackjack = (
            blackjack_is_natural(
                game.player
            )
        )

        dealer_blackjack = (
            blackjack_is_natural(
                game.dealer
            )
        )

        if player_blackjack or dealer_blackjack:

            if player_blackjack and dealer_blackjack:
                await payout(
                    ctx.author.id,
                    bet,
                    "Blackjack Push",
                )

                embed = blackjack_embed(
                    game,
                    reveal=True,
                    status="Both player and dealer have Blackjack. Push.",
                )

                unlock_player(ctx.author.id)

                await ctx.send(
                    embed=embed
                )

                return

            if player_blackjack:
                payout_amount = (
                    bet * Decimal("2.5")
                ).quantize(Decimal("1"))

                await payout(
                    ctx.author.id,
                    payout_amount,
                    "Blackjack Natural",
                )

                embed = blackjack_embed(
                    game,
                    reveal=True,
                    status=(
                        f"Natural Blackjack!\n"
                        f"Payout: "
                        f"**{payout_amount:,.0f} Points** "
                        f"({usd(payout_amount)})"
                    ),
                )

                unlock_player(ctx.author.id)

                message = await ctx.send(
                    embed=embed
                )

                await send_win_log(
                    ctx,
                    game="Blackjack",
                    bet=bet,
                    multiplier=Decimal("2.5"),
                    payout_amount=payout_amount,
                    details="Natural Blackjack",
                )

                return

            # Dealer blackjack.
            unlock_player(ctx.author.id)

            await ctx.send(
                embed=blackjack_embed(
                    game,
                    reveal=True,
                    status="Dealer has Blackjack. You lose.",
                )
            )

            return

        view = BlackjackView(
            owner_id=ctx.author.id,
            game=game,
        )

        message = await ctx.send(
            embed=blackjack_embed(
                game,
                reveal=False,
                status="Choose **Hit**, **Stand**, or **Double**.",
            ),
            view=view,
        )

        view.message = message

    except Exception:
        try:
            await payout(
                ctx.author.id,
                bet,
                "Blackjack Error Refund",
            )
        except Exception:
            pass

        unlock_player(ctx.author.id)

        await ctx.send(
            embed=brand(
                "Blackjack Error",
                "The game could not be started. Your bet was refunded.",
                0xED4245,
            )
        )
# =========================================================
# PART 5/10
# MINES + HILO
# =========================================================


# =========================================================
# MINES CONFIGURATION
# =========================================================

MINES_BOARD_SIZE = 25
MINES_DEFAULT_COUNT = 3


# =========================================================
# MINES HELPERS
# =========================================================

def mines_multiplier(
    mine_count: int,
    safe_picks: int,
) -> Decimal:
    """
    Calculates a progressively increasing Mines multiplier.
    """

    if safe_picks <= 0:
        return Decimal("1")

    multiplier = Decimal("1")

    remaining_safe = MINES_BOARD_SIZE - mine_count

    for pick in range(safe_picks):
        numerator = Decimal(
            remaining_safe - pick
        )

        denominator = Decimal(
            MINES_BOARD_SIZE - pick
        )

        if denominator <= 0:
            break

        multiplier *= (
            numerator / denominator
        )

    # House adjustment.
    multiplier *= Decimal("0.97")

    if multiplier < Decimal("1.01"):
        multiplier = Decimal("1.01")

    return multiplier.quantize(
        Decimal("0.01")
    )


def mines_grid_text(
    mines: set[int],
    revealed: set[int],
    exploded: Optional[int] = None,
    cashout: bool = False,
) -> str:
    """
    Creates a Discord-friendly 5x5 Mines board.
    """

    cells = []

    for index in range(
        MINES_BOARD_SIZE
    ):
        number = index + 1

        if exploded == index:
            symbol = "X"

        elif index in mines and cashout:
            symbol = "M"

        elif index in revealed:
            symbol = "O"

        else:
            symbol = str(number)

        cells.append(
            f"`{symbol:>2}`"
        )

    rows = []

    for index in range(0, 25, 5):
        rows.append(
            " ".join(
                cells[index:index + 5]
            )
        )

    return "\n".join(rows)


# =========================================================
# MINES BUTTON
# =========================================================

class MinesButton(
    discord.ui.Button
):

    def __init__(
        self,
        position: int,
        parent_view,
    ):
        super().__init__(
            label=str(position + 1),
            style=discord.ButtonStyle.secondary,
            row=position // 5,
            custom_id=f"mines_cell_{position}",
        )

        self.position = position
        self.parent_view = parent_view

    async def callback(
        self,
        interaction: discord.Interaction,
    ):
        await self.parent_view.reveal_cell(
            interaction,
            self.position,
        )


# =========================================================
# MINES VIEW
# =========================================================

class MinesView(OwnerView):

    def __init__(
        self,
        owner_id: int,
        bet: Decimal,
        mine_count: int,
    ):
        super().__init__(
            owner_id,
            timeout=300,
        )

        self.bet = bet
        self.mine_count = mine_count

        self.mines: set[int] = set(
            random.sample(
                range(MINES_BOARD_SIZE),
                mine_count,
            )
        )

        self.revealed: set[int] = set()

        self.current_multiplier = Decimal("1")
        self.finished = False
        self.message = None

        for position in range(
            MINES_BOARD_SIZE
        ):
            self.add_item(
                MinesButton(
                    position,
                    self,
                )
            )

        self.add_item(
            discord.ui.Button(
                label="Cash Out",
                style=discord.ButtonStyle.success,
                row=4,
                custom_id="mines_cashout",
            )
        )

        # Replace the final generated button with
# a proper callback-capable button.
cashout_button = self.children[-1]

cashout_button.callback = (
    self.cashout_callback
)

def update_buttons(self):
    for item in self.children:
        if not isinstance(
            item,
            discord.ui.Button,
        ):
            continue

        if item.custom_id == "mines_cashout":
            item.disabled = (
                len(self.revealed) == 0
            )
            continue

        if not item.custom_id.startswith(
            "mines_cell_"
        ):
            continue

        position = int(
            item.custom_id.split("_")[-1]
        )

        if position in self.revealed:
            item.disabled = True
            item.label = "O"
            item.style = (
                discord.ButtonStyle.success
            )

    async def reveal_cell(
    self,
    interaction: discord.Interaction,
    position: int,
):
    if self.finished:
        return

    if position in self.revealed:
        await interaction.response.send_message(
            "That tile is already revealed.",
            ephemeral=True,
        )
        return
    if position in self.mines:
        self.finished = True

        grid = mines_grid_text(
            self.mines,
            self.revealed,
            exploded=position,
            cashout=True,
        )

        await interaction.response.edit_message(
            embed=brand(
                "Mines — You Lost",
                (
                    f"**Bet:** {self.bet:,.0f} Points "
                    f"({usd(self.bet)})\n"
                    f"**Mines:** {self.mine_count}\n\n"
                    f"{grid}\n\n"
                    "You hit a mine.\n"
                    "**Payout:** 0 Points"
                ),
                0xED4245,
            ),
            view=None,
        )
        return

            self.stop()
            unlock_player(self.owner_id)
            return

        self.revealed.add(position)

        self.current_multiplier = (
            mines_multiplier(
                self.mine_count,
                len(self.revealed),
            )
        )

        safe_tiles = (
            MINES_BOARD_SIZE
            - self.mine_count
        )

        # Automatically cash out if every safe
        # tile has been revealed.
        if len(self.revealed) >= safe_tiles:
            await self.finish_win(
                interaction,
                automatic=True,
            )
            return

        self.update_buttons()

        await interaction.response.edit_message(
            embed=brand(
                "Mines",
                (
                    f"**Bet:** {self.bet:,.0f} Points "
                    f"({usd(self.bet)})\n"
                    f"**Mines:** {self.mine_count}\n"
                    f"**Safe Picks:** {len(self.revealed)}\n"
                    f"**Multiplier:** "
                    f"{self.current_multiplier}x\n"
                    f"**Cashout:** "
                    f"{(self.bet * self.current_multiplier).quantize(Decimal('1')):,.0f} Points\n\n"
                    f"{mines_grid_text("
                    self.mines,"
                    " self.revealed"
                    ")}"
                ),
                0x2B2D31,
            ),
            view=self,
        )

    async def finish_win(
        self,
        interaction: discord.Interaction,
        automatic: bool = False,
    ):
        if self.finished:
            return

        self.finished = True

        payout_amount = (
            self.bet * self.current_multiplier
        ).quantize(Decimal("1"))

        await payout(
            self.owner_id,
            payout_amount,
            "Mines",
        )

        description = (
            f"**Bet:** {self.bet:,.0f} Points "
            f"({usd(self.bet)})\n"
            f"**Mines:** {self.mine_count}\n"
            f"**Safe Picks:** {len(self.revealed)}\n"
            f"**Multiplier:** "
            f"{self.current_multiplier}x\n\n"
            f"{mines_grid_text("
            self.mines,"
            " self.revealed,"
            " cashout=True"
            ")}\n\n"
            f"**Payout:** "
            f"{payout_amount:,.0f} Points "
            f"({usd(payout_amount)})"
        )

        if automatic:
            description += (
                "\n\nAll safe tiles were revealed."
            )

        await interaction.response.edit_message(
            embed=brand(
                "Mines — You Won",
                description,
                0x57F287,
            ),
            view=None,
        )

        await send_win_log(
            interaction,
            game="Mines",
            bet=self.bet,
            multiplier=self.current_multiplier,
            payout_amount=payout_amount,
            details=(
                f"{self.mine_count} mines | "
                f"{len(self.revealed)} safe picks"
            ),
        )

        self.stop()
        unlock_player(self.owner_id)

    async def cashout_callback(
        self,
        interaction: discord.Interaction,
    ):
        if self.finished:
            return

        if len(self.revealed) == 0:
            await interaction.response.send_message(
                "Reveal at least one safe tile before cashing out.",
                ephemeral=True,
            )
            return

        await self.finish_win(
            interaction,
            automatic=False,
        )

    async def on_timeout(self):
        if self.finished:
            unlock_player(self.owner_id)
            return

        self.finished = True

        payout_amount = (
            self.bet * self.current_multiplier
        ).quantize(Decimal("1"))

        # Timeout acts as a cashout so the player
        # does not lose an active game simply because
        # Discord's component timeout expired.
        if self.message:
            try:
                await self.message.edit(
                    embed=brand(
                        "Mines — Auto Cashout",
                        (
                            f"Your Mines game timed out.\n\n"
                            f"**Payout:** "
                            f"{payout_amount:,.0f} Points "
                            f"({usd(payout_amount)})"
                        ),
                        0x57F287,
                    ),
                    view=None,
                )
            except Exception:
                pass

        if len(self.revealed) > 0:
            try:
                await payout(
                    self.owner_id,
                    payout_amount,
                    "Mines Timeout Cashout",
                )
            except Exception:
                pass
        else:
            try:
                await payout(
                    self.owner_id,
                    self.bet,
                    "Mines Timeout Refund",
                )
            except Exception:
                pass

        unlock_player(self.owner_id)


# =========================================================
# MINES COMMAND
# =========================================================

@bot.command(
    name="mines",
)
async def mines(
    ctx: commands.Context,
    amount: str = None,
    mine_count: int = MINES_DEFAULT_COUNT,
):
    """
    .mines <bet> [mines]
    """

    if amount is None:
        await ctx.send(
            embed=brand(
                "Mines",
                (
                    "**Usage:**\n"
                    "`.mines <bet> [mines]`\n\n"
                    "**Examples:**\n"
                    "`.mines 100`\n"
                    "`.mines 100 5`\n\n"
                    "The board contains 25 tiles."
                ),
            )
        )
        return

    try:
        mine_count = int(
            mine_count
        )
    except (TypeError, ValueError):
        await ctx.send(
            embed=brand(
                "Invalid Mines",
                "Mine count must be a number.",
                0xED4245,
            )
        )
        return

    if mine_count < 1 or mine_count > 24:
        await ctx.send(
            embed=brand(
                "Invalid Mines",
                "Choose between **1 and 24 mines**.",
                0xED4245,
            )
        )
        return

    try:
        balance = await db_balance(
            ctx.author.id
        )

        bet = resolve_bet(
            amount,
            balance,
        )

    except Exception:
        await ctx.send(
            embed=brand(
                "Invalid Bet",
                "Enter a valid point amount.",
                0xED4245,
            )
        )
        return

    if not await validate_bet(
        ctx,
        bet,
    ):
        return

    if not lock_player(
        ctx.author.id
    ):
        await ctx.send(
            embed=brand(
                "Game Already Running",
                "Finish your current game before starting another one.",
                0xED4245,
            )
        )
        return

    if not await take_bet(
        ctx.author.id,
        bet,
        "Mines",
    ):
        unlock_player(ctx.author.id)

        await ctx.send(
            embed=brand(
                "Bet Failed",
                "Your balance changed before the bet could be placed.",
                0xED4245,
            )
        )
        return

    try:
        view = MinesView(
            owner_id=ctx.author.id,
            bet=bet,
            mine_count=mine_count,
        )

        message = await ctx.send(
            embed=brand(
                "Mines",
                (
                    f"**Bet:** {bet:,.0f} Points "
                    f"({usd(bet)})\n"
                    f"**Mines:** {mine_count}\n"
                    f"**Safe Picks:** 0\n"
                    f"**Multiplier:** 1.00x\n\n"
                    f"{mines_grid_text("
                    view.mines,"
                    " view.revealed"
                    ")}\n\n"
                    "Reveal a tile or cash out."
                ),
            ),
            view=view,
        )

        view.message = message

    except Exception:
        try:
            await payout(
                ctx.author.id,
                bet,
                "Mines Error Refund",
            )
        except Exception:
            pass

        unlock_player(ctx.author.id)

        await ctx.send(
            embed=brand(
                "Mines Error",
                "The game could not be started. Your bet was refunded.",
                0xED4245,
            )
        )


# =========================================================
# HILO
# =========================================================

HILO_SUITS = (
    "♠",
    "♥",
    "♦",
    "♣",
)

HILO_RANKS = (
    "2",
    "3",
    "4",
    "5",
    "6",
    "7",
    "8",
    "9",
    "10",
    "J",
    "Q",
    "K",
    "A",
)


def hilo_rank_value(card: str) -> int:
    rank = card[:-1]

    if rank == "A":
        return 14

    if rank == "K":
        return 13

    if rank == "Q":
        return 12

    if rank == "J":
        return 11

    return int(rank)


def hilo_random_card(
    previous: Optional[str] = None,
) -> str:
    card = random.choice(
        [
            f"{rank}{suit}"
            for rank in HILO_RANKS
            for suit in HILO_SUITS
        ]
    )

    if previous is not None:
        while (
            hilo_rank_value(card)
            == hilo_rank_value(previous)
        ):
            card = random.choice(
                [
                    f"{rank}{suit}"
                    for rank in HILO_RANKS
                    for suit in HILO_SUITS
                ]
            )

    return card


def hilo_multiplier(
    current_card: str,
    prediction: str,
) -> Decimal:
    """
    Fixed 1.96x payout for a correct prediction.
    """

    return Decimal("1.96")


# =========================================================
# HILO VIEW
# =========================================================

class HiloView(OwnerView):

    def __init__(
        self,
        owner_id: int,
        bet: Decimal,
        current_card: str,
    ):
        super().__init__(
            owner_id,
            timeout=180,
        )

        self.bet = bet
        self.current_card = current_card
        self.finished = False
        self.message = None

    async def play(
        self,
        interaction: discord.Interaction,
        prediction: str,
    ):
        if self.finished:
            return

        await interaction.response.defer()

        next_card = hilo_random_card(
            self.current_card
        )

        current_value = hilo_rank_value(
            self.current_card
        )

        next_value = hilo_rank_value(
            next_card
        )

        if prediction == "higher":
            won = next_value > current_value
        elif prediction == "lower":
            won = next_value < current_value
        else:
            won = False

        if not won:
            self.finished = True

            await interaction.edit_original_response(
                embed=brand(
                    "Hilo — You Lost",
                    (
                        f"**Bet:** {self.bet:,.0f} Points "
                        f"({usd(self.bet)})\n\n"
                        f"**Previous Card:** "
                        f"`{self.current_card}`\n"
                        f"**Next Card:** "
                        f"`{next_card}`\n\n"
                        f"**Prediction:** "
                        f"{prediction.title()}\n\n"
                        "Your prediction was incorrect.\n"
                        "**Payout:** 0 Points"
                    ),
                    0xED4245,
                ),
                view=None,
            )

            self.stop()
            unlock_player(self.owner_id)
            return

        multiplier = hilo_multiplier(
            self.current_card,
            prediction,
        )

        payout_amount = (
            self.bet * multiplier
        ).quantize(Decimal("1"))

        await payout(
            self.owner_id,
            payout_amount,
            "Hilo",
        )

        self.finished = True

        await interaction.edit_original_response(
            embed=brand(
                "Hilo — You Won",
                (
                    f"**Bet:** {self.bet:,.0f} Points "
                    f"({usd(self.bet)})\n\n"
                    f"**Previous Card:** "
                    f"`{self.current_card}`\n"
                    f"**Next Card:** "
                    f"`{next_card}`\n\n"
                    f"**Prediction:** "
                    f"{prediction.title()}\n"
                    f"**Multiplier:** {multiplier}x\n\n"
                    f"**Payout:** "
                    f"{payout_amount:,.0f} Points "
                    f"({usd(payout_amount)})"
                ),
                0x57F287,
            ),
            view=None,
        )

        await send_win_log(
            interaction,
            game="Hilo",
            bet=self.bet,
            multiplier=multiplier,
            payout_amount=payout_amount,
            details=(
                f"{self.current_card} -> "
                f"{next_card} | "
                f"{prediction.title()}"
            ),
        )

        self.stop()
        unlock_player(self.owner_id)

    @discord.ui.button(
        label="Higher",
        style=discord.ButtonStyle.primary,
        custom_id="hilo_higher",
    )
    async def higher(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await self.play(
            interaction,
            "higher",
        )

    @discord.ui.button(
        label="Lower",
        style=discord.ButtonStyle.primary,
        custom_id="hilo_lower",
    )
    async def lower(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await self.play(
            interaction,
            "lower",
        )

    async def on_timeout(self):
        if self.finished:
            unlock_player(self.owner_id)
            return

        self.finished = True

        try:
            if self.message:
                await self.message.edit(
                    embed=brand(
                        "Hilo Expired",
                        "The game timed out. Your bet has been refunded.",
                        0xED4245,
                    ),
                    view=None,
                )
        except Exception:
            pass

        try:
            await payout(
                self.owner_id,
                self.bet,
                "Hilo Timeout Refund",
            )
        except Exception:
            pass

        unlock_player(self.owner_id)


# =========================================================
# HILO COMMAND
# =========================================================

@bot.command(
    name="hilo",
)
async def hilo(
    ctx: commands.Context,
    amount: str = None,
):
    """
    .hilo <bet>
    """

    if amount is None:
        await ctx.send(
            embed=brand(
                "Hilo",
                (
                    "**Usage:**\n"
                    "`.hilo <bet>`\n\n"
                    "**Example:**\n"
                    "`.hilo 100`\n\n"
                    "Guess whether the next card is "
                    "higher or lower."
                ),
            )
        )
        return

    try:
        balance = await db_balance(
            ctx.author.id
        )

        bet = resolve_bet(
            amount,
            balance,
        )

    except Exception:
        await ctx.send(
            embed=brand(
                "Invalid Bet",
                "Enter a valid point amount.",
                0xED4245,
            )
        )
        return

    if not await validate_bet(
        ctx,
        bet,
    ):
        return

    if not lock_player(
        ctx.author.id
    ):
        await ctx.send(
            embed=brand(
                "Game Already Running",
                "Finish your current game before starting another one.",
                0xED4245,
            )
        )
        return

    if not await take_bet(
        ctx.author.id,
        bet,
        "Hilo",
    ):
        unlock_player(ctx.author.id)

        await ctx.send(
            embed=brand(
                "Bet Failed",
                "Your balance changed before the bet could be placed.",
                0xED4245,
            )
        )
        return

    try:
        current_card = hilo_random_card()

        view = HiloView(
            owner_id=ctx.author.id,
            bet=bet,
            current_card=current_card,
        )

        message = await ctx.send(
            embed=brand(
                "Hilo",
                (
                    f"**Bet:** {bet:,.0f} Points "
                    f"({usd(bet)})\n\n"
                    f"**Current Card:** "
                    f"`{current_card}`\n\n"
                    "Will the next card be higher or lower?\n\n"
                    "**Multiplier:** 1.96x"
                ),
            ),
            view=view,
        )

        view.message = message

    except Exception:
        try:
            await payout(
                ctx.author.id,
                bet,
                "Hilo Error Refund",
            )
        except Exception:
            pass

        unlock_player(ctx.author.id)

        await ctx.send(
            embed=brand(
                "Hilo Error",
                "The game could not be started. Your bet was refunded.",
                0xED4245,
            )
               )
               # =========================================================
# PART 6/10
# BACCARAT + MARKET
# =========================================================


# =========================================================
# BACCARAT
# =========================================================

BACCARAT_PLAYER_MULTIPLIER = Decimal("1.95")
BACCARAT_BANKER_MULTIPLIER = Decimal("1.95")


def baccarat_card_value(card: str) -> int:
    rank = card[:-1]

    if rank in ("10", "J", "Q", "K"):
        return 0

    if rank == "A":
        return 1

    try:
        return int(rank)
    except ValueError:
        return 0


def baccarat_total(cards: list[str]) -> int:
    return sum(
        baccarat_card_value(card)
        for card in cards
    ) % 10


def baccarat_draw_card(
    shoe: list[str],
) -> str:
    if not shoe:
        shoe.extend(deck())
        random.shuffle(shoe)

    return shoe.pop()


def baccarat_play_round():
    shoe = deck()
    random.shuffle(shoe)

    player = [
        baccarat_draw_card(shoe),
        baccarat_draw_card(shoe),
    ]

    banker = [
        baccarat_draw_card(shoe),
        baccarat_draw_card(shoe),
    ]

    player_total = baccarat_total(player)
    banker_total = baccarat_total(banker)

    # Natural 8 or 9.
    if player_total in (8, 9) or banker_total in (8, 9):
        return player, banker

    # Player third-card rule.
    player_third = None

    if player_total <= 5:
        player_third = baccarat_draw_card(shoe)
        player.append(player_third)

        player_total = baccarat_total(player)

    # Banker third-card rule.
    banker_total = baccarat_total(banker)

    if player_third is None:
        if banker_total <= 5:
            banker.append(
                baccarat_draw_card(shoe)
            )
    else:
        third_value = baccarat_card_value(
            player_third
        )

        banker_draws = False

        if banker_total <= 2:
            banker_draws = True

        elif banker_total == 3:
            banker_draws = third_value != 8

        elif banker_total == 4:
            banker_draws = 2 <= third_value <= 7

        elif banker_total == 5:
            banker_draws = 4 <= third_value <= 7

        elif banker_total == 6:
            banker_draws = 6 <= third_value <= 7

        if banker_draws:
            banker.append(
                baccarat_draw_card(shoe)
            )

    return player, banker


def baccarat_winner(
    player: list[str],
    banker: list[str],
) -> str:
    player_total = baccarat_total(player)
    banker_total = baccarat_total(banker)

    if player_total > banker_total:
        return "player"

    if banker_total > player_total:
        return "banker"

    return "tie"


def baccarat_cards_text(
    cards: list[str],
) -> str:
    return " ".join(
        f"`{card}`"
        for card in cards
    )


# =========================================================
# BACCARAT VIEW
# =========================================================

class BaccaratView(OwnerView):

    def __init__(
        self,
        owner_id: int,
        bet: Decimal,
    ):
        super().__init__(
            owner_id,
            timeout=60,
        )

        self.bet = bet
        self.finished = False

    async def play(
        self,
        interaction: discord.Interaction,
        choice: str,
    ):
        if self.finished:
            return

        self.finished = True

        for item in self.children:
            item.disabled = True

        await interaction.response.send_message(
            content="<a:m_Loading1:1550866495641223188>",
        )

        loading_message = (
            await interaction.original_response()
        )

        try:
            await asyncio.sleep(2)

            player, banker = (
                baccarat_play_round()
            )

            winner = baccarat_winner(
                player,
                banker,
            )

            player_total = baccarat_total(
                player
            )

            banker_total = baccarat_total(
                banker
            )

            won = winner == choice

            if choice == "player":
                multiplier = (
                    BACCARAT_PLAYER_MULTIPLIER
                )

            elif choice == "banker":
                multiplier = (
                    BACCARAT_BANKER_MULTIPLIER
                )

            else:
                multiplier = Decimal("8")

            if winner == "tie":
                # Player/banker bets push on a tie.
                if choice in ("player", "banker"):
                    await payout(
                        self.owner_id,
                        self.bet,
                        "Baccarat Tie Refund",
                    )

                    embed = brand(
                        "Baccarat — Tie",
                        (
                            f"**Bet:** {self.bet:,.0f} Points "
                            f"({usd(self.bet)})\n\n"
                            f"**Player:** {baccarat_cards_text(player)}\n"
                            f"Total: **{player_total}**\n\n"
                            f"**Banker:** {baccarat_cards_text(banker)}\n"
                            f"Total: **{banker_total}**\n\n"
                            "The round ended in a tie.\n"
                            "**Bet refunded.**"
                        ),
                        0xFEE75C,
                    )

                    await loading_message.edit(
                        content=None,
                        embed=embed,
                        view=None,
                    )

                    unlock_player(self.owner_id)
                    return

            if won:
                payout_amount = (
                    self.bet * multiplier
                ).quantize(Decimal("1"))

                await payout(
                    self.owner_id,
                    payout_amount,
                    "Baccarat",
                )

                embed = brand(
                    "Baccarat — You Won",
                    (
                        f"**Bet:** {self.bet:,.0f} Points "
                        f"({usd(self.bet)})\n\n"
                        f"**Player:** {baccarat_cards_text(player)}\n"
                        f"Total: **{player_total}**\n\n"
                        f"**Banker:** {baccarat_cards_text(banker)}\n"
                        f"Total: **{banker_total}**\n\n"
                        f"**Winner:** {winner.title()}\n"
                        f"**Multiplier:** {multiplier}x\n\n"
                        f"**Payout:** "
                        f"{payout_amount:,.0f} Points "
                        f"({usd(payout_amount)})"
                    ),
                    0x57F287,
                )

                await loading_message.edit(
                    content=None,
                    embed=embed,
                    view=None,
                )

                await send_win_log(
                    interaction,
                    game="Baccarat",
                    bet=self.bet,
                    multiplier=multiplier,
                    payout_amount=payout_amount,
                    details=(
                        f"Player {player_total} | "
                        f"Banker {banker_total} | "
                        f"{winner.title()}"
                    ),
                )

            else:
                embed = brand(
                    "Baccarat — You Lost",
                    (
                        f"**Bet:** {self.bet:,.0f} Points "
                        f"({usd(self.bet)})\n\n"
                        f"**Player:** {baccarat_cards_text(player)}\n"
                        f"Total: **{player_total}**\n\n"
                        f"**Banker:** {baccarat_cards_text(banker)}\n"
                        f"Total: **{banker_total}**\n\n"
                        f"**Winner:** {winner.title()}\n\n"
                        "**Payout:** 0 Points"
                    ),
                    0xED4245,
                )

                await loading_message.edit(
                    content=None,
                    embed=embed,
                    view=None,
                )

        except Exception:
            try:
                await payout(
                    self.owner_id,
                    self.bet,
                    "Baccarat Error Refund",
                )
            except Exception:
                pass

            await loading_message.edit(
                content=None,
                embed=brand(
                    "Baccarat Error",
                    (
                        "The game could not be completed.\n"
                        "Your bet has been refunded."
                    ),
                    0xED4245,
                ),
                view=None,
            )

        finally:
            unlock_player(
                self.owner_id
            )

    @discord.ui.button(
        label="Player",
        style=discord.ButtonStyle.primary,
        custom_id="baccarat_player",
    )
    async def player(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await self.play(
            interaction,
            "player",
        )

    @discord.ui.button(
        label="Banker",
        style=discord.ButtonStyle.primary,
        custom_id="baccarat_banker",
    )
    async def banker(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await self.play(
            interaction,
            "banker",
        )


# =========================================================
# BACCARAT COMMAND
# =========================================================

@bot.command(
    name="baccarat",
    aliases=["bacc"],
)
async def baccarat(
    ctx: commands.Context,
    amount: str = None,
):
    """
    .baccarat <bet>
    .bacc <bet>
    """

    if amount is None:
        await ctx.send(
            embed=brand(
                "Baccarat",
                (
                    "**Usage:**\n"
                    "`.baccarat <bet>`\n\n"
                    "**Alias:**\n"
                    "`.bacc <bet>`\n\n"
                    "**Example:**\n"
                    "`.bacc 100`"
                ),
            )
        )
        return

    try:
        balance = await db_balance(
            ctx.author.id
        )

        bet = resolve_bet(
            amount,
            balance,
        )

    except Exception:
        await ctx.send(
            embed=brand(
                "Invalid Bet",
                "Enter a valid point amount.",
                0xED4245,
            )
        )
        return

    if not await validate_bet(
        ctx,
        bet,
    ):
        return

    if not lock_player(
        ctx.author.id
    ):
        await ctx.send(
            embed=brand(
                "Game Already Running",
                "Finish your current game before starting another one.",
                0xED4245,
            )
        )
        return

    if not await take_bet(
        ctx.author.id,
        bet,
        "Baccarat",
    ):
        unlock_player(ctx.author.id)

        await ctx.send(
            embed=brand(
                "Bet Failed",
                "Your balance changed before the bet could be placed.",
                0xED4245,
            )
        )
        return

    try:
        view = BaccaratView(
            owner_id=ctx.author.id,
            bet=bet,
        )

        await ctx.send(
            embed=brand(
                "Baccarat",
                (
                    f"**Bet:** {bet:,.0f} Points "
                    f"({usd(bet)})\n\n"
                    "Choose your bet.\n\n"
                    f"**Player:** "
                    f"{BACCARAT_PLAYER_MULTIPLIER}x\n"
                    f"**Banker:** "
                    f"{BACCARAT_BANKER_MULTIPLIER}x\n"
                    "**Tie:** 8x"
                ),
            ),
            view=view,
        )

    except Exception:
        try:
            await payout(
                ctx.author.id,
                bet,
                "Baccarat Error Refund",
            )
        except Exception:
            pass

        unlock_player(ctx.author.id)

        await ctx.send(
            embed=brand(
                "Baccarat Error",
                "The game could not be started. Your bet was refunded.",
                0xED4245,
            )
        )


# =========================================================
# MARKET GAME
# =========================================================

MARKET_MULTIPLIER = Decimal("1.96")


def market_price() -> Decimal:
    return Decimal(
        str(
            random.randint(
                100,
                10000,
            ) / 100
        )
    )


def market_next_price(
    current: Decimal,
) -> Decimal:
    movement = Decimal(
        str(
            random.uniform(
                -0.12,
                0.12,
            )
        )
    )

    result = (
        current
        * (Decimal("1") + movement)
    )

    if result <= 0:
        result = Decimal("0.01")

    return result.quantize(
        Decimal("0.01")
    )


# =========================================================
# MARKET VIEW
# =========================================================

class MarketView(OwnerView):

    def __init__(
        self,
        owner_id: int,
        bet: Decimal,
        current_price: Decimal,
    ):
        super().__init__(
            owner_id,
            timeout=90,
        )

        self.bet = bet
        self.current_price = current_price
        self.finished = False

    async def play(
        self,
        interaction: discord.Interaction,
        prediction: str,
    ):
        if self.finished:
            return

        self.finished = True

        for item in self.children:
            item.disabled = True

        await interaction.response.send_message(
            content="<a:m_Loading1:1550866495641223188>",
        )

        loading_message = (
            await interaction.original_response()
        )

        try:
            await asyncio.sleep(2)

            next_price = market_next_price(
                self.current_price
            )

            if prediction == "up":
                won = next_price > self.current_price
            else:
                won = next_price < self.current_price

            if won:
                payout_amount = (
                    self.bet * MARKET_MULTIPLIER
                ).quantize(Decimal("1"))

                await payout(
                    self.owner_id,
                    payout_amount,
                    "Market",
                )

                embed = brand(
                    "Market — You Won",
                    (
                        f"**Bet:** {self.bet:,.0f} Points "
                        f"({usd(self.bet)})\n\n"
                        f"**Starting Price:** "
                        f"${self.current_price:,.2f}\n"
                        f"**Ending Price:** "
                        f"${next_price:,.2f}\n\n"
                        f"**Prediction:** "
                        f"{prediction.title()}\n"
                        f"**Multiplier:** "
                        f"{MARKET_MULTIPLIER}x\n\n"
                        f"**Payout:** "
                        f"{payout_amount:,.0f} Points "
                        f"({usd(payout_amount)})"
                    ),
                    0x57F287,
                )

                await loading_message.edit(
                    content=None,
                    embed=embed,
                    view=None,
                )

                await send_win_log(
                    interaction,
                    game="Market",
                    bet=self.bet,
                    multiplier=MARKET_MULTIPLIER,
                    payout_amount=payout_amount,
                    details=(
                        f"${self.current_price:,.2f} -> "
                        f"${next_price:,.2f} | "
                        f"{prediction.title()}"
                    ),
                )

            else:
                embed = brand(
                    "Market — You Lost",
                    (
                        f"**Bet:** {self.bet:,.0f} Points "
                        f"({usd(self.bet)})\n\n"
                        f"**Starting Price:** "
                        f"${self.current_price:,.2f}\n"
                        f"**Ending Price:** "
                        f"${next_price:,.2f}\n\n"
                        f"**Prediction:** "
                        f"{prediction.title()}\n\n"
                        "**Payout:** 0 Points"
                    ),
                    0xED4245,
                )

                await loading_message.edit(
                    content=None,
                    embed=embed,
                    view=None,
                )

        except Exception:
            try:
                await payout(
                    self.owner_id,
                    self.bet,
                    "Market Error Refund",
                )
            except Exception:
                pass

            await loading_message.edit(
                content=None,
                embed=brand(
                    "Market Error",
                    (
                        "The game could not be completed.\n"
                        "Your bet has been refunded."
                    ),
                    0xED4245,
                ),
                view=None,
            )

        finally:
            unlock_player(
                self.owner_id
            )

    @discord.ui.button(
        label="Up",
        style=discord.ButtonStyle.success,
        custom_id="market_up",
    )
    async def up(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await self.play(
            interaction,
            "up",
        )

    @discord.ui.button(
        label="Down",
        style=discord.ButtonStyle.danger,
        custom_id="market_down",
    )
    async def down(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await self.play(
            interaction,
            "down",
        )


# =========================================================
# MARKET COMMAND
# =========================================================

@bot.command(
    name="market",
)
async def market(
    ctx: commands.Context,
    amount: str = None,
):
    """
    .market <bet>
    """

    if amount is None:
        await ctx.send(
            embed=brand(
                "Market",
                (
                    "**Usage:**\n"
                    "`.market <bet>`\n\n"
                    "**Example:**\n"
                    "`.market 100`\n\n"
                    "Predict whether the market price "
                    "will move up or down.\n\n"
                    "**Multiplier:** 1.96x"
                ),
            )
        )
        return

    try:
        balance = await db_balance(
            ctx.author.id
        )

        bet = resolve_bet(
            amount,
            balance,
        )

    except Exception:
        await ctx.send(
            embed=brand(
                "Invalid Bet",
                "Enter a valid point amount.",
                0xED4245,
            )
        )
        return

    if not await validate_bet(
        ctx,
        bet,
    ):
        return

    if not lock_player(
        ctx.author.id
    ):
        await ctx.send(
            embed=brand(
                "Game Already Running",
                "Finish your current game before starting another one.",
                0xED4245,
            )
        )
        return

    if not await take_bet(
        ctx.author.id,
        bet,
        "Market",
    ):
        unlock_player(ctx.author.id)

        await ctx.send(
            embed=brand(
                "Bet Failed",
                "Your balance changed before the bet could be placed.",
                0xED4245,
            )
        )
        return

    try:
        current_price = market_price()

        view = MarketView(
            owner_id=ctx.author.id,
            bet=bet,
            current_price=current_price,
        )

        await ctx.send(
            embed=brand(
                "Market",
                (
                    f"**Bet:** {bet:,.0f} Points "
                    f"({usd(bet)})\n\n"
                    f"**Current Price:** "
                    f"${current_price:,.2f}\n\n"
                    "Choose the direction:\n"
                    "**Up** or **Down**\n\n"
                    "**Multiplier:** 1.96x"
                ),
            ),
            view=view,
        )

    except Exception:
        try:
            await payout(
                ctx.author.id,
                bet,
                "Market Error Refund",
            )
        except Exception:
            pass

        unlock_player(ctx.author.id)

        await ctx.send(
            embed=brand(
                "Market Error",
                "The game could not be started. Your bet was refunded.",
                0xED4245,
            )
               )
          # =========================================================
# PART 7 — HELP / BALANCE / STATS / LEADERBOARD / REWARDS
# =========================================================

HELP_CATEGORIES = {
    "Games": {
        ".mines <bet> [mines]": "Play Mines.",
        ".bj <bet>": "Play Blackjack.",
        ".cf <bet> <heads/tails>": "Play Coinflip.",
        ".hilo <bet>": "Play Hi-Lo.",
        ".market <bet>": "Predict the market.",
        ".baccarat <bet> <player/banker>": "Play Baccarat.",
        ".crazydice <bet>": "Play Crazy Dice.",
        ".cd <bet>": "Crazy Dice alias.",
    },
    "Balance": {
        ".balance": "Check your balance.",
        ".bal": "Check your balance.",
        ".b": "Balance alias.",
        ".stats": "View your casino statistics.",
        ".leaderboard": "View the richest players.",
        ".lb": "Leaderboard alias.",
        ".daily": "Claim your daily reward.",
        ".weekly": "Open your weekly reward.",
        ".week": "Weekly reward alias.",
        ".monthly": "Open your monthly reward.",
    },
    "General": {
        ".help": "Show this help menu.",
        ".whois <user>": "View another user's profile.",
        ".tip <user> <amount>": "Tip another user.",
        ".vault": "View your vault.",
        ".claim": "Claim available rewards.",
        ".deposit": "View deposit information.",
        ".withdraw": "Withdraw your balance.",
        ".price": "View supported crypto prices.",
        ".ai": "Open the AI assistant.",
    },
}


def format_points(value):
    try:
        value = Decimal(str(value))
    except Exception:
        value = Decimal("0")

    if value == value.to_integral():
        return f"{int(value):,}"

    return f"{value:,.2f}"


def points_to_usd(points):
    try:
        points = Decimal(str(points))
    except Exception:
        points = Decimal("0")

    return points / Decimal("200")


def format_usd(points):
    usd = points_to_usd(points)
    return f"${usd:,.2f}"


def decimal_floor(value):
    value = Decimal(str(value))
    return value.quantize(Decimal("0.01"))


async def get_display_balance(bot, user_id):
    balance = await db_balance(bot, user_id)
    return Decimal(str(balance))


# =========================================================
# HELP
# =========================================================

class HelpSelect(discord.ui.Select):
    def __init__(self, author_id):
        self.author_id = author_id

        options = [
            discord.SelectOption(
                label="Games",
                value="Games",
                description="Casino games and betting commands.",
            ),
            discord.SelectOption(
                label="Balance",
                value="Balance",
                description="Balance, rewards and statistics.",
            ),
            discord.SelectOption(
                label="General",
                value="General",
                description="General casino commands.",
            ),
        ]

        super().__init__(
            placeholder="Select a category...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "This help menu belongs to another user.",
                ephemeral=True,
            )
            return

        category = self.values[0]
        commands_list = HELP_CATEGORIES.get(category, {})

        description = "\n".join(
            f"`{command}` — {description}"
            for command, description in commands_list.items()
        )

        embed = discord.Embed(
            title=f"Help — {category}",
            description=description,
        )

        await interaction.response.edit_message(
            embed=embed,
            view=self.view,
        )


class HelpView(discord.ui.View):
    def __init__(self, author_id):
        super().__init__(timeout=180)

        self.author_id = author_id
        self.add_item(HelpSelect(author_id))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


@bot.command(name="help")
async def help_command(ctx, command_name=None):
    if command_name:
        command_name = command_name.lower().strip()

        aliases = {
            "b": "balance",
            "bal": "balance",
            "lb": "leaderboard",
            "cd": "crazydice",
            "cf": "coinflip",
            "bj": "blackjack",
            "bacc": "baccarat",
            "week": "weekly",
        }

        command_name = aliases.get(command_name, command_name)

        command_obj = bot.get_command(command_name)

        if command_obj is None:
            await ctx.send(
                embed=discord.Embed(
                    title="Help",
                    description=f"No command named `{command_name}` was found.",
                )
            )
            return

        aliases_text = ", ".join(
            f"`{a}`" for a in getattr(command_obj, "aliases", [])
        )

        description = command_obj.help or "No description available."

        if aliases_text:
            description += f"\n\nAliases: {aliases_text}"

        embed = discord.Embed(
            title=f"Help — .{command_name}",
            description=description,
        )

        await ctx.send(embed=embed)
        return

    embed = discord.Embed(
        title="Casino Help",
        description=(
            "Select a category below to view available commands.\n\n"
            "All casino games have a minimum bet of "
            f"**{format_points(MINIMUM_BET)} points** "
            f"({format_usd(MINIMUM_BET)})."
        ),
    )

    await ctx.send(
        embed=embed,
        view=HelpView(ctx.author.id),
    )


# =========================================================
# BALANCE
# =========================================================

@bot.command(
    name="balance",
    aliases=["bal", "b"],
    help="Check your casino balance.",
)
async def balance_command(ctx):
    balance = await get_display_balance(bot, ctx.author.id)

    embed = discord.Embed(
        title=f"{ctx.author.display_name}'s Balance",
        description=(
            f"Points\n"
            f"`{format_points(balance)}`\n\n"
            f"USD Value\n"
            f"`{format_usd(balance)}`"
        ),
    )

    await ctx.send(embed=embed)


# =========================================================
# STATS
# =========================================================

@bot.command(
    name="stats",
    help="View your casino statistics.",
)
async def stats_command(ctx, member: discord.Member = None):
    member = member or ctx.author

    stats = await get_user_stats(bot, member.id)

    balance = Decimal(str(stats.get("balance", 0)))
    wagered = Decimal(str(stats.get("wagered", 0)))
    deposited = Decimal(str(stats.get("deposited", 0)))
    withdrawn = Decimal(str(stats.get("withdrawn", 0)))
    wins = int(stats.get("wins", 0) or 0)
    losses = int(stats.get("losses", 0) or 0)

    embed = discord.Embed(
        title=f"{member.display_name}'s Stats",
        description=(
            f"Balance: `{format_points(balance)}` "
            f"({format_usd(balance)})\n"
            f"Wagered: `{format_points(wagered)}` "
            f"({format_usd(wagered)})\n"
            f"Deposited: `{format_points(deposited)}` "
            f"({format_usd(deposited)})\n"
            f"Withdrawn: `{format_points(withdrawn)}` "
            f"({format_usd(withdrawn)})\n\n"
            f"Wins: `{wins:,}`\n"
            f"Losses: `{losses:,}`"
        ),
    )

    await ctx.send(embed=embed)


# =========================================================
# WHOIS
# =========================================================

@bot.command(
    name="whois",
    help="View another user's casino profile.",
)
async def whois_command(ctx, member: discord.Member = None):
    member = member or ctx.author

    stats = await get_user_stats(bot, member.id)

    balance = Decimal(str(stats.get("balance", 0)))
    wagered = Decimal(str(stats.get("wagered", 0)))
    wins = int(stats.get("wins", 0) or 0)
    losses = int(stats.get("losses", 0) or 0)

    embed = discord.Embed(
        title=member.display_name,
        description=(
            f"User: {member.mention}\n"
            f"Balance: `{format_points(balance)}` "
            f"({format_usd(balance)})\n"
            f"Wagered: `{format_points(wagered)}`\n"
            f"Wins: `{wins:,}`\n"
            f"Losses: `{losses:,}`"
        ),
    )

    await ctx.send(embed=embed)


# =========================================================
# LEADERBOARD
# =========================================================

@bot.command(
    name="leaderboard",
    aliases=["lb"],
    help="View the richest casino players.",
)
async def leaderboard_command(ctx):
    rows = []

    try:
        rows = await bot.db.get_leaderboard(limit=10)
    except Exception:
        rows = []

    if not rows:
        await ctx.send(
            embed=discord.Embed(
                title="Leaderboard",
                description="There are no leaderboard records yet.",
            )
        )
        return

    lines = []

    for index, row in enumerate(rows, start=1):
        if isinstance(row, dict):
            user_id = row.get("user_id") or row.get("id")
            balance = row.get("balance", 0)
        else:
            try:
                user_id = row[0]
                balance = row[1]
            except Exception:
                continue

        try:
            user = ctx.guild.get_member(int(user_id))
        except Exception:
            user = None

        name = user.display_name if user else f"User {user_id}"

        lines.append(
            f"`#{index}` **{name}** — "
            f"`{format_points(balance)} points` "
            f"({format_usd(balance)})"
        )

    embed = discord.Embed(
        title="Leaderboard",
        description="\n".join(lines) or "No records available.",
    )

    await ctx.send(embed=embed)


# =========================================================
# REWARD DATABASE HELPERS
# =========================================================

async def get_reward_timestamp(user_id, reward_name):
    key = f"reward:{reward_name}:{user_id}"

    try:
        value = await bot.db.get_setting(key)
    except Exception:
        value = None

    if value is None:
        return 0

    try:
        return int(value)
    except Exception:
        return 0


async def set_reward_timestamp(user_id, reward_name, timestamp):
    key = f"reward:{reward_name}:{user_id}"

    try:
        await bot.db.set_setting(key, str(int(timestamp)))
        return True
    except Exception:
        return False


async def get_user_wagered(bot, user_id):
    stats = await get_user_stats(bot, user_id)

    try:
        return Decimal(str(stats.get("wagered", 0)))
    except Exception:
        return Decimal("0")


# =========================================================
# DAILY
# =========================================================

@bot.command(
    name="daily",
    help="Claim 1 point once every 24 hours.",
)
async def daily_command(ctx):
    user_id = ctx.author.id

    now = int(time.time())
    last_claim = await get_reward_timestamp(user_id, "daily")

    cooldown = 24 * 60 * 60
    remaining = cooldown - (now - last_claim)

    if last_claim and remaining > 0:
        hours = remaining // 3600
        minutes = (remaining % 3600) // 60
        seconds = remaining % 60

        await ctx.send(
            embed=discord.Embed(
                title="Daily",
                description=(
                    f"You already claimed your daily reward.\n\n"
                    f"Next claim in: `{hours}h {minutes}m {seconds}s`"
                ),
            )
        )
        return

    reward = Decimal("1")

    await db_change_balance(
        bot,
        user_id,
        reward,
        "Daily reward",
    )

    await set_reward_timestamp(
        user_id,
        "daily",
        now,
    )

    await ctx.send(
        embed=discord.Embed(
            title="Daily Reward",
            description=(
                f"You received `{format_points(reward)} point`."
            ),
        )
    )


# =========================================================
# WEEKLY / MONTHLY REWARD VIEW
# =========================================================

class RewardClaimButton(discord.ui.Button):
    def __init__(self, reward_type, amount, author_id):
        self.reward_type = reward_type
        self.amount = Decimal(str(amount))
        self.author_id = author_id

        disabled = self.amount <= 0

        label = (
            f"Claim ({format_points(self.amount)} points)"
            if self.amount > 0
            else "Claim (0 points)"
        )

        super().__init__(
            label=label,
            style=discord.ButtonStyle.secondary,
            disabled=disabled,
        )

    async def callback(self, interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "This reward panel belongs to another user.",
                ephemeral=True,
            )
            return

        if self.amount <= 0:
            await interaction.response.send_message(
                "There is nothing available to claim.",
                ephemeral=True,
            )
            return

        reward_type = self.reward_type

        now = int(time.time())

        if reward_type == "weekly":
            cooldown = 7 * 24 * 60 * 60
        else:
            cooldown = 30 * 24 * 60 * 60

        last_claim = await get_reward_timestamp(
            self.author_id,
            reward_type,
        )

        if last_claim and now - last_claim < cooldown:
            await interaction.response.send_message(
                "This reward has already been claimed for this period.",
                ephemeral=True,
            )
            return

        amount = self.amount

        await db_change_balance(
            bot,
            self.author_id,
            amount,
            f"{reward_type.title()} reward",
        )

        await set_reward_timestamp(
            self.author_id,
            reward_type,
            now,
        )

        self.disabled = True
        self.label = f"Claimed ({format_points(amount)} points)"

        embed = discord.Embed(
            title=f"{reward_type.title()} Reward",
            description=(
                f"Claimed `{format_points(amount)} points`.\n\n"
                f"Your next {reward_type} reward will be available "
                f"after the next {reward_type} period."
            ),
        )

        await interaction.response.edit_message(
            embed=embed,
            view=self.view,
        )


class RewardView(discord.ui.View):
    def __init__(
        self,
        reward_type,
        amount,
        author_id,
    ):
        super().__init__(timeout=180)

        self.reward_type = reward_type
        self.amount = Decimal(str(amount))
        self.author_id = author_id

        self.add_item(
            RewardClaimButton(
                reward_type,
                amount,
                author_id,
            )
        )

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


async def build_reward_panel(ctx, reward_type):
    user_id = ctx.author.id
    now = int(time.time())

    if reward_type == "weekly":
        cooldown = 7 * 24 * 60 * 60
        percentage = Decimal("0.01")
        title = "Weekly Reward"
        period_name = "week"
    else:
        cooldown = 30 * 24 * 60 * 60
        percentage = Decimal("0.005")
        title = "Monthly Reward"
        period_name = "month"

    last_claim = await get_reward_timestamp(
        user_id,
        reward_type,
    )

    wagered = await get_user_wagered(
        bot,
        user_id,
    )

    calculated_amount = decimal_floor(
        wagered * percentage
    )

    if calculated_amount < 0:
        calculated_amount = Decimal("0")

    if last_claim:
        elapsed = now - last_claim

        if elapsed < cooldown:
            claimable = Decimal("0")
            remaining = cooldown - elapsed
        else:
            claimable = calculated_amount
            remaining = 0
    else:
        claimable = calculated_amount
        remaining = 0

    if remaining > 0:
        days = remaining // 86400
        hours = (remaining % 86400) // 3600
        minutes = (remaining % 3600) // 60

        next_text = f"{days}d {hours}h {minutes}m"
    else:
        next_text = "Available now"

    if reward_type == "weekly":
        current_text = (
            f"`{format_points(claimable)} points`"
        )
    else:
        current_text = (
            f"`{format_points(claimable)} points`"
        )

    description = (
        f"Currently Claimable:\n"
        f"{current_text}\n\n"
        f"Next {period_name.title()}:\n"
        f"`{next_text}`\n\n"
        f"Calculation:\n"
        f"`{percentage * 100}%` of your wagered points\n\n"
        f"Total Wagered:\n"
        f"`{format_points(wagered)} points`"
    )

    embed = discord.Embed(
        title=title,
        description=description,
    )

    await ctx.send(
        embed=embed,
        view=RewardView(
            reward_type,
            claimable,
            user_id,
        ),
    )


# =========================================================
# WEEKLY
# =========================================================

@bot.command(
    name="weekly",
    aliases=["week"],
    help="Claim 1% of your wagered points once per week.",
)
async def weekly_command(ctx):
    await build_reward_panel(
        ctx,
        "weekly",
    )


# =========================================================
# MONTHLY
# =========================================================

@bot.command(
    name="monthly",
    help="Claim 0.50% of your wagered points once per month.",
)
async def monthly_command(ctx):
    await build_reward_panel(
        ctx,
        "monthly",
)
          # =========================================================
# PART 8 — TIP / VAULT / CLAIM / RAIN / SOS
# =========================================================


# =========================================================
# TIP
# =========================================================

@bot.command(
    name="tip",
    help="Tip another user points.",
)
async def tip_command(ctx, member: discord.Member = None, amount: str = None):
    if member is None or amount is None:
        await ctx.send(
            embed=discord.Embed(
                title="Tip",
                description="Usage: `.tip @user <amount>`",
            )
        )
        return

    if member.bot:
        await ctx.send(
            embed=discord.Embed(
                title="Tip",
                description="You cannot tip a bot.",
            )
        )
        return

    if member.id == ctx.author.id:
        await ctx.send(
            embed=discord.Embed(
                title="Tip",
                description="You cannot tip yourself.",
            )
        )
        return

    try:
        tip_amount = Decimal(str(amount).replace(",", "").strip())
    except Exception:
        await ctx.send(
            embed=discord.Embed(
                title="Tip",
                description="Enter a valid point amount.",
            )
        )
        return

    if tip_amount <= 0:
        await ctx.send(
            embed=discord.Embed(
                title="Tip",
                description="The amount must be greater than 0.",
            )
        )
        return

    if tip_amount != tip_amount.to_integral():
        tip_amount = tip_amount.quantize(Decimal("0.01"))

    sender_balance = await db_balance(
        bot,
        ctx.author.id,
    )

    if sender_balance < tip_amount:
        await ctx.send(
            embed=discord.Embed(
                title="Tip",
                description=(
                    f"You only have `{format_points(sender_balance)} points`."
                ),
            )
        )
        return

    await db_change_balance(
        bot,
        ctx.author.id,
        -tip_amount,
        f"Tip sent to {member.id}",
    )

    await db_change_balance(
        bot,
        member.id,
        tip_amount,
        f"Tip received from {ctx.author.id}",
    )

    embed = discord.Embed(
        title="Tip Sent",
        description=(
            f"{ctx.author.mention} tipped {member.mention}\n\n"
            f"Amount: `{format_points(tip_amount)} points`\n"
            f"USD Value: `{format_usd(tip_amount)}`"
        ),
    )

    await ctx.send(embed=embed)


# =========================================================
# VAULT HELPERS
# =========================================================

async def get_vault_balance(user_id):
    key = f"vault:{user_id}"

    try:
        value = await bot.db.get_setting(key)

        if value is None:
            return Decimal("0")

        return Decimal(str(value))
    except Exception:
        return Decimal("0")


async def set_vault_balance(user_id, amount):
    key = f"vault:{user_id}"

    try:
        await bot.db.set_setting(
            key,
            str(Decimal(str(amount))),
        )
        return True
    except Exception:
        return False


# =========================================================
# VAULT
# =========================================================

@bot.command(
    name="vault",
    help="View and manage your vault.",
)
async def vault_command(ctx):
    balance = await db_balance(
        bot,
        ctx.author.id,
    )

    vault = await get_vault_balance(
        ctx.author.id,
    )

    embed = discord.Embed(
        title="Vault",
        description=(
            f"Wallet Balance\n"
            f"`{format_points(balance)} points`\n\n"
            f"Vault Balance\n"
            f"`{format_points(vault)} points`\n\n"
            f"Use the buttons below to move points."
        ),
    )

    await ctx.send(
        embed=embed,
        view=VaultView(
            ctx.author.id,
        ),
    )


class VaultView(discord.ui.View):
    def __init__(self, author_id):
        super().__init__(timeout=180)

        self.author_id = author_id

        deposit_button = discord.ui.Button(
            label="Deposit",
            style=discord.ButtonStyle.secondary,
        )

        withdraw_button = discord.ui.Button(
            label="Withdraw",
            style=discord.ButtonStyle.secondary,
        )

        deposit_button.callback = self.deposit_callback
        withdraw_button.callback = self.withdraw_callback

        self.add_item(deposit_button)
        self.add_item(withdraw_button)

    async def deposit_callback(self, interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "This vault belongs to another user.",
                ephemeral=True,
            )
            return

        balance = await db_balance(
            bot,
            self.author_id,
        )

        if balance <= 0:
            await interaction.response.send_message(
                "You do not have any points available to move into your vault.",
                ephemeral=True,
            )
            return

        modal = VaultAmountModal(
            self.author_id,
            "deposit",
            balance,
        )

        await interaction.response.send_modal(modal)

    async def withdraw_callback(self, interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "This vault belongs to another user.",
                ephemeral=True,
            )
            return

        vault = await get_vault_balance(
            self.author_id,
        )

        if vault <= 0:
            await interaction.response.send_message(
                "Your vault is empty.",
                ephemeral=True,
            )
            return

        modal = VaultAmountModal(
            self.author_id,
            "withdraw",
            vault,
        )

        await interaction.response.send_modal(modal)


class VaultAmountModal(discord.ui.Modal):
    def __init__(
        self,
        author_id,
        action,
        available,
    ):
        super().__init__(
            title="Vault Amount",
        )

        self.author_id = author_id
        self.action = action
        self.available = Decimal(str(available))

        self.amount = discord.ui.TextInput(
            label="Amount",
            placeholder="Enter points",
            required=True,
            max_length=30,
        )

        self.add_item(self.amount)

    async def on_submit(self, interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "This vault belongs to another user.",
                ephemeral=True,
            )
            return

        try:
            amount = Decimal(
                str(self.amount.value)
                .replace(",", "")
                .strip()
            )
        except Exception:
            await interaction.response.send_message(
                "Enter a valid amount.",
                ephemeral=True,
            )
            return

        if amount <= 0:
            await interaction.response.send_message(
                "Amount must be greater than 0.",
                ephemeral=True,
            )
            return

        if amount > self.available:
            await interaction.response.send_message(
                f"You only have `{format_points(self.available)} points` available.",
                ephemeral=True,
            )
            return

        if self.action == "deposit":
            await db_change_balance(
                bot,
                self.author_id,
                -amount,
                "Vault deposit",
            )

            vault = await get_vault_balance(
                self.author_id,
            )

            await set_vault_balance(
                self.author_id,
                vault + amount,
            )

            new_vault = vault + amount

            description = (
                f"Moved `{format_points(amount)} points` into your vault.\n\n"
                f"Vault Balance: `{format_points(new_vault)} points`"
            )

        else:
            await set_vault_balance(
                self.author_id,
                self.available - amount,
            )

            await db_change_balance(
                bot,
                self.author_id,
                amount,
                "Vault withdrawal",
            )

            description = (
                f"Moved `{format_points(amount)} points` "
                f"from your vault to your balance."
            )

        await interaction.response.send_message(
            embed=discord.Embed(
                title="Vault Updated",
                description=description,
            ),
            ephemeral=True,
        )


# =========================================================
# CLAIM
# =========================================================

@bot.command(
    name="claim",
    help="View available rewards.",
)
async def claim_command(ctx):
    now = int(time.time())
    user_id = ctx.author.id

    daily_last = await get_reward_timestamp(
        user_id,
        "daily",
    )

    weekly_last = await get_reward_timestamp(
        user_id,
        "weekly",
    )

    monthly_last = await get_reward_timestamp(
        user_id,
        "monthly",
    )

    daily_ready = (
        daily_last == 0
        or now - daily_last >= 24 * 60 * 60
    )

    weekly_wager = await get_user_wagered(
        bot,
        user_id,
    )

    weekly_amount = decimal_floor(
        weekly_wager * Decimal("0.01")
    )

    monthly_amount = decimal_floor(
        weekly_wager * Decimal("0.005")
    )

    weekly_ready = (
        weekly_last == 0
        or now - weekly_last >= 7 * 24 * 60 * 60
    )

    monthly_ready = (
        monthly_last == 0
        or now - monthly_last >= 30 * 24 * 60 * 60
    )

    lines = [
        (
            f"Daily: "
            f"`{'1 point available' if daily_ready else 'Already claimed'}`"
        ),
        (
            f"Weekly: "
            f"`{format_points(weekly_amount)} points` "
            f"{'(available)' if weekly_ready else '(waiting)'}"
        ),
        (
            f"Monthly: "
            f"`{format_points(monthly_amount)} points` "
            f"{'(available)' if monthly_ready else '(waiting)'}"
        ),
    ]

    embed = discord.Embed(
        title="Rewards",
        description="\n".join(lines),
    )

    await ctx.send(embed=embed)


# =========================================================
# RAIN
# =========================================================

class RainJoinButton(discord.ui.Button):
    def __init__(self, rain_id):
        super().__init__(
            label="Join Rain",
            style=discord.ButtonStyle.secondary,
        )

        self.rain_id = rain_id

    async def callback(self, interaction):
        rain = bot.active_rains.get(self.rain_id)

        if rain is None:
            await interaction.response.send_message(
                "This rain has ended.",
                ephemeral=True,
            )
            return

        user_id = interaction.user.id

        if user_id in rain["users"]:
            await interaction.response.send_message(
                "You are already in this rain.",
                ephemeral=True,
            )
            return

        rain["users"].add(user_id)

        await interaction.response.send_message(
            "You joined the rain.",
            ephemeral=True,
        )


class RainView(discord.ui.View):
    def __init__(self, rain_id):
        super().__init__(timeout=None)

        self.add_item(
            RainJoinButton(rain_id)
        )


@bot.command(
    name="rain",
    help="Create a points rain.",
)
@commands.has_permissions(administrator=True)
async def rain_command(ctx, amount: str = None, winners: int = 1):
    if amount is None:
        await ctx.send(
            embed=discord.Embed(
                title="Rain",
                description="Usage: `.rain <amount> [winners]`",
            )
        )
        return

    try:
        total_amount = Decimal(
            str(amount)
            .replace(",", "")
            .strip()
        )
    except Exception:
        await ctx.send(
            embed=discord.Embed(
                title="Rain",
                description="Enter a valid point amount.",
            )
        )
        return

    if total_amount <= 0:
        await ctx.send(
            embed=discord.Embed(
                title="Rain",
                description="The rain amount must be greater than 0.",
            )
        )
        return

    try:
        winners = int(winners)
    except Exception:
        winners = 1

    if winners < 1:
        winners = 1

    if winners > 100:
        winners = 100

    rain_id = f"{ctx.guild.id}:{ctx.channel.id}:{time.time_ns()}"

    if not hasattr(bot, "active_rains"):
        bot.active_rains = {}

    bot.active_rains[rain_id] = {
        "amount": total_amount,
        "winners": winners,
        "users": set(),
        "created_by": ctx.author.id,
    }

    embed = discord.Embed(
        title="Rain",
        description=(
            f"Total Amount: `{format_points(total_amount)} points`\n"
            f"Winners: `{winners}`\n\n"
            f"Click **Join Rain** to participate."
        ),
    )

    await ctx.send(
        embed=embed,
        view=RainView(rain_id),
    )


@bot.command(
    name="rainend",
    help="End a rain and distribute its points.",
)
@commands.has_permissions(administrator=True)
async def rainend_command(ctx, rain_id: str = None):
    if not rain_id:
        await ctx.send(
            embed=discord.Embed(
                title="Rain",
                description="A rain ID is required.",
            )
        )
        return

    if not hasattr(bot, "active_rains"):
        bot.active_rains = {}

    rain = bot.active_rains.pop(
        rain_id,
        None,
    )

    if rain is None:
        await ctx.send(
            embed=discord.Embed(
                title="Rain",
                description="Rain not found.",
            )
        )
        return

    users = list(rain["users"])

    if not users:
        await ctx.send(
            embed=discord.Embed(
                title="Rain Ended",
                description="Nobody joined the rain.",
            )
        )
        return

    winner_count = min(
        rain["winners"],
        len(users),
    )

    selected = random.sample(
        users,
        winner_count,
    )

    total = rain["amount"]

    base_share = (
        total / Decimal(str(winner_count))
    ).quantize(Decimal("0.01"))

    distributed = Decimal("0")

    for index, user_id in enumerate(selected):
        if index == winner_count - 1:
            reward = total - distributed
        else:
            reward = base_share

        if reward <= 0:
            continue

        distributed += reward

        await db_change_balance(
            bot,
            user_id,
            reward,
            "Rain reward",
        )

    lines = []

    for user_id in selected:
        member = ctx.guild.get_member(user_id)

        if member:
            name = member.mention
        else:
            name = f"<@{user_id}>"

        lines.append(
            f"{name} — `{format_points(base_share)} points`"
        )

    await ctx.send(
        embed=discord.Embed(
            title="Rain Ended",
            description="\n".join(lines),
        )
    )


# =========================================================
# SOS
# =========================================================

@bot.command(
    name="sos",
    help="Request assistance from casino staff.",
)
async def sos_command(ctx, *, reason: str = None):
    if reason is None:
        reason = "No reason provided."

    embed = discord.Embed(
        title="Support Request",
        description=(
            f"User: {ctx.author.mention}\n"
            f"Channel: {ctx.channel.mention}\n\n"
            f"Reason:\n"
            f"{reason}"
        ),
    )

    await ctx.send(embed=embed)


# =========================================================
# RAIN ERROR HANDLER
# =========================================================

@rain_command.error
async def rain_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send(
            embed=discord.Embed(
                title="Rain",
                description="You need administrator permission to use this command.",
            )
        )
        return

    if isinstance(error, commands.BadArgument):
        await ctx.send(
            embed=discord.Embed(
                title="Rain",
                description="Invalid command arguments.",
            )
        )
        return

    raise error


@rainend_command.error
async def rainend_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send(
            embed=discord.Embed(
                title="Rain",
                description="You need administrator permission to use this command.",
            )
        )
        return

    raise error
          
# =========================================================
# PART 9 — DEPOSIT & WITHDRAW
# =========================================================

import discord
from discord.ext import commands
from decimal import Decimal, InvalidOperation


# =========================================================
# FIXED DEPOSIT ADDRESSES
# =========================================================

DEPOSIT_ADDRESSES = {
    "usdt": "0xc21F13F95afb0d53D54ccCa378E177F50f41ECF2",
    "sol": "HKn9yAXBBUhPpgTrgnxndLL5QCqocpn8nHjNeWTB7Kv6",
    "ltc": "LfdpchVVZbgysmqykQoHTYziUow6C14cwq",
}


# =========================================================
# DEPOSIT SETTINGS
# =========================================================

DEPOSIT_MINIMUMS = {
    "usdt": Decimal("0.50"),
    "sol": Decimal("0.001"),
    "ltc": Decimal("0.0005"),
}

# 1 point = 0.0001 coin
DEPOSIT_POINT_CONVERSION = {
    "usdt": Decimal("0.0001"),
    "sol": Decimal("0.0001"),
    "ltc": Decimal("0.0001"),
}


# =========================================================
# WITHDRAW SETTINGS
# =========================================================

WITHDRAW_MINIMUMS = {
    "ltc": Decimal("20"),
    "sol": Decimal("200"),
    "usdt": Decimal("250"),
}


# =========================================================
# CURRENCY DISPLAY
# =========================================================

CURRENCY_NAMES = {
    "ltc": "LTC",
    "sol": "SOL",
    "usdt": "USDT",
}


# =========================================================
# DEPOSIT EMBED
# =========================================================

def build_deposit_embed():
    embed = discord.Embed(
        title="Cryptobet — Deposit",
        description="Choose a currency below.",
    )

    embed.add_field(
        name="Deposit Information",
        value=(
            "Your deposit address will be sent to your DMs.\n"
            "Deposits are credited only after blockchain confirmation."
        ),
        inline=False,
    )

    return embed


# =========================================================
# DEPOSIT ADDRESS EMBED
# =========================================================

def build_deposit_address_embed(user, crypto):
    crypto = crypto.lower()

    address = DEPOSIT_ADDRESSES[crypto]

    if crypto == "usdt":
        minimum = "0.50 USDT"
        conversion = "1 point = 0.0001 USDT"

    elif crypto == "sol":
        minimum = "0.001 SOL"
        conversion = "1 point = 0.0001 SOL"

    else:
        minimum = "0.0005 LTC"
        conversion = "1 point = 0.0001 LTC"

    embed = discord.Embed(
        title="Cryptobet — Deposit"
    )

    embed.description = (
        f"{user.mention}, deposit **{CURRENCY_NAMES[crypto]}** only:\n\n"
        f"```{address}```\n\n"
        f"Minimum: **{minimum}**\n"
        f"Conversion: **{conversion}**\n"
        f"Fee: **0%**"
    )

    return embed


# =========================================================
# DEPOSIT BUTTON
# =========================================================

class DepositCurrencyButton(discord.ui.Button):

    def __init__(self, crypto):
        self.crypto = crypto

        super().__init__(
            label=crypto.upper(),
            style=discord.ButtonStyle.secondary,
            custom_id=f"deposit_{crypto}",
        )

    async def callback(self, interaction: discord.Interaction):

        try:
            embed = build_deposit_address_embed(
                interaction.user,
                self.crypto,
            )

            try:
                await interaction.user.send(embed=embed)

                await interaction.response.send_message(
                    "Your deposit address has been sent to your DMs.",
                    ephemeral=True,
                )

            except discord.Forbidden:

                await interaction.response.send_message(
                    "I could not send you a DM. Please enable DMs from this server and try again.",
                    ephemeral=True,
                )

        except Exception:

            if interaction.response.is_done():
                await interaction.followup.send(
                    "Something went wrong while creating the deposit message.",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    "Something went wrong while creating the deposit message.",
                    ephemeral=True,
                )


# =========================================================
# DEPOSIT VIEW
# =========================================================

class DepositView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=300)

        self.add_item(DepositCurrencyButton("ltc"))
        self.add_item(DepositCurrencyButton("sol"))
        self.add_item(DepositCurrencyButton("usdt"))


# =========================================================
# .DEPOSIT
# =========================================================

@bot.command(
    name="deposit",
    aliases=["dep"],
)
async def deposit_command(ctx):

    embed = build_deposit_embed()

    await ctx.send(
        embed=embed,
        view=DepositView(),
    )


# =========================================================
# WITHDRAW EMBED
# =========================================================

def build_withdraw_embed():

    embed = discord.Embed(
        title="Cryptobet — Withdraw",
        description="Choose the currency to withdraw.",
    )

    embed.add_field(
        name="Minimum Withdrawal",
        value=(
            "LTC: **20 points**\n"
            "SOL: **200 points**\n"
            "USDT: **250 points**"
        ),
        inline=False,
    )

    embed.add_field(
        name="Processing",
        value="Your withdrawal will be processed automatically.",
        inline=False,
    )

    return embed


# =========================================================
# WITHDRAW MODAL
# =========================================================

class WithdrawModal(discord.ui.Modal):

    def __init__(self, crypto):
        self.crypto = crypto

        super().__init__(
            title=f"Withdraw {crypto.upper()}"
        )

        self.receiving_address = discord.ui.TextInput(
            label="Enter your receiving address",
            placeholder="Enter your wallet address",
            required=True,
            min_length=5,
            max_length=200,
        )

        self.amount = discord.ui.TextInput(
            label="Enter withdrawing amount in points",
            placeholder="Example: 250",
            required=True,
            min_length=1,
            max_length=20,
        )

        self.add_item(self.receiving_address)
        self.add_item(self.amount)

    async def on_submit(self, interaction: discord.Interaction):

        crypto = self.crypto

        address = self.receiving_address.value.strip()
        amount_raw = self.amount.value.strip()

        try:
            amount = Decimal(amount_raw)

        except (InvalidOperation, ValueError):

            await interaction.response.send_message(
                "Please enter a valid withdrawal amount in points.",
                ephemeral=True,
            )
            return

        if amount <= 0:

            await interaction.response.send_message(
                "Withdrawal amount must be greater than 0 points.",
                ephemeral=True,
            )
            return

        minimum = WITHDRAW_MINIMUMS[crypto]

        if amount < minimum:

            await interaction.response.send_message(
                f"Minimum {crypto.upper()} withdrawal is **{minimum} points**.",
                ephemeral=True,
            )
            return

        # -------------------------------------------------
        # CHECK BALANCE
        # -------------------------------------------------

        try:
            balance = await db_balance(interaction.user.id)

        except Exception:

            await interaction.response.send_message(
                "Unable to check your balance right now. Please try again.",
                ephemeral=True,
            )
            return

        if balance < amount:

            await interaction.response.send_message(
                f"You do not have enough points.\n\n"
                f"Required: **{amount} points**\n"
                f"Balance: **{balance} points**",
                ephemeral=True,
            )
            return

        # -------------------------------------------------
        # DEDUCT BALANCE
        # -------------------------------------------------

        try:

            await db_change_balance(
                interaction.user.id,
                -amount,
            )

        except Exception:

            await interaction.response.send_message(
                "The withdrawal could not be processed. Your balance was not changed.",
                ephemeral=True,
            )
            return

        # -------------------------------------------------
        # SAVE WITHDRAWAL
        # -------------------------------------------------

        withdrawal_saved = False

        try:

            if hasattr(bot.db, "create_withdrawal"):

                result = await bot.db.create_withdrawal(
                    user_id=interaction.user.id,
                    crypto=crypto,
                    amount_points=amount,
                    address=address,
                )

                withdrawal_saved = True

        except Exception:

            withdrawal_saved = False

        # -------------------------------------------------
        # ROLLBACK IF DATABASE SAVE FAILED
        # -------------------------------------------------

        if not withdrawal_saved:

            try:

                await db_change_balance(
                    interaction.user.id,
                    amount,
                )

            except Exception:
                pass

            await interaction.response.send_message(
                "The withdrawal request could not be created. Your balance has been restored.",
                ephemeral=True,
            )
            return

        # -------------------------------------------------
        # SUCCESS
        # -------------------------------------------------

        embed = discord.Embed(
            title="Cryptobet — Withdrawal Submitted",
            description=(
                "Your withdrawal has been submitted for automatic processing."
            ),
        )

        embed.add_field(
            name="Currency",
            value=crypto.upper(),
            inline=True,
        )

        embed.add_field(
            name="Amount",
            value=f"{amount} points",
            inline=True,
        )

        embed.add_field(
            name="Receiving Address",
            value=f"```{address}```",
            inline=False,
        )

        embed.add_field(
            name="Status",
            value="Processing",
            inline=False,
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True,
        )


# =========================================================
# WITHDRAW BUTTON
# =========================================================

class WithdrawCurrencyButton(discord.ui.Button):

    def __init__(self, crypto):

        self.crypto = crypto

        super().__init__(
            label=crypto.upper(),
            style=discord.ButtonStyle.secondary,
            custom_id=f"withdraw_{crypto}",
        )

    async def callback(self, interaction: discord.Interaction):

        await interaction.response.send_modal(
            WithdrawModal(self.crypto)
        )


# =========================================================
# WITHDRAW VIEW
# =========================================================

class WithdrawView(discord.ui.View):

    def __init__(self):

        super().__init__(timeout=300)

        self.add_item(
            WithdrawCurrencyButton("sol")
        )

        self.add_item(
            WithdrawCurrencyButton("ltc")
        )

        self.add_item(
            WithdrawCurrencyButton("usdt")
        )


# =========================================================
# .WITHDRAW
# =========================================================

@bot.command(
    name="withdraw",
    aliases=["wd"],
)
async def withdraw_command(ctx):

    embed = build_withdraw_embed()

    await ctx.send(
        embed=embed,
        view=WithdrawView(),
            )

# =========================================================
# PART 10 — THREADS / ADMIN / SETTINGS / STARTUP
# =========================================================


# =========================================================
# THREAD COMMANDS
# =========================================================

@bot.group(
    name="thread",
    invoke_without_command=True,
    help="Manage casino threads.",
)
async def thread_command(ctx):
    if ctx.invoked_subcommand is None:
        embed = discord.Embed(
            title="Thread",
            description=(
                "` .thread create ` — Create a thread\n"
                "` .thread add @user ` — Add a user\n"
                "` .thread remove @user ` — Remove a user\n"
                "` .thread delete ` — Delete the current thread"
            ).replace("` .", "`."),
        )

        await ctx.send(embed=embed)


@thread_command.command(
    name="create",
    help="Create a private thread.",
)
async def thread_create(ctx):
    thread = await ctx.channel.create_thread(
        name=f"{ctx.author.display_name}-thread",
        type=discord.ChannelType.private_thread,
        invitable=True,
    )

    await thread.add_user(ctx.author)

    await thread.send(
        embed=discord.Embed(
            title="Thread Created",
            description=(
                f"Created by {ctx.author.mention}."
            ),
        )
    )


@thread_command.command(
    name="add",
    help="Add a member to the current thread.",
)
async def thread_add(
    ctx,
    member: discord.Member = None,
):
    if not isinstance(
        ctx.channel,
        discord.Thread,
    ):
        await ctx.send(
            embed=discord.Embed(
                title="Thread",
                description="This command must be used inside a thread.",
            )
        )
        return

    if member is None:
        await ctx.send(
            embed=discord.Embed(
                title="Thread",
                description="Usage: `.thread add @user`",
            )
        )
        return

    try:
        await ctx.channel.add_user(member)

        await ctx.send(
            embed=discord.Embed(
                title="Thread",
                description=f"Added {member.mention} to the thread.",
            )
        )
    except Exception as exc:
        await ctx.send(
            embed=discord.Embed(
                title="Thread",
                description=f"Unable to add the user: `{exc}`",
            )
        )


@thread_command.command(
    name="remove",
    help="Remove a member from the current thread.",
)
async def thread_remove(
    ctx,
    member: discord.Member = None,
):
    if not isinstance(
        ctx.channel,
        discord.Thread,
    ):
        await ctx.send(
            embed=discord.Embed(
                title="Thread",
                description="This command must be used inside a thread.",
            )
        )
        return

    if member is None:
        await ctx.send(
            embed=discord.Embed(
                title="Thread",
                description="Usage: `.thread remove @user`",
            )
        )
        return

    try:
        await ctx.channel.remove_user(member)

        await ctx.send(
            embed=discord.Embed(
                title="Thread",
                description=f"Removed {member.mention} from the thread.",
            )
        )
    except Exception as exc:
        await ctx.send(
            embed=discord.Embed(
                title="Thread",
                description=f"Unable to remove the user: `{exc}`",
            )
        )


@thread_command.command(
    name="delete",
    help="Delete the current thread.",
)
async def thread_delete(ctx):
    if not isinstance(
        ctx.channel,
        discord.Thread,
    ):
        await ctx.send(
            embed=discord.Embed(
                title="Thread",
                description="This command must be used inside a thread.",
            )
        )
        return

    await ctx.send(
        embed=discord.Embed(
            title="Thread",
            description="Deleting this thread...",
        )
    )

    await asyncio.sleep(1)

    try:
        await ctx.channel.delete()
    except Exception:
        pass


# =========================================================
# ADMIN — ADD BALANCE
# =========================================================

@bot.command(
    name="add",
    help="Admin: add points to a user's balance.",
)
@commands.is_owner()
async def add_command(
    ctx,
    amount: str = None,
    member: discord.Member = None,
):
    if amount is None or member is None:
        await ctx.send(
            embed=discord.Embed(
                title="Add Balance",
                description="Usage: `.add <points> @user`",
            )
        )
        return

    try:
        points = Decimal(
            str(amount)
            .replace(",", "")
            .strip()
        )
    except Exception:
        await ctx.send(
            embed=discord.Embed(
                title="Add Balance",
                description="Enter a valid point amount.",
            )
        )
        return

    if points <= 0:
        await ctx.send(
            embed=discord.Embed(
                title="Add Balance",
                description="Amount must be greater than 0.",
            )
        )
        return

    await db_change_balance(
        bot,
        member.id,
        points,
        "Owner balance addition",
    )

    new_balance = await db_balance(
        bot,
        member.id,
    )

    await ctx.send(
        embed=discord.Embed(
            title="Balance Added",
            description=(
                f"User: {member.mention}\n"
                f"Added: `{format_points(points)} points`\n"
                f"New Balance: `{format_points(new_balance)} points`"
            ),
        )
    )


@bot.command(
    name="addbal",
    help="Admin: add points to a user's balance.",
)
@commands.is_owner()
async def addbal_command(
    ctx,
    member: discord.Member = None,
    amount: str = None,
):
    if member is None or amount is None:
        await ctx.send(
            embed=discord.Embed(
                title="Add Balance",
                description="Usage: `.addbal @user <points>`",
            )
        )
        return

    try:
        points = Decimal(
            str(amount)
            .replace(",", "")
            .strip()
        )
    except Exception:
        await ctx.send(
            embed=discord.Embed(
                title="Add Balance",
                description="Enter a valid point amount.",
            )
        )
        return

    if points <= 0:
        await ctx.send(
            embed=discord.Embed(
                title="Add Balance",
                description="Amount must be greater than 0.",
            )
        )
        return

    await db_change_balance(
        bot,
        member.id,
        points,
        "Owner balance addition",
    )

    new_balance = await db_balance(
        bot,
        member.id,
    )

    await ctx.send(
        embed=discord.Embed(
            title="Balance Added",
            description=(
                f"User: {member.mention}\n"
                f"Added: `{format_points(points)} points`\n"
                f"New Balance: `{format_points(new_balance)} points`"
            ),
        )
    )


# =========================================================
# ADMIN — REMOVE BALANCE
# =========================================================

@bot.command(
    name="removebal",
    help="Admin: remove points from a user's balance.",
)
@commands.is_owner()
async def removebal_command(
    ctx,
    member: discord.Member = None,
    amount: str = None,
):
    if member is None or amount is None:
        await ctx.send(
            embed=discord.Embed(
                title="Remove Balance",
                description="Usage: `.removebal @user <points>`",
            )
        )
        return

    try:
        points = Decimal(
            str(amount)
            .replace(",", "")
            .strip()
        )
    except Exception:
        await ctx.send(
            embed=discord.Embed(
                title="Remove Balance",
                description="Enter a valid point amount.",
            )
        )
        return

    if points <= 0:
        await ctx.send(
            embed=discord.Embed(
                title="Remove Balance",
                description="Amount must be greater than 0.",
            )
        )
        return

    balance = await db_balance(
        bot,
        member.id,
    )

    if points > balance:
        points = balance

    if points <= 0:
        await ctx.send(
            embed=discord.Embed(
                title="Remove Balance",
                description="The user has no points to remove.",
            )
        )
        return

    await db_change_balance(
        bot,
        member.id,
        -points,
        "Owner balance removal",
    )

    new_balance = await db_balance(
        bot,
        member.id,
    )

    await ctx.send(
        embed=discord.Embed(
            title="Balance Removed",
            description=(
                f"User: {member.mention}\n"
                f"Removed: `{format_points(points)} points`\n"
                f"New Balance: `{format_points(new_balance)} points`"
            ),
        )
    )


# =========================================================
# ADMIN — WIN LOG
# =========================================================

@bot.command(
    name="winlog",
    help="Set the channel where game wins are logged.",
)
@commands.is_owner()
async def winlog_command(
    ctx,
    channel: discord.TextChannel = None,
):
    if channel is None:
        await ctx.send(
            embed=discord.Embed(
                title="Win Log",
                description="Usage: `.winlog #channel`",
            )
        )
        return

    try:
        await bot.db.set_setting(
            "winlog_channel_id",
            str(channel.id),
        )
    except Exception:
        await ctx.send(
            embed=discord.Embed(
                title="Win Log",
                description="Unable to save the win-log channel.",
            )
        )
        return

    await ctx.send(
        embed=discord.Embed(
            title="Win Log",
            description=(
                f"Future game wins will be logged in {channel.mention}."
            ),
        )
    )


# =========================================================
# ADMIN — RESET USER BALANCE
# =========================================================

@bot.command(
    name="resetbal",
    help="Admin: reset a user's balance to zero.",
)
@commands.is_owner()
async def resetbal_command(
    ctx,
    member: discord.Member = None,
):
    if member is None:
        await ctx.send(
            embed=discord.Embed(
                title="Reset Balance",
                description="Usage: `.resetbal @user`",
            )
        )
        return

    balance = await db_balance(
        bot,
        member.id,
    )

    if balance > 0:
        await db_change_balance(
            bot,
            member.id,
            -balance,
            "Owner balance reset",
        )

    await ctx.send(
        embed=discord.Embed(
            title="Balance Reset",
            description=(
                f"{member.mention}'s balance has been reset."
            ),
        )
    )


# =========================================================
# COMMAND CHECK
# =========================================================

@bot.command(
    name="commands",
    help="Show the number of loaded commands.",
)
async def commands_command(ctx):
    command_count = len(bot.commands)

    await ctx.send(
        embed=discord.Embed(
            title="Commands",
            description=(
                f"Loaded commands: `{command_count}`"
            ),
        )
    )


# =========================================================
# GLOBAL BOT ERROR HANDLER
# =========================================================

@bot.event
async def on_command_error(ctx, error):
    if isinstance(
        error,
        commands.CommandNotFound,
    ):
        return

    if isinstance(
        error,
        commands.MissingRequiredArgument,
    ):
        await ctx.send(
            embed=discord.Embed(
                title="Command Error",
                description=(
                    "A required argument is missing.\n"
                    f"Use `{bot.command_prefix(ctx.message)[0]}help "
                    f"{ctx.command.name}` for usage."
                ),
            )
        )
        return

    if isinstance(
        error,
        commands.BadArgument,
    ):
        await ctx.send(
            embed=discord.Embed(
                title="Command Error",
                description="One or more arguments are invalid.",
            )
        )
        return

    if isinstance(
        error,
        commands.NotOwner,
    ):
        await ctx.send(
            embed=discord.Embed(
                title="Permission Denied",
                description="Only the bot owner can use this command.",
            )
        )
        return

    if isinstance(
        error,
        commands.MissingPermissions,
    ):
        await ctx.send(
            embed=discord.Embed(
                title="Permission Denied",
                description="You do not have permission to use this command.",
            )
        )
        return

    print(
        f"[COMMAND ERROR] "
        f"{ctx.command}: {repr(error)}"
    )


# =========================================================
# FINAL STARTUP
# =========================================================

async def initialize_bot():
    if not hasattr(bot, "active_rains"):
        bot.active_rains = {}

    try:
        await bot.db.connect()
        print("[DATABASE] PostgreSQL connected.")
    except Exception as exc:
        print(
            f"[DATABASE] Connection failed: {exc}"
        )
        raise


async def close_bot():
    try:
        await bot.db.close()
    except Exception:
        pass


# =========================================================
# START
# =========================================================

async def main():
    await initialize_bot()

    try:
        await bot.start(BOT_TOKEN)
    finally:
        await close_bot()


if __name__ == "__main__":
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN is missing from Railway environment variables."
        )

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
