import os
import asyncio
import discord

from discord.ext import commands


# =========================================================
# BASIC SETTINGS
# =========================================================

TOKEN = os.getenv("BOT_TOKEN")

PREFIXES = [".", ","]

if not TOKEN:
    raise RuntimeError("BOT_TOKEN is not set in Railway Variables.")


# =========================================================
# INTENTS
# =========================================================

intents = discord.Intents.default()

intents.guilds = True
intents.members = True
intents.messages = True
intents.message_content = True


# =========================================================
# BOT
# =========================================================

class CasinoBot(commands.Bot):

    def __init__(self):
        super().__init__(
            command_prefix=self.get_prefix,
            intents=intents,
            help_command=None,
            case_insensitive=True,
            strip_after_prefix=True
        )

    async def get_prefix(self, bot, message):
        return PREFIXES

    async def setup_hook(self):
        """
        Load all bot modules.

        These modules will be created in the next steps.
        """

        extensions = [
            "config",
            "database",
            "games",
            "crypto",
            "ai",
            "images",
        ]

        for extension in extensions:
            try:
                module = __import__(extension)

                if hasattr(module, "setup"):
                    result = module.setup(self)

                    if asyncio.iscoroutine(result):
                        await result

            except ModuleNotFoundError:
                # During the file-by-file setup, some modules
                # may not exist yet.
                continue

            except Exception as error:
                print(
                    f"[MODULE ERROR] {extension}: "
                    f"{type(error).__name__}: {error}"
                )

    async def on_ready(self):
        print("=" * 50)
        print("Casino bot is starting...")
        print(f"Logged in as: {self.user}")
        print(f"Bot ID: {self.user.id}")
        print(f"Servers: {len(self.guilds)}")
        print("=" * 50)

        await self.change_presence(
            activity=discord.Game(
                name="Casino"
            )
        )


bot = CasinoBot()


# =========================================================
# GLOBAL ERROR HANDLER
# =========================================================

@bot.event
async def on_command_error(ctx, error):

    if isinstance(error, commands.CommandNotFound):
        return

    if isinstance(error, commands.MissingRequiredArgument):
        embed = discord.Embed(
            title="Missing Information",
            description=(
                "You are missing a required argument.\n\n"
                f"Use `{ctx.prefix}help {ctx.command.name}` "
                "to see how to use this command."
            )
        )

        await ctx.reply(
            embed=embed,
            mention_author=False
        )
        return

    if isinstance(error, commands.BadArgument):
        embed = discord.Embed(
            title="Invalid Argument",
            description=(
                "One or more arguments are invalid.\n\n"
                f"Use `{ctx.prefix}help {ctx.command.name}` "
                "to see the correct format."
            )
        )

        await ctx.reply(
            embed=embed,
            mention_author=False
        )
        return

    if isinstance(error, commands.CheckFailure):
        embed = discord.Embed(
            title="Permission Denied",
            description="You do not have permission to use this command."
        )

        await ctx.reply(
            embed=embed,
            mention_author=False
        )
        return

    if isinstance(error, commands.CommandOnCooldown):
        embed = discord.Embed(
            title="Command On Cooldown",
            description=(
                f"Please wait **{error.retry_after:.1f} seconds** "
                "before using this command again."
            )
        )

        await ctx.reply(
            embed=embed,
            mention_author=False
        )
        return

    print(
        f"[COMMAND ERROR] "
        f"{ctx.author} | "
        f"{ctx.command} | "
        f"{type(error).__name__}: {error}"
    )

    embed = discord.Embed(
        title="Something Went Wrong",
        description=(
            "The command could not be completed.\n"
            "Please try again."
        )
    )

    try:
        await ctx.reply(
            embed=embed,
            mention_author=False
        )
    except discord.HTTPException:
        pass


# =========================================================
# BASIC COMMANDS
# =========================================================

@bot.command(
    name="ping",
    aliases=["p"]
)
async def ping(ctx):
    latency = round(bot.latency * 1000)

    embed = discord.Embed(
        title="Pong",
        description=f"Latency: **{latency}ms**"
    )

    await ctx.reply(
        embed=embed,
        mention_author=False
    )


