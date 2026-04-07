# bit → bitcoin-utils 迁移实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Bitcoin 交易构造库从已停止维护的 `bit` 替换为活跃维护的 `bitcoin-utils==0.8.1`，保持所有业务语义不变。

**Architecture:** `bitcoin-utils` 使用全局 `setup()` 切换网络，`PrivateKey.from_wif()` 加载密钥，显式构造 `Transaction` + `sign_segwit_input()` 签名。迁移仅替换交易构造层，不改变 UTXO 选币、费率估算、signer 隔离等业务逻辑。

**Tech Stack:** Python 3.13, bitcoin-utils 0.8.1, bip_utils

**Spec:** `docs/superpowers/specs/2026-04-07-bit-to-bitcoin-utils-migration.md`

---

## 文件结构

### signer 端

| 文件 | 动作 | 职责 |
|------|------|------|
| `signer/pyproject.toml` | 修改 | `bit` → `bitcoin-utils==0.8.1` |
| `signer/bitcoin_support/network.py` | 修改 | 移除 `bit_private_key_class_name`，新增 `bitcoinutils_network` |
| `signer/bitcoin_support/utils.py` | 修改 | `compute_txid` 和 `privkey_bytes_to_wif` 切到 bitcoin-utils |
| `signer/wallets/apps.py` | 修改 | `ready()` 中调 `setup()` |
| `signer/wallets/views.py` | 修改 | 重写 `SignBitcoinView` 签名逻辑 |
| `signer/wallets/tests.py` | 修改 | 更新 mock |

### 主应用端

| 文件 | 动作 | 职责 |
|------|------|------|
| `pyproject.toml` | 修改 | `bit` → `bitcoin-utils==0.8.1` |
| `xcash/bitcoin/network.py` | 修改 | 移除 `bit_private_key_class_name`，新增 `bitcoinutils_network` |
| `xcash/bitcoin/utils.py` | 修改 | `compute_txid` 和 `privkey_bytes_to_wif` 切到 bitcoin-utils |
| `xcash/bitcoin/apps.py` | 修改 | `ready()` 中调 `setup()` |
| `xcash/chains/test_signer.py` | 修改 | 重写 `sign_bitcoin_transaction` |

---

## Task 1: 依赖替换

**Files:**
- Modify: `pyproject.toml`
- Modify: `signer/pyproject.toml`

- [ ] **Step 1: 主应用 pyproject.toml 替换依赖**

将 `pyproject.toml` 第 9-10 行：
```
    # Bitcoin：P2PKH 交易构建、UTXO 选择与 secp256k1 签名
    "bit>=0.8.0",
```
替换为：
```
    # Bitcoin：P2WPKH SegWit 交易构建与 secp256k1 签名
    "bitcoin-utils==0.8.1",
```

- [ ] **Step 2: signer pyproject.toml 替换依赖**

将 `signer/pyproject.toml` 第 15 行：
```
    "bit>=0.8.0",
```
替换为：
```
    "bitcoin-utils==0.8.1",
```

- [ ] **Step 3: 安装新依赖**

Run: `/Users/void/.local/bin/uv pip install bitcoin-utils==0.8.1 && /Users/void/.local/bin/uv pip uninstall bit`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml signer/pyproject.toml
git commit -m "chore: replace bit with bitcoin-utils==0.8.1"
```

---

## Task 2: 网络配置 — 两端同步更新

**Files:**
- Modify: `signer/bitcoin_support/network.py`
- Modify: `xcash/bitcoin/network.py`

- [ ] **Step 1: 更新 signer 网络配置**

将 `signer/bitcoin_support/network.py` 整个文件替换为：

```python
from __future__ import annotations

from dataclasses import dataclass

from bip_utils import Bip44Coins
from bip_utils import Bip84Coins
from django.conf import settings


@dataclass(frozen=True)
class BitcoinNetworkConfig:
    """描述 signer 当前运行所使用的 Bitcoin 网络参数。"""

    name: str
    wif_prefix: bytes
    bip44_coin: Bip44Coins
    bip84_coin: Bip84Coins
    bitcoinutils_network: str


