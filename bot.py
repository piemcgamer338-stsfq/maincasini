# ============================================================
# PART 1 — BOT FOUNDATION
# ============================================================

import os
import asyncio

import discord
from discord.ext import commands
import asyncpg


# ============================================================
# CONFIG
# ============================================================

NAME = "Cryptobet"

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
DATABASE_URL = os.getenv("DATABASE_URL")

PREFIXES = [".", ","]


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
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
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

    async def get_balance(self, user_id):
        await self.ensure_user(user_id)

        async with self.pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT balance
                FROM users
                WHERE user_id = $1
                """,
                user_id,
            )

        return row["balance"]


bot.db = Database(DATABASE_URL)


# ============================================================
# EMBED HELPERS
# ============================================================

def make_embed(title, description=None):
    return discord.Embed(
        title=title,
        description=description or "",
    )


# ============================================================
# EVENTS
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
        "Select a command category from the commands that will be added in the next parts.",
    )

    embed.add_field(
        name="Current Commands",
        value=(
            "`.help`\n"
            "`.bal`\n"
            "`,help`\n"
            "`,bal`"
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

    print(f"Command error in {ctx.command}: {repr(error)}")

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
