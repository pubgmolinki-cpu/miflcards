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
ADMIN_IDS = [123456789] # ВПИШИ СВОЙ ID

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

# --- ЛОГИКА РЕДКОСТИ ---
def get_rarity(rating: float) -> str:
    if rating <= 1.5: return "Stock"
    if rating <= 2.5: return "Series"
    if rating <= 3.5: return "Drop"
    if rating <= 4.5: return "Chase"
    return "One"

# --- ПОСТОЯННОЕ МЕНЮ ---
def main_reply_keyboard():
    kb = [
        [types.KeyboardButton(text="🎁 Получить Карту")],
        [types.KeyboardButton(text="⚽ Мини Игры"), types.KeyboardButton(text="🛒 Магазин")],
        [types.KeyboardButton(text="👤 Профиль"), types.KeyboardButton(text="👥 Рефералы")],
        [types.KeyboardButton(text="📊 ТОП-10")]
    ]
    return types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

# ==========================================
# 1. МАГАЗИН (С БОНУСАМИ)
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
    await message.answer("🛒 <b>МАГАЗИН ПАКОВ</b>\n\nПри покупке пака вы получаете карту и <b>бонусные звезды</b>!", reply_markup=markup, parse_mode="HTML")

@dp.callback_query(F.data.startswith("buy_pack_"))
async def process_buy_pack(callback: types.CallbackQuery, db: Database):
    rarity = callback.data.split("_")[2]
    # Настройки: Цена и Бонус за открытие
    pack_settings = {
        "One": {"price": 3500, "bonus": 500},
        "Chase": {"price": 2800, "bonus": 300},
        "Drop": {"price": 2000, "bonus": 200},
        "Series": {"price": 1200, "bonus": 100},
        "Stock": {"price": 500, "bonus": 50}
    }
    
    conf = pack_settings.get(rarity)
    user = await db.get_user(callback.from_user.id)
    
    if user['stars'] < conf['price']:
        return await callback.answer(f"❌ Недостаточно звезд! Нужно {conf['price']} 🌟", show_alert=True)
    
    card = await db.get_random_card(rarity=rarity)
    if not card:
        return await callback.answer(f"❌ Карты {rarity} закончились!", show_alert=True)
        
    # Списываем цену, начисляем бонус
    total_change = conf['bonus'] - conf['price']
    await db.update_stars(callback.from_user.id, total_change)
    await db.add_card_to_inventory(callback.from_user.id, card['card_id'])
    
    caption = (
        f"🎉 <b>УСПЕШНАЯ ПОКУПКА!</b>\n\n"
        f"👤 <b>Имя:</b> {card['name']}\n"
        f"⭐ <b>Рейтинг:</b> {card['rating']}\n"
        f"🛡 <b>Клуб:</b> {card['club']}\n"
        f"📍 <b>Позиция:</b> {card['position']}\n"
        f"💎 <b>Редкость:</b> {card['rarity']}\n\n"
        f"💰 <b>Бонус за пак:</b> +{conf['bonus']} 🌟"
    )
    await callback.message.answer_photo(card['photo_id'], caption=caption, parse_mode="HTML")
    await callback.answer()

# ==========================================
# 2. АДМИНКА (АВТО-РЕДКОСТЬ)
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
        # Теперь ожидаем только 4 параметра
        args = [a.strip() for a in command.args.split(",")]
        name, rating_val, club, pos = args[0], float(args[1]), args[2], args[3]
        
        # Автоматически определяем редкость по рейтингу
        rarity = get_rarity(rating_val)
        
        await db.pool.execute(
            "INSERT INTO mifl_cards (name, rating, club, position, rarity, photo_id) VALUES ($1, $2, $3, $4, $5, $6)",
            name, rating_val, club, pos, rarity, p_id
        )
        del admin_photo_storage[message.from_user.id]
        await message.answer(f"✅ Добавлен: <b>{name}</b>\n⭐ Рейтинг: {rating_val}\n💎 Редкость: <b>{rarity}</b>", parse_mode="HTML")
    except:
        await message.answer("❌ Ошибка! Формат: <code>/add_player Имя, 4.5, Клуб, Позиция</code>", parse_mode="HTML")

# ==========================================
# ОСТАЛЬНЫЕ ФУНКЦИИ (БЕЗ ИЗМЕНЕНИЙ)
# ==========================================
@dp.message(F.text == "🎁 Получить Карту")
async def handle_get_card(message: types.Message, db: Database):
    user_id = message.from_user.id
    u = await db.get_user(user_id)
    is_vip = await db.is_vip(user_id)
    cd = 2 if is_vip else 4
    if u['last_free_card'] and datetime.now() < u['last_free_card'] + timedelta(hours=cd):
        diff = (u['last_free_card'] + timedelta(hours=cd)) - datetime.now()
        return await message.answer(f"⏳ Жди {int(diff.total_seconds()//60)} мин.")
    card = await db.get_random_card()
    if not card: return await message.answer("Пусто.")
    await db.add_card_to_inventory(user_id, card['card_id'])
    await db.set_cooldown(user_id, 'last_free_card')
    await message.answer_photo(card['photo_id'], caption=f"👤 {card['name']}\n⭐ {card['rating']}\n💎 {card['rarity']}", parse_mode="HTML")

@dp.message(F.text == "📊 ТОП-10")
async def show_top10(message: types.Message, db: Database):
    top = await db.get_top_10()
    txt = "📊 <b>ТОП БОГАЧЕЙ:</b>\n\n"
    for i, user in enumerate(top):
        txt += f"{i+1}. {user['username']} — {user['stars']} 🌟\n"
    await message.answer(txt, parse_mode="HTML")

@dp.message(Command("start"))
async def cmd_start(message: types.Message, db: Database):
    await db.pool.execute("INSERT INTO users (user_id, username) VALUES ($1, $2) ON CONFLICT DO NOTHING", 
                         message.from_user.id, message.from_user.username or message.from_user.first_name)
    await message.answer("⚽ Привет! Погнали играть.", reply_markup=main_reply_keyboard())

async def main():
    asyncio.create_task(start_web_server())
    pool = await asyncpg.create_pool(DATABASE_URL, ssl='require')
    db = Database(pool)
    await db.create_tables()
    dp["db"] = db
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
