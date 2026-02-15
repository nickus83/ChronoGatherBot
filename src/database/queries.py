"""
Database query functions for ChronoGather Bot
"""

from datetime import date
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, insert, update
from sqlalchemy.exc import IntegrityError
from aiogram.types import User as TelegramUser
from os import getenv

from database.models import User, Event, EventParticipant, UserRole


async def get_or_create_user(session: AsyncSession, tg_user: TelegramUser) -> User:
    """Get or create user record from Telegram user object, assign role from ADMIN_IDS if applicable"""

    # Получить список админов из .env
    admin_ids_raw = getenv('ADMIN_IDS', '')
    admin_ids = [int(x.strip()) for x in admin_ids_raw.split(',') if x.strip().isdigit()]

    stmt = select(User).where(User.id == tg_user.id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if user:
        # Update name if changed
        if user.first_name != tg_user.first_name or user.last_name != tg_user.last_name:
            user.first_name = tg_user.first_name
            user.last_name = tg_user.last_name
            user.username = tg_user.username
            await session.commit()

        # Проверить, является ли пользователь админом по ID из .env
        if user.id in admin_ids and user.role != UserRole.ADMIN.value:
            user.role = UserRole.ADMIN.value
            await session.commit()
        elif user.id not in admin_ids and user.role == UserRole.ADMIN.value:
            # Если ID больше нет в .env, но роль была admin, сбросить до player (опционально)
            user.role = UserRole.PLAYER.value
            await session.commit()

        return user

    # Создать нового пользователя
    # Проверить, новый ли пользователь админ по ID
    role = UserRole.ADMIN.value if tg_user.id in admin_ids else UserRole.PLAYER.value

    new_user = User(
        id=tg_user.id,
        username=tg_user.username,
        first_name=tg_user.first_name,
        last_name=tg_user.last_name,
        role=role
    )
    session.add(new_user)
    await session.commit()
    await session.refresh(new_user)
    return new_user


async def create_event_with_participants(
    session: AsyncSession,
    chat_id: int,
    title: str,
    duration_minutes: int,
    is_recurring: bool,
    start_date: Optional[date],
    creator_user_id: int,
    usernames: List[str]
) -> Event:
    """
    Create event and link participants
    """
    # Validate creator exists and has permission
    creator_stmt = select(User).where(User.id == creator_user_id)
    creator_result = await session.execute(creator_stmt)
    creator = creator_result.scalar_one_or_none()
    if not creator or creator.role not in [UserRole.ADMIN.value, UserRole.GM.value]:
        raise ValueError("Creator must be admin or GM")

    # Create event
    event = Event(
        chat_id=chat_id,
        title=title,
        duration_minutes=duration_minutes,
        is_recurring=is_recurring,
        start_date=start_date,
        creator_user_id=creator_user_id
    )
    session.add(event)
    await session.flush()  # To get event.id

    # Link participants
    for username in usernames:
        # Find user by username
        user_stmt = select(User).where(User.username == username)
        user_result = await session.execute(user_stmt)
        user = user_result.scalar_one_or_none()

        if not user:
            # Create placeholder user if not exists (with minimal data)
            user = User(
                id=0,  # Will be updated later when user interacts
                username=username,
                first_name=username,
                role=UserRole.PLAYER.value
            )
            session.add(user)
            await session.flush()

        # Link to event
        participant = EventParticipant(
            event_id=event.id,
            user_id=user.id,
            invited_by=creator_user_id
        )
        session.add(participant)

    await session.commit()
    return event