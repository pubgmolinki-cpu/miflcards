import os
import asyncio
import random
import string
import asyncpg
import logging
from io import BytesIO
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

# --- НАСТРОЙКИ ---
TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
CHANNEL_ID = "@Miflcards"
ADMIN_IDS = [1866813859]

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()

try:
    from profile_generator import generate_profile_image
except ImportError:
    async def generate_profile_image(*args, **kwargs): return None

RARITY_CONFIG = {
    "One": {"icon": "🟡", "price": 3500, "reward": 10000},
    "Chase": {"icon": "🟣", "price": 2800, "reward": 5000},
    "Drop": {"icon": "🔴", "price": 2000, "reward": 2500},
    "Series": {"icon": "🔵", "price": 1200, "reward": 1250},
    "Stock": {"icon": "🟢", "price": 500, "reward": 500}
}

class Form(StatesGroup):
    add_player_photo = State()
    add_player_data = State()
    guess_bet = State()
    guess_playing = State()
    promo_input = State()
    trade_input = State()

# --- КЛАВИАТУРА ---
def main_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🎁 Получить Карту"), KeyboardButton(text="📅 Бонус")],
        [KeyboardButton(text="⚽ Мини Игры"), KeyboardButton(text="🛒 Магазин")],
        [KeyboardButton(text="🔄 Трейд"), KeyboardButton(text="🏷 Промокод")],
        [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="👥 Рефералы")],
        [KeyboardButton(text="📊 ТОП-10")]
    ], resize_keyboard=True)

def sub_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Подписаться на канал", url="https://t.me/Miflcards")],
        [InlineKeyboardButton(text="✅ Я подписался", callback_data="check_subs")]
    ])

