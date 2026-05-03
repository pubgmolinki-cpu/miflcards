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
CHANNEL_ID = "@Miflcards"
ADMIN_IDS = [1866813859]

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Пытаемся импортировать твой генератор
try:
    from profile_generator import generate_profile_image
except ImportError:
    async def generate_profile_image(*args): return None

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

    async def get_random_card(self):
        return await self.pool.fetchrow("SELECT * FROM mifl_cards ORDER BY RANDOM() LIMIT 1")

# --- ПРОВЕРКА ПОДПИСКИ ---
async def check_subscription(user_id):
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in ["member", "administrator", "creator"]
    except:
        return False

# --- ПРОФИЛЬ (ТА САМАЯ СИСТЕМА ФОТО) ---
@dp.message(F.text == "👤 Профиль")
async def view_profile(message: types.Message, state: FSMContext, db: Database):
    await state.clear()
    if not await check_subscription(message.from_user.id): 
        return await message.answer("⚠️ Подпишись на канал!", reply_markup=sub_kb())

    u = await db.get_user(message.from_user.id)
    cnt = await db.pool.fetchval("SELECT COUNT(*) FROM inventory WHERE user_id = $1", message.from_user.id)
    st = "VIP 💎" if u.get('vip_until') and u['vip_until'] > datetime.now() else "Обычный 👤"
    
    caption = f"👤 <b>Профиль: {u['username']}</b>\n💰 Баланс: {u['stars']:,} 🌟\n🎴 Карт: {cnt}\n👑 Статус: {st}"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎴 Моя Коллекция", callback_data="view_col_0")]])

    avatar_bytes = None
    try:
        photos = await bot.get_user_profile_photos(message.from_user.id, limit=1)
        if photos.total_count > 0:
            file = await bot.get_file(photos.photos[0][-1].file_id)
            # ТВОЯ СИСТЕМА:
            downloaded = await bot.download_file(file.file_path)
            avatar_bytes = downloaded.read()

        # Вызов генератора из profile_generator.py
        img_io = await generate_profile_image(avatar_bytes, u['username'], u['stars'], cnt, st)
        if img_io:
            return await message.answer_photo(
                BufferedInputFile(img_io.read(), filename="p.png"), 
                caption=caption, 
                reply_markup=kb, 
                parse_mode="HTML"
            )
    except Exception as e:
        logging.error(f"Avatar system error: {e}")
    
    await message.answer(caption, reply_markup=kb, parse_mode="HTML")

# --- МИНИ-ИГРА УГАДАЙКА (ПОЛНАЯ РАБОТА) ---
@dp.message(F.text == "⚽ Мини Игры")
async def games_menu(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("⚽ Выбери игру:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🧩 Угадай Игрока", callback_data="start_guess")]]))

