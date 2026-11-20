#!/usr/bin/env python3
"""Watchlist Review: analyses the saved weekly runs over three horizons (since the start, last month, last week)
   and writes review.html (published as the "Watchlist Review" artifact) and review.json (the facts behind the written analysis).
   Usage: python3 scripts/weekly_review.py [--notes-start F] [--notes-month F] [--notes-week F] [--out DIR]
   Each notes file holds HTML paragraphs (<p>…</p>) written for that horizon; they appear at the top of its section."""
import json, os, html, argparse, datetime as dt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ap = argparse.ArgumentParser()
for h in ("start", "month", "week"): ap.add_argument(f"--notes-{h}")
ap.add_argument("--notes", help="(old option) same as --notes-week"); ap.add_argument("--out", default=ROOT)
A = ap.parse_args()
RUNS = json.load(open(os.path.join(ROOT, "data/runs/index.json")))["runs"]
DATA = {d: {r["sym"]: r for r in json.load(open(os.path.join(ROOT, f"data/runs/{d}.json")))["results"]} for d in RUNS}
cur_d = RUNS[-1]; CUR = DATA[cur_d]; D = dt.date.fromisoformat
num = lambda x: isinstance(x, (int, float)) and not isinstance(x, bool)
e = lambda s: html.escape(str(s if s is not None else ""))
KIND = {"fund": "ETF", "index": "Index", "crypto": "Crypto"}
kind = lambda r: r.get("kind") or ("index" if r["sym"].startswith("^") else "crypto" if r["sym"].endswith("-USD") else "equity")
sc = lambda r, k: (r or {}).get(k, {}).get("score") if r else None
lab = lambda r, k: ((r or {}).get(k) or {}).get("label")
def tier(l):
    l = (l or "").lower()
    for t, i in (("strong", 4), ("favourable", 3), ("mostly favourable", 3), ("mixed", 2), ("neutral", 2), ("weak", 1), ("unfavourable", 1), ("poor", 0)):
        if l.startswith(t): return i
    return None
def slope(ys):  # least-squares slope per week
    p = [(i, y) for i, y in enumerate(ys) if num(y)]
    if len(p) < 3: return None
    n = len(p); mx = sum(i for i, _ in p) / n; my = sum(y for _, y in p) / n
    den = sum((i - mx) ** 2 for i, _ in p)
    return sum((i - mx) * (y - my) for i, y in p) / den if den else None
def streak(ys):  # consecutive weekly rises (+n) or falls (−n) ending now
    v = [y for y in ys if num(y)]; s = 0
    for a, b in zip(v[-2::-1], v[:0:-1]):
        d = b - a
        if abs(d) < .05: break
        if s == 0: s = 1 if d > 0 else -1
        elif (d > 0) == (s > 0): s += 1 if s > 0 else -1
        else: break
    return s

