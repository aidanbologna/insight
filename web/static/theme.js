// Light and dark. Runs before the page is drawn so there is no flash of the wrong colours.
// With no choice saved, the page follows the device's own light/dark setting (see theme.css).
(function () {
  "use strict";
  var KEY = "insight-theme";
  var root = document.documentElement;

  function saved() {
    try { return localStorage.getItem(KEY); } catch (e) { return null; }
  }

  function current() {
    return root.dataset.theme ||
      (window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  }

  var choice = saved();
  if (choice === "light" || choice === "dark") root.dataset.theme = choice;

  document.addEventListener("DOMContentLoaded", function () {
    var year = document.getElementById("year");
    if (year) year.textContent = new Date().getFullYear();
    var button = document.getElementById("theme-toggle");
    if (!button) return;
    button.addEventListener("click", function () {
      var next = current() === "dark" ? "light" : "dark";
      root.dataset.theme = next;
      try { localStorage.setItem(KEY, next); } catch (e) { /* private window: the choice lasts until reload */ }
      document.dispatchEvent(new CustomEvent("themechange"));
    });
  });
})();
