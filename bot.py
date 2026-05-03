import os
import asyncio
import io
import random
import asyncpg
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from aiohttp import web

from database import Database
from profile_generator import generate_profile_image

# --- КОНФИГУРАЦИЯ ---
TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
CHANNEL_ID = "@Miflcards"
CHANNEL_URL = "https://t.me/Miflcards"
ADMIN_IDS = [1866813859] # Впиши сюда свой ID

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Настройки редкостей и коэффициентов для Угадайки
RARITY_CONFIG = {
    "One": {"icon": "🟡", "name": "One", "price": 3500, "coef": 2.5, "reward": 10000},
    "Chase": {"icon": "🟣", "name": "Chase", "price": 2800, "coef": 2.1, "reward": 5000},
    "Drop": {"icon": "🔴", "name": "Drop", "price": 2000, "coef": 1.8, "reward": 2500},
    "Series": {"icon": "🔵", "name": "Series", "price": 1200, "coef": 1.5, "reward": 1250},
    "Stock": {"icon": "🟢", "name": "Stock", "price": 500, "coef": 1.2, "reward": 500}
}

class AddPlayer(StatesGroup):
    waiting_for_photo = State()
    waiting_for_details = State()

class GuessGame(StatesGroup):
    bet = State()

# --- ВЕБ-СЕРВЕР ДЛЯ RENDER ---
async def handle_health(request):
    return web.Response(text="Bot is running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
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

def format_card_caption(card):
    cfg = RARITY_CONFIG.get(card['rarity'], {"icon": "⚪", "reward": 0})
    return (
        f"👤 {card['name']}\n"
        f"📊 Рейтинг: {card['rating']}\n"
        f"🏢 Клуб: {card['club']}\n"
        f"📍 Позиция: {card['position']}\n"
        f"✨ Редкость: {cfg['icon']} {card['rarity']}\n"
        f"💰 Награда: +{cfg['reward']} 🌟"
    )

# --- MIDDLEWARE ДЛЯ ПРОВЕРКИ ПОДПИСКИ ---
@dp.message.middleware()
async def msg_sub_middleware(handler, event: types.Message, data):
    if event.text and event.text.startswith("/start"):
        return await handler(event, data)
    if await is_subscribed(event.from_user.id):
        return await handler(event, data)
    
    kb = [[InlineKeyboardButton(text="🔗 Подписаться на Miflcards", url=CHANNEL_URL)]]
    await event.answer(
        "⚠️ Доступ ограничен!\n\nЧтобы пользоваться ботом и получать карты, подпишись на наш основной канал.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
    )

@dp.callback_query.middleware()
async def cb_sub_middleware(handler, event: types.CallbackQuery, data):
    if await is_subscribed(event.from_user.id):
        return await handler(event, data)
    await event.answer("⚠️ Сначала подпишись на канал!", show_alert=True)

# --- АДМИН-КОМАНДЫ ---

@dp.message(Command("addcard"))
async def admin_add_card_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    await state.clear()
    await message.answer("🛠 Отправьте фото карточки:")
    await state.set_state(AddPlayer.waiting_for_photo)

@dp.message(AddPlayer.waiting_for_photo, F.photo)
async def admin_get_photo(message: types.Message, state: FSMContext):
    await state.update_data(photo_id=message.photo[-1].file_id)
    await message.answer("✅ Принято! Теперь введи через запятую:\nИмя, Рейтинг, Позиция, Клуб, Редкость\n\nПример: Messi, 99, RW, Miami, One")
    await state.set_state(AddPlayer.waiting_for_details)

@dp.message(AddPlayer.waiting_for_details, F.text)
async def admin_get_details(message: types.Message, state: FSMContext, db: Database):
    parts = [p.strip() for p in message.text.split(",")]
    if len(parts) != 5: return await message.answer("❌ Нужно 5 параметров через запятую!")
    
    name, rating, pos, club, rarity = parts
    photo_id = (await state.get_data())['photo_id']
    
    await db.pool.execute(
        "INSERT INTO mifl_cards (name, rating, position, club, rarity, photo_id) VALUES ($1, $2, $3, $4, $5, $6)",
        name, float(rating), pos, club, rarity, photo_id
    )
    await message.answer(f"✅ Карточка {name} успешно добавлена!")
    await state.clear()

# --- ХЕНДЛЕРЫ КНОПОК ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, command: CommandObject, db: Database, state: FSMContext):
    await state.clear()
    ref_id = int(command.args) if command.args and command.args.isdigit() else None
    await db.pool.execute(
        "INSERT INTO users (user_id, username, referrer_id) VALUES ($1, $2, $3) ON CONFLICT (user_id) DO UPDATE SET username = $2",
        message.from_user.id, message.from_user.username or message.from_user.first_name, ref_id
    )
    if ref_id and ref_id != message.from_user.id:
        await db.update_stars(ref_id, 5000)
    await message.answer("⚽ Добро пожаловать в MIfl Cards!", reply_markup=main_kb())

@dp.message(F.text == "👤 Профиль")
async def handle_profile(message: types.Message, db: Database, state: FSMContext):
    await state.clear()
    u = await db.get_user(message.from_user.id)
    count = await db.pool.fetchval("SELECT COUNT(*) FROM inventory WHERE user_id = $1", message.from_user.id)
    
    status_text = "Обычный"
    if u.get('vip_until') and u['vip_until'] > datetime.now():
        rem = u['vip_until'] - datetime.now()
        status_text = f"VIP ({rem.days}д. {rem.seconds // 3600}ч.)" if rem.days > 0 else f"VIP ({rem.seconds // 3600}ч.)"

    photos = await bot.get_user_profile_photos(message.from_user.id, limit=1)
    ava = (await bot.download_file((await bot.get_file(photos.photos[0][0].file_id)).file_path)).read() if photos.total_count > 0 else None
    
    img_buf = await generate_profile_image(ava, u['username'], u['stars'], count, status_text)
    caption = (f"👤 ПРОФИЛЬ: {u['username']}\n💰 Баланс: {u['stars']:,} 🌟\n🎴 Коллекция: {count} шт.\n👑 Статус: {status_text}").replace(",", " ")
    
    kb = [[InlineKeyboardButton(text="🎴 Моя Коллекция", callback_data="my_col_0")]]
    await message.answer_photo(BufferedInputFile(img_buf.read(), filename="p.png"), caption=caption, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("my_col_"))
async def show_collection(callback: types.CallbackQuery, db: Database):
    page = int(callback.data.split("_")[2])
    cards = await db.pool.fetch("SELECT c.* FROM mifl_cards c JOIN inventory i ON c.card_id = i.card_id WHERE i.user_id = $1 ORDER BY c.rating DESC LIMIT 5 OFFSET $2", callback.from_user.id, page * 5)
    if not cards and page == 0: return await callback.answer("Пусто!", show_alert=True)
    
    txt = "🎴 ТВОЯ КОЛЛЕКЦИЯ:\n\n" + "\n".join([f"• {c['name']} (⭐{c['rating']})" for c in cards])
    nav = []
    if page > 0: nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"my_col_{page-1}"))
    if len(cards) == 5: nav.append(InlineKeyboardButton(text="➡️", callback_data=f"my_col_{page+1}"))
    await callback.message.edit_caption(caption=txt, reply_markup=InlineKeyboardMarkup(inline_keyboard=[nav] if nav else []))

