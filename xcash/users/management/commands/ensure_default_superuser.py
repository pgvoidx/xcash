from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import IntegrityError
from django.db import transaction

from users.models import User


class Command(BaseCommand):
    help = "当系统内不存在管理员时，创建默认 superuser"

    def handle(self, *args, **options):
        if User.objects.filter(is_superuser=True).exists():
            self.stdout.write("已存在管理员账号，跳过默认管理员创建")
            return

        username = settings.DEFAULT_SUPERUSER_USERNAME
        password = settings.DEFAULT_SUPERUSER_PASSWORD

        try:
            with transaction.atomic():
                if User.objects.filter(is_superuser=True).exists():
                    self.stdout.write("已存在管理员账号，跳过默认管理员创建")
                    return
                User.objects.create_superuser(
                    username=username,
                    password=password,
                )
        except IntegrityError:
            # 部署并发启动时，可能已有其他实例抢先创建了同名默认管理员。
            if User.objects.filter(is_superuser=True).exists():
                self.stdout.write("已存在管理员账号，跳过默认管理员创建")
                return
            raise

        self.stdout.write(
            self.style.WARNING(
                f"已创建默认管理员账号: {username} / {password}，请首次登录后立即修改密码"
            )
        )
