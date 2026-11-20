#!/usr/bin/env python3
"""Weekly watchlist review: compares the latest weekly run with the previous one and writes
   review.html (a self-contained page, published as the "Watchlist Weekly Review" artifact) and review.json (facts for the written analysis).
   Usage: python3 scripts/weekly_review.py [--notes notes.html] [--out DIR]
   notes.html = the week's written synthesis (HTML paragraphs), inserted at the top of the page."""
import json, os, sys, html, argparse, datetime as dt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ap = argparse.ArgumentParser(); ap.add_argument("--notes"); ap.add_argument("--out", default=ROOT)
A = ap.parse_args()
RUNS = json.load(open(os.path.join(ROOT, "data/runs/index.json")))["runs"]
load = lambda d: json.load(open(os.path.join(ROOT, f"data/runs/{d}.json")))
cur_d = RUNS[-1]; prev_d = RUNS[-2] if len(RUNS) > 1 else None
CUR = {r["sym"]: r for r in load(cur_d)["results"]}
PREV = {r["sym"]: r for r in load(prev_d)["results"]} if prev_d else {}
e = lambda s: html.escape(str(s if s is not None else ""))
num = lambda x: isinstance(x, (int, float)) and not isinstance(x, bool)
KIND = {"fund": "ETF", "index": "Index", "crypto": "Crypto"}
kind = lambda r: r.get("kind") or ("index" if r["sym"].startswith("^") else "crypto" if r["sym"].endswith("-USD") else "equity")
sc = lambda r, k: (r.get(k) or {}).get("score")
lab = lambda r, k: (r.get(k) or {}).get("label")
TIER = ["Poor", "Weak", "Mixed", "Favourable", "Strong"]
def tier(l):
    l = (l or "").lower()
    for i, t in enumerate(["poor", "weak", "mixed", "favourable", "strong"]):
        if l.startswith(t) or l.startswith("mostly favourable" if t == "favourable" else t): return i
    if l.startswith("unfavourable"): return 1
    if l.startswith("neutral"): return 2
    return None

rows = []
for s, r in CUR.items():
    p = PREV.get(s)
    d_lt = sc(r, "long_term") - sc(p, "long_term") if p and num(sc(r, "long_term")) and num(sc(p, "long_term")) else None
    d_tm = sc(r, "timing") - sc(p, "timing") if p and num(sc(r, "timing")) and num(sc(p, "timing")) else None
    ind = []
    if p:
        for k, m in (r.get("metrics") or {}).items():
            q = (p.get("metrics") or {}).get(k) or {}
            if num(m.get("sc")) and num(q.get("sc")) and not m.get("ctx") and abs(m["sc"] - q["sc"]) >= 2:
                ind.append({"k": k, "l": m.get("l", k), "now": m.get("d"), "was": q.get("d"), "dsc": round(m["sc"] - q["sc"], 1)})
    flags = []
    if p:
        e_now = ((r.get("metrics") or {}).get("e200") or {}).get("v"); e_was = ((p.get("metrics") or {}).get("e200") or {}).get("v")
        if num(e_now) and num(e_was):
            if e_was >= 0 > e_now: flags.append("fell below its 200-day average")
            if e_was < 0 <= e_now: flags.append("moved back above its 200-day average")
        for k, name in (("long_term", "long-term"), ("timing", "timing")):
            a, b = tier(lab(p, k)), tier(lab(r, k))
            if a is not None and b is not None and a != b: flags.append(f"{name} label {lab(p, k)} → {lab(r, k)}")
    ne = r.get("next_earnings")
    if ne and ne.get("date"):
        days = (dt.date.fromisoformat(ne["date"]) - dt.date.fromisoformat(cur_d)).days
        if 0 <= days <= 14: flags.append(f"earnings on {ne['date']}" + ("" if ne.get("confirmed") else " (est.)"))
    if r.get("warning") and not (p and p.get("warning")): flags.append("data warning: " + r["warning"])
    rows.append({"sym": s, "name": r.get("name"), "kind": kind(r), "cur": r.get("cur"), "price": r.get("price"), "w": r.get("chg_1w"),
                 "lt": sc(r, "long_term"), "tm": sc(r, "timing"), "ltl": lab(r, "long_term"), "tml": lab(r, "timing"),
                 "dlt": round(d_lt, 1) if d_lt is not None else None, "dtm": round(d_tm, 1) if d_tm is not None else None,
                 "ind": sorted(ind, key=lambda x: -abs(x["dsc"]))[:4], "flags": flags, "new": p is None and bool(PREV)})

def top(key, n=5, rev=True):
    xs = [x for x in rows if num(x[key]) and abs(x[key]) >= 0.05]
    return sorted(xs, key=lambda x: x[key], reverse=rev)[:n]
