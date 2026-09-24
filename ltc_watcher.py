from __future__ import annotations

import asyncio
import os
from decimal import Decimal

import aiohttp


class LTCWatcher:

    def __init__(
        self,
        bot,
        db,
    ):
        self.bot = bot
        self.db = db

        self.interval = int(
            os.getenv(
                "LTC_WATCH_INTERVAL",
                "60",
            )
        )

        self.endpoint = os.getenv(
            "LTC_PROVIDER_DEPOSIT_URL",
            "",
        ).strip()

        self.api_key = os.getenv(
            "PAYMENT_PROVIDER_API_KEY",
            "",
        ).strip()

        self.session: aiohttp.ClientSession | None = None

        self.task: asyncio.Task | None = None

        self.running = False

    async def start(self):

        if self.running:
            return

        self.running = True

        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(
                total=30
            )
        )

        self.task = asyncio.create_task(
            self._loop()
        )

    async def stop(self):

        self.running = False

        if self.task:

            self.task.cancel()

            try:
                await self.task

            except asyncio.CancelledError:
                pass

            self.task = None

        if self.session:

            await self.session.close()

            self.session = None

    async def _loop(self):

        await self.bot.wait_until_ready()

        while self.running:

            try:

                await self.check()

            except asyncio.CancelledError:

                raise

            except Exception as exc:

                print(
                    f"[LTC WATCHER] {exc}"
                )

            await asyncio.sleep(
                self.interval
            )

    async def check(self):

        if not self.endpoint:
            return

        if not self.session:
            return

        headers = {}

        if self.api_key:

            headers["Authorization"] = (
                f"Bearer {self.api_key}"
            )

        async with self.session.get(
            self.endpoint,
            headers=headers,
        ) as response:

            if response.status != 200:

                print(
                    "[LTC WATCHER] "
                    f"Provider returned {response.status}"
                )

                return

            data = await response.json()

        if isinstance(data, dict):

            deposits = data.get(
                "deposits",
                [],
            )

        elif isinstance(data, list):

            deposits = data

        else:

            deposits = []

        for deposit in deposits:

            await self.process(
                deposit
            )

    async def process(
        self,
        deposit: dict,
    ):

        if not isinstance(
            deposit,
            dict,
        ):
            return

        txid = str(
            deposit.get(
                "txid",
                deposit.get(
                    "transaction",
                    "",
                ),
            )
        ).strip()

        address = str(
            deposit.get(
                "address",
                "",
            )
        ).strip()

        amount_raw = deposit.get(
            "amount",
            "0",
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

        if not txid:
            return

        if not address:
            return

        try:

            amount = Decimal(
                str(amount_raw)
            )

        except Exception:

            return

        if amount <= 0:
            return

        payload = {
            "currency": "LTC",
            "txid": txid,
            "address": address,
            "amount": str(amount),
            "confirmations": confirmations,
            "required_confirmations": required,
        }

        try:

            credited = await self.db.process_deposit(
                payload
            )

        except Exception as exc:

            print(
                "[LTC WATCHER] "
                f"Deposit processing failed: {exc}"
            )

            return

        if credited:

            print(
                "[LTC WATCHER] "
                f"Credited {amount} LTC "
                f"to {address} "
                f"(txid={txid})"
            )


async def start_ltc_watcher(
    bot,
    db,
):

    watcher = LTCWatcher(
        bot,
        db,
    )

    await watcher.start()

    return watcher
