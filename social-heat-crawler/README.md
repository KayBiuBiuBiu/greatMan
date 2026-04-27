# Social Heat Assistant（个人向）

个人学习/涨粉尝试用的小型工具：用**浏览器自动化（Playwright）**按关键词拉取高互动内容、计算**热度分**、取 Top5，并**不直接原样搬运**——将素材与文案存盘，供你**二次编辑后再**走半自动/手动发布，降低平台规则与封禁风险。

> **合规与责任**  
> - 使用须遵守《用户协议》与《网络安全法》等。自动化可能违反平台服务条款。  
> - 本项目不规避验证码、不破解非公开 API，仅供本地学习与个人非商业使用。  
> - **禁止** 批量搬运、侵权、自动化垃圾行为；发布前请**二次创作**并保留素材来源意识。

## 整体架构

```
                    ┌──────────────────┐
  关键词/配置 ─────▶│  run_crawl.py   │
                    └────────┬─────────┘
                             │ Playwright + 已保存登录态
                             ▼
                    ┌──────────────────┐
     开源思路参考  │ crawlers（xhs / douyin）│
     MediaCrawler  │  搜索→列表→详情  │
                    └────────┬─────────┘
                             ▼
                    ┌──────────────────┐
                    │    scoring      │  热度分 = f(赞/评/藏…)
                    └────────┬─────────┘
                             ▼
                    ┌──────────────────┐
                    │ storage/exports │  JSON + 本地下载的图/封图
                    └────────┬─────────┘
                             ▼
              你改文案/改图后 ──▶ run_prepare_publish.py
                             │ Playwright 打开发布页
                             ▼
                    半自动：本地上传，或完全手动
```

- **爬取层**：`playwright` 打开已登录的浏览器态（`storage_state.json`），模拟人类：随机 `delay`、滚动。  
- **数据层**：结构化 JSON + 媒体落盘。  
- **发布层**：**默认不**自动发成品（避免一键搬运），而是打开创作者中心上传页/提示路径；你可先跑 `run_rewrite_text.py`（仅示例）或自行编辑后再发。

## 环境要求

- Python **3.10+**
- 已安装 **Chromium**（由 Playwright 管理）

## 安装

```bash
cd social-heat-crawler
python3.10 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -U pip
pip install -r requirements.txt
playwright install chromium
```

## Cookie / 登录态

**推荐**：在脚本里**首次用有头模式登录一次**，把状态存成文件，以后复用。

> **默认与 `playwright codegen` 一致**  
> `run_crawl` 默认 `SHT_XHS_EMULATE_MOBILE=0`（**桌面 Chrome 环境**），与用 Codegen 保存的 `storage_state_xhs.json` 同构，减少「页面不见了」与假未登录。若用 **`save_login_state.py`（脚本是移动 UA）** 存登录，请设 **`SHT_XHS_EMULATE_MOBILE=1`**。只改一个开关，**保存与爬取必须同档**。  
> 若强推仅手机、下载 App 等，再改 `1` 或只跑 `save_login_state`。发布页 `run_prepare_publish` 为桌面 UA。  
> **系统权限条**（如「访问此设备上的其他应用」）：可点 **屏蔽**；不依赖点「允许」；脚本已用少量 Chromium 启动参数降低弹窗。  
> **若搜索仍 404**：会先试首页再进搜索；可设 `SHT_XHS_SEARCH_URL_MODE=minimal`；并确认登录未过期、少 VPN/频控。

1. 运行：  
   `python scripts/save_login_state.py --platform xiaohongshu`  
2. 在弹出的浏览器里**手动**登录。  
3. 关闭浏览器或按提示保存后，生成 `data/storage_state_xhs.json`（路径见 `config`）。

**可选（更简单、省空间）——用官方 Codegen 在桌面版里登一次**  
只装 Chromium、不用 `--device`，在**桌面版**里扫码登录，关窗即把 Cookie 等写入 `storage_state`：

