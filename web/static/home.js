// The Home page: asks the server for the market snapshot and draws it.
// The server decides how often to come back (every minute while the market is open).
(function () {
  "use strict";

  var grid = document.getElementById("snapshot-grid");
  var updated = document.getElementById("updated");
  var notice = document.getElementById("notice");
  var cards = {};             // symbol -> the elements of its card
  var timer = null;
  var dueAt = 0;              // when the next refresh is due (ms)
  var failures = 0;
  var loading = false;
  var SVG = "http://www.w3.org/2000/svg";

  // --- numbers, written the way the Windows app writes them ------------------------------------
  function grouped(value, digits) {
    return value.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  }
  function fmtPrice(v) { return v == null ? "—" : grouped(v, Math.abs(v) < 1 ? 4 : 2); }
  function sign(v) { return v < 0 ? "-" : "+"; }
  function fmtChange(v) { return v == null ? "—" : sign(v) + grouped(Math.abs(v), 2); }
  function fmtPct(v) { return v == null ? "—" : sign(v) + Math.abs(v).toFixed(2) + "%"; }
  function trend(v) { return v == null || Math.abs(v) < 1e-9 ? "flat" : v > 0 ? "up" : "down"; }

  function clock(date) {
    return date.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
  }
  function when(iso) {
    var date = new Date(iso);
    if (isNaN(date)) return "";
    var sameDay = date.toDateString() === new Date().toDateString();
    return sameDay ? clock(date)
      : date.toLocaleDateString("en-US", { month: "short", day: "numeric" }) + ", " + clock(date);
  }

  // --- cards ---------------------------------------------------------------------------------------
  function element(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function buildCard(card) {
    var box = element("article", "card");
    var top = element("div", "card-top");
    top.appendChild(element("span", "eyebrow", card ? card.label : " "));
    top.appendChild(element("span", "symbol", card ? card.symbol : ""));
    var value = element("p", "card-value", "—");
    var change = element("p", "card-change", " ");
    var spark = document.createElementNS(SVG, "svg");
    spark.setAttribute("class", "spark flat");
    spark.setAttribute("aria-hidden", "true");
    box.appendChild(top);
    box.appendChild(value);
    box.appendChild(change);
    box.appendChild(spark);
    grid.appendChild(box);
    return { box: box, value: value, change: change, spark: spark, values: [], trend: "flat" };
  }

  function drawSpark(card) {
    var svg = card.spark, values = card.values;
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    var width = svg.clientWidth || 200, height = 38, pad = 3;
    svg.setAttribute("viewBox", "0 0 " + width + " " + height);
    svg.setAttribute("class", "spark " + card.trend);
    if (values.length < 2) return;
    var low = Math.min.apply(null, values), high = Math.max.apply(null, values);
    var span = (high - low) || 1, step = (width - 2 * pad) / (values.length - 1);
    function y(v) { return pad + (high - v) * (height - 2 * pad) / span; }
    var points = values.map(function (v, i) { return (pad + i * step).toFixed(1) + "," + y(v).toFixed(1); });

    var base = document.createElementNS(SVG, "line");      // dashed line at where the month started
    base.setAttribute("class", "spark-base");
    base.setAttribute("x1", pad); base.setAttribute("x2", width - pad);
    base.setAttribute("y1", y(values[0]).toFixed(1)); base.setAttribute("y2", y(values[0]).toFixed(1));
    var line = document.createElementNS(SVG, "polyline");
    line.setAttribute("class", "spark-line");
    line.setAttribute("points", points.join(" "));
    var end = document.createElementNS(SVG, "circle");
    var last = points[points.length - 1].split(",");
    end.setAttribute("class", "spark-end");
    end.setAttribute("cx", last[0]); end.setAttribute("cy", last[1]); end.setAttribute("r", 2.5);
    svg.appendChild(base); svg.appendChild(line); svg.appendChild(end);
  }

  function showCard(card) {
    var view = cards[card.symbol];
    if (!view || card.last == null) return;       // no price for this one: leave what is there
    var direction = trend(card.change);
    if (card.kind === "yield") {
      view.value.textContent = card.last.toFixed(2) + "%";
      view.change.textContent = sign(card.change) + Math.abs(card.change * 100).toFixed(1) + " bp";
    } else {
      view.value.textContent = (card.kind === "usd" ? "$" : "") + fmtPrice(card.last);
      view.change.textContent = fmtChange(card.change) + "  (" + fmtPct(card.pct) + ")";
    }
    view.change.className = "card-change " + direction;
    view.values = card.spark || [];
    view.trend = direction;
    drawSpark(view);
  }

  function show(data) {
    if (!Object.keys(cards).length) {             // first answer: replace the placeholders
      grid.textContent = "";
      data.cards.forEach(function (card) { cards[card.symbol] = buildCard(card); });
    }
    data.cards.forEach(showCard);

    document.getElementById("brief-date").textContent = data.date;
    document.getElementById("brief-text").textContent = data.brief;
    ["market", "footer"].forEach(function (name) {
      document.getElementById(name + "-text").textContent = data.market.text;
      document.getElementById(name + "-dot").classList.toggle("is-open", data.market.open);
    });
    document.getElementById("source-name").textContent = data.source;

    if (!data.cards.some(function (card) { return card.last != null; })) {
      showProblem("Market data is unavailable right now. Trying again shortly.");
      return;
    }
    updated.classList.remove("is-problem");
    updated.textContent = (data.stale ? "Numbers from " : "Updated ") + when(data.as_of);
    notice.hidden = !data.notice;
    notice.textContent = data.notice || "";
  }

  function showProblem(message) {
    updated.classList.add("is-problem");
    updated.textContent = message;
  }

  // --- loading and refreshing ------------------------------------------------------------------
  function schedule(seconds) {
    clearTimeout(timer);
    dueAt = Date.now() + seconds * 1000;
    timer = setTimeout(tick, seconds * 1000);
  }

  function tick() {
    if (document.hidden) return;                  // nobody is looking: wait until they come back
    load();
  }

  function load() {
    if (loading) return;
    loading = true;
    fetch("/api/snapshot", { headers: { Accept: "application/json" } })
      .then(function (response) {
        return response.json().then(function (body) { return { ok: response.ok, body: body }; });
      })
      .then(function (result) {
        loading = false;
        if (!result.ok) {
          var error = result.body.error || {};
          failures += 1;
          showProblem(error.message || "The server couldn't get the numbers. Trying again shortly.");
          schedule(Math.min(Math.max(error.retry_after || 20, 20), 300));
          return;
        }
        failures = 0;
        show(result.body);
        schedule(result.body.refresh_seconds || 60);
      })
      .catch(function () {
        loading = false;
        failures += 1;
        showProblem("Couldn't reach the server. Trying again shortly.");
        schedule(Math.min(20 * failures, 120));
      });
  }

  document.addEventListener("visibilitychange", function () {
    if (!document.hidden && Date.now() >= dueAt) load();
  });
  document.addEventListener("themechange", function () {
    Object.keys(cards).forEach(function (symbol) { drawSpark(cards[symbol]); });
  });
  if (window.ResizeObserver) {
    new ResizeObserver(function () {
      Object.keys(cards).forEach(function (symbol) { drawSpark(cards[symbol]); });
    }).observe(grid);
  }

  for (var i = 0; i < 8; i++) buildCard(null);     // empty cards while the first numbers load
  load();
})();
