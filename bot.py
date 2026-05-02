import os
import asyncio
import random
import io
import aiohttp
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile
from PIL import Image, ImageDraw, ImageFont, ImageOps
from aiohttp import web
import asyncpg

# Импортируем твой класс базы данных
from database import Database

# --- КОНФИГУРАЦИЯ ---
TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_IDS = [1866813859] # Замени на свой ID

bot = Bot(token=TOKEN)
dp = Dispatcher()
admin_photo_storage = {}

# --- СОСТОЯНИЯ (FSM) ---
class GuessGame(StatesGroup):
    bet = State()

# --- ВЕБ-СЕРВЕР ДЛЯ RENDER ---
async def handle(request):
    return web.Response(text="MIFL CARDS Bot is Running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def get_rarity(rating: float) -> str:
    if rating <= 1.5: return "Stock"
    if rating <= 2.5: return "Series"
    if rating <= 3.5: return "Drop"
    if rating <= 4.5: return "Chase"
    return "One"

def get_dynamic_bonus(rating: float) -> int:
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

# --- ГЕНЕРАЦИЯ ГРАФИЧЕСКОГО ПРОФИЛЯ ---
async def generate_profile_card(avatar_url, nickname, stars, cards_count, status):
    # Координаты из твоего ТЗ
    TEMPLATE_PATH = "profile_template.png"
    FONT_PATH = "font.ttf"
    
    bg = Image.open(TEMPLATE_PATH).convert("RGBA")
    draw = ImageDraw.Draw(bg)
    
    try:
        font_nick = ImageFont.truetype(FONT_PATH, 42)
        font_label = ImageFont.truetype(FONT_PATH, 24)
        font_val = ImageFont.truetype(FONT_PATH, 34)
    except:
        font_nick = font_label = font_val = ImageFont.load_default()

    # Вставка авы в белый круг (слева сверху)
    async with aiohttp.ClientSession() as session:
        async with session.get(avatar_url) as resp:
            if resp.status == 200:
                ava_data = await resp.read()
                ava = Image.open(io.BytesIO(ava_data)).convert("RGBA")
                ava = ava.resize((146, 146), Image.Resampling.LANCZOS)
                mask = Image.new('L', (146, 146), 0)
                ImageDraw.Draw(mask).ellipse((0, 0, 146, 146), fill=255)
                bg.paste(ava, (122, 115), mask)

    # Отрисовка данных
    draw.text((300, 160), nickname, font=font_nick, fill="white")
    
    # Колонки под эмодзи
    draw.text((267, 400), "Баланс Звёзд:", font=font_label, fill="#CCFFCC", anchor="mm")
    draw.text((267, 445), f"{stars:,}".replace(",", " "), font=font_val, fill="white", anchor="mm")
    
    draw.text((513, 400), "Количество Карт:", font=font_label, fill="#CCFFCC", anchor="mm")
    draw.text((513, 445), str(cards_count), font=font_val, fill="white", anchor="mm")
    
    draw.text((758, 400), "Статус:", font=font_label, fill="#CCFFCC", anchor="mm")
    stat_col = "#FFD700" if status == "VIP" else "white"
    draw.text((758, 445), status, font=font_val, fill=stat_col, anchor="mm")

    buf = io.BytesIO()
    bg.save(buf, format='PNG')
    buf.seek(0)
    return buf

# ==========================================
# ХЕНДЛЕРЫ
# ==========================================

@dp.message(Command("start"))
async def cmd_start(message: types.Message, command: CommandObject, db: Database):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    
    # Реферальная система
    ref_parent = None
    if command.args and command.args.isdigit():
        parent_id = int(command.args)
        if parent_id != user_id:
            ref_parent = parent_id

    await db.pool.execute(
        "INSERT INTO users (user_id, username, referrer_id) VALUES ($1, $2, $3) "
        "ON CONFLICT (user_id) DO UPDATE SET username = $2",
        user_id, username, ref_parent
    )
    
    await message.answer("⚽ Добро пожаловать в <b>MIFL CARDS</b>!", reply_markup=main_reply_keyboard(), parse_mode="HTML")

# --- ПРОФИЛЬ ---
@dp.message(F.text == "👤 Профиль")
async def handle_profile(message: types.Message, db: Database):
    u = await db.get_user(message.from_user.id)
    is_vip = await db.is_vip(message.from_user.id)
    cards_count = await db.pool.fetchval("SELECT COUNT(*) FROM inventory WHERE user_id = $1", message.from_user.id)
    
    status_txt = "VIP" if is_vip else "Обычный"
    
    # Получаем аватарку
    photos = await bot.get_user_profile_photos(message.from_user.id, limit=1)
    if photos.total_count > 0:
        file = await bot.get_file(photos.photos[0][0].file_id)
        ava_url = f"https://api.telegram.org/file/bot{TOKEN}/{file.file_path}"
    else:
        ava_url = "https://ui-avatars.com/api/?name=" + (message.from_user.username or "U")

    img_buf = await generate_profile_card(ava_url, u['username'], u['stars'], cards_count, status_txt)
    photo = BufferedInputFile(img_buf.read(), filename="profile.png")
    
    await message.answer_photo(photo, caption="📊 Ваша игровая статистика:", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🎴 Моя коллекция", callback_data="my_collection")]
    ]))

