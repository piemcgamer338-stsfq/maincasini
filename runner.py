"""Start PacePot with its house-funds UI extension."""

import bot as core
import pacepot_house_balance  # noqa: F401 - importing registers the command


def _shorten_initial_blackjack_deal():
    command = core.bot.get_command("blackjack")
    original = getattr(getattr(command, "callback", None), "__prefix_original__", None)
    if original is None:
        raise RuntimeError("Could not locate the Blackjack command callback.")

    code = original.__code__
    constants = list(code.co_consts)
    matches = [
        index
        for index, value in enumerate(constants)
        if type(value) is float and value == 7.0
    ]
    if len(matches) != 1:
        raise RuntimeError(
            "Expected exactly one 7-second initial Blackjack wait; "
            "the source has changed and needs review."
        )
    constants[matches[0]] = 3.0
    original.__code__ = code.replace(co_consts=tuple(constants))


if __name__ == "__main__":
    _shorten_initial_blackjack_deal()
    print("[STARTUP] House funds menu loaded; Blackjack opening deal is 3 seconds.")
    core.bot.run(core.BOT_TOKEN)
