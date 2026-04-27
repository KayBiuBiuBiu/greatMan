from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SHT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    headless: bool = False
    # 与 `playwright codegen` 存登录态（桌面 Chrome）时一致需为 False。True=设备包模拟 iPhone，需与 save_login 移动版脚本配套。
    xhs_emulate_mobile: bool = False
    # 设备名见 Playwright 文档 / pw.chromium 的 devices 列表，如 iPhone 12, Pixel 5
    xhs_device: str = "iPhone 12"
    # 搜索页入口：部分环境带 source/sort 会 404「页面不见了」；见 xhs_crawler 多候选
    # minimal=仅 keyword | legacy=带 source | try_all=先极简再带 source/斜杠
    xhs_search_url_mode: str = "try_all"
    delay_min: float = 2.0
    delay_max: float = 8.0
    export_dir: Path = Path("data/exports")
    # 去重：已见笔记 MD5 指纹（由 fingerprints 模块读写）
    fingerprints_path: Path = Path("data/seen_fingerprints.json")
    storage_xhs: Path = Path("data/storage_state_xhs.json")
    storage_douyin: Path = Path("data/storage_state_douyin.json")
    # 抖音：导出子目录、搜索与发布（选择器为逗号分隔 CSS）
    douyin_export_subdir: str = "douyin"
    douyin_list_scroll: int = 4
    douyin_goto_timeout_ms: int = 90_000
    douyin_search_max_hrefs: int = 40
    # 创作者中心发布页（站点改版时改 .env）
    douyin_creator_upload_url: str = "https://creator.douyin.com/upload/"
    douyin_title_input_selectors: str = (
        "input[placeholder*='标题'],"
        "textarea[placeholder*='标题'],"
        "input[aria-label*='标题'],"
        "div[contenteditable='true'][data-placeholder*='标题']"
    )
    douyin_publish_delay_min: float = 0.3
    douyin_publish_delay_max: float = 1.0
    # 可选：持久化 user data 目录，减少重复登录
    user_data_dir: str | None = None
    # XHS_DEBUG=1 时保存失败页 HTML 的目录（见 selectors_xhs / README）
    debug_html_dir: Path = Path("data/debug")

    @property
    def export_path(self) -> Path:
        return self.export_dir

    @property
    def douyin_export_path(self) -> Path:
        return self.export_path / (self.douyin_export_subdir or "douyin")


def get_settings() -> Settings:
    return Settings()
