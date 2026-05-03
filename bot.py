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
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from aiohttp import web
from io import BytesIO

# Попытка импорта твоего генератора (если файла нет — будет текст)
try:
    from profile_generator import generate_profile_image
except ImportError:
    generate_profile_image = None

# --- КОНФИГУРАЦИЯ ---
TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_IDS = [1866813859] # Твой ID

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()

class Form(StatesGroup):
    add_player_photo = State()
    add_player_data = State()
    guess_bet = State()
    guess_playing = State()
    promo_input = State()

# --- КЛАВИАТУРЫ ---
def main_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🎁 Получить Карту"), KeyboardButton(text="📅 Бонус")],
        [KeyboardButton(text="⚽ Мини Игры"), KeyboardButton(text="🛒 Магазин")],
        [KeyboardButton(text="🔄 Трейд"), KeyboardButton(text="🏷 Промокод")],
        [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="📊 ТОП-10")]
    ], resize_keyboard=True)

# --- MIDDLEWARE / СБРОС СОСТОЯНИЯ ---
# Если пользователь нажимает на кнопку меню, сбрасываем состояние игры/админки
@dp.message(F.text.in_(["👤 Профиль", "⚽ Мини Игры", "🎁 Получить Карту", "🛒 Магазин", "📊 ТОП-10"]))
async def global_menu_handler(message: types.Message, state: FSMContext, db):
    current_state = await state.get_state()
    if current_state:
        await state.clear()
    
    # Сразу перенаправляем на нужную функцию
    if message.text == "👤 Профиль":
        await view_profile(message, db)
    elif message.text == "⚽ Мини Игры":
        await games_menu(message)
    # Добавь остальные вызовы функций здесь

# --- ПРОФИЛЬ С ФОТО ---
async def view_profile(message: types.Message, db):
    u = await db.get_user(message.from_user.id)
    cnt = await db.pool.fetchval("SELECT COUNT(*) FROM inventory WHERE user_id = $1", message.from_user.id)
    st = "VIP 💎" if u.get('vip_until') and u['vip_until'] > datetime.now() else "Обычный 👤"
    
    caption = (f"👤 <b>Профиль: {u['username']}</b>\n"
               f"💰 Баланс: {u['stars']:,} 🌟\n"
               f"🎴 Карт в коллекции: {cnt}\n"
               f"👑 Статус: {st}")
    
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎴 Моя Коллекция", callback_data="view_col_0")]])

    if generate_profile_image:
        try:
            # Получаем аватарку пользователя
            photos = await bot.get_user_profile_photos(message.from_user.id, limit=1)
            avatar_bytes = None
            if photos.total_count > 0:
                file = await bot.get_file(photos.photos[0][0].file_id)
                avatar_bytes = await bot.download_file(file.file_path)
            
            # Генерируем картинку
            img_io = await generate_profile_image(avatar_bytes, u['username'], u['stars'], cnt, st)
            await message.answer_photo(BufferedInputFile(img_io.read(), filename="profile.png"), caption=caption, reply_markup=kb, parse_mode="HTML")
            return
        except Exception as e:
            logging.error(f"Ошибка генерации фото: {e}")
    
    await message.answer(caption, reply_markup=kb, parse_mode="HTML")

# --- УГАДАЙКА С ТАЙМЕРОМ ---
@dp.callback_query(F.data == "start_guess")
async def guess_bet_step(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("💰 Введите ставку (минимум 100 🌟):")
    await state.set_state(Form.guess_bet)

async def auto_delete_game(message: types.Message, state: FSMContext):
    """Таймер на 60 секунд"""
    await asyncio.sleep(60)
    curr = await state.get_state()
    if curr == Form.guess_playing:
        try:
            await message.delete()
            await message.answer("⏰ Время вышло! Игра аннулирована, ставка не возвращена.")
        except:
            pass
        await state.clear()

@dp.message(Form.guess_bet)
async def guess_logic(message: types.Message, state: FSMContext, db):
    if not message.text.isdigit(): return
    bet = int(message.text)
    u = await db.get_user(message.from_user.id)
    if bet < 100 or bet > u['stars']:
        return await message.answer("❌ Ошибка ставки.")
    
    card = await db.pool.fetchrow("SELECT * FROM mifl_cards ORDER BY RANDOM() LIMIT 1")
    if not card: return await message.answer("База пуста.")
    
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
    
    game_msg = await message.answer(
        f"🧩 <b>Угадай игрока! (60 сек)</b>\n\n🛡 Клуб: {card['club']}\n📍 Позиция: {card['position']}\n💰 Ставка: {bet} 🌟",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML"
    )
    await state.set_state(Form.guess_playing)
    # Запускаем таймер в фоне
    asyncio.create_task(auto_delete_game(game_msg, state))

# --- АДМИН-КОМАНДЫ (ФИКС) ---
@dp.message(Command("add_player"), F.from_user.id.in_(ADMIN_IDS))
async def admin_add_start(message: types.Message, state: FSMContext):
    await message.answer("Отправьте фото игрока:")
    await state.set_state(Form.add_player_photo)

@dp.message(Command("add_promo"), F.from_user.id.in_(ADMIN_IDS))
async def admin_promo(message: types.Message, command: CommandObject, db):
    try:
        code, stars, uses = command.args.split()
        await db.pool.execute("INSERT INTO promocodes (code, stars, max_uses) VALUES ($1, $2, $3)", code.upper(), int(stars), int(uses))
        await message.answer(f"✅ Промокод {code.upper()} создан!")
    except:
        await message.answer("❌ Формат: /add_promo <КОД> <ЗВЕЗДЫ> <ЛИМИТ>")

# --- ОСТАЛЬНАЯ ЛОГИКА (БАЗА) ---
class DBManager:
    def __init__(self, pool):
        self.pool = pool
    async def get_user(self, uid):
        return await self.pool.fetchrow("SELECT * FROM users WHERE user_id = $1", uid)
    async def update_stars(self, uid, amount):
        await self.pool.execute("UPDATE users SET stars = stars + $1 WHERE user_id = $2", amount, uid)

# --- RENDER SERVER ---
async def health(request): return web.Response(text="OK")
async def start_server():
    app = web.Application()
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(os.environ.get("PORT", 8080))).start()

async def main():
    asyncio.create_task(start_server())
    pool = await asyncpg.create_pool(DATABASE_URL, ssl='require')
    db = DBManager(pool)
    dp["db"] = db
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
