# bit → bitcoin-utils 库迁移设计

## 背景

当前项目使用 `bit` 库（v0.8.0）进行 Bitcoin 交易构造和签名。该库已长期不维护（58 个未关闭 issue，CI 仍用 Travis CI），且原生 SegWit 支持需要 workaround（手动设 `type='p2wkh'`）。

刚完成的 Native SegWit 改造验证了 `bit` 在正确配置下可以工作，但长期依赖一个不维护的库存在风险：Python 版本兼容性、安全漏洞无人修复。

## 目标

- 将 `bit` 库替换为 `bitcoin-utils`（v0.8.1，2026-03 活跃维护）
- 仅替换交易构造层，不改变系统分层架构
- 保持所有现有业务语义不变：UTXO 选币、费率估算、RBF、异步广播、signer 隔离

## 非目标

- 不改变 UTXO 选币逻辑
- 不改变费率估算模型
- 不引入 PSBT/Taproot
- 不改变 signer 与主应用的 RPC 契约

## 迁移映射

### API 替换

| `bit` 用法 | `bitcoin-utils` 替代 |
|-----------|---------------------|
| 动态加载 `PrivateKey`/`PrivateKeyTestnet` | `PrivateKey.from_wif(wif)` — 全局 `setup()` 决定网络 |
| `key.create_transaction(outputs, fee, leftover, unspents, replace_by_fee)` | 显式构造 `Transaction` + `key.sign_segwit_input()` + witness |
| `Unspent(amount, script, txid, txindex, type='p2wkh')` | `TxInput(txid, txout_index, sequence=...)` — 金额在签名时传入 |
| `calc_txid(hex)` / `compute_txid()` | `Transaction.from_raw(hex).get_txid()` |
| RBF: `replace_by_fee=True` | 默认 sequence=`0xFFFFFFFD` 已是 opt-in RBF |
| RBF 关闭 | `TxInput(..., sequence=b'\xfe\xff\xff\xff')` |
| `bit_private_key_class_name` 配置 | 移除 — `setup()` 全局切网络 |

### 网络初始化

`bitcoin-utils` 使用全局 `setup('mainnet'/'testnet'/'regtest')` 切换网络。在 signer 和主应用各自的 `AppConfig.ready()` 中调用：

```python
from bitcoinutils.setup import setup
from django.apps import AppConfig

class BitcoinConfig(AppConfig):
    def ready(self):
        network = get_active_bitcoin_network()
        setup(network.bitcoinutils_network)
```

其中 `bitcoinutils_network` 是新增到 `BitcoinNetworkConfig` 的字段，取值为 `'mainnet'`、`'testnet'`、`'regtest'`（signet 映射到 `'testnet'`）。

### 交易构造变化

当前 `bit` 的 `create_transaction()` 内部隐式处理找零计算和 fee 扣减。切到 `bitcoin-utils` 后，由调用方显式控制所有输出，消除隐式行为。

**当前流程（bit）：**
```python
key = PrivateKey(wif)
signed_hex = key.create_transaction(
    outputs=[(to, amount_satoshi, "satoshi")],
    fee=fee_satoshi,
    absolute_fee=True,
    leftover=source_address,   # bit 内部计算找零
    unspents=bit_utxos,
    replace_by_fee=replaceable,
)
```

**新流程（bitcoin-utils）：**
```python
from bitcoinutils.keys import PrivateKey, P2wpkhAddress
from bitcoinutils.transactions import Transaction, TxInput, TxOutput, TxWitnessInput

key = PrivateKey.from_wif(wif)
pub = key.get_public_key()

# 构造输入（sequence 控制 RBF）
sequence = DEFAULT_TX_SEQUENCE if replaceable else NON_RBF_SEQUENCE
inputs = [TxInput(utxo["txid"], utxo["vout"], sequence=sequence) for utxo in utxos]

# 构造输出：目标 + 找零
outputs = [TxOutput(amount_satoshi, address_to_script(to))]
total_input = sum(utxo_amounts)
change = total_input - amount_satoshi - fee_satoshi
if change > 0:
    outputs.append(TxOutput(change, P2wpkhAddress(source_address).to_script_pub_key()))

# 构建并签名
tx = Transaction(inputs, outputs, has_segwit=True)
script_code = pub.get_address().to_script_pub_key()
for i, utxo in enumerate(utxos):
    sig = key.sign_segwit_input(tx, i, script_code, utxo_amounts[i])
    tx.witnesses.append(TxWitnessInput([sig, pub.to_hex()]))

signed_hex = tx.serialize()
txid = tx.get_txid()
```

