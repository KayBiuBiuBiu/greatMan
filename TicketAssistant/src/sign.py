"""
大麦 / 阿里 mtop 签名。

常用算法（H5）：
  sign = MD5( token + "&" + t + "&" + appKey + "&" + data )
  其中 token 来自 Cookie `_m_h5_tk` 下划线前半段（形如 token_时间戳）。

若站点升级，可在 Chrome Sources 搜索 sign 对照 JS 后调整 `method` 或扩展本模块。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import urlencode

from .logger import setup_logger

logger = setup_logger(__name__)


def extract_mtop_token(cookie_value: str) -> str:
    """
    从 _m_h5_tk Cookie 值解析 token。
    示例: "e25xxx_1770000000000" -> "e25xxx"
    """
    if not cookie_value:
        return ""
    return cookie_value.split("_", 1)[0]


class MtopSigner:
    """mtop 请求签名生成器。"""

    def __init__(
        self,
        app_key: str = "12574478",
        method: str = "mtop_h5",
        secret: str = "",
        cookie_token_name: str = "_m_h5_tk",
    ):
        """
        :param app_key: mtop appKey
        :param method: mtop_h5 | params_md5 | hmac_sha256
        :param secret: params_md5 / hmac_sha256 使用的固定密钥（mtop_h5 从 Cookie 取 token，可不填）
        :param cookie_token_name: 存放 token 的 Cookie 名
        """
        self.app_key = app_key
        self.method = method
        self.secret = secret
        self.cookie_token_name = cookie_token_name

    @classmethod
    def from_config(cls, cfg: dict[str, Any], cookies: dict[str, str] | None = None) -> "MtopSigner":
        api = cfg.get("damai_api", {})
        sign_cfg = cfg.get("sign", {})
        signer = cls(
            app_key=str(sign_cfg.get("app_key") or api.get("app_key", "12574478")),
            method=str(sign_cfg.get("method", "mtop_h5")),
            secret=str(sign_cfg.get("secret", "")),
            cookie_token_name=str(sign_cfg.get("cookie_token_name", "_m_h5_tk")),
        )
        if cookies:
            signer._cookies = cookies
        return signer

    def token_from_cookies(self, cookies: dict[str, str]) -> str:
        raw = cookies.get(self.cookie_token_name, "")
        return extract_mtop_token(raw)

    def sign_mtop_h5(self, token: str, timestamp_ms: str, data: str) -> str:
        """阿里 H5 标准: MD5(token&t&appKey&data)。"""
        raw = f"{token}&{timestamp_ms}&{self.app_key}&{data}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def sign_params_md5(self, params: dict[str, Any], timestamp_ms: str) -> str:
        """参数按 key 排序拼接 + secret 后 MD5（部分旧接口）。"""
        merged = dict(params)
        merged["t"] = timestamp_ms
        parts = [f"{k}={merged[k]}" for k in sorted(merged.keys())]
        raw = "&".join(parts) + self.secret
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def sign_hmac_sha256(self, params: dict[str, Any], timestamp_ms: str) -> str:
        merged = dict(params)
        merged["t"] = timestamp_ms
        parts = [f"{k}={merged[k]}" for k in sorted(merged.keys())]
        message = "&".join(parts)
        return hmac.new(
            self.secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def sign(
        self,
        data: str,
        timestamp_ms: str,
        cookies: dict[str, str] | None = None,
        extra_params: dict[str, Any] | None = None,
    ) -> str:
        """
        按配置的 method 生成 sign。
        :param data: mtop data 字段（JSON 字符串，勿 URL 编码）
        """
        if self.method == "mtop_h5":
            cookies = cookies or {}
            token = self.token_from_cookies(cookies)
            if not token:
                logger.warning(
                    "Cookie 中无 %s，mtop 签名可能失败；请先登录或检查 cookies.json",
                    self.cookie_token_name,
                )
            return self.sign_mtop_h5(token, timestamp_ms, data)
        params = extra_params or {"data": data, "appKey": self.app_key}
        if self.method == "hmac_sha256":
            return self.sign_hmac_sha256(params, timestamp_ms)
        return self.sign_params_md5(params, timestamp_ms)

    def build_mtop_query(
        self,
        api: str,
        version: str,
        data_obj: dict[str, Any],
        cookies: dict[str, str] | None = None,
        jsv: str = "2.0",
    ) -> dict[str, str]:
        """
        生成 mtop GET 查询参数字典（含动态 t、sign）。
        """
        data = json.dumps(data_obj, separators=(",", ":"), ensure_ascii=False)
        t = str(int(time.time() * 1000))
        sign = self.sign(data, t, cookies=cookies)
        return {
            "jsv": jsv,
            "appKey": self.app_key,
            "t": t,
            "sign": sign,
            "api": api,
            "v": version,
            "data": data,
        }

    def build_mtop_url(
        self,
        base_url: str,
        api: str,
        version: str,
        data_obj: dict[str, Any],
        cookies: dict[str, str] | None = None,
    ) -> str:
        """拼装完整 mtop GET URL。"""
        params = self.build_mtop_query(api, version, data_obj, cookies=cookies)
        sep = "&" if "?" in base_url else "?"
        return f"{base_url}{sep}{urlencode(params)}"
