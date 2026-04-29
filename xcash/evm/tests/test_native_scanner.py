from unittest.mock import patch

from django.test import TestCase
from django.test import override_settings

from chains.models import Chain
from chains.models import ChainType
from currencies.models import Crypto
from evm.models import EvmScanCursor
from evm.models import EvmScanCursorType
from evm.scanner.native import EvmNativeDirectScanner
from evm.scanner.watchers import clear_evm_watch_set_cache


@override_settings(DEBUG=False)
class EvmNativeScannerNoWatchSetTests(TestCase):
    def setUp(self):
        clear_evm_watch_set_cache()
        self.native = Crypto.objects.create(
            name="Ethereum Native No Watch",
            symbol="ETHNW",
            coingecko_id="ethereum-native-no-watch",
        )
        self.chain = Chain.objects.create(
            code="eth-no-watch",
            name="Ethereum No Watch",
            type=ChainType.EVM,
            chain_id=30_101,
            rpc="http://eth-no-watch.local",
            native_coin=self.native,
            confirm_block_count=6,
            active=True,
        )

    @patch("evm.scanner.native.EvmScannerRpcClient.get_full_block")
    @patch("evm.scanner.native.EvmScannerRpcClient.get_latest_block_number")
    def test_native_scan_advances_cursor_when_no_watched_addresses(
        self,
        get_latest_block_number_mock,
        get_full_block_mock,
    ):
        # 当系统尚未配置任何 EVM 监听地址时，原生币扫描也不应长期显示历史积压。
        EvmScanCursor.objects.create(
            chain=self.chain,
            scanner_type=EvmScanCursorType.NATIVE_DIRECT,
            last_scanned_block=39,
            last_safe_block=33,
            enabled=True,
        )
        get_latest_block_number_mock.return_value = 100

        result = EvmNativeDirectScanner.scan_chain(chain=self.chain, batch_size=32)

        cursor = EvmScanCursor.objects.get(
            chain=self.chain,
            scanner_type=EvmScanCursorType.NATIVE_DIRECT,
        )
        self.assertEqual(result.created_transfers, 0)
        self.assertEqual(result.observed_transfers, 0)
        self.assertEqual(cursor.last_scanned_block, 100)
        self.assertEqual(cursor.last_safe_block, 94)
        get_full_block_mock.assert_not_called()
