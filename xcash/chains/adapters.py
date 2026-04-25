from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
from enum import StrEnum

from chains.models import Chain
from chains.types import AddressStr
from currencies.models import Crypto


class TxCheckStatus(StrEnum):
    """链上交易结果查询的内存枚举。

    这里只描述“当前查到的交易结果”，不落库，也不参与业务状态机建模。
    """

    CONFIRMING = "confirming"
    CONFIRMED = "confirmed"
    DROPPED = "dropped"
    FAILED = "failed"


@dataclass(frozen=True, eq=False)
class TxCheckResult:
    """链上交易状态及 receipt 位置元信息。

    兼容旧代码中直接把 tx_result 返回值与 TxCheckStatus 比较的写法，同时让
    确认任务能在 reorg 后发现 blockNumber / blockHash 变化并刷新确认起点。
    """

    status: TxCheckStatus
    block_number: int | None = None
    block_hash: str | None = None

    def __eq__(self, other: object) -> bool:
        if isinstance(other, TxCheckStatus):
            return self.status == other
        if isinstance(other, str):
            return self.status == other
        if isinstance(other, TxCheckResult):
            return (
                self.status == other.status
                and self.block_number == other.block_number
                and self.block_hash == other.block_hash
            )
        return NotImplemented

    def __hash__(self) -> int:
        # 与 TxCheckStatus 的兼容相等比较保持一致；不同 receipt 元信息出现哈希碰撞可接受。
        return hash(self.status)


class AdapterInterface(ABC):
    """链适配器接口：负责地址验证、余额查询、交易结果查询。

    交易签名与广播逻辑已从 Adapter 层移除，统一由各链专属的 XxxBroadcastTask 模型负责：
    - EVM：evm.EvmBroadcastTask.schedule_transfer()
    """

    @abstractmethod
    def validate_address(self, address: AddressStr) -> bool:
        pass

    @abstractmethod
    def is_address(self, chain: Chain, address: AddressStr) -> bool:
        pass

    @abstractmethod
    def is_contract(self, chain: Chain, address: AddressStr) -> bool:
        pass

    @abstractmethod
    def get_balance(self, address: AddressStr, chain: Chain, crypto: Crypto) -> int:
        pass

    @abstractmethod
    def tx_result(
        self, chain, tx_hash: str
    ) -> TxCheckStatus | TxCheckResult | Exception:
        pass


class AdapterFactory:
    # 各链适配器在首次请求时懒加载，避免类体级别导入产生启动时强依赖。

    @staticmethod
    def get_adapter(chain_type: str) -> AdapterInterface:
        if chain_type == "evm":
            from evm.adapter import EvmAdapter

            return EvmAdapter()
        if chain_type == "btc":
            from bitcoin.adapter import BitcoinAdapter

            return BitcoinAdapter()
        if chain_type == "tron":
            from tron.adapter import TronAdapter

            return TronAdapter()
        raise ValueError(f"Unsupported chain adapter: {chain_type}")
