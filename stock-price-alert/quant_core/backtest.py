import akshare as ak
import pandas as pd
import time
import requests
import baostock as bs

# ==========================
# 自动重试 + 多源回退（终极版）
# ==========================
def load_daily_df(code, retry=3):
    login_ok = False
    try:
        lg = bs.login()  # 登录（无账号也行）
        login_ok = getattr(lg, "error_code", "") == "0"
    except Exception:
        login_ok = False

    if login_ok:
        for attempt in range(retry):
            try:
                # 转换 baostock 格式：sh.600711 / sz.002xxx
                bs_code = f"sh.{code}" if code.startswith("6") else f"sz.{code}"
                rs = bs.query_history_k_data_plus(
                    code=bs_code,
                    start_date="2018-01-01",
                    end_date="2026-12-31",
                    frequency="d",
                    adjustflag="3",  # 前复权
                    fields="date,open,high,low,close,volume"
                )
                rows = []
                while (rs.error_code == "0") and rs.next():
                    rows.append(rs.get_row_data())
                df = pd.DataFrame(rows, columns=rs.fields if rows else [])
                if not df.empty:
                    for col in ("close", "open", "high", "low", "volume"):
                        df[col] = pd.to_numeric(df[col], errors="coerce")
                    df = df.dropna(subset=["close", "open", "high", "low"])
                    if not df.empty:
                        return df
            except Exception:
                time.sleep(1)

    try:
        # 回退1：老接口
        df = ak.stock_zh_a_hist(symbol=code, period="daily", adjust="qfq")
        return df
    except Exception:
        pass

    try:
        # 回退2：新浪（最稳）
        sym = code if code.startswith(("sh", "sz")) else f"sh{code}"
        url = f"https://quotes.sina.cn/stock/api/json.php/HS_{sym}_kline_day"
        r = requests.get(url, timeout=8)
        data = r.json()
        rows = []
        for d in data:
            rows.append({
                "date": d[0],
                "close": float(d[2]),
                "open": float(d[1]),
                "high": float(d[3]),
                "low": float(d[4]),
                "volume": float(d[5])
            })
        return pd.DataFrame(rows)
    except Exception:
        return pd.DataFrame()
    finally:
        if login_ok:
            try:
                bs.logout()
            except Exception:
                pass

# ==========================
# 字段自动适配
# ==========================
def fix_df(df):
    df = df.copy()
    df.columns = df.columns.str.replace("日期","date")
    df.columns = df.columns.str.replace("收盘","close")
    df.columns = df.columns.str.replace("开盘","open")
    df.columns = df.columns.str.replace("最高","high")
    df.columns = df.columns.str.replace("最低","low")
    return df

# ==========================
# 真实策略回测
# ==========================
def run_real_backtest(code, years=3):
    try:
        df = load_daily_df(code)
        if df.empty:
            return {"profit":0,"win":0,"trades":0,"note":"⚠️ 数据源繁忙，稍后再试"}

        df = fix_df(df)
        df = df.tail(252*years).dropna(subset=["close"])
        df["ma20"] = df["close"].rolling(20).mean()
        df["ma60"] = df["close"].rolling(60).mean()
        df = df.dropna()

        trades = []
        for i in range(1, len(df)):
            try:
                if df["ma20"].iloc[i-1] < df["ma60"].iloc[i-1] and df["ma20"].iloc[i] > df["ma60"].iloc[i]:
                    buy = df["close"].iloc[i]
                    for j in range(i+1, min(i+10, len(df))):
                        pct = (df["close"].iloc[j] / buy -1)*100
                        if pct >=8:
                            trades.append(8)
                            break
                        if pct <=-4:
                            trades.append(-4)
                            break
            except:
                continue

        if not trades:
            return {"profit":0,"win":0,"trades":0,"note":"✅ 真实回测：无交易信号"}

        profit = round(sum(trades),2)
        win_rate = round(len([x for x in trades if x>0])/len(trades)*100,1)
        return {
            "profit": profit,
            "win": win_rate,
            "trades": len(trades),
            "note": "✅ 真实K线回测（多源自动回退）"
        }
    except Exception as e:
        return {"profit":0,"win":0,"trades":0,"note":f"降级：{str(e)}"}

# ==========================
# 对外接口
# ==========================
def run_backtest(code, strategy, years=3):
    return run_real_backtest(code, years)

def run_backtest_pack(code, years_list=[1,3,5]):
    out = {"code":code,"results":{}}
    for y in years_list:
        out["results"][y] = run_backtest(code, "", y)
    return out

