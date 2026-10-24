"""性能基准（优化前的锚点，每轮性能优化都要重新跑它做前后对比）。

用法：
    python scripts/bench.py            # 跑全部基准
    python scripts/bench.py --only de  # 只跑 delta_e
"""
from __future__ import annotations

import argparse
import random
import statistics
import time
from pathlib import Path
from typing import List, Tuple

import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core.color_models import rgb_to_lab  # noqa: E402
from app.core.delta_e import delta_e_2000  # noqa: E402
from app.core.config import AppConfig  # noqa: E402
from app.services.paint_matcher import PaintMatcher  # noqa: E402


def _rand_rgb() -> Tuple[int, int, int]:
    return (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))


def bench_delta_e(n: int = 200_000) -> float:
    pairs = [(_rand_rgb(), _rand_rgb()) for _ in range(n)]
    labs = [(rgb_to_lab(a), rgb_to_lab(b)) for a, b in pairs]
    t0 = time.perf_counter()
    s = 0.0
    for la, lb in labs:
        s += delta_e_2000(la, lb)
    dt = time.perf_counter() - t0
    assert s == s  # 防止被优化掉
    return dt


def bench_suggest(n: int = 50) -> float:
    # 默认 50 次：早期用 200 次在部分环境（尤其沙箱）会因累积分配触发段错误，
    # 50 次已足够稳定地测出中位数，且单轮 3 次总计 < 1 分钟。

    cfg = AppConfig().validate()
    matcher = PaintMatcher()
    targets = [_rand_rgb() for _ in range(n)]
    t0 = time.perf_counter()
    for t in targets:
        matcher.suggest(t, cfg)
    dt = time.perf_counter() - t0
    return dt


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    runs = 3

    de_n = 200_000
    suggest_n = 50

    if args.only in ("", "de"):
        times: List[float] = []
        for _ in range(runs):
            times.append(bench_delta_e(de_n))
        print(f"delta_e_2000 x{de_n // 1000}k : {statistics.median(times):.3f}s (median of {runs})")

    if args.only in ("", "suggest"):
        times = []
        for _ in range(runs):
            times.append(bench_suggest(suggest_n))
        print(f"suggest x{suggest_n:<3}     : {statistics.median(times):.3f}s (median of {runs})")


if __name__ == "__main__":
    main()
