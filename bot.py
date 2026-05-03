import os
import asyncio
import random
import logging
from io import BytesIO
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup, 
    ReplyKeyboardMarkup, KeyboardButton
)
from aiohttp import web
import asyncpg

# --- КОНФИГУРАЦИЯ ---
TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
CHANNEL_ID = "@Miflcards"
ADMIN_IDS = [1866813859]

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Подключаем твой генератор
try:
    from profile_generator import generate_profile_image
except ImportError:
    logging.warning("Файл profile_generator.py не найден!")
    async def generate_profile_image(*args, **kwargs): return None

RARITY_CONFIG = {
    "One": {"icon": "🟡", "price": 3500, "reward": 10000},
    "Chase": {"icon": "🟣", "price": 2800, "reward": 5000},
    "Drop": {"icon": "🔴", "price": 2000, "reward": 2500},
    "Series": {"icon": "🔵", "price": 1200, "reward": 1250},
    "Stock": {"icon": "🟢", "price": 500, "reward": 500}
}

class Form(StatesGroup):
    add_player_photo = State()
    add_player_data = State()
    guess_bet = State()
    guess_playing = State()
    promo_input = State()
    trade_input = State()

# --- КЛАВИАТУРА ---
def main_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🎁 Получить Карту"), KeyboardButton(text="📅 Бонус")],
        [KeyboardButton(text="⚽ Мини Игры"), KeyboardButton(text="🛒 Магазин")],
        [KeyboardButton(text="🔄 Трейд"), KeyboardButton(text="🏷 Промокод")],
        [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="👥 Рефералы")],
        [KeyboardButton(text="📊 ТОП-10")]
    ], resize_keyboard=True)

