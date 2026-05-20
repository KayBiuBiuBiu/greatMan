"""票务监控：异步高频轮询大麦接口。"""

import asyncio
import json
from typing import TYPE_CHECKING, Any, Callable

import aiohttp

from .config import get_config
from .logger import setup_logger
from .sign import MtopSigner
from .utils import random_delay

if TYPE_CHECKING:
    from .order import OrderManager
    from .utils import SessionManager

logger = setup_logger(__name__)


class TicketMonitor:
    """异步监控目标演出库存，有票时触发下单。"""

    def __init__(
        self,
        session_manager: "SessionManager",
        order_manager: "OrderManager | None" = None,
        on_ticket_found: Callable[[str, int], None] | None = None,
    ):
        self.session = session_manager
        self.order_manager = order_manager
        self.on_ticket_found = on_ticket_found
        self.cfg = get_config()
        self._running = False
        self._ordered = False
        cookies = session_manager.cookies_for_aiohttp()
        self.signer = MtopSigner.from_config(self.cfg, cookies=cookies)

    def _item_api_config(self) -> tuple[str, str, str]:
        api_cfg = self.cfg.get("damai_api", {})
        base = api_cfg.get(
            "base_url",
            "https://mtop.damai.cn/h5/mtop.damai.wireless.item.get/1.0/",
        )
        api_name = api_cfg.get("api", "mtop.damai.wireless.item.get")
        version = api_cfg.get("version", "1.0")
        return base, api_name, version

    def _build_api_url(self) -> str:
        """使用 sign 模块动态生成 t、sign。"""
        base, api_name, version = self._item_api_config()
        item_id = str(self.cfg.get("item_id", ""))
        cookies = self.session.cookies_for_aiohttp()
        return self.signer.build_mtop_url(
            base,
            api_name,
            version,
            {"itemId": item_id},
            cookies=cookies,
        )

    def _parse_inventory(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        skus: list[dict[str, Any]] = []
        target_price = float(self.cfg.get("target_price", 0))

        payload = data
        if "data" in payload and isinstance(payload["data"], dict):
            inner = payload["data"]
            if "result" in inner:
                try:
                    payload = (
                        json.loads(inner["result"])
                        if isinstance(inner["result"], str)
                        else inner["result"]
                    )
                except (json.JSONDecodeError, TypeError):
                    payload = inner
            else:
                payload = inner

        sku_list = (
            payload.get("skuList")
            or payload.get("skuListVO", {}).get("skuList")
            or payload.get("perform", {}).get("skuList")
            or []
        )
        if not isinstance(sku_list, list):
            return skus

        for sku in sku_list:
            if not isinstance(sku, dict):
                continue
            price_raw = sku.get("price") or sku.get("priceName", "0")
            try:
                price = float(str(price_raw).replace("元", "").replace("¥", "").strip())
            except ValueError:
                price = 0.0
            if target_price > 0 and abs(price - target_price) > 0.01:
                continue
            sku_id = str(sku.get("skuId") or sku.get("sku_id") or "")
            inv = int(
                sku.get("inventory")
                or sku.get("salableQuantity")
                or sku.get("stock", 0)
            )
            if sku_id:
                skus.append({"sku_id": sku_id, "price": price, "inventory": inv})
        return skus

    async def _fetch_once(self, session: aiohttp.ClientSession) -> list[dict[str, Any]]:
        url = self._build_api_url()
        headers = {"User-Agent": self.cfg.get("user_agent", "")}
        try:
            async with session.get(
                url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                text = await resp.text()
                data = json.loads(text)
                ret = data.get("ret")
                if ret and "SUCCESS" not in str(ret):
                    logger.warning("接口返回: %s", ret)
                    if "FAIL_SYS_TOKEN" in str(ret) or "ILLEGAL" in str(ret):
                        logger.warning("sign/token 可能失效，请重新登录或检查 sign.method")
                return self._parse_inventory(data)
        except asyncio.TimeoutError:
            logger.warning("请求超时")
        except (aiohttp.ClientError, json.JSONDecodeError) as e:
            logger.warning("请求或解析失败: %s", e)
        return []

    def _trigger_order(self, sku_id: str, inventory: int) -> None:
        logger.info("🎫 发现余票 skuId=%s inventory=%s", sku_id, inventory)
        mode = self.cfg.get("order_mode", "api")
        logger.info("下单模式: %s", mode)

        if self.on_ticket_found:
            self.on_ticket_found(sku_id, inventory)
        elif self.order_manager:
            self.order_manager.place_order_async(sku_id)
        else:
            logger.error("未配置 OrderManager，无法下单")

    async def _monitor_loop(self) -> None:
        interval = self.cfg.get("query_interval", [1, 3])
        lo, hi = float(interval[0]), float(interval[1])
        cookies = self.session.cookies_for_aiohttp()
        cookie_jar = aiohttp.CookieJar()
        for k, v in cookies.items():
            cookie_jar.update_cookies({k: v})

        async with aiohttp.ClientSession(cookie_jar=cookie_jar) as http:
            while self._running:
                if self._ordered:
                    logger.info("已触发下单，监控结束（单票策略）")
                    break

                skus = await self._fetch_once(http)
                for sku in skus:
                    logger.debug(
                        "sku %s price=%s inv=%s",
                        sku["sku_id"],
                        sku["price"],
                        sku["inventory"],
                    )
                    if sku["inventory"] > 0:
                        self._ordered = True
                        self._trigger_order(sku["sku_id"], sku["inventory"])
                        break

                await asyncio.to_thread(random_delay, lo, hi)

    def start_monitor(self, block: bool = True) -> None:
        self._running = True
        self._ordered = False
        logger.info(
            "开始监控 item_id=%s target_price=%s sign=%s",
            self.cfg.get("item_id"),
            self.cfg.get("target_price"),
            self.signer.method,
        )

        async def _run():
            try:
                await self._monitor_loop()
            except asyncio.CancelledError:
                logger.info("监控任务已取消")

        if block:
            try:
                asyncio.run(_run())
            except KeyboardInterrupt:
                self.stop()
        else:
            return _run()

    def stop(self) -> None:
        self._running = False
        logger.info("监控已停止")
