import os
import asyncio
import re
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandObject
from database import Database
import asyncpg
from aiohttp import web

# --- КОНФИГУРАЦИЯ ---
TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
# Впиши сюда свой ID, чтобы команды работали
ADMIN_IDS = [123456789] 

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Временное хранилище для фото админов
admin_photo_storage = {}

# --- ВЕБ-СЕРВЕР ДЛЯ RENDER (чтобы не падал по таймауту портов) ---
async def handle(request):
    return web.Response(text="MIFL CARDS Bot is Running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

# --- КЛАВИАТУРЫ ---
def main_menu():
    kb = [
        [types.InlineKeyboardButton(text="Получить Карту 🎁", callback_data="get_card")],
        [types.InlineKeyboardButton(text="Мини Игры ⚽", callback_data="games"),
         types.InlineKeyboardButton(text="Магазин 🛒", callback_data="shop")],
        [types.InlineKeyboardButton(text="Профиль 👤", callback_data="profile"),
         types.InlineKeyboardButton(text="Реферальная система 👥", callback_data="refs")],
        [types.InlineKeyboardButton(text="Топ-10 📊", callback_data="top_10")]
    ]
    return types.InlineKeyboardMarkup(inline_keyboard=kb)

# --- АДМИНСКИЕ КОМАНДЫ ---

@dp.message(F.photo, F.from_user.id.in_(ADMIN_IDS))
async def admin_photo(message: types.Message):
    admin_photo_storage[message.from_user.id] = message.photo[-1].file_id
    await message.answer("📸 Фото запомнил! Теперь введи:\n`/add_player Имя, Рейтинг, Клуб, Позиция, Редкость`", parse_mode="Markdown")

@dp.message(Command("add_player"), F.from_user.id.in_(ADMIN_IDS))
async def add_player(message: types.Message, command: CommandObject, db: Database):
    p_id = admin_photo_storage.get(message.from_user.id)
    if not p_id: 
        return await message.answer("❌ Сначала отправь фото игрока!")
    
    if not command.args:
        return await message.answer("❌ Формат: `/add_player Месси, 5.0, Интер, ПФА, One`", parse_mode="Markdown")

    try:
        args = [a.strip() for a in command.args.split(",")]
        await db.pool.execute(
            "INSERT INTO mifl_cards (name, rating, club, position, rarity, photo_id) VALUES ($1, $2, $3, $4, $5, $6)",
            args[0], float(args[1]), args[2], args[3], args[4], p_id
        )
        del admin_photo_storage[message.from_user.id]
        await message.answer(f"✅ Игрок **{args[0]} успешно добавлен!", parse_mode="Markdown")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@dp.message(Command("reset_progress"), F.from_user.id.in_(ADMIN_IDS))
async def reset_user(message: types.Message, command: CommandObject, db: Database):
    if not command.args: return
    uid = int(command.args)
    await db.pool.execute("DELETE FROM inventory WHERE user_id = $1", uid)
    await db.pool.execute("UPDATE users SET stars = 500 WHERE user_id = $1", uid)
    await message.answer(f"🧹 Прогресс {uid} сброшен.")

# --- ОСНОВНЫЕ ФУНКЦИИ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, db: Database):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    await db.pool.execute(
        "INSERT INTO users (user_id, username) VALUES ($1, $2) ON CONFLICT DO NOTHING",
        user_id, username
    )
    await message.answer(f"⚽ Привет, {username}! Ты в MIFL CARDS.", reply_markup=main_menu())

@dp.callback_query(F.data == "get_card")
async def get_card(callback: types.CallbackQuery, db: Database):
    user_id = callback.from_user.id
    u = await db.get_user(user_id)
    
    is_vip = await db.is_vip(user_id)
    cd = 2 if is_vip else 4
    
    if u['last_free_card'] and datetime.now() < u['last_free_card'] + timedelta(hours=cd):
        return await callback.answer("⏳ Рано! Отдыхай.", show_alert=True)
    
    card = await db.get_random_card()
    if not card:
        return await callback.answer("❌ В базе пока нет карт!", show_alert=True)
    
    await db.add_card_to_inventory(user_id, card['card_id'])
    await db.set_cooldown(user_id, 'last_free_card')
    
    await callback.message.answer_photo(
        card['photo_id'], 
        caption=f"🎁 Тебе выпал: **\nРедкость: {card['rarity']}",
        parse_mode="Markdown"
    )

@dp.callback_query(F.data == "profile")
async def show_profile(callback: types.CallbackQuery, db: Database):
    u = await db.get_user(callback.from_user.id)
    is_v = "👑 VIP" if await db.is_vip(callback.from_user.id) else "👤 Обычный"
    txt = f"👤 **ПРОФИЛЬ**\n\n💰 Звезды: {u['stars']} 🌟\n💎 Статус: {is_v}"
    await callback.message.edit_text(txt, reply_markup=main_menu())

# --- ЗАПУСК ---
async def main():
    # Запускаем веб-заглушку для Render
    asyncio.create_task(start_web_server())
    
    pool = await asyncpg.create_pool(DATABASE_URL, ssl='require')
    db = Database(pool)
    await db.create_tables()
    
    dp["db"] = db
    print("🚀 Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Бот остановлен")
