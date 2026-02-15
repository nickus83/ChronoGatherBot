"""
Availability handlers - selecting time slots
"""

from datetime import datetime, timedelta
from typing import List, Tuple

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database.models import EventParticipant, Event, Availability
from database.queries import get_or_create_user
from keyboards.calendar import generate_calendar_keyboard, TimeSlotCallback

router = Router()


@router.message(Command('available'))
async def cmd_available(message: Message, sessionmaker) -> None:
    """
    Show events where user is a participant and hasn't responded yet
    """
    async with sessionmaker() as session:
        user = await get_or_create_user(session, message.from_user)

        # Find active events where user is participant and hasn't responded
        stmt = (
            select(Event)
            .join(EventParticipant)
            .where(
                EventParticipant.user_id == user.id,
                EventParticipant.responded == False,  # Not yet responded
                Event.finished == False  # Event is still active
            )
        )
        result = await session.execute(stmt)
        events = result.scalars().all()

        if not events:
            await message.answer("📋 You have no pending events to respond to.")
            return

        # Build list of events
        event_list = "\n".join([
            f"• <b>{e.title}</b> ({e.start_date or 'Recurring'}) - /select_{e.id}"
            for e in events
        ])
        await message.answer(f"📅 Select an event to provide your availability:\n\n{event_list}")


@router.message(Command('select_'))  # Dynamic command for each event
async def cmd_select_availability(message: Message, sessionmaker) -> None:
    """
    Triggered by /select_{event_id} - show calendar for that event
    """
    try:
        event_id = int(message.text.split('_')[1])
    except (IndexError, ValueError):
        await message.answer("❌ Invalid command. Use commands from the list.")
        return

    async with sessionmaker() as session:
        user = await get_or_create_user(session, message.from_user)

        # Verify user is participant and hasn't responded yet
        participant_stmt = select(EventParticipant).where(
            EventParticipant.event_id == event_id,
            EventParticipant.user_id == user.id
        )
        participant = await session.scalar(participant_stmt)

        if not participant or participant.responded:
            await message.answer("❌ You have already responded to this event or are not a participant.")
            return

        # Get event
        event_stmt = select(Event).where(Event.id == event_id)
        event = await session.scalar(event_stmt)
        if not event:
            await message.answer("❌ Event not found.")
            return

        # Show calendar
        kb_builder = generate_calendar_keyboard(event)
        await message.answer(
            f"📅 Select time slots for '<b>{event.title}</b>' (Duration: {event.duration_minutes // 60}h {event.duration_minutes % 60}m):",
            reply_markup=kb_builder.as_markup()
        )

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
        participant_stmt = select(EventParticipant).where(
            EventParticipant.event_id == callback_data.event_id,
            EventParticipant.user_id == user.id
        )
        participant = await session.scalar(participant_stmt)

        if not participant:
            await callback.answer("❌ You are not a participant of this event.", show_alert=True)
            return

        # Get event
        event_stmt = select(Event).where(Event.id == callback_data.event_id)
        event = await session.scalar(event_stmt)
        if not event:
            await callback.answer("❌ Event not found.", show_alert=True)
            return

        # Calculate end time based on event duration
        start_dt = datetime.strptime(callback_data.time_start, "%H:%M").time()
        duration_td = timedelta(minutes=event.duration_minutes)
        start_datetime = datetime.combine(datetime.today(), start_dt)
        end_datetime = start_datetime + duration_td
        end_time = end_datetime.time()

        # Check if slot already exists
        existing_slot = await session.scalar(
            select(Availability).where(
                Availability.event_id == callback_data.event_id,
                Availability.user_id == user.id,
                Availability.date == (datetime.fromisoformat(callback_data.date).date() if callback_data.date else None),
                Availability.day_of_week == callback_data.day_of_week,
                Availability.time_start == start_dt,
                Availability.time_end == end_time
            )
        )

        if existing_slot:
            # Remove existing slot (toggle off)
            await session.delete(existing_slot)
            await session.commit()
            action = "removed"
        else:
            # Add new slot
            availability = Availability(
                event_id=callback_data.event_id,
                user_id=user.id,
                date=datetime.fromisoformat(callback_data.date).date() if callback_data.date else None,
                day_of_week=callback_data.day_of_week,
                time_start=start_dt,
                time_end=end_time
            )
            session.add(availability)
            await session.commit()
            action = "added"

        # Refresh participant to check if all responded
        await session.refresh(participant)
        # Re-fetch responded status just in case
        participant_stmt = select(EventParticipant).where(EventParticipant.id == participant.id)
        participant = await session.scalar(participant_stmt)

        if action == "added":
            await callback.answer(f"✅ Time slot {callback_data.time_start} added!")
        else:
            await callback.answer(f"❌ Time slot {callback_data.time_start} removed.")

        # Now, check if all participants have responded
        # (For now, just mark current user as responded)
        participant.responded = True
        await session.commit()

        # Re-show calendar to reflect changes
        # Fetch currently selected slots
        selected_stmt = select(Availability).where(
            Availability.event_id == callback_data.event_id,
            Availability.user_id == user.id
        )
        selected_slots_db = await session.scalars(selected_stmt)
        selected_slots = [
            (slot.time_start.strftime("%H:%M"), slot.time_end.strftime("%H:%M")) if not event.is_recurring
            else (slot.day_of_week, slot.time_start.strftime("%H:%M"), slot.time_end.strftime("%H:%M"))
            for slot in selected_slots_db
        ]

        kb_builder = generate_calendar_keyboard(event, selected_slots)
        await callback.message.edit_reply_markup(reply_markup=kb_builder.as_markup())

def register_availability_handlers(dp) -> None:
    """Register availability handlers to dispatcher"""
    dp.include_router(router)