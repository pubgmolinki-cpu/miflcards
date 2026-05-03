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

# --- ВЕБ-СЕРВЕР ---
async def handle_health(request):
    return web.Response(text="Bot is online")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    await web.TCPSite(runner, '0.0.0.0', port).start()

# --- ВСПОМОГАТЕЛЬНОЕ ---
async def is_subscribed(user_id: int):
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in ["member", "administrator", "creator"]
    except: return False

def main_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🎁 Получить Карту"), KeyboardButton(text="📅 Бонус")],
        [KeyboardButton(text="⚽ Мини Игры"), KeyboardButton(text="🛒 Магазин")],
        [KeyboardButton(text="🔄 Трейд"), KeyboardButton(text="🏷 Промокод")],
        [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="👥 Рефералы")],
        [KeyboardButton(text="📊 ТОП-10")]
    ], resize_keyboard=True)

def format_card_caption(card):
    cfg = RARITY_CONFIG.get(card['rarity'], {"icon": "⚪", "reward": 0})
    return (f"👤 {card['name']}\n📊 Рейтинг: {card['rating']}\n🏢 Клуб: {card['club']}\n"
            f"📍 Позиция: {card['position']}\n✨ Редкость: {cfg['icon']} {card['rarity']}\n💰 Награда: +{cfg['reward']} 🌟")

