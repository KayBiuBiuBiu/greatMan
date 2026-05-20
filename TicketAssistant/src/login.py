"""登录模块：扫码登录 + Cookie 复用。"""

import time
from typing import TYPE_CHECKING

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .config import get_config
from .logger import setup_logger

if TYPE_CHECKING:
    from .utils import SessionManager

logger = setup_logger(__name__)


class LoginManager:
    """大麦网登录：优先复用 Cookie，否则打开浏览器等待扫码。"""

    def __init__(self, session_manager: "SessionManager"):
        self.session = session_manager
        self.cfg = get_config()

    def _is_logged_in(self, driver) -> bool:
        """根据页面元素判断是否已登录。"""
        try:
            # 常见：顶部「我的」、用户昵称等
            for selector in [
                (By.PARTIAL_LINK_TEXT, "我的"),
                (By.CSS_SELECTOR, "[class*='user-name']"),
                (By.CSS_SELECTOR, "[class*='login-out']"),
            ]:
                if driver.find_elements(*selector):
                    return True
        except Exception:
            pass
        url = driver.current_url or ""
        # 仍在详情页且非登录页，视为可能已登录
        target = self.cfg.get("target_url", "")
        if target and "detail.damai.cn" in url and "login" not in url.lower():
            return True
        return False

    def _is_login_page(self, driver) -> bool:
        url = (driver.current_url or "").lower()
        return "login" in url or "passport" in url

    def _cookies_from_driver(self, driver) -> dict:
        cookies = {}
        for c in driver.get_cookies():
            cookies[c["name"]] = c["value"]
        return cookies

    def login(self) -> bool:
        """
        执行登录流程。
        :return: 是否成功取得有效 Cookie
        """
        target_url = self.cfg.get("target_url", "")
        if not target_url:
            logger.error("请在 config.yaml 中配置 target_url")
            return False

        # 已有 Cookie 时先尝试复用
        if self.session.cookies_path.exists():
            logger.info("检测到本地 Cookie 文件，尝试复用…")
            self.session.load_cookies()
            # 简单校验：访问目标页看是否被重定向到登录
            try:
                resp = self.session.get(target_url, timeout=15, allow_redirects=True)
                if resp.status_code == 200 and "login" not in resp.url.lower():
                    logger.info("✅ 已登录，复用 Cookie（无需扫码）")
                    return True
            except Exception as e:
                logger.warning("Cookie 校验请求失败: %s", e)

        logger.info("需要扫码登录，正在打开浏览器…")
        options = uc.ChromeOptions()
        options.add_argument("--start-maximized")
        driver = None
        try:
            driver = uc.Chrome(options=options)
            driver.get(target_url)
            time.sleep(2)

            if self._is_logged_in(driver) and not self._is_login_page(driver):
                logger.info("✅ 页面已是登录状态，直接获取 Cookie")
            else:
                logger.info("请在浏览器中完成扫码登录，等待最多 120 秒…")
                wait = WebDriverWait(driver, 120)
                wait.until(
                    lambda d: self._is_logged_in(d) and not self._is_login_page(d)
                )

            cookies = self._cookies_from_driver(driver)
            self.session.session.cookies.update(cookies)
            self.session.save_cookies()
            logger.info("✅ 扫码登录成功，Cookie 已保存")
            return True
        except Exception as e:
            logger.error("登录失败: %s", e)
            return False
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass
                logger.info("浏览器已关闭")
