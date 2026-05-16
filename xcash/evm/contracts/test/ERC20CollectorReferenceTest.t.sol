// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {Test} from "forge-std/Test.sol";
import {ERC20CollectorReference} from "../reference/ERC20CollectorReference.sol";
import {MockERC20} from "./helpers/MockERC20.sol";
import {MockFalseReturnERC20} from "./helpers/MockFalseReturnERC20.sol";
import {MockMalformedReturnERC20} from "./helpers/MockMalformedReturnERC20.sol";
import {MockUsdtLike} from "./helpers/MockUsdtLike.sol";

contract ERC20CollectorReferenceTest is Test {
    address internal vault = address(0xBEEF);

    function test_erc20_reference_transfers_standard_token_to_vault() public {
        MockERC20 token = new MockERC20();
        address predicted = computeCreateAddress(address(this), vm.getNonce(address(this)));
        token.mint(predicted, 1000e18);

        new ERC20CollectorReference(vault, address(token));

        assertEq(token.balanceOf(vault), 1000e18);
        assertEq(token.balanceOf(predicted), 0);
        assertEq(predicted.code.length, 0);
    }

    function test_erc20_reference_supports_usdt_like_token() public {
        MockUsdtLike token = new MockUsdtLike();
        address predicted = computeCreateAddress(address(this), vm.getNonce(address(this)));
        token.mint(predicted, 500e6);

        new ERC20CollectorReference(vault, address(token));

        assertEq(token.balanceOf(vault), 500e6);
        assertEq(token.balanceOf(predicted), 0);
    }

    function test_erc20_reference_reverts_when_transfer_returns_false() public {
        MockFalseReturnERC20 token = new MockFalseReturnERC20();
        address predicted = computeCreateAddress(address(this), vm.getNonce(address(this)));
        token.mint(predicted, 1);

        vm.expectRevert("transfer returned false");
        new ERC20CollectorReference(vault, address(token));
    }

    function test_erc20_reference_reverts_when_transfer_returns_malformed_bool() public {
        MockMalformedReturnERC20 token = new MockMalformedReturnERC20();
        address predicted = computeCreateAddress(address(this), vm.getNonce(address(this)));
        token.mint(predicted, 1);

        vm.expectRevert();
        new ERC20CollectorReference(vault, address(token));
    }

    function test_erc20_reference_allows_zero_balance() public {
        MockFalseReturnERC20 token = new MockFalseReturnERC20();
        new ERC20CollectorReference(vault, address(token));
        assertEq(token.balanceOf(vault), 0);
    }
}
