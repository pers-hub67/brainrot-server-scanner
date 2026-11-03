import asyncio
import json
import logging
import os
from pathlib import Path
from urllib.parse import quote

import aiohttp

PLACE_ID = "109983668079237"
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
MAX_PAGES = int(os.getenv("MAX_PAGES_PER_SCAN", "3"))
MAX_MESSAGES = int(os.getenv("MAX_MESSAGES_PER_SCAN", "5"))
STATE_FILE = Path("seen_servers.json")
API_URL = f"https://games.roblox.com/v1/games/{PLACE_ID}/servers/Public"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("brainrot-scanner")


def load_seen():
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return set(data) if isinstance(data, list) else set()
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return set()


def save_seen(seen):
    STATE_FILE.write_text(
        json.dumps(sorted(seen), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


async def fetch_servers(session):
    result = []
    cursor = None
    for _ in range(MAX_PAGES):
        params = {
            "sortOrder": "Desc",
            "excludeFullGames": "true",
            "limit": "50",
        }
        if cursor:
            params["cursor"] = cursor
        async with session.get(API_URL, params=params) as response:
            if response.status == 429:
                retry = float(response.headers.get("Retry-After", "20"))
                log.warning("Roblox rate limit; retry after %s seconds", retry)
                await asyncio.sleep(retry)
                break
            response.raise_for_status()
            payload = await response.json()
        result.extend(payload.get("data", []))
        cursor = payload.get("nextPageCursor")
        if not cursor:
            break
        await asyncio.sleep(1)
    return result


def join_url(job_id):
    return (
        "https://www.roblox.com/games/start"
        f"?placeId={PLACE_ID}&gameInstanceId={quote(job_id, safe='')}"
    )


async def post_server(session, server):
    job_id = server["id"]
    url = join_url(job_id)
    embed = {
        "title": "Новый публичный сервер Steal a Brainrot",
        "url": url,
        "description": f"[**Присоединиться к серверу Roblox**]({url})",
        "color": 0x5865F2,
        "fields": [
            {
                "name": "Игроки",
                "value": f'{server.get("playing", 0)}/{server.get("maxPlayers", 0)}',
                "inline": True,
            },
            {"name": "Server Job ID", "value": f"`{job_id}`", "inline": False},
        ],
        "footer": {
            "text": "Публичный сервер найден автоматически • доход брейнротов не проверяется"
        },
    }
    payload = {"embeds": [embed], "allowed_mentions": {"parse": []}}
    async with session.post(
        WEBHOOK_URL, params={"wait": "true"}, json=payload
    ) as response:
        if response.status == 429:
            body = await response.json()
            await asyncio.sleep(float(body.get("retry_after", 5)))
            response.raise_for_status()
        response.raise_for_status()


async def main():
    if not WEBHOOK_URL:
        raise SystemExit("Не задан секрет DISCORD_WEBHOOK_URL в GitHub.")
    seen = load_seen()
    timeout = aiohttp.ClientTimeout(total=30)
    headers = {"User-Agent": "BrainrotPublicServerScanner/1.1"}

    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        servers = await fetch_servers(session)

        # Mark servers seen only after their Discord message was delivered.
        fresh = [s for s in servers if s.get("id") and s["id"] not in seen]
        log.info("Получено серверов: %d; новых: %d", len(servers), len(fresh))

        sent = 0
        for server in fresh:
            if sent >= MAX_MESSAGES:
                break
            try:
                await post_server(session, server)
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                log.error("Ошибка отправки для %s: %s", server.get("id"), exc)
                raise
            seen.add(server["id"])
            save_seen(seen)
            sent += 1
            await asyncio.sleep(1.2)

        log.info("Отправлено новых серверов: %d", sent)


if __name__ == "__main__":
    asyncio.run(main())
