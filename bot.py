import os
import asyncio
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandObject
from database import Database
import asyncpg

# Данные из окружения Render
TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_IDS = [1866813859]  # ЗАМЕНИ НА СВОЙ ID

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Временное хранилище для фото админов {admin_id: file_id}
admin_photo_storage = {}

# --- ГЛАВНОЕ МЕНЮ ---
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

# --- АДМИНСКАЯ ЛОГИКА ---

# 1. Сначала админ кидает фото
@dp.message(F.photo, F.from_user.id.in_(ADMIN_IDS))
async def collect_photo(message: types.Message):
    photo_id = message.photo[-1].file_id
    admin_photo_storage[message.from_user.id] = photo_id
    await message.answer(
        "📸 Фото запомнил!\n"
        "Теперь введи данные игрока командой:\n"
        "`/add_player Имя, Рейтинг, Клуб, Позиция, Редкость`",
        parse_mode="Markdown"
    )

# 2. Потом админ вводит команду с данными
@dp.message(Command("add_player"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_add_player(message: types.Message, command: CommandObject, db: Database):
    admin_id = message.from_user.id
    
    # Проверяем, есть ли фото в памяти
    if admin_id not in admin_photo_storage:
        return await message.answer("❌ Сначала отправь боту фото будущей карты!")

    if not command.args:
        return await message.answer("❌ Введи данные через запятую!\nПример: `/add_player Месси, 5.0, Интер Майами, ПФА, One`", parse_mode="Markdown")

    try:
        # Парсим аргументы (разделение по запятой)
        args = [arg.strip() for arg in command.args.split(",")]
        if len(args) < 5:
            return await message.answer("❌ Недостаточно данных! Нужно 5 параметров через запятую.")

        name, rating, club, position, rarity = args
        photo_id = admin_photo_storage[admin_id]

        # Сохраняем в базу
        await db.pool.execute(
            "INSERT INTO mifl_cards (name, rating, club, position, rarity, photo_id) VALUES ($1, $2, $3, $4, $5, $6)",
            name, float(rating), club, position, rarity, photo_id
        )

        # Очищаем временное хранилище
        del admin_photo_storage[admin_id]
        
        await message.answer(f"✅ Карта **{name}** успешно создана!", parse_mode="Markdown")

    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

# 3. Сброс прогресса (админ)
@dp.message(Command("reset_progress"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_reset(message: types.Message, command: CommandObject, db: Database):
    if not command.args:
        return await message.answer("Укажите ID: `/reset_progress 12345`", parse_mode="Markdown")
    target_id = int(command.args)
    await db.pool.execute("DELETE FROM inventory WHERE user_id = $1", target_id)
    await db.pool.execute("UPDATE users SET stars = 500 WHERE user_id = $1", target_id)
    await message.answer(f"🧹 Прогресс игрока {target_id} сброшен.")

# --- БАЗОВЫЕ ХЕНДЛЕРЫ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, db: Database):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    await db.pool.execute(
        "INSERT INTO users (user_id, username) VALUES ($1, $2) ON CONFLICT DO NOTHING",
        user_id, username
    )
    await message.answer(f"Добро пожаловать в MIFL CARDS, {username}! ⚽", reply_markup=main_menu())

async def main():
    pool = await asyncpg.create_pool(DATABASE_URL, ssl='require')
    db = Database(pool)
    await db.create_tables()
    dp["db"] = db
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
