# 从公共常量模块重新导出，供外部模块统一从 evm 包引入 gas 限制常量
# 避免各处直接依赖 common.consts，方便未来集中调整
from common.consts import BASE_TRANSFER_GAS  # noqa: E402, F401
from common.consts import ERC20_TRANSFER_GAS  # noqa: E402, F401
