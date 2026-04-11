"""
invoices 模块 — 加密货币支付账单管理。

并发控制策略
============

本模块存在两种并发控制策略，按场景选择：

1. **悲观锁（select_for_update）**——用于需要读-改-写同一行的路径。
   加锁顺序：先 Invoice，再 PaySlot。绝对禁止反向加锁。

   - InvoiceService.try_match_invoice() — 无锁探测 → 锁 Invoice → 锁 PaySlot（三步式）
   - tasks.check_expired()          — 先锁 Invoice，再批量更新 PaySlot
   - tasks.fallback_invoice_expired() — 先锁 Invoice 批次，再批量更新 PaySlot

2. **乐观并发（唯一约束 + 重试）**——用于分配 PaySlot 的路径。
   不对 PaySlot 行加 SELECT FOR UPDATE，依赖 uniq_invoice_pay_slot_active
   部分唯一约束防冲突，外层 IntegrityError 重试循环处理并发碰撞。

   - Invoice.select_method() — 锁 Invoice，get_pay_differ 普通 SELECT → INSERT → 重试

   原因：get_pay_differ 的候选范围跨 101×N 行，悲观锁会与 FK 约束检查
   （FOR KEY SHARE on Project）形成环形等待，导致死锁。

新增涉及 Invoice + PaySlot 并发写入的路径时，必须遵守上述协议。
"""
