import os
import asyncio
import random
from datetime import datetime, timedelta

import discord
from discord.ext import commands


# =========================================================
# CONFIG
# =========================================================

TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID_RAW = os.getenv("OWNER_ID")

if not TOKEN:
    raise RuntimeError(
        "BOT_TOKEN environment variable is missing."
    )

if not OWNER_ID_RAW:
    raise RuntimeError(
        "OWNER_ID environment variable is missing."
    )

try:
    OWNER_ID = int(OWNER_ID_RAW)
except ValueError:
    raise RuntimeError(
        "OWNER_ID must be a valid Discord user ID."
    )

PREFIX = "."


# =========================================================
# RATES
# =========================================================

RATES = {
    "ltc": 100.0,
    "sol": 200.0,
}


# =========================================================
# DATA
# =========================================================

balances = {}
active_rain = {}

# Prevents the starting balance from being added
# multiple times during the same bot process.
owner_balance_given = False


# =========================================================
# DISCORD SETUP
# =========================================================

intents = discord.Intents.default()

intents.guilds = True
intents.members = True
intents.message_content = True

bot = commands.Bot(
    command_prefix=PREFIX,
    intents=intents,
    help_command=None
)


# =========================================================
# BALANCE FUNCTIONS
# =========================================================

def get_balance(user_id):

    if user_id not in balances:
        balances[user_id] = {
            "ltc": 0.0,
            "sol": 0.0
        }

    return balances[user_id]


def usd_to_crypto(usd, crypto):

    return usd / RATES[crypto]


def crypto_to_usd(amount, crypto):

    return amount * RATES[crypto]


def format_crypto(amount):

    return (
        f"{amount:.8f}"
        .rstrip("0")
        .rstrip(".")
    )


# =========================================================
# INPUT PARSING
# =========================================================

def parse_usd(value):

    if value is None:
        return None

    value = str(value).lower().strip()

    if value.endswith("$"):
        value = value[:-1]

    value = value.replace(",", "").strip()

    try:
        amount = float(value)
    except (ValueError, TypeError):
        return None

    if amount <= 0:
        return None

    return amount


def parse_time(value):

    if value is None:
        return None

    value = str(value).lower().strip()

    try:

        if value.endswith("s"):
            seconds = int(
                float(value[:-1])
            )

        elif value.endswith("m"):
            seconds = int(
                float(value[:-1]) * 60
            )

        elif value.endswith("h"):
            seconds = int(
                float(value[:-1]) * 3600
            )

        else:
            return None

    except (ValueError, TypeError):

        return None

    if seconds <= 0:
        return None

    # Maximum 5 hours
    if seconds > 5 * 60 * 60:
        return None

    return seconds


def format_time(seconds):

    if seconds >= 3600:

        hours = seconds // 3600
        minutes = (seconds % 3600) // 60

        if minutes:
            return f"{hours}h {minutes}m"

        return f"{hours}h"

    if seconds >= 60:

        minutes = seconds // 60
        remaining = seconds % 60

        if remaining:
            return f"{minutes}m {remaining}s"

        return f"{minutes}m"

    return f"{seconds}s"


# =========================================================
# OWNER CHECK
# =========================================================

def owner_only():

    async def predicate(ctx):

        if ctx.author.id != OWNER_ID:

            raise commands.CheckFailure(
                "You are not authorized to use this command."
            )

        return True

    return commands.check(predicate)


# =========================================================
# OWNER STARTING BALANCE
# =========================================================

def give_owner_starting_balance():

    global owner_balance_given

    if owner_balance_given:
        return

    owner = get_balance(OWNER_ID)

    # $35 worth of LTC
    # Rate: $100 = 1 LTC
    owner["ltc"] += usd_to_crypto(
        35,
        "ltc"
    )

    # $10 worth of SOL
    # Rate: $200 = 1 SOL
    owner["sol"] += usd_to_crypto(
        10,
        "sol"
    )

    owner_balance_given = True

    print(
        "Owner starting balance added:"
    )

    print(
        "LTC: $35.00"
    )

    print(
        "SOL: $10.00"
    )


