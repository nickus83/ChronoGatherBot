"""
Admin handlers - admin commands
"""

from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from os import getenv
from sqlalchemy.sql.functions import func

from database.models import Event, User, EventParticipant, UserRole
from database.queries import get_or_create_user

router = Router()


def is_admin(user_id: int) -> bool:
    """Check if user is admin based on ADMIN_IDS from .env"""
    admin_ids_raw = getenv('ADMIN_IDS', '')
    admin_ids = [int(x.strip()) for x in admin_ids_raw.split(',') if x.strip().isdigit()]
    return user_id in admin_ids


@router.message(Command('events'))
async def cmd_events(message: Message, sessionmaker) -> None:
    """
    Show all events (admin only)
    """
    async with sessionmaker() as session:
        user = await get_or_create_user(session, message.from_user)

        if not is_admin(user.id):
            await message.answer("❌ Only admins can use this command.")
            return

        # Fetch all events
        stmt = select(Event).order_by(Event.created_at.desc())
        result = await session.execute(stmt)
        events = result.scalars().all()

        if not events:
            await message.answer("📋 No events found.")
            return

        # Build list of events
        event_list = []
        for e in events:
            status = "✅ Finished" if e.is_recurring or e.finished else "⏳ Active"
            # Correctly import and use func.count
            participant_count_stmt = select(func.count(EventParticipant.id)).where(EventParticipant.event_id == e.id)
            participant_count_result = await session.execute(participant_count_stmt)
            participant_count = participant_count_result.scalar()

            event_list.append(
                f"• <b>{e.title}</b> (ID: {e.id})\n"
                f"  - Chat: {e.chat_id}\n"
                f"  - Creator: {e.creator_user_id}\n"
                f"  - Status: {status}\n"
                f"  - Participants: {participant_count}\n"
            )

        # Send in chunks if too large (optional, for many events)
        # For now, send all at once
        await message.answer("📅 All Events:\n\n" + "\n".join(event_list))


def register_admin_handlers(dp) -> None:
    """Register admin handlers to dispatcher"""
    dp.include_router(router)