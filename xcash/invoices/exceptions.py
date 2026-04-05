class InvoiceStatusError(Exception):
    """账单状态不满足操作前置条件时抛出。"""


class InvoiceAllocationError(Exception):
    """账单无法分配收款地址/金额组合时抛出。"""
