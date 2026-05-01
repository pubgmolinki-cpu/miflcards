import asyncpg
import random
from datetime import datetime, timedelta

class Database:
    def __init__(self, pool):
        self.pool = pool

    async def create_tables(self):
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
                    rating NUMERIC(3,1),
                    club VARCHAR(255),
                    position VARCHAR(10),
                    rarity VARCHAR(50),
                    photo_id TEXT
                );

                CREATE TABLE IF NOT EXISTS inventory (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                    card_id INTEGER REFERENCES mifl_cards(card_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS referrals (
                    id SERIAL PRIMARY KEY,
                    referrer_id BIGINT,
                    referral_id BIGINT UNIQUE,
                    status VARCHAR(20) DEFAULT 'on_check',
                    check_time TIMESTAMP
                );
            """)

    async def get_user(self, user_id):
        return await self.pool.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)

    async def is_vip(self, user_id):
        res = await self.pool.fetchval("SELECT vip_until FROM users WHERE user_id = $1", user_id)
        return res > datetime.now() if res else False

    async def get_random_card(self, rarity=None):
        if rarity:
            return await self.pool.fetchrow("SELECT * FROM mifl_cards WHERE rarity = $1 ORDER BY RANDOM() LIMIT 1", rarity)
        
        r = random.random()
        if r < 0.01: res = "One"
        elif r < 0.05: res = "Chase"
        elif r < 0.15: res = "Drop"
        elif r < 0.40: res = "Series"
        else: res = "Stock"
        return await self.pool.fetchrow("SELECT * FROM mifl_cards WHERE rarity = $1 ORDER BY RANDOM() LIMIT 1", res)

    async def add_card_to_inventory(self, user_id, card_id):
        await self.pool.execute("INSERT INTO inventory (user_id, card_id) VALUES ($1, $2)", user_id, card_id)

    async def update_stars(self, user_id, amount):
        await self.pool.execute("UPDATE users SET stars = stars + $1 WHERE user_id = $2", amount, user_id)

    async def set_cooldown(self, user_id, column):
        await self.pool.execute(f"UPDATE users SET {column} = NOW() WHERE user_id = $1", user_id)

    async def get_top_10(self):
        return await self.pool.fetch("SELECT username, stars FROM users ORDER BY stars DESC LIMIT 10")
