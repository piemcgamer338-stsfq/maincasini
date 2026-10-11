"""NexBet shared-address crypto deposit watcher.

Tracks native LTC and SOL transfers to shared, hard-coded addresses. Each invoice
gets a unique exact crypto amount. Exact matches are preferred; a guarded USD-nearest
fallback is used only when there is one clearly closest pending invoice. Balances are
credited atomically with the deposit status to prevent duplicate payouts.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_UP
from typing import Any, Callable, Optional

import aiohttp
import discord

LTC_EXPLORER_API = os.getenv("LTC_EXPLORER_API", "https://litecoinspace.org/api").rstrip("/")
LTC_EXPLORER_TX = os.getenv("LTC_EXPLORER_TX", "https://litecoinspace.org/tx").rstrip("/")
SOL_EXPLORER_TX = "https://solscan.io/tx"
LTC_EMOJI = "<:ltc:1550062603693457430>"


class DepositExplorerView(discord.ui.View):
    def __init__(self, url: str):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(label="View on Explorer", style=discord.ButtonStyle.link, url=url))


class DepositWatcher:
    def __init__(self, bot, ltc_address: str, sol_address: str, price_provider: Callable[[str], Any]):
        self.bot = bot
        self.ltc_address = ltc_address
        self.sol_address = sol_address
        self.price_provider = price_provider
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self.poll_seconds = max(10, int(os.getenv("DEPOSIT_WATCHER_INTERVAL", "15")))
        self.ltc_confirmations = max(1, int(os.getenv("LTC_DEPOSIT_CONFIRMATIONS", "3")))
        self.sol_rpc_urls = [
            os.getenv("SOLANA_RPC_URL", "").strip(),
            "https://api.mainnet-beta.solana.com",
            "https://solana-rpc.publicnode.com",
        ]
        self.sol_rpc_urls = list(dict.fromkeys(x for x in self.sol_rpc_urls if x))

    @property
    def pool(self):
        return self.bot.db.pool

    @property
    def session(self) -> aiohttp.ClientSession:
        return self.bot.http_session

    async def start(self):
        await self._ensure_schema()
        self._stop_event.clear()
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.run(), name="nexbet-deposit-watcher")
        print("[DEPOSIT WATCHER] LTC + SOL address monitoring enabled")

    async def stop(self):
        self._stop_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    async def _ensure_schema(self):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS deposit_invoices (
                    id BIGSERIAL PRIMARY KEY,
                    reference_code TEXT NOT NULL UNIQUE,
                    user_id BIGINT NOT NULL,
                    currency TEXT NOT NULL CHECK (currency IN ('LTC','SOL')),
                    requested_usd NUMERIC(20,8) NOT NULL,
                    quote_price NUMERIC(24,10) NOT NULL,
                    expected_crypto NUMERIC(30,12) NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    txid TEXT,
                    output_index INTEGER,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    expires_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '24 hours'),
                    detected_at TIMESTAMPTZ,
                    credited_at TIMESTAMPTZ,
                    UNIQUE(currency, expected_crypto)
                )
            """)
            await conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_deposit_invoice_tx_output
                ON deposit_invoices(currency, txid, output_index)
                WHERE txid IS NOT NULL AND output_index IS NOT NULL
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS deposit_transactions (
                    currency TEXT NOT NULL CHECK (currency IN ('LTC','SOL')),
                    txid TEXT NOT NULL,
                    output_index INTEGER NOT NULL,
                    amount_crypto NUMERIC(30,12) NOT NULL,
                    estimated_usd NUMERIC(20,8),
                    invoice_id BIGINT,
                    user_id BIGINT,
                    status TEXT NOT NULL DEFAULT 'unmatched',
                    confirmations INTEGER NOT NULL DEFAULT 0,
                    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    confirmed_at TIMESTAMPTZ,
                    credited_at TIMESTAMPTZ,
                    user_notified BOOLEAN NOT NULL DEFAULT FALSE,
                    confirmed_notified BOOLEAN NOT NULL DEFAULT FALSE,
                    log_channel_id BIGINT,
                    log_message_id BIGINT,
                    PRIMARY KEY(currency, txid, output_index)
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS deposit_scanned_transactions (
                    currency TEXT NOT NULL,
                    txid TEXT NOT NULL,
                    scanned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY(currency, txid)
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS deposit_watcher_state (
                    currency TEXT PRIMARY KEY,
                    initialized BOOLEAN NOT NULL DEFAULT FALSE,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            await conn.execute("ALTER TABLE deposit_invoices ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '24 hours')")
            await conn.execute("ALTER TABLE deposit_transactions ADD COLUMN IF NOT EXISTS estimated_usd NUMERIC(20,8)")
            await conn.execute("ALTER TABLE deposit_transactions ADD COLUMN IF NOT EXISTS user_notified BOOLEAN NOT NULL DEFAULT FALSE")
            await conn.execute("ALTER TABLE deposit_transactions ADD COLUMN IF NOT EXISTS confirmed_notified BOOLEAN NOT NULL DEFAULT FALSE")
            await conn.execute("ALTER TABLE deposit_transactions ADD COLUMN IF NOT EXISTS log_channel_id BIGINT")
            await conn.execute("ALTER TABLE deposit_transactions ADD COLUMN IF NOT EXISTS log_message_id BIGINT")

    async def create_invoice(self, user_id: int, currency: str, usd_amount: Decimal, quote_price: Decimal) -> dict:
        currency = currency.upper()
        if currency not in {"LTC", "SOL"}:
            raise ValueError("Unsupported currency")
        if not await self._is_initialized(currency):
            raise RuntimeError(f"The {currency} blockchain watcher is still initializing. Please try again in a few seconds.")
        usd_amount = Decimal(str(usd_amount)).quantize(Decimal("0.01"))
        quote_price = Decimal(str(quote_price))
        if usd_amount <= 0 or quote_price <= 0:
            raise ValueError("Invalid deposit amount or price")
        precision = Decimal("0.00000001") if currency == "LTC" else Decimal("0.000000001")
        expected = (usd_amount / quote_price).quantize(precision, rounding=ROUND_UP)

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1)::bigint)", f"nexbet_deposit_amount_{currency}")
                await conn.execute("INSERT INTO users(user_id) VALUES($1) ON CONFLICT(user_id) DO NOTHING", int(user_id))
                used_rows = await conn.fetch("SELECT expected_crypto FROM deposit_invoices WHERE currency=$1", currency)
                used = {Decimal(str(row["expected_crypto"])) for row in used_rows}
                # Distinguish concurrent requests sent to the same shared address.
                # Every amount is still a valid LTC satoshi / SOL lamport amount.
                for _ in range(2_000_000):
                    if expected not in used:
                        break
                    expected += precision
                else:
                    raise RuntimeError("Could not allocate a unique deposit amount")

                code = f"NX-{currency}-{os.urandom(5).hex().upper()}"
                row = await conn.fetchrow("""
                    INSERT INTO deposit_invoices
                        (reference_code,user_id,currency,requested_usd,quote_price,expected_crypto,status)
                    VALUES($1,$2,$3,$4,$5,$6,'pending')
                    RETURNING id, reference_code, user_id, currency, requested_usd, quote_price,
                              expected_crypto, status, created_at, expires_at
                """, code, int(user_id), currency, usd_amount, quote_price, expected)
                return dict(row)

    async def run(self):
        while not self._stop_event.is_set():
            try:
                await self._scan_ltc()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print(f"[DEPOSIT WATCHER] LTC scan failed: {type(exc).__name__}: {exc}")
            try:
                await self._scan_sol()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print(f"[DEPOSIT WATCHER] SOL scan failed: {type(exc).__name__}: {exc}")
            try:
                await self._process_confirmations()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print(f"[DEPOSIT WATCHER] Confirmation check failed: {type(exc).__name__}: {exc}")
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.poll_seconds)
            except asyncio.TimeoutError:
                pass

    async def _get_json(self, url: str):
        async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=12)) as response:
            if response.status != 200:
                raise RuntimeError(f"HTTP {response.status} from explorer")
            return await response.json(content_type=None)

    async def _sol_rpc(self, method: str, params: list):
        last_error = None
        for endpoint in self.sol_rpc_urls:
            try:
                async with self.session.post(
                    endpoint,
                    json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as response:
                    if response.status != 200:
                        last_error = RuntimeError(f"HTTP {response.status} from Solana RPC")
                        continue
                    data = await response.json(content_type=None)
                    if data.get("error"):
                        last_error = RuntimeError(str(data["error"]))
                        continue
                    return data.get("result")
            except Exception as exc:
                last_error = exc
        if last_error:
            raise last_error
        raise RuntimeError("No Solana RPC endpoint available")

    async def _is_initialized(self, currency: str) -> bool:
        row = await self.pool.fetchrow("SELECT initialized FROM deposit_watcher_state WHERE currency=$1", currency)
        return bool(row and row["initialized"])

    async def _set_initialized(self, currency: str):
        await self.pool.execute("""
            INSERT INTO deposit_watcher_state(currency, initialized) VALUES($1,TRUE)
            ON CONFLICT(currency) DO UPDATE SET initialized=TRUE, updated_at=NOW()
        """, currency)

    async def _baseline_ltc(self) -> bool:
        data = await self._get_json(f"{LTC_EXPLORER_API}/address/{self.ltc_address}/txs")
        if not isinstance(data, list):
            return False
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                for tx in data:
                    txid = tx.get("txid")
                    if txid:
                        await conn.execute("INSERT INTO deposit_scanned_transactions(currency,txid) VALUES('LTC',$1) ON CONFLICT DO NOTHING", txid)
        await self._set_initialized("LTC")
        print(f"[DEPOSIT WATCHER] LTC initial baseline recorded ({len(data)} recent txs; old transfers not auto-credited)")
        return True

    async def _scan_ltc(self):
        if not await self._is_initialized("LTC"):
            if not await self._baseline_ltc():
                return
            return
        data = await self._get_json(f"{LTC_EXPLORER_API}/address/{self.ltc_address}/txs")
        if not isinstance(data, list):
            return
        for tx in reversed(data):
            txid = tx.get("txid")
            if not txid:
                continue
            already = await self.pool.fetchval(
                "SELECT 1 FROM deposit_scanned_transactions WHERE currency='LTC' AND txid=$1", txid
            )
            if already:
                continue
            status = tx.get("status") or {}
            block_time = status.get("block_time")
            observed_time = datetime.fromtimestamp(int(block_time), tz=timezone.utc) if block_time else datetime.now(timezone.utc)
            for index, output in enumerate(tx.get("vout") or []):
                if output.get("scriptpubkey_address") != self.ltc_address:
                    continue
                sats = output.get("value")
                if sats is None:
                    continue
                amount = (Decimal(str(sats)) / Decimal(100_000_000)).quantize(Decimal("0.00000001"))
                await self._record_incoming_output("LTC", txid, index, amount, observed_time)
            await self.pool.execute(
                "INSERT INTO deposit_scanned_transactions(currency,txid) VALUES('LTC',$1) ON CONFLICT DO NOTHING", txid
            )

    async def _baseline_sol(self) -> bool:
        signatures = await self._sol_rpc("getSignaturesForAddress", [self.sol_address, {"limit": 100, "commitment": "confirmed"}])
        if not isinstance(signatures, list):
            return False
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                for item in signatures:
                    signature = item.get("signature")
                    if signature:
                        await conn.execute("INSERT INTO deposit_scanned_transactions(currency,txid) VALUES('SOL',$1) ON CONFLICT DO NOTHING", signature)
        await self._set_initialized("SOL")
        print(f"[DEPOSIT WATCHER] SOL initial baseline recorded ({len(signatures)} recent signatures; old transfers not auto-credited)")
        return True

    async def _scan_sol(self):
        if not await self._is_initialized("SOL"):
            if not await self._baseline_sol():
                return
            return
        signatures = await self._sol_rpc("getSignaturesForAddress", [self.sol_address, {"limit": 100, "commitment": "confirmed"}])
        if not isinstance(signatures, list):
            return
        for item in reversed(signatures):
            signature = item.get("signature")
            if not signature or item.get("err"):
                continue
            already = await self.pool.fetchval(
                "SELECT 1 FROM deposit_scanned_transactions WHERE currency='SOL' AND txid=$1", signature
            )
            if already:
                continue
            tx = await self._sol_rpc("getTransaction", [signature, {"commitment": "confirmed", "maxSupportedTransactionVersion": 0, "encoding": "jsonParsed"}])
            if not tx:
                continue
            observed_time = datetime.fromtimestamp(int(tx.get("blockTime") or item.get("blockTime") or int(datetime.now(timezone.utc).timestamp())), tz=timezone.utc)
            await self._process_sol_transaction(signature, tx, observed_time)
            await self.pool.execute("INSERT INTO deposit_scanned_transactions(currency,txid) VALUES('SOL',$1) ON CONFLICT DO NOTHING", signature)

    async def _process_sol_transaction(self, signature: str, tx: dict, observed_time: datetime):
        message = ((tx.get("transaction") or {}).get("message") or {})
        meta = tx.get("meta") or {}
        instructions: list[tuple[int, dict]] = []
        direct = message.get("instructions") or []
        for i, ix in enumerate(direct):
            instructions.append((i, ix))
        # Native transfers invoked by programs can be in innerInstructions.
        next_idx = len(direct)
        for group in meta.get("innerInstructions") or []:
            for ix in group.get("instructions") or []:
                instructions.append((next_idx, ix))
                next_idx += 1
        for output_idx, instruction in instructions:
            parsed = instruction.get("parsed") or {}
            info = parsed.get("info") or {}
            if parsed.get("type") not in {"transfer", "transferWithSeed"}:
                continue
            if info.get("destination") != self.sol_address:
                continue
            lamports = info.get("lamports")
            if lamports is None:
                continue
            amount = (Decimal(str(lamports)) / Decimal(1_000_000_000)).quantize(Decimal("0.000000001"))
            await self._record_incoming_output("SOL", signature, output_idx, amount, observed_time)

    async def _find_invoice(self, currency: str, amount: Decimal, observed_time: datetime, current_price: Optional[Decimal]):
        # First preference: exact crypto amount. Amounts are reserved uniquely per invoice.
        exact = await self.pool.fetchrow("""
            SELECT * FROM deposit_invoices
            WHERE currency=$1 AND expected_crypto=$2 AND status='pending' AND created_at <= $3 AND expires_at > NOW()
            ORDER BY created_at LIMIT 1
        """, currency, amount, observed_time)
        if exact:
            return exact, None
        # Guarded fallback for wallets/exchanges that round the displayed amount or if
        # price has moved. Only assign the clearly closest open request; ties/large gaps
        # are left for manual review rather than guessing which person paid.
        if not current_price or current_price <= 0:
            return None, None
        actual_usd = amount * current_price
        candidates = await self.pool.fetch("""
            SELECT * FROM deposit_invoices
            WHERE currency=$1 AND status='pending' AND created_at <= $2 AND expires_at > NOW()
            ORDER BY created_at ASC LIMIT 500
        """, currency, observed_time)
        distances = []
        for candidate in candidates:
            wanted = Decimal(str(candidate["requested_usd"]))
            distance = abs(actual_usd - wanted)
            tolerance = max(Decimal("0.25"), wanted * Decimal("0.10"))
            if distance <= tolerance:
                distances.append((distance, candidate))
        if not distances:
            return None, actual_usd
        distances.sort(key=lambda pair: (pair[0], pair[1]["created_at"]))
        if len(distances) > 1 and (distances[1][0] - distances[0][0]) < Decimal("0.02"):
            return None, actual_usd
        return distances[0][1], actual_usd

    async def _record_incoming_output(self, currency: str, txid: str, output_index: int, amount: Decimal, observed_time: datetime):
        current_price = None
        try:
            current_price = await self.price_provider(currency)
        except Exception:
            current_price = None
        invoice, estimated_usd = await self._find_invoice(currency, amount, observed_time, current_price)
        price_at_match = estimated_usd if estimated_usd is not None else (amount * current_price if current_price else None)
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                already = await conn.fetchrow("""
                    SELECT status FROM deposit_transactions
                    WHERE currency=$1 AND txid=$2 AND output_index=$3 FOR UPDATE
                """, currency, txid, int(output_index))
                if already:
                    return
                if invoice:
                    locked = await conn.fetchrow("SELECT * FROM deposit_invoices WHERE id=$1 FOR UPDATE", invoice["id"])
                    if not locked or locked["status"] != "pending":
                        invoice = None
                    else:
                        await conn.execute("""
                            INSERT INTO deposit_transactions(currency,txid,output_index,amount_crypto,estimated_usd,
                                invoice_id,user_id,status,confirmations,detected_at)
                            VALUES($1,$2,$3,$4,$5,$6,$7,'confirming',0,NOW())
                        """, currency, txid, int(output_index), amount, price_at_match, locked["id"], locked["user_id"])
                        await conn.execute("""
                            UPDATE deposit_invoices SET status='confirming',txid=$2,output_index=$3,detected_at=NOW()
                            WHERE id=$1 AND status='pending'
                        """, locked["id"], txid, int(output_index))
                        return
                await conn.execute("""
                    INSERT INTO deposit_transactions(currency,txid,output_index,amount_crypto,estimated_usd,status,detected_at)
                    VALUES($1,$2,$3,$4,$5,'unmatched',NOW())
                    ON CONFLICT DO NOTHING
                """, currency, txid, int(output_index), amount, price_at_match)
        await self._log_unmatched(currency, txid, amount, output_index, price_at_match)

    async def _log_channel(self):
        try:
            raw = await self.bot.db.setting("depositlog_channel_id", "0")
            channel_id = int(raw or 0)
            if not channel_id:
                return None
            channel = self.bot.get_channel(channel_id)
            if channel is None:
                channel = await self.bot.fetch_channel(channel_id)
            return channel
        except Exception:
            return None

    async def _fetch_user(self, user_id: int):
        user = self.bot.get_user(int(user_id))
        if user is None:
            try:
                user = await self.bot.fetch_user(int(user_id))
            except Exception:
                return None
        return user

    def _crypto_amount(self, currency: str, amount: Any) -> str:
        decimals = 8 if currency == "LTC" else 9
        return f"{Decimal(str(amount)):.{decimals}f} {currency}"

    def _points(self, usd: Any) -> str:
        pts = (Decimal(str(usd)) * Decimal(100)).quantize(Decimal("1"))
        return f"{pts:,.0f} pts"

    def _log_embed(self, *, currency: str, txid: str, amount: Any, status: str, invoice=None, confirmations: int = 0, estimated_usd=None):
        is_ltc = currency == "LTC"
        url = f"{LTC_EXPLORER_TX}/{txid}" if is_ltc else f"{SOL_EXPLORER_TX}/{txid}"
        if invoice:
            usd = Decimal(str(invoice["requested_usd"]))
            uid = int(invoice["user_id"])
            user = self.bot.get_user(uid)
            username = user.display_name if user else f"User {uid}"
            asset = f"{LTC_EMOJI}" if is_ltc else "◎"
            embed = discord.Embed(
                title="📥 Deposit Received",
                description=(
                    f"**{username}** deposited **{self._crypto_amount(currency, amount)}** {asset}\n"
                    f"**Deposit value:** ${usd:,.2f} · **{self._points(usd)}**\n"
                    f"**Status:** {status}"
                    + (f" · **Confirmations:** {confirmations}/{self.ltc_confirmations}" if is_ltc and status != "Confirmed" else "")
                    + f"\n**Reference:** `{invoice['reference_code']}`\n**Transaction:** `{txid}`"
                ),
                color=0x35D07F if status == "Confirmed" else 0xE8B94B,
            )
        else:
            estimate = f" · estimated ${Decimal(str(estimated_usd)):,.2f}" if estimated_usd is not None else ""
            embed = discord.Embed(
                title="⚠️ Unmatched crypto deposit — manual review",
                description=(
                    f"Incoming **{self._crypto_amount(currency, amount)}** {LTC_EMOJI if is_ltc else '◎'}{estimate}\n"
                    f"No safe matching invoice was found; no balance was credited.\n**Transaction:** `{txid}`"
                ),
                color=0xE8B94B,
            )
        embed.set_footer(text=f"NexBet · {currency} deposit monitor")
        return embed, url

    async def _log_unmatched(self, currency: str, txid: str, amount: Decimal, output_index: int, estimated_usd):
        channel = await self._log_channel()
        if not channel:
            return
        embed, url = self._log_embed(currency=currency, txid=txid, amount=amount, status="Manual review", estimated_usd=estimated_usd)
        try:
            await channel.send(embed=embed, view=DepositExplorerView(url))
        except Exception as exc:
            print(f"[DEPOSIT WATCHER] Could not log unmatched deposit: {exc}")

    async def _notify_detected(self, row):
        invoice_id = int(row["invoice_id"])
        invoice = await self.pool.fetchrow("SELECT * FROM deposit_invoices WHERE id=$1", invoice_id)
        if not invoice:
            return
        uid = int(invoice["user_id"])
        currency = invoice["currency"]
        amount_crypto = Decimal(str(row["amount_crypto"]))
        requested_usd = Decimal(str(invoice["requested_usd"]))
        estimated_usd = Decimal(str(row["estimated_usd"])) if row["estimated_usd"] is not None else requested_usd
        asset = f"{LTC_EMOJI} Litecoin" if currency == "LTC" else "◎ Solana"
        user = await self._fetch_user(uid)
        if user:
            embed = discord.Embed(
                title="Deposit Detected · Confirming",
                description=(
                    f"Your **${requested_usd:,.2f} {currency}** deposit (~**{self._points(requested_usd)}**) has been detected.\n\n"
                    f"**Received:** `{self._crypto_amount(currency, amount_crypto)}` ({asset})\n"
                    f"**Estimated on-chain value:** ${estimated_usd:,.2f}\n"
                    f"**Status:** Confirming on the blockchain. Your balance will be credited after confirmation."
                ),
                color=0xE8B94B,
            )
            try:
                await user.send(embed=embed)
            except Exception as exc:
                print(f"[DEPOSIT WATCHER] Unable to DM detected deposit to {uid}: {exc}")
        channel = await self._log_channel()
        log_channel_id = None
        log_message_id = None
        if channel:
            embed, url = self._log_embed(
                currency=currency,
                txid=row["txid"],
                amount=amount_crypto,
                status="Confirming",
                invoice=invoice,
                confirmations=int(row["confirmations"] or 0),
                estimated_usd=estimated_usd,
            )
            try:
                message = await channel.send(embed=embed, view=DepositExplorerView(url))
                log_channel_id, log_message_id = channel.id, message.id
            except Exception as exc:
                print(f"[DEPOSIT WATCHER] Could not send deposit log: {exc}")
        await self.pool.execute("""
            UPDATE deposit_transactions SET user_notified=TRUE, log_channel_id=$4, log_message_id=$5
            WHERE currency=$1 AND txid=$2 AND output_index=$3
        """, currency, row["txid"], int(row["output_index"]), log_channel_id, log_message_id)

    async def _scan_sol_signatures_status(self, signature: str):
        result = await self._sol_rpc("getSignatureStatuses", [[signature], {"searchTransactionHistory": True}])
        values = (result or {}).get("value") or []
        status = values[0] if values else None
        if not status or status.get("err"):
            return False
        return status.get("confirmationStatus") == "finalized"

    async def _ltc_confirmations(self, txid: str) -> int:
        status = await self._get_json(f"{LTC_EXPLORER_API}/tx/{txid}/status")
        if not status or not status.get("confirmed"):
            return 0
        block_height = status.get("block_height")
        if not block_height:
            return 0
        tip = await self._get_json(f"{LTC_EXPLORER_API}/blocks/tip/height")
        return max(0, int(tip) - int(block_height) + 1)

    async def _process_confirmations(self):
        # Retry final DMs/log edits if a process restart happened after the atomic credit.
        credited_rows = await self.pool.fetch("""
            SELECT dt.*, di.requested_usd, di.quote_price, di.reference_code, di.expected_crypto,
                   di.user_id AS invoice_user_id, di.status AS invoice_status
            FROM deposit_transactions dt
            JOIN deposit_invoices di ON di.id=dt.invoice_id
            WHERE dt.status='credited' AND dt.confirmed_notified=FALSE
            ORDER BY dt.credited_at ASC LIMIT 100
        """)
        for credited_row in credited_rows:
            try:
                count = int(credited_row["confirmations"] or 0)
                await self._notify_confirmed(credited_row, count)
            except Exception as exc:
                print(f"[DEPOSIT WATCHER] Could not retry final notification: {exc}")

        rows = await self.pool.fetch("""
            SELECT dt.*, di.requested_usd, di.quote_price, di.reference_code, di.expected_crypto,
                   di.user_id AS invoice_user_id, di.status AS invoice_status
            FROM deposit_transactions dt
            JOIN deposit_invoices di ON di.id=dt.invoice_id
            WHERE dt.status='confirming'
            ORDER BY dt.detected_at ASC LIMIT 100
        """)
        for row in rows:
            if not row["user_notified"]:
                await self._notify_detected(row)
            currency = row["currency"]
            try:
                if currency == "LTC":
                    confirmations = await self._ltc_confirmations(row["txid"])
                    enough = confirmations >= self.ltc_confirmations
                else:
                    finalized = await self._scan_sol_signatures_status(row["txid"])
                    confirmations = 1 if finalized else 0
                    enough = finalized
            except Exception:
                continue
            await self.pool.execute("""
                UPDATE deposit_transactions SET confirmations=$4,
                    confirmed_at=CASE WHEN $4>0 AND confirmed_at IS NULL THEN NOW() ELSE confirmed_at END
                WHERE currency=$1 AND txid=$2 AND output_index=$3 AND status='confirming'
            """, currency, row["txid"], int(row["output_index"]), int(confirmations))
            if enough:
                credited = await self._credit_confirmed(row, confirmations)
                if credited:
                    await self._notify_confirmed(row, confirmations)

    async def _credit_confirmed(self, row, confirmations: int) -> bool:
        currency = row["currency"]
        txid = row["txid"]
        output_index = int(row["output_index"])
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                tx = await conn.fetchrow("""
                    SELECT * FROM deposit_transactions
                    WHERE currency=$1 AND txid=$2 AND output_index=$3 FOR UPDATE
                """, currency, txid, output_index)
                if not tx or tx["status"] == "credited":
                    return False
                if tx["status"] != "confirming" or tx["invoice_id"] is None:
                    return False
                invoice = await conn.fetchrow("SELECT * FROM deposit_invoices WHERE id=$1 FOR UPDATE", tx["invoice_id"])
                if not invoice or invoice["status"] == "credited":
                    return False
                user_id = int(invoice["user_id"])
                amount_usd = Decimal(str(invoice["requested_usd"]))
                await conn.execute("INSERT INTO users(user_id) VALUES($1) ON CONFLICT(user_id) DO NOTHING", user_id)
                user_row = await conn.fetchrow("""
                    UPDATE users
                    SET balance=balance+$2,
                        lifetime_deposit=COALESCE(lifetime_deposit,0)+$2,
                        updated_at=NOW()
                    WHERE user_id=$1 AND frozen=FALSE
                    RETURNING balance
                """, user_id, amount_usd)
                if not user_row:
                    await conn.execute("UPDATE deposit_transactions SET status='review' WHERE currency=$1 AND txid=$2 AND output_index=$3", currency, txid, output_index)
                    await conn.execute("UPDATE deposit_invoices SET status='review' WHERE id=$1", invoice["id"])
                    return False
                amount_crypto = Decimal(str(tx["amount_crypto"]))
                note = f"Automatic {currency} deposit; invoice={invoice['reference_code']}; amount={amount_crypto}; txid={txid}; confirmations={confirmations}"
                await conn.execute("""
                    INSERT INTO transactions(user_id,kind,amount,balance_after,note)
                    VALUES($1,'crypto_deposit',$2,$3,$4)
                """, user_id, amount_usd, user_row["balance"], note)
                await conn.execute("""
                    UPDATE deposit_transactions SET status='credited',credited_at=NOW(),confirmations=$4
                    WHERE currency=$1 AND txid=$2 AND output_index=$3
                """, currency, txid, output_index, int(confirmations))
                await conn.execute("UPDATE deposit_invoices SET status='credited',credited_at=NOW() WHERE id=$1", invoice["id"])
                return True

    async def _notify_confirmed(self, row, confirmations: int):
        fresh_row = await self.pool.fetchrow("""
            SELECT * FROM deposit_transactions
            WHERE currency=$1 AND txid=$2 AND output_index=$3
        """, row["currency"], row["txid"], int(row["output_index"]))
        if fresh_row:
            row = fresh_row
        invoice = await self.pool.fetchrow("SELECT * FROM deposit_invoices WHERE id=$1", row["invoice_id"])
        if not invoice:
            return
        currency = invoice["currency"]
        amount_usd = Decimal(str(invoice["requested_usd"]))
        amount_crypto = Decimal(str(row["amount_crypto"]))
        uid = int(invoice["user_id"])
        user = await self._fetch_user(uid)
        if user:
            embed = discord.Embed(
                title="Deposit Confirmed · NexBet",
                description=(
                    f"Your **{self._crypto_amount(currency, amount_crypto)}** deposit is confirmed.\n"
                    f"**Credited:** ${amount_usd:,.2f} (~**{self._points(amount_usd)}**)\n"
                    + (f"**Confirmations:** {confirmations}/{self.ltc_confirmations}\n" if currency == "LTC" else "**Solana status:** Finalized\n")
                    + f"**Reference:** `{invoice['reference_code']}`\nYour balance has been updated."
                ),
                color=0x35D07F,
            )
            try:
                await user.send(embed=embed)
            except Exception as exc:
                print(f"[DEPOSIT WATCHER] Unable to DM confirmed deposit to {uid}: {exc}")
        channel = None
        message = None
        log_channel_id = row["log_channel_id"]
        log_message_id = row["log_message_id"]
        if log_channel_id and log_message_id:
            try:
                channel = self.bot.get_channel(int(log_channel_id)) or await self.bot.fetch_channel(int(log_channel_id))
                message = await channel.fetch_message(int(log_message_id))
            except Exception:
                message = None
        updated_row = dict(row)
        updated_row["confirmations"] = confirmations
        status = "Confirmed"
        embed, url = self._log_embed(
            currency=currency, txid=row["txid"], amount=amount_crypto, status=status,
            invoice=invoice, confirmations=confirmations,
        )
        if message:
            try:
                await message.edit(embed=embed, view=DepositExplorerView(url))
            except Exception as exc:
                print(f"[DEPOSIT WATCHER] Could not edit confirmed log: {exc}")
        else:
            channel = channel or await self._log_channel()
            if channel:
                try:
                    await channel.send(embed=embed, view=DepositExplorerView(url))
                except Exception as exc:
                    print(f"[DEPOSIT WATCHER] Could not send confirmed log: {exc}")
        await self.pool.execute("""
            UPDATE deposit_transactions SET confirmed_notified=TRUE
            WHERE currency=$1 AND txid=$2 AND output_index=$3
        """, currency, row["txid"], int(row["output_index"]))

    async def _log_unmatched(self, currency: str, txid: str, amount: Decimal, output_index: int, estimated_usd):
        channel = await self._log_channel()
        if not channel:
            return
        embed, url = self._log_embed(currency=currency, txid=txid, amount=amount, status="Manual review", estimated_usd=estimated_usd)
        try:
            await channel.send(embed=embed, view=DepositExplorerView(url))
        except Exception as exc:
            print(f"[DEPOSIT WATCHER] Could not log unmatched deposit: {exc}")
