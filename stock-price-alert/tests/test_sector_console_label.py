"""控制台板块标签：申万一级中文名。"""

from __future__ import annotations

from pathlib import Path

from sector_em import format_sector_console_line, sw_l1_display_name


def test_sw_l1_display_name(tmp_path: Path) -> None:
    names = tmp_path / "data" / "sw_l1_names.json"
    names.parent.mkdir(parents=True)
    names.write_text(
        '{"801080.SI": "电子", "801890.SI": "机械设备"}',
        encoding="utf-8",
    )
    assert sw_l1_display_name("801080.SI", root=tmp_path) == "电子"
    assert sw_l1_display_name("801999.SI", root=tmp_path) == "801999.SI"


def test_format_sector_console_line_from_pack(tmp_path: Path) -> None:
    names = tmp_path / "data" / "sw_l1_names.json"
    names.parent.mkdir(parents=True)
    names.write_text('{"801080.SI": "电子"}', encoding="utf-8")
    cfg: dict = {}
    pack = {"sector_bk": "801080.SI", "rule": {"market": "sz"}}
    line = format_sector_console_line("300077", cfg, root=tmp_path, pack=pack)
    assert line == "      └ 板块：电子（申万一级）"


def test_format_sector_console_line_unresolved(tmp_path: Path) -> None:
    line = format_sector_console_line("999999", {}, root=tmp_path, pack={})
    assert "未解析" in line


def test_resolve_sector_bk_tushare_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sector_em as sem

    monkeypatch.setattr(
        sem,
        "_resolve_sw_via_tushare",
        lambda code6, market, cfg: "801050.SI",
    )
    cfg: dict = {"sources": {"tushare": {"enabled": True}}}
    sw = sem.resolve_sector_bk("600711", "sh", cfg, root=tmp_path)
    assert sw == "801050.SI"
    cache_path = tmp_path / "sector_index_cache.json"
    sem._save_cache_file(
        cache_path,
        {"version": 2, "by_code": {}},
    )
    monkeypatch.setattr(
        sem,
        "_cache_path",
        lambda cfg, root: cache_path,
    )
    sw2 = sem.resolve_sector_bk("600711", "sh", cfg, root=tmp_path)
    assert sw2 == "801050.SI"
