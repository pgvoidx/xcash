// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

/// @title PaymentCollectorFactory
/// @notice Pass-through CREATE2 信道。不持有业务状态，不做业务判断。
/// @dev vault/token 已由 Python 侧写死进 initCode，工厂只负责 CREATE2 部署。
contract PaymentCollectorFactory {
    event Deployed(address indexed collector, bytes32 indexed salt);

    error DeployFailed();

    function deploy(bytes32 salt, bytes calldata initCode) external returns (address collector) {
        assembly {
            let ptr := mload(0x40)
            calldatacopy(ptr, initCode.offset, initCode.length)
            collector := create2(0, ptr, initCode.length, salt)
        }
        if (collector == address(0)) revert DeployFailed();
        emit Deployed(collector, salt);
    }
}
