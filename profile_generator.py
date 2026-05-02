import io
import os
import aiohttp
from PIL import Image, ImageDraw, ImageFont, ImageOps
import asyncio

# --- КОНФИГУРАЦИЯ ---
TEMPLATE_PATH = "profile_template.png"
FONT_PATH = "font.ttf"

# Цвета
THEME_LABEL_COLOR = "#CCFFCC" # Светло-зеленый (в тон сетке)
VALUE_COLOR = "#FFFFFF"       # Белый
VIP_VALUE_COLOR = "#FFD700"   # Золотой

# Кэш шаблона и шрифтов (загружаем один раз на старте)
try:
    BASE_TEMPLATE = Image.open(TEMPLATE_PATH).convert("RGBA")
    FONT_PATH_NICK = FONT_PATH
    FONT_PATH_STATS = FONT_PATH
except:
    print("⚠️ Шаблон или шрифт не найдены. Убедитесь, что они есть в папке.")
    BASE_TEMPLATE = None

async def generate_profile_image(avatar_url, nickname, stars, cards_count, status):
    \"\"\"
    Генерирует оптимизированное изображение профиля.
    \"\"\"
    if BASE_TEMPLATE is None:
        raise FileNotFoundError(TEMPLATE_PATH)
    
    # Делаем копию шаблона
    bg = BASE_TEMPLATE.copy()
    draw = ImageDraw.Draw(bg)

    # Настройка шрифтов (с меньшими размерами)
    try:
        font_nick = ImageFont.truetype(FONT_PATH_NICK, 36)    # Было 48
        font_label = ImageFont.truetype(FONT_PATH_STATS, 20)  # Было 28
        font_val = ImageFont.truetype(FONT_PATH_STATS, 26)    # Было 38
    except OSError:
        font_nick = font_label = font_val = ImageFont.load_default()

    # --- Обработка Аватарки ---
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(avatar_url) as resp:
                if resp.status == 200:
                    ava_data = await resp.read()
                    ava = Image.open(io.BytesIO(ava_data)).convert("RGBA")
                    # Размер под круг (146x146)
                    ava = ava.resize((146, 146), Image.Resampling.LANCZOS)
                    # Круглая маска
                    mask = Image.new('L', (146, 146), 0)
                    ImageDraw.Draw(mask).ellipse((0, 0, 146, 146), fill=255)
                    # Пастим в центр белого круга шаблона
                    # Pillow paste uses top-left: circle center (195,188), r=73. paste point (122,115)
                    bg.paste(ava, (122, 115), mask)
        except Exception as e:
            print(f"⚠️ Ошибка Pillow при обработке аватарки: {e}")

    # --- Отрисовка данных (Fix Coordinates & Smaller Fonts) ---
    # Никнейм (smaller and shifted slightly to fit boundary nicely)
    draw.text((280, 160), nickname, font=font_nick, fill=VALUE_COLOR)

    # Координаты X для центров колонок (Centered under icons)
    STAR_COLUMN_X = 267
    CARD_COLUMN_X = 513
    USER_COLUMN_X = 758

    # Новые вертикальные координаты (ПОДНЯТЫ ВВЕРХ)
    LABEL_Y = 390  # Было 400
    VALUE_Y = 435  # Было 450

    # Блок Звёзд
    draw.text((STAR_COLUMN_X, LABEL_Y), "Баланс Звёзд:", font=font_label, fill=THEME_LABEL_COLOR, anchor="mm")
    stars_str = f"{stars:,}".replace(",", " ") # Формат 10 000
    draw.text((STAR_COLUMN_X, VALUE_Y), stars_str, font=font_val, fill=VALUE_COLOR, anchor="mm")

    # Блок Карт
    draw.text((CARD_COLUMN_X, LABEL_Y), "Количество Карт:", font=font_label, fill=THEME_LABEL_COLOR, anchor="mm")
    draw.text((CARD_COLUMN_X, VALUE_Y), str(cards_count), font=font_val, fill=VALUE_COLOR, anchor="mm")

    # Блок Статуса
    draw.text((USER_COLUMN_X, LABEL_Y), "Статус:", font=font_label, fill=THEME_LABEL_COLOR, anchor="mm")
    # Золотой цвет для VIP
    stat_col = VIP_VALUE_COLOR if status.lower() == "vip" else VALUE_COLOR
    draw.text((USER_COLUMN_X, VALUE_Y), status.capitalize(), font=font_val, fill=stat_col, anchor="mm")

    buf = io.BytesIO()
    bg.save(buf, format='PNG')
    buf.seek(0)
    return buf
