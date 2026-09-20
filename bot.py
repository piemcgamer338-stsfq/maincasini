# ============================================================
# CRYPTOBET
# PART 1 — FOUNDATION + COMPLETE HELP UI
# ============================================================

import os
import asyncio

import asyncpg
import discord
from discord.ext import commands


# ============================================================
# BASIC CONFIG
# ============================================================

NAME = "Cryptobet"

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
DATABASE_URL = os.getenv("DATABASE_URL")

PREFIXES = [".", ","]


# ============================================================
# DISCORD INTENTS
# ============================================================

intents = discord.Intents.default()

intents.guilds = True
intents.members = True
intents.messages = True
intents.message_content = True


# ============================================================
# BOT
# ============================================================

bot = commands.Bot(
    command_prefix=PREFIXES,
    intents=intents,
    help_command=None,
)


# ============================================================
# DATABASE
# ============================================================

class Database:

    def __init__(self, url):
        self.url = url
        self.pool = None

    async def connect(self):

        if not self.url:
            raise RuntimeError(
                "DATABASE_URL is missing from Railway environment variables."
            )

        self.pool = await asyncpg.create_pool(
            self.url,
            min_size=1,
            max_size=5,
        )

        async with self.pool.acquire() as connection:
            await connection.execute("SELECT 1")

        print("PostgreSQL connected.")

    async def close(self):

        if self.pool:
            await self.pool.close()

    async def create_tables(self):

        async with self.pool.acquire() as connection:

            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    balance NUMERIC(30, 8) NOT NULL DEFAULT 0,
                    wagered NUMERIC(30, 8) NOT NULL DEFAULT 0,
                    won NUMERIC(30, 8) NOT NULL DEFAULT 0,
                    lost NUMERIC(30, 8) NOT NULL DEFAULT 0,
                    deposited NUMERIC(30, 8) NOT NULL DEFAULT 0,
                    withdrawn NUMERIC(30, 8) NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )


bot.db = Database(DATABASE_URL)


# ============================================================
# EMBED HELPER
# ============================================================

def make_embed(title, description=""):

    return discord.Embed(
        title=title,
        description=description,
    )


# ============================================================
# HELP CATEGORY DATA
#
# These are the commands the finished bot will contain.
# The commands themselves will be added in later parts.
# ============================================================

HELP_CATEGORIES = {

    "General": [
        ("help", "Open the casino help menu"),
        ("bal", "View your balance"),
        ("stats", "View your casino statistics"),
        ("whois", "View another user's profile"),
        ("leaderboard", "View the casino leaderboard"),
    ],

    "Games": [
        ("blackjack", "Play Blackjack"),
        ("mines", "Play Mines"),
        ("hilo", "Play Hi-Lo"),
        ("coinflip", "Play Coinflip"),
        ("crazydice", "Play Crazy Dice"),
        ("baccarat", "Play Baccarat"),
        ("market", "Play Market"),
    ],

    "Rewards": [
        ("daily", "Claim your daily reward"),
        ("weekly", "Claim your weekly reward"),
        ("monthly", "Claim your monthly reward"),
        ("claim", "View available rewards"),
    ],

    "Money": [
        ("deposit", "Deposit cryptocurrency"),
        ("withdraw", "Withdraw cryptocurrency"),
        ("vault", "Manage your vault"),
        ("tip", "Tip another user"),
    ],

    "Social": [
        ("rain", "Create a point rain"),
        ("rainend", "End an active rain"),
        ("sos", "Request help"),
        ("thread", "Manage a private thread"),
    ],

    "Admin": [
        ("add", "Add points to a user"),
        ("addbal", "Add points to a user"),
        ("removebal", "Remove points from a user"),
        ("resetbal", "Reset a user's balance"),
        ("winlog", "Set the game win-log channel"),
        ("commands", "View administrative commands"),
    ],
}


# ============================================================
# HELP SELECT MENU
# ============================================================