BITCOIN_NETWORKS: dict[str, BitcoinNetworkConfig] = {
    "mainnet": BitcoinNetworkConfig(
        name="mainnet",
        wif_prefix=b"\x80",
        bip44_coin=Bip44Coins.BITCOIN,
        bip84_coin=Bip84Coins.BITCOIN,
        bitcoinutils_network="mainnet",
    ),
    # regtest / signet 继续沿用 testnet 的 WIF 与 BIP44 coin 语义。
    "testnet": BitcoinNetworkConfig(
        name="testnet",
        wif_prefix=b"\xef",
        bip44_coin=Bip44Coins.BITCOIN_TESTNET,
        bip84_coin=Bip84Coins.BITCOIN_TESTNET,
        bitcoinutils_network="testnet",
    ),
    "signet": BitcoinNetworkConfig(
        name="signet",
        wif_prefix=b"\xef",
        bip44_coin=Bip44Coins.BITCOIN_TESTNET,
        bip84_coin=Bip84Coins.BITCOIN_TESTNET,
        bitcoinutils_network="testnet",
    ),
    "regtest": BitcoinNetworkConfig(
        name="regtest",
        wif_prefix=b"\xef",
        bip44_coin=Bip44Coins.BITCOIN_TESTNET,
        bip84_coin=Bip84Coins.BITCOIN_REGTEST,
        bitcoinutils_network="regtest",
    ),
}


def get_active_bitcoin_network() -> BitcoinNetworkConfig:
    network_name = settings.BITCOIN_NETWORK.strip().lower()
    try:
        return BITCOIN_NETWORKS[network_name]
    except KeyError as exc:
        supported = ", ".join(sorted(BITCOIN_NETWORKS))
        msg = f"Unsupported BITCOIN_NETWORK={network_name}. Supported: {supported}"
        raise ValueError(msg) from exc
```

- [ ] **Step 2: 更新主应用网络配置**

将 `xcash/bitcoin/network.py` 整个文件替换为：

```python
from __future__ import annotations

from dataclasses import dataclass

import environ
from bip_utils import Bip44Coins
from bip_utils import Bip84Coins

env = environ.Env()


@dataclass(frozen=True)
class BitcoinNetworkConfig:
    """描述当前部署所使用的 Bitcoin 网络参数。"""

    name: str
    p2pkh_version: bytes
    p2sh_version: bytes
    bech32_hrp: str
    wif_prefix: bytes
    bip44_coin: Bip44Coins
    bip84_coin: Bip84Coins
    bitcoinutils_network: str


BITCOIN_NETWORKS: dict[str, BitcoinNetworkConfig] = {
    "mainnet": BitcoinNetworkConfig(
        name="mainnet",
        p2pkh_version=b"\x00",
        p2sh_version=b"\x05",
        bech32_hrp="bc",
        wif_prefix=b"\x80",
        bip44_coin=Bip44Coins.BITCOIN,
        bip84_coin=Bip84Coins.BITCOIN,
        bitcoinutils_network="mainnet",
    ),
    # regtest / signet 沿用 testnet 的 base58/WIF 版本；bech32 HRP 则分别使用 bcrt / tb。
    "testnet": BitcoinNetworkConfig(
        name="testnet",
        p2pkh_version=b"\x6f",
        p2sh_version=b"\xc4",
        bech32_hrp="tb",
        wif_prefix=b"\xef",
        bip44_coin=Bip44Coins.BITCOIN_TESTNET,
        bip84_coin=Bip84Coins.BITCOIN_TESTNET,
        bitcoinutils_network="testnet",
    ),
    "signet": BitcoinNetworkConfig(
        name="signet",
        p2pkh_version=b"\x6f",
        p2sh_version=b"\xc4",
        bech32_hrp="tb",
        wif_prefix=b"\xef",
        bip44_coin=Bip44Coins.BITCOIN_TESTNET,
        bip84_coin=Bip84Coins.BITCOIN_TESTNET,
        bitcoinutils_network="testnet",
    ),
    "regtest": BitcoinNetworkConfig(
        name="regtest",
        p2pkh_version=b"\x6f",
        p2sh_version=b"\xc4",
        bech32_hrp="bcrt",
        wif_prefix=b"\xef",
        bip44_coin=Bip44Coins.BITCOIN_TESTNET,
        bip84_coin=Bip84Coins.BITCOIN_REGTEST,
        bitcoinutils_network="regtest",
    ),
}


