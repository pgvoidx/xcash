"""
invoices 模块 — 加密货币支付账单管理。

加锁协议（Locking Protocol）
===========================

为防止死锁，本模块所有并发路径必须遵守以下加锁顺序：

    1. 先锁 Invoice 行（select_for_update）
    2. 再锁 InvoicePaySlot 行（select_for_update）

绝对禁止反向加锁（先 PaySlot 再 Invoice），否则会与 select_method / try_match_invoice
的锁顺序形成循环等待，导致数据库死锁。

涉及的关键路径：
- Invoice.select_method()        — 先锁 Invoice，再在 get_pay_differ 中锁 PaySlot
- InvoiceService.try_match_invoice() — 无锁探测 → 锁 Invoice → 锁 PaySlot（三步式）
- tasks.check_expired()          — 先锁 Invoice，再批量更新 PaySlot
- tasks.fallback_invoice_expired() — 先锁 Invoice 批次，再批量更新 PaySlot

新增涉及 Invoice + PaySlot 并发写入的路径时，必须遵守此协议。
"""
