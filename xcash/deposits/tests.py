import unittest
from contextlib import nullcontext
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock
from unittest.mock import PropertyMock
from unittest.mock import patch

from django.test import SimpleTestCase
from django.test import TestCase
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIRequestFactory
from rest_framework.test import force_authenticate
from web3 import Web3

from chains.models import Address
from chains.models import AddressUsage
from chains.models import BroadcastTask
from chains.models import Chain
from chains.models import ChainType
from chains.models import OnchainTransfer
from chains.models import TransferStatus
from chains.models import TransferType
from chains.models import Wallet
from currencies.models import Crypto
from currencies.models import ChainToken
from deposits.models import Deposit
from deposits.models import DepositAddress
from deposits.models import DepositCollection
from deposits.models import DepositStatus
from deposits.models import GasRecharge
from deposits.service import DepositService
from deposits.tasks import gather_deposits
from evm.models import EvmBroadcastTask
from projects.models import Project
from projects.models import RecipientAddress
from projects.models import RecipientAddressUsage
from users.models import Customer
from users.models import User
from common.error_codes import ErrorCode
from deposits.viewsets import DepositViewSet


class DepositServiceCoreTests(TestCase):
    """DepositService 核心逻辑的单元测试。"""

    # -- 状态机幂等性 --

    @patch("deposits.service.Deposit.objects")
    def test_confirm_deposit_idempotent_when_already_completed(
        self, deposit_objects_mock
    ):
        # 已完成的 deposit 重复 confirm 不应抛异常，也不应重复发 webhook。
        deposit = SimpleNamespace(
            pk=1, status=DepositStatus.COMPLETED, refresh_from_db=Mock()
        )
        # 不抛异常即通过
        DepositService.confirm_deposit(deposit)

    @patch("deposits.service.Deposit.objects")
    def test_drop_deposit_idempotent_when_already_deleted(self, deposit_objects_mock):
        # 已删除的 deposit 重复 drop 不应抛异常。
        deposit_objects_mock.select_for_update.return_value.filter.return_value.exists.return_value = (
            False
        )
        deposit = SimpleNamespace(pk=1)
        DepositService.drop_deposit(deposit)

    @patch("deposits.service.Deposit.objects")
    def test_drop_deposit_rejects_non_confirming_status(self, deposit_objects_mock):
        # 非 CONFIRMING 状态（如 COMPLETED）调用 drop 应抛异常。
        from deposits.exceptions import DepositStatusError

        deposit = SimpleNamespace(pk=1, status=DepositStatus.COMPLETED)
        deposit.refresh_from_db = Mock()
        deposit.delete = Mock()
        deposit_objects_mock.select_for_update.return_value.filter.return_value.exists.return_value = (
            True
        )
        with self.assertRaises(DepositStatusError):
            DepositService.drop_deposit(deposit)

    # -- _should_collect 阈值判断 --

    def test_should_collect_triggers_by_time_deadline(self):
        # 金额低于门槛但超过 gather_period 时间的充币应触发归集。
        chain = SimpleNamespace(type=ChainType.EVM, code="eth")
        crypto = SimpleNamespace(
            symbol="USDT",
            get_decimals=Mock(return_value=6),
            price=Mock(return_value=Decimal("1")),
        )
        project = SimpleNamespace(gather_worth=Decimal("100"), gather_period=3)
        customer = SimpleNamespace(project=project)
        transfer = SimpleNamespace(chain=chain, crypto=crypto)
        deposit = SimpleNamespace(
            customer=customer,
            transfer=transfer,
            # 4 天前创建，超过 gather_period=3
            created_at=timezone.now() - timedelta(days=4),
        )

        # 0.5 USDT，远低于 100 USD 门槛，但时间已过期
        should = DepositService._should_collect(deposit, Decimal("0.5"))
        self.assertTrue(should)

    def test_should_collect_fallback_on_missing_price(self):
        # 缺少价格时 worth 回退到 gather_worth，强制触发归集。
        chain = SimpleNamespace(type=ChainType.EVM, code="eth")
        crypto = SimpleNamespace(
            symbol="UNKNOWN",
            get_decimals=Mock(return_value=18),
            price=Mock(side_effect=KeyError("USD")),
        )
        project = SimpleNamespace(gather_worth=Decimal("10"), gather_period=365)
        customer = SimpleNamespace(project=project)
        transfer = SimpleNamespace(chain=chain, crypto=crypto)
        deposit = SimpleNamespace(
            customer=customer,
            transfer=transfer,
            created_at=timezone.now(),
        )

        should = DepositService._should_collect(deposit, Decimal("1"))
        self.assertTrue(should)

    def test_should_collect_above_threshold_immediately(self):
        # 金额达到门槛时应立即触发归集，无需等待 deadline。
        crypto = SimpleNamespace(
            symbol="USDT", price=Mock(return_value=Decimal("1")),
        )
        project = SimpleNamespace(gather_worth=Decimal("100"), gather_period=30)
        deposit = SimpleNamespace(
            customer=SimpleNamespace(project=project),
            transfer=SimpleNamespace(crypto=crypto),
            created_at=timezone.now(),  # 刚创建，远未到 deadline
        )
        # $100 恰好 == 门槛 → 归集
        self.assertTrue(DepositService._should_collect(deposit, Decimal("100")))
        # $100.01 略高于门槛 → 归集
        self.assertTrue(DepositService._should_collect(deposit, Decimal("100.01")))

    def test_should_collect_below_threshold_and_not_expired_skips(self):
        # 金额低于门槛且未到 deadline → 跳过归集。
        crypto = SimpleNamespace(
            symbol="USDT", price=Mock(return_value=Decimal("1")),
        )
        project = SimpleNamespace(gather_worth=Decimal("100"), gather_period=30)
        deposit = SimpleNamespace(
            customer=SimpleNamespace(project=project),
            transfer=SimpleNamespace(crypto=crypto),
            created_at=timezone.now(),  # 刚创建
        )
        # $99.99 略低于 $100 门槛 → 不归集
        self.assertFalse(DepositService._should_collect(deposit, Decimal("99.99")))
        # $0.01 极低 → 不归集
        self.assertFalse(DepositService._should_collect(deposit, Decimal("0.01")))

    def test_should_collect_multi_deposit_sum_crosses_threshold(self):
        # 单笔低于门槛，但多笔合并总额超过门槛时应触发归集。
        # 模拟 _calculate_collection_amount 返回的合并金额。
        crypto = SimpleNamespace(
            symbol="ETH", price=Mock(return_value=Decimal("2000")),
        )
        project = SimpleNamespace(gather_worth=Decimal("100"), gather_period=30)
        deposit = SimpleNamespace(
            customer=SimpleNamespace(project=project),
            transfer=SimpleNamespace(crypto=crypto),
            created_at=timezone.now(),
        )
        # 单笔 0.04 ETH = $80 < $100 → 不归集
        self.assertFalse(DepositService._should_collect(deposit, Decimal("0.04")))
        # 合并 0.04 + 0.02 = 0.06 ETH = $120 > $100 → 归集
        self.assertTrue(DepositService._should_collect(deposit, Decimal("0.06")))

    # -- collect_deposit 防御分支 --

    @patch("deposits.service.AdapterFactory.get_adapter")
    @patch("deposits.service.DepositAddress.objects.get")
    @patch("deposits.service.RecipientAddress.objects.filter")
    @patch.object(DepositService, "_snapshot_collectible_group")
    def test_collect_deposit_returns_false_when_no_recipient(
        self,
        lock_group_mock,
        recipient_filter_mock,
        deposit_address_get_mock,
        adapter_factory_mock,
    ):
        # 项目未配置归集收款地址时应直接返回 False。
        recipient_filter_mock.return_value.order_by.return_value.first.return_value = (
            None
        )

        chain = SimpleNamespace(type=ChainType.EVM, code="eth")
        crypto = SimpleNamespace(
            symbol="USDT",
            is_native=False,
            get_decimals=Mock(return_value=6),
        )
        project = SimpleNamespace(id=1)
        customer = SimpleNamespace(project=project)
        transfer = SimpleNamespace(chain=chain, crypto=crypto)
        deposit = SimpleNamespace(
            id=1,
            pk=1,
            status=DepositStatus.COMPLETED,
            collection_id=None,
            customer=customer,
            customer_id=1,
            transfer=transfer,
        )
        lock_group_mock.return_value = [deposit]

        collected = DepositService.collect_deposit(deposit)
        self.assertFalse(collected)
        adapter_factory_mock.assert_not_called()

    @patch("deposits.service.AdapterFactory.get_adapter")
    @patch("deposits.service.DepositAddress.objects.get")
    @patch("deposits.service.RecipientAddress.objects.filter")
    @patch.object(DepositService, "_snapshot_collectible_group")
    def test_collect_deposit_returns_false_when_zero_balance(
        self,
        lock_group_mock,
        recipient_filter_mock,
        deposit_address_get_mock,
        adapter_factory_mock,
    ):
        # 链上余额为 0 时应直接返回 False。
        recipient_filter_mock.return_value.order_by.return_value.first.return_value = (
            SimpleNamespace(address="0xrecipient")
        )
        chain = SimpleNamespace(type=ChainType.EVM, code="eth")
        crypto = SimpleNamespace(
            symbol="USDT",
            is_native=False,
            get_decimals=Mock(return_value=6),
        )
        project = SimpleNamespace(id=1)
        customer = SimpleNamespace(project=project)
        transfer = SimpleNamespace(chain=chain, crypto=crypto)
        deposit = SimpleNamespace(
            id=1,
            pk=1,
            status=DepositStatus.COMPLETED,
            collection_id=None,
            customer=customer,
            customer_id=1,
            transfer=transfer,
        )
        lock_group_mock.return_value = [deposit]
        deposit_address_get_mock.return_value = SimpleNamespace(
            address=SimpleNamespace(address="0xdeposit")
        )
        adapter_factory_mock.return_value = SimpleNamespace(
            get_balance=Mock(return_value=0)
        )

        collected = DepositService.collect_deposit(deposit)
        self.assertFalse(collected)

    @patch("deposits.service.DepositCollection.objects.create", side_effect=RuntimeError("collection insert failed"))
    @patch("deposits.service.AdapterFactory.get_adapter")
    @patch("deposits.service.RecipientAddress.objects.filter")
    def test_collect_deposit_rolls_back_task_creation_when_collection_insert_fails(
        self,
        recipient_filter_mock,
        adapter_factory_mock,
        _collection_create_mock,
    ):
        project = Project.objects.create(
            name="DemoAtomicCollection",
            wallet=Wallet.objects.create(),
            gather_worth=Decimal("0.1"),
        )
        customer = Customer.objects.create(project=project, uid="customer-atomic")
        native = Crypto.objects.create(
            name="Ethereum Atomic Native",
            symbol="ETHATOMIC",
            coingecko_id="ethereum-atomic-native",
        )
        chain = Chain.objects.create(
            name="Ethereum Atomic",
            code="eth-atomic",
            type=ChainType.EVM,
            native_coin=native,
            chain_id=205,
            rpc="http://localhost:8545",
            active=True,
        )
        deposit_addr = Address.objects.create(
            wallet=project.wallet,
            chain_type=ChainType.EVM,
            usage=AddressUsage.Deposit,
            bip44_account=0,
            address_index=0,
            address="0x00000000000000000000000000000000000005A1",
        )
        DepositAddress.objects.create(
            customer=customer,
            chain_type=chain.type,
            address=deposit_addr,
        )
        recipient_filter_mock.return_value.order_by.return_value.first.return_value = (
            SimpleNamespace(
                address=Web3.to_checksum_address(
                    "0x00000000000000000000000000000000000005b1"
                )
            )
        )
        adapter_factory_mock.return_value = SimpleNamespace(
            get_balance=Mock(return_value=10**18)
        )
        transfer = OnchainTransfer.objects.create(
            chain=chain,
            block=1,
            hash="0x" + "5a" * 32,
            event_id="native:atomic",
            crypto=native,
            from_address="0x0000000000000000000000000000000000000501",
            to_address=deposit_addr.address,
            value="1000000000000000000",
            amount=Decimal("1"),
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

        collected = DepositService.collect_deposit(deposit)

        self.assertFalse(collected)
        deposit.refresh_from_db()
        self.assertIsNone(deposit.collection_id)
        self.assertEqual(DepositCollection.objects.count(), 0)
        self.assertEqual(
            BroadcastTask.objects.filter(
                transfer_type=TransferType.DepositCollection
            ).count(),
            0,
        )
        self.assertEqual(EvmBroadcastTask.objects.count(), 0)

    # -- content property null 保护 --

    def test_content_property_handles_null_customer(self):
        # customer 为 None 时 content 不应抛 AttributeError。
        transfer = SimpleNamespace(
            chain=SimpleNamespace(code="eth"),
            block=100,
            hash="0x" + "a" * 64,
            crypto=SimpleNamespace(symbol="USDT"),
            amount=Decimal("1.5"),
        )

        # 直接调用 Deposit.content.fget 绕过 Django 描述符
        fake_deposit = SimpleNamespace(
            sys_no="DXC-test",
            customer=None,
            transfer=transfer,
            status=DepositStatus.CONFIRMING,
        )
        content = Deposit.content.fget(fake_deposit)

        self.assertIsNone(content["data"]["uid"])
        self.assertEqual(content["data"]["sys_no"], "DXC-test")
        self.assertEqual(content["data"]["chain"], "eth")



class DepositServiceDecimalsTests(TestCase):
    def test_inactive_placeholder_transfer_does_not_create_deposit(self):
        # inactive 占位币允许进入余额统计，但不能进入商户充值业务流。
        transfer = SimpleNamespace(
            chain=SimpleNamespace(type=ChainType.EVM),
            crypto=SimpleNamespace(active=False),
        )

        with patch(
            "deposits.service.DepositAddress.objects.get"
        ) as deposit_address_get_mock:
            created = DepositService.try_create_deposit(transfer)

        self.assertFalse(created)
        deposit_address_get_mock.assert_not_called()

    @patch.object(DepositService, "_lock_pending_group_ids", return_value={1})
    @patch("deposits.service.AdapterFactory.get_adapter")
    @patch("deposits.service.DepositAddress.objects.get")
    @patch("deposits.service.RecipientAddress.objects.filter")
    @patch.object(DepositService, "_snapshot_collectible_group")
    @patch("deposits.service.DepositCollection.objects")
    @patch("deposits.service.Deposit.objects.filter")
    @patch("evm.models.EvmBroadcastTask.schedule_transfer")
    def test_collect_deposit_uses_chain_specific_crypto_decimals(
        self,
        schedule_transfer_mock,
        deposit_filter_mock,
        collection_objects_mock,
        lock_group_mock,
        recipient_filter_mock,
        deposit_address_get_mock,
        adapter_factory_mock,
        _lock_ids_mock,
    ):
        # 覆盖精度场景下，归集发送金额必须按链特定精度换算，而不是 Crypto 默认精度。
        recipient_filter_mock.return_value.order_by.return_value.first.return_value = (
            SimpleNamespace(
                address=Web3.to_checksum_address(
                    "0x00000000000000000000000000000000000000aa"
                )
            )
        )
        collection_objects_mock.create.return_value = SimpleNamespace(pk=999)
        deposit_filter_mock.return_value.update = Mock()
        collection_objects_mock.filter.return_value.update = Mock()
        schedule_transfer_mock.return_value = SimpleNamespace(base_task=Mock())

        chain = SimpleNamespace(
            type=ChainType.EVM,
            code="bsc",
            native_coin=SimpleNamespace(symbol="BNB"),
        )
        crypto = SimpleNamespace(
            symbol="USDT",
            decimals=6,
            is_native=False,
            get_decimals=Mock(return_value=18),
            price=Mock(return_value=Decimal("1")),
        )
        project = SimpleNamespace(id=1, gather_worth=Decimal("0.1"))
        customer = SimpleNamespace(project=project)
        transfer = SimpleNamespace(chain=chain, crypto=crypto, amount=Decimal("1"))
        deposit = SimpleNamespace(
            id=1,
            pk=1,
            status="completed",
            collection_id=None,
            customer=customer,
            customer_id=1,
            transfer=transfer,
            created_at=timezone.now(),
            save=Mock(),
        )
        lock_group_mock.return_value = [deposit]

        fake_addr = SimpleNamespace(
            address="0xdeposit",
            send_crypto=Mock(return_value="0x" + "a" * 64),
        )
        deposit_address_get_mock.return_value = SimpleNamespace(address=fake_addr)

        adapter = SimpleNamespace(get_balance=Mock(return_value=10**18))
        adapter_factory_mock.return_value = adapter

        collected = DepositService.collect_deposit(deposit)

        self.assertTrue(collected)
        schedule_transfer_mock.assert_called_once_with(
            crypto=crypto,
            chain=chain,
            address=fake_addr,
            to=Web3.to_checksum_address("0x00000000000000000000000000000000000000aa"),
            value_raw=10**18,
            transfer_type=TransferType.DepositCollection,
        )

    @patch.object(DepositService, "_lock_pending_group_ids", return_value={2})
    @patch("deposits.service.db_transaction.atomic", return_value=nullcontext())
    @patch("evm.models.EvmBroadcastTask.schedule_transfer", side_effect=RuntimeError("broadcast task create failed"))
    @patch("deposits.service.AdapterFactory.get_adapter")
    @patch("deposits.service.DepositAddress.objects.get")
    @patch("deposits.service.RecipientAddress.objects.filter")
    @patch.object(DepositService, "_snapshot_collectible_group")
    @patch("deposits.service.DepositCollection.objects.create")
    @patch("deposits.service.Deposit.objects.filter")
    def test_collect_deposit_failure_keeps_relations_unbound_before_commit(
        self,
        deposit_filter_mock,
        collection_create_mock,
        lock_group_mock,
        recipient_filter_mock,
        deposit_address_get_mock,
        adapter_factory_mock,
        _schedule_transfer_mock,
        _atomic_mock,
        _lock_ids_mock,
    ):
        # 创建 BroadcastTask 失败时，不应提前创建 collection 或绑定 deposit 关系。
        recipient_filter_mock.return_value.order_by.return_value.first.return_value = (
            SimpleNamespace(address="0xrecipient")
        )
        deposit_filter_mock.return_value.update = Mock()

        chain = SimpleNamespace(
            type=ChainType.EVM,
            code="eth",
            native_coin=SimpleNamespace(symbol="ETH"),
        )
        crypto = SimpleNamespace(
            symbol="USDT",
            is_native=False,
            get_decimals=Mock(return_value=6),
            price=Mock(return_value=Decimal("1")),
        )
        project = SimpleNamespace(id=1, gather_worth=Decimal("0.1"))
        customer = SimpleNamespace(project=project)
        transfer = SimpleNamespace(chain=chain, crypto=crypto, amount=Decimal("1"))
        deposit = SimpleNamespace(
            id=2,
            pk=2,
            status=DepositStatus.COMPLETED,
            collection_id=None,
            customer=customer,
            customer_id=1,
            transfer=transfer,
            created_at=timezone.now(),
            save=Mock(),
        )
        lock_group_mock.return_value = [deposit]
        fake_addr = SimpleNamespace(
            address="0xdeposit",
            send_crypto=Mock(side_effect=RuntimeError("broadcast failed")),
        )
        deposit_address_get_mock.return_value = SimpleNamespace(address=fake_addr)
        adapter_factory_mock.return_value = SimpleNamespace(
            get_balance=Mock(return_value=10**6)
        )

        collected = DepositService.collect_deposit(deposit)

        self.assertFalse(collected)
        collection_create_mock.assert_not_called()
        deposit_filter_mock.return_value.update.assert_not_called()

    def test_should_collect_uses_chain_specific_crypto_decimals(self):
        # 链特定精度为 18、默认精度为 6 时，0.5 个代币不应被误判成巨额资产。
        chain = SimpleNamespace(type=ChainType.EVM, code="bsc")
        crypto = SimpleNamespace(
            symbol="USDT",
            decimals=6,
            get_decimals=Mock(return_value=18),
            price=Mock(return_value=Decimal("1")),
        )
        project = SimpleNamespace(gather_worth=Decimal("1"), gather_period=7)
        customer = SimpleNamespace(project=project)
        transfer = SimpleNamespace(chain=chain, crypto=crypto)
        deposit = SimpleNamespace(
            customer=customer,
            transfer=transfer,
            created_at=timezone.now() - timedelta(days=1),
        )

        should_collect = DepositService._should_collect(deposit, Decimal("0.5"))

        self.assertFalse(should_collect)

    def test_collection_amount_is_sum_of_deposits(self):
        # 归集金额 = 分组内充值金额之和。
        deposits = [
            SimpleNamespace(transfer=SimpleNamespace(amount=Decimal("1.5"))),
            SimpleNamespace(transfer=SimpleNamespace(amount=Decimal("2.3"))),
            SimpleNamespace(transfer=SimpleNamespace(amount=Decimal("0.7"))),
        ]
        total = DepositService._calculate_collection_amount(deposits)
        self.assertEqual(total, Decimal("4.5"))


class GasRechargeServiceTests(SimpleTestCase):
    """GasRechargeService.request_recharge 的单元测试。

    验证两个核心行为：
    1. 无 pending recharge 时正常发起 Vault → 地址的补充交易并创建 GasRecharge 记录。
    2. 已有 pending recharge（stage=QUEUED 且 result=UNKNOWN）时幂等跳过。
    """

    @staticmethod
    def _make_deposit_address():
        """构造最小可用的 DepositAddress mock。"""
        native_coin = SimpleNamespace(symbol="ETH")
        chain = SimpleNamespace(
            type=ChainType.EVM, code="eth",
            native_coin=native_coin,
            base_transfer_gas=50_000,
            erc20_transfer_gas=100_000,
        )
        vault_addr = SimpleNamespace(address="0xvault")
        wallet = SimpleNamespace(get_address=Mock(return_value=vault_addr))
        project = SimpleNamespace(wallet=wallet)
        customer = SimpleNamespace(project=project)
        deposit_address = SimpleNamespace(
            pk=42, id=42,
            customer=customer,
            address=SimpleNamespace(address="0xdeposit"),
        )
        return deposit_address, chain, vault_addr

    @patch("deposits.service.GasRecharge.objects.create")
    @patch("deposits.service.GasRecharge.objects.filter")
    @patch("evm.models.EvmBroadcastTask.schedule_transfer")
    def test_request_recharge_creates_task_and_gas_recharge_when_no_pending(
        self, schedule_mock, gr_filter_mock, gr_create_mock,
    ):
        from deposits.service import GasRechargeService

        gr_filter_mock.return_value.exists.return_value = False
        deposit_address, chain, vault_addr = self._make_deposit_address()
        base_task_sentinel = SimpleNamespace(pk=1001)
        schedule_mock.return_value = SimpleNamespace(base_task=base_task_sentinel)

        erc20_gas_cost = 10 * 100_000
        result = GasRechargeService.request_recharge(
            deposit_address=deposit_address,
            chain=chain,
            erc20_gas_cost=erc20_gas_cost,
        )
        self.assertTrue(result)
        schedule_mock.assert_called_once()
        call_kwargs = schedule_mock.call_args[1]
        # 补 gas 金额 = 10 * erc20_gas_cost = 10_000_000
        self.assertEqual(call_kwargs["value_raw"], 10 * erc20_gas_cost)
        self.assertEqual(call_kwargs["transfer_type"], TransferType.GasRecharge)
        self.assertEqual(call_kwargs["address"], vault_addr)
        self.assertEqual(call_kwargs["to"], "0xdeposit")
        gr_create_mock.assert_called_once_with(
            deposit_address=deposit_address,
            broadcast_task=base_task_sentinel,
        )

    @patch("deposits.service.GasRecharge.objects.create")
    @patch("deposits.service.GasRecharge.objects.filter")
    @patch("evm.models.EvmBroadcastTask.schedule_transfer")
    def test_request_recharge_is_idempotent_when_pending_exists(
        self, schedule_mock, gr_filter_mock, gr_create_mock,
    ):
        from deposits.service import GasRechargeService

        # 已有 pending GasRecharge：不应重复发起新交易，也不应创建新记录。
        gr_filter_mock.return_value.exists.return_value = True
        deposit_address, chain, _ = self._make_deposit_address()

        result = GasRechargeService.request_recharge(
            deposit_address=deposit_address,
            chain=chain,
            erc20_gas_cost=1_000_000,
        )
        self.assertTrue(result)
        schedule_mock.assert_not_called()
        gr_create_mock.assert_not_called()

    @patch("deposits.service.GasRecharge.objects.create")
    @patch("deposits.service.GasRecharge.objects.filter")
    @patch("evm.models.EvmBroadcastTask.schedule_transfer")
    def test_request_recharge_returns_false_when_gas_cost_zero(
        self, schedule_mock, gr_filter_mock, gr_create_mock,
    ):
        from deposits.service import GasRechargeService

        # gas 成本非法（<=0）：不应发起交易，返回 False 由上层决定如何处理。
        deposit_address, chain, _ = self._make_deposit_address()

        result = GasRechargeService.request_recharge(
            deposit_address=deposit_address,
            chain=chain,
            erc20_gas_cost=0,
        )
        self.assertFalse(result)
        schedule_mock.assert_not_called()
        gr_create_mock.assert_not_called()


class GasRechargeServiceIdempotencyDbTests(TestCase):
    """真实落库验证幂等：pending GasRecharge 存在时禁止重复创建第二条。

    历史 bug：BroadcastTask.tx_hash 是 HashField(null=True)，默认存 NULL；
    但幂等过滤用的是 tx_hash=""，永远匹配不到，导致每次 pre-flight 都会
    重新调度 Vault → deposit 地址的 gas 补充，堆积冗余记录、浪费 vault 资金。

    之前的 SimpleTestCase 版本 mock 了 .exists() 的返回值，绕开了真实 ORM
    查询，看起来幂等但实际失效；本用例必须走真实 DB。
    """

    @patch("chains.models.Wallet.get_address")
    @patch("evm.models.EvmBroadcastTask.schedule_transfer")
    def test_request_recharge_is_idempotent_with_real_pending_record(
        self, schedule_mock, get_address_mock,
    ):
        from deposits.service import GasRechargeService

        project = Project.objects.create(
            name="DemoIdem",
            wallet=Wallet.objects.create(),
        )
        customer = Customer.objects.create(project=project, uid="customer-idem")
        native = Crypto.objects.create(
            name="Ethereum Idem",
            symbol="ETHID",
            coingecko_id="ethereum-idem",
        )
        chain = Chain.objects.create(
            name="EthereumIdem",
            code="eth-idem",
            type=ChainType.EVM,
            native_coin=native,
            chain_id=301,
            rpc="http://localhost:8545",
            active=True,
        )
        addr = Address.objects.create(
            wallet=project.wallet,
            chain_type=ChainType.EVM,
            usage=AddressUsage.Deposit,
            bip44_account=0,
            address_index=0,
            address="0x0000000000000000000000000000000000000091",
        )
        deposit_address = DepositAddress.objects.create(
            customer=customer,
            chain_type=chain.type,
            address=addr,
        )
        # 已存在的 pending 广播任务：stage=QUEUED（默认）且 tx_hash 保持 NULL 默认。
        # 关联的 GasRecharge.recharged_at 也保持 NULL，精确匹配"未广播未到账"语义。
        pending_task = BroadcastTask.objects.create(
            chain=chain,
            address=addr,
            transfer_type=TransferType.GasRecharge,
            crypto=native,
            amount=Decimal("1"),
        )
        GasRecharge.objects.create(
            deposit_address=deposit_address,
            broadcast_task=pending_task,
        )

        result = GasRechargeService.request_recharge(
            deposit_address=deposit_address,
            chain=chain,
            erc20_gas_cost=100_000,
        )

        self.assertTrue(result)
        # 幂等的核心断言：不产生第二条 GasRecharge；
        # 如果过滤失效（历史 tx_hash="" 写法），这里会出现 2 条。
        self.assertEqual(GasRecharge.objects.count(), 1)
        # 幂等命中时不应再触达 Vault 地址派生与广播调度。
        schedule_mock.assert_not_called()
        get_address_mock.assert_not_called()


class DepositTransferRematchTests(TestCase):
    @patch("deposits.service.WebhookService.create_event")
    def test_confirm_deposit_emits_completed_webhook(self, create_event_mock):
        # Deposit 显式确认后必须直接发完成通知，不再依赖 post_save signal。
        project = Project.objects.create(
            name="DemoConfirm",
            wallet=Wallet.objects.create(),
            pre_notify=True,
        )
        customer = Customer.objects.create(project=project, uid="customer-confirm")
        chain = Chain.objects.create(
            name="EthereumConfirm",
            code="eth-confirm",
            type=ChainType.EVM,
            native_coin=Crypto.objects.create(
                name="Ethereum Confirm",
                symbol="ETHC",
                coingecko_id="ethereum",
            ),
            chain_id=101,
            rpc="http://localhost:8545",
            active=True,
        )
        addr = Address.objects.create(
            wallet=project.wallet,
            chain_type=ChainType.EVM,
            usage=AddressUsage.Deposit,
            bip44_account=0,
            address_index=0,
            address="0x0000000000000000000000000000000000000011",
        )
        DepositAddress.objects.create(
            customer=customer,
            chain_type=chain.type,
            address=addr,
        )
        transfer = OnchainTransfer.objects.create(
            chain=chain,
            block=1,
            hash="0x" + "4" * 64,
            event_id="erc20:4",
            crypto=Crypto.objects.create(
                name="Tether Confirm",
                symbol="USDTC",
                coingecko_id="tether",
            ),
            from_address="0x0000000000000000000000000000000000000002",
            to_address=addr.address,
            value="1",
            amount=Decimal("1"),
            timestamp=1,
            datetime=timezone.now(),
            status=TransferStatus.CONFIRMED,
            type=TransferType.Deposit,
        )
        created = DepositService.try_create_deposit(transfer)
        self.assertTrue(created)
        create_event_mock.reset_mock()

        DepositService.confirm_deposit(transfer.deposit)

        create_event_mock.assert_called_once()
        payload = create_event_mock.call_args.kwargs["payload"]
        self.assertEqual(payload["type"], "deposit")
        self.assertEqual(payload["data"]["sys_no"], transfer.deposit.sys_no)
        self.assertEqual(payload["data"]["uid"], customer.uid)
        self.assertTrue(payload["data"]["confirmed"])

    @patch("evm.models.EvmBroadcastTask.schedule_transfer")
    @patch("deposits.service.AdapterFactory.get_adapter")
    @patch("deposits.service.RecipientAddress.objects.filter")
    def test_collect_deposit_marks_same_group_records_with_one_collection_hash(
        self,
        recipient_filter_mock,
        adapter_factory_mock,
        schedule_transfer_mock,
    ):
        # 同一客户在同链同币下多笔完成充币应共享一笔归集交易，不能重复发起第二笔归集。
        project = Project.objects.create(
            name="DemoGroupCollect",
            wallet=Wallet.objects.create(),
            gather_worth=Decimal("0.1"),
        )
        customer = Customer.objects.create(
            project=project, uid="customer-group-collect"
        )
        native = Crypto.objects.create(
            name="Ethereum Collect Native",
            symbol="ETHGC",
            coingecko_id="ethereum-group-collect-native",
        )
        crypto = Crypto.objects.create(
            name="Tether Group Collect",
            symbol="USDTGC",
            prices={"USD": "1"},
            coingecko_id="tether-group-collect",
            decimals=6,
        )
        chain = Chain.objects.create(
            name="Ethereum Group Collect",
            code="eth-group-collect",
            type=ChainType.EVM,
            native_coin=native,
            chain_id=201,
            rpc="http://localhost:8545",
            active=True,
        )
        addr = Address.objects.create(
            wallet=project.wallet,
            chain_type=ChainType.EVM,
            usage=AddressUsage.Deposit,
            bip44_account=0,
            address_index=0,
            address="0x00000000000000000000000000000000000000C1",
        )
        DepositAddress.objects.create(
            customer=customer,
            chain_type=chain.type,
            address=addr,
        )
        recipient_filter_mock.return_value.order_by.return_value.first.return_value = (
            SimpleNamespace(address="0x00000000000000000000000000000000000000D1")
        )
        adapter_factory_mock.return_value = SimpleNamespace(
            get_balance=Mock(return_value=10**6)
        )
        base_task = BroadcastTask.objects.create(
            chain=chain,
            address=addr,
            transfer_type=TransferType.DepositCollection,
            crypto=crypto,
            recipient=Web3.to_checksum_address(
                "0x00000000000000000000000000000000000000d1"
            ),
            amount=Decimal("3"),
        )
        schedule_transfer_mock.return_value = SimpleNamespace(base_task=base_task)
        fake_addr = SimpleNamespace(
            address=addr.address,
            send_crypto=Mock(return_value="0x" + "c" * 64),
        )

        with patch(
            "deposits.service.DepositAddress.objects.get",
            return_value=SimpleNamespace(address=fake_addr),
        ):
            transfer1 = OnchainTransfer.objects.create(
                chain=chain,
                block=1,
                hash="0x" + "6" * 64,
                event_id="erc20:6",
                crypto=crypto,
                from_address="0x0000000000000000000000000000000000000101",
                to_address=addr.address,
                value="1",
                amount=Decimal("1"),
                timestamp=1,
                datetime=timezone.now(),
                status=TransferStatus.CONFIRMED,
                type=TransferType.Deposit,
            )
            transfer2 = OnchainTransfer.objects.create(
                chain=chain,
                block=2,
                hash="0x" + "7" * 64,
                event_id="erc20:7",
                crypto=crypto,
                from_address="0x0000000000000000000000000000000000000102",
                to_address=addr.address,
                value="2",
                amount=Decimal("2"),
                timestamp=2,
                datetime=timezone.now(),
                status=TransferStatus.CONFIRMED,
                type=TransferType.Deposit,
            )
            deposit1 = Deposit.objects.create(
                customer=customer,
                transfer=transfer1,
                status=DepositStatus.COMPLETED,
            )
            deposit2 = Deposit.objects.create(
                customer=customer,
                transfer=transfer2,
                status=DepositStatus.COMPLETED,
            )

            collected = DepositService.collect_deposit(deposit1)
            duplicate = DepositService.collect_deposit(deposit2)

        self.assertTrue(collected)
        self.assertFalse(duplicate)
        deposit1.refresh_from_db()
        deposit2.refresh_from_db()
        # 同组 Deposit 应指向同一个 DepositCollection，共享归集哈希
        self.assertIsNotNone(deposit1.collection_id)
        self.assertEqual(deposit1.collection_id, deposit2.collection_id)
        self.assertIsNone(deposit1.collection.collection_hash)
        self.assertEqual(deposit1.collection.broadcast_task, base_task)
        schedule_transfer_mock.assert_called_once()

    @patch("evm.models.EvmBroadcastTask.schedule_transfer")
    @patch("deposits.service.AdapterFactory.get_adapter")
    @patch("deposits.service.DepositAddress.objects.get")
    @patch("deposits.service.RecipientAddress.objects.filter")
    def test_multi_deposit_merges_into_single_collection(
        self,
        recipient_filter_mock,
        deposit_address_get_mock,
        adapter_factory_mock,
        schedule_transfer_mock,
    ):
        """
        同客户连续多笔充值在 prepare_collection 阶段应合并成一笔归集，
        value_raw = 充值总额（非余额），与链上实际余额解耦。
        """
        project = Project.objects.create(
            name="DemoMultiDepositCollect",
            wallet=Wallet.objects.create(),
            gather_worth=Decimal("0.1"),
        )
        customer = Customer.objects.create(
            project=project, uid="customer-multi-deposit-collect"
        )
        native = Crypto.objects.create(
            name="Ethereum MultiDepositCollect Native",
            symbol="ETHMDC",
            prices={"USD": "2000"},
            coingecko_id="ethereum-multi-deposit-collect-native",
        )
        chain = Chain.objects.create(
            name="Ethereum MultiDepositCollect",
            code="eth-multi-deposit-collect",
            type=ChainType.EVM,
            native_coin=native,
            chain_id=301,
            rpc="http://localhost:8545",
            active=True,
        )
        addr = Address.objects.create(
            wallet=project.wallet,
            chain_type=ChainType.EVM,
            usage=AddressUsage.Deposit,
            bip44_account=0,
            address_index=0,
            address="0x00000000000000000000000000000000000005C1",
        )
        da = DepositAddress.objects.create(
            customer=customer, chain_type=chain.type, address=addr,
        )
        recipient_filter_mock.return_value.order_by.return_value.first.return_value = (
            SimpleNamespace(address="0x00000000000000000000000000000000000005D1")
        )
        deposit_address_get_mock.return_value = da

        # 两笔充值：1 ETH + 2 ETH = 总计 3 ETH
        transfer1 = OnchainTransfer.objects.create(
            chain=chain, block=1, hash="0x" + "f1" * 32, event_id="native:mdc1",
            crypto=native,
            from_address="0x0000000000000000000000000000000000000501",
            to_address=addr.address,
            value="1", amount=Decimal("1"), timestamp=1,
            datetime=timezone.now(),
            status=TransferStatus.CONFIRMED, type=TransferType.Deposit,
        )
        transfer2 = OnchainTransfer.objects.create(
            chain=chain, block=2, hash="0x" + "f2" * 32, event_id="native:mdc2",
            crypto=native,
            from_address="0x0000000000000000000000000000000000000502",
            to_address=addr.address,
            value="2", amount=Decimal("2"), timestamp=2,
            datetime=timezone.now(),
            status=TransferStatus.CONFIRMED, type=TransferType.Deposit,
        )
        deposit1 = Deposit.objects.create(
            customer=customer, transfer=transfer1, status=DepositStatus.COMPLETED,
        )
        deposit2 = Deposit.objects.create(
            customer=customer, transfer=transfer2, status=DepositStatus.COMPLETED,
        )

        adapter_factory_mock.return_value = SimpleNamespace(
            get_balance=Mock(return_value=3 * 10**18)
        )
        collection_task = BroadcastTask.objects.create(
            chain=chain, address=addr,
            transfer_type=TransferType.DepositCollection,
            crypto=native,
            recipient=Web3.to_checksum_address(
                "0x00000000000000000000000000000000000005d1"
            ),
            amount=Decimal("3"),
        )
        schedule_transfer_mock.return_value = SimpleNamespace(base_task=collection_task)

        collected = DepositService.collect_deposit(deposit1)
        # 第二笔已被合入同一归集，再调用 collect_deposit 不应再建第二笔
        duplicate = DepositService.collect_deposit(deposit2)

        self.assertTrue(collected)
        self.assertFalse(duplicate)
        deposit1.refresh_from_db()
        deposit2.refresh_from_db()
        # 两笔充值共享同一个 DepositCollection
        self.assertIsNotNone(deposit1.collection_id)
        self.assertEqual(deposit1.collection_id, deposit2.collection_id)
        # 归集金额 = 1 + 2 = 3 ETH（非余额），value_raw = 3 * 10^18
        schedule_transfer_mock.assert_called_once()
        call_kwargs = schedule_transfer_mock.call_args[1]
        self.assertEqual(call_kwargs["value_raw"], 3 * 10**18)

    def test_confirm_collection_marks_same_hash_group_completed(self):
        # 同一归集哈希命中的多条充币记录在确认后要一起写入 collected_at。
        project = Project.objects.create(
            name="DemoGroupConfirm",
            wallet=Wallet.objects.create(),
        )
        customer = Customer.objects.create(
            project=project, uid="customer-group-confirm"
        )
        native = Crypto.objects.create(
            name="Ethereum Confirm Native",
            symbol="ETHGCC",
            coingecko_id="ethereum-group-confirm-native",
        )
        crypto = Crypto.objects.create(
            name="Tether Group Confirm",
            symbol="USDTGCC",
            coingecko_id="tether-group-confirm",
        )
        chain = Chain.objects.create(
            name="Ethereum Group Confirm",
            code="eth-group-confirm",
            type=ChainType.EVM,
            native_coin=native,
            chain_id=202,
            rpc="http://localhost:8545",
            active=True,
        )
        transfer1 = OnchainTransfer.objects.create(
            chain=chain,
            block=1,
            hash="0x" + "8" * 64,
            event_id="erc20:8",
            crypto=crypto,
            from_address="0x0000000000000000000000000000000000000201",
            to_address="0x0000000000000000000000000000000000000211",
            value="1",
            amount=Decimal("1"),
            timestamp=1,
            datetime=timezone.now(),
            status=TransferStatus.CONFIRMED,
            type=TransferType.Deposit,
        )
        transfer2 = OnchainTransfer.objects.create(
            chain=chain,
            block=2,
            hash="0x" + "9" * 64,
            event_id="erc20:9",
            crypto=crypto,
            from_address="0x0000000000000000000000000000000000000202",
            to_address="0x0000000000000000000000000000000000000211",
            value="2",
            amount=Decimal("2"),
            timestamp=2,
            datetime=timezone.now(),
            status=TransferStatus.CONFIRMED,
            type=TransferType.Deposit,
        )
        collection = DepositCollection.objects.create(collection_hash="0x" + "d" * 64)
        deposit1 = Deposit.objects.create(
            customer=customer,
            transfer=transfer1,
            status=DepositStatus.COMPLETED,
            collection=collection,
        )
        deposit2 = Deposit.objects.create(
            customer=customer,
            transfer=transfer2,
            status=DepositStatus.COMPLETED,
            collection=collection,
        )

        DepositService.confirm_collection(collection)

        collection.refresh_from_db()
        self.assertIsNotNone(collection.collected_at)
        # 同一 DepositCollection 下的所有充币记录均通过 collection.collected_at 反映归集完成
        deposit1.refresh_from_db()
        deposit2.refresh_from_db()
        self.assertEqual(deposit1.collection_id, collection.pk)
        self.assertEqual(deposit2.collection_id, collection.pk)

    def test_drop_collection_preserves_fixed_relations_and_clears_chain_observation(self):
        # 归集链上转账失效后，只清理链上观测字段，Deposit -> Collection / Collection -> BroadcastTask 关系保持不变。
        project = Project.objects.create(
            name="DemoDropCollection",
            wallet=Wallet.objects.create(),
        )
        customer = Customer.objects.create(
            project=project, uid="customer-drop-collection"
        )
        native = Crypto.objects.create(
            name="Ethereum Drop Collection Native",
            symbol="ETHDC",
            coingecko_id="ethereum-drop-collection-native",
        )
        crypto = Crypto.objects.create(
            name="Tether Drop Collection",
            symbol="USDTDC",
            coingecko_id="tether-drop-collection",
        )
        chain = Chain.objects.create(
            name="Ethereum Drop Collection",
            code="eth-drop-collection",
            type=ChainType.EVM,
            native_coin=native,
            chain_id=204,
            rpc="http://localhost:8545",
            active=True,
        )
        vault_addr = Address.objects.create(
            wallet=project.wallet,
            chain_type=ChainType.EVM,
            usage=AddressUsage.Vault,
            bip44_account=0,
            address_index=0,
            address="0x0000000000000000000000000000000000000400",
        )
        broadcast_task = BroadcastTask.objects.create(
            chain=chain,
            address=vault_addr,
            transfer_type=TransferType.DepositCollection,
            crypto=crypto,
            recipient="0x0000000000000000000000000000000000000411",
            amount=Decimal("3"),
        )
        collection_hash = "0x" + "e" * 64
        transfer1 = OnchainTransfer.objects.create(
            chain=chain,
            block=1,
            hash="0x" + "d1" * 32,
            event_id="erc20:d1",
            crypto=crypto,
            from_address="0x0000000000000000000000000000000000000401",
            to_address="0x0000000000000000000000000000000000000411",
            value="1",
            amount=Decimal("1"),
            timestamp=1,
            datetime=timezone.now(),
            status=TransferStatus.CONFIRMED,
            type=TransferType.Deposit,
        )
        transfer2 = OnchainTransfer.objects.create(
            chain=chain,
            block=2,
            hash="0x" + "d2" * 32,
            event_id="erc20:d2",
            crypto=crypto,
            from_address="0x0000000000000000000000000000000000000402",
            to_address="0x0000000000000000000000000000000000000411",
            value="2",
            amount=Decimal("2"),
            timestamp=2,
            datetime=timezone.now(),
            status=TransferStatus.CONFIRMED,
            type=TransferType.Deposit,
        )
        collection_transfer = OnchainTransfer.objects.create(
            chain=chain,
            block=3,
            hash=collection_hash,
            event_id="erc20:dc",
            crypto=crypto,
            from_address="0x0000000000000000000000000000000000000411",
            to_address="0x0000000000000000000000000000000000000400",
            value="3",
            amount=Decimal("3"),
            timestamp=3,
            datetime=timezone.now(),
            status=TransferStatus.CONFIRMED,
            type=TransferType.DepositCollection,
        )
        collection = DepositCollection.objects.create(
            collection_hash=collection_hash,
            transfer=collection_transfer,
            broadcast_task=broadcast_task,
            collected_at=timezone.now(),
        )
        deposit1 = Deposit.objects.create(
            customer=customer,
            transfer=transfer1,
            status=DepositStatus.COMPLETED,
            collection=collection,
        )
        deposit2 = Deposit.objects.create(
            customer=customer,
            transfer=transfer2,
            status=DepositStatus.COMPLETED,
            collection=collection,
        )

        DepositService.drop_collection(collection)

        collection.refresh_from_db()
        deposit1.refresh_from_db()
        deposit2.refresh_from_db()
        self.assertEqual(deposit1.collection_id, collection.pk)
        self.assertEqual(deposit2.collection_id, collection.pk)
        self.assertIsNone(collection.collection_hash)
        self.assertIsNone(collection.transfer_id)
        self.assertIsNone(collection.collected_at)
        self.assertEqual(collection.broadcast_task_id, broadcast_task.pk)

    def test_release_failed_collection_unbinds_deposits_and_deletes_collection(self):
        # broadcast_task 终态失败时，release_failed_collection 必须解绑 deposits
        # 并删除 collection，使这些 deposit 可被下一轮 gather_deposits 重新归集。
        project = Project.objects.create(
            name="DemoReleaseFailedCollection",
            wallet=Wallet.objects.create(),
        )
        customer = Customer.objects.create(
            project=project, uid="customer-release-failed"
        )
        native = Crypto.objects.create(
            name="Ethereum Release Failed Native",
            symbol="ETHRF",
            coingecko_id="ethereum-release-failed-native",
        )
        crypto = Crypto.objects.create(
            name="Tether Release Failed",
            symbol="USDTRF",
            coingecko_id="tether-release-failed",
        )
        chain = Chain.objects.create(
            name="Ethereum Release Failed",
            code="eth-release-failed",
            type=ChainType.EVM,
            native_coin=native,
            chain_id=206,
            rpc="http://localhost:8545",
            active=True,
        )
        vault_addr = Address.objects.create(
            wallet=project.wallet,
            chain_type=ChainType.EVM,
            usage=AddressUsage.Vault,
            bip44_account=0,
            address_index=0,
            address="0x0000000000000000000000000000000000000600",
        )
        broadcast_task = BroadcastTask.objects.create(
            chain=chain,
            address=vault_addr,
            transfer_type=TransferType.DepositCollection,
            crypto=crypto,
            recipient="0x0000000000000000000000000000000000000611",
            amount=Decimal("3"),
        )
        transfer1 = OnchainTransfer.objects.create(
            chain=chain,
            block=1,
            hash="0x" + "f1" * 32,
            event_id="erc20:f1",
            crypto=crypto,
            from_address="0x0000000000000000000000000000000000000601",
            to_address="0x0000000000000000000000000000000000000611",
            value="1",
            amount=Decimal("1"),
            timestamp=1,
            datetime=timezone.now(),
            status=TransferStatus.CONFIRMED,
            type=TransferType.Deposit,
        )
        transfer2 = OnchainTransfer.objects.create(
            chain=chain,
            block=2,
            hash="0x" + "f2" * 32,
            event_id="erc20:f2",
            crypto=crypto,
            from_address="0x0000000000000000000000000000000000000602",
            to_address="0x0000000000000000000000000000000000000611",
            value="2",
            amount=Decimal("2"),
            timestamp=2,
            datetime=timezone.now(),
            status=TransferStatus.CONFIRMED,
            type=TransferType.Deposit,
        )
        collection = DepositCollection.objects.create(
            collection_hash=None,
            broadcast_task=broadcast_task,
        )
        deposit1 = Deposit.objects.create(
            customer=customer,
            transfer=transfer1,
            status=DepositStatus.COMPLETED,
            collection=collection,
        )
        deposit2 = Deposit.objects.create(
            customer=customer,
            transfer=transfer2,
            status=DepositStatus.COMPLETED,
            collection=collection,
        )
        collection_id = collection.pk
        before_updated_at = deposit1.updated_at

        DepositService.release_failed_collection(broadcast_task=broadcast_task)

        deposit1.refresh_from_db()
        deposit2.refresh_from_db()
        self.assertIsNone(deposit1.collection_id)
        self.assertIsNone(deposit2.collection_id)
        # updated_at 应被显式刷新，使归集超时监控不误判
        self.assertGreater(deposit1.updated_at, before_updated_at)
        self.assertFalse(DepositCollection.objects.filter(pk=collection_id).exists())

    def test_release_failed_collection_is_noop_when_collection_missing(self):
        # collection 不存在（已被先前清理）时应静默返回，不抛异常。
        native = Crypto.objects.create(
            name="Ethereum Release Noop Native",
            symbol="ETHRN",
            coingecko_id="ethereum-release-noop-native",
        )
        crypto = Crypto.objects.create(
            name="Tether Release Noop",
            symbol="USDTRN",
            coingecko_id="tether-release-noop",
        )
        chain = Chain.objects.create(
            name="Ethereum Release Noop",
            code="eth-release-noop",
            type=ChainType.EVM,
            native_coin=native,
            chain_id=207,
            rpc="http://localhost:8545",
            active=True,
        )
        vault_addr = Address.objects.create(
            wallet=Wallet.objects.create(),
            chain_type=ChainType.EVM,
            usage=AddressUsage.Vault,
            bip44_account=0,
            address_index=0,
            address="0x0000000000000000000000000000000000000700",
        )
        broadcast_task = BroadcastTask.objects.create(
            chain=chain,
            address=vault_addr,
            transfer_type=TransferType.DepositCollection,
            crypto=crypto,
            recipient="0x0000000000000000000000000000000000000711",
            amount=Decimal("1"),
        )

        DepositService.release_failed_collection(broadcast_task=broadcast_task)

        self.assertEqual(
            DepositCollection.objects.filter(broadcast_task=broadcast_task).count(), 0
        )

    @patch("evm.models.EvmBroadcastTask.schedule_transfer")
    @patch("deposits.service.AdapterFactory.get_adapter")
    @patch("deposits.service.DepositAddress.objects.get")
    @patch.object(DepositService, "_select_recipient")
    def test_gather_task_only_sends_once_for_same_collect_group(
        self,
        recipient_filter_mock,
        deposit_address_get_mock,
        adapter_factory_mock,
        schedule_transfer_mock,
    ):
        # 定时归集任务即使一次捞到同组两条 completed deposit，也只能真正发出一笔归集交易。
        project = Project.objects.create(
            name="DemoGroupTask",
            wallet=Wallet.objects.create(),
            gather_worth=Decimal("0.1"),
        )
        customer = Customer.objects.create(project=project, uid="customer-group-task")
        native = Crypto.objects.create(
            name="Ethereum Task Native",
            symbol="ETHGCT",
            coingecko_id="ethereum-group-task-native",
        )
        crypto = Crypto.objects.create(
            name="Tether Group Task",
            symbol="USDTGCT",
            prices={"USD": "1"},
            coingecko_id="tether-group-task",
            decimals=6,
        )
        chain = Chain.objects.create(
            name="Ethereum Group Task",
            code="eth-group-task",
            type=ChainType.EVM,
            native_coin=native,
            chain_id=203,
            rpc="http://localhost:8545",
            active=True,
        )
        addr = Address.objects.create(
            wallet=project.wallet,
            chain_type=ChainType.EVM,
            usage=AddressUsage.Deposit,
            bip44_account=0,
            address_index=0,
            address="0x00000000000000000000000000000000000003C1",
        )
        DepositAddress.objects.create(
            customer=customer,
            chain_type=chain.type,
            address=addr,
        )
        # L1 防御：gather_deposits 现在用 RecipientAddress Exists 子查询过滤候选，
        # 因此必须在真实 DB 中至少有一条 DEPOSIT_COLLECTION recipient 让 deposit
        # 能进入候选集；下面的 mock 只在 service 层 _select_recipient 里生效。
        RecipientAddress.objects.create(
            project=project,
            chain_type=chain.type,
            address=Web3.to_checksum_address(
                "0x00000000000000000000000000000000000003d1"
            ),
            usage=RecipientAddressUsage.DEPOSIT_COLLECTION,
        )
        recipient_filter_mock.return_value = SimpleNamespace(
            address="0x00000000000000000000000000000000000003D1"
        )
        fake_addr = SimpleNamespace(
            address=addr.address,
            send_crypto=Mock(return_value="0x" + "f" * 64),
        )
        deposit_address_get_mock.return_value = SimpleNamespace(address=fake_addr)
        adapter_factory_mock.return_value = SimpleNamespace(
            get_balance=Mock(return_value=10**6)
        )
        base_task = BroadcastTask.objects.create(
            chain=chain,
            address=addr,
            transfer_type=TransferType.DepositCollection,
            crypto=crypto,
            recipient=Web3.to_checksum_address(
                "0x00000000000000000000000000000000000003d1"
            ),
            amount=Decimal("3"),
        )
        schedule_transfer_mock.return_value = SimpleNamespace(base_task=base_task)

        transfer1 = OnchainTransfer.objects.create(
            chain=chain,
            block=1,
            hash="0x" + "a" * 64,
            event_id="erc20:10",
            crypto=crypto,
            from_address="0x0000000000000000000000000000000000000301",
            to_address=addr.address,
            value="1",
            amount=Decimal("1"),
            timestamp=10,
            datetime=timezone.now(),
            status=TransferStatus.CONFIRMED,
            type=TransferType.Deposit,
        )
        transfer2 = OnchainTransfer.objects.create(
            chain=chain,
            block=2,
            hash="0x" + "b" * 64,
            event_id="erc20:11",
            crypto=crypto,
            from_address="0x0000000000000000000000000000000000000302",
            to_address=addr.address,
            value="2",
            amount=Decimal("2"),
            timestamp=11,
            datetime=timezone.now(),
            status=TransferStatus.CONFIRMED,
            type=TransferType.Deposit,
        )
        deposit1 = Deposit.objects.create(
            customer=customer,
            transfer=transfer1,
            status=DepositStatus.COMPLETED,
        )
        deposit2 = Deposit.objects.create(
            customer=customer,
            transfer=transfer2,
            status=DepositStatus.COMPLETED,
        )

        gather_deposits.run()

        deposit1.refresh_from_db()
        deposit2.refresh_from_db()
        # 同组 Deposit 应指向同一个 DepositCollection，且只发出一笔归集交易
        self.assertIsNotNone(deposit1.collection_id)
        self.assertEqual(deposit1.collection_id, deposit2.collection_id)
        self.assertIsNone(deposit1.collection.collection_hash)
        self.assertEqual(deposit1.collection.broadcast_task, base_task)
        schedule_transfer_mock.assert_called_once()


class GatherDepositsSchedulingTests(TestCase):
    """gather_deposits 防 DoS / 公平调度的四层防御测试。

    覆盖：
    - L1：project 没配 DEPOSIT_COLLECTION recipient 的 deposit 不被挑入候选；
    - L3：failed_collection_attempts 达上限的 deposit 不被挑入候选；
    - L3：collect_deposit 返回 False 时累计计数 +1；
    - 公平调度：候选池中按 project quota 做 round-robin。
    """

    def _make_chain(self, *, code: str, chain_id: int) -> Chain:
        native = Crypto.objects.create(
            name=f"Native {code}",
            symbol=f"NAT-{code.upper()}",
            coingecko_id=f"native-{code}",
        )
        return Chain.objects.create(
            name=f"Chain {code}",
            code=code,
            type=ChainType.EVM,
            native_coin=native,
            chain_id=chain_id,
            rpc="http://localhost:8545",
            active=True,
        )

    def _make_project_with_deposit_address(
        self,
        *,
        name: str,
        chain: Chain,
        configure_recipient: bool = True,
        addr_suffix: str = "0001",
    ) -> tuple[Project, Customer, DepositAddress]:
        project = Project.objects.create(
            name=name,
            wallet=Wallet.objects.create(),
            gather_worth=Decimal("0.001"),
        )
        if configure_recipient:
            RecipientAddress.objects.create(
                project=project,
                chain_type=chain.type,
                address=Web3.to_checksum_address(
                    "0x" + addr_suffix.rjust(40, "0")
                ),
                usage=RecipientAddressUsage.DEPOSIT_COLLECTION,
            )
        customer = Customer.objects.create(project=project, uid=f"u-{name}")
        addr = Address.objects.create(
            wallet=project.wallet,
            chain_type=chain.type,
            usage=AddressUsage.Deposit,
            bip44_account=0,
            address_index=0,
            address=Web3.to_checksum_address(
                "0xa" + addr_suffix.rjust(39, "0")
            ),
        )
        deposit_addr = DepositAddress.objects.create(
            customer=customer,
            chain_type=chain.type,
            address=addr,
        )
        return project, customer, deposit_addr

    def _make_deposit(
        self,
        *,
        customer: Customer,
        chain: Chain,
        crypto: Crypto,
        address_obj: Address,
        seq: int,
        failed_attempts: int = 0,
    ) -> Deposit:
        # 用一个唯一可读的 hash/event_id 防 unique 冲突。
        unique_tag = f"{customer.pk:04x}{seq:04x}"
        transfer = OnchainTransfer.objects.create(
            chain=chain,
            block=seq,
            hash="0x" + unique_tag.ljust(64, "f")[:64],
            event_id=f"native:{customer.pk}:{seq}",
            crypto=crypto,
            from_address="0x0000000000000000000000000000000000000999",
            to_address=address_obj.address,
            value="1",
            amount=Decimal("1"),
            timestamp=seq,
            datetime=timezone.now(),
            status=TransferStatus.CONFIRMED,
            type=TransferType.Deposit,
        )
        deposit = Deposit.objects.create(
            customer=customer,
            transfer=transfer,
            status=DepositStatus.COMPLETED,
        )
        if failed_attempts:
            Deposit.objects.filter(pk=deposit.pk).update(
                failed_collection_attempts=failed_attempts
            )
            deposit.refresh_from_db()
        return deposit

    @patch("deposits.tasks.DepositService.collect_deposit")
    def test_gather_skips_deposit_when_project_lacks_recipient(
        self, collect_deposit_mock
    ):
        # L1：未配置 DEPOSIT_COLLECTION recipient 的 project 下的 deposit
        # 不应进入候选集，collect_deposit 不被调用。
        chain = self._make_chain(code="eth-no-recipient", chain_id=701)
        _project, customer, addr_record = self._make_project_with_deposit_address(
            name="proj-no-recipient",
            chain=chain,
            configure_recipient=False,
            addr_suffix="01",
        )
        self._make_deposit(
            customer=customer,
            chain=chain,
            crypto=chain.native_coin,
            address_obj=addr_record.address,
            seq=1,
        )

        gather_deposits.run()

        collect_deposit_mock.assert_not_called()

    @patch("deposits.tasks.DepositService.collect_deposit")
    def test_gather_skips_deposit_after_max_failed_attempts(
        self, collect_deposit_mock
    ):
        # L3：失败计数已达上限的 deposit 不再被调度。
        from deposits.tasks import MAX_FAILED_ATTEMPTS

        chain = self._make_chain(code="eth-max-failed", chain_id=702)
        _project, customer, addr_record = self._make_project_with_deposit_address(
            name="proj-max-failed",
            chain=chain,
            configure_recipient=True,
            addr_suffix="02",
        )
        self._make_deposit(
            customer=customer,
            chain=chain,
            crypto=chain.native_coin,
            address_obj=addr_record.address,
            seq=1,
            failed_attempts=MAX_FAILED_ATTEMPTS,
        )

        gather_deposits.run()

        collect_deposit_mock.assert_not_called()

    @patch("deposits.tasks.DepositService.collect_deposit", return_value=False)
    def test_gather_increments_failed_attempts_on_collect_returning_false(
        self, _collect_deposit_mock
    ):
        # L3：collect_deposit 返回 False 时累计 failed_collection_attempts +1。
        chain = self._make_chain(code="eth-incr-failed", chain_id=703)
        _project, customer, addr_record = self._make_project_with_deposit_address(
            name="proj-incr-failed",
            chain=chain,
            configure_recipient=True,
            addr_suffix="03",
        )
        deposit = self._make_deposit(
            customer=customer,
            chain=chain,
            crypto=chain.native_coin,
            address_obj=addr_record.address,
            seq=1,
        )

        gather_deposits.run()

        deposit.refresh_from_db()
        self.assertEqual(deposit.failed_collection_attempts, 1)

    @patch(
        "deposits.tasks.DepositService.collect_deposit",
        side_effect=lambda d: True,
    )
    def test_gather_per_project_round_robin_quota(self, collect_deposit_mock):
        # 公平调度：A/B 各 100 笔、C 1 笔时，单轮 A/B 各拿到 PER_PROJECT_QUOTA(=4) 个名额，
        # C 拿到 1 个名额，总命中 9 笔（小于 TOTAL_BATCH_SIZE=16），不被任一项目独占。
        from deposits.tasks import PER_PROJECT_QUOTA

        chain = self._make_chain(code="eth-rr", chain_id=704)

        def _build(name: str, count: int, addr_suffix: str) -> Customer:
            _project, customer, addr_record = (
                self._make_project_with_deposit_address(
                    name=name,
                    chain=chain,
                    configure_recipient=True,
                    addr_suffix=addr_suffix,
                )
            )
            for i in range(count):
                self._make_deposit(
                    customer=customer,
                    chain=chain,
                    crypto=chain.native_coin,
                    address_obj=addr_record.address,
                    seq=i + 1,
                )
            return customer

        # 先创建 C 让它的 deposit 在 created_at 排序中排第一，
        # 验证候选池 + Python round-robin 不会因为单一 project 占满前列就饿死小项目。
        customer_c = _build("proj-c", 1, "00cc")
        customer_a = _build("proj-a", 100, "00aa")
        customer_b = _build("proj-b", 100, "00bb")

        gather_deposits.run()

        # 收集本轮被实际调用的 customer.project_id 分布。
        called_project_ids = [
            call.args[0].customer.project_id
            for call in collect_deposit_mock.call_args_list
        ]
        a_count = called_project_ids.count(customer_a.project_id)
        b_count = called_project_ids.count(customer_b.project_id)
        c_count = called_project_ids.count(customer_c.project_id)

        self.assertEqual(a_count, PER_PROJECT_QUOTA)
        self.assertEqual(b_count, PER_PROJECT_QUOTA)
        self.assertEqual(c_count, 1)
        self.assertEqual(a_count + b_count + c_count, 2 * PER_PROJECT_QUOTA + 1)


class DepositAddressApiGuardTests(TestCase):
    def test_address_endpoint_rejects_bitcoin_chain_without_allocating_deposit_address(
        self,
    ):
        project = Project.objects.create(
            name="Bitcoin Deposit Guard Project",
            wallet=Wallet.objects.create(),
            ip_white_list="*",
            webhook="https://example.com/webhook",
        )
        btc = Crypto.objects.create(
            name="Bitcoin Native",
            symbol="BTC-DEPOSIT-GUARD",
            coingecko_id="bitcoin-native-guard",
            decimals=8,
        )
        bitcoin_chain = Chain.objects.create(
            name="Bitcoin Mainnet Guard",
            code="btc-guard",
            type=ChainType.BITCOIN,
            native_coin=btc,
            rpc="http://bitcoin.invalid",
            active=True,
            latest_block_number=321,
        )
        request = APIRequestFactory().get(
            "/v1/deposit/address",
            {"uid": "btc-user", "chain": bitcoin_chain.code, "crypto": btc.symbol},
            HTTP_XC_APPID=project.appid,
        )
        force_authenticate(
            request,
            user=User.objects.create(username="deposit-api-btc"),
        )

        with patch("deposits.viewsets.DepositAddress.get_address") as get_address_mock:
            response = DepositViewSet.as_view({"get": "address"})(request)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], ErrorCode.INVALID_CHAIN.code)
        get_address_mock.assert_not_called()

    def test_address_endpoint_uses_capability_service_to_reject_tron_usdt(
        self,
    ):
        project = Project.objects.create(
            name="Tron Deposit Guard Project",
            wallet=Wallet.objects.create(),
            ip_white_list="*",
            webhook="https://example.com/webhook",
        )
        trx = Crypto.objects.create(
            name="Tron Native",
            symbol="TRX",
            coingecko_id="tron-native-guard",
        )
        usdt = Crypto.objects.create(
            name="Tether on Tron",
            symbol="USDT",
            coingecko_id="tether-tron-guard",
            decimals=6,
        )
        tron_chain = Chain.objects.create(
            name="Tron Mainnet Guard",
            code="tron-guard",
            type=ChainType.TRON,
            native_coin=trx,
            rpc="http://tron.invalid",
            active=True,
            latest_block_number=321,
        )
        ChainToken.objects.create(
            crypto=usdt,
            chain=tron_chain,
            address="TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
            decimals=6,
        )
        request = APIRequestFactory().get(
            "/v1/deposit/address",
            {"uid": "tron-user", "chain": tron_chain.code, "crypto": usdt.symbol},
            HTTP_XC_APPID=project.appid,
        )
        force_authenticate(request, user=User.objects.create(username="deposit-api"))

        with (
            patch(
                "deposits.viewsets.ChainProductCapabilityService.supports_deposit_address",
                return_value=False,
            ) as supports_deposit_address_mock,
            patch("deposits.viewsets.DepositAddress.get_address") as get_address_mock,
        ):
            response = DepositViewSet.as_view({"get": "address"})(request)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], ErrorCode.INVALID_CHAIN.code)
        supports_deposit_address_mock.assert_called_once_with(
            chain=tron_chain,
            crypto=usdt,
        )
        get_address_mock.assert_not_called()

    def test_get_deposit_address_rejects_when_recipient_not_configured(self):
        # L2：project 未配置 DEPOSIT_COLLECTION recipient 时，不允许新建充币地址；
        # 这是防止"用户充值进来无法归集 → gather 队头反复阻塞"的 DoS 攻击面。
        project = Project.objects.create(
            name="No Recipient Guard",
            wallet=Wallet.objects.create(),
            ip_white_list="*",
            webhook="https://example.com/webhook",
        )
        native = Crypto.objects.create(
            name="Ethereum NoRecipient",
            symbol="ETH-NORECP",
            coingecko_id="ethereum-no-recipient",
            decimals=18,
        )
        chain = Chain.objects.create(
            name="Ethereum NoRecipient Chain",
            code="eth-no-recipient",
            type=ChainType.EVM,
            native_coin=native,
            chain_id=801,
            rpc="http://localhost:8545",
            active=True,
        )
        request = APIRequestFactory().get(
            "/v1/deposit/address",
            {"uid": "u1", "chain": chain.code, "crypto": native.symbol},
            HTTP_XC_APPID=project.appid,
        )
        force_authenticate(
            request,
            user=User.objects.create(username="deposit-api-no-recp"),
        )

        # 不直接 mock get_address；目的是验证 service 层校验真实生效，
        # 漏配 recipient 时无法越过校验创建 DepositAddress。
        # 校验 get_or_create 没有走到派生地址那一步：在 patch wallet.get_address，
        # 一旦 service 层校验失败，wallet.get_address 必须没被调用。
        with patch("chains.models.Wallet.get_address") as wallet_get_address_mock:
            response = DepositViewSet.as_view({"get": "address"})(request)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data["code"], ErrorCode.RECIPIENT_NOT_CONFIGURED.code
        )
        # 校验没有触达地址派生 → 证明 service 层在派生前就拒绝。
        wallet_get_address_mock.assert_not_called()


