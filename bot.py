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
    "tails": "https://media.discordapp.net/attachments/1524764567916384256/1549963005104758784/image.png?ex=6aac9b09&is=6aab4989&hm=92dfb2bcab7b6d727648983b4cee345281fcb15d46dbd04b60036fd208b386c5&=&format=webp&quality=lossless",
    "heads": "https://media.discordapp.net/attachments/1524764567916384256/1549963108552802344/image.png?ex=6aac9b22&is=6aab49a2&hm=3e1091d9ee25f60c010281eac36815b31c633ff2db0c3971a723c11f8a5c3368&=&format=webp&quality=lossless",
}


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




def limbo_image(crash: float, target: float, won: bool) -> discord.File:
    canvas = Image.new("RGB", (1200, 620), "#0b1020")
    draw = ImageDraw.Draw(canvas)
    for x in range(0, 1200, 80):
        draw.line((x, 0, x, 620), fill="#1c2940", width=2)
    for y in range(0, 620, 80):
        draw.line((0, y, 1200, y), fill="#1c2940", width=2)
    title = "LIMBO — WIN" if won else "LIMBO — LOST"
    draw.text((55, 45), title, fill="#57f287" if won else "#ed4245", font=_font(66, True))
    draw.text((55, 190), f"{crash:.2f}x", fill="#ffffff", font=_font(150, True))
    draw.text((60, 385), f"Target: {target:.2f}x", fill="#d9e2f2", font=_font(54, True))
    draw.text((60, 475), "The round has ended", fill="#9fb0c8", font=_font(38))
    return image_file(canvas, "limbo.png")


def market_image(result: str) -> discord.File:
    canvas = Image.new("RGB", (1000, 500), "#111318")
    draw = ImageDraw.Draw(canvas)
    font = _font(34, True)
    for x in range(40, 1000, 80): draw.line((x, 35, x, 450), fill="#252a33")
    for y in range(50, 460, 70): draw.line((35, y, 965, y), fill="#252a33")
    points=[]; value=330
    direction = -1 if result == "up" else 1
    for x in range(50, 940, 55):
        value += direction * random.randint(8, 27) + random.randint(-12, 12)
        value=max(60,min(430,value)); points.append((x,value))
    draw.line(points, fill="#57f287" if result == "up" else "#ed4245", width=6)
    draw.text((45, 18), f"MARKET CLOSED {result.upper()}", fill="#ffffff", font=font)
    return image_file(canvas, "market.png")


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
    "Games": "`.mines <bet> [mines]` — Find diamonds and cash out\n`.bj <bet>` / `.blackjack <bet>` — House blackjack\n`.cf <bet> [h/t/r]` — Coinflip\n`.hilo <bet>` — Higher or lower\n`.limbo <bet> <multiplier>` — Beat the crash point\n`.market <bet>` — Pick up or down",
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

import asyncio
import random
import discord
from discord.ext import commands



import random
import discord
from discord.ext import commands


# =========================================================
# SOS - SPLIT OR STEAL
# =========================================================

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


class MarketView(OwnerView):
    def __init__(self, owner, bet): super().__init__(owner.id, timeout=45); self.bet=bet; self.finished=False
    async def resolve(self, interaction, pick):
        if self.finished: return
        self.finished=True; result=random.choice(["up","down"]); payout=round(self.bet*1.97,4) if pick==result else 0
        await bot.db.record_game(self.owner_id,self.bet,payout,"market")
        for item in self.children: item.disabled=True
        embed=brand("Market — Won" if payout else "Market — Lost",f"You chose **{pick.upper()}**. Market closed **{result.upper()}**.\n{'You won **'+money(payout)+' points**.' if payout else 'You lost **'+money(self.bet)+' points**.'}",0x57F287 if payout else 0xED4245)
        embed.set_image(url="attachment://market.png")
        await interaction.response.edit_message(embed=embed,attachments=[market_image(result)],view=self)
    @discord.ui.button(label="Up", style=discord.ButtonStyle.success, emoji=config.E["graph"])
    async def up(self, interaction, button): await self.resolve(interaction,"up")
    @discord.ui.button(label="Down", style=discord.ButtonStyle.danger)
    async def down(self, interaction, button): await self.resolve(interaction,"down")




