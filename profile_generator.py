import io
import os
import aiohttp
from PIL import Image, ImageDraw, ImageFont, ImageOps

# Пути к файлам
TEMPLATE_PATH = "profile_template.png"
FONT_PATH = "font.ttf"

# Кэшируем шаблон, чтобы не читать его с диска каждый раз
BASE_TEMPLATE = None
if os.path.exists(TEMPLATE_PATH):
    BASE_TEMPLATE = Image.open(TEMPLATE_PATH).convert("RGBA")

async def generate_profile_image(avatar_data, nickname, stars, cards_count, status):
    if BASE_TEMPLATE is None:
        return None
    
    bg = BASE_TEMPLATE.copy()
    draw = ImageDraw.Draw(bg)

    # Настройка шрифтов (уменьшенные размеры)
    try:
        font_nick = ImageFont.truetype(FONT_PATH, 34)
        font_label = ImageFont.truetype(FONT_PATH, 18)
        font_val = ImageFont.truetype(FONT_PATH, 24)
    except:
        font_nick = font_label = font_val = ImageFont.load_default()

    # Вставка аватарки (слева сверху)
    if avatar_data:
        try:
            ava = Image.open(io.BytesIO(avatar_data)).convert("RGBA")
            ava = ava.resize((140, 140), Image.Resampling.LANCZOS)
            mask = Image.new('L', (140, 140), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, 140, 140), fill=255)
            bg.paste(ava, (125, 118), mask) # Точные координаты под круг
        except:
            pass

    # Отрисовка ника
    draw.text((285, 165), str(nickname), font=font_nick, fill="white")

    # Координаты статистики (подняты выше по Y)
    LABEL_Y = 385 
    VALUE_Y = 425
    
    # Колонки X
    col_stars = 267
    col_cards = 513
    col_status = 758

    # Баланс
    draw.text((col_stars, LABEL_Y), "Баланс Звёзд:", font=font_label, fill="#CCFFCC", anchor="mm")
    draw.text((col_stars, VALUE_Y), f"{stars:,}".replace(",", " "), font=font_val, fill="white", anchor="mm")

    # Карты
    draw.text((col_cards, LABEL_Y), "Количество Карт:", font=font_label, fill="#CCFFCC", anchor="mm")
    draw.text((col_cards, VALUE_Y), str(cards_count), font=font_val, fill="white", anchor="mm")

    # Статус
    draw.text((col_status, LABEL_Y), "Статус:", font=font_label, fill="#CCFFCC", anchor="mm")
    status_color = "#FFD700" if status == "VIP" else "white"
    draw.text((col_status, VALUE_Y), str(status), font=font_val, fill=status_color, anchor="mm")

    buf = io.BytesIO()
    bg.save(buf, format='PNG')
    buf.seek(0)
    return buf
