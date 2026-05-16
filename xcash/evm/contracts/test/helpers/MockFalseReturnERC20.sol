// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

/// @notice 模拟 transfer 返回 false 的 ERC20，用于验证 collector 不会吞掉失败转账。
contract MockFalseReturnERC20 {
    mapping(address => uint256) public balanceOf;

    function mint(address to, uint256 amount) external {
        balanceOf[to] += amount;
    }

    function transfer(address, uint256) external pure returns (bool) {
        return false;
    }
}
