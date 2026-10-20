/* 在畫面繪製前套用深淺色，避免閃爍（獨立檔案以符合 CSP，不使用 inline script） */
(function () {
  try {
    var t = localStorage.getItem("ost-theme");
    if (t === "light" || t === "dark") document.documentElement.dataset.theme = t;
    else if (matchMedia("(prefers-color-scheme: light)").matches) document.documentElement.dataset.theme = "light";
  } catch (e) { /* 私密模式等無法使用 localStorage */ }
})();
