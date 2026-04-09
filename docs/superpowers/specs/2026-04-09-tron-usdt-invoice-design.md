# Tron USDT Invoice 收款设计方案

**日期**: 2026-04-09

## 1. 背景

当前系统已经具备两类成熟链路：

- `EVM`：内部自扫描器发现原生币直转和 ERC-20 `Transfer`，统一写入 `OnchainTransfer`，再由公共业务层完成 Invoice / Deposit / Withdrawal 的匹配与状态流转。
- `Bitcoin`：独立扫描器发现 BTC 收款，仍通过统一的 `OnchainTransfer` 和业务状态机推进后续流程。

这说明系统的正确扩展点不是为新链重写一套支付业务，而是让新链扫描器只负责把“链上已观察到的转账”转换成统一输入，再复用既有业务流。

本次需求只需要支持 `Tron` 网络上的 `USDT` 收款，目标是让商户可以在 Invoice 场景中使用 `TRON-USDT` 作为支付方式。需求明确不包含 `Tron` 充币地址派生、充币归集、提币、内部签名与广播。

## 2. 目标与非目标

### 2.1 目标

- 支持创建 `TRON` 链配置，并使 `USDT@TRON` 出现在 Invoice 可选支付方式中。
- 支持商户在后台配置 `TRON` 收款地址，仅用于 Invoice 收款。
- 支持扫描 `TRC20 USDT` 转账，并与现有 Invoice 支付槽位匹配。
- 继续复用现有 `OnchainTransfer -> InvoiceService -> Webhook` 主干，不新增平行业务状态机。
- 保持首版范围收敛，避免把 `Tron` 自动扩展为完整的充币 / 提币能力。

### 2.2 非目标

- 不支持 `Tron` 充币地址申请。
- 不支持 `Tron` 充值归集。
- 不支持 `Tron` 提币。
- 不支持 `Tron` signer 扩展、HD 地址派生和内部广播任务。
- 不支持 `TRX` 或其他 `TRC20` 资产。
- 不做自建 `Java-Tron + Event Plugin + MongoDB` 事件总线部署。

## 3. 核心设计结论

### 3.1 首版以 `Invoice-only` 作为产品边界

`Tron` 会进入 `ChainType`，但不会自动成为完整业务链类型。系统必须显式区分“链类型”和“业务能力”：

- `Invoice`：允许 `TRON + USDT`
- `Deposit`：拒绝 `TRON`
- `Withdrawal`：拒绝 `TRON`

原因：

- 当前代码里很多入口只要看到 `active chain + active crypto` 就会继续向下执行。
- 如果只是把 `TRON` 加进 `ChainType` 而不做能力隔离，`Deposit API` 和 `Withdrawal API` 很容易把 `TRON` 当成已正式支持的业务链，造成范围泄漏和错误行为。

### 3.2 扫描器采用“按收款地址轮询 confirmed USDT 历史”的策略

首版扫描器不做全链事件订阅，而是按每个项目配置的 Tron 收款地址轮询其 `USDT` 转账历史：

- 过滤条件只关注 `USDT@TRON` 合约
- 只拉取 `confirmed / solidified` 记录
- 仅处理系统内已配置的收款地址

原因：

- 本次只做 Invoice 收款，不存在海量系统地址扫描需求。
- 现有业务只需要命中系统收款地址，不需要全链数据湖。
- `confirmed-only` 可以显著降低 reorg、removed log、未确认回滚等复杂性。
- 后续若业务量增大，再把底层扫描源替换为 `Java-Tron` 事件插件，上层 `ObservedTransferPayload` 和业务主干仍可复用。

### 3.3 继续复用统一 `OnchainTransfer` 主干

Tron 扫描器发现一条 `USDT Transfer` 后，必须继续走：

1. 解析为统一的 `ObservedTransferPayload`
2. 调用 `TransferService.create_observed_transfer()`
3. 由 `OnchainTransfer.process()` 进入 `InvoiceService.try_match_invoice()`
4. 由现有确认与 webhook 逻辑完成终态推进

