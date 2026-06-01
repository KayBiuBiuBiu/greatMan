import datetime as _dt
import html
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "config.json"
OUTPUTS = ROOT / "outputs"


def load_config():
    with CONFIG.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_html_report(exit_code, command, stdout, stderr):
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    report = OUTPUTS / "report.html"
    status = "PASS" if exit_code == 0 else "FAIL"
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    body = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>家庭聚会助手 Minium 测试报告</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 32px; }}
    .status {{ display: inline-block; padding: 6px 12px; border-radius: 8px; color: white; background: {'#18a058' if exit_code == 0 else '#d03050'}; }}
    pre {{ background: #f6f8fa; padding: 16px; overflow: auto; border-radius: 8px; }}
  </style>
</head>
<body>
  <h1>家庭聚会助手 Minium 测试报告</h1>
  <p>时间：{html.escape(now)}</p>
  <p>结果：<span class="status">{status}</span></p>
  <h2>命令</h2>
  <pre>{html.escape(" ".join(command))}</pre>
  <h2>标准输出</h2>
  <pre>{html.escape(stdout or "")}</pre>
  <h2>错误输出</h2>
  <pre>{html.escape(stderr or "")}</pre>
</body>
</html>
"""
    report.write_text(body, encoding="utf-8")
    print(f"[report] {report}")


def main():
    cfg = load_config()
    dev_tool_path = cfg.get("dev_tool_path", "")
    if not os.path.exists(dev_tool_path):
        print(
            f"[config] 微信开发者工具 CLI 不存在：{dev_tool_path}\n"
            "请修改 minium-tests/config.json 里的 dev_tool_path 后重试。",
            file=sys.stderr,
        )
        return 2

    OUTPUTS.mkdir(parents=True, exist_ok=True)
    command = [
    "minitest",
    "-m", "testcases",
    "-c", str(CONFIG),
    "-s", str(ROOT / "suite.json"),
    "-g"
    ]
    print("[run]", " ".join(command))
    proc = subprocess.run(command, cwd=str(ROOT), text=True, capture_output=True)
    print(proc.stdout)
    if proc.stderr:
        print(proc.stderr, file=sys.stderr)
    write_html_report(proc.returncode, command, proc.stdout, proc.stderr)
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
