import asyncpg
import random
from datetime import datetime, timedelta

class Database:
    def __init__(self, pool):
        self.pool = pool

    async def create_tables(self):
        """Создает все необходимые таблицы, если их еще нет в базе."""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username VARCHAR(255),
                    stars INTEGER DEFAULT 500,
                    referrer_id BIGINT,
                    vip_until TIMESTAMP DEFAULT NULL,
                    last_free_card TIMESTAMP DEFAULT NULL,
                    last_guess_game TIMESTAMP DEFAULT NULL,
                    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS mifl_cards (
                    card_id SERIAL PRIMARY KEY,
                    name VARCHAR(255),
                    rating NUMERIC(2,1),
                    club VARCHAR(255),
                    position VARCHAR(10),
                    rarity VARCHAR(50),
                    photo_id TEXT
                );

                CREATE TABLE IF NOT EXISTS inventory (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(user_id),
                    card_id INTEGER REFERENCES mifl_cards(card_id)
                );

                CREATE TABLE IF NOT EXISTS referrals (
                    id SERIAL PRIMARY KEY,
                    referrer_id BIGINT,
                    referral_id BIGINT UNIQUE,
                    status VARCHAR(20) DEFAULT 'on_check',
                    check_time TIMESTAMP
                );
            """)
            print("✅ База данных проверена и готова к работе.")

    # Остальные методы (get_user_data, add_referral и т.д.) остаются прежними...
