"""House-funds dashboard extension for PacePot.

The main bot remains in bot.py; this module replaces its old one-coin
house-balance command with a live LTC/SOL/ETH dashboard and selector.
"""

from __future__ import annotations

import asyncio
import io
from decimal import Decimal

import aiohttp
import discord
from PIL import Image, ImageDraw, ImageFont

import bot as core


LTC_ADDRESS = "LRywkM6NGXfSSfee6uZ27tt14Ak4M8WasG"
SOL_ADDRESS = "GRfg756CtBFmK9PVri1e8CHQu8ywbiSprJccrdqr7uEa"
SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"
SOLANA_EXPLORER_URL = f"https://explorer.solana.com/address/{SOL_ADDRESS}"
LTC_EXPLORER_URL = f"https://live.blockcypher.com/ltc/address/{LTC_ADDRESS}/"

ASSET_COLORS = {
    "LTC": (186, 163, 227),
    "SOL": (164, 130, 226),
    "ETH": (127, 154, 230),
}


async def _safe_ltc_balance():
    try:
        return await core.fetch_public_ltc_balance(LTC_ADDRESS)
    except Exception as exc:
        print(f"[HOUSE FUNDS] LTC balance fetch failed: {type(exc).__name__}: {exc}")
        return None


async def _fetch_sol_balance():
    session = getattr(core.bot, "http_session", None)
    if session is None:
        raise RuntimeError("HTTP session is not ready")
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getBalance",
        "params": [SOL_ADDRESS],
    }
    async with session.post(
        SOLANA_RPC_URL,
        json=request,
        timeout=aiohttp.ClientTimeout(total=15),
    ) as response:
        response.raise_for_status()
        payload = await response.json()
    if payload.get("error"):
        raise RuntimeError(str(payload["error"]))
    lamports = (payload.get("result") or {}).get("value")
    if lamports is None:
        raise RuntimeError("Solana RPC returned no balance")
    return Decimal(str(lamports)) / Decimal("1000000000")


async def _safe_sol_balance():
    try:
        return await _fetch_sol_balance()
    except Exception as exc:
        print(f"[HOUSE FUNDS] SOL balance fetch failed: {type(exc).__name__}: {exc}")
        return None


async def _safe_price(symbol: str):
    try:
        return await core.get_crypto_usd_price(symbol)
    except Exception as exc:
        print(f"[HOUSE FUNDS] {symbol} price fetch failed: {type(exc).__name__}: {exc}")
        return None


def _usd_value(quantity, price):
    if quantity is None or price is None:
        return None
    return quantity * price


async def _load_assets():
    ltc_quantity, sol_quantity, ltc_price, sol_price = await asyncio.gather(
        _safe_ltc_balance(),
        _safe_sol_balance(),
        _safe_price("LTC"),
        _safe_price("SOL"),
    )
    return {
        "LTC": {
            "name": "Litecoin",
            "quantity": ltc_quantity,
            "price": ltc_price,
            "usd": _usd_value(ltc_quantity, ltc_price),
            "address": LTC_ADDRESS,
            "explorer": LTC_EXPLORER_URL,
        },
        "SOL": {
            "name": "Solana",
            "quantity": sol_quantity,
            "price": sol_price,
            "usd": _usd_value(sol_quantity, sol_price),
            "address": SOL_ADDRESS,
            "explorer": SOLANA_EXPLORER_URL,
        },
        "ETH": {
            "name": "Ethereum",
            "quantity": Decimal("0"),
            "price": Decimal("0"),
            "usd": Decimal("0"),
            "address": None,
            "explorer": None,
        },
    }