@bot.command(aliases=["hb", "housebal"])
async def housebalance(ctx):
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

    if not await bot.game_allowed(ctx):
        return

    # -----------------------------------------------------
    # PARSE BET
    # -----------------------------------------------------

    try:
        amount = parse_amount(bet)

    except ValueError as error:
        await ctx.send(str(error))
        return

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

    if not await bot.db.change_balance(
        ctx.author.id,
        -amount,
        "coinflip_bet"
    ):
        await ctx.send(
            "Insufficient balance."
        )
        return

    # -----------------------------------------------------
    # PLAYER PICK
    # -----------------------------------------------------

    if choice in ("h", "heads"):
        pick = "heads"

    elif choice in ("t", "tails"):
        pick = "tails"

    else:
        pick = random.choice([
            "heads",
            "tails"
        ])

    # -----------------------------------------------------
    # FLIPPING MESSAGE
    # -----------------------------------------------------

    flipping_embed = brand(
        "🪙 Coinflip",
        (
            f"{ctx.author.mention} flipped a coin...\n\n"
            f"Bet: **{money(amount)} points**\n"
            f"Choice: **{pick.title()}**"
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

    result = random.choice([
        "heads",
        "tails"
    ])

    # -----------------------------------------------------
    # PAYOUT
    # -----------------------------------------------------

    if pick == result:

        payout = round(
            amount * 1.92,
            4
        )

        await bot.db.change_balance(
            ctx.author.id,
            payout,
            "coinflip_win"
        )

    else:

        payout = 0

    # -----------------------------------------------------
    # RECORD GAME
    # -----------------------------------------------------

    await bot.db.record_game(
        ctx.author.id,
        amount,
        payout,
        "coinflip"
    )

    # -----------------------------------------------------
    # RESULT EMBED
    # -----------------------------------------------------

    if payout > 0:

        embed = brand(
            "You Won!",
            (
                f"You bet on **{pick.title()}** "
                f"and won **{money(payout)} points!** 🎉"
            ),
            0x57F287
        )

    else:

        embed = brand(
            "You Lost!",
            (
                f"You bet on **{pick.title()}** "
                f"and lost **{money(amount)} points.**"
            ),
            0xED4245
        )

    # -----------------------------------------------------
    # USE HEADS/TAILS IMAGE
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
    if not await bot.game_allowed(ctx): return
    try: amount=parse_amount(bet)
    except ValueError as error: await ctx.send(str(error)); return
    if not await bot.db.change_balance(ctx.author.id,-amount,"blackjack_bet"): await ctx.send("Insufficient balance."); return
    view=BlackjackView(ctx.author,amount); embed,table=view.embed_and_file(); await ctx.send(embed=embed,file=table,view=view)

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
        amount = parse_amount(bet)

    except ValueError as error:
        await ctx.send(str(error))
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

@bot.command()
async def limbo(ctx, bet: str, target: float):
    if not await bot.game_allowed(ctx): return
    try: amount=parse_amount(bet)
    except ValueError as error: await ctx.send(str(error)); return
    if not 1.01<=target<=1000: await ctx.send("Multiplier must be between 1.01x and 1000x."); return
    if not await bot.db.change_balance(ctx.author.id,-amount,"limbo_bet"): await ctx.send("Insufficient balance."); return
    crash=round(1/(1-random.random()*.99),2); payout=round(amount*target*.98,4) if crash>=target else 0
    await bot.db.record_game(ctx.author.id,amount,payout,"limbo"); await ctx.send(embed=brand("Limbo — Won" if payout else "Limbo — Lost",f"Crashed at **{crash:.2f}x** • Target: **{target:.2f}x**\n{'Won **'+money(payout)+' points**.' if payout else 'Your bet did not reach the target.'}",0x57F287 if payout else 0xED4245))

# =========================================================
# HILO CARD IMAGE
# =========================================================

def card_face_image(card: str, filename="hilo_card.png") -> discord.File:
    # Large canvas
    canvas = Image.new(
        "RGB",
        (900, 520),
        "#101522"
    )

    draw = ImageDraw.Draw(canvas)

    # -----------------------------------------------------
    # CARD
    # -----------------------------------------------------

    # Almost full-size playing card
    card_left = 90
    card_top = 25
    card_right = 810
    card_bottom = 495

    draw.rounded_rectangle(
        (
            card_left,
            card_top,
            card_right,
            card_bottom
        ),
        radius=42,
        fill="#ffffff",
        outline="#d8b45c",
        width=10
    )

    # -----------------------------------------------------
    # CARD DATA
    # -----------------------------------------------------

    rank = card[:-1]
    suit = card[-1]

    # Red suits
    if suit in ("♥", "♦"):
        ink = "#d62828"
    else:
        ink = "#111111"

    # -----------------------------------------------------
    # TOP LEFT
    # -----------------------------------------------------

    draw.text(
        (135, 55),
        rank,
        fill=ink,
        font=_font(115, True)
    )

    draw.text(
        (145, 145),
        suit,
        fill=ink,
        font=_font(125, True)
    )

    # -----------------------------------------------------
    # CENTER SUIT
    # -----------------------------------------------------

    center_font = _font(190, True)

    bbox = draw.textbbox(
        (0, 0),
        suit,
        font=center_font
    )

    suit_width = bbox[2] - bbox[0]
    suit_height = bbox[3] - bbox[1]

    draw.text(
        (
            450 - suit_width // 2,
            190 - suit_height // 2
        ),
        suit,
        fill=ink,
        font=center_font
    )

    # -----------------------------------------------------
    # BOTTOM RIGHT
    # -----------------------------------------------------

    bottom_rank_font = _font(115, True)
    bottom_suit_font = _font(125, True)

    # Rank
    bbox = draw.textbbox(
        (0, 0),
        rank,
        font=bottom_rank_font
    )

    rank_width = bbox[2] - bbox[0]

    draw.text(
        (
            765 - rank_width,
            330
        ),
        rank,
        fill=ink,
        font=bottom_rank_font
    )

    # Suit
    bbox = draw.textbbox(
        (0, 0),
        suit,
        font=bottom_suit_font
    )

    suit_width = bbox[2] - bbox[0]

    draw.text(
        (
            765 - suit_width,
            400
        ),
        suit,
        fill=ink,
        font=bottom_suit_font
    )

    # -----------------------------------------------------
    # EXPORT
    # -----------------------------------------------------

    return image_file(
        canvas,
        filename
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
        self.current = random.randint(2, 14)
        self.rounds = 0
        self.finished = False

    # -----------------------------------------------------
    # CARD RANK
    # -----------------------------------------------------

    def rank(self, value):
        return {
            11: "J",
            12: "Q",
            13: "K",
            14: "A"
        }.get(
            value,
            str(value)
        )

    # -----------------------------------------------------
    # GAME EMBED
    # -----------------------------------------------------

    def game_embed(self):

        multiplier = 1 + self.rounds * 0.14

        embed = brand(
            "HiLo",
            (
                f"**Current Card:** "
                f"{self.rank(self.current)}\n"

                f"**Next Card:** ??\n\n"

                f"Higher or Lower? • "
                f"Multiplier: **{multiplier:.2f}x**"
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
        high
    ):

        if self.finished:
            return

        next_card = random.randint(
            2,
            14
        )

        # Higher
        if high:
            won = next_card > self.current

        # Lower
        else:
            won = next_card < self.current

        # =================================================
        # LOST
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
                    f"Current: **{self.rank(self.current)}**\n"
                    f"Next: **{self.rank(next_card)}**\n\n"
                    f"You lost **{money(self.bet)} points**."
                ),
                0xED4245
            )

            embed.set_image(
                url="attachment://hilo_card.png"
            )

            await interaction.response.edit_message(
                embed=embed,
                attachments=[
                    card_face_image(
                        self.rank(next_card) + "♠"
                    )
                ],
                view=self
            )

            return

        # =================================================
        # WON ROUND
        # =================================================

        self.rounds += 1
        self.current = next_card

        # =================================================
        # COMPLETED GAME
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
                    f"{config.E['win']} "
                    f"You won **{money(payout)} points**."
                ),
                0x57F287
            )

            embed.set_image(
                url="attachment://hilo_card.png"
            )

            await interaction.response.edit_message(
                embed=embed,
                attachments=[
                    card_face_image(
                        self.rank(next_card) + "♠"
                    )
                ],
                view=self
            )

            return

        # =================================================
        # CONTINUE
        # =================================================

        await interaction.response.edit_message(
            embed=self.game_embed(),
            attachments=[
                card_face_image(
                    self.rank(self.current) + "♠"
                )
            ],
            view=self
        )

    # -----------------------------------------------------
    # HIGHER BUTTON
    # -----------------------------------------------------

    @discord.ui.button(
        label="Higher",
        style=discord.ButtonStyle.success
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
    # LOWER BUTTON
    # -----------------------------------------------------

    @discord.ui.button(
        label="Lower",
        style=discord.ButtonStyle.primary
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
    # CHECK BET
    # -----------------------------------------------------

    if amount <= 0:

        await ctx.send(
            "Bet must be greater than zero."
        )

        return

    # -----------------------------------------------------
    # REMOVE BALANCE
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
    # SEND GAME
    # -----------------------------------------------------

    await ctx.send(
        embed=view.game_embed(),
        file=card_face_image(
            view.rank(view.current) + "♠"
        ),
        view=view
    )

@bot.command()
async def market(ctx, bet: str):
    if not await bot.game_allowed(ctx): return
    try: amount=parse_amount(bet)
    except ValueError as error: await ctx.send(str(error)); return
    if not await bot.db.change_balance(ctx.author.id,-amount,"market_bet"): await ctx.send("Insufficient balance."); return
    view=MarketView(ctx.author,amount)
    await ctx.send(embed=brand("Market",f"Bet: **{money(amount)} points**\nChoose whether the chart closes up or down."),view=view)

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
