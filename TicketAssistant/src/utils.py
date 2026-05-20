"""通用工具：延迟、会话、通知。"""

import json
import random
import time
from pathlib import Path
from typing import Any

import requests

from .config import get_config
from .logger import setup_logger

logger = setup_logger(__name__)


def random_delay(min_seconds: float, max_seconds: float) -> None:
    """
    在指定秒数范围内随机休眠，模拟人类操作间隔。
    :param min_seconds: 最小秒数
    :param max_seconds: 最大秒数
    """
    if min_seconds > max_seconds:
        min_seconds, max_seconds = max_seconds, min_seconds
    delay = random.uniform(min_seconds, max_seconds)
    logger.debug("random_delay %.2fs", delay)
    time.sleep(delay)


class SessionManager:
    """基于 requests.Session 的会话管理，支持 Cookie 持久化。"""

    def __init__(self, cookies_path: str | None = None, user_agent: str | None = None):
        cfg = get_config()
        self.cookies_path = Path(cookies_path or cfg["cookies_path"])
        self.session = requests.Session()
        ua = user_agent or cfg.get("user_agent")
        if ua:
            self.session.headers.update({"User-Agent": ua})
        self.load_cookies()

    def load_cookies(self) -> bool:
        """从 cookies.json 加载 Cookie；文件不存在则保持新 Session。"""
        if not self.cookies_path.exists():
            logger.info("Cookie 文件不存在，使用新会话: %s", self.cookies_path)
            return False
        try:
            with open(self.cookies_path, "r", encoding="utf-8") as f:
                cookies = json.load(f)
            self.session.cookies.update(cookies)
            logger.info("已加载 Cookie: %s", self.cookies_path)
            return True
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("加载 Cookie 失败: %s", e)
            return False

    def save_cookies(self) -> None:
        """将当前会话 Cookie 保存到文件。"""
        cookies_dict = requests.utils.dict_from_cookiejar(self.session.cookies)
        self.cookies_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cookies_path, "w", encoding="utf-8") as f:
            json.dump(cookies_dict, f, ensure_ascii=False, indent=2)
        logger.info("Cookie 已保存: %s", self.cookies_path)

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        return self.session.get(url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> requests.Response:
        return self.session.post(url, **kwargs)

    def cookies_for_aiohttp(self) -> dict[str, str]:
        """供 aiohttp 使用的 Cookie 字典。"""
        return requests.utils.dict_from_cookiejar(self.session.cookies)


def send_notification(title: str, message: str) -> None:
    """
    通过 Server酱 或 Bark 发送手机通知（在 .env 中配置密钥）。
  任一成功即返回。
    """
    cfg = get_config()
    env = cfg.get("env", {})
    sct_key = env.get("sct_sendkey", "").strip()
    bark_url = env.get("bark_url", "").strip()

    sent = False
    if sct_key:
        try:
            resp = requests.post(
                f"https://sctapi.ftqq.com/{sct_key}.send",
                data={"title": title, "desp": message},
                timeout=10,
            )
            if resp.status_code == 200:
                logger.info("Server酱 通知已发送")
                sent = True
            else:
                logger.warning("Server酱 失败: %s %s", resp.status_code, resp.text[:200])
        except requests.RequestException as e:
            logger.warning("Server酱 请求异常: %s", e)

    if bark_url:
        try:
            base = bark_url.rstrip("/")
            resp = requests.get(
                f"{base}/{title}/{message}",
                timeout=10,
            )
            if resp.status_code == 200:
                logger.info("Bark 通知已发送")
                sent = True
            else:
                logger.warning("Bark 失败: %s", resp.status_code)
        except requests.RequestException as e:
            logger.warning("Bark 请求异常: %s", e)

    if not sent:
        logger.info("[通知未配置] %s — %s", title, message)
