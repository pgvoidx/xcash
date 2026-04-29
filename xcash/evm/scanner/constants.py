from __future__ import annotations

from web3 import Web3

# ERC20 Transfer 事件签名主题，所有日志扫描都依赖这一稳定标识。
ERC20_TRANSFER_TOPIC0 = Web3.to_hex(
    Web3.keccak(text="Transfer(address,address,uint256)")
)

# 单次日志扫描默认块跨度：首版先保守一些，后续可结合链和节点能力再调大。
DEFAULT_ERC20_SCAN_BATCH_SIZE = 100

# ERC20 日志扫描每轮额外复扫的旧块数；只用于幂等补偿轻量重组、任务中断和 RPC 抖动。
DEFAULT_ERC20_SCAN_REPLAY_BLOCKS = 2

# 原生币直转需要逐块取完整交易，单次跨度应明显小于日志扫描。
DEFAULT_NATIVE_SCAN_BATCH_SIZE = 16

# 原生币扫描每轮额外复扫的旧块数；只用于幂等补偿轻量重组、任务中断和 RPC 抖动。
DEFAULT_NATIVE_SCAN_REPLAY_BLOCKS = 2
