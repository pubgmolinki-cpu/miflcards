import io
import os
import aiohttp
from PIL import Image, ImageDraw, ImageFont, ImageOps

# Пути к файлам шаблона и шрифта
TEMPLATE_PATH = "profile_template.png"
FONT_PATH = "font.ttf"  # ЗАМЕНИ НА СВОЙ TTF ФАЙЛ

# Координаты из шаблона (X, Y)
CIRCLE_CENTER = (195, 188)  # Центр белого круга
CIRCLE_RADIUS = 73         # Радиус внутри белого круга для маскировки авы
NICKNAME_POS = (300, 160)  # Координаты начала ника (справа от авы)

# Горизонтальные центры колонок под эмодзи
STAR_COLUMN_X = 267
CARD_COLUMN_X = 513
USER_COLUMN_X = 758

# Вертикальные координаты для текста (Центр строк)
LABEL_Y = 400              # Строка "Баланс Звёзд:" и т.д.
VALUE_Y = 450              # Строка с самим количеством

# Цвета
THEME_LABEL_COLOR = "#CCFFCC" # Светло-зеленый (в тон сетке)
VALUE_COLOR = "#FFFFFF"       # Белый (для цифр)
VIP_VALUE_COLOR = "#FFD700"   # Золотой (специально для VIP статуса)


async def generate_profile_image(avatar_url: str, nickname: str, stars: int, cards: int, status: str) -> io.BytesIO:
    \"\"\"
    Генерирует изображение профиля на основе шаблона и данных пользователя.
    Возвращает BytesIO объект с картинкой.
    \"\"\"
    
    # 1. Загружаем шаблон
    if not os.path.exists(TEMPLATE_PATH):
        raise FileNotFoundError(f"Шаблон не найден по пути: {TEMPLATE_PATH}")
    bg = Image.open(TEMPLATE_PATH).convert("RGBA")
    draw = ImageDraw.Draw(bg)

    # 2. Настраиваем шрифты
    # Если шрифт не найден, PIL откатится к системному (будет некрасиво)
    try:
        font_nick = ImageFont.truetype(FONT_PATH, 48)  # Размер для ника
        font_label = ImageFont.truetype(FONT_PATH, 28) # Размер для подписей
        font_value = ImageFont.truetype(FONT_PATH, 38) # Размер для цифр
    except OSError:
        print(f"⚠️ Шрифт {FONT_PATH} не найден. Используется стандартный.")
        font_nick = font_label = font_value = ImageFont.load_default()

    # 3. Обработка Аватарки (Скачивание и маскировка в круг)
    async with aiohttp.ClientSession() as session:
        async with session.get(avatar_url) as response:
            if response.status == 200:
                avatar_data = await response.read()
                avatar_raw = Image.open(io.BytesIO(avatar_data)).convert("RGBA")
                
                # Масштабируем аву под размер круга
                size = (CIRCLE_RADIUS * 2, CIRCLE_RADIUS * 2)
                avatar_raw = avatar_raw.resize(size, Image.Resampling.LANCZOS)
                
                # Создаем круглую маску
                mask = Image.new('L', size, 0)
                mask_draw = ImageDraw.Draw(mask)
                mask_draw.ellipse((0, 0) + size, fill=255)
                
                # Применяем маску
                avatar_circ = ImageOps.fit(avatar_raw, mask.size, centering=(0.5, 0.5))
                avatar_circ.putalpha(mask)
                
                # Вставляем аву в центр круга на шаблоне
                # PIL вставляет по верхнему левому углу, поэтому вычисляем координаты
                paste_pos = (CIRCLE_CENTER[0] - CIRCLE_RADIUS, CIRCLE_CENTER[1] - CIRCLE_RADIUS)
                bg.alpha_composite(avatar_circ, paste_pos)
            else:
                print(f"⚠️ Не удалось скачать аватарку. Код: {response.status}")
                # Если авы нет, оставляем белый круг пустым или рисуем заглушку

    # 4. Рисуем Никнейм
    draw.text(NICKNAME_POS, nickname, font=font_nick, fill=VALUE_COLOR)

    # 5. Рисуем динамические блоки текста (центрируем по колонкам)
    
    # Блок Звёзд
    # text with anchor="mm" centers the text horizontally around the given X coordinate
    draw.text((STAR_COLUMN_X, LABEL_Y), "Баланс Звёзд:", font=font_label, fill=THEME_LABEL_COLOR, anchor="mm")
    # Добавим пробел в больших числах (например, 10 000)
    stars_str = f"{stars:,}".replace(",", " ")
    draw.text((STAR_COLUMN_X, VALUE_Y), stars_str, font=font_value, fill=VALUE_COLOR, anchor="mm")

    # Блок Карт
    draw.text((CARD_COLUMN_X, LABEL_Y), "Количество Карт:", font=font_label, fill=THEME_LABEL_COLOR, anchor="mm")
    draw.text((CARD_COLUMN_X, VALUE_Y), str(cards), font=font_value, fill=VALUE_COLOR, anchor="mm")

    # Блок Статуса
    # Для VIP статуса используем золотой цвет
    stat_color = VIP_VALUE_COLOR if status.lower() == "vip" else VALUE_COLOR
    draw.text((USER_COLUMN_X, LABEL_Y), "Статус:", font=font_label, fill=THEME_LABEL_COLOR, anchor="mm")
    draw.text((USER_COLUMN_X, VALUE_Y), status.capitalize(), font=font_value, fill=stat_color, anchor="mm")


    # 6. Сохраняем результат в буфер
    output = io.BytesIO()
    bg.save(output, format='PNG')
    output.seek(0)
    return output

