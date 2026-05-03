import os
import asyncio
import random
import string
import asyncpg
import logging
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

# --- НАСТРОЙКИ ---
TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_IDS = [1866813859] # Твой ID

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()

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

# --- КЛАВИАТУРЫ ---
def main_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🎁 Получить Карту"), KeyboardButton(text="📅 Бонус")],
        [KeyboardButton(text="⚽ Мини Игры"), KeyboardButton(text="🛒 Магазин")],
        [KeyboardButton(text="🔄 Трейд"), KeyboardButton(text="🏷 Промокод")],
        [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="📊 ТОП-10")]
    ], resize_keyboard=True)

# --- ЛОГИКА БАЗЫ ДАННЫХ (ВСТРОЕННАЯ) ---
class DBManager:
    def __init__(self, pool):
        self.pool = pool

    async def get_user(self, uid):
        user = await self.pool.fetchrow("SELECT * FROM users WHERE user_id = $1", uid)
        if not user:
            await self.pool.execute("INSERT INTO users (user_id, username, stars) VALUES ($1, $2, 0)", uid, "Игрок")
            return await self.pool.fetchrow("SELECT * FROM users WHERE user_id = $1", uid)
        return user

    async def update_stars(self, uid, amount):
        await self.pool.execute("UPDATE users SET stars = stars + $1 WHERE user_id = $1", amount, uid)

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def start(message: types.Message, db: DBManager):
    await db.get_user(message.from_user.id)
    await message.answer("⚽ Добро пожаловать в <b>Mifl Cards</b>!", reply_markup=main_kb(), parse_mode="HTML")

# --- ПРОФИЛЬ И КОЛЛЕКЦИЯ ---
@dp.message(F.text == "👤 Профиль")
async def profile(message: types.Message, db: DBManager):
    u = await db.get_user(message.from_user.id)
    cnt = await db.pool.fetchval("SELECT COUNT(*) FROM inventory WHERE user_id = $1", message.from_user.id)
    is_vip = u.get('vip_until') and u['vip_until'] > datetime.now()
    status = "👑 VIP" if is_vip else "👤 Обычный"
    
    msg = (f"👤 <b>Ваш Профиль</b>\n\n"
           f"💰 Баланс: {u['stars']:,} 🌟\n"
           f"🎴 Карт в коллекции: {cnt}\n"
           f"🏆 Статус: {status}")
    
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎴 Посмотреть коллекцию", callback_data="view_col_0")]])
    await message.answer(msg, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data.startswith("view_col_"))
async def view_collection(callback: types.CallbackQuery, db: DBManager):
    page = int(callback.data.split("_")[2])
    cards = await db.pool.fetch(
        "SELECT c.name, c.rarity FROM mifl_cards c JOIN inventory i ON c.card_id = i.card_id WHERE i.user_id = $1 LIMIT 10 OFFSET $2", 
        callback.from_user.id, page * 10
    )
    if not cards:
        return await callback.answer("Тут пока пусто или это конец списка!", show_alert=True)
    
    text = "🎴 <b>Ваши карты:</b>\n\n"
    for c in cards:
        icon = RARITY_CONFIG.get(c['rarity'], {}).get('icon', '⚪')
        text += f"{icon} {c['name']} ({c['rarity']})\n"
    
    nav = []
    if page > 0: nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"view_col_{page-1}"))
    nav.append(InlineKeyboardButton(text="➡️", callback_data=f"view_col_{page+1}"))
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[nav]), parse_mode="HTML")

