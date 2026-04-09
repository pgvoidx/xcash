from datetime import timedelta

from django.utils import timezone


def ago(days=0, hours=0, minutes=0, seconds=0):
    return timezone.now() - timedelta(
        days=days,
        hours=hours,
        minutes=minutes,
        seconds=seconds,
    )
