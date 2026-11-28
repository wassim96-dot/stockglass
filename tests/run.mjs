// StockGlass offline tests (27 Nov 2026): no network, about 20 seconds. Run before every pull request (the "Tests" workflow
// runs it on each one): node tests/run.mjs [--skill ../stock-verdict]
//  1. syntax: every script, regime.js and the inline scripts of the pages compile; Python scripts compile; shell scripts parse
//  2. data files: every data/*.json parses; the glossary entries have a name, a "what" text and aliases
//  3. replay of the nightly job: data/market-history.json rebuilt by market-fear.mjs build() gives the saved phases and bear
//     states on every day since 2009 (2020 and 2022 included)
//  4. replay of the live page: liveFear() on each of the last 60 saved days, given that day's quotes, gives the saved phase
//  5. Minervini block of index.html (also used by daily-minervini.mjs) runs on a rising and a falling series
//  6. network helper: an answer that stalls after its headers is cut at the timeout; dead routes are dropped
//  7. copies of shared rules agree (tests/check-copies.mjs; skill copies too with --skill)
// Exit code 1 on any failure.
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { execFileSync } from "node:child_process";
import { createRequire } from "node:module";
import { checkCopies } from "./check-copies.mjs";

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const P = f => path.join(ROOT, f), J = f => JSON.parse(fs.readFileSync(P(f), "utf8"));
const fails = [];
const ok = (cond, msg) => { console.log(`${cond ? "ok  " : "FAIL"} ${msg}`); if (!cond) fails.push(msg); return cond; };
const run = (cmd, args) => { try { execFileSync(cmd, args, { stdio: "pipe" }); return null; } catch (e) { return (e.stderr || e.stdout || e.message).toString().trim().split("\n").slice(-3).join(" | "); } };
const section = t => console.log(`\n[${t}]`);

