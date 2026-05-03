import os
import asyncio
import random
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

# --- КОНФИГУРАЦИЯ ---
TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
CHANNEL_ID = "@Miflcards"  # Канал для проверки подписки
ADMIN_ID = 1866813859

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()

try:
    from profile_generator import generate_profile_image
except ImportError:
    async def generate_profile_image(*args): return None

class Form(StatesGroup):
    add_player_photo = State()
    add_player_data = State()
    guess_bet = State()
    guess_playing = State()

# --- ПРОВЕРКА ПОДПИСКИ ---
async def check_subscription(user_id):
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in ["member", "administrator", "creator"]
    except:
        return False

def sub_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Подписаться на канал", url="https://t.me/Miflcards")],
        [InlineKeyboardButton(text="✅ Я подписался", callback_data="check_subs")]
    ])

# --- КЛАВИАТУРА ---
def main_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🎁 Получить Карту"), KeyboardButton(text="📅 Бонус")],
        [KeyboardButton(text="⚽ Мини Игры"), KeyboardButton(text="🛒 Магазин")],
        [KeyboardButton(text="🔄 Трейд"), KeyboardButton(text="🏷 Промокод")],
        [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="📊 ТОП-10")]
    ], resize_keyboard=True)

# --- КОМАНДА /START ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext, db):
    await state.clear()
    if not await check_subscription(message.from_user.id):
        return await message.answer(f"⚠️ Для работы с ботом подпишись на наш канал {CHANNEL_ID}!", reply_markup=sub_kb())
    
    user = await db.get_user(message.from_user.id, message.from_user.username or message.from_user.first_name)
    await message.answer(f"⚽ Привет, {user['username']}! Ты в деле.", reply_markup=main_kb())

@dp.callback_query(F.data == "check_subs")
async def verify_sub_callback(call: types.CallbackQuery, state: FSMContext, db):
    if await check_subscription(call.from_user.id):
        await call.message.delete()
        await cmd_start(call.message, state, db)
    else:
        await call.answer("❌ Ты всё еще не подписан!", show_alert=True)

# --- ПРОФИЛЬ ---
@dp.message(F.text == "👤 Профиль")
async def view_profile(message: types.Message, state: FSMContext, db):
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
            downloaded = await bot.download_file(file.file_path)
            avatar_bytes = downloaded.read()

        img_io = await generate_profile_image(avatar_bytes, u['username'], u['stars'], cnt, st)
        if img_io:
            return await message.answer_photo(BufferedInputFile(img_io.read(), filename="p.png"), caption=caption, reply_markup=kb, parse_mode="HTML")
    except Exception as e:
        logging.error(f"Err: {e}")
    
    await message.answer(caption, reply_markup=kb, parse_mode="HTML")

# --- УГАДАЙКА (С ТАЙМЕРОМ) ---
@dp.message(F.text == "⚽ Мини Игры")
async def games_menu(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Выбери игру:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🧩 Угадайку", callback_data="start_guess")]]))

@dp.callback_query(F.data == "start_guess")
async def guess_bet_step(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("💰 Введи ставку:")
    await state.set_state(Form.guess_bet)

async def game_timer(msg: types.Message, state: FSMContext):
    await asyncio.sleep(60)
    if await state.get_state() == Form.guess_playing:
        try:
            await msg.delete()
            await msg.answer("⏰ Время вышло! Сообщение удалено.")
        except: pass
        await state.clear()

@dp.message(Form.guess_bet)
async def guess_run(message: types.Message, state: FSMContext, db):
    if not message.text.isdigit(): return
    bet = int(message.text)
    u = await db.get_user(message.from_user.id)
    if bet < 100 or bet > u['stars']: return await message.answer("❌ Ошибка ставки.")
    
    card = await db.pool.fetchrow("SELECT * FROM mifl_cards ORDER BY RANDOM() LIMIT 1")
    others = await db.pool.fetch("SELECT name FROM mifl_cards WHERE name != $1 ORDER BY RANDOM() LIMIT 3", card['name'])
    opts = [card['name']] + [r['name'] for r in others]
    random.shuffle(opts)
    
    await db.update_stars(message.from_user.id, -bet)
    await state.update_data(correct=card['name'], bet=bet, rating=card['rating'], opts=opts)
    
    kb = [
        [InlineKeyboardButton(text=opts[0], callback_data="ans_0"), InlineKeyboardButton(text=opts[1], callback_data="ans_1")],
        [InlineKeyboardButton(text=opts[2], callback_data="ans_2"), InlineKeyboardButton(text=opts[3], callback_data="ans_3")],
        [InlineKeyboardButton(text="💡 Подсказка", callback_data="hint"), InlineKeyboardButton(text="🏳 Сдаться", callback_data="surrender")]
    ]
    
    m = await message.answer(f"🧩 Угадай! (60с)\nКлуб: {card['club']}\nПозиция: {card['position']}\nСтавка: {bet} 🌟", 
                             reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await state.set_state(Form.guess_playing)
    asyncio.create_task(game_timer(m, state))

# --- АДМИНКА ---
@dp.message(Command("add_player"), F.from_user.id == ADMIN_ID)
async def adm_add_p(message: types.Message, state: FSMContext):
    await message.answer("Фото:")
    await state.set_state(Form.add_player_photo)

@dp.message(Form.add_player_photo, F.photo)
async def adm_p_photo(message: types.Message, state: FSMContext):
    await state.update_data(fid=message.photo[-1].file_id)
    await message.answer("Данные (Имя, Рейтинг, Клуб, Позиция, Редкость):")
    await state.set_state(Form.add_player_data)

@dp.message(Form.add_player_data)
async def adm_p_save(message: types.Message, state: FSMContext, db):
    d = [x.strip() for x in message.text.split(",")]
    fid = (await state.get_data())['fid']
    await db.pool.execute("INSERT INTO mifl_cards (name, rating, club, position, rarity, photo_id) VALUES ($1, $2, $3, $4, $5, $6)", d[0], float(d[1]), d[2], d[3], d[4], fid)
    await message.answer("✅ Готово")
    await state.clear()

# --- СЕРВЕР И ЗАПУСК ---
async def handle(r): return web.Response(text="Mifl Cards")
async def start_srv():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(os.environ.get("PORT", 8080))).start()

async def main():
    asyncio.create_task(start_srv())
    pool = await asyncpg.create_pool(DATABASE_URL, ssl='require')
    from database import DBManager # Предполагаем, что класс там
    db = DBManager(pool)
    dp["db"] = db
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
