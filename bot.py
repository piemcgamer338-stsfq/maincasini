# bot.py

import os
import re
import time
import json
import sqlite3
import asyncio
import hashlib
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta, timezone

import aiohttp
import discord
from discord.ext import commands, tasks


# =========================================================
# ENVIRONMENT
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID_RAW = os.getenv("OWNER_ID")

# Add these later in Railway when you connect the wallets.
LTC_XPUB = os.getenv("LTC_XPUB", "").strip()
SOL_MASTER_SEED = os.getenv("SOL_MASTER_SEED", "").strip()
SOL_RPC_URL = os.getenv(
    "SOL_RPC_URL",
    "https://api.mainnet-beta.solana.com"
).strip()

# Optional:
# A Discord channel where automatic deposit notifications are sent.
DEPOSIT_LOG_CHANNEL_ID = os.getenv(
    "DEPOSIT_LOG_CHANNEL_ID",
    ""
).strip()

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is missing.")

if not OWNER_ID_RAW:
    raise RuntimeError("OWNER_ID environment variable is missing.")

try:
    OWNER_ID = int(OWNER_ID_RAW)
except ValueError:
    raise RuntimeError("OWNER_ID must be a valid Discord user ID.")

try:
    DEPOSIT_LOG_CHANNEL_ID = (
        int(DEPOSIT_LOG_CHANNEL_ID)
        if DEPOSIT_LOG_CHANNEL_ID
        else 0
    )
except ValueError:
    DEPOSIT_LOG_CHANNEL_ID = 0


# =========================================================
# SETTINGS
# =========================================================

PREFIX = "."

DB_PATH = os.getenv(
    "DATABASE_PATH",
    "/data/bot.db"
)

if not os.path.exists("/data"):
    DB_PATH = "bot.db"

LTC_CONFIRMATIONS = 2
SOL_CONFIRMATIONS = 1

DEPOSIT_CHECK_SECONDS = 20

# Existing balance rates requested earlier.
RATES = {
    "ltc": Decimal("100"),
    "sol": Decimal("200"),
}

LTC_DERIVATION_PREFIX = "m/0"

# Public Solana derivation path.
# The actual implementation below derives deterministic
# accounts from the configured master seed.
SOL_DERIVATION_PREFIX = "m/44'/501'/"

SOLANA_LAMPORTS = Decimal("1000000000")

LTC_SATOSHIS = Decimal("100000000")


# =========================================================
# INTENTS / BOT
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
# DATABASE
# =========================================================

db_lock = asyncio.Lock()


def db_connect():
    connection = sqlite3.connect(
        DB_PATH,
        timeout=30
    )

    connection.row_factory = sqlite3.Row

    connection.execute(
        "PRAGMA journal_mode=WAL"
    )

    connection.execute(
        "PRAGMA foreign_keys=ON"
    )

    return connection


