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

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Steam CS2 Inventory Monitor; +https://github.com/)"
})

def load_json(path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp.replace(path)

def steamid_from_trade_url(url):
    m = PARTNER_RE.search(url)
    if not m:
        raise ValueError(f"Cannot find partner= in Trade URL: {url}")
    account_id = int(m.group(1))
    return str(STEAM64_BASE + account_id)

def telegram_send(text):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("Telegram secrets are not configured; notification skipped.")
        return
    r = session.post(
        TELEGRAM_API.format(token=token),
        json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=30,
    )
    r.raise_for_status()

def get_inventory(steamid):
    all_assets = {}
    all_descriptions = {}
    start_assetid = None

    for _ in range(100):
        params = {"l": "english", "count": 1000}
        if start_assetid:
            params["start_assetid"] = start_assetid

        r = session.get(
            STEAM_INVENTORY.format(steamid=steamid),
            params=params,
            timeout=30,
        )

        if r.status_code == 429:
            raise RuntimeError(f"Steam rate limited inventory request for {steamid}")
        r.raise_for_status()

        data = r.json()
        if data.get("success") != 1:
            raise RuntimeError(f"Steam inventory returned success={data.get('success')}")

        for desc in data.get("descriptions", []):
            key = (str(desc.get("classid")), str(desc.get("instanceid")))
            all_descriptions[key] = desc

        for asset in data.get("assets", []):
            asset_id = str(asset.get("assetid"))
            key = (str(asset.get("classid")), str(asset.get("instanceid")))
            desc = all_descriptions.get(key, {})
            all_assets[asset_id] = {
                "assetid": asset_id,
                "classid": str(asset.get("classid")),
                "instanceid": str(asset.get("instanceid")),
                "amount": str(asset.get("amount", "1")),
                "market_hash_name": desc.get("market_hash_name") or desc.get("name") or "Unknown item",
                "name": desc.get("name") or "Unknown item",
                "type": desc.get("type") or "",
                "icon_url": desc.get("icon_url") or "",
            }

        if not data.get("more_items"):
            break

        next_id = data.get("last_assetid")
        if not next_id or next_id == start_assetid:
            break
        start_assetid = next_id
        time.sleep(0.5)

    return all_assets

def format_item(item):
    name = item.get("market_hash_name") or item.get("name") or "Unknown item"
    asset = item.get("assetid", "?")
    return f"• <b>{escape(name)}</b>\n  Asset: <code>{escape(asset)}</code>"

def escape(s):
    return (
        str(s).replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )

def main():
    config = load_json(CONFIG_PATH, {"accounts": []})
    state = load_json(STATE_PATH, {"accounts": {}})
    accounts_state = state.setdefault("accounts", {})

    changed = False
    errors = []

    for account in config.get("accounts", []):
        name = account.get("name", "Unnamed")
        url = account.get("trade_url", "").strip()

        if not url:
            continue

        try:
            steamid = steamid_from_trade_url(url)
            inventory = get_inventory(steamid)
            current_ids = set(inventory.keys())

            previous = accounts_state.get(name)
            if previous is None:
                # First run: establish baseline, do NOT spam all existing items.
                accounts_state[name] = {
                    "steamid": steamid,
                    "assets": inventory,
                    "last_check": datetime.now(timezone.utc).isoformat(),
                }
                changed = True
                print(f"{name}: baseline created ({len(inventory)} assets)")
                continue

            previous_assets = previous.get("assets", {})
            previous_ids = set(previous_assets.keys())

            new_ids = current_ids - previous_ids

            if new_ids:
                items = [inventory[i] for i in new_ids]
                lines = [
                    "🟢 <b>CS2 ITEM RELEASED</b>",
                    "",
                    f"Account: <b>{escape(name)}</b>",
                    f"SteamID: <code>{escape(steamid)}</code>",
                    "",
                ]
                lines.extend(format_item(x) for x in items)
                lines += [
                    "",
                    "The item appeared in the normal CS2 inventory (context 2).",
                ]
                telegram_send("\n".join(lines))

            accounts_state[name] = {
                "steamid": steamid,
                "assets": inventory,
                "last_check": datetime.now(timezone.utc).isoformat(),
            }
            changed = True
            print(f"{name}: {len(inventory)} assets, {len(new_ids)} new")

        except Exception as exc:
            msg = f"{name}: {type(exc).__name__}: {exc}"
            print(msg, file=sys.stderr)
            errors.append(msg)

    if errors:
        telegram_send(
            "⚠️ <b>Steam Monitor error</b>\n\n" +
            "\n".join(f"• {escape(x)}" for x in errors)
        )

    if changed:
        save_json(STATE_PATH, state)

if __name__ == "__main__":
    main()
