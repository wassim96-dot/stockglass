// Phase-change alerts (run by the daily workflows): compares today's phase with the last alerted one, kept in
// data/alert-state.json, and writes alert-title.txt / alert-body.md when it changed (the workflow then opens a GitHub
// issue, which the GitHub app pushes to the owner's phone). Usage: node scripts/phase-alert.mjs fear|crypto
import fs from "node:fs";
import path from "node:path";
const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const kind = process.argv[2];
const read = f => { try { return JSON.parse(fs.readFileSync(path.join(ROOT, f), "utf8")); } catch { return null; } };
const state = read("data/alert-state.json") || {};
const out = [];   // [title, body]
const SITE = "https://wassim96-dot.github.io/stockglass/";
if (kind === "fear") {
  const m = read("data/market.json");
  if (m && m.phase) {
    const prev = state.fear?.phase;
    if (prev && prev !== m.phase) {
      const fc = m.fading_checks;
      out.push([`Fear alert: ${m.phase_label} (was ${state.fear.label})`,
        [`**Market fear phase changed: ${state.fear.label} → ${m.phase_label}** (data of ${m.date})`, "",
         `- Fear score **${m.score}/10, ${m.label}** (premium ${m.premium_score}/10, phase ${m.phase_score}/10)`,
         `- VIX ${m.vix} · VIX/VIX3M ${m.vix_vix3m ?? "∅"}${m.stress_days ? ` · day ${m.stress_days} of stress` : ""}`,
         fc ? `- Fading checks: credit ${fc.credit_easing === false ? "still widening" : fc.credit_easing ? "easing" : "n/a"}, new 20-day low ${fc.new_low_5d ? "yes" : "no"}, bear market ${fc.bear_state ? "yes" : "no"}` : null,
         m.risk_flag ? "- ⚠️ High-risk entry (early fear)" : null, "", m.note, "",
         m.phase === "fading" ? "This is the phase that historically preceded the best 3-month market returns (2007–2026). It applies to the market; each stock's own trend and timing still matter." : null,
         `StockGlass: ${SITE} · Rule-based screen on public data, not investment advice.`, "", "@wassim96-dot"].filter(x => x != null).join("\n")]);
    }
    state.fear = { phase: m.phase, label: m.phase_label, date: m.date };
  }
}
if (kind === "crypto") {
  const c = read("data/crypto.json");
  state.crypto = state.crypto || {};
  for (const [a, nm] of [["btc", "Bitcoin"], ["eth", "Ethereum"]]) {
    const r = c?.assets?.[a];
    if (!r || !r.phase) continue;
    const lab = c.phases[r.phase].label, prev = state.crypto[a];
    if (prev && prev.phase !== r.phase) {
      out.push([`Crypto alert: ${nm} ${lab} (was ${prev.label})`,
        [`**${nm} cycle phase changed: ${prev.label} → ${lab}** (data of ${r.date})`, "",
         r.mvrv != null ? `- MVRV ${r.mvrv} · holders' average cost ${Math.round(r.realized_price).toLocaleString("en-US")} USD · price ${Math.round(r.price).toLocaleString("en-US")} USD · 200-day average ${Math.round(r.ma200).toLocaleString("en-US")} USD` : null,
         "", c.phases[r.phase].note, "",
         r.phase === "accumulation" ? "Accumulation has historically been the best one-year entry zone, but it can last months and the trend is usually still down: the trend-confirmation signal is \"Long setups favoured\" on the StockGlass page." : null,
         `StockGlass: ${SITE} · Rule-based screen on public data, not investment advice.`, "", "@wassim96-dot"].filter(x => x != null).join("\n")]);
    }
    state.crypto[a] = { phase: r.phase, label: lab, date: r.date };
  }
}
if (process.env.TEST_ALERT === "true" && !out.length) {   // manual test from the Actions tab: sends one alert with today's reading
  const m = read("data/market.json"), c = read("data/crypto.json");
  out.push([`Test alert: StockGlass phase alerts are working`, [`This is a test. You will get an issue like this whenever the market fear phase or the Bitcoin/Ethereum cycle phase changes.`, "",
    m ? `- Market fear now: ${m.phase_label}, ${m.score}/10 ${m.label} (VIX ${m.vix}, ${m.date})` : null,
    c?.assets?.btc ? `- Bitcoin: ${c.phases[c.assets.btc.phase].label} (MVRV ${c.assets.btc.mvrv})` : null,
    c?.assets?.eth ? `- Ethereum: ${c.phases[c.assets.eth.phase].label} (MVRV ${c.assets.eth.mvrv})` : null, "",
    `You can close this issue.`, "", "@wassim96-dot"].filter(x => x != null).join("\n")]);
}
fs.writeFileSync(path.join(ROOT, "data/alert-state.json"), JSON.stringify(state, null, 1));
fs.rmSync(path.join(ROOT, "alerts"), { recursive: true, force: true });
if (out.length) {
  fs.mkdirSync(path.join(ROOT, "alerts"));
  out.forEach(([t, b], i) => { fs.writeFileSync(path.join(ROOT, `alerts/${i}.title`), t); fs.writeFileSync(path.join(ROOT, `alerts/${i}.md`), b); });
}
console.log(out.length ? `${out.length} alert(s): ${out.map(x => x[0]).join(" | ")}` : `no phase change (${kind})`);
