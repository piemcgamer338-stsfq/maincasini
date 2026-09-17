from __future__ import annotations

import asyncpg
from datetime import datetime, timedelta, timezone


class Database:
    def __init__(self, url: str): self.url, self.pool = url, None

    async def connect(self):
        self.pool = await asyncpg.create_pool(self.url, min_size=1, max_size=8, command_timeout=30)
        async with self.pool.acquire() as c:
            await c.execute('''
            CREATE TABLE IF NOT EXISTS users (
              user_id BIGINT PRIMARY KEY, balance NUMERIC(20,4) NOT NULL DEFAULT 0,
              vault NUMERIC(20,4) NOT NULL DEFAULT 0, wagered NUMERIC(20,4) NOT NULL DEFAULT 0,
              won_games INT NOT NULL DEFAULT 0, games_played INT NOT NULL DEFAULT 0,
              tips_sent NUMERIC(20,4) NOT NULL DEFAULT 0, tips_received NUMERIC(20,4) NOT NULL DEFAULT 0,
              bonus_received NUMERIC(20,4) NOT NULL DEFAULT 0, losses NUMERIC(20,4) NOT NULL DEFAULT 0,
              rakeback NUMERIC(20,4) NOT NULL DEFAULT 0, rakeback_total NUMERIC(20,4) NOT NULL DEFAULT 0,
              daily_at TIMESTAMPTZ, weekly_at TIMESTAMPTZ, monthly_at TIMESTAMPTZ,
              lifetime_deposit NUMERIC(20,4) NOT NULL DEFAULT 0, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS transactions (
              id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL, kind TEXT NOT NULL, amount NUMERIC(20,4) NOT NULL,
              note TEXT NOT NULL DEFAULT '', created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS codes (code TEXT PRIMARY KEY, max_uses INT NOT NULL, uses INT NOT NULL DEFAULT 0, amount NUMERIC(20,4) NOT NULL, active BOOLEAN NOT NULL DEFAULT TRUE);
            CREATE TABLE IF NOT EXISTS code_claims (code TEXT NOT NULL, user_id BIGINT NOT NULL, PRIMARY KEY(code,user_id));
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            ''')

    async def close(self):
        if self.pool: await self.pool.close()

    async def ensure(self, user_id: int):
        await self.pool.execute("INSERT INTO users(user_id) VALUES($1) ON CONFLICT (user_id) DO NOTHING", user_id)

    async def user(self, user_id: int):
        await self.ensure(user_id)
        return await self.pool.fetchrow("SELECT * FROM users WHERE user_id=$1", user_id)

    async def change_balance(self, user_id: int, amount: float, kind="adjustment", note="") -> bool:
        async with self.pool.acquire() as c:
            async with c.transaction():
                await c.execute("INSERT INTO users(user_id) VALUES($1) ON CONFLICT (user_id) DO NOTHING", user_id)
                row = await c.fetchrow("UPDATE users SET balance=balance+$2 WHERE user_id=$1 AND balance+$2>=0 RETURNING balance", user_id, amount)
                if not row: return False
                await c.execute("INSERT INTO transactions(user_id,kind,amount,note) VALUES($1,$2,$3,$4)", user_id, kind, amount, note)
                return True

    async def record_game(self, user_id: int, bet: float, payout: float, game: str):
        async with self.pool.acquire() as c:
            async with c.transaction():
                await c.execute("UPDATE users SET wagered=wagered+$2,games_played=games_played+1 WHERE user_id=$1", user_id, bet)
                if payout > 0:
                    await c.execute("UPDATE users SET balance=balance+$2,won_games=won_games+1,rakeback=rakeback+$3,rakeback_total=rakeback_total+$3 WHERE user_id=$1", user_id, payout, payout*.005)
                else:
                    await c.execute("UPDATE users SET losses=losses+$2,rakeback=rakeback+$3,rakeback_total=rakeback_total+$3 WHERE user_id=$1", user_id, bet, bet*.01)
                await c.execute("INSERT INTO transactions(user_id,kind,amount,note) VALUES($1,'game',$2,$3)", user_id, payout-bet, game)

    async def setting(self, key: str, default=""):
        row = await self.pool.fetchrow("SELECT value FROM settings WHERE key=$1", key)
        return row["value"] if row else default

    async def set_setting(self, key: str, value: str):
        await self.pool.execute("INSERT INTO settings(key,value) VALUES($1,$2) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value", key, value)

    async def leaderboard(self):
        return await self.pool.fetch("SELECT user_id,wagered FROM users ORDER BY wagered DESC LIMIT 10")