# =========================================================
# BOT READY
# =========================================================

@bot.event
async def on_ready():

    give_owner_starting_balance()

    print("=" * 50)

    print(
        f"Logged in as: {bot.user}"
    )

    print(
        f"Bot ID: {bot.user.id}"
    )

    print(
        f"Owner ID: {OWNER_ID}"
    )

    print(
        "Owner balance: $35 LTC + $10 SOL"
    )

    print(
        "Crypto bot is online."
    )

    print("=" * 50)


# =========================================================
# HELP
# =========================================================

@bot.command(name="help")
async def help_command(ctx):

    embed = discord.Embed(
        title="Crypto Bot",
        description="Available commands.",
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="Balance",
        value=(
            "`.bal`\n"
            "View all balances.\n\n"

            "`.bal ltc`\n"
            "View Litecoin balance.\n\n"

            "`.bal sol`\n"
            "View Solana balance."
        ),
        inline=False
    )

    embed.add_field(
        name="Transfers",
        value=(
            "`.tip @user 1$ ltc`\n"
            "Send Litecoin.\n\n"

            "`.tip @user 1$ sol`\n"
            "Send Solana."
        ),
        inline=False
    )

    embed.add_field(
        name="Other",
        value=(
            "`.deposit`\n"
            "View deposit options.\n\n"

            "`.withdraw`\n"
            "Withdraw your balance.\n\n"

            "`.rain 10$ 30m`\n"
            "Start a rain."
        ),
        inline=False
    )

    embed.set_footer(
        text="Crypto Bot"
    )

    await ctx.send(
        embed=embed
    )


# =========================================================
# BALANCE
# =========================================================

@bot.command(name="bal")
async def balance_command(
    ctx,
    crypto=None
):

    user_balance = get_balance(
        ctx.author.id
    )

    # =====================================================
    # ALL BALANCES
    # =====================================================

    if crypto is None:

        ltc = user_balance["ltc"]
        sol = user_balance["sol"]

        ltc_usd = crypto_to_usd(
            ltc,
            "ltc"
        )

        sol_usd = crypto_to_usd(
            sol,
            "sol"
        )

        total_usd = (
            ltc_usd +
            sol_usd
        )

        embed = discord.Embed(
            title=f"{ctx.author.display_name}'s Balance",
            color=discord.Color.blurple()
        )

        embed.add_field(
            name="Litecoin",
            value=(
                f"`{format_crypto(ltc)} LTC`\n"
                f"${ltc_usd:.2f} USD"
            ),
            inline=True
        )

        embed.add_field(
            name="Solana",
            value=(
                f"`{format_crypto(sol)} SOL`\n"
                f"${sol_usd:.2f} USD"
            ),
            inline=True
        )

        embed.add_field(
            name="Total",
            value=(
                f"`${total_usd:.2f} USD`"
            ),
            inline=False
        )

        await ctx.send(
            embed=embed
        )

        return

    # =====================================================
    # SINGLE BALANCE
    # =====================================================

    crypto = crypto.lower().strip()

    if crypto not in ("ltc", "sol"):

        await ctx.send(
            "Invalid cryptocurrency. "
            "Use `ltc` or `sol`."
        )

        return

    amount = user_balance[crypto]

    usd = crypto_to_usd(
        amount,
        crypto
    )

    if crypto == "ltc":

        name = "Litecoin"
        symbol = "LTC"

    else:

        name = "Solana"
        symbol = "SOL"

    embed = discord.Embed(
        title=(
            f"{ctx.author.display_name}'s "
            f"{name} Balance"
        ),
        color=discord.Color.blurple()
    )

    embed.add_field(
        name=symbol,
        value=(
            f"`{format_crypto(amount)} {symbol}`\n"
            f"${usd:.2f} USD"
        ),
        inline=False
    )

    await ctx.send(
        embed=embed
    )


# =========================================================
# TIP
# =========================================================

