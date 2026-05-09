from aiogram import Router
from aiogram.filters import Command
from config import ADMIN_IDS
from ai_engine import calculate_match_odds

router = Router()

@router.message(Command("add_match"))
async def add_match(message, db):

    if message.from_user.id not in ADMIN_IDS:
        return

    args = message.text.split("|")

    if len(args) != 7:
        return await message.answer(
            "/add_match|Team1|Team2|84|79|7|4"
        )

    _, t1, t2, r1, r2, f1, f2 = args

    odds = calculate_match_odds(
        float(r1),
        float(r2),
        int(f1),
        int(f2)
    )

    await db.pool.execute("""
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
        odds_over,
        odds_under,
        odds_btts_yes,
        odds_btts_no
    )
    VALUES (
        $1,$2,$3,$4,$5,$6,
        $7,$8,$9,
        1.9,1.9,
        1.7,2.1
    )
    """,
    t1,
    t2,
    float(r1),
    float(r2),
    int(f1),
    int(f2),
    odds['home'],
    odds['draw'],
    odds['away']
    )

    await message.answer("✅ Матч добавлен")
