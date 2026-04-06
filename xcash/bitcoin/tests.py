from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock
from unittest.mock import PropertyMock
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.test import SimpleTestCase
from django.test import TestCase
from django.utils import timezone

from bitcoin.adapter import BitcoinAdapter
from bitcoin.admin import BitcoinScanCursorAdmin
from bitcoin.models import BitcoinBroadcastTask
from bitcoin.models import BitcoinReservedUtxo
from bitcoin.models import BitcoinScanCursor
from bitcoin.rpc import BitcoinRpcError
from bitcoin.scanner.receipt import BitcoinReceiptScanner
from bitcoin.scanner.service import BitcoinChainScannerService
from bitcoin.scanner.service import BitcoinScanSummary
from chains.adapters import TxCheckStatus
from chains.models import AddressUsage
from chains.models import BroadcastTaskFailureReason
from chains.models import BroadcastTaskResult
from chains.models import BroadcastTaskStage
from chains.models import BroadcastTask
from chains.models import Chain
from chains.models import ChainType
from chains.models import OnchainTransfer
from chains.models import TransferStatus
from chains.models import TransferType
from chains.models import Wallet
from chains.models import r
from chains.test_signer import build_test_remote_signer_backend
from currencies.models import Crypto
from deposits.models import Deposit
from deposits.models import DepositAddress
from deposits.models import DepositCollection
from deposits.models import DepositStatus
from projects.models import Project
from projects.models import RecipientAddress
from users.models import Customer
from users.models import User
from users.otp import build_admin_approval_context
from withdrawals.models import Withdrawal
from withdrawals.models import WithdrawalStatus

_BITCOIN_TEST_PATCHERS = []


def setUpModule():
    # 测试前先清空 Redis 锁，避免前一轮联调残留的账户锁污染当前 signer 回归。
    r.flushdb()
    backend = build_test_remote_signer_backend()
    # Bitcoin 测试仍然走“主应用调用 signer”的链路，只是把远端容器替换成进程内假体。
    for target in (
        "chains.signer.get_signer_backend",
        "bitcoin.models.get_signer_backend",
    ):
        patcher = patch(target, return_value=backend)
        patcher.start()
        _BITCOIN_TEST_PATCHERS.append(patcher)


def tearDownModule():
    while _BITCOIN_TEST_PATCHERS:
        _BITCOIN_TEST_PATCHERS.pop().stop()
    r.flushdb()


class BitcoinRpcClientTests(SimpleTestCase):
    def test_rpc_calls_ignore_proxy_environment(self):
        response = Mock()
        response.json.return_value = {"result": [], "error": None}
        response.is_error = False

        with patch("bitcoin.rpc.httpx.post", return_value=response) as post_mock:
            from bitcoin.rpc import BitcoinRpcClient

            BitcoinRpcClient("http://bitcoin.local").list_wallets()

        self.assertEqual(post_mock.call_args.kwargs["trust_env"], False)


class BitcoinScanCursorAdminTests(TestCase):
    def setUp(self):
        self.native = Crypto.objects.create(
            name="Bitcoin Admin Test",
            symbol="BTCA",
            coingecko_id="bitcoin-admin-test",
            decimals=8,
        )
        self.chain = Chain.objects.create(
            code="btc-admin-test",
            name="Bitcoin Admin Test",
            type=ChainType.BITCOIN,
            rpc="http://bitcoin.local",
            native_coin=self.native,
            active=True,
            confirm_block_count=3,
            latest_block_number=40,
        )
        self.cursor = BitcoinScanCursor.objects.create(
            chain=self.chain,
            last_scanned_block=9,
            last_safe_block=6,
            last_error="old error",
            last_error_at=timezone.now(),
        )
        self.admin = BitcoinScanCursorAdmin(BitcoinScanCursor, AdminSite())
        self.admin.message_user = Mock()

    @patch.object(Chain, "get_latest_block_number", new_callable=PropertyMock)
    def test_sync_selected_to_latest_advances_cursor(
        self, get_latest_block_number_mock
    ):
        get_latest_block_number_mock.return_value = 55

        self.admin.sync_selected_to_latest(
            request=Mock(),
            queryset=BitcoinScanCursor.objects.filter(pk=self.cursor.pk),
        )

        self.cursor.refresh_from_db()
        self.chain.refresh_from_db()

        self.assertEqual(self.cursor.last_scanned_block, 55)
        self.assertEqual(self.cursor.last_safe_block, 52)
        self.assertEqual(self.cursor.last_error, "")
        self.assertIsNone(self.cursor.last_error_at)
        self.assertEqual(self.chain.latest_block_number, 55)
        self.admin.message_user.assert_called_once()
        self.assertEqual(get_latest_block_number_mock.call_count, 1)

    @patch.object(Chain, "get_latest_block_number", new_callable=PropertyMock)
    def test_sync_selected_to_latest_reports_rpc_error_without_mutation(
        self, get_latest_block_number_mock
    ):
        get_latest_block_number_mock.side_effect = RuntimeError("bitcoin rpc timeout")

        self.admin.sync_selected_to_latest(
            request=Mock(),
            queryset=BitcoinScanCursor.objects.filter(pk=self.cursor.pk),
        )

        self.cursor.refresh_from_db()
        self.chain.refresh_from_db()

        self.assertEqual(self.cursor.last_scanned_block, 9)
        self.assertEqual(self.chain.latest_block_number, 40)
        self.admin.message_user.assert_called_once()
        self.assertIn("bitcoin rpc timeout", self.admin.message_user.call_args.args[1])