### 地址到输出脚本的映射

需要一个辅助函数将目标地址（P2PKH/P2SH/P2WPKH）转为对应的 `Script`：

```python
from bitcoinutils.keys import P2pkhAddress, P2shAddress, P2wpkhAddress
from common.utils.bitcoin import classify_bitcoin_address

def address_to_script_pub_key(address: str) -> Script:
    addr_type = classify_bitcoin_address(address)
    if addr_type == "p2wpkh":
        return P2wpkhAddress(address).to_script_pub_key()
    if addr_type == "p2sh":
        return P2shAddress(address).to_script_pub_key()
    return P2pkhAddress(address).to_script_pub_key()
```

## 代码边界

### signer 端

- `signer/bitcoin_support/network.py`
  - 移除 `bit_private_key_class_name` 字段
  - 新增 `bitcoinutils_network: str` 字段
- `signer/bitcoin_support/utils.py`
  - `compute_txid` 改用 `Transaction.from_raw().get_txid()`
  - `privkey_bytes_to_wif` 可改用 `PrivateKey(secret_exponent=...).to_wif()`
  - 移除对 `bit` 的依赖
- `signer/bitcoin_support/apps.py`（新建）
  - `AppConfig.ready()` 中调用 `setup()`
- `signer/wallets/views.py`
  - 移除 `_load_bit_dependencies`、`_convert_to_bit_unspents`
  - 重写 `SignBitcoinView.post()` 中的交易构造和签名逻辑
  - 新增 `_build_and_sign_segwit_tx()` 辅助方法
- `signer/wallets/tests.py`
  - 更新 DummyKey/DummyUnspent mock 为新 API 对应的 mock
- `signer/pyproject.toml`
  - `bit>=0.8.0` → `bitcoin-utils>=0.8.0`

### 主应用端

- `xcash/bitcoin/network.py`
  - 移除 `bit_private_key_class_name` 字段
  - 新增 `bitcoinutils_network: str` 字段
- `xcash/bitcoin/utils.py`
  - `compute_txid` 改用 `Transaction.from_raw().get_txid()`
  - `privkey_bytes_to_wif` 可改用 `PrivateKey(secret_exponent=...).to_wif()`
  - 移除对 `bit` 的依赖
- `xcash/bitcoin/apps.py`
  - `AppConfig.ready()` 中调用 `setup()`
- `xcash/chains/test_signer.py`
  - 移除 `_load_bit_dependencies`
  - 重写 `sign_bitcoin_transaction()` 为显式 `Transaction` 构造
- `pyproject.toml`
  - `bit>=0.8.0` → `bitcoin-utils>=0.8.0`

## 找零逻辑

当前 `bit` 的 `create_transaction` 内部自动处理找零（`leftover` 参数）。切换后，找零逻辑需要在 signer 端显式实现：

1. 计算 `change = total_input - amount_satoshi - fee_satoshi`
2. 如果 `change > dust_limit`：添加找零输出到 `source_address`
3. 如果 `0 < change <= dust_limit`：将找零并入 fee（不创建输出）
4. 如果 `change == 0`：不创建找零输出（sweep 场景）
5. 如果 `change < 0`：拒绝签名（余额不足）

这些逻辑当前隐含在 `bit` 内部，需要显式化。dust limit 已在 signer views.py 中定义（`_BTC_DUST_LIMIT = 294`）。

## 测试策略

- signer 签名测试需更新 mock 结构
- `compute_txid` 测试保持不变（函数签名不变）
- 无需新增测试——替换的是底层库调用，业务逻辑未变
- 端到端验证：BIP84 地址 + 新签名管线 + txid 计算

## 风险

### 风险 1：bitcoin-utils 标注 "not meant for production yet"

缓解：
- 该库实际功能完整（SegWit/Taproot/PSBT），标注偏保守
- 我们仅使用其最基础的 P2WPKH 签名能力
- 项目尚未上线，有充分时间验证

### 风险 2：全局 setup() 在测试中的副作用

缓解：
- 测试环境统一使用 `regtest`，与 `BITCOIN_NETWORK` 设置一致
- `AppConfig.ready()` 在测试进程启动时执行一次，不会在测试间切换

### 风险 3：找零逻辑从隐式变显式可能引入 bug

缓解：
- 找零逻辑简单（5 行代码）
- 已有 dust limit 常量和选币逻辑保证输入总额 >= 输出 + fee
- 通过测试覆盖所有分支
