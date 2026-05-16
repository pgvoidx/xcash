// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {Test} from "forge-std/Test.sol";
import {PaymentCollectorFactory} from "../src/PaymentCollectorFactory.sol";
import {MockERC20} from "./helpers/MockERC20.sol";
import {MockFalseReturnERC20} from "./helpers/MockFalseReturnERC20.sol";
import {MockMalformedReturnERC20} from "./helpers/MockMalformedReturnERC20.sol";
import {MockUsdtLike} from "./helpers/MockUsdtLike.sol";
import {YulLoader} from "./helpers/YulLoader.sol";

contract FactoryTest is Test {
    PaymentCollectorFactory internal factory;
    address payable internal vault = payable(address(0xBEEF));

    function setUp() public {
        factory = new PaymentCollectorFactory();
    }

    function test_deploy_native_collects_all_eth_to_vault() public {
        bytes32 salt = keccak256("order-001");
        bytes memory initCode = YulLoader.loadNativeInitCode(vault);
        address predicted = computeCreate2Address(salt, keccak256(initCode), address(factory));
        vm.deal(predicted, 2 ether);

        vm.expectEmit(true, true, false, false);
        emit PaymentCollectorFactory.Deployed(predicted, salt);

        address deployed = factory.deploy(salt, initCode);

        assertEq(deployed, predicted);
        assertEq(vault.balance, 2 ether);
        assertEq(predicted.code.length, 0);
    }

    function test_deploy_erc20_collects_standard_token() public {
        MockERC20 token = new MockERC20();
        bytes32 salt = keccak256("order-002");
        bytes memory initCode = YulLoader.loadERC20InitCode(vault, address(token));
        address predicted = computeCreate2Address(salt, keccak256(initCode), address(factory));
        token.mint(predicted, 1000e18);

        address deployed = factory.deploy(salt, initCode);

        assertEq(deployed, predicted);
        assertEq(token.balanceOf(vault), 1000e18);
        assertEq(predicted.code.length, 0);
    }

    function test_deploy_erc20_collects_usdt_like_token() public {
        MockUsdtLike token = new MockUsdtLike();
        bytes32 salt = keccak256("order-usdt");
        bytes memory initCode = YulLoader.loadERC20InitCode(vault, address(token));
        address predicted = computeCreate2Address(salt, keccak256(initCode), address(factory));
        token.mint(predicted, 500e6);

        address deployed = factory.deploy(salt, initCode);

        assertEq(deployed, predicted);
        assertEq(token.balanceOf(vault), 500e6);
        assertEq(predicted.code.length, 0);
    }

    function test_deploy_erc20_reverts_when_token_returns_false() public {
        MockFalseReturnERC20 token = new MockFalseReturnERC20();
        bytes32 salt = keccak256("order-false");
        bytes memory initCode = YulLoader.loadERC20InitCode(vault, address(token));
        address predicted = computeCreate2Address(salt, keccak256(initCode), address(factory));
        token.mint(predicted, 1);

        vm.expectRevert(PaymentCollectorFactory.DeployFailed.selector);
        factory.deploy(salt, initCode);

        assertEq(token.balanceOf(vault), 0);
    }

    function test_deploy_erc20_reverts_when_token_returns_malformed_bool() public {
        MockMalformedReturnERC20 token = new MockMalformedReturnERC20();
        bytes32 salt = keccak256("order-malformed");
        bytes memory initCode = YulLoader.loadERC20InitCode(vault, address(token));
        address predicted = computeCreate2Address(salt, keccak256(initCode), address(factory));
        token.mint(predicted, 1);

        vm.expectRevert(PaymentCollectorFactory.DeployFailed.selector);
        factory.deploy(salt, initCode);
    }

    function test_duplicate_salt_and_same_init_code_reverts() public {
        bytes32 salt = keccak256("order-003");
        bytes memory initCode = YulLoader.loadNativeInitCode(vault);
        address predicted = computeCreate2Address(salt, keccak256(initCode), address(factory));
        vm.deal(predicted, 1 ether);
        factory.deploy(salt, initCode);

        vm.expectRevert(PaymentCollectorFactory.DeployFailed.selector);
        factory.deploy(salt, initCode);
    }

    function test_predicted_address_formula_matches_deploy() public {
        bytes32 salt = bytes32(uint256(0x1234));
        bytes memory initCode = YulLoader.loadNativeInitCode(vault);
        bytes32 hash =
            keccak256(abi.encodePacked(bytes1(0xff), address(factory), salt, keccak256(initCode)));
        address predicted = address(uint160(uint256(hash)));
        vm.deal(predicted, 0.5 ether);

        address deployed = factory.deploy(salt, initCode);

        assertEq(deployed, predicted);
    }
}
