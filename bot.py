import os
import asyncio
import io
import random
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile
from aiohttp import web
import asyncpg

# Твои модули
from database import Database
from profile_generator import generate_profile_image

# --- КОНФИГУРАЦИЯ ---
TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_IDS = [1866813859]  # ЗАМЕНИ НА СВОЙ ID

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Редкости и коэффициенты (Stock=🟢, Drop=🔴)
RARITY_CONFIG = {
    "One": {"icon": "🟡", "price": 3500, "coef": 2.5},
    "Chase": {"icon": "🟣", "price": 2800, "coef": 2.1},
    "Drop": {"icon": "🔴", "price": 2000, "coef": 1.8},
    "Series": {"icon": "🔵", "price": 1200, "coef": 1.5},
    "Stock": {"icon": "🟢", "price": 500, "coef": 1.2}
}

# --- СОСТОЯНИЯ ---
class AddPlayer(StatesGroup):
    waiting_for_photo = State()
    waiting_for_details = State()

class GuessGame(StatesGroup):
    bet = State()

# --- КЛАВИАТУРЫ ---
def main_kb():
    kb = [
        [types.KeyboardButton(text="🎁 Получить Карту")],
        [types.KeyboardButton(text="⚽ Мини Игры"), types.KeyboardButton(text="🛒 Магазин")],
        [types.KeyboardButton(text="👤 Профиль"), types.KeyboardButton(text="👥 Рефералы")],
        [types.KeyboardButton(text="📊 ТОП-10")]
    ]
    return types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

# --- ВЕБ-СЕРВЕР (Для Render) ---
async def handle(request): return web.Response(text="Bot is running")
async def start_web():
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', int(os.getenv("PORT", 8080))).start()

# ==========================================
# ОСНОВНАЯ ЛОГИКА
# ==========================================

@dp.message(Command("start"))
async def cmd_start(message: types.Message, command: CommandObject, db: Database):
    user_id = message.from_user.id
    ref_id = int(command.args) if command.args and command.args.isdigit() else None
    
    await db.pool.execute(
        "INSERT INTO users (user_id, username, referrer_id) VALUES ($1, $2, $3) "
        "ON CONFLICT (user_id) DO UPDATE SET username = $2",
        user_id, message.from_user.username or message.from_user.first_name, ref_id
    )
    await message.answer("⚽ Добро пожаловать в **MIFL CARDS**!", reply_markup=main_kb(), parse_mode="Markdown")

# --- ПРОФИЛЬ (ГРАФИКА + ТЕКСТ) ---
@dp.message(F.text == "👤 Профиль")
async def handle_profile(message: types.Message, db: Database):
    user_id = message.from_user.id
    load = await message.answer("🔄 Загрузка профиля...")
    
    try:
        u = await db.get_user(user_id)
        is_vip = await db.is_vip(user_id)
        count = await db.pool.fetchval("SELECT COUNT(*) FROM inventory WHERE user_id = $1", user_id)
        status = "VIP" if is_vip else "Обычный"

        # Получаем аватарку
        ava_bytes = None
        try:
            photos = await bot.get_user_profile_photos(user_id, limit=1)
            if photos.total_count > 0:
                file = await bot.get_file(photos.photos[0][0].file_id)
                content = await bot.download_file(file.file_path)
                ava_bytes = content.read()
        except: pass

        # Генерация картинки
        img_buf = await generate_profile_image(
            ava_bytes, u['username'], u['stars'], count, status
        )

        # Текстовое описание
        stars_f = f"{u['stars']:,}".replace(",", " ")
        caption = (
            f"👤 **ПРОФИЛЬ: {u['username']}**\n\n"
            f"💰 **Баланс:** `{stars_f}` 🌟\n"
            f"🎴 **Коллекция:** `{count}` шт.\n"
            f"👑 **Статус:** `{status}`\n"
        )

        photo_input = BufferedInputFile(img_buf.read(), filename="profile.png")
        await message.answer_photo(
            photo_input, caption=caption, 
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="🎴 Моя коллекция", callback_data="my_collection")]
            ]), parse_mode="Markdown"
        )
    finally: await load.delete()

