from concurrent.futures import ThreadPoolExecutor

from django.test import TestCase
from django.test import TransactionTestCase
from web3 import Web3

from chains.models import AddressUsage
from evm.models import ContractDeployCollection
from evm.services.create2 import ContractDeployCollectionService
from evm.tests._fixtures import make_erc20_token
from evm.tests._fixtures import make_evm_chain
from evm.tests._fixtures import make_evm_system_address


class Create2IdempotencyTests(TestCase):
    def setUp(self):
        self.chain = make_evm_chain(code="eth-c2-idem", chain_id=44002)
        self.chain.create2_factory_address = Web3.to_checksum_address("0x" + "91" * 20)
        self.chain.save(update_fields=["create2_factory_address"])
        self.crypto = make_erc20_token(
            chain=self.chain,
            address_suffix="92",
            decimals=6,
        )
        self.deployer = make_evm_system_address(
            suffix="93",
            usage=AddressUsage.Vault,
        )
        self.vault = ("0x" + "94" * 20).lower()

    def test_same_chain_factory_salt_returns_existing_collection(self):
        kwargs = {
            "deployer": self.deployer,
            "chain": self.chain,
            "crypto": self.crypto,
            "salt": b"\x95" * 32,
            "vault_address": self.vault,
            "expected_collect_value_raw": 1_000_000,
            "gas": 200_000,
        }
        first = ContractDeployCollectionService.create_and_schedule(
            **kwargs,
        ).collection
        second = ContractDeployCollectionService.create_and_schedule(
            **kwargs,
        ).collection

        assert second.pk == first.pk
        assert Web3.is_checksum_address(second.factory_address)
        assert Web3.is_checksum_address(second.vault_address)
        assert ContractDeployCollection.objects.count() == 1

    def test_same_chain_factory_salt_with_different_value_is_rejected(self):
        kwargs = {
            "deployer": self.deployer,
            "chain": self.chain,
            "crypto": self.crypto,
            "salt": b"\x96" * 32,
            "vault_address": self.vault,
            "expected_collect_value_raw": 1_000_000,
            "gas": 200_000,
        }
        ContractDeployCollectionService.create_and_schedule(**kwargs)
        kwargs["expected_collect_value_raw"] = 2_000_000

        with self.assertRaisesRegex(ValueError, "CREATE2 collection conflict"):
            ContractDeployCollectionService.create_and_schedule(**kwargs)

    def test_same_chain_factory_salt_with_different_gas_is_rejected(self):
        kwargs = {
            "deployer": self.deployer,
            "chain": self.chain,
            "crypto": self.crypto,
            "salt": b"\x97" * 32,
            "vault_address": self.vault,
            "expected_collect_value_raw": 1_000_000,
            "gas": 200_000,
        }
        ContractDeployCollectionService.create_and_schedule(**kwargs)
        kwargs["gas"] = 250_000

        with self.assertRaisesRegex(ValueError, "CREATE2 collection conflict"):
            ContractDeployCollectionService.create_and_schedule(**kwargs)


class Create2IdempotencyConcurrencyTests(TransactionTestCase):
    def test_concurrent_same_chain_factory_salt_returns_single_collection(self):
        chain = make_evm_chain(code="eth-c2-idem-concurrent", chain_id=44012)
        chain.create2_factory_address = Web3.to_checksum_address("0x" + "97" * 20)
        chain.save(update_fields=["create2_factory_address"])
        crypto = make_erc20_token(chain=chain, address_suffix="98", decimals=6)
        deployer = make_evm_system_address(suffix="99", usage=AddressUsage.Vault)
        kwargs = {
            "deployer": deployer,
            "chain": chain,
            "crypto": crypto,
            "salt": b"\x9a" * 32,
            "vault_address": Web3.to_checksum_address("0x" + "9b" * 20),
            "expected_collect_value_raw": 1_000_000,
            "gas": 200_000,
        }

        def create_one():
            return ContractDeployCollectionService.create_and_schedule(
                **kwargs,
            ).collection.pk

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: create_one(), range(2)))

        assert len(set(results)) == 1
        assert ContractDeployCollection.objects.count() == 1
