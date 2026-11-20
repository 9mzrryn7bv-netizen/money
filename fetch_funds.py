import json
import os
from datetime import datetime
import yfinance as yf

DATA_FILE = "funds_data.json"

FUND_MAP = {
    "JFP11": {"name": "摩根多重收益 (穩定月配)", "ticker": "AOR", "base_yield": 6.8},
    "MLE24": {"name": "貝萊德世界科技 (A10月配)", "ticker": "XLK", "base_yield": 8.5},
    "NGB1":  {"name": "高盛環球非投資等級債 (月配)", "ticker": "HYG", "base_yield": 7.5},
    "NGB2":  {"name": "高盛新興市場債 (月配)", "ticker": "EMB", "base_yield": 7.8},
    "AIG01": {"name": "安聯收益成長 (AM穩定月收)", "ticker": "JEPI", "fallback_ticker": "AOA", "base_yield": 8.2},
    "ABH01": {"name": "聯博全球非投資等級債 (AA月配)", "ticker": "JNK", "base_yield": 7.6},
    "ABA01": {"name": "聯博美國收益 (AA月配)", "ticker": "AGG", "base_yield": 6.2},
    "PIM01": {"name": "PIMCO 多元收益債 (月配)", "ticker": "BOND", "base_yield": 6.5},
    "FID01": {"name": "富達全球優質債券 (月配)", "ticker": "LQD", "base_yield": 5.8},
    "FRK01": {"name": "富蘭克林穩定月收益 (月配)", "ticker": "AOM", "base_yield": 7.2},
    "JPM02": {"name": "摩根環球非投資等級債 (月配)", "ticker": "USHY", "fallback_ticker": "HYG", "base_yield": 7.4},
    "BLK02": {"name": "貝萊德全球智慧數據股票入息 (A10)", "ticker": "SCHD", "fallback_ticker": "VYM", "base_yield": 7.8},
    "SCH01": {"name": "施羅德環球股債收息 (月配)", "ticker": "AOK", "base_yield": 6.5},
    "UBS01": {"name": "瑞銀美國總收益股票 (月配)", "ticker": "VIG", "base_yield": 7.0},
    "FUB01": {"name": "富邦人壽全委月撥回帳戶 (穩健型)", "ticker": "AOR", "base_yield": 6.0},
}

def load_existing():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"updated_at": "", "funds": {}}

def fetch_annual_series(ticker, base_yield):
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="max", auto_adjust=False)
        if hist.empty or len(hist) < 200:
            return None
        hist.index = hist.index.tz_localize(None)
        hist["Year"] = hist.index.year
        years = sorted(hist["Year"].unique())
        series = []
        prev_close = None
        for yr in years:
            sub = hist[hist["Year"] == yr]
            if sub.empty:
                continue
            close_end = float(sub["Close"].iloc[-1])
            div_sum = float(sub["Dividends"].sum()) if "Dividends" in sub else 0.0
            if prev_close is not None and prev_close > 0:
                nav_chg = round(((close_end - prev_close) / prev_close) * 100, 2)
                div_yield = round((div_sum / prev_close) * 100, 2) if div_sum > 0 else base_yield
                if div_yield < 1.5:
                    div_yield = base_yield
                series.append({"yr": int(yr), "navChg": nav_chg, "divYield": div_yield})
            prev_close = close_end
        return series if len(series) >= 5 else None
    except Exception:
        return None

def main():
    old_data = load_existing()
    new_funds = old_data.get("funds", {})
    updated_any = False

    for code, cfg in FUND_MAP.items():
        series = fetch_annual_series(cfg["ticker"], cfg["base_yield"])
        if not series and cfg.get("fallback_ticker"):
            series = fetch_annual_series(cfg["fallback_ticker"], cfg["base_yield"])
        if series:
            new_funds[code] = {"name": cfg["name"], "years": series}
            updated_any = True
            print(f"[{code}] 更新成功 ({len(series)} 年)")
        else:
            print(f"[{code}] 抓取失敗，保留舊資料")

    if updated_any:
        output = {"updated_at": datetime.utcnow().strftime("%Y-%m-%d"), "funds": new_funds}
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print("funds_data.json 已更新完成。")

if __name__ == "__main__":
    main()