明确不为 Tron 单独引入 `TronInvoicePayment` 之类的旁路模型，否则会重复实现：

- 幂等
- 业务锁顺序
- Invoice 支付槽匹配
- webhook 推送
- 后续统一统计与排障能力

### 3.4 地址格式统一存 `Base58Check`

数据库中 Tron 地址统一存可读的 `Base58Check` 地址，不存内部十六进制格式。

原因：

- 后台录入地址、前端展示地址、商户认知都以 Base58 为主。
- Tron HTTP 生态的账户类接口通常天然接受 Base58。
- 只有在日志解析和 topic 比对时才需要切换到 `41` 前缀十六进制或 20-byte 地址表示。

因此需要一个集中 `TronAddressCodec`，负责：

- `base58 -> hex41`
- `hex41 -> base58`
- `hex41/topic -> 标准 Base58`
- 输入地址规范化与合法性校验

禁止把这些转换逻辑散落在扫描器、adapter、admin 表单里各写一份。

## 4. 架构方案

### 4.1 数据与模块边界

新增 `xcash/tron/` app，职责只包括：

- `TronHttpClient`：对 TronGrid 或兼容 HTTP provider 发起请求
- `TronAddressCodec`：地址规范化与格式互转
- `TronUsdtPaymentScanner`：轮询已配置收款地址的 USDT 转账
- `TronWatchCursor`：记录每个 `(chain, watch_address)` 的扫描推进位置
- `TronAdapter`：补齐公共链任务依赖的最小能力
- `tron.tasks`：Celery 扫描任务入口

明确不在 `tron` app 内实现：

- 提币广播
- 充值地址派生
- 归集策略
- signer 通信

### 4.2 公共层改动

### A. `ChainType`

在主应用与 signer 侧都需要新增 `TRON` 枚举，但 signer 只做“枚举感知”，不做任何地址派生或签名能力。

首版要求：

- 主应用允许创建 `TRON` 类型链
- signer 相关接口若收到 `TRON`，应明确拒绝，而不是误入默认分支

### B. 地址字段

`AddressField` 需要支持：

- EVM checksum 地址
- Bitcoin 地址
- Tron Base58 地址

同时要新增 Tron 地址验证工具，避免将合法性校验写死在 admin 表单层。

### C. 产品能力策略

新增一个集中策略层，例如 `ChainProductCapabilityService`，负责回答：

- 某链类型能否作为 Invoice 收款链
- 某链类型能否申请 Deposit 地址
- 某链类型能否发起 Withdrawal
- 某链和币种组合是否允许出现在正式产品入口

这样可以在 `Invoice / Deposit / Withdrawal` 三个入口共享判断逻辑，避免未来每个视图自己维护 allowlist。

### 4.3 Tron 扫描器设计

### 扫描对象

扫描器只关注：

- 活跃 `TRON` 链
- 活跃 `USDT@TRON` 合约
- 所有 `used_for_invoice=True` 的 Tron 收款地址

不扫描：

- `used_for_deposit=True` 地址
- 未激活资产
- 其他 TRC20 合约
- TRX 转账

### 游标模型

新增 `TronWatchCursor`，维度为 `(chain, address)`。

建议字段：

- `chain`
- `watch_address`
- `last_fingerprint`
- `last_block_number`
- `last_timestamp`
- `enabled`
- `last_error`
- `last_error_at`
- `updated_at`

`last_fingerprint` 用于幂等推进，建议由下列字段拼接：

- `transaction_id`
- `log_index` 或 provider 返回的唯一事件序号

原因：

- 首版是按地址轮询，不是整链顺序扫描。
- 不同地址的事件流互不依赖，独立 cursor 更简单。
- 地址粒度的失败不会阻塞整条链。

### 扫描流程

每轮任务执行：

