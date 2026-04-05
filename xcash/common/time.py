import random
from datetime import timedelta

from django.utils import timezone


def ago(days=0, hours=0, minutes=0, seconds=0):
    return timezone.now() - timedelta(
        days=days,
        hours=hours,
        minutes=minutes,
        seconds=seconds,
    )


def today():
    """
    返回今天 00:00:00 的 datetime（带 Django 时区信息）
    """
    return timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)


def yesterday():
    """
    返回昨天 00:00:00 的 datetime（带 Django 时区信息）
    """
    return today() - timedelta(days=1)


def this_month():
    """返回本月一号"""
    return timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def last_month():
    """返回上月一号"""
    # 回退一天到上个月最后一天，再取replace为1号
    last_month_date = this_month() - timedelta(days=1)
    return last_month_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def random_delay_within_minutes(minutes=5):
    """返回 0-600 之间的随机秒数"""
    return random.randint(0, 60 * minutes)  # noqa: S311 — 任务调度抖动，非加密用途
