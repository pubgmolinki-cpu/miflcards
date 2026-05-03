import os
import asyncio
import io
import random
import asyncpg
from datetime import datetime, timedelta # Исправлено: добавлен timedelta
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from aiogram.exceptions import TelegramBadRequest
from aiohttp import web # Добавлено для Render

from database import Database
from profile_generator import generate_profile_image

# --- КОНФИГУРАЦИЯ ---
TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
CHANNEL_ID = "@Miflcards"
CHANNEL_URL = "https://t.me/Miflcards"

bot = Bot(token=TOKEN)
dp = Dispatcher()

RARITY_CONFIG = {
    "One": {"icon": "🟡", "price": 3500, "coef": 2.5},
    "Chase": {"icon": "🟣", "price": 2800, "coef": 2.1},
    "Drop": {"icon": "🔴", "price": 2000, "coef": 1.8},
    "Series": {"icon": "🔵", "price": 1200, "coef": 1.5},
    "Stock": {"icon": "🟢", "price": 500, "coef": 1.2}
}

class GuessGame(StatesGroup):
    bet = State()

# --- ВЕБ-СЕРВЕР ДЛЯ RENDER (Чтобы не было Port Scan Timeout) ---
async def handle_health(request):
    return web.Response(text="Bot is alive!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    # Render сам подставляет PORT, если его нет — используем 8080
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

async def is_subscribed(user_id: int):
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in ["member", "administrator", "creator"]
    except:
        return False

def main_kb():
    kb = [
        [KeyboardButton(text="🎁 Получить Карту")],
        [KeyboardButton(text="⚽ Мини Игры"), KeyboardButton(text="🛒 Магазин")],
        [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="👥 Рефералы")],
        [KeyboardButton(text="📊 ТОП-10")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

# --- МИДДЛВАРЬ ДЛЯ ПОДПИСКИ ---
@dp.message.middleware()
async def subscription_middleware(handler, event: types.Message, data):
    if not event.text: return await handler(event, data)
    if event.text.startswith("/start") or await is_subscribed(event.from_user.id):
        return await handler(event, data)
    
    kb = [[InlineKeyboardButton(text="🔗 Подписаться на Miflcards", url=CHANNEL_URL)]]
    await event.answer(
        "⚠️ **Доступ ограничен!**\n\nЧтобы пользоваться ботом и получать карты, подпишись на наш основной канал.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb),
        parse_mode="Markdown"
    )

# --- ХЕНДЛЕРЫ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, command: CommandObject, db: Database, state: FSMContext):
    await state.clear()
    ref_id = int(command.args) if command.args and command.args.isdigit() else None
    
    await db.pool.execute(
        "INSERT INTO users (user_id, username, referrer_id) VALUES ($1, $2, $3) "
        "ON CONFLICT (user_id) DO UPDATE SET username = $2",
        message.from_user.id, message.from_user.username or message.from_user.first_name, ref_id
    )
    
    if ref_id and ref_id != message.from_user.id:
        await db.update_stars(ref_id, 5000)
        try: await bot.send_message(ref_id, "🎁 По вашей ссылке зашёл новый игрок! Вам начислено `5 000` 🌟", parse_mode="Markdown")
        except: pass

    await message.answer("⚽ **Добро пожаловать в MIfl Cards!**", reply_markup=main_kb(), parse_mode="Markdown")

@dp.message(F.text == "👤 Профиль")
async def handle_profile(message: types.Message, db: Database, state: FSMContext):
    await state.clear()
    u = await db.get_user(message.from_user.id)
    count = await db.pool.fetchval("SELECT COUNT(*) FROM inventory WHERE user_id = $1", message.from_user.id)
    
    status_text = "Обычный"
    if u.get('vip_until') and u['vip_until'] > datetime.now():
        rem = u['vip_until'] - datetime.now()
        status_text = f"VIP ({rem.days}д. {rem.seconds // 3600}ч.)"

    photos = await bot.get_user_profile_photos(message.from_user.id, limit=1)
    ava_bytes = None
    if photos.total_count > 0:
        file = await bot.get_file(photos.photos[0][0].file_id)
        ava_bytes = (await bot.download_file(file.file_path)).read()

    img_buf = await generate_profile_image(ava_bytes, u['username'], u['stars'], count, status_text)
    
    caption = (f"👤 **ПРОФИЛЬ: {u['username']}**\n"
               f"💰 Баланс: `{u['stars']:,}` 🌟\n"
               f"👑 Статус: `{status_text}`").replace(",", " ")
    
    kb = [[InlineKeyboardButton(text="🎴 Моя Коллекция", callback_data="my_col_0")]]
    await message.answer_photo(BufferedInputFile(img_buf.read(), filename="p.png"), caption=caption, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("my_col_"))
async def show_collection(callback: types.CallbackQuery, db: Database):
    page = int(callback.data.split("_")[2])
    cards = await db.pool.fetch(
        "SELECT c.* FROM mifl_cards c JOIN inventory i ON c.card_id = i.card_id "
        "WHERE i.user_id = $1 ORDER BY c.rating DESC LIMIT 5 OFFSET $2", callback.from_user.id, page * 5
    )
    
    if not cards and page == 0: return await callback.answer("Пусто!", show_alert=True)
    
    txt = "🎴 **ТВОЯ КОЛЛЕКЦИЯ:**\n\n" + "\n".join([f"• {c['name']} (⭐{c['rating']})" for c in cards])
    nav = []
    if page > 0: nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"my_col_{page-1}"))
    if len(cards) == 5: nav.append(InlineKeyboardButton(text="➡️", callback_data=f"my_col_{page+1}"))
    
    await callback.message.edit_caption(caption=txt, reply_markup=InlineKeyboardMarkup(inline_keyboard=[nav] if nav else []), parse_mode="Markdown")

