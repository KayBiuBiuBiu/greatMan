-- Tushare 特色因子缓存表（默认库：data/financial_factors.db）
-- 由 quote_tushare.init_stock_financial_cache() 自动创建；亦可手工执行本脚本。
--
-- industry_moneyflow_cache：json 内 source=aggregated_sw 表示由候选池个股 moneyflow 按申万一级汇总。
-- hot_stock_cache：仅保存沪深 A 股 6 位代码（ths_hot 已过滤）。
-- concept_member_cache：概念代码为东财 BKxxxx.DC（dc_index → dc_member）。
-- hot_concept_stocks_cache：ths_index 涨幅前 N 概念经 dc_member 展开的成分股（trade_date + code）。

CREATE TABLE IF NOT EXISTS stock_moneyflow_cache (
    code TEXT NOT NULL,
    date TEXT NOT NULL,
    json_data TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (code, date)
);

CREATE TABLE IF NOT EXISTS industry_moneyflow_cache (
    industry_code TEXT NOT NULL,
    date TEXT NOT NULL,
    json_data TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (industry_code, date)
);

CREATE TABLE IF NOT EXISTS hot_stock_cache (
    trade_date TEXT NOT NULL PRIMARY KEY,
    json_data TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS broker_recommend_cache (
    month TEXT NOT NULL PRIMARY KEY,
    json_data TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS concept_member_cache (
    concept_code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    json_data TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (concept_code, trade_date)
);

CREATE TABLE IF NOT EXISTS hot_concept_stocks_cache (
    trade_date TEXT NOT NULL,
    code TEXT NOT NULL,
    json_data TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (trade_date, code)
);

CREATE INDEX IF NOT EXISTS idx_hot_concept_stocks_trade_date
ON hot_concept_stocks_cache(trade_date);
