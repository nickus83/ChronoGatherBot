"""
Intersection logic for ChronoGather Bot
Calculates common time slots across multiple users' availability
"""

from datetime import date, time, datetime, timedelta
from typing import List, Tuple, Dict, Optional
from collections import defaultdict

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database.models import Event, Availability


async def calculate_common_slots(
    session: AsyncSession,
    event_id: int
) -> List[Tuple[Optional[date], time, time, int]]:
    """
    Calculate common time slots for an event based on all participants' availability.

    Args:
        session: SQLAlchemy async session
        event_id: ID of the event to analyze

    Returns:
        List of tuples: (date, start_time, end_time, participant_count)
        For recurring events: date will be None, and times represent day-of-week times.
    """
    # Fetch event to check if it's recurring
    event = await session.get(Event, event_id)
    if not event:
        raise ValueError(f"Event with id {event_id} not found")

    # Fetch all availability records for this event
    stmt = select(Availability).where(Availability.event_id == event_id)
    result = await session.execute(stmt)
    all_availabilities = result.scalars().all()

    if not all_availabilities:
        return []

    # Group by date (or day_of_week if recurring)
    slots_by_day: Dict[Optional[date], List[Tuple[time, time, int]]] = defaultdict(list)

    for av in all_availabilities:
        day_key = av.date if not event.is_recurring else av.day_of_week
        slots_by_day[day_key].append((av.time_start, av.time_end, av.user_id))

    common_slots = []
    for day, user_slots in slots_by_day.items():
        # user_slots = [(start, end, user_id), ...]
        # Calculate intersections for this day
        intersections = _find_intersections_for_day(user_slots, event.duration_minutes)
        for start_t, end_t, count in intersections:
            common_slots.append((day, start_t, end_t, count))

    # Sort by date/day and then by start time
    # For recurring events (day_of_week), sort by day_of_week first
    common_slots.sort(key=lambda x: (x[0] if isinstance(x[0], date) else float(x[0] or 999), x[1]))

    return common_slots


def _find_intersections_for_day(
    user_slots: List[Tuple[time, time, int]],  # [(start, end, user_id), ...]
    required_duration_min: int
) -> List[Tuple[time, time, int]]:  # [(start, end, count), ...]
    """
    Find time blocks where at least one user is available for the required duration.
    This is a simplified version focusing on overlapping intervals.
    For true intersection (common to ALL), see `_find_full_intersection_for_day`.
    """
    # This function finds overlaps between *any* users' slots.
    # For "common to all", see `_find_full_intersection_for_day` below.

    # Expand time ranges into timeline points
    timeline = []  # (time, type, user_id) where type: 1 = start, -1 = end
    for start, end, uid in user_slots:
        # Convert time to timedelta from midnight for arithmetic
        start_td = timedelta(hours=start.hour, minutes=start.minute)
        end_td = timedelta(hours=end.hour, minutes=end.minute)
        # Handle overnight spans (e.g. 23:00 -> 01:00 next day) - treat as single day for now
        # If end < start, assume it wraps to next day and ignore for simplicity
        if end_td < start_td:
            continue # Skip overnight wrap for this basic logic

        timeline.append((start_td, 1, uid))
        timeline.append((end_td, -1, uid))

    if not timeline:
        return []

    timeline.sort(key=lambda x: (x[0], -x[1])) # Sort by time, then end (-1) before start (1)

    active_users = set()
    intersections = []
    current_time = timeline[0][0]

    for time_point, event_type, user_id in timeline:
        # Process all events at current_time before moving to next
        if time_point > current_time:
            # Found a block from current_time to time_point
            if len(active_users) > 0:
                duration = time_point - current_time
                if duration.total_seconds() // 60 >= required_duration_min:
                    # Convert timedelta back to time object (relative to day start)
                    start_time = (datetime.min + current_time).time()
                    end_time = (datetime.min + time_point).time()
                    intersections.append((start_time, end_time, len(active_users)))
            current_time = time_point

        if event_type == 1:
            active_users.add(user_id)
        else: # event_type == -1
            active_users.discard(user_id)

    return intersections


def _find_full_intersection_for_day(
    user_slots: List[Tuple[time, time, int]],  # [(start, end, user_id), ...]
    required_duration_min: int,
    total_participants: int
) -> List[Tuple[time, time, int]]:  # [(start, end, count), ...]
    """
    Find time blocks where ALL participants are available for the required duration.
    """
    # This function finds intervals where *ALL* given participants are free.
    # It's more complex and requires grouping by user first, then finding common parts.

    # Group slots by user
    slots_by_user: Dict[int, List[Tuple[time, time]]] = defaultdict(list)
    for start, end, uid in user_slots:
        slots_by_user[uid].append((start, end))

    user_ids = list(slots_by_user.keys())
    if len(user_ids) != total_participants:
        # Not all participants responded yet, this shouldn't happen if called correctly
        return []

    # Find intersection of all users' slots
    # Start with the first user's slots
    common_ranges = slots_by_user[user_ids[0]]

    for uid in user_ids[1:]:
        user_ranges = slots_by_user[uid]
        common_ranges = _intersect_two_slot_lists(common_ranges, user_ranges)
        if not common_ranges:
            break # No common slots left

    # Filter by required duration and convert to desired format
    valid_common_slots = []
    for start, end in common_ranges:
        duration = timedelta(hours=end.hour, minutes=end.minute) - timedelta(hours=start.hour, minutes=start.minute)
        if duration.total_seconds() // 60 >= required_duration_min:
            valid_common_slots.append((start, end, len(user_ids)))

    return valid_common_slots


def _intersect_two_slot_lists(
    list_a: List[Tuple[time, time]],
    list_b: List[Tuple[time, time]]
) -> List[Tuple[time, time]]:
    """
    Helper to find intersection between two lists of time slots.
    Each list contains (start_time, end_time) tuples.
    Assumes slots within each list do not overlap.
    """
    result = []
    i, j = 0, 0
    while i < len(list_a) and j < len(list_b):
        a_start, a_end = list_a[i]
        b_start, b_end = list_b[j]

        # Convert to timedelta for easier calculation
        a_start_td = timedelta(hours=a_start.hour, minutes=a_start.minute)
        a_end_td = timedelta(hours=a_end.hour, minutes=a_end.minute)
        b_start_td = timedelta(hours=b_start.hour, minutes=b_start.minute)
        b_end_td = timedelta(hours=b_end.hour, minutes=b_end.minute)

        # Find overlap start and end
        ov_start_td = max(a_start_td, b_start_td)
        ov_end_td = min(a_end_td, b_end_td)

        if ov_start_td < ov_end_td: # There is an overlap
            ov_start_time = (datetime.min + ov_start_td).time()
            ov_end_time = (datetime.min + ov_end_td).time()
            result.append((ov_start_time, ov_end_time))

        # Move pointer of the interval that ends earlier
        if a_end_td <= b_end_td:
            i += 1
        if b_end_td <= a_end_td:
            j += 1

    return result