def horizon(base_d, label, key):
    """Compare the latest run with base_d, using every run in between for trends."""
    if base_d is None: return {"key": key, "label": label, "available": False}
    win = [d for d in RUNS if D(base_d) <= D(d) <= D(cur_d)]; BASE = DATA[base_d]; out = []
    for s, r in CUR.items():
        b = BASE.get(s); seq = [DATA[d].get(s) for d in win]
        lt = [sc(x, "long_term") for x in seq]; tm = [sc(x, "timing") for x in seq]
        ltv = [v for v in lt if num(v)]
        x = {"sym": s, "name": r.get("name"), "kind": kind(r), "lt": sc(r, "long_term"), "tm": sc(r, "timing"), "ltl": lab(r, "long_term"), "tml": lab(r, "timing"),
             "dlt": None, "dtm": None, "dpx": None, "lt_min": min(ltv) if ltv else None, "lt_max": max(ltv) if ltv else None,
             "lt_avg": round(sum(ltv) / len(ltv), 2) if ltv else None, "slope": slope(lt), "streak": streak(lt), "labels": [], "ind": [], "cross": None, "new": b is None}
        if b:
            if num(x["lt"]) and num(sc(b, "long_term")): x["dlt"] = round(x["lt"] - sc(b, "long_term"), 1)
            if num(x["tm"]) and num(sc(b, "timing")): x["dtm"] = round(x["tm"] - sc(b, "timing"), 1)
            if num(r.get("price")) and num(b.get("price")) and b["price"] > 0 and r.get("cur") == b.get("cur"): x["dpx"] = round((r["price"] / b["price"] - 1) * 100, 1)
            for k, n in (("long_term", "long-term"), ("timing", "timing")):
                if tier(lab(b, k)) is not None and tier(lab(r, k)) is not None and tier(lab(b, k)) != tier(lab(r, k)):
                    x["labels"].append({"what": n, "was": lab(b, k), "now": lab(r, k), "up": tier(lab(r, k)) > tier(lab(b, k))})
            for k, m in (r.get("metrics") or {}).items():
                q = (b.get("metrics") or {}).get(k) or {}
                if not m.get("ctx") and num(m.get("sc")) and num(q.get("sc")) and abs(m["sc"] - q["sc"]) >= 2:
                    path = [((y or {}).get("metrics") or {}).get(k, {}).get("sc") for y in seq]
                    p = [v for v in path if num(v)]
                    steady = len(p) >= 4 and (all(b2 >= a2 for a2, b2 in zip(p, p[1:])) or all(b2 <= a2 for a2, b2 in zip(p, p[1:])))
                    x["ind"].append({"k": k, "l": m.get("l", k), "was": q.get("d"), "now": m.get("d"), "dsc": round(m["sc"] - q["sc"], 1), "steady": steady})
            x["ind"] = sorted(x["ind"], key=lambda i: -abs(i["dsc"]))[:4]
            ev, ew = ((r.get("metrics") or {}).get("e200") or {}).get("v"), ((b.get("metrics") or {}).get("e200") or {}).get("v")
            if num(ev) and num(ew) and (ev >= 0) != (ew >= 0): x["cross"] = "above" if ev >= 0 else "below"
        out.append(x)
    def avg(rows, k, kd=None):
        v = [sc(r, k) for r in rows.values() if (kd is None or kind(r) == kd) and num(sc(r, k))]
        return round(sum(v) / len(v), 2) if v else None
    kinds = sorted({kind(r) for r in CUR.values()}, key=["equity", "fund", "index", "crypto"].index)
    agg = {kd: {"lt_was": avg(BASE, "long_term", kd), "lt_now": avg(CUR, "long_term", kd), "tm_was": avg(BASE, "timing", kd), "tm_now": avg(CUR, "timing", kd)} for kd in kinds}
    path = [{"d": d, "lt": avg(DATA[d], "long_term"), "tm": avg(DATA[d], "timing")} for d in win]
    tiers_was = [tier(lab(r, "long_term")) for r in BASE.values()]; tiers_now = [tier(lab(r, "long_term")) for r in CUR.values()]
    cnt = lambda T: {n: sum(1 for t in T if t == i) for i, n in ((4, "Strong"), (3, "Favourable"), (2, "Mixed"), (1, "Weak"), (0, "Poor"))}
    top = lambda k, rev=True, n=5: sorted([x for x in out if num(x[k]) and abs(x[k]) >= .05], key=lambda x: x[k], reverse=rev)[:n]
    return {"key": key, "label": label, "available": True, "from": base_d, "to": cur_d, "weeks": len(win) - 1, "runs": len(win),
            "lt_up": top("dlt"), "lt_down": top("dlt", False), "tm_up": top("dtm"), "tm_down": top("dtm", False),
            "px_up": top("dpx"), "px_down": top("dpx", False),
            "steady_up": sorted([x for x in out if num(x["slope"]) and x["slope"] >= .1], key=lambda x: -x["slope"])[:5] if len(win) >= 3 else [],
            "steady_down": sorted([x for x in out if num(x["slope"]) and x["slope"] <= -.1], key=lambda x: x["slope"])[:5] if len(win) >= 3 else [],
            "labels": [x for x in out if x["labels"]], "indicators": sorted([x for x in out if x["ind"]], key=lambda x: -max(abs(i["dsc"]) for i in x["ind"]))[:10],
            "crossings": [x for x in out if x["cross"]], "averages": agg, "path": path, "tiers_was": cnt(tiers_was), "tiers_now": cnt(tiers_now),
            "added": sorted(set(CUR) - set(BASE)), "removed": sorted(set(BASE) - set(CUR)), "rows": out}