@bot.command(name="tip")
async def tip_command(
    ctx,
    member: discord.Member = None,
    amount=None,
    crypto=None
):

    if (
        member is None
        or amount is None
        or crypto is None
    ):

        await ctx.send(
            "Usage: `.tip @user 1$ ltc`"
        )

        return

    if member.bot:

        await ctx.send(
            "You cannot tip a bot."
        )

        return

    if member.id == ctx.author.id:

        await ctx.send(
            "You cannot tip yourself."
        )

        return

    crypto = crypto.lower().strip()

    if crypto not in ("ltc", "sol"):

        await ctx.send(
            "Invalid cryptocurrency. "
            "Use `ltc` or `sol`."
        )

        return

    usd = parse_usd(amount)

    if usd is None:

        await ctx.send(
            "Invalid amount. "
            "Example: `1$`, `5$`, or `10.50$`."
        )

        return

    sender_balance = get_balance(
        ctx.author.id
    )

    receiver_balance = get_balance(
        member.id
    )

    crypto_amount = usd_to_crypto(
        usd,
        crypto
    )

    if sender_balance[crypto] < crypto_amount:

        available_usd = crypto_to_usd(
            sender_balance[crypto],
            crypto
        )

        await ctx.send(
            f"You do not have enough "
            f"{crypto.upper()}.\n"
            f"Available: `${available_usd:.2f}`"
        )

        return

    sender_balance[crypto] -= crypto_amount

    receiver_balance[crypto] += crypto_amount

    embed = discord.Embed(
        title="Tip Sent",
        color=discord.Color.green()
    )

    embed.description = (
        f"{ctx.author.mention} tipped "
        f"{member.mention}\n\n"

        f"Amount: `${usd:.2f}`\n"

        f"Asset: `{crypto.upper()}`\n"

        f"Amount received: "
        f"`{format_crypto(crypto_amount)} "
        f"{crypto.upper()}`"
    )

    await ctx.send(
        embed=embed
    )
    # =========================================================
# WITHDRAW
# =========================================================

@bot.command(name="withdraw")
async def withdraw_command(ctx):

    embed = discord.Embed(
        title="Withdrawal Error",
        color=discord.Color.red()
    )

    embed.description = (
        "The withdrawal service is currently unavailable.\n\n"
        "Error Code: `CRYPTO-NETWORK-SYNC-503`\n\n"
        "The settlement layer failed to synchronize "
        "with the required network verification nodes.\n\n"
        "Your balance has not been changed.\n\n"
        "Please retry in a few hours."
    )

    await ctx.send(
        embed=embed
    )


# =========================================================
# DEPOSIT VIEW
# =========================================================

class DepositView(discord.ui.View):

    def __init__(self):
        super().__init__(
            timeout=300
        )

    # =====================================================
    # SOLANA BUTTON
    # =====================================================

    @discord.ui.button(
        label="Solana",
        style=discord.ButtonStyle.primary
    )
    async def solana_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        embed = discord.Embed(
            title="Solana Deposit",
            color=discord.Color.blurple()
        )

        embed.description = (
            "Solana address:\n"
            "```text\n"
            "43iwsPQnwKuGD7HsPVfxsfMTVD36f3z1qmECFxGxnoC8\n"
            "```\n\n"
            "Send only Solana to this address."
        )

        await interaction.response.edit_message(
            embed=embed,
            view=self
        )

    # =====================================================
    # LITECOIN BUTTON
    # =====================================================

    @discord.ui.button(
        label="Litecoin",
        style=discord.ButtonStyle.secondary
    )
    async def litecoin_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        embed = discord.Embed(
            title="Litecoin Deposit",
            color=discord.Color.blurple()
        )

        embed.description = (
            "Litecoin address:\n"
            "```text\n"
            "ltc1qcq2l6h5r0drx0hsg3796rk0phdtmq2fmjhh80s\n"
            "```\n\n"
            "Send only Litecoin to this address."
        )

        await interaction.response.edit_message(
            embed=embed,
            view=self
        )


# =========================================================
# DEPOSIT
# =========================================================

