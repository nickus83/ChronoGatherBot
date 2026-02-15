"""
Availability handlers - selecting time slots
"""

from datetime import datetime, timedelta
from typing import List, Tuple

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Availability, EventParticipant, Event
from database.queries import get_or_create_user
from keyboards.calendar import generate_calendar_keyboard, TimeSlotCallback

router = Router()


@router.callback_query(TimeSlotCallback.filter())
async def handle_timeslot_selection(
    callback: CallbackQuery,
    callback_data: TimeSlotCallback,
    sessionmaker
):
    """
    Handle user clicking on a time slot
    """
    async with sessionmaker() as session:
        user = await get_or_create_user(session, callback.from_user)

        # Verify user is participant of the event
        participant_stmt = session.query(EventParticipant).filter(
            EventParticipant.event_id == callback_data.event_id,
            EventParticipant.user_id == user.id
        )
        participant = await session.scalar(participant_stmt)

        if not participant:
            await callback.answer("❌ You are not a participant of this event.", show_alert=True)
            return

        # Determine slot duration (use event duration or default 30min window)
        event_stmt = session.query(Event).filter(Event.id == callback_data.event_id)
        event = await session.scalar(event_stmt)
        if not event:
            await callback.answer("❌ Event not found.", show_alert=True)
            return

        duration_minutes = event.duration_minutes
        start_dt = datetime.strptime(callback_data.time_start, "%H:%M").time()
        end_dt = (datetime.combine(datetime.today(), start_dt) + timedelta(minutes=duration_minutes)).time()

        # Save availability
        availability = Availability(
            event_id=callback_data.event_id,
            user_id=user.id,
            date=datetime.fromisoformat(callback_data.date).date() if callback_data.date else None,
            day_of_week=callback_data.day_of_week,
            time_start=start_dt,
            time_end=end_dt
        )
        session.add(availability)
        await session.commit()

        # Mark participant as responded
        participant.responded = True
        await session.commit()

        await callback.answer(f"✅ Time slot {callback_data.time_start} selected!")

        # TODO: Notify group about new availability if enough participants responded
        # TODO: Show updated calendar with selected slots


def register_availability_handlers(dp) -> None:
    """Register availability handlers to dispatcher"""
    dp.include_router(router)