import asyncio
from aiohttp import web
from aiogram import Bot, Dispatcher

from config import BOT_TOKEN
from database import Database

from handlers import cards
from handlers import bets
from handlers import matches
from handlers import admin

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

async def health(request):
    return web.Response(text="MIFL UNIVERSE ONLINE")

async def start_webserver():

    app = web.Application()
    app.router.add_get('/', health)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(
        runner,
        '0.0.0.0',
        8080
    )

    await site.start()

async def main():

    db = Database()

    await db.connect()
    await db.create_tables()

    dp['db'] = db

    dp.include_router(cards.router)
    dp.include_router(bets.router)
    dp.include_router(matches.router)
    dp.include_router(admin.router)

    asyncio.create_task(start_webserver())

    await bot.delete_webhook(drop_pending_updates=True)

    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
