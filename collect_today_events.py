#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""collect_today_events.py — 收集今日(T=2026-09-04)前后事件，明日验证使用。

输出：events_today.jsonl，兼容 pronocia_run pipeline。
CN 用 akshare.stock_notice_report（近 4 天：09-04/03/02/01，作为 T-0/T-1/T-3/T-7 窗口）
US 用 SEC EDGAR API submissions/filings（近 4 天提交的 8-K/10-Q/424B5/424B2/S-4）
"""
from __future__ import annotations
import datetime as dt, hashlib, json, re, sys, time, urllib.parse, urllib.request
from collections import defaultdict, Counter
from pathlib import Path

try:
    import akshare as ak
except Exception as e:
    print(f"akshare import failed: {e}", file=sys.stderr)
    sys.exit(1)

OUT_DIR = Path("/root/Pronoia/pronoia_run/today_test")
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_FILE = OUT_DIR / "events_today.jsonl"

CN_BENCHMARK = "sh000300"
US_BENCHMARK = "QQQ"

NEG_TITLE = re.compile(r"投资者关系|IR|路演|调研纪要|会议纪要|问询函|回复|更正|补充|仲裁|诉讼|更正后|补充公告|补充法律意见书")
MA_PATS = re.compile(r"发行股份|收购|资产|再融资|定增|增发|可转债|可交换|募资|回购|重组|分拆|并购|出售资产|股权|投融|募集|重大合同|增持|减持")
EAR_PATS = re.compile(r"业绩|营收|利润|净利润|财报|半年报|季报|年报|预增|预减|超预期|盈利预告|业绩预告|快报|earnings|report")

def eid(market, symbol, evdate, title_prefix=""):
    raw = f"{market}|{symbol}|{evdate}|{title_prefix}"
    suf = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
    return f"today_{market.lower()}_{symbol}_event_{suf}"

def _calc_window(event_date_str, today_dt):
    edate = dt.datetime.strptime(event_date_str[:10], "%Y-%m-%d").date()
    age = (today_dt - edate).days
    if age <= 0: return "T-0", 0    # 当天事件
    if age <= 1: return "T-1", 1
    if age <= 3: return "T-3", 3
    if age <= 7: return "T-7", 7
    if age <= 14: return "T-14", 14
    if age <= 30: return "T-30", 30
    return "T-60", 60

# ======================================================================
# CN
# ======================================================================
def collect_cn(today_dt):
    events = []
    # 近 4 天：T-0 到 T-7 窗口
    dates = []
    for i in range(4):
        d = today_dt - dt.timedelta(days=i)
        # 跳过周末（公告数量基本为 0）
        if d.weekday() >= 5: continue
        dates.append(d.strftime("%Y%m%d"))
    print(f"[CN] 扫日期: {dates}", file=sys.stderr)

    for d in dates:
        try:
            df = ak.stock_notice_report(symbol="全部", date=d)
            n = len(df)
            print(f"  {d}: {n} 行原始公告", file=sys.stderr)
            if n == 0: continue
            df = df.copy()
            df["公告日期"] = df["公告日期"].astype(str)
            syms_ma = set()
            syms_ear = set()
            cap_ma = cap_ear = 0
            LIMIT = 20  # 每天每类
            for _, r in df.iterrows():
                code = str(r["代码"]).zfill(6)
                name = str(r["名称"])
                title = str(r["公告标题"])
                atype = str(r["公告类型"])
                evdate = str(r["公告日期"])[:10]
                url = str(r["网址"])
                if NEG_TITLE.search(title) or NEG_TITLE.search(atype):
                    continue
                text = f"{title} | {code} {name} · {atype}"
                # 去重同一 symbol（避免同公司多条低价值公告）
                qscore = 3
                if MA_PATS.search(title) or MA_PATS.search(atype):
                    etype = "并购/分拆/再融资"
                    if re.search(r"发行股份购买|收购报告书|重大资产|增发预案|可转债|可交换|定增预案|回购方案|重组预案|收购资产|出售资产", title):
                        qscore = 5
                    elif re.search(r"增持|减持|重大合同|股权变动|募集说明书|申报稿", title):
                        qscore = 4
                    if code in syms_ma or cap_ma >= LIMIT: continue
                    syms_ma.add(code); cap_ma += 1
                    win, age = _calc_window(evdate, today_dt)
                    events.append(dict(
                        event_id=eid("CN", code, evdate, title[:40]),
                        market="CN", symbol=code,
                        event_time=evdate, event_date=evdate,
                        event_type_l2=etype, title=title, event_text=text,
                        source_url=url, sector_etf=None,
                        benchmark=CN_BENCHMARK,
                        direction_prior=None, event_strength=None,
                        _source="akshare.stock_notice_report",
                        _window=win, _name=name, _qscore=qscore, _age_days=age,
                    ))
                elif EAR_PATS.search(title) or EAR_PATS.search(atype):
                    etype = "财报超预期/不及预期"
                    if re.search(r"业绩快报|业绩预告|半年报|第.*季度报告|年度报告|季报|年报|净利润.*增长|营收", title):
                        qscore = 5
                    elif re.search(r"业绩说明|盈利预测|财务报告|审计报告|利润分配", title):
                        qscore = 4
                    if code in syms_ear or cap_ear >= LIMIT: continue
                    syms_ear.add(code); cap_ear += 1
                    win, age = _calc_window(evdate, today_dt)
                    events.append(dict(
                        event_id=eid("CN", code, evdate, title[:40]),
                        market="CN", symbol=code,
                        event_time=evdate, event_date=evdate,
                        event_type_l2=etype, title=title, event_text=text,
                        source_url=url, sector_etf=None,
                        benchmark=CN_BENCHMARK,
                        direction_prior=None, event_strength=None,
                        _source="akshare.stock_notice_report",
                        _window=win, _name=name, _qscore=qscore, _age_days=age,
                    ))
                if cap_ma >= LIMIT and cap_ear >= LIMIT: break
            print(f"    MA={cap_ma} EAR={cap_ear}", file=sys.stderr)
        except Exception as e:
            print(f"  {d} err: {type(e).__name__}: {e}", file=sys.stderr)
        time.sleep(0.5)
    return events

# ======================================================================
# US (SEC EDGAR API, 近 4 天 filings)
# ======================================================================
EDGAR_UA = "Pronoia research@pronoia.ai"
TARGET_FORMS = {"8-K", "10-Q", "10-K", "424B2", "424B5", "S-4", "S-4/A", "SC 13D", "SC 13D/A", "DEF 14A", "FWP"}

def _edgar_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": EDGAR_UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())

def _ticker_to_cik():
    """从 EDGAR company_tickers.json 获取 ticker→CIK 映射。"""
    import urllib.request
    url = "https://www.sec.gov/include/ticker.txt"
    req = urllib.request.Request(url, headers={"User-Agent": EDGAR_UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        lines = resp.read().decode("utf-8").splitlines()
    m = {}
    for ln in lines:
        ln = ln.strip().lower()
        if not ln: continue
        parts = ln.split("\t") if "\t" in ln else ln.split()
        if len(parts) == 2:
            ticker, cik = parts
            m[ticker.lower()] = int(cik)
    return m

def collect_us(today_dt):
    events = []
    # 近 4 天
    date_min = (today_dt - dt.timedelta(days=4)).strftime("%Y-%m-%d")
    date_max = today_dt.strftime("%Y-%m-%d")
    print(f"[US] EDGAR filings date range {date_min} to {date_max}", file=sys.stderr)

    # 查热门科技公司 filings（市值前 30 科技股）
    HOT = ["NVDA","AAPL","MSFT","GOOGL","AMZN","META","AMD","TSLA","AVGO","NFLX",
           "CRM","ORCL","ADBE","INTC","QCOM","TXN","AMAT","PYPL","COIN","NOW",
           "PLTR","SNOW","MU","LRCX","ASML","JPM","BAC","XOM","V","DIS"]
    try:
        ticker_map = _ticker_to_cik()
        print(f"  ticker map loaded: {len(ticker_map)} entries", file=sys.stderr)
    except Exception as e:
        print(f"  ticker map failed: {e}", file=sys.stderr)
        return events

    per_symbol_cap = 3
    seen_syms = defaultdict(int)
    for sym in HOT:
        cik = ticker_map.get(sym.lower())
        if not cik: continue
        try:
            url = f"https://data.sec.gov/submissions/CIK{cik:010d}.json"
            dat = _edgar_get(url)
            recent = dat.get("filings", {}).get("recent", {})
            forms = recent.get("form", [])
            dates = recent.get("filingDate", [])
            accnos = recent.get("accessionNumber", [])
            for form, fdate, accn in zip(forms, dates, accnos):
                if form not in TARGET_FORMS: continue
                if fdate < date_min or fdate > date_max: continue
                if seen_syms[sym] >= per_symbol_cap: continue
                seen_syms[sym] += 1
                # classify
                if form in ("8-K",):
                    etype = "财报超预期/不及预期"
                    qscore = 4
                    title_tmpl = f"{sym} {form}"
                elif form in ("10-Q", "10-K"):
                    etype = "财报超预期/不及预期"
                    qscore = 5
                    title_tmpl = f"{sym} {form} Filing"
                elif form in ("424B2","424B5","S-4","S-4/A","SC 13D","SC 13D/A","DEF 14A","FWP"):
                    etype = "并购/分拆/再融资"
                    qscore = 5
                    title_tmpl = f"{sym} {form}"
                else:
                    continue
                evdate = fdate
                accn_stripped = accn.replace("-","")
                src = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn_stripped}/{accn}-index.htm"
                text = f"EDGAR {form} | {sym} | filed {fdate} | accn {accn}"
                win, age = _calc_window(fdate, today_dt)
                events.append(dict(
                    event_id=eid("US", sym, fdate, form + accn[:8]),
                    market="US", symbol=sym,
                    event_time=evdate, event_date=evdate,
                    event_type_l2=etype, title=title_tmpl, event_text=text,
                    source_url=src, sector_etf=None,
                    benchmark=US_BENCHMARK,
                    direction_prior=None, event_strength=None,
                    _source=f"edgar.submissions.CIK{cik:010d}",
                    _window=win, _name=sym, _qscore=qscore, _age_days=age,
                ))
        except Exception as e:
            print(f"  {sym} (cik={cik}) err: {type(e).__name__}: {e}", file=sys.stderr)
        time.sleep(0.15)
    return events

# ======================================================================
# main
# ======================================================================
def main():
    today_dt = dt.date.today()
    print(f"[COLLECT] today={today_dt} -> 明天 2026-09-05 验证", file=sys.stderr)

    cn = collect_cn(today_dt)
    print(f"[CN] {len(cn)} 事件", file=sys.stderr)
    us = collect_us(today_dt)
    print(f"[US] {len(us)} 事件", file=sys.stderr)

    all_evs = cn + us

    # 按窗口去重（同一 symbol + 同一窗口 只留 qscore 最高的 1 条）
    deduped = {}
    for e in all_evs:
        key = (e["market"], e["symbol"], e["_window"])
        if key not in deduped or e["_qscore"] > deduped[key]["_qscore"]:
            deduped[key] = e
    all_evs = list(deduped.values())

    # 写 jsonl
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        for e in all_evs:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    print(f"\n=== SUMMARY ===", file=sys.stderr)
    print(f"total events : {len(all_evs)}", file=sys.stderr)
    market_dist = Counter(e["market"] for e in all_evs)
    etype_dist = Counter(e["event_type_l2"] for e in all_evs)
    win_dist = Counter(e["_window"] for e in all_evs)
    print(f"market dist  : {dict(market_dist)}", file=sys.stderr)
    print(f"etype dist   : {dict(etype_dist)}", file=sys.stderr)
    print(f"window dist  : {dict(sorted(win_dist.items()))}", file=sys.stderr)
    print(f"output       : {OUT_FILE}", file=sys.stderr)

    # sample print
    for w in sorted(set(e["_window"] for e in all_evs)):
        w_evs = [e for e in all_evs if e["_window"] == w]
        print(f"\n[{w}] ({len(w_evs)}条)", file=sys.stderr)
        for e in w_evs[:3]:
            print(f"  {e['market']} {e['symbol']:>8s} {e['event_type_l2']} "
                  f"q={e['_qscore']} {e['title'][:40]}", file=sys.stderr)

if __name__ == "__main__":
    main()
