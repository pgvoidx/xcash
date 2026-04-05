from rest_framework.throttling import SimpleRateThrottle


class BaseInvoiceThrottle(SimpleRateThrottle):
    """Invoice 公开端点的公共限流基类，按 sys_no + IP 双维度限流。"""

    def get_cache_key(self, request, view):
        # 以 sys_no（路径参数）+ 客户端 IP 作为限流维度
        sys_no = view.kwargs.get("sys_no", "unknown")
        ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": f"{sys_no}:{ident}"}


class InvoiceRetrieveThrottle(BaseInvoiceThrottle):
    """公开账单详情接口的频率限制。

    前端通常会对详情页轮询支付状态，因此需要独立于 select_method 限流。
    """

    scope = "invoice_retrieve"


class AppidThrottle(SimpleRateThrottle):
    """按 appid 维度限流，用于商户 API 高风险操作。"""

    def get_cache_key(self, request, view):
        from common.consts import APPID_HEADER

        appid = request.headers.get(APPID_HEADER, "unknown")
        ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": f"{appid}:{ident}"}


class WithdrawalCreateThrottle(AppidThrottle):
    """提币创建接口的频率限制，防止批量发起提币耗尽资金。"""

    scope = "withdrawal_create"


class DepositAddressThrottle(AppidThrottle):
    """充值地址获取接口的频率限制，防止批量占用 HD 地址空间。"""

    scope = "deposit_address"


class InvoiceSelectMethodThrottle(BaseInvoiceThrottle):
    """公开切换支付方式接口的频率限制。

    防止攻击者无凭证枚举账单或滥用 select_method 消耗 PaySlot 配额。
    """

    scope = "invoice_select_method"
