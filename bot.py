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
CHANNEL_ID = "@Miflcards"
ADMIN_ID = 1866813859

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Импорт твоего генератора
try:
    from profile_generator import generate_profile_image
except ImportError:
    async def generate_profile_image(*args): return None

# --- СОСТОЯНИЯ ---
class Form(StatesGroup):
    add_player_photo = State()
    add_player_data = State()
    guess_bet = State()
    guess_playing = State()

# --- КЛАВИАТУРА ---
def main_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🎁 Получить Карту"), KeyboardButton(text="📅 Бонус")],
        [KeyboardButton(text="⚽ Мини Игры"), KeyboardButton(text="🛒 Магазин")],
        [KeyboardButton(text="🔄 Трейд"), KeyboardButton(text="🏷 Промокод")],
        [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="👥 Рефералы")], # Добавил рефералов в кнопки
        [KeyboardButton(text="📊 ТОП-10")]
    ], resize_keyboard=True)

# --- ЛОГИКА ПРОФИЛЯ (ТА САМАЯ СИСТЕМА) ---
@dp.message(F.text == "👤 Профиль")
async def view_profile(message: types.Message, state: FSMContext, db):
    await state.clear()
    u = await db.get_user(message.from_user.id)
    cnt = await db.pool.fetchval("SELECT COUNT(*) FROM inventory WHERE user_id = $1", message.from_user.id)
    
    is_vip = u.get('vip_until') and u['vip_until'] > datetime.now()
    st = "VIP 💎" if is_vip else "Обычный 👤"
    
    caption = (
        f"👤 <b>Профиль: {u['username']}</b>\n"
        f"💰 Баланс: {u['stars']:,} 🌟\n"
        f"🎴 Карт: {cnt}\n"
        f"👑 Статус: {st}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎴 Моя Коллекция", callback_data="view_col_0")]])

    avatar_bytes = None
    try:
        photos = await bot.get_user_profile_photos(message.from_user.id, limit=1)
        if photos.total_count > 0:
            file = await bot.get_file(photos.photos[0][-1].file_id)
            # Вот она, твоя рабочая схема скачивания:
            downloaded = await bot.download_file(file.file_path)
            avatar_bytes = downloaded.read()

        # Генерация через твой скрипт
        img_io = await generate_profile_image(avatar_bytes, u['username'], u['stars'], cnt, st)
        
        if img_io:
            # И твоя рабочая схема отправки:
            return await message.answer_photo(
                BufferedInputFile(img_io.read(), filename="p.png"), 
                caption=caption, 
                reply_markup=kb, 
                parse_mode="HTML"
            )
    except Exception as e:
        logging.error(f"Ошибка системы фото: {e}")
    
    # Фолбэк на текст, если генератор отвалился
    await message.answer(caption, reply_markup=kb, parse_mode="HTML")

# --- ТОП-10 (ВОССТАНОВЛЕНО) ---
@dp.message(F.text == "📊 ТОП-10")
async def leaderboard(message: types.Message, db):
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
        "Приглашай друзей и получай <b>5 000 🌟</b> за каждого!\n\n"
        f"Твоя ссылка:\n<code>{link}</code>"
    )
    await message.answer(text, parse_mode="HTML")

# --- КОМАНДА /START (С РЕФЕРАЛАМИ) ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, command: CommandObject, db):
    # Логика рефералки
    ref_id = command.args
    if ref_id and ref_id.isdigit() and int(ref_id) != message.from_user.id:
        # Проверяем, новый ли это юзер
        exists = await db.pool.fetchval("SELECT 1 FROM users WHERE user_id = $1", message.from_user.id)
        if not exists:
            await db.update_stars(int(ref_id), 5000)
            try:
                await bot.send_message(int(ref_id), "🎉 Твой друг зашел в бота! Тебе начислено +5000 🌟")
            except:
                pass

    user = await db.get_user(message.from_user.id, message.from_user.username or message.from_user.first_name)
    await message.answer(f"⚽ Привет, {user['username']}! Ты зашел в <b>Mifl Cards</b>.", reply_markup=main_kb(), parse_mode="HTML")

# --- ХЕНДЛЕРЫ ДЛЯ ПОДДЕРЖКИ РАБОТЫ НА RENDER ---
async def handle(r):
    return web.Response(text="Bot is running!")

async def main():
    # Запуск микро-сервера для Render
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(os.environ.get("PORT", 8080))).start()

    # Инициализация БД
    pool = await asyncpg.create_pool(DATABASE_URL, ssl='require')
    
    # Я использую твой класс Database (или DBManager), который уже есть в твоем проекте
    # Предполагаем, что он импортирован из твоего файла database.py
    from database import Database 
    db = Database(pool)
    await db.create_tables() # Создаем таблицы если их нет
    
    dp["db"] = db # Прокидываем db в хендлеры

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
