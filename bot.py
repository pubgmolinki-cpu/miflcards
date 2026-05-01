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
ADMIN_IDS = [1866813859] # ВПИШИ СЮДА СВОЙ ID

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

# --- ПОСТОЯННОЕ МЕНЮ (Reply) ---
def main_reply_keyboard():
    kb = [
        [types.KeyboardButton(text="🎁 Получить Карту")],
        [types.KeyboardButton(text="⚽ Мини Игры"), types.KeyboardButton(text="🛒 Магазин")],
        [types.KeyboardButton(text="👤 Профиль"), types.KeyboardButton(text="👥 Рефералы")],
        [types.KeyboardButton(text="📊 ТОП-10")]
    ]
    return types.ReplyKeyboardMarkup(
        keyboard=kb, 
        resize_keyboard=True, 
        input_field_placeholder="Выбери действие..."
    )

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
        return await message.answer(f"⏳ <b>Рано!</b> Следующая карта будет доступна через {hours} ч. {mins} мин.", parse_mode="HTML")

    card = await db.get_random_card()
    if not card: return await message.answer("❌ База карт пока пуста.")
    
    await db.add_card_to_inventory(user_id, card['card_id'])
    await db.set_cooldown(user_id, 'last_free_card')
    
    caption = (
        "🎁 <b>БЕСПЛАТНАЯ КАРТА</b>\n\n"
        f"👤 <b>Имя:</b> {card['name'] or 'Неизвестно'}\n"
        f"⭐ <b>Рейтинг:</b> {card['rating']}\n"
        f"🛡 <b>Клуб:</b> {card['club'] or 'Неизвестно'}\n"
        f"📍 <b>Позиция:</b> {card['position'] or 'Неизвестно'}\n"
        f"💎 <b>Редкость:</b> {card['rarity'] or 'Неизвестно'}"
    )
    await message.answer_photo(card['photo_id'], caption=caption, parse_mode="HTML")

# ==========================================
# 2. МИНИ-ИГРЫ
# ==========================================
@dp.message(F.text == "⚽ Мини Игры")
async def handle_mini_games(message: types.Message):
    kb = [[types.InlineKeyboardButton(text="🧩 Угадайка", callback_data="play_guess")]]
    markup = types.InlineKeyboardMarkup(inline_keyboard=kb)
    await message.answer("⚽ <b>Раздел Мини Игр</b>\n\nВыбери игру из списка ниже:", reply_markup=markup, parse_mode="HTML")

