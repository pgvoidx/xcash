from types import SimpleNamespace
from unittest.mock import Mock

from django.test import TestCase
from web3 import Web3

from chains.models import Chain
from chains.models import ChainType
from currencies.models import Crypto
from evm.scanner.rpc import EvmScannerRpcClient


class EvmScannerRpcClientTests(TestCase):
    def setUp(self):
        self.native = Crypto.objects.create(
            name="BNB RPC",
            symbol="BNBR",
            coingecko_id="binancecoin-rpc",
        )
        self.chain = Chain.objects.create(
            code="bsc-rpc-test",
            name="BSC RPC Test",
            type=ChainType.EVM,
            chain_id=56_001,
            rpc="http://bsc.rpc.local",
            native_coin=self.native,
            active=True,
        )

    def test_get_transfer_logs_splits_request_by_chain_max_block_range(self):
        # RPC 供应商限制 eth_getLogs 区块跨度时，应按链配置切片并聚合结果。
        Chain.objects.filter(pk=self.chain.pk).update(evm_log_max_block_range=10)
        self.chain.refresh_from_db()
        requested_ranges: list[tuple[int, int]] = []

        def fake_get_logs(filter_params: dict) -> list[dict]:
            requested_ranges.append(
                (filter_params["fromBlock"], filter_params["toBlock"])
            )
            return [
                {
                    "blockNumber": filter_params["fromBlock"],
                    "logIndex": 0,
                    "transactionHash": bytes.fromhex("ab" * 32),
                }
            ]

        self.chain.__dict__["w3"] = SimpleNamespace(
            eth=SimpleNamespace(get_logs=Mock(side_effect=fake_get_logs))
        )

        logs = EvmScannerRpcClient(chain=self.chain).get_transfer_logs(
            from_block=100,
            to_block=124,
            token_addresses=[
                Web3.to_checksum_address("0x00000000000000000000000000000000000000aa")
            ],
            topic0=Web3.to_hex(Web3.keccak(text="Transfer(address,address,uint256)")),
        )

        self.assertEqual(requested_ranges, [(100, 109), (110, 119), (120, 124)])
        self.assertEqual(len(logs), 3)