@bot.command(
    name="help"
)
async def help_command(ctx, command_name: str = None):

    # The complete interactive help system will be
    # connected from the configuration/help system later.

    if command_name:

        command = bot.get_command(command_name)

        if command is None:
            embed = discord.Embed(
                title="Command Not Found",
                description=(
                    f"No command named `{command_name}` was found."
                )
            )

            await ctx.reply(
                embed=embed,
                mention_author=False
            )
            return

        description = command.help or "No description available."

        embed = discord.Embed(
            title=f"Help — {command.name}",
            description=description
        )

        if command.aliases:
            embed.add_field(
                name="Aliases",
                value=", ".join(
                    f"`{alias}`"
                    for alias in command.aliases
                ),
                inline=False
            )

        await ctx.reply(
            embed=embed,
            mention_author=False
        )
        return

    embed = discord.Embed(
        title="Help",
        description=(
            "Select a category below to view the available commands.\n\n"
            "`0.01$ = 2 Points`"
        )
    )

    from discord.ui import View, Select

    class HelpSelect(Select):

        def __init__(self):
            options = [
                discord.SelectOption(
                    label="Games",
                    description="View casino games.",
                    emoji="<:x_games:1549794186893598851>",
                    value="games"
                ),
                discord.SelectOption(
                    label="General",
                    description="View general commands.",
                    emoji="<:Commands:1549794393131585607>",
                    value="general"
                ),
                discord.SelectOption(
                    label="Balance",
                    description="View balance and crypto commands.",
                    emoji="<:info:1549794239351758928>",
                    value="balance"
                ),
            ]

            super().__init__(
                placeholder="Select a category",
                options=options,
                min_values=1,
                max_values=1
            )

        async def callback(self, interaction: discord.Interaction):

            category = self.values[0]

            if category == "games":

                embed = discord.Embed(
                    title="GAMES",
                    description=(
                        "`mines` — Diamond and bombs game.\n"
                        "`blackjack` — House Blackjack.\n"
                        "`coinflip` — Flip a coin.\n"
                        "`hilo` — Higher or lower card game.\n"
                        "`limbo` — Reach your target multiplier.\n"
                        "`market` — Predict market direction."
                    )
                )

            elif category == "general":

                embed = discord.Embed(
                    title="GENERAL",
                    description=(
                        "`whois` — Detailed user information.\n"
                        "`stats` — View player statistics.\n"
                        "`thread` — Manage your personal thread.\n"
                        "`leaderboard` — View the top 10 gamblers.\n"
                        "`help` — Show the help menu.\n"
                        "`rakeback` — View your rakeback.\n"
                        "`weekly` — View your weekly bonus.\n"
                        "`monthly` — View your monthly bonus.\n"
                        "`daily` — Claim your daily points.\n"
                        "`rain` — Distribute points among users.\n"
                        "`sos` — Start a split-or-steal event."
                    )
                )

            else:

                embed = discord.Embed(
                    title="BALANCE",
                    description=(
                        "`deposit` — Deposit LTC, SOL or USDT.\n"
                        "`withdraw` — Withdraw your funds.\n"
                        "`price` — Convert Points and USD.\n"
                        "`ai` — Ask the AI a question.\n"
                        "`tip` — Send Points to another user.\n"
                        "`vault` — Manage your Vault.\n"
                        "`balance` — Check a balance.\n"
                        "`claim` — Claim an active code."
                    )
                )

            await interaction.response.edit_message(
                embed=embed,
                view=self.view
            )

    class HelpView(View):

        def __init__(self):
            super().__init__(timeout=180)
            self.add_item(HelpSelect())

    await ctx.reply(
        embed=embed,
        view=HelpView(),
        mention_author=False
    )


# =========================================================
# COMMAND PLACEHOLDERS
# =========================================================
#
# The actual implementations will be connected to:
#
# games.py
# crypto.py
# database.py
# ai.py
# images.py
#
# Keeping the main command routing here makes the project
# easier to maintain while still keeping the casino logic
# separated into modules.
# =========================================================


# ------------------------- GENERAL -------------------------

@bot.command(
    name="whois"
)
async def whois(ctx, member: discord.Member = None):
    module = __import__("database")

    if hasattr(module, "whois"):
        await module.whois(ctx, member)
        return

    await ctx.reply(
        embed=discord.Embed(
            title="Whois",
            description="The Whois system is being initialized."
        ),
        mention_author=False
    )


