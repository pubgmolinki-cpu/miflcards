import os
import asyncio
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandObject
from database import Database
import asyncpg
from aiohttp import web

# --- КОНФИГУРАЦИЯ ---
TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_IDS = [1866813859] # ЗАМЕНИ НА СВОЙ ID

bot = Bot(token=TOKEN)
dp = Dispatcher()
admin_photo_storage = {}

# --- ВЕБ-СЕРВЕР ДЛЯ RENDER ---
async def handle(request):
    return web.Response(text="MIFL CARDS is Running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

# --- ПОСТОЯННОЕ МЕНЮ (Reply Keyboard) ---
def main_reply_keyboard():
    # resize_keyboard=True делает кнопки маленькими и удобными
    # input_field_placeholder — текст в поле ввода
    kb = [
        [types.KeyboardButton(text="🎁 Получить Карту")],
        [types.KeyboardButton(text="🧩 Угадайка"), types.KeyboardButton(text="🛒 Магазин")],
        [types.KeyboardButton(text="👤 Профиль"), types.KeyboardButton(text="👥 Рефералы")],
        [types.KeyboardButton(text="📊 ТОП-10")]
    ]
    return types.ReplyKeyboardMarkup(
        keyboard=kb, 
        resize_keyboard=True, 
        input_field_placeholder="Выберите раздел..."
    )

# --- ОБРАБОТЧИКИ ТЕКСТОВЫХ КНОПОК ---

@dp.message(F.text == "🎁 Получить Карту")
async def handle_get_card(message: types.Message, db: Database):
    user_id = message.from_user.id
    u = await db.get_user(user_id)
    is_vip = await db.is_vip(user_id)
    cd = 2 if is_vip else 4
    
    if u['last_free_card'] and datetime.now() < u['last_free_card'] + timedelta(hours=cd):
        diff = (u['last_free_card'] + timedelta(hours=cd)) - datetime.now()
        mins = int(diff.total_seconds() // 60)
        return await message.answer(f"⏳ Еще не время! Нужно подождать {mins} мин.")

    card = await db.get_random_card()
    if not card: return await message.answer("❌ Карт в базе нет.")
    
    await db.add_card_to_inventory(user_id, card['card_id'])
    await db.set_cooldown(user_id, 'last_free_card')
    
    await message.answer_photo(
        card['photo_id'], 
        caption=f"🎁 Твоя карта: **\nРедкость: {card['rarity']}",
        parse_mode="Markdown"
    )

@dp.message(F.text == "👤 Профиль")
async def handle_profile(message: types.Message, db: Database):
    u = await db.get_user(message.from_user.id)
    is_v = "👑 VIP" if await db.is_vip(message.from_user.id) else "👤 Обычный"
    txt = f"👤 **ПРОФИЛЬ**\n\n💰 Звезды: {u['stars']} 🌟\n💎 Статус: {is_v}"
    await message.answer(txt, parse_mode="Markdown")

@dp.message(F.text == "🛒 Магазин")
async def handle_shop(message: types.Message):
    txt = (
        "🛒 **МАГАЗИН MIFL CARDS**\n\n"
        "👑 VIP (1 день) — 20,000🌟\n"
        "🟡 One Pack — 3,500🌟\n"
        "🟣 Chase Pack — 2,800🌟\n"
        "🟢 Drop Pack — 2,000🌟\n"
        "🔵 Series Pack — 1,200🌟\n"
        "⚪ Stock Pack — 500🌟"
    )
    await message.answer(txt, parse_mode="Markdown")

# --- АДМИНКА ---

@dp.message(F.photo, F.from_user.id.in_(ADMIN_IDS))
async def admin_photo(message: types.Message):
    admin_photo_storage[message.from_user.id] = message.photo[-1].file_id
    await message.answer("📸 Фото принято! Жду данные через /add_player")

@dp.message(Command("add_player"), F.from_user.id.in_(ADMIN_IDS))
async def add_player(message: types.Message, command: CommandObject, db: Database):
    p_id = admin_photo_storage.get(message.from_user.id)
    if not p_id: return await message.answer("❌ Сначала фото!")
    try:
        args = [a.strip() for a in command.args.split(",")]
        await db.pool.execute("INSERT INTO mifl_cards (name, rating, club, position, rarity, photo_id) VALUES ($1, $2, $3, $4, $5, $6)",
                             args[0], float(args[1]), args[2], args[3], args[4], p_id)
        del admin_photo_storage[message.from_user.id]
        await message.answer(f"✅ Карта {args[0]} добавлена!")
    except: await message.answer("❌ Ошибка в формате.")

# --- СТАРТ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, db: Database):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    await db.pool.execute(
        "INSERT INTO users (user_id, username) VALUES ($1, $2) ON CONFLICT DO NOTHING",
        user_id, username
    )
    # Отправляем меню, которое будет висеть всегда
    await message.answer(
        f"⚽ Привет, {username}! Ты в MIFL CARDS.\nИспользуй меню снизу для игры.", 
        reply_markup=main_reply_keyboard()
    )

async def main():
    asyncio.create_task(start_web_server())
    pool = await asyncpg.create_pool(DATABASE_URL, ssl='require')
    db = Database(pool)
    await db.create_tables()
    dp["db"] = db
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
