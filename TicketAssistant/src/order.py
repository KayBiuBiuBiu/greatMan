"""下单模块：API（带 sign）或浏览器全自动。"""

from __future__ import annotations

import json
import threading
from typing import TYPE_CHECKING, Any

from .config import get_config
from .logger import setup_logger
from .sign import MtopSigner
from .utils import send_notification

if TYPE_CHECKING:
    from .browser_order import BrowserOrderManager
    from .utils import SessionManager

logger = setup_logger(__name__)


class OrderManager:
    """大麦下单：order_mode=api 走 mtop+sign；order_mode=browser 走 Selenium。"""

    def __init__(
        self,
        session_manager: "SessionManager",
        browser_order: "BrowserOrderManager | None" = None,
    ):
        self.session = session_manager
        self.browser_order = browser_order
        self.cfg = get_config()
        self._lock = threading.Lock()
        cookies = session_manager.cookies_for_aiohttp()
        self.signer = MtopSigner.from_config(self.cfg, cookies=cookies)

    @property
    def order_mode(self) -> str:
        return str(self.cfg.get("order_mode", "api")).lower()

    def place_order(self, sku_id: str) -> bool:
        if self.order_mode == "browser":
            if not self.browser_order:
                logger.error("order_mode=browser 但未注入 BrowserOrderManager")
                return False
            return self.browser_order.place_order(sku_id)

        return self._place_order_api(sku_id)

    def _place_order_api(self, sku_id: str) -> bool:
        """mtop 下单（需抓包确认 api 名与 data 字段）。"""
        with self._lock:
            logger.info("API 下单 skuId=%s …", sku_id)
            api_cfg = self.cfg.get("damai_api", {})
            base = api_cfg.get(
                "order_base_url",
                "https://mtop.damai.cn/h5/mtop.damai.wireless.order.build/1.0/",
            )
            api_name = api_cfg.get("order_api", "mtop.damai.wireless.order.build")
            version = api_cfg.get("order_version", "1.0")
            item_id = str(self.cfg.get("item_id", ""))

            data_obj: dict[str, Any] = {
                "itemId": item_id,
                "skuId": sku_id,
                "buyNum": 1,
            }
            extra = api_cfg.get("order_data_extra")
            if isinstance(extra, dict):
                data_obj.update(extra)

            cookies = self.session.cookies_for_aiohttp()
            params = self.signer.build_mtop_query(
                api_name, version, data_obj, cookies=cookies
            )

            try:
                resp = self.session.post(
                    base,
                    params=params,
                    timeout=15,
                )
                body: Any = {}
                try:
                    body = resp.json()
                except Exception:
                    body = {"raw": resp.text[:500]}

                if body.get("ret") and "SUCCESS" in str(body.get("ret")):
                    msg = f"API 下单成功 skuId={sku_id}"
                    logger.info(msg)
                    send_notification("抢票成功", msg)
                    return True

                err = f"API 下单失败 {body}"
                logger.error(err)
                send_notification("抢票失败", err[:500])
                return False
            except Exception as e:
                err = f"API 下单异常: {e}"
                logger.exception(err)
                send_notification("抢票异常", err[:500])
                return False

    def place_order_async(self, sku_id: str) -> None:
        t = threading.Thread(
            target=self.place_order,
            args=(sku_id,),
            name=f"order-{sku_id}",
            daemon=True,
        )
        t.start()
        logger.info("已在后台线程启动下单 (%s): %s", self.order_mode, sku_id)
