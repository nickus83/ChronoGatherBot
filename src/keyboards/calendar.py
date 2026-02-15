from datetime import datetime, timedelta, date
from typing import List, Tuple, Optional

from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
from aiogram.filters.callback_data import CallbackData

from database.models import Event, Availability


class TimeSlotCallback(CallbackData, prefix="timeslot"):
    """Callback for time slot selection"""
    event_id: int
    date: Optional[str]  # YYYY-MM-DD for non-recurring
    day_of_week: Optional[int]  # 0=Mon .. 6=Sun for recurring
    time_start: str  # HH:MM


def generate_calendar_keyboard(
    event: Event,
    selected_slots: List[Tuple[str, str]] = None  # [(start_time, end_time)] for non-recurring
) -> InlineKeyboardBuilder:
    """
    Generate calendar keyboard based on event type (recurring/non-recurring)
    """
    kb = InlineKeyboardBuilder()

    if event.is_recurring:
        return _generate_weekday_calendar_kb(kb, event, selected_slots)
    else:
        return _generate_date_calendar_kb(kb, event, selected_slots)


def _generate_date_calendar_kb(
    kb: InlineKeyboardBuilder,
    event: Event,
    selected_slots: List[Tuple[str, str]]
) -> InlineKeyboardBuilder:
    """
    Generate time slots for specific date events
    """
    if not event.start_date:
        kb.button(text="❌ No start date set", callback_data="noop")
        return kb

    target_date = event.start_date.strftime("%Y-%m-%d")
    kb.add(InlineKeyboardButton(text=f"📅 {target_date}", callback_data="noop"))

    time_step = timedelta(minutes=30)
    current_time = datetime.combine(event.start_date, datetime.min.time())
    end_time = current_time + timedelta(hours=24)

    while current_time < end_time:
        time_str = current_time.strftime("%H:%M")

        callback = TimeSlotCallback(
            event_id=event.id,
            date=target_date,
            day_of_week=None,
            time_start=time_str
        ).pack()

        # Mark selected slots visually
        is_selected = any(time_str == s[0] for s in selected_slots or [])  # Handle None
        button_text = f"✅ {time_str}" if is_selected else time_str

        kb.row(InlineKeyboardButton(text=button_text, callback_data=callback))
        current_time += time_step

    return kb


def _generate_weekday_calendar_kb(
    kb: InlineKeyboardBuilder,
    event: Event,
    selected_slots: List[Tuple[int, str, str]]  # [(day_of_week, start_time, end_time)]
) -> InlineKeyboardBuilder:
    """
    Generate weekday selection for recurring events
    """
    weekdays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    for i, day_name in enumerate(weekdays):
        callback = TimeSlotCallback(
            event_id=event.id,
            date=None,
            day_of_week=i,
            time_start="00:00"  # Will be selected next
        ).pack()

        # Mark selected weekdays
        is_selected = any(s[0] == i for s in selected_slots or [])
        button_text = f"✅ {day_name}" if is_selected else day_name

        kb.button(text=button_text, callback_data=callback)

    kb.adjust(7)
    return kb