def get_active_bitcoin_network() -> BitcoinNetworkConfig:
    """返回当前部署使用的 Bitcoin 网络配置。"""
    network_name = env.str("BITCOIN_NETWORK", default="mainnet").strip().lower()
    try:
        return BITCOIN_NETWORKS[network_name]
    except KeyError as exc:
        supported = ", ".join(sorted(BITCOIN_NETWORKS))
        msg = f"Unsupported BITCOIN_NETWORK={network_name}. Supported: {supported}"
        raise ValueError(msg) from exc
```

- [ ] **Step 3: Commit**

```bash
git add signer/bitcoin_support/network.py xcash/bitcoin/network.py
git commit -m "feat: replace bit_private_key_class_name with bitcoinutils_network in network config"
```

---

## Task 3: AppConfig.ready() 网络初始化

**Files:**
- Modify: `signer/wallets/apps.py`
- Modify: `xcash/bitcoin/apps.py`

- [ ] **Step 1: signer WalletsConfig.ready()**

将 `signer/wallets/apps.py` 替换为：

```python
from django.apps import AppConfig


class WalletsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "wallets"
    verbose_name = "Signer Wallets"

    def ready(self):
        from bitcoin_support.network import get_active_bitcoin_network
        from bitcoinutils.setup import setup

        network = get_active_bitcoin_network()
        setup(network.bitcoinutils_network)
```

- [ ] **Step 2: 主应用 BitcoinConfig.ready()**

将 `xcash/bitcoin/apps.py` 替换为：

```python
from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class BitcoinConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "bitcoin"
    verbose_name = _("Bitcoin")

    def ready(self):
        from bitcoin.network import get_active_bitcoin_network
        from bitcoinutils.setup import setup

        network = get_active_bitcoin_network()
        setup(network.bitcoinutils_network)
```

- [ ] **Step 3: Commit**

```bash
git add signer/wallets/apps.py xcash/bitcoin/apps.py
git commit -m "feat: initialize bitcoin-utils network in AppConfig.ready()"
```

---

## Task 4: signer utils — compute_txid 和 privkey_bytes_to_wif

**Files:**
- Modify: `signer/bitcoin_support/utils.py`

- [ ] **Step 1: 替换 compute_txid 和 privkey_bytes_to_wif**

将 `signer/bitcoin_support/utils.py` 中的 `compute_txid` 函数替换为：

```python
def compute_txid(signed_payload_hex: str) -> str:
    """从已签名原始交易 hex 计算 txid。

    SegWit 交易的 txid 基于去除 witness 数据后的序列化。
    """
    from bitcoinutils.transactions import Transaction

    return Transaction.from_raw(signed_payload_hex).get_txid()
```

将 `privkey_bytes_to_wif` 函数替换为：

```python
def privkey_bytes_to_wif(privkey_bytes: bytes) -> str:
    """将原始 32 字节 secp256k1 私钥转换为当前网络 WIF（压缩格式）。

    依赖 bitcoinutils.setup.setup() 已在 AppConfig.ready() 中按当前网络初始化。
    """
    from bitcoinutils.keys import PrivateKey

    secret_exponent = int.from_bytes(privkey_bytes, byteorder="big")
    return PrivateKey(secret_exponent=secret_exponent).to_wif()
```

同时移除不再需要的导入（`hashlib` 可能仍被其他函数使用，检查后决定）和 `bip_utils.Base58Encoder` 导入（如果只被 `privkey_bytes_to_wif` 使用）。

检查后：`hashlib` 不再被本文件使用（`compute_txid` 不再需要），`Base58Encoder` 不再需要。移除这两个导入。

最终文件头部导入为：
```python
from __future__ import annotations

from decimal import ROUND_DOWN
from decimal import Decimal

from bip_utils import P2PKHAddrDecoder
from bip_utils import P2SHAddrDecoder
from bip_utils import SegwitBech32Decoder

