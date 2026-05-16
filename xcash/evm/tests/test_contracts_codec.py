"""evm.contracts_codec 的 sentinel 校验、init_code 拼装与地址预测。"""

import json
from pathlib import Path

import pytest
from eth_utils import is_checksum_address

import evm.contracts_codec as codec

FIXTURES_PATH = Path(__file__).parent / "fixtures" / "collector_init_code_fixtures.json"


@pytest.fixture(scope="module")
def fixtures():
    return json.loads(FIXTURES_PATH.read_text())


def _hex_to_bytes(value: str) -> bytes:
    return bytes.fromhex(value[2:] if value.startswith("0x") else value)


def test_module_import_validates_sentinels():
    assert codec.VAULT_SENTINEL.hex() == "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    assert codec.TOKEN_SENTINEL.hex() == "cafebabecafebabecafebabecafebabecafebabe"


def test_invalid_sentinel_count_raises_import_error():
    with pytest.raises(ImportError):
        codec._check_sentinel(b"", codec.VAULT_SENTINEL, 1, "NativeCollector")


def test_native_and_erc20_template_sentinel_distribution():
    assert codec._NATIVE_TEMPLATE.count(codec.VAULT_SENTINEL) == 1
    assert codec._NATIVE_TEMPLATE.count(codec.TOKEN_SENTINEL) == 0
    assert codec._ERC20_TEMPLATE.count(codec.VAULT_SENTINEL) == 1
    assert codec._ERC20_TEMPLATE.count(codec.TOKEN_SENTINEL) == 1


def test_build_native_init_code_matches_foundry_fixture(fixtures):
    case = fixtures["case_native"]
    assert codec.build_collector_init_code(to=case["vault"]) == _hex_to_bytes(
        case["init_code"]
    )


def test_build_erc20_init_code_matches_foundry_fixture(fixtures):
    case = fixtures["case_erc20"]
    got = codec.build_collector_init_code(
        to=case["vault"],
        token=case["token"],
    )
    assert got == _hex_to_bytes(case["init_code"])


def test_build_edge_vault_init_code_matches_foundry_fixture(fixtures):
    case = fixtures["case_edge"]
    got = codec.build_collector_init_code(
        to=case["vault"],
        token=case["token"],
    )
    assert got == _hex_to_bytes(case["init_code"])


def test_none_or_zero_token_uses_native_template():
    vault = "0x1111111111111111111111111111111111111111"
    native = codec.build_collector_init_code(to=vault)
    assert (
        codec.build_collector_init_code(
            to=vault,
            token=None,
        )
        == native
    )
    assert (
        codec.build_collector_init_code(
            to=vault,
            token="0x0000000000000000000000000000000000000000",
        )
        == native
    )


def test_invalid_to_or_token_address_raises_value_error():
    with pytest.raises(ValueError, match="hex string"):
        codec.build_collector_init_code(to="not-an-address")
    with pytest.raises(ValueError, match="hex string"):
        codec.build_collector_init_code(
            to="0x1111111111111111111111111111111111111111",
            token="not-an-address",
        )


def test_patched_init_code_no_longer_contains_sentinels():
    init_code = codec.build_collector_init_code(
        to="0x1111111111111111111111111111111111111111",
        token="0x2222222222222222222222222222222222222222",
    )
    assert codec.VAULT_SENTINEL not in init_code
    assert codec.TOKEN_SENTINEL not in init_code


def test_init_code_hash_is_32_bytes_and_changes_with_vault():
    h1 = codec.collector_init_code_hash(to="0x1111111111111111111111111111111111111111")
    h2 = codec.collector_init_code_hash(to="0x2222222222222222222222222222222222222222")
    assert isinstance(h1, bytes)
    assert len(h1) == 32
    assert h1 != h2


def test_predict_native_address_matches_foundry_fixture(fixtures):
    case = fixtures["case_native"]
    got = codec.predict_collector_address(
        factory=fixtures["factory"],
        salt=_hex_to_bytes(fixtures["salt"]),
        to=case["vault"],
    )
    assert got.lower() == case["predicted"].lower()


def test_predict_erc20_address_matches_foundry_fixture(fixtures):
    case = fixtures["case_erc20"]
    got = codec.predict_collector_address(
        factory=fixtures["factory"],
        salt=_hex_to_bytes(fixtures["salt"]),
        to=case["vault"],
        token=case["token"],
    )
    assert got.lower() == case["predicted"].lower()


def test_predict_edge_address_matches_foundry_fixture(fixtures):
    case = fixtures["case_edge"]
    got = codec.predict_collector_address(
        factory=fixtures["factory"],
        salt=_hex_to_bytes(fixtures["salt"]),
        to=case["vault"],
        token=case["token"],
    )
    assert got.lower() == case["predicted"].lower()


def test_predict_returns_checksum_address():
    addr = codec.predict_collector_address(
        factory="0xF1A0F1A0F1A0F1A0F1A0F1A0F1A0F1A0F1A0F1A0",
        salt=b"\x00" * 32,
        to="0x1111111111111111111111111111111111111111",
    )
    assert is_checksum_address(addr)


def test_predict_requires_32_byte_salt():
    with pytest.raises(ValueError, match="salt must be 32 bytes"):
        codec.predict_collector_address(
            factory="0xF1A0F1A0F1A0F1A0F1A0F1A0F1A0F1A0F1A0F1A0",
            salt=b"\x00" * 31,
            to="0x1111111111111111111111111111111111111111",
        )
