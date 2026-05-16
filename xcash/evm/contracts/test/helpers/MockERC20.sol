// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

/// @notice 测试用极简 ERC20：成功返回 true，失败 revert。
contract MockERC20 {
    mapping(address => uint256) public balanceOf;

    string public name = "Mock";
    string public symbol = "MOCK";
    uint8 public decimals = 18;

    function mint(address to, uint256 amount) external {
        balanceOf[to] += amount;
    }

    function transfer(address to, uint256 amount) external returns (bool) {
        require(balanceOf[msg.sender] >= amount, "insufficient");
        balanceOf[msg.sender] -= amount;
        balanceOf[to] += amount;
        return true;
    }
}
