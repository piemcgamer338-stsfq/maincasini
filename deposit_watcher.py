"""
deposit_watcher.py — minimal placeholder so bot.py can import DepositWatcher.

bot.py runs in manual deposit-address mode and never creates a DepositWatcher
(bot.deposit_watcher = None), so this class is only here to satisfy the import.
The real alert-only watchers are ltc_watcher.py and sol_watcher.py.
"""


class DepositWatcher:
    def __init__(self, *args, **kwargs):
        pass

    async def start(self):
        pass

    async def stop(self):
        pass

    async def create_invoice(self, *args, **kwargs):
        raise RuntimeError("Automatic deposits are disabled (initializing).")