class HelpSelect(discord.ui.Select):

    def __init__(self):

        options = [
            discord.SelectOption(
                label="General",
                description="Balance, stats and user commands",
                value="General",
            ),
            discord.SelectOption(
                label="Games",
                description="Casino games",
                value="Games",
            ),
            discord.SelectOption(
                label="Rewards",
                description="Daily, weekly and monthly rewards",
                value="Rewards",
            ),
            discord.SelectOption(
                label="Money",
                description="Deposits, withdrawals, vault and tips",
                value="Money",
            ),
            discord.SelectOption(
                label="Social",
                description="Rain, SOS and threads",
                value="Social",
            ),
            discord.SelectOption(
                label="Admin",
                description="Owner and administration commands",
                value="Admin",
            ),
        ]

        super().__init__(
            placeholder="Select a category...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):

        category = self.values[0]

        commands_list = HELP_CATEGORIES.get(
            category,
            [],
        )

        lines = []

        for command_name, description in commands_list:
            lines.append(
                f"`.{command_name}` — {description}"
            )

        embed = make_embed(
            f"{NAME} — {category}",
            "\n".join(lines),
        )

        embed.set_footer(
            text="Use the menu below to switch categories."
        )

        await interaction.response.edit_message(
            embed=embed,
            view=self.view,
        )


# ============================================================
# HELP VIEW
# ============================================================

class HelpView(discord.ui.View):

    def __init__(self):

        super().__init__(timeout=180)

        self.add_item(
            HelpSelect()
        )


# ============================================================
# HELP COMMAND
# ============================================================

@bot.command(
    name="help",
)
async def help_command(ctx):

    embed = make_embed(
        f"{NAME} — Help",
        "Select a category below to view the available commands.",
    )

    embed.add_field(
        name="Categories",
        value=(
            "General\n"
            "Games\n"
            "Rewards\n"
            "Money\n"
            "Social\n"
            "Admin"
        ),
        inline=False,
    )

    embed.set_footer(
        text="Select a category below."
    )

    await ctx.send(
        embed=embed,
        view=HelpView(),
    )


# ============================================================
# BASIC TEST COMMAND
# ============================================================

@bot.command(
    name="ping",
)
async def ping_command(ctx):

    await ctx.send(
        embed=make_embed(
            f"{NAME} — Ping",
            f"Bot latency: **{round(bot.latency * 1000)}ms**",
        )
    )


# ============================================================
# ERROR HANDLER
# ============================================================

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
            embed=make_embed(
                "Invalid Usage",
                "A required argument is missing.",
            )
        )
        return

    if isinstance(
        error,
        commands.BadArgument,
    ):
        await ctx.send(
            embed=make_embed(
                "Invalid Argument",
                "One of the arguments you entered is invalid.",
            )
        )
        return

    print(
        f"Command error in {ctx.command}: "
        f"{repr(error)}"
    )

    await ctx.send(
        embed=make_embed(
            "Command Error",
            "An unexpected error occurred while processing this command.",
        )
    )


# ============================================================
# READY
# ============================================================

@bot.event
async def on_ready():

    print(
        f"Logged in as {bot.user}"
    )

    print(
        f"Bot ID: {bot.user.id}"
    )

    print(
        f"{NAME} is online."
    )


# ============================================================
# STARTUP
# ============================================================

async def main():

    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN is missing from Railway environment variables."
        )

    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is missing from Railway environment variables."
        )

    await bot.db.connect()

    await bot.db.create_tables()

    try:

        await bot.start(
            BOT_TOKEN
        )

    finally:

        await bot.db.close()


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    asyncio.run(
        main()
    )
# ============================================================
# PART 2 — ECONOMY FOUNDATION
# ============================================================

from decimal import Decimal, InvalidOperation


# ============================================================
# ECONOMY SETTINGS
# ============================================================

POINTS_PER_CENT = Decimal("2")
POINTS_PER_USD = Decimal("200")

MINIMUM_BET = Decimal("20")


# ============================================================
# DATABASE ECONOMY METHODS
# ============================================================

async def ensure_user(user_id: int):

    async with bot.db.pool.acquire() as connection:

        await connection.execute(
            """
            INSERT INTO users (user_id)
            VALUES ($1)
            ON CONFLICT (user_id) DO NOTHING
            """,
            user_id,
        )


async def get_balance(user_id: int) -> Decimal:

    await ensure_user(user_id)

    async with bot.db.pool.acquire() as connection:

        row = await connection.fetchrow(
            """
            SELECT balance
            FROM users
            WHERE user_id = $1
            """,
            user_id,
        )

    return Decimal(str(row["balance"]))


async def change_balance(
    user_id: int,
    amount: Decimal,
) -> Decimal:

    await ensure_user(user_id)

    amount = Decimal(str(amount))

    async with bot.db.pool.acquire() as connection:

        row = await connection.fetchrow(
            """
            UPDATE users
            SET balance = balance + $2
            WHERE user_id = $1
            RETURNING balance
            """,
            user_id,
            amount,
        )

    return Decimal(str(row["balance"]))


async def add_wagered(
    user_id: int,
    amount: Decimal,
):

    await ensure_user(user_id)

    amount = Decimal(str(amount))

    async with bot.db.pool.acquire() as connection:

        await connection.execute(
            """
            UPDATE users
            SET wagered = wagered + $2
            WHERE user_id = $1
            """,
            user_id,
            amount,
        )


async def add_won(
    user_id: int,
    amount: Decimal,
):

    await ensure_user(user_id)

    amount = Decimal(str(amount))

    async with bot.db.pool.acquire() as connection:

        await connection.execute(
            """
            UPDATE users
            SET won = won + $2
            WHERE user_id = $1
            """,
            user_id,
            amount,
        )