prev_d = RUNS[-2] if len(RUNS) > 1 else None
month_base = None
if prev_d:
    older = [d for d in RUNS[:-1] if (D(cur_d) - D(d)).days >= 26]
    month_base = older[-1] if older else RUNS[0]
H = {"start": horizon(RUNS[0] if len(RUNS) > 1 else None, "Since the start", "start"),
     "month": horizon(month_base, "Last month", "month"),
     "week": horizon(prev_d, "Last week", "week")}
if H["month"]["available"] and (D(cur_d) - D(month_base)).days < 26: H["month"]["short"] = True

# current-state lists (not tied to a horizon)
alerts = []
for s, r in CUR.items():
    f = []
    ne = r.get("next_earnings")
    if ne and ne.get("date"):
        days = (D(ne["date"]) - D(cur_d)).days
        if 0 <= days <= 14: f.append(f"earnings on {ne['date']}" + ("" if ne.get("confirmed") else " (est.)"))
    if r.get("warning"): f.append("data warning: " + r["warning"])
    if f: alerts.append({"sym": s, "name": r.get("name"), "kind": kind(r), "flags": f})
wk = {x["sym"]: x for x in (H["week"].get("rows") or [])}; st = {x["sym"]: x for x in (H["start"].get("rows") or [])}
watch = []
for s, r in CUR.items():
    lt, tm = sc(r, "long_term"), sc(r, "timing")
    if num(lt) and lt >= 6.2 and num(tm) and (tm >= 6.2 or (num((wk.get(s) or {}).get("dtm")) and wk[s]["dtm"] >= 1)):
        watch.append({"sym": s, "name": r.get("name"), "kind": kind(r), "lt": lt, "tm": tm, "ltl": lab(r, "long_term"),
                      "streak": (st.get(s) or {}).get("streak") or 0})
watch = sorted(watch, key=lambda x: -(x["lt"] + x["tm"]))[:6]
facts = {"date": cur_d, "first_run": RUNS[0], "runs": len(RUNS), "count": len(CUR), "watch": watch, "alerts": alerts,
         "horizons": {k: {kk: vv for kk, vv in v.items() if kk != "rows"} for k, v in H.items()}}
json.dump(facts, open(os.path.join(A.out, "review.json"), "w"), indent=1, ensure_ascii=False)

# ---------- page ----------
def col(s):  # same tier colours as Stock Verdict History
    if not num(s): return "var(--ink3)"
    return "var(--good)" if s >= 7.5 else "var(--ok)" if s >= 6.2 else "var(--warn)" if s >= 4.5 else "#ff9a6b" if s >= 3 else "var(--bad)"
dl = lambda v: "" if not num(v) or abs(v) < .05 else f'<span class="d {"u" if v > 0 else "n"}">{"▲" if v > 0 else "▼"}{abs(v):.1f}</span>'
pc = lambda v: "" if not num(v) else f'<span class="d {"u" if v >= 0 else "n"}">{v:+.1f}%</span>'
f1 = lambda v: f"{v:.1f}" if num(v) else "∅"
badge = lambda x: f'<span class="k">{KIND[x["kind"]]}</span>' if x["kind"] in KIND else ""
fd = lambda d: D(d).strftime("%-d %b %Y")
def ul(items, empty): return "<ul>" + ("".join(items) or f'<li class="mt">{empty}</li>') + "</ul>"
def li(x, right, sub=None): return f'<li><b>{e(x["sym"])}</b>{badge(x)} <span class="nm">{e(sub if sub is not None else x["name"])}</span><span class="r">{right}</span></li>'
def card(title, body, note=""): return f'<section class="c"><h3>{title}</h3>{body}{f"<p class=sub>{note}</p>" if note else ""}</section>'
def spark(path):
    pts = [(i, p["lt"], p["tm"]) for i, p in enumerate(path)]
    if len(pts) < 2: return ""
    vals = [v for p in pts for v in p[1:] if num(v)]
    if not vals: return ""
    lo, hi = min(vals) - .3, max(vals) + .3
    W, Hh = 300, 60; n = len(pts) - 1; y = lambda v: Hh - 6 - (v - lo) / (hi - lo) * (Hh - 12)
    line = lambda j, c: '<path d="' + "".join(("M" if i == 0 else "L") + f"{6 + i * (W - 12) / n:.1f} {y(p[j]):.1f}" for i, p in enumerate(pts) if num(p[j])) + f'" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
    return f'<svg class="sp" viewBox="0 0 {W} {Hh}" preserveAspectRatio="none" role="img" aria-label="Average scores over time"><line x1="0" x2="{W}" y1="{y(5):.1f}" y2="{y(5):.1f}" stroke="rgba(150,190,240,.25)" stroke-dasharray="3 4"/>{line(1, "var(--lt)")}{line(2, "var(--tm)")}</svg><p class="sub"><span style="color:var(--lt)">— average long-term</span> · <span style="color:var(--tm)">— average timing</span> · scale {lo + .3:.1f}–{hi - .3:.1f}</p>'
