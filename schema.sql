-- Таблица пользователей
CREATE TABLE users (
    user_id BIGINT PRIMARY KEY,
    username VARCHAR(255),
    stars INTEGER DEFAULT 1000, -- Начальный капитал
    referrer_id BIGINT,
    vip_until TIMESTAMP DEFAULT NULL,
    last_free_card TIMESTAMP DEFAULT NULL,
    last_guess_game TIMESTAMP DEFAULT NULL,
    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Таблица карт (База игроков)
CREATE TABLE mifl_cards (
    card_id SERIAL PRIMARY KEY,
    name VARCHAR(255),
    rating NUMERIC(2,1),
    club VARCHAR(255),
    position VARCHAR(10),
    rarity VARCHAR(50), -- Stock, Series, Drop, Chase, One
    photo_id TEXT       -- File_id картинки в Telegram
);

-- Таблица инвентаря
CREATE TABLE inventory (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(user_id),
    card_id INTEGER REFERENCES mifl_cards(card_id)
);

-- Таблица рефералов на проверке
CREATE TABLE referrals (
    id SERIAL PRIMARY KEY,
    referrer_id BIGINT,
    referral_id BIGINT UNIQUE,
    status VARCHAR(20) DEFAULT 'on_check', -- on_check, success, failed
    check_time TIMESTAMP
);

