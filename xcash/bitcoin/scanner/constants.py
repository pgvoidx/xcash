from __future__ import annotations

# BTC 扫描同样需要在推进主游标时回退一小段，覆盖轻微重组和任务抖动。
DEFAULT_REORG_LOOKBACK_BLOCKS = 12

# 单轮默认最多推进 144 个块，既能覆盖长时间停机后的补扫，又不会让单次任务跑太久。
DEFAULT_SCAN_BATCH_SIZE = 144