```bash
# 已 pip install playwright 后，仅下载 Chromium（比 install 全量小）
playwright install chromium

# 项目根在 social-heat-crawler 时，路径用相对或绝对均可
playwright codegen --save-storage=data/storage_state_xhs.json https://www.xiaohongshu.com
```

在弹窗里点右上角「登录」→ 扫码成功 → 关闭 Codegen 窗口，即会生成/更新 `data/storage_state_xhs.json`。  
**重要**：与上述默认一致——**不要**在 `.env` 里开 `SHT_XHS_EMULATE_MOBILE=1`（否则与 Codegen 桌面态冲突）。若你改用手机脚本 `save_login_state.py` 存，再设 **`SHT_XHS_EMULATE_MOBILE=1`**。

> 从浏览器开发者工具**复制 Cookie 字符串**也可注入，但各站格式差异大，维护成本高；Playwright 的 `storage_state` 最稳。

**降低风控建议**

- 单个账号、低频率、**随机 2–8s** 间延时；少并发。  
- 不 24/7 跑。  
- 发内容前**必**二次创作，本项目鼓励「下载→本地改→再发」。

## 如何运行

```bash
# 1)（首次）保存登录
# 抖音（默认，见 --platform）——生成 data/storage_state_douyin.json
python scripts/save_login_state.py --platform douyin

# 或小红书——生成 data/storage_state_xhs.json
python scripts/save_login_state.py --platform xiaohongshu

# 2) 按关键词爬取 + 算分 + Top5 导出
# 抖音：搜索 www.douyin.com/search/关键词，抓 /video/ 详情（默认 --platform douyin）
python scripts/run_crawl.py --platform douyin --keyword "旅行" --top 5

# 小红书
python scripts/run_crawl.py --platform xiaohongshu --keyword "旅行" --top 5

# 2b) 美食垂类（仅小红书有 food pack）：多子关键词 + 尝试「最热」+ 去重
python scripts/run_crawl.py --platform xiaohongshu --food-pack --search-sort hot --top 5

# 3) 对 Top 文案做简单同义替换示例（可改为调用你自己的大模型 API）
python scripts/run_rewrite_text.py

# 4) 半自动发：抖音或小红书（需对应 storage_state_*.json）
python scripts/crawl_douyin.py --keyword 旅行 --min-likes 0 --top 5
python scripts/run_prepare_publish.py --platform xiaohongshu
python scripts/run_prepare_publish.py --platform douyin
```

在 **zsh** 里从文档里复制带 `#` 开头的说明行时，若整行是 `# 中文…`，可能报 `command not found: #`（需 `setopt interactivecomments` 才当注释）。**只复制不含 `#` 的命令行即可。** 若 `crawl_douyin` 得到 `count=0` / `items` 为空，可降 `--min-likes` 重试；发抖音时可用 `python scripts/run_prepare_publish.py --platform douyin --title "你的标题"`。

### 浪姐：先爬抖音再发小红书（一键）

项目**不能**把抖音里的短视频文件自动搬家发布；`run_prepare_publish` 发的是**图文笔记**（标题/摘要 + 本地**封面图**），适合二创。需要**两套登录态**：`storage_state_douyin.json`（爬）+ `storage_state_xhs.json`（发）。

```bash
# 1) 两个平台各保存一次登录（各跑一遍，按提示扫码/登录）
python scripts/save_login_state.py --platform douyin
python scripts/save_login_state.py --platform xiaohongshu

# 2) 一键：多关键词搜「浪姐/乘风破浪…」→ 取 Top5 → 把 Top1 发到小红书
python scripts/flow_langjie_douyin_to_xhs.py

# 发第 2 条、或只发不重爬、或只填不点发布：
python scripts/flow_langjie_douyin_to_xhs.py --item-index 2
python scripts/flow_langjie_douyin_to_xhs.py --skip-crawl
python scripts/flow_langjie_douyin_to_xhs.py --manual
```