@override_settings(
    SIGNER_BACKEND="remote",
    SIGNER_BASE_URL="http://signer.internal",
    SIGNER_SHARED_SECRET="secret",
)
class DepositRemoteSignerFlowTests(TestCase):
    @patch("chains.signer.get_signer_backend")
    def test_deposit_address_allocation_uses_remote_signer_without_local_mnemonic(
        self,
        get_signer_backend_mock,
    ):
        # remote signer 模式下，充币地址分配必须只走远端派生，不能再读取本地助记词。
        signer_backend = Mock()
        signer_backend.derive_address.return_value = Web3.to_checksum_address(
            "0x000000000000000000000000000000000000d001"
        )
        get_signer_backend_mock.return_value = signer_backend
        wallet = Wallet.objects.create()
        with patch("projects.signals.Wallet.generate", return_value=wallet):
            project = Project.objects.create(
                name="RemoteDepositAddressProject",
                wallet=wallet,
            )
        customer = Customer.objects.create(
            project=project, uid="customer-remote-deposit-address"
        )
        chain = Chain.objects.create(
            name="Ethereum Remote Deposit Address",
            code="eth-remote-deposit-address",
            type=ChainType.EVM,
            native_coin=Crypto.objects.create(
                name="Ethereum Remote Deposit Address Native",
                symbol="ETHRDA",
                coingecko_id="ethereum-remote-deposit-address-native",
            ),
            chain_id=401,
            rpc="http://localhost:8545",
            active=True,
        )
        # L2 防御：DepositAddress.get_address 现在要求 project 已配 DEPOSIT_COLLECTION recipient。
        RecipientAddress.objects.create(
            project=project,
            chain_type=chain.type,
            address=Web3.to_checksum_address(
                "0x000000000000000000000000000000000000d099"
            ),
            usage=RecipientAddressUsage.DEPOSIT_COLLECTION,
        )

        with patch("projects.signals.Wallet.generate", return_value=wallet):
            address = DepositAddress.get_address(chain=chain, customer=customer)

        deposit_addr = DepositAddress.objects.get(
            customer=customer, chain_type=chain.type
        )
        self.assertEqual(
            address,
            Web3.to_checksum_address("0x000000000000000000000000000000000000d001"),
        )
        self.assertEqual(deposit_addr.address.address, address)
        signer_backend.derive_address.assert_called_once()

    @patch("evm.models.get_signer_backend")
    @patch.object(EvmBroadcastTask, "_next_nonce", return_value=0)
    @patch("deposits.service.AdapterFactory.get_adapter")
    @patch("deposits.service.RecipientAddress.objects.filter")
    @patch.object(Chain, "w3", new_callable=PropertyMock)
    def test_collect_deposit_uses_remote_signer_without_local_mnemonic(
        self,
        chain_w3_mock,
        recipient_filter_mock,
        adapter_factory_mock,
        _next_nonce_mock,
        get_signer_backend_mock,
    ):
        # remote signer 模式下，归集链路应直接使用远端签名，不允许回退到主应用本地持钥。
        signer_backend = Mock()
        signer_backend.sign_evm_transaction.return_value = SimpleNamespace(
            tx_hash="0x" + "e" * 64,
            raw_transaction="0xdeadbeef",
        )
        get_signer_backend_mock.return_value = signer_backend
        wallet = Wallet.objects.create()
        with patch("projects.signals.Wallet.generate", return_value=wallet):
            project = Project.objects.create(
                name="RemoteDepositCollectProject",
                wallet=wallet,
                gather_worth=Decimal("0.1"),
            )
        customer = Customer.objects.create(
            project=project, uid="customer-remote-deposit-collect"
        )
        native = Crypto.objects.create(
            name="Ethereum Remote Deposit Collect Native",
            symbol="ETHRDC",
            prices={"USD": "1"},
            coingecko_id="ethereum-remote-deposit-collect-native",
        )
        chain = Chain.objects.create(
            name="Ethereum Remote Deposit Collect",
            code="eth-remote-deposit-collect",
            type=ChainType.EVM,
            native_coin=native,
            chain_id=402,
            rpc="http://localhost:8545",
            active=True,
        )
        chain_w3_mock.return_value = SimpleNamespace(
            eth=SimpleNamespace(gas_price=5, send_raw_transaction=Mock())
        )
        addr = Address.objects.create(
            wallet=wallet,
            chain_type=ChainType.EVM,
            usage=AddressUsage.Deposit,
            bip44_account=0,
            address_index=0,
            address=Web3.to_checksum_address(
                "0x000000000000000000000000000000000000d002"
            ),
        )
        DepositAddress.objects.create(
            customer=customer,
            chain_type=chain.type,
            address=addr,
        )
        recipient_filter_mock.return_value.order_by.return_value.first.return_value = (
            SimpleNamespace(
                address=Web3.to_checksum_address(
                    "0x000000000000000000000000000000000000d003"
                )
            )
        )
        adapter_factory_mock.return_value = SimpleNamespace(
            get_balance=Mock(return_value=10**18 + 10**6)
        )
        transfer = OnchainTransfer.objects.create(
            chain=chain,
            block=1,
            hash="0x" + "1" * 64,
            event_id="native:remote-collect",
            crypto=native,
            from_address=Web3.to_checksum_address(
                "0x000000000000000000000000000000000000d010"
            ),
            to_address=addr.address,
            value="1",
            amount=Decimal("1"),
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

        collected = DepositService.collect_deposit(deposit)

        self.assertTrue(collected)
        deposit.refresh_from_db()
        self.assertIsNotNone(deposit.collection_id)
        self.assertIsNotNone(deposit.collection.broadcast_task_id)
        self.assertIsNone(deposit.collection.collection_hash)
        signer_backend.sign_evm_transaction.assert_not_called()


# ---------------------------------------------------------------------------
# Anvil 集成测试：充币归集完整链路
# 依赖本地 anvil (docker compose -f docker-compose.dev.yml up ethereum)
# ---------------------------------------------------------------------------

ANVIL_RPC = "http://127.0.0.1:8545"

_anvil_available = False
try:
    _w3_probe = Web3(Web3.HTTPProvider(ANVIL_RPC, request_kwargs={"timeout": 2}))
    _anvil_available = _w3_probe.is_connected()
except Exception:  # noqa: BLE001
    pass


@unittest.skipUnless(_anvil_available, "需要本地 anvil")
class DepositCollectionAnvilTests(TestCase):
    """
    依赖本地 anvil 的充币归集完整链路集成测试。

    新的归集设计下，prepare_collection 不再做 gas 补充，gas 职责已上移到
    EVM 广播层 pre-flight。由于本套测试用 mock 替换了 schedule_transfer
    直接在 anvil 上真实转账，真正的广播（及其 pre-flight gas 补给）被绕过。
    因此这些集成测试聚焦"余额/归集金额/对账"等归集侧真实链路行为，gas
    补给流程单独由单元测试 + 广播层测试覆盖。

    仅 mock 两处：
      1. Wallet.get_address — 跳过 remote signer
      2. EvmBroadcastTask.schedule_transfer — 通过 anvil impersonation 做真实链上转账
    其余（余额查询、归集金额、归集逻辑）全部走真实链路。
    """

    DEPOSIT_ADDR = Web3.to_checksum_address(
        "0x1111111111111111111111111111111111111111"
    )
    VAULT_ADDR = Web3.to_checksum_address(
        "0x2222222222222222222222222222222222222222"
    )
    RECIPIENT_ADDR = Web3.to_checksum_address(
        "0x3333333333333333333333333333333333333333"
    )
    # 给充币地址预留的 gas 垫资，保证 anvil 上真实转账有足够 native 付 gas。
    GAS_PADDING_WEI = 10**17

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.w3 = Web3(Web3.HTTPProvider(ANVIL_RPC, request_kwargs={"timeout": 8}))

    def setUp(self):
        # anvil 快照，每个测试独立
        self._snapshot = self.w3.provider.make_request("evm_snapshot", [])["result"]

        # -- DB fixtures --
        self.native = Crypto.objects.create(
            name="ETH Anvil", symbol="ETH_ANV",
            prices={"USD": "2000"}, coingecko_id="eth-anvil",
        )
        self.chain = Chain.objects.create(
            name="Anvil", code="anvil",
            type=ChainType.EVM, native_coin=self.native,
            chain_id=31337, rpc=ANVIL_RPC, active=True,
        )
        self.wallet = Wallet.objects.create()
        self.project = Project.objects.create(
            name="AnvilProject", wallet=self.wallet,
            gather_worth=Decimal("0.001"), gather_period=7,
        )
        self.customer = Customer.objects.create(
            project=self.project, uid="anvil-customer",
        )
        self.deposit_addr_obj = Address.objects.create(
            wallet=self.wallet, chain_type=ChainType.EVM,
            usage=AddressUsage.Deposit, bip44_account=0,
            address_index=0, address=self.DEPOSIT_ADDR,
        )
        self.vault_addr_obj = Address.objects.create(
            wallet=self.wallet, chain_type=ChainType.EVM,
            usage=AddressUsage.Vault, bip44_account=100_000_000,
            address_index=0, address=self.VAULT_ADDR,
        )
        DepositAddress.objects.create(
            customer=self.customer, chain_type=ChainType.EVM,
            address=self.deposit_addr_obj,
        )
        RecipientAddress.objects.create(
            project=self.project, chain_type=ChainType.EVM,
            address=self.RECIPIENT_ADDR, name="vault",
            usage=RecipientAddressUsage.DEPOSIT_COLLECTION,
        )

        # 为 vault / recipient 初始化
        self._set_balance(self.VAULT_ADDR, 10 * 10**18)
        self._set_balance(self.RECIPIENT_ADDR, 0)

        # -- Mocks --
        # 1. Wallet.get_address → 直接返回 vault Address（跳过 signer）
        patcher_wallet = patch.object(Wallet, "get_address", return_value=self.vault_addr_obj)
        self.wallet_get_addr_mock = patcher_wallet.start()
        self.addCleanup(patcher_wallet.stop)

        # 2. EvmBroadcastTask.schedule_transfer → anvil impersonation 真实转账
        patcher_schedule = patch(
            "evm.models.EvmBroadcastTask.schedule_transfer",
            side_effect=self._anvil_schedule_transfer,
        )
        self.schedule_mock = patcher_schedule.start()
        self.addCleanup(patcher_schedule.stop)

    def tearDown(self):
        self.w3.provider.make_request("evm_revert", [self._snapshot])

    # ---- helpers ----

    def _set_balance(self, addr: str, amount_wei: int):
        self.w3.provider.make_request("anvil_setBalance", [addr, hex(amount_wei)])

    def _on_chain_balance(self, addr: str) -> int:
        return self.w3.eth.get_balance(Web3.to_checksum_address(addr))

    def _impersonate_send_eth(self, from_addr: str, to_addr: str, value_wei: int) -> str:
        self.w3.provider.make_request("anvil_impersonateAccount", [from_addr])
        tx = self.w3.eth.send_transaction({
            "from": from_addr, "to": to_addr,
            "value": value_wei, "gas": 21_000,
            "gasPrice": self.w3.eth.gas_price,
        })
        receipt = self.w3.eth.wait_for_transaction_receipt(tx)
        self.w3.provider.make_request("anvil_stopImpersonatingAccount", [from_addr])
        return "0x" + receipt.transactionHash.hex()

    def _anvil_schedule_transfer(self, *, address, crypto, chain, to, value_raw, transfer_type):
        """EvmBroadcastTask.schedule_transfer 的替代：在 anvil 上真实转账。"""
        from_addr = address.address if hasattr(address, "address") else address
        tx_hash = self._impersonate_send_eth(from_addr, to, value_raw)
        decimals = crypto.get_decimals(chain)
        base_task = BroadcastTask.objects.create(
            chain=chain, address=address if isinstance(address, Address) else self.deposit_addr_obj,
            transfer_type=transfer_type, crypto=crypto,
            recipient=to,
            amount=Decimal(value_raw) / Decimal(10**decimals),
            tx_hash=tx_hash,
        )
        return SimpleNamespace(base_task=base_task)

    def _create_deposit(self, amount: Decimal, *, seq: int = 1) -> Deposit:
        """创建 Deposit 记录并在 anvil 上设置对应余额。

        为保证 schedule_transfer mock 调用 anvil impersonation 真实转账时能付
        gas，每次创建充值时同时额外预充一份 GAS_PADDING_WEI。这部分不计入
        归集金额（归集金额 = 充值总额，不是余额），只用来模拟"广播层已经
        通过 pre-flight 确认 gas 到账"的状态。
        """
        decimals = self.native.get_decimals(self.chain)
        amount_raw = int(amount * Decimal(10**decimals))

        # 在链上为充值地址添加余额（模拟用户充币）+ gas 垫资
        current = self._on_chain_balance(self.DEPOSIT_ADDR)
        self._set_balance(self.DEPOSIT_ADDR, current + amount_raw + self.GAS_PADDING_WEI)

        transfer = OnchainTransfer.objects.create(
            chain=self.chain, block=seq,
            hash="0x" + f"{seq:064x}",
            event_id=f"native:anvil:{seq}",
            crypto=self.native,
            from_address="0x0000000000000000000000000000000000000999",
            to_address=self.DEPOSIT_ADDR,
            value=str(amount_raw), amount=amount,
            timestamp=seq, datetime=timezone.now(),
            status=TransferStatus.CONFIRMED,
            type=TransferType.Deposit,
        )
        return Deposit.objects.create(
            customer=self.customer, transfer=transfer,
            status=DepositStatus.COMPLETED,
        )

    # ---- 场景 1: 单笔原生币充值 → 归集 ----

    def test_single_native_deposit_collect_transfers_exact_amount(self):
        deposit = self._create_deposit(Decimal("1"), seq=1)

        # gas 已通过 _create_deposit 预置（GAS_PADDING_WEI），一轮即成功
        self.assertTrue(DepositService.collect_deposit(deposit))
        deposit.refresh_from_db()
        self.assertIsNotNone(deposit.collection_id)

        # 验证 recipient 收到恰好 1 ETH（非余额）
        recipient_balance = self._on_chain_balance(self.RECIPIENT_ADDR)
        self.assertEqual(recipient_balance, 10**18)

    # ---- 场景 2: 多笔充值合并归集 ----

    def test_multi_deposit_merged_collection(self):
        d1 = self._create_deposit(Decimal("0.5"), seq=1)
        d2 = self._create_deposit(Decimal("1.5"), seq=2)
        d3 = self._create_deposit(Decimal("1"), seq=3)

        self.assertTrue(DepositService.collect_deposit(d1))

        d1.refresh_from_db()
        d2.refresh_from_db()
        d3.refresh_from_db()

        # 三笔充值共享同一 DepositCollection
        self.assertIsNotNone(d1.collection_id)
        self.assertEqual(d1.collection_id, d2.collection_id)
        self.assertEqual(d1.collection_id, d3.collection_id)

        # recipient 收到精确 3 ETH
        self.assertEqual(self._on_chain_balance(self.RECIPIENT_ADDR), 3 * 10**18)

    # ---- 场景 3: 连续 2 轮独立归集，每轮对账独立 ----

    def test_two_rounds_independent_collections(self):
        # -- 第一轮：充 1 ETH --
        d1 = self._create_deposit(Decimal("1"), seq=1)
        self.assertTrue(DepositService.collect_deposit(d1))
        d1.refresh_from_db()
        self.assertIsNotNone(d1.collection_id)
        self.assertEqual(self._on_chain_balance(self.RECIPIENT_ADDR), 10**18)

        # -- 第二轮：充 2 ETH --
        d2 = self._create_deposit(Decimal("2"), seq=2)
        self.assertTrue(DepositService.collect_deposit(d2))
        d2.refresh_from_db()
        self.assertIsNotNone(d2.collection_id)
        # 两轮独立 DepositCollection
        self.assertNotEqual(d1.collection_id, d2.collection_id)
        # recipient 累计收到 1 + 2 = 3 ETH
        self.assertEqual(self._on_chain_balance(self.RECIPIENT_ADDR), 3 * 10**18)

    # ---- 场景 4: 连续 3 轮递增充值，每轮独立对账 ----

    def test_three_rounds_progressive_deposits(self):
        amounts = [Decimal("0.1"), Decimal("0.5"), Decimal("2")]
        collection_ids = []
        expected_recipient = 0

        for i, amount in enumerate(amounts, start=1):
            deposit = self._create_deposit(amount, seq=i)
            self.assertTrue(DepositService.collect_deposit(deposit))

            deposit.refresh_from_db()
            self.assertIsNotNone(deposit.collection_id)
            collection_ids.append(deposit.collection_id)

            # 归集金额精确等于充值金额
            decimals = self.native.get_decimals(self.chain)
            expected_recipient += int(amount * Decimal(10**decimals))
            self.assertEqual(
                self._on_chain_balance(self.RECIPIENT_ADDR), expected_recipient
            )

        # 3 轮 DepositCollection 各自独立
        self.assertEqual(len(set(collection_ids)), 3)

    # ---- 场景 5: 小额低于阈值，deadline 后才归集 ----

    def test_deposit_below_threshold_collected_after_deadline(self):
        # 抬高归集阈值到 $5000，使 0.001 ETH ($2) 低于门槛
        self.project.gather_worth = Decimal("5000")
        self.project.save(update_fields=["gather_worth"])

        deposit = self._create_deposit(Decimal("0.001"), seq=1)

        # worth = 0.001 ETH * $2000 = $2 < gather_worth=$5000 且未过期 → 跳过
        self.assertFalse(DepositService.collect_deposit(deposit))
        deposit.refresh_from_db()
        self.assertIsNone(deposit.collection_id)

        # 修改创建时间到 gather_period 天前 → deadline 过期触发归集
        Deposit.objects.filter(pk=deposit.pk).update(
            created_at=timezone.now() - timedelta(days=self.project.gather_period + 1)
        )
        deposit.refresh_from_db()

        self.assertTrue(DepositService.collect_deposit(deposit))
        deposit.refresh_from_db()
        self.assertIsNotNone(deposit.collection_id)
        self.assertEqual(self._on_chain_balance(self.RECIPIENT_ADDR), 10**15)