# --- ПАК ОПЕНИНГ (ПОЛУЧИТЬ КАРТУ) ---
@dp.message(F.text == "🎁 Получить Карту")
async def get_free_card(message: types.Message, db: Database, state: FSMContext):
    await state.clear()
    u = await db.get_user(message.from_user.id)
    cd = 2 if (u.get('vip_until') and u['vip_until'] > datetime.now()) else 4
    if u.get('last_drop') and datetime.now() < u['last_drop'] + timedelta(hours=cd):
        rem = (u['last_drop'] + timedelta(hours=cd)) - datetime.now()
        return await message.answer(f"⏳ Жди {rem.seconds // 3600}ч. { (rem.seconds // 60) % 60 }мин.")

    card = await db.get_random_card()
    if not card: return await message.answer("База пуста!")
    
    # Анимация открытия
    status_msg = await message.answer("📦 Открываем пак...")
    await asyncio.sleep(1.2)
    
    cfg = RARITY_CONFIG.get(card['rarity'], {"icon": "⚪", "reward": 0})
    await status_msg.edit_text(f"✨ Ого! Это КАРТА ТИПА {card['rarity']} {cfg['icon']}")
    await asyncio.sleep(1.2)
    
    await db.pool.execute("INSERT INTO inventory (user_id, card_id) VALUES ($1, $2)", message.from_user.id, card['card_id'])
    await db.update_stars(message.from_user.id, cfg['reward'])
    await db.set_cooldown(message.from_user.id, 'last_drop')
    
    await message.answer_photo(card['photo_id'], caption=format_card_caption(card))
    await status_msg.delete()