async def add_lost(
    user_id: int,
    amount: Decimal,
):

    await ensure_user(user_id)

    amount = Decimal(str(amount))

    async with bot.db.pool.acquire() as connection:

        await connection.execute(
            """
            UPDATE users
            SET lost = lost + $2
            WHERE user_id = $1
            """,
            user_id,
            amount,
        )


async def add_deposited(
    user_id: int,
    amount: Decimal,
):

    await ensure_user(user_id)

    amount = Decimal(str(amount))

    async with bot.db.pool.acquire() as connection:

        await connection.execute(
            """
            UPDATE users
            SET deposited = deposited + $2
            WHERE user_id = $1
            """,
            user_id,
            amount,
        )


async def add_withdrawn(
    user_id: int,
    amount: Decimal,
):

    await ensure_user(user_id)

    amount = Decimal(str(amount))

    async with bot.db.pool.acquire() as connection:

        await connection.execute(
            """
            UPDATE users
            SET withdrawn = withdrawn + $2
            WHERE user_id = $1
            """,
            user_id,
            amount,
        )


# ============================================================
# BALANCE COMMAND
# ============================================================

@bot.command(
    name="bal",
    aliases=["balance", "b"],
)
async def balance_command(ctx):

    balance = await get_balance(
        ctx.author.id
    )

    embed = make_embed(
        f"{NAME} — Balance",
        (
            f"**{balance:,.2f} Points**\n\n"
            f"Minimum bet: **{MINIMUM_BET:,.0f} Points**"
        ),
    )

    await ctx.send(
        embed=embed
    )


# ============================================================
# STATS COMMAND
# ============================================================

@bot.command(
    name="stats",
)
async def stats_command(ctx):

    await ensure_user(
        ctx.author.id
    )

    async with bot.db.pool.acquire() as connection:

        user = await connection.fetchrow(
            """
            SELECT
                balance,
                wagered,
                won,
                lost,
                deposited,
                withdrawn,
                created_at
            FROM users
            WHERE user_id = $1
            """,
            ctx.author.id,
        )

    balance = Decimal(str(user["balance"]))
    wagered = Decimal(str(user["wagered"]))
    won = Decimal(str(user["won"]))
    lost = Decimal(str(user["lost"]))
    deposited = Decimal(str(user["deposited"]))
    withdrawn = Decimal(str(user["withdrawn"]))

    embed = make_embed(
        f"{NAME} — {ctx.author.display_name}",
        "Casino statistics",
    )

    embed.add_field(
        name="Balance",
        value=f"{balance:,.2f} Points",
        inline=True,
    )

    embed.add_field(
        name="Wagered",
        value=f"{wagered:,.2f} Points",
        inline=True,
    )

    embed.add_field(
        name="Won",
        value=f"{won:,.2f} Points",
        inline=True,
    )

    embed.add_field(
        name="Lost",
        value=f"{lost:,.2f} Points",
        inline=True,
    )

    embed.add_field(
        name="Deposited",
        value=f"{deposited:,.2f} Points",
        inline=True,
    )

    embed.add_field(
        name="Withdrawn",
        value=f"{withdrawn:,.2f} Points",
        inline=True,
    )

    embed.set_footer(
        text="All amounts are displayed in Points."
    )

    await ctx.send(
        embed=embed
    )


# ============================================================
# INTERNAL BET VALIDATION
# ============================================================

def parse_points(
    value: str,
) -> Decimal:

    value = value.strip()

    try:

        amount = Decimal(value)

    except InvalidOperation:

        raise ValueError(
            "Invalid point amount."
        )

    if not amount.is_finite():

        raise ValueError(
            "Invalid point amount."
        )

    if amount <= 0:

        raise ValueError(
            "Amount must be greater than zero."
        )

    return amount


async def validate_bet(
    user_id: int,
    amount: Decimal,
):

    amount = Decimal(str(amount))

    if amount < MINIMUM_BET:

        return False, (
            f"Minimum bet is "
            f"**{MINIMUM_BET:,.0f} Points**."
        )

    balance = await get_balance(
        user_id
    )

    if balance < amount:

        return False, (
            f"You only have "
            f"**{balance:,.2f} Points**."
        )

    return True, None


# ============================================================
# INTERNAL BET DEDUCTION
# ============================================================

async def take_bet(
    user_id: int,
    amount: Decimal,
):

    amount = Decimal(str(amount))

    valid, error_message = await validate_bet(
        user_id,
        amount,
    )

    if not valid:

        return False, error_message

    new_balance = await change_balance(
        user_id,
        -amount,
    )

    await add_wagered(
        user_id,
        amount,
    )

    return True, new_balance


# ============================================================
# INTERNAL PAYOUT
# ============================================================

async def payout(
    user_id: int,
    amount: Decimal,
):

    amount = Decimal(str(amount))

    new_balance = await change_balance(
        user_id,
        amount,
    )

    await add_won(
        user_id,
        amount,
    )

    return new_balance
