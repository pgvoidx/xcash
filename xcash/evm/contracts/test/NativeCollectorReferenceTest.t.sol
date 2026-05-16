// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {Test} from "forge-std/Test.sol";
import {NativeCollectorReference} from "../reference/NativeCollectorReference.sol";

contract NativeCollectorReferenceTest is Test {
    address payable internal vault = payable(address(0xBEEF));

    function test_native_reference_transfers_all_eth_to_vault() public {
        address predicted = computeCreateAddress(address(this), vm.getNonce(address(this)));
        vm.deal(predicted, 1.5 ether);

        new NativeCollectorReference(vault);

        assertEq(vault.balance, 1.5 ether);
        assertEq(predicted.balance, 0);
        assertEq(predicted.code.length, 0);
    }

    function test_native_reference_allows_zero_balance() public {
        new NativeCollectorReference(vault);
        assertEq(vault.balance, 0);
    }
}
