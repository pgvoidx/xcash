// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

/// @notice transfer 返回非 ABI bool 的非零 word，用于验证 collector 严格拒绝畸形返回。
contract MockMalformedReturnERC20 {
    mapping(address => uint256) public balanceOf;

    function mint(address to, uint256 amount) external {
        balanceOf[to] += amount;
    }

    function transfer(address, uint256) external pure returns (uint256) {
        return 2;
    }
}
