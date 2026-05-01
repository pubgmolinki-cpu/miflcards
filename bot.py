import os
import asyncio
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandObject
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

# --- ЛОГИКА ОПРЕДЕЛЕНИЯ РЕДКОСТИ ---
def get_rarity(rating: float) -> str:
    if rating <= 1.5: return "Stock"
    if rating <= 2.5: return "Series"
    if rating <= 3.5: return "Drop"
    if rating <= 4.5: return "Chase"
    return "One"

def main_reply_keyboard():
    kb = [
        [types.KeyboardButton(text="🎁 Получить Карту")],
        [types.KeyboardButton(text="⚽ Мини Игры"), types.KeyboardButton(text="🛒 Магазин")],
        [types.KeyboardButton(text="👤 Профиль"), types.KeyboardButton(text="👥 Рефералы")],
        [types.KeyboardButton(text="📊 ТОП-10")]
    ]
    return types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

# ==========================================
# 1. ПОЛУЧЕНИЕ БЕСПЛАТНОЙ КАРТЫ
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
    
    await db.add_card_to_inventory(user_id, card['card_id'])
    await db.set_cooldown(user_id, 'last_free_card')
    
    caption = (
        "🎁 <b>БЕСПЛАТНАЯ КАРТА</b>\n\n"
        f"👤 <b>Имя:</b> {card['name']}\n"
        f"⭐ <b>Рейтинг:</b> {card['rating']}\n"
        f"🛡 <b>Клуб:</b> {card['club']}\n"
        f"📍 <b>Позиция:</b> {card['position']}\n"
        f"💎 <b>Редкость:</b> {card['rarity']}"
    )
    await message.answer_photo(card['photo_id'], caption=caption, parse_mode="HTML")

# ==========================================
# 2. МАГАЗИН ПАКОВ (С БОНУСАМИ)
# ==========================================
@dp.message(F.text == "🛒 Магазин")
async def handle_shop(message: types.Message):
    kb = [
        [types.InlineKeyboardButton(text="🟡 One Pack — 3,500🌟", callback_data="buy_pack_One")],
        [types.InlineKeyboardButton(text="🟣 Chase Pack — 2,800🌟", callback_data="buy_pack_Chase")],
        [types.InlineKeyboardButton(text="🔴 Drop Pack — 2,000🌟", callback_data="buy_pack_Drop")],
        [types.InlineKeyboardButton(text="🔵 Series Pack — 1,200🌟", callback_data="buy_pack_Series")],
        [types.InlineKeyboardButton(text="🟢 Stock Pack — 500🌟", callback_data="buy_pack_Stock")]
    ]
    markup = types.InlineKeyboardMarkup(inline_keyboard=kb)
    await message.answer("🛒 <b>МАГАЗИН ПАКОВ</b>\nВ каждом паке гарантированная редкость + бонусные звезды!", reply_markup=markup, parse_mode="HTML")

@dp.callback_query(F.data.startswith("buy_pack_"))
async def process_buy_pack(callback: types.CallbackQuery, db: Database):
    rarity = callback.data.split("_")[2]
    pack_settings = {
        "One": {"price": 3500, "bonus": 500},
        "Chase": {"price": 2800, "bonus": 300},
        "Drop": {"price": 2000, "bonus": 200},
        "Series": {"price": 1200, "bonus": 100},
        "Stock": {"price": 500, "bonus": 50}
    }
    conf = pack_settings[rarity]
    user = await db.get_user(callback.from_user.id)
    
    if user['stars'] < conf['price']:
        return await callback.answer(f"❌ Недостаточно звёзд! Нужно {conf['price']} 🌟", show_alert=True)
    
    card = await db.get_random_card(rarity=rarity)
    if not card: return await callback.answer(f"❌ Карт {rarity} нет в наличии!", show_alert=True)
        
    await db.update_stars(callback.from_user.id, conf['bonus'] - conf['price'])
    await db.add_card_to_inventory(callback.from_user.id, card['card_id'])
    
    caption = (
        f"🎉 <b>{rarity.upper()} PACK ОТКРЫТ!</b>\n\n"
        f"👤 <b>Имя:</b> {card['name']}\n"
        f"⭐ <b>Рейтинг:</b> {card['rating']}\n"
        f"💎 <b>Редкость:</b> {card['rarity']}\n\n"
        f"💰 <b>Бонус:</b> +{conf['bonus']} 🌟"
    )
    await callback.message.answer_photo(card['photo_id'], caption=caption, parse_mode="HTML")
    await callback.answer()

# ==========================================
# 3. ПРОФИЛЬ И КОЛЛЕКЦИЯ
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

# ==========================================
# 4. АДМИН-КОМАНДЫ (УПРАВЛЕНИЕ)
# ==========================================
@dp.message(F.photo, F.from_user.id.in_(ADMIN_IDS))
async def admin_photo(message: types.Message):
    admin_photo_storage[message.from_user.id] = message.photo[-1].file_id
    await message.answer("📸 Фото принято! Теперь введи данные:\n<code>/add_player Имя, Рейтинг, Клуб, Позиция</code>", parse_mode="HTML")

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
        await message.answer(f"✅ Успешно! Карта <b>{name}</b> ({rarity}) добавлена.", parse_mode="HTML")
    except:
        await message.answer("❌ Ошибка! Формат: <code>/add_player Месси, 5.0, Интер, ПФА</code>", parse_mode="HTML")

@dp.message(Command("clear_cards"), F.from_user.id.in_(ADMIN_IDS))
async def clear_cards(message: types.Message, db: Database):
    await db.pool.execute("DELETE FROM inventory")
    await db.pool.execute("DELETE FROM mifl_cards")
    await message.answer("🧹 База карт и все инвентари полностью очищены!", parse_mode="HTML")

@dp.message(Command("reset_progress"))
async def reset_progress(message: types.Message, db: Database):
    await db.pool.execute("DELETE FROM inventory WHERE user_id = $1", message.from_user.id)
    await db.pool.execute("UPDATE users SET stars = 500 WHERE user_id = $1", message.from_user.id)
    await message.answer("🔄 Весь твой прогресс обнулен!", parse_mode="HTML")

# ==========================================
# 5. ОСТАЛЬНОЕ (СТАРТ, ТОП)
# ==========================================
@dp.message(F.text == "📊 ТОП-10")
async def show_top10(message: types.Message, db: Database):
    top = await db.get_top_10()
    text = "📊 <b>ТОП-10 БОГАТЕЙШИХ:</b>\n\n"
    for i, u in enumerate(top):
        text += f"{i+1}. {u['username']} — {u['stars']} 🌟\n"
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("start"))
async def cmd_start(message: types.Message, db: Database):
    await db.pool.execute("INSERT INTO users (user_id, username) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET username = $2", 
                         message.from_user.id, message.from_user.username or message.from_user.first_name)
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