class BitcoinScannerTests(TestCase):
    def setUp(self):
        self.native = Crypto.objects.create(
            name="Bitcoin Test",
            symbol="BTCT",
            coingecko_id="bitcoin-test",
            decimals=8,
        )
        self.chain = Chain.objects.create(
            code="btc-test",
            name="Bitcoin Test",
            type=ChainType.BITCOIN,
            rpc="http://bitcoin.local",
            native_coin=self.native,
            active=True,
            confirm_block_count=1,
        )

    def test_watch_set_includes_deposit_and_recipient_addresses(self):
        # Bitcoin 扫描器必须同时关注充币地址和项目收款地址，否则会漏掉系统真实入账。
        project = Project.objects.create(
            name="btc-watch-project",
            wallet=Wallet.generate(),
        )
        customer = Customer.objects.create(project=project, uid="btc-watch-customer")
        deposit_address = DepositAddress.get_address(self.chain, customer)
        recipient = RecipientAddress.objects.create(
            name="btc-recipient",
            project=project,
            chain_type=ChainType.BITCOIN,
            address="1BoatSLRHtKNngkdXEeobR76b53LETtpyT",
        )

        from bitcoin.scanner.watchers import load_watch_set

        watch_set = load_watch_set()

        self.assertIn(deposit_address, watch_set.watched_addresses)
        self.assertIn(recipient.address, watch_set.watched_addresses)
        self.assertIn(recipient.address, watch_set.recipient_addresses)

    def test_chain_scanner_service_wraps_receipt_scan_result(self):
        # 链级入口只负责编排 Bitcoin 收款扫描，并把结果折叠成统一摘要对象。
        with patch(
            "bitcoin.scanner.service.BitcoinReceiptScanner.scan_recent_receipts",
            return_value=3,
        ) as scan_mock:
            summary = BitcoinChainScannerService.scan_chain(chain=self.chain)

        self.assertEqual(summary, BitcoinScanSummary(created_receipts=3))
        scan_mock.assert_called_once_with(self.chain)

    def test_chain_scanner_service_rejects_non_bitcoin_chain(self):
        # 编排入口必须拒绝错误链类型，避免任务层把非 BTC 链误送进 UTXO 扫描逻辑。
        evm_chain = Chain(
            code="eth-test",
            name="Ethereum Test",
            type=ChainType.EVM,
            native_coin=self.native,
        )

        with self.assertRaisesMessage(ValueError, "仅支持扫描 Bitcoin 链"):
            BitcoinChainScannerService.scan_chain(chain=evm_chain)

    @patch("bitcoin.adapter.BitcoinRpcClient")
    def test_tx_result_falls_back_to_raw_transaction_when_wallet_not_loaded(
        self,
        bitcoin_client_cls,
    ):
        client = bitcoin_client_cls.return_value
        client.get_transaction.side_effect = BitcoinRpcError(
            "Bitcoin RPC error (gettransaction): Requested wallet does not exist or is not loaded"
        )
        client.get_raw_transaction.return_value = {
            "txid": "abc",
            "confirmations": 2,
        }

        result = BitcoinAdapter.tx_result(self.chain, "abc")

        self.assertEqual(result, TxCheckStatus.CONFIRMED)
        client.get_transaction.assert_called_once_with("abc")
        client.get_raw_transaction.assert_called_once_with("abc")

    def test_compute_scan_window_bootstraps_from_recent_blocks_for_new_cursor(self):
        # 首次创建游标时必须优先覆盖最近区块，否则现网已运行链的首轮扫描会追不到最新入账。
        cursor = BitcoinScanCursor(chain=self.chain)

        from_block, to_block = BitcoinReceiptScanner._compute_scan_window(
            cursor=cursor,
            latest_height=500,
            confirm_block_count=1,
            batch_size=BitcoinReceiptScanner.SCAN_BATCH_SIZE,
        )

        self.assertEqual(from_block, 357)
        self.assertEqual(to_block, 500)

    @patch("bitcoin.scanner.receipt.TransferService.create_observed_transfer")
    @patch("bitcoin.scanner.receipt.BitcoinReceiptScanner._resolve_sender_address")
    @patch("bitcoin.scanner.receipt.BitcoinRpcClient.get_block")
    @patch("bitcoin.scanner.receipt.BitcoinRpcClient.get_block_hash")
    @patch("bitcoin.scanner.receipt.BitcoinRpcClient.get_block_count")
    @patch("bitcoin.scanner.receipt.load_watch_set")
    def test_scan_recent_receipts_advances_persistent_cursor(
        self,
        load_watch_set_mock,
        get_block_count_mock,
        get_block_hash_mock,
        get_block_mock,
        resolve_sender_address_mock,
        create_observed_transfer_mock,
    ):
        # BTC 扫描必须把推进位置落库，避免长时间停机后只能靠最近窗口猜测补扫。
        watched_address = "1BoatSLRHtKNngkdXEeobR76b53LETtpyT"
        load_watch_set_mock.return_value = SimpleNamespace(
            watched_addresses=frozenset({watched_address}),
            recipient_addresses=frozenset({watched_address}),
        )
        get_block_count_mock.return_value = 5
        get_block_hash_mock.side_effect = lambda height: f"block-{height}"
        get_block_mock.side_effect = lambda block_hash: {
            "height": int(block_hash.split("-")[1]),
            "time": 1_700_000_000,
            "tx": [
                {
                    "txid": "ab" * 32,
                    "blocktime": 1_700_000_000,
                    "vout": [
                        {
                            "n": 0,
                            "value": "0.01",
                            "scriptPubKey": {"address": watched_address},
                        }
                    ],
                }
            ],
        }
        resolve_sender_address_mock.return_value = (
            "1ExternalSenderAddress1111111111114T1an2"
        )
        create_observed_transfer_mock.return_value = SimpleNamespace(created=True)

        created_count = BitcoinReceiptScanner.scan_recent_receipts(self.chain)

        cursor = BitcoinScanCursor.objects.get(chain=self.chain)
        self.assertEqual(created_count, 6)
        self.assertEqual(cursor.last_scanned_block, 5)
        self.assertEqual(cursor.last_safe_block, 4)
        self.chain.refresh_from_db()
        self.assertEqual(self.chain.latest_block_number, 5)

    @patch("bitcoin.scanner.receipt.TransferService.create_observed_transfer")
    @patch("bitcoin.scanner.receipt.BitcoinReceiptScanner._resolve_sender_address")
    @patch("bitcoin.scanner.receipt.BitcoinRpcClient.get_block")
    @patch("bitcoin.scanner.receipt.BitcoinRpcClient.get_block_hash")
    @patch("bitcoin.scanner.receipt.BitcoinRpcClient.get_block_count")
    @patch("bitcoin.scanner.receipt.load_watch_set")
    def test_scan_recent_receipts_rewinds_tail_window_idempotently(
        self,
        load_watch_set_mock,
        get_block_count_mock,
        get_block_hash_mock,
        get_block_mock,
        resolve_sender_address_mock,
        create_observed_transfer_mock,
    ):
        # 主游标推进后仍要回退一小段尾部重扫，以覆盖轻微重组，同时不能重复建单。
        watched_address = "1BoatSLRHtKNngkdXEeobR76b53LETtpyT"
        load_watch_set_mock.return_value = SimpleNamespace(
            watched_addresses=frozenset({watched_address}),
            recipient_addresses=frozenset({watched_address}),
        )
        get_block_count_mock.return_value = 30
        get_block_hash_mock.side_effect = lambda height: f"block-{height}"
        get_block_mock.side_effect = lambda block_hash: {
            "height": int(block_hash.split("-")[1]),
            "time": 1_700_000_000,
            "tx": [
                {
                    "txid": "cd" * 32,
                    "blocktime": 1_700_000_000,
                    "vout": [
                        {
                            "n": 0,
                            "value": "0.01",
                            "scriptPubKey": {"address": watched_address},
                        }
                    ],
                }
            ],
        }
        resolve_sender_address_mock.return_value = (
            "1ExternalSenderAddress1111111111114T1an2"
        )
        create_observed_transfer_mock.side_effect = [
            SimpleNamespace(created=True),
            *[SimpleNamespace(created=False) for _ in range(60)],
        ]

        first = BitcoinReceiptScanner.scan_recent_receipts(self.chain)
        second = BitcoinReceiptScanner.scan_recent_receipts(self.chain)

        cursor = BitcoinScanCursor.objects.get(chain=self.chain)
        self.assertGreater(first, 0)
        self.assertEqual(second, 0)
        self.assertEqual(cursor.last_scanned_block, 30)

    @patch("bitcoin.scanner.receipt.BitcoinRpcClient.get_block_count")
    def test_scan_recent_receipts_records_cursor_error_when_rpc_fails(
        self,
        get_block_count_mock,
    ):
        # RPC 失败后必须把错误写回游标，方便后台与运维定位扫描停滞原因。
        get_block_count_mock.side_effect = BitcoinRpcError("rpc timeout")

        with self.assertRaises(BitcoinRpcError):
            BitcoinReceiptScanner.scan_recent_receipts(self.chain)

        cursor = BitcoinScanCursor.objects.get(chain=self.chain)
        self.assertEqual(cursor.last_scanned_block, 0)
        self.assertEqual(cursor.last_error, "rpc timeout")
        self.assertIsNotNone(cursor.last_error_at)

    @patch("bitcoin.scanner.receipt.load_watch_set")
    @patch("bitcoin.scanner.receipt.BitcoinRpcClient.get_block_count")
    def test_scan_recent_receipts_skips_disabled_cursor(
        self,
        get_block_count_mock,
        load_watch_set_mock,
    ):
        # 后台禁用扫描游标后，任务应立即停扫且不再触发任何节点请求。
        BitcoinScanCursor.objects.create(
            chain=self.chain,
            last_scanned_block=12,
            last_safe_block=10,
            enabled=False,
        )
        get_block_count_mock.return_value = 99
        load_watch_set_mock.return_value = SimpleNamespace(
            watched_addresses=frozenset(),
            recipient_addresses=frozenset(),
        )

        created_count = BitcoinReceiptScanner.scan_recent_receipts(self.chain)

        self.assertEqual(created_count, 0)
        get_block_count_mock.assert_not_called()
        load_watch_set_mock.assert_not_called()
        cursor = BitcoinScanCursor.objects.get(chain=self.chain)
        self.assertEqual(cursor.last_scanned_block, 12)
        self.assertEqual(cursor.last_safe_block, 10)

    def test_should_track_output_filters_change_and_non_recipient_internal_flow(self):
        # BTC 首版只接收安全场景，内部找零和内部流向非项目收款地址都不应误判为入账。
        internal_addresses = frozenset({"internal-deposit", "project-recipient"})
        recipient_addresses = frozenset({"project-recipient"})

        self.assertFalse(
            BitcoinReceiptScanner._should_track_output(
                sender_address="internal-deposit",
                recipient_address="internal-deposit",
                internal_addresses=internal_addresses,
                recipient_addresses=recipient_addresses,
            )
        )
        self.assertFalse(
            BitcoinReceiptScanner._should_track_output(
                sender_address="internal-deposit",
                recipient_address="another-internal",
                internal_addresses=internal_addresses | {"another-internal"},
                recipient_addresses=recipient_addresses,
            )
        )
        self.assertTrue(
            BitcoinReceiptScanner._should_track_output(
                sender_address="external-address",
                recipient_address="internal-deposit",
                internal_addresses=internal_addresses,
                recipient_addresses=recipient_addresses,
            )
        )
        self.assertTrue(
            BitcoinReceiptScanner._should_track_output(
                sender_address="internal-deposit",
                recipient_address="project-recipient",
                internal_addresses=internal_addresses,
                recipient_addresses=recipient_addresses,
            )
        )