@dp.callback_query(F.data == "play_guess")
async def start_guess_game(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.answer("🚧 Игра «Угадайка» в разработке!")

# ==========================================
# 3. МАГАЗИН ПАКОВ
# ==========================================
@dp.message(F.text == "🛒 Магазин")
async def handle_shop(message: types.Message):
    kb = [
        [types.InlineKeyboardButton(text="👑 VIP (1 день) — 20,000🌟", callback_data="buy_vip")],
        [types.InlineKeyboardButton(text="🟡 One Pack — 3,500🌟", callback_data="buy_pack_One")],
        [types.InlineKeyboardButton(text="🟣 Chase Pack — 2,800🌟", callback_data="buy_pack_Chase")],
        [types.InlineKeyboardButton(text="🟢 Drop Pack — 2,000🌟", callback_data="buy_pack_Drop")],
        [types.InlineKeyboardButton(text="🔵 Series Pack — 1,200🌟", callback_data="buy_pack_Series")],
        [types.InlineKeyboardButton(text="⚪ Stock Pack — 500🌟", callback_data="buy_pack_Stock")]
    ]
    markup = types.InlineKeyboardMarkup(inline_keyboard=kb)
    await message.answer("🛒 <b>МАГАЗИН MIFL CARDS</b>\n\nВыбери пак, чтобы гарантированно получить карту указанной редкости:", reply_markup=markup, parse_mode="HTML")

@dp.callback_query(F.data.startswith("buy_pack_"))
async def process_buy_pack(callback: types.CallbackQuery, db: Database):
    rarity = callback.data.split("_")[2]
    prices = {"One": 3500, "Chase": 2800, "Drop": 2000, "Series": 1200, "Stock": 500}
    price = prices.get(rarity, 0)
    
    user = await db.get_user(callback.from_user.id)
    if user['stars'] < price:
        return await callback.answer(f"❌ Недостаточно звезд! Нужно {price} 🌟", show_alert=True)
    
    card = await db.get_random_card(rarity=rarity)
    if not card:
        return await callback.answer(f"❌ Карт редкости {rarity} пока нет в базе!", show_alert=True)
        
    await db.update_stars(callback.from_user.id, -price)
    await db.add_card_to_inventory(callback.from_user.id, card['card_id'])
    
    caption = (
        f"🎉 <b>УСПЕШНАЯ ПОКУПКА!</b>\n\n"
        f"Тебе выпала карта из <b>{rarity} Pack</b>:\n"
        f"👤 <b>Имя:</b> {card['name'] or 'Неизвестно'}\n"
        f"⭐ <b>Рейтинг:</b> {card['rating']}\n"
        f"🛡 <b>Клуб:</b> {card['club'] or 'Неизвестно'}\n"
        f"📍 <b>Позиция:</b> {card['position'] or 'Неизвестно'}\n"
        f"💎 <b>Редкость:</b> {card['rarity'] or 'Неизвестно'}"
    )
    await callback.message.answer_photo(card['photo_id'], caption=caption, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "buy_vip")
async def buy_vip(callback: types.CallbackQuery, db: Database):
    user = await db.get_user(callback.from_user.id)
    if user['stars'] < 20000:
        return await callback.answer("❌ Недостаточно звезд для VIP!", show_alert=True)
    
    await db.update_stars(callback.from_user.id, -20000)
    new_vip_date = datetime.now() + timedelta(days=1)
    await db.pool.execute("UPDATE users SET vip_until = $1 WHERE user_id = $2", new_vip_date, callback.from_user.id)
    
    await callback.message.answer("👑 <b>Поздравляем!</b> Вы приобрели VIP-статус на 1 день. Кулдаун снижен до 2 часов!", parse_mode="HTML")
    await callback.answer()

# ==========================================
# 4. ПРОФИЛЬ, ТОП-10 И РЕФЕРАЛЫ
# ==========================================
@dp.message(F.text == "👤 Профиль")
async def handle_profile(message: types.Message, db: Database):
    u = await db.get_user(message.from_user.id)
    is_v = "👑 VIP" if await db.is_vip(message.from_user.id) else "👤 Обычный"
    cards_count = await db.pool.fetchval("SELECT COUNT(*) FROM inventory WHERE user_id = $1", message.from_user.id)
    
    txt = (
        f"👤 <b>ТВОЙ ПРОФИЛЬ</b>\n\n"
        f"💰 <b>Баланс:</b> {u['stars']} 🌟\n"
        f"💎 <b>Статус:</b> {is_v}\n"
        f"🎴 <b>Собрано карт:</b> {cards_count} шт."
    )
    await message.answer(txt, parse_mode="HTML")

@dp.message(F.text == "📊 ТОП-10")
async def show_top10(message: types.Message, db: Database):
    top_users = await db.get_top_10()
    if not top_users:
        return await message.answer("📊 Топ пока пуст.")
        
    text = "📊 <b>ТОП-10 БОГАЧЕЙ MIFL CARDS:</b>\n\n"
    medals = ["🥇", "🥈", "🥉"]
    
    for i, user in enumerate(top_users):
        place = medals[i] if i < 3 else f"<b>{i+1}.</b>"
        text += f"{place} {user['username']} — {user['stars']} 🌟\n"
        
    await message.answer(text, parse_mode="HTML")

@dp.message(F.text == "👥 Рефералы")
async def show_refs(message: types.Message, db: Database):
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={message.from_user.id}"
    refs_count = await db.pool.fetchval("SELECT COUNT(*) FROM users WHERE referrer_id = $1", message.from_user.id)
    
    text = (
        f"👥 <b>РЕФЕРАЛЬНАЯ СИСТЕМА</b>\n\n"
        f"Приглашай друзей и получай звезды!\n\n"
        f"🔗 <b>Твоя ссылка:</b>\n<code>{ref_link}</code>\n\n"
        f"📈 <b>Ты пригласил:</b> {refs_count} чел."
    )
    await message.answer(text, parse_mode="HTML")

# ==========================================
# 5. АДМИНКА (ДОБАВЛЕНИЕ И ОЧИСТКА)
# ==========================================
@dp.message(F.photo, F.from_user.id.in_(ADMIN_IDS))
async def admin_photo(message: types.Message):
    admin_photo_storage[message.from_user.id] = message.photo[-1].file_id
    await message.answer("📸 Фото принято! Жду команду:\n<code>/add_player Имя, Рейтинг, Клуб, Позиция, Редкость</code>", parse_mode="HTML")

@dp.message(Command("add_player"), F.from_user.id.in_(ADMIN_IDS))
async def add_player(message: types.Message, command: CommandObject, db: Database):
    p_id = admin_photo_storage.get(message.from_user.id)
    if not p_id: return await message.answer("❌ Сначала отправь фото!")
    if not command.args: return await message.answer("❌ Нет аргументов!")
    
    try:
        args = [a.strip() for a in command.args.split(",")]
        if len(args) < 5:
            return await message.answer("❌ Нужно ровно 5 параметров через запятую!")
            
        name, rating, club, position, rarity = args
        
        # Проверка, чтобы случайно не записать пустоту
        if not name or not club or not position:
            return await message.answer("❌ Имя, Клуб и Позиция не могут быть пустыми!")
            
        await db.pool.execute(
            "INSERT INTO mifl_cards (name, rating, club, position, rarity, photo_id) VALUES ($1, $2, $3, $4, $5, $6)",
            name, float(rating), club, position, rarity, p_id
        )
        del admin_photo_storage[message.from_user.id]
        await message.answer(f"✅ Карта <b>{name}</b> успешно добавлена в базу!", parse_mode="HTML")
    except Exception as e: 
        await message.answer(f"❌ Ошибка в формате. Детали: {e}")

@dp.message(Command("clear_cards"), F.from_user.id.in_(ADMIN_IDS))
async def clear_cards(message: types.Message, db: Database):
    # Эта команда полностью удалит все сломанные карты из базы
    await db.pool.execute("DELETE FROM inventory")
    await db.pool.execute("DELETE FROM mifl_cards")
    await message.answer("🧹 <b>База карт полностью очищена!</b> Теперь можешь добавлять их заново правильно.", parse_mode="HTML")

@dp.message(Command("start"))
async def cmd_start(message: types.Message, db: Database, command: CommandObject):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    
    referrer_id = None
    if command.args and command.args.isdigit():
        referrer_id = int(command.args)
        if referrer_id == user_id: referrer_id = None

    try:
        await db.pool.execute(
            "INSERT INTO users (user_id, username, referrer_id) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
            user_id, username, referrer_id
        )
    except: pass

    await message.answer(
        f"⚽ Добро пожаловать, <b>{username}</b>! Ты в MIFL CARDS.\nИспользуй меню снизу для навигации.", 
        reply_markup=main_reply_keyboard(),
        parse_mode="HTML"
    )

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
