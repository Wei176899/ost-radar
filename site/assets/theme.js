/* 防止網站被其他頁面以 iframe 嵌入（點擊劫持）。GitHub Pages 無法設定 frame-ancestors 標頭，改由此處處理 */
(function () {
  if (window.top !== window.self) {
    try { window.top.location.replace(window.self.location.href); }
    catch (e) { document.documentElement.style.display = "none"; }
  }
})();

/* 在畫面繪製前套用深淺色，避免閃爍（獨立檔案以符合 CSP，不使用 inline script） */
(function () {
  try {
    var t = localStorage.getItem("ost-theme");
    if (t === "light" || t === "dark") document.documentElement.dataset.theme = t;
    else if (matchMedia("(prefers-color-scheme: light)").matches) document.documentElement.dataset.theme = "light";
  } catch (e) { /* 私密模式等無法使用 localStorage */ }
})();

/* 網頁字型載入完成後才套用（避免外部字型拖慢首屏） */
(function () {
  var l = document.getElementById("webfonts");
  if (!l) return;
  var on = function () { l.media = "all"; };
  if (l.sheet) on(); else l.addEventListener("load", on);
})();
