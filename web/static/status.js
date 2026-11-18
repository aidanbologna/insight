// The status page: how the data fetches have gone since the server started. Refreshes every 30 seconds.
(function () {
  "use strict";

  var KIND_NAMES = { quotes: "Prices", history: "Charts", details: "Company details", earnings: "Earnings",
                     search: "Search" };
  var RESULT = { failed: ["Failed", "weak"], rate_limited: ["Slow down", "fair"], empty: ["Empty", "fair"] };

  function byId(id) { return document.getElementById(id); }
  function cell(text, className) {
    var td = document.createElement("td");
    if (className) td.className = className;
    td.textContent = text;
    return td;
  }
  function row(cells) {
    var tr = document.createElement("tr");
    cells.forEach(function (c) { tr.appendChild(c); });
    return tr;
  }
  function when(iso) {
    if (!iso) return "not yet";
    var date = new Date(iso);
    return date.toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
                                          second: "2-digit" });
  }
  function duration(seconds) {
    var d = Math.floor(seconds / 86400), h = Math.floor(seconds % 86400 / 3600), m = Math.floor(seconds % 3600 / 60);
    if (d) return d + "d " + h + "h";
    if (h) return h + "h " + m + "m";
    return m ? m + "m " + (seconds % 60) + "s" : seconds + "s";
  }

  function show(s) {
    var t = s.totals, asked = t.ok + t.empty + t.failed + t.rate_limited;
    byId("subtitle").textContent = "Data from " + s.source + ". Server started " + when(s.started) +
      " and has been up for " + duration(s.uptime_seconds) + ".";
    byId("total-ok").textContent = t.ok;
    byId("total-empty").textContent = t.empty;
    byId("total-failed").textContent = t.failed;
    byId("total-limited").textContent = t.rate_limited;
    byId("total-failed").className = "card-value" + (t.failed ? " down" : "");
    byId("total-limited").className = "card-value" + (t.rate_limited ? " down" : "");
    byId("share-ok").textContent = asked
      ? Math.round(t.ok / asked * 100) + "% of " + asked + (asked === 1 ? " fetch" : " fetches") : "No fetches yet";
    byId("holding").textContent = s.holding_back_seconds
      ? "Holding back for " + duration(s.holding_back_seconds) : "Not holding back";

    var rows = byId("fetch-rows");
    rows.textContent = "";
    Object.keys(s.fetches).forEach(function (kind) {
      var f = s.fetches[kind];
      rows.appendChild(row([cell(KIND_NAMES[kind] || kind), cell(f.ok, "number"), cell(f.empty, "number"),
                            cell(f.failed, "number"), cell(f.rate_limited, "number"), cell(when(s.last_ok[kind]))]));
    });

    var c = s.cache, lim = s.ceiling, v = s.visitors;
    var served = c.fresh + c.fetched + c.joined + c.stale;
    var facts = [
      ["Answers served", served + " in all: " + c.fresh + " from memory, " + c.fetched + " fetched new, " +
        c.joined + " shared someone else's fetch, " + c.stale + " older than their lifetime"],
      ["Answers held in memory", c.entries + " (" + c.numbers.toLocaleString("en-US") + " numbers)"],
      ["Ceiling on the data source", lim.per_minute + " a minute, " + lim.burst + " at once. " + lim.waited +
        " fetches waited their turn, " + lim.turned_away + " were turned away, " + lim.held_back +
        " were not sent while holding back"],
      ["Visitors", v.addresses_last_10_minutes + " address" + (v.addresses_last_10_minutes === 1 ? "" : "es") +
        " in the last 10 minutes. Limit " + v.per_minute + " requests a minute each; " + v.limited + " requests refused"],
      ["Visitor address taken from", (v.address_from === "forwarded" ? "the host's forwarding header" : "the connection") +
        " (this request passed " + v.forwarding_steps_on_this_request + " forwarding step" +
        (v.forwarding_steps_on_this_request === 1 ? "" : "s") + ")"],
      ["Memory in use", s.memory_mb == null ? "not available on this system" : s.memory_mb + " MB"],
      ["Web version", s.web_version]
    ];
    var body = byId("facts");
    body.textContent = "";
    facts.forEach(function (fact) { body.appendChild(row([cell(fact[0]), cell(String(fact[1]))])); });

    var problems = byId("problem-rows");
    problems.textContent = "";
    s.problems.forEach(function (p) {
      var result = RESULT[p.outcome] || [p.outcome, "fair"];
      var pill = document.createElement("span");
      pill.className = "pill " + result[1];
      pill.textContent = result[0];
      var resultCell = document.createElement("td");
      resultCell.appendChild(pill);
      problems.appendChild(row([cell(when(p.at)), cell(KIND_NAMES[p.kind] || p.kind), cell(p.what), resultCell,
                                cell(p.message)]));
    });
    byId("problem-table").hidden = !s.problems.length;
    byId("no-problems").hidden = !!s.problems.length;
  }

  var timer = null;

  function load() {
    clearTimeout(timer);
    fetch("/api/status", { headers: { Accept: "application/json" } })
      .then(function (response) {
        if (!response.ok) throw new Error("status " + response.status);
        return response.json();
      })
      .then(show)
      .catch(function () { byId("subtitle").textContent = "Couldn't reach the server. Trying again shortly."; })
      .then(function () {
        clearTimeout(timer);
        timer = setTimeout(function () { if (!document.hidden) load(); }, 30000);
      });
  }

  document.addEventListener("visibilitychange", function () { if (!document.hidden) load(); });
  load();
})();
