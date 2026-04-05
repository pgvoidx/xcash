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
from deposits.models import DepositAddress
from projects.models import Project
from projects.models import RecipientAddress
from users.models import Customer
from users.models import User

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
