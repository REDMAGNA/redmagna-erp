"""Business-time arithmetic for optional support SLA calendars."""

from datetime import date, datetime, time, timedelta, timezone as datetime_timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ValidationError
from django.utils import timezone


WEEKDAYS = {str(day) for day in range(7)}


def validate_calendar(schedule, timezone_name):
    if not isinstance(schedule, dict):
        raise ValidationError("El calendario SLA debe ser un objeto con días de semana e intervalos.")
    if set(schedule) - WEEKDAYS:
        raise ValidationError("Usa claves de día de semana de 0 (lunes) a 6 (domingo).")
    try:
        ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, TypeError, ValueError):
        raise ValidationError({"calendar_timezone": "Selecciona una zona horaria IANA válida."}) from None
    interval_count = 0
    for weekday, intervals in schedule.items():
        if not isinstance(intervals, list):
            raise ValidationError(f"Los intervalos del día {weekday} deben ser una lista.")
        previous_end = None
        for interval in intervals:
            if not isinstance(interval, (list, tuple)) or len(interval) != 2:
                raise ValidationError("Cada intervalo debe contener hora de inicio y hora de fin (HH:MM).")
            try:
                start = time.fromisoformat(interval[0])
                end = time.fromisoformat(interval[1])
            except (TypeError, ValueError):
                raise ValidationError("Las horas del calendario deben usar el formato HH:MM.") from None
            if start.tzinfo or end.tzinfo or start >= end:
                raise ValidationError("Cada intervalo debe tener horas locales válidas y terminar después de iniciar.")
            if start.second or start.microsecond or end.second or end.microsecond:
                raise ValidationError("Configura los intervalos con precisión de minutos (HH:MM).")
            if previous_end is not None and start < previous_end:
                raise ValidationError("Los intervalos diarios no pueden traslaparse y deben estar ordenados.")
            previous_end = end
            interval_count += 1
    if schedule and not interval_count:
        raise ValidationError("El calendario debe incluir al menos un intervalo laborable o dejarse vacío para usar minutos corridos.")


def _local_interval(day: date, interval, zone):
    start_time, end_time = (time.fromisoformat(value) for value in interval)
    return (
        datetime.combine(day, start_time, tzinfo=zone),
        datetime.combine(day, end_time, tzinfo=zone),
    )


def add_working_seconds(start_at, seconds, schedule, timezone_name):
    """Add seconds inside weekly local-time intervals, skipping closed time."""
    if not schedule:
        return start_at + timedelta(seconds=seconds)
    zone = ZoneInfo(timezone_name)
    cursor = timezone.localtime(start_at, zone)
    remaining = max(0, int(seconds))
    for _ in range(3660):
        intervals = schedule.get(str(cursor.weekday()), [])
        for interval in intervals:
            interval_start, interval_end = _local_interval(cursor.date(), interval, zone)
            if cursor >= interval_end:
                continue
            if cursor < interval_start:
                cursor = interval_start
            cursor_utc = cursor.astimezone(datetime_timezone.utc)
            interval_end_utc = interval_end.astimezone(datetime_timezone.utc)
            available = max(0, int((interval_end_utc - cursor_utc).total_seconds()))
            if remaining <= available:
                return (cursor_utc + timedelta(seconds=remaining)).astimezone(timezone.get_current_timezone())
            remaining -= available
            cursor = interval_end
        cursor = datetime.combine(cursor.date() + timedelta(days=1), time.min, tzinfo=zone)
    raise ValidationError("El calendario SLA no permite calcular el vencimiento dentro del horizonte disponible.")


def working_seconds_between(start_at, end_at, schedule, timezone_name):
    """Count scheduled seconds in a pause interval, ignoring closed periods."""
    if end_at <= start_at or not schedule:
        return max(0, int((end_at - start_at).total_seconds())) if not schedule else 0
    zone = ZoneInfo(timezone_name)
    local_start = timezone.localtime(start_at, zone)
    local_end = timezone.localtime(end_at, zone)
    total = 0
    day = local_start.date()
    while day <= local_end.date():
        for interval in schedule.get(str(day.weekday()), []):
            interval_start, interval_end = _local_interval(day, interval, zone)
            left = max(start_at, interval_start.astimezone(start_at.tzinfo))
            right = min(end_at, interval_end.astimezone(end_at.tzinfo))
            if right > left:
                total += int((right - left).total_seconds())
        day += timedelta(days=1)
    return total
