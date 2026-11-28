"""Guidance & news catalyst score and the third score ("Timing + guidance & news").

Evidence behind the design (see references/guidance.md):
- Investors underreact to management-forecast (guidance) news, so prices keep drifting after it
  (Ng, Tuna & Verdi 2013, Review of Accounting Studies).
- Earnings news (surprises, announcement returns, analyst revisions) predicts returns over the next
  months and adds to price momentum; momentum is strongest when price and earnings news agree
  (Chan, Jegadeesh & Lakonishok 1996, Journal of Finance).
- The price reaction around the report (earnings-announcement return) drifts further and does not
  reverse (Brandt, Kishore, Santa-Clara & Venkatachalam, "Earnings announcements are full of surprises").
- Post-earnings drift lasts about 60 trading days (Bernard & Thomas 1989).
- Weekly aggregated news predicts returns for about one quarter; positive news is absorbed within
  1-2 weeks, negative news over up to 13 weeks (Heston & Sinha 2017, Financial Analysts Journal);
  negative words in firm news predict lower earnings and returns (Tetlock, Saar-Tsechansky & Macskassy 2008).
Weights are judgement-based priors informed by that evidence, not fitted to data.
"""
import math, re
from datetime import date

# ---- parameters -------------------------------------------------------------------------------
G_WEIGHTS = {"surprise": 0.35, "trend": 0.35, "reaction": 0.30}      # inside the guidance score
# Earnings-news composite (indicator review 18 Nov 2026): guidance, EPS surprise (SUE), estimate revisions and news are only
# moderately correlated (SUE–revisions 0.44, each with past returns ~0.29; Chan, Jegadeesh & Lakonishok 1996) and each adds
# information, so they are averaged here once; the entry-timing score no longer contains surprise or revisions.
C_WEIGHTS = {"guidance": 0.45, "surprise": 0.20, "revision": 0.15, "news": 0.20}
BLEND_BY_N = {4: 0.40, 3: 0.40, 2: 0.30, 1: 0.20}                     # catalyst weight in the third score by number of parts
RECENCY = [0.4, 0.3, 0.2, 0.1]                                        # newest -> oldest guidance updates
ACTION = {"raised": 1.0, "increased": 1.0, "lowered": -1.0, "cut": -1.0, "reduced": -1.0, "withdrawn": -1.0,
          "suspended": -1.0, "maintained": 0.0, "confirmed": 0.0, "reiterated": 0.0, "initiated": 0.0, "narrowed": 0.0}
SURPRISE_BANDS = [(-5, 0), (-3, 1.5), (-1.5, 3), (-0.5, 4.5), (0.5, 5.5), (1.5, 7), (3, 8.5), (5, 10)]   # % vs consensus
REACTION_BANDS = [(-12, 0), (-8, 1.5), (-4, 3), (-1.5, 4.5), (1.5, 5.5), (4, 7), (8, 8.5), (12, 10)]   # abnormal % move
QUAL = {"above": 7.5, "beat": 7.5, "in line": 5.0, "inline": 5.0, "below": 2.5, "miss": 2.5}
DRIFT_HALF_LIFE = 90          # days: surprise and reaction fade toward neutral as the report ages (PEAD ~60 trading days)
NEWS_WINDOW = 91              # days (13 weeks, Heston & Sinha)
NEWS_HALF_LIFE = {1: 7, -1: 30, 0: 14}        # positive news absorbed fast, negative slowly
IMPACT = {"positive": 1, "negative": -1, "neutral": 0, "uncertain": 0, "mixed": 0}
SCOPE_STOCK = {"company": 1.0, "sector": 0.6, "event": 0.5, "market": 0.4, "macro": 0.4, "geopolitics": 0.4}
SCOPE_ETF = {"company": 0.6, "sector": 0.8, "event": 0.8, "market": 1.0, "macro": 1.0, "geopolitics": 1.0}
MATERIALITY = {"high": 1.5, "medium": 1.0, "low": 0.5}
PRIOR_WEIGHT = 1.0            # shrinks the news score toward neutral when there is little news

MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}

def num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None

def band(v, s):
    if v is None: return None
    if v <= s[0][0]: return s[0][1]
    for (a, x), (b, y) in zip(s, s[1:]):
        if v <= b: return x + (y - x) * (v - a) / (b - a)
    return s[-1][1]