def _font(size: int, bold: bool = False):
    candidates = (
        [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
        ]
        if bold
        else [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        ]
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _quantity_text(symbol: str, quantity):
    if quantity is None:
        return "Balance unavailable"
    return f"{quantity:.8f} {symbol}"


def _usd_text(value):
    return "—" if value is None else f"${value:,.2f}"


def create_house_balance_dashboard(assets) -> discord.File:
    """Render a mobile-friendly, purple PacePot total-and-wallet image."""
    width, height = 1536, 700
    background = (21, 16, 34)
    image = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(image)

    # Low-contrast decorative circles echo the coin pattern in the banner.
    for x, y, radius in [
        (1340, 58, 112),
        (1460, 220, 80),
        (170, 655, 125),
        (755, 20, 66),
    ]:
        draw.ellipse(
            (x - radius, y - radius, x + radius, y + radius),
            outline=(39, 29, 57),
            width=3,
        )

    white = (246, 240, 255)
    muted = (182, 165, 206)
    violet = (191, 151, 245)
    edge = (129, 93, 168)
    panel = (35, 28, 50)

    draw.text((62, 36), "PacePot", font=_font(44, True), fill=white)
    draw.text(
        (width - 62, 51),
        "House balance",
        font=_font(25),
        fill=muted,
        anchor="ra",
    )
    draw.line((62, 101, width - 62, 101), fill=(70, 54, 91), width=2)

    known_values = [
        asset["usd"] for asset in assets.values() if asset.get("usd") is not None
    ]
    total_usd = sum(known_values, Decimal("0"))
    partial = any(
        assets[symbol].get("quantity") is None or assets[symbol].get("usd") is None
        for symbol in ("LTC", "SOL")
    )
    draw.rounded_rectangle(
        (62, 130, width - 62, 322),
        radius=28,
        fill=panel,
        outline=edge,
        width=3,
    )
    draw.text((99, 162), "Total Balance", font=_font(29, True), fill=violet)
    draw.text(
        (99, 210),
        ("~" if partial else "") + f"${total_usd:,.2f}",
        font=_font(62, True),
        fill=white,
    )
    if partial:
        draw.text(
            (width - 100, 273),
            "Partial total · one or more live values unavailable",
            font=_font(18),
            fill=muted,
            anchor="ra",
        )
    else:
        draw.text(
            (width - 100, 273),
            "Estimated USD value · live balances and market prices",
            font=_font(18),
            fill=muted,
            anchor="ra",
        )

    margin, gap = 62, 18
    card_width = (width - margin * 2 - gap * 2) // 3
    card_y1, card_y2 = 352, 636
    icons = {"LTC": "Ł", "SOL": "S", "ETH": "◆"}
    for index, symbol in enumerate(("LTC", "SOL", "ETH")):
        asset = assets[symbol]
        x1 = margin + index * (card_width + gap)
        x2 = x1 + card_width
        color = ASSET_COLORS[symbol]
        draw.rounded_rectangle(
            (x1, card_y1, x2, card_y2),
            radius=24,
            fill=panel,
            outline=edge,
            width=3,
        )
        draw.ellipse((x1 + 25, card_y1 + 28, x1 + 83, card_y1 + 86), fill=color)
        draw.text(
            (x1 + 54, card_y1 + 57),
            icons[symbol],
            font=_font(31, True),
            fill=(28, 21, 42),
            anchor="mm",
        )
        draw.text(
            (x1 + 99, card_y1 + 40),
            asset["name"],
            font=_font(27, True),
            fill=white,
        )
        draw.text(
            (x1 + 28, card_y1 + 116),
            _usd_text(asset.get("usd")),
            font=_font(43, True),
            fill=white,
        )
        draw.text(
            (x1 + 30, card_y1 + 183),
            _quantity_text(symbol, asset.get("quantity")),
            font=_font(21, True),
            fill=violet,
        )

    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    output.seek(0)
    return discord.File(output, filename="pacepot_house_balance.png")


class HouseFundsSelect(discord.ui.Select):
    def __init__(self, assets):
        self.assets = assets
        super().__init__(
            placeholder="Select a coin for its balance and address",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label="Litecoin (LTC)", value="LTC"),
                discord.SelectOption(label="Solana (SOL)", value="SOL"),
                discord.SelectOption(label="Ethereum (ETH)", value="ETH"),
            ],
        )

    async def callback(self, interaction: discord.Interaction):
        symbol = self.values[0]
        asset = self.assets[symbol]
        quantity = _quantity_text(symbol, asset.get("quantity"))
        usd_value = _usd_text(asset.get("usd"))
        description = (
            f"**Wallet balance**\n{quantity} · {usd_value} USD\n\n"
            "**Hot wallet · Payout address**\n"
        )
        if asset.get("address"):
            description += f"`{asset['address']}`"
        else:
            description += "No ETH payout address configured."

        embed = discord.Embed(
            title=f"{asset['name']} · House funds",
            description=description,
            color=0x9E75D3,
        )
        link_view = None
        if asset.get("explorer"):
            link_view = discord.ui.View(timeout=180)
            link_view.add_item(
                discord.ui.Button(
                    label="View on blockchain",
                    style=discord.ButtonStyle.link,
                    url=asset["explorer"],
                )
            )
        await interaction.response.send_message(
            embed=embed,
            view=link_view,
            ephemeral=True,
        )


class HouseFundsView(core.V2LayoutView):
    def __init__(self, assets):
        super().__init__(timeout=600)
        selector = HouseFundsSelect(assets)
        self.add_item(
            discord.ui.Container(
                discord.ui.MediaGallery(
                    discord.MediaGalleryItem(
                        media="attachment://pacepot_house_balance.png"
                    )
                ),
                discord.ui.ActionRow(selector),
                accent_color=0x9E75D3,
            )
        )


@core.prefix_command(
    name="housebal",
    aliases=["hb", "housebalance", "funds"],
)
async def housebal(interaction: core.PrefixInteraction):
    assets = await _load_assets()
    image = create_house_balance_dashboard(assets)
    await interaction.response.send_message(
        file=image,
        view=HouseFundsView(assets),
    )
