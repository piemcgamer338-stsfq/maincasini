from __future__ import annotations

import asyncio, io, random, time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import aiohttp
import discord
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont

import config
from database import Database
from games import card_value, deck, hand_total, parse_amount, provably_fair


def money(value) -> str: return f"{float(value):,.2f}"
def usd(points) -> str: return f"${float(points) * config.POINT_USD:,.2f}"
def brand(title: str, description: str = "", colour=0x2B2D31):
    return discord.Embed(title=f"{config.CASINO_NAME} — {title}", description=description, colour=colour, timestamp=datetime.now(timezone.utc))
def allowed_admin(ctx): return ctx.author.id in config.ADMIN_USER_IDS or ctx.author.guild_permissions.administrator


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


SOL_DEPOSIT_ADDRESS = "HKn9yAXBBUhPpgTrgnxndLL5QCqocpn8nHjNeWTB7Kv6"
USDT_BEP20_DEPOSIT_ADDRESS = "0xc21F13F95afb0d53D54ccCa378E177F50f41ECF2"


def make_deposit_qr(address: str, currency: str, username: str) -> discord.File:
    import qrcode

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=12,
        border=2,
    )
    qr.add_data(address)
    qr.make(fit=True)

    qr_image = qr.make_image(
        fill_color="#FFFFFF",
        back_color="#101116",
    ).convert("RGB")

    qr_image = qr_image.resize((560, 560))

    canvas = Image.new("RGB", (700, 700), "#101116")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()

    draw.text(
        (30, 25),
        f"{username.upper()}'S {currency} DEPOSIT ADDRESS",
        fill="#FFFFFF",
        font=font,
    )

    canvas.paste(qr_image, (70, 75))

    draw.text(
        (30, 655),
        f"Only send {currency} on the correct network.",
        fill="#B5BAC1",
        font=font,
    )

    output = io.BytesIO()
    canvas.save(output, "PNG")
    output.seek(0)

    return discord.File(output, filename="deposit_qr.png")