watch = [x for x in rows if num(x["lt"]) and x["lt"] >= 6.2 and num(x["tm"]) and (x["tm"] >= 6.2 or (num(x["dtm"]) and x["dtm"] >= 1))]
watch = sorted(watch, key=lambda x: -(x["lt"] + x["tm"]))[:6]
facts = {"date": cur_d, "previous": prev_d, "count": len(rows), "scored": sum(1 for x in rows if num(x["lt"])),
         "lt_up": top("dlt"), "lt_down": top("dlt", rev=False), "tm_up": top("dtm"), "tm_down": top("dtm", rev=False),
         "price_up": top("w"), "price_down": top("w", rev=False), "flags": [x for x in rows if x["flags"]],
         "indicator_moves": [x for x in rows if x["ind"]], "watch": watch,
         "removed": sorted(set(PREV) - set(CUR)), "added": sorted(set(CUR) - set(PREV)) if PREV else []}
json.dump(facts, open(os.path.join(A.out, "review.json"), "w"), indent=1, ensure_ascii=False)

# ---------- page ----------
def col(s):
    if not num(s): return "var(--ink3)"
    h = 4 + s / 5 * 44 if s <= 5 else 48 + (s - 5) / 5 * 102
    return f"hsl({h:.0f} 70% var(--lum))"
dl = lambda v: "" if not num(v) or abs(v) < 0.05 else f'<span class="d {"u" if v > 0 else "n"}">{"▲" if v > 0 else "▼"}{abs(v):.1f}</span>'
pc = lambda v: "" if not num(v) else f'<span class="d {"u" if v >= 0 else "n"}">{v:+.1f}%</span>'
f1 = lambda v: f"{v:.1f}" if num(v) else "∅"
badge = lambda x: f'<span class="k">{KIND[x["kind"]]}</span>' if x["kind"] in KIND else ""
def li(x, key):
    v = x[key]; extra = pc(v) if key == "w" else dl(v)
    sco = x["lt"] if key in ("dlt", "w") else x["tm"]
    return f'<li><b>{e(x["sym"])}</b>{badge(x)} <span class="nm">{e(x["name"])}</span><span class="r">{extra} <i style="color:{col(sco)}">{f1(sco)}</i></span></li>'
def block(title, xs, key, empty):
    body = "".join(li(x, key) for x in xs) or f'<li class="mt">{empty}</li>'
    return f'<section class="c"><h3>{title}</h3><ul>{body}</ul></section>'
first = prev_d is None
notes = open(A.notes, encoding="utf-8").read() if A.notes and os.path.exists(A.notes) else ""
fd = lambda d: dt.date.fromisoformat(d).strftime("%-d %b %Y")
flag_html = "".join(f'<li><b>{e(x["sym"])}</b>{badge(x)} <span class="nm">{e("; ".join(x["flags"]))}</span></li>' for x in facts["flags"]) or '<li class="mt">Nothing notable.</li>'
ind_html = "".join(f'<li><b>{e(x["sym"])}</b>{badge(x)} <span class="nm">' + "; ".join(f'{e(i["l"])} {e(i["was"])} → {e(i["now"])} ({"+" if i["dsc"] > 0 else ""}{i["dsc"]})' for i in x["ind"]) + "</span></li>" for x in sorted(facts["indicator_moves"], key=lambda x: -max(abs(i["dsc"]) for i in x["ind"]))[:10]) or '<li class="mt">No indicator moved by 2 points or more.</li>'
watch_html = "".join(f'<li><b>{e(x["sym"])}</b>{badge(x)} <span class="nm">{e(x["name"])} · {e(x["ltl"])}</span><span class="r"><i style="color:{col(x["lt"])}">{f1(x["lt"])}</i> <i style="color:{col(x["tm"])}">{f1(x["tm"])}</i></span></li>' for x in watch) or '<li class="mt">No name combines a favourable long-term score with favourable timing this week.</li>'
groups = [("equity", "Stocks"), ("fund", "ETFs"), ("index", "Indices"), ("crypto", "Crypto")]
tables = ""
for k, n in groups:
    xs = sorted([x for x in rows if x["kind"] == k], key=lambda x: -(x["lt"] if num(x["lt"]) else -1))
    if not xs: continue
    tr = "".join(f'<tr><td><b>{e(x["sym"])}</b><small>{e(x["name"])}</small></td><td style="color:{col(x["lt"])}">{f1(x["lt"])}{dl(x["dlt"])}</td><td style="color:{col(x["tm"])}">{f1(x["tm"])}{dl(x["dtm"])}</td><td>{pc(x["w"])}</td></tr>' for x in xs)
    tables += f'<section class="c"><h3>{n} <span class="sub">{len(xs)}</span></h3><div class="tw"><table><tr><th></th><th>Long-term</th><th>Timing</th><th>1 week</th></tr>{tr}</table></div></section>'
moves = "" if first else (block("Long-term score up", facts["lt_up"], "dlt", "No rise.") + block("Long-term score down", facts["lt_down"], "dlt", "No fall.")
         + block("Timing up", facts["tm_up"], "dtm", "No rise.") + block("Timing down", facts["tm_down"], "dtm", "No fall."))
