from __future__ import annotations

import asyncio, io, random, time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import aiohttp
import discord
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont

import config
from database import Database
from games import card_value, deck, hand_total, parse_amount, provably_fair

import os

print(
    "OPENAI_API_KEY loaded:",
    bool(os.getenv("OPENAI_API_KEY"))
)


def money(value) -> str: return f"{float(value):,.2f}"
def usd(points) -> str: return f"${float(points) * config.POINT_USD:,.2f}"
def brand(title: str, description: str = "", colour=0x2B2D31):
    return discord.Embed(title=f"{config.CASINO_NAME} — {title}", description=description, colour=colour, timestamp=datetime.now(timezone.utc))
def allowed_admin(ctx): return ctx.author.id in config.ADMIN_USER_IDS or ctx.author.guild_permissions.administrator

CARDS_DIR = Path(__file__).resolve().parent

def image_file(image: Image.Image, name: str) -> discord.File:
    output = io.BytesIO()
    image.save(output, "PNG")
    output.seek(0)
    return discord.File(output, filename=name)

def card_image_name(card: str) -> str:
    rank, suit = card[:-1], card[-1]
    rank_name = {"A": "ace", "J": "jack", "Q": "queen", "K": "king"}.get(rank, rank)
    suit_name = {"♣": "clubs", "♦": "diamonds", "♥": "hearts", "♠": "spades"}[suit]
    return f"{rank_name}_of_{suit_name}.png"

def blackjack_table(player, dealer, reveal=False) -> discord.File:
    canvas = Image.new("RGB", (1200, 680), "#0a422d")
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((25, 25, 1175, 655), radius=35, outline="#d9b66b", width=5)
    font = ImageFont.load_default()
    draw.text((50, 55), "DEALER", fill="#f5e7c0", font=font)
    draw.text((50, 385), "PLAYER", fill="#f5e7c0", font=font)
    def paste_card(card, x, y, hidden=False):
        if hidden:
            draw.rounded_rectangle((x, y, x + 150, y + 220), radius=12, fill="#111827", outline="#d9b66b", width=4)
            draw.text((x + 53, y + 105), "?", fill="#d9b66b", font=font)
            return
        path = CARDS_DIR / card_image_name(card)
        if path.exists():
            image = Image.open(path).convert("RGBA").resize((150, 220), Image.Resampling.LANCZOS)
            canvas.paste(image, (x, y), image)
        else:
            draw.rounded_rectangle((x, y, x + 150, y + 220), radius=12, fill="#f7f7f7")
            draw.text((x + 40, y + 105), card, fill="#111111", font=font)
    for index, card in enumerate(dealer): paste_card(card, 50 + index * 175, 95, hidden=(index == 1 and not reveal))
    for index, card in enumerate(player): paste_card(card, 50 + index * 175, 425)
    return image_file(canvas, "blackjack_table.png")

COINFLIP_IMAGES = {
    "tails": "https://cdn.bloxjack.com/assets/chip-tails-v2.webp?v=20260826-1",
    "heads": "https://cdn.bloxjack.com/assets/chip-heads-v2.webp?v=20260826-1",}

