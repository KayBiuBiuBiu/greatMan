"""
抖音（PC 网页）选择器，站点常改版，请用 DevTools 对真实页面增删行。
"""

from __future__ import annotations

# 搜索列表：视频 / 作品详情链接
VIDEO_LINK_SELECTORS: list[str] = [
    'a[href*="/video/"]',
    'a[href*="douyin.com/video/"]',
    'li a[href*="/video/"]',
    'div[class*="search"] a[href*="/video/"]',
    'div[class*="result"] a[href*="/video/"]',
]

# 视频详情页：标题
DETAIL_TITLE_SELECTORS: list[str] = [
    "h1",
    "h1[data-e2e]",
    "span[data-e2e='video-title']",
    "div[class*='title'] h1",
    "div.video-info h1",
]

# 描述 / 文案
DETAIL_DESC_SELECTORS: list[str] = [
    "div[class*='desc']",
    "div[data-e2e='video-desc']",
    "span[data-e2e='video-desc']",
    "div.video-info p",
]

LIKE_TEXT_SELECTORS: list[str] = [
    "span[data-e2e='like-count']",
    "div[class*='like'] span",
    "button[aria-label*='赞'] + span",
]

COMMENT_TEXT_SELECTORS: list[str] = [
    "span[data-e2e='comment-count']",
    "div[class*='comment'] span",
]

# 分享 / 收藏（参与热度时可在业务里用 shares/collects）
SHARE_TEXT_SELECTORS: list[str] = [
    "span[data-e2e='share-count']",
    "div[class*='share'] span",
]

COLLECT_TEXT_SELECTORS: list[str] = [
    "span[data-e2e='collect-count']",
    "div[class*='fav'] span",
    "div[class*='collect'] span",
]

IMG_SELECTORS: list[str] = [
    "div[class*='player'] img",
    "div[class*='video'] img",
    "img[src*='p3-pc']",
    "img[src*='p9-pc']",
    "img[src*='douyinpic.com']",
    "picture img",
    "main img",
]
