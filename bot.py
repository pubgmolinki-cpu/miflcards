import os
import asyncio
import io
import random
import string
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
ADMIN_IDS = [1866813859] # Твой ID

bot = Bot(token=TOKEN)
dp = Dispatcher()

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

class PromoState(StatesGroup):
    waiting_for_code = State()

class TradeState(StatesGroup):
    enter_code = State()

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
        [KeyboardButton(text="🎁 Получить Карту"), KeyboardButton(text="📅 Бонус")],
        [KeyboardButton(text="⚽ Мини Игры"), KeyboardButton(text="🛒 Магазин")],
        [KeyboardButton(text="🔄 Трейд"), KeyboardButton(text="🏷 Промокод")],
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

def generate_trade_code():
    chars = string.ascii_uppercase + string.digits
    return "TRD-" + ''.join(random.choice(chars) for _ in range(5))

# --- MIDDLEWARE ДЛЯ ПРОВЕРКИ ПОДПИСКИ ---
@dp.message.middleware()
async def msg_sub_middleware(handler, event: types.Message, data):
    if event.text and event.text.startswith("/"):
        return await handler(event, data)
    if await is_subscribed(event.from_user.id):
        return await handler(event, data)
    
    kb = [[InlineKeyboardButton(text="🔗 Подписаться на Miflcards", url=CHANNEL_URL)]]
    await event.answer("⚠️ Доступ ограничен!\n\nДля использования бота подпишись на наш канал.", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query.middleware()
async def cb_sub_middleware(handler, event: types.CallbackQuery, data):
    if await is_subscribed(event.from_user.id):
        return await handler(event, data)
    await event.answer("⚠️ Сначала подпишись на канал!", show_alert=True)

# --- АДМИН-КОМАНДЫ (ВКЛЮЧАЯ ПРОМОКОДЫ) ---

@dp.message(Command("add_promo"))
async def admin_add_promo(message: types.Message, command: CommandObject, db: Database):
    if message.from_user.id not in ADMIN_IDS: return
    args = command.args.split() if command.args else []
    if len(args) != 3:
        return await message.answer("❌ Формат: /add_promo <КОД> <ЗВЕЗДЫ> <АКТИВАЦИИ>\nПример: /add_promo START 5000 100")
    
    code, stars, uses = args[0], int(args[1]), int(args[2])
    await db.pool.execute("INSERT INTO promocodes (code, stars, max_uses, current_uses) VALUES ($1, $2, $3, 0)", code, stars, uses)
    await message.answer(f"✅ Промокод {code} создан!\nНаграда: {stars} 🌟\nАктиваций: {uses}")

@dp.message(Command("add_player"))
async def admin_add_card_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    await state.clear()
    await message.answer("🛠 Отправьте фото карточки:")
    await state.set_state(AddPlayer.waiting_for_photo)

@dp.message(AddPlayer.waiting_for_photo, F.photo)
async def admin_get_photo(message: types.Message, state: FSMContext):
    await state.update_data(photo_id=message.photo[-1].file_id)
    await message.answer("✅ Принято! Теперь введи через запятую:\nИмя, Рейтинг, Позиция, Клуб, Редкость\nПример: Messi, 99, RW, Miami, One")
    await state.set_state(AddPlayer.waiting_for_details)

@dp.message(AddPlayer.waiting_for_details, F.text)
async def admin_get_details(message: types.Message, state: FSMContext, db: Database):
    parts = [p.strip() for p in message.text.split(",")]
    if len(parts) != 5: return await message.answer("❌ Нужно 5 параметров через запятую!")
    name, rating, pos, club, rarity = parts
    photo_id = (await state.get_data())['photo_id']
    await db.pool.execute("INSERT INTO mifl_cards (name, rating, position, club, rarity, photo_id) VALUES ($1, $2, $3, $4, $5, $6)", name, float(rating), pos, club, rarity, photo_id)
    await message.answer(f"✅ Карточка {name} добавлена!")
    await state.clear()

# --- СИСТЕМА ПРОМОКОДОВ (ДЛЯ ИГРОКОВ) ---

@dp.message(F.text == "🏷 Промокод")
async def ask_promo(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("🏷 Введи промокод:")
    await state.set_state(PromoState.waiting_for_code)

@dp.message(PromoState.waiting_for_code)
async def process_promo(message: types.Message, state: FSMContext, db: Database):
    code = message.text.strip()
    promo = await db.pool.fetchrow("SELECT * FROM promocodes WHERE code = $1", code)
    
    if not promo:
        await state.clear()
        return await message.answer("❌ Промокод не найден!")
        
    if promo['current_uses'] >= promo['max_uses']:
        await state.clear()
        return await message.answer("❌ Этот промокод больше не действителен (лимит активаций исчерпан).")
        
    already_used = await db.pool.fetchval("SELECT 1 FROM used_promos WHERE user_id = $1 AND code = $2", message.from_user.id, code)
    if already_used:
        await state.clear()
        return await message.answer("❌ Вы уже активировали этот промокод!")
        
    await db.pool.execute("UPDATE promocodes SET current_uses = current_uses + 1 WHERE code = $1", code)
    await db.pool.execute("INSERT INTO used_promos (user_id, code) VALUES ($1, $2)", message.from_user.id, code)
    await db.update_stars(message.from_user.id, promo['stars'])
    
    await message.answer(f"✅ Промокод успешно активирован!\nВам начислено {promo['stars']} 🌟")
    await state.clear()

# --- СИСТЕМА ТРЕЙДА (ОБМЕН КАРТАМИ) ---

@dp.message(F.text == "🔄 Трейд")
async def trade_menu(message: types.Message, state: FSMContext):
    await state.clear()
    kb = [
        [InlineKeyboardButton(text="📤 Создать предложение", callback_data="trade_create_0")],
        [InlineKeyboardButton(text="📥 Ввести код обмена", callback_data="trade_enter_code")]
    ]
    await message.answer("🔄 СИСТЕМА ОБМЕНА КАРТАМИ\n\nСоздай код обмена и передай его другу, либо введи код друга, чтобы предложить свою карту.", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("trade_create_"))
async def trade_create(callback: types.CallbackQuery, db: Database):
    page = int(callback.data.split("_")[2])
    cards = await db.pool.fetch("SELECT c.* FROM mifl_cards c JOIN inventory i ON c.card_id = i.card_id WHERE i.user_id = $1 ORDER BY c.rating DESC LIMIT 5 OFFSET $2", callback.from_user.id, page * 5)
    
    if not cards: return await callback.answer("У тебя нет карт для обмена!", show_alert=True)
    
    kb = [[InlineKeyboardButton(text=f"Выбрать: {c['name']} (⭐{c['rating']})", callback_data=f"tr_sel_{c['card_id']}")] for c in cards]
    nav = []
    if page > 0: nav.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"trade_create_{page-1}"))
    if len(cards) == 5: nav.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"trade_create_{page+1}"))
    if nav: kb.append(nav)
    
    try: await callback.message.edit_text("📤 Выбери карту, которую хочешь отдать:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    except: pass

@dp.callback_query(F.data.startswith("tr_sel_"))
async def trade_generate_code(callback: types.CallbackQuery, db: Database):
    card_id = int(callback.data.split("_")[2])
    has_card = await db.pool.fetchval("SELECT 1 FROM inventory WHERE user_id = $1 AND card_id = $2", callback.from_user.id, card_id)
    if not has_card: return await callback.answer("Эта карта пропала из твоего инвентаря!", show_alert=True)
    
    code = generate_trade_code()
    await db.pool.execute("INSERT INTO active_trades (code, user_a, card_a) VALUES ($1, $2, $3)", code, callback.from_user.id, card_id)
    
    await callback.message.edit_text(f"✅ Обмен создан!\n\nТвой уникальный код обмена:\n`{code}`\n\nПередай его другу. Когда он выберет карту взамен, тебе придет запрос на подтверждение.")

@dp.callback_query(F.data == "trade_enter_code")
async def trade_enter(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(TradeState.enter_code)
    await callback.message.answer("📥 Введи код обмена (например, TRD-XXXXX):")
    await callback.answer()

@dp.message(TradeState.enter_code)
async def trade_process_code(message: types.Message, state: FSMContext, db: Database):
    code = message.text.strip().upper()
    trade = await db.pool.fetchrow("SELECT * FROM active_trades WHERE code = $1", code)
    if not trade: return await message.answer("❌ Код не найден или обмен уже завершен.")
    if trade['user_a'] == message.from_user.id: return await message.answer("❌ Ты не можешь обмениваться сам с собой!")
    
    await state.update_data(trade_code=code)
    
    cards = await db.pool.fetch("SELECT c.* FROM mifl_cards c JOIN inventory i ON c.card_id = i.card_id WHERE i.user_id = $1 ORDER BY c.rating DESC LIMIT 5", message.from_user.id)
    if not cards: return await message.answer("У тебя нет карт для обмена!")
    
    kb = [[InlineKeyboardButton(text=f"Предложить: {c['name']} (⭐{c['rating']})", callback_data=f"tr_off_{c['card_id']}")] for c in cards]
    kb.append([InlineKeyboardButton(text="➡️ Больше карт", callback_data="trade_offer_1")])
    await message.answer("ВЫБЕРИ КАРТУ, ЧТОБЫ ПРЕДЛОЖИТЬ ВЗАМЕН:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("trade_offer_"))
async def trade_offer_pg(callback: types.CallbackQuery, state: FSMContext, db: Database):
    page = int(callback.data.split("_")[2])
    cards = await db.pool.fetch("SELECT c.* FROM mifl_cards c JOIN inventory i ON c.card_id = i.card_id WHERE i.user_id = $1 ORDER BY c.rating DESC LIMIT 5 OFFSET $2", callback.from_user.id, page * 5)
    kb = [[InlineKeyboardButton(text=f"Предложить: {c['name']} (⭐{c['rating']})", callback_data=f"tr_off_{c['card_id']}")] for c in cards]
    nav = []
    if page > 0: nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"trade_offer_{page-1}"))
    if len(cards) == 5: nav.append(InlineKeyboardButton(text="➡️", callback_data=f"trade_offer_{page+1}"))
    if nav: kb.append(nav)
    try: await callback.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    except: pass

@dp.callback_query(F.data.startswith("tr_off_"))
async def trade_send_offer(callback: types.CallbackQuery, state: FSMContext, db: Database):
    card_b_id = int(callback.data.split("_")[2])
    data = await state.get_data()
    code = data.get('trade_code')
    if not code: return await callback.answer("Сессия истекла", show_alert=True)
    
    trade = await db.pool.fetchrow("SELECT * FROM active_trades WHERE code = $1", code)
    if not trade: return await callback.answer("Этот обмен уже не существует", show_alert=True)
    
    card_a = await db.pool.fetchrow("SELECT name, rating FROM mifl_cards WHERE card_id = $1", trade['card_a'])
    card_b = await db.pool.fetchrow("SELECT name, rating FROM mifl_cards WHERE card_id = $1", card_b_id)
    
    u_b_name = callback.from_user.first_name
    
    kb = [
        [InlineKeyboardButton(text="✅ ПРИНЯТЬ ОБМЕН", callback_data=f"trok_{code}_{card_b_id}_{callback.from_user.id}")],
        [InlineKeyboardButton(text="❌ ОТКЛОНИТЬ", callback_data=f"trno_{code}")]
    ]
    
    try:
        await bot.send_message(
            trade['user_a'], 
            f"🔄 НОВОЕ ПРЕДЛОЖЕНИЕ ОБМЕНА!\n\nИгрок {u_b_name} предлагает:\nКарта: {card_b['name']} (⭐{card_b['rating']})\n\nВзамен на твою карту:\n{card_a['name']} (⭐{card_a['rating']})", 
            reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
        )
        await callback.message.edit_text("✅ Запрос на обмен отправлен игроку! Ожидай ответа.")
    except:
        await callback.message.edit_text("❌ Не удалось отправить запрос (возможно игрок заблокировал бота).")
    await state.clear()

@dp.callback_query(F.data.startswith("trok_"))
async def trade_accept(callback: types.CallbackQuery, db: Database):
    parts = callback.data.split("_")
    code, card_b_id, user_b_id = parts[1], int(parts[2]), int(parts[3])
    user_a_id = callback.from_user.id
    
    trade = await db.pool.fetchrow("SELECT * FROM active_trades WHERE code = $1", code)
    if not trade: return await callback.message.edit_text("❌ Этот обмен уже завершен или отменен.")
    card_a_id = trade['card_a']
    
    has_a = await db.pool.fetchval("SELECT 1 FROM inventory WHERE user_id = $1 AND card_id = $2", user_a_id, card_a_id)
    has_b = await db.pool.fetchval("SELECT 1 FROM inventory WHERE user_id = $1 AND card_id = $2", user_b_id, card_b_id)
    
    if not has_a or not has_b:
        await db.pool.execute("DELETE FROM active_trades WHERE code = $1", code)
        return await callback.message.edit_text("❌ Обмен отменен: у кого-то из игроков больше нет этой карты.")
        
    await db.pool.execute("DELETE FROM inventory WHERE ctid = (SELECT ctid FROM inventory WHERE user_id = $1 AND card_id = $2 LIMIT 1)", user_a_id, card_a_id)
    await db.pool.execute("DELETE FROM inventory WHERE ctid = (SELECT ctid FROM inventory WHERE user_id = $1 AND card_id = $2 LIMIT 1)", user_b_id, card_b_id)
    
    await db.pool.execute("INSERT INTO inventory (user_id, card_id) VALUES ($1, $2)", user_a_id, card_b_id)
    await db.pool.execute("INSERT INTO inventory (user_id, card_id) VALUES ($1, $2)", user_b_id, card_a_id)
    
    await db.pool.execute("DELETE FROM active_trades WHERE code = $1", code)
    await callback.message.edit_text("✅ Обмен успешно завершен! Карты перемещены.")
    try: await bot.send_message(user_b_id, "✅ Твое предложение обмена было принято! Карта добавлена в твой профиль.")
    except: pass

@dp.callback_query(F.data.startswith("trno_"))
async def trade_reject(callback: types.CallbackQuery, db: Database):
    code = callback.data.split("_")[1]
    await db.pool.execute("DELETE FROM active_trades WHERE code = $1", code)
    await callback.message.edit_text("❌ Обмен отменен.")

# --- ОСТАЛЬНЫЕ БАЗОВЫЕ ХЕНДЛЕРЫ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, command: CommandObject, db: Database, state: FSMContext):
    await state.clear()
    ref_id = int(command.args) if command.args and command.args.isdigit() else None
    await db.pool.execute("INSERT INTO users (user_id, username, referrer_id) VALUES ($1, $2, $3) ON CONFLICT (user_id) DO UPDATE SET username = $2", message.from_user.id, message.from_user.username or message.from_user.first_name, ref_id)
    if ref_id and ref_id != message.from_user.id: await db.update_stars(ref_id, 5000)
    await message.answer("⚽ Добро пожаловать в MIfl Cards!\nСобирай карты, играй и становись лучшим!", reply_markup=main_kb())

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

@dp.message(F.text == "📅 Бонус")
async def daily_bonus(message: types.Message, db: Database):
    u = await db.get_user(message.from_user.id)
    if u.get('last_bonus') and datetime.now() < u['last_bonus'] + timedelta(hours=24):
        rem = (u['last_bonus'] + timedelta(hours=24)) - datetime.now()
        hours, remainder = divmod(rem.seconds, 3600)
        return await message.answer(f"⏳ Следующий бонус будет доступен через {hours}ч. {remainder // 60}мин.")
    
    bonus_amount = random.randint(500, 2000)
    await db.update_stars(message.from_user.id, bonus_amount)
    await db.pool.execute("UPDATE users SET last_bonus = $1 WHERE user_id = $2", datetime.now(), message.from_user.id)
    await message.answer(f"🎁 Вы получили ежедневный бонус: {bonus_amount} 🌟!")

@dp.message(F.text == "🎁 Получить Карту")
async def get_free_card(message: types.Message, db: Database, state: FSMContext):
    await state.clear()
    u = await db.get_user(message.from_user.id)
    cd = 2 if (u.get('vip_until') and u['vip_until'] > datetime.now()) else 4
    if u.get('last_drop') and datetime.now() < u['last_drop'] + timedelta(hours=cd):
        rem = (u['last_drop'] + timedelta(hours=cd)) - datetime.now()
        return await message.answer(f"⏳ Жди {rem.seconds // 3600}ч. { (rem.seconds // 60) % 60 }мин.")

    card = await db.get_random_card()
    if not card: return await message.answer("База карт пуста!")
    
    status_msg = await message.answer("📦 Открываем пак...")
    await asyncio.sleep(1.2)
    cfg = RARITY_CONFIG.get(card['rarity'], {"icon": "⚪", "reward": 0})
    await status_msg.edit_text(f"✨ Ого! Это КАРТА ТИПА {card['rarity']} {cfg['icon']}")
    await asyncio.sleep(1.2)
    
    has_card = await db.pool.fetchval("SELECT 1 FROM inventory WHERE user_id = $1 AND card_id = $2", message.from_user.id, card['card_id'])
    await db.set_cooldown(message.from_user.id, 'last_drop')
    
    if has_card:
        sell_price = int(cfg['reward'] * 0.5)
        await db.update_stars(message.from_user.id, sell_price)
        await message.answer_photo(card['photo_id'], caption=format_card_caption(card) + f"\n\n♻️ У вас уже есть эта карта! Она автоматически продана за {sell_price} 🌟.")
    else:
        await db.pool.execute("INSERT INTO inventory (user_id, card_id) VALUES ($1, $2)", message.from_user.id, card['card_id'])
        await db.update_stars(message.from_user.id, cfg['reward'])
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
        
        has_card = await db.pool.fetchval("SELECT 1 FROM inventory WHERE user_id = $1 AND card_id = $2", callback.from_user.id, card['card_id'])
        if has_card: return await callback.answer("Вам выпала карта, которая у вас уже есть. Звезды не списаны. Попробуйте еще раз!", show_alert=True)

        await db.update_stars(callback.from_user.id, -price)
        await db.pool.execute("INSERT INTO inventory (user_id, card_id) VALUES ($1, $2)", callback.from_user.id, card['card_id'])
        await callback.message.answer_photo(card['photo_id'], caption=f"🛒 Куплена карта:\n\n{format_card_caption(card)}")
    await callback.answer()

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
    
    # Новые таблицы для промокодов и трейда
    try: 
        await pool.execute("CREATE TABLE IF NOT EXISTS promocodes (code TEXT PRIMARY KEY, stars INT, max_uses INT, current_uses INT DEFAULT 0)")
        await pool.execute("CREATE TABLE IF NOT EXISTS used_promos (user_id BIGINT, code TEXT)")
        await pool.execute("CREATE TABLE IF NOT EXISTS active_trades (code TEXT PRIMARY KEY, user_a BIGINT, card_a INT)")
    except: pass
    
    dp["db"] = db
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
