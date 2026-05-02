import os
import asyncio
import io
import datetime
from datetime import datetime as dt, timedelta
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandObject
from aiogram.types import BufferedInputFile
from aiohttp import web
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# Импортируем оптимизированный генератор
from profile_generator import generate_profile_image
# Твой класс базы данных (убедись, что методы pool.fetchval и pool.execute работают)
from database import Database

# --- КОНФИГУРАЦИЯ ---
TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_IDS = [123456789] # Твой ID

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- ВСПОМОГАТЕЛЬНАЯ ЛОГИКА ---
# Обновленный конфиг редкостей: Stock=Зеленый🟢, Drop=Красный🔴
RARITY_CONFIG = {
    "One": {"icon": "🟡", "price": 3500},
    "Chase": {"icon": "🟣", "price": 2800},
    "Drop": {"icon": "🔴", "price": 2000},
    "Series": {"icon": "🔵", "price": 1200},
    "Stock": {"icon": "🟢", "price": 500}
}

# Кэш аватар для ускорения профиля (user_id -> {'content': bytes, 'expires': timestamp})
avatar_cache = {}

def main_reply_keyboard():
    kb = [
        [types.KeyboardButton(text="🎁 Получить Карту")],
        [types.KeyboardButton(text="⚽ Мини Игры"), types.KeyboardButton(text="🛒 Магазин")],
        [types.KeyboardButton(text="👤 Профиль"), types.KeyboardButton(text="👥 Рефералы")],
        [types.KeyboardButton(text="📊 ТОП-10")]
    ]
    return types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

# --- ВЕБ-СЕРВЕР ДЛЯ RENDER ---
async def handle(request): return web.Response(text="MIFL CARDS Bot is Running!")
async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

# --- ХЕНДЛЕРЫ ---

# 👤 ОПТИМИЗИРОВАННЫЙ ПРОФИЛЬ С КЭШЕМ И ТЕКСТОМ
@dp.message(F.text == "👤 Профиль")
async def handle_profile(message: types.Message, db: Database):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    
    # Loading message
    loading_msg = await message.answer("🔄 Загружаю футуристичный профиль...")

    try:
        # 1. Получаем реальные данные из БД ( safe with direct pool calls)
        u = await db.get_user(user_id)
        cards_count = await db.pool.fetchval("SELECT COUNT(*) FROM inventory WHERE user_id = $1", user_id)
        is_vip = await db.is_vip(user_id)
        status_txt = "VIP" if is_vip else "Обычный"

        # 2. Обработка Аватарки с Кэшированием (Ускоряет повторные нажатия)
        cached_ava = avatar_cache.get(user_id)
        ava_bytes = None
        
        # Если в кэше нет или протухла (Кэшируем на 5 минут)
        if not cached_ava or cached_ava['expires'] < dt.now().timestamp():
            photos = await bot.get_user_profile_photos(user_id, limit=1)
            if photos.total_count > 0:
                # Берем самое последнее фото, средний размер для скорости (индекс [1])
                photo = photos.photos[0][1] 
                file = await bot.get_file(photo.file_id)
                ava_bytes = await bot.download_file(file.file_path) # aiogram helper
                # Пишем в кэш
                avatar_cache[user_id] = {
                    'content': ava_bytes, 
                    'expires': dt.now().timestamp() + timedelta(minutes=5).total_seconds()
                }
            else:ava_bytes = None # Если авы нет, Pillow использует ui-avatars

        # Если кэш сработал, берем контент из кэша
        if cached_ava and not ava_bytes: ava_bytes = cached_ava['content']

        ava_buf = io.BytesIO(ava_bytes) if ava_bytes else None

        # 3. Генерируем графику ( Pillow оптимизирована, работает <0.1с)
        img_buf = await generate_profile_image(
            avatar_url=ava_buf if ava_buf else "default_avatar", #ui-avatars handling in generator
            nickname=username,
            stars=u['stars'],
            cards_count=cards_count,
            status=status_txt
        )

        # 4. Текстовое описание статистики (Full Markdown repeat)
        # Добавляем пробелы в баланс для красоты в тексте
        stars_txt = f"{u['stars']:,}".replace(",", " ")
        status_emoji = "👑" if is_vip else "👤"
        
        caption = (
            f"👤 **ТВОЙ ПРОФИЛЬ** (Graphics v2)\n\n"
            f"💰 **Баланс Звёзд:** `{stars_txt}` 🌟\n"
            f"🎴 **Количество Карт:** `{cards_count}` шт.\n"
            f"💎 **Статус:** `{status_txt}` {status_emoji}\n\n"
            f"📊 Ваша футуристичная игровая статистика в графическом и текстовом формате:"
        )

        photo_input = BufferedInputFile(img_buf.read(), filename="profile.png")
        await message.answer_photo(photo_input, caption=caption, reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="🎴 Моя коллекция", callback_data="my_collection")]
        ]), parse_mode="Markdown")

    except Exception as e:
        await message.answer(f"❌ Ошибка при генерации профиля: {e}")
    finally:
        # Удаляем loading
        await loading_msg.delete()

# 🛒 МАГАЗИН (ВОССТАНОВИЛИ ВСЕ ПАКИ)
@dp.message(F.text == "🛒 Магазин")
async def handle_shop(message: types.Message):
    kb = [
        [types.InlineKeyboardButton(text="🟡 One Pack — 3,500🌟", callback_data="buy_pack_One")],
        [types.InlineKeyboardButton(text="🟣 Chase Pack — 2,800🌟", callback_data="buy_pack_Chase")],
        [types.InlineKeyboardButton(text="🔴 Drop Pack — 2,000🌟", callback_data="buy_pack_Drop")], # Drop Red🔴
        [types.InlineKeyboardButton(text="🔵 Series Pack — 1,200🌟", callback_data="buy_pack_Series")],
        [types.InlineKeyboardButton(text="🟢 Stock Pack — 500🌟", callback_data="buy_pack_Stock")],   # Stock Green🟢
        [types.InlineKeyboardButton(text="👑 VIP (1 день) — 20,000🌟", callback_data="buy_vip")]
    ]
    markup = types.InlineKeyboardMarkup(inline_keyboard=kb)
    await message.answer("🛒 <b>МАГАЗИН MIFL CARDS</b>", reply_markup=markup, parse_mode="HTML")

# Оставшаяся логика (Мини Игры, Топ, Рефералы, Команды админа) не менялась.
# Запускаем...
async def main():
    asyncio.create_task(start_web_server())
    pool = await asyncpg.create_pool(DATABASE_URL, ssl='require')
    db = Database(pool)
    await db.create_tables()
    dp["db"] = db
    print("Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
