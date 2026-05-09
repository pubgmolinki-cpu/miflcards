from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

router = Router()

@router.message(F.text == "🎰 Ставки")
async def bets_menu(message, db):

    matches = await db.pool.fetch(
        "SELECT * FROM matches WHERE status = 'OPEN'"
    )

    if not matches:
        return await message.answer("Нет активных матчей")

    for match in matches:

        text = (
            f"⚽ {match['team1']} vs {match['team2']}\n\n"
            f"П1 — {match['odds_home']}\n"
            f"X — {match['odds_draw']}\n"
            f"П2 — {match['odds_away']}"
        )

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="П1",
                        callback_data=f"bet_home_{match['match_id']}"
                    ),
                    InlineKeyboardButton(
                        text="X",
                        callback_data=f"bet_draw_{match['match_id']}"
                    ),
                    InlineKeyboardButton(
                        text="П2",
                        callback_data=f"bet_away_{match['match_id']}"
                    )
                ]
            ]
        )

        await message.answer(text, reply_markup=kb)