若要把**自己电脑上的视频**发到抖音（非自动扒链），可用已登录态打开发布页再手动上传：

```bash
python scripts/open_douyin_creator.py
```

抖音爬取为 **PC 站 + 你保存的 `storage_state_douyin` 同环境**；站点常有改版，若选不中链接请改 `crawlers/selectors_douyin.py`。热度分含**分享**（`shares`），`export_ops` 中字段与小红书条目共存。

输出目录默认：`data/exports/`，含 `crawl_result.json` 与每条目的 `media/`。

- **垂类关键词**：`--food-pack` 或 `--track food` 使用 `tracks.py` 里的一组子词；也可用 `--keywords "a b,c"` 自定义多轮。  
- **结果排序**：`--search-sort` 为 `hot` / `new` / `general`（会尝试在搜索页点对应 tab，并带常见 query；最终以详情页算出的**热度分**再排一次）。  
- **去重**：默认开启，指纹为「标题前 40 字 + 首图 URL」的 MD5，库文件默认 `data/seen_fingerprints.json`（可用 `.env` 的 `SHT_FINGERPRINTS_PATH` 改路径）。`--no-dedup` 可关。  
- **只保留更火**：`--min-heat` 设最低热度分（在取 TopN 前过滤；热度算法见 `scoring.py`）。

## 配置

复制 `.env.example` 为 `.env`，按需改：

- 延时范围、无头/有头、导出路径、指纹库路径。  
- **选择器**：`src/social_heat_crawler/crawlers/selectors_xhs.py` 内集中维护，站点改版时只改此文件。

## 与 [MediaCrawler](https://github.com/NanmiCoder/MediaCrawler) 的关系

- **思路**借鉴：用浏览器真打开页面、登录态、滚动加载、从 DOM/内嵌数据取信息。  
- 本仓库为**精简、可自己看完**的实现，不复制其整库；你需要根据实际页面**更新选择器**。

## 项目结构

```
social-heat-crawler/
  README.md
  requirements.txt
  pyproject.toml
  .env.example
  scripts/
    save_login_state.py
    run_crawl.py
    run_rewrite_text.py
    run_prepare_publish.py
    flow_langjie_douyin_to_xhs.py
    open_douyin_creator.py
  src/social_heat_crawler/
    __init__.py
    config.py
    fingerprints.py
    human.py
    scoring.py
    storage.py
    tracks.py
    crawlers/
      base.py
      xhs_crawler.py
      douyin_crawler.py
      export_ops.py
      selectors_xhs.py
      selectors_douyin.py
    publish/
      xhs_open_creator.py
```

`--demo` 模式只走 `export_ops` + 排序，**不加载 Playwright**，便于先装依赖中的非浏览器部分并检查导出目录；真实爬取需 `playwright install chromium`。

## 小红书选择器与调试（第 1 步已落地）

- 见 `src/social_heat_crawler/crawlers/selectors_xhs.py`：标题、正文、赞/评/藏、图片各有多组**备选 CSS**；通用方法 `find_with_fallback()` 依序尝试，失败时打中文警告而不中断单条笔记解析。  
- 互动数另用 `find_interaction_count_from_texts()`；图片用 `collect_image_urls()` 多路收集。  
- 设 **`XHS_DEBUG=1`** 且某字段全部候选失败时，会把**当前页 HTML** 存到 `SHT_DEBUG_HTML_DIR`（默认 `data/debug/`，在 `.env` 可改）。  
- 详情页与搜索页若改版，请用 DevTools 更新同文件中的列表，勿改 `xhs_crawler` 主流程（除非要调整热度正则）。

**抖音**选择器在 `crawlers/selectors_douyin.py`，与抓取逻辑 `douyin_crawler.py` 同规则维护。

## 声明

- 不保证与任意时刻的小红书/抖音页面兼容；选择器需自行维护。  
- **禁止** 用于违法或批量搬运；发布内容须**二次创作**与合法使用素材。
