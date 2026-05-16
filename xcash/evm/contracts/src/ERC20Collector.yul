/// @notice ERC20 收款合约（实际部署版本）
///
/// init_code 行为：
/// 1. balanceOf(this) 读取合约 ERC20 余额
/// 2. balance > 0 时 transfer(vault, balance)，兼容 USDT 不返回值
/// 3. selfdestruct(vault)，清空 runtime code，并带回扫意外残留 ETH
object "ERC20Collector" {
    code {
        // sentinel 只能在模板里各出现一次；先写入内存，后续统一 mload 使用。
        let vaultSlot := add(0x80, callvalue())
        let tokenSlot := add(0xa0, callvalue())
        mstore(vaultSlot, 0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef)
        mstore(tokenSlot, 0xcafebabecafebabecafebabecafebabecafebabe)

        // balanceOf(address(this))
        mstore(0x00, 0x70a0823100000000000000000000000000000000000000000000000000000000)
        mstore(0x04, address())
        let ok := staticcall(gas(), mload(tokenSlot), 0x00, 0x24, 0x00, 0x20)
        if iszero(ok) { revert(0, 0) }
        if lt(returndatasize(), 0x20) { revert(0, 0) }

        let bal := mload(0x00)
        if gt(bal, 0) {
            // transfer(vault, balance)
            mstore(0x00, 0xa9059cbb00000000000000000000000000000000000000000000000000000000)
            mstore(0x04, mload(vaultSlot))
            mstore(0x24, bal)
            ok := call(gas(), mload(tokenSlot), 0, 0x00, 0x44, 0x00, 0x20)
            if iszero(ok) { revert(0, 0) }

            let size := returndatasize()
            if gt(size, 0) {
                if lt(size, 0x20) { revert(0, 0) }
                if iszero(eq(mload(0x00), 1)) { revert(0, 0) }
            }
        }

        selfdestruct(mload(vaultSlot))
    }
}
