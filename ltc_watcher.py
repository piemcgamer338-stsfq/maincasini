"""
ltc_watcher.py — Litecoin deposit watcher (alert only, no crediting)

Watches your LTC addresses. When a deposit lands it posts an embed in
#depolog so you can go check tickets. Everyone shows as "Anonymous".

Run:   pip install -U discord.py aiohttp
       BOT_TOKEN=xxxx python ltc_watcher.py

Optional env:
       DEPOLOG_CHANNEL_ID   exact channel id (else it finds a channel named "depolog")
       LTC_ADDRESSES        comma separated, overrides the list below
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

DEFAULT_ADDRESSES = [
    "LZqqL95Uetb12wsdEHbcmAYvsuikQUeRNh",
    "ltc1qw0t8exz0wnn8wxzy5uq7pjkuglwp0sryr0cya2",
    "ltc1qcq2l6h5r0drx0hsg3796rk0phdtmq2fmjhh80s",
]
ADDRESSES = [
    a.strip()
    for a in (os.environ.get("LTC_ADDRESSES") or ",".join(DEFAULT_ADDRESSES)).split(",")
    if a.strip()
]

SEEN_FILE = Path(__file__).with_name("ltc_seen.json")
EMBED_COLOR = 0x9B59FF
EXPLORER_TX = "https://litecoinspace.org/tx/{}"

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
async def fetch_json(session: aiohttp.ClientSession, url: str):
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as r:
        if r.status != 200:
            raise RuntimeError(f"{r.status} {url}")
        return await r.json()


async def incoming_txs(session: aiohttp.ClientSession, address: str) -> list[tuple[str, int]]:
    """Return [(txid, litoshis_received)] for txs that pay `address` (not spends)."""
    out: list[tuple[str, int]] = []
    try:
        txs = await fetch_json(session, f"https://litecoinspace.org/api/address/{address}/txs")
        for tx in txs:
            # skip txs where this address is an input (our own outgoing / change)
            if any((v.get("prevout") or {}).get("scriptpubkey_address") == address for v in tx.get("vin", [])):
                continue
            got = sum(
                o.get("value", 0)
                for o in tx.get("vout", [])
                if o.get("scriptpubkey_address") == address
            )
            if got > 0:
                out.append((tx["txid"], got))
        return out
    except Exception as e:
        print(f"[watcher] litecoinspace failed for {address[:10]}…: {e}")

    # fallback: BlockCypher
    txs = (await fetch_json(
        session, f"https://api.blockcypher.com/v1/ltc/main/addrs/{address}/full?limit=10"
    )).get("txs", [])
    for tx in txs:
        if any(address in (i.get("addresses") or []) for i in tx.get("inputs", [])):
            continue
        got = sum(o.get("value", 0) for o in tx.get("outputs", []) if address in (o.get("addresses") or []))
        if got > 0:
            out.append((tx["hash"], got))
    return out


async def ltc_usd(session: aiohttp.ClientSession) -> float | None:
    for url, pick in (
        ("https://api.coingecko.com/api/v3/simple/price?ids=litecoin&vs_currencies=usd",
         lambda j: j["litecoin"]["usd"]),
        ("https://min-api.cryptocompare.com/data/price?fsym=LTC&tsyms=USD",
         lambda j: j["USD"]),
    ):
        try:
            return float(pick(await fetch_json(session, url)))
        except Exception:
            continue
    return None


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
        print(f"[watcher] online as {self.user} · watching {len(ADDRESSES)} LTC address(es)")

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
            for txid, litoshis in reversed(txs):  # oldest first
                if txid in seen_for:
                    continue
                seen_for.append(txid)
                save_seen(self.seen)
                if not silent:
                    await self.announce(txid, litoshis)
            self.seen[addr] = seen_for[-200:]
        save_seen(self.seen)

    async def announce(self, txid: str, litoshis: int):
        channel = self.find_channel()
        if channel is None:
            print("[watcher] depolog channel not found")
            return
        ltc = litoshis / 1e8
        price = await ltc_usd(self.session)
        usd = f"**${ltc * price:,.2f}**" if price else "**?**"

        embed = discord.Embed(
            title="↘ Deposit Received",
            description=(
                f"> `Anonymous` deposited {usd}\n"
                f"> ◈ `{ltc:.6f} LTC` · [`{txid[:10]}…{txid[-6:]}`]({EXPLORER_TX.format(txid)})"
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
        print(f"[watcher] deposit {ltc:.6f} LTC {txid}")

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