@dp.callback_query(F.data == "start_guess")
async def guess_bet_step(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("💰 Введите ставку (мин. 100, макс. 20000 🌟):")
    await state.set_state(Form.guess_bet)

async def game_timer(msg: types.Message, state: FSMContext):
    await asyncio.sleep(60)
    if await state.get_state() == Form.guess_playing:
        try:
            await msg.delete()
            await msg.answer("⏰ Время вышло! Ставка сгорела.")
        except: pass
        await state.clear()

@dp.message(Form.guess_bet)
async def guess_logic(message: types.Message, state: FSMContext, db: Database):
    if not message.text.isdigit(): return
    bet = int(message.text)
    u = await db.get_user(message.from_user.id)
    
    if bet < 100 or bet > 20000 or bet > u['stars']:
        return await message.answer("❌ Недостаточно средств или неверная ставка (100-20000).")
    
    card = await db.get_random_card()
    others = await db.pool.fetch("SELECT name FROM mifl_cards WHERE name != $1 ORDER BY RANDOM() LIMIT 3", card['name'])
    opts = [card['name']] + [r['name'] for r in others]
    random.shuffle(opts)
    
    await db.update_stars(message.from_user.id, -bet)
    await state.update_data(correct=card['name'], bet=bet, rating=card['rating'], opts=opts, cid=card['card_id'])
    
    kb = [
        [InlineKeyboardButton(text=opts[0], callback_data="ans_0"), InlineKeyboardButton(text=opts[1], callback_data="ans_1")],
        [InlineKeyboardButton(text=opts[2], callback_data="ans_2"), InlineKeyboardButton(text=opts[3], callback_data="ans_3")],
        [InlineKeyboardButton(text="💡 Подсказка (-20%)", callback_data="hint"), InlineKeyboardButton(text="🏳 Сдаться", callback_data="surrender")]
    ]
    
    msg = await message.answer(
        f"🧩 <b>Угадай игрока! (60 сек)</b>\n\n🛡 Клуб: {card['club']}\n📍 Позиция: {card['position']}\n💰 Ставка: {bet} 🌟", 
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML"
    )
    await state.set_state(Form.guess_playing)
    asyncio.create_task(game_timer(msg, state))

@dp.callback_query(F.data == "hint", Form.guess_playing)
async def guess_hint(call: types.CallbackQuery, state: FSMContext, db: Database):
    data = await state.get_data()
    cost = int(data['bet'] * 0.2)
    await db.update_stars(call.from_user.id, -cost)
    await call.answer(f"Подсказка: Рейтинг этого игрока — {data['rating']} (-{cost} 🌟)", show_alert=True)

@dp.callback_query(F.data == "surrender", Form.guess_playing)
async def guess_give_up(call: types.CallbackQuery, state: FSMContext, db: Database):
    data = await state.get_data()
    card = await db.pool.fetchrow("SELECT * FROM mifl_cards WHERE card_id = $1", data['cid'])
    await call.message.delete()
    await call.message.answer_photo(card['photo_id'], caption=f"🏳 Ты сдался. Это был <b>{data['correct']}</b>.", parse_mode="HTML")
    await state.clear()

@dp.callback_query(F.data.startswith("ans_"), Form.guess_playing)
async def check_ans(call: types.CallbackQuery, state: FSMContext, db: Database):
    idx = int(call.data.split("_")[1])
    data = await state.get_data()
    card = await db.pool.fetchrow("SELECT * FROM mifl_cards WHERE card_id = $1", data['cid'])
    await call.message.delete()
    
    if data['opts'][idx] == data['correct']:
        win = data['bet'] * 2
        await db.update_stars(call.from_user.id, win)
        txt = f"🎉 <b>ПОБЕДА!</b>\nЭто <b>{data['correct']}</b>!\n💰 Выиграно: {win} 🌟"
    else:
        txt = f"💥 <b>ПРОИГРЫШ</b>\nПравильный ответ: <b>{data['correct']}</b>.\n💸 Потеряно: {data['bet']} 🌟"
               
    await call.message.answer_photo(card['photo_id'], caption=txt, parse_mode="HTML")
    await state.clear()

# --- СИСТЕМА ТРЕЙДА ---
@dp.message(F.text == "🔄 Трейд")
async def trade_init(message: types.Message, state: FSMContext):
    await state.clear()
    kb = [[InlineKeyboardButton(text="📤 Создать код", callback_data="tr_create")], [InlineKeyboardButton(text="📥 Ввести код", callback_data="tr_join")]]
    await message.answer("🔄 <b>ОБМЕН КАРТАМИ</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@dp.callback_query(F.data == "tr_create")
async def tr_create_pg(call: types.CallbackQuery, db: Database):
    cards = await db.pool.fetch("SELECT c.* FROM mifl_cards c JOIN inventory i ON c.card_id = i.card_id WHERE i.user_id = $1 LIMIT 5", call.from_user.id)
    if not cards: return await call.answer("У тебя нет карт для обмена!", show_alert=True)
    kb = [[InlineKeyboardButton(text=f"{c['name']}", callback_data=f"trgen_{c['card_id']}")] for c in cards]
    await call.message.edit_text("Выбери карту, которую хочешь отдать:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("trgen_"))
async def tr_gen_final(call: types.CallbackQuery, db: Database):
    cid = int(call.data.split("_")[1])
    code = "TRD-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=5))
    await db.pool.execute("INSERT INTO active_trades (code, user_a, card_a) VALUES ($1, $2, $3)", code, call.from_user.id, cid)
    await call.message.edit_text(f"✅ Код обмена создан! Передай его другу:\n\n<code>{code}</code>", parse_mode="HTML")

# --- ОСТАЛЬНЫЕ ФУНКЦИИ (СТАРТ, МАГАЗИН, ТОП) ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext, command: CommandObject, db: Database):
    await state.clear()
    if not await check_subscription(message.from_user.id):
        return await message.answer("⚠️ Для игры подпишись на канал!", reply_markup=sub_kb())
    
    ref_id = command.args
    user_exists = await db.pool.fetchval("SELECT 1 FROM users WHERE user_id = $1", message.from_user.id)
    if not user_exists:
        await db.get_user(message.from_user.id, message.from_user.first_name)
        if ref_id and ref_id.isdigit() and int(ref_id) != message.from_user.id:
            await db.update_stars(int(ref_id), 5000)
            try: await bot.send_message(int(ref_id), "👥 Новый реферал! +5000 🌟")
            except: pass
            
    await message.answer(f"⚽ Добро пожаловать в <b>Mifl Cards</b>!", reply_markup=main_kb(), parse_mode="HTML")

@dp.message(F.text == "📊 ТОП-10")
async def leaderboard(message: types.Message, db: Database):
    rows = await db.pool.fetch("SELECT username, stars FROM users ORDER BY stars DESC LIMIT 10")
    txt = "🏆 <b>ТОП-10 ИГРОКОВ:</b>\n\n" + "\n".join([f"{i+1}. {r['username']} — {r['stars']:,} 🌟" for i, r in enumerate(rows)])
    await message.answer(txt, parse_mode="HTML")

@dp.message(F.text == "📅 Бонус")
async def cmd_bonus(message: types.Message, db: Database):
    u = await db.get_user(message.from_user.id)
    if u.get('last_bonus') and datetime.now() < u['last_bonus'] + timedelta(hours=24):
        return await message.answer("⏳ Бонус будет доступен позже!")
    val = random.randint(500, 2500)
    await db.update_stars(message.from_user.id, val)
    await db.pool.execute("UPDATE users SET last_bonus = $1 WHERE user_id = $2", datetime.now(), message.from_user.id)
    await message.answer(f"🎁 Получено {val} 🌟!")

# --- ЗАПУСК ---
async def handle(r): return web.Response(text="Mifl Cards")
async def main():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(os.environ.get("PORT", 8080))).start()

    pool = await asyncpg.create_pool(DATABASE_URL, ssl='require')
    db = Database(pool)
    await db.create_tables()
    dp["db"] = db
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
