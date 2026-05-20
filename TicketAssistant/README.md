# TicketAssistant 抢票助手

Python 大麦网抢票辅助脚本（学习 / 自用）。**扫码登录 + Cookie 复用 + 异步监控 + 多线程下单**。

## 项目结构

```
TicketAssistant/
├── requirements.txt
├── .env.example
├── config.yaml
├── main.py
├── src/
│   ├── config.py
│   ├── logger.py
│   ├── utils.py
│   ├── login.py
│   ├── monitor.py
│   └── order.py
└── logs/
```

## 快速开始

```bash
cd TicketAssistant
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # 可选：配置通知密钥
```

编辑 `config.yaml`：

- `target_url` / `item_id`：目标演出
- `target_price`：目标票价
- `damai_api`：**务必根据浏览器抓包更新 sign、完整 query**

运行：

```bash
python main.py
```

首次或 Cookie 失效时会打开 Chrome，**手动扫码登录**；成功后 Cookie 写入 `cookies.json`。

## 两种下单策略

| 模式 | 配置 | 说明 |
|------|------|------|
| **api** | `order_mode: api` | `src/sign.py` 按阿里 mtop H5 规则生成 sign（`MD5(token&t&appKey&data)`，token 来自 `_m_h5_tk` Cookie） |
| **browser** | `order_mode: browser` | `src/browser_order.py` 用 Selenium 点击购票，**无需逆向 sign**，慢约 2–3 秒 |

监控始终走 **API + 动态 sign**（有票时更快）；仅「下单」步骤随 `order_mode` 切换。

### sign 进阶

若 `mtop_h5` 失效，可在 Chrome Sources 搜索 `sign` 对照 JS，将 `config.yaml` 中 `sign.method` 改为 `params_md5` 或 `hmac_sha256` 并填写 `sign.secret`。

## 说明

- 登录后 Cookie 须含 `_m_h5_tk`，否则 API 签名失败。
- `damai_api.order_*` 字段需按抓包更新。
- 请遵守平台服务条款，合理设置 `query_interval`。

## 通知

在 `.env` 中配置其一：

- `SCT_SENDKEY`：Server酱
- `BARK_URL`：Bark 推送地址
