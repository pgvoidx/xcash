// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {Test} from "forge-std/Test.sol";
import {ERC20CollectorReference} from "../reference/ERC20CollectorReference.sol";
import {NativeCollectorReference} from "../reference/NativeCollectorReference.sol";
import {MockERC20} from "./helpers/MockERC20.sol";
import {MockUsdtLike} from "./helpers/MockUsdtLike.sol";
import {YulLoader} from "./helpers/YulLoader.sol";

contract EquivalenceTest is Test {
    address payable internal vault = payable(address(0xBEEF));

    function test_native_yul_matches_reference_transfer_behavior() public {
        address refAddr = computeCreateAddress(address(this), vm.getNonce(address(this)));
        vm.deal(refAddr, 1 ether);
        new NativeCollectorReference(vault);
        uint256 vaultAfterRef = vault.balance;

        vm.deal(vault, 0);

        bytes memory initCode = YulLoader.loadNativeInitCode(vault);
        bytes32 salt = bytes32(uint256(0xA11CE));
        address yulAddr = computeCreate2Address(salt, keccak256(initCode), address(this));
        vm.deal(yulAddr, 1 ether);

        address deployed = _deployCreate2(salt, initCode);

        assertEq(deployed, yulAddr);
        assertEq(vaultAfterRef, 1 ether, "reference vault balance");
        assertEq(vault.balance, 1 ether, "yul vault balance");
        assertEq(yulAddr.code.length, 0, "yul code should be cleared");
    }

    function test_erc20_yul_matches_reference_for_standard_token() public {
        MockERC20 refToken = new MockERC20();
        address refAddr = computeCreateAddress(address(this), vm.getNonce(address(this)));
        refToken.mint(refAddr, 1000e18);
        new ERC20CollectorReference(vault, address(refToken));
        uint256 vaultAfterRef = refToken.balanceOf(vault);

        MockERC20 yulToken = new MockERC20();
        bytes memory initCode = YulLoader.loadERC20InitCode(vault, address(yulToken));
        bytes32 salt = bytes32(uint256(0xB0B));
        address yulAddr = computeCreate2Address(salt, keccak256(initCode), address(this));
        yulToken.mint(yulAddr, 1000e18);

        address deployed = _deployCreate2(salt, initCode);

        assertEq(deployed, yulAddr);
        assertEq(vaultAfterRef, 1000e18);
        assertEq(yulToken.balanceOf(vault), 1000e18);
        assertEq(yulAddr.code.length, 0);
    }

    function test_erc20_yul_supports_usdt_like_token() public {
        MockUsdtLike token = new MockUsdtLike();
        bytes memory initCode = YulLoader.loadERC20InitCode(vault, address(token));
        bytes32 salt = bytes32(uint256(0xC0DE));
        address yulAddr = computeCreate2Address(salt, keccak256(initCode), address(this));
        token.mint(yulAddr, 500e6);

        address deployed = _deployCreate2(salt, initCode);

        assertEq(deployed, yulAddr);
        assertEq(token.balanceOf(vault), 500e6);
        assertEq(yulAddr.code.length, 0);
    }

    function _deployCreate2(bytes32 salt, bytes memory initCode) private returns (address deployed) {
        assembly {
            deployed := create2(0, add(initCode, 0x20), mload(initCode), salt)
        }
        require(deployed != address(0), "create2 failed");
    }
}
