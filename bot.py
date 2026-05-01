import os
import asyncio
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from database import Database
import asyncpg

# ТОКЕН И URL БЕРЕМ ИЗ RENDER (Environment Variables)
TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

bot = Bot(token=TOKEN)
dp = Dispatcher()

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

# --- ОБРАБОТЧИКИ ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    # Логика регистрации и проверки подписки на @Miflcards
    await message.answer("Добро пожаловать в **MIFL CARDS**! ⚽", reply_markup=main_menu())

@dp.callback_query(F.data == "shop")
async def open_shop(callback: types.CallbackQuery):
    text = (
        "**МАГАЗИН MIFL CARDS 🛒**\n\n"
        "👑 **VIP (1 день)** — 20,000 ⭐\n"
        "🟡 **One Pack** — 3,500 ⭐\n"
        "🟣 **Chase Pack** — 2,800 ⭐\n"
        "🟢 **Drop Pack** — 2,000 ⭐\n"
        "🔵 **Series Pack** — 1,200 ⭐\n"
        "⚪ **Stock Pack** — 500 ⭐"
    )
    # Кнопки покупки...
    await callback.message.edit_text(text, reply_markup=main_menu()) # Упрощено для примера

@dp.callback_query(F.data == "top_10")
async def show_top(callback: types.CallbackQuery):
    # Здесь логика запроса Топ-10 из БД
    await callback.message.answer("📊 Таблица лидеров...")

async def main():
    # Подключение к Render Postgres с SSL
    pool = await asyncpg.create_pool(DATABASE_URL, ssl='require')
    db = Database(pool)
    dp["db"] = db # Прокидываем базу в хендлеры
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