from .network import get_active_bitcoin_network
```

- [ ] **Step 2: Commit**

```bash
git add signer/bitcoin_support/utils.py
git commit -m "feat(signer): switch compute_txid and privkey_bytes_to_wif to bitcoin-utils"
```

---

## Task 5: signer 签名视图重写

**Files:**
- Modify: `signer/wallets/views.py`

这是最核心的改动。将 `SignBitcoinView` 中的 `bit` 交易构造替换为 `bitcoin-utils` 的显式交易构造。

- [ ] **Step 1: 替换 SignBitcoinView 的签名逻辑**

移除 `from importlib import import_module`（如果仅被 `_load_bit_dependencies` 使用——检查后发现 `SignEvmView` 不用它，所以可移除）。

移除以下方法：
- `_load_bit_dependencies`
- `_convert_to_bit_unspents`

替换整个 `SignBitcoinView` 类为：

```python
class SignBitcoinView(SignerAPIView):
    @staticmethod
    def _build_and_sign_segwit_tx(
        *,
        privkey_hex: str,
        source_address: str,
        to: str,
        amount_satoshi: int,
        fee_satoshi: int,
        replaceable: bool,
        utxos: list[dict],
    ) -> tuple[str, str]:
        """构建并签名 P2WPKH SegWit 交易，返回 (txid, signed_hex)。

        找零逻辑显式处理：
        - change > dust_limit → 创建找零输出
        - 0 < change <= dust_limit → 并入 fee
        - change == 0 → 无找零（sweep）
        - change < 0 → 拒绝签名
        """
        from bitcoinutils.keys import P2pkhAddress
        from bitcoinutils.keys import P2shAddress
        from bitcoinutils.keys import P2wpkhAddress
        from bitcoinutils.keys import PrivateKey
        from bitcoinutils.transactions import Transaction
        from bitcoinutils.transactions import TxInput
        from bitcoinutils.transactions import TxOutput
        from bitcoinutils.transactions import TxWitnessInput
        from bitcoin_support.utils import classify_bitcoin_address

        # 构造输入
        sequence = b"\xfd\xff\xff\xff" if replaceable else b"\xfe\xff\xff\xff"
        inputs = [
            TxInput(utxo["txid"], int(utxo["vout"]), sequence=sequence)
            for utxo in utxos
        ]

        # 构造目标输出
        addr_type = classify_bitcoin_address(to)
        if addr_type == "p2wpkh":
            target_script = P2wpkhAddress(to).to_script_pub_key()
        elif addr_type == "p2sh":
            target_script = P2shAddress(to).to_script_pub_key()
        else:
            target_script = P2pkhAddress(to).to_script_pub_key()

        outputs = [TxOutput(amount_satoshi, target_script)]

        # 找零计算
        total_input = sum(btc_to_satoshi(utxo["amount"]) for utxo in utxos)
        change = total_input - amount_satoshi - fee_satoshi
        if change < 0:
            raise ValueError("UTXO 余额不足以覆盖转账金额与矿工费")
        if change > _BTC_DUST_LIMIT:
            change_script = P2wpkhAddress(source_address).to_script_pub_key()
            outputs.append(TxOutput(change, change_script))
        # 0 < change <= dust_limit: 并入 fee，不创建找零输出

        # 构建交易
        tx = Transaction(inputs, outputs, has_segwit=True)

        # 签名所有输入（P2WPKH）
        secret_exponent = int.from_bytes(
            bytes.fromhex(privkey_hex), byteorder="big"
        )
        key = PrivateKey(secret_exponent=secret_exponent)
        pub = key.get_public_key()
        script_code = pub.get_address().to_script_pub_key()

        for i, utxo in enumerate(utxos):
            utxo_amount = btc_to_satoshi(utxo["amount"])
            sig = key.sign_segwit_input(tx, i, script_code, utxo_amount)
            tx.witnesses.append(TxWitnessInput([sig, pub.to_hex()]))

        return tx.get_txid(), tx.serialize()

    def post(self, request):
        self._assert_authenticated(request)
        serializer = SignBitcoinSerializer(data=request.data)
        if not serializer.is_valid():
            raise SignerAPIError(ErrorCode.PARAMETER_ERROR, str(serializer.errors))

        data = serializer.validated_data
        # 签名操作使用行锁，保证冻结立即互斥。
        wallet = self._load_wallet(data["wallet_id"], for_signing=True)
        self._assert_wallet_can_sign(wallet=wallet)
        # 一次派生同时取地址和私钥，避免重复解密助记词。
        expected_address, privkey_hex = wallet.derive_key_pair(
            chain_type=ChainType.BITCOIN,
            bip44_account=data["bip44_account"],
            address_index=data["address_index"],
        )
        if expected_address != data["source_address"]:
            raise SignerAPIError(
                ErrorCode.ACCESS_DENY,
                "source_address 与派生路径不匹配",
            )
        if not self._is_internal_destination(
            chain_type=data["chain_type"],
            address=data["to"],
        ):
            self._assert_wallet_sign_rate_limit(wallet=wallet, endpoint=request.path)

        try:
            txid, signed_payload = self._build_and_sign_segwit_tx(
                privkey_hex=privkey_hex,
                source_address=data["source_address"],
                to=data["to"],
                amount_satoshi=data["amount_satoshi"],
                fee_satoshi=data["fee_satoshi"],
                replaceable=data["replaceable"],
                utxos=data["utxos"],
            )
        except Exception:
            # 截断异常链，防止 traceback frame 中的私钥泄露到日志系统。
            raise SignerAPIError(
                ErrorCode.PARAMETER_ERROR,
                "Bitcoin 交易签名失败",
            ) from None

        self._record_audit(
            request=request,
            status_value=SignerRequestAudit.Status.SUCCEEDED,
        )
        return Response(
            {
                "txid": txid,
                "signed_payload": signed_payload,
            },
            status=status.HTTP_200_OK,
        )
