"""EVM 模块数据库触发器定义。

通过 post_migrate 信号在每次迁移后自动安装，不依赖手写 RunSQL migration，
清空并重建迁移文件后触发器仍会被自动重建。
"""

from django.db import connections

# nonce 连续性触发器：
# - 无记录时 nonce 必须为 0
# - 有记录时 nonce 必须为 max(nonce) + 1
# 配合 UNIQUE(address, chain, nonce) 约束，从数据库层面杜绝 nonce 乱序或跳跃。
_NONCE_SEQUENTIAL_FUNC = """
CREATE OR REPLACE FUNCTION evm_check_nonce_sequential()
RETURNS TRIGGER AS $$
DECLARE
    max_nonce BIGINT;
BEGIN
    SELECT MAX(nonce)
      INTO max_nonce
      FROM evm_evmbroadcasttask
     WHERE address_id = NEW.address_id
       AND chain_id   = NEW.chain_id;

    IF max_nonce IS NULL AND NEW.nonce != 0 THEN
        RAISE EXCEPTION
            'first nonce must be 0, got % (address_id=%, chain_id=%)',
            NEW.nonce, NEW.address_id, NEW.chain_id;
    END IF;

    IF max_nonce IS NOT NULL AND NEW.nonce != max_nonce + 1 THEN
        RAISE EXCEPTION
            'nonce must be max+1: expected %, got % (address_id=%, chain_id=%)',
            max_nonce + 1, NEW.nonce, NEW.address_id, NEW.chain_id;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

_NONCE_SEQUENTIAL_TRIGGER = """
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_evm_broadcast_task_nonce_sequential'
    ) THEN
        CREATE TRIGGER trg_evm_broadcast_task_nonce_sequential
            BEFORE INSERT ON evm_evmbroadcasttask
            FOR EACH ROW
            EXECUTE FUNCTION evm_check_nonce_sequential();
    END IF;
END;
$$;
"""


def install_triggers(*, using: str = "default") -> None:
    """安装 EVM 模块所有数据库触发器（幂等）。"""
    with connections[using].cursor() as cursor:
        cursor.execute(_NONCE_SEQUENTIAL_FUNC)
        cursor.execute(_NONCE_SEQUENTIAL_TRIGGER)