def pdate(x):
    """ISO date, or '28 Oct 2026', '25–26 Oct 2026' (last day), 'Oct 28, 2026'. None if not a single dated day."""
    if not isinstance(x, str): return None
    s = x.strip()
    try: return date.fromisoformat(s[:10])
    except Exception: pass
    m = re.search(r"(\d{1,2})(?:\s*[–-]\s*(\d{1,2}))?\s+([A-Za-z]{3})[a-z]*\.?\s+(\d{4})", s)
    if m and m.group(3).lower() in MONTHS:
        d = int(m.group(2) or m.group(1))
        try: return date(int(m.group(4)), MONTHS[m.group(3).lower()], d)
        except ValueError: return None
    m = re.search(r"([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})", s)
    if m and m.group(1).lower() in MONTHS:
        try: return date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))
        except ValueError: return None
    return None

def fade(score, age):
    if score is None or age is None: return score
    return 5 + (score - 5) * 0.5 ** (max(age, 0) / DRIFT_HALF_LIFE)

def human(v, unit=None):
    if v is None: return "?"
    if unit == "%": return f"{v:g}%"
    a = abs(v)
    for d, s in ((1e12, " T"), (1e9, " B"), (1e6, " M")):
        if a >= d: return f"{v / d:.3g}{s}"
    return f"{v:g}"

CUR = {"EUR": "€", "USD": "$", "GBP": "£", "CHF": "CHF ", "JPY": "¥", "SEK": "SEK ", "DKK": "DKK ", "NOK": "NOK "}

def fmt_range(lo, hi, mid, unit=None, currency=None):
    pre = "" if unit == "%" else CUR.get(str(currency or "").upper(), "")
    if lo is not None and hi is not None and lo != hi:
        a, b = human(lo, unit), human(hi, unit)
        sa, sb = a.rsplit(" ", 1) if " " in a else (a, ""), b.rsplit(" ", 1) if " " in b else (b, "")
        if unit == "%": return f"{lo:g}–{hi:g}%"
        if sa[1] == sb[1]: return f"{pre}{sa[0]}–{sb[0]}" + (f" {sb[1]}" if sb[1] else "")
        return f"{pre}{a}–{pre}{b}"
    return (pre + human(mid, unit)) if mid is not None else "—"

