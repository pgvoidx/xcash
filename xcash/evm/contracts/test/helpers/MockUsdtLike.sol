// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

/// @notice 模拟 USDT 的非标行为：transfer 成功但不返回 bool。
contract MockUsdtLike {
    mapping(address => uint256) public balanceOf;

    function mint(address to, uint256 amount) external {
        balanceOf[to] += amount;
    }

    function transfer(address to, uint256 amount) external {
        require(balanceOf[msg.sender] >= amount, "insufficient");
        balanceOf[msg.sender] -= amount;
        balanceOf[to] += amount;
    }
}
