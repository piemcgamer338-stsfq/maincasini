"""Central configuration.  Set these values as Railway environment variables."""
from __future__ import annotations

import os


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


CASINO_NAME = env("CASINO_NAME", "Casino")
TOKEN = env("DISCORD_TOKEN")
DATABASE_URL = env("DATABASE_URL")
LTC_XPUB = env("LTC_XPUB")
LTC_DERIVATION_PATH = env("LTC_DERIVATION_PATH")
PAYMENT_PROVIDER_API_KEY = env("PAYMENT_PROVIDER_API_KEY")
OPENAI_API_KEY = env("OPENAI_API_KEY")
BSC_RPC_URL = env("BSC_RPC_URL")
SOLANA_RPC_URL = env("SOLANA_RPC_URL")
WIN_LOG_CHANNEL_ID = int(env("WIN_LOG_CHANNEL_ID", "0") or 0)
WITHDRAW_LOG_CHANNEL_ID = int(env("WITHDRAW_LOG_CHANNEL_ID", "0") or 0)
RAIN_ROLE_ID = int(env("RAIN_ROLE_ID", "0") or 0)
ADMIN_USER_IDS = {int(value) for value in env("ADMIN_USER_IDS").split(",") if value.strip().isdigit()}

POINT_USD = 0.005
GAME_COOLDOWN_SECONDS = 3
MIN_WITHDRAW = {"LTC": 20, "SOL": 220, "USDT": 150}

E = {
    "games": "<:x_games:1549794186893598851>", "general": "<:Commands:1549794393131585607>",
    "balance": "<:info:1549794239351758928>", "win": "<:Tick:1549965628050513960>",
    "lose": "<:cross2n:1550062215220961370>", "points": "<:usd:1550062382469087274>",
    "deposit": "<:deposit:1550062472411484180>", "withdraw": "<:withdraw:1550062505873641512>",
    "ltc": "<:ltc:1550062603693457430>", "sol": "<:Solana:1550062641081356348>",
    "usdt": "<:usdt:1550062695380819978>", "blackjack": "<:blackjack:1550062769301102602>",
    "bomb": "<:bomb:1550062841485066324>", "diamond": "<:diamond:1550062867796201483>",
    "coin": "<:Coin:1550064228918886402>", "hilo": "<:hilo_resis:1550063012121935893>",
    "graph": "<:GraphUp:1550063076714348574>", "rain": "<:cloud:1550063489093996585>",
    "gift": "<:gift:1550063393736499200>",
}
