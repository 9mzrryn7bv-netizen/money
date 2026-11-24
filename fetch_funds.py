import json
import math
import os
import re
import time
import urllib.request
from datetime import datetime
from html.parser import HTMLParser

DATA_FILE = "funds_data.json"

# 15 檔熱門月配息基金（完全維持原始代碼對照不變）
FUND_MAP = {
    "JFP11": {"name": "摩根多重收益 (美元對沖/穩定月配)", "dj_id": "JFZA5"},
    "MLE24": {"name": "貝萊德世界科技 (A10美元/穩定月配)", "dj_id": "SHZV9"},
    "NGB1":  {"name": "高盛環球非投資等級債 (X股美元/月配)", "dj_id": "ANZ89"},
    "NGB2":  {"name": "高盛新興市場債 (X股美元/月配)", "dj_id": "ANZA2"},
    "AIG01": {"name": "安聯收益成長 (AM穩定月收/美元)", "dj_id": "TLZ64"},
    "ABH01": {"name": "聯博全球非投資等級債 (AA穩定月配/美元)", "dj_id": "ALB58"},
    "ABA01": {"name": "聯博美國收益 (AA穩定月配/美元)", "dj_id": "ALB62"},
    "PIM01": {"name": "PIMCO 多元收益債 (M級月收息)", "dj_id": "PIM41"},
    "PIM02": {"name": "PIMCO 多元收益債 (M級月收息強化)", "dj_id": "PIM51"},
    "FID01": {"name": "富達全球優質債券 (A股C月配息/美元)", "dj_id": "FTZX0"},
    "FRK01": {"name": "富蘭克林穩定月收益 (美元月配)", "dj_id": "FLZ92"},
    "BLK02": {"name": "貝萊德全球智慧數據股票入息 (A6美元)", "dj_id": "SHZT9"},
    "SCH01": {"name": "施羅德環球股債收息 (A股月配/美元)", "dj_id": "PYZL8"},
    "SCH02": {"name": "施羅德環球收息債券 (A月配固定/美元)", "dj_id": "PYZR2"},
    "UBS01": {"name": "瑞銀美國總收益股票 (美元月配)", "dj_id": "SBZB2"},
}

HOSTS = [
    "https://tbb.moneydj.com",
    "https://tcbbankfund.moneydj.com",
    "https://yuantabank.moneydj.com",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}


class TableParser(HTMLParser):
    """嚴格解析 HTML 表格中的每一列與儲存格"""
    def __init__(self):
        super().__init__()
        self.rows = []
        self._in_cell = False
        self._cur_row = None
        self._cur_cell = []

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        if t == "tr":
            self._cur_row = []
        elif t in ("td", "th") and self._cur_row is not None:
            self._in_cell = True
            self._cur_cell = []

    def handle_endtag(self, tag):
        t = tag.lower()
        if t in ("td", "th") and self._in_cell:
            text = re.sub(r"\s+", " ", "".join(self._cur_cell)).strip()
            self._cur_row.append(text)
            self._in_cell = False
            self._cur_cell = []
        elif t == "tr" and self._cur_row is not None:
            if self._cur_row:
                self.rows.append(self._cur_row)
            self._cur_row = None

    def handle_data(self, data):
        if self._in_cell:
            self._cur_cell.append(data)


def http_get(url, timeout=15):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        for enc in ("utf-8", "cp950", "big5", "latin1"):
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
    """抓取完整歷史每日除息後淨值，回傳按日期排序的 [(YYYYMMDD, YYYY-MM, nav), ...]"""
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
                        if len(digits) >= 8 and math.isfinite(val) and val > 0:
                            ymd = digits[:8]
                            ym = f"{digits[:4]}-{digits[4:6]}"
                            records.append((ymd, ym, val))
                    except Exception:
                        continue
                if len(records) > len(best_records):
                    best_records = records
                if len(best_records) > 1000:
                    best_records.sort(key=lambda x: x[0])
                    return best_records
            except Exception:
                continue
        if len(best_records) > 250:
            best_records.sort(key=lambda x: x[0])
            return best_records
    if len(best_records) >= 20:
        best_records.sort(key=lambda x: x[0])
        return best_records
    return None