@bot.command(
    name="stats"
)
async def stats(ctx, member: discord.Member = None):
    module = __import__("database")

    if hasattr(module, "stats"):
        await module.stats(ctx, member)
        return

    await ctx.reply(
        embed=discord.Embed(
            title="Stats",
            description="The statistics system is being initialized."
        ),
        mention_author=False
    )


@bot.command(
    name="leaderboard",
    aliases=["lb"]
)
async def leaderboard(ctx):
    module = __import__("database")

    if hasattr(module, "leaderboard"):
        await module.leaderboard(ctx)
        return

    await ctx.reply(
        embed=discord.Embed(
            title="Leaderboard",
            description="The leaderboard system is being initialized."
        ),
        mention_author=False
    )


@bot.command(
    name="rakeback",
    aliases=["rb"]
)
async def rakeback(ctx):
    module = __import__("database")

    if hasattr(module, "rakeback"):
        await module.rakeback(ctx)
        return

    await ctx.reply(
        embed=discord.Embed(
            title="Rakeback",
            description="The rakeback system is being initialized."
        ),
        mention_author=False
    )


@bot.command(
    name="weekly",
    aliases=["week"]
)
async def weekly(ctx):
    module = __import__("database")

    if hasattr(module, "weekly"):
        await module.weekly(ctx)
        return

    await ctx.reply(
        embed=discord.Embed(
            title="Weekly Bonus",
            description="The weekly bonus system is being initialized."
        ),
        mention_author=False
    )


@bot.command(
    name="monthly",
    aliases=["month"]
)
async def monthly(ctx):
    module = __import__("database")

    if hasattr(module, "monthly"):
        await module.monthly(ctx)
        return

    await ctx.reply(
        embed=discord.Embed(
            title="Monthly Bonus",
            description="The monthly bonus system is being initialized."
        ),
        mention_author=False
    )


@bot.command(
    name="daily"
)
async def daily(ctx):
    module = __import__("database")

    if hasattr(module, "daily"):
        await module.daily(ctx)
        return

    await ctx.reply(
        embed=discord.Embed(
            title="Daily",
            description="The daily reward system is being initialized."
        ),
        mention_author=False
    )


# ------------------------- BALANCE -------------------------

@bot.command(
    name="balance",
    aliases=["b", "bal"]
)
async def balance(ctx, member: discord.Member = None):
    module = __import__("database")

    if hasattr(module, "balance"):
        await module.balance(ctx, member)
        return

    await ctx.reply(
        embed=discord.Embed(
            title="User Balance",
            description="The balance system is being initialized."
        ),
        mention_author=False
    )


@bot.command(
    name="price"
)
async def price(ctx, amount: str):
    module = __import__("database")

    if hasattr(module, "price"):
        await module.price(ctx, amount)
        return

    await ctx.reply(
        embed=discord.Embed(
            title="Price",
            description="The price system is being initialized."
        ),
        mention_author=False
    )


@bot.command(
    name="deposit"
)
async def deposit(ctx):
    module = __import__("crypto")

    if hasattr(module, "deposit"):
        await module.deposit(ctx)
        return

    await ctx.reply(
        embed=discord.Embed(
            title="Deposit",
            description="The deposit system is being initialized."
        ),
        mention_author=False
    )


@bot.command(
    name="withdraw"
)
async def withdraw(ctx):
    module = __import__("crypto")

    if hasattr(module, "withdraw"):
        await module.withdraw(ctx)
        return

    await ctx.reply(
        embed=discord.Embed(
            title="Withdrawal",
            description="The withdrawal system is being initialized."
        ),
        mention_author=False
    )


@bot.command(
    name="tip"
)
async def tip(ctx, member: discord.Member, amount: str):
    module = __import__("database")

    if hasattr(module, "tip"):
        await module.tip(ctx, member, amount)
        return

    await ctx.reply(
        embed=discord.Embed(
            title="Tip",
            description="The tip system is being initialized."
        ),
        mention_author=False
    )


@bot.command(
    name="vault"
)
async def vault(ctx):
    module = __import__("database")

    if hasattr(module, "vault"):
        await module.vault(ctx)
        return

    await ctx.reply(
        embed=discord.Embed(
            title="Vault",
            description="The Vault system is being initialized."
        ),
        mention_author=False
    )


