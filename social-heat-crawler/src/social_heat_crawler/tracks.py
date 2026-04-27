"""预置「赛道」关键词，便于多轮子词覆盖一个垂类。"""

from __future__ import annotations

# 偏美食垂类；可按你所在城市/品类自行改小清单或改用 CLI 多关键词。
FOOD_KEYWORDS: list[str] = [
    "美食",
    "探店 美食",
    "必吃 美食",
    "小吃 美食",
    "甜品 探店",
    "火锅 探店",
]

TRACK_KEYWORDS: dict[str, list[str]] = {
    "food": FOOD_KEYWORDS,
}
