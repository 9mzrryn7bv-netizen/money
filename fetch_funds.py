import json
import os
import re
import time
import urllib.request
from datetime import datetime

DATA_FILE = "funds_data.json"

# 15 檔熱門月配息基金真實 MoneyDJ 代碼對照表
FUND_MAP = {
    "JFP11": {"name": "摩根多重收益 (美元對沖/穩定月配)", "dj_id": "JFZA5", "base_yield": 6.8},
    "MLE24": {"name": "貝萊德世界科技 (A10美元/穩定月配)", "dj_id": "SHZV9", "base_yield": 8.5},
    "NGB1":  {"name": "高盛環球非投資等級債 (X股美元/月配)", "dj_id": "ANZ89", "base_yield": 7.5},
    "NGB2":  {"name": "高盛新興市場債 (X股美元/月配)", "dj_id": "ANZA2", "base_yield": 7.8},
    "AIG01": {"name": "安聯收益成長 (AM穩定月收/美元)", "dj_id": "TLZ64", "base_yield": 8.2},
    "ABH01": {"name": "聯博全球非投資等級債 (AA穩定月配/美元)", "dj_id": "ALB58", "base_yield": 7.6},
    "ABA01": {"name": "聯博美國收益 (AA穩定月配/美元)", "dj_id": "ALB62", "base_yield": 6.2},
    "PIM01": {"name": "PIMCO 多元收益債 (M級月收息)", "dj_id": "PIM41", "base_yield": 6.5},
    "PIM02": {"name": "PIMCO 多元收益債 (M級月收息強化)", "dj_id": "PIM51", "base_yield": 7.5},
    "FID01": {"name": "富達全球優質債券 (A股C月配息/美元)", "dj_id": "FTZX0", "base_yield": 5.8},
    "FRK01": {"name": "富蘭克林穩定月收益 (美元月配)", "dj_id": "FLZ92", "base_yield": 7.2},
    "BLK02": {"name": "貝萊德全球智慧數據股票入息 (A6美元)", "dj_id": "SHZT9", "base_yield": 7.8},
    "SCH01": {"name": "施羅德環球股債收息 (A股月配/美元)", "dj_id": "PYZL8", "base_yield": 6.5},
    "SCH02": {"name": "施羅德環球收息債券 (A月配固定/美元)", "dj_id": "PYZR2", "base_yield": 6.8},
    "UBS01": {"name": "瑞銀美國總收益股票 (美元月配)", "dj_id": "SBZB2", "base_yield": 7.0},
}

HOSTS = [
    "https://tbb.moneydj.com",
    "https://tcbbankfund.moneydj.com",
    "https://yuantabank.moneydj.com",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}

def http_get(url, timeout=15):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        for enc in ("utf-8", "big5", "cp950", "latin1"):
            try:
                return raw.decode(enc)
            except Exception:
                continue
    return ""

def load_existing():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"updated_at": "", "funds": {}}

def fetch_nav_history(dj_id):
    today = datetime.utcnow().strftime("%Y-%m-%d")
    for host in HOSTS:
        url = f"{host}/w/bcd/BCDNavList.djbcd?a={dj_id}&b=1&c=2008-01-01&d={today}"
        try:
            text = http_get(url).strip()
            parts = text.split()
            if len(parts) < 2:
                continue
            dates = parts[0].split(",")
            navs = parts[1].split(",")
            if len(dates) != len(navs) or len(dates) < 20:
                continue
            records = []
            for d_str, n_str in zip(dates, navs):
                try:
                    yr = int(d_str.replace("-", "/")[:4])
                    val = float(n_str)
                    if val > 0:
                        records.append((yr, d_str, val))
                except Exception:
                    continue
            if len(records) >= 20:
                return records
        except Exception:
            continue
    return None

def fetch_div_history(dj_id):
    """抓取年度配息總額，回傳 {year: total_div_amount}"""
    div_by_yr = {}
    for host in HOSTS:
        url = f"{host}/w/wb/wb05.djhtm?a={dj_id}"
        try:
            html = http_get(url)
            if not html:
                continue
            # 擷取表格中的「除息日 (YYYY/MM/DD) ... 配息金額」
            rows = re.findall(r"(\d{4}/\d{2}/\d{2})</t[dh]>\s*<t[dh][^>]*>([\d\.]+)", html)
            if rows:
                for d_str, amt_str in rows:
                    yr = int(d_str[:4])
                    amt = float(amt_str)
                    if 0 < amt < 50:
                        div_by_yr[yr] = div_by_yr.get(yr, 0.0) + amt
                return div_by_yr
        except Exception:
            continue
    return div_by_yr

def build_annual_series(dj_id, base_yield):
    nav_records = fetch_nav_history(dj_id)
    if not nav_records:
        return None

    div_by_yr = fetch_div_history(dj_id)

    # 整理每年年底淨值與首筆淨值
    by_yr = {}
    for yr, d_str, val in nav_records:
        if yr not in by_yr:
            by_yr[yr] = {"first": val, "last": val}
        else:
            by_yr[yr]["last"] = val

    years = sorted(by_yr.keys())
    series = []
    prev_close = None

    for yr in years:
        close_end = by_yr[yr]["last"]
        ref_nav = prev_close if prev_close else by_yr[yr]["first"]
        if ref_nav and ref_nav > 0:
            nav_chg = round(((close_end - ref_nav) / ref_nav) * 100, 2)
            ann_div = div_by_yr.get(yr, 0.0)
            div_yield = round((ann_div / ref_nav) * 100, 2) if ann_div > 0 else base_yield
            # 若成立首年僅配息 1~2 個月導致年化偏低，改用基準殖利率避免失真
            if div_yield < 1.5 or div_yield > 30:
                div_yield = base_yield
            series.append({"yr": int(yr), "navChg": nav_chg, "divYield": div_yield})
        prev_close = close_end

    return series if len(series) >= 1 else None

def main():
    old_data = load_existing()
    new_funds = old_data.get("funds", {})
    updated_any = False

    for code, cfg in FUND_MAP.items():
        series = build_annual_series(cfg["dj_id"], cfg["base_yield"])
        if series:
            new_funds[code] = {"name": cfg["name"], "years": series}
            updated_any = True
            print(f"[{code} / {cfg['dj_id']}] 真實資料更新成功（共 {len(series)} 年，最新 {series[-1]['yr']} 年）")
        else:
            print(f"[{code} / {cfg['dj_id']}] 抓取失敗，保留舊資料")
        time.sleep(0.6)  # 避免請求過快被擋

    if updated_any:
        output = {
            "updated_at": datetime.utcnow().strftime("%Y-%m-%d"),
            "funds": new_funds
        }
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print("funds_data.json 已更新完成。")
    else:
        print("本次無任何更新（可能受限於海外 IP），維持原檔案。")

if __name__ == "__main__":
    main()