// 1. syntax
section("syntax");
for (const f of [...fs.readdirSync(P("scripts")).filter(f => f.endsWith(".mjs")).map(f => "scripts/" + f), ...fs.readdirSync(P("scripts/lib")).filter(f => f.endsWith(".mjs")).map(f => "scripts/lib/" + f), ...fs.readdirSync(P("tests")).filter(f => f.endsWith(".mjs")).map(f => "tests/" + f), "regime.js"]) {
  const e = run("node", ["--check", P(f)]); ok(!e, `${f} compiles${e ? ": " + e : ""}`);
}
for (const f of fs.readdirSync(ROOT).filter(f => f.endsWith(".html"))) {
  const html = fs.readFileSync(P(f), "utf8"), rx = /<script(\s[^>]*)?>([\s\S]*?)<\/script>/gi; let m, n = 0, bad = null;
  while ((m = rx.exec(html))) {
    const attrs = m[1] || ""; if (/\bsrc=/.test(attrs) || /type=["']?(application\/(ld\+)?json|text\/template)/.test(attrs) || !m[2].trim()) continue;
    n++; try { new vm.Script(m[2], { filename: f }); } catch (e) { bad = bad || `${e.message} (script ${n})`; }
  }
  ok(!bad, `${f}: ${n} inline script(s) compile${bad ? ": " + bad : ""}`);
}
for (const f of fs.readdirSync(P("scripts")).filter(f => f.endsWith(".py")).concat(["../tests/py_bridge.py"])) {
  const e = run("python3", ["-c", "import ast,sys; ast.parse(open(sys.argv[1]).read())", P("scripts/" + f)]); ok(!e, `${path.normalize("scripts/" + f)} compiles${e ? ": " + e : ""}`);
}
for (const f of fs.readdirSync(P("scripts")).filter(f => f.endsWith(".sh"))) { const e = run("bash", ["-n", P("scripts/" + f)]); ok(!e, `scripts/${f} parses${e ? ": " + e : ""}`); }

// 2. data files
section("data files");
for (const f of fs.readdirSync(P("data")).filter(f => f.endsWith(".json"))) { let e = null; try { J("data/" + f); } catch (x) { e = x.message; } ok(!e, `data/${f} parses${e ? ": " + e : ""}`); }
const GL = J("data/glossary.json"), badG = Object.entries(GL).filter(([, v]) => !v || !v.n || !v.w || !Array.isArray(v.a)).map(([k]) => k);
ok(!badG.length, `glossary: ${Object.keys(GL).length} entries with a name, a "what" text and aliases${badG.length ? "; missing in " + badG.join(", ") : ""}`);
// every tap-to-explain key the pages use exists in the glossary (28 Nov 2026): data-g="…" in the markup and code, Minervini
// rows (row("tt_…") / row("w_dir")), and the same in the skill's render.py when --skill is given. A missing key shows no ⓘ, silently.
{
  const si = process.argv.indexOf("--skill"), sk = si > 0 ? path.resolve(process.argv[si + 1]) : null;
  const files = ["index.html", "today.html", "history.html"].map(f => [f, fs.readFileSync(P(f), "utf8")]);
  if (sk && fs.existsSync(path.join(sk, "scripts/render.py"))) files.push(["skill render.py", fs.readFileSync(path.join(sk, "scripts/render.py"), "utf8")]);
  for (const [f, src] of files) {
    const keys = new Set([...src.matchAll(/data-g=\\?"([a-z][a-z0-9_]*)\\?"/g)].map(m => m[1]).concat([...src.matchAll(/row\(\s*"((?:tt_|w_)[a-z0-9_]+)"/g)].map(m => m[1])));
    const miss = [...keys].filter(k => !GL[k]);
    ok(!miss.length, `${f}: ${keys.size} tap-to-explain keys all in the glossary${miss.length ? "; missing " + miss.join(", ") : ""}`);
  }
}
const MH = J("data/market-history.json"), C = Object.fromEntries(MH.columns.map((k, i) => [k, i]));
ok(MH.rows.length > 2500 && MH.rows.every((r, i) => i === 0 || r[C.date] > MH.rows[i - 1][C.date]), `market history: ${MH.rows.length} rows in date order`);

// 3. nightly job replay: the saved history rebuilt from its own inputs gives the same phases
section("replay: nightly market-fear job");
{
  const { build, reading } = await import(P("scripts/market-fear.mjs"));
  const mp = k => new Map(MH.rows.filter(r => r[C[k]] != null).map(r => [r[C.date], r[C[k]]]));
  const days = MH.rows.map(r => r[C.date]), S = build(days, mp("vix"), mp("vix3m"), mp("spx"), mp("credit"));
  // from 2009 (the first two years are the HAR model's warm-up): every phase and every bear-state flag must match
  const saved = new Map(MH.rows.map(r => [r[C.date], r])), T = S.filter(s => s.date >= "2009-01-01");
  const miss = T.filter(s => saved.get(s.date)[C.phase] !== s.phase || !!saved.get(s.date)[C.bear] !== !!s.bear);
  ok(T.length > 4000 && miss.length === 0, `build() on the saved inputs: ${T.length - miss.length}/${T.length} days since 2009 match (phase and bear state; ${T.filter(s => s.bear).length} bear days)${miss.length ? "; first: " + miss.slice(0, 3).map(s => `${s.date} ${s.phase}≠${saved.get(s.date)[C.phase]}`).join(", ") : ""}`);
  const R = reading(S); ok(R && typeof R.score === "number" && R.phase === MH.rows.at(-1)[C.phase], `reading() of the last day: ${R?.phase} ${R?.score}/10`);
}

// 4. live page replay
section("replay: live fear (page and skill)");
{
  const G = createRequire(import.meta.url)(P("regime.js")), R = MH.rows; let hit = 0, n = 0; const miss = [];
  for (let i = R.length - 60; i < R.length; i++) { n++;
    const L = G.liveFear({ columns: MH.columns, rows: R.slice(0, i) }, { date: R[i][C.date], vix: R[i][C.vix], vix3m: R[i][C.vix3m], spx: R[i][C.spx], credit: R[i][C.credit] });
    if (L && L.phase === R[i][C.phase]) hit++; else miss.push(`${R[i][C.date]} ${L?.phase}≠${R[i][C.phase]}`); }
  ok(hit === n, `liveFear(): ${hit}/${n} saved phases reproduced${miss.length ? "; " + miss.slice(0, 3).join(", ") : ""}`);
}

// 5. Minervini block (the code between @tt-begin and @tt-end in index.html)
section("Minervini trend template");
{
  const html = fs.readFileSync(P("index.html"), "utf8"), a = html.indexOf("/* @tt-begin"), b = html.indexOf("/* @tt-end */");
  if (ok(a > 0 && b > a, "markers @tt-begin / @tt-end found")) {
    const ctx = vm.createContext({ Math, Date, Map, JSON, Number, String, Array, Object, isFinite, sum: x => x.reduce((p, q) => p + q, 0), last: x => x[x.length - 1],
      isN: v => typeof v === "number" && isFinite(v), S: null, MF: null });
    vm.runInContext(html.slice(a, b), ctx);
    const series = (f, n = 400) => Array.from({ length: n }, (_, i) => { const c = f(i); return { t: Date.UTC(2025, 0, 1) + i * 864e5, c, h: c * 1.01, l: c * 0.99, v: 1e6 }; });
    const mk = d => new Map(d.map(x => [new Date(x.t).toISOString().slice(0, 10), x.c]));
    const T = d => { ctx.S = { kind: "equity", closes: d, price: d.at(-1).c, cur: "USD", mktC: mk(series(i => 100 + i * 0.05)), mktN: "test", benchC: null, benchN: "test", mkt: null, fear: null };
      return vm.runInContext("trendTemplate()", ctx); };
    let up = null, down = null, e = null;
    try { up = T(series(i => 50 * Math.exp(i * 0.003) * (1 + 0.01 * Math.sin(i)))); down = T(series(i => 200 * Math.exp(-i * 0.002) * (1 + 0.01 * Math.sin(i)))); } catch (x) { e = x.message; }
    ok(!e && up && down, `trendTemplate() runs on synthetic data${e ? ": " + e : ""}`);
    if (up && down) ok(up.passed > down.passed && !down.met, `rising stock passes more blocks (${up.passed}/${up.total}) than a falling one (${down.passed}/${down.total}), which does not meet it`);
    let short; try { short = T(series(i => 50 + i, 199)); } catch (x) { short = "error " + x.message; }
    ok(short === null, `fewer than 200 days of prices: no reading (${short === null ? "null" : JSON.stringify(short).slice(0, 60)})`);
  }
}

// 6. network helper (local server only): a stalled answer times out, dead routes are dropped
section("network helper (scripts/lib/net.mjs)");
{
  const http = await import("node:http"), { fetchText, Routes } = await import(P("scripts/lib/net.mjs"));
  const srv = http.createServer((q, r) => { r.writeHead(200, { "content-type": "application/json" }); r.write("{"); }).listen(0);   // headers, then nothing
  await new Promise(r => srv.once("listening", r));
  const t0 = Date.now(); let e = null;
  try { await fetchText(`http://127.0.0.1:${srv.address().port}/`, { timeout: 1500 }); } catch (x) { e = x; }
  const s = (Date.now() - t0) / 1000;
  ok(e && s < 4, `a server that sends headers then stalls is cut at the timeout (${s.toFixed(1)} s)`);
  const R = new Routes(["a", "b"], { maxStrikes: 2, timeout: 500 }); let calls = 0;
  for (let i = 0; i < 5; i++) await R.get("u", () => undefined, { wrap: () => { calls++; return "http://127.0.0.1:1/"; } });
  ok(calls === 4, `two dead routes are dropped after 2 failures each (${calls} calls for 5 requests)`);
  srv.close(); srv.closeAllConnections?.();
}

// 7. copies of shared rules
section("copies of shared rules");
{
  const i = process.argv.indexOf("--skill"), skill = i > 0 ? path.resolve(process.argv[i + 1]) : null;
  const pr = checkCopies({ skill, log: l => console.log(l) });
  pr.forEach(p => fails.push(p));
}

console.log(`\n${fails.length ? `${fails.length} FAILED:\n  - ` + fails.join("\n  - ") : "ALL PASSED"}`);
process.exit(fails.length ? 1 : 0);