1. 找到所有活跃 `TRON` 链
2. 找到每条链上所有 Invoice 收款地址
3. 为每个地址加载或创建 `TronWatchCursor`
4. 调用 provider 查询该地址的 `USDT` TRC20 历史
5. 过滤掉已在 cursor 之前处理过的记录
6. 将每条记录解析为统一 `ObservedTransferPayload`
7. 调用 `TransferService.create_observed_transfer()`
8. 推进 cursor

### 为什么选择 `confirmed-only`

首版扫描器只接收 provider 已标记为 confirmed 的交易，理由：

- 需求只要求收款匹配，不要求“未确认即展示”
- 当前系统里 `Bitcoin` 与 `EVM` 已经各自承担了链特有复杂度，Tron 首版应避免再引入未确认状态的额外分支
- 这样可以不实现 reorg 回退和 removed event 处理

这意味着 Tron 首版的到账体验偏稳健，不追求秒级“待确认”反馈。

### 4.4 交易落库与匹配

Tron `USDT Transfer` 解析后，统一映射为：

- `hash = tx_id`
- `event_id = trc20:<log_index>`
- `from_address = 标准 Base58`
- `to_address = 标准 Base58`
- `crypto = USDT`
- `value = 链上原始整数`
- `amount = value / 10^decimals`

这样可以复用现有 `(chain, hash, event_id)` 唯一键语义：

- 同一笔交易的不同事件不会冲突
- 同一事件重复扫描是天然幂等

一旦 `OnchainTransfer` 创建成功，后续继续由公共业务层完成：

- Invoice 支付槽匹配
- 支付状态推进
- webhook 创建

### 4.5 确认与终态

Tron 首版虽然只摄入已确认交易，但仍保留统一确认主干，不在扫描器内部直接跳过 `transfer.confirm()`。

实现方式：

- `TronAdapter.tx_result()` 对已存在的链上交易返回 `CONFIRMED`
- `Chain.get_latest_block_number` 支持 `TRON`
- `confirm_block_count` 对 Tron V1 明确设为 `0`

这样系统仍通过统一 `confirm_transfer` 和 `block_number_updated` 推进终态，不新增 Tron 特判式终态分支。

之所以选择 `0`：

- 扫描器本身只摄入 provider 已确认的交易
- 首版不需要再叠加“本系统额外等待 N 个区块”的二次确认逻辑
- 这样可以复用现有公共确认任务，同时避免 UI 和状态机再引入一套 Tron 专属确认进度解释

设计要求：

- 不能让 Tron 扫描器直接绕过 `OnchainTransfer.confirm()` 去改 Invoice 终态
- 不能因为“已经是 confirmed 交易”就复制一套立即完成逻辑

### 4.6 管理后台与配置

后台需要支持：

- 创建 `TRON` 链
- 在 `ChainToken` 中配置 `USDT@TRON` 合约地址与精度
- 在项目中录入 `TRON` 收款地址
- 查看 Tron 扫描游标状态

后台必须明确文案边界：

- `TRON` 地址目前仅用于账单收款
- 不用于充币归集
- 不用于提币

## 5. 数据流

### 5.1 配置阶段

1. 管理员创建 `TRON` 链，填入 provider endpoint
2. 管理员创建或启用 `USDT`，并配置 `USDT@TRON` 的 `ChainToken`
3. 商户项目配置 `TRON` 收款地址，标记 `used_for_invoice=True`

### 5.2 支付阶段

1. 商户创建 Invoice
2. `Invoice.available_methods()` 发现当前项目具备 `USDT -> [tron-xxx]`
3. 用户选择 `TRON-USDT`
4. 系统沿用现有 differ 逻辑生成 `(pay_address, pay_amount)` 支付槽
5. 用户转入 Tron USDT
6. `TronUsdtPaymentScanner` 轮询到该地址的 confirmed TRC20 Transfer
7. 扫描器写入 `OnchainTransfer`
8. `OnchainTransfer.process()` 匹配命中 Invoice
9. 统一确认流程推进到 `Invoice.COMPLETED`
10. 现有 webhook 机制通知商户

