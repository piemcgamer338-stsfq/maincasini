"""
deposit_watcher.py — LTC + SOL deposit watcher (alert only, no crediting)

Watches your LTC and SOL deposit addresses. When money arrives it posts an
embed in #depolog so you can go check tickets. Everyone shows as "Anonymous".

Two ways to use it:
  1) Inside bot.py  -> DepositWatcher(bot).start()   (already patched in bot.py)
  2) Standalone     -> BOT_TOKEN=xxx python deposit_watcher.py

Optional env:
  DEPOLOG_CHANNEL_ID   exact channel id (else finds a channel named "depolog")
  LTC_ADDRESSES        comma separated, overrides defaults
  SOL_ADDRESSES        comma separated, overrides defaults
  SOL_RPC_URL          default public mainnet RPC (Helius/QuickNode if rate limited)
  POLL_SECONDS         default 30
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

import aiohttp
import discord

# ------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------
CHANNEL_NAME = "depolog"
POLL_SECONDS = int(os.environ.get("POLL_SECONDS", "30"))
SOL_RPC_URL = os.environ.get("SOL_RPC_URL", "https://api.mainnet-beta.solana.com").strip()

DEFAULT_LTC = [
    "LZqqL95Uetb12wsdEHbcmAYvsuikQUeRNh",
    "ltc1qw0t8exz0wnn8wxzy5uq7pjkuglwp0sryr0cya2",
    "ltc1qcq2l6h5r0drx0hsg3796rk0phdtmq2fmjhh80s",
]
DEFAULT_SOL = [
    "43iwsPQnwKuGD7HsPVfxsfMTVD36f3z1qmECFxGxnoC8",
    "77dKxkofTVP1vgo3SLZpMtpaNC8UGBDKray4yJ8jNeSG",
    "7ei1awPcw27T3o2dWKXz2T4heTuZcSjpChswfE9sANm7",
]


def _addr_list(env: str, default: list[str]) -> list[str]:
    raw = os.environ.get(env) or ",".join(default)
    return [a.strip() for a in raw.split(",") if a.strip()]


LTC_ADDRESSES = _addr_list("LTC_ADDRESSES", DEFAULT_LTC)
SOL_ADDRESSES = _addr_list("SOL_ADDRESSES", DEFAULT_SOL)

SEEN_FILE = Path(__file__).with_name("deposit_seen.json")
RECENT_SECONDS = 600  # on a fresh start, still alert for deposits newer than this

COINS = {
    "LTC": {
        "color": 0x9B59FF,
        "decimals": 8,
        "tx_url": "https://litecoinspace.org/tx/{}",
        "price_ids": ("litecoin", "LTC"),
    },
    "SOL": {
        "color": 0x9945FF,
        "decimals": 9,
        "tx_url": "https://solscan.io/tx/{}",
        "price_ids": ("solana", "SOL"),
    },
}


# ------------------------------------------------------------
# HTTP HELPERS
# ------------------------------------------------------------
async def _get_json(session: aiohttp.ClientSession, url: str):
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as r:
        if r.status != 200:
            raise RuntimeError(f"{r.status} {url}")
        return await r.json(content_type=None)


async def _rpc(session: aiohttp.ClientSession, method: str, params: list):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    async with session.post(SOL_RPC_URL, json=payload, timeout=aiohttp.ClientTimeout(total=25)) as r:
        data = await r.json(content_type=None)
    if data.get("error"):
        raise RuntimeError(str(data["error"]))
    return data["result"]


# ------------------------------------------------------------
# CHAIN READERS  -> list of (txid, amount_in_smallest_unit, unix_time)
# ------------------------------------------------------------
async def ltc_incoming(session, address: str, skip: set) -> list[tuple[str, int, float]]:
    out: list[tuple[str, int, float]] = []
    try:
        txs = await _get_json(session, f"https://litecoinspace.org/api/address/{address}/txs")
        for tx in txs:
            if tx["txid"] in skip:
                continue
            if any((v.get("prevout") or {}).get("scriptpubkey_address") == address for v in tx.get("vin", [])):
                continue  # our own outgoing / change
            got = sum(o.get("value", 0) for o in tx.get("vout", []) if o.get("scriptpubkey_address") == address)
            if got > 0:
                st = tx.get("status") or {}
                ts = st.get("block_time") if st.get("confirmed") else time.time()
                out.append((tx["txid"], got, float(ts or time.time())))
        return out
    except Exception as e:
        print(f"[DEPOSIT] litecoinspace failed for {address[:10]}…: {e} (trying BlockCypher)")

    data = await _get_json(session, f"https://api.blockcypher.com/v1/ltc/main/addrs/{address}/full?limit=10")
    for tx in data.get("txs", []):
        if tx["hash"] in skip:
            continue
        if any(address in (i.get("addresses") or []) for i in tx.get("inputs", [])):
            continue
        got = sum(o.get("value", 0) for o in tx.get("outputs", []) if address in (o.get("addresses") or []))
        if got > 0:
            out.append((tx["hash"], got, 0.0))  # unknown time -> treated as old on fresh start
    return out


async def sol_incoming(session, address: str, skip: set) -> list[tuple[str, int, float]]:
    sigs = await _rpc(session, "getSignaturesForAddress", [address, {"limit": 10, "commitment": "confirmed"}])
    out: list[tuple[str, int, float]] = []
    for s in sigs:
        sig = s["signature"]
        if s.get("err") or sig in skip:
            continue
        tx = await _rpc(session, "getTransaction", [sig, {
            "encoding": "jsonParsed", "commitment": "confirmed", "maxSupportedTransactionVersion": 0}])
        if not tx or (tx.get("meta") or {}).get("err"):
            continue
        keys = [k["pubkey"] if isinstance(k, dict) else k for k in tx["transaction"]["message"]["accountKeys"]]
        if address not in keys:
            continue
        i = keys.index(address)
        delta = tx["meta"]["postBalances"][i] - tx["meta"]["preBalances"][i]
        if delta > 0:
            out.append((sig, delta, float(s.get("blockTime") or time.time())))
    return out


async def usd_price(session, coin: str) -> float | None:
    gecko, cc = COINS[coin]["price_ids"]
    for url, pick in (
        (f"https://api.coingecko.com/api/v3/simple/price?ids={gecko}&vs_currencies=usd", lambda j: j[gecko]["usd"]),
        (f"https://min-api.cryptocompare.com/data/price?fsym={cc}&tsyms=USD", lambda j: j["USD"]),
    ):
        try:
            return float(pick(await _get_json(session, url)))
        except Exception:
            continue
    return None


# ------------------------------------------------------------
# WATCHER
# ------------------------------------------------------------
class DepositWatcher:
    def __init__(self, client: discord.Client, channel_id: int | None = None):
        self.client = client
        self.channel_id = channel_id or int(os.environ.get("DEPOLOG_CHANNEL_ID", "0") or 0)
        self.session: aiohttp.ClientSession | None = None
        self._task: asyncio.Task | None = None
        try:
            self.seen: dict = json.loads(SEEN_FILE.read_text())
        except Exception:
            self.seen = {}

    async def start(self):
        if self._task:
            return
        self.session = aiohttp.ClientSession()
        self._task = asyncio.create_task(self._loop())
        print(f"[DEPOSIT] Watcher started · {len(LTC_ADDRESSES)} LTC + {len(SOL_ADDRESSES)} SOL address(es)")

    async def stop(self):
        if self._task:
            self._task.cancel()
            self._task = None
        if self.session:
            await self.session.close()
            self.session = None

    def _save(self):
        try:
            SEEN_FILE.write_text(json.dumps(self.seen))
        except Exception as e:
            print(f"[DEPOSIT] could not save seen file: {e}")

    def _channel(self):
        if self.channel_id:
            return self.client.get_channel(self.channel_id)
        for g in self.client.guilds:
            for c in g.text_channels:
                if c.name.lower().replace("-", "").replace("_", "") == CHANNEL_NAME:
                    return c
        return None

    async def _loop(self):
        await self.client.wait_until_ready()
        ch = self._channel()
        print(f"[DEPOSIT] Log channel: {'#' + ch.name if ch else 'NOT FOUND (create #depolog or set DEPOLOG_CHANNEL_ID)'}")
        while True:
            for coin, addrs, reader in (("LTC", LTC_ADDRESSES, ltc_incoming), ("SOL", SOL_ADDRESSES, sol_incoming)):
                for addr in addrs:
                    try:
                        await self._scan(coin, addr, reader)
                    except Exception as e:
                        print(f"[DEPOSIT] {coin} {addr[:10]}… error: {type(e).__name__}: {e}")
            await asyncio.sleep(POLL_SECONDS)

    async def _scan(self, coin: str, addr: str, reader):
        first = addr not in self.seen
        seen_list = self.seen.setdefault(addr, [])
        txs = await reader(self.session, addr, set(seen_list))
        for txid, amount, ts in reversed(txs):  # oldest first
            seen_list.append(txid)
            old = ts <= 0 or (time.time() - ts) > RECENT_SECONDS
            if first and old:
                continue  # fresh start: don't spam old history
            await self._announce(coin, txid, amount)
        self.seen[addr] = seen_list[-300:]
        self._save()

    async def _announce(self, coin: str, txid: str, amount: int):
        ch = self._channel()
        if ch is None:
            print("[DEPOSIT] depolog channel not found — deposit NOT announced:", coin, txid)
            return
        cfg = COINS[coin]
        qty = amount / (10 ** cfg["decimals"])
        price = await usd_price(self.session, coin)
        usd = f"**${qty * price:,.2f}**" if price else "**?**"
        url = cfg["tx_url"].format(txid)

        embed = discord.Embed(
            title="↘ Deposit Received",
            description=(
                f"> `Anonymous` deposited {usd}\n"
                f"> ◈ `{qty:.6f} {coin}` · [`{txid[:10]}…{txid[-6:]}`]({url})"
            ),
            color=cfg["color"],
        )
        embed.set_footer(text="✦ on-chain deposit ✦")
        embed.timestamp = discord.utils.utcnow()
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="View on explorer ↗", url=url))
        await ch.send(embed=embed, view=view)
        print(f"[DEPOSIT] {coin} deposit {qty:.6f} {txid}")

    # kept so old bot.py code calling this never crashes
    async def create_invoice(self, *args, **kwargs):
        raise RuntimeError("Automatic deposits are disabled (initializing).")


# ------------------------------------------------------------
# STANDALONE
# ------------------------------------------------------------
if __name__ == "__main__":
    token = (os.environ.get("BOT_TOKEN") or os.environ.get("DISCORD_TOKEN") or os.environ.get("TOKEN") or "").strip()
    if not token:
        raise SystemExit("Set BOT_TOKEN env var first.")

    class _Client(discord.Client):
        async def setup_hook(self):
            self.watcher = DepositWatcher(self)
            await self.watcher.start()

        async def on_ready(self):
            print(f"[DEPOSIT] online as {self.user}")

    _Client(intents=discord.Intents.default()).run(token)
