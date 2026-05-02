import io
import os
import aiohttp
from PIL import Image, ImageDraw, ImageFont

TEMPLATE_PATH = "profile_template.png"
FONT_PATH = "font.ttf"

BASE_TEMPLATE = None
if os.path.exists(TEMPLATE_PATH):
    BASE_TEMPLATE = Image.open(TEMPLATE_PATH).convert("RGBA")

async def generate_profile_image(avatar_data, nickname, stars, cards_count, status):
    if BASE_TEMPLATE is None:
        return None
    
    bg = BASE_TEMPLATE.copy()
    draw = ImageDraw.Draw(bg)

    try:
        font_nick = ImageFont.truetype(FONT_PATH, 36)
        font_label = ImageFont.truetype(FONT_PATH, 18)
        font_val = ImageFont.truetype(FONT_PATH, 26)
    except:
        font_nick = font_label = font_val = ImageFont.load_default()

    # --- АВАТАРКА ---
    if avatar_data:
        try:
            ava = Image.open(io.BytesIO(avatar_data)).convert("RGBA")
            # Чуть увеличил размер для идеального попадания в кольцо
            ava = ava.resize((146, 146), Image.Resampling.LANCZOS)
            mask = Image.new('L', (146, 146), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, 146, 146), fill=255)
            
            # Сдвинул ВВЕРХ и ВЛЕВО, чтобы попасть ровно в белую обводку шаблона
            bg.paste(ava, (95, 88), mask) 
        except Exception as e:
            print("Ошибка авы:", e)

    # --- НИКНЕЙМ ---
    # Поднял выше (Y=140), чтобы быть по центру аватарки, и сдвинул чуть левее
    draw.text((260, 140), str(nickname), font=font_nick, fill="white")

    # --- СТАТИСТИКА ---
    # Поднял тексты ВЫШЕ к иконкам (было 385 и 425)
    LABEL_Y = 350 
    VALUE_Y = 390
    
    # Колонки по оси X (они стоят ровно под иконками, их не трогаем)
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
