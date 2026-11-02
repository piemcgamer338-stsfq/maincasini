"""
sol_watcher.py — Solana deposit watcher (alert only, no crediting)

Watches your SOL addresses. When a deposit lands it posts an embed in
#depolog so you can go check tickets. Everyone shows as "Anonymous".

Run:   pip install -U discord.py aiohttp
       BOT_TOKEN=xxxx python sol_watcher.py

Optional env:
       DEPOLOG_CHANNEL_ID   exact channel id (else it finds a channel named "depolog")
       SOL_ADDRESSES        comma separated, overrides the list below
       SOL_RPC_URL          default public mainnet RPC (use Helius/QuickNode if rate limited)
       POLL_SECONDS         default 30
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import aiohttp
import discord

# ------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------
TOKEN = (
    os.environ.get("BOT_TOKEN")
    or os.environ.get("DISCORD_TOKEN")
    or os.environ.get("TOKEN")
    or ""
).strip()

CHANNEL_ID = int(os.environ.get("DEPOLOG_CHANNEL_ID", "0") or 0)
CHANNEL_NAME = "depolog"
POLL_SECONDS = int(os.environ.get("POLL_SECONDS", "30"))

RPC_URL = os.environ.get("SOL_RPC_URL", "https://api.mainnet-beta.solana.com").strip()

DEFAULT_ADDRESSES = [
    "43iwsPQnwKuGD7HsPVfxsfMTVD36f3z1qmECFxGxnoC8",
    "77dKxkofTVP1vgo3SLZpMtpaNC8UGBDKray4yJ8jNeSG",
    "7ei1awPcw27T3o2dWKXz2T4heTuZcSjpChswfE9sANm7",
]
ADDRESSES = [
    a.strip()
    for a in (os.environ.get("SOL_ADDRESSES") or ",".join(DEFAULT_ADDRESSES)).split(",")
    if a.strip()
]

SEEN_FILE = Path(__file__).with_name("sol_seen.json")
EMBED_COLOR = 0x9945FF
EXPLORER_TX = "https://solscan.io/tx/{}"

# ------------------------------------------------------------
# SEEN STORE
# ------------------------------------------------------------
def load_seen() -> dict:
    try:
        return json.loads(SEEN_FILE.read_text())
    except Exception:
        return {}


def save_seen(data: dict) -> None:
    try:
        SEEN_FILE.write_text(json.dumps(data))
    except Exception as e:
        print(f"[watcher] could not save seen file: {e}")


# ------------------------------------------------------------
# CHAIN + PRICE
# ------------------------------------------------------------
async def rpc(session: aiohttp.ClientSession, method: str, params: list):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    async with session.post(RPC_URL, json=payload, timeout=aiohttp.ClientTimeout(total=25)) as r:
        data = await r.json(content_type=None)
    if data.get("error"):
        raise RuntimeError(str(data["error"]))
    return data["result"]


async def incoming_txs(session: aiohttp.ClientSession, address: str) -> list[tuple[str, int]]:
    """Return [(signature, lamports_received)] newest first, only txs that raised the balance."""
    sigs = await rpc(session, "getSignaturesForAddress", [address, {"limit": 10, "commitment": "confirmed"}])
    out: list[tuple[str, int]] = []
    for s in sigs:
        if s.get("err"):
            continue
        sig = s["signature"]
        if sig in SEEN_CACHE.get(address, ()):  # already handled, skip the extra RPC call
            out.append((sig, 0))
            continue
        tx = await rpc(session, "getTransaction", [sig, {
            "encoding": "jsonParsed", "commitment": "confirmed", "maxSupportedTransactionVersion": 0}])
        if not tx or tx["meta"].get("err"):
            continue
        keys = [k["pubkey"] if isinstance(k, dict) else k for k in tx["transaction"]["message"]["accountKeys"]]
        if address not in keys:
            continue
        i = keys.index(address)
        delta = tx["meta"]["postBalances"][i] - tx["meta"]["preBalances"][i]
        if delta > 0:
            out.append((sig, delta))
    return out


async def sol_usd(session: aiohttp.ClientSession) -> float | None:
    for url, pick in (
        ("https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd",
         lambda j: j["solana"]["usd"]),
        ("https://min-api.cryptocompare.com/data/price?fsym=SOL&tsyms=USD",
         lambda j: j["USD"]),
    ):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                return float(pick(await r.json()))
        except Exception:
            continue
    return None


SEEN_CACHE: dict = {}


# ------------------------------------------------------------
# DISCORD
# ------------------------------------------------------------
class Watcher(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.seen: dict = load_seen()
        self.session: aiohttp.ClientSession | None = None
        self._task: asyncio.Task | None = None

    async def setup_hook(self):
        self.session = aiohttp.ClientSession()
        self._task = asyncio.create_task(self.loop_forever())

    async def on_ready(self):
        print(f"[watcher] online as {self.user} · watching {len(ADDRESSES)} SOL address(es)")

    def find_channel(self) -> discord.abc.Messageable | None:
        if CHANNEL_ID:
            return self.get_channel(CHANNEL_ID)
        for g in self.guilds:
            for c in g.text_channels:
                if c.name.lower().replace("-", "").replace("_", "") == CHANNEL_NAME:
                    return c
        return None

    async def loop_forever(self):
        await self.wait_until_ready()
        first_run = not self.seen  # first ever run: record old txs silently
        while not self.is_closed():
            try:
                await self.scan(silent=first_run)
                first_run = False
            except Exception as e:
                print(f"[watcher] scan error: {e}")
            await asyncio.sleep(POLL_SECONDS)

    async def scan(self, silent: bool = False):
        assert self.session
        for addr in ADDRESSES:
            try:
                txs = await incoming_txs(self.session, addr)
            except Exception as e:
                print(f"[watcher] {addr[:10]}… failed: {e}")
                continue
            seen_for = self.seen.setdefault(addr, [])
            SEEN_CACHE[addr] = set(seen_for)
            for txid, lamports in reversed(txs):  # oldest first
                if txid in seen_for:
                    continue
                seen_for.append(txid)
                save_seen(self.seen)
                if not silent:
                    await self.announce(txid, lamports)
            self.seen[addr] = seen_for[-200:]
        save_seen(self.seen)

    async def announce(self, txid: str, lamports: int):
        channel = self.find_channel()
        if channel is None:
            print("[watcher] depolog channel not found")
            return
        sol = lamports / 1e9
        price = await sol_usd(self.session)
        usd = f"**${sol * price:,.2f}**" if price else "**?**"

        embed = discord.Embed(
            title="↘ Deposit Received",
            description=(
                f"> `Anonymous` deposited {usd}\n"
                f"> ◈ `{sol:.6f} SOL` · [`{txid[:10]}…{txid[-6:]}`]({EXPLORER_TX.format(txid)})"
            ),
            color=EMBED_COLOR,
        )
        embed.set_footer(text="✦ on-chain deposit ✦")
        embed.timestamp = discord.utils.utcnow()

        view = discord.ui.View()
        view.add_item(discord.ui.Button(
            label="View on explorer ↗", url=EXPLORER_TX.format(txid)
        ))
        await channel.send(embed=embed, view=view)
        print(f"[watcher] deposit {sol:.6f} SOL {txid}")

    async def close(self):
        if self._task:
            self._task.cancel()
        if self.session:
            await self.session.close()
        await super().close()


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("Set BOT_TOKEN env var first.")
    Watcher().run(TOKEN)
