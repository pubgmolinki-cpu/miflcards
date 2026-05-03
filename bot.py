import os
import asyncio
import random
import string
import asyncpg
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

from database import Database
from profile_generator import generate_profile_image

# --- КОНФИГУРАЦИЯ ---
TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
CHANNEL_ID = "@Miflcards"
CHANNEL_URL = "https://t.me/Miflcards"
ADMIN_IDS = [1866813859]

bot = Bot(token=TOKEN)
dp = Dispatcher()

RARITY_CONFIG = {
    "One": {"icon": "🟡", "price": 3500, "reward": 10000},
    "Chase": {"icon": "🟣", "price": 2800, "reward": 5000},
    "Drop": {"icon": "🔴", "price": 2000, "reward": 2500},
    "Series": {"icon": "🔵", "price": 1200, "reward": 1250},
    "Stock": {"icon": "🟢", "price": 500, "reward": 500}
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

# --- КЛАВИАТУРЫ ---
def main_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🎁 Получить Карту"), KeyboardButton(text="📅 Бонус")],
        [KeyboardButton(text="⚽ Мини Игры"), KeyboardButton(text="🛒 Магазин")],
        [KeyboardButton(text="🔄 Трейд"), KeyboardButton(text="🏷 Промокод")],
        [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="👥 Рефералы")],
        [KeyboardButton(text="📊 ТОП-10")]
    ], resize_keyboard=True)

def cancel_inline():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action")]])

# --- ВСПОМОГАТЕЛЬНОЕ ---
def format_card_caption(card):
    cfg = RARITY_CONFIG.get(card['rarity'], {"icon": "⚪"})
    return (f"👤 {card['name']}\n📊 Рейтинг: {card['rating']}\n🏢 Клуб: {card['club']}\n"
            f"📍 Позиция: {card['position']}\n✨ Редкость: {cfg['icon']} {card['rarity']}")

# --- ОБРАБОТЧИКИ ОТМЕНЫ ---
@dp.callback_query(F.data == "cancel_action")
async def process_cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Действие отменено.")
    await callback.answer()

@dp.message(F.text.lower() == "отмена")
async def text_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Действия отменены.", reply_markup=main_kb())

# --- ПОЛНАЯ АДМИНКА ---

@dp.message(Command("add_promo"))
async def adm_promo(message: types.Message, command: CommandObject, db: Database):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        code, stars, uses = command.args.split()
        await db.pool.execute("INSERT INTO promocodes (code, stars, max_uses, current_uses) VALUES ($1, $2, $3, 0)", code.upper(), int(stars), int(uses))
        await message.answer(f"✅ Промокод {code.upper()} создан!")
    except: await message.answer("❌ Формат: /add_promo <КОД> <ЗВЕЗДЫ> <ЛИМИТ>")

@dp.message(Command("add_player"))
async def adm_add_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    await message.answer("🛠 Отправь фото игрока:", reply_markup=cancel_inline())
    await state.set_state(AddPlayer.waiting_for_photo)

@dp.message(AddPlayer.waiting_for_photo, F.photo)
async def adm_get_photo(message: types.Message, state: FSMContext):
    await state.update_data(p_id=message.photo[-1].file_id)
    await message.answer("✅ Введи через запятую: Имя, Рейтинг, Позиция, Клуб, Редкость", reply_markup=cancel_inline())
    await state.set_state(AddPlayer.waiting_for_details)

@dp.message(AddPlayer.waiting_for_details, F.text)
async def adm_save_card(message: types.Message, state: FSMContext, db: Database):
    try:
        p = [x.strip() for x in message.text.split(",")]
        p_id = (await state.get_data())['p_id']
        await db.pool.execute("INSERT INTO mifl_cards (name, rating, position, club, rarity, photo_id) VALUES ($1, $2, $3, $4, $5, $6)", p[0], float(p[1]), p[2], p[3], p[4], p_id)
        await message.answer("✅ Карта добавлена!")
    except: await message.answer("❌ Ошибка в формате.")
    await state.clear()

@dp.message(Command("reset_progress"))
async def adm_reset(message: types.Message, command: CommandObject, db: Database):
    if message.from_user.id not in ADMIN_IDS: return
    if not command.args: return await message.answer("Укажи ID игрока.")
    uid = int(command.args)
    await db.pool.execute("DELETE FROM inventory WHERE user_id = $1", uid)
    await db.pool.execute("UPDATE users SET stars = 0 WHERE user_id = $1", uid)
    await message.answer(f"✅ Прогресс игрока {uid} обнулен.")

