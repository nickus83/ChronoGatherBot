"""
Scheduler for reminders and notifications
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot

def init_scheduler(bot: Bot) -> AsyncIOScheduler:
    """Initialize APScheduler"""
    scheduler = AsyncIOScheduler()
    # TODO: Add reminder jobs
    return scheduler