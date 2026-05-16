// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {Vm} from "forge-std/Vm.sol";

/// @notice 从 artifacts/ 读取 hex 编译产物，并替换 sentinel 为真实地址。
library YulLoader {
    Vm internal constant VM = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));

    bytes20 internal constant VAULT_SENTINEL =
        hex"deadbeefdeadbeefdeadbeefdeadbeefdeadbeef";
    bytes20 internal constant TOKEN_SENTINEL =
        hex"cafebabecafebabecafebabecafebabecafebabe";
    function loadNativeInitCode(address vault) internal view returns (bytes memory) {
        bytes memory template = _loadHexArtifact("artifacts/NativeCollector.bin");
        return _replace20(template, VAULT_SENTINEL, bytes20(vault));
    }

    function loadERC20InitCode(address vault, address token)
        internal
        view
        returns (bytes memory)
    {
        bytes memory template = _loadHexArtifact("artifacts/ERC20Collector.bin");
        bytes memory patched = _replace20(template, VAULT_SENTINEL, bytes20(vault));
        return _replace20(patched, TOKEN_SENTINEL, bytes20(token));
    }

    function _loadHexArtifact(string memory path) private view returns (bytes memory) {
        string memory hexText = VM.readFile(path);
        require(bytes(hexText).length > 0, "artifact not built");
        return VM.parseBytes(hexText);
    }

    function _replace20(bytes memory data, bytes20 from, bytes20 to)
        private
        pure
        returns (bytes memory)
    {
        uint256 count;
        uint256 hitIndex;
        for (uint256 i = 0; i + 20 <= data.length; i++) {
            bool matched = true;
            for (uint256 j = 0; j < 20; j++) {
                if (data[i + j] != from[j]) {
                    matched = false;
                    break;
                }
            }
            if (matched) {
                count++;
                hitIndex = i;
            }
        }
        require(count == 1, "sentinel must occur exactly once");
        for (uint256 j = 0; j < 20; j++) {
            data[hitIndex + j] = to[j];
        }
        return data;
    }

}
