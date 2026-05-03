import os
import asyncio
import random
import string
import asyncpg
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

# --- НАСТРОЙКИ ---
TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
CHANNEL_ID = "@Miflcards"
ADMIN_IDS = [1866813859]

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Импорт твоего генератора
try:
    from profile_generator import generate_profile_image
except ImportError:
    logging.warning("Файл profile_generator.py не найден! Фото профиля не будет работать.")
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

def sub_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Подписаться на канал", url="https://t.me/Miflcards")],
        [InlineKeyboardButton(text="✅ Я подписался", callback_data="check_subs")]
    ])

# --- БАЗА ДАННЫХ ---
class Database:
    def __init__(self, pool):
        self.pool = pool

    async def create_tables(self):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, username TEXT, stars INT DEFAULT 0, vip_until TIMESTAMP, last_drop TIMESTAMP, last_bonus TIMESTAMP);
                CREATE TABLE IF NOT EXISTS mifl_cards (card_id SERIAL PRIMARY KEY, name TEXT, rating FLOAT, club TEXT, position TEXT, rarity TEXT, photo_id TEXT);
                CREATE TABLE IF NOT EXISTS inventory (user_id BIGINT, card_id INT);
                CREATE TABLE IF NOT EXISTS promocodes (code TEXT PRIMARY KEY, stars INT, max_uses INT, current_uses INT DEFAULT 0);
                CREATE TABLE IF NOT EXISTS used_promos (user_id BIGINT, code TEXT);
                CREATE TABLE IF NOT EXISTS active_trades (code TEXT PRIMARY KEY, user_a BIGINT, card_a INT);
            """)

    async def get_user(self, uid, username="Игрок"):
        user = await self.pool.fetchrow("SELECT * FROM users WHERE user_id = $1", uid)
        if not user:
            await self.pool.execute("INSERT INTO users (user_id, username, stars) VALUES ($1, $2, 0)", uid, username)
            return await self.pool.fetchrow("SELECT * FROM users WHERE user_id = $1", uid)
        return user

    async def update_stars(self, uid, amount):
        await self.pool.execute("UPDATE users SET stars = stars + $1 WHERE user_id = $2", amount, uid)

# --- ЛОГИКА ПОДПИСКИ ---
async def check_subscription(user_id):
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in ["member", "administrator", "creator"]
    except: return False

@dp.callback_query(F.data == "check_subs")
async def verify_sub_callback(call: types.CallbackQuery, db: Database):
    if await check_subscription(call.from_user.id):
        await call.message.delete()
        user = await db.get_user(call.from_user.id, call.from_user.first_name)
        await call.message.answer(f"⚽ Привет, {user['username']}! Ты в игре.", reply_markup=main_kb())
    else: await call.answer("❌ Подпишись на канал!", show_alert=True)

# --- СТАРТ ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext, command: CommandObject, db: Database):
    await state.clear()
    if not await check_subscription(message.from_user.id):
        return await message.answer("⚠️ Подпишись на канал!", reply_markup=sub_kb())
    
    ref_id = command.args
    if ref_id and ref_id.isdigit() and int(ref_id) != message.from_user.id:
        user_exists = await db.pool.fetchval("SELECT 1 FROM users WHERE user_id = $1", message.from_user.id)
        if not user_exists:
            await db.pool.execute("INSERT INTO users (user_id, username, stars) VALUES ($1, $2, 0)", message.from_user.id, message.from_user.first_name)
            await db.update_stars(int(ref_id), 5000)
            try: await bot.send_message(int(ref_id), "👥 +5 000 🌟 за нового реферала!")
            except: pass
            
    user = await db.get_user(message.from_user.id, message.from_user.first_name)
    await message.answer(f"⚽ Добро пожаловать, {user['username']}!", reply_markup=main_kb())

# --- ПРОФИЛЬ (ВЫЗОВ profile_generator.py) ---
@dp.message(F.text == "👤 Профиль")
async def view_profile(message: types.Message, state: FSMContext, db: Database):
    await state.clear()
    if not await check_subscription(message.from_user.id): return await message.answer("⚠️ Подпишись!", reply_markup=sub_kb())

    u = await db.get_user(message.from_user.id)
    cnt = await db.pool.fetchval("SELECT COUNT(*) FROM inventory WHERE user_id = $1", message.from_user.id)
    
    is_vip = u['vip_until'] and u['vip_until'] > datetime.now()
    st_text, st_color = ("VIP 💎", "yellow") if is_vip else ("Обычный 👤", "white")
    st_full = f"{st_text} (до {u['vip_until'].strftime('%d.%m.%y | %H:%M')})" if is_vip else st_text
    
    caption = f"👤 <b>Профиль: {u['username']}</b>\n💰 Баланс: {u['stars']:,} 🌟\n🎴 Карт: {cnt}\n👑 Статус: {st_full}"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎴 Моя Коллекция", callback_data="view_col_0")]])

    try:
        avatar_bytes = None
        photos = await bot.get_user_profile_photos(message.from_user.id, limit=1)
        if photos.total_count > 0:
            file = await bot.get_file(photos.photos[0][-1].file_id)
            obj = await bot.download(file)
            avatar_bytes = obj.read()

        # Вызываем твой скрипт profile_generator.py
        img_io = await generate_profile_image(avatar_bytes, u['username'], u['stars'], cnt, st_text, color=st_color)
        
        if img_io:
            img_io.seek(0)
            photo_file = BufferedInputFile(img_io.getvalue(), filename=f"p_{message.from_user.id}.png")
            return await message.answer_photo(photo_file, caption=caption, reply_markup=kb, parse_mode="HTML")
            
    except Exception as e:
        logging.error(f"Ошибка вызова генератора профиля: {e}")
    
    await message.answer(caption, reply_markup=kb, parse_mode="HTML")

# --- РЕФЕРАЛЫ ---
@dp.message(F.text == "👥 Рефералы")
async def refs_menu(message: types.Message):
    bot_me = await bot.get_me()
    link = f"https://t.me/{bot_me.username}?start={message.from_user.id}"
    text = (
        "👥 <b>Реферальная программа</b>\n\n"
        "За каждого приглашенного друга ты получишь <b>5 000 🌟</b>!\n\n"
        f"Твоя ссылка для приглашения:\n<code>{link}</code>"
    )
    await message.answer(text, parse_mode="HTML")

# --- ТОП-10 ---
@dp.message(F.text == "📊 ТОП-10")
async def leaderboard(message: types.Message, db: Database):
    rows = await db.pool.fetch("SELECT username, stars FROM users ORDER BY stars DESC LIMIT 10")
    if not rows: return await message.answer("В топе пока никого.")
    
    text = "🏆 <b>ТОП-10 ИГРОКОВ:</b>\n\n"
    for i, r in enumerate(rows, 1):
        text += f"{i}. {r['username']} — {r['stars']:,} 🌟\n"
    await message.answer(text, parse_mode="HTML")

# --- МЕХАНИКА КАРТ ---
@dp.message(F.text == "🎁 Получить Карту")
async def get_free_card(message: types.Message, db: Database):
    u = await db.get_user(message.from_user.id)
    cd = 2 if (u['vip_until'] and u['vip_until'] > datetime.now()) else 4
    if u['last_drop'] and datetime.now() < u['last_drop'] + timedelta(hours=cd):
        diff = (u['last_drop'] + timedelta(hours=cd)) - datetime.now()
        return await message.answer(f"⏳ Пак будет доступен через {diff.seconds // 3600}ч. {(diff.seconds // 60) % 60}м.")

    card = await db.pool.fetchrow("SELECT * FROM mifl_cards ORDER BY RANDOM() LIMIT 1")
    if not card: return await message.answer("База пуста.")
    
    cfg = RARITY_CONFIG.get(card['rarity'], {"icon": "⚪", "reward": 500})
    await db.pool.execute("UPDATE users SET last_drop = $1 WHERE user_id = $2", datetime.now(), message.from_user.id)
    
    has = await db.pool.fetchval("SELECT 1 FROM inventory WHERE user_id = $1 AND card_id = $2", message.from_user.id, card['card_id'])
    
    msg = await bot.send_message(message.chat.id, "📦 Открываем...")
    await asyncio.sleep(1.5)
    for step in [f"📊 Рейтинг: {card['rating']}", f"📍 Позиция: {card['position']}", f"🏢 Клуб: {card['club']}"]:
        await msg.edit_text(f"📦 Открываем...\n{step}")
        await asyncio.sleep(1)
    await msg.delete()

    if has:
        reward = int(cfg['reward'] * 0.5)
        await db.update_stars(message.from_user.id, reward)
        res_text = f"♻️ Дубликат продан за {reward} 🌟"
    else:
        await db.pool.execute("INSERT INTO inventory (user_id, card_id) VALUES ($1, $2)", message.from_user.id, card['card_id'])
        await db.update_stars(message.from_user.id, cfg['reward'])
        res_text = f"🎊 Новая карта! +{cfg['reward']} 🌟"

    cap = f"👤 {card['name']}\n📊 Рейтинг: {card['rating']}\n✨ Редкость: {cfg['icon']} {card['rarity']}\n\n{res_text}"
    await bot.send_photo(message.chat.id, photo=card['photo_id'], caption=cap)

# --- МАГАЗИН И БОНУС ---
@dp.message(F.text == "🛒 Магазин")
async def shop_menu(message: types.Message):
    kb = [[InlineKeyboardButton(text=f"{r} — {v['price']} 🌟", callback_data=f"buy_{r}")] for r, v in RARITY_CONFIG.items()]
    kb.append([InlineKeyboardButton(text="💎 VIP (1 день) — 15 000 🌟", callback_data="buy_VIP")])
    await message.answer("🛒 <b>Магазин</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@dp.callback_query(F.data.startswith("buy_"))
async def process_buy(call: types.CallbackQuery, db: Database):
    choice = call.data.split("_")[1]
    u = await db.get_user(call.from_user.id)
    
    if choice == "VIP":
        if u['stars'] < 15000: return await call.answer("Недостаточно звёзд!", show_alert=True)
        new_date = (u['vip_until'] if u['vip_until'] and u['vip_until'] > datetime.now() else datetime.now()) + timedelta(days=1)
        await db.pool.execute("UPDATE users SET stars = stars - 15000, vip_until = $1 WHERE user_id = $2", new_date, call.from_user.id)
        return await call.message.answer("💎 VIP статус продлен!")

    if u['stars'] < RARITY_CONFIG[choice]['price']: return await call.answer("Недостаточно звёзд!", show_alert=True)
    card = await db.pool.fetchrow("SELECT * FROM mifl_cards WHERE rarity = $1 ORDER BY RANDOM() LIMIT 1", choice)
    if not card: return await call.answer("Карт такой редкости нет.")
    
    await db.update_stars(call.from_user.id, -RARITY_CONFIG[choice]['price'])
    await db.pool.execute("INSERT INTO inventory (user_id, card_id) VALUES ($1, $2)", call.from_user.id, card['card_id'])
    await call.message.answer(f"🛍 Куплен пак {choice}!")

@dp.message(F.text == "📅 Бонус")
async def cmd_bonus(message: types.Message, db: Database):
    u = await db.get_user(message.from_user.id)
    if u['last_bonus'] and datetime.now() < u['last_bonus'] + timedelta(hours=24):
        return await message.answer("⏳ Заходи завтра!")
    
    val = random.randint(6000, 15000) if random.random() < 0.1 else random.randint(1000, 4000)
    await db.update_stars(message.from_user.id, val)
    await db.pool.execute("UPDATE users SET last_bonus = $1 WHERE user_id = $2", datetime.now(), message.from_user.id)
    await message.answer(f"🎁 Твой бонус: {val} 🌟")

# --- УГАДАЙКА ---
@dp.message(F.text == "⚽ Мини Игры")
async def games_menu(message: types.Message):
    await message.answer("⚽ Выбери игру:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🧩 Угадай Игрока", callback_data="start_guess")]]))

@dp.callback_query(F.data == "start_guess")
async def guess_bet_step(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer("💰 Введи ставку (100 - 20 000 🌟):")
    await state.set_state(Form.guess_bet)

@dp.message(Form.guess_bet)
async def guess_start(message: types.Message, state: FSMContext, db: Database):
    if not message.text.isdigit(): return
    bet, u = int(message.text), await db.get_user(message.from_user.id)
    if bet < 100 or bet > 20000 or bet > u['stars']: return await message.answer("❌ Ошибка ставки.")
    
    card = await db.pool.fetchrow("SELECT * FROM mifl_cards ORDER BY RANDOM() LIMIT 1")
    others = await db.pool.fetch("SELECT name FROM mifl_cards WHERE name != $1 ORDER BY RANDOM() LIMIT 3", card['name'])
    opts = [card['name']] + [r['name'] for r in others]
    random.shuffle(opts)
    
    await db.update_stars(message.from_user.id, -bet)
    await state.update_data(correct=card['name'], bet=bet, opts=opts, photo=card['photo_id'])
    
    kb = [[InlineKeyboardButton(text=opts[0], callback_data="ans_0"), InlineKeyboardButton(text=opts[1], callback_data="ans_1")],
          [InlineKeyboardButton(text=opts[2], callback_data="ans_2"), InlineKeyboardButton(text=opts[3], callback_data="ans_3")]]
    
    await message.answer(f"🧩 <b>Угадай игрока!</b>\n🛡 Клуб: {card['club']}\n📍 Поз: {card['position']}\n💰 Ставка: {bet}", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    await state.set_state(Form.guess_playing)

@dp.callback_query(F.data.startswith("ans_"), Form.guess_playing)
async def check_guess(call: types.CallbackQuery, state: FSMContext, db: Database):
    idx, data = int(call.data.split("_")[1]), await state.get_data()
    await call.message.delete()
    if data['opts'][idx] == data['correct']:
        await db.update_stars(call.from_user.id, data['bet']*2)
        txt = f"🎉 Верно! Это {data['correct']}. +{data['bet']*2} 🌟"
    else: txt = f"💥 Увы, это был {data['correct']}."
    await call.message.answer_photo(data['photo'], caption=txt)
    await state.clear()

# --- АДМИН-КОМАНДЫ ---
@dp.message(Command("add_promo"), F.from_user.id.in_(ADMIN_IDS))
async def adm_promo(message: types.Message, command: CommandObject, db: Database):
    try:
        c, s, u = command.args.split()
        await db.pool.execute("INSERT INTO promocodes (code, stars, max_uses) VALUES ($1, $2, $3)", c.upper(), int(s), int(u))
        await message.answer(f"✅ Код {c.upper()} создан!")
    except: await message.answer("Формат: /add_promo КОД ЗВЕЗДЫ ЛИМИТ")

@dp.message(Command("clear_cards"), F.from_user.id.in_(ADMIN_IDS))
async def adm_clear(message: types.Message, db: Database):
    await db.pool.execute("TRUNCATE TABLE mifl_cards CASCADE")
    await message.answer("⚠️ База карт очищена!")

@dp.message(Command("add_player"), F.from_user.id.in_(ADMIN_IDS))
async def adm_add_p(message: types.Message, state: FSMContext):
    await message.answer("Отправь фото:")
    await state.set_state(Form.add_player_photo)

@dp.message(Form.add_player_photo, F.photo)
async def adm_p_photo(message: types.Message, state: FSMContext):
    await state.update_data(fid=message.photo[-1].file_id)
    await message.answer("Имя, Рейтинг, Клуб, Позиция")
    await state.set_state(Form.add_player_data)

@dp.message(Form.add_player_data)
async def adm_p_save(message: types.Message, state: FSMContext, db: Database):
    d = [x.strip() for x in message.text.split(",")]
    rat = float(d[1])
    if rat >= 5.0: r = "One"
    elif 4.0 <= rat <= 4.5: r = "Chase"
    elif 3.0 <= rat <= 3.5: r = "Drop"
    elif 2.0 <= rat <= 2.5: r = "Series"
    else: r = "Stock"
    
    fid = (await state.get_data())['fid']
    await db.pool.execute("INSERT INTO mifl_cards (name, rating, club, position, rarity, photo_id) VALUES ($1, $2, $3, $4, $5, $6)", d[0], rat, d[2], d[3], r, fid)
    await message.answer(f"✅ Игрок добавлен! Редкость: {r}")
    await state.clear()

# --- СЕРВЕР И ЗАПУСК ---
async def start_srv():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Mifl Running"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(os.environ.get("PORT", 8080))).start()

async def main():
    asyncio.create_task(start_srv())
    pool = await asyncpg.create_pool(DATABASE_URL, ssl='require')
    db = Database(pool)
    await db.create_tables()
    dp["db"] = db
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
