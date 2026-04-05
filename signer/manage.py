#!/usr/bin/env python
import os
import sys
from pathlib import Path


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

    signer_root = Path(__file__).resolve().parent
    # 独立 signer 入口只把 signer 项目根目录加入模块搜索路径，避免继续依赖仓库根目录。
    sys.path.insert(0, str(signer_root))

    from django.core.management import execute_from_command_line  # noqa: PLC0415

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
