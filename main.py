import asyncio
import os
import random
import string
import aiohttp
from playwright.async_api import async_playwright

BASE_URL = "https://guns.lol/{}"
CHARS = string.ascii_lowercase + string.digits
RATE_RETRY_DELAY = 120

# -------- CONFIG -------- #
WEBHOOK_AVAILABLE = os.getenv("WEBHOOK_AVAILABLE")
WEBHOOK_TAKEN = os.getenv("WEBHOOK_TAKEN")
WEBHOOK_BANNED = os.getenv("WEBHOOK_BANNED")
WEBHOOK_RATE = os.getenv("WEBHOOK_RATE")

MODE = os.getenv("MODE", "1c")
WORDLIST = os.getenv("WORDLIST", "words.txt")
AMOUNT = int(os.getenv("AMOUNT", "5000"))
CONCURRENCY = int(os.getenv("PAGES", "5"))

COOKIE_FILE = "cookies.txt"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/149.0.0.0 Safari/537.36"
)

available_list = []
banned_list = []
taken_list = []
claimed_list = []

# -------- LOAD FULL COOKIES FROM FILE -------- #
def load_cookies():
    if not os.path.exists(COOKIE_FILE):
        print(f"❌ {COOKIE_FILE} not found!")
        print(f"Current dir: {os.getcwd()}")
        print("Make sure cookies.txt is committed to the repo.")
        return []
    
    with open(COOKIE_FILE, "r", encoding="utf-8") as f:
        cookies = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    
    print(f"✅ Loaded {len(cookies)} cookie sets from {COOKIE_FILE}")
    return cookies

FULL_COOKIES = load_cookies()

# -------- WEBHOOK -------- #
async def send_live(webhook, session, msg, allow_mentions=False):
    if not webhook:
        return
    payload = {
        "content": msg,
        "allowed_mentions": (
            {"parse": ["everyone", "roles"]} if allow_mentions else {"parse": []}
        )
    }
    try:
        async with session.post(webhook, json=payload) as resp:
            if resp.status == 429:
                retry = float(resp.headers.get("Retry-After", "1"))
                await asyncio.sleep(retry)
            elif resp.status >= 400:
                text = await resp.text()
                print(f"[WEBHOOK ERROR {resp.status}] {text[:200]}")
    except Exception as e:
        print(f"Webhook send failed: {e}")

# -------- CLAIM USERNAME -------- #
async def claim_username(username, session):
    if not FULL_COOKIES:
        print(f"❌ No cookies loaded for claiming {username}")
        return False
    
    cookie_header = random.choice(FULL_COOKIES)
    
    headers = {
        'Cookie': cookie_header,
        'accept': '*/*',
        'accept-language': 'en-US,en;q=0.9',
        'content-type': 'text/plain;charset=UTF-8',
        'origin': 'https://guns.lol',
        'priority': 'u=1, i',
        'referer': 'https://guns.lol/account',
        'sec-ch-ua': '"Brave";v="149", "Chromium";v="149", "Not)A;Brand";v="24"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'sec-gpc': '1',
        'user-agent': USER_AGENT
    }

    try:
        async with session.post(
            "https://guns.lol/api/account/username",
            headers=headers,
            json={"username": username}
        ) as resp:
            if resp.status == 200:
                claimed_list.append(username)
                await send_live(
                    WEBHOOK_AVAILABLE,
                    session,
                    f"🎯 **CLAIMED SUCCESSFULLY**: `{username}` <@&1466285392717414400>",
                    allow_mentions=True
                )
                return True
            else:
                text = await resp.text()
                print(f"Claim failed for {username} | Status: {resp.status}")
                return False
    except Exception as e:
        print(f"Claim exception for {username}: {e}")
        return False

# -------- CHECK & WORKER (unchanged) --------
async def check_username(page, username, session):
    try:
        await page.goto(BASE_URL.format(username), timeout=20000, wait_until="domcontentloaded")
        await page.wait_for_timeout(300)

        body_text = (await page.inner_text("body")).lower()
        if "too many requests" in body_text:
            await send_live(WEBHOOK_RATE, session, f"⏳ RATE LIMITED — sleeping {RATE_RETRY_DELAY}s")
            await asyncio.sleep(RATE_RETRY_DELAY)
            return

        h1_text = ""
        try:
            h1_text = (await page.locator("h1").first.inner_text()).strip().lower()
        except:
            pass

        if h1_text == "username not found":
            available_list.append(username)
            await send_live(WEBHOOK_AVAILABLE, session, f"✅ AVAILABLE: `{username}` <@&1466285392717414400>", allow_mentions=True)
            await claim_username(username, session)
            return

        if h1_text == "this user has been banned":
            banned_list.append(username)
            await send_live(WEBHOOK_BANNED, session, f"⚠️ BANNED: `{username}` <@&1465095383259549818>", allow_mentions=True)
            return

        taken_list.append(username)
    except Exception as e:
        print(f"Check error for {username}: {e}")
        taken_list.append(username)

async def worker(name, queue, page, session):
    while not queue.empty():
        username = await queue.get()
        await check_username(page, username, session)
        await asyncio.sleep(0.6)
        queue.task_done()

# -------- SUMMARY (unchanged) --------
async def send_summary(url, title, names, color):
    if not url or not names:
        return
    payload = {
        "embeds": [{
            "title": title,
            "description": "```\n" + "\n".join(names[:50]) + "\n```",
            "color": color
        }],
        "allowed_mentions": {"parse": []}
    }
    async with aiohttp.ClientSession() as s:
        async with s.post(url, json=payload) as resp:
            if resp.status >= 400:
                print(f"[SUMMARY ERROR {resp.status}]")

# -------- MAIN -------- #
async def main():
    if not FULL_COOKIES:
        print("No cookies loaded — claiming disabled.")

    if MODE == "4c":
        usernames = ["".join(random.choice(CHARS) for _ in range(4)) for _ in range(AMOUNT)]
    elif MODE == "wordlist":
        if not os.path.exists(WORDLIST):
            print("WORDLIST file not found")
            return
        with open(WORDLIST, "r", encoding="utf-8") as f:
            usernames = [line.strip() for line in f if line.strip()]
    else:
        print("Invalid MODE")
        return

    print(f"Starting with {len(usernames)} usernames (Mode: {MODE})")

    queue = asyncio.Queue()
    for u in usernames:
        queue.put_nowait(u)

    async with aiohttp.ClientSession() as session:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
            pages = [await browser.new_page(user_agent=USER_AGENT) for _ in range(CONCURRENCY)]
            workers = [asyncio.create_task(worker(f"W{i}", queue, pages[i], session)) for i in range(CONCURRENCY)]
            await queue.join()
            for w in workers:
                w.cancel()
            await browser.close()

    await send_summary(WEBHOOK_AVAILABLE, "✅ Available Names", available_list, 0x57F287)
    await send_summary(WEBHOOK_TAKEN, "❌ Taken Names", taken_list, 0xED4245)
    await send_summary(WEBHOOK_BANNED, "⚠️ Banned Names", banned_list, 0xFEE75C)
    await send_summary(WEBHOOK_AVAILABLE, "🎯 Successfully Claimed", claimed_list, 0x00FF00)

    print(f"Run complete. Claimed: {len(claimed_list)}")

if __name__ == "__main__":
    asyncio.run(main())