# --- УГАДАЙКА (КАК НА СКРИНШОТЕ) ---
@dp.message(F.text == "⚽ Мини Игры")
async def games(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🧩 Угадай Игрока", callback_data="start_guess")]])
    await message.answer("Выберите игру:", reply_markup=kb)

@dp.callback_query(F.data == "start_guess")
async def guess_bet_step(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("💰 Введите вашу ставку (от 100 🌟):")
    await state.set_state(Form.guess_bet)

@dp.message(Form.guess_bet)
async def guess_start_logic(message: types.Message, state: FSMContext, db: DBManager):
    if not message.text.isdigit(): return
    bet = int(message.text)
    u = await db.get_user(message.from_user.id)
    if bet < 100 or bet > u['stars']: return await message.answer("❌ Недостаточно 🌟 или некорректная ставка.")
    
    card = await db.pool.fetchrow("SELECT * FROM mifl_cards ORDER BY RANDOM() LIMIT 1")
    if not card: return await message.answer("База карт пуста!")
    
    others = await db.pool.fetch("SELECT name FROM mifl_cards WHERE name != $1 ORDER BY RANDOM() LIMIT 3", card['name'])
    options = [card['name']] + [r['name'] for r in others]
    random.shuffle(options)
    
    await db.update_stars(message.from_user.id, -bet)
    await state.update_data(correct=card['name'], bet=bet, rating=card['rating'], opts=options)
    
    kb = [
        [InlineKeyboardButton(text=options[0], callback_data="ans_0"), InlineKeyboardButton(text=options[1], callback_data="ans_1")],
        [InlineKeyboardButton(text=options[2], callback_data="ans_2"), InlineKeyboardButton(text=options[3], callback_data="ans_3")],
        [InlineKeyboardButton(text="💡 Подсказка", callback_data="hint"), InlineKeyboardButton(text="🏳 Сдаться", callback_data="surrender")]
    ]
    
    await message.answer(
        f"🧩 <b>Угадай игрока!</b>\n\n🛡 Клуб: {card['club']}\n📍 Позиция: {card['position']}\n💰 Ставка: {bet} 🌟",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML"
    )
    await state.set_state(Form.guess_playing)

@dp.callback_query(F.data == "hint", Form.guess_playing)
async def guess_hint(callback: types.CallbackQuery, state: FSMContext, db: DBManager):
    data = await state.get_data()
    cost = int(data['bet'] * 0.2)
    await db.update_stars(callback.from_user.id, -cost)
    await callback.answer(f"Подсказка: Рейтинг этого игрока — {data['rating']}! (Списано {cost} 🌟)", show_alert=True)

@dp.callback_query(F.data == "surrender", Form.guess_playing)
async def guess_give_up(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await callback.message.edit_text(f"🏳 Вы сдались! Это был <b>{data['correct']}</b>.", parse_mode="HTML")
    await state.clear()

@dp.callback_query(F.data.startswith("ans_"), Form.guess_playing)
async def guess_finish(callback: types.CallbackQuery, state: FSMContext, db: DBManager):
    idx = int(callback.data.split("_")[1])
    data = await state.get_data()
    if data['opts'][idx] == data['correct']:
        win = data['bet'] * 2
        await db.update_stars(callback.from_user.id, win)
        await callback.message.edit_text(f"✅ ПРАВИЛЬНО! Это {data['correct']}.\nВы выиграли <b>{win}</b> 🌟!", parse_mode="HTML")
    else:
        await callback.message.edit_text(f"❌ ОШИБКА! Это был <b>{data['correct']}</b>.", parse_mode="HTML")
    await state.clear()

# --- АДМИН ПАНЕЛЬ ---
@dp.message(Command("add_player"))
async def admin_add_p(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    await message.answer("Отправьте фото игрока:")
    await state.set_state(Form.add_player_photo)

@dp.message(Form.add_player_photo, F.photo)
async def admin_add_photo(message: types.Message, state: FSMContext):
    await state.update_data(fid=message.photo[-1].file_id)
    await message.answer("Теперь введи данные через запятую:\nИмя, Рейтинг, Клуб, Позиция, Редкость")
    await state.set_state(Form.add_player_data)

@dp.message(Form.add_player_data)
async def admin_add_save(message: types.Message, state: FSMContext, db: DBManager):
    try:
        d = [x.strip() for x in message.text.split(",")]
        fid = (await state.get_data())['fid']
        await db.pool.execute(
            "INSERT INTO mifl_cards (name, rating, club, position, rarity, photo_id) VALUES ($1, $2, $3, $4, $5, $6)",
            d[0], float(d[1]), d[2], d[3], d[4], fid
        )
        await message.answer("✅ Карта сохранена!")
    except:
        await message.answer("❌ Ошибка в формате данных.")
    await state.clear()

# --- ВЕБ-СЕРВЕР ДЛЯ RENDER ---
async def health_check(request):
    return web.Response(text="Mifl Cards Online")

async def start_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(os.environ.get("PORT", 8080)))
    await site.start()

# --- ЗАПУСК ---
async def main():
    asyncio.create_task(start_server())
    pool = await asyncpg.create_pool(DATABASE_URL, ssl='require')
    db = DBManager(pool)
    
    # Создание таблиц если их нет
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, username TEXT, stars INT DEFAULT 0, vip_until TIMESTAMP, last_drop TIMESTAMP, last_bonus TIMESTAMP);
            CREATE TABLE IF NOT EXISTS mifl_cards (card_id SERIAL PRIMARY KEY, name TEXT, rating FLOAT, club TEXT, position TEXT, rarity TEXT, photo_id TEXT);
            CREATE TABLE IF NOT EXISTS inventory (user_id BIGINT, card_id INT);
            CREATE TABLE IF NOT EXISTS promocodes (code TEXT PRIMARY KEY, stars INT, max_uses INT, current_uses INT DEFAULT 0);
        """)

    dp["db"] = db
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
