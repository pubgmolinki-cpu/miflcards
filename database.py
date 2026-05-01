import asyncpg
import random
from datetime import datetime, timedelta

class Database:
    def __init__(self, pool):
        self.pool = pool

    async def get_user_data(self, user_id):
        # Получаем данные профиля и место в топе
        user = await self.pool.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
        rank = await self.pool.fetchval("SELECT count(*) + 1 FROM users WHERE stars > (SELECT stars FROM users WHERE user_id = $1)", user_id)
        return user, rank

    async def add_referral(self, referrer_id, referral_id):
        check_time = datetime.now() + timedelta(days=1)
        await self.pool.execute(
            "INSERT INTO referrals (referrer_id, referral_id, check_time) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
            referrer_id, referral_id, check_time
        )

    async def get_random_card(self, rarity=None):
        if rarity:
            return await self.pool.fetchrow("SELECT * FROM mifl_cards WHERE rarity = $1 ORDER BY RANDOM() LIMIT 1", rarity)
        # Обычный шанс выпадения
        r = random.random()
        if r < 0.01: res = "One"
        elif r < 0.05: res = "Chase"
        elif r < 0.15: res = "Drop"
        elif r < 0.40: res = "Series"
        else: res = "Stock"
        return await self.pool.fetchrow("SELECT * FROM mifl_cards WHERE rarity = $1 ORDER BY RANDOM() LIMIT 1", res)

    async def give_card(self, user_id, card_id, stars):
        await self.pool.execute("INSERT INTO inventory (user_id, card_id) VALUES ($1, $2)", user_id, card_id)
        await self.pool.execute("UPDATE users SET stars = stars + $1 WHERE user_id = $2", stars, user_id)
