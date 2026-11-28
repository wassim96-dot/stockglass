"""Ownership evolution (context only, never scored): who holds the stock over the last four quarters.

Input: input.json -> ownership (see references/ownership.md)
  points  : up to 4 dated snapshots of the shareholder structure, in % of shares
            categories: institutional, retail, insiders, state, employees, strategic, treasury, public (undivided free float), other
  breadth : optional quarterly counts of 13F funds that opened/added vs trimmed/closed positions (US)
"""
from datetime import date

CATS = [("institutional", "Institutions"), ("retail", "Retail & other"), ("public", "Free float (undivided)"), ("insiders", "Insiders"),
        ("state", "State"), ("strategic", "Strategic holders"), ("employees", "Employees"), ("treasury", "Treasury shares"), ("other", "Other")]
LABEL = dict(CATS)

def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

def _d(x):
    try: return date.fromisoformat(str(x)[:10])
    except Exception: return None

def ownership_block(OW, REF):
    if not isinstance(OW, dict): return None
    pts = []
    for p in OW.get("points") or []:
        if not isinstance(p, dict): continue
        d = _d(p.get("date"))
        if d is None or d > REF: continue
        seg = {k: _num(p.get(k)) for k, _ in CATS if _num(p.get(k)) is not None}
        derived = False
        if "retail" not in seg and "institutional" in seg and OW.get("retail_is_remainder", True):
            rest = 100 - sum(v for k, v in seg.items() if k != "public")
            if rest >= 0: seg["retail"] = round(rest, 2); derived = True
        pts.append({"date": str(d), "period": p.get("period") or str(d), "segments": seg, "retail_derived": derived,
                    "holders": _num(p.get("holders")), "source": p.get("source")})
    pts.sort(key=lambda x: x["date"]); pts = pts[-4:]
    br = []
    for b in OW.get("breadth") or []:
        if not isinstance(b, dict): continue
        buy = (_num(b.get("new")) or 0) + (_num(b.get("increased")) or 0)
        sell = (_num(b.get("reduced")) or 0) + (_num(b.get("closed")) or 0)
        if buy + sell <= 0: continue
        br.append({"period": b.get("period"), "date": b.get("date"), "buyers": int(buy), "sellers": int(sell), "new": _num(b.get("new")), "closed": _num(b.get("closed")),
                   "buyers_pct": round(buy / (buy + sell) * 100, 1)})
    br.sort(key=lambda x: str(x.get("date") or x.get("period"))); br = br[-4:]
    if not pts and not br: return None
    changes, key, trend = {}, None, None
    if len(pts) >= 2:
        a, b = pts[0]["segments"], pts[-1]["segments"]
        changes = {k: round(b[k] - a[k], 2) for k in b if k in a}
        key = "institutional" if "institutional" in changes else "public" if "public" in changes else next(iter(changes), None)
        if key is not None:
            dv = changes[key]
            trend = "rising" if dv > 1 else "falling" if dv < -1 else "stable"
    parts = []
    if key is not None:
        parts.append(f"{LABEL[key]} {pts[0]['segments'][key]:.1f}% → {pts[-1]['segments'][key]:.1f}% ({changes[key]:+.1f} pt, {trend}) from {pts[0]['period']} to {pts[-1]['period']}")
    elif pts:
        s = pts[-1]["segments"]; parts.append(f"{pts[-1]['period']}: " + ", ".join(f"{LABEL[k]} {v:.1f}%" for k, v in s.items()))
    if br:
        parts.append("13F funds adding vs trimming: " + " → ".join(f"{x['period']} {x['buyers_pct']:.0f}%" for x in br) + " of position changes were buys")
    return {"points": pts, "breadth": br, "changes_pp": changes, "trend_key": key, "trend": trend,
            "source": OW.get("source"), "basis": OW.get("basis"), "note": "; ".join(parts) + "." if parts else None,
            "scored": False}
