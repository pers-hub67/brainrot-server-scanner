import json
import os
import time
from pathlib import Path

import requests

PLACE_ID = os.getenv("ROBLOX_PLACE_ID", "109983668079237")
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
MAX_PAGES = int(os.getenv("MAX_PAGES_PER_SCAN", "3"))
MAX_MESSAGES = int(os.getenv("MAX_MESSAGES_PER_SCAN", "5"))
SEEN_FILE = Path("seen_servers.json")

ROBLOX_API = f"https://games.roblox.com/v1/games/{PLACE_ID}/servers/Public"


def load_seen():
    try:
        return set(json.loads(SEEN_FILE.read_text(encoding="utf-8")))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def save_seen(seen):
    # Keep the state file bounded.
    SEEN_FILE.write_text(
        json.dumps(sorted(seen)[-5000:], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_servers():
    session = requests.Session()
    session.headers.update({"User-Agent": "BrainrotServerScanner/1.0"})
    cursor = None
    results = []

    for _ in range(MAX_PAGES):
        params = {"sortOrder": "Asc", "limit": 100}
        if cursor:
            params["cursor"] = cursor

        response = session.get(ROBLOX_API, params=params, timeout=25)
        response.raise_for_status()
        payload = response.json()

        results.extend(payload.get("data", []))
        cursor = payload.get("nextPageCursor")
        if not cursor:
            break
        time.sleep(0.4)

    return results


def send_discord(server):
    job_id = server.get("id", "")
    playing = server.get("playing", 0)
    max_players = server.get("maxPlayers", 0)
    join_url = (
        f"https://www.roblox.com/games/start?placeId={PLACE_ID}"
        f"&gameInstanceId={job_id}"
    )

    embed = {
        "title": "Найден публичный сервер Steal a Brainrot",
        "description": (
            f"**Игроков:** {playing}/{max_players}\n"
            f"**Job ID:** `{job_id}`\n"
            f"[Присоединиться к серверу]({join_url})\n\n"
            "Доходы и содержимое баз этим сканером пока не проверяются."
        ),
        "color": 0x5865F2,
    }
    response = requests.post(
        WEBHOOK_URL,
        json={"embeds": [embed]},
        timeout=20,
    )
    response.raise_for_status()


def main():
    if not WEBHOOK_URL:
        raise RuntimeError("Не задан секрет DISCORD_WEBHOOK_URL")

    seen = load_seen()
    servers = get_servers()
    new_servers = [s for s in servers if s.get("id") and s["id"] not in seen]

    sent = 0
    for server in new_servers:
        if sent >= MAX_MESSAGES:
            break
        try:
            send_discord(server)
            seen.add(server["id"])
            sent += 1
            time.sleep(1.2)  # avoid Discord webhook rate limits
        except requests.RequestException as exc:
            print(f"Не удалось отправить сервер {server.get('id')}: {exc}")
            break

    # Mark only successfully sent servers as seen.
    save_seen(seen)
    print(
        f"Проверено серверов: {len(servers)}; новых: {len(new_servers)}; "
        f"отправлено в Discord: {sent}"
    )


if __name__ == "__main__":
    main()
