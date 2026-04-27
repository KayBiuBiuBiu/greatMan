import random
import time


def human_delay(smin: float, smax: float) -> None:
    """模拟人类操作间隔（秒）。"""
    t = random.uniform(smin, smax)
    time.sleep(t)


def jitter_ms(base: int, spread: int = 400) -> int:
    return max(0, base + random.randint(-spread, spread))