def setup_database():

    connection = db_connect()

    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            ltc_balance TEXT NOT NULL DEFAULT '0',
            sol_balance TEXT NOT NULL DEFAULT '0',
            points INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS deposit_addresses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            crypto TEXT NOT NULL,
            address TEXT NOT NULL UNIQUE,
            derivation_index INTEGER NOT NULL,
            created_at INTEGER NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            UNIQUE(user_id, crypto)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS deposits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            crypto TEXT NOT NULL,
            address TEXT NOT NULL,
            txid TEXT NOT NULL,
            amount_crypto TEXT NOT NULL,
            amount_usd TEXT NOT NULL,
            confirmations INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending',
            user_id INTEGER NOT NULL,
            created_at INTEGER NOT NULL,
            credited_at INTEGER,
            UNIQUE(crypto, txid, address)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scanner_state (
            crypto TEXT PRIMARY KEY,
            last_scan INTEGER NOT NULL DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rain_participants (
            rain_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            PRIMARY KEY(rain_id, user_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rains (
            rain_id INTEGER PRIMARY KEY,
            owner_id INTEGER NOT NULL,
            amount_crypto TEXT NOT NULL,
            amount_usd TEXT NOT NULL,
            crypto TEXT NOT NULL,
            end_time INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            finished INTEGER NOT NULL DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    connection.commit()
    connection.close()


setup_database()


# =========================================================
# DATABASE HELPERS
# =========================================================

def now_ts():
    return int(time.time())


def ensure_user_sync(user_id):

    connection = db_connect()

    connection.execute(
        """
        INSERT OR IGNORE INTO users
        (user_id, ltc_balance, sol_balance, points, created_at)
        VALUES (?, '0', '0', 0, ?)
        """,
        (
            user_id,
            now_ts()
        )
    )

    connection.commit()
    connection.close()


async def ensure_user(user_id):

    async with db_lock:

        await asyncio.to_thread(
            ensure_user_sync,
            user_id
        )


def get_user_sync(user_id):

    ensure_user_sync(user_id)

    connection = db_connect()

    row = connection.execute(
        """
        SELECT *
        FROM users
        WHERE user_id = ?
        """,
        (user_id,)
    ).fetchone()

    connection.close()

    return row


async def get_user(user_id):

    return await asyncio.to_thread(
        get_user_sync,
        user_id
    )


def get_balance_sync(user_id, crypto):

    row = get_user_sync(user_id)

    return Decimal(
        row[f"{crypto}_balance"]
    )


async def get_balance(user_id, crypto):

    return await asyncio.to_thread(
        get_balance_sync,
        user_id,
        crypto
    )


def change_balance_sync(
    user_id,
    crypto,
    amount
):

    ensure_user_sync(user_id)

    connection = db_connect()

    row = connection.execute(
        f"""
        SELECT {crypto}_balance
        FROM users
        WHERE user_id = ?
        """,
        (user_id,)
    ).fetchone()

    old_balance = Decimal(
        row[f"{crypto}_balance"]
    )

    new_balance = old_balance + Decimal(amount)

    if new_balance < 0:
        connection.close()
        raise ValueError(
            "Insufficient balance."
        )

    connection.execute(
        f"""
        UPDATE users
        SET {crypto}_balance = ?
        WHERE user_id = ?
        """,
        (
            str(new_balance),
            user_id
        )
    )

    connection.commit()
    connection.close()

    return old_balance, new_balance


async def change_balance(
    user_id,
    crypto,
    amount
):

    async with db_lock:

        return await asyncio.to_thread(
            change_balance_sync,
            user_id,
            crypto,
            amount
        )


def change_points_sync(
    user_id,
    amount
):

    ensure_user_sync(user_id)

    connection = db_connect()

    row = connection.execute(
        """
        SELECT points
        FROM users
        WHERE user_id = ?
        """,
        (user_id,)
    ).fetchone()

    old_points = int(row["points"])

    new_points = old_points + amount

    if new_points < 0:
        connection.close()
        raise ValueError(
            "Insufficient points."
        )

    connection.execute(
        """
        UPDATE users
        SET points = ?
        WHERE user_id = ?
        """,
        (
            new_points,
            user_id
        )
    )

    connection.commit()
    connection.close()

    return old_points, new_points


async def change_points(
    user_id,
    amount
):

    async with db_lock:

        return await asyncio.to_thread(
            change_points_sync,
            user_id,
            amount
        )


# =========================================================
# FORMAT / PARSING
# =========================================================

def parse_usd(value):

    if value is None:
        return None

    value = str(value).strip().lower()

    if value.endswith("$"):
        value = value[:-1]

    value = value.replace(",", "").strip()

    try:
        amount = Decimal(value)
    except InvalidOperation:
        return None

    if amount <= 0:
        return None

    return amount.quantize(
        Decimal("0.01")
    )


def format_crypto(amount):

    amount = Decimal(amount)

    text = format(
        amount,
        "f"
    )

    if "." in text:
        text = text.rstrip("0").rstrip(".")

    return text or "0"


def usd_to_crypto(
    usd,
    crypto
):

    return Decimal(usd) / RATES[crypto]


def crypto_to_usd(
    amount,
    crypto
):

    return Decimal(amount) * RATES[crypto]


def format_usd(amount):

    return f"${Decimal(amount):.2f}"


def parse_duration(value):

    if not value:
        return None

    value = str(value).lower().strip()

    match = re.fullmatch(
        r"(\d+(?:\.\d+)?)(s|m|h)",
        value
    )

    if not match:
        return None

    number = Decimal(match.group(1))
    unit = match.group(2)

    if unit == "s":
        seconds = number
    elif unit == "m":
        seconds = number * 60
    else:
        seconds = number * 3600

    seconds = int(seconds)

    if seconds <= 0:
        return None

    if seconds > 5 * 60 * 60:
        return None

    return seconds


def format_duration(seconds):

    seconds = int(seconds)

    hours = seconds // 3600
    seconds %= 3600

    minutes = seconds // 60
    seconds %= 60

    parts = []

    if hours:
        parts.append(f"{hours}h")

    if minutes:
        parts.append(f"{minutes}m")

    if seconds or not parts:
        parts.append(f"{seconds}s")

    return " ".join(parts)


# =========================================================
# LTC XPUB DERIVATION
# =========================================================

def ltc_address_from_xpub(
    xpub,
    index
):
    """
    Requires bip_utils.

    The xpub remains public and can derive receive addresses.
    Private keys are not needed for deposit detection.
    """

    try:

        from bip_utils import (
            Bip44,
            Bip44Coins,
            Bip44Changes
        )

        ctx = Bip44.FromExtendedKey(
            xpub,
            Bip44Coins.LITECOIN
        )

        address = (
            ctx
            .Change(Bip44Changes.CHAIN_EXT)
            .AddressIndex(index)
            .PublicKey()
            .ToAddress()
        )

        return address

    except Exception as exc:

        raise RuntimeError(
            "Unable to derive Litecoin address from LTC_XPUB: "
            f"{exc}"
        )


def get_ltc_address_sync(
    user_id
):

    connection = db_connect()

    row = connection.execute(
        """
        SELECT address
        FROM deposit_addresses
        WHERE user_id = ?
        AND crypto = 'ltc'
        """,
        (user_id,)
    ).fetchone()

    if row:
        connection.close()
        return row["address"]

    if not LTC_XPUB:

        connection.close()

        raise RuntimeError(
            "LTC_XPUB is not configured."
        )

    row = connection.execute(
        """
        SELECT MAX(derivation_index) AS max_index
        FROM deposit_addresses
        WHERE crypto = 'ltc'
        """
    ).fetchone()

    next_index = (
        0
        if row["max_index"] is None
        else int(row["max_index"]) + 1
    )

    address = ltc_address_from_xpub(
        LTC_XPUB,
        next_index
    )

    connection.execute(
        """
        INSERT INTO deposit_addresses
        (
            user_id,
            crypto,
            address,
            derivation_index,
            created_at
        )
        VALUES (?, 'ltc', ?, ?, ?)
        """,
        (
            user_id,
            address,
            next_index,
            now_ts()
        )
    )

    connection.commit()
    connection.close()

    return address


async def get_ltc_address(
    user_id
):

    async with db_lock:

        return await asyncio.to_thread(
            get_ltc_address_sync,
            user_id
        )


# =========================================================
# SOLANA ADDRESS DERIVATION
# =========================================================

def sol_address_from_seed(
    seed,
    index
):
    """
    Deterministically creates a Solana deposit address.

    Requires:
        bip_utils

    SOL_MASTER_SEED is intentionally read from Railway
    and never sent to an external service.
    """

    try:

        from bip_utils import (
            Bip39SeedGenerator,
            SolAddrDecoder,
            SolanaKeyGenerator
        )

        seed_bytes = None

        # Accept a BIP39 mnemonic.
        words = seed.split()

        if len(words) in (
            12,
            15,
            18,
            21,
            24
        ):
            seed_bytes = Bip39SeedGenerator(
                seed
            ).Generate()

        else:
            # Accept a hexadecimal seed.
            cleaned = seed.lower().replace(
                "0x",
                ""
            )

            try:
                seed_bytes = bytes.fromhex(
                    cleaned
                )
            except ValueError:
                raise RuntimeError(
                    "SOL_MASTER_SEED must be a BIP39 "
                    "mnemonic or hexadecimal seed."
                )

        path = (
            f"{SOL_DERIVATION_PREFIX}"
            f"{index}'/0'"
        )

        private_key = SolanaKeyGenerator.FromSeed(
            seed_bytes,
            path
        )

        return str(
            private_key.PublicKey()
        )

    except ImportError:

        raise RuntimeError(
            "Install bip_utils to enable Solana "
            "automatic deposit addresses."
        )

    except Exception as exc:

        raise RuntimeError(
            "Unable to derive Solana address: "
            f"{exc}"
        )


def get_sol_address_sync(
    user_id
):

    connection = db_connect()

    row = connection.execute(
        """
        SELECT address
        FROM deposit_addresses
        WHERE user_id = ?
        AND crypto = 'sol'
        """,
        (user_id,)
    ).fetchone()

    if row:
        connection.close()
        return row["address"]

    if not SOL_MASTER_SEED:

        connection.close()

        raise RuntimeError(
            "SOL_MASTER_SEED is not configured."
        )

    row = connection.execute(
        """
        SELECT MAX(derivation_index) AS max_index
        FROM deposit_addresses
        WHERE crypto = 'sol'
        """
    ).fetchone()

    next_index = (
        0
        if row["max_index"] is None
        else int(row["max_index"]) + 1
    )

    address = sol_address_from_seed(
        SOL_MASTER_SEED,
        next_index
    )

    connection.execute(
        """
        INSERT INTO deposit_addresses
        (
            user_id,
            crypto,
            address,
            derivation_index,
            created_at
        )
        VALUES (?, 'sol', ?, ?, ?)
        """,
        (
            user_id,
            address,
            next_index,
            now_ts()
        )
    )

    connection.commit()
    connection.close()

    return address


async def get_sol_address(
    user_id
):

    async with db_lock:

        return await asyncio.to_thread(
            get_sol_address_sync,
            user_id
        )


# =========================================================
# DEPOSIT ADDRESS LOOKUP
# =========================================================

def get_address_owner_sync(
    crypto,
    address
):

    connection = db_connect()

    row = connection.execute(
        """
        SELECT user_id
        FROM deposit_addresses
        WHERE crypto = ?
        AND address = ?
        """,
        (
            crypto,
            address
        )
    ).fetchone()

    connection.close()

    if not row:
        return None

    return int(row["user_id"])


async def get_address_owner(
    crypto,
    address
):

    return await asyncio.to_thread(
        get_address_owner_sync,
        crypto,
        address
    )


# =========================================================
# DEPOSIT DATABASE
# =========================================================

def deposit_exists_sync(
    crypto,
    txid,
    address
):

    connection = db_connect()

    row = connection.execute(
        """
        SELECT id
        FROM deposits
        WHERE crypto = ?
        AND txid = ?
        AND address = ?
        """,
        (
            crypto,
            txid,
            address
        )
    ).fetchone()

    connection.close()

    return row is not None


async def deposit_exists(
    crypto,
    txid,
    address
):

    return await asyncio.to_thread(
        deposit_exists_sync,
        crypto,
        txid,
        address
    )


def insert_deposit_sync(
    crypto,
    address,
    txid,
    amount_crypto,
    amount_usd,
    confirmations,
    user_id
):

    connection = db_connect()

    cursor = connection.cursor()

    try:

        cursor.execute(
            """
            INSERT INTO deposits
            (
                crypto,
                address,
                txid,
                amount_crypto,
                amount_usd,
                confirmations,
                status,
                user_id,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
            """,
            (
                crypto,
                address,
                txid,
                str(amount_crypto),
                str(amount_usd),
                confirmations,
                user_id,
                now_ts()
            )
        )

        connection.commit()

        return True

    except sqlite3.IntegrityError:

        connection.rollback()

        return False

    finally:

        connection.close()


async def insert_deposit(
    crypto,
    address,
    txid,
    amount_crypto,
    amount_usd,
    confirmations,
    user_id
):

    async with db_lock:

        return await asyncio.to_thread(
            insert_deposit_sync,
            crypto,
            address,
            txid,
            amount_crypto,
            amount_usd,
            confirmations,
            user_id
        )


def mark_deposit_credited_sync(
    crypto,
    txid,
    address
):

    connection = db_connect()

    row = connection.execute(
        """
        SELECT *
        FROM deposits
        WHERE crypto = ?
        AND txid = ?
        AND address = ?
        """,
        (
            crypto,
            txid,
            address
        )
    ).fetchone()

    if not row:
        connection.close()
        return None

    if row["status"] == "credited":
        connection.close()
        return None

    connection.execute(
        """
        UPDATE deposits
        SET status = 'credited',
            credited_at = ?,
            confirmations = ?
        WHERE id = ?
        """,
        (
            now_ts(),
            max(
                int(row["confirmations"]),
                1
            ),
            row["id"]
        )
    )

    connection.commit()
    connection.close()

    return row


async def mark_deposit_credited(
    crypto,
    txid,
    address
):

    async with db_lock:

        return await asyncio.to_thread(
            mark_deposit_credited_sync,
            crypto,
            txid,
            address
        )


def update_deposit_confirmations_sync(
    crypto,
    txid,
    address,
    confirmations
):

    connection = db_connect()

    connection.execute(
        """
        UPDATE deposits
        SET confirmations = ?
        WHERE crypto = ?
        AND txid = ?
        AND address = ?
        """,
        (
            confirmations,
            crypto,
            txid,
            address
        )
    )

    connection.commit()
    connection.close()


async def update_deposit_confirmations(
    crypto,
    txid,
    address,
    confirmations
):

    await asyncio.to_thread(
        update_deposit_confirmations_sync,
        crypto,
        txid,
        address,
        confirmations
    )


# =========================================================
# DEPOSIT NOTIFICATION
# =========================================================

async def send_deposit_notification(
    user_id,
    crypto,
    amount_crypto,
    amount_usd,
    txid
):

    user = bot.get_user(user_id)

    if user:

        embed = discord.Embed(
            title="Deposit Credited",
            description=(
                f"Your `{crypto.upper()}` deposit has been "
                "confirmed and credited.\n\n"
                f"Amount: "
                f"`{format_crypto(amount_crypto)} "
                f"{crypto.upper()}`\n"
                f"Value: `{format_usd(amount_usd)}`\n"
                f"Transaction: `{txid}`"
            ),
            color=discord.Color.green()
        )

        try:
            await user.send(
                embed=embed
            )
        except discord.HTTPException:
            pass

    if DEPOSIT_LOG_CHANNEL_ID:

        channel = bot.get_channel(
            DEPOSIT_LOG_CHANNEL_ID
        )

        if channel:

            embed = discord.Embed(
                title="Automatic Deposit",
                color=discord.Color.green()
            )

            embed.description = (
                f"User: <@{user_id}>\n"
                f"Asset: `{crypto.upper()}`\n"
                f"Amount: "
                f"`{format_crypto(amount_crypto)} "
                f"{crypto.upper()}`\n"
                f"USD Value: `{format_usd(amount_usd)}`\n"
                f"TXID: `{txid}`"
            )

            try:
                await channel.send(
                    embed=embed
                )
            except discord.HTTPException:
                pass


# =========================================================
# HTTP SESSION
# =========================================================

http_session = None


async def get_http_session():

    global http_session

    if http_session is None:

        timeout = aiohttp.ClientTimeout(
            total=20
        )

        http_session = aiohttp.ClientSession(
            timeout=timeout
        )

    return http_session


# =========================================================
# LITECOIN MONITOR
# =========================================================

async def get_ltc_address_transactions(
    address
):

    session = await get_http_session()

    url = (
        "https://litecoinspace.org/api/address/"
        f"{address}/txs"
    )

    try:

        async with session.get(
            url
        ) as response:

            if response.status != 200:
                return []

            return await response.json()

    except Exception:

        return []


async def process_ltc_transaction(
    address,
    tx
):

    txid = tx.get("txid")

    if not txid:
        return

    user_id = await get_address_owner(
        "ltc",
        address
    )

    if user_id is None:
        return

    total_received = Decimal("0")

    for output in tx.get(
        "vout",
        []
    ):

        scriptpubkey = output.get(
            "scriptpubkey_address"
        )

        if scriptpubkey != address:
            continue

        value = output.get(
            "value",
            0
        )

        total_received += (
            Decimal(value) /
            LTC_SATOSHIS
        )

    if total_received <= 0:
        return

    if await deposit_exists(
        "ltc",
        txid,
        address
    ):
        return

    amount_usd = crypto_to_usd(
        total_received,
        "ltc"
    )

    inserted = await insert_deposit(
        "ltc",
        address,
        txid,
        total_received,
        amount_usd,
        LTC_CONFIRMATIONS,
        user_id
    )

    if not inserted:
        return

    # The public API response is sufficient for identifying
    # the transaction. The transaction is only credited after
    # the configured confirmation threshold.
    status = tx.get(
        "status",
        {}
    )

    confirmed = bool(
        status.get("confirmed")
    )

    if not confirmed:
        return

    block_height = status.get(
        "block_height"
    )

    if block_height is None:
        return

    try:

        session = await get_http_session()

        async with session.get(
            "https://litecoinspace.org/api/blocks/tip/height"
        ) as response:

            if response.status != 200:
                return

            tip_height = int(
                await response.text()
            )

    except Exception:

        return

    confirmations = (
        tip_height -
        int(block_height) +
        1
    )

    await update_deposit_confirmations(
        "ltc",
        txid,
        address,
        confirmations
    )

    if confirmations < LTC_CONFIRMATIONS:
        return

    row = await mark_deposit_credited(
        "ltc",
        txid,
        address
    )

    if row is None:
        return

    await change_balance(
        user_id,
        "ltc",
        total_received
    )

    await send_deposit_notification(
        user_id,
        "ltc",
        total_received,
        amount_usd,
        txid
    )


async def scan_ltc():

    if not LTC_XPUB:
        return

    connection = db_connect()

    rows = connection.execute(
        """
        SELECT user_id, address
        FROM deposit_addresses
        WHERE crypto = 'ltc'
        AND active = 1
        """
    ).fetchall()

    connection.close()

    for row in rows:

        transactions = (
            await get_ltc_address_transactions(
                row["address"]
            )
        )

        for tx in transactions:

            await process_ltc_transaction(
                row["address"],
                tx
            )


# =========================================================
# SOLANA RPC
# =========================================================

async def sol_rpc(
    method,
    params
):

    session = await get_http_session()

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params
    }

    try:

        async with session.post(
            SOL_RPC_URL,
            json=payload
        ) as response:

            if response.status != 200:
                return None

            data = await response.json()

            return data.get(
                "result"
            )

    except Exception:

        return None


async def get_sol_signatures(
    address
):

    return await sol_rpc(
        "getSignaturesForAddress",
        [
            address,
            {
                "limit": 20,
                "commitment": "finalized"
            }
        ]
    )


async def get_sol_transaction(
    signature
):

    return await sol_rpc(
        "getTransaction",
        [
            signature,
            {
                "encoding": "jsonParsed",
                "commitment": "finalized",
                "maxSupportedTransactionVersion": 0
            }
        ]
    )


def find_sol_received_amount(
    transaction,
    address
):

    if not transaction:
        return Decimal("0")

    meta = transaction.get(
        "meta"
    )

    tx = transaction.get(
        "transaction"
    )

    if not meta or not tx:
        return Decimal("0")

    if meta.get("err") is not None:
        return Decimal("0")

    message = tx.get(
        "message",
        {}
    )

    account_keys = message.get(
        "accountKeys",
        []
    )

    pre_balances = meta.get(
        "preBalances",
        []
    )

    post_balances = meta.get(
        "postBalances",
        []
    )

    for index, account in enumerate(
        account_keys
    ):

        if isinstance(
            account,
            dict
        ):
            pubkey = account.get(
                "pubkey"
            )
        else:
            pubkey = account

        if pubkey != address:
            continue

        if index >= len(
            pre_balances
        ):
            continue

        if index >= len(
            post_balances
        ):
            continue

        difference = (
            int(post_balances[index]) -
            int(pre_balances[index])
        )

        if difference <= 0:
            return Decimal("0")

        return (
            Decimal(difference) /
            SOLANA_LAMPORTS
        )

    return Decimal("0")


async def process_sol_transaction(
    address,
    signature
):

    user_id = await get_address_owner(
        "sol",
        address
    )

    if user_id is None:
        return

    if await deposit_exists(
        "sol",
        signature,
        address
    ):
        return

    transaction = await get_sol_transaction(
        signature
    )

    if not transaction:
        return

    amount = find_sol_received_amount(
        transaction,
        address
    )

    if amount <= 0:
        return

    amount_usd = crypto_to_usd(
        amount,
        "sol"
    )

    inserted = await insert_deposit(
        "sol",
        address,
        signature,
        amount,
        amount_usd,
        SOL_CONFIRMATIONS,
        user_id
    )

    if not inserted:
        return

    row = await mark_deposit_credited(
        "sol",
        signature,
        address
    )

    if row is None:
        return

    await change_balance(
        user_id,
        "sol",
        amount
    )

    await send_deposit_notification(
        user_id,
        "sol",
        amount,
        amount_usd,
        signature
    )


async def scan_sol():

    if not SOL_MASTER_SEED:
        return

    connection = db_connect()

    rows = connection.execute(
        """
        SELECT user_id, address
        FROM deposit_addresses
        WHERE crypto = 'sol'
        AND active = 1
        """
    ).fetchall()

    connection.close()

    for row in rows:

        signatures = await get_sol_signatures(
            row["address"]
        )

        if not signatures:
            continue

        for item in signatures:

            if item.get("err") is not None:
                continue

            signature = item.get(
                "signature"
            )

            if not signature:
                continue

            await process_sol_transaction(
                row["address"],
                signature
            )


# =========================================================
# AUTOMATIC BLOCKCHAIN SCANNER
# =========================================================

@tasks.loop(
    seconds=DEPOSIT_CHECK_SECONDS
)
async def blockchain_scanner():

    try:

        await scan_ltc()

    except Exception as exc:

        print(
            f"[LTC SCANNER] {exc}"
        )

    try:

        await scan_sol()

    except Exception as exc:

        print(
            f"[SOL SCANNER] {exc}"
        )


@blockchain_scanner.before_loop
async def before_blockchain_scanner():

    await bot.wait_until_ready()


# =========================================================
# OWNER
# =========================================================

def owner_only():

    async def predicate(ctx):

        if ctx.author.id != OWNER_ID:

            raise commands.CheckFailure(
                "Owner only."
            )

        return True

    return commands.check(
        predicate
    )


# =========================================================
# OWNER STARTING BALANCE
# =========================================================

def give_owner_starting_balance_sync():

    connection = db_connect()

    row = connection.execute(
        """
        SELECT value
        FROM settings
        WHERE key = 'owner_starting_balance_given'
        """
    ).fetchone()

    if row:

        connection.close()
        return False

    connection.execute(
        """
        INSERT OR IGNORE INTO users
        (
            user_id,
            ltc_balance,
            sol_balance,
            points,
            created_at
        )
        VALUES (?, '0', '0', 0, ?)
        """,
        (
            OWNER_ID,
            now_ts()
        )
    )

    connection.commit()
    connection.close()

    return True


async def give_owner_starting_balance():

    async with db_lock:

        should_add = await asyncio.to_thread(
            give_owner_starting_balance_sync
        )

        if not should_add:
            return

        await asyncio.to_thread(
            change_balance_sync,
            OWNER_ID,
            "ltc",
            usd_to_crypto(
                Decimal("35"),
                "ltc"
            )
        )

        await asyncio.to_thread(
            change_balance_sync,
            OWNER_ID,
            "sol",
            usd_to_crypto(
                Decimal("10"),
                "sol"
            )
        )

        connection = db_connect()

        connection.execute(
            """
            INSERT OR REPLACE INTO settings
            (key, value)
            VALUES (
                'owner_starting_balance_given',
                '1'
            )
            """
        )

        connection.commit()
        connection.close()


# =========================================================
# HELP
# =========================================================

@bot.command(name="help")
async def help_command(
    ctx
):

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
        name="Deposits",
        value=(
            "`.deposit`\n"
            "Get your personal LTC/SOL deposit addresses.\n\n"
            "Deposits are monitored automatically."
        ),
        inline=False
    )

    embed.add_field(
        name="Other",
        value=(
            "`.withdraw`\n"
            "View withdrawal status.\n\n"
            "`.rain 10$ 30m`\n"
            "Start a SOL rain."
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

    user = await get_user(
        ctx.author.id
    )

    ltc = Decimal(
        user["ltc_balance"]
    )

    sol = Decimal(
        user["sol_balance"]
    )

    if crypto is None:

        ltc_usd = crypto_to_usd(
            ltc,
            "ltc"
        )

        sol_usd = crypto_to_usd(
            sol,
            "sol"
        )

        total = (
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
                f"{format_usd(ltc_usd)}"
            ),
            inline=True
        )

        embed.add_field(
            name="Solana",
            value=(
                f"`{format_crypto(sol)} SOL`\n"
                f"{format_usd(sol_usd)}"
            ),
            inline=True
        )

        embed.add_field(
            name="Total",
            value=(
                f"`{format_usd(total)}`"
            ),
            inline=False
        )

        await ctx.send(
            embed=embed
        )

        return

    crypto = crypto.lower().strip()

    if crypto not in (
        "ltc",
        "sol"
    ):

        await ctx.send(
            "Invalid cryptocurrency. "
            "Use `ltc` or `sol`."
        )

        return

    amount = (
        ltc
        if crypto == "ltc"
        else sol
    )

    usd = crypto_to_usd(
        amount,
        crypto
    )

    name = (
        "Litecoin"
        if crypto == "ltc"
        else "Solana"
    )

    symbol = (
        "LTC"
        if crypto == "ltc"
        else "SOL"
    )

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
            f"{format_usd(usd)}"
        ),
        inline=False
    )

    await ctx.send(
        embed=embed
    )


# =========================================================
# DEPOSIT UI
# =========================================================

class DepositView(
    discord.ui.View
):

    def __init__(
        self,
        user_id
    ):

        super().__init__(
            timeout=600
        )

        self.user_id = user_id

    async def interaction_check(
        self,
        interaction
    ):

        if interaction.user.id != self.user_id:

            await interaction.response.send_message(
                "This deposit panel belongs to another user.",
                ephemeral=True
            )

            return False

        return True

    @discord.ui.button(
        label="Solana",
        style=discord.ButtonStyle.primary
    )
    async def sol_button(
        self,
        interaction,
        button
    ):

        try:

            address = await get_sol_address(
                self.user_id
            )

        except Exception as exc:

            await interaction.response.send_message(
                f"Solana deposit setup is not configured yet.\n`{exc}`",
                ephemeral=True
            )

            return

        embed = discord.Embed(
            title="Solana Deposit",
            color=discord.Color.blurple()
        )

        embed.description = (
            "Your personal Solana deposit address:\n\n"
            f"```text\n"
            f"{address}\n"
            f"```\n\n"
            "Send only SOL to this address.\n"
            "Incoming deposits are checked automatically."
        )

        await interaction.response.edit_message(
            embed=embed,
            view=self
        )

    @discord.ui.button(
        label="Litecoin",
        style=discord.ButtonStyle.secondary
    )
    async def ltc_button(
        self,
        interaction,
        button
    ):

        try:

            address = await get_ltc_address(
                self.user_id
            )

        except Exception as exc:

            await interaction.response.send_message(
                f"Litecoin deposit setup is not configured yet.\n`{exc}`",
                ephemeral=True
            )

            return

        embed = discord.Embed(
            title="Litecoin Deposit",
            color=discord.Color.blurple()
        )

        embed.description = (
            "Your personal Litecoin deposit address:\n\n"
            f"```text\n"
            f"{address}\n"
            f"```\n\n"
            "Send only LTC to this address.\n"
            "Incoming deposits are checked automatically."
        )

        await interaction.response.edit_message(
            embed=embed,
            view=self
        )


# =========================================================
# DEPOSIT
# =========================================================

@bot.command(name="deposit")
async def deposit_command(
    ctx
):

    await ensure_user(
        ctx.author.id
    )

    embed = discord.Embed(
        title="Deposit",
        description=(
            "Your personal deposit addresses are "
            "available in your DMs.\n\n"
            "Select an asset below."
        ),
        color=discord.Color.blurple()
    )

    try:

        await ctx.author.send(
            embed=embed,
            view=DepositView(
                ctx.author.id
            )
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

    if crypto not in (
        "ltc",
        "sol"
    ):

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
            "Example: `1$`, `5$`, or `10.50$`."
        )

        return

    crypto_amount = usd_to_crypto(
        usd,
        crypto
    )

    sender_balance = await get_balance(
        ctx.author.id,
        crypto
    )

    if sender_balance < crypto_amount:

        available_usd = crypto_to_usd(
            sender_balance,
            crypto
        )

        await ctx.send(
            f"You do not have enough {crypto.upper()}.\n"
            f"Available: `{format_usd(available_usd)}`"
        )

        return

    await change_balance(
        ctx.author.id,
        crypto,
        -crypto_amount
    )

    await change_balance(
        member.id,
        crypto,
        crypto_amount
    )

    embed = discord.Embed(
        title="Tip Sent",
        color=discord.Color.green()
    )

    embed.description = (
        f"{ctx.author.mention} tipped "
        f"{member.mention}\n\n"
        f"Amount: `{format_usd(usd)}`\n"
        f"Asset: `{crypto.upper()}`\n"
        f"Received: "
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
async def withdraw_command(
    ctx
):

    embed = discord.Embed(
        title="Withdrawal Error",
        description=(
            "The withdrawal service is currently unavailable.\n\n"
            "Error Code: `CRYPTO-NETWORK-SYNC-503`\n\n"
            "Your balance has not been changed.\n\n"
            "Please retry in a few hours."
        ),
        color=discord.Color.red()
    )

    await ctx.send(
        embed=embed
    )


# =========================================================
# RAIN
# =========================================================

class RainView(
    discord.ui.View
):

    def __init__(
        self,
        rain_id
    ):

        super().__init__(
            timeout=None
        )

        self.rain_id = rain_id

    @discord.ui.button(
        label="Join Rain",
        style=discord.ButtonStyle.primary
    )
    async def join(
        self,
        interaction,
        button
    ):

        connection = db_connect()

        rain = connection.execute(
            """
            SELECT *
            FROM rains
            WHERE rain_id = ?
            AND finished = 0
            """,
            (self.rain_id,)
        ).fetchone()

        if not rain:

            connection.close()

            await interaction.response.send_message(
                "This rain has already ended.",
                ephemeral=True
            )

            return

        if now_ts() >= rain["end_time"]:

            connection.close()

            await interaction.response.send_message(
                "This rain has already ended.",
                ephemeral=True
            )

            return

        existing = connection.execute(
            """
            SELECT 1
            FROM rain_participants
            WHERE rain_id = ?
            AND user_id = ?
            """,
            (
                self.rain_id,
                interaction.user.id
            )
        ).fetchone()

        if existing:

            connection.close()

            await interaction.response.send_message(
                "You have already joined this rain.",
                ephemeral=True
            )

            return

        connection.execute(
            """
            INSERT INTO rain_participants
            (rain_id, user_id)
            VALUES (?, ?)
            """,
            (
                self.rain_id,
                interaction.user.id
            )
        )

        connection.commit()
        connection.close()

        await interaction.response.send_message(
            "You joined the rain.",
            ephemeral=True
        )


async def finish_rain(
    rain_id
):

    while True:

        connection = db_connect()

        rain = connection.execute(
            """
            SELECT *
            FROM rains
            WHERE rain_id = ?
            AND finished = 0
            """,
            (rain_id,)
        ).fetchone()

        connection.close()

        if not rain:
            return

        remaining = (
            rain["end_time"] -
            now_ts()
        )

        if remaining <= 0:
            break

        await asyncio.sleep(
            min(
                remaining,
                30
            )
        )

    async with db_lock:

        connection = db_connect()

        rain = connection.execute(
            """
            SELECT *
            FROM rains
            WHERE rain_id = ?
            AND finished = 0
            """,
            (rain_id,)
        ).fetchone()

        if not rain:

            connection.close()
            return

        participants = connection.execute(
            """
            SELECT user_id
            FROM rain_participants
            WHERE rain_id = ?
            """,
            (rain_id,)
        ).fetchall()

        connection.execute(
            """
            UPDATE rains
            SET finished = 1
            WHERE rain_id = ?
            """,
            (rain_id,)
        )

        connection.commit()
        connection.close()

        participant_ids = [
            int(row["user_id"])
            for row in participants
        ]

        total = Decimal(
            rain["amount_crypto"]
        )

        if not participant_ids:

            await asyncio.to_thread(
                change_balance_sync,
                rain["owner_id"],
                rain["crypto"],
                total
            )

            result = discord.Embed(
                title="Rain Ended",
                description=(
                    "Nobody joined the rain.\n\n"
                    f"The full "
                    f"`{format_crypto(total)} "
                    f"{rain['crypto'].upper()}` "
                    "has been returned."
                ),
                color=discord.Color.orange()
            )

        else:

            each = (
                total /
                Decimal(
                    len(participant_ids)
                )
            )

            for user_id in participant_ids:

                await asyncio.to_thread(
                    change_balance_sync,
                    user_id,
                    rain["crypto"],
                    each
                )

            mentions = " ".join(
                f"<@{user_id}>"
                for user_id in participant_ids
            )

            result = discord.Embed(
                title="Rain Finished",
                description=(
                    f"Participants: "
                    f"`{len(participant_ids)}`\n"
                    f"Prize per participant: "
                    f"`{format_crypto(each)} "
                    f"{rain['crypto'].upper()}`\n\n"
                    f"{mentions}"
                ),
                color=discord.Color.green()
            )

    channel = bot.get_channel(
        rain["channel_id"]
    )

    if not channel:
        return

    try:

        await channel.send(
            embed=result
        )

        original = await channel.fetch_message(
            rain["message_id"]
        )

        await original.edit(
            view=None
        )

    except discord.HTTPException:
        pass


@bot.command(name="rain")
async def rain_command(
    ctx,
    amount=None,
    duration=None
):

    if (
        amount is None
        or duration is None
    ):

        await ctx.send(
            "Usage: `.rain 10$ 30m`"
        )

        return

    usd = parse_usd(
        amount
    )

    if usd is None:

        await ctx.send(
            "Invalid amount."
        )

        return

    seconds = parse_duration(
        duration
    )

    if seconds is None:

        await ctx.send(
            "Invalid time. "
            "Maximum rain duration is 5 hours."
        )

        return

    crypto = "sol"

    crypto_amount = usd_to_crypto(
        usd,
        crypto
    )

    current = await get_balance(
        ctx.author.id,
        crypto
    )

    if current < crypto_amount:

        available = crypto_to_usd(
            current,
            crypto
        )

        await ctx.send(
            f"You do not have enough SOL.\n"
            f"Required: `{format_usd(usd)}`\n"
            f"Available: `{format_usd(available)}`"
        )

        return

    await change_balance(
        ctx.author.id,
        crypto,
        -crypto_amount
    )

    rain_id = (
        int(time.time() * 1000) %
        2147483647
    )

    end_time = (
        now_ts() +
        seconds
    )

    embed = discord.Embed(
        title="Rain",
        description=(
            f"{ctx.author.mention} started a rain.\n\n"
            f"Prize: `{format_usd(usd)}`\n"
            f"Asset: `SOL`\n"
            f"Duration: `{format_duration(seconds)}`\n"
            f"Ends: <t:{end_time}:R>\n\n"
            "Click the button below to join."
        ),
        color=discord.Color.blurple()
    )

    message = await ctx.send(
        embed=embed,
        view=RainView(
            rain_id
        )
    )

    connection = db_connect()

    connection.execute(
        """
        INSERT INTO rains
        (
            rain_id,
            owner_id,
            amount_crypto,
            amount_usd,
            crypto,
            end_time,
            channel_id,
            message_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            rain_id,
            ctx.author.id,
            str(crypto_amount),
            str(usd),
            crypto,
            end_time,
            ctx.channel.id,
            message.id
        )
    )

    connection.commit()
    connection.close()

    asyncio.create_task(
        finish_rain(
            rain_id
        )
    )


# =========================================================
# ADD BALANCE
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

    if crypto not in (
        "ltc",
        "sol"
    ):

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
            "Invalid amount."
        )

        return

    crypto_amount = usd_to_crypto(
        usd,
        crypto
    )

    old_balance, new_balance = await change_balance(
        member.id,
        crypto,
        crypto_amount
    )

    embed = discord.Embed(
        title="Balance Added",
        color=discord.Color.green()
    )

    embed.description = (
        f"User: {member.mention}\n"
        f"Added: `{format_usd(usd)}`\n"
        f"Asset: `{crypto.upper()}`\n"
        f"Added: "
        f"`{format_crypto(crypto_amount)} "
        f"{crypto.upper()}`\n\n"
        f"Previous: "
        f"`{format_crypto(old_balance)} "
        f"{crypto.upper()}`\n"
        f"New: "
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

    if crypto not in (
        "ltc",
        "sol"
    ):

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
            "Invalid amount."
        )

        return

    crypto_amount = usd_to_crypto(
        usd,
        crypto
    )

    current = await get_balance(
        member.id,
        crypto
    )

    if current < crypto_amount:

        await ctx.send(
            f"{member.mention} does not have enough "
            f"{crypto.upper()}."
        )

        return

    old_balance, new_balance = await change_balance(
        member.id,
        crypto,
        -crypto_amount
    )

    embed = discord.Embed(
        title="Balance Removed",
        color=discord.Color.red()
    )

    embed.description = (
        f"User: {member.mention}\n"
        f"Removed: `{format_usd(usd)}`\n"
        f"Asset: `{crypto.upper()}`\n"
        f"Removed: "
        f"`{format_crypto(crypto_amount)} "
        f"{crypto.upper()}`\n\n"
        f"Previous: "
        f"`{format_crypto(old_balance)} "
        f"{crypto.upper()}`\n"
        f"New: "
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
# ADD POINTS
# =========================================================

@bot.command(name="add")
@owner_only()
async def add_points_command(
    ctx,
    point: int = None,
    member: discord.Member = None
):

    if (
        point is None
        or member is None
    ):

        await ctx.send(
            "Usage: `.add 100 @user`"
        )

        return

    if point <= 0:

        await ctx.send(
            "Points must be greater than 0."
        )

        return

    old_points, new_points = await change_points(
        member.id,
        point
    )

    embed = discord.Embed(
        title="Points Added",
        color=discord.Color.green()
    )

    embed.description = (
        f"User: {member.mention}\n"
        f"Added: `{point:,} points`\n\n"
        f"Previous Points: `{old_points:,}`\n"
        f"New Points: `{new_points:,}`"
    )

    embed.set_footer(
        text="OWNER CONTROL"
    )

    await ctx.send(
        embed=embed
    )


# =========================================================
# BOT READY
# =========================================================

@bot.event
async def on_ready():

    print("=" * 60)

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
        f"Database: {DB_PATH}"
    )

    print(
        f"LTC automatic deposits: "
        f"{'READY' if LTC_XPUB else 'WAITING FOR LTC_XPUB'}"
    )

    print(
        f"SOL automatic deposits: "
        f"{'READY' if SOL_MASTER_SEED else 'WAITING FOR SOL_MASTER_SEED'}"
    )

    print(
        "Crypto bot is online."
    )

    print("=" * 60)

    await give_owner_starting_balance()

    if not blockchain_scanner.is_running():

        blockchain_scanner.start()


# =========================================================
# COMMAND ERROR HANDLER
# =========================================================

@bot.event
async def on_command_error(
    ctx,
    error
):

    if isinstance(
        error,
        commands.CommandNotFound
    ):
        return

    if isinstance(
        error,
        commands.CheckFailure
    ):

        await ctx.send(
            "You are not authorized "
            "to use this command."
        )

        return

    if isinstance(
        error,
        commands.MemberNotFound
    ):

        await ctx.send(
            "User not found. "
            "Please mention a valid server member."
        )

        return

    if isinstance(
        error,
        commands.MissingRequiredArgument
    ):

        await ctx.send(
            "Missing required argument.\n"
            "Use `.help` to see command usage."
        )

        return

    if isinstance(
        error,
        commands.BadArgument
    ):

        await ctx.send(
            "Invalid command argument.\n"
            "Use `.help` for command usage."
        )

        return

    print(
        f"Command error: {repr(error)}"
    )


# =========================================================
# SHUTDOWN
# =========================================================

async def close_session():

    global http_session

    if http_session:

        await http_session.close()

        http_session = None


async def shutdown():

    await close_session()


# =========================================================
# START
# =========================================================

print(
    "Starting crypto bot..."
)

bot.run(
    BOT_TOKEN
)