page = f"""<title>Watchlist Weekly Review</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root{{--bg:#eceff3;--card:#fff;--ink:#16191d;--ink2:#47505b;--ink3:#6b7480;--ln:rgba(0,0,0,.09);--up:#0e8a57;--dn:#c4314b;--acc:#1f6fc5;--lum:38%}}
@media (prefers-color-scheme: dark){{:root:not([data-theme="light"]){{--bg:#14171b;--card:#1d2127;--ink:#eef1f5;--ink2:#b6bec9;--ink3:#828b96;--ln:rgba(255,255,255,.1);--up:#3ddc97;--dn:#ff7a8a;--acc:#5db3ff;--lum:64%;color-scheme:dark}}}}
:root[data-theme="dark"]{{--bg:#14171b;--card:#1d2127;--ink:#eef1f5;--ink2:#b6bec9;--ink3:#828b96;--ln:rgba(255,255,255,.1);--up:#3ddc97;--dn:#ff7a8a;--acc:#5db3ff;--lum:64%;color-scheme:dark}}
body{{background:var(--bg);color:var(--ink);font:14px/1.5 Inter,system-ui,-apple-system,Segoe UI,Roboto,sans-serif}}
.w{{max-width:860px;margin:0 auto;padding-block:16px 40px;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}}
h1{{font-size:20px;margin:0;letter-spacing:-.01em;text-wrap:balance}}h3{{font-size:13px;margin:0 0 6px;text-transform:uppercase;letter-spacing:.05em;color:var(--ink2)}}
.sub{{color:var(--ink3);font-size:12px;font-weight:500}}.top{{display:flex;flex-wrap:wrap;gap:6px 12px;align-items:baseline;margin-bottom:12px}}
.c{{background:var(--card);border:1px solid var(--ln);border-radius:14px;padding:12px 14px;margin-bottom:10px;min-width:0}}
.g2{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px}}.g2 .c{{margin:0}}
.notes p{{margin:.3em 0 .6em;max-width:70ch}}ul{{list-style:none;margin:0;padding:0}}li{{display:flex;flex-wrap:wrap;gap:4px 6px;align-items:baseline;padding:5px 0;border-bottom:1px solid var(--ln)}}li:last-child{{border:0}}
.nm{{color:var(--ink2);font-size:12.5px;min-width:0}}.r{{margin-left:auto;white-space:nowrap}}.r i{{font-style:normal;font-weight:700;margin-left:6px}}.mt{{color:var(--ink3)}}
.k{{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;color:var(--ink3);border:1px solid var(--ln);border-radius:5px;padding:0 4px}}
.d{{font-size:11.5px;font-weight:600;margin-left:3px}}.d.u{{color:var(--up)}}.d.n{{color:var(--dn)}}
.tw{{overflow-x:auto}}table{{width:100%;border-collapse:collapse;font-size:13px}}td,th{{padding:5px 4px;border-bottom:1px solid var(--ln);text-align:right;white-space:nowrap}}td:first-child,th:first-child{{text-align:left;white-space:normal}}
th{{color:var(--ink3);font-size:11px;font-weight:600}}td small{{display:block;color:var(--ink3);font-size:11px;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}td b{{font-size:13px}}
a{{color:var(--acc)}}.ft{{color:var(--ink3);font-size:11.5px;margin-top:14px}}
</style>
<div class="w">
<div class="top"><h1>Watchlist weekly review</h1><span class="sub">{fd(cur_d)}{" · vs " + fd(prev_d) if prev_d else " · first weekly run"} · {facts["scored"]} of {len(rows)} scored</span></div>
{f'<section class="c notes"><h3>This week</h3>{notes}</section>' if notes else ""}
<div class="g2">
<section class="c"><h3>Worth a closer look</h3><ul>{watch_html}</ul><p class="sub">Long-term ≥ 6.2 with timing ≥ 6.2 or improving by 1+ point. Long-term · timing.</p></section>
<section class="c"><h3>Alerts</h3><ul>{flag_html}</ul></section>
{moves}
{"" if first else f'<section class="c"><h3>Indicators that moved most</h3><ul>{ind_html}</ul><p class="sub">Scored indicators whose score changed by 2+ points (out of 10).</p></section>'}
{block("Best week (price)", facts["price_up"], "w", "∅")}{block("Worst week (price)", facts["price_down"], "w", "∅")}
</div>
<div style="margin-top:10px">{tables}</div>
<p class="ft">Full details and every indicator's history: <a href="https://wassim96-dot.github.io/stockglass/history.html" target="_blank" rel="noopener">StockGlass watchlist history</a>. Scores from the weekly GitHub run of StockGlass (Yahoo Finance, SEC, Nasdaq). Rule-based screen on public data, not investment advice.</p>
</div>"""
open(os.path.join(A.out, "review.html"), "w", encoding="utf-8").write(page)
print(f"review.html + review.json written ({cur_d}{' vs ' + prev_d if prev_d else ', first run'}; {len(rows)} tickers)")