# --- БЕСПЛАТНАЯ КАРТА ---
@dp.message(F.text == "🎁 Получить Карту")
async def handle_free_card(message: types.Message, db: Database):
    user_id = message.from_user.id
    u = await db.get_user(user_id)
    is_vip = await db.is_vip(user_id)
    
    cd_hours = 2 if is_vip else 4
    if u['last_free_card'] and datetime.now() < u['last_free_card'] + timedelta(hours=cd_hours):
        diff = (u['last_free_card'] + timedelta(hours=cd_hours)) - datetime.now()
        return await message.answer(f"⏳ Доступно через {int(diff.total_seconds()//3600)}ч {int((diff.total_seconds()%3600)//60)}м")

    card = await db.get_random_card()
    if not card: return await message.answer("❌ Карт пока нет.")

    msg = await message.answer("Открываем пак 📦...")
    await asyncio.sleep(2.5)
    await msg.delete()

    bonus = get_dynamic_bonus(card['rating'])
    await db.update_stars(user_id, bonus)
    await db.add_card_to_inventory(user_id, card['card_id'])
    await db.set_cooldown(user_id, 'last_free_card')

    caption = f"🎁 <b>БЕСПЛАТНАЯ КАРТА</b>\n\n👤 {card['name']}\n⭐ Рейтинг: {card['rating']}\n💎 {card['rarity']}\n\n💰 Бонус: +{bonus} 🌟"
    await message.answer_photo(card['photo_id'], caption=caption, parse_mode="HTML")