class DepositView(OwnerView):
    async def send_currency(self, interaction: discord.Interaction, currency: str):
        deposits = {
            "SOL": {
                "name": "Solana (SOL)",
                "address": SOL_DEPOSIT_ADDRESS,
                "minimum": "0.025 USD worth of SOL",
                "conversion": "1 point = $0.005 USD",
                "emoji": config.E["sol"],
                "network_note": "Only send SOL using the Solana network.",
            },
            "USDT": {
                "name": "USDT (BEP-20)",
                "address": USDT_BEP20_DEPOSIT_ADDRESS,
                "minimum": "0.025 USDT",
                "conversion": "1 point = $0.005 USD",
                "emoji": config.E["usdt"],
                "network_note": "Only send USDT on BNB Smart Chain (BEP-20).",
            },
        }

        data = deposits[currency]

        qr_file = make_deposit_qr(
            data["address"],
            currency,
            interaction.user.display_name,
        )

        embed = brand(
            f"Your {data['name']} Deposit Address",
            (
                f"{interaction.user.mention}, deposit **{data['name']}** only:\n"
                f"```{data['address']}```\n"
                f"**Minimum:** {data['minimum']}\n"
                f"**Conversion:** {data['conversion']}\n"
                f"**Fee:** 0%\n\n"
                f"⚠️ {data['network_note']}\n"
                "After sending, wait till 1 Confirmation ."
            ),
            0x5865F2,
        )

        embed.set_image(url="attachment://deposit_qr.png")
        embed.set_footer(text=f"{config.CASINO_NAME} • Deposit address")

        try:
            await interaction.user.send(embed=embed, file=qr_file)

            await interaction.response.send_message(
                f"{config.E['win']} I sent your {data['name']} deposit address in DM.",
                ephemeral=True,
            )

        except discord.Forbidden:
            await interaction.response.send_message(
                "I cannot DM you. Enable Direct Messages from server members, then try again.",
                ephemeral=True,
            )

    @discord.ui.button(
        label="LTC",
        style=discord.ButtonStyle.secondary,
        emoji=config.E["ltc"],
    )
    async def ltc(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not config.LTC_XPUB:
            await interaction.response.send_message(
                "LTC address generation is not configured yet.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "Your unique Litecoin address is being generated. Please try again after the LTC xpub system is added.",
            ephemeral=True,
        )

    @discord.ui.button(
        label="SOL",
        style=discord.ButtonStyle.secondary,
        emoji=config.E["sol"],
    )
    async def sol(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.send_currency(interaction, "SOL")

    @discord.ui.button(
        label="USDT (BEP-20)",
        style=discord.ButtonStyle.secondary,
        emoji=config.E["usdt"],
    )
    async def usdt(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.send_currency(interaction, "USDT")


@bot.command()
async def deposit(ctx):
    embed = brand(
        "Deposit",
        "Choose a currency below. Your deposit address will be sent privately in DM.",
    )

    embed.set_footer(
        text=f"{config.CASINO_NAME} • Deposits are credited after 1 verification"
    )

    await ctx.send(
        embed=embed,
        view=DepositView(ctx.author.id),
    )
    
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
        embed = brand("Withdrawal requested", f"**Total:** {money(amount)} points ({usd(amount)})\n**Currency:** {self.currency}\n**Address:** `{address}`\n\nYour withdrawal request will be sent by an administrator within a few hours.", 0xFEE75C)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        channel = bot.get_channel(config.WITHDRAW_LOG_CHANNEL_ID)
        if channel: await channel.send(embed=brand("Withdrawal request", f"{config.E['withdraw']} **{money(amount)} points** withdrawn by {interaction.user.mention}.\nCurrency: **{self.currency}**\nAddress: `{address}`\nPayment will be sent by an administrator within a few hours."))


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


class MinesView(OwnerView):
    def __init__(self, owner, bet, mines):
        super().__init__(owner.id, timeout=120); self.bet, self.mines, self.opened = bet, mines, 0; self.bombs = set(random.sample(range(25), mines)); self.finished = False
        for index in range(25):
            button = discord.ui.Button(label="\u200b", style=discord.ButtonStyle.secondary, row=index//5, custom_id=str(index))
            button.callback = self.pick; self.add_item(button)
        cash = discord.ui.Button(label="Cash out", style=discord.ButtonStyle.success, row=4); cash.callback = self.cashout; self.add_item(cash)
    def multiplier(self): return max(1.0, (25 / (25-self.mines)) ** self.opened * .96)
    async def pick(self, interaction):
        if self.finished: return
        index = int(interaction.data["custom_id"]); button = next(x for x in self.children if x.custom_id == str(index))
        if index in self.bombs:
            self.finished=True; button.emoji=config.E["bomb"]; button.style=discord.ButtonStyle.danger; button.disabled=True
            for x in self.children:
                if x.custom_id and int(x.custom_id) in self.bombs: x.emoji=config.E["bomb"]; x.disabled=True
            await bot.db.record_game(self.owner_id, self.bet, 0, "mines")
            await interaction.response.edit_message(embed=brand("Mines — Lost", f"You hit a mine and lost **{money(self.bet)} points**.", 0xED4245), view=self); return
        self.opened += 1; button.emoji=config.E["diamond"]; button.style=discord.ButtonStyle.success; button.disabled=True
        if self.opened == 25-self.mines: await self.cashout(interaction); return
        await interaction.response.edit_message(embed=brand("Mines", f"Diamonds: **{self.opened}** • Current payout: **{money(self.bet*self.multiplier())} points**"), view=self)
    async def cashout(self, interaction):
        if self.finished: return
        self.finished=True; payout=round(self.bet*self.multiplier(),4)
        for x in self.children: x.disabled=True
        await bot.db.record_game(self.owner_id, self.bet, payout, "mines")
        await interaction.response.edit_message(embed=brand("Mines — Cashed out", f"{config.E['win']} You won **{money(payout)} points** ({self.multiplier():.2f}x).", 0x57F287), view=self)


class BlackjackView(OwnerView):
    def __init__(self, owner, bet):
        super().__init__(owner.id, timeout=60); self.bet=bet; self.server,self.hash,self.rng=provably_fair(str(owner.id)); self.deck=deck(self.rng); self.player=[self.deck.pop(),self.deck.pop()]; self.dealer=[self.deck.pop(),self.deck.pop()]; self.done=False
    def text(self, reveal=False):
        dealer = ", ".join(self.dealer) if reveal else f"{self.dealer[0]}, ??"
        return f"**Your Hand:** {', '.join(self.player)} (**{hand_total(self.player)}**)\n**Dealer's Hand:** {dealer}" 
    async def finish(self, interaction):
        while hand_total(self.dealer) < 17: self.dealer.append(self.deck.pop())
        player,dealer_total=hand_total(self.player),hand_total(self.dealer)
        payout = round(self.bet*(2.0 if dealer_total>21 or player>dealer_total else 0),4)
        if player>21 or (dealer_total<=21 and dealer_total>=player): payout=0
        await bot.db.record_game(self.owner_id,self.bet,payout,"blackjack"); self.done=True
        for item in self.children: item.disabled=True
        outcome="Won" if payout else "Lost"; colour=0x57F287 if payout else 0xED4245
        fair=f"\n\n**Provably Fair**\nPublic Hash: `{self.hash}`\nServer Seed: `{self.server}`\nClient Seed: `{self.owner_id}`"
        await interaction.response.edit_message(embed=brand(f"Blackjack — {outcome}", self.text(True)+fair,colour),view=self)
    @discord.ui.button(label="Hit", style=discord.ButtonStyle.primary)
    async def hit(self, interaction, button):
        self.player.append(self.deck.pop())
        if hand_total(self.player)>21: await self.finish(interaction)
        else: await interaction.response.edit_message(embed=brand("Blackjack",self.text()),view=self)
    @discord.ui.button(label="Stand", style=discord.ButtonStyle.secondary)
    async def stand(self, interaction, button): await self.finish(interaction)
    @discord.ui.button(label="Double", style=discord.ButtonStyle.success)
    async def double(self, interaction, button):
        if len(self.player)!=2 or not await bot.db.change_balance(self.owner_id,-self.bet,"blackjack_double"):
            await interaction.response.send_message("Double is only available on your first hand with enough balance.",ephemeral=True); return
        self.bet*=2; self.player.append(self.deck.pop()); await self.finish(interaction)
    @discord.ui.button(label="Split", style=discord.ButtonStyle.secondary, disabled=True)
    async def split(self, interaction, button): await interaction.response.send_message("Split will be enabled in the next blackjack update.",ephemeral=True)


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

@bot.command()
async def withdraw(ctx):
    await ctx.send(embed=brand("Withdraw", "Choose the currency to withdraw.\nLTC minimum: **20** • SOL: **220** • USDT: **150** points\n\nRequests are sent by an administrator within a few hours."),view=WithdrawView(ctx.author.id))

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

@bot.command(aliases=["cf"])
async def coinflip(ctx, bet: str, choice: str="r"):
    if not await bot.game_allowed(ctx): return
    try: amount=parse_amount(bet)
    except ValueError as error: await ctx.send(str(error)); return
    if choice.lower() not in ("h","heads","t","tails","r","random"): await ctx.send("Choose h, t, or r."); return
    if not await bot.db.change_balance(ctx.author.id,-amount,"coinflip_bet"): await ctx.send("Insufficient balance."); return
    pick=random.choice(["heads","tails"]) if choice.lower() in ("r","random") else ("heads" if choice.lower().startswith("h") else "tails")
    result=random.choice(["heads","tails"]); payout=round(amount*1.92,4) if pick==result else 0
    await bot.db.record_game(ctx.author.id,amount,payout,"coinflip")
    await ctx.send(embed=brand("Coinflip — Won" if payout else "Coinflip — Lost",f"You chose **{pick.title()}**. The coin landed on **{result.title()}**.\n{'You won **'+money(payout)+' points**.' if payout else 'You lost **'+money(amount)+' points**.'}",0x57F287 if payout else 0xED4245))

@bot.command(aliases=["bj"])
async def blackjack(ctx, bet: str):
    if not await bot.game_allowed(ctx): return
    try: amount=parse_amount(bet)
    except ValueError as error: await ctx.send(str(error)); return
    if not await bot.db.change_balance(ctx.author.id,-amount,"blackjack_bet"): await ctx.send("Insufficient balance."); return
    view=BlackjackView(ctx.author,amount); await ctx.send(embed=brand("Blackjack",view.text()),view=view)

@bot.command()
async def mines(ctx, bet: str, mine_count: int=3):
    if not await bot.game_allowed(ctx): return
    try: amount=parse_amount(bet)
    except ValueError as error: await ctx.send(str(error)); return
    if not 1<=mine_count<=20: await ctx.send("Choose from 1 to 20 mines."); return
    if not await bot.db.change_balance(ctx.author.id,-amount,"mines_bet"): await ctx.send("Insufficient balance."); return
    view=MinesView(ctx.author,amount,mine_count); await ctx.send(embed=brand("Mines",f"Bet: **{money(amount)} points** • Mines: **{mine_count}**\nFind diamonds, then cash out."),view=view)

@bot.command()
async def limbo(ctx, bet: str, target: float):
    if not await bot.game_allowed(ctx): return
    try: amount=parse_amount(bet)
    except ValueError as error: await ctx.send(str(error)); return
    if not 1.01<=target<=1000: await ctx.send("Multiplier must be between 1.01x and 1000x."); return
    if not await bot.db.change_balance(ctx.author.id,-amount,"limbo_bet"): await ctx.send("Insufficient balance."); return
    crash=round(1/(1-random.random()*.99),2); payout=round(amount*target*.98,4) if crash>=target else 0
    await bot.db.record_game(ctx.author.id,amount,payout,"limbo"); await ctx.send(embed=brand("Limbo — Won" if payout else "Limbo — Lost",f"Crashed at **{crash:.2f}x** • Target: **{target:.2f}x**\n{'Won **'+money(payout)+' points**.' if payout else 'Your bet did not reach the target.'}",0x57F287 if payout else 0xED4245))

@bot.command()
async def market(ctx, bet: str, choice: str="up"):
    if not await bot.game_allowed(ctx): return
    try: amount=parse_amount(bet)
    except ValueError as error: await ctx.send(str(error)); return
    if choice.lower() not in ("up","down"): await ctx.send("Choose `up` or `down`."); return
    if not await bot.db.change_balance(ctx.author.id,-amount,"market_bet"): await ctx.send("Insufficient balance."); return
    result=random.choice(["up","down"]); payout=round(amount*1.97,4) if result==choice.lower() else 0
    await bot.db.record_game(ctx.author.id,amount,payout,"market"); await ctx.send(embed=brand("Market — Won" if payout else "Market — Lost",f"Market moved **{result.upper()}**. {'Won **'+money(payout)+' points**.' if payout else 'You lost **'+money(amount)+' points**.'}",0x57F287 if payout else 0xED4245))

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
