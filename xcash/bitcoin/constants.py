# Bitcoin 系统常量

# Bitcoin 原生精度：1 BTC = 10^8 satoshi
BTC_DECIMALS = 8
SATOSHI_PER_BTC = 10**BTC_DECIMALS

# 默认目标确认块数（用于 estimatesmartfee）：6 块约 60 分钟
BTC_FEE_TARGET_BLOCKS = 6

# 默认最低矿工费（satoshi/byte），当节点 estimatesmartfee 失败时使用
BTC_DEFAULT_FEE_RATE_SAT_PER_BYTE = 10

# Legacy P2PKH 交易体积估算参数
BTC_P2PKH_TX_OVERHEAD_VBYTES = 10
BTC_P2PKH_INPUT_VBYTES = 148
BTC_P2PKH_OUTPUT_VBYTES = 34
BTC_P2PKH_TX_BYTES = (
    BTC_P2PKH_TX_OVERHEAD_VBYTES + BTC_P2PKH_INPUT_VBYTES + BTC_P2PKH_OUTPUT_VBYTES * 2
)

# Bitcoin 主网 WIF 前缀（mainnet compressed private key）
BTC_WIF_PREFIX = b"\x80"