# --- МАГАЗИН И VIP ---
@dp.message(F.text == "🛒 Магазин")
async def handle_shop(message: types.Message):
    kb = [
        [types.InlineKeyboardButton(text="🟡 One Pack — 3,500🌟", callback_data="buy_pack_One")],
        [types.InlineKeyboardButton(text="👑 VIP (1 день) — 20,000🌟", callback_data="buy_vip")]
    ]
    await message.answer("🛒 <b>МАГАЗИН</b>", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@dp.callback_query(F.data == "buy_vip")
async def buy_vip(callback: types.CallbackQuery, db: Database):
    u = await db.get_user(callback.from_user.id)
    if u['stars'] < 20000: return await callback.answer("❌ Недостаточно звёзд!", show_alert=True)
    
    await db.update_stars(callback.from_user.id, -20000)
    expiry = datetime.now() + timedelta(days=1)
    await db.pool.execute("UPDATE users SET vip_until = $1 WHERE user_id = $2", expiry, callback.from_user.id)
    await callback.message.answer("👑 <b>VIP активирован!</b> КД на всё снижено в 2 раза!")
    await callback.answer()

# --- МИНИ-ИГРА УГАДАЙКА ---
@dp.message(F.text == "⚽ Мини Игры")
async def games_menu(message: types.Message):
    kb = [[types.InlineKeyboardButton(text="🧩 Угадайка", callback_data="play_guess")]]
    await message.answer("⚽ Выбери игру:", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data == "play_guess")
async def start_guess(callback: types.CallbackQuery, db: Database, state: FSMContext):
    u = await db.get_user(callback.from_user.id)
    is_vip = await db.is_vip(callback.from_user.id)
    cd = 2 if is_vip else 4
    
    if u.get('last_game_guess') and datetime.now() < u['last_game_guess'] + timedelta(hours=cd):
        diff = (u['last_game_guess'] + timedelta(hours=cd)) - datetime.now()
        return await callback.answer(f"⏳ Доступно через {int(diff.total_seconds()//60)} мин.", show_alert=True)

    await callback.message.answer("🧩 Введите ставку (до 25,000 🌟):")
    await state.set_state(GuessGame.bet)
    await callback.answer()

@dp.message(GuessGame.bet)
async def process_bet(message: types.Message, state: FSMContext, db: Database):
    if not message.text.isdigit(): return
    bet = int(message.text)
    user = await db.get_user(message.from_user.id)
    if bet > 25000 or bet > user['stars']: return await message.answer("❌ Ошибка ставки.")

    card = await db.get_random_card()
    wrong = await db.pool.fetch("SELECT name FROM mifl_cards WHERE name != $1 ORDER BY RANDOM() LIMIT 3", card['name'])
    options = [card['name']] + [r['name'] for r in wrong]
    random.shuffle(options)
    
    coefs = {"Stock": 1.2, "Series": 1.5, "Drop": 1.8, "Chase": 2.1, "One": 2.5}
    c = coefs.get(card['rarity'], 1.0)
    
    kb = [[types.InlineKeyboardButton(text=opt, callback_data=f"ans_{'w' if opt==card['name'] else 'l'}_{bet}_{card['card_id']}")] for opt in options]
    
    await db.update_stars(message.from_user.id, -bet)
    await db.set_cooldown(message.from_user.id, 'last_game_guess')
    
    await message.answer(f"🧩 <b>КТО ЭТО?</b>\n⭐ Рейтинг: {card['rating']}\n🛡 Клуб: {card['club']}\n📈 Коэф: x{c}\n⏱ 60 секунд!", 
                         reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    await state.clear()

@dp.callback_query(F.data.startswith("ans_"))
async def check_guess(callback: types.CallbackQuery, db: Database):
    _, res, bet, c_id = callback.data.split("_")
    card = await db.pool.fetchrow("SELECT * FROM mifl_cards WHERE card_id = $1", int(c_id))
    
    if res == 'w':
        coefs = {"Stock": 1.2, "Series": 1.5, "Drop": 1.8, "Chase": 2.1, "One": 2.5}
        win = int(int(bet) * coefs.get(card['rarity'], 1.0))
        await db.update_stars(callback.from_user.id, win)
        await callback.message.delete()
        await callback.message.answer_photo(card['photo_id'], caption=f"✅ <b>ВЕРНО!</b>\nВыиграно: {win} 🌟")
    else:
        await callback.message.edit_text(f"❌ Неверно! Это был {card['name']}.")
    await callback.answer()

# --- ОСТАЛЬНЫЕ ФУНКЦИИ (ТОП, РЕФЕРАЛЫ) ---
@dp.message(F.text == "👥 Рефералы")
async def show_refs(message: types.Message):
    me = await bot.get_me()
    await message.answer(f"🔗 Ссылка:\n<code>t.me/{me.username}?start={message.from_user.id}</code>", parse_mode="HTML")

@dp.message(F.text == "📊 ТОП-10")
async def show_top(message: types.Message, db: Database):
    top = await db.pool.fetch("SELECT username, stars FROM users ORDER BY stars DESC LIMIT 10")
    txt = "📊 <b>ТОП БОГАТЕЕВ:</b>\n\n"
    for i, r in enumerate(top): txt += f"{i+1}. {r['username']} — {r['stars']} 🌟\n"
    await message.answer(txt, parse_mode="HTML")

# --- ЗАПУСК ---
async def main():
    asyncio.create_task(start_web_server())
    pool = await asyncpg.create_pool(DATABASE_URL, ssl='require')
    db = Database(pool)
    await db.create_tables()
    dp["db"] = db
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