# --- MIDDLEWARE ---
@dp.message.middleware()
async def sub_check(handler, event: types.Message, data):
    if event.text and (event.text.startswith("/") or event.from_user.id in ADMIN_IDS):
        return await handler(event, data)
    if await is_subscribed(event.from_user.id):
        return await handler(event, data)
    
    kb = [[InlineKeyboardButton(text="🔗 Подписаться", url=CHANNEL_URL)]]
    await event.answer("⚠️ Подпишись на канал, чтобы играть!", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

# --- АДМИН-ФУНКЦИИ ---

@dp.message(Command("add_promo"))
async def adm_promo(message: types.Message, command: CommandObject, db: Database):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        code, stars, uses = command.args.split()
        await db.pool.execute("INSERT INTO promocodes (code, stars, max_uses, current_uses) VALUES ($1, $2, $3, 0)", code.upper(), int(stars), int(uses))
        await message.answer(f"✅ Промокод {code.upper()} создан на {uses} использований!")
    except:
        await message.answer("❌ Формат: /add_promo <КОД> <ЗВЕЗДЫ> <ЛИМИТ>")

@dp.message(Command("add_player"))
async def adm_add_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    await message.answer("🛠 Отправь фото игрока:")
    await state.set_state(AddPlayer.waiting_for_photo)

@dp.message(AddPlayer.waiting_for_photo, F.photo)
async def adm_get_photo(message: types.Message, state: FSMContext):
    await state.update_data(p_id=message.photo[-1].file_id)
    await message.answer("✅ Введи: Имя, Рейтинг, Позиция, Клуб, Редкость")
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
    if command.args:
        uid = int(command.args)
        await db.pool.execute("DELETE FROM inventory WHERE user_id = $1", uid)
        await db.pool.execute("UPDATE users SET stars = 0, vip_until = NULL WHERE user_id = $1", uid)
        await message.answer(f"✅ Игрок {uid} обнулен.")

@dp.message(Command("clear_cards"))
async def adm_clear(message: types.Message, db: Database):
    if message.from_user.id not in ADMIN_IDS: return
    await db.pool.execute("TRUNCATE TABLE mifl_cards CASCADE")
    await message.answer("⚠️ Все карты удалены из базы!")

# --- ИГРОВАЯ ЛОГИКА ---

@dp.message(F.text == "📅 Бонус")
async def cmd_bonus(message: types.Message, db: Database):
    u = await db.get_user(message.from_user.id)
    if u.get('last_bonus') and datetime.now() < u['last_bonus'] + timedelta(hours=24):
        diff = (u['last_bonus'] + timedelta(hours=24)) - datetime.now()
        return await message.answer(f"⏳ Бонус будет через {diff.seconds // 3600}ч. {(diff.seconds // 60) % 60}мин.")
    
    val = random.randint(500, 2500)
    await db.update_stars(message.from_user.id, val)
    await db.pool.execute("UPDATE users SET last_bonus = $1 WHERE user_id = $2", datetime.now(), message.from_user.id)
    await message.answer(f"🎁 Начислено {val} 🌟 за ежедневный вход!")

@dp.message(F.text == "🏷 Промокод")
async def promo_start(message: types.Message, state: FSMContext):
    await message.answer("🏷 Введи секретный промокод:")
    await state.set_state(PromoState.waiting_for_code)

@dp.message(PromoState.waiting_for_code)
async def promo_use(message: types.Message, state: FSMContext, db: Database):
    code = message.text.strip().upper()
    promo = await db.pool.fetchrow("SELECT * FROM promocodes WHERE code = $1", code)
    if not promo or promo['current_uses'] >= promo['max_uses']:
        return await message.answer("❌ Код неверный или истек.")
    
    used = await db.pool.fetchval("SELECT 1 FROM used_promos WHERE user_id = $1 AND code = $2", message.from_user.id, code)
    if used: return await message.answer("❌ Ты уже вводил этот код!")
    
    await db.pool.execute("UPDATE promocodes SET current_uses = current_uses + 1 WHERE code = $1", code)
    await db.pool.execute("INSERT INTO used_promos (user_id, code) VALUES ($1, $2)", message.from_user.id, code)
    await db.update_stars(message.from_user.id, promo['stars'])
    await message.answer(f"✅ Успех! Получено {promo['stars']} 🌟")
    await state.clear()

@dp.message(F.text == "🔄 Трейд")
async def trade_main(message: types.Message):
    kb = [[InlineKeyboardButton(text="📤 Создать обмен", callback_data="tr_new_0")],
          [InlineKeyboardButton(text="📥 Ввести код", callback_data="tr_join")]]
    await message.answer("🔄 ОБМЕН КАРТАМИ\nХочешь обменяться с кем-то?", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("tr_new_"))
async def tr_new(callback: types.CallbackQuery, db: Database):
    pg = int(callback.data.split("_")[2])
    cards = await db.pool.fetch("SELECT c.* FROM mifl_cards c JOIN inventory i ON c.card_id = i.card_id WHERE i.user_id = $1 LIMIT 5 OFFSET $2", callback.from_user.id, pg*5)
    if not cards: return await callback.answer("Пусто!")
    
    kb = [[InlineKeyboardButton(text=f"{c['name']} (⭐{c['rating']})", callback_data=f"trgen_{c['card_id']}")] for c in cards]
    nav = []
    if pg > 0: nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"tr_new_{pg-1}"))
    if len(cards) == 5: nav.append(InlineKeyboardButton(text="➡️", callback_data=f"tr_new_{pg+1}"))
    if nav: kb.append(nav)
    await callback.message.edit_text("Выбери свою карту для обмена:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("trgen_"))
async def tr_gen(callback: types.CallbackQuery, db: Database):
    cid = int(callback.data.split("_")[1])
    code = "TRD-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=5))
    await db.pool.execute("INSERT INTO active_trades (code, user_a, card_a) VALUES ($1, $2, $3)", code, callback.from_user.id, cid)
    await callback.message.edit_text(f"✅ Обмен создан!\nПередай этот код другу:\n`{code}`")

@dp.callback_query(F.data == "tr_join")
async def tr_join_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("📥 Введи код обмена:")
    await state.set_state(TradeState.enter_code)

@dp.message(TradeState.enter_code)
async def tr_join_process(message: types.Message, state: FSMContext, db: Database):
    code = message.text.strip().upper()
    tr = await db.pool.fetchrow("SELECT * FROM active_trades WHERE code = $1", code)
    if not tr or tr['user_a'] == message.from_user.id: return await message.answer("❌ Ошибка кода.")
    
    await state.update_data(tr_code=code)
    cards = await db.pool.fetch("SELECT c.* FROM mifl_cards c JOIN inventory i ON c.card_id = i.card_id WHERE i.user_id = $1 LIMIT 5", message.from_user.id)
    kb = [[InlineKeyboardButton(text=f"Предложить: {c['name']}", callback_data=f"troff_{c['card_id']}")] for c in cards]
    await message.answer("Выбери карту, которую предложишь взамен:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("troff_"))
async def tr_finish_offer(callback: types.CallbackQuery, state: FSMContext, db: Database):
    cb_id = int(callback.data.split("_")[1])
    data = await state.get_data()
    code = data.get('tr_code')
    tr = await db.pool.fetchrow("SELECT * FROM active_trades WHERE code = $1", code)
    
    card_a = await db.pool.fetchrow("SELECT name FROM mifl_cards WHERE card_id = $1", tr['card_a'])
    card_b = await db.pool.fetchrow("SELECT name FROM mifl_cards WHERE card_id = $1", cb_id)
    
    kb = [[InlineKeyboardButton(text="✅ ПРИНЯТЬ", callback_data=f"trapp_{code}_{cb_id}_{callback.from_user.id}")],
          [InlineKeyboardButton(text="❌ ОТМЕНА", callback_data=f"trrej_{code}")]]
    
    await bot.send_message(tr['user_a'], f"🔄 ПРЕДЛОЖЕНИЕ!\nВам дают {card_b['name']} за вашего {card_a['name']}", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.message.edit_text("⏳ Запрос отправлен владельцу. Ждем ответа.")
    await state.clear()

@dp.callback_query(F.data.startswith("trapp_"))
async def tr_approve(callback: types.CallbackQuery, db: Database):
    _, code, cb_id, ub_id = callback.data.split("_")
    tr = await db.pool.fetchrow("SELECT * FROM active_trades WHERE code = $1", code)
    if not tr: return await callback.message.edit_text("❌ Обмен устарел.")
    
    # Смена владельцев
    await db.pool.execute("DELETE FROM inventory WHERE user_id = $1 AND card_id = $2", tr['user_a'], tr['card_a'])
    await db.pool.execute("DELETE FROM inventory WHERE user_id = $1 AND card_id = $2", int(ub_id), int(cb_id))
    await db.pool.execute("INSERT INTO inventory (user_id, card_id) VALUES ($1, $2), ($3, $4)", tr['user_a'], int(cb_id), int(ub_id), tr['card_a'])
    
    await db.pool.execute("DELETE FROM active_trades WHERE code = $1", code)
    await callback.message.edit_text("✅ Обмен завершен!")
    await bot.send_message(int(ub_id), "✅ Твой обмен принят! Карта добавлена.")

# --- БАЗОВЫЕ КОМАНДЫ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, command: CommandObject, db: Database):
    ref = int(command.args) if command.args and command.args.isdigit() else None
    await db.pool.execute("INSERT INTO users (user_id, username, referrer_id) VALUES ($1, $2, $3) ON CONFLICT (user_id) DO UPDATE SET username = $2", message.from_user.id, message.from_user.username or message.from_user.first_name, ref)
    if ref and ref != message.from_user.id: await db.update_stars(ref, 5000)
    await message.answer("⚽ Добро пожаловать в MIfl Cards!", reply_markup=main_kb())

@dp.message(F.text == "🎁 Получить Карту")
async def get_card(message: types.Message, db: Database):
    u = await db.get_user(message.from_user.id)
    cd = 2 if (u.get('vip_until') and u['vip_until'] > datetime.now()) else 4
    if u.get('last_drop') and datetime.now() < u['last_drop'] + timedelta(hours=cd):
        diff = (u['last_drop'] + timedelta(hours=cd)) - datetime.now()
        return await message.answer(f"⏳ Жди {diff.seconds // 3600}ч. {(diff.seconds // 60) % 60}мин.")

    card = await db.get_random_card()
    if not card: return await message.answer("База пуста.")
    
    has = await db.pool.fetchval("SELECT 1 FROM inventory WHERE user_id = $1 AND card_id = $2", message.from_user.id, card['card_id'])
    cfg = RARITY_CONFIG.get(card['rarity'], {"reward": 500})
    await db.set_cooldown(message.from_user.id, 'last_drop')

    if has:
        sell = int(cfg['reward'] * 0.5)
        await db.update_stars(message.from_user.id, sell)
        await message.answer_photo(card['photo_id'], caption=format_card_caption(card) + f"\n\n♻️ Дубликат продан за {sell} 🌟")
    else:
        await db.pool.execute("INSERT INTO inventory (user_id, card_id) VALUES ($1, $2)", message.from_user.id, card['card_id'])
        await db.update_stars(message.from_user.id, cfg['reward'])
        await message.answer_photo(card['photo_id'], caption=format_card_caption(card))

@dp.message(F.text == "👤 Профиль")
async def view_profile(message: types.Message, db: Database):
    u = await db.get_user(message.from_user.id)
    cnt = await db.pool.fetchval("SELECT COUNT(*) FROM inventory WHERE user_id = $1", message.from_user.id)
    st = "VIP" if u.get('vip_until') and u['vip_until'] > datetime.now() else "Обычный"
    
    # Генерация фото (предположим, функция готова)
    try:
        photos = await bot.get_user_profile_photos(message.from_user.id, limit=1)
        ava = (await bot.download_file((await bot.get_file(photos.photos[0][0].file_id)).file_path)).read() if photos.total_count > 0 else None
        img = await generate_profile_image(ava, u['username'], u['stars'], cnt, st)
        await message.answer_photo(BufferedInputFile(img.read(), "p.png"), caption=f"👤 Профиль: {u['username']}\n💰 Звезды: {u['stars']}\n👑 Статус: {st}")
    except:
        await message.answer(f"👤 Профиль: {u['username']}\n💰 Звезды: {u['stars']}\n👑 Статус: {st}")

@dp.message(F.text == "📊 ТОП-10")
async def leaderboard(message: types.Message, db: Database):
    rows = await db.pool.fetch("SELECT username, stars FROM users ORDER BY stars DESC LIMIT 10")
    txt = "🏆 ТОП ИГРОКОВ:\n\n" + "\n".join([f"{i+1}. {r['username']} — {r['stars']} 🌟" for i, r in enumerate(rows)])
    await message.answer(txt)

# --- ЗАПУСК ---
async def main():
    asyncio.create_task(start_web_server())
    pool = await asyncpg.create_pool(DATABASE_URL, ssl='require')
    db = Database(pool)
    await db.create_tables()
    
    # Проверка новых таблиц
    async with pool.acquire() as conn:
        await conn.execute("CREATE TABLE IF NOT EXISTS promocodes (code TEXT PRIMARY KEY, stars INT, max_uses INT, current_uses INT)")
        await conn.execute("CREATE TABLE IF NOT EXISTS used_promos (user_id BIGINT, code TEXT)")
        await conn.execute("CREATE TABLE IF NOT EXISTS active_trades (code TEXT PRIMARY KEY, user_a BIGINT, card_a INT)")
        await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_bonus TIMESTAMP")

    dp["db"] = db
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