# --- БАЗА ДАННЫХ ---
class Database:
    def __init__(self, pool):
        self.pool = pool

    async def create_tables(self):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, username TEXT, stars INT DEFAULT 0, vip_until TIMESTAMP, last_drop TIMESTAMP, last_bonus TIMESTAMP);
                CREATE TABLE IF NOT EXISTS mifl_cards (card_id SERIAL PRIMARY KEY, name TEXT, rating FLOAT, club TEXT, position TEXT, rarity TEXT, photo_id TEXT);
                CREATE TABLE IF NOT EXISTS inventory (user_id BIGINT, card_id INT);
                CREATE TABLE IF NOT EXISTS promocodes (code TEXT PRIMARY KEY, stars INT, max_uses INT, current_uses INT DEFAULT 0);
                CREATE TABLE IF NOT EXISTS used_promos (user_id BIGINT, code TEXT);
                CREATE TABLE IF NOT EXISTS active_trades (code TEXT PRIMARY KEY, user_a BIGINT, card_a INT);
            """)

    async def get_user(self, uid, username="Игрок"):
        user = await self.pool.fetchrow("SELECT * FROM users WHERE user_id = $1", uid)
        if not user:
            await self.pool.execute("INSERT INTO users (user_id, username, stars) VALUES ($1, $2, 0)", uid, username)
            return await self.pool.fetchrow("SELECT * FROM users WHERE user_id = $1", uid)
        return user

    async def update_stars(self, uid, amount):
        await self.pool.execute("UPDATE users SET stars = stars + $1 WHERE user_id = $2", amount, uid)

    async def get_random_card(self):
        return await self.pool.fetchrow("SELECT * FROM mifl_cards ORDER BY RANDOM() LIMIT 1")

# --- СИСТЕМА ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext, command: CommandObject, db: Database):
    await state.clear()
    if not await check_subscription(message.from_user.id):
        return await message.answer("⚠️ Для игры необходимо подписаться на наш канал!", reply_markup=sub_kb())
    
    ref_id = command.args
    ref_id = int(ref_id) if ref_id and ref_id.isdigit() else None
    
    user_exists = await db.pool.fetchval("SELECT 1 FROM users WHERE user_id = $1", message.from_user.id)
    if not user_exists:
        await db.pool.execute("INSERT INTO users (user_id, username, stars) VALUES ($1, $2, 0)", message.from_user.id, message.from_user.first_name)
        if ref_id and ref_id != message.from_user.id:
            await db.update_stars(ref_id, 5000)
            try: await bot.send_message(ref_id, "👥 По вашей ссылке зарегистрировался новый игрок! +5000 🌟")
            except: pass
            
    user = await db.pool.fetchrow("SELECT * FROM users WHERE user_id = $1", message.from_user.id)
    await message.answer(f"⚽ Привет, {user['username']}! Добро пожаловать в <b>Mifl Cards</b>.", reply_markup=main_kb(), parse_mode="HTML")

async def check_subscription(user_id):
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in ["member", "administrator", "creator"]
    except: return False

@dp.callback_query(F.data == "check_subs")
async def verify_sub_callback(call: types.CallbackQuery, db: Database):
    if await check_subscription(call.from_user.id):
        await call.message.delete()
        user = await db.get_user(call.from_user.id)
        await call.message.answer(f"⚽ Привет, {user['username']}! Добро пожаловать в <b>Mifl Cards</b>.", reply_markup=main_kb(), parse_mode="HTML")
    else: await call.answer("❌ Ты всё еще не подписан!", show_alert=True)

# --- ПРОФИЛЬ ---
@dp.message(F.text == "👤 Профиль")
async def view_profile(message: types.Message, state: FSMContext, db: Database):
    await state.clear()
    if not await check_subscription(message.from_user.id): return await message.answer("⚠️ Подпишись на канал!", reply_markup=sub_kb())

    u = await db.get_user(message.from_user.id)
    cnt = await db.pool.fetchval("SELECT COUNT(*) FROM inventory WHERE user_id = $1", message.from_user.id)
    
    is_vip = u.get('vip_until') and u['vip_until'] > datetime.now()
    if is_vip:
        st_text = "VIP 💎"
        st_full = f"VIP 💎 (до {u['vip_until'].strftime('%d.%m.%y | %H:%M')})"
        st_color = "yellow"
    else:
        st_text = "Обычный 👤"
        st_full = st_text
        st_color = "white"
    
    caption = f"👤 <b>Профиль: {u['username']}</b>\n💰 Баланс: {u['stars']:,} 🌟\n🎴 Карт: {cnt}\n👑 Статус: {st_full}"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎴 Моя Коллекция", callback_data="view_col_0")]])

    avatar_bytes = None
    try:
        photos = await bot.get_user_profile_photos(message.from_user.id, limit=1)
        if photos.total_count > 0:
            file = await bot.get_file(photos.photos[0][-1].file_id)
            # Aiogram 3.x download
            downloaded = await bot.download(file)
            avatar_bytes = downloaded.read()

        img_io = await generate_profile_image(avatar_bytes, u['username'], u['stars'], cnt, st_text, color=st_color)
        if img_io:
            img_io.seek(0) # Сброс указателя
            return await message.answer_photo(BufferedInputFile(img_io.read(), filename="profile.png"), caption=caption, reply_markup=kb, parse_mode="HTML")
    except Exception as e:
        logging.error(f"Profile photo error: {e}")
    
    await message.answer(caption, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data.startswith("view_col_"))
async def view_collection(callback: types.CallbackQuery, db: Database):
    page = int(callback.data.split("_")[2])
    cards = await db.pool.fetch("SELECT c.name, c.rarity FROM mifl_cards c JOIN inventory i ON c.card_id = i.card_id WHERE i.user_id = $1 LIMIT 10 OFFSET $2", callback.from_user.id, page * 10)
    
    if not cards: 
        if page == 0: return await callback.answer("У вас пока нет карт!", show_alert=True)
        else: return await callback.answer("Конец списка!", show_alert=True)
    
    text = "🎴 <b>Ваши карты:</b>\n\n"
    for c in cards:
        text += f"{RARITY_CONFIG.get(c['rarity'], {}).get('icon', '⚪')} {c['name']} ({c['rarity']})\n"
    
    nav = [InlineKeyboardButton(text="⬅️", callback_data=f"view_col_{page-1}")] if page > 0 else []
    if len(cards) == 10: nav.append(InlineKeyboardButton(text="➡️", callback_data=f"view_col_{page+1}"))
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[nav]), parse_mode="HTML")
    await callback.answer()

# --- МЕХАНИКИ ПАКОВ ---
async def animate_pack_opening(chat_id, card, reward_text=""):
    msg = await bot.send_message(chat_id, "Открываем Пак 📦...")
    await asyncio.sleep(random.randint(3, 4))
    for step in [f"Рейтинг: {card['rating']}", f"Рейтинг: {card['rating']}\nПозиция: {card['position']}", f"Рейтинг: {card['rating']}\nПозиция: {card['position']}\nКлуб: {card['club']}"]:
        await msg.edit_text(f"Открываем Пак 📦...\n{step}")
        await asyncio.sleep(1.5)
    await msg.delete()
    
    cfg = RARITY_CONFIG.get(card['rarity'], {"icon": "⚪"})
    cap = f"👤 {card['name']}\n📊 Рейтинг: {card['rating']}\n🏢 Клуб: {card['club']}\n📍 Позиция: {card['position']}\n✨ Редкость: {cfg['icon']} {card['rarity']}"
    if reward_text: cap += f"\n\n{reward_text}"
    await bot.send_photo(chat_id, photo=card['photo_id'], caption=cap)

@dp.message(F.text == "🎁 Получить Карту")
async def get_free_card(message: types.Message, db: Database):
    u = await db.get_user(message.from_user.id)
    cd = 2 if (u.get('vip_until') and u['vip_until'] > datetime.now()) else 4
    if u.get('last_drop') and datetime.now() < u['last_drop'] + timedelta(hours=cd):
        diff = (u['last_drop'] + timedelta(hours=cd)) - datetime.now()
        return await message.answer(f"⏳ Следующий пак через {diff.seconds // 3600}ч. {(diff.seconds // 60) % 60}м.")

    card = await db.get_random_card()
    if not card: return await message.answer("База карт пуста.")
    
    has = await db.pool.fetchval("SELECT 1 FROM inventory WHERE user_id = $1 AND card_id = $2", message.from_user.id, card['card_id'])
    cfg = RARITY_CONFIG.get(card['rarity'], {"icon": "⚪", "reward": 500})
    await db.pool.execute("UPDATE users SET last_drop = $1 WHERE user_id = $2", datetime.now(), message.from_user.id)

    if has:
        sell = int(cfg['reward'] * 0.5)
        await db.update_stars(message.from_user.id, sell)
        await animate_pack_opening(message.chat.id, card, f"♻️ Дубликат продан за {sell} 🌟")
    else:
        await db.pool.execute("INSERT INTO inventory (user_id, card_id) VALUES ($1, $2)", message.from_user.id, card['card_id'])
        await db.update_stars(message.from_user.id, cfg['reward'])
        await animate_pack_opening(message.chat.id, card, f"🎊 Новая карта! +{cfg['reward']} 🌟")

# --- МАГАЗИН И БОНУС ---
@dp.message(F.text == "🛒 Магазин")
async def shop_menu(message: types.Message):
    kb = [[InlineKeyboardButton(text=f"Пак {r} — {v['price']} 🌟", callback_data=f"buy_{r}")] for r, v in RARITY_CONFIG.items()]
    kb.append([InlineKeyboardButton(text="💎 VIP Статус (1 день) — 15000 🌟", callback_data="buy_VIP")])
    await message.answer("🛒 <b>Магазин</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@dp.callback_query(F.data.startswith("buy_"))
async def process_buy(call: types.CallbackQuery, db: Database):
    choice = call.data.split("_")[1]
    u = await db.get_user(call.from_user.id)
    
    if choice == "VIP":
        if u['stars'] < 15000: return await call.answer("Недостаточно звезд!", show_alert=True)
        new_date = (u['vip_until'] if u['vip_until'] and u['vip_until'] > datetime.now() else datetime.now()) + timedelta(days=1)
        await db.pool.execute("UPDATE users SET stars = stars - 15000, vip_until = $1 WHERE user_id = $2", new_date, call.from_user.id)
        return await call.message.answer("💎 VIP успешно приобретен!")

    if u['stars'] < RARITY_CONFIG[choice]['price']: return await call.answer("Недостаточно звезд!", show_alert=True)
    card = await db.pool.fetchrow("SELECT * FROM mifl_cards WHERE rarity = $1 ORDER BY RANDOM() LIMIT 1", choice)
    if not card: return await call.answer("Карт нет.", show_alert=True)
    
    await db.update_stars(call.from_user.id, -RARITY_CONFIG[choice]['price'])
    await db.pool.execute("INSERT INTO inventory (user_id, card_id) VALUES ($1, $2)", call.from_user.id, card['card_id'])
    await call.message.delete()
    await animate_pack_opening(call.message.chat.id, card, "🛍 Покупка в магазине!")

@dp.message(F.text == "📅 Бонус")
async def cmd_bonus(message: types.Message, db: Database):
    u = await db.get_user(message.from_user.id)
    if u.get('last_bonus') and datetime.now() < u['last_bonus'] + timedelta(hours=24):
        diff = (u['last_bonus'] + timedelta(hours=24)) - datetime.now()
        return await message.answer(f"⏳ Бонус через {diff.seconds // 3600}ч.")
    
    if random.random() < 0.10: 
        val = random.randint(6000, 15000)
        txt = f"Сегодня у вас «Удачливый День 🤑».\n\nВаш бонус: {val} ⭐"
    else:
        val = random.randint(1000, 4000)
        txt = f"Сегодня у вас «Обычный День».\n\nВаш бонус: {val} ⭐"
        
    await db.update_stars(message.from_user.id, val)
    await db.pool.execute("UPDATE users SET last_bonus = $1 WHERE user_id = $2", datetime.now(), message.from_user.id)
    await message.answer(txt)

# --- МИНИ-ИГРЫ ---
@dp.message(F.text == "⚽ Мини Игры")
async def games_menu(message: types.Message):
    await message.answer("⚽ Выбери игру:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🧩 Угадай Игрока", callback_data="start_guess")]]))

@dp.callback_query(F.data == "start_guess")
async def guess_bet_step(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("💰 Введите ставку (100 - 20000 🌟):")
    await state.set_state(Form.guess_bet)

@dp.message(Form.guess_bet)
async def guess_logic(message: types.Message, state: FSMContext, db: Database):
    if not message.text.isdigit(): return
    bet, u = int(message.text), await db.get_user(message.from_user.id)
    if bet < 100 or bet > 20000 or bet > u['stars']: return await message.answer("❌ Неверная ставка.")
    
    card = await db.get_random_card()
    if not card: return
    others = await db.pool.fetch("SELECT name FROM mifl_cards WHERE name != $1 ORDER BY RANDOM() LIMIT 3", card['name'])
    opts = [card['name']] + [r['name'] for r in others]
    random.shuffle(opts)
    
    await db.update_stars(message.from_user.id, -bet)
    await state.update_data(correct=card['name'], bet=bet, rating=card['rating'], opts=opts, cid=card['card_id'])
    
    kb = [[InlineKeyboardButton(text=opts[0], callback_data="ans_0"), InlineKeyboardButton(text=opts[1], callback_data="ans_1")],
          [InlineKeyboardButton(text=opts[2], callback_data="ans_2"), InlineKeyboardButton(text=opts[3], callback_data="ans_3")],
          [InlineKeyboardButton(text="💡 Подсказка", callback_data="hint"), InlineKeyboardButton(text="🏳 Сдаться", callback_data="surrender")]]
    
    await message.answer(f"🧩 <b>Угадай игрока!</b>\n🛡 Клуб: {card['club']}\n📍 Поз: {card['position']}\n💰 Ставка: {bet} 🌟", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    await state.set_state(Form.guess_playing)

@dp.callback_query(F.data.startswith("ans_"), Form.guess_playing)
async def check_ans(call: types.CallbackQuery, state: FSMContext, db: Database):
    idx, data = int(call.data.split("_")[1]), await state.get_data()
    card = await db.pool.fetchrow("SELECT * FROM mifl_cards WHERE card_id = $1", data['cid'])
    await call.message.delete()
    if data['opts'][idx] == data['correct']:
        await db.update_stars(call.from_user.id, data['bet']*2)
        txt = f"🎉 <b>ПОБЕДА!</b> Это <b>{data['correct']}</b>! +{data['bet']*2} 🌟"
    else: txt = f"💥 <b>ПРОИГРЫШ.</b> Это был <b>{data['correct']}</b>."
    await call.message.answer_photo(card['photo_id'], caption=txt, parse_mode="HTML")
    await state.clear()

@dp.callback_query(F.data == "hint", Form.guess_playing)
async def guess_hint(call: types.CallbackQuery, state: FSMContext, db: Database):
    data = await state.get_data()
    await db.update_stars(call.from_user.id, -int(data['bet']*0.2))
    await call.answer(f"Рейтинг: {data['rating']}", show_alert=True)

@dp.callback_query(F.data == "surrender", Form.guess_playing)
async def guess_give_up(call: types.CallbackQuery, state: FSMContext):
    await call.message.delete()
    await call.message.answer("🏳 Вы сдались.")
    await state.clear()

# --- ПРОМОКОДЫ ---
@dp.message(F.text == "🏷 Промокод")
async def promo_start(message: types.Message, state: FSMContext):
    await state.set_state(Form.promo_input)
    await message.answer("🏷 Введи код:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_promo")]]))

@dp.callback_query(F.data == "cancel_promo")
async def cancel_promo(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("❌ Отменено.")

@dp.message(Form.promo_input)
async def promo_use(message: types.Message, state: FSMContext, db: Database):
    code = message.text.strip().upper()
    promo = await db.pool.fetchrow("SELECT * FROM promocodes WHERE code = $1", code)
    if not promo or promo['current_uses'] >= promo['max_uses']: return await message.answer("❌ Код недействителен.")
    if await db.pool.fetchval("SELECT 1 FROM used_promos WHERE user_id = $1 AND code = $2", message.from_user.id, code): return await message.answer("❌ Уже использован.")
    
    await db.pool.execute("UPDATE promocodes SET current_uses = current_uses + 1 WHERE code = $1", code)
    await db.pool.execute("INSERT INTO used_promos (user_id, code) VALUES ($1, $2)", message.from_user.id, code)
    await db.update_stars(message.from_user.id, promo['stars'])
    await message.answer(f"✅ Активировано! +{promo['stars']} 🌟")
    await state.clear()

# --- АДМИНКА ---
@dp.message(Command("add_promo"), F.from_user.id.in_(ADMIN_IDS))
async def adm_promo(message: types.Message, command: CommandObject, db: Database):
    try:
        code, stars, uses = command.args.split()
        await db.pool.execute("INSERT INTO promocodes (code, stars, max_uses) VALUES ($1, $2, $3)", code.upper(), int(stars), int(uses))
        await message.answer(f"✅ Код {code.upper()} создан!")
    except: await message.answer("Формат: /add_promo КОД ЗВЕЗДЫ ЛИМИТ")

@dp.message(Command("clear_cards"), F.from_user.id.in_(ADMIN_IDS))
async def adm_clear(message: types.Message, db: Database):
    await db.pool.execute("TRUNCATE TABLE mifl_cards CASCADE")
    await message.answer("⚠️ База карт очищена!")

@dp.message(Command("add_player"), F.from_user.id.in_(ADMIN_IDS))
async def adm_add_p(message: types.Message, state: FSMContext):
    await message.answer("Отправь фото:")
    await state.set_state(Form.add_player_photo)

@dp.message(Form.add_player_photo, F.photo)
async def adm_p_photo(message: types.Message, state: FSMContext):
    await state.update_data(fid=message.photo[-1].file_id)
    await message.answer("Имя, Рейтинг, Клуб, Позиция")
    await state.set_state(Form.add_player_data)

@dp.message(Form.add_player_data)
async def adm_p_save(message: types.Message, state: FSMContext, db: Database):
    d = [x.strip() for x in message.text.split(",")]
    rating = float(d[1])
    if rating >= 5.0: r = "One"
    elif 4.0 <= rating <= 4.5: r = "Chase"
    elif 3.0 <= rating <= 3.5: r = "Drop"
    elif 2.0 <= rating <= 2.5: r = "Series"
    else: r = "Stock"
    
    fid = (await state.get_data())['fid']
    await db.pool.execute("INSERT INTO mifl_cards (name, rating, club, position, rarity, photo_id) VALUES ($1, $2, $3, $4, $5, $6)", d[0], rating, d[2], d[3], r, fid)
    await message.answer(f"✅ Добавлен! Редкость: {r}")
    await state.clear()

# --- ОБМЕН (ТРЕЙД) ---
@dp.message(F.text == "🔄 Трейд")
async def trade_init(message: types.Message):
    kb = [[InlineKeyboardButton(text="📤 Создать", callback_data="tr_create")], [InlineKeyboardButton(text="📥 Ввести", callback_data="tr_join")]]
    await message.answer("🔄 ОБМЕН", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data == "tr_create")
async def tr_create_pg(call: types.CallbackQuery, db: Database):
    cards = await db.pool.fetch("SELECT c.* FROM mifl_cards c JOIN inventory i ON c.card_id = i.card_id WHERE i.user_id = $1 LIMIT 5", call.from_user.id)
    if not cards: return await call.answer("Нет карт!", show_alert=True)
    kb = [[InlineKeyboardButton(text=c['name'], callback_data=f"trgen_{c['card_id']}")] for c in cards]
    await call.message.edit_text("Выбери карту:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("trgen_"))
async def tr_gen_final(call: types.CallbackQuery, db: Database):
    code = "TRD-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=5))
    await db.pool.execute("INSERT INTO active_trades (code, user_a, card_a) VALUES ($1, $2, $3)", code, call.from_user.id, int(call.data.split("_")[1]))
    await call.message.edit_text(f"✅ Код: `{code}`", parse_mode="Markdown")

@dp.callback_query(F.data == "tr_join")
async def tr_join_input(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer("Введи код:")
    await state.set_state(Form.trade_input)

@dp.message(Form.trade_input)
async def tr_join_logic(message: types.Message, state: FSMContext, db: Database):
    tr = await db.pool.fetchrow("SELECT * FROM active_trades WHERE code = $1", message.text.strip().upper())
    if not tr or tr['user_a'] == message.from_user.id: return await message.answer("Ошибка.")
    await state.update_data(tr_code=tr['code'])
    cards = await db.pool.fetch("SELECT c.* FROM mifl_cards c JOIN inventory i ON c.card_id = i.card_id WHERE i.user_id = $1 LIMIT 5", message.from_user.id)
    kb = [[InlineKeyboardButton(text=f"Дать: {c['name']}", callback_data=f"troff_{c['card_id']}")] for c in cards]
    await message.answer("Твоё предложение?", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("troff_"))
async def tr_send_to_a(call: types.CallbackQuery, state: FSMContext, db: Database):
    data = await state.get_data()
    tr = await db.pool.fetchrow("SELECT * FROM active_trades WHERE code = $1", data['tr_code'])
    kb = [[InlineKeyboardButton(text="✅ ПРИНЯТЬ", callback_data=f"trapp_{tr['code']}_{call.data.split('_')[1]}_{call.from_user.id}")]]
    await bot.send_message(tr['user_a'], f"🔄 Запрос обмена {tr['code']}", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await call.message.edit_text("⏳ Ждем ответа...")
    await state.clear()

@dp.callback_query(F.data.startswith("trapp_"))
async def tr_accept(call: types.CallbackQuery, db: Database):
    _, code, cb_id, ub_id = call.data.split("_")
    tr = await db.pool.fetchrow("SELECT * FROM active_trades WHERE code = $1", code)
    if tr:
        await db.pool.execute("DELETE FROM inventory WHERE user_id = $1 AND card_id = $2", tr['user_a'], tr['card_a'])
        await db.pool.execute("DELETE FROM inventory WHERE user_id = $1 AND card_id = $2", int(ub_id), int(cb_id))
        await db.pool.execute("INSERT INTO inventory (user_id, card_id) VALUES ($1, $2), ($3, $4)", tr['user_a'], int(cb_id), int(ub_id), tr['card_a'])
        await db.pool.execute("DELETE FROM active_trades WHERE code = $1", code)
        await call.message.edit_text("✅ Обмен завершен!")
        await bot.send_message(int(ub_id), "✅ Обмен принят!")

# --- СТАРТ ---
async def start_srv():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Mifl"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(os.environ.get("PORT", 8080))).start()

async def main():
    asyncio.create_task(start_srv())
    pool = await asyncpg.create_pool(DATABASE_URL, ssl='require')
    db = Database(pool)
    await db.create_tables()
    dp["db"] = db
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