def guidance_block(GD, REF, currency=None):
    items = [dict(x) for x in (GD.get("items") or []) if isinstance(x, dict)]
    rows = []
    for it in items:
        d = pdate(it.get("date"))
        if d is None or d > REF: continue
        lo, hi = num(it.get("low")), num(it.get("high"))
        mid = num(it.get("mid"))
        if mid is None and lo is not None and hi is not None: mid = (lo + hi) / 2
        elif mid is None: mid = lo if lo is not None else hi
        it.update(_d=d, _mid=mid, _lo=lo, _hi=hi)
        rows.append(it)
    rows.sort(key=lambda r: r["_d"])
    if not rows: return None
    prev = None
    for r in rows:
        act = str(r.get("action") or "").strip().lower()
        same = prev is not None and str(prev.get("metric") or "") == str(r.get("metric") or "")   # metric names the guided period
        chg = None
        if same and prev["_mid"] not in (None, 0) and r["_mid"] is not None:
            chg = (r["_mid"] / prev["_mid"] - 1) * 100
        if not act:   # derive the action when only numbers were given
            if prev is None or not same: act = "initiated" if r["_mid"] is not None else "none"
            elif chg is None: act = "maintained"
            elif chg > 0.5: act = "raised"
            elif chg < -0.5: act = "lowered"
            else:
                w0 = (prev["_hi"] - prev["_lo"]) if None not in (prev["_hi"], prev["_lo"]) else None
                w1 = (r["_hi"] - r["_lo"]) if None not in (r["_hi"], r["_lo"]) else None
                act = "narrowed" if w0 is not None and w1 is not None and w1 < w0 else "maintained"
        a = ACTION.get(act)
        if act == "narrowed" and chg is not None: a = 0.5 if chg > 0.1 else -0.5 if chg < -0.1 else 0.0
        r["_act"], r["_a"], r["_chg"] = act, a, chg
        sp = num(r.get("vs_consensus_pct"))
        cb = num(r.get("consensus_before"))
        if sp is None and cb not in (None, 0) and r["_mid"] is not None: sp = (r["_mid"] - cb) / abs(cb) * 100
        r["_sp"] = sp
        rx = num(r.get("reaction_pct"))
        bx = num(r.get("benchmark_pct"))
        # abnormal reaction = stock minus benchmark on the day; without the benchmark move the part is left out
        # (never "the market moved 0%"), and the guidance score rescales over surprise and trend
        r["_ab"] = None if rx is None or bx is None else rx - bx
        r["_raw"] = rx
        prev = r
    last = rows[-1]
    age = (REF - last["_d"]).days
    # g1 surprise of the latest guidance vs consensus
    g1 = band(last["_sp"], SURPRISE_BANDS)
    if g1 is None:
        q = str(last.get("vs_consensus") or "").strip().lower()
        g1 = QUAL.get(q)
    g1 = fade(g1, age)
    # g2 revision trend over the last 4 updates (recency weighted)
    recent = [r for r in rows if r["_a"] is not None][-4:][::-1]
    g2 = None
    if recent:
        ws = RECENCY[:len(recent)]
        g2 = 5 + 5 * sum(w * r["_a"] for w, r in zip(ws, recent)) / sum(ws)
    # g3 market reaction to the latest report
    g3 = fade(band(last["_ab"], REACTION_BANDS), age)
    comps = {"surprise": g1, "trend": g2, "reaction": g3}
    have = {k: v for k, v in comps.items() if v is not None}
    G = None
    if len(have) >= 2 and age <= 200:
        G = round(sum(G_WEIGHTS[k] * v for k, v in have.items()) / sum(G_WEIGHTS[k] for k in have), 1)
    # summary text
    acts = [r["_act"] for r in rows[-4:]]
    cnt = {k: sum(1 for a in acts if a in ks) for k, ks in (("raised", ("raised", "increased")), ("maintained", ("maintained", "confirmed", "reiterated", "narrowed")),
                                                            ("lowered", ("lowered", "cut", "reduced")), ("withdrawn", ("withdrawn", "suspended")))}
    net = sum(r["_a"] for r in rows[-4:] if r["_a"] is not None)
    trend_label = ("Rising" if net >= 1 and cnt["lowered"] + cnt["withdrawn"] == 0 else "Falling" if net <= -1 and cnt["raised"] == 0
                   else "Mixed" if cnt["raised"] and (cnt["lowered"] or cnt["withdrawn"]) else "Stable")
    no_rev = all(a in ("none", "initiated", "") for a in acts)
    if no_rev: trend_label = "n/a"   # quarter-by-quarter guidance (a new period each time): no revision of the same outlook to compare
    parts = [f"{v} {k}" for k, v in cnt.items() if v]
    sp = last["_sp"]
    vs = (f"above consensus ({sp:+.1f}%)" if sp is not None and sp > 0.5 else f"below consensus ({sp:+.1f}%)" if sp is not None and sp < -0.5
          else f"in line with consensus ({sp:+.1f}%)" if sp is not None else
          {"above": "above consensus", "beat": "above consensus", "in line": "in line with consensus", "inline": "in line with consensus",
           "below": "below consensus", "miss": "below consensus"}.get(str(last.get("vs_consensus") or "").lower(), "vs consensus: not available"))
    note = ((f"Guidance trend: n/a (each of the last {len(rows[-4:])} report(s) guided a new period, so there is no revision to compare); "
             if no_rev else f"Guidance trend: {trend_label.lower()} over the last {len(rows[-4:])} report(s) ({', '.join(parts) or 'no change recorded'}); ")
            + f"latest ({last.get('period') or last['_d']}) {last['_act']}, {vs}")
    if last["_ab"] is not None: note += f"; price reaction {last['_ab']:+.1f}% vs the market"
    elif last.get("_raw") is not None: note += f"; price reaction {last['_raw']:+.1f}% (benchmark move not available, so not scored)"
    note += "."
    out_rows = []
    for r in rows[-4:]:
        rng = r.get("text") or fmt_range(r["_lo"], r["_hi"], r["_mid"], r.get("unit"), currency)
        out_rows.append({"date": str(r["_d"]), "period": r.get("period"), "metric": r.get("metric"), "guidance": rng, "action": r["_act"],
                         "mid_change_pct": None if r["_chg"] is None else round(r["_chg"], 1),
                         "vs_consensus_pct": None if r["_sp"] is None else round(r["_sp"], 1), "vs_consensus": r.get("vs_consensus"),
                         "reaction_pct": None if r["_ab"] is None else round(r["_ab"], 1), "raw_reaction_pct": None if r.get("_raw") is None else round(r["_raw"], 1), "note": r.get("note"), "source": r.get("source")})
    return {"score": G, "components": {k: None if v is None else round(v, 1) for k, v in comps.items()}, "latest_age_days": age,
            "trend_label": trend_label, "latest_vs_consensus": vs, "beat_expectations": None if sp is None and not last.get("vs_consensus") else (sp is not None and sp > 0.5) or str(last.get("vs_consensus") or "").lower() in ("above", "beat"),
            "metric": GD.get("metric") or last.get("metric"), "items": out_rows, "note": note,
            "basis": "surprise vs consensus 35%, revision trend over 4 reports 35% (weights 4:3:2:1, newest first), price reaction 30%; surprise and reaction fade with a 90-day half-life"}