```

同时从文件顶部移除不再需要的导入：
- `from importlib import import_module`（已不再被任何地方使用）
- `from bitcoin_support.utils import privkey_bytes_to_wif`（不再需要，WIF 转换在 `_build_and_sign_segwit_tx` 内用 `PrivateKey(secret_exponent=...)` 替代）
- `from bitcoin_support.utils import compute_txid`（不再需要，txid 在 `_build_and_sign_segwit_tx` 内通过 `tx.get_txid()` 获得）

保留的导入：
- `from bitcoin_support.utils import btc_to_satoshi`（仍在 serializer 中使用）
- `from bitcoin_support.utils import is_valid_bitcoin_address`（仍在 serializer 中使用）

- [ ] **Step 2: Commit**

```bash
git add signer/wallets/views.py
git commit -m "feat(signer): rewrite SignBitcoinView with bitcoin-utils transaction construction"
```

---

## Task 6: signer 测试更新

**Files:**
- Modify: `signer/wallets/tests.py`

- [ ] **Step 1: 更新 Bitcoin 签名测试**

将 `test_bitcoin_sign_endpoint_passes_replaceable_flag_to_bit_library` 测试（约第 408-463 行）替换为：

```python
    @patch("wallets.views.SignBitcoinView._build_and_sign_segwit_tx")
    def test_bitcoin_sign_endpoint_passes_replaceable_flag(
        self,
        build_tx_mock,
    ):
        build_tx_mock.return_value = ("ab" * 32, "00" * 100)

        wallet = self._create_wallet(wallet_id=3004)
        recipient = wallet.derive_address(
            chain_type=ChainType.BITCOIN,
            bip44_account=0,
            address_index=1,
        )
        body = self._bitcoin_sign_body(
            wallet=wallet,
            recipient=recipient,
            replaceable=True,
        )

        response = self.client.post(
            "/v1/sign/bitcoin",
            data=body,
            content_type="application/json",
            **self._signed_headers(body=body, path="/v1/sign/bitcoin"),
        )

        self.assertEqual(response.status_code, 200)
        call_kwargs = build_tx_mock.call_args.kwargs
        self.assertTrue(call_kwargs["replaceable"])
        self.assertEqual(call_kwargs["to"], recipient)