def parse_div_table(html):
    """嚴格定位表頭欄位，解析每一筆真實除息日與每單位配息金額"""
    parser = TableParser()
    parser.feed(html)

    date_col = None
    amt_col = None
    div_by_ym = {}
    raw_count = 0

    for row in parser.rows:
        # 1. 偵測表頭列，動態鎖定「除息日」與「配息金額/息值」欄位索引
        if any("除息日" in cell for cell in row):
            for idx, cell in enumerate(row):
                if "除息日" in cell:
                    date_col = idx
                elif any(k in cell for k in ("配息金額", "每單位配息", "息值", "分配金額")) and "率" not in cell:
                    amt_col = idx
            continue

        # 2. 解析資料列
        d_match = None
        if date_col is not None and date_col < len(row):
            d_match = re.search(r"(\d{4})[/-](\d{2})[/-](\d{2})", row[date_col])
        elif len(row) >= 2:
            d_match = re.search(r"(\d{4})[/-](\d{2})[/-](\d{2})", row[0])

        if not d_match:
            continue

        ym = f"{d_match.group(1)}-{d_match.group(2)}"
        amt = None

        # 優先使用表頭鎖定的金額欄位
        if amt_col is not None and amt_col < len(row):
            cell_val = row[amt_col].replace(",", "").strip()
            if re.fullmatch(r"\d+(?:\.\d+)?", cell_val):
                amt = float(cell_val)
        else:
            # 備援：跳過日期與百分比欄位，找第一個純小數金額
            for idx, cell in enumerate(row):
                if idx == 0 or "%" in cell or "/" in cell or "-" in cell:
                    continue
                cell_val = cell.replace(",", "").strip()
                if re.fullmatch(r"\d+(?:\.\d+)?", cell_val):
                    amt = float(cell_val)
                    break

        if amt is not None and math.isfinite(amt) and 0 < amt < 50:
            div_by_ym[ym] = round(div_by_ym.get(ym, 0.0) + amt, 6)
            raw_count += 1

    return div_by_ym, raw_count


def fetch_div_history(dj_id):
    """依序向 MoneyDJ 主機抓取真實配息表"""
    for host in HOSTS:
        url = f"{host}/w/wb/wb05.djhtm?a={dj_id}"
        try:
            html = http_get(url)
            if not html:
                continue
            div_by_ym, raw_count = parse_div_table(html)
            if raw_count >= 3:
                return div_by_ym, raw_count
        except Exception:
            continue
    return {}, 0


def build_monthly_series(dj_id):
    nav_records = fetch_nav_history(dj_id)
    if not nav_records:
        return None, 0, None

    div_by_ym, raw_div_count = fetch_div_history(dj_id)
    if raw_div_count == 0:
        return None, 0, None

    # 每月取最後一個交易日的真實淨值（nav_records 已按 YYYYMMDD 嚴格排序）
    nav_by_ym = {}
    for ymd, ym, val in nav_records:
        nav_by_ym[ym] = val

    months = []
    latest_real_div = None

    for ym in sorted(nav_by_ym.keys()):
        nav = round(nav_by_ym[ym], 4)
        div = div_by_ym.get(ym, 0.0)
        # 合理性防呆：單月配息不可能超過淨值的 20%
        if div > nav * 0.2:
            div = 0.0
        if div > 0:
            latest_real_div = (ym, div)
        months.append({"ym": ym, "nav": nav, "div": div})

    return (months if len(months) >= 6 else None), raw_div_count, latest_real_div


def main():
    old_funds = load_existing().get("funds", {})
    new_funds = {}
    success_count = 0

    print("=== 開始執行嚴謹數據抓取與稽核 ===")
    for code, cfg in FUND_MAP.items():
        months, div_cnt, latest_div = build_monthly_series(cfg["dj_id"])
        if months and div_cnt > 0:
            new_funds[code] = {"name": cfg["name"], "months": months}
            success_count += 1
            ld_str = f"{latest_div[0]}: {latest_div[1]}" if latest_div else "無"
            print(
                f"✅ [{code} / {cfg['dj_id']}] "
                f"淨值: {months[-1]['nav']} ({months[-1]['ym']}, 共{len(months)}月) | "
                f"真實配息: {div_cnt}期 (最新 {ld_str})"
            )
        else:
            if code in old_funds and "months" in old_funds[code]:
                new_funds[code] = old_funds[code]
                print(f"⚠️ [{code} / {cfg['dj_id']}] 真實配息或淨值抓取失敗，保留上一版安全資料")
            else:
                print(f"❌ [{code} / {cfg['dj_id']}] 抓取失敗且無舊檔")
        time.sleep(0.5)

    if success_count > 0:
        output = {
            "updated_at": datetime.utcnow().strftime("%Y-%m-%d"),
            "funds": new_funds
        }
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2, allow_nan=False)
        print(f"=== 稽核完成：{success_count}/{len(FUND_MAP)} 檔真實數據已寫入 funds_data.json ===")
    else:
        raise RuntimeError("所有標的皆抓取失敗，中止寫入以保護既有資料。")


if __name__ == "__main__":
    main()
