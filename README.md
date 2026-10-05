# Steam CS2 Trade Protection Monitor

Monitors the public CS2 inventory (context 2) of up to 4 Steam accounts and sends Telegram notifications when a new asset appears in the tradable/main inventory.

This is designed to detect CS2 items that leave Steam's 7-day Trade Protection: protected items are placed in context 16, and after protection ends they appear in the normal context 2 inventory. Steam community documentation/third-party implementations confirm this behavior.

## Important limitation

A Trade URL by itself is NOT an authentication credential and does not grant access to a private inventory. This project uses the public inventory endpoint, so the Steam profile/inventory must be visible.

Because public context 2 does not expose the protected context 16 inventory, the monitor cannot know the exact item while it is protected. It detects the item when it becomes visible in context 2.

## Setup

1. Create a GitHub repository and upload all files from this project.
2. Open `config/accounts.json` and replace the example Trade URLs with your 4 Trade URLs.
3. Create a Telegram bot with @BotFather and obtain:
   - `TELEGRAM_BOT_TOKEN`
   - your numeric `TELEGRAM_CHAT_ID`
4. Add these as GitHub repository secrets:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
5. In GitHub: Settings -> Actions -> General -> Workflow permissions -> enable "Read and write permissions".
6. Go to Actions -> Steam CS2 Trade Monitor -> Run workflow once manually.
7. The workflow will then run every 10 minutes.

## Why the Trade URL?

The monitor extracts the Steam account's 32-bit partner/account ID from:
`https://steamcommunity.com/tradeoffer/new/?partner=123456789&token=...`

The token is not needed for public inventory reading. It is only retained in the config because the input is your Trade URL.

## Commands

No commands are required. The bot sends notifications automatically.

## Notification examples

🟢 **CS2 ITEM RELEASED**

Account: `ACC #2`
Item: `AK-47 | Redline`
Asset ID: `123456789`
Status: appeared in normal inventory

The monitor also sends an error notification if Steam temporarily blocks/rate-limits an account.

## State

`data/state.json` is committed back to the repository by GitHub Actions. This prevents duplicate notifications between workflow runs.

Do not store Steam passwords, session cookies, refresh tokens, or Steam Guard secrets in this repository.
