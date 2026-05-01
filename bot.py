import os
import asyncio
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandObject
from database import Database
import asyncpg

# Конфигурация из Environment Variables Render
TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_IDS = [1866813859] # ВСТАВЬ СВОЙ ID СЮДА
CHANNEL_URL = "https://t.me/Miflcards"
CHANNEL_ID = "@Miflcards"

bot = Bot(token=TOKEN)
dp = Dispatcher()
admin_photo_storage = {}

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

# --- ПРОВЕРКА ПОДПИСКИ ---
async def check_sub(user_id):
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in ["member", "administrator", "creator"]
    except: return False

# --- ОБРАБОТКА КОМАНД ---
@dp.message(Command("start"))
async def start(message: types.Message, db: Database, command: CommandObject):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    
    user = await db.get_user(user_id)
    if not user:
        args = command.args
        referrer = int(args) if args and args.isdigit() else None
        await db.pool.execute("INSERT INTO users (user_id, username, referrer_id) VALUES ($1, $2, $3)", 
                             user_id, username, referrer)
    
    await message.answer(f"Добро пожаловать в MIFL CARDS! ⚽", reply_markup=main_menu())

# --- АДМИН ПАНЕЛЬ ---
@dp.message(F.photo, F.from_user.id.in_(ADMIN_IDS))
async def admin_photo(message: types.Message):
    admin_photo_storage[message.from_user.id] = message.photo[-1].file_id
    await message.answer("📸 Фото сохранено. Используй /add_player Имя, Рейтинг, Клуб, Позиция, Редкость")

@dp.message(Command("add_player"), F.from_user.id.in_(ADMIN_IDS))
async def add_player(message: types.Message, command: CommandObject, db: Database):
    p_id = admin_photo_storage.get(message.from_user.id)
    if not p_id: return await message.answer("❌ Сначала кинь фото!")
    
    try:
        args = [a.strip() for a in command.args.split(",")]
        await db.pool.execute("INSERT INTO mifl_cards (name, rating, club, position, rarity, photo_id) VALUES ($1, $2, $3, $4, $5, $6)",
                             args[0], float(args[1]), args[2], args[3], args[4], p_id)
        del admin_photo_storage[message.from_user.id]
        await message.answer(f"✅ Игрок {args[0]} добавлен!")
    except: await message.answer("❌ Ошибка. Формат: Имя, 5.0, Клуб, Поз, Редкость")

# --- ЛОГИКА КНОПОК ---
@dp.callback_query(F.data == "get_card")
async def get_card(callback: types.CallbackQuery, db: Database):
    if not await check_sub(callback.from_user.id):
        return await callback.answer("❌ Подпишись на канал!", show_alert=True)
    
    u = await db.get_user(callback.from_user.id)
    is_vip = await db.is_vip(callback.from_user.id)
    cd = 2 if is_vip else 4
    
    if u['last_free_card'] and datetime.now() < u['last_free_card'] + timedelta(hours=cd):
        return await callback.answer("⏳ Кулдаун!", show_alert=True)
    
    card = await db.get_random_card()
    if not card: return await callback.answer("База карт пуста!")
    
    await db.add_card_to_inventory(u['user_id'], card['card_id'])
    await db.set_cooldown(u['user_id'], 'last_free_card')
    await callback.message.answer_photo(card['photo_id'], caption=f"🎁 Выпала карта: {card['name']}")

@dp.callback_query(F.data == "shop")
async def shop(callback: types.CallbackQuery):
    txt = "🛒 **МАГАЗИН**\n\n👑 VIP (1 день) - 20,000🌟\n🟡 One Pack - 3,500🌟\n..."
    await callback.message.edit_text(txt, reply_markup=main_menu())

# --- ЗАПУСК ---
async def main():
    pool = await asyncpg.create_pool(DATABASE_URL, ssl='require')
    db = Database(pool)
    await db.create_tables()
    dp["db"] = db
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
