"""
Event handlers - creating and managing events
Also includes completion checking logic.
"""

import re
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database.models import Event, User, EventParticipant, Availability, UserRole
from database.queries import get_or_create_user, create_event_with_participants
from utils.intersection import calculate_common_slots # Import the new function

router = Router()


def parse_event_command(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse /event command text into structured data.

    Examples:
    /event "Mothership: Session 3" 3h30m 16.02.2026 @blimmsky @kosmovar
    /event -r "Monster Hearts" 4h @nickus83 @chilovar

    Returns:
        dict with keys: title, duration_minutes, is_recurring, start_date, usernames
    """
    # Match: [-r] "title" duration [date] [@user1 @user2...]
    pattern = r'^(?:-r\s+)?\"([^\"]+)\"\s+((?:\d+h)?(?:\d+m)?)\s*(\d{2}\.\d{2}\.\d{4})?\s*(.*)$'
    match = re.match(pattern, text.strip())

    if not match:
        return None

    is_recurring = bool('-r' in text.split())
    title, duration_str, date_str, usernames_str = match.groups()

    # Parse duration: "3h30m" -> 210 minutes
    duration_minutes = 0
    if 'h' in duration_str:
        h_match = re.search(r'(\d+)h', duration_str)
        if h_match:
            duration_minutes += int(h_match.group(1)) * 60
    if 'm' in duration_str:
        m_match = re.search(r'(\d+)m', duration_str)
        if m_match:
            duration_minutes += int(m_match.group(1))

    if duration_minutes == 0:
        return None  # Invalid duration

    # Parse date: DD.MM.YYYY -> datetime.date
    start_date = None
    if date_str:
        try:
            start_date = datetime.strptime(date_str, '%d.%m.%Y').date()
        except ValueError:
            return None  # Invalid date

    # Parse usernames: "@user1 @user2" -> ["user1", "user2"]
    usernames = []
    if usernames_str:
        usernames = [u.lstrip('@') for u in usernames_str.split() if u.startswith('@')]

    return {
        'title': title.strip(),
        'duration_minutes': duration_minutes,
        'is_recurring': is_recurring,
        'start_date': start_date,
        'usernames': usernames
    }


@router.message(Command('event'))
async def cmd_newevent(message: Message, sessionmaker) -> None:
    """
    Handle /event command
    Usage: /event [-r] "Title" 3h30m [DD.MM.YYYY] [@user1 @user2...]
    """
    async with sessionmaker() as session:
        if not message.text:
            await message.answer("❌ Invalid command format. Use:\n<code>/event \"Title\" 3h30m 16.02.2026 @user1 @user2</code>")
            return

        # Extract command arguments after /event
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.answer("❌ Specify event details:\n<code>/event \"Title\" 3h30m 16.02.2026 @user1 @user2</code>")
            return

        parsed = parse_event_command(args[1])
        if not parsed:
            await message.answer(
                "❌ Invalid command format.\n\n"
                "<b>Examples:</b>\n"
                "<code>/event \"Mothership: Session 3\" 3h30m 16.02.2026 @user1 @user2</code>\n"
                "<code>/event -r \"Monster Hearts\" 4h @user1 @user2</code>"
            )
            return

        # Check if user can create events (admin or gm)
        user = await get_or_create_user(session, message.from_user)
        if user.role not in [UserRole.ADMIN.value, UserRole.GM.value]:
            await message.answer("❌ Only admins and GMs can create events.")
            return

        # Create event in DB
        try:
            event = await create_event_with_participants(
                session=session,
                chat_id=message.chat.id,
                title=parsed['title'],
                duration_minutes=parsed['duration_minutes'],
                is_recurring=parsed['is_recurring'],
                start_date=parsed['start_date'],
                creator_user_id=user.id,
                usernames=parsed['usernames']
            )

            # Success response
            recurring_text = "🔄 Recurring" if event.is_recurring else "📅 One-time"
            participants_text = f"\n👥 Participants: {len(parsed['usernames'])} invited"

            await message.answer(
                f"✅ {recurring_text} event created!\n\n"
                f"🎮 <b>{event.title}</b>\n"
                f"⏱️ Duration: {parsed['duration_minutes'] // 60}h {parsed['duration_minutes'] % 60}m\n"
                f"📅 Start: {event.start_date or 'Recurring'}\n"
                f"{participants_text}\n\n"
                f"Now each participant should go to private chat with the bot and respond to availability requests."
            )

            # NEW: Ask GM to set availability first
            gm_availability_msg = (
                f"📅 <b>Your turn, GM!</b>\n"
                f"Please go to private chat with the bot (@ChronoGatherBot) and select when you can host '{event.title}'."
            )
            await message.answer(gm_availability_msg)

        except Exception as e:
            await message.answer(f"❌ Failed to create event: {str(e)}")


# --- NEW FUNCTION: Check Completion and Notify ---
async def check_and_notify_completion(
    session: AsyncSession,
    bot_instance, # Pass the bot instance here
    event_id: int
):
    """
    Checks if all participants have responded.
    If yes, calculates intersections and sends notification to the group chat.
    """
    # Fetch event
    event = await session.get(Event, event_id)
    if not event:
        print(f"Log: Event {event_id} not found for completion check.")
        return

    # Fetch participants
    stmt = select(EventParticipant).where(EventParticipant.event_id == event_id)
    result = await session.execute(stmt)
    participants = result.scalars().all()

    total_participants = len(participants)
    responded_count = sum(1 for p in participants if p.responded)

    print(f"Log: Event {event.title}: {responded_count}/{total_participants} responded.") # Debug log

    if responded_count == total_participants:
        print(f"Log: All participants responded for event {event_id}. Calculating intersections...") # Debug log
        # All responded, calculate common slots
        common_slots = await calculate_common_slots(session, event_id)

        if common_slots:
            # Format message
            msg_lines = [f"🎉 <b>Common slots found for '{event.title}'!</b>"]
            for day, start_t, end_t, count in common_slots:
                day_str = str(day) if day else "Recurring (Day of Week TBD)"
                msg_lines.append(f"• {day_str} {start_t.strftime('%H:%M')} - {end_t.strftime('%H:%M')} ({count} people)")

            notification_message = "\n".join(msg_lines)
        else:
            notification_message = f"❌ No common slots found for '{event.title}' after everyone responded."

        # Send message to the group chat
        try:
            await bot_instance.send_message(chat_id=event.chat_id, text=notification_message)
            print(f"Log: Notification sent to chat {event.chat_id} for event {event_id}.") # Debug log
            # Optionally, mark event as finished here
            # event.finished = True
            # await session.commit()
        except TelegramAPIError as e:
            print(f"Log: Failed to send notification to chat {event.chat_id}: {e}") # Log error
    else:
        print(f"Log: Still waiting for {total_participants - responded_count} participants for event {event_id}.") # Debug log


def register_event_handlers(dp) -> None:
    """Register event handlers to dispatcher"""
    dp.include_router(router)