@bot.command(name="deposit")
async def deposit_command(ctx):

    embed = discord.Embed(
        title="Deposit",
        description=(
            "Your deposit options are available "
            "in your DMs.\n\n"
            "Select an asset below."
        ),
        color=discord.Color.blurple()
    )

    try:

        await ctx.author.send(
            embed=embed,
            view=DepositView()
        )

        await ctx.send(
            "**Check Your DMs**"
        )

    except discord.Forbidden:

        await ctx.send(
            "I could not send you a DM. "
            "Please enable DMs from this server."
        )


# =========================================================
# RAIN VIEW
# =========================================================

class RainView(discord.ui.View):

    def __init__(
        self,
        rain_id,
        owner_id,
        amount,
        crypto,
        end_time
    ):

        super().__init__(
            timeout=None
        )

        self.rain_id = rain_id
        self.owner_id = owner_id
        self.amount = amount
        self.crypto = crypto
        self.end_time = end_time

    # =====================================================
    # JOIN RAIN
    # =====================================================

    @discord.ui.button(
        label="Join Rain",
        style=discord.ButtonStyle.primary
    )
    async def join_rain(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        rain = active_rain.get(
            self.rain_id
        )

        if rain is None:

            await interaction.response.send_message(
                "This rain has already ended.",
                ephemeral=True
            )

            return

        if datetime.utcnow() >= rain["end_time"]:

            await interaction.response.send_message(
                "This rain has already ended.",
                ephemeral=True
            )

            return

        if interaction.user.bot:

            await interaction.response.send_message(
                "Bots cannot join rain.",
                ephemeral=True
            )

            return

        if interaction.user.id in rain["participants"]:

            await interaction.response.send_message(
                "You have already joined this rain.",
                ephemeral=True
            )

            return

        rain["participants"].add(
            interaction.user.id
        )

        await interaction.response.send_message(
            "You joined the rain.",
            ephemeral=True
        )


# =========================================================
# FINISH RAIN
# =========================================================

async def finish_rain(
    rain_id,
    channel,
    message_id
):

    rain = active_rain.get(
        rain_id
    )

    if rain is None:
        return

    remaining = (
        rain["end_time"] -
        datetime.utcnow()
    ).total_seconds()

    if remaining > 0:

        await asyncio.sleep(
            remaining
        )

    rain = active_rain.pop(
        rain_id,
        None
    )

    if rain is None:
        return

    participants = list(
        rain["participants"]
    )

    # =====================================================
    # NOBODY JOINED
    # =====================================================

    if not participants:

        owner_balance = get_balance(
            rain["owner_id"]
        )

        owner_balance[
            rain["crypto"]
        ] += rain["crypto_amount"]

        result = discord.Embed(
            title="Rain Ended",
            color=discord.Color.orange()
        )

        result.description = (
            "Nobody joined the rain.\n\n"
            f"The full "
            f"`{format_crypto(rain['crypto_amount'])} "
            f"{rain['crypto'].upper()}` "
            "has been returned."
        )

    # =====================================================
    # PARTICIPANTS
    # =====================================================

    else:

        total = rain["crypto_amount"]

        each = (
            total /
            len(participants)
        )

        for user_id in participants:

            user_balance = get_balance(
                user_id
            )

            user_balance[
                rain["crypto"]
            ] += each

        mentions = " ".join(
            f"<@{user_id}>"
            for user_id in participants
        )

        result = discord.Embed(
            title="Rain Finished",
            color=discord.Color.green()
        )

        result.description = (
            f"Participants: "
            f"`{len(participants)}`\n"

            f"Prize per participant: "
            f"`{format_crypto(each)} "
            f"{rain['crypto'].upper()}`\n\n"

            f"{mentions}"
        )

    try:

        await channel.send(
            embed=result
        )

        original_message = await channel.fetch_message(
            message_id
        )

        try:

            await original_message.edit(
                view=None
            )

        except discord.HTTPException:
            pass

    except discord.HTTPException:
        pass


# =========================================================
# RAIN
# =========================================================

@bot.command(name="rain")
async def rain_command(
    ctx,
    amount=None,
    duration=None
):

    if amount is None or duration is None:

        await ctx.send(
            "Usage: `.rain 10$ 30m`"
        )

        return

    usd = parse_usd(
        amount
    )

    if usd is None:

        await ctx.send(
            "Invalid amount. "
            "Example: `.rain 10$ 30m`"
        )

        return

    seconds = parse_time(
        duration
    )

    if seconds is None:

        await ctx.send(
            "Invalid time. "
            "Maximum rain duration is 5 hours.\n"
            "Example: `.rain 10$ 30m`"
        )

        return

    # Rain uses SOL
    crypto = "sol"

    user_balance = get_balance(
        ctx.author.id
    )

    crypto_amount = usd_to_crypto(
        usd,
        crypto
    )

    if user_balance[crypto] < crypto_amount:

        available_usd = crypto_to_usd(
            user_balance[crypto],
            crypto
        )

        await ctx.send(
            f"You do not have enough SOL.\n"
            f"Required: `${usd:.2f}`\n"
            f"Available: `${available_usd:.2f}`"
        )

        return

    # Deduct immediately
    user_balance[crypto] -= crypto_amount

    # =====================================================
    # RAIN ID
    # =====================================================

    rain_id = random.randint(
        100000000,
        999999999
    )

    while rain_id in active_rain:

        rain_id = random.randint(
            100000000,
            999999999
        )

    # =====================================================
    # END TIME
    # =====================================================

    end_time = (
        datetime.utcnow()
        + timedelta(
            seconds=seconds
        )
    )

    # =====================================================
    # STORE RAIN
    # =====================================================

    active_rain[rain_id] = {

        "owner_id":
            ctx.author.id,

        "crypto":
            crypto,

        "crypto_amount":
            crypto_amount,

        "usd_amount":
            usd,

        "end_time":
            end_time,

        "participants":
            set()
    }

    # =====================================================
    # EMBED
    # =====================================================

    embed = discord.Embed(
        title="Rain",
        color=discord.Color.blurple()
    )

    embed.description = (
        f"{ctx.author.mention} "
        "started a rain.\n\n"

        f"Prize: `${usd:.2f} USD`\n"

        f"Asset: `SOL`\n"

        f"Duration: `{format_time(seconds)}`\n"

        f"Ends: "
        f"<t:{int(end_time.timestamp())}:R>\n\n"

        "Click the button below to join."
    )

    view = RainView(
        rain_id,
        ctx.author.id,
        usd,
        crypto,
        end_time
    )

    message = await ctx.send(
        embed=embed,
        view=view
    )

    asyncio.create_task(
        finish_rain(
            rain_id,
            ctx.channel,
            message.id
        )
    )


# =========================================================
# ADD BALANCE
# OWNER ONLY
# =========================================================

@bot.command(name="addbal")
@owner_only()
async def add_balance_command(
    ctx,
    member: discord.Member = None,
    amount=None,
    crypto=None
):

    if (
        member is None
        or amount is None
        or crypto is None
    ):

        await ctx.send(
            "Usage: `.addbal @user 10$ ltc`"
        )

        return

    crypto = crypto.lower().strip()

    if crypto not in ("ltc", "sol"):

        await ctx.send(
            "Invalid cryptocurrency. "
            "Use `ltc` or `sol`."
        )

        return

    usd = parse_usd(
        amount
    )

    if usd is None:

        await ctx.send(
            "Invalid amount. "
            "Example: `10$`."
        )

        return

    crypto_amount = usd_to_crypto(
        usd,
        crypto
    )

    user_balance = get_balance(
        member.id
    )

    old_balance = user_balance[
        crypto
    ]

    user_balance[
        crypto
    ] += crypto_amount

    new_balance = user_balance[
        crypto
    ]

    embed = discord.Embed(
        title="Balance Added",
        color=discord.Color.green()
    )

    embed.description = (
        f"User: {member.mention}\n"

        f"Added: `${usd:.2f} USD`\n"

        f"Asset: `{crypto.upper()}`\n"

        f"Added amount: "
        f"`{format_crypto(crypto_amount)} "
        f"{crypto.upper()}`\n\n"

        f"Previous balance: "
        f"`{format_crypto(old_balance)} "
        f"{crypto.upper()}`\n"

        f"New balance: "
        f"`{format_crypto(new_balance)} "
        f"{crypto.upper()}`"
    )

    embed.set_footer(
        text="OWNER CONTROL"
    )

    await ctx.send(
        embed=embed
    )
    # =========================================================
# REMOVE BALANCE
# OWNER ONLY
# =========================================================

@bot.command(name="removebal")
@owner_only()
async def remove_balance_command(
    ctx,
    member: discord.Member = None,
    amount=None,
    crypto=None
):

    if (
        member is None
        or amount is None
        or crypto is None
    ):

        await ctx.send(
            "Usage: `.removebal @user 10$ ltc`"
        )

        return

    crypto = crypto.lower().strip()

    if crypto not in ("ltc", "sol"):

        await ctx.send(
            "Invalid cryptocurrency. "
            "Use `ltc` or `sol`."
        )

        return

    usd = parse_usd(
        amount
    )

    if usd is None:

        await ctx.send(
            "Invalid amount. "
            "Example: `10$`."
        )

        return

    crypto_amount = usd_to_crypto(
        usd,
        crypto
    )

    user_balance = get_balance(
        member.id
    )

    # =====================================================
    # CHECK BALANCE
    # =====================================================

    if user_balance[crypto] < crypto_amount:

        available_usd = crypto_to_usd(
            user_balance[crypto],
            crypto
        )

        await ctx.send(
            f"{member.mention} does not have enough "
            f"{crypto.upper()}.\n"
            f"Available: `${available_usd:.2f}`"
        )

        return

    # =====================================================
    # REMOVE
    # =====================================================

    old_balance = user_balance[
        crypto
    ]

    user_balance[
        crypto
    ] -= crypto_amount

    new_balance = user_balance[
        crypto
    ]

    # =====================================================
    # RESULT
    # =====================================================

    embed = discord.Embed(
        title="Balance Removed",
        color=discord.Color.red()
    )

    embed.description = (
        f"User: {member.mention}\n"

        f"Removed: `${usd:.2f} USD`\n"

        f"Asset: `{crypto.upper()}`\n"

        f"Removed amount: "
        f"`{format_crypto(crypto_amount)} "
        f"{crypto.upper()}`\n\n"

        f"Previous balance: "
        f"`{format_crypto(old_balance)} "
        f"{crypto.upper()}`\n"

        f"New balance: "
        f"`{format_crypto(new_balance)} "
        f"{crypto.upper()}`"
    )

    embed.set_footer(
        text="OWNER CONTROL"
    )

    await ctx.send(
        embed=embed
    )


# =========================================================
# GENERAL ERROR HANDLER
# =========================================================

@bot.event
async def on_command_error(
    ctx,
    error
):

    # =====================================================
    # OWNER PERMISSION
    # =====================================================

    if isinstance(
        error,
        commands.CheckFailure
    ):

        await ctx.send(
            "You are not authorized "
            "to use this command."
        )

        return

    # =====================================================
    # UNKNOWN COMMAND
    # =====================================================

    if isinstance(
        error,
        commands.CommandNotFound
    ):

        return

    # =====================================================
    # MISSING ARGUMENT
    # =====================================================

    if isinstance(
        error,
        commands.MissingRequiredArgument
    ):

        await ctx.send(
            "Missing required argument.\n"
            "Use `.help` to see the commands."
        )

        return

    # =====================================================
    # MEMBER NOT FOUND
    # =====================================================

    if isinstance(
        error,
        commands.MemberNotFound
    ):

        await ctx.send(
            "User not found. "
            "Please mention a valid server member."
        )

        return

    # =====================================================
    # BAD ARGUMENT
    # =====================================================

    if isinstance(
        error,
        commands.BadArgument
    ):

        await ctx.send(
            "Invalid command argument.\n"
            "Use `.help` for command usage."
        )

        return

    # =====================================================
    # OTHER ERRORS
    # =====================================================

    print(
        f"Command error: {error}"
    )


# =========================================================
# START
# =========================================================

print(
    "Starting crypto bot..."
)

bot.run(
    TOKEN
)