# --- БАЗА ДАННЫХ ---
class Database:
    def __init__(self, pool):
        self.pool = pool

    async def create_tables(self):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY, 
                    username TEXT, 
                    stars INT DEFAULT 0, 
                    vip_until TIMESTAMP, 
                    last_drop TIMESTAMP, 
                    last_bonus TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS mifl_cards (
                    card_id SERIAL PRIMARY KEY, 
                    name TEXT, 
                    rating FLOAT, 
                    club TEXT, 
                    position TEXT, 
                    rarity TEXT, 
                    photo_id TEXT
                );
                CREATE TABLE IF NOT EXISTS inventory (user_id BIGINT, card_id INT);
                CREATE TABLE IF NOT EXISTS promocodes (
                    code TEXT PRIMARY KEY, 
                    stars INT, 
                    max_uses INT, 
                    current_uses INT DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS used_promos (user_id BIGINT, code TEXT);
            """)

    async def get_user(self, uid, username="Игрок"):
        user = await self.pool.fetchrow("SELECT * FROM users WHERE user_id = $1", uid)
        if not user:
            await self.pool.execute("INSERT INTO users (user_id, username, stars) VALUES ($1, $2, 0)", uid, username)
            return await self.pool.fetchrow("SELECT * FROM users WHERE user_id = $1", uid)
        return user

    async def update_stars(self, uid, amount):
        await self.pool.execute("UPDATE users SET stars = stars + $1 WHERE user_id = $2", amount, uid)

# --- ПРОФИЛЬ (ИСПРАВЛЕНА ЗАГРУЗКА АВАТАРА) ---
@dp.message(F.text == "👤 Профиль")
async def view_profile(message: types.Message, state: FSMContext, db: Database):
    await state.clear()
    u = await db.get_user(message.from_user.id)
    cnt = await db.pool.fetchval("SELECT COUNT(*) FROM inventory WHERE user_id = $1", message.from_user.id)
    
    is_vip = u['vip_until'] and u['vip_until'] > datetime.now()
    st_text, st_color = ("VIP 💎", "yellow") if is_vip else ("Обычный 👤", "white")
    
    caption = (
        f"👤 <b>Профиль: {u['username']}</b>\n"
        f"💰 Баланс: {u['stars']:,} 🌟\n"
        f"🎴 Карт в коллекции: {cnt}\n"
        f"👑 Статус: {st_text}"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎴 Моя Коллекция", callback_data="view_col_0")]])

    try:
        avatar_bytes = None
        photos = await bot.get_user_profile_photos(message.from_user.id, limit=1)
        
        # Если у юзера есть аватарка, корректно скачиваем её байты
        if photos.total_count > 0:
            file = await bot.get_file(photos.photos[0][-1].file_id)
            downloaded_file = await bot.download(file)
            avatar_bytes = downloaded_file.getvalue() # getvalue() вместо read()!

        # Генерируем фото через твой скрипт
        img_io = await generate_profile_image(avatar_bytes, u['username'], u['stars'], cnt, st_text, color=st_color)
        
        # Если скрипт вернул BytesIO, отправляем его
        if img_io:
            photo_file = BufferedInputFile(img_io.getvalue(), filename="profile.png")
            return await message.answer_photo(photo_file, caption=caption, reply_markup=kb, parse_mode="HTML")
            
    except Exception as e:
        logging.error(f"Ошибка генерации профиля: {e}")
    
    # Если скрипт упал или вернул None, отправляем просто текст, чтобы бот не зависал
    await message.answer(caption, reply_markup=kb, parse_mode="HTML")

# --- ТОП-10 ---
@dp.message(F.text == "📊 ТОП-10")
async def leaderboard(message: types.Message, db: Database):
    rows = await db.pool.fetch("SELECT username, stars FROM users ORDER BY stars DESC LIMIT 10")
    if not rows:
        return await message.answer("🏆 Список лидеров пока пуст.")
    
    text = "🏆 <b>ТОП-10 ИГРОКОВ:</b>\n\n"
    for i, r in enumerate(rows, 1):
        text += f"{i}. {r['username']} — <b>{r['stars']:,}</b> 🌟\n"
    
    await message.answer(text, parse_mode="HTML")

# --- РЕФЕРАЛЫ ---
@dp.message(F.text == "👥 Рефералы")
async def referrals_menu(message: types.Message):
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start={message.from_user.id}"
    text = (
        "👥 <b>Реферальная программа</b>\n\n"
        "Приглашайте друзей и получайте бонусы!\n"
        "💰 Награда за друга: <b>5 000 🌟</b>\n\n"
        f"Твоя ссылка:\n<code>{link}</code>"
    )
    await message.answer(text, parse_mode="HTML")

# --- СТАРТ И РЕФЕРАЛЬНАЯ СИСТЕМА ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, command: CommandObject, db: Database):
    ref_id = command.args
    if ref_id and ref_id.isdigit() and int(ref_id) != message.from_user.id:
        exists = await db.pool.fetchval("SELECT 1 FROM users WHERE user_id = $1", message.from_user.id)
        if not exists:
            await db.update_stars(int(ref_id), 5000)
            try: await bot.send_message(int(ref_id), "🎉 У вас новый реферал! +5000 🌟")
            except: pass
            
    await db.get_user(message.from_user.id, message.from_user.first_name)
    await message.answer(f"⚽ Привет! Добро пожаловать в <b>Mifl Cards</b>.", reply_markup=main_kb(), parse_mode="HTML")

# --- МЕХАНИКА КАРТ ---
@dp.message(F.text == "🎁 Получить Карту")
async def get_card(message: types.Message, db: Database):
    u = await db.get_user(message.from_user.id)
    cd = 2 if (u['vip_until'] and u['vip_until'] > datetime.now()) else 4
    if u['last_drop'] and datetime.now() < u['last_drop'] + timedelta(hours=cd):
        diff = (u['last_drop'] + timedelta(hours=cd)) - datetime.now()
        return await message.answer(f"⏳ Пак будет через {diff.seconds // 3600}ч. {(diff.seconds // 60) % 60}м.")

    card = await db.pool.fetchrow("SELECT * FROM mifl_cards ORDER BY RANDOM() LIMIT 1")
    if not card: return await message.answer("База пуста.")
    
    cfg = RARITY_CONFIG.get(card['rarity'], {"icon": "⚪", "reward": 500})
    await db.pool.execute("UPDATE users SET last_drop = $1 WHERE user_id = $2", datetime.now(), message.from_user.id)
    
    has = await db.pool.fetchval("SELECT 1 FROM inventory WHERE user_id = $1 AND card_id = $2", message.from_user.id, card['card_id'])
    if has:
        reward = int(cfg['reward'] * 0.5)
        await db.update_stars(message.from_user.id, reward)
        res = f"♻️ Дубликат! Продан за {reward} 🌟"
    else:
        await db.pool.execute("INSERT INTO inventory (user_id, card_id) VALUES ($1, $2)", message.from_user.id, card['card_id'])
        await db.update_stars(message.from_user.id, cfg['reward'])
        res = f"🎊 Новая карта! +{cfg['reward']} 🌟"

    await message.answer_photo(
        card['photo_id'], 
        caption=f"👤 {card['name']}\n✨ Редкость: {cfg['icon']} {card['rarity']}\n\n{res}"
    )

# --- МАГАЗИН И БОНУС ---
@dp.message(F.text == "🛒 Магазин")
async def shop(message: types.Message):
    buttons = [[InlineKeyboardButton(text=f"{r} — {v['price']} 🌟", callback_data=f"buy_{r}")] for r, v in RARITY_CONFIG.items()]
    buttons.append([InlineKeyboardButton(text="💎 VIP (1 день) — 15000 🌟", callback_data="buy_vip")])
    await message.answer("🛒 Магазин", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.message(F.text == "📅 Бонус")
async def daily_bonus(message: types.Message, db: Database):
    u = await db.get_user(message.from_user.id)
    if u['last_bonus'] and datetime.now() < u['last_bonus'] + timedelta(hours=24):
        return await message.answer("⏳ Бонус можно взять раз в 24 часа!")
    
    val = random.randint(6000, 15000) if random.random() < 0.1 else random.randint(1000, 4000)
    await db.update_stars(message.from_user.id, val)
    await db.pool.execute("UPDATE users SET last_bonus = $1 WHERE user_id = $2", datetime.now(), message.from_user.id)
    await message.answer(f"🎁 Вы получили бонус: {val} 🌟")

# --- ЗАПУСК ---
async def main():
    pool = await asyncpg.create_pool(DATABASE_URL, ssl='require')
    db = Database(pool)
    await db.create_tables()
    dp["db"] = db
    
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot is running"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(os.environ.get("PORT", 8080))).start()
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