def notes_for(k):
    f = getattr(A, f"notes_{k}") or (A.notes if k == "week" else None)
    return open(f, encoding="utf-8").read() if f and os.path.exists(f) else ""
KN = {"equity": "Stocks", "fund": "ETFs", "index": "Indices", "crypto": "Crypto"}
def section(h):
    k = h["key"]; nt = notes_for(k)
    if not h["available"]:
        why = "Needs at least two weekly runs." if k != "month" else "Needs at least two weekly runs; a full month of history from four weeks on."
        return f'<section class="hz" id="{k}"><h2>{h["label"]}</h2>{f"<div class=c>{nt}</div>" if nt else ""}<p class="sub">{why} Data so far: {len(RUNS)} run{"s" if len(RUNS) != 1 else ""} since {fd(RUNS[0])}.</p></section>'
    sub = f'{fd(h["from"])} → {fd(h["to"])} · {h["weeks"]} week{"s" if h["weeks"] != 1 else ""}' + (" · history shorter than a month so far" if h.get("short") else "")
    mv = lambda xs, key, sco: [li(x, dl(x[key]) + f' <i style="color:{col(x[sco])}">{f1(x[sco])}</i>') for x in xs]
    pxl = lambda xs: [li(x, pc(x["dpx"])) for x in xs]
    labs = [li(x, "", "; ".join(f'{l["what"]}: {l["was"]} → {l["now"]}' for l in x["labels"])) for x in h["labels"]]
    inds = [li(x, "", "; ".join(f'{i["l"]} {i["was"]} → {i["now"]} ({i["dsc"]:+.1f}{", steady" if i["steady"] else ""})' for i in x["ind"])) for x in h["indicators"]]
    cross = [li(x, "", f'moved {x["cross"]} its 200-day average') for x in h["crossings"]]
    aver = "".join(f'<tr><td>{KN[kd]}</td><td>{f1(a["lt_was"])} → <b style="color:{col(a["lt_now"])}">{f1(a["lt_now"])}</b></td><td>{f1(a["tm_was"])} → <b style="color:{col(a["tm_now"])}">{f1(a["tm_now"])}</b></td></tr>' for kd, a in h["averages"].items())
    tw, tn = h["tiers_was"], h["tiers_now"]
    tiers = " · ".join(f'{n} {tw[n]}→{tn[n]}' for n in tn if tw[n] or tn[n])
    body = f'<div class="c"><h3>Watchlist averages</h3><div class="tw"><table><tr><th></th><th>Long-term</th><th>Timing</th></tr>{aver}</table></div><p class="sub">Long-term labels: {tiers}</p>{spark(h["path"]) if k != "week" else ""}</div>'
    grid = (card("Long-term score up", ul(mv(h["lt_up"], "dlt", "lt"), "No rise.")) + card("Long-term score down", ul(mv(h["lt_down"], "dlt", "lt"), "No fall."))
            + card("Timing up", ul(mv(h["tm_up"], "dtm", "tm"), "No rise.")) + card("Timing down", ul(mv(h["tm_down"], "dtm", "tm"), "No fall."))
            + card("Best price change", ul(pxl(h["px_up"]), "∅")) + card("Worst price change", ul(pxl(h["px_down"]), "∅")))
    if h["runs"] >= 3:
        grid += card("Steadily improving", ul([li(x, f'{x["slope"]:+.2f}/wk <i style="color:{col(x["lt"])}">{f1(x["lt"])}</i>') for x in h["steady_up"]], "None yet."), "Long-term score trend per week (least-squares slope over every run).")
        grid += card("Steadily weakening", ul([li(x, f'{x["slope"]:+.2f}/wk <i style="color:{col(x["lt"])}">{f1(x["lt"])}</i>') for x in h["steady_down"]], "None."))
    grid += card("Label changes", ul(labs, "No label changed.")) + card("Indicators that moved most", ul(inds, "No scored indicator moved by 2+ points."), "Score change out of 10; “steady” = moved the same way in every run of the period.")
    if cross: grid += card("200-day average crossings", ul(cross, ""))
    extra = ""
    if h["added"] or h["removed"]: extra = f'<p class="sub">{"Added: " + ", ".join(h["added"]) + ". " if h["added"] else ""}{"Removed: " + ", ".join(h["removed"]) + "." if h["removed"] else ""}</p>'
    return f'<section class="hz" id="{k}"><h2>{h["label"]} <span class="sub">{sub}</span></h2>{f"<div class=c>{nt}</div>" if nt else ""}{body}<div class="g2">{grid}</div>{extra}</section>'

