/* 原聲雷達 OST Radar */
(() => {
  "use strict";

  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmtN = (n) => (n == null ? "—" : Number(n).toLocaleString("zh-TW"));
  // 外部資料的網址只允許 http(s)，擋掉 javascript: / data: 等
  const safeUrl = (u) => { try { const x = new URL(u, location.href); return /^https?:$/.test(x.protocol) ? x.href : "#"; } catch { return "#"; } };
  const ext = 'target="_blank" rel="noopener noreferrer"';
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

  const FMT = { vinyl: "黑膠", "7inch": "7 吋", cd: "CD", cassette: "卡帶" };
  const FMT_LONG = { vinyl: "黑膠 LP", "7inch": "7 吋黑膠", cd: "CD", cassette: "卡帶" };
  const KIND = { anime: "動畫", game: "遊戲", movie: "電影", other: "其他" };
  const SUB = { ost: "原聲帶", song: "歌曲・主題曲", arrange: "改編・演奏" };
  const ST_CLS = { 預購: "pre", 現貨: "stock", 可訂購: "ord", 缺貨: "out", 待確認: "unk" };
  const STATUSES = ["預購", "現貨", "可訂購", "待確認", "缺貨"];
  // 狀態的白話說明：卡片提示、狀態說明、詳細頁共用
  const STATUS_HELP = {
    預購: "還沒發售，可以先下訂，發售後出貨。",
    現貨: "店家有庫存，下單後就會寄出。",
    可訂購: "可以下單，但店家要向海外或廠商調貨，需要等待到貨。",
    待確認: "暫時無法確認庫存，請到通路頁面確認。",
    缺貨: "目前售完或無法購買。",
  };
  const TAGS = ["限定盤", "彩膠", "日版", "台灣版", "BOX", "附特典", "180g", "代購", "二手"];
  const MARKET = new Set(["ruten", "yahoo", "myacg"]); // 載入後依 meta 的通路類型更新
  // 以使用者當地日期為準（toISOString 是 UTC，台灣清晨會變成前一天）
  const TODAY = new Date(Date.now() - new Date().getTimezoneOffset() * 6e4).toISOString().slice(0, 10);

  let ITEMS = [], NEWS = [], META = {}, SRC = {};
  const BY_ID = new Map();

  // 本機儲存（收藏、瀏覽紀錄、顯示方式）：私密模式或被封鎖時安靜失敗，網站照常可用
  const store = {
    get(k, d) { try { const v = JSON.parse(localStorage.getItem(k)); return v ?? d; } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* 無法儲存 */ } },
  };
  const HEART = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20.3s-7.6-4.6-7.6-10.2A4.3 4.3 0 0 1 12 7.4a4.3 4.3 0 0 1 7.6 2.7c0 5.6-7.6 10.2-7.6 10.2z"/></svg>`;
  const GROUPS = new Map();          // 比價群組 g → 同一商品在各通路的報價
  const BUYABLE = new Set(["現貨", "預購", "可訂購", "待確認"]);
  const STALE_DAYS = 5;
  // 資料確認日距今天數（ck = 通路狀態最後確認日；舊資料沒有 ck 時以資料產生日為準）
  const ageDays = (it) => {
    const d = it.ck || (META.generated || "").slice(0, 10);
    return d ? Math.max(0, Math.round((Date.parse(TODAY) - Date.parse(d)) / 864e5)) : 0;
  };

  /* ------------------------------------------------------------ data */
  async function load() {
    const get = (u) => fetch(u, { cache: "no-cache" }).then((r) => (r.ok ? r.json() : null)).catch(() => null);
    const [items, news, meta, thumbs] = await Promise.all([
      get("data/items.json"), get("data/news.json"), get("data/meta.json"), get("img/map.json")]);
    ITEMS = items || []; NEWS = news || []; META = meta || {};
    (META.sources || []).forEach((s) => { SRC[s.key] = s; if (s.type === "拍賣") MARKET.add(s.key); });
    const map = thumbs || {};
    ITEMS.forEach((it, i) => {
      it._i = i; it._q = `${it.t} ${it.fr || ""} ${it.sl || ""} ${FMT[it.f] || ""} ${it.bc || ""}`.toLowerCase();
      BY_ID.set(it.id, it);
      const m = map[it.id];
      if (m === 0) it.i = "";                              // 通路的「無圖片」佔位圖
      else if (m) { it.th = `img/${m[0]}.webp`; it.c = m[1]; } // 同網域 WebP 縮圖 + 主色
      if (it.g) { if (!GROUPS.has(it.g)) GROUPS.set(it.g, []); GROUPS.get(it.g).push(it); }
    });
  }
  // 組內可購買的最低價（拍賣誘餌價已在資料端排除，這裡再過濾低於 250 元的報價）
  function offerInfo(it) {
    const all = (it.g && GROUPS.get(it.g)) || [it];
    const ok = all.filter((o) => BUYABLE.has(o.st) && (o.p || 0) >= 250 && ageDays(o) <= 3);
    const low = ok.length ? Math.min(...ok.map((o) => o.p)) : null;
    return { all, ok, low, stores: new Set(all.map((o) => o.s)).size };
  }
  const shortDate = (d) => { const [, m, dd] = (d || "").split("-"); return m ? `${+m}/${+dd}` : ""; };
  // 販售狀況：剩餘庫存、已售出、預購截止
  function salesBits(it) {
    const out = [];
    if (it.dl && it.dl >= TODAY) {
      const left = Math.round((Date.parse(it.dl) - Date.parse(TODAY)) / 864e5);
      out.push(left <= 7 ? (left ? `剩 ${left} 天截止預購` : "今天截止預購") : `預購至 ${shortDate(it.dl)}`);
    }
    if (it.q != null && it.st !== "缺貨" && it.q > 0) out.push(it.q <= 10 ? `剩 ${it.q} 件` : `庫存 ${it.q}`);
    if (it.so) out.push(`已售 ${fmtN(it.so)}`);
    return out;
  }
  const srcName = (k) => SRC[k]?.name || k;

  /* ------------------------------------------------------------ pieces */
  function img(src, alt, cls = "", { eager = false, fallback = "" } = {}) {
    if (!src || safeUrl(src) === "#") return "";
    const fb = fallback && safeUrl(fallback) !== "#" ? ` data-fb="${esc(safeUrl(fallback))}"` : "";
    return `<img class="${esc(cls)}" src="${esc(safeUrl(src))}" alt="${esc(alt)}" width="360" height="360" decoding="async" ` +
      `${eager ? 'loading="eager" fetchpriority="high"' : 'loading="lazy"'} referrerpolicy="no-referrer"${fb}>`;
  }
  // 封面：先用主色鋪底 → 同網域縮圖（失敗時退回通路原圖）
  function cover(it, { eager = false, hi = false, phLen = 28 } = {}) {
    const src = it.th || it.i;
    return `<div class="cover"${it.c ? ` data-c="${esc(it.c)}"` : ""}><div class="ph" aria-hidden="true">${esc(it.t.slice(0, phLen))}</div>` +
      img(src, "", "", { eager, fallback: it.th ? it.i : "" }) +
      (hi && it.th && it.i ? img(it.i, it.t, "hi", { eager: true }) : "") + `</div>`;
  }
  function priceHtml(p) {
    return p ? `<span class="price"><small>NT$</small>${fmtN(p)}</span>` : `<span class="price">—</span>`;
  }
  function relLabel(it) {
    if (!it.r) return "";
    const [y, m, d] = it.r.split("-");
    if (!d) return `${+m} 月出貨`;
    return it.r > TODAY ? `${+m}/${+d} 發售` : `${y}.${m}`;
  }
  const relLong = (r) => { const [y, m, d] = r.split("-"); return d ? `${y}.${m}.${d}` : `${y} 年 ${+m} 月（預計）`; };
  const stLabel = (it) => it.st;
  function card(it, { tag = "button" } = {}) {
    const st = ST_CLS[it.st] || "unk";
    const flags = (it.fl || []).slice(0, 1).map((f) => `<span class="pill flag">${esc(f.replace(/ .*/, ""))}</span>`).join("");
    // 卡片只留最關鍵的一行補充：發售日／剩餘數量／資料過舊，其餘資訊放在詳細頁
    const sub = [];
    if (it.r && it.st === "預購") sub.push(`<span class="rel">${esc(relLabel(it))}</span>`);
    const sales = salesBits(it);
    if (sales.length) sub.push(`<span class="${/剩/.test(sales[0]) ? "warn" : "v"}">${esc(sales[0])}</span>`);
    const age = ageDays(it);
    if (age >= 2) sub.push(`<span class="${age >= STALE_DAYS ? "warn" : ""}">${age} 天前資料</span>`);
    const oi = offerInfo(it);
    const cmp = oi.stores > 1
      ? `<div class="card-cmp"><span>${oi.stores} 家有賣</span>${oi.low ? `<b>最低 $${fmtN(oi.low)}</b>` : ""}</div>` : "";
    const bestPill = it.best && oi.stores > 1 ? `<span class="pill best">最低價</span>` : "";
    return `<div class="cell"><${tag} class="card${it.st === "缺貨" ? " is-out" : ""}" data-f="${esc(it.f)}" data-i="${it._i}" type="button" aria-label="${esc(it.t)}，${esc(it.st)}，${esc(srcName(it.s))}${it.p ? "，" + fmtN(it.p) + " 元" : ""}">
      <div class="sleeve"><span class="disc" aria-hidden="true"></span>
        ${cover(it)}
        <div class="pill-row"><span class="pill ${st}" title="${esc(STATUS_HELP[it.st] || "")}">${esc(stLabel(it))}</span>${bestPill || flags}</div>
        <span class="fmt-tag">${esc(FMT[it.f] || it.f)}${Number(it.d) > 1 ? " ×" + esc(it.d) : ""}</span>
      </div>
      <div class="card-t">${esc(it.t)}</div>
      <div class="card-meta">${priceHtml(it.p)}<span class="src">${esc(srcName(it.s))}</span></div>
      ${sub.length ? `<div class="card-sub">${sub.join("")}</div>` : ""}
      ${cmp}
    </${tag}>${favBtn(it)}</div>`;
  }
  // 收藏按鈕放在卡片旁（不放進卡片按鈕裡，避免巢狀互動元素）
  function favBtn(it, cls = "fav") {
    const on = isFav(it.id);
    return `<button type="button" class="${cls}" data-fav="${esc(it.id)}" aria-pressed="${on}" aria-label="${on ? "取消收藏" : "加入收藏"}：${esc(it.t)}" title="${on ? "取消收藏" : "加入收藏"}">${HEART}${cls === "fav" ? "" : `<span>${on ? "已收藏" : "收藏"}</span>`}</button>`;
  }

  /* ------------------------------------------------------------ 收藏與瀏覽紀錄（存在本機） */
  // 收藏時記下當時的狀態與價格，之後比對就能提醒「補貨」「降價」「售完」
  let FAV = store.get("ost-fav", {});
  if (!FAV || typeof FAV !== "object" || Array.isArray(FAV)) FAV = {};
  const isFav = (id) => Object.hasOwn(FAV, id);
  const snap = (it) => ({ t: it.t, p: it.p ?? null, st: it.st, s: it.s, u: it.u, img: it.th || it.i || "", at: TODAY, vs: it.st, vp: it.p ?? null });
  function toggleFav(id) {
    const it = BY_ID.get(id);
    if (isFav(id)) delete FAV[id];
    else if (it) FAV[id] = snap(it);
    else return;
    store.set("ost-fav", FAV);
    $$(`[data-fav="${CSS.escape(id)}"]`).forEach((b) => {
      const on = isFav(id);
      b.setAttribute("aria-pressed", on);
      b.title = on ? "取消收藏" : "加入收藏";
      b.setAttribute("aria-label", `${on ? "取消收藏" : "加入收藏"}：${it?.t || ""}`);
      const label = b.querySelector("span"); if (label) label.textContent = on ? "已收藏" : "收藏";
    });
    updateFavBadge();
    toast(isFav(id) ? "已加入收藏，補貨或降價時會在 ♡ 提醒" : "已取消收藏");
  }
  const LIVE = new Set(["現貨", "預購", "可訂購"]);
  // 與某個時間點的狀態比較，回傳值得提醒的變化
  function favChange(st0, p0, it) {
    if (!it) return { txt: "已不在資料中（可能下架）", cls: "mute" };
    if (st0 === "預購" && it.st === "現貨") return { txt: "已到貨，有現貨", cls: "ok" };
    if (!LIVE.has(st0) && LIVE.has(it.st)) return { txt: `補貨了，現在${it.st}`, cls: "ok" };
    if (LIVE.has(st0) && it.st === "缺貨") return { txt: "已售完", cls: "mute" };
    if (p0 && it.p && it.p < p0) return { txt: `降價 $${fmtN(p0)} → $${fmtN(it.p)}`, cls: "ok" };
    if (p0 && it.p && it.p > p0) return { txt: `漲價 $${fmtN(p0)} → $${fmtN(it.p)}`, cls: "warn" };
    return null;
  }
  function updateFavBadge() {
    const ids = Object.keys(FAV), b = $("#favCount");
    const news = ids.some((id) => { const f = FAV[id], it = BY_ID.get(id); return it ? favChange(f.vs, f.vp, it) : !f.ack; });
    b.hidden = !ids.length; b.textContent = ids.length;
    b.classList.toggle("news", news);
    $("#favBtn").setAttribute("aria-label", `我的收藏與瀏覽紀錄${ids.length ? `（${ids.length} 筆${news ? "，有新變化" : ""}）` : ""}`);
  }
  let RECENT = store.get("ost-recent", []);
  if (!Array.isArray(RECENT)) RECENT = [];
  function pushRecent(id) {
    RECENT = [id, ...RECENT.filter((x) => x !== id)].slice(0, 24);
    store.set("ost-recent", RECENT);
  }
  function miniRow(it, extra = "") {
    return `<a class="alt-row" href="#" data-i="${it._i}" data-back="col">${it.i ? img(it.th || it.i, "", "ok", { fallback: it.th ? it.i : "" }) : `<span class="ph"></span>`}
      <span><span class="at">${esc(it.t)}</span><span class="as">${esc(srcName(it.s))}</span>${extra}</span>
      <span class="ap">${it.p ? "$" + fmtN(it.p) : "—"}<span class="${ST_CLS[it.st] || ""}">${esc(it.st)}</span></span></a>`;
  }
  function openCollection({ push = true } = {}) {
    if ($("#sheet").hidden) lastFocus = document.activeElement;
    const favs = Object.entries(FAV).sort((a, b) => (b[1].at || "").localeCompare(a[1].at || ""));
    const favHtml = favs.map(([id, f]) => {
      const it = BY_ID.get(id);
      const c = favChange(f.st, f.p, it);
      const chg = c ? `<span class="chg ${c.cls}">${esc(c.txt)}</span>` : "";
      const since = `<span class="as">收藏於 ${esc(shortDate(f.at))}</span>`;
      const row = it ? miniRow(it, chg || since)
        : `<a class="alt-row" href="${esc(safeUrl(f.u))}" ${ext}><span class="ph"></span><span><span class="at">${esc(f.t)}</span><span class="as">${esc(srcName(f.s))}</span>${chg}</span><span class="ap">↗</span></a>`;
      return `<li class="col-row">${row}<button type="button" class="col-rm" data-fav="${esc(id)}" aria-pressed="true" aria-label="取消收藏：${esc(f.t)}" title="取消收藏">✕</button></li>`;
    }).join("");
    const recent = RECENT.map((id) => BY_ID.get(id)).filter(Boolean).slice(0, 12);
    $("#sheetBody").innerHTML = `
      <div class="col-head"><p class="sb-k">本機收藏</p><h2 class="sb-t" id="sheetTitle">我的收藏${favs.length ? `<small>${favs.length} 筆</small>` : ""}</h2>
        <p class="col-note">收藏與瀏覽紀錄只存在這台裝置的瀏覽器，不需要登入。收藏後補貨、降價或售完，會在這裡標示。</p></div>
      ${favs.length ? `<ol class="col-list">${favHtml}</ol>`
        : `<div class="bubble left"><b>還沒有收藏</b>看到喜歡的商品，點封面右上角的 ♡ 就能收藏。</div>`}
      <div class="sb-alt"><h4>最近看過${recent.length ? `<button type="button" class="link-btn" data-clear-recent>清除紀錄</button>` : ""}</h4>
        ${recent.length ? recent.map((it) => miniRow(it)).join("") : `<p>還沒有瀏覽紀錄。</p>`}</div>`;
    // 已看過目前的變化：清掉導覽列的提醒點（列表上的變化標示仍以收藏當時為準）
    favs.forEach(([id, f]) => { const it = BY_ID.get(id); if (it) { f.vs = it.st; f.vp = it.p ?? null; } else f.ack = 1; });
    store.set("ost-fav", FAV); updateFavBadge();
    showSheet({ push, url: (u) => { u.searchParams.delete("item"); u.searchParams.set("view", "fav"); } });
  }
  function showSheet({ push, url }) {
    const u = new URL(location.href); url(u); u.hash = "";
    if ($("#sheet").hidden && push) history.pushState({ sheet: 1 }, "", u);   // 返回鍵可關閉
    else history.replaceState(history.state, "", u);
    $("#sheet").hidden = false; document.body.classList.add("lock");
    $(".sheet-card").scrollTop = 0;
    $(".sheet-close").focus({ preventScroll: true });
  }

  /* ------------------------------------------------------------ hero */
  function countUp(el, to) {
    if (reduce || !to) { el.textContent = fmtN(to); return; }
    const t0 = performance.now(), dur = 1400;
    const step = (t) => {
      const k = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - k, 4);
      el.textContent = fmtN(Math.round(to * e));
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }
  function renderHero() {
    const jp = ITEMS.filter((i) => i.jp);
    const pre = jp.filter((i) => i.st === "預購");
    const month = TODAY.slice(0, 7);
    const n = {
      pre: pre.length,
      stock: jp.filter((i) => i.st === "現貨").length,
      month: pre.filter((i) => !MARKET.has(i.s) && (i.r || "").startsWith(month)).length,
      new: ITEMS.filter((i) => i.jp && i.st !== "缺貨" && (i.fl || []).includes("NEW")).length,
    };
    $$("#stats b[data-k]").forEach((b) => countUp(b, n[b.dataset.k]));
    if (!n.new) $('#stats [data-go="new"]').hidden = true;     // 第一次巡檢還沒有「新上架」基準
    countUp($("#heroCount"), n.pre);
    const shops = (META.sources || []).length;
    if (shops) $("#heroEyebrow").textContent = `${shops} 家唱片行・電商・拍賣，每日更新`;
    // 快速查看：常見需求 + 商品最多的作品，讓第一次來的人有地方可以點
    const freq = {};
    ITEMS.forEach((i) => { if (i.fr && i.jp && i.st !== "缺貨" && !MARKET.has(i.s)) freq[i.fr] = (freq[i.fr] || 0) + 1; });
    const topFr = Object.entries(freq).sort((a, b) => b[1] - a[1]).slice(0, 5).map(([k]) => k);
    $("#quick").innerHTML = `<span class="quick-k">快速查看</span>` +
      (n.month ? `<button type="button" class="hot" data-go="month">本月發售</button>` : "") +
      `<button type="button" data-go="vinyl-stock">有現貨的黑膠</button>` +
      topFr.map((f) => `<button type="button" data-go="fr:${esc(f)}">${esc(f)}</button>`).join("");
    // 首頁封面：最近即將發售的預購（資料檔依 id 排序，這裡自行挑選）
    const pics = pre.filter((i) => i.i && !MARKET.has(i.s) && i.r && i.r >= TODAY)
      .sort((a, b) => a.r.localeCompare(b.r)).slice(0, 3);
    const fill = pics.length < 3 ? jp.filter((i) => i.i && !MARKET.has(i.s) && i.st === "現貨").slice(0, 3 - pics.length) : [];
    $("#heroSleeves").innerHTML = [...pics, ...fill].map((i) =>
      img(i.th || i.i, "", "ok", { eager: true, fallback: i.th ? i.i : "" }).replace("<img ", "<img data-ph ")).join("");
    if (META.generated) $("#updated").textContent = `資料更新 ${META.generated.slice(5).replace("-", "/")}`;
    $("#footMeta").textContent = META.generated ? `更新於 ${META.generated.replace(/-/g, ".")} · ${fmtN(META.total)} 筆 · ${fmtN(META.news)} 則新聞` : "";
  }

  /* ------------------------------------------------------------ ticker */
  function renderTicker() {
    if (!$(".ticker")) return;   // 跑馬燈已移除（持續移動的文字不易閱讀）
    const list = NEWS.filter((n) => n.jp).slice(0, 18);
    if (!list.length) { $(".ticker").hidden = true; return; }
    const html = list.map((n) => `<a href="${esc(safeUrl(n.url))}" ${ext}><time>${esc(n.date.slice(5).replace("-", "."))}</time>${esc(n.title)}</a>`).join("");
    $("#ticker").innerHTML = html + html.replace(/<a /g, '<a tabindex="-1" aria-hidden="true" ');
  }

  /* ------------------------------------------------------------ tabs + rail */
  function tabs(el, defs, onPick) {
    el.innerHTML = defs.map((d, i) => `<button class="tab" role="tab" type="button" aria-selected="${i === 0}" data-k="${esc(d.k)}">${d.label}</button>`).join("");
    el.addEventListener("click", (e) => {
      const b = e.target.closest(".tab"); if (!b) return;
      $$(".tab", el).forEach((t) => t.setAttribute("aria-selected", t === b));
      onPick(b.dataset.k);
    });
    if (defs.length) onPick(defs[0].k);
  }
  function rail(el, list, empty) {
    el.innerHTML = list.length ? list.map((i) => card(i)).join("") : `<p class="rail-empty">${empty}</p>`;
    el.scrollLeft = 0;
  }

  function renderUpcoming() {
    const pre = ITEMS.filter((i) => i.st === "預購" && i.jp && !MARKET.has(i.s));
    const dated = pre.filter((i) => i.r && i.r >= TODAY.slice(0, 8) + "01").sort((a, b) => a.r.localeCompare(b.r));
    const groups = new Map();
    dated.forEach((i) => { const k = i.r.slice(0, 7); if (!groups.has(k)) groups.set(k, []); groups.get(k).push(i); });
    const undated = pre.filter((i) => !i.r);
    const market = ITEMS.filter((i) => i.st === "預購" && i.jp && MARKET.has(i.s));
    const defs = [...groups.entries()].slice(0, 10).map(([k, v]) => {
      const [y, m] = k.split("-");
      const yr = y !== TODAY.slice(0, 4) ? `${esc(y)} ` : "";
      return { k, label: `<b>${yr}${+m} 月</b><small>${v.length} 筆</small>`, list: v };
    });
    if (undated.length) defs.push({ k: "tba", label: `日期未定<small>${undated.length} 筆</small>`, list: undated });
    if (market.length) defs.push({ k: "market", label: `拍賣代購<small>${market.length} 筆</small>`, list: market.slice(0, 60) });
    const map = Object.fromEntries(defs.map((d) => [d.k, d.list]));
    tabs($("#months"), defs, (k) => rail($("#upcomingRail"), map[k] || [], "目前沒有預購"));
    if (!defs.length) rail($("#upcomingRail"), [], "目前沒有預購");
  }

  function renderPulse() {
    const fl = ITEMS.filter((i) => (i.fl || []).length && i.jp && i.st !== "缺貨");  // 已售完的新品不放在動態裡
    if (!fl.length) { $("#pulse").hidden = true; $('.nav-links a[href="#pulse"]').hidden = true; return; }
    const by = (p) => fl.filter((i) => i.fl.some((f) => f.startsWith(p)));
    const defs = [
      { k: "all", name: "全部", list: fl },
      { k: "NEW", name: "新上架", list: by("NEW") },
      { k: "開放預購", name: "開放預購", list: by("開放預購") },
      { k: "補貨", name: "補貨", list: by("補貨") },
      { k: "已到貨", name: "已到貨", list: by("已到貨") },
      { k: "降價", name: "降價", list: by("降價") },
    ].filter((d) => d.list.length || d.k === "all");
    const map = Object.fromEntries(defs.map((d) => [d.k, d.list]));
    // 分頁網格：手機每頁 6 筆、電腦 12 筆，不必一直往下或往右滑
    let cur = [];
    const show = (n, scroll) => {
      const size = isMobile() ? 6 : 12, pages = Math.max(1, Math.ceil(cur.length / size));
      const page = Math.min(Math.max(1, n), pages), start = (page - 1) * size;
      $("#pulseGrid").innerHTML = cur.length ? cur.slice(start, start + size).map((i) => card(i)).join("")
        : `<p class="rail-empty">目前沒有變動。</p>`;
      pager($("#pulsePager"), page, pages, (p) => show(p, true));
      if (scroll) $("#pulseTabs").scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "center" });
    };
    tabs($("#pulseTabs"), defs.map((d) => ({ k: d.k, label: `${d.name}<small>${d.list.length}</small>` })),
      (k) => { cur = map[k].slice().sort((a, b) => (b.fs || "").localeCompare(a.fs || "")).slice(0, 120); show(1, false); });
  }

  /* ------------------------------------------------------------ news */
  const HL = /(アナログ盤?|レコード|LP|黑膠|vinyl|サウンドトラック|サントラ|原聲帶?|カセット|卡帶|発売決定|予約)/gi;
  function renderNews() {
    const news = NEWS.filter((n) => n.type === "news").sort((a, b) => (b.jp - a.jp) || b.date.localeCompare(a.date));
    let shown = 12;
    const draw = () => {
      $("#newsList").innerHTML = news.slice(0, shown).map((n) => `
        <li><a href="${esc(safeUrl(n.url))}" ${ext}>
          <time datetime="${esc(n.date)}">${esc(n.date.replace(/-/g, "."))}</time>
          <span><span class="nt">${esc(n.title).replace(HL, "<mark>$1</mark>")}</span><span class="ns">${esc(n.source)}${n.related ? ` · +${Number(n.related) || 0} 則相關` : ""}${n.franchise ? " · " + esc(n.franchise) : ""}</span></span>
          ${n.release && n.release >= TODAY ? `<span class="rel">${esc(n.release.slice(5).replace("-", "/"))} 發售</span>` : "<span></span>"}
        </a></li>`).join("") || `<li class="rail-empty">尚無新聞</li>`;
      let more = $("#newsMore");
      if (shown < news.length) {
        if (!more) {
          more = Object.assign(document.createElement("button"), { id: "newsMore", className: "btn ghost news-more", type: "button" });
          more.addEventListener("click", () => { shown += 12; draw(); });
          $("#newsList").after(more);
        }
        more.textContent = `更多 · ${news.length - shown}`;
      } else if (more) more.remove();
    };
    draw();
    const labels = NEWS.filter((n) => n.type === "label").sort((a, b) => (b.jp - a.jp) || (b.announce - a.announce) || b.date.localeCompare(a.date)).slice(0, 8);
    $("#labelGrid").innerHTML = labels.map((n) => `
      <a class="lcard" href="${esc(safeUrl(n.url))}" ${ext}>
        <div class="lc-img">${img(/cdn\.shopify\.com/.test(n.image || "") ? n.image + (n.image.includes("?") ? "&" : "?") + "width=360" : n.image, "", "ok")}<span class="pill-row"><span class="pill ${n.status === "預購" ? "pre" : n.status === "現貨" ? "stock" : "out"}">${esc(n.status)}</span></span></div>
        <span class="lc-t">${esc(n.title)}</span>
        <span class="lc-m"><span>${esc(n.source)}</span><span>${n.price ? esc(n.currency) + " " + fmtN(Number(n.price) || 0) : ""}</span></span>
      </a>`).join("") || `<p class="rail-empty">尚無資料</p>`;
  }

  /* ------------------------------------------------------------ catalog */
  let VIEW = "grid";
  const F = { page: 1, merge: true, q: "", ch: "shop", fmt: "", st: new Set(), kind: new Set(), src: new Set(), tag: new Set(), fr: "", sort: "smart", onlyJp: true, hideOut: true, onlyVer: false };
  let filtered = [];

  function readURL() {
    const p = new URLSearchParams(location.search);
    F.q = p.get("q") || ""; F.ch = p.get("ch") ?? "shop"; F.fmt = p.get("f") || ""; F.fr = p.get("fr") || ""; F.sort = p.get("sort") || "smart";
    ["st", "kind", "src", "tag"].forEach((k) => (F[k] = new Set((p.get(k) || "").split(",").filter(Boolean))));
    if (p.has("jp")) F.onlyJp = p.get("jp") !== "0";
    if (p.has("out")) F.hideOut = p.get("out") !== "1";
    if (p.has("ver")) F.onlyVer = p.get("ver") === "1";
    if (p.has("merge")) F.merge = p.get("merge") !== "0";
    F.page = Math.max(1, parseInt(p.get("page") || "1", 10) || 1);
    // 只接受已知值，避免網址參數帶入非預期內容
    if (!Object.hasOwn(SORTS, F.sort)) F.sort = "smart";
    if (!["", "shop", "market"].includes(F.ch)) F.ch = "shop";
    if (F.fmt && !Object.hasOwn(FMT, F.fmt)) F.fmt = "";
  }
  function writeURL() {
    const p = new URLSearchParams();
    if (F.q) p.set("q", F.q); if (F.ch !== "shop") p.set("ch", F.ch); if (F.fmt) p.set("f", F.fmt); if (F.fr) p.set("fr", F.fr); if (F.sort !== "smart") p.set("sort", F.sort);
    ["st", "kind", "src", "tag"].forEach((k) => F[k].size && p.set(k, [...F[k]].join(",")));
    if (!F.onlyJp) p.set("jp", "0"); if (!F.hideOut) p.set("out", "1"); if (F.onlyVer) p.set("ver", "1"); if (!F.merge) p.set("merge", "0"); if (F.page > 1) p.set("page", String(F.page));
    const cur = new URLSearchParams(location.search).get("item");
    if (cur) p.set("item", cur);
    const s = p.toString();
    history.replaceState(null, "", (s ? "?" + s : location.pathname) + location.hash);
  }

  function match(it, skip = "") {
    // 「只看日系」不套用在電影原聲帶（多為歐美作品）；選了「電影」類型時一併顯示
    if (F.onlyJp && !it.jp && !(it.k === "movie" && (F.kind.has("movie") || skip === "kind"))) return false;
    if (skip !== "ch" && skip !== "src" && !F.src.size && F.ch) {               // 指定通路時不受此限制
      if (F.ch === "shop" && MARKET.has(it.s)) return false;
      if (F.ch === "market" && !MARKET.has(it.s)) return false;
    }
    if (skip !== "st" && F.hideOut && it.st === "缺貨" && !F.st.has("缺貨")) return false;
    if (F.onlyVer && !it.v) return false;
    if (skip !== "fmt" && F.fmt && it.f !== F.fmt) return false;
    if (skip !== "st" && F.st.size && !F.st.has(it.st)) return false;
    if (skip !== "kind" && F.kind.size && !F.kind.has(it.k)) return false;
    if (skip !== "src" && F.src.size && !F.src.has(it.s)) return false;
    if (skip !== "tag" && F.tag.size && ![...F.tag].every((t) => (it.tg || []).includes(t))) return false;
    if (F.fr && it.fr !== F.fr) return false;
    if (F.q) { for (const w of F.q.toLowerCase().split(/\s+/)) if (w && !it._q.includes(w)) return false; }
    return true;
  }
  const ORDER = { 預購: 0, 現貨: 1, 可訂購: 2, 待確認: 3, 缺貨: 4 };
  const SORTS = {
    smart: (a, b) => ((b.fl || []).length > 0) - ((a.fl || []).length > 0) || ORDER[a.st] - ORDER[b.st] || MARKET.has(a.s) - MARKET.has(b.s) || (b.v - a.v) || (b.r || "").localeCompare(a.r || ""),
    release: (a, b) => (b.r || "").localeCompare(a.r || ""),
    first: (a, b) => (b.fs || "").localeCompare(a.fs || "") || a._i - b._i,
    priceAsc: (a, b) => (a.p ?? 1e9) - (b.p ?? 1e9),
    priceDesc: (a, b) => (b.p ?? -1) - (a.p ?? -1),
  };

  function counts(dim, keyFn) {
    const c = {};
    ITEMS.forEach((it) => { if (match(it, dim)) { const k = keyFn(it); c[k] = (c[k] || 0) + 1; } });
    return c;
  }
  function chipSet(el, dim, defs) {
    el.innerHTML = defs.map((d) => `<button class="chip" type="button" data-v="${esc(d.v)}" aria-pressed="${F[dim].has(d.v)}">${esc(d.label)}<small>${d.n ?? ""}</small></button>`).join("");
  }
  function renderControls() {
    const cc = counts("ch", (i) => (MARKET.has(i.s) ? "market" : "shop"));
    $("#chSeg").innerHTML = [["shop", "店家"], ["market", "拍賣"], ["", "全部"]].map(([v, l]) =>
      `<button type="button" data-v="${v}" aria-pressed="${F.ch === v}">${l}<small>${fmtN(v ? cc[v] || 0 : (cc.shop || 0) + (cc.market || 0))}</small></button>`).join("");
    $("#chSeg").classList.toggle("muted", F.src.size > 0);
    const cf = counts("fmt", (i) => i.f), tot = Object.values(cf).reduce((a, b) => a + b, 0);
    $("#fmtSeg").innerHTML = [["", "全部", tot], ...Object.keys(FMT).map((k) => [k, FMT[k], cf[k] || 0])]
      .map(([v, l, n]) => `<button type="button" data-v="${v}" aria-pressed="${F.fmt === v}">${l}<small>${fmtN(n)}</small></button>`).join("");
    const cs = counts("st", (i) => i.st);
    chipSet($("#statusChips"), "st", STATUSES.map((s) => ({ v: s, label: s, n: cs[s] || 0 })));
    const ck = counts("kind", (i) => i.k);
    chipSet($("#kindChips"), "kind", Object.keys(KIND).map((k) => ({ v: k, label: KIND[k], n: ck[k] || 0 })));
    const cs2 = counts("src", (i) => i.s);
    chipSet($("#srcChips"), "src", (META.sources || []).map((s) => ({ v: s.key, label: s.name, n: cs2[s.key] || 0 })));
    const ct = {}; ITEMS.forEach((it) => match(it, "tag") && (it.tg || []).forEach((t) => (ct[t] = (ct[t] || 0) + 1)));
    chipSet($("#tagChips"), "tag", TAGS.filter((t) => ct[t]).map((t) => ({ v: t, label: t, n: ct[t] })));
    const active = F.st.size + F.kind.size + F.src.size + F.tag.size + (F.fr ? 1 : 0) + (F.onlyVer ? 1 : 0) + (F.onlyJp ? 0 : 1) + (F.hideOut ? 0 : 1) + (F.merge ? 0 : 1) + (F.sort !== "smart" ? 1 : 0);
    $("#filterBadge").hidden = !active; $("#filterBadge").textContent = active;
    renderActive();
  }
  // 目前套用的條件，以可移除的標籤列出（不必打開篩選面板也知道結果為什麼變少）
  function renderActive() {
    const out = [];
    const add = (rm, label) => out.push(`<button type="button" class="achip" data-rm="${esc(rm)}" aria-label="移除條件：${esc(label)}">${esc(label)}<i aria-hidden="true">✕</i></button>`);
    if (F.q) add("q", `搜尋「${F.q}」`);
    if (F.fmt) add("fmt", FMT_LONG[F.fmt] || F.fmt);
    if (F.fr) add("fr", F.fr);
    F.st.forEach((v) => add(`st:${v}`, v));
    F.kind.forEach((v) => add(`kind:${v}`, KIND[v] || v));
    F.src.forEach((v) => add(`src:${v}`, srcName(v)));
    F.tag.forEach((v) => add(`tag:${v}`, v));
    if (!F.hideOut) add("hideOut", "包含缺貨");
    if (!F.onlyJp) add("onlyJp", "包含非日本作品");
    if (F.onlyVer) add("onlyVer", "只看已確認庫存");
    if (!F.merge) add("merge", "不合併同款");
    if (F.sort !== "smart") add("sort", `排序：${$(`#sortSel option[value="${F.sort}"]`)?.textContent || ""}`);
    if (out.length > 1) out.push(`<button type="button" class="achip clear" data-rm="all">全部清除</button>`);
    $("#activeChips").innerHTML = out.join("");
  }
  function removeFilter(rm) {
    const [k, v] = rm.split(/:(.*)/);
    if (k === "all") return resetFilters();
    if (k === "q") { F.q = ""; $("#q").value = ""; $("#heroQ").value = ""; }
    else if (k === "fmt") F.fmt = "";
    else if (k === "fr") { F.fr = ""; $("#frSel").value = ""; }
    else if (["st", "kind", "src", "tag"].includes(k)) F[k].delete(v);
    else if (k === "hideOut") { F.hideOut = true; $("#hideOut").checked = true; }
    else if (k === "onlyJp") { F.onlyJp = true; $("#onlyJp").checked = true; }
    else if (k === "onlyVer") { F.onlyVer = false; $("#onlyVerified").checked = false; }
    else if (k === "merge") { F.merge = true; $("#mergeSame").checked = true; }
    else if (k === "sort") { F.sort = "smart"; $("#sortSel").value = "smart"; }
    applyFilters();
  }
  function resetFilters() {
    Object.assign(F, { merge: true, q: "", ch: "shop", fmt: "", fr: "", sort: "smart", onlyJp: true, hideOut: true, onlyVer: false });
    ["st", "kind", "src", "tag"].forEach((k) => F[k].clear());
    $("#q").value = ""; $("#heroQ").value = ""; $("#frSel").value = ""; $("#sortSel").value = "smart";
    $("#onlyJp").checked = true; $("#hideOut").checked = true; $("#onlyVerified").checked = false; $("#mergeSame").checked = true;
    applyFilters();
  }

  // 篩選後讓結果從搜尋列正下方開始，避免內容變短時頁面跳動、搜尋列被捲走
  function keepAnchor() {
    if ($("#filterPanel").classList.contains("open") && isMobile()) return;
    const bar = $("#filters"), stickyTop = parseFloat(getComputedStyle(bar).top) || 0;
    const target = $(".result-row").getBoundingClientRect().top + scrollY - stickyTop - bar.offsetHeight - 6;
    if (scrollY > target + 1) window.scrollTo({ top: target, behavior: "instant" });
  }
  const isMobile = () => matchMedia("(max-width: 820px)").matches;
  // 分頁按鈕：‹ 1 … 4 5 6 … 20 ›，手機顯示較少頁碼
  function pager(el, page, pages, go) {
    if (pages <= 1) { el.innerHTML = ""; el.hidden = true; return; }
    el.hidden = false;
    const span = isMobile() ? 1 : 2, nums = new Set([1, pages]);
    for (let i = page - span; i <= page + span; i++) if (i >= 1 && i <= pages) nums.add(i);
    const list = [...nums].sort((a, b) => a - b);
    let html = `<button type="button" data-p="${page - 1}" ${page <= 1 ? "disabled" : ""} aria-label="上一頁">‹</button>`;
    list.forEach((n, i) => {
      if (i && n - list[i - 1] > 1) html += `<span class="gap">…</span>`;
      html += `<button type="button" data-p="${n}" ${n === page ? 'aria-current="page"' : ""}>${n}</button>`;
    });
    html += `<button type="button" data-p="${page + 1}" ${page >= pages ? "disabled" : ""} aria-label="下一頁">›</button>`;
    el.innerHTML = html;
    el.onclick = (e) => { const b = e.target.closest("button[data-p]"); if (b && !b.disabled) go(+b.dataset.p); };
  }
  function applyFilters({ anchor = true, keepPage = false } = {}) {
    let list = ITEMS.filter((i) => match(i));
    if (F.merge) { // 同一商品只顯示一張卡：有貨優先、其次最低價
      const rank = { 現貨: 0, 預購: 1, 可訂購: 2, 待確認: 3, 缺貨: 4 };
      const by = new Map();
      list.forEach((i) => {
        const k = i.g || i.id, cur = by.get(k);
        if (!cur || rank[i.st] - rank[cur.st] < 0 ||
            (rank[i.st] === rank[cur.st] && (i.p || 1e9) < (cur.p || 1e9))) by.set(k, i);
      });
      list = [...by.values()];
    }
    filtered = list.sort(SORTS[F.sort] || SORTS.smart);
    if (!keepPage) F.page = 1;
    showPage(F.page, { scroll: false });
    const pre = filtered.filter((i) => i.st === "預購").length, stock = filtered.filter((i) => i.st === "現貨").length;
    $("#resultLine").innerHTML = `找到 <b>${fmtN(filtered.length)}</b> 筆・預購 ${fmtN(pre)}・現貨 ${fmtN(stock)}`;
    $("#applyCount").textContent = fmtN(filtered.length);
    renderControls();
    writeURL();
    if (anchor) keepAnchor();
  }
  // 沒有結果時，告訴使用者可以怎麼放寬條件
  function emptyState() {
    const acts = [];
    if (F.q) acts.push(["q", "清除搜尋字"]);
    if (F.hideOut) acts.push(["showOut", "也顯示缺貨"]);
    if (F.ch === "shop" && !F.src.size) acts.push(["market", "也找拍賣"]);
    if (F.onlyJp) acts.push(["onlyJp", "包含非日本作品"]);
    acts.push(["all", "清除全部條件"]);
    return `<div class="empty"><div class="bubble"><b>找不到符合的商品…</b>${F.q ? `「${esc(F.q)}」可能換個寫法，例如日文或英文名稱。` : "目前的條件太嚴格了，試著放寬看看。"}</div>
      <div class="empty-acts">${acts.map(([k, l], i) => `<button type="button" class="btn${i === 0 ? " primary" : " ghost"}" data-empty="${k}">${l}</button>`).join("")}</div></div>`;
  }
  // 分頁顯示：手機每頁 20 筆、電腦 36 筆
  const pageSize = () => (isMobile() ? 20 : 36);
  function showPage(n, { scroll = true } = {}) {
    const size = pageSize(), pages = Math.max(1, Math.ceil(filtered.length / size));
    F.page = Math.min(Math.max(1, n), pages);
    const start = (F.page - 1) * size;
    $("#grid").innerHTML = filtered.length
      ? filtered.slice(start, start + size).map((i) => card(i)).join("")
      : emptyState();
    pager($("#pager"), F.page, pages, (p) => showPage(p));
    $("#pageInfo").textContent = pages > 1 ? `第 ${F.page} / ${pages} 頁` : "";
    if (scroll) {
      writeURL();
      const bar = $("#filters"), stickyTop = parseFloat(getComputedStyle(bar).top) || 0;
      const top = $(".result-row").getBoundingClientRect().top + scrollY - stickyTop - bar.offsetHeight - 6;
      window.scrollTo({ top, behavior: reduce ? "auto" : "smooth" });
    }
  }

  function bindCatalog() {
    readURL();
    $("#q").value = F.q; $("#sortSel").value = F.sort;
    $("#onlyJp").checked = F.onlyJp; $("#hideOut").checked = F.hideOut; $("#onlyVerified").checked = F.onlyVer;
    const frs = (META.franchises || []).slice().sort((a, b) => a.localeCompare(b, "zh-Hant"));
    $("#frSel").insertAdjacentHTML("beforeend", frs.map((f) => `<option>${esc(f)}</option>`).join(""));
    $("#frList").innerHTML = frs.map((f) => `<option value="${esc(f)}"></option>`).join("");   // 搜尋框自動完成作品名稱
    // 顯示方式：卡片（看封面）／清單（一次看更多筆），記在本機
    const setView = (v) => {
      VIEW = v === "list" ? "list" : "grid";
      $("#grid").classList.toggle("as-list", VIEW === "list");
      $$("#viewSeg button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.v === VIEW));
    };
    setView(store.get("ost-view", "grid"));
    $("#viewSeg").addEventListener("click", (e) => {
      const b = e.target.closest("button"); if (!b) return;
      setView(b.dataset.v); store.set("ost-view", VIEW);
    });
    $("#frSel").value = F.fr;

    let t;
    $("#q").addEventListener("input", (e) => { clearTimeout(t); t = setTimeout(() => { F.q = e.target.value.trim(); applyFilters(); }, 180); });
    $("#chSeg").addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; F.ch = b.dataset.v; F.src.clear(); applyFilters(); });
    $("#fmtSeg").addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; F.fmt = b.dataset.v; applyFilters(); });
    [["#statusChips", "st"], ["#kindChips", "kind"], ["#srcChips", "src"], ["#tagChips", "tag"]].forEach(([s, k]) =>
      $(s).addEventListener("click", (e) => {
        const b = e.target.closest(".chip"); if (!b) return;
        F[k].has(b.dataset.v) ? F[k].delete(b.dataset.v) : F[k].add(b.dataset.v); applyFilters();
      }));
    $("#frSel").addEventListener("change", (e) => { F.fr = e.target.value; applyFilters(); });
    $("#sortSel").addEventListener("change", (e) => { F.sort = e.target.value; applyFilters(); });
    $("#onlyJp").addEventListener("change", (e) => { F.onlyJp = e.target.checked; applyFilters(); });
    $("#hideOut").addEventListener("change", (e) => { F.hideOut = e.target.checked; applyFilters(); });
    $("#onlyVerified").addEventListener("change", (e) => { F.onlyVer = e.target.checked; applyFilters(); });
    $("#mergeSame").checked = F.merge;
    $("#mergeSame").addEventListener("change", (e) => { F.merge = e.target.checked; applyFilters(); });
    $("#resetBtn").addEventListener("click", resetFilters);
    $("#activeChips").addEventListener("click", (e) => { const b = e.target.closest("[data-rm]"); if (b) removeFilter(b.dataset.rm); });
    $("#grid").addEventListener("click", (e) => {
      const b = e.target.closest("[data-empty]"); if (!b) return;
      const k = b.dataset.empty;
      if (k === "q") removeFilter("q");
      else if (k === "showOut") { F.hideOut = false; $("#hideOut").checked = false; applyFilters(); }
      else if (k === "market") { F.ch = ""; applyFilters(); }
      else if (k === "onlyJp") { F.onlyJp = false; $("#onlyJp").checked = false; applyFilters(); }
      else resetFilters();
    });
    $("#legend").innerHTML = STATUSES.map((s) =>
      `<div><dt><span class="pill ${ST_CLS[s]}">${s}</span></dt><dd>${esc(STATUS_HELP[s])}</dd></div>`).join("");
    // 首頁的數字與快速查看：直接帶到對應的商品
    const go = (k) => {
      const toCatalog = () => { applyFilters({ anchor: false }); $("#catalog").scrollIntoView({ behavior: reduce ? "auto" : "smooth" }); };
      const fresh = () => {
        Object.assign(F, { q: "", ch: "shop", fmt: "", fr: "", onlyJp: true, hideOut: true, onlyVer: false });
        ["st", "kind", "src", "tag"].forEach((x) => F[x].clear());
        $("#q").value = ""; $("#frSel").value = ""; $("#onlyJp").checked = true; $("#hideOut").checked = true; $("#onlyVerified").checked = false;
      };
      if (k === "month") {
        $("#upcoming").scrollIntoView({ behavior: reduce ? "auto" : "smooth" });
        $(`#months .tab[data-k="${TODAY.slice(0, 7)}"]`)?.click();
      } else if (k === "new") {
        $("#pulse").scrollIntoView({ behavior: reduce ? "auto" : "smooth" });
        $('#pulseTabs .tab[data-k="NEW"]')?.click();
      } else if (k === "vinyl-stock") { fresh(); F.fmt = "vinyl"; F.st.add("現貨"); toCatalog(); }
      else if (k.startsWith("st:")) { fresh(); F.st.add(k.slice(3)); toCatalog(); }
      else if (k.startsWith("fr:")) { fresh(); F.fr = k.slice(3); $("#frSel").value = F.fr; toCatalog(); }
    };
    $("#stats").addEventListener("click", (e) => { const b = e.target.closest("[data-go]"); if (b) go(b.dataset.go); });
    $("#quick").addEventListener("click", (e) => { const b = e.target.closest("[data-go]"); if (b) go(b.dataset.go); });
    const panel = $("#filterPanel"), openBtn = $("#filterOpen");
    const setPanel = (open, { fromPop = false } = {}) => {
      const mobile = isMobile();
      if (mobile && !fromPop) {
        if (open && !panel.classList.contains("open")) history.pushState({ panel: 1 }, "");
        else if (!open && history.state?.panel) { history.back(); return; }
      }
      panel.classList.toggle("open", open); openBtn.setAttribute("aria-expanded", open);
      $("#filters").classList.toggle("panel-open", open && mobile);
      $("#fpBackdrop").hidden = !(open && mobile);
      if (mobile) document.body.classList.toggle("lock", open);
      if (open && mobile) $("#filterClose").focus({ preventScroll: true });
    };
    $("#fpBackdrop").addEventListener("click", () => setPanel(false));
    addEventListener("popstate", () => { if (panel.classList.contains("open")) setPanel(false, { fromPop: true }); });
    openBtn.addEventListener("click", () => setPanel(!panel.classList.contains("open")));
    $("#filterClose").addEventListener("click", () => setPanel(false));
    $("#applyBtn").addEventListener("click", () => { setPanel(false); setTimeout(keepAnchor, 150); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && panel.classList.contains("open")) setPanel(false); });

    $("#heroSearch").addEventListener("submit", (e) => {
      e.preventDefault();
      F.q = $("#heroQ").value.trim(); $("#q").value = F.q; applyFilters({ anchor: false });
      $("#heroQ").blur();
      $("#catalog").scrollIntoView({ behavior: reduce ? "auto" : "smooth" });
    });
    document.addEventListener("keydown", (e) => {
      if (e.key !== "/" || /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName) || !$("#sheet").hidden) return;
      e.preventDefault(); $("#q").focus({ preventScroll: true });
      $("#filters").scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
    });

    let lastMobile = isMobile();  // 轉向或視窗大小改變導致每頁筆數不同時重新分頁
    addEventListener("resize", () => { if (isMobile() !== lastMobile) { lastMobile = isMobile(); showPage(1, { scroll: false }); } });
    applyFilters({ anchor: false, keepPage: true });
  }

  /* ------------------------------------------------------------ detail sheet */
  function grams(s) {
    const t = s.toLowerCase().replace(/[\(\)\[\]（）【】《》「」『』\/\-–—_:：,，.。!！?？'"＋+&]/g, " ")
      .replace(/黑膠|彩膠|唱片|限定|盤|生產|生産|完全|初回|進口|日本|官方|環球|lp|cd|vinyl|edition|limited|版|\d+\s*(?:lp|cd)/g, " ");
    const set = new Set();
    t.split(/\s+/).forEach((w) => {
      if (!w) return;
      if (/^[a-z0-9]+$/.test(w)) { if (w.length > 2) set.add(w); return; }
      for (let i = 0; i < w.length - 1; i++) set.add(w.slice(i, i + 2));
    });
    return set;
  }
  function similar(it) {
    const g = grams(it.t); if (g.size < 2) return [];
    const pool = ITEMS.filter((o) => o !== it && o.f === it.f && o.s !== it.s && (!it.fr || o.fr === it.fr));
    return pool.map((o) => {
      const h = grams(o.t); let inter = 0; g.forEach((x) => h.has(x) && inter++);
      return [inter / (g.size + h.size - inter), o];
    }).filter(([s]) => s >= 0.32)
      .sort((a, b) => MARKET.has(a[1].s) - MARKET.has(b[1].s) || b[0] - a[0] || (a[1].p ?? 1e9) - (b[1].p ?? 1e9))
      .filter(([, o], _, arr) => { const n = (arr._n ||= {}); n[o.s] = (n[o.s] || 0) + 1; return n[o.s] <= 2; })
      .slice(0, 6).map(([, o]) => o);
  }
  // 查詢外部資料庫用的關鍵字：去掉格式、版本、通路標記
  const refQuery = (it) => it.t.replace(/[【\[(（][^】\])）]*[】\])）]/g, " ")
    .replace(/黑膠|彩膠|唱片|LP|CD|限定|初回|生產|生産|盤|預購|代購|代訂|現貨|全新|日版|進口|\d+\s*(?:吋|寸)/gi, " ")
    .replace(/\s+/g, " ").trim().slice(0, 80);
  let lastFocus = null;
  function openSheet(it, { push = true, back = false } = {}) {
    if ($("#sheet").hidden) lastFocus = document.activeElement;
    pushRecent(it.id);
    const st = ST_CLS[it.st] || "unk";
    const ckDate = shortDate(it.ck || (META.generated || "").slice(0, 10));
    const age = ageDays(it);
    const ver = age >= STALE_DAYS
      ? `<span class="ver no">${esc(ckDate)} 之後未能更新</span>`
      : it.v
        ? `<span class="ver">✓ ${esc(ckDate)} 確認${it.q != null && it.st !== "缺貨" ? `・庫存 ${it.q}` : ""}</span>`
        : `<span class="ver no">${esc(ckDate)} 列表資料・未複查</span>`;
    const rows = [
      ["格式", `${esc(FMT_LONG[it.f] || it.f)}${it.d ? `（${esc(it.d)} 張）` : ""}`],
      ["類型", `${KIND[it.k] || ""}・${SUB[it.sb] || ""}`],
      it.fr && ["作品", `<a href="?fr=${encodeURIComponent(it.fr)}#catalog" data-fr="${esc(it.fr)}">${esc(it.fr)} →</a>`],
      it.r && ["發售日", esc(relLong(it.r))],
      it.dl && ["預購截止", esc(relLong(it.dl)) + (it.dl < TODAY ? "（已截止）"
        : `（還有 ${Math.round((Date.parse(it.dl) - Date.parse(TODAY)) / 864e5)} 天）`)],
      it.q != null && it.st !== "缺貨" && ["剩餘庫存", it.q > 0 ? `${fmtN(it.q)} 件` : "需調貨"],
      it.so && ["已售出", `${fmtN(it.so)} 件`],
      it.n && !(it.r && /^預計/.test(it.n)) && ["備註", esc(it.n)],
      it.sl && ["品牌／賣家", esc(it.sl)],
      ["通路", `${esc(srcName(it.s))}${MARKET.has(it.s) ? "（拍賣）" : ""}`],
      it.bc && ["條碼", `<span class="num">${esc(it.bc)}</span> <button type="button" class="link-btn" data-copy="${esc(it.bc)}">複製</button>`],
      ["首次發現", esc((it.fs || "").replace(/-/g, "."))],
      (it.tg || []).length && ["版本", `<div class="sb-tags">${it.tg.map((t) => `<span>${esc(t)}</span>`).join("")}</div>`],
      (it.fl || []).length && ["動態", `<div class="sb-tags">${it.fl.map((t) => `<span>${esc(t)}</span>`).join("")}</div>`],
    ].filter(Boolean);
    // 比價：同一商品的所有報價，可購買者依價格排序
    const oi = offerInfo(it);
    const offers = oi.all.slice().sort((a, b) =>
      (BUYABLE.has(b.st) - BUYABLE.has(a.st)) || (a.p ?? 1e9) - (b.p ?? 1e9));  // 可購買者依價格由低到高
    const cmpHtml = oi.stores > 1 ? `<div class="sb-cmp"><h4>比價<small>${oi.stores} 家・${oi.all.length} 筆</small></h4>
      <ol>${offers.map((o) => {
        const low = oi.low != null && o.p === oi.low && BUYABLE.has(o.st) && o.p >= 250;
        const bits = salesBits(o);
        return `<li class="${low ? "low" : ""}${o === it ? " cur" : ""}">
          <a href="#" data-i="${o._i}" class="cmp-main"><span class="cs">${esc(srcName(o.s))}</span>
            <span class="cst ${ST_CLS[o.st] || "unk"}">${esc(stLabel(o))}</span>
            ${bits.length ? `<span class="cb">${esc(bits.join("・"))}</span>` : ""}</a>
          <span class="cp">${o.p ? "$" + fmtN(o.p) : "—"}${low ? "<em>最低</em>" : ""}</span>
          <a class="cgo" href="${esc(safeUrl(o.u))}" ${ext} aria-label="前往 ${esc(srcName(o.s))}">↗</a></li>`;
      }).join("")}</ol></div>` : "";
    const sameGroup = new Set(oi.all);
    const alts = similar(it).filter((o) => !sameGroup.has(o));
    // 同作品的其他商品（參考唱片行的「所有作品」「相關商品」）：每組只取一筆，有貨優先
    const altSet = new Set(alts);
    let siblings = [], sibTotal = 0;
    if (it.fr) {
      const rank = { 現貨: 0, 預購: 1, 可訂購: 2, 待確認: 3, 缺貨: 4 }, seen = new Set([it.g || it.id]);
      const pool = ITEMS.filter((o) => o.fr === it.fr && !MARKET.has(o.s) && !sameGroup.has(o) && !altSet.has(o))
        .sort((a, b) => rank[a.st] - rank[b.st] || (b.r || "").localeCompare(a.r || ""));
      pool.forEach((o) => { const k = o.g || o.id; if (!seen.has(k)) { seen.add(k); siblings.push(o); } });
      sibTotal = siblings.length; siblings = siblings.slice(0, 6);
    }
    $("#sheetBody").innerHTML = `
      ${back ? `<button type="button" class="link-btn sb-back" data-open-col>← 回到我的收藏</button>` : ""}
      <div class="sb-hero card" data-f="${esc(it.f)}"><span class="disc" aria-hidden="true"></span>
        ${cover(it, { eager: true, hi: true, phLen: 40 })}</div>
      <p class="sb-k">${esc(srcName(it.s))} · ${esc(FMT_LONG[it.f] || "")}</p>
      <h2 class="sb-t" id="sheetTitle">${esc(it.t)}</h2>
      <p class="sb-price">${it.p ? `<small>NT$</small>${fmtN(it.p)}` : "—"}</p>
      <div class="sb-status"><div class="sb-status-top"><span class="pill ${st}">${esc(stLabel(it))}</span>${ver}</div>
        ${STATUS_HELP[it.st] ? `<p class="sb-help">${esc(STATUS_HELP[it.st])}</p>` : ""}</div>
      <dl class="sb-dl">${rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>
      <div class="sb-actions">
        <a class="btn primary sb-buy" href="${esc(safeUrl(it.u))}" ${ext}>前往 ${esc(srcName(it.s))} <span aria-hidden="true">↗</span></a>
        ${favBtn(it, "btn ghost sb-fav")}
        <button class="btn ghost sb-share" type="button" data-share aria-label="分享">分享</button>
      </div>
      ${(META.links || []).filter((l) => l.search).map((l) => `<a class="sb-ref" href="${esc(safeUrl(l.search.replace("{q}", encodeURIComponent(refQuery(it)))))}" ${ext}>在 ${esc(l.name)} 查詢版本資料 <span aria-hidden="true">↗</span></a>`).join("")}
      ${cmpHtml}
      ${alts.length ? `<div class="sb-alt"><h4>相似商品</h4>
        ${alts.map((o) => `<a class="alt-row" href="#" data-i="${o._i}">${o.i ? img(o.th || o.i, "", "ok", { fallback: o.th ? o.i : "" }) : `<span class="ph"></span>`}
          <span><span class="at">${esc(o.t)}</span><span class="as">${esc(srcName(o.s))}</span></span>
          <span class="ap">${o.p ? "$" + fmtN(o.p) : "—"}<span>${esc(o.st)}</span></span></a>`).join("")}</div>` : ""}
      ${siblings.length ? `<div class="sb-alt"><h4>同作品的其他商品<small>${sibTotal} 款</small></h4>
        ${siblings.map((o) => miniRow(o).replace(' data-back="col"', "")).join("")}
        ${sibTotal > siblings.length ? `<a class="sb-more" href="?fr=${encodeURIComponent(it.fr)}#catalog" data-fr="${esc(it.fr)}">看「${esc(it.fr)}」全部 ${sibTotal + 1} 款 →</a>` : ""}</div>` : ""}`;
    current = it;
    showSheet({ push, url: (u) => { u.searchParams.delete("view"); u.searchParams.set("item", it.id); } });
  }
  let current = null;
  function toast(msg) {
    const t = $("#toast"); t.textContent = msg; t.hidden = false;
    clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), 2200);
  }
  async function share() {
    if (!current) return;
    const url = location.href, title = current.t;
    try {
      if (navigator.share) await navigator.share({ title, url });
      else { await navigator.clipboard.writeText(url); toast("已複製連結"); }
    } catch (e) { /* 使用者取消分享 */ }
  }
  function closeSheet({ fromPop = false } = {}) {
    if ($("#sheet").hidden) return;
    if (!fromPop && history.state?.sheet) { history.back(); return; }  // 交給 popstate 收尾
    const u = new URL(location.href); u.searchParams.delete("item"); u.searchParams.delete("view"); history.replaceState(null, "", u);
    $(".sheet-card").style.transform = "";
    current = null;
    $("#sheet").hidden = true; document.body.classList.remove("lock");
    lastFocus?.focus?.({ preventScroll: true });
  }
  function bindSheet() {
    addEventListener("popstate", () => { if (!$("#sheet").hidden) closeSheet({ fromPop: true }); });
    // 手機：在詳細頁頂端往下滑即可關閉
    const card = $(".sheet-card");
    let y0 = null, dy = 0;
    card.addEventListener("touchstart", (e) => { y0 = card.scrollTop <= 0 ? e.touches[0].clientY : null; dy = 0; }, { passive: true });
    card.addEventListener("touchmove", (e) => {
      if (y0 == null) return;
      dy = Math.max(0, e.touches[0].clientY - y0);
      if (dy > 0) card.style.transform = `translateY(${dy}px)`;
    }, { passive: true });
    card.addEventListener("touchend", () => {
      if (y0 == null) return;
      card.style.transition = "transform .25s ease";
      if (dy > 110) closeSheet(); else card.style.transform = "";
      setTimeout(() => (card.style.transition = ""), 260);
      y0 = null;
    });
    document.addEventListener("click", (e) => {
      const fav = e.target.closest("[data-fav]");
      if (fav) {
        toggleFav(fav.dataset.fav);
        if (fav.classList.contains("col-rm")) openCollection({ push: false });   // 在收藏清單裡移除：重新整理清單
        return;
      }
      if (e.target.closest("[data-open-col]")) { openCollection({ push: false }); return; }
      if (e.target.closest("[data-clear-recent]")) { RECENT = []; store.set("ost-recent", RECENT); openCollection({ push: false }); return; }
      const cp = e.target.closest("[data-copy]");
      if (cp) {
        navigator.clipboard?.writeText(cp.dataset.copy).then(() => toast("已複製條碼"), () => toast("無法複製，請手動選取"));
        return;
      }
      const c = e.target.closest(".card[data-i], .alt-row[data-i], .cmp-main[data-i]");
      if (c && !c.closest(".sb-hero")) { e.preventDefault(); openSheet(ITEMS[+c.dataset.i], { back: c.dataset.back === "col" }); return; }
      if (e.target.closest("[data-close]")) closeSheet();
      if (e.target.closest("[data-share]")) share();
      const fr = e.target.closest("a[data-fr]");
      if (fr) {
        e.preventDefault(); closeSheet();
        F.fr = fr.dataset.fr; $("#frSel").value = F.fr; F.onlyJp = true; applyFilters({ anchor: false });
        $("#catalog").scrollIntoView({ behavior: reduce ? "auto" : "smooth" });
      }
    });
    document.addEventListener("keydown", (e) => {
      if ($("#sheet").hidden) return;
      if (e.key === "Escape") closeSheet();
      if (e.key === "Tab") {
        const f = $$("#sheet a[href], #sheet button").filter((x) => x.offsetParent);
        if (!f.length) return;
        if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
        else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
      }
    });
  }

  /* ------------------------------------------------------------ stores */
  function renderStores() {
    const groups = [["唱片行", "唱片行"], ["書店電商", "電商"], ["綜合電商", "電商"], ["拍賣", "拍賣"]];
    const by = {};
    (META.sources || []).forEach((s) => {
      const g = (groups.find(([t]) => t === s.type) || [s.type, s.type])[1];
      (by[g] ||= []).push(s);
    });
    const tile = (s) => `
      <li class="store">
        <button class="store-row" type="button" data-src="${esc(s.key)}" aria-label="只看 ${esc(s.name)} 的商品">
          <span class="sn">${esc(s.name)}</span>
          <span class="sc">${fmtN(s.count)}</span>
          ${s.down ? `<span class="se">未更新</span>` : ""}
        </button>
        <a class="store-ext" href="${esc(safeUrl(s.home))}" ${ext} aria-label="開啟 ${esc(s.name)} 網站">↗</a>
      </li>`;
    const ref = (l) => `
      <li class="store">
        <a class="store-row" href="${esc(safeUrl(l.home))}" ${ext}><span class="sn">${esc(l.name)}</span><span class="sc">${l.note ? esc(l.note) : "—"}</span></a>
        <a class="store-ext" href="${esc(safeUrl(l.home))}" ${ext} aria-label="開啟 ${esc(l.name)} 網站">↗</a>
      </li>`;
    const linksBy = {};
    (META.links || []).forEach((l) => (linksBy[l.type] ||= []).push(l));  // 僅提供連結的通路與資料庫
    const sections = ["唱片行", "電商", "拍賣", "資料庫"].filter((g) => by[g] || linksBy[g]).map((g) =>
      `<div class="store-group"><h3>${g}</h3><ul>${(by[g] || []).map(tile).join("")}${(linksBy[g] || []).map(ref).join("")}</ul></div>`);
    $("#storeList").innerHTML = sections.join("");
    $("#storeList").addEventListener("click", (e) => {
      const b = e.target.closest("button.store-row"); if (!b) return;
      F.src = new Set([b.dataset.src]); F.onlyJp = true; $("#onlyJp").checked = true; applyFilters({ anchor: false });
      $("#catalog").scrollIntoView({ behavior: reduce ? "auto" : "smooth" });
    });
  }

  /* ------------------------------------------------------------ chrome */
  function bindChrome() {
    const nav = $(".nav"), topBtn = $("#toTop");
    let lastY = scrollY;
    const onScroll = () => {
      const y = scrollY;
      nav.classList.toggle("scrolled", y > 8);
      if (isMobile()) {
        if (y > 480 && y > lastY + 6) document.body.classList.add("nav-hidden");
        else if (y < lastY - 6 || y < 200) document.body.classList.remove("nav-hidden");
      }
      topBtn.hidden = y < 1600;
      lastY = y;
    };
    addEventListener("scroll", onScroll, { passive: true }); onScroll();
    topBtn.addEventListener("click", () => scrollTo({ top: 0, behavior: reduce ? "auto" : "smooth" }));
    $("#themeBtn").addEventListener("click", () => {
      const t = document.documentElement.dataset.theme === "light" ? "dark" : "light";
      document.documentElement.dataset.theme = t;
      try { localStorage.setItem("ost-theme", t); } catch (e) { /* 私密模式 */ }
    });
    const links = $$(".nav-links a");
    const io = new IntersectionObserver((es) => es.forEach((e) => {
      if (e.isIntersecting) links.forEach((a) => a.classList.toggle("active", a.getAttribute("href") === "#" + e.target.id));
    }), { rootMargin: "-45% 0px -50% 0px" });
    $$("main section[id]").forEach((s) => io.observe(s));
    const rv = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("in"); rv.unobserve(e.target); } }), { rootMargin: "0px 0px -10% 0px" });
    $$(".section-head, .news-grid, .store-list").forEach((el) => { el.classList.add("reveal"); rv.observe(el); });
  }

  /* ------------------------------------------------------------ skeleton + parallax */
  function skeleton() {
    const sk = `<div class="skel" aria-hidden="true"><i></i><b></b><b></b></div>`;
    ["#upcomingRail", "#pulseGrid"].forEach((s) => ($(s).innerHTML = sk.repeat(6)));
    $("#grid").innerHTML = sk.repeat(10);
    $("#newsList").innerHTML = `<li class="skel-line"></li>`.repeat(6);
  }
  function parallax() {
    if (reduce || !matchMedia("(hover: hover) and (pointer: fine)").matches) return;
    const stage = $(".hero-stage"), sl = $("#heroSleeves"), tt = $(".turntable");
    let raf = 0;
    addEventListener("pointermove", (e) => {
      if (raf || scrollY > innerHeight) return;
      raf = requestAnimationFrame(() => {
        raf = 0;
        const x = e.clientX / innerWidth - 0.5, y = e.clientY / innerHeight - 0.5;
        tt.style.transform = `translate(${x * -10}px, ${y * -10}px)`;
        sl.style.transform = `translate(${x * 22}px, ${y * 18}px) rotate(${x * 3}deg)`;
        stage.style.setProperty("--tilt", `${x * 4}deg`);
      });
    }, { passive: true });
  }

  /* ------------------------------------------------------------ boot */
  // 圖片載入／失敗改用事件委派（不用 inline onload/onerror，才能啟用嚴格 CSP）
  document.addEventListener("load", (e) => { if (e.target.tagName === "IMG") e.target.classList.add("ok"); }, true);
  document.addEventListener("error", (e) => {
    const t = e.target;
    if (t.tagName !== "IMG") return;
    if (t.dataset.fb) { t.src = t.dataset.fb; delete t.dataset.fb; return; } // 縮圖失敗 → 通路原圖
    if (t.hasAttribute("data-ph")) t.replaceWith(Object.assign(document.createElement("div"), { className: "ph" }));
    else t.remove();
  }, true);
  // 主色底：用 CSSOM 設定（嚴格 CSP 不允許 HTML 內的 style 屬性）
  new MutationObserver((ms) => ms.forEach((m) => m.addedNodes.forEach((n) => {
    if (n.nodeType !== 1) return;
    (n.matches?.("[data-c]") ? [n] : []).concat([...n.querySelectorAll("[data-c]")])
      .forEach((el) => {
        if (/^#[0-9a-f]{6}$/i.test(el.dataset.c)) el.style.backgroundColor = el.dataset.c;  // 只接受 #rrggbb
        el.removeAttribute("data-c");
      });
  }))).observe(document.body, { childList: true, subtree: true });
  bindChrome();
  skeleton();
  parallax();
  load().then(() => {
    renderHero(); renderTicker(); renderUpcoming(); renderPulse(); renderNews(); renderStores();
    bindCatalog(); bindSheet();
    updateFavBadge();
    $("#favBtn").addEventListener("click", () => openCollection());
    const params = new URLSearchParams(location.search);
    const hit = params.get("item") && BY_ID.get(params.get("item"));
    if (hit) openSheet(hit, { push: false });
    else if (params.get("view") === "fav") openCollection({ push: false });
  });
})();