def news_block(items, REF, is_etf=False, has_guidance=False):
    scope_w = SCOPE_ETF if is_etf else SCOPE_STOCK
    used, W, S = [], 0.0, 0.0
    for x in items or []:
        if not isinstance(x, dict): continue
        d = pdate(x.get("date"))
        if d is None: continue
        age = (REF - d).days
        if age < 0 or age > NEWS_WINDOW: continue
        s = IMPACT.get(str(x.get("impact") or "").lower(), 0)
        w = scope_w.get(str(x.get("scope") or "").lower(), 0.5) * MATERIALITY.get(str(x.get("materiality") or "medium").lower(), 1.0)
        if has_guidance and str(x.get("kind") or "").lower() in ("results", "guidance", "earnings"): w *= 0.5   # already in the guidance score
        w *= 0.5 ** (age / NEWS_HALF_LIFE[s])
        W += w; S += w * s
        used.append({"date": str(d), "title": x.get("title"), "impact": s, "weight": round(w, 3)})
    if not used or W <= 0: return None
    net = S / W
    shrink = W / (W + PRIOR_WEIGHT)
    N = round(5 + 5 * net * shrink, 1)
    return {"score": N, "net_sentiment": round(net, 2), "effective_weight": round(W, 2), "shrink": round(shrink, 2), "n_items": len(used), "items": used,
            "basis": "impact ±1 × scope × materiality × recency (half-life 7 days for positive, 30 for negative, 14 for neutral news; last 13 weeks), shrunk toward 5 when news is thin"}

def third_score(timing_score, GB, NB, tiers, tier_fn, is_etf=False, event=None, sue=None, rev=None):
    parts = {"guidance": GB["score"] if GB else None, "surprise": sue, "revision": rev, "news": NB["score"] if NB else None}
    have = {k: v for k, v in parts.items() if v is not None}
    G, N = parts["guidance"], parts["news"]
    if have:
        C = sum(C_WEIGHTS[k] * v for k, v in have.items()) / sum(C_WEIGHTS[k] for k in have)
        w = BLEND_BY_N[len(have)]
        names = {"guidance": "guidance", "surprise": "EPS surprise", "revision": "estimate revisions", "news": "news"}
        avail = ", ".join(names[k] for k in have)
    else: C, w, avail = None, 0.0, "none"
    C = None if C is None else round(C, 1)
    T3 = None if timing_score is None or C is None else round((1 - w) * timing_score + w * C, 1)
    notes = []
    if T3 is not None:
        d_ = C - timing_score
        if (C - 5) * (timing_score - 5) < 0 and abs(d_) >= 2:
            notes.append("Guidance/news and the price trend point in opposite directions: price moves not confirmed by earnings news are the ones most likely to correct (Chan, Jegadeesh & Lakonishok 1996).")
        elif abs(C - 5) >= 1 and abs(timing_score - 5) >= 1 and (C - 5) * (timing_score - 5) > 0:
            notes.append("Guidance/news confirm the price trend: momentum is strongest when price and earnings news agree (Chan, Jegadeesh & Lakonishok 1996).")
    if event and event.get("in_window"):
        notes.append(f"New results and guidance are due on {event['date']}, inside the window: they will replace the guidance input.")
    t = tier_fn(T3, tiers) or {"tier": None, "label": "Not enough data" if timing_score is not None else "Not enough data", "meaning": ""}
    if T3 is None and timing_score is not None:
        t = {"tier": None, "label": "Not computed", "meaning": "No guidance, EPS surprise, estimate revision or dated news, so only the entry-timing score applies."}
    return {"name": "Timing + guidance & news", "score": T3, "horizon": "2–12 weeks",
            "question": "Do recent guidance and news strengthen or weaken the entry case?",
            "basis": (f"Entry timing {round((1 - w) * 100)}% + earnings-news composite {round(w * 100)}% ({avail}; weights guidance 45, surprise 20, revisions 15, news 20, rescaled to what is available)") if C is not None else "Needs guidance, an EPS surprise, estimate revisions or dated news",
            "catalyst_score": C, "guidance_score": G, "news_score": N, "surprise_score": None if sue is None else round(sue, 1), "revision_score": None if rev is None else round(rev, 1),
            "catalyst_weight": w, "available": avail, "parts_used": len(have),
            "data_confidence": "high" if len(have) >= 3 else "medium" if have else None,
            "notes": notes, **t}
