from django.core.management.base import BaseCommand

from core.default_data import ensure_base_currencies
from core.default_data import ensure_local_chains


class Command(BaseCommand):
    help = "初始化本地联调链（anvil / bitcoin regtest）"

    def handle(self, *args, **options):
        self.stdout.write("开始初始化本地联调环境...")

        ensure_base_currencies(stdout=self.stdout)
        ensure_local_chains(stdout=self.stdout)

        self.stdout.write(self.style.SUCCESS("🎉 本地联调链初始化完成"))
