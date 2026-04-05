from __future__ import annotations

from django.core.management.base import BaseCommand

from bitcoin.rpc import BitcoinRpcClient
from bitcoin.rpc import BitcoinRpcError
from chains.models import Address
from chains.models import ChainType
from core.default_data import build_local_bitcoin_root_rpc
from projects.models import RecipientAddress


class Command(BaseCommand):
    help = "准备本地 Bitcoin regtest 钱包：创建/加载钱包、预挖区块并导入系统 BTC 地址"

    def add_arguments(self, parser):
        parser.add_argument(
            "--wallet-name",
            default="xcash",
            help="本地 regtest 钱包名，默认 xcash",
        )
        parser.add_argument(
            "--mine-blocks",
            type=int,
            default=101,
            help="首次准备时预挖的区块数，默认 101（让 coinbase 立即成熟）",
        )
        parser.add_argument(
            "--skip-import",
            action="store_true",
            help="只准备钱包和区块，不导入系统内已有的 BTC 地址",
        )

    def handle(self, *args, **options):
        wallet_name: str = options["wallet_name"]
        mine_blocks: int = max(0, options["mine_blocks"])
        skip_import: bool = options["skip_import"]

        # 根 RPC 用于 createwallet / loadwallet；真正业务链配置仍使用 wallet 路径。
        root_client = BitcoinRpcClient(build_local_bitcoin_root_rpc())
        wallet_client = self._ensure_wallet(
            root_client=root_client, wallet_name=wallet_name
        )

        if mine_blocks:
            # regtest 必须先挖成熟 coinbase，后续 sendtoaddress 才能直接给系统地址打款。
            mining_address = wallet_client.get_new_address(
                label="xcash-regtest-miner",
                address_type="legacy",
            )
            wallet_client.generate_to_address(mine_blocks, mining_address)
            self.stdout.write(f"✅ 已预挖 {mine_blocks} 个 regtest 区块")

        if not skip_import:
            imported_count = self._import_known_bitcoin_addresses(
                wallet_client=wallet_client
            )
            self.stdout.write(f"✅ 已导入 {imported_count} 个 BTC watch-only 地址")

        self.stdout.write(self.style.SUCCESS("🎉 本地 Bitcoin regtest 已准备就绪"))

    @staticmethod
    def _wallet_rpc_url(wallet_name: str) -> str:
        base_url = build_local_bitcoin_root_rpc()
        return f"{base_url}/wallet/{wallet_name}"

    def _ensure_wallet(
        self,
        *,
        root_client: BitcoinRpcClient,
        wallet_name: str,
    ) -> BitcoinRpcClient:
        loaded_wallets = set(root_client.list_wallets())
        if wallet_name not in loaded_wallets:
            try:
                root_client.load_wallet(wallet_name)
            except BitcoinRpcError as exc:
                # 本地首次启动时钱包通常不存在；这里显式创建，避免要求用户手工 bitcoin-cli。
                error_message = str(exc)
                if (
                    "Wallet file not found" in error_message
                    or "Path does not exist" in error_message
                ):
                    root_client.create_wallet(wallet_name)
                else:
                    raise

        return BitcoinRpcClient(self._wallet_rpc_url(wallet_name))

    @staticmethod
    def _known_bitcoin_imports() -> list[tuple[str, str]]:
        addr_imports = [
            (addr.address, f"addr({addr.address})")
            for addr in Address.objects.filter(chain_type=ChainType.BITCOIN)
        ]
        recipient_imports = [
            (address, f"addr({address})")
            for address in RecipientAddress.objects.filter(
                chain_type=ChainType.BITCOIN
            ).values_list(
                "address",
                flat=True,
            )
        ]
        # watch-only 导入按地址去重后顺序处理，重复运行时保持幂等。
        deduped_imports: dict[str, str] = {}
        for address, descriptor in [*addr_imports, *recipient_imports]:
            deduped_imports.setdefault(address, descriptor)
        return list(deduped_imports.items())

    def _import_known_bitcoin_addresses(
        self,
        *,
        wallet_client: BitcoinRpcClient,
    ) -> int:
        imported_count = 0
        for address, descriptor in self._known_bitcoin_imports():
            try:
                wallet_client.import_address(
                    address, label="xcash-watch-only", rescan=False
                )
            except BitcoinRpcError as exc:
                error_message = str(exc)
                if "Only legacy wallets are supported by this command" in error_message:
                    # descriptor 私钥钱包无法导入 watch-only；这里转成 best-effort，
                    # 真正需要 UTXO 时由 scantxoutset 回退兜底，避免本地准备命令被阻断。
                    try:
                        wallet_client.import_descriptor(
                            descriptor=descriptor,
                            label="xcash-watch-only",
                        )
                    except BitcoinRpcError as descriptor_exc:
                        if "Cannot import descriptor without private keys" in str(
                            descriptor_exc
                        ):
                            self.stdout.write(
                                self.style.WARNING(
                                    f"⚠️ 当前钱包不支持 watch-only descriptor 导入，已跳过地址 {address}"
                                )
                            )
                            continue
                        raise
                    imported_count += 1
                    continue
                # 重复导入同一地址属于正常幂等场景，不应阻断整批本地准备流程。
                if "already exists" in error_message.lower():
                    continue
                raise
            imported_count += 1
        return imported_count
