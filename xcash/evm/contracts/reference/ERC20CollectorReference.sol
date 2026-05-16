// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

/// @title ERC20CollectorReference
/// @notice ERC20 收款合约的 Solidity 参考实现，仅供阅读与等价测试基准，不部署上链。
/// @dev 实际部署版本见 src/ERC20Collector.yul。
contract ERC20CollectorReference {
    constructor(address vault, address token) payable {
        (bool ok, bytes memory data) =
            token.staticcall(abi.encodeWithSelector(0x70a08231, address(this)));
        require(ok && data.length >= 32, "balanceOf failed");

        uint256 balance = abi.decode(data, (uint256));
        if (balance > 0) {
            (ok, data) = token.call(abi.encodeWithSelector(0xa9059cbb, vault, balance));
            require(ok, "transfer failed");
            if (data.length > 0) {
                require(data.length >= 32, "transfer malformed");
                require(abi.decode(data, (bool)), "transfer returned false");
            }
        }

        selfdestruct(payable(vault));
    }
}
