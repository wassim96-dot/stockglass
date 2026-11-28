#!/usr/bin/env python3
"""Runs the Python copies of the shared rules for tests/check-copies.mjs (no network).

stdin: JSON list of calls [{"fn": "regime.fear_zone", "args": [...]}, ...]; stdout: JSON list of results ({"ok": value} or
{"err": message}). Modules: regime = scripts/regime.py (or the one given with --regime, e.g. the skill's copy);
weekly.credit_read = credit_read() taken from scripts/weekly_review.py (that file is a script, so only the function is loaded);
skill_render.credit_read = credit_read() from the skill's scripts/render.py when --render is given;
skill_score.consts = the WI, LENS, LENS_ETF, LENS_CRYPTO, TM_TIERS, TM_TIERS_ETF and SETUP_W literals of the skill's scripts/score.py
when --score is given; skill_score.setup_score = its setup_score() (short-term setup score, 28 Nov 2026).
"""
import ast, importlib.util, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


def load_function(path, fn, consts=None):
    """Exec only the named top-level function of a script file (plus the imports it needs and the constants given)."""
    src = open(path, encoding="utf-8").read(); tree = ast.parse(src)
    ns = dict(consts or {})
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)): exec(compile(ast.Module([node], []), path, "exec"), ns)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == fn:
            exec(compile(ast.Module([node], []), path, "exec"), ns); return ns[fn]
    raise KeyError(f"{fn} not found in {path}")


def load_consts(path, names):
    """Top-level literal assignments (dicts of numbers) of a script, without running it."""
    out = {}
    for node in ast.parse(open(path, encoding="utf-8").read()).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and getattr(node.targets[0], "id", None) in names:
            out[node.targets[0].id] = ast.literal_eval(node.value)
    return out


def main():
    args = sys.argv[1:]; opt = lambda k: args[args.index(k) + 1] if k in args else None
    mods = {"regime": load_module(opt("--regime") or os.path.join(ROOT, "scripts", "regime.py"), "regime_under_test")}
    fns = {"weekly.credit_read": lambda: load_function(os.path.join(ROOT, "scripts", "weekly_review.py"), "credit_read")}
    if opt("--score"):
        sys.path.insert(0, os.path.dirname(os.path.abspath(opt("--score"))))   # its imports (catalyst, ownership, flows) resolve from the skill folder
        fns["skill_score.consts"] = lambda: (lambda: load_consts(opt("--score"), {"WI", "LENS", "LENS_ETF", "LENS_CRYPTO", "TM_TIERS", "TM_TIERS_ETF", "SETUP_W"}))
        fns["skill_score.setup_score"] = lambda: load_function(opt("--score"), "setup_score", load_consts(opt("--score"), {"SETUP_W"}))
    if opt("--render"): fns["skill_render.credit_read"] = lambda: load_function(opt("--render"), "credit_read")
    cache, out = {}, []
    for call in json.load(sys.stdin):
        try:
            name = call["fn"]
            if name not in cache:
                mod, _, attr = name.partition(".")
                cache[name] = fns[name]() if name in fns else getattr(mods[mod], attr)
            out.append({"ok": cache[name](*call.get("args", []))})
        except Exception as e:                       # noqa: BLE001 (report, the JS side decides)
            out.append({"err": f"{type(e).__name__}: {e}"})
    json.dump(out, sys.stdout, default=lambda o: list(o) if isinstance(o, (tuple, set)) else str(o))


if __name__ == "__main__":
    main()
