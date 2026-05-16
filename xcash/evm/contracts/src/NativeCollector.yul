/// @notice Native 收款合约（实际部署版本）
///
/// init_code 行为：
/// 1. PUSH20 vault（sentinel 占位，Python 侧 patch 为真实地址）
/// 2. SELFDESTRUCT，把合约自身 ETH 余额转给 vault，并在构造同笔交易内清空代码
object "NativeCollector" {
    code {
        let vault := 0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef
        selfdestruct(vault)
    }
}
