import httpx
import structlog
from celery import shared_task

from currencies.models import Crypto
from currencies.models import Fiat

logger = structlog.get_logger()


@shared_task(
    ignore_result=True,
)
def refresh_crypto_prices():
    crypto_ids = list(
        # 占位币的 coingecko_id 只是内部标识，不能拿去请求真实行情。
        Crypto.objects.filter(active=True, coingecko_id__isnull=False)
        .exclude(coingecko_id="")
        .values_list(
            "coingecko_id",
            flat=True,
        )
    )

    if not crypto_ids:
        return

    fiat_codes = list(
        Fiat.objects.all().values_list(
            "code",
            flat=True,
        )
    )

    if not fiat_codes:
        return

    # 修复：拆分 f-string，避免语法错误阻断 Celery task 导入。
    api_url = (
        "https://api.coingecko.com/api/v3/simple/price"
        f"?ids={','.join(crypto_ids)}"
        f"&vs_currencies={','.join(code.lower() for code in fiat_codes)}"
    )
    try:
        response = httpx.get(api_url, timeout=8)
        response.raise_for_status()
        price_data = response.json()
    except Exception:
        # 外部价格源失败时仅记录日志，避免周期任务异常中断整个 worker。
        logger.exception("刷新加密货币价格失败")
        return

    for crypto_id in crypto_ids:
        crypto = Crypto.objects.get(coingecko_id=crypto_id)
        for fiat_code in fiat_codes:
            price = price_data.get(crypto_id, {}).get(fiat_code.lower(), None)
            if price:
                crypto.prices[fiat_code] = price
        # 价格刷新只更新 JSONField prices，避免把其他字段旧值随任务回写。
        crypto.save(update_fields=["prices"])