```

- [ ] **Step 2: 运行 signer 测试**

Run: `.venv/bin/python -m pytest signer/ -x -q --no-header 2>&1 | tail -5`

Expected: 全部 PASSED

- [ ] **Step 3: Commit**

```bash
git add signer/wallets/tests.py
git commit -m "test(signer): update Bitcoin signing test for bitcoin-utils"
```

---

## Task 7: 主应用 utils — compute_txid 和 privkey_bytes_to_wif

**Files:**
- Modify: `xcash/bitcoin/utils.py`

- [ ] **Step 1: 替换 compute_txid**

将 `xcash/bitcoin/utils.py` 中的 `compute_txid` 函数（约第 168-176 行）替换为：

```python
def compute_txid(signed_payload_hex: str) -> str:
    """从已签名原始交易 hex 计算 txid。

    SegWit 交易的 txid 基于去除 witness 数据后的序列化。
    """
    from bitcoinutils.transactions import Transaction

    return Transaction.from_raw(signed_payload_hex).get_txid()
```

- [ ] **Step 2: 替换 privkey_bytes_to_wif**

将 `privkey_bytes_to_wif` 函数（约第 160-165 行）替换为：

```python
def privkey_bytes_to_wif(privkey_bytes: bytes) -> str:
    """将原始 32 字节 secp256k1 私钥转换为当前网络 WIF（压缩格式）。

    依赖 bitcoinutils.setup.setup() 已在 AppConfig.ready() 中按当前网络初始化。
    """
    from bitcoinutils.keys import PrivateKey

    secret_exponent = int.from_bytes(privkey_bytes, byteorder="big")
    return PrivateKey(secret_exponent=secret_exponent).to_wif()
```

移除不再需要的导入：`from bip_utils import Base58Encoder`。

注意：`hashlib` 仍被 `extract_input_sequences_from_raw_transaction` 等函数间接需要（检查后发现不需要——那些函数不用 hashlib），但保险起见检查文件内其他使用。实际上 `hashlib` 在本文件中只被旧 `compute_txid` 和旧 `privkey_bytes_to_wif` 使用，可以移除。

- [ ] **Step 3: Commit**

```bash
git add xcash/bitcoin/utils.py
git commit -m "feat(bitcoin): switch compute_txid and privkey_bytes_to_wif to bitcoin-utils"
```

---

## Task 8: test_signer 重写

**Files:**
- Modify: `xcash/chains/test_signer.py`

- [ ] **Step 1: 重写 sign_bitcoin_transaction**

移除 `_load_bit_dependencies` 方法，重写 `sign_bitcoin_transaction` 方法。

移除导入：
```python
from importlib import import_module
```

移除方法：
```python
@staticmethod
def _load_bit_dependencies():
    ...
```

将 `sign_bitcoin_transaction` 方法替换为：

```python
    def sign_bitcoin_transaction(
        self,
        *,
        address,
        chain,
        source_address: str,
        to: str,
        amount_satoshi: int,
        fee_satoshi: int,
        replaceable: bool,
        utxos: list[dict],
    ) -> BitcoinSignedPayload:
        from bitcoinutils.keys import P2pkhAddress
        from bitcoinutils.keys import P2shAddress
        from bitcoinutils.keys import P2wpkhAddress
        from bitcoinutils.keys import PrivateKey
        from bitcoinutils.transactions import Transaction
        from bitcoinutils.transactions import TxInput
        from bitcoinutils.transactions import TxOutput
        from bitcoinutils.transactions import TxWitnessInput
        from common.utils.bitcoin import classify_bitcoin_address

        # 构造输入
        sequence = b"\xfd\xff\xff\xff" if replaceable else b"\xfe\xff\xff\xff"
        inputs = [
            TxInput(utxo["txid"], int(utxo["vout"]), sequence=sequence)
            for utxo in utxos
        ]

        # 构造目标输出
        addr_type = classify_bitcoin_address(to)
        if addr_type == "p2wpkh":
            target_script = P2wpkhAddress(to).to_script_pub_key()
        elif addr_type == "p2sh":
            target_script = P2shAddress(to).to_script_pub_key()
        else:
            target_script = P2pkhAddress(to).to_script_pub_key()
        outputs = [TxOutput(amount_satoshi, target_script)]

        # 找零
        total_input = sum(btc_to_satoshi(utxo["amount"]) for utxo in utxos)
        change = total_input - amount_satoshi - fee_satoshi
        if change > 294:  # P2WPKH dust limit
            change_script = P2wpkhAddress(source_address).to_script_pub_key()
            outputs.append(TxOutput(change, change_script))

        # 构建交易
        tx = Transaction(inputs, outputs, has_segwit=True)

        # 签名
        privkey_bytes = bytes.fromhex(
            self._private_key_hex(
                wallet_id=address.wallet_id,
                chain_type=address.chain_type,
                bip44_account=address.bip44_account,
                address_index=address.address_index,
            )
        )
        secret_exponent = int.from_bytes(privkey_bytes, byteorder="big")
        key = PrivateKey(secret_exponent=secret_exponent)
        pub = key.get_public_key()
        script_code = pub.get_address().to_script_pub_key()

        for i, utxo in enumerate(utxos):
            utxo_amount = btc_to_satoshi(utxo["amount"])
            sig = key.sign_segwit_input(tx, i, script_code, utxo_amount)
            tx.witnesses.append(TxWitnessInput([sig, pub.to_hex()]))

        return BitcoinSignedPayload(
            txid=tx.get_txid(),
            signed_payload=tx.serialize(),
        )
