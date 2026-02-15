"""
ChronoGather Bot - Telegram scheduling bot
Entry point
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from dotenv import load_dotenv

from database.models import init_db
from handlers import (
    register_event_handlers,
    register_availability_handlers,
    register_admin_handlers
)
from utils.scheduler import init_scheduler
# NEW: Import the finalize function
from handlers.availability import finalize_availability_and_check_completion

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def main() -> None:
    """Main bot entry point"""

    # Load environment variables
    env_path = Path(__file__).parent.parent / '.env'
    if env_path.exists():
        load_dotenv(env_path)
    else:
        logger.error("❌ .env file not found!")
        logger.info("Copy .env.example to .env and fill in your settings")
        return

    # Get bot token from environment
    from os import getenv
    bot_token = getenv('BOT_TOKEN')
    if not bot_token:
        logger.error("❌ BOT_TOKEN not found in .env file")
        return

    # Get database URL
    db_url = getenv('DB_URL', 'sqlite:///./db.sqlite3')

    # Initialize database engine
    if db_url.startswith('sqlite:///'):
        db_url = db_url.replace('sqlite:///', 'sqlite+aiosqlite:///')
    elif db_url.startswith('postgresql://'):
        db_url = db_url.replace('postgresql://', 'postgresql+asyncpg://')

    engine = create_async_engine(db_url, echo=False)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    # Initialize database tables
    await init_db(db_url)
    logger.info("✅ Database initialized")

    # Initialize bot and dispatcher
    bot = Bot(
        token=bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    # Register handlers with database session
    register_event_handlers(dp)
    register_availability_handlers(dp)
    register_admin_handlers(dp)

    # Add sessionmaker and bot instance to dispatch context
    dp['sessionmaker'] = sessionmaker
    dp['bot'] = bot # NEW: Make bot available globally in handlers

    logger.info("✅ Handlers registered")

    # Initialize scheduler for reminders
    scheduler = init_scheduler(bot)
    scheduler.start()
    logger.info("✅ Scheduler started")

    # NEW: Add a post-process hook or manually call finalize after slot save
    # We need to hook into the callback handler's success path.
    # Let's modify the handler itself to call finalize after committing.
    # See the updated availability.py above which adds finalize_availability_and_check_completion

    # Start polling
    logger.info("🚀 ChronoGather Bot started polling...")
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown()
        await bot.session.close()
        await engine.dispose()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 ChronoGather Bot stopped by user")