RARITY_BOOSTS = {
    "Stock": 0.05,
    "Series": 0.10,
    "Drop": 0.15,
    "Chase": 0.25,
    "One": 0.40
}

async def get_boosted_odds(db, user_id, team_name, base_odds):

    cards = await db.pool.fetch("""
    SELECT c.rarity
    FROM mifl_cards c
    JOIN inventory i ON c.card_id = i.card_id
    WHERE i.user_id = $1
    AND c.club = $2
    """, user_id, team_name)

    if not cards:
        return base_odds, False

    total_boost = 0

    for card in cards:
        total_boost += RARITY_BOOSTS.get(card['rarity'], 0)

    total_boost = min(total_boost, 0.7)

    return round(base_odds + total_boost, 2), True
