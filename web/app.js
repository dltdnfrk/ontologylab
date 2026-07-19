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
    updateReviewBadge(counts);
    if (!counts) {
      box.innerHTML = "<div class='status-row'><span>집계 없음</span></div>";
      return;
    }
    box.innerHTML =
      "<div class='status-row'><span>개념(노드) 검토 대기:</span> <code>" +
      (counts.nodes_proposed || 0) +
      "</code></div>" +
      "<div class='status-row'><span>관계(엣지) 검토 대기:</span> <code>" +
      (counts.edges_proposed || 0) +
      "</code></div>" +
      "<div class='status-row'><span>개념 승인됨:</span> <code>" +
      (counts.nodes_verified || 0) +
      "</code></div>" +
      "<div class='status-row'><span>관계 승인됨:</span> <code>" +
      (counts.edges_verified || 0) +
      "</code></div>" +
      "<div class='status-row'><span>문서:</span> <code>" +
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

  // 승인/거부는 요청이 겹치면 이중 POST가 되므로 전역 1건씩만 처리
  var actPending = false;

  function setLastAction(text) {
    var el = $("#review-last-action");
    if (!el) return;
    el.textContent = text;
    el.classList.remove("hidden");
  }

  async function act(kind, id) {
    if (actPending) return;
    actPending = true;
    var path =
      kind === "approve" ? "/api/proposals/approve" : "/api/proposals/reject";
    var row = reviewRows.filter(function (r) { return r.id === id; })[0];
    var keepIdx = reviewCursor;
    try {
      await api(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: id, cascade: kind === "approve" }),
      });
      $("#review-error").classList.add("hidden");
      setLastAction(
        (kind === "approve" ? "승인됨: " : "거부됨: ") +
          ((row && row.label) || id.slice(0, 12))
      );
      await loadProposals(keepIdx);
    } catch (err) {
      var el = $("#review-error");
      el.textContent = friendlyError(err);
      el.classList.remove("hidden");
    } finally {
      actPending = false;
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
    // ③ 검토 탭이 보일 때만 동작 — 다른 탭에서 보이지 않는 행이
    // 조용히 승인/거부되는 사고 방지 (승인은 눈으로 보고 하는 행위)
    var reviewPanel = document.getElementById("tab-review");
    if (!reviewPanel || !reviewPanel.classList.contains("active")) return;
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

  async function loadProposals(keepIndex) {
    var tbody = $("#proposals-body");
    var empty = $("#review-empty");
    var err = $("#review-error");
    err.classList.add("hidden");
    empty.classList.add("hidden");
    showTableLoading(tbody, 8);
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
              " <span class='badge' role='img'" +
              " aria-label='추출기·크리틱 판단 불일치'>⚠</span>";
          }
          if (item.critic_rationale) {
            var rationale = String(item.critic_rationale);
            if (rationale.length > 80) rationale = rationale.slice(0, 80) + "…";
            critic += "<br><small class='muted'>" + escapeHtml(rationale) + "</small>";
          }
        }
        tr.innerHTML =
          "<td><input type='checkbox' class='row-check' data-id='" +
          escapeHtml(item.id || "") +
          "' aria-label='선택'></td>" +
          "<td>" +
          kindKo(item.kind) +
          "</td>" +
          "<td>" +
          escapeHtml(item.type_name || item.entity_type || item.relation_type || "") +
          "</td>" +
          "<td title='" + escapeHtml(item.id || "") + "'><strong>" +
          escapeHtml(itemLabel(item)) +
          "</strong></td>" +
          "<td>" +
          conf +
          "</td>" +
          "<td>" +
          critic +
          "</td>" +
          "<td title='" + escapeHtml(item.source_doc_id || "") + "'><small>" +
          escapeHtml(item.doc_title || (item.source_doc_id || "").slice(0, 10)) +
          "</small></td>" +
          "<td class='actions'></td>";
        var actions = tr.querySelector(".actions");
        var approveBtn = document.createElement("button");
        approveBtn.className = "btn btn-primary";
        approveBtn.textContent = "승인";
        approveBtn.addEventListener("click", function () {
          act("approve", item.id);
        });
        var rejectBtn = document.createElement("button");
        rejectBtn.className = "btn btn-danger";
        rejectBtn.textContent = "거부";
        rejectBtn.addEventListener("click", function () {
          act("reject", item.id);
        });
        actions.appendChild(approveBtn);
        actions.appendChild(document.createTextNode(" "));
        actions.appendChild(rejectBtn);
        if (item.kind === "node") {
          var focusBtn = document.createElement("button");
          focusBtn.className = "btn";
          focusBtn.textContent = "엔티티";
          focusBtn.title = "엔티티 중심 보기: 모든 멘션과 관계";
          focusBtn.addEventListener("click", function () {
            loadEntityPanel(item.id);
          });
          actions.appendChild(document.createTextNode(" "));
          actions.appendChild(focusBtn);
        }
        tbody.appendChild(tr);
        reviewRows.push({
          id: item.id, kind: item.kind, tr: tr, label: itemLabel(item),
        });
      });
      var idx = typeof keepIndex === "number" ? keepIndex : 0;
      if (reviewRows.length) focusRow(Math.min(idx, reviewRows.length - 1));
    } catch (e) {
      err.textContent = friendlyError(e);
      err.classList.remove("hidden");
      tbody.innerHTML = "";
    } finally {
      var checkAll = $("#review-check-all");
      if (checkAll) checkAll.checked = false;
      updateBulkButtons();
    }
  }

  /* -- 일괄 승인/거부: 체크박스 + 명시적 확인창 (자동 승인 없음) -- */

  function updateBulkButtons() {
    var n = document.querySelectorAll(
      "#proposals-body .row-check:checked"
    ).length;
    var ok = $("#bulk-approve-btn");
    var no = $("#bulk-reject-btn");
    if (!ok || !no) return;
    ok.disabled = n === 0;
    no.disabled = n === 0;
    ok.textContent = n ? "선택 승인 (" + n + ")" : "선택 승인";
    no.textContent = n ? "선택 거부 (" + n + ")" : "선택 거부";
  }

  async function bulkAct(kind) {
    var ids = [].map.call(
      document.querySelectorAll("#proposals-body .row-check:checked"),
      function (cb) { return cb.dataset.id; }
    );
    if (!ids.length) return;
    var question =
      kind === "approve"
        ? ids.length + "건을 모두 승인할까요? 승인된 항목은 팩에 들어갑니다."
        : ids.length + "건을 모두 거부할까요?";
    if (!window.confirm(question)) return;
    if (actPending) return;
    actPending = true;
    $("#bulk-approve-btn").disabled = true;
    $("#bulk-reject-btn").disabled = true;
    var path =
      kind === "approve" ? "/api/proposals/approve" : "/api/proposals/reject";
    var done = 0;
    try {
      for (var i = 0; i < ids.length; i++) {
        await api(path, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id: ids[i], cascade: kind === "approve" }),
        });
        done++;
      }
      $("#review-error").classList.add("hidden");
      setLastAction(
        (kind === "approve" ? "승인됨: " : "거부됨: ") + done + "건"
      );
    } catch (e) {
      var el = $("#review-error");
      el.textContent = done + "건 처리 후 오류: " + friendlyError(e);
      el.classList.remove("hidden");
    } finally {
      actPending = false;
      await loadProposals();
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
          (eng.available ? "사용 가능" : "미설치") +
          (eng.default_model ? " (기본 모델: " + eng.default_model + ")" : "");
        list.appendChild(li);
      });
      var cost = await api("/api/cost");
      $("#cost-pre").textContent = JSON.stringify(cost, null, 2);
    } catch (e) {
      list.innerHTML = "<li class='err-msg'>" + e.message + "</li>";
    }
  }

  async function loadSettings() {
    var box = $("#settings-result");
    try {
      var s = await api("/api/settings");
      $("#settings-default-engine").value = s.default_engine || "";
      $("#settings-default-model").value = s.default_model || "";
      $("#settings-data-dir").value = s.data_dir || "";
      $("#settings-packs-dir").value = s.packs_dir || "";
    } catch (e) {
      showResult(box, escapeHtml(friendlyError(e)), true);
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

  // Fixed-enum display labels (Korean). The raw value is kept for CSS class
  // and any logic; only the visible text is localized. Unknown values fall
  // back to the raw string so data never breaks.
  var STATUS_KO = {
    proposed: "검토 대기", verified: "승인됨", rejected: "거부됨",
    invalidated: "무효화됨", merged: "병합됨", dismissed: "기각",
    stale: "만료", running: "실행 중", complete: "완료", failed: "실패",
  };
  function statusKo(s) {
    var k = String(s || "").toLowerCase();
    return STATUS_KO[k] || s || "—";
  }
  function kindKo(k) {
    return k === "node" ? "개념" : k === "edge" ? "관계" : k || "";
  }

  function statusBadge(status) {
    var s = String(status || "").toLowerCase();
    return (
      "<span class='badge st-" +
      escapeHtml(s) +
      "'>" +
      escapeHtml(statusKo(s)) +
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

  // 첫 로드 중 빈 테이블이 "데이터 없음"으로 오독되지 않게 placeholder 행
  function showTableLoading(tbody, cols) {
    tbody.innerHTML =
      "<tr><td colspan='" + cols + "' class='muted'>불러오는 중…</td></tr>";
  }

  // fetch 계열 네트워크 오류를 사람이 읽을 수 있는 안내로 (최빈 장애: 서버 꺼짐)
  function friendlyError(e) {
    var m = String((e && e.message) || e);
    if (/failed to fetch|networkerror|load failed/i.test(m)) {
      return "서버에 연결할 수 없습니다. ontologylab 서버가 실행 중인지 확인한 뒤 다시 시도하세요.";
    }
    return m;
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
      else reject(new Error("복사 실패"));
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
    empty.classList.add("hidden");
    showTableLoading(tbody, 4);
    try {
      var data = await api("/api/documents");
      var docs = (data && data.documents) || [];
      tbody.innerHTML = docs
        .map(function (doc) {
          return (
            "<tr>" +
            "<td>" + escapeHtml(doc.source_kind || "") + "</td>" +
            "<td>" + escapeHtml(doc.title || "(제목 없음)") + "</td>" +
            "<td><code>" + escapeHtml(doc.source_uri || "") + "</code></td>" +
            "<td><small>" + escapeHtml(fmtTs(doc.fetched_ts)) + "</small></td>" +
            "</tr>"
          );
        })
        .join("");
      empty.classList.toggle("hidden", docs.length > 0);
    } catch (e) {
      tbody.innerHTML = "";
      err.textContent = friendlyError(e);
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
      showResult(box, "수집할 대상이 없습니다 — URL, 파일 경로, 또는 논문 검색어를 입력하세요.", true);
      return;
    }
    btn.disabled = true;
    showResult(box, "<span class='muted'>수집 중…</span>");
    try {
      var res = await apiSend("/api/collect", payload);
      if (res && res.ok) {
        showResult(
          box,
          "<span class='ok-msg'>수집 완료.</span> 전체 문서 <code>" +
            escapeHtml(String(res.documents != null ? res.documents : "?")) +
            "</code>개 · 새로 추가 <code>" +
            escapeHtml(String(res.created != null ? res.created : "?")) +
            "</code>개 · 중복 건너뜀 <code>" +
            escapeHtml(String(res.duplicates != null ? res.duplicates : "?")) +
            "</code>개 <button type='button' class='btn btn-primary'" +
            " data-goto='jobs'>다음: ② 추출 실행 →</button>"
        );
        await loadDocuments();
      } else {
        showResult(
          box,
          errorKindBadge(res && res.error_kind) +
            " " +
            escapeHtml((res && res.detail) || "수집 실패."),
          true
        );
      }
    } catch (e) {
      showResult(box, escapeHtml(friendlyError(e)), true);
    } finally {
      btn.disabled = false;
    }
  });

  /* -- Jobs -- */

  var jobsPollTimer = null;
  var selectedJobId = null;
  var extractEnginesLoaded = false;
  // running→complete/failed 전환 감지용 (완료 순간 안내를 띄우기 위해)
  var prevJobStatuses = {};

  async function populateEngineSelect() {
    var sel = $("#extract-engine");
    try {
      var engines = (await api("/api/engines")) || [];
      sel.innerHTML = "";
      engines.forEach(function (eng) {
        var opt = document.createElement("option");
        opt.value = eng.name;
        opt.textContent = eng.name + (eng.available ? "" : " (미설치)");
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
      "개념 +" + (t.nodes_new || 0) + "/~" + (t.nodes_merged || 0) +
      " · 관계 +" + (t.edges_new || 0) + "/~" + (t.edges_merged || 0)
    );
  }

  function renderJobDetail(job) {
    $("#job-detail").classList.remove("hidden");
    $("#job-detail-title").textContent =
      "작업 " + String(job.job_id || "").slice(0, 12) + " — " + statusKo(job.status);
    var lines = (job.progress || []).slice();
    if (job.error) lines.push("오류: " + job.error);
    /* textContent: progress lines are server/crawl-derived, never innerHTML */
    $("#job-progress").textContent = lines.length ? lines.join("\n") : "(진행 내역 없음)";
  }

  async function selectJob(jobId) {
    selectedJobId = jobId;
    try {
      var job = await api("/api/jobs/" + encodeURIComponent(jobId));
      if (job) renderJobDetail(job);
    } catch (e) {
      $("#job-detail").classList.remove("hidden");
      $("#job-detail-title").textContent = "작업 " + String(jobId).slice(0, 12);
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
    var jobsBody = $("#jobs-body");
    if (!jobsBody.children.length) showTableLoading(jobsBody, 6);
    try {
      var data = await api("/api/jobs");
      var jobs = (data && data.jobs) || [];
      renderJobs(jobs);
      // running → 종료 전환 감지: 완료 순간에 다음 단계 안내 + 검토 배지 갱신
      jobs.forEach(function (job) {
        var prev = prevJobStatuses[job.job_id];
        if (prev === "running" && job.status === "complete") {
          showResult(
            $("#extract-result"),
            "<span class='ok-msg'>추출 완료!</span> " +
              escapeHtml(totalsSummary(job.totals)) +
              " <button type='button' class='btn btn-primary'" +
              " data-goto='review'>③ 검토하러 가기 →</button>"
          );
          loadProposals();
        } else if (prev === "running" && job.status === "failed") {
          showResult(
            $("#extract-result"),
            statusBadge("failed") + " " + escapeHtml(job.error || "추출 실패"),
            true
          );
        }
        prevJobStatuses[job.job_id] = job.status;
      });
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
      if (jobsBody.querySelector("td[colspan]")) jobsBody.innerHTML = "";
      err.textContent = friendlyError(e);
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
    showResult(box, "<span class='muted'>추출 시작 중…</span>");
    try {
      var res = await apiSend("/api/extract", payload);
      if (res && res.job_id) {
        selectedJobId = res.job_id;
        showResult(
          box,
          "작업 시작 <code>" +
            escapeHtml(String(res.job_id).slice(0, 12)) +
            "</code> " +
            statusBadge(res.status || "running")
        );
        await loadJobs();
      } else {
        showResult(
          box,
          escapeHtml((res && (res.detail || res.error)) || "추출 시작 실패."),
          true
        );
      }
    } catch (e) {
      showResult(box, escapeHtml(friendlyError(e)), true);
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
    empty.classList.add("hidden");
    showTableLoading(tbody, 8);
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
      populateDiffSelects(packs);
    } catch (e) {
      tbody.innerHTML = "";
      err.textContent = friendlyError(e);
      err.classList.remove("hidden");
    }
  }

  /* -- Pack diff (W14): compare two built packs -- */

  function populateDiffSelects(packs) {
    var selA = $("#diff-pack-a");
    var selB = $("#diff-pack-b");
    var prevA = selA.value;
    var prevB = selB.value;
    var opts = (packs || [])
      .map(function (p) {
        var id = escapeHtml(p.pack_id || "");
        return "<option value='" + id + "'>" + id + "</option>";
      })
      .join("");
    selA.innerHTML = opts;
    selB.innerHTML = opts;
    if (prevA) selA.value = prevA;
    if (prevB) selB.value = prevB;
    /* default the two dropdowns to distinct packs so a diff is meaningful */
    if (!prevB && (packs || []).length > 1) selB.value = packs[1].pack_id;
  }

  function diffGroupHtml(title, group) {
    group = group || {};
    function labelRow(items, sign) {
      if (!items || !items.length) return "";
      var body = items
        .map(function (it) {
          var label = escapeHtml(it.label || it.id || "");
          if (it.fields && it.fields.length) {
            label +=
              " <small class='muted'>(" +
              it.fields.map(escapeHtml).join(", ") +
              ")</small>";
          }
          return label;
        })
        .join("<br>");
      return (
        "<div class='status-row'><span>" + sign + "</span><span>" + body +
        "</span></div>"
      );
    }
    var out = "<p><strong>" + escapeHtml(title) + "</strong></p>";
    var rows =
      labelRow(group.added, "+") +
      labelRow(group.removed, "−") +
      labelRow(group.changed, "~");
    return out + (rows || "<p class='muted'>변경 없음</p>");
  }

  function renderPackDiff(box, d) {
    if (d.identical) {
      showResult(
        box,
        "<span class='ok-msg'>두 팩이 동일합니다.</span> " +
          "<small class='muted'>콘텐츠 해시 동일 — 변경 없음.</small>"
      );
      return;
    }
    var s = d.summary || {};
    var html =
      "<p><strong>요약</strong> — 개념 +" +
      escapeHtml(String(s.nodes_added || 0)) + "/−" +
      escapeHtml(String(s.nodes_removed || 0)) + "/~" +
      escapeHtml(String(s.nodes_changed || 0)) + " · 관계 +" +
      escapeHtml(String(s.edges_added || 0)) + "/−" +
      escapeHtml(String(s.edges_removed || 0)) + "/~" +
      escapeHtml(String(s.edges_changed || 0)) + "</p>";
    var mc = d.manifest_changes || {};
    var mkeys = Object.keys(mc);
    if (mkeys.length) {
      html += "<p><strong>매니페스트 변경</strong></p>";
      mkeys.forEach(function (k) {
        html +=
          "<div class='status-row'><span><code>" + escapeHtml(k) +
          "</code></span><span>" + escapeHtml(String(mc[k].a)) + " → " +
          escapeHtml(String(mc[k].b)) + "</span></div>";
      });
    }
    html += diffGroupHtml("개념", d.nodes);
    html += diffGroupHtml("관계", d.edges);
    showResult(box, html);
  }

  $("#pack-diff-btn").addEventListener("click", async function () {
    var box = $("#pack-diff-result");
    var btn = $("#pack-diff-btn");
    var a = $("#diff-pack-a").value;
    var b = $("#diff-pack-b").value;
    if (!a || !b) {
      showResult(box, "비교할 팩 두 개를 고르세요.", true);
      return;
    }
    btn.disabled = true;
    showResult(box, "<span class='muted'>비교 중…</span>");
    try {
      var d = await api(
        "/api/packs/" + encodeURIComponent(a) + "/diff/" + encodeURIComponent(b)
      );
      renderPackDiff(box, d);
    } catch (e) {
      showResult(box, escapeHtml(friendlyError(e)), true);
    } finally {
      btn.disabled = false;
    }
  });

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
        flashButton(btn, "번들 완료!");
        window.location.href = res.download_url;
      } else {
        flashButton(btn, "실패");
        var errEl = $("#packs-error");
        errEl.textContent = (res && res.detail) || "mcpb 번들 생성 실패";
        errEl.classList.remove("hidden");
      }
    } catch (e) {
      flashButton(btn, "실패");
    }
  });

  $("#pack-build-form").addEventListener("submit", async function (ev) {
    ev.preventDefault();
    var box = $("#pack-build-result");
    var btn = $("#pack-build-submit");
    var name = $("#pack-name").value.trim();
    if (!name) {
      showResult(box, "팩 이름을 입력하세요.", true);
      return;
    }
    btn.disabled = true;
    showResult(box, "<span class='muted'>팩 빌드 중…</span>");
    try {
      var res = await apiSend("/api/packs/build", { name: name });
      if (res && res.ok) {
        var manifest = res.manifest || {};
        var counts = manifest.counts || {};
        showResult(
          box,
          "<span class='ok-msg'>팩 빌드 완료.</span> <code>" +
            escapeHtml(manifest.pack_id || name) +
            "</code> · 문서 <code>" +
            escapeHtml(String(counts.documents || 0)) +
            "</code> · 개념 <code>" +
            escapeHtml(String(counts.nodes_verified || 0)) +
            "</code> · 관계 <code>" +
            escapeHtml(String(counts.edges_verified || 0)) +
            "</code> <button type='button' class='btn btn-primary'" +
            " data-goto='mcp'>다음: ⑤ AI에 연결 →</button>"
        );
        $("#pack-name").value = "";
        await loadPacks();
        await loadMcp();
      } else {
        showResult(box, escapeHtml((res && res.detail) || "팩 빌드 실패."), true);
      }
    } catch (e) {
      showResult(box, escapeHtml(friendlyError(e)), true);
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
    empty.classList.add("hidden");
    cards.innerHTML = "<p class='muted'>불러오는 중…</p>";
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
          "<p class='muted'>문서 " + escapeHtml(String(counts.documents || 0)) +
          " · 개념 " + escapeHtml(String(counts.nodes_verified || 0)) +
          " · 관계 " + escapeHtml(String(counts.edges_verified || 0)) +
          "</p>";
        var pre = document.createElement("pre");
        pre.className = "code-block";
        pre.textContent = pack.serve_command || "—";
        card.appendChild(pre);
        var copyBtn = document.createElement("button");
        copyBtn.type = "button";
        copyBtn.className = "btn";
        copyBtn.textContent = "연결 설정 복사 (JSON)";
        copyBtn.addEventListener("click", function () {
          copyText(JSON.stringify(pack.stdio_config || {}, null, 2)).then(
            function () {
              flashButton(copyBtn, "복사됨!");
            },
            function () {
              flashButton(copyBtn, "복사 실패");
            }
          );
        });
        card.appendChild(copyBtn);
        cards.appendChild(card);
      });
      empty.classList.toggle("hidden", packs.length > 0);
    } catch (e) {
      err.textContent = friendlyError(e);
      err.classList.remove("hidden");
    }
  }

  /* -- Communities (W12): read-only; populated only from built packs -- */

  async function loadCommunities() {
    var tbody = $("#communities-body");
    var empty = $("#communities-empty");
    var err = $("#communities-error");
    err.classList.add("hidden");
    empty.classList.add("hidden");
    showTableLoading(tbody, 4);
    try {
      var data = await api("/api/communities");
      var communities = (data && data.communities) || [];
      tbody.innerHTML = "";
      communities.forEach(function (c) {
        var tr = document.createElement("tr");
        tr.innerHTML =
          "<td><code>" + escapeHtml(String(c.id || "").slice(0, 12)) + "</code></td>" +
          "<td>" + escapeHtml(String(c.member_count || 0)) + "</td>" +
          "<td>" + escapeHtml(c.summary || "—") + "</td>" +
          "<td><small class='muted'>" + escapeHtml(c.summary_method || "—") + "</small></td>";
        tr.addEventListener("click", function () {
          loadCommunityMembers(c.id);
        });
        tbody.appendChild(tr);
      });
      empty.classList.toggle("hidden", communities.length > 0);
    } catch (e) {
      tbody.innerHTML = "";
      err.textContent = friendlyError(e);
      err.classList.remove("hidden");
    }
  }

  async function loadCommunityMembers(communityId) {
    var panel = $("#community-detail");
    var body = $("#community-detail-body");
    var err = $("#community-detail-error");
    err.classList.add("hidden");
    panel.classList.remove("hidden");
    body.innerHTML = "<p class='muted'>불러오는 중…</p>";
    try {
      var data = await api(
        "/api/communities/" + encodeURIComponent(communityId)
      );
      var community = data.community || {};
      var members = data.members || [];
      $("#community-detail-title").textContent =
        "커뮤니티 " + String(communityId).slice(0, 12) +
        " (구성원 " + members.length + "개)";
      var html = "";
      if (community.summary) {
        html += "<p>" + escapeHtml(community.summary) + "</p>";
      }
      html +=
        "<div class='table-wrap'><table><thead><tr>" +
        "<th>이름</th><th>타입</th><th>상태</th>" +
        "</tr></thead><tbody>";
      members.forEach(function (m) {
        html +=
          "<tr><td>" + escapeHtml(m.name || "") + "</td>" +
          "<td>" + escapeHtml(m.entity_type || "") + "</td>" +
          "<td>" + statusBadge(m.status) + "</td></tr>";
      });
      html += "</tbody></table></div>";
      body.innerHTML = html;
    } catch (e) {
      body.innerHTML = "";
      err.textContent = friendlyError(e);
      err.classList.remove("hidden");
    }
  }

  /* -- Entity-centric review panel (W11) -- */

  async function entityAct(kind, id, entityId) {
    await act(kind, id); // reuses the per-item gate + queue refresh
    loadEntityPanel(entityId); // then re-render the panel in place
  }

  /* W13: invalidate a VERIFIED edge — history-preserving (tombstone), never
     a delete. Confirmed because it is a state change; the panel re-renders,
     dropping the now-non-current edge as the visible outcome. */
  async function invalidateEdge(edgeId, entityId) {
    if (
      !window.confirm(
        "이 승인된 관계를 무효화할까요?\n삭제되는 것이 아니라 " +
          "'더 이상 유효하지 않음'으로 표시되고 이력은 보존됩니다."
      )
    ) {
      return;
    }
    var err = $("#entity-panel-error");
    err.classList.add("hidden");
    try {
      var res = await apiSend(
        "/api/edges/" + encodeURIComponent(edgeId) + "/invalidate",
        { note: "invalidated via dashboard" }
      );
      if (res && res.ok === undefined && res.detail) throw new Error(res.detail);
      loadEntityPanel(entityId);
    } catch (e) {
      err.textContent = friendlyError(e);
      err.classList.remove("hidden");
    }
  }

  async function loadEntityPanel(entityId) {
    var panel = $("#entity-panel");
    var body = $("#entity-panel-body");
    var err = $("#entity-panel-error");
    err.classList.add("hidden");
    panel.classList.remove("hidden");
    body.innerHTML = "<p class='muted'>불러오는 중…</p>";
    var ctx;
    try {
      ctx = await api("/api/entity/" + encodeURIComponent(entityId) + "/review");
    } catch (e) {
      body.innerHTML = "";
      err.textContent = friendlyError(e);
      err.classList.remove("hidden");
      return;
    }
    var ent = ctx.entity || {};
    $("#entity-panel-title").textContent =
      "엔티티: " + (ent.name || entityId.slice(0, 12));

    var html = "";
    html +=
      "<p><strong>" + escapeHtml(ent.name || "") + "</strong> " +
      statusBadge(ent.status) +
      " <small class='muted'>" + escapeHtml(ent.entity_type || "") +
      " · 확신도 " +
      (ent.confidence == null ? "—" : Number(ent.confidence).toFixed(2)) +
      (ctx.critic
        ? " · 크리틱 " + Number(ctx.critic.score).toFixed(2) +
          (ctx.critic.rationale
            ? " (" + escapeHtml(ctx.critic.rationale) + ")"
            : "")
        : "") +
      "</small></p>";
    if ((ent.aliases || []).length) {
      html += "<p><small>별칭: " +
        ent.aliases.map(escapeHtml).join(", ") + "</small></p>";
    }

    var counts = ctx.counts || {};
    html += "<h4>멘션 (" + escapeHtml(String(counts.mentions || 0)) + ")</h4>";
    (ctx.mentions || []).forEach(function (m) {
      html +=
        "<div class='status-box'><small class='muted'>" +
        escapeHtml(m.doc_title || (m.source_doc_id || "").slice(0, 10)) +
        "</small><br><small>…" +
        escapeHtml(m.excerpt || "(스팬 없음)") + "…</small></div>";
    });

    html += "<h4>관계 (검토 대기 " +
      escapeHtml(String(counts.relations_proposed || 0)) + "건 · 승인 " +
      escapeHtml(String(counts.relations_verified || 0)) + "건)</h4>";
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
        " <small class='muted'>(상대: " +
        escapeHtml(statusKo((rel.other || {}).status)) + ")" +
        (rel.critic_score != null
          ? " 크리틱 " + Number(rel.critic_score).toFixed(2)
          : "") +
        "</small>";
      line.appendChild(label);
      if (rel.status === "proposed") {
        var actions = document.createElement("span");
        var ok = document.createElement("button");
        ok.className = "btn btn-primary";
        ok.textContent = "승인";
        ok.addEventListener("click", function () {
          entityAct("approve", rel.id, entityId);
        });
        var no = document.createElement("button");
        no.className = "btn btn-danger";
        no.textContent = "거부";
        no.addEventListener("click", function () {
          entityAct("reject", rel.id, entityId);
        });
        actions.appendChild(ok);
        actions.appendChild(document.createTextNode(" "));
        actions.appendChild(no);
        line.appendChild(actions);
      } else if (rel.status === "verified") {
        var vActions = document.createElement("span");
        var invalidate = document.createElement("button");
        invalidate.className = "btn btn-danger";
        invalidate.textContent = "무효화";
        invalidate.title =
          "승인을 취소하지 않고 '지금은 유효하지 않음'으로 표시합니다 (이력 보존)";
        invalidate.addEventListener("click", function () {
          invalidateEdge(rel.id, entityId);
        });
        vActions.appendChild(invalidate);
        line.appendChild(vActions);
      }
      body.appendChild(line);
    });

    if ((ctx.merge_candidates || []).length) {
      var h4 = document.createElement("h4");
      h4.textContent = "병합 후보 (" + ctx.merge_candidates.length + ")";
      body.appendChild(h4);
      ctx.merge_candidates.forEach(function (cand) {
        var line = document.createElement("div");
        line.className = "status-row";
        var span = document.createElement("span");
        span.innerHTML =
          "~ <strong>" + escapeHtml((cand.other || {}).name || "") +
          "</strong> " + statusBadge((cand.other || {}).status) +
          " <small class='muted'>점수 " +
          Number(cand.score || 0).toFixed(2) + " · " +
          (cand.reasons || []).map(escapeHtml).join(", ") +
          " — 병합 탭에서 결정</small>";
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
      "<br><small class='muted'>타입: " + escapeHtml(node.entity_type || "") +
      " · 확신도: " + (node.confidence == null ? "—" : Number(node.confidence).toFixed(2)) +
      " · 인용: " + escapeHtml(String(node.citation_count || 0)) + "</small>" +
      "<br><small>별칭: " + aliases + "</small>" +
      "<br><small>속성: " + props + "</small>" +
      "<br><small class='muted'><code>" + escapeHtml((node.id || "").slice(0, 12)) + "</code></small>" +
      "</td>"
    );
  }

  async function mergeAct(candidateId, targetId, sourceId) {
    if (actPending) return;
    actPending = true;
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
      err.textContent = friendlyError(e);
      err.classList.remove("hidden");
    } finally {
      actPending = false;
    }
  }

  async function mergeDismiss(candidateId) {
    if (actPending) return;
    actPending = true;
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
      err.textContent = friendlyError(e);
      err.classList.remove("hidden");
    } finally {
      actPending = false;
    }
  }

  async function loadMergeCandidates() {
    var cards = $("#merge-cards");
    var empty = $("#merge-empty");
    var err = $("#merge-error");
    err.classList.add("hidden");
    empty.classList.add("hidden");
    cards.innerHTML = "<p class='muted'>불러오는 중…</p>";
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
          "<strong>점수 " + escapeHtml(Number(item.score || 0).toFixed(2)) + "</strong>" +
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
        addBtn("◀ “" + (a.name || "A") + "” 유지", "btn-primary", function () {
          mergeAct(item.id, a.id, b.id);
        });
        addBtn("“" + (b.name || "B") + "” 유지 ▶", "btn-primary", function () {
          mergeAct(item.id, b.id, a.id);
        });
        addBtn("중복 아님", "", function () {
          mergeDismiss(item.id);
        });
        cards.appendChild(card);
      });
      empty.classList.toggle("hidden", items.length > 0);
    } catch (e) {
      err.textContent = friendlyError(e);
      err.classList.remove("hidden");
    }
  }

  $("#merge-scan-btn").addEventListener("click", async function () {
    var box = $("#merge-scan-result");
    var btn = $("#merge-scan-btn");
    btn.disabled = true;
    showResult(box, "<span class='muted'>스캔 중…</span>");
    try {
      var res = await apiSend("/api/merge/scan", {});
      if (res && res.ok) {
        showResult(
          box,
          "노드 <code>" + escapeHtml(String(res.nodes || 0)) +
            "</code>개 스캔 · 새 후보 <code>" +
            escapeHtml(String(res.candidates_new || 0)) + "</code>건"
        );
        await loadMergeCandidates();
      } else {
        showResult(box, escapeHtml((res && res.detail) || "스캔 실패."), true);
      }
    } catch (e) {
      showResult(box, escapeHtml(friendlyError(e)), true);
    } finally {
      btn.disabled = false;
    }
  });
  $("#merge-refresh-btn").addEventListener("click", loadMergeCandidates);

  /* -- Lazy loading + refresh wiring -- */

  var tabLoaders = {
    review: loadProposals,
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
    communities: loadCommunities,
    engines: loadEngines,
  };

  // 탭을 열 때마다 새로 로드 — 로컬 API라 비용이 없고, 다른 탭에서
  // 바꾼 데이터가 낡은 화면으로 남는 것(거짓 상태)을 막는다.
  // (settings는 입력 중 값이 GET으로 덮이지 않게 제외)
  function maybeLoadTab(name) {
    if (name === "home") return loadHome();
    if (tabLoaders[name]) tabLoaders[name]();
  }

  /* -- 홈(시작하기): 파이프라인 현황 + 다음 할 일 추천 ---------------- */

  function updateReviewBadge(counts) {
    var badge = $("#review-badge");
    if (!badge) return;
    var pending = counts
      ? (counts.nodes_proposed || 0) + (counts.edges_proposed || 0)
      : 0;
    badge.textContent = String(pending);
    badge.classList.toggle("hidden", pending === 0);
  }

  function setNextAction(text, gotoTab, btnLabel) {
    var box = $("#next-action");
    $("#next-action-text").textContent = text;
    var btn = $("#next-action-btn");
    btn.textContent = btnLabel;
    btn.dataset.goto = gotoTab;
    box.classList.remove("hidden");
  }

  var HOME_STATS = [
    "#stat-sources", "#stat-jobs", "#stat-review", "#stat-packs", "#stat-mcp",
  ];

  function setStat(sel, text, state) {
    var el = $(sel);
    if (!el) return;
    el.textContent = text;
    el.className = "step-stat" + (state ? " " + state : "");
  }

  async function loadHome() {
    var homeErr = $("#home-error");
    if (homeErr) homeErr.classList.add("hidden");
    try {
      var data = await api("/api/proposals?limit=1");
      var c = data.counts || {};
      var packs = [];
      try {
        packs = ((await api("/api/packs")) || {}).packs || [];
      } catch (_) { /* 팩 목록 실패는 홈 표시를 막지 않음 */ }
      var jobs = [];
      try {
        jobs = ((await api("/api/jobs")) || {}).jobs || [];
      } catch (_) { /* 작업 목록 실패도 홈 표시를 막지 않음 */ }
      var running = jobs.some(function (j) { return j.status === "running"; });

      var docs = c.documents || 0;
      var pending = (c.nodes_proposed || 0) + (c.edges_proposed || 0);
      var verified = (c.nodes_verified || 0) + (c.edges_verified || 0);

      updateReviewBadge(c);
      setStat("#stat-sources", "문서 " + docs + "개",
        docs ? "is-ok" : "is-todo");
      setStat(
        "#stat-jobs",
        running ? "추출 진행 중…"
          : jobs.length ? "실행 " + jobs.length + "회" : "아직 없음",
        running || !jobs.length ? "is-todo" : "is-ok"
      );
      setStat(
        "#stat-review",
        "대기 " + pending + "건 · 승인 " + verified + "건",
        pending > 0 ? "is-todo" : "is-ok"
      );
      setStat("#stat-packs", "팩 " + packs.length + "개",
        packs.length ? "is-ok" : "is-todo");
      setStat("#stat-mcp", packs.length ? "연결 가능" : "팩 필요",
        packs.length ? "is-ok" : "is-todo");

      // 다음 할 일 추천 (파이프라인 상태 기반)
      if (docs === 0) {
        setNextAction("먼저 문서를 넣으세요.", "sources", "① 수집으로 가기");
      } else if (pending > 0) {
        setNextAction(
          "AI 제안 " + pending + "건이 검토를 기다립니다.",
          "review", "③ 검토로 가기"
        );
      } else if (running) {
        setNextAction(
          "추출이 진행 중입니다. 끝나면 ③ 검토에 제안이 올라옵니다.",
          "jobs", "② 추출 상태 보기"
        );
      } else if (verified === 0 && jobs.length > 0) {
        setNextAction(
          "제안이 모두 처리됐습니다. 새 문서를 수집하거나 다시 추출해 보세요.",
          "sources", "① 수집으로 가기"
        );
      } else if (verified === 0) {
        setNextAction("문서에서 지식을 추출해 보세요.", "jobs", "② 추출로 가기");
      } else if (packs.length === 0) {
        setNextAction(
          "승인된 지식 " + verified + "건을 팩으로 내보내세요.",
          "packs", "④ 팩 빌드하러 가기"
        );
      } else {
        setNextAction(
          "팩이 준비됐습니다. 새로 승인한 내용이 있다면 ④에서 팩을 다시 빌드하고, " +
            "아니면 ⑤에서 AI에 연결하세요.",
          "mcp", "⑤ 연결로 가기"
        );
      }
    } catch (_) {
      $("#next-action").classList.add("hidden");
      if (homeErr) homeErr.classList.remove("hidden");
      HOME_STATS.forEach(function (sel) { setStat(sel, "확인 불가"); });
    }
  }

  // 홈 스텝 카드·"다음 단계" 링크·빈 상태 버튼의 탭 점프 (이벤트 위임)
  document.addEventListener("click", function (ev) {
    var target = ev.target.closest("[data-goto]");
    if (!target) return;
    var tab = target.dataset.goto;
    showTab(tab);
    maybeLoadTab(tab);
  });

  $("#sources-refresh-btn").addEventListener("click", loadDocuments);
  $("#jobs-refresh-btn").addEventListener("click", loadJobs);
  $("#packs-refresh-btn").addEventListener("click", loadPacks);
  $("#mcp-refresh-btn").addEventListener("click", loadMcp);
  $("#communities-refresh-btn").addEventListener("click", loadCommunities);

  /* 일괄 선택 배선 + 홈 오류 재시도 */
  $("#proposals-body").addEventListener("change", function (ev) {
    if (ev.target && ev.target.classList.contains("row-check")) {
      updateBulkButtons();
    }
  });
  $("#review-check-all").addEventListener("change", function () {
    var on = $("#review-check-all").checked;
    document
      .querySelectorAll("#proposals-body .row-check")
      .forEach(function (cb) { cb.checked = on; });
    updateBulkButtons();
  });
  $("#bulk-approve-btn").addEventListener("click", function () {
    bulkAct("approve");
  });
  $("#bulk-reject-btn").addEventListener("click", function () {
    bulkAct("reject");
  });
  $("#home-retry-btn").addEventListener("click", loadHome);

  /* Settings: editable form (GET populates, PUT saves) */
  $("#settings-form").addEventListener("submit", async function (ev) {
    ev.preventDefault();
    var box = $("#settings-result");
    var btn = $("#settings-save-btn");
    var model = $("#settings-default-model").value.trim();
    var dataDir = $("#settings-data-dir").value.trim();
    var packsDir = $("#settings-packs-dir").value.trim();
    var payload = {
      default_engine: $("#settings-default-engine").value.trim() || "mock",
      default_model: model || null,
      data_dir: dataDir || null,
      packs_dir: packsDir || null,
    };
    btn.disabled = true;
    try {
      await api("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      showResult(box, "<span class='ok-msg'>설정을 저장했습니다.</span>");
    } catch (e) {
      showResult(box, escapeHtml(friendlyError(e)), true);
    } finally {
      btn.disabled = false;
    }
  });

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
        opt.textContent = eng.name + (eng.available ? "" : " (미설치)");
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
    showResult(box, "<span class='muted'>크리틱 채점 중… (참고용 점수 — 승인은 항상 사용자 몫)</span>");
    try {
      var res = await apiSend("/api/critic/run", {
        engine: $("#critic-engine").value || "mock",
      });
      if (res && res.ok) {
        showResult(
          box,
          "크리틱 채점 완료 — 후보 <code>" + escapeHtml(String(res.candidates || 0)) +
            "</code>건 중 <code>" + escapeHtml(String(res.scored || 0)) +
            "</code>건 채점 · 불일치 <code>" +
            escapeHtml(String(res.disagreements || 0)) + "</code>건"
        );
        $("#review-order").value = "critic";
        reviewOrder = "critic";
        await loadProposals();
      } else {
        showResult(box, escapeHtml((res && res.detail) || "크리틱 실행 실패."), true);
      }
    } catch (e) {
      showResult(box, escapeHtml(friendlyError(e)), true);
    } finally {
      btn.disabled = false;
    }
  });
  populateCriticEngines();

  loadHome();
  loadProposals();
  loadEngines();
  loadSettings();
})();