class BitcoinTaskTests(TestCase):
    @patch("bitcoin.tasks.BitcoinChainScannerService.scan_chain")
    def test_scan_bitcoin_receipts_only_scans_active_bitcoin_chains(
        self, scan_chain_mock
    ):
        # 定时任务层只能挑启用中的 BTC 链，具体扫描细节统一下沉到链级 service。
        from bitcoin.tasks import scan_bitcoin_receipts

        native = Crypto.objects.create(
            name="Bitcoin Task",
            symbol="BTCQ",
            coingecko_id="bitcoin-task",
            decimals=8,
        )
        bitcoin_chain = Chain.objects.create(
            code="btc-active",
            name="Bitcoin Active",
            type=ChainType.BITCOIN,
            rpc="http://bitcoin.active",
            native_coin=native,
            active=True,
        )
        Chain.objects.create(
            code="btc-inactive",
            name="Bitcoin Inactive",
            type=ChainType.BITCOIN,
            rpc="http://bitcoin.inactive",
            native_coin=native,
            active=False,
        )
        Chain.objects.create(
            code="eth-active",
            name="Ethereum Active",
            type=ChainType.EVM,
            chain_id=1,
            rpc="http://eth.active",
            native_coin=native,
            active=True,
        )
        scan_chain_mock.return_value = BitcoinScanSummary(created_receipts=0)

        scan_bitcoin_receipts.run()

        scan_chain_mock.assert_called_once_with(chain=bitcoin_chain)

    @patch("bitcoin.tasks.BitcoinBroadcastTransferObserver.observe_chain")
    @patch("bitcoin.tasks.BitcoinChainScannerService.scan_chain")
    def test_scan_bitcoin_receipts_skips_disabled_chain_cursor_entirely(
        self,
        scan_chain_mock,
        observe_chain_mock,
    ):
        # 游标被禁用时，整条 BTC 扫描任务都应停下，
        # 既不能继续做收款扫描，也不能继续补录内部出账。
        from bitcoin.tasks import scan_bitcoin_receipts

        native = Crypto.objects.create(
            name="Bitcoin Task Disabled",
            symbol="BTCDIS",
            coingecko_id="bitcoin-task-disabled",
            decimals=8,
        )
        chain = Chain.objects.create(
            code="btc-disabled",
            name="Bitcoin Disabled",
            type=ChainType.BITCOIN,
            rpc="http://bitcoin.disabled",
            native_coin=native,
            active=True,
        )
        BitcoinScanCursor.objects.create(
            chain=chain,
            last_scanned_block=15,
            last_safe_block=12,
            enabled=False,
        )

        scan_bitcoin_receipts.run()

        scan_chain_mock.assert_not_called()
        observe_chain_mock.assert_not_called()

    @patch("withdrawals.service.WebhookService.create_event")
    @patch("chains.tasks.process_transfer.apply_async")
    @patch("bitcoin.rpc.BitcoinRpcClient.get_block")
    @patch("bitcoin.rpc.BitcoinRpcClient.get_raw_transaction")
    @patch("bitcoin.tasks.BitcoinChainScannerService.scan_chain")
    def test_scan_bitcoin_receipts_observes_pending_withdrawal_tasks(
        self,
        scan_chain_mock,
        get_raw_transaction_mock,
        get_block_mock,
        _process_transfer_mock,
        _create_event_mock,
    ):
        # BTC 出账进入区块后，定时扫描必须能补出 OnchainTransfer，
        # 否则 Withdrawal 永远无法从 PENDING 进入 CONFIRMING。
        from bitcoin.tasks import scan_bitcoin_receipts

        native = Crypto.objects.create(
            name="Bitcoin Task Observe",
            symbol="BTCO",
            coingecko_id="bitcoin-task-observe",
            decimals=8,
        )
        chain = Chain.objects.create(
            code="btc-observe",
            name="Bitcoin Observe",
            type=ChainType.BITCOIN,
            rpc="http://bitcoin.observe",
            native_coin=native,
            active=True,
            confirm_block_count=1,
        )
        project = Project.objects.create(
            name="btc-observe-project",
            wallet=Wallet.generate(),
        )
        vault = project.wallet.get_address(
            chain_type=ChainType.BITCOIN,
            usage=AddressUsage.Vault,
        )
        tx_hash = "ab" * 32
        recipient = "1BoatSLRHtKNngkdXEeobR76b53LETtpyT"

        base_task = BroadcastTask.objects.create(
            chain=chain,
            address=vault,
            transfer_type=TransferType.Withdrawal,
            crypto=native,
            recipient=recipient,
            amount=Decimal("0.01"),
            tx_hash=tx_hash,
            stage=BroadcastTaskStage.PENDING_CHAIN,
            result=BroadcastTaskResult.UNKNOWN,
        )
        BitcoinBroadcastTask.objects.create(
            base_task=base_task,
            address=vault,
            chain=chain,
            signed_payload="signed-payload",
            fee_satoshi=500,
        )
        withdrawal = Withdrawal.objects.create(
            project=project,
            out_no="btc-observe-withdrawal",
            chain=chain,
            crypto=native,
            amount=Decimal("0.01"),
            to=recipient,
            hash=tx_hash,
            broadcast_task=base_task,
            status=WithdrawalStatus.PENDING,
        )

        scan_chain_mock.return_value = BitcoinScanSummary(created_receipts=0)
        get_raw_transaction_mock.return_value = {
            "txid": tx_hash,
            "blockhash": "block-1",
            "blocktime": 1_700_000_000,
            "vout": [
                {
                    "n": 0,
                    "value": "0.01",
                    "scriptPubKey": {"address": recipient},
                }
            ],
        }
        get_block_mock.return_value = {
            "height": 12,
            "time": 1_700_000_000,
        }

        scan_bitcoin_receipts.run()

        transfer = OnchainTransfer.objects.get(
            chain=chain,
            hash=tx_hash,
            event_id="vout:0",
        )
        self.assertEqual(transfer.from_address, vault.address)
        self.assertEqual(transfer.to_address, recipient)

        transfer.process()
        withdrawal.refresh_from_db()
        self.assertEqual(withdrawal.status, WithdrawalStatus.CONFIRMING)

    @patch("chains.tasks.process_transfer.apply_async")
    @patch("bitcoin.rpc.BitcoinRpcClient.get_block")
    @patch("bitcoin.rpc.BitcoinRpcClient.get_raw_transaction")
    @patch("bitcoin.rpc.BitcoinRpcClient.get_transaction")
    def test_broadcast_observer_uses_old_tx_hash_history_after_fee_replacement(
        self,
        get_transaction_mock,
        get_raw_transaction_mock,
        get_block_mock,
        _process_transfer_mock,
    ):
        # 手工 RBF 后如果旧 tx 反而先被矿工打包，observer 仍必须能通过 tx_hash 历史补录。
        from bitcoin.scanner.broadcast import BitcoinBroadcastTransferObserver

        native = Crypto.objects.create(
            name="Bitcoin Task Observe History",
            symbol="BTCOH",
            coingecko_id="bitcoin-task-observe-history",
            decimals=8,
        )
        chain = Chain.objects.create(
            code="btc-observe-history",
            name="Bitcoin Observe History",
            type=ChainType.BITCOIN,
            rpc="http://bitcoin.observe.history",
            native_coin=native,
            active=True,
            confirm_block_count=1,
        )
        project = Project.objects.create(
            name="btc-observe-history-project",
            wallet=Wallet.generate(),
        )
        vault = project.wallet.get_address(
            chain_type=ChainType.BITCOIN,
            usage=AddressUsage.Vault,
        )
        old_hash = "cd" * 32
        new_hash = "ef" * 32
        recipient = "1BoatSLRHtKNngkdXEeobR76b53LETtpyT"

        base_task = BroadcastTask.objects.create(
            chain=chain,
            address=vault,
            transfer_type=TransferType.Withdrawal,
            crypto=native,
            recipient=recipient,
            amount=Decimal("0.01"),
            tx_hash=old_hash,
            stage=BroadcastTaskStage.PENDING_CHAIN,
            result=BroadcastTaskResult.UNKNOWN,
        )
        base_task.create_initial_tx_hash()
        base_task.append_tx_hash(new_hash)
        BitcoinBroadcastTask.objects.create(
            base_task=base_task,
            address=vault,
            chain=chain,
            signed_payload="signed-payload",
            fee_satoshi=500,
        )
        withdrawal = Withdrawal.objects.create(
            project=project,
            out_no="btc-observe-history-withdrawal",
            chain=chain,
            crypto=native,
            amount=Decimal("0.01"),
            to=recipient,
            hash=new_hash,
            broadcast_task=base_task,
            status=WithdrawalStatus.PENDING,
        )

        def raw_tx_side_effect(tx_hash: str):
            if tx_hash == old_hash:
                return {
                    "txid": old_hash,
                    "blockhash": "block-history-1",
                    "blocktime": 1_700_000_001,
                    "vout": [
                        {
                            "n": 0,
                            "value": "0.01",
                            "scriptPubKey": {"address": recipient},
                        }
                    ],
                }
            return None

        get_transaction_mock.return_value = None
        get_raw_transaction_mock.side_effect = raw_tx_side_effect
        get_block_mock.return_value = {
            "height": 13,
            "time": 1_700_000_001,
        }

        created_count = BitcoinBroadcastTransferObserver.observe_chain(chain=chain)

        self.assertEqual(created_count, 1)
        transfer = OnchainTransfer.objects.get(
            chain=chain,
            hash=old_hash,
            event_id="vout:0",
        )
        transfer.process()
        withdrawal.refresh_from_db()
        base_task.refresh_from_db()
        self.assertEqual(withdrawal.status, WithdrawalStatus.CONFIRMING)
        self.assertEqual(withdrawal.hash, old_hash)
        self.assertEqual(base_task.tx_hash, old_hash)


