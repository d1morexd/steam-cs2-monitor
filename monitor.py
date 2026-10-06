import json
import os
import re
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

import requests


ROOT = Path(__file__).resolve().parent

CONFIG_PATH = ROOT / "config" / "accounts.json"
STATE_PATH = ROOT / "data" / "state.json"

STEAM_INVENTORY = "https://steamcommunity.com/inventory/{steamid}/730/2"
TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

PARTNER_RE = re.compile(r"(?:^|[?&])partner=(\d+)")
STEAM64_BASE = 76561197960265728

MAX_RETRIES = 5
RETRY_DELAYS = [15, 30, 60, 120, 180]

session = requests.Session()

session.headers.update({
    "User-Agent": "Mozilla/5.0"
})


def load_json(path, default):
    if not path.exists():
        return default

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)

    temp_path = path.with_suffix(".tmp")

    with temp_path.open("w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )
        f.write("\n")

    temp_path.replace(path)


def steamid_from_trade_url(url):
    match = PARTNER_RE.search(url)

    if not match:
        raise ValueError(
            f"Cannot find partner= in Trade URL: {url}"
        )

    account_id = int(match.group(1))

    return str(STEAM64_BASE + account_id)


def telegram_send(text):
    token = os.environ.get(
        "TELEGRAM_BOT_TOKEN",
        ""
    ).strip()

    chat_id = os.environ.get(
        "TELEGRAM_CHAT_ID",
        ""
    ).strip()

    if not token or not chat_id:
        print(
            "Telegram secrets are not configured; "
            "notification skipped."
        )
        return

    response = session.post(
        TELEGRAM_API.format(token=token),
        json={
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        },
        timeout=30,
    )

    response.raise_for_status()


def get_inventory(steamid):
    all_items = {}
    start_assetid = None

    for _ in range(100):
        params = {
            "l": "english",
            "count": 1000,
        }

        if start_assetid:
            params["start_assetid"] = start_assetid

        response = None

        for attempt in range(MAX_RETRIES):
            response = session.get(
                STEAM_INVENTORY.format(steamid=steamid),
                params=params,
                timeout=30,
            )

            if response.status_code != 429:
                break

            delay = RETRY_DELAYS[
                min(
                    attempt,
                    len(RETRY_DELAYS) - 1
                )
            ]

            print(
                f"Steam returned HTTP 429 for {steamid}. "
                f"Waiting {delay}s before retry "
                f"{attempt + 1}/{MAX_RETRIES}..."
            )

            time.sleep(delay)

        if response is None:
            raise RuntimeError(
                f"No response from Steam for {steamid}"
            )

        if response.status_code == 429:
            raise RuntimeError(
                f"Steam rate limited inventory request "
                f"for {steamid} after {MAX_RETRIES} retries"
            )

        response.raise_for_status()

        data = response.json()

        if data.get("success") != 1:
            raise RuntimeError(
                f"Steam inventory returned "
                f"success={data.get('success')}"
            )

        descriptions = {}

        for description in data.get(
            "descriptions",
            []
        ):
            key = (
                str(description.get("classid")),
                str(description.get("instanceid")),
            )

            descriptions[key] = description

        for asset in data.get(
            "assets",
            []
        ):
            asset_id = str(
                asset.get("assetid")
            )

            key = (
                str(asset.get("classid")),
                str(asset.get("instanceid")),
            )

            description = descriptions.get(
                key,
                {}
            )

            item_name = (
                description.get("market_hash_name")
                or description.get("name")
                or "Unknown item"
            )

            all_items[asset_id] = {
                "assetid": asset_id,
                "classid": str(
                    asset.get("classid")
                ),
                "instanceid": str(
                    asset.get("instanceid")
                ),
                "name": item_name,
            }

        if not data.get("more_items"):
            break

        next_assetid = data.get(
            "last_assetid"
        )

        if not next_assetid:
            break

        if next_assetid == start_assetid:
            break

        start_assetid = next_assetid

        time.sleep(2)

    return all_items


def send_new_item_message(
    account_name,
    item
):
    item_name = (
        item.get("name")
        or "Unknown item"
    )

    message = (
        "🟢 Новый скин появился!\n\n"
        f"👤 Аккаунт: {account_name}\n"
        f"🔫 {item_name}"
    )

    telegram_send(message)


def main():
    config = load_json(
        CONFIG_PATH,
        {"accounts": []}
    )

    state = load_json(
        STATE_PATH,
        {"accounts": {}}
    )

    accounts_state = state.setdefault(
        "accounts",
        {}
    )

    changed = False
    errors = []

    accounts = config.get(
        "accounts",
        []
    )

    for index, account in enumerate(accounts):
        account_name = account.get(
            "name",
            "Unnamed"
        )

        trade_url = account.get(
            "trade_url",
            ""
        ).strip()

        if not trade_url:
            continue

        try:
            steamid = steamid_from_trade_url(
                trade_url
            )

            inventory = get_inventory(
                steamid
            )

            current_ids = set(
                inventory.keys()
            )

            previous = accounts_state.get(
                account_name
            )

            if previous is None:
                accounts_state[account_name] = {
                    "steamid": steamid,
                    "assets": inventory,
                    "last_check": datetime.now(
                        timezone.utc
                    ).isoformat(),
                }

                changed = True

                print(
                    f"{account_name}: "
                    f"{len(inventory)} assets, "
                    f"baseline created"
                )

            else:
                previous_assets = previous.get(
                    "assets",
                    {}
                )

                previous_ids = set(
                    previous_assets.keys()
                )

                new_ids = (
                    current_ids - previous_ids
                )

                for asset_id in new_ids:
                    item = inventory[asset_id]

                    send_new_item_message(
                        account_name,
                        item
                    )

                accounts_state[account_name] = {
                    "steamid": steamid,
                    "assets": inventory,
                    "last_check": datetime.now(
                        timezone.utc
                    ).isoformat(),
                }

                changed = True

                print(
                    f"{account_name}: "
                    f"{len(inventory)} assets, "
                    f"{len(new_ids)} new"
                )

        except Exception as error:
            error_message = (
                f"{account_name}: "
                f"{type(error).__name__}: "
                f"{error}"
            )

            print(
                error_message,
                file=sys.stderr
            )

            errors.append(
                error_message
            )

        if index < len(accounts) - 1:
            time.sleep(10)

    if errors:
        telegram_send(
            "⚠️ Steam Monitor error\n\n"
            + "\n".join(
                f"• {error}"
                for error in errors
            )
        )

    if changed:
        save_json(
            STATE_PATH,
            state
        )


if __name__ == "__main__":
    main()
