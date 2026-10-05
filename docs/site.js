// Познаване на системата. Сайтът работи и без този скрипт.
(function () {
  // На началната страница правилният бутон е червен и е първи
  var buttons = document.getElementById("buttons");
  if (!buttons) return;
  var ua = (navigator.userAgent || "") + " " + (navigator.platform || "");
  var os = /Win/i.test(ua) ? "win" : (/Mac/i.test(ua) && !/iPhone|iPad|iPod/i.test(ua)) ? "mac" : null;
  var btn = os && document.getElementById("btn-" + os);
  if (!btn) return;
  btn.classList.add("primary");
  buttons.insertBefore(btn, buttons.firstChild);
})();
