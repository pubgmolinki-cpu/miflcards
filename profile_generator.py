import io
import os
from PIL import Image, ImageDraw, ImageFont

TEMPLATE_PATH = "profile_template.png"
FONT_PATH = "font.ttf"

# Загружаем шаблон один раз при запуске бота
BASE_TEMPLATE = None
if os.path.exists(TEMPLATE_PATH):
    BASE_TEMPLATE = Image.open(TEMPLATE_PATH).convert("RGBA")

async def generate_profile_image(avatar_data, nickname, stars, cards_count, status):
    if BASE_TEMPLATE is None:
        return None
    
    bg = BASE_TEMPLATE.copy()
    draw = ImageDraw.Draw(bg)

    # Настройка шрифтов (размеры, которые идеально подошли в прошлый раз)
    try:
        font_nick = ImageFont.truetype(FONT_PATH, 38)
        font_label = ImageFont.truetype(FONT_PATH, 18)
        font_val = ImageFont.truetype(FONT_PATH, 26)
    except OSError:
        font_nick = font_label = font_val = ImageFont.load_default()

    # --- АВАТАРКА ---
    if avatar_data:
        try:
            ava = Image.open(io.BytesIO(avatar_data)).convert("RGBA")
            # Чуть уменьшил размер для лучшего входа в кольцо
            size = (150, 150)
            ava = ava.resize(size, Image.Resampling.LANCZOS)
            
            # Круглая маска
            mask = Image.new('L', size, 0)
            ImageDraw.Draw(mask).ellipse((0, 0, size[0], size[1]), fill=255)
            
            # --- НОВЫЕ ТОЧНЫЕ КООРДИНАТЫ ---
            # Было 75 -> стало 95 (ПРОВЕЕ)
            # Было 52 -> стало 35 (ВЫШЕ)
            bg.paste(ava, (95, 35), mask) 
        except Exception:
            pass

    # --- НИКНЕЙМ ---
    # Сдвинут вправо (+20) и вверх (-17) следом за авой
    # Координаты: (275, 95), anchor="lm" ставит текст ровно по центру авы
    draw.text((275, 95), str(nickname), font=font_nick, fill="white", anchor="lm")

    # --- СТАТИСТИКА (Координаты идеальны, не трогаем) ---
    LABEL_Y = 350 
    VALUE_Y = 390
    col_stars, col_cards, col_status = 267, 513, 758

    draw.text((col_stars, LABEL_Y), "Баланс Звёзд:", font=font_label, fill="#CCFFCC", anchor="mm")
    draw.text((col_stars, VALUE_Y), f"{stars:,}".replace(",", " "), font=font_val, fill="white", anchor="mm")

    draw.text((col_cards, LABEL_Y), "Количество Карт:", font=font_label, fill="#CCFFCC", anchor="mm")
    draw.text((col_cards, VALUE_Y), str(cards_count), font=font_val, fill="white", anchor="mm")

    draw.text((col_status, LABEL_Y), "Статус:", font=font_label, fill="#CCFFCC", anchor="mm")
    status_color = "#FFD700" if status == "VIP" else "white"
    draw.text((col_status, VALUE_Y), str(status), font=font_val, fill=status_color, anchor="mm")

    buf = io.BytesIO()
    bg.save(buf, format='PNG')
    buf.seek(0)
    return buf
