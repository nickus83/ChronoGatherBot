"""
Admin handlers - admin commands
"""

from aiogram import Router

router = Router()


def register_admin_handlers(dp) -> None:
    """Register admin handlers to dispatcher"""
    dp.include_router(router)