"""
Database models for ChronoGather Bot
SQLAlchemy 2.0 async ORM
"""

from typing import Optional
from datetime import datetime
from enum import Enum

from sqlalchemy import (
    create_engine, Column, Integer, String, DateTime,
    Boolean, ForeignKey, Text, func, inspect, Date, Time
)
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.dialects.postgresql import JSONB

Base = declarative_base()


class UserRole(str, Enum):
    PLAYER = "player"
    GM = "gm"
    ADMIN = "admin"


class User(Base):
    """Telegram user with role"""

    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)  # Telegram user ID
    username = Column(String(100))          # @username (can be None)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100))
    role = Column(String(20), default=UserRole.PLAYER.value)
    created_at = Column(DateTime, default=func.now())

    # Relationships
    created_events = relationship('Event', back_populates='creator')
    availabilities = relationship('Availability', back_populates='user')

    def __repr__(self):
        return f"<User(id={self.id}, name='{self.first_name}', role='{self.role}')>"


class Event(Base):
    """Scheduled event (game session, meeting, etc.)"""

    __tablename__ = 'events'

    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, nullable=False)  # Telegram group ID
    title = Column(String(255), nullable=False)
    duration_minutes = Column(Integer, nullable=False)  # e.g., 210 for 3.5h

    is_recurring = Column(Boolean, default=False)  # True = by weekday, False = specific date
    start_date = Column(Date)  # Only for non-recurring events

    creator_user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    created_at = Column(DateTime, default=func.now())
    finished = Column(Boolean, default=False)  # All participants responded

    # Relationships
    creator = relationship('User', back_populates='created_events')
    participants = relationship('EventParticipant', back_populates='event', cascade='all, delete-orphan')
    availabilities = relationship('Availability', back_populates='event', cascade='all, delete-orphan')

    def __repr__(self):
        return f"<Event(id={self.id}, title='{self.title}', recurring={self.is_recurring})>"


class EventParticipant(Base):
    """Link between event and participant"""

    __tablename__ = 'event_participants'

    event_id = Column(Integer, ForeignKey('events.id'), primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), primary_key=True)
    invited_by = Column(Integer, ForeignKey('users.id'))  # Who added this user
    responded = Column(Boolean, default=False)  # Has user selected time?

    # Relationships
    event = relationship('Event', back_populates='participants')
    user = relationship('User')
    inviter = relationship('User', foreign_keys=[invited_by])

    def __repr__(self):
        return f"<EventParticipant(event_id={self.event_id}, user_id={self.user_id}, responded={self.responded})>"


class Availability(Base):
    """User availability for an event"""

    __tablename__ = 'availabilities'

    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey('events.id', ondelete='CASCADE'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)

    # For non-recurring: exact date
    date = Column(Date)  # e.g., 2026-02-16

    # For recurring: day of week (0=Monday, 6=Sunday)
    day_of_week = Column(Integer)  # 0-6 only if recurring

    # Time range (stored as time only, e.g. '18:00')
    time_start = Column(Time, nullable=False)  # '18:00'
    time_end = Column(Time, nullable=False)    # '22:00'

    comment = Column(Text)  # Optional reason for unavailability or note

    created_at = Column(DateTime, default=func.now())

    # Relationships
    event = relationship('Event', back_populates='availabilities')
    user = relationship('User', back_populates='availabilities')

    def __repr__(self):
        return f"<Availability(event_id={self.event_id}, user_id={self.user_id}, date={self.date}, {self.time_start}-{self.time_end})>"