@bot.command(
    name="claim"
)
async def claim(ctx, code: str):
    module = __import__("database")

    if hasattr(module, "claim"):
        await module.claim(ctx, code)
        return

    await ctx.reply(
        embed=discord.Embed(
            title="Claim",
            description="The code system is being initialized."
        ),
        mention_author=False
    )


# ------------------------- AI -------------------------

@bot.command(
    name="ai"
)
async def ai_command(ctx, *, question: str):
    module = __import__("ai")

    if hasattr(module, "ask"):
        await module.ask(ctx, question)
        return

    await ctx.reply(
        embed=discord.Embed(
            title="AI",
            description="The AI system is being initialized."
        ),
        mention_author=False
    )


# ------------------------- GAMES -------------------------

@bot.command(
    name="mines"
)
async def mines(ctx, amount: str = None, mines_count: int = 3):
    module = __import__("games")

    if hasattr(module, "mines"):
        await module.mines(ctx, amount, mines_count)
        return

    await ctx.reply(
        embed=discord.Embed(
            title="Mines",
            description="The Mines game is being initialized."
        ),
        mention_author=False
    )


@bot.command(
    name="blackjack",
    aliases=["bj"]
)
async def blackjack(ctx, amount: str, *side_bets):
    module = __import__("games")

    if hasattr(module, "blackjack"):
        await module.blackjack(ctx, amount, side_bets)
        return

    await ctx.reply(
        embed=discord.Embed(
            title="Blackjack",
            description="The Blackjack game is being initialized."
        ),
        mention_author=False
    )


@bot.command(
    name="coinflip",
    aliases=["cf"]
)
async def coinflip(
    ctx,
    amount: str,
    choice: str = "random"
):
    module = __import__("games")

    if hasattr(module, "coinflip"):
        await module.coinflip(ctx, amount, choice)
        return

    await ctx.reply(
        embed=discord.Embed(
            title="Coinflip",
            description="The Coinflip game is being initialized."
        ),
        mention_author=False
    )


@bot.command(
    name="hilo"
)
async def hilo(ctx, amount: str):
    module = __import__("games")

    if hasattr(module, "hilo"):
        await module.hilo(ctx, amount)
        return

    await ctx.reply(
        embed=discord.Embed(
            title="Hi-Lo",
            description="The Hi-Lo game is being initialized."
        ),
        mention_author=False
    )


@bot.command(
    name="limbo"
)
async def limbo(ctx, amount: str, multiplier: float):
    module = __import__("games")

    if hasattr(module, "limbo"):
        await module.limbo(ctx, amount, multiplier)
        return

    await ctx.reply(
        embed=discord.Embed(
            title="Limbo",
            description="The Limbo game is being initialized."
        ),
        mention_author=False
    )


@bot.command(
    name="market"
)
async def market(ctx, amount: str):
    module = __import__("games")

    if hasattr(module, "market"):
        await module.market(ctx, amount)
        return

    await ctx.reply(
        embed=discord.Embed(
            title="Market",
            description="The Market game is being initialized."
        ),
        mention_author=False
    )


# =========================================================
# THREAD COMMANDS
# =========================================================

@bot.group(
    name="thread",
    invoke_without_command=True
)
async def thread(ctx):
    if ctx.invoked_subcommand is None:

        embed = discord.Embed(
            title="Thread",
            description=(
                f"`{ctx.prefix}thread create`\n"
                f"`{ctx.prefix}thread add [user]`\n"
                f"`{ctx.prefix}thread remove [user]`\n"
                f"`{ctx.prefix}thread delete`"
            )
        )

        await ctx.reply(
            embed=embed,
            mention_author=False
        )


@thread.command(
    name="create"
)
async def thread_create(ctx):
    module = __import__("database")

    if hasattr(module, "thread_create"):
        await module.thread_create(ctx)
        return

    await ctx.reply(
        embed=discord.Embed(
            title="Thread",
            description="The thread system is being initialized."
        ),
        mention_author=False
    )


@thread.command(
    name="add"
)
async def thread_add(ctx, member: discord.Member):
    module = __import__("database")

    if hasattr(module, "thread_add"):
        await module.thread_add(ctx, member)
        return

    await ctx.reply(
        embed=discord.Embed(
            title="Thread",
            description="The thread system is being initialized."
        ),
        mention_author=False
    )


