"""
Availability handlers - selecting time slots
"""

from aiogram import Router

router = Router()


def register_availability_handlers(dp) -> None:
    """Register availability handlers to dispatcher"""
    dp.include_router(router)