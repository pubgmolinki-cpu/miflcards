import asyncpg
import random
from datetime import datetime, timedelta


class Database:
    def __init__(self, pool):
        self.pool = pool

    async def create_tables(self):
        async with self.pool.acquire() as conn:

            # USERS
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username VARCHAR(255),
                stars BIGINT DEFAULT 500,
                referrer_id BIGINT,

                vip_until TIMESTAMP DEFAULT NULL,

                last_free_card TIMESTAMP DEFAULT NULL,
                last_guess_game TIMESTAMP DEFAULT NULL,
                last_bonus TIMESTAMP DEFAULT NULL,

                total_bets INTEGER DEFAULT 0,
                bets_won INTEGER DEFAULT 0,

                favorite_club VARCHAR(255) DEFAULT NULL,

                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # CARDS
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS mifl_cards (
                card_id SERIAL PRIMARY KEY,

                name VARCHAR(255),
                rating NUMERIC(3,1),

                club VARCHAR(255),
                position VARCHAR(10),

                rarity VARCHAR(50),

                trait VARCHAR(255) DEFAULT NULL,

                market_price BIGINT DEFAULT 1000,

                hot BOOLEAN DEFAULT FALSE,

                photo_id TEXT
            );
            """)

            # INVENTORY
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS inventory (
                id SERIAL PRIMARY KEY,

                user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                card_id INTEGER REFERENCES mifl_cards(card_id) ON DELETE CASCADE
            );
            """)

            # REFERRALS
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                id SERIAL PRIMARY KEY,

                referrer_id BIGINT,
                referral_id BIGINT UNIQUE,

                status VARCHAR(20) DEFAULT 'on_check',

                check_time TIMESTAMP
            );
            """)

            # MATCHES
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS matches (
                match_id SERIAL PRIMARY KEY,

                team1 VARCHAR(255),
                team2 VARCHAR(255),

                team1_rating NUMERIC(4,1),
                team2_rating NUMERIC(4,1),

                team1_form INTEGER,
                team2_form INTEGER,

                odds_home NUMERIC(4,2),
                odds_draw NUMERIC(4,2),
                odds_away NUMERIC(4,2),

                odds_over_25 NUMERIC(4,2),
                odds_under_25 NUMERIC(4,2),

                odds_btts_yes NUMERIC(4,2),
                odds_btts_no NUMERIC(4,2),

                status VARCHAR(50) DEFAULT 'OPEN',

                final_score VARCHAR(20) DEFAULT NULL,

                starts_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # BETS
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS bets (
                bet_id SERIAL PRIMARY KEY,

                user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,

                match_id INTEGER REFERENCES matches(match_id) ON DELETE CASCADE,

                bet_type VARCHAR(50),

                prediction VARCHAR(255),

                amount BIGINT,

                odds NUMERIC(5,2),

                won BOOLEAN DEFAULT NULL,

                paid BOOLEAN DEFAULT FALSE,

                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # EXPRESS BETS
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS express_bets (
                express_id SERIAL PRIMARY KEY,

                user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,

                matches TEXT,

                total_odds NUMERIC(8,2),

                amount BIGINT,

                won BOOLEAN DEFAULT NULL,

                paid BOOLEAN DEFAULT FALSE,

                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # EVENT BETS
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS event_bets (
                event_id SERIAL PRIMARY KEY,

                title VARCHAR(255),

                option_name VARCHAR(255),

                odds NUMERIC(5,2),

                active BOOLEAN DEFAULT TRUE
            );
            """)

            # MARKET HISTORY
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS market_history (
                id SERIAL PRIMARY KEY,

                card_id INTEGER REFERENCES mifl_cards(card_id) ON DELETE CASCADE,

                old_price BIGINT,
                new_price BIGINT,

                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # PROMOCODES
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS promocodes (
                code VARCHAR(255) PRIMARY KEY,

                stars BIGINT,

                max_uses INTEGER,

                current_uses INTEGER DEFAULT 0
            );
            """)

            # USED PROMOS
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS used_promos (
                id SERIAL PRIMARY KEY,

                user_id BIGINT,
                code VARCHAR(255)
            );
            """)

            # ACTIVE TRADES
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS active_trades (
                code VARCHAR(255) PRIMARY KEY,

                user_a BIGINT,
                card_a INTEGER
            );
            """)

            print("✅ ALL DATABASE TABLES CREATED")

    # =========================
    # USERS
    # =========================

    async def get_user(self, user_id):
        return await self.pool.fetchrow(
            "SELECT * FROM users WHERE user_id = $1",
            user_id
        )

    async def create_user(self, user_id, username, referrer_id=None):
        await self.pool.execute("""
        INSERT INTO users (
            user_id,
            username,
            referrer_id
        )
        VALUES ($1, $2, $3)
        ON CONFLICT (user_id) DO NOTHING
        """, user_id, username, referrer_id)

    async def update_stars(self, user_id, amount):
        await self.pool.execute("""
        UPDATE users
        SET stars = stars + $1
        WHERE user_id = $2
        """, amount, user_id)

    async def is_vip(self, user_id):
        res = await self.pool.fetchval("""
        SELECT vip_until
        FROM users
        WHERE user_id = $1
        """, user_id)

        return res > datetime.now() if res else False

    async def set_cooldown(self, user_id, column):
        await self.pool.execute(
            f"UPDATE users SET {column} = NOW() WHERE user_id = $1",
            user_id
        )

    async def get_top_10(self):
        return await self.pool.fetch("""
        SELECT username, stars
        FROM users
        ORDER BY stars DESC
        LIMIT 10
        """)

    # =========================
    # CARDS
    # =========================

    async def get_random_card(self, rarity=None):

        if rarity:
            return await self.pool.fetchrow("""
            SELECT *
            FROM mifl_cards
            WHERE rarity = $1
            ORDER BY RANDOM()
            LIMIT 1
            """, rarity)

        r = random.random()

        if r < 0.01:
            res = "One"

        elif r < 0.05:
            res = "Chase"

        elif r < 0.15:
            res = "Drop"

        elif r < 0.40:
            res = "Series"

        else:
            res = "Stock"

        return await self.pool.fetchrow("""
        SELECT *
        FROM mifl_cards
        WHERE rarity = $1
        ORDER BY RANDOM()
        LIMIT 1
        """, res)

    async def add_card_to_inventory(self, user_id, card_id):
        await self.pool.execute("""
        INSERT INTO inventory (
            user_id,
            card_id
        )
        VALUES ($1, $2)
        """, user_id, card_id)

    async def user_has_card(self, user_id, card_id):
        return await self.pool.fetchval("""
        SELECT 1
        FROM inventory
        WHERE user_id = $1
        AND card_id = $2
        """, user_id, card_id)

    async def get_user_cards(self, user_id):
        return await self.pool.fetch("""
        SELECT c.*
        FROM mifl_cards c
        JOIN inventory i
        ON c.card_id = i.card_id
        WHERE i.user_id = $1
        """, user_id)

    # =========================
    # MATCHES
    # =========================

    async def create_match(
        self,
        team1,
        team2,
        r1,
        r2,
        f1,
        f2,
        home_odds,
        draw_odds,
        away_odds
    ):
        await self.pool.execute("""
        INSERT INTO matches (
            team1,
            team2,

            team1_rating,
            team2_rating,

            team1_form,
            team2_form,

            odds_home,
            odds_draw,
            odds_away,

            odds_over_25,
            odds_under_25,

            odds_btts_yes,
            odds_btts_no
        )
        VALUES (
            $1,$2,
            $3,$4,
            $5,$6,
            $7,$8,$9,
            1.90,1.90,
            1.75,2.05
        )
        """,
        team1,
        team2,
        r1,
        r2,
        f1,
        f2,
        home_odds,
        draw_odds,
        away_odds
        )

    async def get_open_matches(self):
        return await self.pool.fetch("""
        SELECT *
        FROM matches
        WHERE status = 'OPEN'
        ORDER BY starts_at
        """)

    async def set_match_result(self, match_id, score):
        await self.pool.execute("""
        UPDATE matches
        SET
            final_score = $1,
            status = 'FINISHED'
        WHERE match_id = $2
        """, score, match_id)

    # =========================
    # BETS
    # =========================

    async def create_bet(
        self,
        user_id,
        match_id,
        bet_type,
        prediction,
        amount,
        odds
    ):
        await self.pool.execute("""
        INSERT INTO bets (
            user_id,
            match_id,
            bet_type,
            prediction,
            amount,
            odds
        )
        VALUES (
            $1,$2,$3,$4,$5,$6
        )
        """,
        user_id,
        match_id,
        bet_type,
        prediction,
        amount,
        odds
        )

    async def get_user_bets(self, user_id):
        return await self.pool.fetch("""
        SELECT *
        FROM bets
        WHERE user_id = $1
        ORDER BY created_at DESC
        """, user_id)

    # =========================
    # BOOSTS
    # =========================

    async def get_team_cards(self, user_id, club):

        return await self.pool.fetch("""
        SELECT c.*
        FROM mifl_cards c
        JOIN inventory i
        ON c.card_id = i.card_id
        WHERE i.user_id = $1
        AND c.club = $2
        """,
        user_id,
        club
        )

    # =========================
    # MARKET
    # =========================

    async def update_market_price(
        self,
        card_id,
        new_price
    ):
        old_price = await self.pool.fetchval("""
        SELECT market_price
        FROM mifl_cards
        WHERE card_id = $1
        """, card_id)

        await self.pool.execute("""
        UPDATE mifl_cards
        SET market_price = $1
        WHERE card_id = $2
        """, new_price, card_id)

        await self.pool.execute("""
        INSERT INTO market_history (
            card_id,
            old_price,
            new_price
        )
        VALUES ($1,$2,$3)
        """, card_id, old_price, new_price)
