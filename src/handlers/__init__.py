"""Handlers package"""
from .events import register_event_handlers
from .availability import register_availability_handlers
from .admin import register_admin_handlers

__all__ = [
    'register_event_handlers',
    'register_availability_handlers',
    'register_admin_handlers'
]