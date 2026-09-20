# ============================================================
# PART 2 — CONFIGURATION + USER STATS
# ============================================================

import os
import asyncio
from decimal import Decimal

import discord
from discord.ext import commands
import asyncpg


# ============================================================
# CONFIGURATION
# ============================================================

NAME = "Cryptobet"

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
DATABASE_URL = os.getenv("DATABASE_URL")

PREFIXES = [".", ","]

MINIMUM_BET = Decimal("20")

POINTS_PER_USD = Decimal("200")

COINFLIP_MULTIPLIER = Decimal("1.96")

GAME_WIN_CHANCE = Decimal("45")


# ============================================================
# INTENTS
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

            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS bot_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
                """
            )

    async def ensure_user(self, user_id):
        async with self.pool.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO users (user_id)
                VALUES ($1)
                ON CONFLICT (user_id) DO NOTHING
                """,
                user_id,
            )

    async def get_user(self, user_id):
        await self.ensure_user(user_id)

        async with self.pool.acquire() as connection:
            return await connection.fetchrow(
                """
                SELECT
                    user_id,
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
                user_id,
            )

    async def get_balance(self, user_id):
        row = await self.get_user(user_id)
        return Decimal(str(row["balance"]))

    async def change_balance(self, user_id, amount):
        amount = Decimal(str(amount))

        await self.ensure_user(user_id)

        async with self.pool.acquire() as connection:
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

    async def add_wagered(self, user_id, amount):
        amount = Decimal(str(amount))

        await self.ensure_user(user_id)

        await self.pool.execute(
            """
            UPDATE users
            SET wagered = wagered + $2
            WHERE user_id = $1
            """,
            user_id,
            amount,
        )

    async def add_won(self, user_id, amount):
        amount = Decimal(str(amount))

        await self.ensure_user(user_id)

        await self.pool.execute(
            """
            UPDATE users
            SET won = won + $2
            WHERE user_id = $1
            """,
            user_id,
            amount,
        )

    async def add_lost(self, user_id, amount):
        amount = Decimal(str(amount))

        await self.ensure_user(user_id)

        await self.pool.execute(
            """
            UPDATE users
            SET lost = lost + $2
            WHERE user_id = $1
            """,
            user_id,
            amount,
        )

    async def add_deposited(self, user_id, amount):
        amount = Decimal(str(amount))

        await self.ensure_user(user_id)

        await self.pool.execute(
            """
            UPDATE users
            SET deposited = deposited + $2
            WHERE user_id = $1
            """,
            user_id,
            amount,
        )

    async def add_withdrawn(self, user_id, amount):
        amount = Decimal(str(amount))

        await self.ensure_user(user_id)

        await self.pool.execute(
            """
            UPDATE users
            SET withdrawn = withdrawn + $2
            WHERE user_id = $1
            """,
            user_id,
            amount,
        )

    async def set_setting(self, key, value):
        await self.pool.execute(
            """
            INSERT INTO bot_settings (key, value)
            VALUES ($1, $2)
            ON CONFLICT (key)
            DO UPDATE SET value = EXCLUDED.value
            """,
            key,
            str(value),
        )

    async def get_setting(self, key, default=None):
        row = await self.pool.fetchrow(
            """
            SELECT value
            FROM bot_settings
            WHERE key = $1
            """,
            key,
        )

        if row is None:
            return default

        return row["value"]


bot.db = Database(DATABASE_URL)


# ============================================================
# EMBED HELPER
# ============================================================

def make_embed(title, description=None):
    return discord.Embed(
        title=title,
        description=description or "",
    )


# ============================================================
# BOT READY
# ============================================================

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    print(f"Bot ID: {bot.user.id}")
    print(f"{NAME} is online.")


# ============================================================
# HELP
# ============================================================

@bot.command(name="help")
async def help_command(ctx):

    embed = make_embed(
        f"{NAME} — Help",
        "Casino commands will be added as we build each part.",
    )

    embed.add_field(
        name="General",
        value=(
            "`.help`\n"
            "`.bal`\n"
            "`.balance`\n"
            "`.b`\n"
            "`,help`\n"
            "`,bal`"
        ),
        inline=False,
    )

    embed.add_field(
        name="Game Settings",
        value=(
            f"Minimum Bet: **{MINIMUM_BET:,.0f} Points**\n"
            f"Points per $1: **{POINTS_PER_USD:,.0f}**\n"
            f"Game Win Chance: **{GAME_WIN_CHANCE}%**"
        ),
        inline=False,
    )

    await ctx.send(embed=embed)


# ============================================================
# BALANCE
# ============================================================

@bot.command(name="bal", aliases=["balance", "b"])
async def balance_command(ctx):

    balance = await bot.db.get_balance(ctx.author.id)

    embed = make_embed(
        f"{ctx.author.display_name} — Balance",
        f"**{balance:,.2f} Points**",
    )

    await ctx.send(embed=embed)


# ============================================================
# STATS
# ============================================================

@bot.command(name="stats")
async def stats_command(ctx):

    user = await bot.db.get_user(ctx.author.id)

    embed = make_embed(
        f"{ctx.author.display_name} — Stats"
    )

    embed.add_field(
        name="Balance",
        value=f"{Decimal(str(user['balance'])):,.2f} Points",
        inline=False,
    )

    embed.add_field(
        name="Wagered",
        value=f"{Decimal(str(user['wagered'])):,.2f} Points",
        inline=True,
    )

    embed.add_field(
        name="Won",
        value=f"{Decimal(str(user['won'])):,.2f} Points",
        inline=True,
    )

    embed.add_field(
        name="Lost",
        value=f"{Decimal(str(user['lost'])):,.2f} Points",
        inline=True,
    )

    embed.add_field(
        name="Deposited",
        value=f"{Decimal(str(user['deposited'])):,.2f} Points",
        inline=True,
    )

    embed.add_field(
        name="Withdrawn",
        value=f"{Decimal(str(user['withdrawn'])):,.2f} Points",
        inline=True,
    )

    await ctx.send(embed=embed)


# ============================================================
# ERROR HANDLER
# ============================================================

@bot.event
async def on_command_error(ctx, error):

    if isinstance(error, commands.CommandNotFound):
        return

    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(
            embed=make_embed(
                "Invalid Usage",
                "You are missing a required argument.",
            )
        )
        return

    if isinstance(error, commands.MissingPermissions):
        await ctx.send(
            embed=make_embed(
                "Permission Denied",
                "You do not have permission to use this command.",
            )
        )
        return

    print(
        f"Command error in "
        f"{ctx.command}: "
        f"{repr(error)}"
    )

    await ctx.send(
        embed=make_embed(
            "Command Error",
            "An error occurred while processing this command.",
        )
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
        await bot.start(BOT_TOKEN)

    finally:
        await bot.db.close()


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    asyncio.run(main())
