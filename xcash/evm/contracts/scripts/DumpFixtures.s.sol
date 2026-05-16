// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {Script} from "forge-std/Script.sol";
import {YulLoader} from "../test/helpers/YulLoader.sol";

contract DumpFixtures is Script {
    function run() external {
        address factory = 0xf1a0F1A0F1A0F1A0f1a0F1a0f1a0f1a0F1A0f1A0;
        bytes32 salt = bytes32(uint256(0xC0DE));

        address vault1 = 0x1111111111111111111111111111111111111111;
        bytes memory init1 = YulLoader.loadNativeInitCode(vault1);
        address addr1 = computeCreate2Address(salt, keccak256(init1), factory);

        address vault2 = 0x2222222222222222222222222222222222222222;
        address token2 = 0x3333333333333333333333333333333333333333;
        bytes memory init2 = YulLoader.loadERC20InitCode(vault2, token2);
        address addr2 = computeCreate2Address(salt, keccak256(init2), factory);

        address vault3 = 0xFFfFfFffFFfffFFfFFfFFFFFffFFFffffFfFFFfF;
        address token3 = address(uint160(uint256(keccak256("usdt"))));
        bytes memory init3 = YulLoader.loadERC20InitCode(vault3, token3);
        address addr3 = computeCreate2Address(salt, keccak256(init3), factory);

        string memory json = string.concat(
            "{",
            '"factory":"',
            vm.toString(factory),
            '",',
            '"salt":"',
            vm.toString(salt),
            '",',
            '"case_native":{',
            '"vault":"',
            vm.toString(vault1),
            '","init_code":"',
            vm.toString(init1),
            '","predicted":"',
            vm.toString(addr1),
            '"},',
            '"case_erc20":{',
            '"vault":"',
            vm.toString(vault2),
            '","token":"',
            vm.toString(token2),
            '","init_code":"',
            vm.toString(init2),
            '","predicted":"',
            vm.toString(addr2),
            '"},',
            '"case_edge":{',
            '"vault":"',
            vm.toString(vault3),
            '","token":"',
            vm.toString(token3),
            '","init_code":"',
            vm.toString(init3),
            '","predicted":"',
            vm.toString(addr3),
            '"}',
            "}"
        );

        vm.writeFile("../tests/fixtures/collector_init_code_fixtures.json", json);
    }
}
