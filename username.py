import asyncio
import random
import re
import aiohttp

from aiogram import Bot, Dispatcher, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage

from playwright.async_api import async_playwright
from googletrans import Translator

# ================= CONFIG =================
BOT_TOKEN = "8645796534:AAGWYF3jxGQeUU987-QhpAmnJxjjmR0vgBM"
# ==========================================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

translator = Translator()

# ================= GLOBALS =================
session = None
browser = None

SEM = asyncio.Semaphore(10)
PAGE_SEM = asyncio.Semaphore(3)
lock = asyncio.Lock()

translate_cache = {}

# ================= INIT =================

async def init_all():
    global session, browser
    session = aiohttp.ClientSession()

    p = await async_playwright().start()
    browser = await p.chromium.launch(headless=True)

# ================= KEYBOARDS =================

menu_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🔍 Проверить юзернейм")],
        [KeyboardButton(text="🎲 Рандом юзернеймы")],
        [KeyboardButton(text="🔥 Топ юзернеймы")],
        [KeyboardButton(text="⬅️ Назад")],
    ],
    resize_keyboard=True
)

back_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="⬅️ Назад")]],
    resize_keyboard=True
)

# ================= WORDS =================

with open("words.txt", "r", encoding="utf-8") as f:
    words = [w.strip().lower() for w in f if w.strip()]

# ================= VALIDATION =================

def is_valid_username(username: str):
    return re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{3,30}[a-zA-Z0-9]", username) is not None

# ================= TRANSLATE =================

def translate_word(word: str):
    if word in translate_cache:
        return translate_cache[word]

    try:
        t = translator.translate(word, dest="ru").text
        translate_cache[word] = t
        return t
    except:
        return "без перевода"

def username_translate(username: str):
    clean = re.sub(r'[^a-zA-Z]', '', username)
    if not clean:
        return "без перевода"
    return translate_word(clean)

# ================= QUALITY =================

def score_username(u):
    score = 0
    if len(u) <= 5:
        score += 5
    elif len(u) <= 7:
        score += 3
    if u[0].isalpha():
        score += 1
    return score

# ================= TELEGRAM CHECK =================

async def check_telegram(username: str):
    url = f"https://t.me/{username}"
    try:
        async with session.get(url, timeout=10) as resp:
            text = await resp.text()
            return "If you have Telegram" not in text
    except:
        return True

# ================= FRAGMENT =================

async def check_fragment(username: str):
    url = f"https://fragment.com/username/{username}"

    async with PAGE_SEM:
        page = await browser.new_page()
        try:
            await page.goto(url, timeout=30000)
            content = (await page.content()).lower()

            if "unavailable" in content:
                return True, url

            if any(x in content for x in ["buy now", "make offer", "auction"]):
                return False, url

            return True, url
        except:
            return False, url
        finally:
            await page.close()

# ================= CHECK =================

async def check_username(username: str):
    username = username.strip().lstrip("@")

    if not is_valid_username(username):
        return "❌ невалидный"

    if not await check_telegram(username):
        return "❌ занят (Telegram)"

    free, url = await check_fragment(username)

    if not free:
        return f"❌ занят на Fragment\n🔗 {url}"

    return "✅ свободен"

# ================= FAST =================

async def fast_check(username):
    async with SEM:
        try:
            return await asyncio.wait_for(check_username(username), timeout=12)
        except:
            return "❌ ошибка"

# ================= GENERATORS =================

def generate_username():
    while True:
        w1 = random.choice(words)
        w2 = random.choice(words)

        username = random.choice([
            w1,
            w1 + w2,
            w1[:4] + w2[:3],
        ])

        if (
            is_valid_username(username)
            and 5 <= len(username) <= 12
            and len(set(username)) >= 3
        ):
            return username


def generate_top_username():
    while True:
        w1 = random.choice(words)
        w2 = random.choice(words)

        if len(w1) < 3 or len(w2) < 3:
            continue

        if w1 == w2:
            continue

        if random.random() < 0.7:
            username = w1
        else:
            username = w1 + w2

        if (
            is_valid_username(username)
            and 4 <= len(username) <= 10
            and score_username(username) >= 4
            and "_" not in username
            and len(set(username)) >= 4
        ):
            return username

