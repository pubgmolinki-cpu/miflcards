from aiogram import Router, F

router = Router()

@router.message(F.text == "⚽ Матчи")
async def show_matches(message, db):

    matches = await db.pool.fetch(
        "SELECT * FROM matches ORDER BY starts_at"
    )

    if not matches:
        return await message.answer("Матчей пока нет")

    text = "⚽ АКТИВНЫЕ МАТЧИ\n\n"

    for match in matches:

        text += (
            f"{match['team1']} vs {match['team2']}\n"
            f"📅 {match['starts_at']}\n"
            f"📊 {match['status']}\n\n"
        )

    await message.answer(text)
