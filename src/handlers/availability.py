from datetime import datetime, timedelta
from typing import List, Tuple
import re

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database.models import Availability, EventParticipant, Event
from database.queries import get_or_create_user
from keyboards.calendar import generate_calendar_keyboard, TimeSlotCallback

router = Router()


@router.message(Command('available'))
async def cmd_available(message: Message, sessionmaker) -> None:
    """
    DEPRECATED: Use /select instead.
    Show events where user is a participant and hasn't responded yet
    """
    await message.answer("ℹ️ This command is deprecated. Use /select to choose an event.")


@router.message(Command('select'))
async def cmd_select(message: Message, sessionmaker) -> None:
    """
    Show user a list of events where they haven't responded yet.
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

        # Build list of events with numbered buttons
        event_list = []
        for i, e in enumerate(events, start=1):
            event_list.append(f"{i}. <b>{e.title}</b> ({e.start_date or 'Recurring'})")

        await message.answer(
            f"📅 Select an event to provide your availability:\n\n" +
            "\n".join(event_list) +
            f"\n\nSend the number (1-{len(events)}) to proceed."
        )


@router.message(F.text.isdigit())  # Handles numeric input like "1" *after* /select was implicitly shown
async def cmd_select_number(message: Message, sessionmaker) -> None:
    """
    Handle numeric input after /select to choose an event
    NOTE: This is a simplified approach. A better way is using FSM (aiogram's Finite State Machine).
    For now, this assumes the user just sent a number right after seeing the list from /select.
    """
    text = message.text.strip()
    choice_num = int(text)

    async with sessionmaker() as session:
        user = await get_or_create_user(session, message.from_user)

        # Fetch events again (could be optimized by storing in FSM, but for now simple re-query)
        stmt = (
            select(Event)
            .join(EventParticipant)
            .where(
                EventParticipant.user_id == user.id,
                EventParticipant.responded == False,
                Event.finished == False
            )
            .order_by(Event.created_at)  # Consistent order
        )
        result = await session.execute(stmt)
        events = result.scalars().all()

        if not events or choice_num < 1 or choice_num > len(events):
            await message.answer("❌ Invalid number. Use /select again to see the list.")
            return

        chosen_event = events[choice_num - 1]

        # Fetch current user's selected slots to pass to calendar
        slots_stmt = select(Availability).where(
            Availability.event_id == chosen_event.id,
            Availability.user_id == user.id
        )
        slots_db = await session.scalars(slots_stmt)
        selected_slots = []
        for slot in slots_db:
            time_start_str = slot.time_start.strftime("%H:%M") # Convert back to string for display logic
            time_end_str = slot.time_end.strftime("%H:%M")
            if chosen_event.is_recurring:
                selected_slots.append((slot.day_of_week, time_start_str, time_end_str))
            else:
                selected_slots.append((time_start_str, time_end_str))

        # Show calendar
        kb_builder = generate_calendar_keyboard(chosen_event, selected_slots)
        await message.answer(
            f"📅 Select time slots for '<b>{chosen_event.title}</b>' (Duration: {chosen_event.duration_minutes // 60}h {chosen_event.duration_minutes % 60}m):",
            reply_markup=kb_builder.as_markup()
        )


@router.callback_query(TimeSlotCallback.filter())
async def handle_timeslot_selection(
    callback: CallbackQuery,
    callback_data: TimeSlotCallback,  # Исправлен синтаксис
    sessionmaker,
    bot  # Получаем бота из контекста
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

        # Calculate end time based on event duration using hour/minute from callback
        start_time_obj = datetime.min.time().replace(hour=callback_data.hour, minute=callback_data.minute)
        duration_td = timedelta(minutes=event.duration_minutes)
        start_datetime = datetime.combine(datetime.today(), start_time_obj)
        end_datetime = start_datetime + duration_td
        end_time = end_datetime.time()

        # Check if slot already exists
        existing_slot = await session.scalar(
            select(Availability).where(
                Availability.event_id == callback_data.event_id,
                Availability.user_id == user.id,
                Availability.date == (datetime.fromisoformat(callback_data.date).date() if callback_data.date else None),
                Availability.day_of_week == callback_data.day_of_week,
                Availability.time_start == start_time_obj,
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
                time_start=start_time_obj,
                time_end=end_time
            )
            session.add(availability)
            await session.commit()
            action = "added"

        # Mark participant as responded
        participant.responded = True
        await session.commit()

        if action == "added":
            time_str = start_time_obj.strftime("%H:%M")
            await callback.answer(f"✅ Time slot {time_str} added!")
        else:
            time_str = start_time_obj.strftime("%H:%M")
            await callback.answer(f"❌ Time slot {time_str} removed.")

        # Re-fetch user's slots to update calendar
        slots_stmt = select(Availability).where(
            Availability.event_id == callback_data.event_id,
            Availability.user_id == user.id
        )
        slots_db = await session.scalars(slots_stmt)
        selected_slots = []
        for slot in slots_db:
            time_start_str = slot.time_start.strftime("%H:%M") # Convert back to string for display logic
            time_end_str = slot.time_end.strftime("%H:%M")
            if event.is_recurring:
                selected_slots.append((slot.day_of_week, time_start_str, time_end_str))
            else:
                selected_slots.append((time_start_str, time_end_str))

        # Re-show calendar to reflect changes
        kb_builder = generate_calendar_keyboard(event, selected_slots)
        await callback.message.edit_reply_markup(reply_markup=kb_builder.as_markup())

        # Проверяем, все ли ответили
        # Импортируем функцию проверки и вызываем её
        from handlers.events import check_and_notify_completion
        await check_and_notify_completion(session, bot, callback_data.event_id)


def register_availability_handlers(dp) -> None:
    """Register availability handlers to dispatcher"""
    dp.include_router(router)