@dp.message(F.text == "🛒 Магазин")
async def shop(message: types.Message, state: FSMContext):
    await state.clear()
    kb = [[InlineKeyboardButton(text=f"{v['icon']} {k} — {v['price']} 🌟", callback_data=f"buy_{k}")] for k,v in RARITY_CONFIG.items()]
    kb.append([InlineKeyboardButton(text="👑 VIP (24ч) — 20 000 🌟", callback_data="buy_vip")])
    await message.answer("🛒 МАГАЗИН КАРТ:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("buy_"))
async def process_buy(callback: types.CallbackQuery, db: Database):
    item = callback.data.split("_")[1]
    u = await db.get_user(callback.from_user.id)
    if item == "vip":
        if u['stars'] < 20000: return await callback.answer("Недостаточно звёзд!", show_alert=True)
        await db.update_stars(callback.from_user.id, -20000)
        new_v = (u['vip_until'] if u.get('vip_until') and u['vip_until'] > datetime.now() else datetime.now()) + timedelta(hours=24)
        await db.pool.execute("UPDATE users SET vip_until = $1 WHERE user_id = $2", new_v, callback.from_user.id)
        await callback.message.answer("👑 VIP куплен!")
    elif item in RARITY_CONFIG:
        price = RARITY_CONFIG[item]['price']
        if u['stars'] < price: return await callback.answer("Недостаточно звёзд!", show_alert=True)
        card = await db.pool.fetchrow("SELECT * FROM mifl_cards WHERE rarity = $1 ORDER BY RANDOM() LIMIT 1", item)
        if not card: return await callback.answer("Нет карт такой редкости!", show_alert=True)
        
        await db.update_stars(callback.from_user.id, -price)
        await db.pool.execute("INSERT INTO inventory (user_id, card_id) VALUES ($1, $2)", callback.from_user.id, card['card_id'])
        
        await callback.message.answer_photo(card['photo_id'], caption=f"🛒 Куплена карта:\n\n{format_card_caption(card)}")
    await callback.answer()

# --- МИНИ-ИГРА УГАДАЙКА ---
@dp.message(F.text == "⚽ Мини Игры")
async def games_menu(message: types.Message, state: FSMContext):
    await state.clear()
    kb = [[InlineKeyboardButton(text="🧩 Угадай игрока", callback_data="play_guess")]]
    await message.answer("⚽ Выбери игру:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data == "play_guess")
async def guess_start(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("🧩 Введи ставку (от 100):")
    await state.set_state(GuessGame.bet)
    await callback.answer()

@dp.message(GuessGame.bet)
async def guess_bet(message: types.Message, state: FSMContext, db: Database):
    if not message.text.isdigit(): return await message.answer("Введи число!")
    bet = int(message.text)
    u = await db.get_user(message.from_user.id)
    if bet < 100 or bet > u['stars']: return await message.answer("Неверная ставка!")
    
    card = await db.get_random_card()
    if not card: return await state.clear()
    
    wrong = await db.pool.fetch("SELECT name FROM mifl_cards WHERE name != $1 ORDER BY RANDOM() LIMIT 3", card['name'])
    opts = [card['name']] + [r['name'] for r in wrong]
    random.shuffle(opts)
    await state.update_data(correct=card['name'], bet=bet, cid=card['card_id'], opts=opts)
    
    kb = [[InlineKeyboardButton(text=o, callback_data=f"gans_{i}")] for i, o in enumerate(opts)]
    await db.update_stars(message.from_user.id, -bet)
    await message.answer(f"🧩 КТО ЭТО?\n⭐ Рейтинг: {card['rating']}\n📍 Позиция: {card['position']}\n🏢 Клуб: {card['club']}", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("gans_"))
async def guess_check(callback: types.CallbackQuery, state: FSMContext, db: Database):
    data = await state.get_data()
    if not data: return await callback.answer("Сессия истекла")
    
    chosen = data['opts'][int(callback.data.split("_")[1])]
    card = await db.pool.fetchrow("SELECT * FROM mifl_cards WHERE card_id = $1", data['cid'])
    cfg = RARITY_CONFIG.get(card['rarity'], {"coef": 1.5})
    
    if chosen == data['correct']:
        win = int(data['bet'] * cfg['coef'])
        await db.update_stars(callback.from_user.id, win)
        res_text = f"✅ Верно! Это был {card['name']}.\nТвой выигрыш: {win} 🌟 (x{cfg['coef']})"
    else:
        res_text = f"❌ Неверно! Это был {card['name']}."
    
    await callback.message.answer_photo(card['photo_id'], caption=f"{res_text}\n\n{format_card_caption(card)}")
    await state.clear()
    await callback.message.delete()

@dp.message(F.text == "👥 Рефералы")
async def refs(message: types.Message, state: FSMContext):
    await state.clear()
    me = await bot.get_me()
    await message.answer(f"👥 Приглашай друзей! Бонус 5 000 🌟\n\n🔗 Твоя ссылка:\nt.me/{me.username}?start={message.from_user.id}")

@dp.message(F.text == "📊 ТОП-10")
async def top_players(message: types.Message, db: Database, state: FSMContext):
    await state.clear()
    rows = await db.pool.fetch("SELECT username, stars FROM users ORDER BY stars DESC LIMIT 10")
    txt = "📊 ТОП-10 БОГАТЕЕВ:\n\n" + "\n".join([f"{i+1}. {r['username']} — {r['stars']:,} 🌟" for i, r in enumerate(rows)]).replace(",", " ")
    await message.answer(txt)

# --- ЗАПУСК ---
async def main():
    asyncio.create_task(start_web_server())
    pool = await asyncpg.create_pool(DATABASE_URL, ssl='require')
    db = Database(pool)
    await db.create_tables()
    try: await pool.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_drop TIMESTAMP")
    except: pass
    dp["db"] = db
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
