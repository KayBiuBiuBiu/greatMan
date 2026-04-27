from __future__ import annotations

def heat_score(
    likes: int = 0,
    comments: int = 0,
    collects: int = 0,
    shares: int = 0,
) -> float:
    """
    简单热度分：可自调权重。
    经验：评论与收藏往往比纯赞更能代表讨论度。
    """
    return (
        likes * 1.0
        + comments * 3.0
        + collects * 2.0
        + shares * 2.5
    )


def top_n(items: list[dict], n: int, key: str = "heat") -> list[dict]:
    sorted_items = sorted(
        [x for x in items if key in x],
        key=lambda x: float(x[key]),
        reverse=True,
    )
    return sorted_items[:n]
