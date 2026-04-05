from __future__ import annotations

from decimal import Decimal
from os import environ
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from bitcoin.scanner import BitcoinChainScannerService
from chains.models import Chain
from chains.models import ChainType
from chains.models import OnchainTransfer
from chains.models import Wallet
from core.tests import LocalChainIntegrationMixin
from currencies.models import Crypto
from projects.models import Project
from projects.models import RecipientAddress


class LocalBitcoinScannerIntegrationTests(LocalChainIntegrationMixin, TestCase):
    def _scan_bitcoin_chain_and_get_transfer(
        self, *, chain: Chain, tx_hash: str
    ) -> OnchainTransfer:
        """使用真实 Bitcoin 链级扫描入口抓取交易，并校验重扫幂等。"""
        summary = BitcoinChainScannerService.scan_chain(chain=chain)
        normalized_tx_hash = str(tx_hash).lower()
        transfer = OnchainTransfer.objects.filter(
            chain=chain,
            hash=normalized_tx_hash,
        ).first()
        if transfer is None:
            msg = f"Bitcoin scanner did not capture transfer: {normalized_tx_hash}"
            raise RuntimeError(msg)

        # scanner 包入口完成首扫后，二次重扫必须依赖唯一键保持幂等，不得重复建单。
        self.assertGreaterEqual(summary.created_receipts, 1)
        transfer_count = OnchainTransfer.objects.filter(
            chain=chain, hash=normalized_tx_hash
        ).count()
        second_summary = BitcoinChainScannerService.scan_chain(chain=chain)
        self.assertEqual(second_summary.created_receipts, 0)
        self.assertEqual(
            OnchainTransfer.objects.filter(
                chain=chain, hash=normalized_tx_hash
            ).count(),
            transfer_count,
        )
        return transfer

    @patch.dict(environ, {"BITCOIN_NETWORK": "regtest"}, clear=False)
    def test_local_bitcoin_chain_scanner_service_captures_project_recipient(self):
        # 真实 regtest 联调：链级 scanner service 也必须能命中项目收款地址，并保持重扫幂等。
        wallet_client = self._require_bitcoin()
        crypto = Crypto.objects.create(
            name="Bitcoin Recipient Local",
            symbol="BTCR",
            coingecko_id="bitcoin-recipient-local",
            decimals=8,
        )
        chain = Chain.objects.create(
            name="Bitcoin Regtest Recipient",
            code="bitcoin-regtest-recipient",
            type=ChainType.BITCOIN,
            native_coin=crypto,
            rpc=self.BTC_RPC,
            active=True,
            confirm_block_count=1,
        )
        project = Project.objects.create(
            name="Local BTC Recipient Project",
            wallet=Wallet.generate(),
        )
        recipient = RecipientAddress.objects.create(
            name="Local BTC Recipient",
            project=project,
            chain_type=ChainType.BITCOIN,
            address=wallet_client.get_new_address(
                label="btc-project-recipient",
                address_type="legacy",
            ),
        )

        # prepare_local_bitcoin 会把项目收款地址导入 watch-only，确保真实节点扫描路径与生产一致。
        call_command(
            "prepare_local_bitcoin", "--wallet-name=xcash", "--mine-blocks=101"
        )
        tx_hash = wallet_client.send_to_address(recipient.address, Decimal("0.015"))
        mining_address = wallet_client.get_new_address(
            label="btc-recipient-miner",
            address_type="legacy",
        )
        wallet_client.generate_to_address(1, mining_address)

        transfer = self._scan_bitcoin_chain_and_get_transfer(
            chain=chain, tx_hash=tx_hash
        )

        self.assertEqual(transfer.to_address, recipient.address)
        self.assertEqual(transfer.amount, Decimal("0.015"))
        self.assertFalse(hasattr(transfer, "deposit"))
