// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

/// @title NativeCollectorReference
/// @notice Native 收款合约的 Solidity 参考实现，仅供阅读与等价测试基准，不部署上链。
/// @dev 实际部署版本见 src/NativeCollector.yul。
contract NativeCollectorReference {
    constructor(address payable vault) payable {
        selfdestruct(vault);
    }
}