@dp.message(F.text == "👥 Рефералы")
async def refs(message: types.Message, state: FSMContext):
    await state.clear()
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start={message.from_user.id}"
    await message.answer(f"👥 **ПРИГЛАШАЙ ДРУЗЕЙ!**\nБонус: `5 000` 🌟 за каждого.\n\n🔗 Твоя ссылка:\n`{link}`", parse_mode="Markdown")

# --- УГАДАЙКА ---
@dp.message(F.text == "⚽ Мини Игры")
async def games_menu(message: types.Message, state: FSMContext):
    await state.clear()
    kb = [[InlineKeyboardButton(text="🧩 Угадай игрока", callback_data="play_guess")]]
    await message.answer("⚽ **Выберите игру:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data == "play_guess")
async def guess_start(callback: types.CallbackQuery, state: FSMContext, db: Database):
    await state.clear()
    await callback.message.answer("🧩 Введите ставку (от 100 🌟):")
    await state.set_state(GuessGame.bet)

@dp.message(GuessGame.bet)
async def guess_bet(message: types.Message, state: FSMContext, db: Database):
    if not message.text.isdigit(): return await message.answer("Числом, пожалуйста!")
    bet = int(message.text)
    u = await db.get_user(message.from_user.id)
    if bet < 100 or bet > u['stars']: return await message.answer("Мало звёзд!")

    card = await db.get_random_card()
    wrong = await db.pool.fetch("SELECT name FROM mifl_cards WHERE name != $1 ORDER BY RANDOM() LIMIT 3", card['name'])
    opts = [card['name']] + [r['name'] for r in wrong]
    random.shuffle(opts)
    
    await state.update_data(correct=card['name'], bet=bet, cid=card['card_id'], opts=opts)
    kb = [[InlineKeyboardButton(text=o, callback_data=f"gans_{i}")] for i, o in enumerate(opts)]
    
    await db.update_stars(message.from_user.id, -bet)
    await message.answer(f"🧩 **КТО ЭТО?**\n⭐ Рейтинг: `{card['rating']}`\n📍 Позиция: `{card['position']}`", 
                         reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("gans_"))
async def guess_check(callback: types.CallbackQuery, state: FSMContext, db: Database):
    data = await state.get_data()
    if not data: return await callback.answer("Ошибка сессии")
    
    chosen = data['opts'][int(callback.data.split("_")[1])]
    card = await db.pool.fetchrow("SELECT * FROM mifl_cards WHERE card_id = $1", data['cid'])
    
    if chosen == data['correct']:
        win = int(data['bet'] * RARITY_CONFIG.get(card['rarity'], {"coef": 1.5})['coef'])
        await db.update_stars(callback.from_user.id, win)
        await callback.message.answer(f"✅ **ВЕРНО!** +{win} 🌟")
    else:
        await callback.message.answer(f"❌ **Мимо!** Это был {data['correct']}")
    
    await state.clear()
    await callback.message.delete()

# --- ЗАПУСК ---
async def main():
    # Запускаем веб-сервер в фоне для Render
    asyncio.create_task(start_web_server())
    
    pool = await asyncpg.create_pool(DATABASE_URL, ssl='require')
    db = Database(pool)
    await db.create_tables()
    dp["db"] = db
    
    # Удаляем вебхук (на всякий случай) и запускаем поллинг
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