@thread.command(
    name="remove"
)
async def thread_remove(ctx, member: discord.Member):
    module = __import__("database")

    if hasattr(module, "thread_remove"):
        await module.thread_remove(ctx, member)
        return

    await ctx.reply(
        embed=discord.Embed(
            title="Thread",
            description="The thread system is being initialized."
        ),
        mention_author=False
    )


@thread.command(
    name="delete"
)
async def thread_delete(ctx):
    module = __import__("database")

    if hasattr(module, "thread_delete"):
        await module.thread_delete(ctx)
        return

    await ctx.reply(
        embed=discord.Embed(
            title="Thread",
            description="The thread system is being initialized."
        ),
        mention_author=False
    )


# =========================================================
# ADMIN COMMANDS
# =========================================================

@bot.command(
    name="createcode"
)
@commands.has_permissions(administrator=True)
async def createcode(ctx, code: str, max_users: int, amount: str):
    module = __import__("database")

    if hasattr(module, "createcode"):
        await module.createcode(
            ctx,
            code,
            max_users,
            amount
        )
        return

    await ctx.reply(
        embed=discord.Embed(
            title="Create Code",
            description="The code system is being initialized."
        ),
        mention_author=False
    )


@bot.command(
    name="resetlb"
)
@commands.has_permissions(administrator=True)
async def resetlb(ctx, period: str):
    module = __import__("database")

    if hasattr(module, "resetlb"):
        await module.resetlb(ctx, period)
        return

    await ctx.reply(
        embed=discord.Embed(
            title="Reset Leaderboard",
            description="The leaderboard system is being initialized."
        ),
        mention_author=False
    )


@bot.command(
    name="resetstats"
)
@commands.has_permissions(administrator=True)
async def resetstats(ctx, member: discord.Member):
    module = __import__("database")

    if hasattr(module, "resetstats"):
        await module.resetstats(ctx, member)
        return

    await ctx.reply(
        embed=discord.Embed(
            title="Reset Stats",
            description="The statistics system is being initialized."
        ),
        mention_author=False
    )


@bot.command(
    name="freez"
)
@commands.has_permissions(administrator=True)
async def freez(ctx):
    module = __import__("database")

    if hasattr(module, "freeze"):
        await module.freeze(ctx)
        return

    await ctx.reply(
        embed=discord.Embed(
            title="Freeze",
            description="The freeze system is being initialized."
        ),
        mention_author=False
    )


@bot.command(
    name="unfreez"
)
@commands.has_permissions(administrator=True)
async def unfreez(ctx):
    module = __import__("database")

    if hasattr(module, "unfreeze"):
        await module.unfreeze(ctx)
        return

    await ctx.reply(
        embed=discord.Embed(
            title="Unfreeze",
            description="The freeze system is being initialized."
        ),
        mention_author=False
    )


@bot.command(
    name="forcelose"
)
@commands.has_permissions(administrator=True)
async def forcelose(
    ctx,
    member: discord.Member,
    game: str
):
    module = __import__("games")

    if hasattr(module, "forcelose"):
        await module.forcelose(
            ctx,
            member,
            game
        )
        return

    await ctx.reply(
        embed=discord.Embed(
            title="Force Lose",
            description="The game administration system is being initialized."
        ),
        mention_author=False
    )


@bot.command(
    name="rainping"
)
@commands.has_permissions(administrator=True)
async def rainping(
    ctx,
    role: discord.Role
):
    module = __import__("database")

    if hasattr(module, "set_rain_role"):
        await module.set_rain_role(ctx, role)
        return

    await ctx.reply(
        embed=discord.Embed(
            title="Rain Ping",
            description="The rain role system is being initialized."
        ),
        mention_author=False
    )


# =========================================================
# LOG COMMAND
# =========================================================

@bot.command(
    name="winlog"
)
@commands.has_permissions(administrator=True)
async def winlog(
    ctx,
    channel: discord.TextChannel
):
    module = __import__("database")

    if hasattr(module, "set_win_log"):
        await module.set_win_log(ctx, channel)
        return

    await ctx.reply(
        embed=discord.Embed(
            title="Win Log",
            description="The logging system is being initialized."
        ),
        mention_author=False
    )


# =========================================================
# START
# =========================================================

if __name__ == "__main__":
    bot.run(TOKEN)
