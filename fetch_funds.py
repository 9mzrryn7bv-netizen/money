import json
import os
import re
import time
import urllib.request
from datetime import datetime

DATA_FILE = "funds_data.json"

# 15 檔熱門月配息基金（維持原始代碼不變）
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
    param_variants = [
        f"a={dj_id}&c=2008-01-01&d={today}",
        f"a={dj_id}&b=0&c=2008-01-01&d={today}",
    ]
    best_records = []
    for host in HOSTS:
        for params in param_variants:
            url = f"{host}/w/bcd/BCDNavList.djbcd?{params}"
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
                        digits = re.sub(r"\D", "", d_str)
                        val = float(n_str)
                        if len(digits) >= 6 and val > 0:
                            ym = f"{digits[:4]}-{digits[4:6]}"
                            records.append((ym, val))
                    except Exception:
                        continue
                if len(records) > len(best_records):
                    best_records = records
                if len(best_records) > 1000:
                    return best_records
            except Exception:
                continue
        if len(best_records) > 250:
            return best_records
    return best_records if len(best_records) >= 20 else None

def fetch_div_history(dj_id):
    """抓取每月配息金額，回傳 {'YYYY-MM': div_amount}"""
    div_by_ym = {}
    for host in HOSTS:
        url = f"{host}/w/wb/wb05.djhtm?a={dj_id}"
        try:
            html = http_get(url)
            if not html:
                continue
            rows = re.findall(r"(\d{4}/\d{2}/\d{2})</t[dh]>\s*<t[dh][^>]*>([\d\.]+)", html)
            if rows:
                for d_str, amt_str in rows:
                    ym = d_str[:7].replace("/", "-")
                    amt = float(amt_str)
                    if 0 < amt < 50:
                        div_by_ym[ym] = round(div_by_ym.get(ym, 0.0) + amt, 5)
                return div_by_ym
        except Exception:
            continue
    return div_by_ym

def build_monthly_series(dj_id, base_yield):
    nav_records = fetch_nav_history(dj_id)
    if not nav_records:
        return None

    div_by_ym = fetch_div_history(dj_id)
    has_real_div = len(div_by_ym) > 0

    nav_by_ym = {}
    for ym, val in nav_records:
        nav_by_ym[ym] = val

    months = []
    for ym in sorted(nav_by_ym.keys()):
        nav = round(nav_by_ym[ym], 4)
        if has_real_div:
            div = div_by_ym.get(ym, 0.0)
        else:
            div = round(nav * (base_yield / 100.0 / 12.0), 5)
        months.append({"ym": ym, "nav": nav, "div": div})

    return months if len(months) >= 6 else None

def main():
    old_funds = load_existing().get("funds", {})
    # 只保留 FUND_MAP 內的 15 檔，徹底清除舊版殘留的 NaN 標的
    new_funds = {}
    updated_any = False

    for code, cfg in FUND_MAP.items():
        months = build_monthly_series(cfg["dj_id"], cfg["base_yield"])
        if months:
            new_funds[code] = {"name": cfg["name"], "months": months}
            updated_any = True
            print(f"[{code} / {cfg['dj_id']}] 成功 | 最新淨值: {months[-1]['nav']} ({months[-1]['ym']}) | 共 {len(months)} 個月")
        elif code in old_funds and "months" in old_funds[code]:
            new_funds[code] = old_funds[code]
            print(f"[{code} / {cfg['dj_id']}] 抓取失敗，保留舊資料")
        else:
            print(f"[{code} / {cfg['dj_id']}] 抓取失敗")
        time.sleep(0.5)

    if updated_any:
        output = {
            "updated_at": datetime.utcnow().strftime("%Y-%m-%d"),
            "funds": new_funds
        }
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2, allow_nan=False)
        print("funds_data.json 已更新完成（已清除舊版殘留資料）。")
    else:
        print("本次無任何更新，維持原檔案。")

if __name__ == "__main__":
    main()
