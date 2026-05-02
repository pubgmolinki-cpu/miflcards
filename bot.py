import os
import asyncio
import random
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from database import Database
import asyncpg
from aiohttp import web

# --- КОНФИГУРАЦИЯ ---
TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_IDS = [1866813859]  # ЗАМЕНИ НА СВОЙ ID

bot = Bot(token=TOKEN)
dp = Dispatcher()
admin_photo_storage = {}

# --- СОСТОЯНИЯ ДЛЯ МИНИ-ИГР ---
class GuessGame(StatesGroup):
    bet = State()
    guess = State()

# --- ВЕБ-СЕРВЕР ДЛЯ RENDER ---
async def handle(request):
    return web.Response(text="MIFL CARDS is Running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

# --- ЛОГИКА РЕДКОСТИ И БОНУСОВ ---
def get_rarity(rating: float) -> str:
    if rating <= 1.5: return "Stock"
    if rating <= 2.5: return "Series"
    if rating <= 3.5: return "Drop"
    if rating <= 4.5: return "Chase"
    return "One"

def get_dynamic_bonus(rating: float) -> int:
    """Выдает рандомный бонус в зависимости от рейтинга"""
    if rating <= 2.0: return random.randint(67, 1000)
    if rating <= 3.5: return random.randint(670, 1400)
    if rating <= 4.5: return random.randint(1100, 1900)
    return random.randint(1700, 2500)

def main_reply_keyboard():
    kb = [
        [types.KeyboardButton(text="🎁 Получить Карту")],
        [types.KeyboardButton(text="⚽ Мини Игры"), types.KeyboardButton(text="🛒 Магазин")],
        [types.KeyboardButton(text="👤 Профиль"), types.KeyboardButton(text="👥 Рефералы")],
        [types.KeyboardButton(text="📊 ТОП-10")]
    ]
    return types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

# ==========================================
# 1. ПОЛУЧЕНИЕ БЕСПЛАТНОЙ КАРТЫ (С АНИМАЦИЕЙ)
# ==========================================
@dp.message(F.text == "🎁 Получить Карту")
async def handle_get_card(message: types.Message, db: Database):
    user_id = message.from_user.id
    u = await db.get_user(user_id)
    is_vip = await db.is_vip(user_id)
    cd = 2 if is_vip else 4
    
    if u['last_free_card'] and datetime.now() < u['last_free_card'] + timedelta(hours=cd):
        diff = (u['last_free_card'] + timedelta(hours=cd)) - datetime.now()
        hours, remainder = divmod(int(diff.total_seconds()), 3600)
        mins, _ = divmod(remainder, 60)
        return await message.answer(f"⏳ <b>Рано!</b> Доступно через: {hours}ч {mins}мин.", parse_mode="HTML")

    card = await db.get_random_card()
    if not card: return await message.answer("❌ База карт пуста.")
    
    # Анимация открытия
    anim_msg = await message.answer("Открываем пак 📦...")
    await asyncio.sleep(2.5)
    await anim_msg.delete()
    
    bonus = get_dynamic_bonus(card['rating'])
    await db.update_stars(user_id, bonus)
    await db.add_card_to_inventory(user_id, card['card_id'])
    await db.set_cooldown(user_id, 'last_free_card')
    
    caption = (
        "🎁 <b>БЕСПЛАТНАЯ КАРТА</b>\n\n"
        f"👤 <b>Имя:</b> {card['name']}\n"
        f"⭐ <b>Рейтинг:</b> {card['rating']}\n"
        f"🛡 <b>Клуб:</b> {card['club']}\n"
        f"📍 <b>Позиция:</b> {card['position']}\n"
        f"💎 <b>Редкость:</b> {card['rarity']}\n\n"
        f"💰 <b>Бонус:</b> +{bonus} 🌟"
    )
    await message.answer_photo(card['photo_id'], caption=caption, parse_mode="HTML")

# ==========================================
# 2. МАГАЗИН ПАКОВ
# ==========================================
@dp.message(F.text == "🛒 Магазин")
async def handle_shop(message: types.Message):
    kb = [
        [types.InlineKeyboardButton(text="🟡 One Pack — 3,500🌟", callback_data="buy_pack_One")],
        [types.InlineKeyboardButton(text="🟣 Chase Pack — 2,800🌟", callback_data="buy_pack_Chase")],
        [types.InlineKeyboardButton(text="🔴 Drop Pack — 2,000🌟", callback_data="buy_pack_Drop")],
        [types.InlineKeyboardButton(text="🔵 Series Pack — 1,200🌟", callback_data="buy_pack_Series")],
        [types.InlineKeyboardButton(text="🟢 Stock Pack — 500🌟", callback_data="buy_pack_Stock")],
        [types.InlineKeyboardButton(text="👑 VIP (1 день) — 20,000🌟", callback_data="buy_vip")]
    ]
    markup = types.InlineKeyboardMarkup(inline_keyboard=kb)
    await message.answer("🛒 <b>МАГАЗИН ПАКОВ</b>", reply_markup=markup, parse_mode="HTML")

@dp.callback_query(F.data == "buy_vip")
async def process_buy_vip(callback: types.CallbackQuery, db: Database):
    price = 20000
    user = await db.get_user(callback.from_user.id)
    if user['stars'] < price:
        return await callback.answer("❌ Недостаточно звёзд для покупки VIP!", show_alert=True)
    
    await db.update_stars(callback.from_user.id, -price)
    # Тут можно добавить логику записи VIP-статуса в базу, например db.set_vip(callback.from_user.id, days=1)
    await callback.message.answer("👑 <b>Поздравляем!</b> Вы приобрели VIP-статус на 1 день!", parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("buy_pack_"))
async def process_buy_pack(callback: types.CallbackQuery, db: Database):
    rarity = callback.data.split("_")[2]
    prices = {"One": 3500, "Chase": 2800, "Drop": 2000, "Series": 1200, "Stock": 500}
    price = prices[rarity]
    
    user = await db.get_user(callback.from_user.id)
    if user['stars'] < price:
        return await callback.answer(f"❌ Нужно {price} 🌟", show_alert=True)
    
    card = await db.get_random_card(rarity=rarity)
    if not card: return await callback.answer(f"❌ Карт {rarity} нет в наличии!", show_alert=True)
    
    # Списываем цену за пак
    await db.update_stars(callback.from_user.id, -price)
    
    await callback.message.delete()
    anim_msg = await callback.message.answer(f"Открываем {rarity} Pack 📦...")
    await asyncio.sleep(2.5)
    await anim_msg.delete()
        
    bonus = get_dynamic_bonus(card['rating'])
    await db.update_stars(callback.from_user.id, bonus)
    await db.add_card_to_inventory(callback.from_user.id, card['card_id'])
    
    caption = (
        f"🎉 <b>{rarity.upper()} PACK ОТКРЫТ!</b>\n\n"
        f"👤 <b>Имя:</b> {card['name']}\n"
        f"⭐ <b>Рейтинг:</b> {card['rating']}\n"
        f"💎 <b>Редкость:</b> {card['rarity']}\n\n"
        f"💰 <b>Выпал бонус:</b> +{bonus} 🌟"
    )
    await callback.message.answer_photo(card['photo_id'], caption=caption, parse_mode="HTML")
    await callback.answer()

# ==========================================
# 3. МИНИ-ИГРА: УГАДАЙКА
# ==========================================
@dp.message(F.text == "⚽ Мини Игры")
async def handle_mini_games(message: types.Message):
    kb = [[types.InlineKeyboardButton(text="🧩 Угадайка", callback_data="play_guess")]]
    await message.answer("⚽ <b>Мини Игры</b>\nВыбери игру:", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@dp.callback_query(F.data == "play_guess")
async def start_guess(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("🧩 <b>УГАДАЙКА</b>\nВведи сумму ставки (максимум 25,000 🌟):", parse_mode="HTML")
    await state.set_state(GuessGame.bet)
    await callback.answer()

@dp.message(GuessGame.bet)
async def process_bet(message: types.Message, state: FSMContext, db: Database):
    if not message.text.isdigit():
        return await message.answer("❌ Введите число!")
    
    bet = int(message.text)
    if bet > 25000:
        return await message.answer("❌ Максимальная ставка — 25 000 🌟!")
    if bet <= 0:
        return await message.answer("❌ Ставка должна быть больше нуля!")
        
    user = await db.get_user(message.from_user.id)
    if user['stars'] < bet:
        return await message.answer("❌ У вас недостаточно звёзд!")
        
    card = await db.get_random_card()
    if not card: return await message.answer("❌ В базе нет карт для игры.")

    # Списываем ставку
    await db.update_stars(message.from_user.id, -bet)
    
    coefs = {"Stock": 1.2, "Series": 1.5, "Drop": 1.8, "Chase": 2.1, "One": 2.5}
    coef = coefs.get(card['rarity'], 1.0)
    end_time = datetime.now() + timedelta(seconds=60)
    
    await state.update_data(bet=bet, card_name=card['name'], coef=coef, end_time=end_time.isoformat())
    await state.set_state(GuessGame.guess)
    
    txt = (
        f"🧩 <b>ИГРА НАЧАЛАСЬ</b> (Ставка: {bet} 🌟)\n\n"
        f"🛡 <b>Клуб:</b> {card['club']}\n"
        f"📍 <b>Позиция:</b> {card['position']}\n"
        f"💎 <b>Редкость:</b> {card['rarity']}\n\n"
        f"⏱ У тебя <b>60 секунд</b>! Напиши имя игрока в чат:"
    )
    await message.answer(txt, parse_mode="HTML")

@dp.message(GuessGame.guess)
async def process_guess(message: types.Message, state: FSMContext, db: Database):
    data = await state.get_data()
    end_time = datetime.fromisoformat(data['end_time'])
    
    if datetime.now() > end_time:
        await state.clear()
        return await message.answer(f"⏳ <b>Время вышло!</b> Правильный ответ: <b>{data['card_name']}</b>.\nСтавка сгорела.", parse_mode="HTML")
        
    if message.text.strip().lower() == data['card_name'].lower():
        win_amount = int(data['bet'] * data['coef'])
        await db.update_stars(message.from_user.id, win_amount)
        await message.answer(f"✅ <b>ВЕРНО!</b> Это {data['card_name']}.\nТвой выигрыш: <b>{win_amount} 🌟</b> (Множитель: x{data['coef']})", parse_mode="HTML")
    else:
        await message.answer(f"❌ <b>НЕВЕРНО!</b> Это был <b>{data['card_name']}</b>.\nСтавка сгорела.", parse_mode="HTML")
        
    await state.clear()

# ==========================================
# 4. ПРОФИЛЬ И РЕФЕРАЛЫ
# ==========================================
@dp.message(F.text == "👤 Профиль")
async def handle_profile(message: types.Message, db: Database):
    u = await db.get_user(message.from_user.id)
    is_v = "👑 VIP" if await db.is_vip(message.from_user.id) else "👤 Обычный"
    cards_count = await db.pool.fetchval("SELECT COUNT(*) FROM inventory WHERE user_id = $1", message.from_user.id)
    
    kb = [[types.InlineKeyboardButton(text="🎴 Моя коллекция", callback_data="my_collection")]]
    markup = types.InlineKeyboardMarkup(inline_keyboard=kb)
    
    txt = (
        f"👤 <b>ТВОЙ ПРОФИЛЬ</b>\n\n"
        f"💰 <b>Баланс:</b> {u['stars']} 🌟\n"
        f"💎 <b>Статус:</b> {is_v}\n"
        f"🎴 <b>Всего карт:</b> {cards_count} шт."
    )
    await message.answer(txt, reply_markup=markup, parse_mode="HTML")

@dp.message(F.text == "👥 Рефералы")
async def show_refs(message: types.Message):
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={message.from_user.id}"
    
    text = (
        f"👥 <b>ТВОЯ РЕФЕРАЛЬНАЯ СИСТЕМА</b>\n\n"
        f"Приглашай друзей и получай бонусы!\n"
        f"🔗 <b>Твоя ссылка:</b>\n<code>{ref_link}</code>"
    )
    await message.answer(text, parse_mode="HTML")

# Коллекция, Топ и Админка остались без изменений, как в прошлом коде
@dp.callback_query(F.data == "my_collection")
async def show_collection(callback: types.CallbackQuery, db: Database):
    query = """
        SELECT c.name, c.rarity, COUNT(*) as count 
        FROM inventory i JOIN mifl_cards c ON i.card_id = c.card_id
        WHERE i.user_id = $1 GROUP BY c.name, c.rarity
        ORDER BY CASE c.rarity WHEN 'One' THEN 1 WHEN 'Chase' THEN 2 WHEN 'Drop' THEN 3 WHEN 'Series' THEN 4 ELSE 5 END
    """
    cards = await db.pool.fetch(query, callback.from_user.id)
    if not cards: return await callback.answer("📭 Твоя коллекция пока пуста!", show_alert=True)
    
    icons = {"One": "🟡", "Chase": "🟣", "Drop": "🔴", "Series": "🔵", "Stock": "🟢"}
    text = "🎴 <b>ТВОЯ КОЛЛЕКЦИЯ:</b>\n\n"
    for c in cards:
        text += f"{icons.get(c['rarity'], '▫️')} {c['name']} {f'(x{c['count']})' if c['count']>1 else ''}\n"
    await callback.message.answer(text[:4000], parse_mode="HTML")
    await callback.answer()

@dp.message(F.text == "📊 ТОП-10")
async def show_top10(message: types.Message, db: Database):
    top = await db.get_top_10()
    text = "📊 <b>ТОП-10 БОГАТЕЙШИХ:</b>\n\n"
    for i, u in enumerate(top):
        text += f"{i+1}. {u['username']} — {u['stars']} 🌟\n"
    await message.answer(text, parse_mode="HTML")

@dp.message(F.photo, F.from_user.id.in_(ADMIN_IDS))
async def admin_photo(message: types.Message):
    admin_photo_storage[message.from_user.id] = message.photo[-1].file_id
    await message.answer("📸 Фото принято! Введи:\n<code>/add_player Имя, Рейтинг, Клуб, Позиция</code>", parse_mode="HTML")

@dp.message(Command("add_player"), F.from_user.id.in_(ADMIN_IDS))
async def add_player(message: types.Message, command: CommandObject, db: Database):
    p_id = admin_photo_storage.get(message.from_user.id)
    if not p_id: return await message.answer("❌ Сначала отправь фото!")
    try:
        args = [a.strip() for a in command.args.split(",")]
        name, rat, club, pos = args[0], float(args[1]), args[2], args[3]
        rarity = get_rarity(rat)
        await db.pool.execute(
            "INSERT INTO mifl_cards (name, rating, club, position, rarity, photo_id) VALUES ($1, $2, $3, $4, $5, $6)",
            name, rat, club, pos, rarity, p_id
        )
        del admin_photo_storage[message.from_user.id]
        await message.answer(f"✅ Карта <b>{name}</b> ({rarity}) добавлена.", parse_mode="HTML")
    except:
        await message.answer("❌ Ошибка формата!", parse_mode="HTML")

@dp.message(Command("start"))
async def cmd_start(message: types.Message, command: CommandObject, db: Database):
    # Логика рефералки при старте
    referrer_id = None
    if command.args and command.args.isdigit() and int(command.args) != message.from_user.id:
        referrer_id = int(command.args)

    await db.pool.execute("INSERT INTO users (user_id, username) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET username = $2", 
                         message.from_user.id, message.from_user.username or message.from_user.first_name)
    
    if referrer_id:
        # Начисляем бонус рефоводу (например, 500 звезд) - раскомментируй если нужно
        # await db.update_stars(referrer_id, 500) 
        pass
        
    await message.answer("⚽ Добро пожаловать в <b>MIFL CARDS</b>!", reply_markup=main_reply_keyboard(), parse_mode="HTML")

async def main():
    asyncio.create_task(start_web_server())
    pool = await asyncpg.create_pool(DATABASE_URL, ssl='require')
    db = Database(pool)
    await db.create_tables()
    dp["db"] = db
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