```

同时移除不再使用的导入：
- `from bitcoin.utils import compute_txid`
- `from bitcoin.utils import privkey_bytes_to_wif`

保留的导入：
- `from bitcoin.utils import btc_to_satoshi`（仍在使用）

- [ ] **Step 2: Commit**

```bash
git add xcash/chains/test_signer.py
git commit -m "feat(test_signer): rewrite Bitcoin signing with bitcoin-utils"
```

---

## Task 9: 验证与清理

- [ ] **Step 1: 运行 signer 测试**

Run: `.venv/bin/python -m pytest signer/ -x -q --no-header 2>&1 | tail -5`

Expected: 全部 PASSED

- [ ] **Step 2: 确认无残留 bit 引用**

Run: `grep -rn "from bit\b\|import bit\b\|from bit\.\|\"bit\"\|'bit'" xcash/ signer/ --include="*.py" | grep -v __pycache__ | grep -v ".pyc" | grep -v bitcoin`

Expected: 无输出（所有 `bit` 引用已清除）

- [ ] **Step 3: 端到端验证**

```bash
.venv/bin/python -c "
from bitcoinutils.setup import setup
from bitcoinutils.keys import PrivateKey, P2wpkhAddress, P2pkhAddress
from bitcoinutils.transactions import Transaction, TxInput, TxOutput, TxWitnessInput

setup('mainnet')
k = PrivateKey.from_wif('L1uyy5qTuGrVXrmrsvHWHgVzW9kKdrp27wBC7Vs6nZDTF2BRUVwy')
pub = k.get_public_key()
addr = pub.get_segwit_address()

txin = TxInput('ab'*32, 0)
out = TxOutput(50000, P2pkhAddress('1BoatSLRHtKNngkdXEeobR76b53LETtpyT').to_script_pub_key())
change_out = TxOutput(49000, addr.to_script_pub_key())
tx = Transaction([txin], [out, change_out], has_segwit=True)

sig = k.sign_segwit_input(tx, 0, pub.get_address().to_script_pub_key(), 100000)
tx.witnesses.append(TxWitnessInput([sig, pub.to_hex()]))

raw = bytes.fromhex(tx.serialize())
assert raw[4] == 0x00 and raw[5] == 0x01, 'Must be SegWit'
assert len(tx.get_txid()) == 64
print('E2E OK: bitcoin-utils signing pipeline verified')
"
```

Expected: `E2E OK: bitcoin-utils signing pipeline verified`

- [ ] **Step 4: 卸载 bit 库（如果仍安装）**

Run: `/Users/void/.local/bin/uv pip uninstall bit 2>/dev/null; echo "done"`

- [ ] **Step 5: Commit（如有清理改动）**

```bash
git add -A
git commit -m "chore: remove remaining bit library references"
```
