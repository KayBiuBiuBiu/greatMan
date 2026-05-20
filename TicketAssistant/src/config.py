"""配置加载：config.yaml + .env 环境变量。"""

from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
import os

# 项目根目录
ROOT_DIR = Path(__file__).resolve().parent.parent
_CONFIG_CACHE: dict[str, Any] | None = None


def _load_yaml() -> dict[str, Any]:
    config_path = ROOT_DIR / "config.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data


def get_config(reload: bool = False) -> dict[str, Any]:
    """
    获取合并后的配置（yaml + 环境变量）。
    敏感信息从 .env 读取，键名见 .env.example。
    """
    global _CONFIG_CACHE
    if _CONFIG_CACHE is not None and not reload:
        return _CONFIG_CACHE

    load_dotenv(ROOT_DIR / ".env")
    cfg = _load_yaml()

    # 环境变量覆盖 / 补充
    cfg["env"] = {
        "damai_username": os.getenv("DAMAI_USERNAME", ""),
        "damai_password": os.getenv("DAMAI_PASSWORD", ""),
        "sct_sendkey": os.getenv("SCT_SENDKEY", ""),
        "bark_url": os.getenv("BARK_URL", ""),
    }

    cfg["cookies_path"] = str(ROOT_DIR / cfg.get("cookies_file", "cookies.json"))
    _CONFIG_CACHE = cfg
    return cfg
