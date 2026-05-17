"""EVM collector 合约 init_code 编解码模块。"""

from __future__ import annotations

from pathlib import Path

from eth_utils import keccak
from eth_utils import to_canonical_address
from eth_utils import to_checksum_address

_ARTIFACTS_DIR = Path(__file__).parent / "contracts" / "artifacts"

VAULT_SENTINEL: bytes = bytes.fromhex(
    "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
)
TOKEN_SENTINEL: bytes = bytes.fromhex(
    "cafebabecafebabecafebabecafebabecafebabe"
)
ZERO_ADDRESS: bytes = b"\x00" * 20


def _load_template(name: str) -> bytes:
    path = _ARTIFACTS_DIR / name
    if not path.exists():
        raise ImportError(
            f"Yul artifact {path} not found; run `make build-yul` in "
            "xcash/evm/contracts/"
        )

    hex_text = path.read_text().strip()
    if hex_text.startswith("0x"):
        hex_text = hex_text[2:]
    try:
        return bytes.fromhex(hex_text)
    except ValueError as exc:
        raise ImportError(f"Yul artifact {path} is not valid hex") from exc


def _check_sentinel(
    template: bytes,
    sentinel: bytes,
    expected: int,
    label: str,
) -> None:
    count = template.count(sentinel)
    if count != expected:
        raise ImportError(
            f"{label}: sentinel {sentinel.hex()} expected {expected} "
            f"occurrence(s), found {count}"
        )


_NATIVE_TEMPLATE: bytes = _load_template("NativeCollector.bin")
_ERC20_TEMPLATE: bytes = _load_template("ERC20Collector.bin")

_check_sentinel(_NATIVE_TEMPLATE, VAULT_SENTINEL, 1, "NativeCollector")
_check_sentinel(_NATIVE_TEMPLATE, TOKEN_SENTINEL, 0, "NativeCollector")
_check_sentinel(_ERC20_TEMPLATE, VAULT_SENTINEL, 1, "ERC20Collector")
_check_sentinel(_ERC20_TEMPLATE, TOKEN_SENTINEL, 1, "ERC20Collector")


def build_collector_init_code(
    to: str,
    token: str | None = None,
) -> bytes:
    """构造 collector init_code，to/token 写死为字节码立即数。"""
    to_bytes = to_canonical_address(to)
    if to_bytes == ZERO_ADDRESS:
        raise ValueError("vault address must not be zero")
    if token is None:
        return _NATIVE_TEMPLATE.replace(VAULT_SENTINEL, to_bytes)

    token_bytes = to_canonical_address(token)
    if token_bytes == ZERO_ADDRESS:
        return _NATIVE_TEMPLATE.replace(VAULT_SENTINEL, to_bytes)
    if token_bytes == to_bytes:
        raise ValueError("token address must differ from vault")

    patched = _ERC20_TEMPLATE.replace(VAULT_SENTINEL, to_bytes)
    return patched.replace(TOKEN_SENTINEL, token_bytes)


def collector_init_code_hash(
    to: str,
    token: str | None = None,
) -> bytes:
    """返回 collector init_code 的 keccak256，长度固定 32 字节。"""
    return keccak(build_collector_init_code(to, token))


def predict_collector_address(
    *,
    factory: str,
    salt: bytes,
    to: str,
    token: str | None = None,
) -> str:
    """按 EIP-1014 离线预测 CREATE2 部署地址，返回 EIP-55 checksum。"""
    if len(salt) != 32:
        raise ValueError(f"salt must be 32 bytes, got {len(salt)}")

    factory_bytes = to_canonical_address(factory)
    init_hash = collector_init_code_hash(to, token)
    digest = keccak(b"\xff" + factory_bytes + bytes(salt) + init_hash)
    return to_checksum_address(digest[-20:])