wkrows = {x["sym"]: x for x in (H["week"].get("rows") or [])}; strows = {x["sym"]: x for x in (H["start"].get("rows") or [])}
tables = ""
for kd, n in KN.items():
    xs = sorted([(s, r) for s, r in CUR.items() if kind(r) == kd], key=lambda t: -(sc(t[1], "long_term") if num(sc(t[1], "long_term")) else -1))
    if not xs: continue
    tr = "".join(f'<tr><td><b>{e(s)}</b><small>{e(r.get("name"))}</small></td><td style="color:{col(sc(r, "long_term"))}">{f1(sc(r, "long_term"))}{dl((wkrows.get(s) or {}).get("dlt"))}</td>'
                 f'<td style="color:{col(sc(r, "timing"))}">{f1(sc(r, "timing"))}{dl((wkrows.get(s) or {}).get("dtm"))}</td><td>{dl((strows.get(s) or {}).get("dlt")) or "–"}</td><td>{pc(r.get("chg_1w"))}</td></tr>' for s, r in xs)
    tables += f'<section class="c"><h3>{n} <span class="sub">{len(xs)}</span></h3><div class="tw"><table><tr><th></th><th>Long-term</th><th>Timing</th><th>Since start</th><th>1 week</th></tr>{tr}</table></div></section>'
watch_html = ul([li(x, f'<i style="color:{col(x["lt"])}">{f1(x["lt"])}</i> <i style="color:{col(x["tm"])}">{f1(x["tm"])}</i>', f'{x["name"]} · {x["ltl"]}' + (f' · improving {x["streak"]} weeks' if x["streak"] >= 2 else "")) for x in watch],
                "No name combines a favourable long-term score with favourable timing this week.")
