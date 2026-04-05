from __future__ import annotations

from typing import Any

from django.db import transaction

from webhooks.models import WebhookEvent


class WebhookService:
    """封装 webhook 事件的创建与状态更新，供业务模块调用。"""

    @staticmethod
    def enqueue_delivery(event: WebhookEvent) -> None:
        """在事务提交后派发投递任务，避免回滚后仍消费悬空 WebhookEvent。"""
        from webhooks.tasks import deliver_event

        transaction.on_commit(lambda event_id=event.pk: deliver_event.delay(event_id))

    @staticmethod
    def create_event(*, project, payload: dict[str, Any]) -> WebhookEvent:
        event = WebhookEvent.objects.create(project=project, payload=payload)
        WebhookService.enqueue_delivery(event)
        return event
