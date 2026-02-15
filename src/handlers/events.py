"""
Event handlers - creating and managing events
"""

import re
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.exceptions import TelegramAPIError

from database.models import Event, User, EventParticipant, UserRole
from database.queries import get_or_create_user, create_event_with_participants

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

        except Exception as e:
            await message.answer(f"❌ Failed to create event: {str(e)}")


def register_event_handlers(dp) -> None:
    """Register event handlers to dispatcher"""
    dp.include_router(router)