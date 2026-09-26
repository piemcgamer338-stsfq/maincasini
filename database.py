from __future__ import annotations

import asyncpg
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional


class Database:

    def __init__(self, url: str):
        self.url = url
        self.pool: Optional[asyncpg.Pool] = None

    # =========================================================
    # CONNECTION
    # =========================================================

    async def connect(self):

        self.pool = await asyncpg.create_pool(
            self.url,
            min_size=1,
            max_size=10,
            command_timeout=30,
        )

        async with self.pool.acquire() as conn:

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,

                    balance NUMERIC(20,8) NOT NULL DEFAULT 0,
                    vault NUMERIC(20,8) NOT NULL DEFAULT 0,

                    wagered NUMERIC(20,8) NOT NULL DEFAULT 0,
                    won_games INTEGER NOT NULL DEFAULT 0,
                    games_played INTEGER NOT NULL DEFAULT 0,
                    losses NUMERIC(20,8) NOT NULL DEFAULT 0,

                    rakeback NUMERIC(20,8) NOT NULL DEFAULT 0,
                    rakeback_total NUMERIC(20,8) NOT NULL DEFAULT 0,

                    lifetime_deposit NUMERIC(20,8) NOT NULL DEFAULT 0,
                    lifetime_withdraw NUMERIC(20,8) NOT NULL DEFAULT 0,

                    affiliate_id BIGINT,
                    affiliate_earnings NUMERIC(20,8)
                        NOT NULL DEFAULT 0,

                    rank_index INTEGER NOT NULL DEFAULT 0,
                    rank_reward_claimed INTEGER NOT NULL DEFAULT 0,

                    daily_wager NUMERIC(20,8)
                        NOT NULL DEFAULT 0,

                    weekly_wager NUMERIC(20,8)
                        NOT NULL DEFAULT 0,

                    monthly_wager NUMERIC(20,8)
                        NOT NULL DEFAULT 0,

                    race_wager NUMERIC(20,8)
                        NOT NULL DEFAULT 0,

                    total_tips_sent NUMERIC(20,8)
                        NOT NULL DEFAULT 0,

                    total_tips_received NUMERIC(20,8)
                        NOT NULL DEFAULT 0,

                    total_rain_received NUMERIC(20,8)
                        NOT NULL DEFAULT 0,

                    verified BOOLEAN NOT NULL DEFAULT FALSE,

                    frozen BOOLEAN NOT NULL DEFAULT FALSE,

                    created_at TIMESTAMPTZ
                        NOT NULL DEFAULT NOW(),

                    updated_at TIMESTAMPTZ
                        NOT NULL DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS house (
                    id INTEGER PRIMARY KEY,
                    balance NUMERIC(20,8) NOT NULL DEFAULT 0
                );

                INSERT INTO house(id, balance)
                VALUES(1, 0)
                ON CONFLICT(id) DO NOTHING;

                CREATE TABLE IF NOT EXISTS transactions (
                    id BIGSERIAL PRIMARY KEY,

                    user_id BIGINT NOT NULL,

                    kind TEXT NOT NULL,

                    amount NUMERIC(20,8)
                        NOT NULL,

                    balance_after NUMERIC(20,8),

                    note TEXT NOT NULL DEFAULT '',

                    created_at TIMESTAMPTZ
                        NOT NULL DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS game_history (
                    id BIGSERIAL PRIMARY KEY,

                    user_id BIGINT NOT NULL,

                    game TEXT NOT NULL,

                    bet NUMERIC(20,8)
                        NOT NULL,

                    payout NUMERIC(20,8)
                        NOT NULL DEFAULT 0,

                    profit NUMERIC(20,8)
                        NOT NULL DEFAULT 0,

                    result TEXT NOT NULL DEFAULT '',

                    game_id BIGINT,

                    server_hash TEXT,
                    server_seed TEXT,
                    client_seed TEXT,
                    nonce BIGINT,

                    created_at TIMESTAMPTZ
                        NOT NULL DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS deposit_addresses (
                    id BIGSERIAL PRIMARY KEY,

                    user_id BIGINT NOT NULL,

                    currency TEXT NOT NULL,

                    address TEXT NOT NULL,

                    derivation_index INTEGER,

                    created_at TIMESTAMPTZ
                        NOT NULL DEFAULT NOW(),

                    UNIQUE(user_id, currency),

                    UNIQUE(currency, address)
                );

                CREATE TABLE IF NOT EXISTS deposits (
                    id BIGSERIAL PRIMARY KEY,

                    user_id BIGINT,

                    currency TEXT NOT NULL,

                    address TEXT,

                    txid TEXT NOT NULL,

                    amount NUMERIC(30,12)
                        NOT NULL,

                    confirmations INTEGER
                        NOT NULL DEFAULT 0,

                    required_confirmations INTEGER
                        NOT NULL DEFAULT 3,

                    credited BOOLEAN
                        NOT NULL DEFAULT FALSE,

                    created_at TIMESTAMPTZ
                        NOT NULL DEFAULT NOW(),

                    confirmed_at TIMESTAMPTZ,

                    UNIQUE(currency, txid)
                );

                CREATE TABLE IF NOT EXISTS withdrawals (
                    id BIGSERIAL PRIMARY KEY,

                    user_id BIGINT NOT NULL,

                    currency TEXT NOT NULL,

                    address TEXT NOT NULL,

                    amount NUMERIC(30,12)
                        NOT NULL,

                    fee NUMERIC(30,12)
                        NOT NULL DEFAULT 0,

                    status TEXT NOT NULL DEFAULT 'pending',

                    txid TEXT,

                    created_at TIMESTAMPTZ
                        NOT NULL DEFAULT NOW(),

                    processed_at TIMESTAMPTZ
                );

                CREATE TABLE IF NOT EXISTS promo_codes (
                    code TEXT PRIMARY KEY,

                    amount NUMERIC(20,8)
                        NOT NULL,

                    max_uses INTEGER NOT NULL,

                    uses INTEGER NOT NULL DEFAULT 0,

                    requirement INTEGER NOT NULL DEFAULT 0,

                    active BOOLEAN NOT NULL DEFAULT TRUE,

                    created_by BIGINT,

                    created_at TIMESTAMPTZ
                        NOT NULL DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS promo_claims (
                    code TEXT NOT NULL,

                    user_id BIGINT NOT NULL,

                    claimed_at TIMESTAMPTZ
                        NOT NULL DEFAULT NOW(),

                    PRIMARY KEY(code, user_id)
                );

                CREATE TABLE IF NOT EXISTS affiliates (
                    user_id BIGINT PRIMARY KEY,

                    code TEXT UNIQUE NOT NULL,

                    referred_by BIGINT,

                    referrals INTEGER NOT NULL DEFAULT 0,

                    earnings NUMERIC(20,8)
                        NOT NULL DEFAULT 0,

                    total_paid NUMERIC(20,8)
                        NOT NULL DEFAULT 0,

                    created_at TIMESTAMPTZ
                        NOT NULL DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS affiliate_referrals (
                    user_id BIGINT PRIMARY KEY,

                    affiliate_id BIGINT NOT NULL,

                    created_at TIMESTAMPTZ
                        NOT NULL DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,

                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS races (
                    id BIGSERIAL PRIMARY KEY,

                    name TEXT NOT NULL DEFAULT '3 Day Race',

                    started_at TIMESTAMPTZ
                        NOT NULL DEFAULT NOW(),

                    ended_at TIMESTAMPTZ,

                    active BOOLEAN NOT NULL DEFAULT TRUE
                );

                CREATE TABLE IF NOT EXISTS race_entries (
                    race_id BIGINT NOT NULL,

                    user_id BIGINT NOT NULL,

                    wagered NUMERIC(20,8)
                        NOT NULL DEFAULT 0,

                    PRIMARY KEY(race_id, user_id)
                );

                CREATE TABLE IF NOT EXISTS rain_events (
                    id TEXT PRIMARY KEY,

                    creator_id BIGINT NOT NULL,

                    amount NUMERIC(20,8)
                        NOT NULL,

                    duration INTEGER NOT NULL,

                    started_at TIMESTAMPTZ
                        NOT NULL DEFAULT NOW(),

                    ended_at TIMESTAMPTZ,

                    active BOOLEAN NOT NULL DEFAULT TRUE
                );

                CREATE TABLE IF NOT EXISTS rain_entries (
                    rain_id TEXT NOT NULL,

                    user_id BIGINT NOT NULL,

                    amount NUMERIC(20,8)
                        NOT NULL DEFAULT 0,

                    joined_at TIMESTAMPTZ
                        NOT NULL DEFAULT NOW(),

                    PRIMARY KEY(rain_id, user_id)
                );

                CREATE TABLE IF NOT EXISTS private_channels (
                    channel_id BIGINT PRIMARY KEY,

                    owner_id BIGINT NOT NULL,

                    created_at TIMESTAMPTZ
                        NOT NULL DEFAULT NOW(),

                    below_balance_since TIMESTAMPTZ
                );

                CREATE TABLE IF NOT EXISTS seeds (
                    user_id BIGINT PRIMARY KEY,

                    server_seed TEXT NOT NULL,

                    client_seed TEXT NOT NULL,

                    nonce BIGINT NOT NULL DEFAULT 0,

                    created_at TIMESTAMPTZ
                        NOT NULL DEFAULT NOW()
                );

                CREATE INDEX IF NOT EXISTS idx_history_user
                ON game_history(user_id);

                CREATE INDEX IF NOT EXISTS idx_history_created
                ON game_history(created_at DESC);

                CREATE INDEX IF NOT EXISTS idx_users_wagered
                ON users(wagered DESC);

                CREATE INDEX IF NOT EXISTS idx_race_wagered
                ON race_entries(race_id, wagered DESC);

                CREATE INDEX IF NOT EXISTS idx_deposits_txid
                ON deposits(txid);

                CREATE INDEX IF NOT EXISTS idx_withdrawals_user
                ON withdrawals(user_id);
            """)

            # -------------------------------------------------
            # SAFE MIGRATIONS FOR EXISTING DATABASES
            # -------------------------------------------------

            migrations = [
                """
                ALTER TABLE transactions
                ADD COLUMN IF NOT EXISTS
                balance_after NUMERIC(20,8)
                """,

                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS
                updated_at TIMESTAMPTZ
                NOT NULL DEFAULT NOW()
                """,

                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS
                lifetime_withdraw NUMERIC(20,8)
                NOT NULL DEFAULT 0
                """,

                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS
                affiliate_id BIGINT
                """,

                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS
                affiliate_earnings NUMERIC(20,8)
                NOT NULL DEFAULT 0
                """,

                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS
                rank_index INTEGER
                NOT NULL DEFAULT 0
                """,

                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS
                rank_reward_claimed INTEGER
                NOT NULL DEFAULT 0
                """,

                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS
                daily_wager NUMERIC(20,8)
                NOT NULL DEFAULT 0
                """,

                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS
                weekly_wager NUMERIC(20,8)
                NOT NULL DEFAULT 0
                """,

                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS
                monthly_wager NUMERIC(20,8)
                NOT NULL DEFAULT 0
                """,

                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS
                race_wager NUMERIC(20,8)
                NOT NULL DEFAULT 0
                """,

                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS
                total_tips_sent NUMERIC(20,8)
                NOT NULL DEFAULT 0
                """,

                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS
                total_tips_received NUMERIC(20,8)
                NOT NULL DEFAULT 0
                """,

                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS
                total_rain_received NUMERIC(20,8)
                NOT NULL DEFAULT 0
                """,

                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS
                verified BOOLEAN
                NOT NULL DEFAULT FALSE
                """,

                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS
                frozen BOOLEAN
                NOT NULL DEFAULT FALSE
                """,
            ]

            for migration in migrations:
                await conn.execute(migration)

    async def close(self):

        if self.pool:
            await self.pool.close()

    # =========================================================
    # BASIC USER FUNCTIONS
    # =========================================================

    async def ensure(self, user_id: int):

        async with self.pool.acquire() as conn:

            await conn.execute(
                """
                INSERT INTO users(user_id)
                VALUES($1)
                ON CONFLICT(user_id)
                DO NOTHING
                """,
                user_id,
            )

    async def user(self, user_id: int):

        await self.ensure(user_id)

        return await self.pool.fetchrow(
            """
            SELECT *
            FROM users
            WHERE user_id=$1
            """,
            user_id,
        )

    async def balance(
        self,
        user_id: int,
    ) -> Decimal:

        row = await self.user(user_id)

        return Decimal(
            str(row["balance"])
        )

    # =========================================================
    # BALANCE CHANGE
    # =========================================================

    async def change_balance(
        self,
        user_id: int,
        amount,
        kind: str = "adjustment",
        note: str = "",
    ) -> bool:

        amount = Decimal(str(amount))

        async with self.pool.acquire() as conn:

            async with conn.transaction():

                await conn.execute(
                    """
                    INSERT INTO users(user_id)
                    VALUES($1)
                    ON CONFLICT(user_id)
                    DO NOTHING
                    """,
                    user_id,
                )

                row = await conn.fetchrow(
                    """
                    UPDATE users
                    SET
                        balance = balance + $2,
                        updated_at = NOW()
                    WHERE user_id=$1
                      AND frozen=FALSE
                      AND balance + $2 >= 0
                    RETURNING balance
                    """,
                    user_id,
                    amount,
                )

                if not row:
                    return False

                await conn.execute(
                    """
                    INSERT INTO transactions(
                        user_id,
                        kind,
                        amount,
                        balance_after,
                        note
                    )
                    VALUES($1,$2,$3,$4,$5)
                    """,
                    user_id,
                    kind,
                    amount,
                    row["balance"],
                    note,
                )

                return True

    # =========================================================
    # GAME SETTLEMENT
    #
    # IMPORTANT:
    # The game command first removes the stake.
    #
    # record_game() ONLY adds the payout when payout > 0.
    #
    # This prevents the old double-credit bug.
    # =========================================================

    async def record_game(
        self,
        user_id: int,
        bet,
        payout,
        game: str,
        *,
        result: str = "",
        game_id: Optional[int] = None,
        server_hash: Optional[str] = None,
        server_seed: Optional[str] = None,
        client_seed: Optional[str] = None,
        nonce: Optional[int] = None,
        race_amount=None,
    ):

        bet = Decimal(str(bet))
        payout = Decimal(str(payout))

        if race_amount is None:
            race_amount = bet

        race_amount = Decimal(
            str(race_amount)
        )

        profit = payout - bet

        async with self.pool.acquire() as conn:

            async with conn.transaction():

                await conn.execute(
                    """
                    INSERT INTO users(user_id)
                    VALUES($1)
                    ON CONFLICT(user_id)
                    DO NOTHING
                    """,
                    user_id,
                )

                if payout > 0:

                    await conn.execute(
                        """
                        UPDATE users
                        SET
                            balance = balance + $2,
                            wagered = wagered + $3,
                            games_played = games_played + 1,
                            won_games = won_games + 1,
                            daily_wager = daily_wager + $3,
                            weekly_wager = weekly_wager + $3,
                            monthly_wager = monthly_wager + $3,
                            race_wager = race_wager + $4,
                            rakeback = rakeback,
                            updated_at = NOW()
                        WHERE user_id=$1
                        """,
                        user_id,
                        payout,
                        bet,
                        race_amount,
                    )

                else:

                    rakeback = bet * Decimal("0.01")

                    await conn.execute(
                        """
                        UPDATE users
                        SET
                            wagered = wagered + $2,
                            games_played = games_played + 1,
                            losses = losses + $2,
                            daily_wager = daily_wager + $2,
                            weekly_wager = weekly_wager + $2,
                            monthly_wager = monthly_wager + $2,
                            race_wager = race_wager + $3,
                            rakeback = rakeback + $4,
                            rakeback_total = rakeback_total + $4,
                            updated_at = NOW()
                        WHERE user_id=$1
                        """,
                        user_id,
                        bet,
                        race_amount,
                        rakeback,
                    )

                await conn.execute(
                    """
                    INSERT INTO game_history(
                        user_id,
                        game,
                        bet,
                        payout,
                        profit,
                        result,
                        game_id,
                        server_hash,
                        server_seed,
                        client_seed,
                        nonce
                    )
                    VALUES(
                        $1,$2,$3,$4,$5,
                        $6,$7,$8,$9,$10,$11
                    )
                    """,
                    user_id,
                    game,
                    bet,
                    payout,
                    profit,
                    result,
                    game_id,
                    server_hash,
                    server_seed,
                    client_seed,
                    nonce,
                )

                await conn.execute(
                    """
                    INSERT INTO transactions(
                        user_id,
                        kind,
                        amount,
                        note
                    )
                    VALUES(
                        $1,
                        'game',
                        $2,
                        $3
                    )
                    """,
                    user_id,
                    profit,
                    game,
                )

    # =========================================================
    # RAKEBACK
    # =========================================================

    async def rakeback(
        self,
        user_id: int,
    ) -> Decimal:

        row = await self.user(user_id)

        return Decimal(
            str(row["rakeback"])
        )

    async def claim_rakeback(
        self,
        user_id: int,
    ) -> Decimal:

        async with self.pool.acquire() as conn:

            async with conn.transaction():

                row = await conn.fetchrow(
                    """
                    SELECT rakeback
                    FROM users
                    WHERE user_id=$1
                    FOR UPDATE
                    """,
                    user_id,
                )

                if not row:
                    return Decimal("0")

                amount = Decimal(
                    str(row["rakeback"])
                )

                if amount <= 0:
                    return Decimal("0")

                await conn.execute(
                    """
                    UPDATE users
                    SET
                        balance = balance + $2,
                        rakeback = 0,
                        updated_at = NOW()
                    WHERE user_id=$1
                    """,
                    user_id,
                    amount,
                )

                await conn.execute(
                    """
                    INSERT INTO transactions(
                        user_id,
                        kind,
                        amount,
                        note
                    )
                    VALUES(
                        $1,
                        'rakeback',
                        $2,
                        'Rakeback claim'
                    )
                    """,
                    user_id,
                    amount,
                )

                return amount

    # =========================================================
    # HISTORY
    # =========================================================

    async def history(
        self,
        user_id: int,
        limit: int = 10,
    ):

        return await self.pool.fetch(
            """
            SELECT *
            FROM game_history
            WHERE user_id=$1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            user_id,
            limit,
        )

    # =========================================================
    # LEADERBOARD
    # =========================================================

    async def leaderboard(
        self,
        limit: int = 10,
    ):

        return await self.pool.fetch(
            """
            SELECT user_id, wagered
            FROM users
            WHERE wagered > 0
            ORDER BY wagered DESC
            LIMIT $1
            """,
            limit,
        )

    async def top_wager_race(
        self,
        limit: int = 3,
    ):

        return await self.pool.fetch(
            """
            SELECT user_id, wagered
            FROM users
            WHERE wagered > 0
            ORDER BY wagered DESC
            LIMIT $1
            """,
            limit,
        )

    # =========================================================
    # RACE
    # =========================================================

    async def start_race(
        self,
        name: str = "3 Day Race",
    ) -> int:

        async with self.pool.acquire() as conn:

            await conn.execute(
                """
                UPDATE races
                SET
                    active=FALSE,
                    ended_at=NOW()
                WHERE active=TRUE
                """
            )

            row = await conn.fetchrow(
                """
                INSERT INTO races(name)
                VALUES($1)
                RETURNING id
                """,
                name,
            )

            await conn.execute(
                """
                UPDATE users
                SET race_wager=0
                """
            )

            return row["id"]

    async def active_race(self):

        return await self.pool.fetchrow(
            """
            SELECT *
            FROM races
            WHERE active=TRUE
            ORDER BY id DESC
            LIMIT 1
            """
        )

    async def end_race(self):

        async with self.pool.acquire() as conn:

            async with conn.transaction():

                race = await conn.fetchrow(
                    """
                    SELECT *
                    FROM races
                    WHERE active=TRUE
                    ORDER BY id DESC
                    LIMIT 1
                    FOR UPDATE
                    """
                )

                if not race:
                    return None

                await conn.execute(
                    """
                    UPDATE races
                    SET
                        active=FALSE,
                        ended_at=NOW()
                    WHERE id=$1
                    """,
                    race["id"],
                )

                return race

    async def race_leaderboard(
        self,
        race_id: int,
        limit: int = 10,
    ):

        return await self.pool.fetch(
            """
            SELECT user_id, wagered
            FROM race_entries
            WHERE race_id=$1
            ORDER BY wagered DESC
            LIMIT $2
            """,
            race_id,
            limit,
        )

    async def add_race_wager(
        self,
        race_id: int,
        user_id: int,
        amount,
    ):

        amount = Decimal(str(amount))

        await self.pool.execute(
            """
            INSERT INTO race_entries(
                race_id,
                user_id,
                wagered
            )
            VALUES($1,$2,$3)
            ON CONFLICT(race_id,user_id)
            DO UPDATE SET
                wagered =
                    race_entries.wagered + EXCLUDED.wagered
            """,
            race_id,
            user_id,
            amount,
        )

    # =========================================================
    # DEPOSIT ADDRESSES
    # =========================================================

    async def get_deposit_address(
        self,
        user_id: int,
        currency: str,
    ) -> Optional[str]:

        row = await self.pool.fetchrow(
            """
            SELECT address
            FROM deposit_addresses
            WHERE user_id=$1
              AND currency=$2
            """,
            user_id,
            currency.upper(),
        )

        return row["address"] if row else None

    async def save_deposit_address(
        self,
        user_id: int,
        currency: str,
        address: str,
        derivation_index: Optional[int] = None,
    ):

        return await self.pool.fetchrow(
            """
            INSERT INTO deposit_addresses(
                user_id,
                currency,
                address,
                derivation_index
            )
            VALUES($1,$2,$3,$4)
            ON CONFLICT(user_id,currency)
            DO UPDATE SET
                address=EXCLUDED.address,
                derivation_index=
                    EXCLUDED.derivation_index
            RETURNING *
            """,
            user_id,
            currency.upper(),
            address,
            derivation_index,
        )

    # =========================================================
    # DEPOSITS
    # =========================================================

    async def process_deposit(
        self,
        deposit: dict,
    ) -> bool:

        currency = str(
            deposit.get("currency", "")
        ).upper()

        txid = str(
            deposit.get("txid", "")
        ).strip()

        amount = Decimal(
            str(
                deposit.get(
                    "amount",
                    "0",
                )
            )
        )

        address = deposit.get(
            "address"
        )

        confirmations = int(
            deposit.get(
                "confirmations",
                0,
            )
        )

        required = int(
            deposit.get(
                "required_confirmations",
                3,
            )
        )

        if not currency or not txid:
            return False

        async with self.pool.acquire() as conn:

            async with conn.transaction():

                existing = await conn.fetchrow(
                    """
                    SELECT *
                    FROM deposits
                    WHERE currency=$1
                      AND txid=$2
                    FOR UPDATE
                    """,
                    currency,
                    txid,
                )

                if existing and existing["credited"]:
                    return False

                user_id = None

                if address:

                    row = await conn.fetchrow(
                        """
                        SELECT user_id
                        FROM deposit_addresses
                        WHERE currency=$1
                          AND address=$2
                        """,
                        currency,
                        address,
                    )

                    if row:
                        user_id = row["user_id"]

                if user_id is None:
                    return False

                if existing:

                    await conn.execute(
                        """
                        UPDATE deposits
                        SET
                            confirmations=$3
                        WHERE currency=$1
                          AND txid=$2
                        """,
                        currency,
                        txid,
                        confirmations,
                    )

                else:

                    await conn.execute(
                        """
                        INSERT INTO deposits(
                            user_id,
                            currency,
                            address,
                            txid,
                            amount,
                            confirmations,
                            required_confirmations
                        )
                        VALUES(
                            $1,$2,$3,$4,$5,$6,$7
                        )
                        """,
                        user_id,
                        currency,
                        address,
                        txid,
                        amount,
                        confirmations,
                        required,
                    )

                if confirmations < required:
                    return False

                already = await conn.fetchval(
                    """
                    SELECT credited
                    FROM deposits
                    WHERE currency=$1
                      AND txid=$2
                    """,
                    currency,
                    txid,
                )

                if already:
                    return False

                await conn.execute(
                    """
                    UPDATE deposits
                    SET
                        credited=TRUE,
                        confirmed_at=NOW()
                    WHERE currency=$1
                      AND txid=$2
                    """,
                    currency,
                    txid,
                )

                await conn.execute(
                    """
                    UPDATE users
                    SET
                        balance = balance + $2,
                        lifetime_deposit =
                            lifetime_deposit + $2,
                        updated_at=NOW()
                    WHERE user_id=$1
                    """,
                    user_id,
                    amount,
                )

                await conn.execute(
                    """
                    INSERT INTO transactions(
                        user_id,
                        kind,
                        amount,
                        note
                    )
                    VALUES(
                        $1,
                        'deposit',
                        $2,
                        $3
                    )
                    """,
                    user_id,
                    amount,
                    f"{currency} deposit {txid}",
                )

                return True

    # =========================================================
    # WITHDRAWALS
    # =========================================================

    async def create_withdrawal(
        self,
        user_id: int,
        currency: str,
        address: str,
        amount,
        fee=Decimal("0"),
    ) -> bool:

        amount = Decimal(str(amount))
        fee = Decimal(str(fee))

        total = amount + fee

        async with self.pool.acquire() as conn:

            async with conn.transaction():

                row = await conn.fetchrow(
                    """
                    UPDATE users
                    SET
                        balance = balance - $2,
                        lifetime_withdraw =
                            lifetime_withdraw + $2,
                        updated_at=NOW()
                    WHERE user_id=$1
                      AND frozen=FALSE
                      AND balance >= $2
                    RETURNING balance
                    """,
                    user_id,
                    total,
                )

                if not row:
                    return False

                await conn.execute(
                    """
                    INSERT INTO withdrawals(
                        user_id,
                        currency,
                        address,
                        amount,
                        fee
                    )
                    VALUES($1,$2,$3,$4,$5)
                    """,
                    user_id,
                    currency.upper(),
                    address,
                    amount,
                    fee,
                )

                await conn.execute(
                    """
                    INSERT INTO transactions(
                        user_id,
                        kind,
                        amount,
                        balance_after,
                        note
                    )
                    VALUES(
                        $1,
                        'withdraw',
                        $2,
                        $3,
                        $4
                    )
                    """,
                    user_id,
                    -total,
                    row["balance"],
                    f"{currency.upper()} withdrawal",
                )

                return True

    # =========================================================
    # TIPS
    # =========================================================

    async def tip(
        self,
        sender: int,
        receiver: int,
        amount,
    ) -> bool:

        amount = Decimal(str(amount))

        if amount <= 0:
            return False

        if sender == receiver:
            return False

        async with self.pool.acquire() as conn:

            async with conn.transaction():

                await conn.execute(
                    """
                    INSERT INTO users(user_id)
                    VALUES($1)
                    ON CONFLICT(user_id)
                    DO NOTHING
                    """,
                    sender,
                )

                await conn.execute(
                    """
                    INSERT INTO users(user_id)
                    VALUES($1)
                    ON CONFLICT(user_id)
                    DO NOTHING
                    """,
                    receiver,
                )

                sender_row = await conn.fetchrow(
                    """
                    UPDATE users
                    SET
                        balance=balance-$2,
                        total_tips_sent =
                            total_tips_sent+$2,
                        updated_at=NOW()
                    WHERE user_id=$1
                      AND frozen=FALSE
                      AND balance >= $2
                    RETURNING balance
                    """,
                    sender,
                    amount,
                )

                if not sender_row:
                    return False

                await conn.execute(
                    """
                    UPDATE users
                    SET
                        balance=balance+$2,
                        total_tips_received =
                            total_tips_received+$2,
                        updated_at=NOW()
                    WHERE user_id=$1
                    """,
                    receiver,
                    amount,
                )

                await conn.execute(
                    """
                    INSERT INTO transactions(
                        user_id,
                        kind,
                        amount,
                        note
                    )
                    VALUES(
                        $1,
                        'tip_sent',
                        $2,
                        $3
                    )
                    """,
                    sender,
                    -amount,
                    f"Tip to {receiver}",
                )

                await conn.execute(
                    """
                    INSERT INTO transactions(
                        user_id,
                        kind,
                        amount,
                        note
                    )
                    VALUES(
                        $1,
                        'tip_received',
                        $2,
                        $3
                    )
                    """,
                    receiver,
                    amount,
                    f"Tip from {sender}",
                )

                return True

    # =========================================================
    # PROMO CODES
    # =========================================================

    async def create_code(
        self,
        code: str,
        amount,
        max_uses: int,
        requirement: int,
        created_by: int,
    ):

        return await self.pool.fetchrow(
            """
            INSERT INTO promo_codes(
                code,
                amount,
                max_uses,
                requirement,
                created_by
            )
            VALUES($1,$2,$3,$4,$5)
            RETURNING *
            """,
            code.upper(),
            Decimal(str(amount)),
            max_uses,
            requirement,
            created_by,
        )

    async def claim_code(
        self,
        user_id: int,
        code: str,
    ) -> tuple[bool, str, Decimal]:

        code = code.upper().strip()

        async with self.pool.acquire() as conn:

            async with conn.transaction():

                promo = await conn.fetchrow(
                    """
                    SELECT *
                    FROM promo_codes
                    WHERE code=$1
                      AND active=TRUE
                    FOR UPDATE
                    """,
                    code,
                )

                if not promo:
                    return (
                        False,
                        "That promo code is invalid.",
                        Decimal("0"),
                    )

                if promo["uses"] >= promo["max_uses"]:
                    return (
                        False,
                        "That promo code has reached its maximum uses.",
                        Decimal("0"),
                    )

                already = await conn.fetchval(
                    """
                    SELECT 1
                    FROM promo_claims
                    WHERE code=$1
                      AND user_id=$2
                    """,
                    code,
                    user_id,
                )

                if already:
                    return (
                        False,
                        "You already claimed this code.",
                        Decimal("0"),
                    )

                requirement = promo["requirement"]

                user = await conn.fetchrow(
                    """
                    SELECT *
                    FROM users
                    WHERE user_id=$1
                    """,
                    user_id,
                )

                if requirement == 1:
                    if Decimal(
                        str(user["lifetime_deposit"])
                    ) < Decimal("1"):
                        return (
                            False,
                            "You need at least $1 deposited.",
                            Decimal("0"),
                        )

                elif requirement == 2:
                    if Decimal(
                        str(user["lifetime_deposit"])
                    ) < Decimal("25"):
                        return (
                            False,
                            "You need at least $25 deposited.",
                            Decimal("0"),
                        )

                elif requirement == 3:
                    if Decimal(
                        str(user["wagered"])
                    ) < Decimal("10"):
                        return (
                            False,
                            "You need at least $10 wagered.",
                            Decimal("0"),
                        )

                amount = Decimal(
                    str(promo["amount"])
                )

                await conn.execute(
                    """
                    INSERT INTO promo_claims(
                        code,
                        user_id
                    )
                    VALUES($1,$2)
                    """,
                    code,
                    user_id,
                )

                await conn.execute(
                    """
                    UPDATE promo_codes
                    SET uses=uses+1
                    WHERE code=$1
                    """,
                    code,
                )

                await conn.execute(
                    """
                    UPDATE users
                    SET
                        balance=balance+$2,
                        updated_at=NOW()
                    WHERE user_id=$1
                    """,
                    user_id,
                    amount,
                )

                await conn.execute(
                    """
                    INSERT INTO transactions(
                        user_id,
                        kind,
                        amount,
                        note
                    )
                    VALUES(
                        $1,
                        'promo',
                        $2,
                        $3
                    )
                    """,
                    user_id,
                    amount,
                    f"Promo {code}",
                )

                return (
                    True,
                    "Promo claimed.",
                    amount,
                )

    # =========================================================
    # AFFILIATES
    # =========================================================

    async def create_affiliate(
        self,
        user_id: int,
        code: str,
    ):

        return await self.pool.fetchrow(
            """
            INSERT INTO affiliates(
                user_id,
                code
            )
            VALUES($1,$2)
            ON CONFLICT(user_id)
            DO UPDATE SET code=EXCLUDED.code
            RETURNING *
            """,
            user_id,
            code,
        )

    async def affiliate(self, user_id: int):

        return await self.pool.fetchrow(
            """
            SELECT *
            FROM affiliates
            WHERE user_id=$1
            """,
            user_id,
        )

    async def set_referrer(
        self,
        user_id: int,
        affiliate_id: int,
    ) -> bool:

        async with self.pool.acquire() as conn:

            async with conn.transaction():

                existing = await conn.fetchval(
                    """
                    SELECT affiliate_id
                    FROM affiliate_referrals
                    WHERE user_id=$1
                    """,
                    user_id,
                )

                if existing:
                    return False

                if user_id == affiliate_id:
                    return False

                await conn.execute(
                    """
                    INSERT INTO affiliate_referrals(
                        user_id,
                        affiliate_id
                    )
                    VALUES($1,$2)
                    """,
                    user_id,
                    affiliate_id,
                )

                await conn.execute(
                    """
                    UPDATE users
                    SET affiliate_id=$2
                    WHERE user_id=$1
                    """,
                    user_id,
                    affiliate_id,
                )

                await conn.execute(
                    """
                    UPDATE affiliates
                    SET referrals=referrals+1
                    WHERE user_id=$1
                    """,
                    affiliate_id,
                )

                return True

    async def add_affiliate_earnings(
        self,
        referred_user: int,
        wager_amount,
    ):

        wager_amount = Decimal(
            str(wager_amount)
        )

        async with self.pool.acquire() as conn:

            row = await conn.fetchrow(
                """
                SELECT affiliate_id
                FROM users
                WHERE user_id=$1
                """,
                referred_user,
            )

            if not row or not row["affiliate_id"]:
                return Decimal("0")

            affiliate_id = row["affiliate_id"]

            referrals = await conn.fetchval(
                """
                SELECT referrals
                FROM affiliates
                WHERE user_id=$1
                """,
                affiliate_id,
            )

            referrals = int(referrals or 0)

            rate = Decimal("0")

            for minimum, tier_rate in (
                (1, Decimal("0.0010")),
                (10, Decimal("0.0020")),
                (25, Decimal("0.0035")),
                (100, Decimal("0.0050")),
            ):
                if referrals >= minimum:
                    rate = tier_rate

            if rate <= 0:
                return Decimal("0")

            earning = (
                wager_amount * rate
            ).quantize(
                Decimal("0.00000001")
            )

            await conn.execute(
                """
                UPDATE affiliates
                SET earnings=earnings+$2
                WHERE user_id=$1
                """,
                affiliate_id,
                earning,
            )

            await conn.execute(
                """
                UPDATE users
                SET affiliate_earnings =
                    affiliate_earnings+$2
                WHERE user_id=$1
                """,
                affiliate_id,
                earning,
            )

            return earning

    async def claim_affiliate(
        self,
        user_id: int,
    ) -> Decimal:

        async with self.pool.acquire() as conn:

            async with conn.transaction():

                row = await conn.fetchrow(
                    """
                    SELECT earnings
                    FROM affiliates
                    WHERE user_id=$1
                    FOR UPDATE
                    """,
                    user_id,
                )

                if not row:
                    return Decimal("0")

                amount = Decimal(
                    str(row["earnings"])
                )

                if amount <= 0:
                    return Decimal("0")

                await conn.execute(
                    """
                    UPDATE affiliates
                    SET
                        earnings=0,
                        total_paid=total_paid+$2
                    WHERE user_id=$1
                    """,
                    user_id,
                    amount,
                )

                await conn.execute(
                    """
                    UPDATE users
                    SET
                        balance=balance+$2,
                        affiliate_earnings=0
                    WHERE user_id=$1
                    """,
                    user_id,
                    amount,
                )

                await conn.execute(
                    """
                    INSERT INTO transactions(
                        user_id,
                        kind,
                        amount,
                        note
                    )
                    VALUES(
                        $1,
                        'affiliate',
                        $2,
                        'Affiliate claim'
                    )
                    """,
                    user_id,
                    amount,
                )

                return amount

    # =========================================================
    # RAIN
    # =========================================================

    async def create_rain(
        self,
        rain_id: str,
        creator_id: int,
        amount,
        duration: int,
    ):

        await self.pool.execute(
            """
            INSERT INTO rain_events(
                id,
                creator_id,
                amount,
                duration
            )
            VALUES($1,$2,$3,$4)
            """,
            rain_id,
            creator_id,
            Decimal(str(amount)),
            duration,
        )

    async def join_rain(
        self,
        rain_id: str,
        user_id: int,
    ) -> bool:

        try:

            await self.pool.execute(
                """
                INSERT INTO rain_entries(
                    rain_id,
                    user_id
                )
                VALUES($1,$2)
                """,
                rain_id,
                user_id,
            )

            return True

        except asyncpg.UniqueViolationError:

            return False

    async def rain_entries(
        self,
        rain_id: str,
    ):

        return await self.pool.fetch(
            """
            SELECT user_id
            FROM rain_entries
            WHERE rain_id=$1
            ORDER BY joined_at
            """,
            rain_id,
        )

    async def finish_rain(
        self,
        rain_id: str,
    ):

        await self.pool.execute(
            """
            UPDATE rain_events
            SET
                active=FALSE,
                ended_at=NOW()
            WHERE id=$1
            """,
            rain_id,
        )

    # =========================================================
    # SETTINGS
    # =========================================================

    async def setting(
        self,
        key: str,
        default: str = "",
    ):

        row = await self.pool.fetchrow(
            """
            SELECT value
            FROM settings
            WHERE key=$1
            """,
            key,
        )

        if not row:
            return default

        return row["value"]

    async def set_setting(
        self,
        key: str,
        value: str,
    ):

        await self.pool.execute(
            """
            INSERT INTO settings(
                key,
                value
            )
            VALUES($1,$2)
            ON CONFLICT(key)
            DO UPDATE SET
                value=EXCLUDED.value
            """,
            key,
            value,
        )

    # =========================================================
    # FREEZE
    # =========================================================

    async def set_frozen(
        self,
        user_id: int,
        frozen: bool,
    ):

        await self.pool.execute(
            """
            UPDATE users
            SET frozen=$2
            WHERE user_id=$1
            """,
            user_id,
            frozen,
        )

    # =========================================================
    # SEEDS
    # =========================================================

    async def get_seed_state(
        self,
        user_id: int,
    ):

        row = await self.pool.fetchrow(
            """
            SELECT *
            FROM seeds
            WHERE user_id=$1
            """,
            user_id,
        )

        if row:
            return row

        import secrets

        server_seed = secrets.token_hex(32)
        client_seed = secrets.token_hex(16)

        return await self.pool.fetchrow(
            """
            INSERT INTO seeds(
                user_id,
                server_seed,
                client_seed,
                nonce
            )
            VALUES($1,$2,$3,0)
            RETURNING *
            """,
            user_id,
            server_seed,
            client_seed,
        )

    async def rotate_seed(
        self,
        user_id: int,
    ):

        import secrets

        server_seed = secrets.token_hex(32)
        client_seed = secrets.token_hex(16)

        return await self.pool.fetchrow(
            """
            INSERT INTO seeds(
                user_id,
                server_seed,
                client_seed,
                nonce
            )
            VALUES($1,$2,$3,0)
            ON CONFLICT(user_id)
            DO UPDATE SET
                server_seed=EXCLUDED.server_seed,
                client_seed=EXCLUDED.client_seed,
                nonce=0
            RETURNING *
            """,
            user_id,
            server_seed,
            client_seed,
        )

    async def next_nonce(
        self,
        user_id: int,
    ) -> int:

        row = await self.pool.fetchrow(
            """
            UPDATE seeds
            SET nonce=nonce+1
            WHERE user_id=$1
            RETURNING nonce
            """,
            user_id,
        )

        if not row:
            await self.get_seed_state(user_id)

            row = await self.pool.fetchrow(
                """
                UPDATE seeds
                SET nonce=nonce+1
                WHERE user_id=$1
                RETURNING nonce
                """,
                user_id,
            )

        return int(row["nonce"])

    # =========================================================
    # RANK
    # =========================================================

    async def set_rank(
        self,
        user_id: int,
        rank_index: int,
    ):

        await self.pool.execute(
            """
            UPDATE users
            SET rank_index=$2
            WHERE user_id=$1
            """,
            user_id,
            rank_index,
        )

    async def rank_index(
        self,
        user_id: int,
    ) -> int:

        row = await self.user(user_id)

        return int(
            row["rank_index"]
        )


    async def claim_rank_reward(
        self,
        user_id: int,
        rank_index: int,
        reward=None,
    ) -> bool:
        """Atomically claim a rank reward.

        If reward is supplied, it is credited in the same transaction as the
        claimed-rank marker. The optional third argument preserves compatibility
        with older bot builds that only passed user_id and rank_index.
        """
        reward_value = Decimal(str(reward)) if reward is not None else Decimal("0")

        if rank_index < 0:
            return False
        if reward_value < 0:
            return False

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    SELECT rank_reward_claimed, balance, frozen
                    FROM users
                    WHERE user_id=$1
                    FOR UPDATE
                    """,
                    user_id,
                )

                if not row or row["frozen"]:
                    return False

                claimed = int(row["rank_reward_claimed"] or 0)
                if rank_index <= claimed:
                    return False

                if reward_value > 0:
                    updated = await conn.fetchrow(
                        """
                        UPDATE users
                        SET
                            balance = balance + $2,
                            rank_reward_claimed = $3,
                            updated_at = NOW()
                        WHERE user_id=$1
                        RETURNING balance
                        """,
                        user_id,
                        reward_value,
                        rank_index,
                    )

                    if not updated:
                        return False

                    await conn.execute(
                        """
                        INSERT INTO transactions(
                            user_id, kind, amount, balance_after, note
                        )
                        VALUES($1, 'rank_reward', $2, $3, $4)
                        """,
                        user_id,
                        reward_value,
                        updated["balance"],
                        f"Rank reward #{rank_index}",
                    )
                else:
                    await conn.execute(
                        """
                        UPDATE users
                        SET rank_reward_claimed=$2,
                            updated_at=NOW()
                        WHERE user_id=$1
                        """,
                        user_id,
                        rank_index,
                    )

                return True
