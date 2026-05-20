#!/usr/bin/env python3
"""
抢票助手入口。
用法: python main.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.browser_order import BrowserOrderManager
from src.config import get_config
from src.logger import setup_logger
from src.login import LoginManager
from src.monitor import TicketMonitor
from src.order import OrderManager
from src.utils import SessionManager


def main() -> int:
    cfg = get_config()
    log = setup_logger(level=cfg.get("log_level", "INFO"))
    mode = cfg.get("order_mode", "api")
    log.info("TicketAssistant 启动 | 下单模式=%s", mode)

    session = SessionManager()
    login_mgr = LoginManager(session)

    try:
        if not login_mgr.login():
            log.error("登录失败，退出")
            return 1

        browser_order = BrowserOrderManager(session) if mode == "browser" else None
        order_mgr = OrderManager(session, browser_order=browser_order)
        monitor = TicketMonitor(session, order_manager=order_mgr)
        monitor.start_monitor(block=True)
        return 0
    except KeyboardInterrupt:
        log.info("用户中断，正在退出…")
        return 0
    except Exception as e:
        log.exception("运行异常: %s", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