# --- АДМИН: ДОБАВИТЬ ИГРОКА ---
@dp.message(Command("add_player"))
async def admin_add(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    await message.answer("📸 Отправь фото игрока:")
    await state.set_state(AddPlayer.waiting_for_photo)

@dp.message(AddPlayer.waiting_for_photo, F.photo)
async def admin_photo(message: types.Message, state: FSMContext):
    await state.update_data(photo_id=message.photo[-1].file_id)
    await message.answer("📝 Введи: `Имя | Рейтинг | Клуб | Позиция`", parse_mode="Markdown")
    await state.set_state(AddPlayer.waiting_for_details)

@dp.message(AddPlayer.waiting_for_details)
async def admin_final(message: types.Message, state: FSMContext, db: Database):
    try:
        name, rat, club, pos = [i.strip() for i in message.text.split("|")]
        rating = float(rat.replace(",", "."))
        
        # Авто-редкость
        if rating <= 1.5: rar = "Stock"
        elif rating <= 2.5: rar = "Series"
        elif rating <= 3.5: rar = "Drop"
        elif rating <= 4.5: rar = "Chase"
        else: rar = "One"

        data = await state.get_data()
        await db.pool.execute(
            "INSERT INTO mifl_cards (name, rating, rarity, club, position, photo_id) VALUES ($1,$2,$3,$4,$5,$6)",
            name, rating, rar, club, pos, data['photo_id']
        )
        await message.answer(f"✅ Добавлен: {name} ({RARITY_CONFIG[rar]['icon']} {rar})")
        await state.clear()
    except: await message.answer("❌ Ошибка формата!")

# --- МИНИ-ИГРЫ: УГАДАЙКА ---
@dp.callback_query(F.data == "play_guess")
async def guess_start(callback: types.CallbackQuery, db: Database, state: FSMContext):
    u = await db.get_user(callback.from_user.id)
    is_vip = await db.is_vip(callback.from_user.id)
    cd = 2 if is_vip else 4
    
    if u.get('last_game_guess') and datetime.now() < u['last_game_guess'] + timedelta(hours=cd):
        diff = (u['last_game_guess'] + timedelta(hours=cd)) - datetime.now()
        return await callback.answer(f"⏳ Жди {int(diff.total_seconds()//60)} мин.", show_alert=True)

    await callback.message.answer("🧩 Введи ставку (до 25,000 🌟):")
    await state.set_state(GuessGame.bet)
    await callback.answer()

@dp.message(GuessGame.bet)
async def guess_bet(message: types.Message, state: FSMContext, db: Database):
    if not message.text.isdigit(): return
    bet = int(message.text)
    u = await db.get_user(message.from_user.id)
    if bet < 1 or bet > 25000 or bet > u['stars']: return await message.answer("❌ Ошибка ставки.")

    card = await db.get_random_card()
    wrong = await db.pool.fetch("SELECT name FROM mifl_cards WHERE name != $1 ORDER BY RANDOM() LIMIT 3", card['name'])
    opts = [card['name']] + [r['name'] for r in wrong]
    random.shuffle(opts)
    
    coef = RARITY_CONFIG[card['rarity']]['coef']
    kb = [[types.InlineKeyboardButton(text=o, callback_data=f"ans_{'w' if o==card['name'] else 'l'}_{bet}_{card['card_id']}")] for o in opts]
    
    await db.update_stars(message.from_user.id, -bet)
    await db.set_cooldown(message.from_user.id, 'last_game_guess')
    
    await message.answer(
        f"🧩 **УГАДАЙКА**\n⭐ Рейтинг: `{card['rating']}`\n📈 Коэф: `x{coef}`",
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown"
    )
    await state.clear()

@dp.callback_query(F.data.startswith("ans_"))
async def guess_ans(callback: types.CallbackQuery, db: Database):
    _, res, bet, c_id = callback.data.split("_")
    card = await db.pool.fetchrow("SELECT * FROM mifl_cards WHERE card_id = $1", int(c_id))
    
    if res == 'w':
        win = int(int(bet) * RARITY_CONFIG[card['rarity']]['coef'])
        await db.update_stars(callback.from_user.id, win)
        await callback.message.delete()
        await callback.message.answer_photo(card['photo_id'], caption=f"✅ **ВЕРНО!**.")
    await callback.answer()

# --- МАГАЗИН ---
@dp.message(F.text == "🛒 Магазин")
async def shop(message: types.Message):
    buttons = []
    for rar, cfg in RARITY_CONFIG.items():
        buttons.append([types.InlineKeyboardButton(text=f"{cfg['icon']} {rar} Pack — {cfg['price']}🌟", callback_data=f"buy_pack_{rar}")])
    buttons.append([types.InlineKeyboardButton(text="👑 VIP (1 день) — 20,000🌟", callback_data="buy_vip")])
    
    await message.answer("🛒 **МАГАЗИН**", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="Markdown")

@dp.callback_query(F.data == "buy_vip")
async def buy_vip(callback: types.CallbackQuery, db: Database):
    u = await db.get_user(callback.from_user.id)
    if u['stars'] < 20000: return await callback.answer("❌ Мало звезд!", show_alert=True)
    await db.update_stars(callback.from_user.id, -20000)
    exp = datetime.now() + timedelta(days=1)
    await db.pool.execute("UPDATE users SET vip_until = $1 WHERE user_id = $2", exp, callback.from_user.id)
    await callback.message.answer("👑 VIP активирован! КД снижено в 2 раза.")
    await callback.answer()

# --- ЗАПУСК ---
async def main():
    asyncio.create_task(start_web())
    pool = await asyncpg.create_pool(DATABASE_URL, ssl='require')
    db = Database(pool)
    await db.create_tables()
    dp["db"] = db
    print("Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
