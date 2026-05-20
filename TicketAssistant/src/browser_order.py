"""
浏览器全自动下单（Selenium）。

不逆向 sign，在真实浏览器环境中点击「购买 → 选票档 → 提交」。
比纯 API 慢约 2–3 秒，但稳定性更好。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import undetected_chromedriver as uc
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .config import get_config
from .logger import setup_logger
from .utils import random_delay, send_notification

if TYPE_CHECKING:
    from .utils import SessionManager

logger = setup_logger(__name__)


class BrowserOrderManager:
    """使用 undetected-chromedriver 模拟大麦购票流程。"""

    def __init__(self, session_manager: "SessionManager | None" = None):
        self.session = session_manager
        self.cfg = get_config()
        self.sel = self.cfg.get("browser_order", {}).get("selectors", {})

    def _load_cookies_into_driver(self, driver) -> None:
        """将 cookies.json 注入浏览器（需先打开同域页面）。"""
        path = Path(self.cfg.get("cookies_path", "cookies.json"))
        if not path.exists() and self.session:
            path = Path(self.session.cookies_path)
        if not path.exists():
            logger.warning("无 Cookie 文件，浏览器可能未登录")
            return
        with open(path, "r", encoding="utf-8") as f:
            cookies = json.load(f)
        for name, value in cookies.items():
            try:
                driver.add_cookie(
                    {
                        "name": name,
                        "value": value,
                        "domain": ".damai.cn",
                        "path": "/",
                    }
                )
            except Exception:
                pass

    def _click_first_match(self, driver, wait: WebDriverWait, selectors: list[str]) -> bool:
        for css in selectors:
            if not css:
                continue
            try:
                el = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, css)))
                el.click()
                return True
            except TimeoutException:
                continue
        return False

    def _click_price_tier(self, driver, wait: WebDriverWait, target_price: float) -> bool:
        """点击包含目标票价的票档（文本匹配）。"""
        price_text = str(int(target_price)) if target_price == int(target_price) else str(target_price)
        xpaths = [
            f"//*[contains(@class,'sku') and contains(.,'{price_text}')]",
            f"//*[contains(@class,'perform') and contains(.,'{price_text}')]",
            f"//*[contains(text(),'{price_text}') and contains(text(),'元')]",
            f"//*[contains(text(),'¥{price_text}')]",
        ]
        cfg_xpath = self.sel.get("price_tier_xpath")
        if cfg_xpath:
            xpaths.insert(0, cfg_xpath.format(price=price_text))

        for xp in xpaths:
            try:
                el = wait.until(EC.element_to_be_clickable((By.XPATH, xp)))
                el.click()
                logger.info("已选票档: %s", price_text)
                return True
            except TimeoutException:
                continue
        return False

    def place_order(self, sku_id: str = "") -> bool:
        """
        启动浏览器完成购票流程。
        :param sku_id: API 模式下的 skuId；浏览器模式主要按 target_price 点选
        """
        target_url = self.cfg.get("target_url", "")
        if not target_url:
            logger.error("请配置 target_url")
            return False

        target_price = float(self.cfg.get("target_price", 0))
        wait_sec = int(self.cfg.get("browser_order", {}).get("wait_timeout", 15))
        headless = bool(self.cfg.get("browser_order", {}).get("headless", False))

        buy_selectors = self.sel.get("buy_button", "").split(",") if self.sel.get("buy_button") else []
        if not buy_selectors:
            buy_selectors = [
                ".buy__button",
                ".buybtn",
                "button.buy-btn",
                "[class*='buyButton']",
            ]

        confirm_selectors = self.sel.get("confirm_button", "").split(",") if self.sel.get("confirm_button") else []
        if not confirm_selectors:
            confirm_selectors = [
                ".submit-button",
                "button[type='submit']",
                "[class*='submit']",
            ]

        submit_selectors = self.sel.get("submit_order", "").split(",") if self.sel.get("submit_order") else []
        if not submit_selectors:
            submit_selectors = confirm_selectors + [
                "//button[contains(.,'提交订单')]",
                "//button[contains(.,'立即提交')]",
            ]

        driver = None
        try:
            logger.info("🌐 启动浏览器下单（skuId=%s）…", sku_id or "-")
            options = uc.ChromeOptions()
            if headless:
                options.add_argument("--headless=new")
            options.add_argument("--start-maximized")

            driver = uc.Chrome(options=options)
            driver.get("https://www.damai.cn/")
            time.sleep(1)
            self._load_cookies_into_driver(driver)

            driver.get(target_url)
            wait = WebDriverWait(driver, wait_sec)
            random_delay(0.5, 1.0)

            # 1. 立即购买 / 选座购买
            if not self._click_first_match(driver, wait, buy_selectors):
                # 尝试按文案
                try:
                    wait.until(EC.element_to_be_clickable((By.PARTIAL_LINK_TEXT, "立即购买"))).click()
                except TimeoutException:
                    try:
                        wait.until(EC.element_to_be_clickable((By.PARTIAL_LINK_TEXT, "购买"))).click()
                    except TimeoutException:
                        raise RuntimeError("未找到「购买」按钮，请在 config.yaml 配置 browser_order.selectors")

            random_delay(0.8, 1.5)

            # 2. 选票档
            if target_price > 0:
                if not self._click_price_tier(driver, wait, target_price):
                    logger.warning("未自动匹配到票档 %.0f，请检查页面结构或 selectors", target_price)

            random_delay(0.5, 1.0)

            # 3. 确定 / 下一步
            self._click_first_match(driver, wait, confirm_selectors)
            try:
                wait.until(EC.element_to_be_clickable((By.PARTIAL_LINK_TEXT, "确定"))).click()
            except TimeoutException:
                pass

            random_delay(0.5, 1.0)

            # 4. 提交订单
            clicked = False
            for sel in submit_selectors:
                if sel.startswith("//"):
                    try:
                        wait.until(EC.element_to_be_clickable((By.XPATH, sel))).click()
                        clicked = True
                        break
                    except TimeoutException:
                        continue
                elif sel:
                    if self._click_first_match(driver, wait, [sel]):
                        clicked = True
                        break
            if not clicked:
                try:
                    wait.until(EC.element_to_be_clickable((By.PARTIAL_LINK_TEXT, "提交订单"))).click()
                except TimeoutException:
                    logger.warning("未找到「提交订单」，请手动在浏览器中完成最后一步")

            random_delay(1.0, 2.0)
            msg = f"浏览器下单流程已执行 skuId={sku_id or 'n/a'}，请确认订单页是否成功"
            logger.info(msg)
            send_notification("抢票助手-浏览器下单", msg)

            # 保存最新 Cookie
            if self.session:
                cookies = {c["name"]: c["value"] for c in driver.get_cookies()}
                self.session.session.cookies.update(cookies)
                self.session.save_cookies()

            return True
        except Exception as e:
            err = f"浏览器下单失败: {e}"
            logger.exception(err)
            send_notification("抢票失败-浏览器", str(e)[:500])
            return False
        finally:
            if driver:
                keep_open = self.cfg.get("browser_order", {}).get("keep_browser_open", True)
                if keep_open:
                    logger.info("浏览器保持打开，便于手动支付；关闭窗口后脚本继续")
                    try:
                        input("按 Enter 关闭浏览器…")
                    except EOFError:
                        pass
                try:
                    driver.quit()
                except Exception:
                    pass

    def place_order_async(self, sku_id: str = "") -> None:
        import threading

        threading.Thread(
            target=self.place_order,
            args=(sku_id,),
            name="browser-order",
            daemon=True,
        ).start()
