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
BASE_DIR = Path(__file__).resolve().parent
BOT_TOKEN = config.TOKEN
DATABASE_URL = config.DATABASE_URL
MIN_BET = Decimal('0.10')
MIN_MINES_BET = Decimal('0.10')
MIN_FROG_BET = Decimal('0.10')
COINFLIP_MULTIPLIER = Decimal('1.92')
DICE_MULTIPLIER = Decimal('1.92')
MAX_MINES = 20
MAX_MINES_TILES = 25
GAME_COOLDOWN = max(0, int(getattr(config, 'GAME_COOLDOWN_SECONDS', 3)))
RAKEBACK_RATE = Decimal('0.01')
RAIN_DURATIONS = {1: 60, 2: 120, 5: 300, 10: 600}
RANKS = [{'name': 'Bronze', 'stage': 'I', 'wager': Decimal('50'), 'reward': Decimal('1')}, {'name': 'Bronze', 'stage': 'II', 'wager': Decimal('150'), 'reward': Decimal('2')}, {'name': 'Bronze', 'stage': 'III', 'wager': Decimal('300'), 'reward': Decimal('3')}, {'name': 'Silver', 'stage': 'I', 'wager': Decimal('400'), 'reward': Decimal('5')}, {'name': 'Silver', 'stage': 'II', 'wager': Decimal('500'), 'reward': Decimal('8')}, {'name': 'Silver', 'stage': 'III', 'wager': Decimal('600'), 'reward': Decimal('10')}, {'name': 'Diamond', 'stage': None, 'wager': Decimal('1000'), 'reward': Decimal('15')}, {'name': 'Amethyst', 'stage': None, 'wager': Decimal('1200'), 'reward': Decimal('20')}, {'name': 'Celestial', 'stage': None, 'wager': Decimal('1500'), 'reward': Decimal('30')}]
AFFILIATE_TIERS = [(1, Decimal('0.0010')), (10, Decimal('0.0020')), (25, Decimal('0.0035')), (100, Decimal('0.0050'))]
CODE_REQUIREMENTS = {1: {'name': '$1 Deposit', 'type': 'deposit', 'amount': Decimal('1')}, 2: {'name': '$25 Deposit', 'type': 'deposit', 'amount': Decimal('25')}, 3: {'name': '$10 Wagered', 'type': 'wager', 'amount': Decimal('10')}}

def D(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal('0')
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal('0')

def money(value) -> str:
    amount = D(value).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
    return f'${amount:,.2f}'

def plain_money(value) -> str:
    amount = D(value).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
    return f'{amount:,.2f}'

def parse_money(value: str | int | float | Decimal) -> Optional[Decimal]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        amount = value
    else:
        raw = str(value).strip().replace(',', '').replace('$', '')
        if raw.lower() in {'all', 'half'}:
            return None
        try:
            amount = Decimal(raw)
        except InvalidOperation:
            return None
    if amount <= 0:
        return None
    return amount.quantize(Decimal('0.01'), rounding=ROUND_DOWN)

def normalize_amount(value: str) -> Optional[Decimal]:
    raw = str(value).strip().lower()
    if raw.endswith('$'):
        raw = raw[:-1]
    return parse_money(raw)

def amount_or_all(raw: str, balance: Decimal) -> Optional[Decimal]:
    value = str(raw).strip().lower()
    if value == 'all':
        return balance
    if value == 'half':
        return (balance / Decimal('2')).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
    return normalize_amount(value)

def valid_bet(amount: Decimal) -> bool:
    return amount >= MIN_BET

def base_embed(title: Optional[str]=None, description: Optional[str]=None, color: int=0x2B2D31) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=color, timestamp=datetime.now(timezone.utc))
    return embed

def success_embed(title: str, description: str) -> discord.Embed:
    return base_embed(title=title, description=description, color=5763719)

def error_embed(title: str, description: str) -> discord.Embed:
    return base_embed(title=title, description=description, color=15548997)

def neutral_embed(title: str, description: str) -> discord.Embed:
    return base_embed(title=title, description=description, color=5793266)

def components_v2_available() -> bool:
    return all((hasattr(discord.ui, name) for name in ('LayoutView', 'Container', 'TextDisplay', 'ActionRow')))

def make_text_display(text: str):
    return discord.ui.TextDisplay(text)

def make_container(*items, accent_color: Optional[int]=None):
    kwargs = {}
    if accent_color is not None:
        kwargs['accent_color'] = accent_color
    return discord.ui.Container(*items, **kwargs)

class V2LayoutView(discord.ui.LayoutView):

    def __init__(self, *, timeout: Optional[float]=180):
        super().__init__(timeout=timeout)

class ButtonView(discord.ui.View):

    def __init__(self, *, timeout: Optional[float]=180):
        super().__init__(timeout=timeout)

class WalletView(ButtonView):

    def __init__(self, bot: 'CasinoBot', user_id: int):
        super().__init__(timeout=180)
        self.bot = bot
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(embed=base_embed(description='This wallet belongs to another user.', color=2829617), ephemeral=True)
            return False
        return True

    @discord.ui.button(label='Deposit', style=discord.ButtonStyle.success, custom_id='wallet_deposit')
    async def deposit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(embed=base_embed(description='Choose a currency Below', color=2829617), view=DepositCurrencyView(self.bot, interaction.user.id), ephemeral=True)

    @discord.ui.button(label='Withdraw', style=discord.ButtonStyle.secondary, custom_id='wallet_withdraw')
    async def withdraw_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(WithdrawModal(self.bot, interaction.user.id))

class DepositCurrencyView(ButtonView):

    def __init__(self, bot: 'CasinoBot', user_id: int):
        super().__init__(timeout=180)
        self.bot = bot
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(embed=base_embed(description='This deposit menu belongs to another user.', color=2829617), ephemeral=True)
            return False
        return True

    @discord.ui.button(label='LTC', style=discord.ButtonStyle.secondary, emoji='Ł', custom_id='deposit_ltc')
    async def ltc_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.bot.send_deposit_dm(interaction, 'LTC')

    @discord.ui.button(label='SOL', style=discord.ButtonStyle.secondary, emoji='◎', custom_id='deposit_sol')
    async def sol_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.bot.send_deposit_dm(interaction, 'SOL')

class MainWalletV2(V2LayoutView):

    def __init__(self, bot: 'CasinoBot', user: discord.User | discord.Member):
        super().__init__(timeout=180)
        self.bot = bot
        self.user_id = user.id
        text = make_text_display(f'## Wallet\n**Balance:** {money(0)}')
        row = discord.ui.ActionRow()
        row.add_item(discord.ui.Button(label='Deposit', style=discord.ButtonStyle.success, custom_id=f'wallet_v2_deposit:{user.id}'))
        row.add_item(discord.ui.Button(label='Withdraw', style=discord.ButtonStyle.secondary, custom_id=f'wallet_v2_withdraw:{user.id}'))
        container = make_container(text, row, accent_color=58998)
        self.add_item(container)

class WithdrawModal(discord.ui.Modal):

    def __init__(self, bot: 'CasinoBot', user_id: int):
        super().__init__(title='Withdraw', timeout=300)
        self.bot = bot
        self.user_id = user_id
        self.currency = discord.ui.TextInput(label='Currency', placeholder='LTC / SOL / ETH / USDT', required=True, max_length=10)
        self.address = discord.ui.TextInput(label='Withdrawal Address', placeholder='Enter your wallet address', required=True, max_length=150)
        self.amount = discord.ui.TextInput(label='Amount', placeholder='Example: 10.00', required=True, max_length=30)
        self.add_item(self.currency)
        self.add_item(self.address)
        self.add_item(self.amount)

    async def on_submit(self, interaction: discord.Interaction):
        await self.bot.handle_withdrawal(interaction=interaction, user_id=self.user_id, currency=self.currency.value, address=self.address.value, amount_text=self.amount.value)

