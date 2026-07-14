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
      maybeLoadTab(btn.dataset.tab);
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

  // --- keyboard-first review state -----------------------------------
  var reviewRows = []; // [{id, tr}] in render order
  var reviewCursor = -1;
  var reviewOrder = "confidence"; // least-certain first (triage default)

  function focusRow(index) {
    if (!reviewRows.length) return;
    if (reviewCursor >= 0 && reviewRows[reviewCursor]) {
      reviewRows[reviewCursor].tr.classList.remove("row-focused");
    }
    reviewCursor = Math.max(0, Math.min(index, reviewRows.length - 1));
    var row = reviewRows[reviewCursor];
    row.tr.classList.add("row-focused");
    row.tr.scrollIntoView({ block: "nearest" });
  }

  document.addEventListener("keydown", function (ev) {
    // never hijack typing in inputs
    var tag = (ev.target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select") return;
    if (!reviewRows.length) return;
    if (ev.key === "j") focusRow(reviewCursor + 1);
    else if (ev.key === "k") focusRow(reviewCursor - 1);
    else if (ev.key === "a" && reviewCursor >= 0)
      act("approve", reviewRows[reviewCursor].id);
    else if (ev.key === "r" && reviewCursor >= 0)
      act("reject", reviewRows[reviewCursor].id);
    else if (ev.key === "s") focusRow(reviewCursor + 1); // skip
    else if (ev.key === "e" && reviewCursor >= 0) {
      var focused = reviewRows[reviewCursor];
      // entity view applies to nodes; for an edge, no-op
      if (focused.kind === "node") loadEntityPanel(focused.id);
      else return;
    } else return;
    ev.preventDefault();
  });

  async function loadProposals() {
    var tbody = $("#proposals-body");
    var empty = $("#review-empty");
    var err = $("#review-error");
    err.classList.add("hidden");
    reviewRows = [];
    reviewCursor = -1;
    try {
      var data = await api("/api/proposals?limit=200&order=" + reviewOrder);
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
        /* Advisory display ONLY: the critic score never pre-selects or
           pre-checks a decision (anchoring-bias guard). */
        var critic = "—";
        if (item.critic_score != null) {
          critic = Number(item.critic_score).toFixed(2);
          if (item.critic_disagreement) {
            critic +=
              " <span class='badge' title='extractor/critic disagreement" +
              (item.critic_rationale
                ? ": " + escapeHtml(item.critic_rationale)
                : "") +
              "'>⚠</span>";
          } else if (item.critic_rationale) {
            critic =
              "<span title='" + escapeHtml(item.critic_rationale) + "'>" +
              critic + "</span>";
          }
        }
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
          "<td>" +
          critic +
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
        if (item.kind === "node") {
          var focusBtn = document.createElement("button");
          focusBtn.className = "btn";
          focusBtn.textContent = "Entity";
          focusBtn.title = "Entity-centric view: all mentions and relations";
          focusBtn.addEventListener("click", function () {
            loadEntityPanel(item.id);
          });
          actions.appendChild(document.createTextNode(" "));
          actions.appendChild(focusBtn);
        }
        tbody.appendChild(tr);
        reviewRows.push({ id: item.id, kind: item.kind, tr: tr });
      });
      if (reviewRows.length) focusRow(0);
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

  /* ---- M8 dashboard: Sources / Jobs / Packs / MCP ---- */

  /* All server-derived strings (titles, URIs, progress lines, ids, details)
     are attacker-influenced content from crawled pages: always escapeHtml
     before innerHTML, or use textContent. */
  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  /* POST helper that returns the JSON body even on non-2xx, so ok:false
     contract envelopes ({ok, error_kind, detail}) render instead of throwing. */
  async function apiSend(path, payload) {
    var res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    var body = null;
    try {
      body = await res.json();
    } catch (_) {
      body = null;
    }
    if (body && typeof body === "object") return body;
    if (!res.ok) throw new Error(res.statusText || "HTTP " + res.status);
    return {};
  }

  function splitList(value) {
    return String(value || "")
      .split(",")
      .map(function (s) {
        return s.trim();
      })
      .filter(Boolean);
  }

  function toInt(value, fallback) {
    var n = parseInt(value, 10);
    return isNaN(n) ? fallback : n;
  }

  function fmtTs(ts) {
    if (ts == null || ts === "") return "—";
    var d = typeof ts === "number" ? new Date(ts < 1e12 ? ts * 1000 : ts) : new Date(ts);
    return isNaN(d.getTime()) ? String(ts) : d.toLocaleString();
  }

  function statusBadge(status) {
    var s = String(status || "").toLowerCase();
    return (
      "<span class='badge st-" +
      escapeHtml(s) +
      "'>" +
      escapeHtml(s || "—") +
      "</span>"
    );
  }

  function errorKindBadge(kind) {
    var k = String(kind || "error");
    return (
      "<span class='badge badge-errkind kind-" +
      escapeHtml(k) +
      "'>" +
      escapeHtml(k.replace(/_/g, " ").toUpperCase()) +
      "</span>"
    );
  }

  function showResult(el, html, isError) {
    el.innerHTML = html;
    el.classList.toggle("result-error", !!isError);
    el.classList.remove("hidden");
  }

  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text);
    }
    /* fallback: hidden textarea + execCommand for non-secure contexts */
    return new Promise(function (resolve, reject) {
      var ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      var ok = false;
      try {
        ok = document.execCommand("copy");
      } catch (_) {
        ok = false;
      }
      document.body.removeChild(ta);
      if (ok) resolve();
      else reject(new Error("copy failed"));
    });
  }

  function flashButton(btn, label) {
    var original = btn.textContent;
    btn.textContent = label;
    btn.disabled = true;
    setTimeout(function () {
      btn.textContent = original;
      btn.disabled = false;
    }, 1500);
  }

  /* -- Sources -- */

  async function loadDocuments() {
    var tbody = $("#documents-body");
    var empty = $("#sources-empty");
    var err = $("#sources-error");
    err.classList.add("hidden");
    try {
      var data = await api("/api/documents");
      var docs = (data && data.documents) || [];
      tbody.innerHTML = docs
        .map(function (doc) {
          return (
            "<tr>" +
            "<td>" + escapeHtml(doc.source_kind || "") + "</td>" +
            "<td>" + escapeHtml(doc.title || "(untitled)") + "</td>" +
            "<td><code>" + escapeHtml(doc.source_uri || "") + "</code></td>" +
            "<td><small>" + escapeHtml(fmtTs(doc.fetched_ts)) + "</small></td>" +
            "</tr>"
          );
        })
        .join("");
      empty.classList.toggle("hidden", docs.length > 0);
    } catch (e) {
      err.textContent = String(e.message || e);
      err.classList.remove("hidden");
    }
  }

  $("#collect-form").addEventListener("submit", async function (ev) {
    ev.preventDefault();
    var box = $("#collect-result");
    var btn = $("#collect-submit");
    var payload = {
      urls: splitList($("#collect-urls").value),
      files: splitList($("#collect-files").value),
      paper_queries: splitList($("#collect-paper-query").value),
      paper_source: $("#collect-paper-source").value,
      limit: toInt($("#collect-limit").value, 5),
    };
    if (!payload.urls.length && !payload.files.length && !payload.paper_queries.length) {
      showResult(box, "Nothing to collect — provide URLs, file paths, or a paper query.", true);
      return;
    }
    btn.disabled = true;
    showResult(box, "<span class='muted'>Collecting…</span>");
    try {
      var res = await apiSend("/api/collect", payload);
      if (res && res.ok) {
        showResult(
          box,
          "<span class='ok-msg'>Collected.</span> documents: <code>" +
            escapeHtml(String(res.documents != null ? res.documents : "?")) +
            "</code> · created: <code>" +
            escapeHtml(String(res.created != null ? res.created : "?")) +
            "</code> · duplicates: <code>" +
            escapeHtml(String(res.duplicates != null ? res.duplicates : "?")) +
            "</code>"
        );
        await loadDocuments();
      } else {
        showResult(
          box,
          errorKindBadge(res && res.error_kind) +
            " " +
            escapeHtml((res && res.detail) || "Collect failed."),
          true
        );
      }
    } catch (e) {
      showResult(box, escapeHtml(String(e.message || e)), true);
    } finally {
      btn.disabled = false;
    }
  });

  /* -- Jobs -- */

  var jobsPollTimer = null;
  var selectedJobId = null;
  var extractEnginesLoaded = false;

  async function populateEngineSelect() {
    var sel = $("#extract-engine");
    try {
      var engines = (await api("/api/engines")) || [];
      sel.innerHTML = "";
      engines.forEach(function (eng) {
        var opt = document.createElement("option");
        opt.value = eng.name;
        opt.textContent = eng.name + (eng.available ? "" : " (missing)");
        opt.disabled = !eng.available;
        sel.appendChild(opt);
      });
      var firstAvailable = engines.filter(function (e) {
        return e.available;
      })[0];
      if (firstAvailable) sel.value = firstAvailable.name;
    } catch (_) {
      sel.innerHTML = "<option value='mock'>mock</option>";
    }
  }

  function totalsSummary(totals) {
    var t = totals || {};
    return (
      "nodes +" + (t.nodes_new || 0) + "/~" + (t.nodes_merged || 0) +
      " · edges +" + (t.edges_new || 0) + "/~" + (t.edges_merged || 0)
    );
  }

  function renderJobDetail(job) {
    $("#job-detail").classList.remove("hidden");
    $("#job-detail-title").textContent =
      "Job " + String(job.job_id || "").slice(0, 12) + " — " + (job.status || "");
    var lines = (job.progress || []).slice();
    if (job.error) lines.push("error: " + job.error);
    /* textContent: progress lines are server/crawl-derived, never innerHTML */
    $("#job-progress").textContent = lines.length ? lines.join("\n") : "(no progress yet)";
  }

  async function selectJob(jobId) {
    selectedJobId = jobId;
    try {
      var job = await api("/api/jobs/" + encodeURIComponent(jobId));
      if (job) renderJobDetail(job);
    } catch (e) {
      $("#job-detail").classList.remove("hidden");
      $("#job-detail-title").textContent = "Job " + String(jobId).slice(0, 12);
      $("#job-progress").textContent = String(e.message || e);
    }
    await loadJobs();
  }

  function renderJobs(jobs) {
    var tbody = $("#jobs-body");
    tbody.innerHTML = "";
    jobs.forEach(function (job) {
      var tr = document.createElement("tr");
      if (job.job_id === selectedJobId) tr.classList.add("selected");
      tr.innerHTML =
        "<td><code>" + escapeHtml(String(job.job_id || "").slice(0, 12)) + "</code></td>" +
        "<td>" + escapeHtml(job.engine || "") +
        (job.model ? " <small class='muted'>" + escapeHtml(job.model) + "</small>" : "") +
        "</td>" +
        "<td>" + statusBadge(job.status) + "</td>" +
        "<td><small>" + escapeHtml(totalsSummary(job.totals)) + "</small></td>" +
        "<td><small>" + escapeHtml(fmtTs(job.started_ts)) + "</small></td>" +
        "<td><small>" + escapeHtml(fmtTs(job.finished_ts)) + "</small></td>";
      tr.addEventListener("click", function () {
        selectJob(job.job_id);
      });
      tbody.appendChild(tr);
    });
    $("#jobs-empty").classList.toggle("hidden", jobs.length > 0);
  }

  function scheduleJobsPoll(anyRunning) {
    if (jobsPollTimer) {
      clearTimeout(jobsPollTimer);
      jobsPollTimer = null;
    }
    if (anyRunning) jobsPollTimer = setTimeout(loadJobs, 1500);
  }

  async function loadJobs() {
    var err = $("#jobs-error");
    err.classList.add("hidden");
    try {
      var data = await api("/api/jobs");
      var jobs = (data && data.jobs) || [];
      renderJobs(jobs);
      if (selectedJobId) {
        var sel = jobs.filter(function (j) {
          return j.job_id === selectedJobId;
        })[0];
        if (sel) renderJobDetail(sel);
      }
      var anyRunning = jobs.some(function (j) {
        return j.status === "running";
      });
      scheduleJobsPoll(anyRunning);
    } catch (e) {
      err.textContent = String(e.message || e);
      err.classList.remove("hidden");
      scheduleJobsPoll(false);
    }
  }

  $("#extract-form").addEventListener("submit", async function (ev) {
    ev.preventDefault();
    var box = $("#extract-result");
    var btn = $("#extract-submit");
    var model = $("#extract-model").value.trim();
    var payload = {
      engine: $("#extract-engine").value || "mock",
      model: model || null,
      doc_ids: [],
      /* mirror paths.DEFAULT_MAX_ENGINE_CALLS / DEFAULT_TIME_BUDGET_S —
         change there first, then here */
      max_engine_calls: 200,
      time_budget: 1800,
      seed: toInt($("#extract-seed").value, 7),
    };
    btn.disabled = true;
    showResult(box, "<span class='muted'>Starting extraction…</span>");
    try {
      var res = await apiSend("/api/extract", payload);
      if (res && res.job_id) {
        selectedJobId = res.job_id;
        showResult(
          box,
          "Started job <code>" +
            escapeHtml(String(res.job_id).slice(0, 12)) +
            "</code> " +
            statusBadge(res.status || "running")
        );
        await loadJobs();
      } else {
        showResult(
          box,
          escapeHtml((res && (res.detail || res.error)) || "Failed to start extraction."),
          true
        );
      }
    } catch (e) {
      showResult(box, escapeHtml(String(e.message || e)), true);
    } finally {
      btn.disabled = false;
    }
  });

  /* -- Packs -- */

  async function loadPacks() {
    var tbody = $("#packs-body");
    var empty = $("#packs-empty");
    var err = $("#packs-error");
    err.classList.add("hidden");
    try {
      var data = await api("/api/packs");
      var packs = (data && data.packs) || [];
      tbody.innerHTML = packs
        .map(function (pack) {
          var counts = pack.counts || {};
          return (
            "<tr>" +
            "<td><code>" + escapeHtml(pack.pack_id || "") + "</code></td>" +
            "<td><small>" + escapeHtml(fmtTs(pack.created_ts)) + "</small></td>" +
            "<td>" + escapeHtml(String(counts.documents || 0)) + "</td>" +
            "<td>" + escapeHtml(String(counts.nodes_verified || 0)) + "</td>" +
            "<td>" + escapeHtml(String(counts.edges_verified || 0)) + "</td>" +
            "<td>" + escapeHtml(pack.search_tier || "—") + "</td>" +
            "<td><code>" + escapeHtml(String(pack.content_hash || "").slice(0, 12)) + "</code></td>" +
            "<td><button type='button' class='btn mcpb-btn' data-pack='" +
            escapeHtml(pack.pack_id || "") + "'>.mcpb</button></td>" +
            "</tr>"
          );
        })
        .join("");
      empty.classList.toggle("hidden", packs.length > 0);
    } catch (e) {
      err.textContent = String(e.message || e);
      err.classList.remove("hidden");
    }
  }

  /* Bundle-and-download one pack as .mcpb (delegated: rows re-render). */
  $("#packs-body").addEventListener("click", async function (ev) {
    var btn = ev.target.closest ? ev.target.closest(".mcpb-btn") : null;
    if (!btn) return;
    var packId = btn.dataset.pack;
    btn.disabled = true;
    try {
      var res = await apiSend(
        "/api/packs/" + encodeURIComponent(packId) + "/mcpb", {}
      );
      if (res && res.ok) {
        flashButton(btn, "Bundled!");
        window.location.href = res.download_url;
      } else {
        flashButton(btn, "Failed");
        var errEl = $("#packs-error");
        errEl.textContent = (res && res.detail) || "mcpb bundling failed";
        errEl.classList.remove("hidden");
      }
    } catch (e) {
      flashButton(btn, "Failed");
    } finally {
      btn.disabled = false;
    }
  });

  $("#pack-build-form").addEventListener("submit", async function (ev) {
    ev.preventDefault();
    var box = $("#pack-build-result");
    var btn = $("#pack-build-submit");
    var name = $("#pack-name").value.trim();
    if (!name) {
      showResult(box, "Pack name is required.", true);
      return;
    }
    btn.disabled = true;
    showResult(box, "<span class='muted'>Building pack…</span>");
    try {
      var res = await apiSend("/api/packs/build", { name: name });
      if (res && res.ok) {
        var manifest = res.manifest || {};
        var counts = manifest.counts || {};
        showResult(
          box,
          "<span class='ok-msg'>Pack built.</span> <code>" +
            escapeHtml(manifest.pack_id || name) +
            "</code> · documents: <code>" +
            escapeHtml(String(counts.documents || 0)) +
            "</code> · nodes: <code>" +
            escapeHtml(String(counts.nodes_verified || 0)) +
            "</code> · edges: <code>" +
            escapeHtml(String(counts.edges_verified || 0)) +
            "</code>"
        );
        await loadPacks();
        await loadMcp();
      } else {
        showResult(box, escapeHtml((res && res.detail) || "Pack build failed."), true);
      }
    } catch (e) {
      showResult(box, escapeHtml(String(e.message || e)), true);
    } finally {
      btn.disabled = false;
    }
  });

  /* -- MCP -- */

  async function loadMcp() {
    var cards = $("#mcp-cards");
    var empty = $("#mcp-empty");
    var err = $("#mcp-error");
    err.classList.add("hidden");
    try {
      var data = await api("/api/mcp/status");
      $("#mcp-packs-dir").textContent = (data && data.packs_dir) || "—";
      var packs = (data && data.packs) || [];
      cards.innerHTML = "";
      packs.forEach(function (pack) {
        var counts = pack.counts || {};
        var card = document.createElement("div");
        card.className = "mcp-card";
        card.innerHTML =
          "<div class='row space-between'>" +
          "<strong><code>" + escapeHtml(pack.pack_id || "") + "</code></strong>" +
          "<span class='muted'>" + escapeHtml(fmtTs(pack.created_ts)) + "</span>" +
          "</div>" +
          "<p class='muted'>documents: " + escapeHtml(String(counts.documents || 0)) +
          " · nodes: " + escapeHtml(String(counts.nodes_verified || 0)) +
          " · edges: " + escapeHtml(String(counts.edges_verified || 0)) +
          "</p>";
        var pre = document.createElement("pre");
        pre.className = "code-block";
        pre.textContent = pack.serve_command || "—";
        card.appendChild(pre);
        var copyBtn = document.createElement("button");
        copyBtn.type = "button";
        copyBtn.className = "btn";
        copyBtn.textContent = "Copy stdio config";
        copyBtn.addEventListener("click", function () {
          copyText(JSON.stringify(pack.stdio_config || {}, null, 2)).then(
            function () {
              flashButton(copyBtn, "Copied!");
            },
            function () {
              flashButton(copyBtn, "Copy failed");
            }
          );
        });
        card.appendChild(copyBtn);
        cards.appendChild(card);
      });
      empty.classList.toggle("hidden", packs.length > 0);
    } catch (e) {
      err.textContent = String(e.message || e);
      err.classList.remove("hidden");
    }
  }

  /* -- Entity-centric review panel (W11) -- */

  async function entityAct(kind, id, entityId) {
    await act(kind, id); // reuses the per-item gate + queue refresh
    loadEntityPanel(entityId); // then re-render the panel in place
  }

  async function loadEntityPanel(entityId) {
    var panel = $("#entity-panel");
    var body = $("#entity-panel-body");
    var err = $("#entity-panel-error");
    err.classList.add("hidden");
    panel.classList.remove("hidden");
    body.innerHTML = "<p class='muted'>Loading…</p>";
    var ctx;
    try {
      ctx = await api("/api/entity/" + encodeURIComponent(entityId) + "/review");
    } catch (e) {
      body.innerHTML = "";
      err.textContent = String(e.message || e);
      err.classList.remove("hidden");
      return;
    }
    var ent = ctx.entity || {};
    $("#entity-panel-title").textContent =
      "Entity: " + (ent.name || entityId.slice(0, 12));

    var html = "";
    html +=
      "<p><strong>" + escapeHtml(ent.name || "") + "</strong> " +
      statusBadge(ent.status) +
      " <small class='muted'>" + escapeHtml(ent.entity_type || "") +
      " · conf " +
      (ent.confidence == null ? "—" : Number(ent.confidence).toFixed(2)) +
      (ctx.critic
        ? " · critic " + Number(ctx.critic.score).toFixed(2) +
          (ctx.critic.rationale
            ? " (" + escapeHtml(ctx.critic.rationale) + ")"
            : "")
        : "") +
      "</small></p>";
    if ((ent.aliases || []).length) {
      html += "<p><small>aliases: " +
        ent.aliases.map(escapeHtml).join(", ") + "</small></p>";
    }

    var counts = ctx.counts || {};
    html += "<h4>Mentions (" + escapeHtml(String(counts.mentions || 0)) + ")</h4>";
    (ctx.mentions || []).forEach(function (m) {
      html +=
        "<div class='status-box'><small class='muted'>" +
        escapeHtml(m.doc_title || (m.source_doc_id || "").slice(0, 10)) +
        "</small><br><small>…" +
        escapeHtml(m.excerpt || "(no span)") + "…</small></div>";
    });

    html += "<h4>Relations (" +
      escapeHtml(String(counts.relations_proposed || 0)) + " proposed / " +
      escapeHtml(String(counts.relations_verified || 0)) + " verified)</h4>";
    body.innerHTML = html;

    (ctx.relations || []).forEach(function (rel) {
      var line = document.createElement("div");
      line.className = "status-row";
      var arrow =
        rel.direction === "out"
          ? "—[" + rel.relation_type + "]→ " + (rel.other || {}).name
          : "←[" + rel.relation_type + "]— " + (rel.other || {}).name;
      var label = document.createElement("span");
      label.innerHTML =
        statusBadge(rel.status) + " " + escapeHtml(arrow) +
        " <small class='muted'>(other: " +
        escapeHtml((rel.other || {}).status || "") + ")" +
        (rel.critic_score != null
          ? " critic " + Number(rel.critic_score).toFixed(2)
          : "") +
        "</small>";
      line.appendChild(label);
      if (rel.status === "proposed") {
        var actions = document.createElement("span");
        var ok = document.createElement("button");
        ok.className = "btn btn-primary";
        ok.textContent = "Approve";
        ok.addEventListener("click", function () {
          entityAct("approve", rel.id, entityId);
        });
        var no = document.createElement("button");
        no.className = "btn btn-danger";
        no.textContent = "Reject";
        no.addEventListener("click", function () {
          entityAct("reject", rel.id, entityId);
        });
        actions.appendChild(ok);
        actions.appendChild(document.createTextNode(" "));
        actions.appendChild(no);
        line.appendChild(actions);
      }
      body.appendChild(line);
    });

    if ((ctx.merge_candidates || []).length) {
      var h4 = document.createElement("h4");
      h4.textContent = "Merge candidates (" + ctx.merge_candidates.length + ")";
      body.appendChild(h4);
      ctx.merge_candidates.forEach(function (cand) {
        var line = document.createElement("div");
        line.className = "status-row";
        var span = document.createElement("span");
        span.innerHTML =
          "~ <strong>" + escapeHtml((cand.other || {}).name || "") +
          "</strong> " + statusBadge((cand.other || {}).status) +
          " <small class='muted'>score " +
          Number(cand.score || 0).toFixed(2) + " · " +
          (cand.reasons || []).map(escapeHtml).join(", ") +
          " — decide in the Merge tab</small>";
        line.appendChild(span);
        body.appendChild(line);
      });
    }
  }

  /* -- Merge review (W7) -- */

  function nodeCellHtml(node) {
    var aliases = (node.aliases || []).map(escapeHtml).join(", ") || "—";
    var props = Object.keys(node.properties || {}).length
      ? escapeHtml(JSON.stringify(node.properties))
      : "—";
    return (
      "<td class='merge-node'>" +
      "<strong>" + escapeHtml(node.name || "") + "</strong> " +
      statusBadge(node.status) +
      "<br><small class='muted'>type: " + escapeHtml(node.entity_type || "") +
      " · conf: " + (node.confidence == null ? "—" : Number(node.confidence).toFixed(2)) +
      " · citations: " + escapeHtml(String(node.citation_count || 0)) + "</small>" +
      "<br><small>aliases: " + aliases + "</small>" +
      "<br><small>props: " + props + "</small>" +
      "<br><small class='muted'><code>" + escapeHtml((node.id || "").slice(0, 12)) + "</code></small>" +
      "</td>"
    );
  }

  async function mergeAct(candidateId, targetId, sourceId) {
    var err = $("#merge-error");
    err.classList.add("hidden");
    try {
      var res = await apiSend(
        "/api/merge/candidates/" + encodeURIComponent(candidateId) + "/merge",
        { target_id: targetId, source_id: sourceId }
      );
      if (res && res.ok === undefined && res.detail) throw new Error(res.detail);
      await loadMergeCandidates();
      await loadProposals();
    } catch (e) {
      err.textContent = String(e.message || e);
      err.classList.remove("hidden");
    }
  }

  async function mergeDismiss(candidateId) {
    var err = $("#merge-error");
    err.classList.add("hidden");
    try {
      var res = await apiSend(
        "/api/merge/candidates/" + encodeURIComponent(candidateId) + "/dismiss",
        {}
      );
      if (res && res.ok === undefined && res.detail) throw new Error(res.detail);
      await loadMergeCandidates();
    } catch (e) {
      err.textContent = String(e.message || e);
      err.classList.remove("hidden");
    }
  }

  async function loadMergeCandidates() {
    var cards = $("#merge-cards");
    var empty = $("#merge-empty");
    var err = $("#merge-error");
    err.classList.add("hidden");
    try {
      var data = await api("/api/merge/candidates?limit=100");
      var items = (data && data.items) || [];
      cards.innerHTML = "";
      items.forEach(function (item) {
        var a = item.node_a || {};
        var b = item.node_b || {};
        var card = document.createElement("div");
        card.className = "mcp-card merge-card";
        var reasons = (item.reasons || [])
          .map(function (r) {
            return "<span class='badge'>" + escapeHtml(r) + "</span>";
          })
          .join(" ");
        card.innerHTML =
          "<div class='row space-between'>" +
          "<strong>score " + escapeHtml(Number(item.score || 0).toFixed(2)) + "</strong>" +
          "<span>" + reasons + "</span>" +
          "</div>" +
          "<div class='table-wrap'><table class='merge-table'><tbody><tr>" +
          nodeCellHtml(a) + nodeCellHtml(b) +
          "</tr></tbody></table></div>" +
          "<div class='form-actions merge-actions'></div>";
        var actions = card.querySelector(".merge-actions");
        function addBtn(label, cls, handler) {
          var btn = document.createElement("button");
          btn.type = "button";
          btn.className = "btn " + cls;
          btn.textContent = label;
          btn.addEventListener("click", handler);
          actions.appendChild(btn);
          actions.appendChild(document.createTextNode(" "));
        }
        addBtn("◀ Keep “" + (a.name || "A") + "”", "btn-primary", function () {
          mergeAct(item.id, a.id, b.id);
        });
        addBtn("Keep “" + (b.name || "B") + "” ▶", "btn-primary", function () {
          mergeAct(item.id, b.id, a.id);
        });
        addBtn("Not a duplicate", "", function () {
          mergeDismiss(item.id);
        });
        cards.appendChild(card);
      });
      empty.classList.toggle("hidden", items.length > 0);
    } catch (e) {
      err.textContent = String(e.message || e);
      err.classList.remove("hidden");
    }
  }

  $("#merge-scan-btn").addEventListener("click", async function () {
    var box = $("#merge-scan-result");
    var btn = $("#merge-scan-btn");
    btn.disabled = true;
    showResult(box, "<span class='muted'>Scanning…</span>");
    try {
      var res = await apiSend("/api/merge/scan", {});
      if (res && res.ok) {
        showResult(
          box,
          "Scanned <code>" + escapeHtml(String(res.nodes || 0)) +
            "</code> nodes · new candidates: <code>" +
            escapeHtml(String(res.candidates_new || 0)) + "</code>"
        );
        await loadMergeCandidates();
      } else {
        showResult(box, escapeHtml((res && res.detail) || "Scan failed."), true);
      }
    } catch (e) {
      showResult(box, escapeHtml(String(e.message || e)), true);
    } finally {
      btn.disabled = false;
    }
  });
  $("#merge-refresh-btn").addEventListener("click", loadMergeCandidates);

  /* -- Lazy loading + refresh wiring -- */

  var tabLoaders = {
    merge: loadMergeCandidates,
    sources: loadDocuments,
    jobs: function () {
      if (!extractEnginesLoaded) {
        extractEnginesLoaded = true;
        populateEngineSelect();
      }
      return loadJobs();
    },
    packs: loadPacks,
    mcp: loadMcp,
  };
  var loadedTabs = {};

  function maybeLoadTab(name) {
    if (loadedTabs[name] || !tabLoaders[name]) return;
    loadedTabs[name] = true;
    tabLoaders[name]();
  }

  $("#sources-refresh-btn").addEventListener("click", loadDocuments);
  $("#jobs-refresh-btn").addEventListener("click", loadJobs);
  $("#packs-refresh-btn").addEventListener("click", loadPacks);
  $("#mcp-refresh-btn").addEventListener("click", loadMcp);

  $("#refresh-btn").addEventListener("click", loadProposals);

  $("#review-order").addEventListener("change", function () {
    reviewOrder = $("#review-order").value || "confidence";
    loadProposals();
  });

  async function populateCriticEngines() {
    var sel = $("#critic-engine");
    try {
      var engines = (await api("/api/engines")) || [];
      sel.innerHTML = "";
      engines.forEach(function (eng) {
        var opt = document.createElement("option");
        opt.value = eng.name;
        opt.textContent = eng.name + (eng.available ? "" : " (missing)");
        opt.disabled = !eng.available;
        sel.appendChild(opt);
      });
    } catch (_) {
      sel.innerHTML = "<option value='mock'>mock</option>";
    }
  }

  $("#critic-run-btn").addEventListener("click", async function () {
    var box = $("#critic-result");
    var btn = $("#critic-run-btn");
    btn.disabled = true;
    showResult(box, "<span class='muted'>Critic scoring… (advisory only — approval stays yours)</span>");
    try {
      var res = await apiSend("/api/critic/run", {
        engine: $("#critic-engine").value || "mock",
      });
      if (res && res.ok) {
        showResult(
          box,
          "Critic scored <code>" + escapeHtml(String(res.scored || 0)) +
            "</code>/<code>" + escapeHtml(String(res.candidates || 0)) +
            "</code> pending item(s) · disagreements: <code>" +
            escapeHtml(String(res.disagreements || 0)) + "</code>"
        );
        $("#review-order").value = "critic";
        reviewOrder = "critic";
        await loadProposals();
      } else {
        showResult(box, escapeHtml((res && res.detail) || "Critic run failed."), true);
      }
    } catch (e) {
      showResult(box, escapeHtml(String(e.message || e)), true);
    } finally {
      btn.disabled = false;
    }
  });
  populateCriticEngines();

  loadProposals();
  loadEngines();
  loadSettings();
})();
