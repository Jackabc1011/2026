(() => {
  "use strict";

  const DATA_URL = "data/latest.json";
  const REFRESH_MS = 5 * 60 * 1000;
  const DIM_LABELS = { social: "社交 KOL", smart_money: "聪明钱", momentum: "价格动量", attention: "榜单热度" };
  const SOURCE_LABELS = {
    x: "X / KOL", wallets: "聪明钱钱包", binance: "币安", coingecko: "CoinGecko",
    dexscreener: "DexScreener", dex_resolve: "合约解析", fear_greed: "恐慌贪婪指数",
  };

  const state = { data: null, rating: "", query: "", hideRisky: false, kolTag: "", open: new Set() };
  const $ = (id) => document.getElementById(id);

  // ------------------------------------------------------------ helpers
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  function safeUrl(u) {
    try {
      const url = new URL(u);
      return url.protocol === "https:" || url.protocol === "http:" ? url.href : "#";
    } catch { return "#"; }
  }

  function fmtPrice(p) {
    if (p == null) return "—";
    if (p >= 1000) return "$" + p.toLocaleString("en-US", { maximumFractionDigits: 0 });
    if (p >= 1) return "$" + p.toFixed(2);
    if (p >= 0.01) return "$" + p.toFixed(4);
    return "$" + p.toPrecision(3);
  }

  function fmtUsd(v) {
    if (v == null) return "—";
    if (v >= 1e9) return "$" + (v / 1e9).toFixed(2) + "B";
    if (v >= 1e6) return "$" + (v / 1e6).toFixed(2) + "M";
    if (v >= 1e3) return "$" + (v / 1e3).toFixed(1) + "K";
    return "$" + v.toFixed(0);
  }

  function fmtPct(v) {
    if (v == null) return '<span class="muted">—</span>';
    const cls = v > 0 ? "up" : v < 0 ? "down" : "";
    const sign = v > 0 ? "+" : v < 0 ? "−" : "";
    return `<span class="${cls}">${sign}${Math.abs(v).toFixed(1)}%</span>`;
  }

  function ago(iso) {
    if (!iso) return "";
    const s = (Date.now() - new Date(iso).getTime()) / 1000;
    if (s < 60) return "刚刚";
    if (s < 3600) return Math.floor(s / 60) + " 分钟前";
    if (s < 86400) return Math.floor(s / 3600) + " 小时前";
    return Math.floor(s / 86400) + " 天前";
  }

  // Minimal, safe markdown: escape first, then **bold**, "- " lists, paragraphs.
  function miniMarkdown(md) {
    const lines = esc(md).split(/\n/);
    let html = "", inList = false;
    for (const raw of lines) {
      const line = raw.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/^#{1,6}\s*/, "");
      if (/^\s*[-*]\s+/.test(raw)) {
        if (!inList) { html += "<ul>"; inList = true; }
        html += "<li>" + line.replace(/^\s*[-*]\s+/, "") + "</li>";
      } else {
        if (inList) { html += "</ul>"; inList = false; }
        if (line.trim()) html += "<p>" + line + "</p>";
      }
    }
    return html + (inList ? "</ul>" : "");
  }

  // ------------------------------------------------------------ renderers
  function renderHeader(d) {
    $("updated").textContent = `更新于 ${ago(d.generated_at)} · 回看 ${d.lookback_hours}h`;
    $("updated").title = new Date(d.generated_at).toLocaleString();
    $("demo-banner").hidden = !d.demo;

    $("majors").innerHTML = (d.market.majors || []).map((m) => `
      <div class="tile"><div class="k">${esc(m.symbol)}</div>
      <div class="v">${fmtPrice(m.price)}</div><div class="d">${fmtPct(m.change_24h)} 24h</div></div>`).join("");

    const f = d.market.fear_greed;
    $("fng").innerHTML = f ? `
      <div class="k">恐慌贪婪指数</div>
      <div class="v">${f.value} <small>${esc(f.label)}</small></div>
      <div class="fng-bar"><i style="width:${Math.max(0, Math.min(100, f.value))}%"></i></div>` : '<div class="k">恐慌贪婪指数</div><div class="v">—</div>';

    $("sources").innerHTML = Object.entries(d.sources || {}).map(([k, v]) => {
      const cls = v.ok ? "" : v.skipped ? "skip" : "bad";
      const mark = v.ok ? "✓" : v.skipped ? "–" : "✕";
      const title = v.ok ? `${v.count} 条` : (v.error || "");
      return `<span class="src ${cls}" title="${esc(title)}">${mark} ${esc(SOURCE_LABELS[k] || k)}</span>`;
    }).join("");

    const b = d.brief;
    $("brief-card").hidden = !b;
    if (b) {
      $("brief").innerHTML = miniMarkdown(b.text);
      $("brief-model").textContent = b.model === "demo" ? "示例" : `由 ${b.model} 生成`;
    }
  }

  function dimsHtml(c) {
    return `<div class="dims">${Object.keys(DIM_LABELS).map((k) => `
      <span class="dim" data-tip="${DIM_LABELS[k]}：${c[k].toFixed(0)}">
        <i class="d-${k}" style="height:${Math.max(2, c[k] * 0.26)}px"></i></span>`).join("")}</div>`;
  }

  function filteredOpps() {
    const q = state.query.trim().toUpperCase();
    return (state.data.opportunities || []).filter((o) => {
      if (q && !o.symbol.includes(q) && !(o.name || "").toUpperCase().includes(q)) return false;
      if (state.rating === "重点关注" && o.rating !== "重点关注") return false;
      if (state.rating === "观察" && o.rating === "噪音") return false;
      if (state.hideRisky && o.risks.length >= 2) return false;
      return true;
    });
  }

  function detailHtml(o) {
    const m = o.market || {};
    const links = [];
    if (m.url) links.push(`<a href="${safeUrl(m.url)}" target="_blank" rel="noopener">行情 ↗</a>`);
    links.push(`<a href="https://x.com/search?q=%24${encodeURIComponent(o.symbol)}&f=live" target="_blank" rel="noopener">X 实时讨论 ↗</a>`);
    if (m.address && m.chain && m.chain !== "binance") {
      links.push(`<a href="https://dexscreener.com/${encodeURIComponent(m.chain)}/${encodeURIComponent(m.address)}" target="_blank" rel="noopener">DexScreener ↗</a>`);
    }
    const created = m.pair_created_at ? new Date(m.pair_created_at).toLocaleDateString() : "—";
    return `<div class="detail-grid">
      <div>
        <h3>四维得分</h3>
        <div class="kv">${Object.entries(DIM_LABELS).map(([k, l]) => `<span>${l}</span><span>${o.components[k].toFixed(1)}</span>`).join("")}
          <span>共振维度</span><span>${o.confluence} / 4</span></div>
        <h3>行情</h3>
        <div class="kv">
          <span>链</span><span>${esc(m.chain || "—")}</span>
          <span>24h 成交</span><span>${fmtUsd(m.volume_24h)}</span>
          <span>流动性</span><span>${fmtUsd(m.liquidity)}</span>
          <span>FDV</span><span>${fmtUsd(m.fdv)}</span>
          <span>上线</span><span>${created}</span>
          ${m.address ? `<span>合约</span><span><code>${esc(m.address.slice(0, 6))}…${esc(m.address.slice(-4))}</code></span>` : ""}
        </div>
        <div class="links">${links.join("")}</div>
      </div>
      <div>
        <h3>信号</h3><ul>${o.signals.map((s) => `<li>${esc(s)}</li>`).join("") || "<li>—</li>"}</ul>
        <h3>风险</h3><ul>${o.risks.map((s) => `<li>⚠ ${esc(s)}</li>`).join("") || "<li>未发现明显风险标记</li>"}</ul>
        ${o.buys.length ? `<h3>聪明钱买入</h3><ul>${o.buys.map((b) => `
          <li><a href="${safeUrl(b.tx_url)}" target="_blank" rel="noopener">${esc(b.label)}</a> · ${ago(b.time)}</li>`).join("")}</ul>` : ""}
      </div>
      <div>
        <h3>KOL 原文</h3>
        ${o.mentions.map((t) => `<div class="quote"><div class="who">${esc(t.name)} · ${ago(t.created_at)}
          · <a href="${safeUrl(t.url)}" target="_blank" rel="noopener">原文</a></div>${esc(t.text.slice(0, 280))}</div>`).join("") || '<p class="empty">无</p>'}
      </div>
    </div>`;
  }

  function renderOpps() {
    const rows = filteredOpps();
    $("opps-empty").hidden = rows.length > 0;
    $("opps").querySelector("tbody").innerHTML = rows.map((o, i) => {
      const m = o.market || {};
      const open = state.open.has(o.symbol);
      const chain = m.chain && m.chain !== "binance" ? `<span class="chain">${esc(m.chain)}</span>` : "";
      const riskN = o.risks.length ? `<span class="risk-n" title="${esc(o.risks.join("；"))}">⚠${o.risks.length}</span>` : "";
      const row = `<tr class="row${open ? " open" : ""}" data-sym="${esc(o.symbol)}" tabindex="0" aria-expanded="${open}">
        <td class="num hide-sm">${i + 1}</td>
        <td><span class="sym">${esc(o.symbol)}</span>${chain}<span class="sym-name">${esc(o.name)}</span></td>
        <td><div class="score"><b>${o.score.toFixed(0)}</b><span class="bar"><i style="width:${o.score}%"></i></span></div></td>
        <td>${dimsHtml(o.components)}</td>
        <td class="num hide-sm">${fmtPrice(m.price)}</td>
        <td class="num hide-sm">${fmtPct(m.change_1h)}</td>
        <td class="num">${fmtPct(m.change_24h)}</td>
        <td class="num hide-sm">${fmtUsd(m.liquidity)}</td>
        <td class="hide-md"><div class="chips">${o.signals.slice(0, 3).map((s) => `<span class="chip">${esc(s)}</span>`).join("")}</div></td>
        <td><span class="badge r-${esc(o.rating)}">${esc(o.rating)}</span>${riskN}</td>
      </tr>`;
      return row + (open ? `<tr class="detail"><td colspan="10">${detailHtml(o)}</td></tr>` : "");
    }).join("");
  }

  function renderFeed() {
    const d = state.data;
    const tags = [...new Set((d.kol_feed || []).map((t) => t.tag).filter(Boolean))];
    $("kol-tags").innerHTML = ["", ...tags].map((t) =>
      `<button type="button" data-tag="${esc(t)}" class="${state.kolTag === t ? "on" : ""}">${esc(t || "全部")}</button>`).join("");
    const feed = (d.kol_feed || []).filter((t) => !state.kolTag || t.tag === state.kolTag);
    const src = d.sources?.x;
    $("feed").innerHTML = feed.map((t) => `<li>
      <div class="who"><span><b>${esc(t.name)}</b> @${esc(t.handle)}</span>
        <a href="${safeUrl(t.url)}" target="_blank" rel="noopener">${ago(t.created_at)}</a></div>
      <div class="text">${esc(t.text)}</div>
      <div class="tags">${t.symbols.map((s) => `<span class="tok">$${esc(s)}</span>`).join("")}</div>
    </li>`).join("") || `<li class="empty">${src && !src.ok ? esc(src.error) : "暂无推文"}</li>`;

    const w = d.smart_money || [];
    const ws = d.sources?.wallets;
    $("wallets").innerHTML = w.map((b) => `<li>
      <div class="who"><span><b>${esc(b.label)}</b> · ${esc(b.chain)}</span>
        <a href="${safeUrl(b.tx_url)}" target="_blank" rel="noopener">${ago(b.time)}</a></div>
      <div class="text">买入 <span class="tok">${esc(b.symbol || "未知代币")}</span>
        ${b.amount != null ? Number(b.amount).toLocaleString("en-US", { maximumFractionDigits: 2 }) : ""}</div>
    </li>`).join("") || `<li class="empty">${ws && !ws.ok ? esc(ws.error) : "暂无买入记录"}</li>`;
  }

  function renderTrending() {
    const t = state.data.trending || {};
    const item = (x, right) => `<li><div class="row2"><span><b>${esc(x.symbol)}</b>
      <span class="sym-name" style="display:inline">${esc(x.name && x.name !== x.symbol ? x.name : "")}</span></span>
      <span>${right}</span></div></li>`;
    $("t-cg").innerHTML = (t.coingecko || []).map((x) => item(x, fmtPct(x.change_24h))).join("") || '<li class="empty">无数据</li>';
    $("t-dex").innerHTML = (t.dex_boosts || []).map((x) => item(x, `${fmtPct(x.change_24h)} · ${fmtUsd(x.liquidity)}`)).join("") || '<li class="empty">无数据</li>';
    $("t-bn").innerHTML = (t.binance_gainers || []).map((x) => item(x, fmtPct(x.change_24h))).join("") || '<li class="empty">无数据</li>';
  }

  function render() {
    if (!state.data) return;
    renderHeader(state.data);
    renderOpps();
    renderFeed();
    renderTrending();
  }

  async function load() {
    try {
      const r = await fetch(`${DATA_URL}?t=${Date.now()}`, { cache: "no-store" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      state.data = await r.json();
      render();
    } catch (e) {
      $("updated").textContent = `数据加载失败：${e.message}（先运行 python -m collector）`;
    }
  }

  // ------------------------------------------------------------ events
  $("q").addEventListener("input", (e) => { state.query = e.target.value; renderOpps(); });
  $("hide-risky").addEventListener("change", (e) => { state.hideRisky = e.target.checked; renderOpps(); });
  document.querySelector(".seg[aria-label='评级']").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    state.rating = b.dataset.rating;
    b.parentElement.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
    renderOpps();
  });
  $("kol-tags").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    state.kolTag = b.dataset.tag; renderFeed();
  });
  const toggleRow = (tr) => {
    const s = tr.dataset.sym;
    state.open.has(s) ? state.open.delete(s) : state.open.add(s);
    renderOpps();
  };
  $("opps").addEventListener("click", (e) => {
    if (e.target.closest("a")) return;
    const tr = e.target.closest("tr.row"); if (tr) toggleRow(tr);
  });
  $("opps").addEventListener("keydown", (e) => {
    const tr = e.target.closest("tr.row");
    if (tr && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); toggleRow(tr); }
  });
  $("refresh").addEventListener("click", load);

  // Tooltip for the four-dimension bars
  const tip = $("tip");
  document.addEventListener("mouseover", (e) => {
    const el = e.target.closest("[data-tip]");
    if (!el) { tip.hidden = true; return; }
    tip.textContent = el.dataset.tip; tip.hidden = false;
    const r = el.getBoundingClientRect();
    tip.style.left = Math.min(window.innerWidth - tip.offsetWidth - 8, r.left) + "px";
    tip.style.top = (r.top - tip.offsetHeight - 6) + "px";
  });

  // Theme toggle (persisted per browser)
  const root = document.documentElement;
  try { const t = localStorage.getItem("theme"); if (t) root.dataset.theme = t; } catch {}
  $("theme").addEventListener("click", () => {
    const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("theme", root.dataset.theme); } catch {}
  });

  load();
  setInterval(load, REFRESH_MS);
  setInterval(() => state.data && renderHeader(state.data), 60 * 1000);
})();