def _font(size=42, bold=False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        str(CARDS_DIR / ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")),
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            pass
    return ImageFont.load_default()







class CasinoBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default(); intents.message_content = True; intents.members = True
        super().__init__(command_prefix=lambda bot, msg: (".", ","), intents=intents, help_command=None)
        self.db = Database(config.DATABASE_URL) if config.DATABASE_URL else None
        self.cooldowns: dict[int, float] = {}

    async def setup_hook(self):
        if not self.db: raise RuntimeError("DATABASE_URL is missing from Railway variables.")
        await self.db.connect()

    async def close(self):
        if self.db: await self.db.close()
        await super().close()

    async def game_allowed(self, ctx) -> bool:
        if await self.db.setting("frozen", "0") == "1":
            await ctx.send(embed=brand("Games frozen", "Games are temporarily unavailable.", 0xED4245)); return False
        now = time.monotonic(); previous = self.cooldowns.get(ctx.author.id, 0)
        if now - previous < config.GAME_COOLDOWN_SECONDS:
            await ctx.send(f"{config.E['lose']} Please wait {config.GAME_COOLDOWN_SECONDS - (now-previous):.1f}s before another game.", delete_after=4); return False
        self.cooldowns[ctx.author.id] = now; return True


bot = CasinoBot()


class OwnerView(discord.ui.View):
    def __init__(self, owner_id: int, timeout=180): super().__init__(timeout=timeout); self.owner_id = owner_id
    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This menu belongs to another user.", ephemeral=True); return False
        return True


HELP = {
    "Games": "`.mines <bet> [mines]` — Find diamonds and cash out\n`.bj <bet>` / `.blackjack <bet>` — House blackjack\n`.cf <bet> [h/t/r]` — Coinflip\n`.hilo <bet>` — Higher or lower\n`.market <bet>` — Pick up or down\n`.baccarat/bacc <bet> <player/banker>` — Normal Baccarat with 1.95x Multi\n`.crazydice/cd <bet>` — Crazy Dice lower or higher choose dice amount and get 1.98x win",
    "General": "`.whois [user]` — Detailed user information\n`.stats [user]` — Player statistics\n`.thread create|add|remove|delete` — Personal thread\n`.leaderboard` / `.lb` — Top gamblers\n`.help [command]` — Command help\n`.daily` — Claim 1 point every 24 hours\n`.rain <amount>` — Start a rain\n`.sos <amount>` — Split or steal event",
    "Balance": "`.deposit` — LTC, SOL, or USDT deposits\n`.withdraw` — Request a withdrawal\n`.price <points>` — Convert points to USD\n`.ai <question>` — Ask the configured AI\n`.tip <user> <points>` — Send points\n`.vault deposit|withdraw <points>` — Personal vault\n`.balance [user]` / `.b` — Check balance\n`.claim <code>` — Claim a code\n`.rb`, `.weekly`, `.monthly` — Bonuses",
}


class HelpView(OwnerView):
    @discord.ui.select(placeholder="Select a category", options=[
        discord.SelectOption(label="GAMES", value="Games", emoji=config.E["games"]),
        discord.SelectOption(label="GENERAL", value="General", emoji=config.E["general"]),
        discord.SelectOption(label="BALANCE", value="Balance", emoji=config.E["balance"]),
    ])
    async def choose(self, interaction, select):
        category = select.values[0]
        embed = brand(f"{category} Commands", HELP[category])
        embed.set_footer(text=f"{config.CASINO_NAME} • Use .help <command> for details")
        await interaction.response.edit_message(embed=embed, view=self)

# ============================================================
# GIFT CARD STORE
# Paid + Fixed Rewards
# ============================================================

from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

import discord


# ============================================================
# GIFT CARD PACK CONFIGURATION
# ============================================================

GC_PACKS = {
    "gc_1": {
        "label": "$1 Gift Card Pack",
        "cost": 200.0,
        "reward": 200.0,
        "reward_usd": 1.00,
    },

    "gc_5": {
        "label": "$5 Gift Card Pack",
        "cost": 1000.0,
        "reward": 1000.0,
        "reward_usd": 5.00,
    },

    "gc_10": {
        "label": "$10 Gift Card Pack",
        "cost": 2000.0,
        "reward": 2000.0,
        "reward_usd": 10.00,
    },
}


# ============================================================
# FONT HELPER
# ============================================================

def gc_font(size, bold=False):

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
            return ImageFont.truetype(path, size)
        except Exception:
            continue

    return ImageFont.load_default()


# ============================================================
# ROUNDED RECTANGLE HELPER
# ============================================================

def gc_round_rect(
    draw,
    xy,
    radius,
    fill,
    outline=None,
    width=1
):

    draw.rounded_rectangle(
        xy,
        radius=radius,
        fill=fill,
        outline=outline,
        width=width
    )


# ============================================================
# GIFT CARD REWARD IMAGE
# ============================================================

def create_gc_reward_card(reward_usd: float):

    WIDTH = 1000
    HEIGHT = 500

    # --------------------------------------------------------
    # Base
    # --------------------------------------------------------

    image = Image.new(
        "RGB",
        (WIDTH, HEIGHT),
        (9, 13, 23)
    )

    draw = ImageDraw.Draw(image)

    # --------------------------------------------------------
    # Background gradient
    # --------------------------------------------------------

    for y in range(HEIGHT):

        ratio = y / HEIGHT

        r = int(9 + (18 * ratio))
        g = int(13 + (17 * ratio))
        b = int(23 + (25 * ratio))

        draw.line(
            [(0, y), (WIDTH, y)],
            fill=(r, g, b)
        )

    # --------------------------------------------------------
    # Futuristic diagonal lines
    # --------------------------------------------------------

    for x in range(-HEIGHT, WIDTH, 80):

        draw.line(
            [
                (x, HEIGHT),
                (x + HEIGHT, 0)
            ],
            fill=(29, 37, 54),
            width=2
        )

    # --------------------------------------------------------
    # Outer card
    # --------------------------------------------------------

    card_x1 = 60
    card_y1 = 50
    card_x2 = WIDTH - 60
    card_y2 = HEIGHT - 50

    gc_round_rect(
        draw,
        (
            card_x1,
            card_y1,
            card_x2,
            card_y2
        ),
        38,
        fill=(16, 22, 35),
        outline=(68, 79, 103),
        width=3
    )

    # --------------------------------------------------------
    # Inner card
    # --------------------------------------------------------

    gc_round_rect(
        draw,
        (
            card_x1 + 12,
            card_y1 + 12,
            card_x2 - 12,
            card_y2 - 12
        ),
        30,
        fill=(21, 28, 43),
        outline=(38, 48, 69),
        width=2
    )

    # --------------------------------------------------------
    # Header
    # --------------------------------------------------------

    title_font = gc_font(
        30,
        True
    )

    draw.text(
        (100, 82),
        "GIFT CARD REVEAL",
        font=title_font,
        fill=(230, 234, 242)
    )

    # --------------------------------------------------------
    # Subheader
    # --------------------------------------------------------

    small_font = gc_font(
        19,
        False
    )

    draw.text(
        (100, 123),
        "Your card contains",
        font=small_font,
        fill=(133, 146, 168)
    )

    # --------------------------------------------------------
    # Reward box
    # --------------------------------------------------------

    reward_box = (
        100,
        165,
        WIDTH - 100,
        380
    )

    if reward_usd <= 0:

        box_fill = (31, 32, 39)
        box_outline = (84, 88, 100)
        reward_color = (170, 174, 185)

        reward_text = "$0"

    else:

        box_fill = (27, 35, 42)
        box_outline = (72, 118, 91)
        reward_color = (92, 232, 145)

        if reward_usd == int(reward_usd):
            reward_text = f"${int(reward_usd)}"
        else:
            reward_text = f"${reward_usd:,.2f}"

    gc_round_rect(
        draw,
        reward_box,
        25,
        fill=box_fill,
        outline=box_outline,
        width=3
    )

    # --------------------------------------------------------
    # Reward amount
    # --------------------------------------------------------

    reward_font = gc_font(
        105,
        True
    )

    bbox = draw.textbbox(
        (0, 0),
        reward_text,
        font=reward_font
    )

    text_width = bbox[2] - bbox[0]

    text_x = (
        WIDTH - text_width
    ) // 2

    text_y = 205

    draw.text(
        (
            text_x,
            text_y
        ),
        reward_text,
        font=reward_font,
        fill=reward_color
    )

    # --------------------------------------------------------
    # Bottom label
    # --------------------------------------------------------

    bottom_font = gc_font(
        18,
        False
    )

    bottom_text = "Gift Card Pack"

    bbox = draw.textbbox(
        (0, 0),
        bottom_text,
        font=bottom_font
    )

    bottom_width = (
        bbox[2] - bbox[0]
    )

    draw.text(
        (
            (WIDTH - bottom_width) // 2,
            417
        ),
        bottom_text,
        font=bottom_font,
        fill=(108, 119, 139)
    )

    # --------------------------------------------------------
    # Convert image to memory
    # --------------------------------------------------------

    buffer = BytesIO()

    image.save(
        buffer,
        format="PNG",
        optimize=True
    )

    buffer.seek(0)

    return buffer


# ============================================================
# GIFT CARD SELECT MENU
# ============================================================

class GiftCardSelect(discord.ui.Select):

    def __init__(self, owner_id):

        self.owner_id = owner_id

        options = [
            discord.SelectOption(
                label="$1",
                description="Purchase a $1 Gift Card Pack",
                value="gc_1",
                emoji="🎁"
            ),

            discord.SelectOption(
                label="$5",
                description="Purchase a $5 Gift Card Pack",
                value="gc_5",
                emoji="🎁"
            ),

            discord.SelectOption(
                label="$10",
                description="Purchase a $10 Gift Card Pack",
                value="gc_10",
                emoji="🎁"
            ),
        ]

        super().__init__(
            placeholder="Select a gift card pack...",
            min_values=1,
            max_values=1,
            options=options
        )

    # ========================================================
    # DROPDOWN CALLBACK
    # ========================================================

    async def callback(
        self,
        interaction: discord.Interaction
    ):

        # ----------------------------------------------------
        # User ownership check
        # ----------------------------------------------------

        if interaction.user.id != self.owner_id:

            await interaction.response.send_message(
                "This gift card menu belongs to someone else.",
                ephemeral=True
            )

            return

        # ----------------------------------------------------
        # Get selected pack
        # ----------------------------------------------------

        pack_id = self.values[0]

        pack = GC_PACKS.get(
            pack_id
        )

        if not pack:

            await interaction.response.send_message(
                "Invalid gift card pack.",
                ephemeral=True
            )

            return

        # ----------------------------------------------------
        # Get current balance
        # ----------------------------------------------------

        row = await bot.db.user(
            interaction.user.id
        )

        if not row:

            await interaction.response.send_message(
                "Your account could not be found.",
                ephemeral=True
            )

            return

        current_balance = float(
            row["balance"]
        )

        # ----------------------------------------------------
        # Check balance
        # ----------------------------------------------------

        if current_balance < pack["cost"]:

            await interaction.response.send_message(
                embed=brand(
                    "Not Enough Points",
                    (
                        f"You need **{money(pack['cost'])} points** "
                        f"(${pack['reward_usd']:.2f}) to purchase "
                        f"this pack.\n\n"
                        f"Your balance: "
                        f"**{money(current_balance)} points**"
                    ),
                    0xED4245
                ),
                ephemeral=True
            )

            return

        # ----------------------------------------------------
        # Deduct purchase
        # ----------------------------------------------------

        success = await bot.db.change_balance(
            interaction.user.id,
            -pack["cost"],
            "gc_purchase",
            pack_id
        )

        if not success:

            await interaction.response.send_message(
                embed=brand(
                    "Purchase Failed",
                    (
                        "Your balance could not be updated. "
                        "Please try again."
                    ),
                    0xED4245
                ),
                ephemeral=True
            )

            return

        # ----------------------------------------------------
        # Add fixed reward
        # ----------------------------------------------------

        reward_success = await bot.db.change_balance(
            interaction.user.id,
            pack["reward"],
            "gc_reward",
            pack_id
        )

        if not reward_success:

            # Attempt to refund the purchase if the reward
            # credit fails.

            await bot.db.change_balance(
                interaction.user.id,
                pack["cost"],
                "gc_refund",
                pack_id
            )

            await interaction.response.send_message(
                embed=brand(
                    "Purchase Failed",
                    (
                        "The reward could not be credited, "
                        "so your points were refunded."
                    ),
                    0xED4245
                ),
                ephemeral=True
            )

            return

        # ----------------------------------------------------
        # Generate reward card
        # ----------------------------------------------------

        image_buffer = create_gc_reward_card(
            pack["reward_usd"]
        )

        image_file = discord.File(
            image_buffer,
            filename="gift_card_reward.png"
        )

        # ----------------------------------------------------
        # Result
        # ----------------------------------------------------

        result_title = "🍀 Lucky!"

        result_description = (
            f"Congratulations! Your card contained "
            f"**${pack['reward_usd']:,.2f}**.\n\n"
            f"• Reward: **{money(pack['reward'])} points** "
            f"(${pack['reward_usd']:,.2f})\n"
            f"• Cost: **{money(pack['cost'])} points** "
            f"(${pack['cost'] / 200:.2f})"
        )

        result_embed = brand(
            result_title,
            result_description,
            0x57F287
        )

        result_embed.set_image(
            url="attachment://gift_card_reward.png"
        )

        result_embed.set_footer(
            text="Gift Cards Store"
        )

        # ----------------------------------------------------
        # Replace store message with result
        # ----------------------------------------------------

        await interaction.response.edit_message(
            embed=result_embed,
            view=None,
            attachments=[image_file]
        )

        self.view.stop()


# ============================================================
# GIFT CARD VIEW
# ============================================================

class GiftCardView(discord.ui.View):

    def __init__(self, owner_id):

        super().__init__(
            timeout=60
        )

        self.owner_id = owner_id

        self.message = None

        self.add_item(
            GiftCardSelect(
                owner_id
            )
        )

    # ========================================================
    # TIMEOUT
    # ========================================================

    async def on_timeout(self):

        for item in self.children:

            item.disabled = True

        if self.message:

            try:

                await self.message.edit(
                    view=self
                )

            except discord.HTTPException:

                pass


# ============================================================
# .GC COMMAND
# ============================================================

@bot.command(
    name="gc"
)
async def gc(ctx):

    # --------------------------------------------------------
    # Store embed
    # --------------------------------------------------------

    embed = brand(
        "Gift Cards Store",
        (
            "Select a pack tier from the dropdown menu "
            "below to get started!"
        ),
        0x3498DB
    )

    # --------------------------------------------------------
    # $1
    # --------------------------------------------------------

    embed.add_field(
        name="$1 Gift Card Pack",
        value=(
            "**Cost:** 200 points ($1.00)\n\n"
            "**How It Works:**\n"
            "• Purchase a pack using points.\n"
            "• Reveal your gift card.\n"
            "• Your reward is automatically credited "
            "to your balance."
        ),
        inline=False
    )

    # --------------------------------------------------------
    # $5
    # --------------------------------------------------------

    embed.add_field(
        name="$5 Gift Card Pack",
        value=(
            "**Cost:** 1,000 points ($5.00)\n\n"
            "**How It Works:**\n"
            "• Purchase a pack using points.\n"
            "• Reveal your gift card.\n"
            "• Your reward is automatically credited "
            "to your balance."
        ),
        inline=False
    )

    # --------------------------------------------------------
    # $10
    # --------------------------------------------------------

    embed.add_field(
        name="$10 Gift Card Pack",
        value=(
            "**Cost:** 2,000 points ($10.00)\n\n"
            "**How It Works:**\n"
            "• Purchase a pack using points.\n"
            "• Reveal your gift card.\n"
            "• Your reward is automatically credited "
            "to your balance."
        ),
        inline=False
    )

    # --------------------------------------------------------
    # Dropdown
    # --------------------------------------------------------

    view = GiftCardView(
        ctx.author.id
    )

    message = await ctx.send(
        embed=embed,
        view=view
    )

    view.message = message

import asyncio
import random
import discord
from discord.ext import commands

# =========================================================
# MARKET GAME
# =========================================================

import random
from decimal import Decimal, InvalidOperation
from io import BytesIO

from PIL import (
    Image,
    ImageDraw,
    ImageFont,
    ImageFilter
)


# =========================================================
# MARKET CONFIG
# =========================================================

MARKET_PAYOUT = Decimal("1.92")

MINIMUM_BET = Decimal("1")


# =========================================================
# MARKET IMAGE GENERATOR
# =========================================================

def market_font(size, bold=False):

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
            return ImageFont.truetype(path, size)
        except Exception:
            pass

    return ImageFont.load_default()


# =========================================================
# RANDOM MARKET DATA
# =========================================================

def generate_market_history():

    points = []

    # Start somewhere around the middle
    current = random.uniform(
        0.42,
        0.62
    )

    for _ in range(24):

        # Random movement
        movement = random.uniform(
            -0.11,
            0.11
        )

        current += movement

        # Keep chart inside bounds
        current = max(
            0.12,
            min(
                0.88,
                current
            )
        )

        points.append(
            current
        )

    return points


# =========================================================
# GENERATE FUTURE MARKET MOVEMENT
# =========================================================

def generate_market_future(
    start_value,
    result
):

    values = []

    current = start_value

    # -----------------------------------------------------
    # UP RESULT
    # -----------------------------------------------------

    if result == "UP":

        # Random total upward movement
        target_change = random.uniform(
            0.18,
            0.42
        )

        target = min(
            0.92,
            current + target_change
        )

    # -----------------------------------------------------
    # DOWN RESULT
    # -----------------------------------------------------

    else:

        target_change = random.uniform(
            0.18,
            0.42
        )

        target = max(
            0.08,
            current - target_change
        )

    steps = 16

    for i in range(steps):

        remaining = steps - i

        # Amount needed to eventually reach target
        difference = target - current

        # Stronger movement as the chart approaches result
        base_step = (
            difference / remaining
        )

        # Random noise
        noise = random.uniform(
            -0.055,
            0.055
        )

        movement = (
            base_step
            + noise
        )

        current += movement

        # Don't allow chart to leave boundaries
        current = max(
            0.06,
            min(
                0.94,
                current
            )
        )

        values.append(
            current
        )

    # Force final point clearly toward result
    if result == "UP":

        values[-1] = random.uniform(
            max(current, 0.72),
            0.94
        )

    else:

        values[-1] = random.uniform(
            0.06,
            min(current, 0.30)
        )

    return values


# =========================================================
# MARKET IMAGE
# =========================================================

def create_market_chart(
    result=None
):

    WIDTH = 1200
    HEIGHT = 675

    # -----------------------------------------------------
    # BASE IMAGE
    # -----------------------------------------------------

    image = Image.new(
        "RGB",
        (
            WIDTH,
            HEIGHT
        ),
        (7, 9, 13)
    )

    draw = ImageDraw.Draw(
        image
    )

    # -----------------------------------------------------
    # BACKGROUND GRADIENT
    # -----------------------------------------------------

    for y in range(HEIGHT):

        ratio = y / HEIGHT

        r = int(
            7 + (8 * ratio)
        )

        g = int(
            9 + (9 * ratio)
        )

        b = int(
            13 + (13 * ratio)
        )

        draw.line(
            [
                (0, y),
                (WIDTH, y)
            ],
            fill=(
                r,
                g,
                b
            )
        )

    # -----------------------------------------------------
    # HEADER
    # -----------------------------------------------------

    title_font = market_font(
        34,
        True
    )

    draw.text(
        (
            60,
            30
        ),
        "BETRUSH  |  MARKET PREDICTION",
        font=title_font,
        fill=(240, 242, 247)
    )

    # -----------------------------------------------------
    # CHART AREA
    # -----------------------------------------------------

    left = 65
    right = WIDTH - 55

    top = 135
    bottom = HEIGHT - 65

    chart_width = (
        right - left
    )

    chart_height = (
        bottom - top
    )

    # -----------------------------------------------------
    # GRID
    # -----------------------------------------------------

    grid_color = (
        28,
        31,
        39
    )

    for i in range(7):

        y = int(
            top
            + (
                chart_height / 6
            ) * i
        )

        draw.line(
            [
                (left, y),
                (right, y)
            ],
            fill=grid_color,
            width=2
        )

    for i in range(13):

        x = int(
            left
            + (
                chart_width / 12
            ) * i
        )

        draw.line(
            [
                (x, top),
                (x, bottom)
            ],
            fill=grid_color,
            width=2
        )

    # =====================================================
    # RANDOM HISTORY
    # =====================================================

    history = generate_market_history()

    # -----------------------------------------------------
    # Split chart into:
    #
    # 65% historical
    # 35% future
    # -----------------------------------------------------

    history_end_x = int(
        left
        + chart_width * 0.64
    )

    future_end_x = right

    # -----------------------------------------------------
    # Convert history values to coordinates
    # -----------------------------------------------------

    history_points = []

    for i, value in enumerate(history):

        x = int(
            left
            + (
                history_end_x - left
            )
            * (
                i / (
                    len(history) - 1
                )
            )
        )

        y = int(
            top
            + (
                1 - value
            )
            * chart_height
        )

        history_points.append(
            (
                x,
                y
            )
        )

    # =====================================================
    # DRAW GREY HISTORY
    # =====================================================

    grey_line = (
        135,
        145,
        162
    )

    for i in range(
        len(history_points) - 1
    ):

        draw.line(
            [
                history_points[i],
                history_points[i + 1]
            ],
            fill=grey_line,
            width=5
        )

    # =====================================================
    # CURRENT POINT
    # =====================================================

    start_x, start_y = (
        history_points[-1]
    )

    # =====================================================
    # HIDDEN / PRE-REVEAL
    # =====================================================

    if result is None:

        # -------------------------------------------------
        # Hidden future line
        # -------------------------------------------------

        hidden_points = []

        current_y = start_y

        future_steps = 16

        for i in range(
            1,
            future_steps + 1
        ):

            x = int(
                start_x
                + (
                    future_end_x
                    - start_x
                )
                * (
                    i / future_steps
                )
            )

            current_y += random.randint(
                -25,
                25
            )

            current_y = max(
                top + 25,
                min(
                    bottom - 25,
                    current_y
                )
            )

            hidden_points.append(
                (
                    x,
                    current_y
                )
            )

        # -------------------------------------------------
        # Grey hidden line
        # -------------------------------------------------

        previous = (
            start_x,
            start_y
        )

        for point in hidden_points:

            draw.line(
                [
                    previous,
                    point
                ],
                fill=(
                    66,
                    70,
                    80
                ),
                width=4
            )

            previous = point

        # -------------------------------------------------
        # Hidden vertical divider
        # -------------------------------------------------

        draw.line(
            [
                (
                    start_x,
                    top
                ),
                (
                    start_x,
                    bottom
                )
            ],
            fill=(
                55,
                59,
                69
            ),
            width=2
        )

        # -------------------------------------------------
        # QUESTION MARK
        # -------------------------------------------------

        question_font = market_font(
            115,
            True
        )

        question = "?"

        bbox = draw.textbbox(
            (
                0,
                0
            ),
            question,
            font=question_font
        )

        q_width = (
            bbox[2] - bbox[0]
        )

        q_height = (
            bbox[3] - bbox[1]
        )

        center_x = int(
            start_x
            + (
                future_end_x
                - start_x
            ) / 2
        )

        center_y = int(
            top
            + chart_height / 2
        )

        q_x = (
            center_x
            - q_width / 2
        )

        q_y = (
            center_y
            - q_height / 2
        )

        # Shadow

        draw.text(
            (
                int(q_x + 5),
                int(q_y + 6)
            ),
            question,
            font=question_font,
            fill=(0, 0, 0)
        )

        # Main ?

        draw.text(
            (
                int(q_x),
                int(q_y)
            ),
            question,
            font=question_font,
            fill=(
                155,
                160,
                170
            )
        )

        # -------------------------------------------------
        # PREDICT LABEL
        # -------------------------------------------------

        label_font = market_font(
            18,
            True
        )

        label = "CHOOSE THE MARKET DIRECTION"

        bbox = draw.textbbox(
            (
                0,
                0
            ),
            label,
            font=label_font
        )

        label_width = (
            bbox[2] - bbox[0]
        )

        draw.text(
            (
                center_x
                - label_width / 2,
                bottom - 38
            ),
            label,
            font=label_font,
            fill=(
                100,
                105,
                115
            )
        )

    # =====================================================
    # REVEAL
    # =====================================================

    else:

        # -------------------------------------------------
        # Generate random future based on result
        # -------------------------------------------------

        future_values = (
            generate_market_future(
                history[-1],
                result
            )
        )

        future_points = []

        for i, value in enumerate(
            future_values,
            start=1
        ):

            x = int(
                start_x
                + (
                    future_end_x
                    - start_x
                )
                * (
                    i / len(
                        future_values
                    )
                )
            )

            y = int(
                top
                + (
                    1 - value
                )
                * chart_height
            )

            future_points.append(
                (
                    x,
                    y
                )
            )

        all_points = [
            history_points[-1]
        ] + future_points

        # -------------------------------------------------
        # RESULT COLOR
        # -------------------------------------------------

        if result == "UP":

            line_color = (
                45,
                230,
                125
            )

            result_label = (
                "▲ MARKET WENT UP"
            )

        else:

            line_color = (
                255,
                72,
                82
            )

            result_label = (
                "▼ MARKET WENT DOWN"
            )

        # -------------------------------------------------
        # GLOW
        # -------------------------------------------------

        glow = Image.new(
            "RGBA",
            (
                WIDTH,
                HEIGHT
            ),
            (
                0,
                0,
                0,
                0
            )
        )

        glow_draw = ImageDraw.Draw(
            glow
        )

        for i in range(
            len(all_points) - 1
        ):

            glow_draw.line(
                [
                    all_points[i],
                    all_points[i + 1]
                ],
                fill=(
                    line_color[0],
                    line_color[1],
                    line_color[2],
                    100
                ),
                width=24
            )

        glow = glow.filter(
            ImageFilter.GaussianBlur(
                13
            )
        )

        image = Image.alpha_composite(
            image.convert("RGBA"),
            glow
        ).convert("RGB")

        draw = ImageDraw.Draw(
            image
        )

        # -------------------------------------------------
        # REVEALED LINE
        # -------------------------------------------------

        for i in range(
            len(all_points) - 1
        ):

            draw.line(
                [
                    all_points[i],
                    all_points[i + 1]
                ],
                fill=line_color,
                width=6
            )

        # -------------------------------------------------
        # START DOT
        # -------------------------------------------------

        draw.ellipse(
            (
                start_x - 6,
                start_y - 6,
                start_x + 6,
                start_y + 6
            ),
            fill=line_color
        )

        # -------------------------------------------------
        # FINAL DOT
        # -------------------------------------------------

        final_x, final_y = (
            all_points[-1]
        )

        draw.ellipse(
            (
                final_x - 12,
                final_y - 12,
                final_x + 12,
                final_y + 12
            ),
            fill=line_color
        )

        # -------------------------------------------------
        # RESULT LABEL
        # -------------------------------------------------

        result_font = market_font(
            26,
            True
        )

        bbox = draw.textbbox(
            (
                0,
                0
            ),
            result_label,
            font=result_font
        )

        result_width = (
            bbox[2] - bbox[0]
        )

        center_x = int(
            start_x
            + (
                future_end_x
                - start_x
            ) / 2
        )

        draw.text(
            (
                center_x
                - result_width / 2,
                bottom - 42
            ),
            result_label,
            font=result_font,
            fill=line_color
        )

    # =====================================================
    # CONVERT TO DISCORD FILE
    # =====================================================

    buffer = BytesIO()

    image.save(
        buffer,
        format="PNG",
        optimize=True
    )

    buffer.seek(0)

    return buffer


# =========================================================
# MARKET VIEW
# =========================================================

class MarketView(discord.ui.View):

    def __init__(
        self,
        ctx,
        bet
    ):

        super().__init__(
            timeout=30
        )

        self.ctx = ctx

        self.bet = Decimal(
            str(bet)
        )

        self.finished = False
        self.message = None

    # =====================================================
    # USER CHECK
    # =====================================================

    async def interaction_check(
        self,
        interaction: discord.Interaction
    ):

        if (
            interaction.user.id
            != self.ctx.author.id
        ):

            await interaction.response.send_message(
                "This market game belongs to someone else.",
                ephemeral=True
            )

            return False

        return True

    # =====================================================
    # FINISH GAME
    # =====================================================

    async def finish_game(
        self,
        interaction,
        direction
    ):

        if self.finished:
            return

        self.finished = True

        # -------------------------------------------------
        # Disable buttons
        # -------------------------------------------------

        for child in self.children:
            child.disabled = True

        # -------------------------------------------------
        # Generate actual result
        # -------------------------------------------------

        market_result = random.choice(
            [
                "UP",
                "DOWN"
            ]
        )

        won = (
            market_result
            == direction
        )

        # =================================================
        # WIN
        # =================================================

        if won:

            payout = (
                self.bet
                * MARKET_PAYOUT
            )

            try:

                success = await bot.db.change_balance(
                    self.ctx.author.id,
                    float(payout),
                    "market_win"
                )

            except Exception as error:

                print(
                    f"[MARKET] Payout error: {error}"
                )

                success = False

            if not success:

                self.finished = False

                for child in self.children:
                    child.disabled = False

                await interaction.response.send_message(
                    embed=brand(
                        "Market Error",
                        (
                            "The payout could not be "
                            "processed. Your game was "
                            "not completed."
                        ),
                        0xED4245
                    ),
                    ephemeral=True
                )

                return

            result_title = (
                "📈 Market Won!"
            )

            result_colour = (
                0x57F287
            )

            result_text = (
                f"**Result:** {market_result}\n"
                f"**Your Choice:** {direction}\n"
                f"**Bet:** {self.bet:,.2f} points\n"
                f"**Payout:** {payout:,.2f} points\n"
                f"**Multiplier:** {MARKET_PAYOUT}x"
            )

        # =================================================
        # LOSS
        # =================================================

        else:

            result_title = (
                "📉 Market Lost"
            )

            result_colour = (
                0xED4245
            )

            result_text = (
                f"**Result:** {market_result}\n"
                f"**Your Choice:** {direction}\n"
                f"**Bet:** {self.bet:,.2f} points\n"
                f"**Payout:** 0.00 points\n"
                f"**Multiplier:** {MARKET_PAYOUT}x"
            )

        # =================================================
        # GENERATE REVEALED IMAGE
        # =================================================

        try:

            chart = create_market_chart(
                result=market_result
            )

            chart_file = discord.File(
                chart,
                filename="market_result.png"
            )

        except Exception as error:

            print(
                f"[MARKET] Result image error: {error}"
            )

            # Still show the result if image generation fails

            embed = brand(
                result_title,
                result_text,
                result_colour
            )

            await interaction.response.edit_message(
                embed=embed,
                view=self
            )

            self.stop()

            return

        # =================================================
        # RESULT EMBED
        # =================================================

        embed = brand(
            result_title,
            result_text,
            result_colour
        )

        embed.set_image(
            url="attachment://market_result.png"
        )

        embed.set_footer(
            text="Market Prediction"
        )

        # =================================================
        # UPDATE MESSAGE
        # =================================================

        try:

            await interaction.response.edit_message(
                embed=embed,
                view=self,
                attachments=[
                    chart_file
                ]
            )

        except Exception as error:

            print(
                f"[MARKET] Result update error: {error}"
            )

        self.stop()

    # =====================================================
    # UP BUTTON
    # =====================================================

    @discord.ui.button(
        label="UP",
        style=discord.ButtonStyle.success,
        emoji="📈"
    )
    async def up_button(
        self,
        interaction,
        button
    ):

        await self.finish_game(
            interaction,
            "UP"
        )

    # =====================================================
    # DOWN BUTTON
    # =====================================================

    @discord.ui.button(
        label="DOWN",
        style=discord.ButtonStyle.danger,
        emoji="📉"
    )
    async def down_button(
        self,
        interaction,
        button
    ):

        await self.finish_game(
            interaction,
            "DOWN"
        )

    # =====================================================
    # TIMEOUT
    # =====================================================

    async def on_timeout(self):

        if self.finished:
            return

        self.finished = True

        # Disable buttons
        for child in self.children:
            child.disabled = True

        # -------------------------------------------------
        # Refund bet
        # -------------------------------------------------

        try:

            await bot.db.change_balance(
                self.ctx.author.id,
                float(self.bet),
                "market_timeout_refund"
            )

        except Exception as error:

            print(
                f"[MARKET] Timeout refund error: {error}"
            )

        # -------------------------------------------------
        # Update message
        # -------------------------------------------------

        if self.message:

            try:

                embed = brand(
                    "Market Expired",
                    (
                        "The prediction window expired.\n\n"
                        f"Your **{self.bet:,.2f} points** "
                        "bet has been refunded."
                    ),
                    0x95A5A6
                )

                await self.message.edit(
                    embed=embed,
                    view=self
                )

            except discord.HTTPException:
                pass

        self.stop()


# =========================================================
# MARKET COMMAND
# =========================================================

@bot.command(
    name="market"
)
async def market(
    ctx,
    amount: str = None
):

    # =====================================================
    # USAGE
    # =====================================================

    if amount is None:

        await ctx.send(
            embed=brand(
                "📊 Market Prediction",
                (
                    "**Usage:**\n"
                    "`.market <amount>`\n\n"
                    f"**Minimum Bet:** "
                    f"{MINIMUM_BET:,.0f} points\n"
                    f"**Payout:** "
                    f"{MARKET_PAYOUT}x total\n\n"
                    "Predict whether the hidden "
                    "market will go **UP** or **DOWN**."
                )
            )
        )

        return

    # =====================================================
    # PARSE BET
    # =====================================================

    try:

        bet = Decimal(
            str(amount)
        )

    except (
        InvalidOperation,
        ValueError
    ):

        await ctx.send(
            embed=brand(
                "Market",
                "Enter a valid bet amount.",
                0xED4245
            )
        )

        return

    # =====================================================
    # VALIDATE
    # =====================================================

    if not bet.is_finite():

        await ctx.send(
            embed=brand(
                "Market",
                "Enter a valid bet amount.",
                0xED4245
            )
        )

        return

    if bet <= 0:

        await ctx.send(
            embed=brand(
                "Market",
                "Bet must be greater than 0.",
                0xED4245
            )
        )

        return

    if bet < MINIMUM_BET:

        await ctx.send(
            embed=brand(
                "Market",
                (
                    f"Minimum bet is "
                    f"**{MINIMUM_BET:,.0f} points**."
                ),
                0xED4245
            )
        )

        return

    # =====================================================
    # GET USER
    # =====================================================

    try:

        row = await bot.db.user(
            ctx.author.id
        )

    except Exception as error:

        print(
            f"[MARKET] Database error: {error}"
        )

        await ctx.send(
            embed=brand(
                "Market",
                "Database error. Please try again.",
                0xED4245
            )
        )

        return

    if not row:

        await ctx.send(
            embed=brand(
                "Market",
                "Your account could not be found.",
                0xED4245
            )
        )

        return

    # =====================================================
    # BALANCE
    # =====================================================

    try:

        balance = Decimal(
            str(row["balance"])
        )

    except Exception:

        await ctx.send(
            embed=brand(
                "Market",
                "Your balance could not be read.",
                0xED4245
            )
        )

        return

    # =====================================================
    # BALANCE CHECK
    # =====================================================

    if balance < bet:

        await ctx.send(
            embed=brand(
                "Market",
                (
                    "**Insufficient balance.**\n\n"
                    f"**Balance:** "
                    f"{balance:,.2f} points\n"
                    f"**Bet:** "
                    f"{bet:,.2f} points"
                ),
                0xED4245
            )
        )

        return

    # =====================================================
    # DEDUCT BET
    # =====================================================

    try:

        deducted = await bot.db.change_balance(
            ctx.author.id,
            -float(bet),
            "market_bet"
        )

    except Exception as error:

        print(
            f"[MARKET] Bet deduction error: {error}"
        )

        deducted = False

    if not deducted:

        await ctx.send(
            embed=brand(
                "Market",
                (
                    "Your bet could not be processed. "
                    "Please try again."
                ),
                0xED4245
            )
        )

        return

    # =====================================================
    # GENERATE UNIQUE HIDDEN CHART
    # =====================================================

    try:

        chart = create_market_chart(
            result=None
        )

        chart_file = discord.File(
            chart,
            filename="market.png"
        )

    except Exception as error:

        print(
            f"[MARKET] Image generation error: {error}"
        )

        # Refund if image generation fails

        try:

            await bot.db.change_balance(
                ctx.author.id,
                float(bet),
                "market_image_refund"
            )

        except Exception as refund_error:

            print(
                f"[MARKET] Refund error: "
                f"{refund_error}"
            )

        await ctx.send(
            embed=brand(
                "Market",
                (
                    "The market chart could not be "
                    "generated. Your bet was refunded."
                ),
                0xED4245
            )
        )

        return

    # =====================================================
    # GAME EMBED
    # =====================================================

    embed = brand(
        "📊 Market Prediction",
        (
            f"**Bet:** {bet:,.2f} points\n"
            f"**Payout:** {MARKET_PAYOUT}x total\n\n"
            "The future market movement is hidden.\n"
            "Study the chart and predict **UP** or **DOWN**."
        )
    )

    embed.set_image(
        url="attachment://market.png"
    )

    embed.set_footer(
        text="Market Prediction • Choose your direction"
    )

    # =====================================================
    # VIEW
    # =====================================================

    view = MarketView(
        ctx,
        bet
    )

    # =====================================================
    # SEND
    # =====================================================

    try:

        message = await ctx.send(
            embed=embed,
            file=chart_file,
            view=view
        )

        view.message = message

    except Exception as error:

        print(
            f"[MARKET] Message error: {error}"
        )

        # -------------------------------------------------
        # REFUND
        # -------------------------------------------------

        try:

            await bot.db.change_balance(
                ctx.author.id,
                float(bet),
                "market_refund"
            )

        except Exception as refund_error:

            print(
                f"[MARKET] Refund error: {refund_error}"
            )

        return

# =========================================================
# CRAZY DICE
# =========================================================

import hashlib
import secrets


# =========================================================
# CRAZY DICE VIEW
# =========================================================

class CrazyDiceView(discord.ui.View):

    def __init__(self, author, amount):
        super().__init__(timeout=120)

        self.author = author
        self.amount = amount
        self.modality = None
        self.dice_count = None
        self.finished = False

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:

        if interaction.user.id != self.author.id:

            await interaction.response.send_message(
                "This game belongs to someone else.",
                ephemeral=True,
            )

            return False

        return True

    # -----------------------------------------------------
    # FIRST SCREEN
    # -----------------------------------------------------

    def first_embed(self):

        return brand(
            "Crazy Dice",
            (
                f"Bet: **{money(self.amount)} points**\n\n"
                "**Choose your winning condition:**\n\n"
                "📈 **Higher Wins** — Highest total wins\n"
                "📉 **Lower Wins** — Lowest total wins\n"
                "🤝 **Tie Wins** — Both totals must be equal"
            ),
        )

    # -----------------------------------------------------
    # SECOND SCREEN
    # -----------------------------------------------------

    def dice_embed(self):

        if self.modality == "higher":
            modality_name = "Higher Wins"

        elif self.modality == "lower":
            modality_name = "Lower Wins"

        else:
            modality_name = "Tie Wins"

        return brand(
            "Crazy Dice",
            (
                f"Bet: **{money(self.amount)} points**\n"
                f"Modality: **{modality_name}**\n\n"
                "**Choose your dice count:**\n\n"
                "1 Dice\n"
                "3 Dice\n"
                "6 Dice"
            ),
        )

    # -----------------------------------------------------
    # CHANGE TO DICE SELECTION
    # -----------------------------------------------------

    def show_dice_buttons(self):

        self.clear_items()

        self.add_item(
            CrazyDiceDiceButton(
                "1 Dice",
                1,
            )
        )

        self.add_item(
            CrazyDiceDiceButton(
                "3 Dice",
                3,
            )
        )

        self.add_item(
            CrazyDiceDiceButton(
                "6 Dice",
                6,
            )
        )

    # -----------------------------------------------------
    # HIGHER
    # -----------------------------------------------------

    @discord.ui.button(
        label="Higher Wins",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def higher_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        if self.finished:
            return

        self.modality = "higher"

        self.show_dice_buttons()

        await interaction.response.edit_message(
            embed=self.dice_embed(),
            view=self,
        )

    # -----------------------------------------------------
    # LOWER
    # -----------------------------------------------------

    @discord.ui.button(
        label="Lower Wins",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def lower_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        if self.finished:
            return

        self.modality = "lower"

        self.show_dice_buttons()

        await interaction.response.edit_message(
            embed=self.dice_embed(),
            view=self,
        )

    # -----------------------------------------------------
    # TIE
    # -----------------------------------------------------

    @discord.ui.button(
        label="Tie Wins",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def tie_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        if self.finished:
            return

        self.modality = "tie"

        self.show_dice_buttons()

        await interaction.response.edit_message(
            embed=self.dice_embed(),
            view=self,
        )

    # -----------------------------------------------------
    # ACTUAL GAME
    # -----------------------------------------------------

    async def play(
        self,
        interaction: discord.Interaction,
        dice_count: int,
    ):

        if self.finished:
            return

        self.finished = True
        self.dice_count = dice_count

        # =================================================
        # SEND LOADING MESSAGE FIRST
        # =================================================
        #
        # This is intentionally the FIRST thing we do.
        # It prevents Discord's interaction timeout.
        #

        try:

            await interaction.response.send_message(
                "<a:m_Loading1:1550866495641223188>"
            )

            loading_message = (
                await interaction.original_response()
            )

        except Exception:

            self.finished = False

            return

        # Disable the old dice buttons.
        for item in self.children:
            item.disabled = True

        # Update the original setup message.
        try:

            await interaction.message.edit(
                embed=self.dice_embed(),
                view=self,
            )

        except Exception:
            pass

        # =================================================
        # WAIT 3 SECONDS
        # =================================================

        await asyncio.sleep(3)

        # =================================================
        # CREATE PROVABLY FAIR SEEDS
        # =================================================

        try:

            server_seed = secrets.token_hex(32)

            client_seed = str(
                secrets.randbelow(10**18)
            )

            # =================================================
            # DETERMINISTIC DICE ROLL
            # =================================================

            def generate_roll(
                side: str,
                index: int,
            ):

                data = (
                    f"{server_seed}:"
                    f"{client_seed}:"
                    f"crazydice:"
                    f"{side}:"
                    f"{dice_count}:"
                    f"{index}"
                ).encode()

                digest = hashlib.sha256(
                    data
                ).hexdigest()

                number = int(
                    digest[:16],
                    16,
                )

                return (number % 6) + 1

            player_dice = []

            dealer_dice = []

            for index in range(dice_count):

                player_dice.append(
                    generate_roll(
                        "player",
                        index,
                    )
                )

                dealer_dice.append(
                    generate_roll(
                        "dealer",
                        index,
                    )
                )

            player_total = sum(
                player_dice
            )

            dealer_total = sum(
                dealer_dice
            )

            # =================================================
            # DETERMINE MODALITY
            # =================================================

            if self.modality == "higher":

                modality_name = "Higher Wins"

                payout_multiplier = Decimal("1.96")

                if player_total > dealer_total:

                    result = "win"

                elif player_total == dealer_total:

                    result = "push"

                else:

                    result = "lose"

            elif self.modality == "lower":

                modality_name = "Lower Wins"

                payout_multiplier = Decimal("1.96")

                if player_total < dealer_total:

                    result = "win"

                elif player_total == dealer_total:

                    result = "push"

                else:

                    result = "lose"

            else:

                modality_name = "Tie Wins"

                if dice_count == 1:

                    payout_multiplier = Decimal("5")

                elif dice_count == 3:

                    payout_multiplier = Decimal("7")

                else:

                    payout_multiplier = Decimal("9")

                if player_total == dealer_total:

                    result = "win"

                else:

                    result = "lose"

            # =================================================
            # PAYOUT
            # =================================================

            payout = Decimal("0")

            if result == "win":

                payout = (
                    Decimal(str(self.amount))
                    * payout_multiplier
                )

                await bot.db.change_balance(
                    self.author.id,
                    payout,
                    "crazydice_win",
                )

            elif result == "push":

                # Return the original bet.
                payout = Decimal(
                    str(self.amount)
                )

                await bot.db.change_balance(
                    self.author.id,
                    payout,
                    "crazydice_push",
                )

            # =================================================
            # RESULT TEXT
            # =================================================

            if result == "win":

                result_text = (
                    f"Congratulations! You won the "
                    f"**{modality_name}** "
                    f"({dice_count} Dice) modality. "
                    f"You gained **{money(payout)}** points."
                )

            elif result == "push":

                result_text = (
                    f"**{modality_name}** "
                    f"({dice_count} Dice) resulted in a tie. "
                    "Your bet was returned."
                )

            else:

                result_text = (
                    f"You lost the "
                    f"**{modality_name}** "
                    f"({dice_count} Dice) game."
                )

            # =================================================
            # FINAL RESULT
            # =================================================

            result_embed = brand(
                "Crazy Dice",
                (
                    f"{result_text}\n\n"

                    f"**Your Roll**\n"
                    f"Dice: **"
                    f"{', '.join(map(str, player_dice))}"
                    f"**\n"
                    f"Total: **{player_total}**\n\n"

                    f"**Bot Rolled**\n"
                    f"Dice: **"
                    f"{', '.join(map(str, dealer_dice))}"
                    f"**\n"
                    f"Total: **{dealer_total}**\n\n"

                    f"**Payout:** "
                    f"{payout_multiplier}x\n\n"

                    f"🔒 **Provably Fair**\n"
                    f"**Server Seed:** "
                    f"`{server_seed}`\n"
                    f"**Client Seed:** "
                    f"`{client_seed}`"
                ),
            )

            # =================================================
            # EDIT LOADING MESSAGE
            # =================================================

            await loading_message.edit(
                content=None,
                embed=result_embed,
            )

        except Exception as error:

            # -------------------------------------------------
            # NEVER LEAVE THE USER WITH A DEAD GAME
            # -------------------------------------------------

            try:

                error_embed = brand(
                    "Crazy Dice",
                    (
                        "An error occurred while processing "
                        "the game.\n\n"
                        "Your bet was not automatically "
                        "returned by this error handler."
                    ),
                    0xED4245,
                )

                await loading_message.edit(
                    content=None,
                    embed=error_embed,
                )

            except Exception:
                pass

            print(
                f"[Crazy Dice Error] "
                f"{type(error).__name__}: {error}"
            )

        finally:

            self.stop()


# =========================================================
# CRAZY DICE DICE BUTTON
# =========================================================

class CrazyDiceDiceButton(discord.ui.Button):

    def __init__(
        self,
        label: str,
        dice_count: int,
    ):

        super().__init__(
            label=label,
            style=discord.ButtonStyle.secondary,
            row=0,
        )

        self.dice_count = dice_count

    async def callback(
        self,
        interaction: discord.Interaction,
    ):

        view = self.view

        if not isinstance(
            view,
            CrazyDiceView,
        ):
            return

        if interaction.user.id != view.author.id:

            await interaction.response.send_message(
                "This game belongs to someone else.",
                ephemeral=True,
            )

            return

        await view.play(
            interaction,
            self.dice_count,
        )


# =========================================================
# CRAZY DICE COMMAND
# =========================================================

@bot.command(
    aliases=["cd"],
)
async def crazydice(
    ctx,
    bet: str,
):

    if not await bot.game_allowed(ctx):
        return

    # =====================================================
    # PARSE BET
    # =====================================================

    try:

        bet_lower = bet.lower().strip()

        if bet_lower in (
            "half",
            "all",
            "max",
        ):

            row = await bot.db.user(
                ctx.author.id
            )

            if not row:

                await ctx.send(
                    "Your account could not be found."
                )

                return

            balance = row["balance"]

            if bet_lower in (
                "all",
                "max",
            ):

                amount = parse_amount(
                    str(balance)
                )

            else:

                half_balance = (
                    Decimal(str(balance))
                    / Decimal("2")
                )

                amount = parse_amount(
                    str(half_balance)
                )

        else:

            amount = parse_amount(
                bet
            )

    except ValueError as error:

        await ctx.send(
            str(error)
        )

        return

    # =====================================================
    # MINIMUM BET
    # =====================================================

    if Decimal(str(amount)) < Decimal("20"):

        await ctx.send(
            "The minimum bet is **20 points ($0.10)**."
        )

        return

    # =====================================================
    # DEDUCT BET
    # =====================================================

    if not await bot.db.change_balance(
        ctx.author.id,
        -amount,
        "crazydice_bet",
    ):

        await ctx.send(
            "Insufficient balance."
        )

        return

    # =====================================================
    # START GAME
    # =====================================================

    view = CrazyDiceView(
        ctx.author,
        amount,
    )

    await ctx.send(
        embed=view.first_embed(),
        view=view,
    )

            
import random
import discord


# =========================================================
# SOS CONFIRMATION VIEW
# =========================================================

class SOSConfirmView(discord.ui.View):

    def __init__(self, ctx, amount):
        super().__init__(timeout=30)

        self.ctx = ctx
        self.amount = amount
        self.message = None
        self.finished = False

    # -----------------------------------------------------
    # ONLY HOST CAN USE CONFIRMATION BUTTONS
    # -----------------------------------------------------

    async def interaction_check(self, interaction: discord.Interaction):

        if interaction.user.id != self.ctx.author.id:

            await interaction.response.send_message(
                "Only the event host can use these buttons.",
                ephemeral=True
            )

            return False

        return True

    # -----------------------------------------------------
    # START
    # -----------------------------------------------------

    @discord.ui.button(
        label="Start",
        style=discord.ButtonStyle.success,
        emoji="✅"
    )
    async def start_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if self.finished:
            return

        # Take money only when host actually starts
        balance_changed = await bot.db.change_balance(
            self.ctx.author.id,
            -self.amount,
            "sos_pot"
        )

        if not balance_changed:

            await interaction.response.send_message(
                "You do not have enough balance to start this event.",
                ephemeral=True
            )

            return

        self.finished = True
        self.stop()

        for child in self.children:
            child.disabled = True

        # First acknowledge the button
        await interaction.response.edit_message(
            content="",
            embed=discord.Embed(
                title="🟢 SOS Event Starting",
                description=(
                    f"{self.ctx.author.mention} started a "
                    f"**{money(self.amount)}** Split or Steal event.\n\n"
                    "Players can now join the event."
                ),
                color=discord.Color.green()
            ),
            view=None
        )

        # Create the actual JOIN view
        join_view = SOSJoinView(
            self.ctx,
            self.amount
        )

        join_view.message = self.message

        # Replace confirmation with JOIN event
        await self.message.edit(
            content="",
            embed=join_view.make_embed(),
            view=join_view
        )

    # -----------------------------------------------------
    # DECLINE
    # -----------------------------------------------------

    @discord.ui.button(
        label="Decline",
        style=discord.ButtonStyle.danger,
        emoji="❌"
    )
    async def decline_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        await self.cancel(
            interaction,
            "The SOS event was declined."
        )

    # -----------------------------------------------------
    # DON'T START
    # -----------------------------------------------------

    @discord.ui.button(
        label="Don't Start",
        style=discord.ButtonStyle.secondary,
        emoji="🛑"
    )
    async def dont_start_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        await self.cancel(
            interaction,
            "The SOS event was cancelled."
        )

    # -----------------------------------------------------
    # CANCEL
    # -----------------------------------------------------

    async def cancel(
        self,
        interaction,
        reason
    ):

        if self.finished:
            return

        self.finished = True
        self.stop()

        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(
            content="",
            embed=discord.Embed(
                title="🛑 SOS Event Cancelled",
                description=reason,
                color=discord.Color.red()
            ),
            view=self
        )

    # -----------------------------------------------------
    # CONFIRMATION TIMEOUT
    # -----------------------------------------------------

    async def on_timeout(self):

        if self.finished:
            return

        self.finished = True

        for child in self.children:
            child.disabled = True

        if self.message:

            await self.message.edit(
                content="",
                embed=discord.Embed(
                    title="⌛ SOS Confirmation Expired",
                    description=(
                        "The event was not started in time."
                    ),
                    color=discord.Color.orange()
                ),
                view=self
            )


# =========================================================
# SOS JOIN VIEW
# =========================================================

class SOSJoinView(discord.ui.View):

    def __init__(
        self,
        ctx,
        amount
    ):
        super().__init__(timeout=28)

        self.ctx = ctx
        self.amount = amount

        # Users who actually clicked Join Event
        self.players = []

        self.message = None
        self.finished = False

    # -----------------------------------------------------
    # MENTIONS FOR MESSAGE CONTENT
    # -----------------------------------------------------

    def joined_mentions(self):

        if not self.players:
            return ""

        return " ".join(
            user.mention
            for user in self.players
        )

    # -----------------------------------------------------
    # NAMES FOR EMBED
    # -----------------------------------------------------

    def joined_names(self):

        if not self.players:
            return "No players have joined yet."

        return "\n".join(
            f"• {user.display_name}"
            for user in self.players
        )

    # -----------------------------------------------------
    # JOIN EMBED
    # -----------------------------------------------------

    def make_embed(self):

        embed = discord.Embed(
            title="⚔️ Split or Steal Event",
            description=(
                f"**Pot:** {money(self.amount)}\n"
                f"**Hosted by:** {self.ctx.author.display_name}\n\n"

                f"**Total Players Joined:** "
                f"{len(self.players)} / 2 minimum\n\n"

                f"**Users:**\n"
                f"{self.joined_names()}\n\n"

                "Click **Join Event** to participate.\n"
                "Two players will be selected when "
                "the timer ends."
            ),
            color=discord.Color.blurple()
        )

        embed.set_footer(
            text="Join period: 28 seconds"
        )

        return embed

    # -----------------------------------------------------
    # JOIN BUTTON
    # -----------------------------------------------------

    @discord.ui.button(
        label="Join Event",
        style=discord.ButtonStyle.success,
        emoji="🎮"
    )
    async def join_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if self.finished:

            await interaction.response.send_message(
                "This event has already ended.",
                ephemeral=True
            )

            return

        # Already joined
        if interaction.user.id in [
            user.id for user in self.players
        ]:

            await interaction.response.send_message(
                "You already joined this event.",
                ephemeral=True
            )

            return

        # Add player
        self.players.append(
            interaction.user
        )

        # Public message mentions joined users
        # so they receive a notification.
        await interaction.response.edit_message(
            content=self.joined_mentions(),
            embed=self.make_embed(),
            view=self
        )

    # -----------------------------------------------------
    # JOIN TIMEOUT
    # -----------------------------------------------------

    async def on_timeout(self):

        if self.finished:
            return

        self.finished = True

        for child in self.children:
            child.disabled = True

        # -------------------------------------------------
        # NOT ENOUGH PLAYERS
        # -------------------------------------------------

        if len(self.players) < 2:

            # Refund host
            await bot.db.change_balance(
                self.ctx.author.id,
                self.amount,
                "sos_not_enough_players_refund"
            )

            await self.message.edit(
                content="",
                embed=discord.Embed(
                    title="❌ SOS Event Cancelled",
                    description=(
                        "Not enough players joined.\n\n"
                        "**Minimum required:** 2 players\n"
                        f"**Joined:** {len(self.players)}\n\n"
                        f"Refunded: **{money(self.amount)}**"
                    ),
                    color=discord.Color.red()
                ),
                view=self
            )

            return

        # -------------------------------------------------
        # SELECT TWO RANDOM PLAYERS
        # -------------------------------------------------

        selected_players = random.sample(
            self.players,
            2
        )

        # Create decision view
        decision_view = SOSDecisionView(
            self.ctx,
            self.amount,
            selected_players
        )

        decision_view.message = self.message

        # Mention both selected players in CONTENT.
        # Their notifications happen here.
        #
        # The embed itself does not contain actual
        # mentions, so there are no extra notifications.
        await self.message.edit(
            content=(
                f"{selected_players[0].mention} "
                f"{selected_players[1].mention}"
            ),
            embed=decision_view.make_embed(),
            view=decision_view
        )


# =========================================================
# SOS DECISION VIEW
# =========================================================

class SOSDecisionView(discord.ui.View):

    def __init__(
        self,
        ctx,
        amount,
        players
    ):
        super().__init__(timeout=28)

        self.ctx = ctx
        self.amount = amount
        self.players = players

        # user_id -> SPLIT / STEAL
        self.choices = {}

        self.message = None
        self.finished = False

    # -----------------------------------------------------
    # PUBLIC EMBED
    # -----------------------------------------------------

    def make_embed(self):

        player_one = self.players[0]
        player_two = self.players[1]

        # IMPORTANT:
        #
        # We DO NOT reveal SPLIT or STEAL until BOTH
        # players have selected.
        #
        # Before that:
        #
        # Locked In
        # Thinking...
        #

        status_one = (
            "Locked In"
            if player_one.id in self.choices
            else "Thinking..."
        )

        status_two = (
            "Locked In"
            if player_two.id in self.choices
            else "Thinking..."
        )

        embed = discord.Embed(
            title="⚔️ SPLIT OR STEAL FACE-OFF",
            description=(
                "The players have been selected!\n"
                "Decisions close in **28 seconds**.\n\n"

                f"• **Player 1:** "
                f"{player_one.display_name} "
                f"➔ **{status_one}**\n"

                f"• **Player 2:** "
                f"{player_two.display_name} "
                f"➔ **{status_two}**\n\n"

                "Players, click your choice below to lock "
                "in your decision privately."
            ),
            color=discord.Color.gold()
        )

        return embed

    # -----------------------------------------------------
    # ONLY SELECTED PLAYERS CAN USE BUTTONS
    # -----------------------------------------------------

    async def interaction_check(
        self,
        interaction: discord.Interaction
    ):

        player_ids = [
            player.id
            for player in self.players
        ]

        # Not a selected player
        if interaction.user.id not in player_ids:

            await interaction.response.send_message(
                "You are not one of the selected players.",
                ephemeral=True
            )

            return False

        # Already chose
        if interaction.user.id in self.choices:

            await interaction.response.send_message(
                "You already locked in your decision.",
                ephemeral=True
            )

            return False

        return True

    # -----------------------------------------------------
    # SPLIT
    # -----------------------------------------------------

    @discord.ui.button(
        label="SPLIT",
        style=discord.ButtonStyle.success,
        emoji="🤝"
    )
    async def split_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        await self.choose(
            interaction,
            "SPLIT"
        )

    # -----------------------------------------------------
    # STEAL
    # -----------------------------------------------------

    @discord.ui.button(
        label="STEAL",
        style=discord.ButtonStyle.danger,
        emoji="💰"
    )
    async def steal_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        await self.choose(
            interaction,
            "STEAL"
        )

    # -----------------------------------------------------
    # PLAYER CHOICE
    # -----------------------------------------------------

    async def choose(
        self,
        interaction,
        choice
    ):

        # Save decision
        self.choices[
            interaction.user.id
        ] = choice

        # PRIVATE response
        #
        # It does NOT say "You chose SPLIT"
        # to avoid leaking anything.
        await interaction.response.send_message(
            "🔒 Your decision has been locked in.",
            ephemeral=True
        )

        # -------------------------------------------------
        # ONLY ONE PLAYER HAS ANSWERED
        # -------------------------------------------------

        if len(self.choices) < 2:

            # Public message ONLY says Locked In.
            await self.message.edit(
                content=(
                    f"{self.players[0].mention} "
                    f"{self.players[1].mention}"
                ),
                embed=self.make_embed(),
                view=self
            )

            return

        # -------------------------------------------------
        # BOTH PLAYERS HAVE ANSWERED
        # -------------------------------------------------

        await self.finish_event()

    # -----------------------------------------------------
    # FINISH EVENT
    # -----------------------------------------------------

    async def finish_event(self):

        if self.finished:
            return

        self.finished = True
        self.stop()

        for child in self.children:
            child.disabled = True

        player_one = self.players[0]
        player_two = self.players[1]

        choice_one = self.choices.get(
            player_one.id,
            "STEAL"
        )

        choice_two = self.choices.get(
            player_two.id,
            "STEAL"
        )

        # =================================================
        # BOTH SPLIT
        # =================================================

        if (
            choice_one == "SPLIT"
            and
            choice_two == "SPLIT"
        ):

            first_reward = self.amount // 2
            second_reward = (
                self.amount - first_reward
            )

            await bot.db.change_balance(
                player_one.id,
                first_reward,
                "sos_split"
            )

            await bot.db.change_balance(
                player_two.id,
                second_reward,
                "sos_split"
            )

            result_text = (
                f"• **Player 1:** "
                f"{player_one.mention} ➔ **SPLIT**\n"

                f"• **Player 2:** "
                f"{player_two.mention} ➔ **SPLIT**\n\n"

                "🤝 **Both players chose SPLIT!**\n\n"

                f"{player_one.mention} received "
                f"**{money(first_reward)}**\n"

                f"{player_two.mention} received "
                f"**{money(second_reward)}**"
            )

        # =================================================
        # PLAYER 1 STEALS
        # =================================================

        elif (
            choice_one == "STEAL"
            and
            choice_two == "SPLIT"
        ):

            await bot.db.change_balance(
                player_one.id,
                self.amount,
                "sos_steal"
            )

            result_text = (
                f"• **Player 1:** "
                f"{player_one.mention} ➔ **STEAL**\n"

                f"• **Player 2:** "
                f"{player_two.mention} ➔ **SPLIT**\n\n"

                f"💰 {player_one.mention} "
                "stole the entire pot!\n\n"

                f"Reward: **{money(self.amount)}**"
            )

        # =================================================
        # PLAYER 2 STEALS
        # =================================================

        elif (
            choice_one == "SPLIT"
            and
            choice_two == "STEAL"
        ):

            await bot.db.change_balance(
                player_two.id,
                self.amount,
                "sos_steal"
            )

            result_text = (
                f"• **Player 1:** "
                f"{player_one.mention} ➔ **SPLIT**\n"

                f"• **Player 2:** "
                f"{player_two.mention} ➔ **STEAL**\n\n"

                f"💰 {player_two.mention} "
                "stole the entire pot!\n\n"

                f"Reward: **{money(self.amount)}**"
            )

        # =================================================
        # BOTH STEAL
        # =================================================

        else:

            result_text = (
                f"• **Player 1:** "
                f"{player_one.mention} ➔ **STEAL**\n"

                f"• **Player 2:** "
                f"{player_two.mention} ➔ **STEAL**\n\n"

                "💀 **Both players chose STEAL.**\n\n"

                "Nobody receives the pot."
            )

        # =================================================
        # SHOW RESULT
        # =================================================

        await self.message.edit(
            content="",
            embed=discord.Embed(
                title="🏁 SOS EVENT RESULT",
                description=result_text,
                color=discord.Color.green()
            ),
            view=self
        )

    # -----------------------------------------------------
    # DECISION TIMEOUT
    # -----------------------------------------------------

    async def on_timeout(self):

        if self.finished:
            return

        # Anyone who didn't answer becomes STEAL.
        for player in self.players:

            if player.id not in self.choices:

                self.choices[
                    player.id
                ] = "STEAL"

        # Now both decisions can be revealed.
        await self.finish_event()


# =========================================================
# SOS COMMAND
# =========================================================

@bot.command(
    name="sos",
    aliases=["splitorsteal"]
)
async def sos(
    ctx,
    amount: str = None
):

    # -----------------------------------------------------
    # GAME CHANNEL CHECK
    # -----------------------------------------------------

    if not await bot.game_allowed(ctx):
        return

    # -----------------------------------------------------
    # NO AMOUNT
    # -----------------------------------------------------

    if amount is None:

        await ctx.send(
            f"Usage: `{ctx.prefix}sos <amount>`"
        )

        return

    # -----------------------------------------------------
    # PARSE AMOUNT
    # -----------------------------------------------------

    try:

        value = parse_amount(amount)

    except ValueError as error:

        await ctx.send(
            str(error)
        )

        return

    # -----------------------------------------------------
    # INVALID AMOUNT
    # -----------------------------------------------------

    if value <= 0:

        await ctx.send(
            "The amount must be greater than zero."
        )

        return

    # -----------------------------------------------------
    # CHECK BALANCE
    #
    # We don't remove the balance yet.
    # It gets removed only when Start is clicked.
    # -----------------------------------------------------

    # If your DB has a balance getter, you can add a
    # balance check here. Otherwise Start will check it.

    # -----------------------------------------------------
    # CONFIRMATION
    # -----------------------------------------------------

    confirm_view = SOSConfirmView(
        ctx,
        value
    )

    embed = discord.Embed(
        title="⚔️ Confirm Split or Steal",
        description=(
            f"{ctx.author.mention} wants to start a "
            f"Split or Steal event.\n\n"

            f"**Pot:** {money(value)}\n"
            f"**Host:** {ctx.author.display_name}\n\n"

            "Do you want to start this event?"
        ),
        color=discord.Color.gold()
    )

    message = await ctx.send(
        embed=embed,
        view=confirm_view
    )

    confirm_view.message = message

class WithdrawModal(discord.ui.Modal, title="Withdrawal request"):
    address = discord.ui.TextInput(label="Receiving address", min_length=20, max_length=128)
    amount = discord.ui.TextInput(label="Points to withdraw", placeholder="Minimum shown in previous menu")
    def __init__(self, currency, owner_id): super().__init__(); self.currency, self.owner_id = currency, owner_id
    async def on_submit(self, interaction):
        try: amount = parse_amount(self.amount.value)
        except ValueError as error: await interaction.response.send_message(str(error), ephemeral=True); return
        if amount < config.MIN_WITHDRAW[self.currency]:
            await interaction.response.send_message(f"Minimum {self.currency} withdrawal: {config.MIN_WITHDRAW[self.currency]} points.", ephemeral=True); return
        address = self.address.value.strip()
        if self.currency == "LTC" and not address.lower().startswith(("ltc1", "m", "n", "l")):
            await interaction.response.send_message("That does not look like a Litecoin address.", ephemeral=True); return
        if self.currency == "SOL" and (len(address) < 32 or len(address) > 50):
            await interaction.response.send_message("That does not look like a Solana address.", ephemeral=True); return
        if self.currency == "USDT" and not (address.startswith("0x") and len(address) == 42):
            await interaction.response.send_message("USDT BEP-20 needs a BSC address beginning with 0x.", ephemeral=True); return
        if not await bot.db.change_balance(interaction.user.id, -amount, "withdraw_request", f"{self.currency}:{address}"):
            await interaction.response.send_message("You do not have enough points.", ephemeral=True); return
        embed = brand("Withdrawal requested", f"**Total:** {money(amount)} points ({usd(amount)})\n**Currency:** {self.currency}\n**Address:** `{address}`\n\nYour Withdrawl has been succesfully proceed.", 0xFEE75C)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        channel = bot.get_channel(config.WITHDRAW_LOG_CHANNEL_ID)
        if channel: await channel.send(embed=brand("Withdrawal", f"{config.E['withdraw']} **{money(amount)} points** withdrawn by {interaction.user.mention}.\nCurrency: **{self.currency}**\nAddress: `{address}`\nPayment will be recived in few minutes."))


class WithdrawView(OwnerView):
    async def choose(self, interaction, currency):
        await interaction.response.send_modal(WithdrawModal(currency, self.owner_id))
    @discord.ui.button(label="LTC", emoji=config.E["ltc"])
    async def ltc(self, interaction, button): await self.choose(interaction, "LTC")
    @discord.ui.button(label="SOL", emoji=config.E["sol"])
    async def sol(self, interaction, button): await self.choose(interaction, "SOL")
    @discord.ui.button(label="USDT", emoji=config.E["usdt"])
    async def usdt(self, interaction, button): await self.choose(interaction, "USDT")


class ConfirmTipView(OwnerView):
    def __init__(self, owner, recipient, amount): super().__init__(owner.id); self.owner, self.recipient, self.amount = owner, recipient, amount
    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success, emoji=config.E["win"])
    async def confirm(self, interaction, button):
        if not await bot.db.change_balance(self.owner.id, -self.amount, "tip_sent", str(self.recipient.id)):
            await interaction.response.edit_message(content="Insufficient balance.", view=None); return
        await bot.db.change_balance(self.recipient.id, self.amount, "tip_received", str(self.owner.id))
        await bot.db.pool.execute("UPDATE users SET tips_sent=tips_sent+$2 WHERE user_id=$1", self.owner.id, self.amount)
        await bot.db.pool.execute("UPDATE users SET tips_received=tips_received+$2 WHERE user_id=$1", self.recipient.id, self.amount)
        await interaction.response.edit_message(content=f"{config.E['win']} {self.owner.mention} tipped {self.recipient.mention} **{money(self.amount)} points**.", view=None)
    @discord.ui.button(label="Decline", style=discord.ButtonStyle.secondary)
    async def decline(self, interaction, button): await interaction.response.edit_message(content="Tip cancelled.", view=None)


class BlackjackView(OwnerView):
    def __init__(self, owner, bet):
        super().__init__(owner.id, timeout=60); self.bet=bet; self.server,self.hash,self.rng=provably_fair(str(owner.id)); self.deck=deck(self.rng); self.player=[self.deck.pop(),self.deck.pop()]; self.dealer=[self.deck.pop(),self.deck.pop()]; self.done=False
    def text(self, reveal=False):
        dealer = ", ".join(self.dealer) if reveal else f"{self.dealer[0]}, ??"
        return f"**Your Hand:** {', '.join(self.player)} (**{hand_total(self.player)}**)\n**Dealer's Hand:** {dealer}" 
    def embed_and_file(self, reveal=False, title="Blackjack", colour=0x2B2D31, extra=""):
        embed=brand(title,self.text(reveal)+extra,colour)
        embed.set_image(url="attachment://blackjack_table.png")
        return embed, blackjack_table(self.player,self.dealer,reveal)
    async def finish(self, interaction):
        while hand_total(self.dealer) < 17: self.dealer.append(self.deck.pop())
        player,dealer_total=hand_total(self.player),hand_total(self.dealer)
        payout = round(self.bet*(2.0 if dealer_total>21 or player>dealer_total else 0),4)
        if player>21 or (dealer_total<=21 and dealer_total>=player): payout=0
        await bot.db.record_game(self.owner_id,self.bet,payout,"blackjack"); self.done=True
        for item in self.children: item.disabled=True
        outcome="Won" if payout else "Lost"; colour=0x57F287 if payout else 0xED4245
        fair=f"\n\n**Provably Fair**\nPublic Hash: `{self.hash}`\nServer Seed: `{self.server}`\nClient Seed: `{self.owner_id}`"
        embed,table=self.embed_and_file(True,f"Blackjack — {outcome}",colour,fair)
        await interaction.response.edit_message(embed=embed,attachments=[table],view=self)
    @discord.ui.button(label="Hit", style=discord.ButtonStyle.primary)
    async def hit(self, interaction, button):
        self.player.append(self.deck.pop())
        if hand_total(self.player)>21: await self.finish(interaction)
        else:
            embed,table=self.embed_and_file()
            await interaction.response.edit_message(embed=embed,attachments=[table],view=self)
    @discord.ui.button(label="Stand", style=discord.ButtonStyle.secondary)
    async def stand(self, interaction, button): await self.finish(interaction)
    @discord.ui.button(label="Double", style=discord.ButtonStyle.success)
    async def double(self, interaction, button):
        if len(self.player)!=2 or not await bot.db.change_balance(self.owner_id,-self.bet,"blackjack_double"):
            await interaction.response.send_message("Double is only available on your first hand with enough balance.",ephemeral=True); return
        self.bet*=2; self.player.append(self.deck.pop()); await self.finish(interaction)
    @discord.ui.button(label="Split", style=discord.ButtonStyle.secondary, disabled=True)
    async def split(self, interaction, button): await interaction.response.send_message("Split will be enabled in the next blackjack update.",ephemeral=True)






@bot.command(aliases=["hb", "housebal"])
async def housebalance(ctx):
    try:
        row = await bot.db.pool.fetchrow(
            "SELECT balance FROM house LIMIT 1"
        )

        if not row:
            await ctx.send(
                embed=brand(
                    "House Balance",
                    "House balance is not configured yet.",
                    0xED4245,
                )
            )
            return

        house_balance = float(row["balance"])

        await ctx.send(
            embed=brand(
                f"{config.CASINO_NAME} House Balance",
                (
                    f"<:usd:1550062382469087274> "
                    f"**Total liquidity: ${house_balance:,.2f}**\n\n"
                    "Note: house balance can be refilled or money can be "
                    "added by Owners anytime."
                ),
                0x00E676,
            )
        )

    except Exception as error:
        print(f"HOUSEBAL ERROR: {error}")

        await ctx.send(
            embed=brand(
                "House Balance",
                "Something went wrong while checking the house balance.",
                0xED4245,
            )
        )

import io
import random
import asyncio
from PIL import Image, ImageDraw


@bot.command()
async def help(ctx, command: str = None):
    if command:
        await ctx.send(embed=brand(f"Help: {command}", "Use the command menu for the available command groups.")); return
    embed=brand("Help", "**0.01 USD = 2 Points**\nUse `.help <command>` for details.\n-# Select a category below.")
    await ctx.send(embed=embed, view=HelpView(ctx.author.id))

@bot.command(aliases=["b"])
async def balance(ctx, member: discord.Member = None):
    member=member or ctx.author; row=await bot.db.user(member.id)
    await ctx.send(embed=brand("User Balance", f"{config.E['points']} **{money(row['balance'])} Points**\n≈ **{usd(row['balance'])}**\nOwner: {member.mention}"))

@bot.command()
async def price(ctx, points: str):
    try: amount=parse_amount(points)
    except ValueError as error: await ctx.send(str(error)); return
    await ctx.send(embed=brand("Point conversion", f"**{money(amount)} points** = **{usd(amount)} USD**\n1 point = $0.005"))

# ============================================================
# DEPOSIT SYSTEM - COMPLETE CODE
# ============================================================

import io
import qrcode

from bip_utils import (
    Bip44,
    Bip44Coins,
    Bip44Changes,
)


# ============================================================
# SETTINGS
# ============================================================

SOL_DEPOSIT_ADDRESS = "HKn9yAXBBUhPpgTrgnxndLL5QCqocpn8nHjNeWTB7Kv6"

USDT_DEPOSIT_ADDRESS = "0xc21F13F95afb0d53D54ccCa378E177F50f41ECF2"

LTC_MIN_DEPOSIT = 0.0005
SOL_MIN_DEPOSIT = 0.001
USDT_MIN_DEPOSIT = 1.0


# ============================================================
# DATABASE
# ============================================================

async def ensure_deposit_table():

    await bot.db.pool.execute("""
        CREATE TABLE IF NOT EXISTS deposit_addresses (
            user_id BIGINT NOT NULL,
            currency TEXT NOT NULL,
            address TEXT NOT NULL,
            derivation_index BIGINT,
            created_at TIMESTAMPTZ DEFAULT NOW(),

            PRIMARY KEY (user_id, currency),
            UNIQUE (address)
        )
    """)


async def get_saved_deposit_address(user_id, currency):

    await ensure_deposit_table()

    return await bot.db.pool.fetchval(
        """
        SELECT address
        FROM deposit_addresses
        WHERE user_id = $1
        AND currency = $2
        """,
        user_id,
        currency,
    )


# ============================================================
# LTC XPUB
# ============================================================

def ltc_address_from_xpub(xpub: str, index: int) -> str:

    if not xpub:
        raise ValueError(
            "LTC_XPUB is missing from Railway variables."
        )

    wallet = Bip44.FromExtendedKey(
        xpub.strip(),
        Bip44Coins.LITECOIN,
    )

    address = (
        wallet
        .Change(Bip44Changes.CHAIN_EXT)
        .AddressIndex(index)
        .PublicKey()
        .ToAddress()
    )

    return address


async def generate_ltc_deposit_address(user_id: int) -> str:

    await ensure_deposit_table()

    existing = await get_saved_deposit_address(
        user_id,
        "LTC",
    )

    if existing:
        return existing

    row = await bot.db.pool.fetchrow(
        """
        SELECT COALESCE(
            MAX(derivation_index), -1
        ) + 1 AS next_index
        FROM deposit_addresses
        WHERE currency = 'LTC'
        """
    )

    index = int(row["next_index"])

    address = ltc_address_from_xpub(
        config.LTC_XPUB,
        index,
    )

    await bot.db.pool.execute(
        """
        INSERT INTO deposit_addresses
            (user_id, currency, address, derivation_index)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (user_id, currency)
        DO NOTHING
        """,
        user_id,
        "LTC",
        address,
        index,
    )

    saved = await get_saved_deposit_address(
        user_id,
        "LTC",
    )

    return saved or address


# ============================================================
# QR CODE
# ============================================================

def make_deposit_qr(address: str, currency: str):

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )

    if currency == "LTC":
        data = f"litecoin:{address}"

    elif currency == "SOL":
        data = f"solana:{address}"

    else:
        data = address

    qr.add_data(data)
    qr.make(fit=True)

    image = qr.make_image(
        fill_color="black",
        back_color="white",
    ).convert("RGB")

    output = io.BytesIO()

    image.save(
        output,
        format="PNG",
    )

    output.seek(0)

    return discord.File(
        output,
        filename="deposit_qr.png",
    )


# ============================================================
# DEPOSIT VIEW
# ============================================================

class DepositView(OwnerView):

    def __init__(self, owner_id: int):

        super().__init__(
            owner_id,
            timeout=180,
        )

    async def send_currency(
        self,
        interaction: discord.Interaction,
        currency: str,
    ):

        try:

            await interaction.response.defer(
                ephemeral=True,
            )

        except discord.InteractionResponded:
            pass

        user = interaction.user

        try:

            if currency == "LTC":

                if not config.LTC_XPUB:

                    await interaction.followup.send(
                        "LTC_XPUB is missing from Railway variables.",
                        ephemeral=True,
                    )

                    return

                address = await generate_ltc_deposit_address(
                    user.id,
                )

                minimum = LTC_MIN_DEPOSIT
                conversion = "1 point = 0.0001 LTC"

            elif currency == "SOL":

                address = SOL_DEPOSIT_ADDRESS

                minimum = SOL_MIN_DEPOSIT
                conversion = "1 point = 0.0001 SOL"

            elif currency == "USDT":

                address = USDT_DEPOSIT_ADDRESS

                minimum = USDT_MIN_DEPOSIT
                conversion = "1 point = 0.0001 USDT"

            else:

                await interaction.followup.send(
                    "Unsupported currency.",
                    ephemeral=True,
                )

                return

            print(
                f"[DEPOSIT] {currency} selected by "
                f"{user} ({user.id})"
            )

            qr_file = make_deposit_qr(
                address,
                currency,
            )

            embed = discord.Embed(
                title=f"Your {currency} Deposit Address",
                description=(
                    f"{user.mention}, deposit "
                    f"**{currency}** only:\n\n"
                    f"```{address}```\n\n"
                    f"Minimum: **{minimum} {currency}**\n"
                    f"Conversion: **{conversion}**\n"
                    f"Fee: **0%**"
                ),
                colour=0x3498DB,
            )

            embed.set_image(
                url="attachment://deposit_qr.png"
            )

            embed.set_footer(
                text=(
                    f"Only send {currency} | "
                    f"Minimum: {minimum} {currency}"
                )
            )

            try:

                await user.send(
                    embed=embed,
                    file=qr_file,
                )

            except discord.Forbidden:

                await interaction.followup.send(
                    "I couldn't DM you. "
                    "Please enable your DMs from server members.",
                    ephemeral=True,
                )

                return

            except discord.HTTPException as error:

                print(
                    f"[DEPOSIT DM ERROR] {error}"
                )

                await interaction.followup.send(
                    "Failed to send your deposit DM.",
                    ephemeral=True,
                )

                return

            await interaction.followup.send(
                f"{config.E['win']} Your **{currency}** "
                "deposit address has been sent to your DMs.",
                ephemeral=True,
            )

        except Exception as error:

            print(
                f"[DEPOSIT ERROR] {currency}: "
                f"{type(error).__name__}: {error}"
            )

            await interaction.followup.send(
                "Could not generate your deposit address. "
                "Please contact an administrator.",
                ephemeral=True,
            )

    @discord.ui.button(
        label="LTC",
        style=discord.ButtonStyle.secondary,
        emoji=config.E["ltc"],
    )
    async def ltc(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await self.send_currency(
            interaction,
            "LTC",
        )

    @discord.ui.button(
        label="SOL",
        style=discord.ButtonStyle.secondary,
        emoji=config.E["sol"],
    )
    async def sol(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await self.send_currency(
            interaction,
            "SOL",
        )

    @discord.ui.button(
        label="USDT (BEP-20)",
        style=discord.ButtonStyle.secondary,
        emoji=config.E["usdt"],
    )
    async def usdt(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await self.send_currency(
            interaction,
            "USDT",
        )


# ============================================================
# DEPOSIT COMMAND
# ============================================================

@bot.command()
async def deposit(ctx):

    embed = brand(
        "Deposit",
        (
            "Choose a currency below.\n\n"
            "Your deposit address will be sent to your DMs.\n"
            "Deposits are credited only after blockchain confirmation."
        ),
        0x3498DB,
    )

    await ctx.send(
        embed=embed,
        view=DepositView(
            ctx.author.id,
        ),
    )


@bot.command()
async def withdraw(ctx):
    await ctx.send(embed=brand("Withdraw", "Choose the currency to withdraw.\nLTC minimum: **20** • SOL: **220** • USDT: **150** points\n\nYour Withdrawl will be proceed automatic"),view=WithdrawView(ctx.author.id))

@bot.command()
async def tip(ctx, member: discord.Member, points: str):
    if member.bot or member.id==ctx.author.id: await ctx.send("Choose another user."); return
    try: amount=parse_amount(points)
    except ValueError as error: await ctx.send(str(error)); return
    await ctx.send(f"Send **{money(amount)} points** to {member.mention}?",view=ConfirmTipView(ctx.author,member,amount))

@bot.command()
async def daily(ctx):
    row=await bot.db.user(ctx.author.id); now=datetime.now(timezone.utc); last=row['daily_at']
    if float(row['balance']) < 1: await ctx.send(embed=brand("Daily", "You need at least **1 point** in your balance to claim daily.")); return
    if last and now-last < timedelta(hours=24): await ctx.send(embed=brand("Daily",f"Please come back <t:{int((last+timedelta(hours=24)).timestamp())}:R>.")); return
    await bot.db.change_balance(ctx.author.id,1,"daily"); await bot.db.pool.execute("UPDATE users SET daily_at=$2,bonus_received=bonus_received+1 WHERE user_id=$1",ctx.author.id,now)
    await ctx.send(embed=brand("Daily claimed",f"{config.E['win']} You received **1.00 point**."))

async def bonus(ctx, period, days):
    row=await bot.db.user(ctx.author.id); field=f"{period}_at"; last=row[field]; now=datetime.now(timezone.utc); earned=float(row['losses'])*(.005 if period!='weekly' else .005)
    if last and now-last<timedelta(days=days): await ctx.send(embed=brand(f"{period.title()} Bonus",f"Claimed already. Return <t:{int((last+timedelta(days=days)).timestamp())}:R>.")); return
    if earned<=0: await ctx.send(embed=brand(f"{period.title()} Bonus", "**Claimable:** 0 points\nPlay games to earn a bonus.")); return
    await bot.db.change_balance(ctx.author.id,earned,period); await bot.db.pool.execute(f"UPDATE users SET {field}=$2,losses=0,bonus_received=bonus_received+$3 WHERE user_id=$1",ctx.author.id,now,earned)
    await ctx.send(embed=brand(f"{period.title()} Bonus",f"{config.E['win']} Claimed **{money(earned)} points** ({usd(earned)})."))
@bot.command(aliases=["week"])
async def weekly(ctx): await bonus(ctx,"weekly",7)
@bot.command(aliases=["monthy"])
async def monthly(ctx): await bonus(ctx,"monthly",30)
@bot.command(aliases=["rb"])
async def rakeback(ctx):
    row=await bot.db.user(ctx.author.id); available=float(row['rakeback'])
    if available<=0: await ctx.send(embed=brand("Your Rakeback Details","Available Rakeback Points: **0 points**\nYou get 1% of losses and 0.5% of wins.")); return
    await bot.db.change_balance(ctx.author.id,available,"rakeback"); await bot.db.pool.execute("UPDATE users SET rakeback=0 WHERE user_id=$1",ctx.author.id)
    await ctx.send(embed=brand("Your Rakeback Details",f"{config.E['win']} Claimed **{money(available)} points**."))

import io
import random
import asyncio
from PIL import Image, ImageDraw, ImageFont
import discord


# =========================================================
# COINFLIP IMAGES
# =========================================================

COINFLIP_IMAGES = {
    "heads": "https://media.discordapp.net/attachments/1550136730731024425/1550495453781426216/image.png?ex=6aae8aea&is=6aad396a&hm=871a61aec62433c1a7cc838f9405b39095b00e521ee5b64a154b7318f3e2d80d&=&format=webp&quality=lossless&width=640&height=516",

    "tails": "https://media.discordapp.net/attachments/1550136730731024425/1550495462342267053/image.png?ex=6aae8aed&is=6aad396d&hm=276af9bbf5c628c07c7d3c735d1ea7092a2e679502af81856cee5fd45820484a&=&format=webp&quality=lossless"
}


# =========================================================
# COINFLIP CONFIG
# =========================================================

# TOTAL payout multiplier.
#
# Example:
# 100 bet -> 192 total payout
# 500 bet -> 960 total payout
# 1000 bet -> 1920 total payout
#
# The original bet is already removed before the game,
# so the player receives the full 1.92x amount on a win.

COINFLIP_PAYOUT = 1.92


# =========================================================
# COINFLIP COMMAND
# =========================================================

@bot.command(
    name="coinflip",
    aliases=["cf"]
)
async def coinflip(
    ctx,
    bet: str,
    choice: str = "r"
):

    # -----------------------------------------------------
    # CHECK IF GAMES ARE ALLOWED
    # -----------------------------------------------------

    if not await bot.game_allowed(ctx):
        return

    # -----------------------------------------------------
    # PARSE BET
    # -----------------------------------------------------

    try:

        amount = parse_amount(bet)

    except ValueError as error:

        await ctx.send(
            str(error)
        )

        return

    # -----------------------------------------------------
    # VALIDATE BET
    # -----------------------------------------------------

    if amount <= 0:

        await ctx.send(
            "Bet must be greater than zero."
        )

        return

    # -----------------------------------------------------
    # CHOICE
    # -----------------------------------------------------

    choice = choice.lower()

    if choice not in (
        "h",
        "heads",
        "t",
        "tails",
        "r",
        "random"
    ):

        await ctx.send(
            "Choose `h`, `t`, or `r`."
        )

        return

    # -----------------------------------------------------
    # REMOVE BET
    # -----------------------------------------------------

    deducted = await bot.db.change_balance(
        ctx.author.id,
        -amount,
        "coinflip_bet"
    )

    if not deducted:

        await ctx.send(
            "Insufficient balance."
        )

        return

    # -----------------------------------------------------
    # PLAYER PICK
    # -----------------------------------------------------

    if choice in (
        "h",
        "heads"
    ):

        pick = "heads"

    elif choice in (
        "t",
        "tails"
    ):

        pick = "tails"

    else:

        pick = random.choice(
            [
                "heads",
                "tails"
            ]
        )

    # -----------------------------------------------------
    # FLIPPING MESSAGE
    # -----------------------------------------------------

    flipping_embed = brand(
        "🪙 Coinflip",
        (
            f"{ctx.author.mention} flipped a coin...\n\n"
            f"**Bet:** {money(amount)} points\n"
            f"**Choice:** {pick.title()}\n"
            f"**Payout:** {COINFLIP_PAYOUT:.2f}x total"
        )
    )

    flipping_message = await ctx.send(
        embed=flipping_embed
    )

    # -----------------------------------------------------
    # WAIT 2 SECONDS
    # -----------------------------------------------------

    await asyncio.sleep(2)

    # -----------------------------------------------------
    # RESULT
    # -----------------------------------------------------

    result = random.choice(
        [
            "heads",
            "tails"
        ]
    )

    # -----------------------------------------------------
    # PAYOUT
    # -----------------------------------------------------

    if pick == result:

        # -------------------------------------------------
        # 1.92x TOTAL PAYOUT
        #
        # 100 bet = 192 payout
        # 200 bet = 384 payout
        # 500 bet = 960 payout
        # -------------------------------------------------

        payout = round(
            amount * COINFLIP_PAYOUT,
            4
        )

        payout_success = await bot.db.change_balance(
            ctx.author.id,
            payout,
            "coinflip_win"
        )

        # -------------------------------------------------
        # PAYOUT ERROR
        # -------------------------------------------------

        if not payout_success:

            # Refund original bet if payout fails
            try:

                await bot.db.change_balance(
                    ctx.author.id,
                    amount,
                    "coinflip_payout_refund"
                )

            except Exception as refund_error:

                print(
                    f"[COINFLIP] Refund error: "
                    f"{refund_error}"
                )

            error_embed = brand(
                "Coinflip Error",
                (
                    "The payout could not be processed.\n\n"
                    "Your original bet has been refunded."
                ),
                0xED4245
            )

            await flipping_message.edit(
                content="",
                embed=error_embed
            )

            return

    else:

        payout = 0

    # -----------------------------------------------------
    # RECORD GAME
    # -----------------------------------------------------

    try:

        await bot.db.record_game(
            ctx.author.id,
            amount,
            payout,
            "coinflip"
        )

    except Exception as error:

        print(
            f"[COINFLIP] Record game error: "
            f"{error}"
        )

    # -----------------------------------------------------
    # RESULT EMBED
    # -----------------------------------------------------

    if payout > 0:

        embed = brand(
            "🎉 You Won!",
            (
                f"You bet on **{pick.title()}** "
                f"and the coin landed on "
                f"**{result.title()}**.\n\n"
                f"**Bet:** {money(amount)} points\n"
                f"**Payout:** {money(payout)} points\n"
                f"**Multiplier:** {COINFLIP_PAYOUT:.2f}x"
            ),
            0x57F287
        )

    else:

        embed = brand(
            "You Lost!",
            (
                f"You bet on **{pick.title()}** "
                f"but the coin landed on "
                f"**{result.title()}**.\n\n"
                f"**Bet:** {money(amount)} points\n"
                f"**Payout:** 0 points"
            ),
            0xED4245
        )

    # -----------------------------------------------------
    # RESULT IMAGE
    # -----------------------------------------------------

    embed.set_image(
        url=COINFLIP_IMAGES[result]
    )

    # -----------------------------------------------------
    # FOOTER
    # -----------------------------------------------------

    embed.set_footer(
        text="🔒 Provably Fair | Coinflip"
    )

    # -----------------------------------------------------
    # EDIT ORIGINAL MESSAGE
    # -----------------------------------------------------

    await flipping_message.edit(
        content="",
        embed=embed
    )

@bot.command()
async def addbal(ctx, member: discord.Member, points: str):
    if not allowed_admin(ctx):
        await ctx.send("Administrator only.")
        return

    try:
        amount = parse_amount(points)
    except ValueError as error:
        await ctx.send(str(error))
        return

    await bot.db.change_balance(
        member.id,
        amount,
        "admin_add_balance",
        f"Added by {ctx.author.id}",
    )

    await ctx.send(
        embed=brand(
            "Balance Added",
            (
                f"{config.E['win']} Added **{money(amount)} points** "
                f"to {member.mention}.\n"
                f"Value added: **{usd(amount)}**"
            ),
            0x57F287,
        )
    )
    
@bot.command(aliases=["bj"])
async def blackjack(ctx, bet: str):

    if not await bot.game_allowed(ctx):
        return

    try:
        bet_lower = bet.lower().strip()

        if bet_lower in ("half", "all", "max"):

            row = await bot.db.user(ctx.author.id)

            if not row:
                await ctx.send(
                    "Your account could not be found."
                )
                return

            balance = row["balance"]

            if bet_lower in ("all", "max"):
                amount = parse_amount(str(balance))

            else:
                half_balance = Decimal(str(balance)) / Decimal("2")
                amount = parse_amount(str(half_balance))

        else:
            amount = parse_amount(bet)

    except ValueError as error:
        await ctx.send(str(error))
        return

    # Minimum bet: 20 points ($0.10)
    if amount < Decimal("20"):
        await ctx.send(
            "The minimum bet is **20 points ($0.10)**."
        )
        return

    if not await bot.db.change_balance(
        ctx.author.id,
        -amount,
        "blackjack_bet",
    ):
        await ctx.send(
            "Insufficient balance."
        )
        return

    view = BlackjackView(
        ctx.author,
        amount
    )

    embed, table = view.embed_and_file()

    await ctx.send(
        embed=embed,
        file=table,
        view=view
    )
# ============================================================
# MINES GAME
# ============================================================

class MinesView(OwnerView):

    def __init__(self, owner, bet, mines):
        super().__init__(owner.id, timeout=120)

        self.bet = bet
        self.mines = mines
        self.opened = 0

        self.bombs = set(
            random.sample(range(25), mines)
        )

        self.finished = False
        self.message = None

        # Keep track of opened tiles.
        self.opened_tiles = set()

        # Create 5x5 board.
        for index in range(25):

            button = discord.ui.Button(
                label="\u200b",
                style=discord.ButtonStyle.secondary,
                row=index // 5,
                custom_id=f"mines_{index}",
            )

            button.callback = self.pick

            self.add_item(button)

    def multiplier(self):
        return max(
            1.0,
            (25 / (25 - self.mines)) ** self.opened * .96
        )

    async def pick(self, interaction):

        if self.finished:
            await interaction.response.send_message(
                "This Mines game has ended.",
                ephemeral=True,
            )
            return

        index = int(
            interaction.data["custom_id"].split("_")[1]
        )

        # Prevent clicking an already opened tile.
        if index in self.opened_tiles:
            await interaction.response.send_message(
                "You already opened this tile.",
                ephemeral=True,
            )
            return

        button = next(
            x for x in self.children
            if x.custom_id == f"mines_{index}"
        )

        # ----------------------------------------------------
        # MINE HIT
        # ----------------------------------------------------

        if index in self.bombs:

            self.finished = True

            button.emoji = config.E["bomb"]
            button.style = discord.ButtonStyle.danger
            button.disabled = True

            # Reveal all bombs.
            for x in self.children:

                if (
                    x.custom_id
                    and x.custom_id.startswith("mines_")
                    and int(x.custom_id.split("_")[1]) in self.bombs
                ):
                    x.emoji = config.E["bomb"]
                    x.disabled = True

            # Disable all tiles.
            for x in self.children:
                x.disabled = True

            await bot.db.record_game(
                self.owner_id,
                self.bet,
                0,
                "mines",
            )

            await interaction.response.edit_message(
                embed=brand(
                    "Mines — Lost",
                    (
                        f"You hit a mine and lost "
                        f"**{money(self.bet)} points**."
                    ),
                    0xED4245,
                ),
                view=self,
            )

            # Remove cashout reaction if present.
            if self.message:
                try:
                    await self.message.clear_reactions()
                except discord.HTTPException:
                    pass

            return

        # ----------------------------------------------------
        # SAFE TILE
        # ----------------------------------------------------

        self.opened += 1
        self.opened_tiles.add(index)

        button.emoji = config.E["diamond"]
        button.style = discord.ButtonStyle.success
        button.disabled = True

        # ----------------------------------------------------
        # ALL SAFE TILES OPENED
        # ----------------------------------------------------

        if self.opened == 25 - self.mines:

            await self.cashout_message(
                interaction.message
            )

            return

        # ----------------------------------------------------
        # UPDATE BOARD
        # ----------------------------------------------------

        embed = brand(
            "Mines",
            (
                f"Diamonds: **{self.opened}** • "
                f"Current payout: "
                f"**{money(self.bet * self.multiplier())} points**"
            ),
        )

        await interaction.response.edit_message(
            embed=embed,
            view=self,
        )

        # Add cashout reaction once.
        if self.message and self.opened == 1:

            try:
                await self.message.add_reaction("💰")
            except discord.HTTPException:
                pass

    # ========================================================
    # CASHOUT FROM REACTION
    # ========================================================

    async def cashout_message(self, message):

        if self.finished:
            return

        self.finished = True

        payout = round(
            self.bet * self.multiplier(),
            4,
        )

        # Disable all tiles.
        for x in self.children:
            x.disabled = True

        await bot.db.record_game(
            self.owner_id,
            self.bet,
            payout,
            "mines",
        )

        embed = brand(
            "Mines — Cashed out",
            (
                f"{config.E['win']} You won "
                f"**{money(payout)} points** "
                f"({self.multiplier():.2f}x)."
            ),
            0x57F287,
        )

        await message.edit(
            embed=embed,
            view=self,
        )

        try:
            await message.clear_reactions()
        except discord.HTTPException:
            pass

    async def on_timeout(self):

        if self.finished:
            return

        self.finished = True

        for x in self.children:
            x.disabled = True

        if self.message:

            try:
                await self.message.edit(view=self)
                await self.message.clear_reactions()
            except discord.HTTPException:
                pass

# ============================================================
# MINES COMMAND
# ============================================================
@bot.command()
async def mines(ctx, bet: str, mine_count: int = 3):

    if not await bot.game_allowed(ctx):
        return

    try:
        bet_lower = bet.lower().strip()

        if bet_lower in ("half", "all", "max"):

            row = await bot.db.user(ctx.author.id)

            if not row:
                await ctx.send(
                    "Your account could not be found."
                )
                return

            balance = row["balance"]

            if bet_lower in ("all", "max"):
                amount = parse_amount(str(balance))

            else:
                half_balance = Decimal(str(balance)) / Decimal("2")
                amount = parse_amount(str(half_balance))

        else:
            amount = parse_amount(bet)

    except ValueError as error:
        await ctx.send(str(error))
        return

    # Minimum bet: 20 points ($0.10)
    if amount < Decimal("20"):
        await ctx.send(
            "The minimum bet is **20 points ($0.10)**."
        )
        return

    if not 1 <= mine_count <= 20:

        await ctx.send(
            "Choose from 1 to 20 mines."
        )

        return

    if not await bot.db.change_balance(
        ctx.author.id,
        -amount,
        "mines_bet",
    ):

        await ctx.send(
            "Insufficient balance."
        )

        return

    view = MinesView(
        ctx.author,
        amount,
        mine_count,
    )

    message = await ctx.send(
        embed=brand(
            "Mines",
            (
                f"Bet: **{money(amount)} points** • "
                f"Mines: **{mine_count}**\n"
                f"Find diamonds, then react with 💰 to cash out."
            ),
        ),
        view=view,
    )

    # Save message for reaction cashout.
    view.message = message

    # Store active game by message ID.
    if not hasattr(bot, "active_mines"):
        bot.active_mines = {}

    bot.active_mines[message.id] = view
        
# =========================================================
# HILO CARD SETTINGS
# =========================================================

import os
import random
import discord


HILO_CARD_FOLDER = "."


HILO_SUITS = [
    "clubs",
    "diamonds",
    "hearts",
    "spades"
]


HILO_RANKS = {
    2: "2",
    3: "3",
    4: "4",
    5: "5",
    6: "6",
    7: "7",
    8: "8",
    9: "9",
    10: "10",
    11: "jack",
    12: "queen",
    13: "king",
    14: "ace"
}


# =========================================================
# GET CARD PNG
# =========================================================

def hilo_card_file(rank, suit):

    filename = f"{HILO_RANKS[rank]}_of_{suit}.png"

    path = os.path.join(
        HILO_CARD_FOLDER,
        filename
    )

    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Card image not found: {filename}"
        )

    return discord.File(
        path,
        filename="hilo_card.png"
    )


# =========================================================
# HILO VIEW
# =========================================================

class HiloView(OwnerView):

    def __init__(self, owner, bet):

        super().__init__(
            owner.id,
            timeout=60
        )

        self.bet = bet

        self.current_rank = random.randint(
            2,
            14
        )

        self.current_suit = random.choice(
            HILO_SUITS
        )

        self.rounds = 0
        self.finished = False

    # -----------------------------------------------------
    # RANK NAME
    # -----------------------------------------------------

    def rank_name(self, value):

        return {
            11: "Jack",
            12: "Queen",
            13: "King",
            14: "Ace"
        }.get(
            value,
            str(value)
        )

    # -----------------------------------------------------
    # CURRENT CARD
    # -----------------------------------------------------

    def current_card_file(self):

        return hilo_card_file(
            self.current_rank,
            self.current_suit
        )

    # -----------------------------------------------------
    # GAME EMBED
    # -----------------------------------------------------

    def game_embed(self):

        multiplier = 1 + (
            self.rounds * 0.14
        )

        embed = brand(
            "HiLo",
            (
                f"**Current Card:** "
                f"{self.rank_name(self.current_rank)}\n\n"

                f"**Next Card:** ❓\n\n"

                f"**High or Low?**\n\n"

                f"**Current Streak:** "
                f"{self.rounds}\n"

                f"**Current Multi:** "
                f"{multiplier:.2f}x"
            )
        )

        embed.set_image(
            url="attachment://hilo_card.png"
        )

        return embed

    # -----------------------------------------------------
    # GUESS
    # -----------------------------------------------------

    async def guess(
        self,
        interaction,
        higher
    ):

        if self.finished:
            return

        # Draw next card
        next_rank = random.randint(
            2,
            14
        )

        next_suit = random.choice(
            HILO_SUITS
        )

        # -------------------------------------------------
        # HIGHER / LOWER
        # -------------------------------------------------

        if higher:

            won = (
                next_rank >
                self.current_rank
            )

        else:

            won = (
                next_rank <
                self.current_rank
            )

        # =================================================
        # LOSS
        # =================================================

        if not won:

            self.finished = True

            for item in self.children:
                item.disabled = True

            await bot.db.record_game(
                self.owner_id,
                self.bet,
                0,
                "hilo"
            )

            embed = brand(
                "HiLo — Lost",
                (
                    f"**Current Card:** "
                    f"{self.rank_name(self.current_rank)}\n"

                    f"**Next Card:** "
                    f"{self.rank_name(next_rank)}\n\n"

                    f"**Current Streak:** "
                    f"{self.rounds}\n"

                    f"**Current Multi:** "
                    f"{1 + self.rounds * 0.14:.2f}x\n\n"

                    f"You lost **{money(self.bet)} points**."
                ),
                0xED4245
            )

            embed.set_image(
                url="attachment://hilo_card.png"
            )

            next_file = hilo_card_file(
                next_rank,
                next_suit
            )

            await interaction.response.edit_message(
                embed=embed,
                attachments=[next_file],
                view=self
            )

            return

        # =================================================
        # WON ROUND
        # =================================================

        self.rounds += 1

        self.current_rank = next_rank
        self.current_suit = next_suit

        # =================================================
        # FINISH AFTER 8 ROUNDS
        # =================================================

        if self.rounds >= 8:

            self.finished = True

            payout = round(
                self.bet * (
                    1 + self.rounds * 0.14
                ),
                4
            )

            for item in self.children:
                item.disabled = True

            await bot.db.change_balance(
                self.owner_id,
                payout,
                "hilo_win"
            )

            await bot.db.record_game(
                self.owner_id,
                self.bet,
                payout,
                "hilo"
            )

            embed = brand(
                "HiLo — Won",
                (
                    f"**Current Card:** "
                    f"{self.rank_name(self.current_rank)}\n\n"

                    f"**Current Streak:** "
                    f"{self.rounds}\n"

                    f"**Current Multi:** "
                    f"{1 + self.rounds * 0.14:.2f}x\n\n"

                    f"{config.E['win']} "
                    f"You won **{money(payout)} points**!"
                ),
                0x57F287
            )

            embed.set_image(
                url="attachment://hilo_card.png"
            )

            final_file = hilo_card_file(
                self.current_rank,
                self.current_suit
            )

            await interaction.response.edit_message(
                embed=embed,
                attachments=[final_file],
                view=self
            )

            return

        # =================================================
        # NEXT ROUND
        # =================================================

        await interaction.response.edit_message(
            embed=self.game_embed(),
            attachments=[
                self.current_card_file()
            ],
            view=self
        )

    # -----------------------------------------------------
    # HIGHER
    # -----------------------------------------------------

    @discord.ui.button(
        label="Higher",
        style=discord.ButtonStyle.success,
        emoji="⬆️"
    )
    async def higher(
        self,
        interaction,
        button
    ):

        await self.guess(
            interaction,
            True
        )

    # -----------------------------------------------------
    # LOWER
    # -----------------------------------------------------

    @discord.ui.button(
        label="Lower",
        style=discord.ButtonStyle.primary,
        emoji="⬇️"
    )
    async def lower(
        self,
        interaction,
        button
    ):

        await self.guess(
            interaction,
            False
        )


# =========================================================
# HILO COMMAND
# =========================================================

@bot.command()
async def hilo(
    ctx,
    bet: str
):

    if not await bot.game_allowed(ctx):
        return

    try:

        amount = parse_amount(bet)

    except ValueError as error:

        await ctx.send(
            str(error)
        )

        return

    if amount <= 0:

        await ctx.send(
            "Bet must be greater than zero."
        )

        return

    # -----------------------------------------------------
    # TAKE BET
    # -----------------------------------------------------

    if not await bot.db.change_balance(
        ctx.author.id,
        -amount,
        "hilo_bet"
    ):

        await ctx.send(
            "Insufficient balance."
        )

        return

    # -----------------------------------------------------
    # CREATE GAME
    # -----------------------------------------------------

    view = HiloView(
        ctx.author,
        amount
    )

    # -----------------------------------------------------
    # GET REAL CARD PNG
    # -----------------------------------------------------

    try:

        card_file = view.current_card_file()

    except FileNotFoundError as error:

        # Refund if image is missing
        await bot.db.change_balance(
            ctx.author.id,
            amount,
            "hilo_card_error_refund"
        )

        await ctx.send(
            f"HiLo card error: `{error}`"
        )

        return

    # -----------------------------------------------------
    # SEND
    # -----------------------------------------------------

    await ctx.send(
        embed=view.game_embed(),
        file=card_file,
        view=view
    )


@bot.command()
async def stats(ctx, member: discord.Member=None):
    member=member or ctx.author; row=await bot.db.user(member.id)
    text=f"Withdrawals: **0 points** (**0 times**)\nWon: **{row['won_games']} games**\nBonus received: **{money(row['bonus_received'])} points**\nTotal Played: **{row['games_played']} games** and wagered **{money(row['wagered'])} points**\nTips sent: **{money(row['tips_sent'])} points**\nTips received: **{money(row['tips_received'])} points**"
    embed=brand(f"Stats for {member.display_name}",text); embed.set_thumbnail(url=member.display_avatar.url); await ctx.send(embed=embed)

@bot.command()
async def whois(ctx, member: discord.Member=None):
    member=member or ctx.author; created=f"<t:{int(member.created_at.timestamp())}:F>"; joined=f"<t:{int(member.joined_at.timestamp())}:F>" if member.joined_at else "Unknown"
    roles=", ".join(r.mention for r in member.roles[1:]) or "None"
    embed=brand(f"Information for {member}",f"**Global Info**\n> **ID:** {member.id}\n> **Bot:** {'Yes' if member.bot else 'No'}\n> **Created:** {created}\n> **Username:** {member.name}\n\n**Server Info**\n> **Nickname:** {member.nick or 'None'}\n> **Joined:** {joined}\n> **Roles:** {roles}\n> **Status:** {member.status}")
    embed.set_thumbnail(url=member.display_avatar.url); await ctx.send(embed=embed)

@bot.command(aliases=["lb"])
async def leaderboard(ctx):
    rows=await bot.db.leaderboard(); lines=[]
    for index,row in enumerate(rows,1):
        user=bot.get_user(row['user_id']) or await bot.fetch_user(row['user_id']); lines.append(f"`#{index}` **{user}** — {money(row['wagered'])} points")
    await ctx.send(embed=brand("Leaderboard", "\n".join(lines) or "No games have been played yet."))

@bot.command()
async def vault(ctx, action: str, points: str):
    try: amount=parse_amount(points)
    except ValueError as error: await ctx.send(str(error)); return
    row=await bot.db.user(ctx.author.id)
    if action.lower()=="deposit":
        if not await bot.db.change_balance(ctx.author.id,-amount,"vault_deposit"): await ctx.send("Insufficient balance."); return
        await bot.db.pool.execute("UPDATE users SET vault=vault+$2 WHERE user_id=$1",ctx.author.id,amount)
    elif action.lower()=="withdraw":
        if float(row['vault'])<amount: await ctx.send("Insufficient vault balance."); return
        await bot.db.pool.execute("UPDATE users SET vault=vault-$2 WHERE user_id=$1",ctx.author.id,amount); await bot.db.change_balance(ctx.author.id,amount,"vault_withdraw")
    else: await ctx.send("Use `.vault deposit <points>` or `.vault withdraw <points>`."); return
    await ctx.send(embed=brand("Vault",f"{config.E['win']} Vault {action.lower()} complete: **{money(amount)} points**."))

@bot.command()
async def claim(ctx, code: str):
    code=code.upper()
    async with bot.db.pool.acquire() as c:
        async with c.transaction():
            record=await c.fetchrow("SELECT * FROM codes WHERE code=$1 FOR UPDATE",code)
            already=await c.fetchrow("SELECT 1 FROM code_claims WHERE code=$1 AND user_id=$2",code,ctx.author.id)
            if not record or not record['active'] or already or record['uses']>=record['max_uses']: await ctx.send("Invalid, expired, or already claimed code."); return
            await c.execute("INSERT INTO code_claims(code,user_id) VALUES($1,$2)",code,ctx.author.id); await c.execute("UPDATE codes SET uses=uses+1 WHERE code=$1",code)
    await bot.db.change_balance(ctx.author.id,float(record['amount']),"code",code); await ctx.send(embed=brand("Code claimed",f"{config.E['gift']} You received **{money(record['amount'])} points**. Wager 3× your code amount before withdrawing."))

@bot.command()
async def createcode(ctx, code: str, max_users: int, amount: str):
    if not allowed_admin(ctx): await ctx.send("Administrator only."); return
    try: value=parse_amount(amount)
    except ValueError as error: await ctx.send(str(error)); return
    await bot.db.pool.execute("INSERT INTO codes(code,max_uses,amount) VALUES($1,$2,$3) ON CONFLICT(code) DO UPDATE SET max_uses=$2,amount=$3,uses=0,active=TRUE",code.upper(),max_users,value)
    await ctx.send(f"{config.E['win']} Code `{code.upper()}` created.")

@bot.command()
async def freeze(ctx):
    if not allowed_admin(ctx): await ctx.send("Administrator only."); return
    await bot.db.set_setting("frozen","1"); await ctx.send("Games frozen.")
@bot.command()
async def unfreeze(ctx):
    if not allowed_admin(ctx): await ctx.send("Administrator only."); return
    await bot.db.set_setting("frozen","0"); await ctx.send("Games unfrozen.")

@bot.command()
async def ai(ctx, *, question: str):
    await ctx.send(embed=brand("AI", "AI integration needs `OPENAI_API_KEY` before it can answer questions. It will not discuss or influence casino games."))

@bot.command()
async def thread(ctx, action: str="create", member: discord.Member=None):
    if action.lower()=="create":
        created=await ctx.channel.create_thread(name=f"{ctx.author.display_name}'s {config.CASINO_NAME} thread",type=discord.ChannelType.private_thread,invitable=False)
        await created.add_user(ctx.author); await ctx.send(f"Your personal thread: {created.mention}")
    else: await ctx.send("Use `.thread create`. Member management requires running the command inside your private thread.")

@bot.event
async def on_ready(): print(f"Logged in as {bot.user} ({bot.user.id})")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound): return
    if isinstance(error, (commands.MissingRequiredArgument, commands.BadArgument)):
        await ctx.send("Invalid command usage. Use `.help` to see commands."); return
    if isinstance(error, commands.CommandOnCooldown): await ctx.send("Please wait before using that command again."); return
    print(repr(error)); await ctx.send("Something went wrong. Please try again.")

if __name__ == "__main__":
    if not config.TOKEN: raise RuntimeError("DISCORD_TOKEN is missing from Railway variables.")
    if not config.DATABASE_URL: raise RuntimeError("DATABASE_URL is missing from Railway variables.")
    bot.run(config.TOKEN)
