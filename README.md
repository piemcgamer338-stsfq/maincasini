# Discord Casino Bot

## Railway variables

```text
DISCORD_TOKEN=
DATABASE_URL=
CASINO_NAME=Casino
ADMIN_USER_IDS=
WIN_LOG_CHANNEL_ID=
WITHDRAW_LOG_CHANNEL_ID=
RAIN_ROLE_ID=

# Deposit integration — do not add private keys or a seed phrase.
LTC_XPUB=
LTC_DERIVATION_PATH=
PAYMENT_PROVIDER_API_KEY=
BSC_RPC_URL=
SOLANA_RPC_URL=
OPENAI_API_KEY=
```

`CASINO_NAME` is the single branding variable.  It can be changed in Railway and the bot restarted.

## Important production notes

The bot has a fully working PostgreSQL points ledger, games, tips, bonuses, withdrawal requests, interactive help, and cards folder. Withdrawal requests reduce a user's points and are logged for an administrator to fulfil manually.

Do not accept real deposits until a real, audited payment provider webhook is connected. The current deposit menu deliberately does not invent addresses or credit balances. It only allows deposits after valid address assignment and two confirmed on-chain confirmations are implemented for your selected provider. Never store a wallet seed phrase or a private key in this repository or in public messages.

The `assets/cards` folder contains the supplied card PNG files, ready for a later blackjack-table image renderer.