# ================= PROGRESS =================

def progress_bar(current, total):
    filled = int(current / total * 10)
    percent = int(current / total * 100)
    return f"{'█'*filled}{'░'*(10-filled)} {percent}%"

# ================= HANDLERS =================

@dp.message(Command("start"))
async def start(msg: types.Message):
    await msg.answer("👋 Добро пожаловать!", reply_markup=menu_kb)

@dp.message(lambda m: m.text == "⬅️ Назад")
async def back(msg: types.Message):
    await msg.answer("Главное меню", reply_markup=menu_kb)

@dp.message(lambda m: m.text == "🔍 Проверить юзернейм")
async def ask(msg: types.Message):
    await msg.answer("Введите username:", reply_markup=back_kb)

@dp.message(lambda m: m.text not in [
    "🔍 Проверить юзернейм",
    "🎲 Рандом юзернеймы",
    "🔥 Топ юзернеймы",
    "⬅️ Назад"
])
async def check(msg: types.Message):
    username = msg.text.strip().lstrip("@")

    status = await msg.answer("🔍 Проверка...")

    result = await fast_check(username)
    tr = username_translate(username)

    await status.edit_text(f"@{username} ({tr}) — {result}")

# ================= RANDOM =================

@dp.message(lambda m: m.text == "🎲 Рандом юзернеймы")
async def random_users(msg: types.Message):
    target = 10
    found = []
    attempts = 0

    progress = await msg.answer("🔍 0/10")

    async def worker():
        nonlocal attempts
        while True:
            async with lock:
                if len(found) >= target or attempts > 500:
                    return
                attempts += 1

            u = generate_username()
            r = await fast_check(u)

            if "свободен" in r:
                async with lock:
                    if len(found) < target:
                        found.append(u)

    tasks = [asyncio.create_task(worker()) for _ in range(10)]

    while len(found) < target and attempts < 500:
        try:
            await progress.edit_text(f"🔍 {progress_bar(len(found), target)} {len(found)}/{target}")
        except:
            pass
        await asyncio.sleep(1)

    for t in tasks:
        t.cancel()

    text = (
        "🔥 Найдено:\n\n"
        "⚠️ Некоторые username могут быть некорректными или недоступными по правилам Telegram.\n"
        "Бот не всегда может это учесть, поэтому при необходимости проверяйте вручную.\n\n"
    )

    for u in found:
        text += f"@{u} ({username_translate(u)})\n"

    await progress.delete()
    await msg.answer(text, reply_markup=menu_kb)

# ================= TOP =================

@dp.message(lambda m: m.text == "🔥 Топ юзернеймы")
async def top_users(msg: types.Message):
    target = 10
    found = []
    attempts = 0

    progress = await msg.answer("🔥 0/10")

    async def worker():
        nonlocal attempts
        while True:
            async with lock:
                if len(found) >= target or attempts > 500:
                    return
                attempts += 1

            u = generate_top_username()
            r = await fast_check(u)

            if "свободен" in r:
                async with lock:
                    if len(found) < target:
                        found.append(u)

    tasks = [asyncio.create_task(worker()) for _ in range(10)]

    while len(found) < target and attempts < 500:
        try:
            await progress.edit_text(f"🔥 {progress_bar(len(found), target)} {len(found)}/{target}")
        except:
            pass
        await asyncio.sleep(1)

    for t in tasks:
        t.cancel()

    text = (
        "💎 ТОП:\n\n"
        "⚠️ Некоторые username могут быть некорректными или недоступными по правилам Telegram.\n"
        "Бот не всегда может это учесть, поэтому при необходимости проверяйте вручную.\n\n"
    )

    for u in found:
        text += f"@{u} ({username_translate(u)})\n"

    await progress.delete()
    await msg.answer(text, reply_markup=menu_kb)

# ================= MAIN =================

async def main():
    await init_all()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())