alert_html = ul([li(x, "", "; ".join(x["flags"])) for x in alerts], "Nothing notable.")
page = f"""<title>Watchlist Review</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root{{--bg:#12243d;--ink:#eef5ff;--ink2:#b7c9e2;--ink3:#8199ba;--ln:rgba(150,190,240,.2);--good:#3ddc97;--ok:#9be36b;--warn:#ffb84a;--bad:#ff6b81;--lt:#3ddc97;--tm:#5aa9ff;--acc:#9fd0ff;color-scheme:dark}}
*{{box-sizing:border-box}}
body{{margin:0;font:13.5px/1.5 Inter,-apple-system,"Segoe UI",Roboto,sans-serif;color:var(--ink);background:var(--bg);background-image:linear-gradient(160deg,#10203a 0%,#152a49 55%,#183153 100%);background-attachment:fixed;min-height:100vh;font-variant-numeric:tabular-nums}}
.w{{max-width:900px;margin:0 auto;padding-block:18px 36px;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}}
h1{{font-size:22px;font-weight:800;letter-spacing:-.02em;margin:0;text-wrap:balance}}h2{{font-size:17px;font-weight:800;letter-spacing:-.01em;margin:24px 0 10px;text-wrap:balance}}
h3{{font-size:11px;font-weight:700;margin:0 0 6px;text-transform:uppercase;letter-spacing:.06em;color:var(--ink3)}}
.sub{{color:var(--ink3);font-size:12px;font-weight:500}}.top{{display:flex;flex-wrap:wrap;gap:6px 12px;align-items:baseline;margin-bottom:10px}}
.nav{{display:flex;gap:6px;flex-wrap:wrap;margin:6px 0 14px}}.nav a{{text-decoration:none;color:var(--ink);background:rgba(255,255,255,.08);border:1px solid var(--ln);border-radius:99px;padding:4px 12px;font-size:12px;font-weight:600}}
.c{{background:linear-gradient(150deg,rgba(84,120,172,.42),rgba(38,66,110,.34));border:1px solid rgba(160,200,245,.22);border-radius:18px;box-shadow:inset 0 1px 0 rgba(255,255,255,.18),0 12px 34px rgba(3,10,30,.4);padding:14px 16px;margin-bottom:12px;min-width:0}}
.c p{{margin:.3em 0 .6em;max-width:72ch;color:var(--ink)}}.c p.sub{{color:var(--ink3);font-size:11.5px}}
.g2{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,270px),1fr));gap:12px}}.g2 .c{{margin:0}}
ul{{list-style:none;margin:0;padding:0}}li{{display:flex;flex-wrap:wrap;gap:4px 6px;align-items:baseline;padding:6px 0;border-bottom:1px solid var(--ln)}}li:last-child{{border:0}}
li b{{font-weight:800}}.nm{{color:var(--ink3);font-size:12px;min-width:0}}.r{{margin-left:auto;white-space:nowrap}}.r i{{font-style:normal;font-weight:800;margin-left:6px}}.mt{{color:var(--ink3)}}
.k{{font-size:10px;padding:0 7px;border-radius:99px;border:1px solid var(--ln);color:var(--ink3);font-weight:600}}
.d{{font-size:11px;font-weight:800;margin-left:5px}}.d.u{{color:var(--good)}}.d.n{{color:var(--bad)}}
.tw{{overflow-x:auto}}table{{width:100%;border-collapse:collapse;font-size:12.5px}}td,th{{padding:5px 6px;border-bottom:1px solid var(--ln);text-align:right;white-space:nowrap}}td{{color:var(--ink2)}}
td:first-child,th:first-child{{text-align:left;white-space:normal}}th{{color:var(--ink3);font-size:10.5px;font-weight:600}}td b{{color:var(--ink);font-weight:800}}
td small{{display:block;color:var(--ink3);font-size:11px;max-width:190px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
svg.sp{{width:100%;height:64px;display:block;margin-top:8px}}a{{color:var(--acc)}}.ft{{color:var(--ink3);font-size:11px;margin-top:16px}}
</style>
<div class="w">
<div class="top"><h1>Watchlist review</h1><span class="sub">{fd(cur_d)} · {len(CUR)} tickers · {len(RUNS)} weekly run{"s" if len(RUNS) != 1 else ""} since {fd(RUNS[0])}</span></div>
<nav class="nav"><a href="#start">Since the start</a><a href="#month">Last month</a><a href="#week">Last week</a><a href="#all">All scores</a></nav>
<div class="g2">{card("Worth a closer look", watch_html, "Long-term ≥ 6.2 with timing ≥ 6.2 or up 1+ point this week. Scores: long-term · timing.")}{card("Alerts", alert_html, "Earnings within 14 days and data warnings.")}</div>
{section(H["start"])}{section(H["month"])}{section(H["week"])}
<h2 id="all">All scores <span class="sub">change vs last week · since start</span></h2>{tables}
<p class="ft">Every indicator's history: <a href="https://wassim96-dot.github.io/stockglass/history.html" target="_blank" rel="noopener">StockGlass watchlist history</a>. Scores from the weekly GitHub run of StockGlass (Yahoo Finance, SEC, Nasdaq). Rule-based screen on public data, not investment advice.</p>
</div>"""
open(os.path.join(A.out, "review.html"), "w", encoding="utf-8").write(page)
print(f"review.html + review.json written: {cur_d}, {len(RUNS)} runs since {RUNS[0]}; horizons: " + ", ".join(f'{k} {"from " + v["from"] if v["available"] else "n/a"}' for k, v in H.items()))