@dp.message(Command("clear_cards"))
async def adm_clear(message: types.Message, db: Database):
    if message.from_user.id not in ADMIN_IDS: return
    await db.pool.execute("TRUNCATE TABLE mifl_cards CASCADE")
    await message.answer("⚠️ База карт полностью очищена!")

# --- МАГАЗИН И ПАК ОПЕНИНГ ---

@dp.message(F.text == "🛒 Магазин")
async def shop_menu(message: types.Message):
    kb = [[InlineKeyboardButton(text=f"Пак {r} — {v['price']} 🌟", callback_data=f"buy_{r}")] for r, v in RARITY_CONFIG.items()]
    await message.answer("🛒 Магазин паков:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("buy_"))
async def process_buy(callback: types.CallbackQuery, db: Database):
    rarity = callback.data.split("_")[1]
    u = await db.get_user(callback.from_user.id)
    cfg = RARITY_CONFIG[rarity]
    if u['stars'] < cfg['price']: return await callback.answer("Недостаточно звезд!", show_alert=True)
    card = await db.pool.fetchrow("SELECT * FROM mifl_cards WHERE rarity = $1 ORDER BY RANDOM() LIMIT 1", rarity)
    if not card: return await callback.answer("Карт такой редкости нет.", show_alert=True)
    await db.update_stars(callback.from_user.id, -cfg['price'])
    await db.pool.execute("INSERT INTO inventory (user_id, card_id) VALUES ($1, $2)", callback.from_user.id, card['card_id'])
    await callback.message.answer_photo(card['photo_id'], caption=f"🛍 Куплено!\n\n{format_card_caption(card)}")
    await callback.answer()

@dp.message(F.text == "🎁 Получить Карту")
async def get_card(message: types.Message, db: Database):
    u = await db.get_user(message.from_user.id)
    cd = 2 if (u.get('vip_until') and u['vip_until'] > datetime.now()) else 4
    if u.get('last_drop') and datetime.now() < u['last_drop'] + timedelta(hours=cd):
        diff = (u['last_drop'] + timedelta(hours=cd)) - datetime.now()
        return await message.answer(f"⏳ Подожди еще {diff.seconds // 3600}ч. {(diff.seconds // 60) % 60}м.")
    card = await db.get_random_card()
    if not card: return await message.answer("База пуста.")
    has = await db.pool.fetchval("SELECT 1 FROM inventory WHERE user_id = $1 AND card_id = $2", message.from_user.id, card['card_id'])
    await db.set_cooldown(message.from_user.id, 'last_drop')
    if has:
        reward = int(RARITY_CONFIG.get(card['rarity'], {"reward": 500})['reward'] * 0.5)
        await db.update_stars(message.from_user.id, reward)
        await message.answer_photo(card['photo_id'], caption=f"{format_card_caption(card)}\n\n♻️ Дубликат! +{reward} 🌟")
    else:
        reward = RARITY_CONFIG.get(card['rarity'], {"reward": 500})['reward']
        await db.pool.execute("INSERT INTO inventory (user_id, card_id) VALUES ($1, $2)", message.from_user.id, card['card_id'])
        await db.update_stars(message.from_user.id, reward)
        await message.answer_photo(card['photo_id'], caption=f"{format_card_caption(card)}\n\n🎊 Новая карта! +{reward} 🌟")

# --- ПРОЧЕЕ ---

@dp.message(F.text == "📅 Бонус")
async def cmd_bonus(message: types.Message, db: Database):
    u = await db.get_user(message.from_user.id)
    if u.get('last_bonus') and datetime.now() < u['last_bonus'] + timedelta(hours=24):
        diff = (u['last_bonus'] + timedelta(hours=24)) - datetime.now()
        return await message.answer(f"⏳ Бонус через {diff.seconds // 3600}ч.")
    val = random.randint(500, 2500)
    await db.update_stars(message.from_user.id, val)
    await db.pool.execute("UPDATE users SET last_bonus = $1 WHERE user_id = $2", datetime.now(), message.from_user.id)
    await message.answer(f"🎁 Получено {val} 🌟")

@dp.message(F.text == "🏷 Промокод")
async def promo_start(message: types.Message, state: FSMContext):
    await state.set_state(PromoState.waiting_for_code)
    await message.answer("🏷 Введи код:", reply_markup=cancel_inline())

@dp.message(PromoState.waiting_for_code)
async def promo_use(message: types.Message, state: FSMContext, db: Database):
    code = message.text.strip().upper()
    promo = await db.pool.fetchrow("SELECT * FROM promocodes WHERE code = $1", code)
    if not promo or promo['current_uses'] >= promo['max_uses']: return await message.answer("❌ Код неверный.")
    used = await db.pool.fetchval("SELECT 1 FROM used_promos WHERE user_id = $1 AND code = $2", message.from_user.id, code)
    if used: return await message.answer("❌ Уже использован.")
    await db.pool.execute("UPDATE promocodes SET current_uses = current_uses + 1 WHERE code = $1", code)
    await db.pool.execute("INSERT INTO used_promos (user_id, code) VALUES ($1, $2)", message.from_user.id, code)
    await db.update_stars(message.from_user.id, promo['stars'])
    await message.answer(f"✅ Успех! +{promo['stars']} 🌟")
    await state.clear()

@dp.message(F.text == "⚽ Мини Игры")
async def games_menu(message: types.Message):
    kb = [[InlineKeyboardButton(text="🧩 Угадай Игрока", callback_data="play_guess")]]
    await message.answer("⚽ Выбери игру:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data == "play_guess")
async def guess_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("🧩 Введи ставку:", reply_markup=cancel_inline())
    await state.set_state(GuessGame.bet)

@dp.message(GuessGame.bet)
async def guess_logic(message: types.Message, state: FSMContext, db: Database):
    if not message.text.isdigit(): return
    bet = int(message.text)
    u = await db.get_user(message.from_user.id)
    if bet < 100 or bet > u['stars']: return await message.answer("Ошибка ставки.")
    card = await db.get_random_card()
    others = await db.pool.fetch("SELECT name FROM mifl_cards WHERE name != $1 ORDER BY RANDOM() LIMIT 3", card['name'])
    opts = [card['name']] + [r['name'] for r in others]
    random.shuffle(opts)
    await state.update_data(correct=card['name'], bet=bet, cid=card['card_id'], opts=opts)
    kb = [[InlineKeyboardButton(text=o, callback_data=f"ans_{i}")] for i, o in enumerate(opts)]
    await db.update_stars(message.from_user.id, -bet)
    await message.answer(f"КТО ЭТО?\n⭐ Рейтинг: {card['rating']}\n🏢 Клуб: {card['club']}", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("ans_"))
async def guess_check(callback: types.CallbackQuery, state: FSMContext, db: Database):
    data = await state.get_data()
    if data['opts'][int(callback.data.split("_")[1])] == data['correct']:
        await db.update_stars(callback.from_user.id, data['bet'] * 2)
        await callback.message.answer(f"✅ Верно! +{data['bet']*2} 🌟")
    else: await callback.message.answer(f"❌ Неверно! Это был {data['correct']}")
    await state.clear()

@dp.message(F.text == "🔄 Трейд")
async def trade_init(message: types.Message):
    kb = [[InlineKeyboardButton(text="📤 Создать код", callback_data="tr_create")], [InlineKeyboardButton(text="📥 Ввести код", callback_data="tr_join")]]
    await message.answer("🔄 ОБМЕН КАРТАМИ", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data == "tr_create")
async def tr_create_pg(callback: types.CallbackQuery, db: Database):
    cards = await db.pool.fetch("SELECT c.* FROM mifl_cards c JOIN inventory i ON c.card_id = i.card_id WHERE i.user_id = $1 LIMIT 5", callback.from_user.id)
    if not cards: return await callback.answer("Нет карт!", show_alert=True)
    kb = [[InlineKeyboardButton(text=f"{c['name']}", callback_data=f"trgen_{c['card_id']}")] for c in cards]
    await callback.message.edit_text("Выбери карту:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("trgen_"))
async def tr_gen_final(callback: types.CallbackQuery, db: Database):
    cid = int(callback.data.split("_")[1])
    code = "TRD-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=5))
    await db.pool.execute("INSERT INTO active_trades (code, user_a, card_a) VALUES ($1, $2, $3)", code, callback.from_user.id, cid)
    await callback.message.edit_text(f"✅ Код: `{code}`")

@dp.callback_query(F.data == "tr_join")
async def tr_join_input(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("📥 Введи код:", reply_markup=cancel_inline())
    await state.set_state(TradeState.enter_code)

@dp.message(TradeState.enter_code)
async def tr_join_logic(message: types.Message, state: FSMContext, db: Database):
    code = message.text.strip().upper()
    tr = await db.pool.fetchrow("SELECT * FROM active_trades WHERE code = $1", code)
    if not tr or tr['user_a'] == message.from_user.id: return await message.answer("❌ Ошибка.")
    await state.update_data(tr_code=code)
    cards = await db.pool.fetch("SELECT c.* FROM mifl_cards c JOIN inventory i ON c.card_id = i.card_id WHERE i.user_id = $1 LIMIT 5", message.from_user.id)
    kb = [[InlineKeyboardButton(text=f"Дать: {c['name']}", callback_data=f"troff_{c['card_id']}")] for c in cards]
    await message.answer("Что предложишь взамен?", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("troff_"))
async def tr_send_to_a(callback: types.CallbackQuery, state: FSMContext, db: Database):
    cb_id, code = int(callback.data.split("_")[1]), (await state.get_data())['tr_code']
    tr = await db.pool.fetchrow("SELECT * FROM active_trades WHERE code = $1", code)
    kb = [[InlineKeyboardButton(text="✅ ПРИНЯТЬ", callback_data=f"trapp_{code}_{cb_id}_{callback.from_user.id}")], [InlineKeyboardButton(text="❌ ОТМЕНА", callback_data=f"trrej_{code}")]]
    await bot.send_message(tr['user_a'], f"🔄 Запрос обмена по коду {code}", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.message.edit_text("⏳ Ожидание ответа...")
    await state.clear()

@dp.callback_query(F.data.startswith("trapp_"))
async def tr_accept(callback: types.CallbackQuery, db: Database):
    _, code, cb_id, ub_id = callback.data.split("_")
    tr = await db.pool.fetchrow("SELECT * FROM active_trades WHERE code = $1", code)
    if tr:
        await db.pool.execute("DELETE FROM inventory WHERE user_id = $1 AND card_id = $2", tr['user_a'], tr['card_a'])
        await db.pool.execute("DELETE FROM inventory WHERE user_id = $1 AND card_id = $2", int(ub_id), int(cb_id))
        await db.pool.execute("INSERT INTO inventory (user_id, card_id) VALUES ($1, $2), ($3, $4)", tr['user_a'], int(cb_id), int(ub_id), tr['card_a'])
        await db.pool.execute("DELETE FROM active_trades WHERE code = $1", code)
        await callback.message.edit_text("✅ Обмен завершен!")
        await bot.send_message(int(ub_id), "✅ Обмен принят!")

@dp.message(F.text == "👤 Профиль")
async def view_profile(message: types.Message, db: Database):
    u = await db.get_user(message.from_user.id)
    cnt = await db.pool.fetchval("SELECT COUNT(*) FROM inventory WHERE user_id = $1", message.from_user.id)
    st = "VIP" if u.get('vip_until') and u['vip_until'] > datetime.now() else "Обычный"
    try:
        photos = await bot.get_user_profile_photos(message.from_user.id, limit=1)
        ava = (await bot.download_file((await bot.get_file(photos.photos[0][0].file_id)).file_path)).read() if photos.total_count > 0 else None
        img = await generate_profile_image(ava, u['username'], u['stars'], cnt, st)
        await message.answer_photo(BufferedInputFile(img.read(), "p.png"), caption=f"👤 {u['username']}\n💰 {u['stars']} 🌟\n👑 {st}")
    except: await message.answer(f"👤 {u['username']}\n💰 {u['stars']} 🌟\n👑 {st}")

@dp.message(F.text == "📊 ТОП-10")
async def leaderboard(message: types.Message, db: Database):
    rows = await db.pool.fetch("SELECT username, stars FROM users ORDER BY stars DESC LIMIT 10")
    txt = "🏆 ТОП-10:\n\n" + "\n".join([f"{i+1}. {r['username']} — {r['stars']} 🌟" for i, r in enumerate(rows)])
    await message.answer(txt)

@dp.message(Command("start"))
async def cmd_start(message: types.Message, command: CommandObject, db: Database):
    ref = int(command.args) if command.args and command.args.isdigit() else None
    await db.pool.execute("INSERT INTO users (user_id, username, referrer_id) VALUES ($1, $2, $3) ON CONFLICT (user_id) DO UPDATE SET username = $2", message.from_user.id, message.from_user.username or message.from_user.first_name, ref)
    if ref and ref != message.from_user.id: await db.update_stars(ref, 5000)
    await message.answer("⚽ Привет в MIfl Cards!", reply_markup=main_kb())

async def main():
    asyncio.create_task(web._run_app(web.Application().add_routes([web.get('/', lambda r: web.Response(text="OK"))]), port=int(os.environ.get("PORT", 8080))))
    pool = await asyncpg.create_pool(DATABASE_URL, ssl='require')
    db = Database(pool)
    await db.create_tables()
    async with pool.acquire() as conn:
        await conn.execute("CREATE TABLE IF NOT EXISTS promocodes (code TEXT PRIMARY KEY, stars INT, max_uses INT, current_uses INT DEFAULT 0)")
        await conn.execute("CREATE TABLE IF NOT EXISTS used_promos (user_id BIGINT, code TEXT)")
        await conn.execute("CREATE TABLE IF NOT EXISTS active_trades (code TEXT PRIMARY KEY, user_a BIGINT, card_a INT)")
        await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_bonus TIMESTAMP")
    dp["db"] = db
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