class BitcoinWatchSyncTests(TestCase):
    def setUp(self):
        self.native = Crypto.objects.create(
            name="Bitcoin Watch Sync",
            symbol="BTCSYNC",
            coingecko_id="bitcoin-watch-sync",
            decimals=8,
        )
        self.chain = Chain.objects.create(
            code="btc-sync",
            name="Bitcoin Sync",
            type=ChainType.BITCOIN,
            rpc="http://bitcoin.sync/wallet/xcash",
            native_coin=self.native,
            active=True,
            confirm_block_count=1,
        )
        self.project = Project.objects.create(
            name="btc-sync-project",
            wallet=Wallet.generate(),
        )
        self.customer = Customer.objects.create(project=self.project, uid="btc-sync-user")

    @patch("bitcoin.tasks.sync_bitcoin_watch_addresses.apply_async")
    def test_wallet_get_address_schedules_watch_sync_for_new_bitcoin_address(
        self,
        apply_async_mock,
    ):
        with self.captureOnCommitCallbacks(execute=True):
            self.project.wallet.get_address(
                chain_type=ChainType.BITCOIN,
                usage=AddressUsage.Deposit,
                address_index=3,
            )

        apply_async_mock.assert_called_once()

    @patch("bitcoin.tasks.sync_bitcoin_watch_addresses.apply_async")
    def test_saving_bitcoin_recipient_address_schedules_watch_sync(
        self,
        apply_async_mock,
    ):
        with self.captureOnCommitCallbacks(execute=True):
            RecipientAddress.objects.create(
                name="btc-sync-recipient",
                project=self.project,
                chain_type=ChainType.BITCOIN,
                address="1BoatSLRHtKNngkdXEeobR76b53LETtpyT",
                used_for_invoice=True,
                used_for_deposit=False,
            )

        apply_async_mock.assert_called_once()

    @patch("bitcoin.watch_sync.BitcoinRpcClient.import_descriptor")
    @patch("bitcoin.watch_sync.BitcoinRpcClient.import_address")
    def test_sync_chain_imports_known_addresses_with_descriptor_fallback(
        self,
        import_address_mock,
        import_descriptor_mock,
    ):
        deposit_address = DepositAddress.get_address(self.chain, self.customer)
        RecipientAddress.objects.create(
            name="btc-sync-import-recipient",
            project=self.project,
            chain_type=ChainType.BITCOIN,
            address="1BoatSLRHtKNngkdXEeobR76b53LETtpyT",
            used_for_invoice=True,
            used_for_deposit=False,
        )

        import_address_mock.side_effect = [
            BitcoinRpcError("Only legacy wallets are supported by this command"),
            None,
        ]

        from bitcoin.watch_sync import BitcoinWatchSyncService

        imported_count = BitcoinWatchSyncService.sync_chain(self.chain)

        self.assertEqual(imported_count, 2)
        self.assertEqual(import_address_mock.call_count, 2)
        import_descriptor_mock.assert_called_once()
        descriptor = import_descriptor_mock.call_args.kwargs["descriptor"]
        self.assertEqual(descriptor, f"addr({deposit_address})")


class BitcoinReservedUtxoTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(username="btc-utxo-user")
        self.wallet = Wallet.generate()
        self.project = Project.objects.create(
            name="btc-utxo-project",
            wallet=self.wallet,
        )
        self.native = Crypto.objects.create(
            name="Bitcoin Native",
            symbol="BTCU",
            coingecko_id="bitcoin-utxo",
            decimals=8,
        )
        self.chain = Chain.objects.create(
            code="btc-utxo",
            name="Bitcoin UTXO",
            type=ChainType.BITCOIN,
            rpc="http://bitcoin.local",
            native_coin=self.native,
            active=True,
            confirm_block_count=1,
        )
        self.address = self.wallet.get_address(
            chain_type=ChainType.BITCOIN,
            usage=AddressUsage.Vault,
        )

    @patch("bitcoin.models.select_utxos_for_amount")
    @patch("bitcoin.models.get_signer_backend")
    @patch(
        "bitcoin.models.BitcoinRpcClient.estimate_smart_fee",
        return_value=Decimal("0.0001"),
    )
    @patch("bitcoin.models.BitcoinRpcClient.list_unspent")
    @patch("chains.models.Address.release_lock")
    @patch("chains.models.Address.get_lock", return_value=True)
    def test_schedule_transfer_excludes_reserved_utxo_and_reserves_selected_input(
        self,
        _get_lock_mock,
        _release_lock_mock,
        list_unspent_mock,
        _estimate_fee_mock,
        get_signer_backend_mock,
        select_utxos_mock,
    ):
        # 已被本地任务预留的 UTXO 不得再次参与选币；新选中的输入必须立即写入预留表。
        reserved_task = BroadcastTask.objects.create(
            chain=self.chain,
            address=self.address,
            transfer_type=TransferType.Withdrawal,
            crypto=self.native,
            recipient="1BoatSLRHtKNngkdXEeobR76b53LETtpyT",
            amount=Decimal("0.1"),
            tx_hash="b" * 64,
        )
        BitcoinReservedUtxo.objects.create(
            chain=self.chain,
            address=self.address,
            broadcast_task=reserved_task,
            txid="utxo-reserved",
            vout=0,
        )

        list_unspent_mock.return_value = [
            {
                "txid": "utxo-reserved",
                "vout": 0,
                "amount": "0.5",
                "confirmations": 10,
                "scriptPubKey": "76a914",
            },
            {
                "txid": "utxo-free",
                "vout": 1,
                "amount": "1.0",
                "confirmations": 10,
                "scriptPubKey": "76a914",
            },
        ]

        select_utxos_mock.side_effect = lambda **kwargs: (
            kwargs["utxos"],
            120,
        )
        signer_backend = SimpleNamespace(
            sign_bitcoin_transaction=Mock(
                return_value=SimpleNamespace(
                    txid="a" * 64,
                    signed_payload="signed-payload",
                )
            )
        )
        get_signer_backend_mock.return_value = signer_backend

        task = BitcoinBroadcastTask.schedule_transfer(
            address=self.address,
            chain=self.chain,
            crypto=self.native,
            to="1BoatSLRHtKNngkdXEeobR76b53LETtpyT",
            amount=Decimal("0.25"),
            transfer_type=TransferType.Withdrawal,
        )

        self.assertEqual(task.base_task.tx_hash, "a" * 64)
        self.assertEqual(
            list(
                BitcoinReservedUtxo.objects.filter(
                    broadcast_task=task.base_task,
                    released_at__isnull=True,
                ).values_list("txid", "vout")
            ),
            [("utxo-free", 1)],
        )
        select_utxos_mock.assert_called_once()
        self.assertEqual(
            select_utxos_mock.call_args.kwargs["utxos"][0]["txid"], "utxo-free"
        )
        signer_backend.sign_bitcoin_transaction.assert_called_once()
        self.assertTrue(
            signer_backend.sign_bitcoin_transaction.call_args.kwargs.get("replaceable")
        )

    @patch("chains.models.Balance.update_from_transfer")
    def test_confirm_releases_reserved_utxos(self, _update_balance_mock):
        # Bitcoin 转账一旦确认成功，之前为该任务预留的 UTXO 必须释放。
        base_task = BroadcastTask.objects.create(
            chain=self.chain,
            address=self.address,
            transfer_type=TransferType.Withdrawal,
            crypto=self.native,
            recipient="1BoatSLRHtKNngkdXEeobR76b53LETtpyT",
            amount=Decimal("0.1"),
            tx_hash="c" * 64,
        )
        BitcoinReservedUtxo.objects.create(
            chain=self.chain,
            address=self.address,
            broadcast_task=base_task,
            txid="utxo-confirm",
            vout=2,
        )
        transfer = OnchainTransfer.objects.create(
            chain=self.chain,
            block=1,
            hash="c" * 64,
            event_id="vout:0",
            crypto=self.native,
            from_address="1BoatSLRHtKNngkdXEeobR76b53LETtpyT",
            to_address="1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
            value=Decimal("1000"),
            amount=Decimal("0.1"),
            timestamp=1,
            datetime=timezone.now(),
            status=TransferStatus.CONFIRMING,
        )

        with patch("chains.models.timezone.now", return_value=self.chain.created_at):
            transfer.confirm()

        reservation = BitcoinReservedUtxo.objects.get(broadcast_task=base_task)
        self.assertIsNotNone(reservation.released_at)

    @patch(
        "bitcoin.models.select_utxos_for_amount",
        side_effect=lambda **kwargs: (kwargs["utxos"], 120),
    )
    @patch("bitcoin.models.get_signer_backend")
    @patch(
        "bitcoin.models.BitcoinRpcClient.estimate_smart_fee",
        return_value=Decimal("0.0001"),
    )
    @patch("bitcoin.models.BitcoinRpcClient.list_unspent")
    @patch("chains.models.Address.release_lock")
    @patch("chains.models.Address.get_lock", return_value=True)
    def test_second_schedule_transfer_is_blocked_by_db_reserved_utxo_boundary(
        self,
        _get_lock_mock,
        _release_lock_mock,
        list_unspent_mock,
        _estimate_fee_mock,
        get_signer_backend_mock,
        _select_utxos_mock,
    ):
        # 即使节点第二次仍返回同一枚 UTXO，数据库预留也必须阻止系统签出第二笔交易。
        list_unspent_mock.return_value = [
            {
                "txid": "utxo-shared",
                "vout": 0,
                "amount": "1.0",
                "confirmations": 10,
                "scriptPubKey": "76a914",
            }
        ]
        signer_backend = SimpleNamespace(
            sign_bitcoin_transaction=Mock(
                return_value=SimpleNamespace(
                    txid="d" * 64,
                    signed_payload="signed-payload",
                )
            )
        )
        get_signer_backend_mock.return_value = signer_backend

        BitcoinBroadcastTask.schedule_transfer(
            address=self.address,
            chain=self.chain,
            crypto=self.native,
            to="1BoatSLRHtKNngkdXEeobR76b53LETtpyT",
            amount=Decimal("0.25"),
            transfer_type=TransferType.Withdrawal,
        )

        with self.assertRaisesMessage(ValueError, "无可用未预留 UTXO"):
            BitcoinBroadcastTask.schedule_transfer(
                address=self.address,
                chain=self.chain,
                crypto=self.native,
                to="1BoatSLRHtKNngkdXEeobR76b53LETtpyT",
                amount=Decimal("0.25"),
                transfer_type=TransferType.Withdrawal,
            )

    @patch(
        "bitcoin.models.select_utxos_for_amount",
        side_effect=lambda **kwargs: (kwargs["utxos"], 120),
    )
    @patch("bitcoin.models.get_signer_backend")
    @patch(
        "bitcoin.models.BitcoinRpcClient.estimate_smart_fee",
        return_value=Decimal("0.0001"),
    )
    @patch("bitcoin.models.BitcoinRpcClient.list_unspent")
    @patch("chains.models.Address.release_lock")
    @patch(
        "chains.models.Address.get_lock",
        side_effect=AssertionError("redis address lock should not be used"),
    )
    def test_schedule_transfer_no_longer_depends_on_redis_address_lock(
        self,
        _get_lock_mock,
        _release_lock_mock,
        list_unspent_mock,
        _estimate_fee_mock,
        get_signer_backend_mock,
        _select_utxos_mock,
    ):
        list_unspent_mock.return_value = [
            {
                "txid": "utxo-db-lock",
                "vout": 0,
                "amount": "1.0",
                "confirmations": 10,
                "scriptPubKey": "76a914",
            }
        ]
        signer_backend = SimpleNamespace(
            sign_bitcoin_transaction=Mock(
                return_value=SimpleNamespace(
                    txid="e" * 64,
                    signed_payload="signed-payload",
                )
            )
        )
        get_signer_backend_mock.return_value = signer_backend

        task = BitcoinBroadcastTask.schedule_transfer(
            address=self.address,
            chain=self.chain,
            crypto=self.native,
            to="1BoatSLRHtKNngkdXEeobR76b53LETtpyT",
            amount=Decimal("0.25"),
            transfer_type=TransferType.Withdrawal,
        )

        self.assertEqual(task.base_task.tx_hash, "e" * 64)
        signer_backend.sign_bitcoin_transaction.assert_called_once()

    @patch("bitcoin.models.BitcoinRpcClient.send_raw_transaction")
    def test_broadcast_missing_utxo_marks_withdrawal_failed(
        self,
        send_raw_transaction_mock,
    ):
        # 输入已花费时，BTC 广播失败必须同步把 Withdrawal 终局为 FAILED。
        send_raw_transaction_mock.side_effect = BitcoinRpcError(
            "Bitcoin RPC error (sendrawtransaction): missingorspent"
        )
        tx_hash = "f" * 64
        base_task = BroadcastTask.objects.create(
            chain=self.chain,
            address=self.address,
            transfer_type=TransferType.Withdrawal,
            crypto=self.native,
            recipient="1BoatSLRHtKNngkdXEeobR76b53LETtpyT",
            amount=Decimal("0.1"),
            tx_hash=tx_hash,
            stage=BroadcastTaskStage.QUEUED,
            result=BroadcastTaskResult.UNKNOWN,
        )
        task = BitcoinBroadcastTask.objects.create(
            base_task=base_task,
            address=self.address,
            chain=self.chain,
            signed_payload="signed-payload",
            fee_satoshi=100,
        )
        BitcoinReservedUtxo.objects.create(
            chain=self.chain,
            address=self.address,
            broadcast_task=base_task,
            txid="utxo-failed",
            vout=0,
        )
        withdrawal = Withdrawal.objects.create(
            project=self.project,
            out_no="btc-failed-withdrawal",
            chain=self.chain,
            crypto=self.native,
            amount=Decimal("0.1"),
            to="1BoatSLRHtKNngkdXEeobR76b53LETtpyT",
            hash=tx_hash,
            broadcast_task=base_task,
            status=WithdrawalStatus.PENDING,
        )

        task.broadcast()

        base_task.refresh_from_db()
        withdrawal.refresh_from_db()
        reservation = BitcoinReservedUtxo.objects.get(broadcast_task=base_task)
        self.assertEqual(base_task.result, BroadcastTaskResult.FAILED)
        self.assertEqual(base_task.failure_reason, BroadcastTaskFailureReason.DOUBLE_SPEND)
        self.assertEqual(withdrawal.status, WithdrawalStatus.FAILED)
        self.assertIsNotNone(reservation.released_at)

    @patch("bitcoin.models.BitcoinRpcClient.send_raw_transaction")
    def test_broadcast_missing_utxo_drops_pending_collection(
        self,
        send_raw_transaction_mock,
    ):
        # BTC 归集广播失败后，占位 DepositCollection 必须释放，否则后续无法重试。
        send_raw_transaction_mock.side_effect = BitcoinRpcError(
            "Bitcoin RPC error (sendrawtransaction): txn-mempool-conflict"
        )
        customer = Customer.objects.create(project=self.project, uid="btc-collect-user")
        transfer = OnchainTransfer.objects.create(
            chain=self.chain,
            block=1,
            hash="1" * 64,
            event_id="vout:0",
            crypto=self.native,
            from_address="12cbQLTFMXRnSzktFkuoG3eHoMeFtpTu3S",
            to_address=self.address.address,
            value=Decimal("10000000"),
            amount=Decimal("0.1"),
            timestamp=1,
            datetime=timezone.now(),
            status=TransferStatus.CONFIRMED,
            type=TransferType.Deposit,
        )
        deposit = Deposit.objects.create(
            customer=customer,
            transfer=transfer,
            status=DepositStatus.COMPLETED,
        )
        tx_hash = "2" * 64
        base_task = BroadcastTask.objects.create(
            chain=self.chain,
            address=self.address,
            transfer_type=TransferType.DepositCollection,
            crypto=self.native,
            recipient="1BoatSLRHtKNngkdXEeobR76b53LETtpyT",
            amount=Decimal("0.1"),
            tx_hash=tx_hash,
            stage=BroadcastTaskStage.QUEUED,
            result=BroadcastTaskResult.UNKNOWN,
        )
        task = BitcoinBroadcastTask.objects.create(
            base_task=base_task,
            address=self.address,
            chain=self.chain,
            signed_payload="signed-payload",
            fee_satoshi=100,
        )
        collection = DepositCollection.objects.create(
            collection_hash=tx_hash,
            broadcast_task=base_task,
        )
        deposit.collection = collection
        deposit.save(update_fields=["collection"])

        task.broadcast()

        deposit.refresh_from_db()
        base_task.refresh_from_db()
        self.assertEqual(base_task.result, BroadcastTaskResult.FAILED)
        self.assertFalse(DepositCollection.objects.filter(pk=collection.pk).exists())
        self.assertIsNone(deposit.collection_id)


class BitcoinFeeBumpTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(
            name="btc-fee-bump-project",
            wallet=Wallet.generate(),
        )
        self.native = Crypto.objects.create(
            name="Bitcoin Fee Bump",
            symbol="BTCBUMP",
            coingecko_id="bitcoin-fee-bump",
            decimals=8,
        )
        self.chain = Chain.objects.create(
            code="btc-fee-bump",
            name="Bitcoin Fee Bump",
            type=ChainType.BITCOIN,
            rpc="http://bitcoin.bump",
            native_coin=self.native,
            active=True,
            confirm_block_count=1,
        )
        self.address = self.project.wallet.get_address(
            chain_type=ChainType.BITCOIN,
            usage=AddressUsage.Vault,
        )
        self.recipient = "1BoatSLRHtKNngkdXEeobR76b53LETtpyT"

    def _build_signed_payload(self, *, replaceable: bool, fee_satoshi: int = 100) -> str:
        del fee_satoshi
        sequence = "fdffffff" if replaceable else "feffffff"
        return (
            "01000000"
            "01"
            + "00" * 32
            + "00000000"
            + "00"
            + sequence
            + "01"
            + "0000000000000000"
            + "00"
            + "00000000"
        )

    def _create_pending_withdrawal(self, *, tx_hash: str = "11" * 32):
        base_task = BroadcastTask.objects.create(
            chain=self.chain,
            address=self.address,
            transfer_type=TransferType.Withdrawal,
            crypto=self.native,
            recipient=self.recipient,
            amount=Decimal("0.01"),
            tx_hash=tx_hash,
            stage=BroadcastTaskStage.PENDING_CHAIN,
            result=BroadcastTaskResult.UNKNOWN,
        )
        task = BitcoinBroadcastTask.objects.create(
            base_task=base_task,
            address=self.address,
            chain=self.chain,
            signed_payload=self._build_signed_payload(replaceable=True),
            fee_satoshi=100,
        )
        BitcoinReservedUtxo.objects.create(
            chain=self.chain,
            address=self.address,
            broadcast_task=base_task,
            txid="aa" * 32,
            vout=0,
        )
        withdrawal = Withdrawal.objects.create(
            project=self.project,
            out_no=f"btc-fee-bump-{tx_hash[:8]}",
            chain=self.chain,
            crypto=self.native,
            amount=Decimal("0.01"),
            to=self.recipient,
            hash=tx_hash,
            broadcast_task=base_task,
            status=WithdrawalStatus.PENDING,
        )
        return withdrawal, task

    @patch("bitcoin.fee_bump.get_signer_backend")
    @patch(
        "bitcoin.fee_bump.BitcoinRpcClient.send_raw_transaction",
        return_value="22" * 32,
    )
    @patch(
        "bitcoin.fee_bump.BitcoinRpcClient.estimate_smart_fee",
        return_value=Decimal("0.0002"),
    )
    @patch("bitcoin.fee_bump.BitcoinRpcClient.get_raw_transaction")
    def test_fee_bump_service_replaces_hash_payload_and_fee(
        self,
        get_raw_transaction_mock,
        _estimate_fee_mock,
        send_raw_transaction_mock,
        get_signer_backend_mock,
    ):
        from bitcoin.fee_bump import BitcoinFeeBumpService

        withdrawal, task = self._create_pending_withdrawal()

        def raw_tx_side_effect(tx_hash: str):
            if tx_hash == "aa" * 32:
                return {
                    "txid": tx_hash,
                    "confirmations": 12,
                    "vout": [
                        {
                            "n": 0,
                            "value": "0.02",
                            "scriptPubKey": {"hex": "76a914"},
                        }
                    ],
                }
            return None

        get_raw_transaction_mock.side_effect = raw_tx_side_effect
        signer_backend = SimpleNamespace(
            sign_bitcoin_transaction=Mock(
                return_value=SimpleNamespace(
                    txid="22" * 32,
                    signed_payload="signed-new-payload",
                )
            )
        )
        get_signer_backend_mock.return_value = signer_backend

        bumped_task = BitcoinFeeBumpService.bump_withdrawal(
            withdrawal_id=withdrawal.pk,
            approval_context=build_admin_approval_context(
                source="test_bitcoin_fee_bump"
            ),
        )

        withdrawal.refresh_from_db()
        task.refresh_from_db()
        task.base_task.refresh_from_db()
        self.assertEqual(bumped_task.pk, task.pk)
        self.assertEqual(task.base_task.tx_hash, "22" * 32)
        self.assertEqual(task.signed_payload, "signed-new-payload")
        self.assertGreater(task.fee_satoshi, 100)
        self.assertEqual(withdrawal.hash, "22" * 32)
        self.assertEqual(
            list(
                task.base_task.tx_hashes.order_by("version").values_list("hash", flat=True)
            ),
            ["11" * 32, "22" * 32],
        )
        self.assertTrue(
            signer_backend.sign_bitcoin_transaction.call_args.kwargs.get("replaceable")
        )
        send_raw_transaction_mock.assert_called_once_with("signed-new-payload")

    @patch("bitcoin.fee_bump.get_signer_backend")
    @patch(
        "bitcoin.fee_bump.BitcoinRpcClient.send_raw_transaction",
        side_effect=BitcoinRpcError(
            "Bitcoin RPC error (sendrawtransaction): txn-mempool-conflict"
        ),
    )
    @patch(
        "bitcoin.fee_bump.BitcoinRpcClient.estimate_smart_fee",
        return_value=Decimal("0.0002"),
    )
    @patch("bitcoin.fee_bump.BitcoinRpcClient.get_raw_transaction")
    def test_fee_bump_service_keeps_current_hash_when_broadcast_result_is_ambiguous(
        self,
        get_raw_transaction_mock,
        _estimate_fee_mock,
        _send_raw_transaction_mock,
        get_signer_backend_mock,
    ):
        from bitcoin.fee_bump import BitcoinFeeBumpService

        withdrawal, task = self._create_pending_withdrawal(tx_hash="33" * 32)

        def raw_tx_side_effect(tx_hash: str):
            if tx_hash == "aa" * 32:
                return {
                    "txid": tx_hash,
                    "confirmations": 12,
                    "vout": [
                        {
                            "n": 0,
                            "value": "0.02",
                            "scriptPubKey": {"hex": "76a914"},
                        }
                    ],
                }
            return None

        get_raw_transaction_mock.side_effect = raw_tx_side_effect
        signer_backend = SimpleNamespace(
            sign_bitcoin_transaction=Mock(
                return_value=SimpleNamespace(
                    txid="44" * 32,
                    signed_payload="signed-ambiguous-payload",
                )
            )
        )
        get_signer_backend_mock.return_value = signer_backend

        with self.assertRaisesMessage(ValueError, "txn-mempool-conflict"):
            BitcoinFeeBumpService.bump_withdrawal(
                withdrawal_id=withdrawal.pk,
                approval_context=build_admin_approval_context(
                    source="test_bitcoin_fee_bump"
                ),
            )

        withdrawal.refresh_from_db()
        task.refresh_from_db()
        task.base_task.refresh_from_db()
        self.assertEqual(task.base_task.tx_hash, "33" * 32)
        self.assertEqual(task.signed_payload, self._build_signed_payload(replaceable=True))
        self.assertEqual(task.fee_satoshi, 100)
        self.assertEqual(withdrawal.hash, "33" * 32)
        self.assertEqual(task.base_task.tx_hashes.count(), 0)

    @patch("bitcoin.models.BitcoinRpcClient.send_raw_transaction")
    def test_stale_broadcast_conflict_does_not_finalize_replaced_task(
        self,
        send_raw_transaction_mock,
    ):
        send_raw_transaction_mock.side_effect = BitcoinRpcError(
            "Bitcoin RPC error (sendrawtransaction): txn-mempool-conflict"
        )
        _withdrawal, task = self._create_pending_withdrawal(tx_hash="55" * 32)
        stale_task = BitcoinBroadcastTask.objects.select_related("base_task").get(
            pk=task.pk
        )
        _ = stale_task.base_task.tx_hash

        task.base_task.create_initial_tx_hash()
        task.base_task.append_tx_hash("66" * 32)
        BitcoinBroadcastTask.objects.filter(pk=task.pk).update(
            signed_payload="signed-replaced-payload",
            fee_satoshi=999,
        )

        stale_task.broadcast()

        task.refresh_from_db()
        task.base_task.refresh_from_db()
        self.assertEqual(task.base_task.tx_hash, "66" * 32)
        self.assertEqual(task.base_task.result, BroadcastTaskResult.UNKNOWN)
        self.assertEqual(task.base_task.stage, BroadcastTaskStage.PENDING_CHAIN)
