// Познаване на системата и версията под бутоните. Сайтът работи и без този скрипт.

// Версията: в HTML е написана на ръка, тук се взима от последния Release (това, което бутоните теглят)
(function () {
  var spots = document.querySelectorAll("[data-ver]");
  if (!spots.length || !window.fetch) return;
  fetch("https://api.github.com/repos/sako4018/newspaper/releases/latest")
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (d) {
      if (!d || !/^v\d+(\.\d+)*$/.test(d.tag_name || "")) return;
      for (var i = 0; i < spots.length; i++) spots[i].textContent = d.tag_name;
    })
    .catch(function () {});
})();

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