class DiceSetupView(ButtonView):

    def __init__(self, bot: 'CasinoBot', user_id: int, amount: Decimal):
        super().__init__(timeout=120)
        self.bot = bot
        self.user_id = user_id
        self.amount = amount
        self.mode = None
        self.dice_count = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(embed=base_embed(description='This dice setup belongs to another player.', color=2829617), ephemeral=True)
            return False
        return True

    @discord.ui.button(label='Crazy Dice', style=discord.ButtonStyle.primary, custom_id='dice_mode_crazy')
    async def crazy(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.mode = 'crazy'
        await self._choose_dice(interaction)

    @discord.ui.button(label='Normal Dice', style=discord.ButtonStyle.secondary, custom_id='dice_mode_normal')
    async def normal(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.mode = 'normal'
        await self._choose_dice(interaction)

    async def _choose_dice(self, interaction: discord.Interaction):
        view = DiceCountView(self.bot, self.user_id, self.amount, self.mode)
        await interaction.response.edit_message(embed=base_embed(description='**Choose Number of Dice**\n\nSelect 1, 2, or 3 dice.', color=2829617), view=view)

class DiceCountView(ButtonView):

    def __init__(self, bot: 'CasinoBot', user_id: int, amount: Decimal, mode: str):
        super().__init__(timeout=120)
        self.bot = bot
        self.user_id = user_id
        self.amount = amount
        self.mode = mode

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(embed=base_embed(description='This dice setup belongs to another player.', color=2829617), ephemeral=True)
            return False
        return True

    async def choose(self, interaction: discord.Interaction, count: int):
        await interaction.response.defer()
        await self.bot.start_dice_game(interaction, self.user_id, self.amount, self.mode, count)

    @discord.ui.button(label='1 Dice', style=discord.ButtonStyle.secondary, custom_id='dice_count_1')
    async def one(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.choose(interaction, 1)

    @discord.ui.button(label='2 Dice', style=discord.ButtonStyle.secondary, custom_id='dice_count_2')
    async def two(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.choose(interaction, 2)

    @discord.ui.button(label='3 Dice', style=discord.ButtonStyle.secondary, custom_id='dice_count_3')
    async def three(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.choose(interaction, 3)

class CoinflipView(ButtonView):

    def __init__(self, bot: 'CasinoBot', user_id: int, amount: Decimal, color: str, game_id: int, server_hash: str, client_seed: str, nonce: int):
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

class MinesGame:

    def __init__(self, bot: 'CasinoBot', user_id: int, amount: Decimal, mines: int, game_id: int, server_hash: str, server_seed: str, client_seed: str, nonce: int):
        self.bot = bot
        self.user_id = user_id
        self.amount = amount
        self.mines = mines
        self.game_id = game_id
        self.server_hash = server_hash
        self.server_seed = server_seed
        self.client_seed = client_seed
        self.nonce = nonce
        self.bombs = set(random.sample(range(MinesView.TILE_COUNT), mines))
        self.opened: set[int] = set()
        self.finished = False

    @property
    def multiplier(self) -> Decimal:
        opened = len(self.opened)
        if opened <= 0:
            return Decimal('1.00')
        value = (Decimal(str(MinesView.TILE_COUNT)) / Decimal(str(MinesView.TILE_COUNT - self.mines))) ** opened
        value *= Decimal('0.96')
        return value.quantize(Decimal('0.01'), rounding=ROUND_DOWN)

    @property
    def payout(self) -> Decimal:
        return (self.amount * self.multiplier).quantize(Decimal('0.01'), rounding=ROUND_DOWN)

class MinesView(ButtonView):
    TILE_COUNT = 24

    def __init__(self, game: MinesGame):
        super().__init__(timeout=300)
        self.game = game
        for index in range(self.TILE_COUNT):
            button = discord.ui.Button(label='?', style=discord.ButtonStyle.secondary, custom_id=f'mine:{index}', row=index // 5)
            button.callback = self.make_callback(index)
            self.add_item(button)
        cashout = discord.ui.Button(label='Cashout', style=discord.ButtonStyle.success, custom_id='mine_cashout', row=4)
        cashout.callback = self.cashout
        self.add_item(cashout)

    def make_callback(self, index: int):

        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.game.user_id:
                await interaction.response.send_message(embed=error_embed('Mines', 'This Mines game belongs to another player.'), ephemeral=True)
                return
            await self.game.bot.mines_click(interaction, self.game, index, self)
        return callback

    async def cashout(self, interaction: discord.Interaction):
        if interaction.user.id != self.game.user_id:
            await interaction.response.send_message(embed=error_embed('Mines', 'This Mines game belongs to another player.'), ephemeral=True)
            return
        await self.game.bot.mines_cashout(interaction, self.game, self)

class RainView(ButtonView):

    def __init__(self, bot: 'CasinoBot', rain_id: str):
        super().__init__(timeout=None)
        self.bot = bot
        self.rain_id = rain_id

    @discord.ui.button(label='Join Rain', style=discord.ButtonStyle.success, custom_id='rain_join')
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.bot.join_rain(interaction, self.rain_id)

class CasinoBot(commands.Bot):

    def __init__(self):
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True
        intents.messages = True
        intents.message_content = True
        super().__init__(command_prefix=commands.when_mentioned, intents=intents, help_command=None)
        self.db: Optional[Database] = None
        self.http_session: Optional[aiohttp.ClientSession] = None
        self.started_at = datetime.now(timezone.utc)
        self.active_games: dict[int, dict] = {}
        self.active_mines: dict[int, MinesGame] = {}
        self.active_rains: dict[str, dict] = {}
        self.active_dice: dict[int, dict] = {}
        self.game_counter = random.randint(1000, 9999)
        self._cooldowns: dict[tuple[int, str], float] = {}
        self.ltc_watcher_task = None

    def next_game_id(self) -> int:
        self.game_counter += 1
        if self.game_counter > 999999:
            self.game_counter = 1000
        return self.game_counter

    def create_server_seed(self) -> str:
        return secrets.token_hex(32)

    def server_hash(self, server_seed: str) -> str:
        return hashlib.sha256(server_seed.encode()).hexdigest()

    def create_client_seed(self, user_id: int) -> str:
        return f'{user_id}-{secrets.token_hex(16)}'

    def fair_digest(self, server_seed: str, client_seed: str, nonce: int, game: str='') -> bytes:
        message = f'{client_seed}:{nonce}:{game}'.encode()
        return hmac.new(server_seed.encode(), message, hashlib.sha256).digest()

    def fair_roll(self, server_seed: str, client_seed: str, nonce: int, game: str='') -> Decimal:
        digest = self.fair_digest(server_seed, client_seed, nonce, game)
        number = int.from_bytes(digest[:8], 'big')
        value = Decimal(number) / Decimal(2 ** 64) * Decimal('100')
        return value.quantize(Decimal('0.01'))

    def fair_int(self, server_seed: str, client_seed: str, nonce: int, minimum: int, maximum: int, game: str='') -> int:
        digest = self.fair_digest(server_seed, client_seed, nonce, game)
        number = int.from_bytes(digest[:8], 'big')
        return minimum + number % (maximum - minimum + 1)

    def check_game_cooldown(self, user_id: int, command_name: str) -> float:
        if GAME_COOLDOWN <= 0:
            return 0
        key = (user_id, command_name)
        now = time.monotonic()
        last = self._cooldowns.get(key, 0)
        remaining = GAME_COOLDOWN - (now - last)
        if remaining > 0:
            return remaining
        self._cooldowns[key] = now
        return 0

    async def get_db_user(self, user_id: int):
        if self.db is None:
            raise RuntimeError('Database is not connected.')
        return await self.db.user(user_id)

    async def get_balance(self, user_id: int) -> Decimal:
        row = await self.get_db_user(user_id)
        if not row:
            return Decimal('0')
        return D(row.get('balance', 0) if hasattr(row, 'get') else row['balance'])

    async def deduct_bet(self, user_id: int, amount: Decimal, game: str) -> bool:
        if amount < MIN_BET:
            return False
        return await self.db.change_balance(user_id, -amount, kind='bet', note=game)

    async def settle_win(self, user_id: int, bet: Decimal, payout: Decimal, game: str):
        await self.db.record_game(user_id, bet, payout, game)

    async def settle_loss(self, user_id: int, bet: Decimal, game: str):
        await self.db.record_game(user_id, bet, Decimal('0'), game)

    async def setup_hook(self):
        if not DATABASE_URL:
            raise RuntimeError('DATABASE_URL is missing.')
        self.db = Database(DATABASE_URL)
        await self.db.connect()
        await self.db.pool.execute('\n            CREATE TABLE IF NOT EXISTS house (\n                id INTEGER PRIMARY KEY,\n                balance NUMERIC(20,8) NOT NULL DEFAULT 0\n            )\n            ')
        await self.db.pool.execute('\n            INSERT INTO house(id, balance)\n            VALUES(1, 0)\n            ON CONFLICT(id) DO NOTHING\n            ')
        await self.db.pool.execute('\n            ALTER TABLE transactions\n            ADD COLUMN IF NOT EXISTS balance_after NUMERIC(20,8)\n            ')
        await self.db.pool.execute('\n            ALTER TABLE users\n            ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()\n            ')
        self.http_session = aiohttp.ClientSession()
        self.add_view(RainView(self, 'persistent'))
        try:
            synced = await self.tree.sync()
            print(f'[BOT] Synced {len(synced)} slash commands.')
        except Exception as exc:
            print(f'[BOT] Slash command sync failed: {exc}')
        self.ltc_watcher_task = asyncio.create_task(self.ltc_deposit_watcher())

    async def close(self):
        if self.ltc_watcher_task:
            self.ltc_watcher_task.cancel()
            try:
                await self.ltc_watcher_task
            except asyncio.CancelledError:
                pass
        if self.http_session:
            await self.http_session.close()
        if self.db:
            await self.db.close()
        await super().close()

    async def on_ready(self):
        print(f'[BOT] Logged in as {self.user} ({self.user.id})')
        print(f'[BOT] Servers: {len(self.guilds)}')
        await self.change_presence(activity=discord.Game(name='/help'))

    async def safe_send(self, interaction: discord.Interaction, *, content: Optional[str]=None, embed: Optional[discord.Embed]=None, view: Optional[discord.ui.View]=None, ephemeral: bool=False):
        if embed is None and content is not None:
            embed = base_embed(title=None, description=content, color=2829617)
        kwargs = {'embed': embed, 'view': view, 'ephemeral': ephemeral}
        kwargs = {key: value for key, value in kwargs.items() if value is not None}
        if interaction.response.is_done():
            return await interaction.followup.send(**kwargs)
        return await interaction.response.send_message(**kwargs)

    async def command_error(self, interaction: discord.Interaction, error: Exception):
        print(f'[COMMAND ERROR] {interaction.command}: {error}')
        if isinstance(error, app_commands.CommandOnCooldown):
            await self.safe_send(interaction, content=f'Please wait **{error.retry_after:.1f}s**.', ephemeral=True)
            return
        await self.safe_send(interaction, embed=error_embed('Something went wrong', 'Please try again in a moment.'), ephemeral=True)

    async def send_deposit_dm(self, interaction: discord.Interaction, currency: str):
        currency = currency.upper()
        address = await self.get_deposit_address(interaction.user.id, currency)
        if not address:
            await interaction.response.send_message(embed=base_embed(description='A deposit address is not available yet.', color=2829617), ephemeral=True)
            return
        try:
            await interaction.user.send(embed=base_embed(title=f'{currency} Deposit', description=f'**Deposit Address:**\n`{address}`\n\nDeposits are credited only after blockchain confirmation.', color=2829617))
            await interaction.response.send_message(embed=base_embed(description='Your deposit address is sent to your DMs. Deposits are credited only after blockchain confirmation.', color=2829617), ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(embed=base_embed(description="I couldn't DM you. Please enable DMs from this server and try again.", color=2829617), ephemeral=True)

    async def get_deposit_address(self, user_id: int, currency: str) -> Optional[str]:
        currency = currency.upper()
        if hasattr(self.db, 'get_deposit_address'):
            return await self.db.get_deposit_address(user_id, currency)
        if currency == 'SOL':
            return os.getenv('SOL_DEPOSIT_ADDRESS', '') or None
        if currency == 'LTC':
            return await self.generate_ltc_address(user_id)
        return None

    async def generate_ltc_address(self, user_id: int) -> Optional[str]:
        if hasattr(self.db, 'get_or_create_ltc_address'):
            return await self.db.get_or_create_ltc_address(user_id, config.LTC_XPUB, config.LTC_DERIVATION_PATH)
        return None

    async def handle_withdrawal(self, interaction: discord.Interaction, user_id: int, currency: str, address: str, amount_text: str):
        currency = currency.strip().upper()
        address = address.strip()
        amount = normalize_amount(amount_text)
        if currency not in {'LTC', 'SOL', 'ETH', 'USDT'}:
            await interaction.response.send_message(embed=base_embed(description='Supported currencies: LTC, SOL, ETH, USDT.', color=2829617), ephemeral=True)
            return
        if amount is None:
            await interaction.response.send_message(embed=base_embed(description='Enter a valid withdrawal amount.', color=2829617), ephemeral=True)
            return
        minimum = D(config.MIN_WITHDRAW.get(currency, 0))
        if minimum and amount < minimum:
            await interaction.response.send_message(embed=base_embed(description=f'Minimum {currency} withdrawal is {money(minimum)}.', color=2829617), ephemeral=True)
            return
        if not self.valid_withdraw_address(currency, address):
            await interaction.response.send_message(embed=base_embed(description='That withdrawal address is invalid.', color=2829617), ephemeral=True)
            return
        balance = await self.get_balance(user_id)
        if amount > balance:
            await interaction.response.send_message(embed=base_embed(description='You Dont Have Enough Crypto\n-# use /deposit to top-up Funds', color=2829617), ephemeral=True)
            return
        if hasattr(self.db, 'create_withdrawal'):
            created = await self.db.create_withdrawal(user_id=user_id, currency=currency, address=address, amount=amount)
            if not created:
                await interaction.response.send_message(embed=base_embed(description='Your withdrawal could not be created.', color=2829617), ephemeral=True)
                return
        else:
            deducted = await self.db.change_balance(user_id, -amount, kind='withdraw', note=f'{currency}:{address}')
            if not deducted:
                await interaction.response.send_message(embed=base_embed(description='Your withdrawal could not be processed.', color=2829617), ephemeral=True)
                return
        await interaction.response.send_message(embed=base_embed(description=f'## Withdrawal Requested\n\n**Amount:** {money(amount)}\n**Currency:** {currency}\n**Address:** `{address}`\n\nYour withdrawal is pending processing.', color=2829617), ephemeral=True)

    def valid_withdraw_address(self, currency: str, address: str) -> bool:
        if not address:
            return False
        if currency == 'LTC':
            return address.startswith(('ltc1', 'M', 'm', 'L')) and len(address) >= 26
        if currency == 'SOL':
            return 32 <= len(address) <= 50
        if currency in {'ETH', 'USDT'}:
            return address.startswith('0x') and len(address) == 42
        return False

    async def ltc_deposit_watcher(self):
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                await self.check_ltc_deposits()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print(f'[LTC WATCHER] {exc}')
            await asyncio.sleep(60)

    async def check_ltc_deposits(self):
        endpoint = os.getenv('LTC_PROVIDER_DEPOSIT_URL', '').strip()
        if not endpoint:
            return
        if not self.http_session:
            return
        headers = {}
        api_key = getattr(config, 'PAYMENT_PROVIDER_API_KEY', '')
        if api_key:
            headers['Authorization'] = f'Bearer {api_key}'
        async with self.http_session.get(endpoint, headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as response:
            if response.status != 200:
                return
            data = await response.json()
        if not isinstance(data, list):
            return
        for deposit in data:
            if not isinstance(deposit, dict):
                continue
            await self.process_ltc_deposit(deposit)

    async def process_ltc_deposit(self, deposit: dict):
        if not hasattr(self.db, 'process_deposit'):
            return
        await self.db.process_deposit(deposit)
bot = CasinoBot()

def slash_command_available(interaction: discord.Interaction) -> bool:
    return interaction.guild is not None

async def require_database(interaction: discord.Interaction) -> bool:
    if bot.db is None:
        await bot.safe_send(interaction, content='Database is not ready yet.', ephemeral=True)
        return False
    return True

async def require_bet_amount(interaction: discord.Interaction, amount: Decimal) -> bool:
    if amount < MIN_BET:
        await bot.safe_send(interaction, embed=error_embed('Invalid Bet', f'The minimum bet is **{money(MIN_BET)}**.'), ephemeral=True)
        return False
    return True

async def require_sufficient_balance(interaction: discord.Interaction, amount: Decimal) -> bool:
    balance = await bot.get_balance(interaction.user.id)
    if amount > balance:
        await bot.safe_send(interaction, embed=error_embed('Insufficient Balance', 'You Dont Have Enough Crypto\n-# use /deposit to top-up Funds'), ephemeral=True)
        return False
    return True
HELP_GENERAL = '## General\n`/help` — Show this help menu\n`/balance` — View your wallet\n`/deposit` — Deposit cryptocurrency\n`/withdraw` — Withdraw funds\n`/stats` — View your player statistics\n`/history` — View recent game history\n`/howtoplay` — Learn how to play\n`/rewardinfo` — View rewards and perks\n`/affiliateinfo` — View affiliate rates\n`/fair` — View provably-fair information'
HELP_GAMES = '## Games\n`/dice` — Select a dice game\n`/roll` — Roll your dice\n`/coinflip` — Play Red or Blue coinflip\n`/mines` — Play Mines\n`/blackjack` — Play Blackjack\n`/frog-run` — Play Frog Run\n`/retrigger` — Retrigger an unfinished game\n`/fix-dice` — Recover a dice game'
HELP_REWARDS = '## Rewards\n`/rakeback` — Claim available rakeback\n`/ranks` — View rank progression\n`/rank-rewards` — Claim rank rewards\n`/affiliates` — View your affiliates\n`/affiliate-claim` — Claim affiliate earnings\n`/claim` — Claim a promo code\n`/leaderboard` — View top wagerers\n`/race` — View the active wager race'
HELP_SOCIAL = '## Social\n`/tip` — Tip another player\n`/rain` — Start a rain event\n`/private-channel` — Manage a private gaming channel'
HELP_ADMIN = '## Admin\n`/ranksetup` — Configure rank roles\n`/code` — Create a promotional code\n`/race start` — Start a wager race\n`/race end` — End a wager race'

def rank_for_wager(wagered: Decimal) -> dict:
    current = RANKS[0]
    for rank in RANKS:
        if wagered >= rank['wager']:
            current = rank
    return current

def next_rank_for_wager(wagered: Decimal) -> Optional[dict]:
    for rank in RANKS:
        if wagered < rank['wager']:
            return rank
    return None

def rank_label(rank: dict) -> str:
    if rank.get('stage'):
        return f"{rank['name']} Stage {rank['stage']}"
    return rank['name']

def rank_progress(wagered: Decimal) -> tuple[dict, Optional[dict]]:
    current = rank_for_wager(wagered)
    upcoming = next_rank_for_wager(wagered)
    return (current, upcoming)

def format_history_row(row) -> str:
    if hasattr(row, 'get'):
        game = row.get('game', row.get('note', 'Game'))
        amount = row.get('amount', 0)
        created_at = row.get('created_at', None)
    else:
        game = row['game']
        amount = row['amount']
        created_at = row['created_at']
    if isinstance(created_at, datetime):
        timestamp = discord.utils.format_dt(created_at, style='R')
    else:
        timestamp = 'Unknown time'
    amount_decimal = D(amount)
    sign = '+' if amount_decimal >= 0 else ''
    return f'**{game}** · {sign}{money(amount_decimal)} · {timestamp}'

@bot.tree.command(name='history', description='View your last 10 games.')
async def history_command(interaction: discord.Interaction):
    user_id = interaction.user.id
    games = []
    if hasattr(bot.db, 'game_history'):
        games = await bot.db.game_history(user_id, 10)
    else:
        games = await bot.db.pool.fetch("\n            SELECT\n                created_at,\n                note,\n                amount\n            FROM transactions\n            WHERE user_id = $1\n              AND kind = 'game'\n            ORDER BY created_at DESC\n            LIMIT 10\n            ", user_id)
    lines = ['## Game History', '']
    if not games:
        lines.append('No games played yet.')
    else:
        for game in games:
            if isinstance(game, dict):
                created = game.get('created_at')
                game_name = game.get('game', game.get('note', 'Game'))
                amount = D(game.get('amount', 0))
            else:
                created = game['created_at']
                game_name = game.get('game', game.get('note', 'Game'))
                amount = D(game.get('amount', 0))
            if created:
                timestamp = discord.utils.format_dt(created, style='R')
            else:
                timestamp = 'Unknown time'
            result = f'+{money(amount)}' if amount > 0 else money(amount)
            lines.append(f'**{game_name}** · {result} · {timestamp}')
    embed = base_embed(None, '\n'.join(lines), 58998)
    embed.set_footer(text='last 10 Games history')
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name='rank-rewards', description='View and claim available rank rewards.')
async def rank_rewards_command(interaction: discord.Interaction):
    user_id = interaction.user.id
    row = await bot.get_db_user(user_id)
    wagered = D(row['wagered']) if row else Decimal('0')
    claimed_index = 0
    if hasattr(bot.db, 'get_claimed_rank'):
        claimed_index = int(await bot.db.get_claimed_rank(user_id))
    available = []
    for index, rank in enumerate(RANKS):
        if wagered >= rank['wager'] and index >= claimed_index:
            available.append((index, rank))
    if not available:
        await interaction.response.send_message(embed=base_embed(description='You have no rank rewards available.', color=2829617), ephemeral=True)
        return
    lines = ['## Available Rank Rewards', '']
    for index, rank in available:
        label = rank['name']
        if rank['stage']:
            label += f" Stage {rank['stage']}"
        lines.append(f"**{label}** — {money(rank['reward'])}")
    lines.append('')
    lines.append('Use the claim button below to claim the next available reward.')
    await interaction.response.send_message(embed=base_embed(None, '\n'.join(lines), 58998), view=RankRewardView(bot, user_id, available[0][0]), ephemeral=True)

class RankRewardView(ButtonView):

    def __init__(self, bot_instance: CasinoBot, user_id: int, rank_index: int):
        super().__init__(timeout=120)
        self.bot = bot_instance
        self.user_id = user_id
        self.rank_index = rank_index

    @discord.ui.button(label='Claim Reward', style=discord.ButtonStyle.success)
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(embed=base_embed(description='This reward belongs to another user.', color=2829617), ephemeral=True)
            return
        rank = RANKS[self.rank_index]
        if hasattr(self.bot.db, 'claim_rank_reward'):
            success = await self.bot.db.claim_rank_reward(self.user_id, self.rank_index)
        else:
            success = await self.bot.db.change_balance(self.user_id, rank['reward'], kind='rank_reward', note=f"{rank['name']} Stage {rank['stage']}")
        if not success:
            await interaction.response.send_message(embed=base_embed(description='This reward has already been claimed or is not available.', color=2829617), ephemeral=True)
            return
        await interaction.response.edit_message(embed=success_embed('Rank Reward Claimed!', f"You received **{money(rank['reward'])}**."), view=None)

def mines_embed(game: MinesGame, *, revealed: bool=False, result: Optional[str]=None) -> discord.Embed:
    if game.finished:
        title = '💣 Mines — Game Over'
    else:
        title = '💣 Mines'
    lines = [f'**Bet:** {money(game.amount)}', f'**Mines:** {game.mines}', f'**Safe Tiles:** {len(game.opened)}/{MinesView.TILE_COUNT - game.mines}', f'**Multiplier:** {game.multiplier:.2f}x']
    if not game.finished and len(game.opened) > 0:
        lines.append(f'**Cashout:** {money(game.payout)}')
    if result:
        lines.append('')
        lines.append(result)
    embed = base_embed(title, '\n'.join(lines), 58998 if not game.finished else 15548997)
    embed.set_footer(text=f'Game #{game.game_id} • Provably fair')
    return embed

async def mines_reveal_all(game: MinesGame, view: MinesView):
    for item in view.children:
        if not isinstance(item, discord.ui.Button):
            continue
        custom_id = item.custom_id or ''
        if not custom_id.startswith('mine:'):
            continue
        try:
            index = int(custom_id.split(':')[1])
        except (ValueError, IndexError):
            continue
        if index in game.bombs:
            item.label = '💣'
            item.style = discord.ButtonStyle.danger
        elif index in game.opened:
            item.label = '💎'
            item.style = discord.ButtonStyle.success
        else:
            item.label = '·'
            item.style = discord.ButtonStyle.secondary
        item.disabled = True
    for item in view.children:
        if isinstance(item, discord.ui.Button) and item.custom_id == 'mine_cashout':
            item.disabled = True

async def mines_click_impl(bot_instance: CasinoBot, interaction: discord.Interaction, game: MinesGame, index: int, view: MinesView):
    if game.finished:
        await interaction.response.send_message(embed=base_embed(description='This Mines game has already ended.', color=2829617), ephemeral=True)
        return
    if index in game.opened:
        await interaction.response.send_message(embed=base_embed(description='That tile is already open.', color=2829617), ephemeral=True)
        return
    await interaction.response.defer()
    if index in game.bombs:
        game.finished = True
        button = next((item for item in view.children if isinstance(item, discord.ui.Button) and item.custom_id == f'mine:{index}'), None)
        if button:
            button.label = '💣'
            button.style = discord.ButtonStyle.danger
            button.disabled = True
        await mines_reveal_all(game, view)
        await bot_instance.settle_loss(game.user_id, game.amount, 'mines')
        bot_instance.active_mines.pop(game.user_id, None)
        embed = mines_embed(game, revealed=True, result=f'💥 You hit a mine and lost **{money(game.amount)}**.')
        await interaction.edit_original_response(embed=embed, view=view)
        return
    game.opened.add(index)
    button = next((item for item in view.children if isinstance(item, discord.ui.Button) and item.custom_id == f'mine:{index}'), None)
    if button:
        button.label = '💎'
        button.style = discord.ButtonStyle.success
        button.disabled = True
    safe_count = MinesView.TILE_COUNT - game.mines
    if len(game.opened) >= safe_count:
        game.finished = True
        payout = game.payout
        await bot_instance.settle_win(game.user_id, game.amount, payout, 'mines')
        bot_instance.active_mines.pop(game.user_id, None)
        await mines_reveal_all(game, view)
        embed = mines_embed(game, revealed=True, result=f'🎉 All safe tiles cleared!\n**Won:** {money(payout)}')
        await interaction.edit_original_response(embed=embed, view=view)
        await bot_instance.check_rank_up(game.user_id)
        return
    embed = mines_embed(game)
    await interaction.edit_original_response(embed=embed, view=view)

async def mines_cashout_impl(bot_instance: CasinoBot, interaction: discord.Interaction, game: MinesGame, view: MinesView):
    if game.finished:
        await interaction.response.send_message(embed=base_embed(description='This Mines game has already ended.', color=2829617), ephemeral=True)
        return
    if not game.opened:
        await interaction.response.send_message(embed=base_embed(description='Open at least one safe tile before cashing out.', color=2829617), ephemeral=True)
        return
    await interaction.response.defer()
    game.finished = True
    payout = game.payout
    await bot_instance.settle_win(game.user_id, game.amount, payout, 'mines')
    bot_instance.active_mines.pop(game.user_id, None)
    await mines_reveal_all(game, view)
    embed = mines_embed(game, revealed=True, result=f'💰 Cashed out for **{money(payout)}**.')
    await interaction.edit_original_response(embed=embed, view=view)
    await bot_instance.check_rank_up(game.user_id)

async def mines_timeout(game: MinesGame, view: MinesView):
    if game.finished:
        return
    game.finished = True
    await mines_reveal_all(game, view)
    game.bot.active_mines.pop(game.user_id, None)

async def casino_mines_click(self: CasinoBot, interaction: discord.Interaction, game: MinesGame, index: int, view: MinesView):
    await mines_click_impl(self, interaction, game, index, view)

async def casino_mines_cashout(self: CasinoBot, interaction: discord.Interaction, game: MinesGame, view: MinesView):
    await mines_cashout_impl(self, interaction, game, view)
CasinoBot.mines_click = casino_mines_click
CasinoBot.mines_cashout = casino_mines_cashout

async def rain_daily_wager(bot_instance: CasinoBot, user_id: int) -> Decimal:
    if hasattr(bot_instance.db, 'get_daily_wager'):
        return D(await bot_instance.db.get_daily_wager(user_id))
    row = await bot_instance.get_db_user(user_id)
    if not row:
        return Decimal('0')
    return D(row['wagered'])

async def has_rain_role(interaction: discord.Interaction) -> bool:
    role_id = getattr(config, 'RAIN_ROLE_ID', 0)
    if not role_id:
        return True
    if not isinstance(interaction.user, discord.Member):
        return False
    return any((role.id == role_id for role in interaction.user.roles))

async def join_rain(self: CasinoBot, interaction: discord.Interaction, rain_id: str):
    rain = self.active_rains.get(rain_id)
    if not rain:
        await interaction.response.send_message(embed=base_embed(description='This rain has already ended.', color=2829617), ephemeral=True)
        return
    if not await has_rain_role(interaction):
        await interaction.response.send_message(embed=base_embed(description='You need the verified role to join rain.', color=2829617), ephemeral=True)
        return
    wagered = await rain_daily_wager(self, interaction.user.id)
    if wagered < Decimal('1'):
        await interaction.response.send_message(embed=base_embed(description='You need at least **$1** wagered today to join rain.', color=2829617), ephemeral=True)
        return
    if interaction.user.id in rain['players']:
        await interaction.response.send_message(embed=base_embed(description='You already joined this rain.', color=2829617), ephemeral=True)
        return
    rain['players'].add(interaction.user.id)
    await interaction.response.send_message(embed=base_embed(description='You joined the rain.', color=2829617), ephemeral=True)
CasinoBot.join_rain = join_rain

async def finish_rain(self: CasinoBot, rain_id: str):
    rain = self.active_rains.pop(rain_id, None)
    if not rain:
        return
    amount = D(rain['amount'])
    players = list(rain['players'])
    channel = self.get_channel(rain['channel_id'])
    if not channel:
        return
    if not players:
        await self.db.change_balance(rain['user_id'], amount, kind='rain_refund', note=rain_id)
        await channel.send(embed=base_embed(description=f'## Rain Ended — {money(amount)}\nNobody joined the rain, so the full amount was refunded.', color=2829617))
        return
    share = (amount / Decimal(len(players))).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
    distributed = share * len(players)
    remainder = (amount - distributed).quantize(Decimal('0.01'))
    if remainder > 0:
        share += (remainder / Decimal(len(players))).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
    successful = []
    for user_id in players:
        try:
            credited = await self.db.change_balance(user_id, share, kind='rain', note=rain_id)
            if credited:
                successful.append(user_id)
        except Exception:
            continue
    count = len(successful)
    if count <= 0:
        await self.db.change_balance(rain['user_id'], amount, kind='rain_refund', note=rain_id)
        await channel.send(embed=base_embed(description=f'## Rain Ended — {money(amount)}\nNobody could be credited, so the rain was refunded.', color=2829617))
        return
    mention_text = ' '.join((f'<@{uid}>' for uid in successful))
    await channel.send(embed=base_embed(description=f"## Rain Ended — {money(amount)}\n## **{rain['owner_mention']}** rained on **{count}** players — **{money(share)}** each!\n\n{mention_text}", color=2829617))
CasinoBot.finish_rain = finish_rain

async def rain_timer(bot_instance: CasinoBot, rain_id: str, seconds: int):
    await asyncio.sleep(seconds)
    await bot_instance.finish_rain(rain_id)

@bot.tree.command(name='coinflip', description='Flip a coin against the bot.')
@app_commands.describe(amount='Amount to bet', color='Choose Red or Blue')
@app_commands.choices(color=[app_commands.Choice(name='Red', value='red'), app_commands.Choice(name='Blue', value='blue')])
async def coinflip(interaction: discord.Interaction, amount: str, color: app_commands.Choice[str]):
    user_id = interaction.user.id
    cooldown = bot.check_game_cooldown(user_id, 'coinflip')
    if cooldown:
        await bot.safe_send(interaction, content=f'Please wait **{cooldown:.1f}s** before playing again.', ephemeral=True)
        return
    balance = await bot.get_balance(user_id)
    bet = amount_or_all(amount, balance)
    if bet is None:
        await bot.safe_send(interaction, embed=error_embed('Invalid Amount', 'Enter a valid amount such as `$1`, `1`, or `0.10`.'), ephemeral=True)
        return
    if bet < MIN_BET:
        await bot.safe_send(interaction, embed=error_embed('Minimum Bet', f'The minimum bet is **{money(MIN_BET)}**.'), ephemeral=True)
        return
    if bet > balance:
        await bot.safe_send(interaction, content='You Dont Have Enough Crypto\n-# use /deposit to top-up Funds', ephemeral=True)
        return
    selected = color.value
    game_id = bot.next_game_id()
    server_seed = bot.create_server_seed()
    server_hash = bot.server_hash(server_seed)
    client_seed = bot.create_client_seed(user_id)
    nonce = 0
    if not await bot.deduct_bet(user_id, bet, 'coinflip'):
        await bot.safe_send(interaction, content='Your balance changed. Please try again.', ephemeral=True)
        return
    bot.active_games[user_id] = {'type': 'coinflip', 'game_id': game_id, 'bet': bet, 'selected': selected, 'server_seed': server_seed, 'server_hash': server_hash, 'client_seed': client_seed, 'nonce': nonce}
    selected_name = 'Red' if selected == 'red' else 'Blue'
    opponent_name = 'Blue' if selected == 'red' else 'Red'
    await interaction.response.send_message(embed=neutral_embed('## Flipping…', f'**{interaction.user.display_name}** ( {selected_name}) vs Bot ( {opponent_name})\n\n**Bet:** {money(bet)} · **Game #{game_id}**'))
    await asyncio.sleep(2)
    game = bot.active_games.pop(user_id, None)
    if not game:
        return
    roll = bot.fair_roll(game['server_seed'], game['client_seed'], game['nonce'], 'coinflip')
    result = 'red' if roll < Decimal('50') else 'blue'
    won = result == selected
    if won:
        payout = (bet * COINFLIP_MULTIPLIER).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
        await bot.settle_win(user_id, bet, payout, 'coinflip')
        result_title = f'## Coinflip — {result.title()} wins!'
        result_color = 5763719
        result_text = f'**Result:** {result.title()}\n**Roll:** {roll}\n**Bet:** {money(bet)}\n**Payout:** {money(payout)} **(1.92x)**'
    else:
        payout = Decimal('0')
        await bot.settle_loss(user_id, bet, 'coinflip')
        result_title = f'## Coinflip — {result.title()} wins!'
        result_color = 15548997
        result_text = f'**Result:** {result.title()}\n**Roll:** {roll}\n**Bet:** {money(bet)}\n**Lost:** {money(bet)}'
    embed = base_embed(title=result_title, description=result_text, color=result_color)
    embed.add_field(name='Provably Fair', value=f"**Server Hash:** `{game['server_hash']}`\n**Client Seed:** `{game['client_seed']}`\n**Nonce:** `{game['nonce']}`", inline=False)
    embed.add_field(name='Game', value=f'`#{game_id}`', inline=True)
    embed.set_footer(text='Verify this result with /provably-fair')
    await interaction.edit_original_response(embed=embed)
    try:
        sticker_key = 'coinflip_red_sticker' if result == 'red' else 'coinflip_blue_sticker'
        sticker_id = await bot.db.setting(sticker_key, '')
        if sticker_id:
            sticker = await bot.fetch_sticker(int(sticker_id))
            await interaction.followup.send(stickers=[sticker])
    except Exception as exc:
        print(f'[COINFLIP STICKER] {exc}')

@bot.tree.command(name='cfred', description='Set the Red coinflip sticker ID.')
@app_commands.describe(sticker_id='Discord sticker ID')
async def cfred(interaction: discord.Interaction, sticker_id: str):
    if not bot.is_owner(interaction.user):
        await interaction.response.send_message(embed=base_embed(description='Only the bot owner can use this command.', color=2829617), ephemeral=True)
        return
    try:
        value = int(sticker_id)
    except ValueError:
        await interaction.response.send_message(embed=base_embed(description='Sticker ID must be a number.', color=2829617), ephemeral=True)
        return
    await bot.db.set_setting('coinflip_red_sticker', str(value))
    await interaction.response.send_message(embed=base_embed(description=f'Red coinflip sticker set to `{value}`.', color=2829617), ephemeral=True)

@bot.tree.command(name='cfblue', description='Set the Blue coinflip sticker ID.')
@app_commands.describe(sticker_id='Discord sticker ID')
async def cfblue(interaction: discord.Interaction, sticker_id: str):
    if not bot.is_owner(interaction.user):
        await interaction.response.send_message(embed=base_embed(description='Only the bot owner can use this command.', color=2829617), ephemeral=True)
        return
    try:
        value = int(sticker_id)
    except ValueError:
        await interaction.response.send_message(embed=base_embed(description='Sticker ID must be a number.', color=2829617), ephemeral=True)
        return
    await bot.db.set_setting('coinflip_blue_sticker', str(value))
    await interaction.response.send_message(embed=base_embed(description=f'Blue coinflip sticker set to `{value}`.', color=2829617), ephemeral=True)

def mines_multiplier(mines: int, opened: int) -> Decimal:
    if opened <= 0:
        return Decimal('1.00')
    safe_tiles = MinesView.TILE_COUNT - mines
    multiplier = (Decimal(str(MinesView.TILE_COUNT)) / Decimal(str(safe_tiles))) ** opened
    multiplier *= Decimal('0.96')
    return multiplier.quantize(Decimal('0.01'), rounding=ROUND_DOWN)

def mines_embed(game: MinesGame) -> discord.Embed:
    current = mines_multiplier(game.mines, len(game.opened))
    payout = (game.amount * current).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
    embed = base_embed(title='## Mines', description=f'**Bet:** {money(game.amount)}\n**Mines:** {game.mines}\n**Opened:** {len(game.opened)}/{MinesView.TILE_COUNT - game.mines}\n**Multiplier:** {current:.2f}x\n**Current Payout:** {money(payout)}', color=58998)
    embed.add_field(name='Game', value=f'`#{game.game_id}`', inline=True)
    embed.add_field(name='Provably Fair', value=f'Server Hash: `{game.server_hash}`', inline=False)
    return embed

async def mines_click(self, interaction: discord.Interaction, game: MinesGame, index: int, view: MinesView):
    if game.finished:
        await interaction.response.send_message(embed=base_embed(description='This Mines game has ended.', color=2829617), ephemeral=True)
        return
    if index in game.opened:
        await interaction.response.send_message(embed=base_embed(description='That tile is already open.', color=2829617), ephemeral=True)
        return
    game.opened.add(index)
    button = next((item for item in view.children if getattr(item, 'custom_id', None) == f'mine:{index}'), None)
    if index in game.bombs:
        game.finished = True
        for item in view.children:
            custom_id = getattr(item, 'custom_id', '')
            if custom_id.startswith('mine:'):
                tile_index = int(custom_id.split(':')[1])
                item.disabled = True
                if tile_index in game.bombs:
                    item.label = '💣'
                    item.style = discord.ButtonStyle.danger
                elif tile_index in game.opened:
                    item.label = '💎'
                    item.style = discord.ButtonStyle.success
        await bot.settle_loss(game.user_id, game.amount, 'mines')
        embed = base_embed(title='## Mines — Bomb!', description=f'You hit a bomb.\n\n**Bet:** {money(game.amount)}\n**Lost:** {money(game.amount)}', color=15548997)
        embed.add_field(name='Game', value=f'`#{game.game_id}`', inline=True)
        embed.add_field(name='Server Hash', value=f'`{game.server_hash}`', inline=False)
        bot.active_mines.pop(game.user_id, None)
        await interaction.response.edit_message(embed=embed, view=view)
        return
    if button:
        button.label = '💎'
        button.style = discord.ButtonStyle.success
        button.disabled = True
    safe_tiles = MinesView.TILE_COUNT - game.mines
    if len(game.opened) >= safe_tiles:
        await mines_cashout(self, interaction, game, view, automatic=True)
        return
    await interaction.response.edit_message(embed=mines_embed(game), view=view)

async def mines_cashout(self, interaction: discord.Interaction, game: MinesGame, view: MinesView, automatic: bool=False):
    if game.finished:
        await interaction.response.send_message(embed=base_embed(description='This Mines game has already ended.', color=2829617), ephemeral=True)
        return
    if len(game.opened) <= 0:
        await interaction.response.send_message(embed=base_embed(description='Open at least one tile before cashing out.', color=2829617), ephemeral=True)
        return
    game.finished = True
    multiplier = mines_multiplier(game.mines, len(game.opened))
    payout = (game.amount * multiplier).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
    await bot.settle_win(game.user_id, game.amount, payout, 'mines')
    for item in view.children:
        custom_id = getattr(item, 'custom_id', '')
        if custom_id.startswith('mine:'):
            tile_index = int(custom_id.split(':')[1])
            item.disabled = True
            if tile_index in game.bombs:
                item.label = '💣'
                item.style = discord.ButtonStyle.danger
            elif tile_index in game.opened:
                item.label = '💎'
                item.style = discord.ButtonStyle.success
    bot.active_mines.pop(game.user_id, None)
    embed = base_embed(title='## Mines — Cashed Out', description=f'**Bet:** {money(game.amount)}\n**Multiplier:** {multiplier:.2f}x\n**Payout:** {money(payout)}', color=5763719)
    embed.add_field(name='Tiles Opened', value=str(len(game.opened)), inline=True)
    embed.add_field(name='Game', value=f'`#{game.game_id}`', inline=True)
    embed.add_field(name='Provably Fair', value=f'Server Hash: `{game.server_hash}`\nClient Seed: `{game.client_seed}`\nNonce: `{game.nonce}`', inline=False)
    if automatic:
        embed.title = '## Mines — All Safe Tiles!'
    await interaction.response.edit_message(embed=embed, view=view)
CasinoBot.mines_click = mines_click
CasinoBot.mines_cashout = mines_cashout

async def get_verified_role(guild: discord.Guild) -> Optional[discord.Role]:
    role_id = getattr(config, 'RAIN_ROLE_ID', 0)
    if not role_id:
        return None
    return guild.get_role(role_id)

async def user_can_join_rain(guild: discord.Guild, member: discord.Member) -> tuple[bool, str]:
    role = await get_verified_role(guild)
    if role is not None:
        if role not in member.roles:
            return (False, 'You need the verified role to join Rain.')
    try:
        row = await bot.db.user(member.id)
        wagered = D(row['wagered']) if row else Decimal('0')
    except Exception:
        wagered = Decimal('0')
    if wagered < Decimal('1'):
        return (False, 'You need at least **$1 wagered** to join Rain.')
    return (True, '')

async def join_rain(self, interaction: discord.Interaction, rain_id: str):
    rain_data = self.active_rains.get(rain_id)
    if not rain_data:
        await interaction.response.send_message(embed=base_embed(description='This Rain has already ended.', color=2829617), ephemeral=True)
        return
    if interaction.guild is None:
        await interaction.response.send_message(embed=base_embed(description='Rain is only available in servers.', color=2829617), ephemeral=True)
        return
    if interaction.user.id in rain_data['users']:
        await interaction.response.send_message(embed=base_embed(description='You already joined this Rain.', color=2829617), ephemeral=True)
        return
    member = interaction.guild.get_member(interaction.user.id)
    if member is None:
        await interaction.response.send_message(embed=base_embed(description='You must be a server member to join.', color=2829617), ephemeral=True)
        return
    allowed, reason = await user_can_join_rain(interaction.guild, member)
    if not allowed:
        await interaction.response.send_message(embed=base_embed(description=reason, color=2829617), ephemeral=True)
        return
    rain_data['users'].add(interaction.user.id)
    await interaction.response.send_message(embed=base_embed(description='You joined the Rain!', color=2829617), ephemeral=True)

async def finish_rain(rain_id: str):
    await asyncio.sleep(RAIN_DURATIONS[bot.active_rains[rain_id]['duration']])
    rain_data = bot.active_rains.pop(rain_id, None)
    if not rain_data:
        return
    users = list(rain_data['users'])
    amount = D(rain_data['amount'])
    channel = bot.get_channel(rain_data['channel_id'])
    if not users:
        await bot.db.change_balance(rain_data['host_id'], amount, kind='rain_refund', note=rain_id)
        if channel:
            await channel.send(embed=base_embed(title=f'## Rain Ended — {money(amount)}', description=f'Nobody joined the Rain.\n{money(amount)} was refunded.', color=15548997))
        return
    share = (amount / Decimal(str(len(users)))).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
    distributed = share * Decimal(str(len(users)))
    remainder = (amount - distributed).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
    for index, user_id in enumerate(users):
        payout = share
        if index == 0:
            payout += remainder
        if payout <= 0:
            continue
        await bot.db.change_balance(user_id, payout, kind='rain', note=rain_id)
    host = bot.get_user(rain_data['host_id'])
    host_name = host.display_name if host else 'User'
    description = f'## **{host_name}** rained on **{len(users)}** players — **{money(share)}** each!\n\n'
    names = []
    for user_id in users:
        member = channel.guild.get_member(user_id) if channel and hasattr(channel, 'guild') else None
        if member:
            names.append(member.display_name)
    if names:
        shown = names[:10]
        description += ', '.join((f'**{name}**' for name in shown))
        if len(names) > 10:
            description += f' **+{len(names) - 10} more**'
    if channel:
        await channel.send(embed=base_embed(title=f'## Rain Ended — {money(amount)}', description=description, color=5763719))
CasinoBot.join_rain = join_rain

@bot.tree.command(name='balance', description='View your wallet balance.')
async def balance(interaction: discord.Interaction):
    balance_value = await bot.get_balance(interaction.user.id)
    embed = base_embed(description=f"## {interaction.user.display_name}'s Wallet\n\n**Balance:** {money(balance_value)}", color=58998)
    await interaction.response.send_message(embed=embed, view=WalletView(bot, interaction.user.id))

@bot.tree.command(name='deposit', description='Get a cryptocurrency deposit address.')
@app_commands.describe(currency='Currency to deposit.')
@app_commands.choices(currency=[app_commands.Choice(name='LTC', value='LTC'), app_commands.Choice(name='SOL', value='SOL')])
async def deposit(interaction: discord.Interaction, currency: Optional[app_commands.Choice[str]]=None):
    if currency:
        await bot.send_deposit_dm(interaction, currency.value)
        return
    await interaction.response.send_message(embed=base_embed(description='Choose a currency Below', color=2829617), view=DepositCurrencyView(bot, interaction.user.id), ephemeral=True)

@bot.tree.command(name='withdraw', description='Withdraw your balance.')
async def withdraw(interaction: discord.Interaction):
    await interaction.response.send_modal(WithdrawModal(bot, interaction.user.id))
HELP_TEXT = '\n## Games\n`/dice` `/roll`\n`/coinflip`\n`/mines`\n`/frog-run`\n`/bj` `/blackjack`\n\n## Wallet\n`/balance`\n`/deposit`\n`/withdraw`\n`/tip`\n\n## Rewards\n`/rakeback`\n`/ranks`\n`/rank-rewards`\n`/rewardinfo`\n\n## Rain & Affiliates\n`/rain`\n`/affiliate`\n`/affiliates`\n`/affiliate-claim`\n`/affiliateinfo`\n\n## Competition\n`/leaderboard`\n`/race`\n\n## Information\n`/howtoplay`\n`/stats`\n`/history`\n`/fair`\n`/provably-fair`\n\n## Other\n`/claim`\n`/private-channel`\n`/retrigger`\n`/fix-dice`\n'

@bot.tree.command(name='help', description='View available commands.')
async def help_command(interaction: discord.Interaction):
    await interaction.response.send_message(embed=base_embed(title='Help', description=HELP_TEXT, color=58998))

@bot.tree.command(name='howtoplay', description='Learn how to use the casino.')
async def howtoplay(interaction: discord.Interaction):
    text = '\n## How To Play\n\n### Fund Your Account\nUse `/deposit` to fund your wallet.\n\nSupported cryptocurrency systems include:\n**LTC · ETH · USDT · SOL**\n\nDeposits are credited only after blockchain confirmation.\n\n### Dice\nUse `/dice <amount>` to create a Dice game.\n\nChoose:\n- Normal Dice\n- Crazy Dice\n- 1 Dice\n- 2 Dice\n- 3 Dice\n\nThen use `/roll`.\n\nNormal Dice uses the highest total.\nCrazy Dice uses the lowest total.\n\n### Coinflip\nUse:\n\n`/coinflip <amount> <red/blue>`\n\nChoose **Red** or **Blue**.\n\nWinning pays **1.92x**.\n\n### Mines\nUse:\n\n`/mines <amount> <mines>`\n\nChoose up to **20 mines**.\n\nOpen tiles to increase your multiplier.\nCash out before hitting a mine.\n\n### Frog Run\nUse `/frog-run` to start a Frog Run game.\n\nAdvance through the board while avoiding losing positions.\nCash out before the run ends.\n\n### Blackjack\nUse:\n\n`/bj <amount>`\n\nOptional side bets:\n- 21+3\n- Perfect Pairs\n\nNormal Blackjack rules apply.\n\nInsurance is available when applicable.\n\nGames automatically stand after one hour.\n\nUse `/retrigger` if your game needs to be restored.\n\n### Withdraw\nUse `/withdraw` to request a withdrawal.\n\n### Rain\nRain distributes crypto/points to eligible verified players.\n\nYou must have the required verified role and have wagered at least **$1 during the required daily period**.\n\n### Private Channels\nPrivate channels require at least **$25 balance**.\n\nChannels automatically close if the balance remains below $25 for 10 minutes.\n\n### Provably Fair\nEvery supported game uses a server seed, client seed and nonce.\n\nUse `/provably-fair` to inspect game information.\n'
    await interaction.response.send_message(embed=base_embed(title='How To Play', description=text, color=58998))

@bot.tree.command(name='rewardinfo', description='View rewards and perks.')
async def rewardinfo(interaction: discord.Interaction):
    text = "\n## Rewards & Perks\n\n### Rakeback\nReceive **1% rakeback on losses**.\n\nWins do not generate rakeback.\n\nUse `/rakeback` to claim your available amount.\n\n### Ranks\nProgress through wager milestones.\n\nEvery rank can provide a cash reward.\n\nUse `/ranks` to see all stages.\n\n### Affiliates\nAffiliate commission is based on qualifying wager activity.\n\n### Promo Codes\nUse `/claim <code>` to claim an eligible promotional code.\n\n### Wager Race\nCompete for the highest wager during an active race.\n\nUse `/race` to view the current standings.\n\n### Tips & Rain\nUsers can tip each other with `/tip`.\n\nRain events can distribute funds to eligible verified players.\n\n### Deposit Bonuses\nPromotional deposit bonuses may include:\n- 50%\n- 100%\n- 200%\n\nPromotions can have wager multipliers and maximum cashout conditions.\n\n### Game Wagering\nGame wagering contributes according to the game's rules.\n\n### Betting Limits\nThe minimum bet is **$0.10**.\n\nPromotional or special games can have their own minimums.\n\n### Restrictions\nWithdrawal, tipping and PvP eligibility can be restricted by active promotions.\n\nAlways check the terms attached to a promotion before using it.\n"
    await interaction.response.send_message(embed=base_embed(title='Rewards & Perks', description=text, color=58998))

@bot.tree.command(name='affiliateinfo', description='View affiliate commission information.')
async def affiliateinfo(interaction: discord.Interaction):
    text = '\n## Affiliate Program\n\nCommission rates:\n\n**1+ referred users** → **0.10%**\n\n**10+ referred users** → **0.20%**\n\n**25+ referred users** → **0.35%**\n\n**100+ referred users** → **0.50%**\n\nUse `/affiliates` to view your affiliate information.\n\nUse `/affiliate-claim` to claim available earnings.\n'
    await interaction.response.send_message(embed=base_embed(title='Affiliate Info', description=text, color=58998))

@bot.tree.command(name='stats', description='View your statistics.')
async def stats(interaction: discord.Interaction):
    row = await bot.get_db_user(interaction.user.id)
    balance_value = D(row['balance'])
    wagered = D(row['wagered'])
    deposited = D(row['lifetime_deposit'])
    withdrawn = D(row['total_withdrawn']) if 'total_withdrawn' in row else Decimal('0')
    rank_index = bot.get_rank_index(wagered)
    current_rank = RANKS[rank_index]
    if rank_index + 1 < len(RANKS):
        next_rank = RANKS[rank_index + 1]
        remaining = max(Decimal('0'), next_rank['wager'] - wagered)
        next_stage = f'wager {money(remaining)} more to reach **{bot.rank_label(next_rank)}**'
    else:
        next_stage = 'Maximum rank reached'
    await interaction.response.send_message(embed=base_embed(description=f"## {interaction.user.display_name}'s Stats\n\n**Balance:** {money(balance_value)}\n**Rank:** **{bot.rank_label(current_rank)}** · {rank_index + 1}/{len(RANKS)} stages\n**Total Wagered:** {money(wagered)}\n**Total Deposited:** {money(deposited)}\n**Total Withdrawn:** {money(withdrawn)}\n**Next Stage:** {next_stage}"))

def _rank_index(self, wagered: Decimal) -> int:
    result = 0
    for index, rank in enumerate(RANKS):
        if wagered >= rank['wager']:
            result = index
    return result

def _rank_label(self, rank: dict) -> str:
    if rank['stage']:
        return f"{rank['name']} Stage {rank['stage']}"
    return rank['name']
CasinoBot.get_rank_index = _rank_index
CasinoBot.rank_label = _rank_label

@bot.tree.command(name='ranks', description='View all rank stages.')
async def ranks(interaction: discord.Interaction):
    lines = ['## Rank Progression', '']
    for rank in RANKS:
        lines.append(f"**{bot.rank_label(rank)}** — wager {money(rank['wager'])} — reward {money(rank['reward'])}")
    await interaction.response.send_message(embed=base_embed(description='\n'.join(lines)))

@bot.tree.command(name='rakeback', description='Claim your available 1% loss rakeback.')
async def rakeback(interaction: discord.Interaction):
    row = await bot.get_db_user(interaction.user.id)
    available = D(row['rakeback'])
    if available <= 0:
        await interaction.response.send_message(embed=base_embed(description='You Dont have any rakeback avalable . try again later', color=2829617), ephemeral=True)
        return
    if hasattr(bot.db, 'claim_rakeback'):
        amount = D(await bot.db.claim_rakeback(interaction.user.id))
    else:
        amount = available
        await bot.db.pool.execute('\n            UPDATE users\n            SET rakeback = 0\n            WHERE user_id = $1\n            ', interaction.user.id)
    if amount <= 0:
        await interaction.response.send_message(embed=base_embed(description='You Dont have any rakeback avalable . try again later', color=2829617), ephemeral=True)
        return
    await bot.db.change_balance(interaction.user.id, amount, kind='rakeback', note='1% loss rakeback')
    await interaction.response.send_message(embed=success_embed('Rakeback Claimed', f'You received **{money(amount)}**.'))

@bot.tree.command(name='affiliate', description='View your affiliate information.')
async def affiliate(interaction: discord.Interaction):
    user_id = interaction.user.id
    if hasattr(bot.db, 'affiliate_stats'):
        data = await bot.db.affiliate_stats(user_id)
        referrals = int(data.get('referrals', 0))
        earnings = D(data.get('earnings', 0))
        commission = D(data.get('rate', 0))
    else:
        referrals = 0
        earnings = Decimal('0')
        commission = Decimal('0')
    percent = commission * Decimal('100')
    await interaction.response.send_message(embed=base_embed(description=f'## Affiliate\n\n**Referrals:** {referrals}\n**Commission:** {percent:.2f}%\n**Available:** {money(earnings)}'))

@bot.tree.command(name='affiliates', description='View your affiliate dashboard.')
async def affiliates(interaction: discord.Interaction):
    await affiliate.callback(interaction)

@bot.tree.command(name='affiliate-claim', description='Claim your affiliate earnings.')
async def affiliate_claim(interaction: discord.Interaction):
    if hasattr(bot.db, 'claim_affiliate'):
        amount = D(await bot.db.claim_affiliate(interaction.user.id))
    else:
        amount = Decimal('0')
    if amount <= 0:
        await interaction.response.send_message(embed=base_embed(description='You have $0 to claim.', color=2829617), ephemeral=True)
        return
    await bot.db.change_balance(interaction.user.id, amount, kind='affiliate', note='Affiliate claim')
    await interaction.response.send_message(embed=success_embed('Affiliate Claimed', f'You received **{money(amount)}**.'))

@bot.tree.command(name='tip', description='Tip another user.')
@app_commands.describe(user='User receiving the tip.', amount='Amount to tip.')
async def tip(interaction: discord.Interaction, user: discord.Member, amount: str):
    if user.id == interaction.user.id:
        await interaction.response.send_message(embed=base_embed(description='You cannot tip yourself.', color=2829617), ephemeral=True)
        return
    value = normalize_amount(amount)
    if value is None:
        await interaction.response.send_message(embed=base_embed(description='Enter a valid amount.', color=2829617), ephemeral=True)
        return
    if value < Decimal('0.01'):
        await interaction.response.send_message(embed=base_embed(description='Minimum tip is $0.01.', color=2829617), ephemeral=True)
        return
    success = await bot.db.change_balance(interaction.user.id, -value, kind='tip_sent', note=str(user.id))
    if not success:
        await interaction.response.send_message(embed=base_embed(description='You Dont Have Enough Crypto', color=2829617), ephemeral=True)
        return
    await bot.db.change_balance(user.id, value, kind='tip_received', note=str(interaction.user.id))
    await interaction.response.send_message(embed=base_embed(description=f'**{interaction.user.display_name}** tipped **{user.display_name}** **{money(value)}**.', color=2829617))

@bot.tree.command(name='leaderboard', description='View the top wagerers.')
async def leaderboard(interaction: discord.Interaction):
    rows = await bot.db.leaderboard()
    lines = ['## Top Wagerers', 'Top 10 by total wagered', '']
    for row in rows:
        member = interaction.guild.get_member(int(row['user_id'])) if interaction.guild else None
        if member:
            name = member.mention
        else:
            name = f"<@{row['user_id']}>"
        lines.append(f"{name}: {money(row['wagered'])}")
    if len(rows) == 0:
        lines.append('No wager history yet.')
    await interaction.response.send_message(embed=base_embed(description='\n'.join(lines)))

async def send_race_message(interaction: discord.Interaction):
    ongoing = await bot.db.setting('race_active', '0')
    rows = []
    if ongoing == '1':
        if hasattr(bot.db, 'race_leaderboard'):
            rows = await bot.db.race_leaderboard(3)
        lines = ['## 3 Day Race — On GOING', '']
        for row in rows:
            lines.append(f"<@{row['user_id']}> : {money(row['wagered'])} wagared")
        if not rows:
            lines.append('No wagerers yet.')
    else:
        if hasattr(bot.db, 'race_winners'):
            rows = await bot.db.race_winners(3)
        lines = ['## 3 Day Race — Winners!', '']
        prizes = [Decimal('70'), Decimal('50'), Decimal('30')]
        for index, row in enumerate(rows[:3]):
            prize = prizes[index]
            lines.append(f"**{index + 1}.** <@{row['user_id']}> — {money(prize)}")
        lines.extend(['', 'Winners Open Ticket'])
    await interaction.response.send_message(embed=base_embed(description='\n'.join(lines)))

@bot.tree.command(name='race', description='View the current wager race.')
async def race(interaction: discord.Interaction):
    await send_race_message(interaction)

def owner_only():

    async def predicate(interaction: discord.Interaction):
        if interaction.user.id not in config.ADMIN_USER_IDS:
            raise app_commands.CheckFailure('Owner only')
        return True
    return app_commands.check(predicate)
race_group = app_commands.Group(name='raceadmin', description='Race administration.')

@race_group.command(name='start', description='Start a new wager race.')
@owner_only()
async def race_start(interaction: discord.Interaction):
    await bot.db.set_setting('race_active', '1')
    if hasattr(bot.db, 'reset_race'):
        await bot.db.reset_race()
    await interaction.response.send_message(embed=base_embed(description='## 3 Day Race — Started\n\nThe wager race has started.', color=2829617))

@race_group.command(name='end', description='End the current wager race.')
@owner_only()
async def race_end(interaction: discord.Interaction):
    if hasattr(bot.db, 'finish_race'):
        await bot.db.finish_race()
    await bot.db.set_setting('race_active', '0')
    await interaction.response.send_message(embed=base_embed(description='## 3 Day Race — Ended\n\nWinners are now available through `/race`.', color=2829617))
bot.tree.add_command(race_group)

@bot.tree.command(name='retrigger', description='Restore a recoverable unfinished game.')
async def retrigger(interaction: discord.Interaction):
    user_id = interaction.user.id
    game = bot.active_games.get(user_id)
    if game:
        await interaction.response.send_message(embed=base_embed(description='Your active game has been restored.', color=2829617), ephemeral=True)
        return
    if user_id in bot.active_mines:
        await interaction.response.send_message(embed=base_embed(description='Your Mines game is still active.', color=2829617), ephemeral=True)
        return
    if user_id in bot.active_dice:
        await interaction.response.send_message(embed=base_embed(description='Your Dice game is still active.', color=2829617), ephemeral=True)
        return
    await interaction.response.send_message(embed=base_embed(description='No recoverable game was found.', color=2829617), ephemeral=True)

@bot.tree.command(name='fix-dice', description='Recover an interrupted dice game.')
async def fix_dice(interaction: discord.Interaction):
    game = bot.active_dice.get(interaction.user.id)
    if not game:
        await interaction.response.send_message(embed=base_embed(description='No active Dice game was found.', color=2829617), ephemeral=True)
        return
    await interaction.response.send_message(embed=base_embed(description='Your active Dice game is available again.', color=2829617), ephemeral=True)

class PrivateChannelView(ButtonView):

    def __init__(self, bot_instance: CasinoBot, owner_id: int):
        super().__init__(timeout=600)
        self.bot = bot_instance
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(embed=base_embed(description='Only the channel owner can use these controls.', color=2829617), ephemeral=True)
            return False
        return True

    @discord.ui.button(label='Add Member', style=discord.ButtonStyle.success)
    async def add_member(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PrivateMemberModal(self.bot, interaction.channel.id, add=True))

    @discord.ui.button(label='Remove Member', style=discord.ButtonStyle.secondary)
    async def remove_member(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PrivateMemberModal(self.bot, interaction.channel.id, add=False))

    @discord.ui.button(label='Delete', style=discord.ButtonStyle.danger)
    async def delete_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = interaction.channel
        await interaction.response.send_message(embed=base_embed(description='Deleting this private channel.', color=2829617), ephemeral=True)
        await channel.delete(reason='Private channel deleted by owner.')

class PrivateMemberModal(discord.ui.Modal):

    def __init__(self, bot_instance: CasinoBot, channel_id: int, add: bool):
        super().__init__(title='Add Member' if add else 'Remove Member')
        self.bot = bot_instance
        self.channel_id = channel_id
        self.add_member_mode = add
        self.user_id_input = discord.ui.TextInput(label='User ID', placeholder='Discord user ID', required=True, max_length=25)
        self.add_item(self.user_id_input)

    async def on_submit(self, interaction: discord.Interaction):
        channel = interaction.guild.get_channel(self.channel_id)
        if not channel:
            await interaction.response.send_message(embed=base_embed(description='Channel not found.', color=2829617), ephemeral=True)
            return
        try:
            user_id = int(self.user_id_input.value.strip())
        except ValueError:
            await interaction.response.send_message(embed=base_embed(description='Invalid user ID.', color=2829617), ephemeral=True)
            return
        member = interaction.guild.get_member(user_id)
        if not member:
            try:
                member = await interaction.guild.fetch_member(user_id)
            except discord.HTTPException:
                await interaction.response.send_message(embed=base_embed(description='Member not found.', color=2829617), ephemeral=True)
                return
        overwrite = channel.overwrites_for(member)
        overwrite.view_channel = self.add_member_mode
        await channel.set_permissions(member, overwrite=overwrite)
        await interaction.response.send_message(embed=base_embed(description=f'{member.mention} was added.' if self.add_member_mode else f'{member.mention} was removed.', color=2829617), ephemeral=True)

@bot.tree.command(name='private-channel', description='Create a private channel.')
async def private_channel(interaction: discord.Interaction):
    balance_value = await bot.get_balance(interaction.user.id)
    if balance_value < Decimal('25'):
        await interaction.response.send_message(embed=base_embed(description='You need at least **$25.00** balance to create a private channel.', color=2829617), ephemeral=True)
        return
    guild = interaction.guild
    if guild is None:
        await interaction.response.send_message(embed=base_embed(description='This command can only be used in a server.', color=2829617), ephemeral=True)
        return
    category = interaction.channel.category
    overwrites = {guild.default_role: discord.PermissionOverwrite(view_channel=False), interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)}
    channel = await guild.create_text_channel(name=f'private-{interaction.user.name}', category=category, overwrites=overwrites, reason='Private channel created.')
    await channel.send(embed=base_embed(description=f'## Private Channel\nOwner: {interaction.user.mention}\n\nThis channel requires a **$25 balance**.\nIf your balance stays below $25 for 10 minutes, the channel may be closed.', color=2829617), view=PrivateChannelView(bot, interaction.user.id))
    await interaction.response.send_message(embed=base_embed(description=f'Private channel created: {channel.mention}', color=2829617), ephemeral=True)

@tasks.loop(minutes=1)
async def private_channel_monitor():
    if not bot.db:
        return
    for guild in bot.guilds:
        for channel in guild.text_channels:
            if not channel.name.startswith('private-'):
                continue
            owner_id = None
            try:
                owner_name = channel.name[len('private-'):]
                member = discord.utils.find(lambda m: m.name == owner_name and m.guild.id == guild.id, guild.members)
                if member:
                    owner_id = member.id
            except Exception:
                continue
            if not owner_id:
                continue
            balance_value = await bot.get_balance(owner_id)
            if balance_value >= Decimal('25'):
                continue
            marker = f'private_low_balance:{channel.id}'
            since = await bot.db.setting(marker, '')
            if not since:
                await bot.db.set_setting(marker, datetime.now(timezone.utc).isoformat())
                continue
            try:
                started = datetime.fromisoformat(since)
                elapsed = (datetime.now(timezone.utc) - started).total_seconds()
            except Exception:
                elapsed = 0
            if elapsed >= 600:
                try:
                    await channel.delete(reason='Private channel balance below $25 for 10 minutes.')
                except discord.HTTPException:
                    pass

@bot.tree.command(name='claim', description='Claim a promo code.')
@app_commands.describe(code='Promo code.')
async def claim(interaction: discord.Interaction, code: str):
    code = code.strip().upper()
    if hasattr(bot.db, 'claim_code'):
        result = await bot.db.claim_code(interaction.user.id, code)
        if not result:
            await interaction.response.send_message(embed=base_embed(description='That code is invalid, expired, or already claimed.', color=2829617), ephemeral=True)
            return
        amount = D(result['amount'])
    else:
        row = await bot.db.pool.fetchrow('\n            SELECT\n                code,\n                amount,\n                max_uses,\n                uses,\n                active\n            FROM codes\n            WHERE code = $1\n            ', code)
        if not row:
            await interaction.response.send_message(embed=base_embed(description='Invalid promo code.', color=2829617), ephemeral=True)
            return
        if not row['active'] or row['uses'] >= row['max_uses']:
            await interaction.response.send_message(embed=base_embed(description='That code has expired.', color=2829617), ephemeral=True)
            return
        already = await bot.db.pool.fetchval('\n            SELECT 1\n            FROM code_claims\n            WHERE code = $1\n              AND user_id = $2\n            ', code, interaction.user.id)
        if already:
            await interaction.response.send_message(embed=base_embed(description='You already claimed this code.', color=2829617), ephemeral=True)
            return
        amount = D(row['amount'])
        async with bot.db.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute('\n                    INSERT INTO code_claims(\n                        code,\n                        user_id\n                    )\n                    VALUES($1, $2)\n                    ', code, interaction.user.id)
                await conn.execute('\n                    UPDATE codes\n                    SET uses = uses + 1\n                    WHERE code = $1\n                    ', code)
    await bot.db.change_balance(interaction.user.id, amount, kind='promo', note=code)
    await interaction.response.send_message(embed=success_embed('Promo Claimed', f'You received **{money(amount)}**.'))

@bot.tree.command(name='code', description='Create a promotional code.')
@app_commands.describe(amount='Amount each person receives.', max_uses='Maximum number of claims.', requirement='Requirement number: 1, 2, or 3.')
@owner_only()
async def code_command(interaction: discord.Interaction, amount: str, max_uses: int, requirement: int):
    value = normalize_amount(amount)
    if value is None:
        await interaction.response.send_message(embed=base_embed(description='Invalid amount.', color=2829617), ephemeral=True)
        return
    if max_uses <= 0:
        await interaction.response.send_message(embed=base_embed(description='Max uses must be greater than zero.', color=2829617), ephemeral=True)
        return
    if requirement not in CODE_REQUIREMENTS:
        await interaction.response.send_message(embed=base_embed(description='Requirement must be 1, 2, or 3.', color=2829617), ephemeral=True)
        return
    code = 'GOOSE-' + ''.join((secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8)))
    await bot.db.pool.execute('\n        INSERT INTO codes(\n            code,\n            max_uses,\n            amount\n        )\n        VALUES($1, $2, $3)\n        ', code, max_uses, value)
    requirement_data = CODE_REQUIREMENTS[requirement]
    await interaction.response.send_message(embed=success_embed('Promo Code Created', f"**Code:** `{code}`\n**Amount:** {money(value)} per person\n**Max Uses:** {max_uses}\n**Requirement:** {requirement_data['name']}"), ephemeral=True)

@bot.tree.command(name='rain', description='Start a rain event.')
@app_commands.describe(amount='Total amount to rain.', duration='Duration in minutes: 1, 2, 5 or 10.')
@app_commands.choices(duration=[app_commands.Choice(name='1 minute', value=1), app_commands.Choice(name='2 minutes', value=2), app_commands.Choice(name='5 minutes', value=5), app_commands.Choice(name='10 minutes', value=10)])
async def rain(interaction: discord.Interaction, amount: str, duration: app_commands.Choice[int]):
    value = normalize_amount(amount)
    if value is None:
        await interaction.response.send_message(embed=base_embed(description='Enter a valid amount.', color=2829617), ephemeral=True)
        return
    if value < MIN_BET:
        await interaction.response.send_message(embed=base_embed(description='Rain amount must be at least $0.10.', color=2829617), ephemeral=True)
        return
    success = await bot.db.change_balance(interaction.user.id, -value, kind='rain_start', note='rain')
    if not success:
        await interaction.response.send_message(embed=base_embed(description='You Dont Have Enough Crypto\n-# use /deposit to top-up Funds', color=2829617), ephemeral=True)
        return
    rain_id = secrets.token_hex(12)
    bot.active_rains[rain_id] = {'owner_id': interaction.user.id, 'amount': value, 'duration': duration.value, 'joined': set(), 'started': time.monotonic(), 'channel_id': interaction.channel.id, 'refunded': False}
    view = RainView(bot, rain_id)
    await interaction.response.send_message(embed=base_embed(description=f'## Rain Started — **{money(value)}**\n\n**{interaction.user.mention}** rained — **{money(value)}**\n\nClick on Button Below to Join', color=2829617), view=view)
    asyncio.create_task(bot.finish_rain(rain_id, interaction.channel.id))

async def _join_rain(self, interaction: discord.Interaction, rain_id: str):
    rain_data = self.active_rains.get(rain_id)
    if not rain_data:
        await interaction.response.send_message(embed=base_embed(description='This rain has ended.', color=2829617), ephemeral=True)
        return
    if interaction.user.id == rain_data['owner_id']:
        await interaction.response.send_message(embed=base_embed(description='The rain creator cannot join their own rain.', color=2829617), ephemeral=True)
        return
    role_id = getattr(config, 'RAIN_ROLE_ID', 0)
    if role_id:
        role = interaction.guild.get_role(role_id)
        if role and role not in interaction.user.roles:
            await interaction.response.send_message(embed=base_embed(description='You need the verified role to join rain.', color=2829617), ephemeral=True)
            return
    if hasattr(self.db, 'daily_wager'):
        wagered = D(await self.db.daily_wager(interaction.user.id))
    else:
        wagered = Decimal('1')
    if wagered < Decimal('1'):
        await interaction.response.send_message(embed=base_embed(description='You must wager at least **$1 today** to join rain.', color=2829617), ephemeral=True)
        return
    if interaction.user.id in rain_data['joined']:
        await interaction.response.send_message(embed=base_embed(description='You already joined this rain.', color=2829617), ephemeral=True)
        return
    rain_data['joined'].add(interaction.user.id)
    await interaction.response.send_message(embed=base_embed(description='You joined the rain!', color=2829617), ephemeral=True)
CasinoBot.join_rain = _join_rain

async def _finish_rain(self, rain_id: str, channel_id: int):
    rain_data = self.active_rains.get(rain_id)
    if not rain_data:
        return
    await asyncio.sleep(RAIN_DURATIONS.get(rain_data['duration'], 60))
    joined = list(rain_data['joined'])
    total = D(rain_data['amount'])
    channel = self.get_channel(channel_id)
    if not joined:
        await self.db.change_balance(rain_data['owner_id'], total, kind='rain_refund', note='No rain participants')
        if channel:
            await channel.send(embed=base_embed(description=f'## Rain Ended — **{money(total)}**\n\nNobody joined the rain.\nThe full amount was refunded.', color=2829617))
        self.active_rains.pop(rain_id, None)
        return
    share = (total / Decimal(len(joined))).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
    distributed = Decimal('0')
    for user_id in joined:
        if share <= 0:
            continue
        await self.db.change_balance(user_id, share, kind='rain', note=rain_id)
        distributed += share
    remainder = total - distributed
    if remainder > 0:
        await self.db.change_balance(rain_data['owner_id'], remainder, kind='rain_remainder', note=rain_id)
    if channel:
        mentions = ' '.join((f'<@{uid}>' for uid in joined))
        owner = self.get_user(rain_data['owner_id'])
        if owner:
            owner_mention = owner.mention
        else:
            owner_mention = f"<@{rain_data['owner_id']}>"
        await channel.send(embed=base_embed(description=f'## Rain Ended — **{money(total)}**\n\n## **{owner_mention}** rained on **{len(joined)}** players — **{money(share)}** each!\n\n{mentions}', color=2829617))
    self.active_rains.pop(rain_id, None)
CasinoBot.finish_rain = _finish_rain

class FrogRunView(ButtonView):
    ROWS = 6
    LANES = 3

    def __init__(self, bot_instance: CasinoBot, user_id: int, amount: Decimal, game_id: int):
        super().__init__(timeout=300)
        self.bot = bot_instance
        self.user_id = user_id
        self.amount = amount
        self.game_id = game_id
        self.position = 0
        self.multiplier = Decimal('1.00')
        self.finished = False
        self.losing_lanes: dict[int, int] = {}
        self.chosen_lanes: dict[int, int] = {}
        self._build_buttons()

    def board_text(self) -> str:
        rows = []
        for row in range(self.ROWS - 1, -1, -1):
            if row >= self.position:
                rows.append('🟫 🟫 🟫')
                continue
            losing = self.losing_lanes.get(row)
            chosen = self.chosen_lanes.get(row)
            cells = []
            for lane in range(self.LANES):
                if lane == chosen:
                    cells.append('🐸')
                elif lane == losing:
                    cells.append('🟥')
                else:
                    cells.append('🟩')
            rows.append(' '.join(cells))
        if self.finished and self.position >= self.ROWS:
            frog_line = '🐸'
        elif self.position == 0:
            frog_line = '     🐸'
        else:
            frog_line = '     🐸'
        return '\n'.join(rows) + '\n' + frog_line

    def board_embed(self, title: str='Frog Jump', color: int=2829617, extra: str='') -> discord.Embed:
        embed = base_embed(title=title, description=f'```{self.board_text()}```\n**Bet:** {money(self.amount)}\n**Stage:** {min(self.position, self.ROWS)}/{self.ROWS}\n**Multiplier:** {self.multiplier:.2f}x\n**Current Payout:** {money(self.amount * self.multiplier)}{extra}', color=color)
        embed.set_footer(text=f'Game #{self.game_id} • Pick a lane')
        return embed

    def _build_buttons(self):
        self.clear_items()
        for lane in range(self.LANES):
            button = discord.ui.Button(label=f'Jump {lane + 1}', style=discord.ButtonStyle.secondary, custom_id=f'frog:{lane}', row=0)
            button.callback = self.make_callback(lane)
            self.add_item(button)
        cashout = discord.ui.Button(label='Cashout', style=discord.ButtonStyle.success, custom_id='frog_cashout', row=0)
        cashout.callback = self.cashout
        self.add_item(cashout)

    def make_callback(self, lane: int):

        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message(embed=error_embed('Frog Jump', 'This game belongs to another player.'), ephemeral=True)
                return
            await self.bot.frog_step(interaction, self, lane)
        return callback

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(embed=error_embed('Frog Jump', 'This game belongs to another player.'), ephemeral=True)
            return False
        return True

    async def cashout(self, interaction: discord.Interaction):
        if self.finished:
            await interaction.response.send_message(embed=error_embed('Frog Jump', 'This game has already ended.'), ephemeral=True)
            return
        if self.position <= 0:
            await interaction.response.send_message(embed=error_embed('Frog Jump', 'Jump at least once before cashing out.'), ephemeral=True)
            return
        self.finished = True
        payout = (self.amount * self.multiplier).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
        await self.bot.settle_win(self.user_id, self.amount, payout, 'frog-jump')
        self.bot.active_games.pop(self.user_id, None)
        for child in self.children:
            child.disabled = True
        embed = self.board_embed('Frog Jump — Cashed Out', 5763719, f'\n\n**Payout:** {money(payout)}')
        await interaction.response.edit_message(embed=embed, view=self)

async def _frog_step(self, interaction: discord.Interaction, view: FrogRunView, lane: int):
    if view.finished:
        await interaction.response.send_message(embed=error_embed('Frog Jump', 'This game has already ended.'), ephemeral=True)
        return
    if view.position >= view.ROWS:
        return
    row = view.position
    losing_lane = random.randrange(view.LANES)
    view.losing_lanes[row] = losing_lane
    if lane == losing_lane:
        view.finished = True
        view.chosen_lanes[row] = lane
        for child in view.children:
            child.disabled = True
        await self.settle_loss(view.user_id, view.amount, 'frog-jump')
        self.active_games.pop(view.user_id, None)
        embed = view.board_embed('Frog Jump — Lost', 15548997, f'\n\n🟥 You landed on the losing tile.\n**Lost:** {money(view.amount)}')
        await interaction.response.edit_message(embed=embed, view=view)
        return
    view.chosen_lanes[row] = lane
    view.position += 1
    view.multiplier = (Decimal('1.20') ** view.position).quantize(Decimal('0.01'))
    if view.position >= view.ROWS:
        view.finished = True
        payout = (view.amount * view.multiplier).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
        await self.settle_win(view.user_id, view.amount, payout, 'frog-jump')
        self.active_games.pop(view.user_id, None)
        for child in view.children:
            child.disabled = True
        embed = view.board_embed('Frog Jump — Finished!', 5763719, f'\n\n🟩 All six rows cleared!\n**Payout:** {money(payout)}')
        await interaction.response.edit_message(embed=embed, view=view)
        return
    embed = view.board_embed('Frog Jump', 2829617)
    await interaction.response.edit_message(embed=embed, view=view)
CasinoBot.frog_step = _frog_step

@bot.tree.command(name='frog-jump', description='Play the 6-row Frog Jump game.')
@app_commands.describe(amount='Amount to bet.')
async def frog_jump(interaction: discord.Interaction, amount: str):
    value = normalize_amount(amount)
    if value is None or value < MIN_FROG_BET:
        await interaction.response.send_message(embed=error_embed('Frog Jump', f'Minimum bet is {money(MIN_FROG_BET)}.'), ephemeral=True)
        return
    remaining = bot.check_game_cooldown(interaction.user.id, 'frog-jump')
    if remaining:
        await interaction.response.send_message(embed=error_embed('Frog Jump', f'Please wait **{remaining:.1f}s**.'), ephemeral=True)
        return
    if interaction.user.id in bot.active_games and bot.active_games[interaction.user.id].get('type') == 'frog-jump':
        await interaction.response.send_message(embed=error_embed('Frog Jump', 'You already have an active Frog Jump game.'), ephemeral=True)
        return
    if not await bot.deduct_bet(interaction.user.id, value, 'frog-jump'):
        await interaction.response.send_message(embed=error_embed('Frog Jump', "You don't have enough balance."), ephemeral=True)
        return
    game_id = bot.next_game_id()
    view = FrogRunView(bot, interaction.user.id, value, game_id)
    bot.active_games[interaction.user.id] = {'type': 'frog-jump', 'view': view}
    await interaction.response.send_message(embed=view.board_embed('Frog Jump', 2829617), view=view)
bot.tree.add_command(app_commands.Command(name='frog-run', description='Play Frog Jump.', callback=frog_jump.callback))

@bot.tree.command(name='dice', description='Create a Dice game.')
@app_commands.describe(amount='Amount to bet.')
async def dice(interaction: discord.Interaction, amount: str):
    value = normalize_amount(amount)
    if value is None or value < MIN_BET:
        await interaction.response.send_message(embed=base_embed(description='Minimum bet is **$0.10**.', color=2829617), ephemeral=True)
        return
    balance_value = await bot.get_balance(interaction.user.id)
    if value > balance_value:
        await interaction.response.send_message(embed=base_embed(description='You Dont Have Enough Crypto', color=2829617), ephemeral=True)
        return
    await interaction.response.send_message(embed=base_embed(description='**Choose Dice Mode**\n\n**Crazy Dice**\nLowest Wins\n\n**Dice**\nHighest Wins', color=2829617), view=DiceSetupView(bot, interaction.user.id, value))

async def _start_dice_game(self, interaction: discord.Interaction, user_id: int, amount: Decimal, mode: str, dice_count: int):
    success = await self.deduct_bet(user_id, amount, 'dice')
    if not success:
        await interaction.edit_original_response(content='You Dont Have Enough Crypto', view=None)
        return
    game_id = self.next_game_id()
    server_seed = self.create_server_seed()
    server_hash = self.server_hash(server_seed)
    client_seed = self.create_client_seed(user_id)
    nonce = 0
    self.active_dice[user_id] = {'user_id': user_id, 'amount': amount, 'mode': mode, 'dice_count': dice_count, 'game_id': game_id, 'server_seed': server_seed, 'server_hash': server_hash, 'client_seed': client_seed, 'nonce': nonce, 'player_rolls': [], 'bot_rolls': [], 'message_id': None, 'channel_id': interaction.channel.id}
    mode_name = 'Crazy' if mode == 'crazy' else 'Normal'
    await interaction.edit_original_response(content=f'## Dice - /roll to proceed\n\nMode: **{dice_count} Rolls ({mode_name})** · Bet: **{money(amount)}**\n{interaction.user.mention} vs Bot\n\n{interaction.user.display_name}: ' + ' + '.join(('?' for _ in range(dice_count))) + f' = ?\nBot: ' + ' + '.join(('?' for _ in range(dice_count))) + f' = ?\n\nGame #{game_id} · Provably fair.\nServer hash: `{server_hash}`', view=None)
CasinoBot.start_dice_game = _start_dice_game

@bot.tree.command(name='roll', description='Roll your active Dice game.')
async def roll(interaction: discord.Interaction):
    game = bot.active_dice.get(interaction.user.id)
    if not game:
        await interaction.response.send_message(embed=base_embed(description="You don't have an active Dice game.", color=2829617), ephemeral=True)
        return
    if len(game['player_rolls']) >= game['dice_count']:
        await interaction.response.send_message(embed=base_embed(description='You have already rolled all your dice.', color=2829617), ephemeral=True)
        return
    index = len(game['player_rolls'])
    player_roll = bot.fair_int(game['server_seed'], game['client_seed'], game['nonce'] + index, 1, 6, 'dice-player')
    game['player_rolls'].append(player_roll)
    if len(game['player_rolls']) < game['dice_count']:
        player_text = ' + '.join((str(x) for x in game['player_rolls']))
        player_text += ' + ?'
        await interaction.response.send_message(embed=base_embed(description=f"🎲 You rolled **{player_roll}**\nCurrent total: **{sum(game['player_rolls'])}**", color=2829617))
        return
    game['bot_rolls'] = [bot.fair_int(game['server_seed'], game['client_seed'], game['nonce'] + 100 + i, 1, 6, 'dice-bot') for i in range(game['dice_count'])]
    player_total = sum(game['player_rolls'])
    bot_total = sum(game['bot_rolls'])
    if game['mode'] == 'crazy':
        player_wins = player_total < bot_total
    else:
        player_wins = player_total > bot_total
    if player_total == bot_total:
        result = 'Push'
    elif player_wins:
        result = 'Win'
    else:
        result = 'Loss'
    if result == 'Win':
        payout = (game['amount'] * DICE_MULTIPLIER).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
        await bot.settle_win(game['user_id'], game['amount'], payout, 'dice')
    elif result == 'Loss':
        payout = Decimal('0')
        await bot.settle_loss(game['user_id'], game['amount'], 'dice')
    else:
        payout = game['amount']
        await bot.db.change_balance(game['user_id'], game['amount'], kind='game_push', note='dice')
        await bot.db.record_game(game['user_id'], game['amount'], Decimal('0'), 'dice_push')
    player_values = ' + '.join((str(x) for x in game['player_rolls']))
    bot_values = ' + '.join((str(x) for x in game['bot_rolls']))
    if result == 'Win':
        color = 5763719
    elif result == 'Loss':
        color = 15548997
    else:
        color = 16705372
    await interaction.response.send_message(embed=base_embed(title=f'Dice — {result}!', description=f"**{interaction.user.display_name}:** {player_values} = **{player_total}**\n**Bot:** {bot_values} = **{bot_total}**\n\n**Bet:** {money(game['amount'])}\n**Payout:** {money(payout)}\n\nGame #{game['game_id']}\nServer hash: `{game['server_hash']}`\nClient seed: `{game['client_seed']}`\nNonce: `{game['nonce']}`", color=color))
    bot.active_dice.pop(interaction.user.id, None)

@bot.tree.command(name='mines', description='Play Mines.')
@app_commands.describe(amount='Amount to bet.', mines='Number of mines, 1-20.')
async def mines(interaction: discord.Interaction, amount: str, mines: app_commands.Range[int, 1, 20]):
    user_id = interaction.user.id
    if user_id in bot.active_mines:
        await interaction.response.send_message(embed=error_embed('Mines', 'You already have an active Mines game.'), ephemeral=True)
        return
    remaining = bot.check_game_cooldown(user_id, 'mines')
    if remaining:
        await interaction.response.send_message(embed=error_embed('Mines', f'Please wait **{remaining:.1f}s** before starting another game.'), ephemeral=True)
        return
    balance = await bot.get_balance(user_id)
    bet = amount_or_all(amount, balance)
    if bet is None:
        await interaction.response.send_message(embed=error_embed('Mines', 'Enter a valid bet amount.'), ephemeral=True)
        return
    if bet < MIN_MINES_BET:
        await interaction.response.send_message(embed=error_embed('Mines', f'Minimum bet is {money(MIN_MINES_BET)}.'), ephemeral=True)
        return
    if bet > balance:
        await interaction.response.send_message(embed=error_embed('Mines', "You don't have enough balance."), ephemeral=True)
        return
    if not await bot.deduct_bet(user_id, bet, 'mines'):
        await interaction.response.send_message(embed=error_embed('Mines', 'Your balance changed. Please try again.'), ephemeral=True)
        return
    game_id = bot.next_game_id()
    server_seed = bot.create_server_seed()
    server_hash = bot.server_hash(server_seed)
    client_seed = bot.create_client_seed(user_id)
    game = MinesGame(bot, user_id, bet, int(mines), game_id, server_hash, server_seed, client_seed, 0)
    bot.active_mines[user_id] = game
    view = MinesView(game)
    embed = mines_embed(game)
    embed.description += '\n\n**Board:** 24 tiles + Cashout\nClick a tile to reveal it.'
    await interaction.response.send_message(embed=embed, view=view)

async def _mines_click(self, interaction: discord.Interaction, game: MinesGame, index: int, view: MinesView):
    if game.finished:
        await interaction.response.send_message(embed=base_embed(description='This game has ended.', color=2829617), ephemeral=True)
        return
    if index in game.opened:
        await interaction.response.send_message(embed=base_embed(description='That tile is already open.', color=2829617), ephemeral=True)
        return
    game.opened.add(index)
    button = next((item for item in view.children if getattr(item, 'custom_id', None) == f'mine:{index}'), None)
    if index in game.bombs:
        game.finished = True
        for item in view.children:
            custom_id = getattr(item, 'custom_id', '')
            if custom_id.startswith('mine:'):
                tile_index = int(custom_id.split(':')[1])
                item.disabled = True
                if tile_index in game.bombs:
                    item.label = '💣'
                elif tile_index in game.opened:
                    item.label = '💎'
        await self.settle_loss(game.user_id, game.amount, 'mines')
        await interaction.response.edit_message(embed=base_embed(description=f'## Mines — Boom!\n\nBet: **{money(game.amount)}**\nLost: **{money(game.amount)}**\n\nGame #{game.game_id}', color=2829617), view=view)
        self.active_mines.pop(game.user_id, None)
        return
    if button:
        button.label = '💎'
        button.style = discord.ButtonStyle.success
        button.disabled = True
    if len(game.opened) >= MinesView.TILE_COUNT - game.mines:
        game.finished = True
        payout = game.payout
        await self.settle_win(game.user_id, game.amount, payout, 'mines')
        for item in view.children:
            item.disabled = True
        await interaction.response.edit_message(embed=base_embed(description=f'## Mines — Cleared!\n\nBet: **{money(game.amount)}**\nMultiplier: **{game.multiplier:.2f}x**\nPayout: **{money(payout)}**', color=2829617), view=view)
        self.active_mines.pop(game.user_id, None)
        return
    await interaction.response.edit_message(embed=base_embed(description=f'## Mines\n\nBet: **{money(game.amount)}**\nOpened: **{len(game.opened)}**\nMultiplier: **{game.multiplier:.2f}x**\nCashout: **{money(game.payout)}**', color=2829617), view=view)
CasinoBot.mines_click = _mines_click

async def _mines_cashout(self, interaction: discord.Interaction, game: MinesGame, view: MinesView):
    if game.finished:
        await interaction.response.send_message(embed=base_embed(description='This game has ended.', color=2829617), ephemeral=True)
        return
    if not game.opened:
        await interaction.response.send_message(embed=base_embed(description='Open at least one tile before cashing out.', color=2829617), ephemeral=True)
        return
    game.finished = True
    payout = game.payout
    await self.settle_win(game.user_id, game.amount, payout, 'mines')
    for item in view.children:
        item.disabled = True
    await interaction.response.edit_message(embed=base_embed(description=f'## Mines — Cashed Out\n\nBet: **{money(game.amount)}**\nOpened: **{len(game.opened)}**\nMultiplier: **{game.multiplier:.2f}x**\nPayout: **{money(payout)}**', color=2829617), view=view)
    self.active_mines.pop(game.user_id, None)
CasinoBot.mines_cashout = _mines_cashout

def blackjack_card_value(card: str) -> int:
    value = card.split('_')[0].lower()
    if value in {'jack', 'queen', 'king'}:
        return 10
    if value == 'ace':
        return 11
    try:
        return int(value)
    except ValueError:
        return 10

def blackjack_hand_total(cards: list[str]) -> int:
    total = sum((blackjack_card_value(card) for card in cards if card != 'hidden'))
    aces = sum((1 for card in cards if card.startswith('ace_')))
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total

def blackjack_deck() -> list[str]:
    suits = ['clubs', 'diamonds', 'hearts', 'spades']
    ranks = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'jack', 'queen', 'king', 'ace']
    cards = [f'{rank}_of_{suit}' for suit in suits for rank in ranks]
    random.shuffle(cards)
    return cards

def card_path(card: str) -> Path:
    return BASE_DIR / f'{card}.png'

def create_blackjack_image(player_cards: list[str], dealer_cards: list[str], hidden: bool=True) -> Optional[discord.File]:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    table_w, table_h = (1050, 470)
    canvas = Image.new('RGBA', (table_w, table_h), (18, 82, 55, 255))
    draw = ImageDraw.Draw(canvas)
    for y in range(table_h):
        shade = int(22 + y / table_h * 14)
        draw.line((0, y, table_w, y), fill=(18, shade + 45, 55, 255))
    draw.rounded_rectangle((14, 14, table_w - 14, table_h - 14), radius=26, outline=(210, 210, 210, 150), width=3)
    draw.rounded_rectangle((30, 30, table_w - 30, table_h - 30), radius=20, outline=(0, 0, 0, 80), width=2)
    card_paths: list[tuple[Path | None, bool]] = []
    for card in player_cards:
        card_paths.append((card_path(card), False))
    for idx, card in enumerate(dealer_cards):
        if hidden and idx == 1:
            card_paths.append((None, True))
        elif card != 'hidden':
            card_paths.append((card_path(card), False))
    images = []
    for path, is_hidden in card_paths:
        if is_hidden:
            images.append(None)
            continue
        if path and path.exists():
            try:
                images.append(Image.open(path).convert('RGBA'))
            except Exception:
                images.append(None)
        else:
            images.append(None)
    if not any(images):
        return None
    target_h = 340
    gap = 20
    valid_images = []
    for img in images:
        if img is None:
            valid_images.append(None)
        else:
            ratio = target_h / img.height
            valid_images.append(img.resize((int(img.width * ratio), target_h), Image.LANCZOS))
    total_w = sum((img.width if img else 220 for img in valid_images)) + gap * (len(valid_images) - 1)
    x = max(35, (table_w - total_w) // 2)
    y = 65
    for img in valid_images:
        if img is None:
            w, h = (220, target_h)
            draw.rounded_rectangle((x, y, x + w, y + h), radius=18, fill=(27, 31, 36, 255), outline=(225, 225, 225, 220), width=3)
            draw.rounded_rectangle((x + 12, y + 12, x + w - 12, y + h - 12), radius=12, outline=(70, 190, 120, 220), width=5)
            draw.text((x + w // 2 - 18, y + h // 2 - 25), '?', fill=(240, 240, 240, 255))
        else:
            canvas.alpha_composite(img, (x, y))
        x += (img.width if img else 220) + gap
    output = io.BytesIO()
    canvas.save(output, format='PNG')
    output.seek(0)
    return discord.File(output, filename='blackjack.png')

class BlackjackView(ButtonView):

    def __init__(self, bot_instance: CasinoBot, user_id: int, game: dict):
        super().__init__(timeout=3600)
        self.bot = bot_instance
        self.user_id = user_id
        self.game = game

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(embed=error_embed('Blackjack', 'This Blackjack game belongs to another player.'), ephemeral=True)
            return False
        return True

    @discord.ui.button(label='Hit', style=discord.ButtonStyle.primary)
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.bot.blackjack_hit(interaction, self)

    @discord.ui.button(label='Stand', style=discord.ButtonStyle.success)
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.bot.blackjack_stand(interaction, self)

    @discord.ui.button(label='Double', style=discord.ButtonStyle.secondary)
    async def double(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.bot.blackjack_double(interaction, self)

def blackjack_embed(game: dict, title: str, color: int, hidden: bool=True, extra: str='') -> tuple[discord.Embed, Optional[discord.File]]:
    player_total = blackjack_hand_total(game['player'])
    dealer_cards = game['dealer']
    dealer_total = '?' if hidden else str(blackjack_hand_total(dealer_cards))
    embed = base_embed(title=title, description=f"**Bet:** {money(game['bet'])}\n**Player:** {player_total}\n**Dealer:** {dealer_total}\n\n**Game:** `#{game['game_id']}`\n**Server Hash:** `{game['server_hash']}`{extra}", color=color)
    embed.set_image(url='attachment://blackjack.png')
    embed.set_footer(text='Hit • Stand • Double  |  /provably-fair')
    return (embed, create_blackjack_image(game['player'], game['dealer'], hidden=hidden))

async def _blackjack_finish(self, interaction: discord.Interaction, view: BlackjackView, result: str):
    game = view.game
    if game['finished']:
        return
    game['finished'] = True
    player_total = blackjack_hand_total(game['player'])
    dealer_total = blackjack_hand_total(game['dealer'])
    if result == 'win':
        payout = (game['bet'] * Decimal('2')).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
        await self.settle_win(game['user_id'], game['bet'], payout, 'blackjack')
        title, color = ('Blackjack — Won', 5763719)
    elif result == 'push':
        payout = game['bet']
        await self.db.change_balance(game['user_id'], payout, kind='blackjack_push', note='blackjack')
        await self.db.record_game(game['user_id'], game['bet'], Decimal('0'), 'blackjack_push')
        title, color = ('Blackjack — Push', 16705372)
    else:
        payout = Decimal('0')
        await self.settle_loss(game['user_id'], game['bet'], 'blackjack')
        title, color = ('Blackjack — Lost', 15548997)
    for item in view.children:
        item.disabled = True
    embed, file = blackjack_embed(game, title, color, hidden=False, extra=f"\n\n**Payout:** {money(payout)}\n**Server Hash:** `{game['server_hash']}`\n**Client Seed:** `{game['client_seed']}`\n**Nonce:** `{game['nonce']}`")
    await interaction.response.defer()
    if interaction.message and file:
        await interaction.message.edit(embed=embed, view=view, attachments=[file])
    else:
        await interaction.edit_original_response(embed=embed, view=view)
    self.active_games.pop(game['user_id'], None)
CasinoBot.blackjack_finish = _blackjack_finish

async def _blackjack_hit(self, interaction: discord.Interaction, view: BlackjackView):
    game = view.game
    if game['finished']:
        return
    game['player'].append(game['deck'].pop())
    total = blackjack_hand_total(game['player'])
    if total > 21:
        await self.blackjack_finish(interaction, view, 'loss')
        return
    embed, file = blackjack_embed(game, 'Blackjack', 2829617, hidden=True)
    await interaction.response.defer()
    if interaction.message and file:
        await interaction.message.edit(embed=embed, view=view, attachments=[file])
    else:
        await interaction.edit_original_response(embed=embed, view=view)
CasinoBot.blackjack_hit = _blackjack_hit

async def _blackjack_stand(self, interaction: discord.Interaction, view: BlackjackView):
    game = view.game
    if game['finished']:
        return
    while blackjack_hand_total(game['dealer']) < 17:
        game['dealer'].append(game['deck'].pop())
    player_total = blackjack_hand_total(game['player'])
    dealer_total = blackjack_hand_total(game['dealer'])
    if dealer_total > 21 or player_total > dealer_total:
        result = 'win'
    elif player_total == dealer_total:
        result = 'push'
    else:
        result = 'loss'
    await self.blackjack_finish(interaction, view, result)
CasinoBot.blackjack_stand = _blackjack_stand

async def _blackjack_double(self, interaction: discord.Interaction, view: BlackjackView):
    game = view.game
    if game['finished']:
        return
    if len(game['player']) != 2:
        await interaction.response.send_message(embed=error_embed('Blackjack', 'Double is only available on your first two cards.'), ephemeral=True)
        return
    if not await self.deduct_bet(game['user_id'], game['bet'], 'blackjack-double'):
        await interaction.response.send_message(embed=error_embed('Blackjack', "You don't have enough balance to double."), ephemeral=True)
        return
    game['bet'] += game['bet']
    game['player'].append(game['deck'].pop())
    if blackjack_hand_total(game['player']) > 21:
        await self.blackjack_finish(interaction, view, 'loss')
    else:
        await self.blackjack_stand(interaction, view)
CasinoBot.blackjack_double = _blackjack_double

@bot.tree.command(name='blackjack', description='Play Blackjack.')
@app_commands.describe(amount='Blackjack bet.')
async def blackjack(interaction: discord.Interaction, amount: str):
    value = normalize_amount(amount)
    if value is None or value < MIN_BET:
        await interaction.response.send_message(embed=error_embed('Blackjack', f'Minimum bet is {money(MIN_BET)}.'), ephemeral=True)
        return
    if not await bot.deduct_bet(interaction.user.id, value, 'blackjack'):
        await interaction.response.send_message(embed=error_embed('Blackjack', "You don't have enough balance."), ephemeral=True)
        return
    deck = blackjack_deck()
    player = [deck.pop(), deck.pop()]
    dealer = [deck.pop(), deck.pop()]
    server_seed = bot.create_server_seed()
    game = {'user_id': interaction.user.id, 'bet': value, 'deck': deck, 'player': player, 'dealer': dealer, 'game_id': bot.next_game_id(), 'server_seed': server_seed, 'server_hash': bot.server_hash(server_seed), 'client_seed': bot.create_client_seed(interaction.user.id), 'nonce': 0, 'finished': False}
    bot.active_games[interaction.user.id] = game
    view = BlackjackView(bot, interaction.user.id, game)
    embed, file = blackjack_embed(game, 'Blackjack', 2829617, hidden=True)
    if file:
        await interaction.response.send_message(embed=embed, view=view, file=file)
    else:
        await interaction.response.send_message(embed=embed, view=view)
bot.tree.add_command(app_commands.Command(name='bj', description='Play Blackjack.', callback=blackjack.callback))

@bot.tree.command(name='housebalance', description='View house liquidity.')
async def housebalance(interaction: discord.Interaction):
    row = await bot.db.pool.fetchrow('\n        SELECT balance\n        FROM house\n        LIMIT 1\n        ')
    if not row:
        await interaction.response.send_message(embed=error_embed('House Balance', 'House balance is not configured yet.'), ephemeral=True)
        return
    await interaction.response.send_message(embed=base_embed(title='House Balance', description=f"**Total liquidity:** {money(row['balance'])}"))

@bot.tree.command(name='addbal', description='Add balance to a user.')
@owner_only()
@app_commands.describe(user='User receiving balance.', amount='Amount to add.')
async def addbal(interaction: discord.Interaction, user: discord.Member, amount: str):
    value = normalize_amount(amount)
    if value is None:
        await interaction.response.send_message(embed=base_embed(description='Invalid amount.', color=2829617), ephemeral=True)
        return
    await bot.db.change_balance(user.id, value, kind='admin_credit', note=f'Admin: {interaction.user.id}')
    await interaction.response.send_message(embed=base_embed(description=f'Added **{money(value)}** to {user.mention}.', color=2829617))

@bot.tree.command(name='ranksetup', description='Create/update casino rank roles.')
@owner_only()
async def ranksetup(interaction: discord.Interaction):
    guild = interaction.guild
    if guild is None:
        await interaction.response.send_message(embed=base_embed(description='This command can only be used in a server.', color=2829617), ephemeral=True)
        return
    created = []
    for rank in RANKS:
        label = bot.rank_label(rank)
        existing = discord.utils.get(guild.roles, name=label)
        if existing:
            continue
        try:
            role = await guild.create_role(name=label, reason='Casino rank setup')
            created.append(role.name)
        except discord.HTTPException:
            continue
    if created:
        description = 'Created:\n' + '\n'.join((f'• {name}' for name in created))
    else:
        description = 'All rank roles already exist.'
    await interaction.response.send_message(embed=success_embed('Rank Setup', description))

async def check_rank_up(user_id: int):
    row = await bot.get_db_user(user_id)
    wagered = D(row['wagered'])
    current_index = bot.get_rank_index(wagered)
    previous_claimed = await bot.db.setting(f'rank_notified:{user_id}', '-1')
    try:
        previous_index = int(previous_claimed)
    except ValueError:
        previous_index = -1
    if current_index <= previous_index:
        return
    await bot.db.set_setting(f'rank_notified:{user_id}', str(current_index))
    rank = RANKS[current_index]
    user = bot.get_user(user_id)
    if not user:
        return
    try:
        await user.send(embed=base_embed(description=f"**Rank Up!** You reached **{bot.rank_label(rank)}** and earned **{money(rank['reward'])}** — pick your coin in the DM below, or claim anytime with **/rank-rewards**", color=2829617))
    except discord.HTTPException:
        pass

@tasks.loop(seconds=30)
async def rank_monitor():
    if not bot.db:
        return
    try:
        rows = await bot.db.pool.fetch('\n            SELECT user_id, wagered\n            FROM users\n            ')
        for row in rows:
            await check_rank_up(int(row['user_id']))
    except Exception as exc:
        print(f'[RANK MONITOR] {exc}')

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    print(f'[APP COMMAND ERROR] {interaction.command}: {error}')
    if isinstance(error, app_commands.CheckFailure):
        await bot.safe_send(interaction, content='You do not have permission to use this command.', ephemeral=True)
        return
    if isinstance(error, app_commands.TransformerError):
        await bot.safe_send(interaction, content='One of the supplied values is invalid.', ephemeral=True)
        return
    await bot.safe_send(interaction, embed=error_embed('Something went wrong', 'Please try again.'), ephemeral=True)

@rank_monitor.before_loop
async def before_rank_monitor():
    await bot.wait_until_ready()

@private_channel_monitor.before_loop
async def before_private_monitor():
    await bot.wait_until_ready()
_original_on_ready = bot.on_ready

async def _final_on_ready():
    await _original_on_ready()
    if not rank_monitor.is_running():
        rank_monitor.start()
    if not private_channel_monitor.is_running():
        private_channel_monitor.start()
bot.on_ready = _final_on_ready
if __name__ == '__main__':
    if not BOT_TOKEN:
        raise RuntimeError('DISCORD_TOKEN is not configured.')
    bot.run(BOT_TOKEN)
