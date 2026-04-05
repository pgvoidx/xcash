from celery import shared_task

from alerts.service import TelegramAlertError
from alerts.service import TelegramAlertService


@shared_task(
    ignore_result=True,
    autoretry_for=(TelegramAlertError,),
    retry_backoff=True,
    max_retries=3,
    retry_backoff_max=300,
)
def send_project_telegram_alert(*, state_id: int, mode: str) -> None:
    TelegramAlertService().send_state_message(state_id=state_id, mode=mode)


@shared_task(
    ignore_result=True,
    autoretry_for=(TelegramAlertError,),
    retry_backoff=True,
    max_retries=3,
    retry_backoff_max=300,
)
def send_project_telegram_test(*, config_id: int) -> None:
    TelegramAlertService().send_test_message(config_id=config_id)