## 6. 需要刻意避免的设计

### 6.1 不新增 Tron 专属 Invoice 模型

这是最容易“看起来快，后面最难收”的方案，会复制：

- 收款匹配逻辑
- 并发锁顺序
- webhook
- 状态机

不采用。

### 6.2 不在首版引入 signer / 派生地址

本次没有 Tron 充值和提币需求，把 Tron 接到 signer 只会扩大范围，并迫使：

- HD 派生路径重新设计
- 内部地址识别扩展
- 签名与广播接口扩展

不采用。

### 6.3 不依赖“当前先不用”来做能力控制

仅靠运营约定或文档声明“Tron 先不做充提币”是不够的，系统必须在代码层显式拒绝，否则行为会漏出到：

- `DepositViewSet.address`
- `WithdrawalViewSet.create`
- 相关序列化器与服务层

## 7. 风险与应对

### 风险 1：地址格式混乱导致匹配失败

表现：

- provider 返回 hex / topic 地址
- 后台录入的是 Base58
- 支付槽存的是原样字符串

应对：

- 一律以 `Base58` 作为数据库标准地址
- 所有 Tron 地址进系统前统一走 `TronAddressCodec.normalize_base58`

### 风险 2：新增 `ChainType.TRON` 后误入充提币入口

应对：

- 引入集中能力策略
- 在 API 入口和 service 层双重拦截
- 为拒绝行为补测试

### 风险 3：扫描器重复消费

应对：

- 依赖 `(chain, hash, event_id)` 唯一键保证最终幂等
- cursor 使用事件级 fingerprint，避免分页窗口重叠导致重复推进

### 风险 4：provider 不稳定

应对：

- 所有 HTTP 调用必须带超时
- 记录结构化错误日志
- 单地址 cursor 错误不阻塞其他地址
- 未来允许切换到底层自建节点事件源

## 8. 测试策略

只为“行为正确性”补测试，不为后台展示配置写脆弱测试。

必须补的测试：

- Tron 地址校验与规范化测试
- `Invoice` 能力开放测试：`TRON-USDT` 可进入支付方式
- `Deposit` 拒绝测试：Tron 不允许申请充币地址
- `Withdrawal` 拒绝测试：Tron 不允许发起提币
- 扫描器解析测试：provider 响应正确生成 `ObservedTransferPayload`
- 幂等测试：同一 `tx_id + log_index` 重放不重复创建 `OnchainTransfer`
- 账单匹配测试：Tron USDT 转账命中 pay slot 并完成 Invoice 流程

首版不要求：

- admin 展示测试
- 自建 Tron 节点集成测试
- 充币/提币链路测试

## 9. 分阶段实施建议

### Phase 1：最小接入

- `ChainType.TRON`
- Tron 地址字段支持
- 能力策略
- Tron 链和 `USDT@TRON` 配置
- 扫描器写入 `OnchainTransfer`
- Invoice 命中闭环

### Phase 2：治理与观测

- Tron 游标后台页
- 更完整的错误监控
- provider 指标与扫描耗时统计

### Phase 3：后续可扩展项

仅在确有业务需要时再考虑：

- Tron 充值地址
- Tron 归集
- Tron 提币
- 自建 Java-Tron 事件基础设施

## 10. 最终决策

本次采用以下方案：

- 将 `TRON` 作为正式链类型引入
- 产品能力上只开放 `Invoice 收款`
- 首版只支持 `USDT@TRON`
- 扫描器按“收款地址 + confirmed USDT 历史”轮询
- 统一复用 `OnchainTransfer` 和现有 Invoice 主链路
- 明确拒绝 Tron 充币地址、归集、提币、signer 扩展

这条路线对当前代码库的侵入最小，同时保留未来向完整 Tron 能力扩展的演进路径。
