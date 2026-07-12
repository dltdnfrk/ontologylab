/* ontologylab local dashboard — review queue + engines/settings. Offline, no CDN. */

(function () {
  "use strict";

  function $(sel) {
    return document.querySelector(sel);
  }

  function showTab(name) {
    document.querySelectorAll(".tab-btn").forEach(function (btn) {
      var on = btn.dataset.tab === name;
      btn.classList.toggle("active", on);
      btn.setAttribute("aria-selected", on ? "true" : "false");
    });
    document.querySelectorAll(".tab-panel").forEach(function (panel) {
      panel.classList.toggle("active", panel.dataset.tabPanel === name);
    });
  }

  document.querySelectorAll(".tab-btn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      showTab(btn.dataset.tab);
    });
  });

  async function api(path, opts) {
    var res = await fetch(path, opts);
    var body = null;
    try {
      body = await res.json();
    } catch (_) {
      body = null;
    }
    if (!res.ok) {
      var detail = (body && body.detail) || res.statusText;
      throw new Error(detail);
    }
    return body;
  }

  function renderCounts(counts) {
    var box = $("#counts-box");
    if (!counts) {
      box.innerHTML = "<div class='status-row'><span>No counts</span></div>";
      return;
    }
    box.innerHTML =
      "<div class='status-row'><span>nodes proposed:</span> <code>" +
      (counts.nodes_proposed || 0) +
      "</code></div>" +
      "<div class='status-row'><span>edges proposed:</span> <code>" +
      (counts.edges_proposed || 0) +
      "</code></div>" +
      "<div class='status-row'><span>nodes verified:</span> <code>" +
      (counts.nodes_verified || 0) +
      "</code></div>" +
      "<div class='status-row'><span>edges verified:</span> <code>" +
      (counts.edges_verified || 0) +
      "</code></div>" +
      "<div class='status-row'><span>documents:</span> <code>" +
      (counts.documents || 0) +
      "</code></div>";
  }

  function itemLabel(item) {
    if (item.label) return item.label;
    if (item.name) return item.name;
    if (item.src_node_id && item.dst_node_id) {
      return item.src_node_id.slice(0, 8) + " → " + item.dst_node_id.slice(0, 8);
    }
    return item.id ? item.id.slice(0, 12) : "—";
  }

  async function act(kind, id) {
    var path =
      kind === "approve" ? "/api/proposals/approve" : "/api/proposals/reject";
    try {
      await api(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: id, cascade: kind === "approve" }),
      });
      $("#review-error").classList.add("hidden");
      await loadProposals();
    } catch (err) {
      var el = $("#review-error");
      el.textContent = String(err.message || err);
      el.classList.remove("hidden");
    }
  }

  async function loadProposals() {
    var tbody = $("#proposals-body");
    var empty = $("#review-empty");
    var err = $("#review-error");
    err.classList.add("hidden");
    try {
      var data = await api("/api/proposals?limit=200");
      renderCounts(data.counts);
      tbody.innerHTML = "";
      var items = data.items || [];
      if (!items.length) {
        empty.classList.remove("hidden");
        return;
      }
      empty.classList.add("hidden");
      items.forEach(function (item) {
        var tr = document.createElement("tr");
        var conf =
          item.confidence == null ? "—" : Number(item.confidence).toFixed(2);
        tr.innerHTML =
          "<td>" +
          (item.kind || "") +
          "</td>" +
          "<td>" +
          (item.type_name || item.entity_type || item.relation_type || "") +
          "</td>" +
          "<td><code>" +
          itemLabel(item) +
          "</code><br><small class='muted'>" +
          (item.id || "").slice(0, 12) +
          "</small></td>" +
          "<td>" +
          conf +
          "</td>" +
          "<td><small>" +
          (item.source_doc_id || "").slice(0, 10) +
          "</small></td>" +
          "<td class='actions'></td>";
        var actions = tr.querySelector(".actions");
        var approveBtn = document.createElement("button");
        approveBtn.className = "btn btn-primary";
        approveBtn.textContent = "Approve";
        approveBtn.addEventListener("click", function () {
          act("approve", item.id);
        });
        var rejectBtn = document.createElement("button");
        rejectBtn.className = "btn btn-danger";
        rejectBtn.textContent = "Reject";
        rejectBtn.addEventListener("click", function () {
          act("reject", item.id);
        });
        actions.appendChild(approveBtn);
        actions.appendChild(document.createTextNode(" "));
        actions.appendChild(rejectBtn);
        tbody.appendChild(tr);
      });
    } catch (e) {
      err.textContent = String(e.message || e);
      err.classList.remove("hidden");
    }
  }

  async function loadEngines() {
    var list = $("#engines-list");
    try {
      var engines = await api("/api/engines");
      list.innerHTML = "";
      engines.forEach(function (eng) {
        var li = document.createElement("li");
        li.textContent =
          eng.name +
          " — " +
          (eng.available ? "available" : "missing") +
          (eng.default_model ? " (default: " + eng.default_model + ")" : "");
        list.appendChild(li);
      });
      var cost = await api("/api/cost");
      $("#cost-pre").textContent = JSON.stringify(cost, null, 2);
    } catch (e) {
      list.innerHTML = "<li class='err-msg'>" + e.message + "</li>";
    }
  }

  async function loadSettings() {
    try {
      var s = await api("/api/settings");
      $("#settings-pre").textContent = JSON.stringify(s, null, 2);
    } catch (e) {
      $("#settings-pre").textContent = String(e.message || e);
    }
  }

  $("#refresh-btn").addEventListener("click", loadProposals);

  loadProposals();
  loadEngines();
  loadSettings();
})();
