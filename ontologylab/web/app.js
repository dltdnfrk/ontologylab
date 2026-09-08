/* ontologylab local dashboard — review queue + engines/settings. Offline, no CDN. */

(function () {
  "use strict";

  function $(sel) {
    return document.querySelector(sel);
  }

  function ontologyLabelKo(value) {
    var localizer = window.ontologylabLocalizer;
    return localizer ? localizer.ontologyLabelKo(value) : value;
  }

  var uiUtils = window.ontologylabUiUtils;

  function plainDocumentTitle(value, fallback) {
    return uiUtils.plainText(value) || fallback || "(제목 없음)";
  }

  var chatSession = window.ontologylabCreateChatSession(window);
  var initialChatHtml = $("#chat-log").innerHTML;
  var retryActions = {};
  var retrySequence = 0;

  function requestConfirmation(options) {
    var dialog = $("#confirm-dialog");
    var submit = $("#confirm-dialog-submit");
    var reason = $("#confirm-dialog-reason");
    var reasonWrap = $("#confirm-dialog-reason-wrap");
    var reasonHelp = $("#confirm-dialog-reason-help");
    var reasonRequired = !!options.reasonRequired;
    var invoker = options.invoker || document.activeElement;
    $("#confirm-dialog-title").textContent = options.title;
    $("#confirm-dialog-message").textContent = options.message;
    reason.value = options.reason || "";
    reason.placeholder = options.reasonPlaceholder || "판단 근거를 기록합니다";
    reasonWrap.classList.toggle("hidden", !reasonRequired);
    reasonHelp.classList.toggle("hidden", !reasonRequired);
    submit.textContent = options.confirmLabel || "실행";
    submit.classList.toggle("btn-danger", options.danger !== false);
    submit.disabled = reasonRequired && !reason.value.trim();

    return new Promise(function (resolve) {
      function syncReason() {
        submit.disabled = reasonRequired && !reason.value.trim();
      }
      function finish() {
        reason.removeEventListener("input", syncReason);
        dialog.removeEventListener("close", finish);
        var accepted = dialog.returnValue === "confirm";
        if (invoker && invoker.focus) invoker.focus();
        resolve(accepted ? (reasonRequired ? reason.value.trim() : true) : false);
      }
      reason.addEventListener("input", syncReason);
      dialog.addEventListener("close", finish, { once: true });
      dialog.returnValue = "";
      dialog.showModal();
      if (reasonRequired) reason.focus();
    });
  }

  function showTab(name) {
    if (chatSession.startsNewOnEntry(
      document.body.dataset.activeTab || null,
      name
    )) {
      startNewChatSession();
    }
    document.querySelectorAll(".tab-btn").forEach(function (btn) {
      var on = btn.dataset.tab === name;
      btn.classList.toggle("active", on);
      btn.id = "tab-button-" + btn.dataset.tab;
      btn.setAttribute("aria-controls", "tab-" + btn.dataset.tab);
      btn.setAttribute("aria-selected", on ? "true" : "false");
      btn.setAttribute("tabindex", on ? "0" : "-1");
    });
    document.querySelectorAll(".tab-panel").forEach(function (panel) {
      var on = panel.dataset.tabPanel === name;
      panel.classList.toggle("active", on);
      panel.setAttribute("role", "tabpanel");
      panel.setAttribute("aria-labelledby", "tab-button-" + panel.dataset.tabPanel);
      panel.setAttribute("aria-hidden", on ? "false" : "true");
    });
    // 파이프라인 스트립의 현재 단계 마커 (CSS가 body[data-active-tab]로 그림)
    document.body.dataset.activeTab = name;
    // 탭을 옮기면 맨 위에서 시작한다. 스크롤 위치를 물려받으면 새 화면의
    // 제목이 뷰포트 밖으로 밀리고, 첫 문단이 sticky 파이프라인 바에
    // 가로로 잘린 채 나타난다.
    var main = document.querySelector("main");
    if (main) main.scrollTop = 0;
    renderStatusKeys(name);
    // 화면을 바꾼 것이 사람이 아닐 수 있다 — Aside의 AI가 몰면 사람은
    // 자기가 누르지 않은 이동을 보게 된다. 어디에 왔는지는 늘 같은
    // 자리에서 읽혀야 한다.
    var where = document.getElementById("statusbar-where");
    if (where) where.textContent = SCREEN_KO[name] || name;
  }

  /* 레일이 좁은 폭에서 아이콘만 남기므로, 화면 이름을 글자로 말하는 곳이
     상태바뿐인 경우가 있다. 여기 이름은 aria-label과 같은 말을 쓴다 —
     AI가 읽는 이름과 사람이 보는 이름이 다르면 둘의 대화가 어긋난다. */
  var SCREEN_KO = {
    home: "홈", sources: "리서치", review: "검토", packs: "팩",
    artifacts: "아티팩트", mcp: "연결", merge: "병합",
    communities: "커뮤니티", graph: "그래프",
    engines: "엔진", settings: "설정",
  };

  /* 화면마다 쓸 수 있는 키가 다르다. 검토에만 있는 단축키를 모든 탭에서
     보여주면 상태바가 장식이 되고, 장식은 아무도 읽지 않는다. */
  var TAB_KEYS = {
    review: [
      ["j / k", "이동"], ["a", "승인"], ["r", "거부"],
      ["u", "되돌리기"], ["d", "자세히"],
    ],
    graph: [["엔터 / 스페이스바", "선택"], ["이스케이프", "선택 해제"]],
  };

  function renderStatusKeys(tab) {
    var box = document.getElementById("statusbar-keys");
    if (!box) return;
    // ⌘K는 어느 화면에서나 열리므로 항상 첫 자리에 둔다. 팔레트는 발견되지
    // 않으면 없는 것과 같고, 발견될 자리는 여기뿐이다.
    var keys = [["⌘K", "찾기"]].concat(TAB_KEYS[tab] || []);
    box.innerHTML = keys
      .map(function (pair) {
        return (
          "<span><kbd>" + escapeHtml(pair[0]) + "</kbd>" +
          escapeHtml(pair[1]) + "</span>"
        );
      })
      .join("");
  }

  document.querySelectorAll(".tab-btn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      showTab(btn.dataset.tab);
      maybeLoadTab(btn.dataset.tab);
    });
  });
  $("nav.tabs").addEventListener("keydown", function (ev) {
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(ev.key)) return;
    var tabs = Array.from(document.querySelectorAll(".tab-btn"));
    var current = tabs.indexOf(document.activeElement);
    if (current < 0) return;
    var next = ev.key === "Home" ? 0
      : ev.key === "End" ? tabs.length - 1
      : (current + (ev.key === "ArrowDown" ? 1 : -1) + tabs.length) % tabs.length;
    tabs[next].focus();
    tabs[next].click();
    ev.preventDefault();
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
      // detail은 문자열일 수도, {field, detail}일 수도, 422면 [{loc, msg}]
      // 배열일 수도 있다. 그대로 Error에 넣으면 화면에 `[object Object]`
      // 만 남고 어느 칸이 틀렸는지는 사라진다.
      var err = new Error(uiUtils.errorText(body, res.statusText));
      err.httpStatus = res.status;
      err.errorKind = body && body.error_kind;
      err.responseBody = body;
      err.retryAfter = retryAfterSeconds(res);
      throw err;
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
    // 값이 위, 이름이 아래로 읽히도록 CSS가 뒤집는다(#counts-box). 그래서
    // 라벨 끝의 콜론은 빼고, 검토 대기 두 칸은 '제안됨' 상태색을 입도록
    // 표시한다 — 이 화면에서 실제로 행동해야 하는 숫자가 그 둘이다.
    // 한 대상에 이름 하나. 예전엔 같은 것을 개념·노드·엔티티 세 가지로
    // 불러서, 화면마다 다른 단어를 다시 배워야 했다.
    box.innerHTML =
      "<div class='status-row is-pending'><span>개념 대기</span> <code>" +
      (counts.nodes_proposed || 0) +
      "</code></div>" +
      "<div class='status-row is-pending'><span>관계 대기</span> <code>" +
      (counts.edges_proposed || 0) +
      "</code></div>" +
      "<div class='status-row'><span>개념 승인</span> <code>" +
      (counts.nodes_verified || 0) +
      "</code></div>" +
      "<div class='status-row'><span>관계 승인</span> <code>" +
      (counts.edges_verified || 0) +
      "</code></div>" +
      "<div class='status-row'><span>문서</span> <code>" +
      (counts.documents || 0) +
      "</code></div>";
  }

  /* 초 단위를 사람이 읽는 시간으로. 1072.9433485820264 → "17분 53초" */
  function fmtDuration(seconds) {
    var s = Math.round(Number(seconds) || 0);
    if (s < 60) return s + "초";
    var m = Math.floor(s / 60);
    if (m < 60) return m + "분 " + (s % 60) + "초";
    return Math.floor(m / 60) + "시간 " + (m % 60) + "분";
  }

  /* 엔진 탭의 비용 요약을 읽을 수 있는 줄글로 만든다(JSON 덤프 대체) */
  function formatCost(cost) {
    if (!cost) return "실행 기록이 없습니다.";
    var lines = [
      "엔진 호출  " + (cost.total_engine_calls || 0) + "회",
      "총 소요    " + fmtDuration(cost.total_elapsed_s),
    ];
    // API가 주는 키는 engine_calls / elapsed_s 다. 예전에 calls / elapsed 로
    // 읽어서 총계는 25회인데 엔진별 내역은 전부 0회로 나왔다.
    var per = cost.per_engine || {};
    Object.keys(per).forEach(function (name) {
      var v = per[name] || {};
      lines.push(
        "  · " + name + "  " + (v.engine_calls || 0) + "회 · " +
        fmtDuration(v.elapsed_s)
      );
    });
    return lines.join("\n");
  }

  function itemLabel(item) {
    if (item.label) return item.label;
    if (item.name) return item.name;
    if (item.src_node_id && item.dst_node_id) {
      return item.src_node_id.slice(0, 8) + " → " + item.dst_node_id.slice(0, 8);
    }
    return item.id ? item.id.slice(0, 12) : "—";
  }

  /* 검토 표의 '이름 / 엔드포인트' 셀. 관계는 서버가 준 src_label/dst_label로
     양끝과 화살표를 나눠 감싼다 — 화살표까지 같은 잉크로 굵게 찍으면
     "A → B"가 한 덩어리로 뭉쳐 어느 쪽이 출발인지 눈에 안 들어온다. */
  function itemLabelHtml(item) {
    if (item.kind === "edge" && item.src_label && item.dst_label) {
      return (
        "<strong class='ep'>" + escapeHtml(item.src_label) + "</strong>" +
        "<span class='ep-arrow' aria-hidden='true'>→</span>" +
        "<strong class='ep'>" + escapeHtml(item.dst_label) + "</strong>"
      );
    }
    return "<strong>" + escapeHtml(itemLabel(item)) + "</strong>";
  }

  // 승인/거부는 요청이 겹치면 이중 POST가 되므로 전역 1건씩만 처리
  var actPending = false;

  /* 마지막 결정 하나를 되돌릴 수 있게 들고 있는다. 'a'/'r'이 커서 키
     'j'/'k' 바로 옆이라 한 박자 이른 결정이 자주 나는데, 지금까지는
     그 결정이 그대로 확정이었다. */
  var lastDecision = null;   // {ids: [...], label}

  function setLastAction(text, decision) {
    var el = $("#review-last-action");
    lastDecision = decision || null;
    if (!el) return;
    el.textContent = "";
    el.appendChild(document.createTextNode(text));
    if (decision) {
      var undo = document.createElement("button");
      undo.type = "button";
      undo.className = "btn btn-link undo-btn";
      undo.textContent = "되돌리기 (u)";
      undo.addEventListener("click", undoLastDecision);
      el.appendChild(document.createTextNode(" "));
      el.appendChild(undo);
    }
    el.classList.remove("hidden");
  }

  async function undoLastDecision() {
    if (!lastDecision || actPending) return;
    var target = lastDecision;
    var confirmed = await requestConfirmation({
      title: "마지막 검토 결정을 되돌립니다",
      message: "승인 또는 거부 기록을 검토 대기 상태로 되돌립니다.",
      confirmLabel: "결정 되돌리기",
      danger: true,
      invoker: document.activeElement,
    });
    if (!confirmed) return;
    actPending = true;
    try {
      // 승인은 cascade로 관계와 양끝 개념을 함께 확정할 수 있으므로,
      // 되돌리기도 그 묶음 전체를 되돌려야 반쪽만 풀리지 않는다.
      // 역순으로 — 관계가 먼저 큐로 돌아가야 끝점 개념도 풀 수 있다
      // (승인된 관계가 매달린 개념은 서버가 되돌리기를 거부한다).
      var ids = target.ids.slice().reverse();
      for (var i = 0; i < ids.length; i++) {
        await api("/api/proposals/reopen", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id: ids[i] }),
        });
      }
      $("#review-error").classList.add("hidden");
      setLastAction(
        "되돌렸습니다: " + target.label +
          (ids.length > 1 ? " (" + ids.length + "건)" : ""),
        null
      );
      await loadProposals(reviewCursor);
    } catch (err) {
      // 승인된 관계가 매달린 개념은 되돌릴 수 없다 — 서버가 막는 이유를
      // 그대로 보여줘야 무엇을 먼저 해야 하는지 알 수 있다.
      var el = $("#review-error");
      el.textContent = friendlyError(err);
      el.classList.remove("hidden");
    } finally {
      actPending = false;
    }
  }

  async function act(kind, id) {
    if (actPending) return;
    var confirmed = await requestConfirmation({
      title: kind === "approve" ? "제안을 승인합니다" : "제안을 거부합니다",
      message: kind === "approve"
        ? "선택한 제안을 승인된 지식으로 기록합니다."
        : "선택한 제안을 거부 기록으로 남깁니다.",
      confirmLabel: kind === "approve" ? "제안 승인" : "제안 거부",
      danger: kind !== "approve",
      invoker: document.activeElement,
    });
    if (!confirmed) return;
    actPending = true;
    var path =
      kind === "approve" ? "/api/proposals/approve" : "/api/proposals/reject";
    var row = reviewRows.filter(function (r) { return r.id === id; })[0];
    var keepIdx = reviewCursor;
    try {
      var res = await api(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: id, cascade: kind === "approve" }),
      });
      $("#review-error").classList.add("hidden");
      var label = (row && row.label) || id.slice(0, 12);
      // 서버가 실제로 확정한 id 전부를 받는다 — 관계를 승인하면 cascade로
      // 끝점 개념까지 함께 확정되므로, 영수증도 되돌리기도 그 수를 알아야
      // 한다("1건 승인"이라 적고 3건을 바꾸면 안 된다).
      var touched = (res && (res.approved_ids || res.rejected_ids)) || [id];
      setLastAction(
        (kind === "approve" ? "승인됨: " : "거부됨: ") + label +
          (touched.length > 1 ? " (끝점 포함 " + touched.length + "건)" : ""),
        { ids: touched, label: label }
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
    renderEvidence(row.item);
  }

  /* 근거 패널 — 지금 커서가 놓인 항목이 '어느 문장에서 나왔는지'를 보여준다.
     서버가 스팬을 >>> <<< 로 감싸 주므로 그 자리를 <mark>로 바꿔 칠한다.
     추가 요청은 없다: 큐 응답에 이미 발췌가 실려 온다. */
  /* 증거 등급. 근거 문장 바로 옆이라야 판단에 쓰인다 — 논문이 심사를
     거쳤는지는 그 문장을 믿을지 정하는 첫 번째 재료다.

     `unknown` 을 숨기지 않는다. Crossref 는 약탈적 저널에도 DOI 를 주고
     bioRxiv preprint 가 나중에 Nature 에 실리기도 한다. 모르는 걸 모른다고
     해야 검토자가 직접 확인하러 갈 수 있다. */
  var GRADE_KO = {
    peer_reviewed: "동료심사",
    preprint: "preprint · 미심사",
    registration: "임상시험 등록 · 논문 아님",
    other: "저널 논문 아님",
    unknown: "심사 여부 모름",
  };

  function evidenceBadge(item) {
    var g = item.evidence_grade || "unknown";
    var src = item.doc_source ? " · " + escapeHtml(item.doc_source) : "";
    return "<span class='ev-grade g-" + escapeHtml(g) + "'>" +
      escapeHtml(GRADE_KO[g] || g) + "</span>" + src;
  }

  function renderEvidence(item) {
    var pane = $("#evidence-pane");
    if (!pane) return;
    if (!item) {
      pane.innerHTML =
        "<p class='muted evidence-idle'>검토할 항목이 없습니다.</p>";
      return;
    }
    var html =
      "<div class='ev-head'>" +
      "<span class='badge st-proposed'>" + kindKo(item.kind) + "</span>" +
      "<code>" + escapeHtml(ontologyLabelKo(item.type_name || "")) + "</code>" +
      "</div>" +
      "<h3 class='ev-label'>" + itemLabelHtml(item) + "</h3>";

    if (item.kind === "edge") {
      // 엔드포인트 상태를 미리 보여야 '끝점이 아직 승인 안 됨' 오류가
      // 눌러 보기 전에 예측된다 (approve는 양끝이 verified여야 통과).
      html +=
        "<p class='ev-endpoints muted'><small>" +
        escapeHtml(item.src_label || "?") + " → " +
        escapeHtml(item.dst_label || "?") +
        " · 승인하면 양끝 개념도 함께 승인됩니다</small></p>";
    }

    html += "<h4 class='ev-section'>근거</h4>";
    if (item.excerpt) {
      html +=
        "<blockquote class='ev-excerpt'>" + markExcerpt(item.excerpt) +
        "</blockquote>" +
        "<p class='ev-source muted'><small>" +
        evidenceBadge(item) + " " +
        escapeHtml(plainDocumentTitle(item.doc_title, item.source_doc_id || "")) +
        "</small></p>";
    } else if (!item.source_span) {
      // 스팬이 없는 개체가 생기는 길은 하나뿐이다: 모델이 관계의 끝점으로만
      // 이름을 대서 자리표시자로 만들어진 경우. 정상 개체 경로는 원문 대조에
      // 실패하면 거부하므로 스팬이 반드시 있다. 그러니 여기서 "기록되지
      // 않았어요"라고 말하면 장부 누락처럼 읽히는데, 실제로는 근거가 아예
      // 없다는 뜻이다 — 승인 여부를 가르는 사실을 완곡어법으로 가리는 셈.
      html +=
        "<p class='ev-noevidence ev-ungrounded'><small><strong>이 이름은 원문에 " +
        "나오지 않습니다.</strong> 모델이 관계를 설명하려고 덧붙인 이름이며 " +
        "근거 문장이 없습니다. 승인하면 출처 없는 지식이 됩니다.</small></p>";
    } else {
      html +=
        "<p class='muted ev-noevidence'><small>스팬은 기록돼 있는데 원문 " +
        "문장을 읽지 못했습니다. 원문 파일이 삭제되었을 수 있습니다.</small></p>";
    }

    // 발췌문은 근거 문장 하나만 보여준다. 그것으로 판정이 서는 경우가
    // 대부분이지만, 서지 않는 경우 — 저자가 다음 줄에서 부정하거나, 같은
    // 문단에서 열 개 제안이 한꺼번에 나온 경우 — 를 확인할 길이 지금까지
    // 없었다. 원문 전체를 옆에 연다.
    if (item.source_doc_id) {
      html +=
        "<p><button type='button' class='btn-link' data-open-doc='" +
        escapeHtml(item.source_doc_id) + "' data-open-item='" +
        escapeHtml(item.id || "") + "'>원문 전체 보기 →</button></p>";
    }

    html +=
      "<h4 class='ev-section'>판단 재료</h4>" +
      "<div class='ev-meta'>" +
      "<div><span>확신도</span><code>" +
      (item.confidence == null ? "—" : Number(item.confidence).toFixed(2)) +
      "</code></div>" +
      "<div><span>크리틱</span><code>" +
      (item.critic_score == null ? "—" : Number(item.critic_score).toFixed(2)) +
      "</code></div>" +
      "</div>";
    if (item.critic_disagreement) {
      html +=
        "<p class='ev-disagree'><small>추출기와 크리틱의 판단이 다릅니다. " +
        "근거를 다시 확인합니다.</small></p>";
    }
    if (item.critic_rationale) {
      html +=
        "<p class='muted ev-rationale'><small>" +
        escapeHtml(String(item.critic_rationale)) + "</small></p>";
    }
    // 계보는 접어 둔다. 대부분의 결정은 근거 문장만 보고 내려지고, 엔진·
    // 프롬프트 버전까지 늘 펼쳐 두면 정작 읽어야 할 발췌문이 아래로 밀린다.
    // 다만 "왜 이걸 믿는가"는 이 도구의 질문 자체이므로 한 번의 클릭 거리에
    // 둔다 — 지금까지는 sqlite를 열어야 닿았다.
    html +=
      "<details class='prov' data-kind='" + escapeHtml(item.kind || "") +
      "' data-id='" + escapeHtml(item.id || "") + "'>" +
      "<summary>계보 — 이 항목을 무엇이 언제 만들었나</summary>" +
      "<div class='prov-body muted'><small>여는 중…</small></div></details>";
    // 레지스트리 강화: 이름이 실제 개체인지 외부 DB에 확인해 보여준다.
    // 관계(엣지)는 강화 대상이 아니다. 조회 결과는 참고용일 뿐 — 승인은
    // 여전히 사람만 한다는 문구를 버튼 옆에 박아 둔다.
    if (item.kind === "node") {
      html +=
        "<div class='ev-enrich'>" +
        "<h4>레지스트리 확인</h4>" +
        "<button type='button' class='btn' data-enrich-id='" +
        escapeHtml(item.id || "") + "'>강화 실행</button>" +
        "<p class='muted'><small>UniProt·PubChem·ClinVar 조회 결과는 참고용입니다. " +
        "승인은 사용자가 수행합니다.</small></p>" +
        "<ul id='enrich-results' class='enrich-results'></ul>" +
        "</div>";
    }
    pane.innerHTML = html;
    if (item.kind === "node") loadStoredEnrichments(item.id);
  }

  /* 저장된 레지스트리 답을 강화 목록에 채운다. 강화 실행 버튼은 항상
     다시 조회하지만, 이미 조회된 답은 포커스만 바꿔도 보여야 한다. */
  async function loadStoredEnrichments(nodeId) {
    var box = $("#enrich-results");
    if (!box) return;
    try {
      var data = await api(
        "/api/enrichments/" + encodeURIComponent(nodeId)
      );
      renderEnrichments(box, data.enrichments || []);
    } catch (_) {
      /* 저장된 답이 없거나 서버가 응답하지 않으면 빈 목록이면 된다. */
    }
  }

  function renderEnrichments(box, rows) {
    box.innerHTML = rows.map(function (r) {
      var reg = REGISTRY_KO[r.registry] || r.registry;
      if (r.error) {
        return "<li class='enrich-row enrich-err'><strong>" +
          escapeHtml(reg) + "</strong> 조회 실패 (" +
          escapeHtml(ENRICH_ERR_KO[r.error] || r.error) + ")</li>";
      }
      return "<li class='enrich-row'><strong>" + escapeHtml(reg) + "</strong> " +
        "<code>" + escapeHtml(r.identifier) + "</code> " +
        escapeHtml(r.label) +
        (r.description ? " <small class='muted'>" +
          escapeHtml(r.description) + "</small>" : "") +
        "</li>";
    }).join("");
    if (!rows.length) {
      box.innerHTML = "<li>" + emptyState({
        icon: "add", title: UI_COPY_KO.emptyRegistry.title,
        description: UI_COPY_KO.emptyRegistry.description,
        action: { label: UI_COPY_KO.emptyRegistry.action, clickTarget: ".ev-enrich [data-enrich-id]" },
      }) + "</li>";
    }
  }

  async function runEnrichment(nodeId) {
    var box = $("#enrich-results");
    if (!box) return;
    box.innerHTML = "<li class='muted'><small>확인 중…</small></li>";
    try {
      var data = await api(
        "/api/review/" + encodeURIComponent(nodeId) + "/enrich",
        { method: "POST" }
      );
      renderEnrichments(box, data.enrichments || []);
    } catch (err) {
      box.innerHTML = "<li class='enrich-row enrich-err'>" +
        escapeHtml(friendlyError(err)) + "</li>";
    }
  }

  var REGISTRY_KO = {
    uniprot: "UniProt", pubchem: "PubChem", clinvar: "ClinVar",
  };
  var ENRICH_ERR_KO = {
    not_found: "일치 항목 없음", timeout: "시간 초과",
    offline: "네트워크 차단", refused: "거절됨",
    http_429: "요청 한도", shape: "응답 형식 오류",
  };

  function fmtProvenance(record) {
    var rows = [];
    var ex = record.extraction || {};
    var rv = record.review || {};
    var doc = record.document || {};
    rows.push(["추출 엔진", ex.model ? ex.engine + " · " + ex.model : ex.engine]);
    rows.push(["프롬프트", ex.prompt_version || "—"]);
    rows.push(["추출 시각", fmtRelative(ex.created_ts) + " (" + fmtTs(ex.created_ts) + ")"]);
    rows.push(["출처 문서", plainDocumentTitle(doc.title, doc.id || "—")]);
    rows.push(["문서 URI", doc.source_uri || "—"]);
    if (record.source_span) {
      rows.push(["문서 내 위치",
        record.source_span.start + "–" + record.source_span.end]);
    }
    rows.push([
      "승인",
      rv.verified_ts
        ? (rv.verified_by || "?") + " · " + fmtRelative(rv.verified_ts) +
          " (" + fmtTs(rv.verified_ts) + ")"
        : "아직 승인 안 됨",
    ]);
    if (record.critic) {
      rows.push([
        "크리틱 (참고)",
        Number(record.critic.score).toFixed(2) + " · " + (record.critic.engine || ""),
      ]);
    }
    return (
      "<dl class='prov-list'>" +
      rows
        .map(function (pair) {
          return "<dt>" + escapeHtml(pair[0]) + "</dt><dd>" +
            escapeHtml(String(pair[1] == null ? "—" : pair[1])) + "</dd>";
        })
        .join("") +
      "</dl>"
    );
  }

  // 펼칠 때 한 번만 가져온다 — 큐를 훑는 동안 모든 항목의 계보를 미리
  // 부르면 행마다 요청이 하나씩 붙는다.
  document.addEventListener("toggle", async function (ev) {
    var box = ev.target;
    if (!box.classList || !box.classList.contains("prov")) return;
    if (!box.open || box.dataset.loaded === "1") return;
    box.dataset.loaded = "1";
    var body = box.querySelector(".prov-body");
    try {
      var record = await api(
        "/api/provenance/" + encodeURIComponent(box.dataset.kind) +
        "/" + encodeURIComponent(box.dataset.id)
      );
      body.innerHTML = fmtProvenance(record);
      body.classList.remove("muted");
    } catch (e) {
      body.textContent = "계보를 불러오지 못했습니다: " + (e.message || e);
      box.dataset.loaded = "";   // 다시 열면 재시도
    }
  }, true);   // toggle은 버블링하지 않는다 — 캡처 단계에서 받아야 한다

  /* span_excerpt가 넣어 준 >>> <<< 마커를 <mark>로 바꾼다.
     이스케이프를 먼저 하고 마커를 치환해야 원문 속 꺾쇠가 태그로 새지 않는다. */
  function markExcerpt(excerpt) {
    return escapeHtml(String(excerpt))
      .replace(/&gt;&gt;&gt;/g, "<mark>")
      .replace(/&lt;&lt;&lt;/g, "</mark>");
  }

  /* ---------- 명령 팔레트 (⌘K) ----------------------------------------
     화면 이동과 개체 검색을 한 입력창에 합친다. 사용자는 "무엇을 찾는지"만
     치고, 그게 탭 이름인지 개체 이름인지는 여기서 판단한다.
     화면 목록은 즉시(로컬), 개체는 디바운스 뒤 /api/search로. */

  var PALETTE_TABS = [
    ["sources", "리서치", "주제 한 줄로 수집 + 추출"],
    ["review", "검토", "제안 승인 / 거부"],
    ["packs", "팩", "승인한 지식 묶기"],
    ["artifacts", "아티팩트", "문서와 팩 산출물 확인"],
    ["mcp", "연결", "Claude 연결 설정"],
    ["home", "홈", "현황판"],
    ["merge", "병합", "중복 개체 정리"],
    ["communities", "커뮤니티", "주요 테마"],
    ["graph", "그래프", "자유 탐색"],
    ["engines", "엔진", "AI 연결"],
    ["settings", "설정", "기본값 · 소스 키"],
  ];

  var paletteItems = [];      // [{kind, label, meta, run}]
  var paletteCursor = 0;
  var paletteSeq = 0;         // 늦게 온 응답이 새 입력을 덮어쓰지 못하게
  var paletteInvoker = null;
  var paletteBackground = [
    "header.app-header", "nav.tabs", "main", "#doc-panel",
    "#rail-resizer", "footer.statusbar",
  ];

  function setAppInert(on) {
    paletteBackground.forEach(function (selector) {
      var el = $(selector);
      if (el) el.inert = on;
    });
  }

  function paletteOpen() {
    var box = $("#palette");
    if (!box.classList.contains("hidden")) return;
    paletteInvoker = document.activeElement;
    setAppInert(true);
    box.classList.remove("hidden");
    var input = $("#palette-input");
    input.value = "";
    paletteRender(paletteLocal(""));
    input.focus();
  }

  function paletteClose() {
    var box = $("#palette");
    if (box.classList.contains("hidden")) return;
    box.classList.add("hidden");
    setAppInert(false);
    if (paletteInvoker && paletteInvoker.focus) paletteInvoker.focus();
    paletteInvoker = null;
  }

  function paletteLocal(query) {
    var q = query.trim().toLowerCase();
    return PALETTE_TABS.filter(function (row) {
      return !q || row[1].toLowerCase().indexOf(q) >= 0 ||
        row[0].indexOf(q) >= 0 || (row[2] || "").toLowerCase().indexOf(q) >= 0;
    }).map(function (row) {
      return {
        kind: "화면", label: row[1], meta: row[2], prose: true,
        run: function () { showTab(row[0]); maybeLoadTab(row[0]); },
      };
    });
  }

  function paletteRender(items) {
    paletteItems = items;
    paletteCursor = 0;
    var list = $("#palette-list");
    if (!items.length) {
      list.innerHTML = "<li class='palette-empty'>일치하는 화면이나 개체가 없습니다.</li>";
      return;
    }
    list.innerHTML = items
      .map(function (item, index) {
        return (
          "<li class='palette-item' role='option' data-index='" + index + "'" +
          " aria-selected='" + (index === 0 ? "true" : "false") + "'>" +
          "<span class='pi-kind'>" + escapeHtml(item.kind) + "</span>" +
          "<span class='pi-name" + (item.prose ? " pi-prose" : "") + "'>" +
          escapeHtml(item.label) + "</span>" +
          "<span class='pi-meta'>" + escapeHtml(item.meta || "") + "</span></li>"
        );
      })
      .join("");
  }

  function paletteMove(delta) {
    if (!paletteItems.length) return;
    var next = (paletteCursor + delta + paletteItems.length) % paletteItems.length;
    paletteCursor = next;
    $("#palette-list").querySelectorAll(".palette-item").forEach(function (el, i) {
      el.setAttribute("aria-selected", i === next ? "true" : "false");
      if (i === next && el.scrollIntoView) el.scrollIntoView({ block: "nearest" });
    });
  }

  function paletteRun(index) {
    var item = paletteItems[index];
    if (!item) return;
    paletteClose();
    item.run();
  }

  async function paletteSearch(query) {
    var local = paletteLocal(query);
    var q = query.trim();
    // 친 것이 화면 이름도 개체 이름도 아니면 그것은 리서치 주제다 —
    // 커맨드 라인의 마지막 해석. 실행까지 하지는 않는다(런은 비용이 있다):
    // 주제를 채워 리서치 화면에 세워 두고, 시작은 사람이 누른다.
    if (q.length >= 2) {
      local = local.concat([{
        kind: "리서치", label: "“" + q + "” 주제로 리서치", meta: "주제 채우기",
        prose: true,
        run: function () {
          showTab("sources");
          maybeLoadTab("sources");
          var topic = $("#research-topic");
          topic.value = q;
          topic.focus();
        },
      }]);
    }
    // 개체 검색은 두 글자부터. 한 글자로는 거의 모든 개체가 걸려서 화면
    // 항목이 결과 아래로 밀려나고, 팔레트가 이동 수단이 아니게 된다.
    if (q.length < 2) { paletteRender(local); return; }
    paletteRender(local);
    var seq = ++paletteSeq;
    try {
      var data = await api("/api/search?q=" + encodeURIComponent(q) + "&limit=8");
      if (seq !== paletteSeq) return;   // 더 최신 입력이 이미 렌더됨
      var hits = ((data && data.results) || []).map(function (row) {
        return {
          kind: row.status === "verified" ? "승인됨" : "제안",
          label: row.name,
          meta: ontologyLabelKo(row.entity_type || ""),
          run: function () {
            showTab("review");
            maybeLoadTab("review");
            loadEntityPanel(row.id);
          },
        };
      });
      if (seq === paletteSeq) paletteRender(local.concat(hits));
    } catch (_) {
      /* 검색 실패는 조용히 — 화면 이동은 계속 되어야 한다 */
    }
  }

  (function wirePalette() {
    var input = $("#palette-input");
    var debounce = null;
    input.addEventListener("input", function () {
      clearTimeout(debounce);
      var value = input.value;
      debounce = setTimeout(function () { paletteSearch(value); }, 120);
    });
    input.addEventListener("keydown", function (ev) {
      if (ev.key === "ArrowDown") { paletteMove(1); ev.preventDefault(); }
      else if (ev.key === "ArrowUp") { paletteMove(-1); ev.preventDefault(); }
      else if (ev.key === "Enter") { paletteRun(paletteCursor); ev.preventDefault(); }
      else if (ev.key === "Escape") { paletteClose(); ev.preventDefault(); }
    });
    $("#palette-list").addEventListener("click", function (ev) {
      var li = ev.target.closest ? ev.target.closest(".palette-item") : null;
      if (li) paletteRun(Number(li.dataset.index));
    });
    // 바깥 클릭으로 닫기 — 모달인데 빠져나갈 길이 esc뿐이면 갇힌 느낌이 든다
    $("#palette").addEventListener("mousedown", function (ev) {
      if (ev.target === $("#palette")) paletteClose();
    });
    $("#palette").addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") {
        paletteClose();
        ev.preventDefault();
        return;
      }
      if (ev.key !== "Tab") return;
      var focusable = Array.from($("#palette").querySelectorAll(
        'input, button, a[href], [tabindex]:not([tabindex="-1"])'
      )).filter(function (el) { return !el.disabled && !el.hidden; });
      if (!focusable.length) return;
      var first = focusable[0];
      var last = focusable[focusable.length - 1];
      if (ev.shiftKey && document.activeElement === first) {
        last.focus();
        ev.preventDefault();
      } else if (!ev.shiftKey && document.activeElement === last) {
        first.focus();
        ev.preventDefault();
      }
    });
    // 헤더의 커맨드 라인은 이 팔레트의 문손잡이다.
    var opener = $("#cmdk-open");
    if (opener) opener.addEventListener("click", paletteOpen);
  })();

  document.addEventListener("keydown", function (ev) {
    // ⌘K / Ctrl+K는 입력칸 안에서도 열려야 한다 — 주제를 치다가 다른 개체를
    // 확인하고 싶어지는 건 흔한 흐름이고, 그때 마우스를 잡게 하면 안 된다.
    if ((ev.metaKey || ev.ctrlKey) && (ev.key === "k" || ev.key === "K")) {
      paletteOpen();
      ev.preventDefault();
      return;
    }
    // never hijack typing in inputs
    var tag = (ev.target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select") return;
    // ② 검토 탭이 보일 때만 동작 — 다른 탭에서 보이지 않는 행이
    // 조용히 승인/거부되는 사고 방지 (승인은 눈으로 보고 하는 행위)
    var reviewPanel = document.getElementById("tab-review");
    if (!reviewPanel || !reviewPanel.classList.contains("active")) return;
    // 되돌리기는 큐가 비어 있어도 되어야 한다 — 마지막 한 건을 잘못
    // 승인해 큐가 0이 된 순간이 바로 가장 되돌리고 싶은 때다.
    if (ev.key === "u") { undoLastDecision(); ev.preventDefault(); return; }
    if (!reviewRows.length) return;
    if (ev.key === "j") {
      focusRow(reviewCursor + 1);
    }
    else if (ev.key === "k") focusRow(reviewCursor - 1);
    else if (ev.key === "a" && reviewCursor >= 0)
      act("approve", reviewRows[reviewCursor].id);
    else if (ev.key === "r" && reviewCursor >= 0)
      act("reject", reviewRows[reviewCursor].id);
    // 'd' = 자세히. 이전의 's'(건너뛰기)는 'j'와 완전히 같은 동작이라
    // 아무것도 미루지 않았다 — 있으나 마나 한 키라 없앴다.
    else if (ev.key === "d" && reviewCursor >= 0) {
      var focused = reviewRows[reviewCursor];
      if (focused.kind === "node") loadEntityPanel(focused.id);
      else return;
    } else return;
    ev.preventDefault();
  });

  async function loadProposals(keepIndex) {
    var generation = ++reviewLoadGeneration;
    var tbody = $("#proposals-body");
    var empty = $("#review-empty");
    var err = $("#review-error");
    err.classList.add("hidden");
    empty.classList.add("hidden");
    showTableLoading(tbody, 7);
    reviewRows = [];
    reviewCursor = -1;
    reviewNextCursor = null;
    reviewHasMore = false;
    reviewLoadingMore = false;
    reviewTotal = 0;
    reviewTriage = null;
    reviewCalibration = null;
    updateReviewProgress();
    try {
      var data = await api("/api/proposals?limit=" + reviewPageSize + "&order=" + reviewOrder);
      if (generation !== reviewLoadGeneration) return;
      var advisories = await loadProposalAdvisories();
      if (generation !== reviewLoadGeneration) return;
      renderCounts(data.counts);
      reviewTotal = ((data.counts || {}).nodes_proposed || 0) +
        ((data.counts || {}).edges_proposed || 0);
      reviewTriage = advisories.triage;
      reviewCalibration = advisories.calibration;
      tbody.innerHTML = "";
      var items = data.items || [];
      if (!items.length) {
        empty.classList.remove("hidden");
        updateReviewProgress();
        return;
      }
      empty.classList.add("hidden");
      reviewHasMore = !!data.has_more;
      reviewNextCursor = data.next_cursor || null;
      items.forEach(appendReviewRow);
      updateReviewProgress();
      var idx = typeof keepIndex === "number" ? keepIndex : 0;
      if (reviewRows.length) focusRow(Math.min(idx, reviewRows.length - 1));
      else renderEvidence(null);
    } catch (e) {
      if (generation !== reviewLoadGeneration) return;
      err.textContent = friendlyError(e);
      err.classList.remove("hidden");
      tbody.innerHTML = "";
    } finally {
      if (generation === reviewLoadGeneration) {
        var checkAll = $("#review-check-all");
        if (checkAll) checkAll.checked = false;
        updateBulkButtons();
        updateReviewProgress();
      }
    }
  }

  /* 검토 큐는 명시적인 페이지 단위로만 DOM에 붙인다. */
  var reviewPageSize = 50;
  var reviewNextCursor = null;
  var reviewHasMore = false;
  var reviewLoadingMore = false;
  var reviewTotal = 0;
  var reviewLoadGeneration = 0;

  function updateReviewProgress() {
    var progress = $("#review-progress");
    var more = $("#review-more-btn");
    if (progress) progress.textContent = "표시 " + reviewRows.length + " · 전체 " + reviewTotal;
    if (more) {
      more.classList.toggle("hidden", !reviewHasMore);
      more.disabled = reviewLoadingMore;
      more.textContent = reviewLoadingMore ? "불러오는 중…" : "더 보기";
    }
  }

  function calibratedConfidence(curve, raw) {
    if (!curve || raw == null || !curve.boundaries.length) return null;
    var result = curve.values[0];
    for (var i = 0; i < curve.boundaries.length; i++) {
      if (raw >= curve.boundaries[i]) result = curve.values[i];
      else break;
    }
    return result;
  }

  function safeToReviewLast(triage, score) {
    return !!(
      triage && triage.available && score != null && score > triage.threshold
    );
  }

  var reviewTriage = null;
  var reviewCalibration = null;

  async function loadProposalAdvisories() {
    // Fail-open both ways: endpoints missing/erroring and `available: false`
    // both leave the queue rendering exactly as before.
    var triage = null;
    var calibration = null;
    try {
      var tri = await api("/api/review/triage");
      triage = tri && tri.available ? tri : null;
    } catch (_) { triage = null; }
    try {
      var cal = await api("/api/review/calibration");
      calibration = cal && cal.available ? cal.curve : null;
    } catch (_) { calibration = null; }
    return { triage: triage, calibration: calibration };
  }

  function appendReviewRow(item) {
    var tbody = $("#proposals-body");
    var tr = document.createElement("tr");
    var conf =
      item.confidence == null ? "—" : Number(item.confidence).toFixed(2);
    /* 크리틱 점수·근거는 근거 패널(renderEvidence)에서 보여준다. 표에
       같이 두면 좁은 칸에 80자로 잘린 이유가 들어가 읽히지도 않고,
       결정 직전에 점수부터 눈에 들어와 앵커링을 만든다. */
    // 이름은 행마다 달라야 한다. 열세 행의 승인 버튼이 모두 "승인"이면
    // 조작하는 쪽은 위치로 고를 수밖에 없는데, 이 목록은 확신도 순이라
    // 한 건을 처리할 때마다 재정렬된다 — 위치로 고른 클릭은 방금 읽은
    // 그 항목이 아닐 수 있다. 이 앱의 약속이 "직접 승인한 것만
    // 지식이 된다"이므로, 무엇을 승인하는지 모르는 승인은 그 약속을
    // 조용히 깬다. Aside의 AI가 이 화면을 몰면 특히 그렇다.
    var label = itemLabel(item);
    var what = kindKo(item.kind) + " " + label;
    var cal = calibratedConfidence(reviewCalibration, item.confidence);
    var confText =
      conf + (cal == null ? "" : " <small class='muted'>→" + cal.toFixed(2) + "</small>");
    var safeBadge = safeToReviewLast(reviewTriage, item.critic_score)
      ? " <small class='muted' title='conformal: 거절권 항목과 통계적으로 구분됩니다'>· 안전권</small>"
      : "";
    tr.innerHTML =
      "<td><input type='checkbox' class='row-check' data-id='" +
      escapeHtml(item.id || "") +
      "' aria-label='" + escapeHtml("선택: " + what) + "'></td>" +
      "<td>" +
      kindKo(item.kind) +
      "</td>" +
      "<td title='" + escapeHtml(item.id || "") + "'>" +
      itemLabelHtml(item) +
      safeBadge +
      "</td>" +
      "<td class='conf-cell' style='--v:" +
      (item.confidence == null ? 0 : Number(item.confidence)) +
      "'>" + confText + "</td>" +
      "<td class='critic-cell'>" +
      (item.critic_score == null ? "—" : Number(item.critic_score).toFixed(2)) +
      "</td>" +
      "<td>" + timeHtml(item.created_ts) + "</td>" +
      "<td class='actions'></td>";
    // 행을 클릭하면 근거 패널이 그 항목으로 옮겨간다 (결정은 버튼/키로만)
    tr.addEventListener("click", function (ev) {
      if (ev.target.closest("button, input")) return;
      var at = reviewRows.findIndex(function (r) { return r.id === item.id; });
      if (at >= 0) focusRow(at);
    });
    var actions = tr.querySelector(".actions");
    var approveBtn = document.createElement("button");
    approveBtn.className = "btn btn-primary";
    approveBtn.textContent = "승인";
    // 보이는 글자는 짧게, 이름은 대상을 못 박아서. 승인은 되돌릴 수는
    // 있어도 되돌려야 하는 일이므로, 무엇에 대한 승인인지가 클릭하는
    // 쪽에 반드시 보여야 한다.
    approveBtn.setAttribute("aria-label", "승인: " + what);
    approveBtn.addEventListener("click", function () {
      act("approve", item.id);
    });
    var rejectBtn = document.createElement("button");
    rejectBtn.className = "btn btn-danger";
    rejectBtn.textContent = "거부";
    rejectBtn.setAttribute("aria-label", "거부: " + what);
    rejectBtn.addEventListener("click", function () {
      act("reject", item.id);
    });
    actions.appendChild(approveBtn);
    actions.appendChild(document.createTextNode(" "));
    actions.appendChild(rejectBtn);
    var focusBtn = document.createElement("button");
    focusBtn.className = "btn";
    focusBtn.textContent = "자세히";
    focusBtn.setAttribute("aria-label", "자세히: " + what);
    focusBtn.addEventListener("click", function () {
      if (item.kind === "node") loadEntityPanel(item.id);
      else {
        var at = reviewRows.findIndex(function (row) { return row.id === item.id; });
        if (at >= 0) focusRow(at);
      }
    });
    actions.appendChild(document.createTextNode(" "));
    actions.appendChild(focusBtn);
    tbody.appendChild(tr);
    // item 전체를 들고 있어야 근거 패널이 추가 요청 없이 즉시 그려진다
    reviewRows.push({
      id: item.id, kind: item.kind, tr: tr, label: itemLabel(item), item: item,
    });
  }

  async function reviewLoadMore() {
    if (reviewLoadingMore || !reviewHasMore || !reviewNextCursor) return;
    var generation = reviewLoadGeneration;
    reviewLoadingMore = true;
    updateReviewProgress();
    var tbody = $("#proposals-body");
    var loadingRow = document.createElement("tr");
    loadingRow.id = "review-loading-row";
    loadingRow.innerHTML =
      "<td colspan='7' class='muted'>더 불러오는 중…</td>";
    tbody.appendChild(loadingRow);
    try {
      var data = await api(
        "/api/proposals?limit=" + reviewPageSize + "&order=" + reviewOrder +
        "&cursor=" + encodeURIComponent(reviewNextCursor)
      );
      if (generation !== reviewLoadGeneration) return;
      renderCounts(data.counts);
      reviewHasMore = !!data.has_more;
      reviewNextCursor = data.next_cursor || null;
      (data.items || []).forEach(appendReviewRow);
    } catch (error) {
      if (generation !== reviewLoadGeneration) return;
      var err = $("#review-error");
      err.textContent = friendlyError(error);
      err.classList.remove("hidden");
    } finally {
      loadingRow.remove();
      if (generation === reviewLoadGeneration) {
        reviewLoadingMore = false;
        updateReviewProgress();
      }
    }
  }

  $("#review-more-btn").addEventListener("click", reviewLoadMore);

  /* -- 외부 레코드(주석) 큐 --------------------------------------------
     제안 큐와 나란히 두되 묻는 것이 다르다. 여기서 사람이 판정하는 건
     "이 사실이 참인가"가 아니라 "이게 이 노드의 레코드가 맞는가"다.
     그래서 행이 반드시 두 이름을 나란히 보여준다: 우리가 부르는 이름과
     리소스가 부르는 이름. 후자만 보여주면 확인할 수 없는 확인을
     요구하는 셈이다. */

  async function loadAnnotations() {
    var list = $("#annotations-list");
    var empty = $("#annotations-empty");
    if (!list) return;
    try {
      var body = (await api("/api/annotations")) || {};
      var items = body.annotations || [];
      var counts = body.counts || {};
      var badge = $("#annotations-count");
      if (badge) badge.textContent = String(counts.proposed || 0);
      // 조회 범위는 서버가 말한다. 화면에 종 이름을 적어 두면 상수를
      // 바꿔도 화면만 옛 종을 계속 주장한다.
      (body.organism ? [body.organism] : []).forEach(function (label) {
        ["#annotations-scope", "#annotations-scope-2"].forEach(function (sel) {
          var el = $(sel);
          if (el) el.textContent = label;
        });
      });

      list.innerHTML = items
        .map(function (a) {
          var facts = a.facts || {};
          var detail = facts.function || facts.summary || facts.gene_name || "";
          return (
            "<li class='ann-row' data-id='" + escapeHtml(a.id) + "'>" +
            "<div class='ann-match'>" +
            "<span class='ann-ours'>" + escapeHtml(a.node_name || "") + "</span>" +
            "<span class='ann-arrow' aria-hidden='true'>≟</span>" +
            "<span class='ann-theirs'>" + escapeHtml(a.matched_name || "") + "</span>" +
            "</div>" +
            "<div class='ann-meta'>" +
            "<code>" + escapeHtml(a.resource || "") + "</code> " +
            "<a href='" + escapeHtml(a.record_url || "#") + "' target='_blank'" +
            " rel='noopener noreferrer'>" + escapeHtml(a.external_id || "") + " ↗</a>" +
            (detail ? "<span class='ann-detail'>" + escapeHtml(detail.slice(0, 140)) +
                      "</span>" : "") +
            "</div>" +
            "<div class='ann-actions'>" +
            "<button type='button' class='btn btn-primary ann-accept'" +
            " aria-label='" + escapeHtml("맞는 레코드로 승인: " + (a.node_name || "") +
              " = " + (a.matched_name || "")) + "'>맞음</button> " +
            "<button type='button' class='btn btn-danger ann-reject'" +
            " aria-label='" + escapeHtml("다른 레코드로 거부: " + (a.node_name || "") +
              " ≠ " + (a.matched_name || "")) + "'>아님</button>" +
            "</div></li>"
          );
        })
        .join("");
      if (empty) empty.classList.toggle("hidden", items.length > 0);
    } catch (e) {
      list.innerHTML = "";
      showResult($("#enrich-result"), escapeHtml(friendlyError(e)), true);
    }
  }

  $("#annotations-list").addEventListener("click", async function (ev) {
    var accept = ev.target.closest(".ann-accept");
    var reject = ev.target.closest(".ann-reject");
    if (!accept && !reject) return;
    var row = ev.target.closest(".ann-row");
    if (!row) return;
    var confirmed = await requestConfirmation({
      title: accept ? "외부 레코드를 승인합니다" : "외부 레코드를 거부합니다",
      message: accept
        ? "이 외부 레코드를 선택한 개념의 일치 기록으로 반영합니다."
        : "이 외부 레코드를 일치하지 않는 기록으로 남깁니다.",
      confirmLabel: accept ? "레코드 승인" : "레코드 거부",
      danger: !accept,
      invoker: accept || reject,
    });
    if (!confirmed) return;
    try {
      var res = await apiSend(
        "/api/annotations/" + encodeURIComponent(row.dataset.id) + "/decide",
        { accept: !!accept }
      );
      if (res && res.ok) {
        await loadAnnotations();
        // 승인은 노드 속성을 바꾸므로 근거 패널의 개념 정보도 낡는다.
        loadProposals();
      } else {
        showResult($("#enrich-result"),
          errorKindBadge(res && res.error_kind) + " " +
          escapeHtml(uiUtils.errorText(res, "결정 실패.")), true);
      }
    } catch (e) {
      showResult($("#enrich-result"), escapeHtml(friendlyError(e)), true);
    }
  });

  $("#enrich-btn").addEventListener("click", async function () {
    var btn = $("#enrich-btn");
    var box = $("#enrich-result");
    btn.disabled = true;
    showResult(box, "<span class='muted'>승인된 개념을 외부 리소스에서 조회 중…</span>");
    try {
      var res = await apiSend("/api/enrich?limit=50", {});
      if (res && res.ok) {
        // 조회 결과를 결과가 아니라 *상황*으로 말한다. 숫자만 주면 매칭
        // 0건이 "고장"으로 읽히는데, 실제 원인은 대개 셋 중 하나이고
        // 셋의 대처가 전부 다르다 — 이름이 심볼이 아니거나, 사람 유전자가
        // 아니거나, 이미 결정해서 건너뛴 것이거나.
        var bits = ["개념 " + res.nodes_considered + "개"];
        if (res.lookups) bits.push("조회 " + res.lookups + "회");
        if (res.matched) bits.push("매칭 " + res.matched + " (새 제안 " + res.proposed + ")");
        if (res.skipped_decided) bits.push("이미 결정 " + res.skipped_decided);
        if (res.failures && res.failures.length) bits.push("실패 " + res.failures.length);

        var why = [];
        if (res.skipped_shape) {
          why.push("개념 이름 " + res.skipped_shape +
                   "건은 심볼 형식이 아니어서 조회하지 않았습니다 (공백 포함 또는 길이 초과)");
        }
        if (res.missed) {
          why.push(res.missed + "건은 조회했지만 <strong>" +
                   escapeHtml(res.organism || "") +
                   "</strong> 레코드에 해당 이름이 없습니다");
        }
        showResult(box,
          "<span class='" + (res.matched ? "ok-msg" : "muted") + "'>조회 완료.</span> " +
          bits.join(" · ") +
          (why.length
            ? "<br><small class='muted'>" + why.join(" · ") + ".</small>"
            : "") +
          (!res.matched && !res.lookups && !res.skipped_decided
            ? "<br><small class='muted'>승인된 개념이 없습니다. 먼저 제안을 승인합니다.</small>"
            : ""));
        await loadAnnotations();
      } else {
        showResult(box, errorKindBadge(res && res.error_kind) + " " +
          escapeHtml(uiUtils.errorText(res, "조회 실패.")), true);
      }
    } catch (e) {
      showResult(box, escapeHtml(friendlyError(e)), true);
    } finally {
      btn.disabled = false;
    }
  });

  /* -- 일괄 승인/거부: 체크박스 + 명시적 확인창 (자동 승인 없음) -- */

  function updateReasonControl(controlId, disabled, reason) {
    var wrapper = document.querySelector('[data-reason-control="' + controlId + '"]');
    if (!wrapper) return;
    wrapper.tabIndex = disabled ? 0 : -1;
    wrapper.classList.toggle("reason-disabled", disabled);
    var tip = wrapper.querySelector(".reason-tooltip");
    if (tip) tip.textContent = reason;
  }

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
    updateReasonControl("bulk-approve-btn", n === 0, UI_COPY_KO.selectionRequired);
    updateReasonControl("bulk-reject-btn", n === 0, UI_COPY_KO.selectionRequired);
  }

  async function bulkAct(kind) {
    var ids = [].map.call(
      document.querySelectorAll("#proposals-body .row-check:checked"),
      function (cb) { return cb.dataset.id; }
    );
    if (!ids.length) return;
    var question =
      kind === "approve"
        ? ids.length + "건을 모두 승인합니다. 승인한 항목은 팩에 포함됩니다."
        : ids.length + "건을 모두 거부 기록으로 남깁니다.";
    var confirmed = await requestConfirmation({
      title: kind === "approve" ? "선택 항목을 승인합니다" : "선택 항목을 거부합니다",
      message: question,
      confirmLabel: kind === "approve" ? "모두 승인" : "모두 거부",
      danger: kind !== "approve",
      invoker: kind === "approve" ? $("#bulk-approve-btn") : $("#bulk-reject-btn"),
    });
    if (!confirmed) return;
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
      // 가용성이 이 화면의 전부인데 이전에는 전부 같은 검은 글머리표라
      // 쓸 수 있는 엔진과 없는 엔진이 구분되지 않았다. 상태색을 입힌다.
      engines.forEach(function (eng) {
        var li = document.createElement("li");
        li.className = eng.available ? "is-available" : "is-missing";
        li.innerHTML =
          "<span class='eng-name'>" + escapeHtml(eng.name) + "</span>" +
          "<span class='eng-state'>" +
          (eng.available ? "사용 가능" : "미설치") + "</span>" +
          (eng.default_model
            ? "<span class='eng-model'>기본 모델 " +
              escapeHtml(eng.default_model) + "</span>"
            : "");
        list.appendChild(li);
      });
      // 날것 JSON을 그대로 뿌리면 total_elapsed_s가 유효숫자 16자리로
      // 나와(1072.9433485820264) 화면에서 가장 큰 덩어리가 가장 안 읽히는
      // 요소가 된다. 사람이 읽는 단위로 정리해서 보여준다.
      var cost = await api("/api/cost");
      $("#cost-pre").textContent = formatCost(cost);
    } catch (e) {
      list.innerHTML = "<li class='err-msg'>" + escapeHtml(e.message || String(e)) + "</li>";
    }
    // Providers render independently — its own try/catch keeps a provider
    // fetch failure from blanking the engine list (and vice versa).
    loadProviders();
  }

  /* ---- Providers (configurable API model backends) ---- */

  /* Bound env names are derived here from id + origin. The public API
     never returns a locator; do not read p.api_key_env. Custom origins
     include a 12-hex SHA-256 of scheme://host:port so a URL change cannot
     reuse the previous credential. */
  function officialProviderEnv(baseUrl) {
    try {
      var parsed = new URL(baseUrl);
      var host = (parsed.hostname || "").toLowerCase();
      var protocol = parsed.protocol;
      var port = parsed.port ? Number(parsed.port) : (protocol === "https:" ? 443 : 80);
      if (protocol === "https:" && port === 443) {
        if (host === "api.anthropic.com") return "ANTHROPIC_API_KEY";
        if (host === "api.openai.com") return "OPENAI_API_KEY";
        if (host === "openrouter.ai") return "OPENROUTER_API_KEY";
      }
    } catch (err) {}
    return "";
  }

  function normalizedProviderOrigin(baseUrl) {
    try {
      var parsed = new URL(baseUrl);
      var host = (parsed.hostname || "").toLowerCase();
      var protocol = parsed.protocol;
      if ((protocol !== "http:" && protocol !== "https:") || !host) return "";
      var port = parsed.port ? Number(parsed.port) : (protocol === "https:" ? 443 : 80);
      var scheme = protocol === "https:" ? "https" : "http";
      if (host.indexOf(":") !== -1) return scheme + "://[" + host + "]:" + port;
      return scheme + "://" + host + ":" + port;
    } catch (err) {
      return "";
    }
  }

  function sha256Hex12(text) {
    return crypto.subtle.digest("SHA-256", new TextEncoder().encode(text)).then(
      function (buf) {
        var bytes = new Uint8Array(buf);
        var hex = "";
        for (var i = 0; i < 6; i++) {
          var part = bytes[i].toString(16);
          hex += part.length < 2 ? "0" + part : part;
        }
        return hex.toUpperCase();
      }
    );
  }

  function dedicatedProviderEnv(id, baseUrl) {
    var official = officialProviderEnv(baseUrl);
    if (official) return Promise.resolve(official);
    var slug = String(id || "").toUpperCase().replace(/-/g, "_");
    var fingerprint = normalizedProviderOrigin(baseUrl) || String(baseUrl || "");
    return sha256Hex12(fingerprint).then(function (digest) {
      return "ONTOLOGYLAB_PROVIDER_" + slug + "_" + digest;
    });
  }

  function providerIssuanceUrl(baseUrl) {
    var official = officialProviderEnv(baseUrl);
    if (official === "ANTHROPIC_API_KEY") return "https://console.anthropic.com/settings/keys";
    if (official === "OPENAI_API_KEY") return "https://platform.openai.com/api-keys";
    if (official === "OPENROUTER_API_KEY") return "https://openrouter.ai/settings/keys";
    return "";
  }

  var providerPreviewSequence = 0;
  async function updateProviderCredentialMeta() {
    var id = $("#provider-id").value.trim();
    var baseUrl = $("#provider-base-url").value.trim();
    var seq = ++providerPreviewSequence;
    var env = id && baseUrl ? await dedicatedProviderEnv(id, baseUrl) : "—";
    if (seq !== providerPreviewSequence) return;
    $("#provider-env-preview").textContent = env;
    var host = $("#provider-credential-meta");
    var old = host.querySelector("a");
    if (old) old.remove();
    var issuance = providerIssuanceUrl(baseUrl);
    if (issuance) {
      var link = document.createElement("a");
      link.href = issuance;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = "공식 키 발급 페이지";
      host.appendChild(link);
    }
  }

  $("#provider-id").addEventListener("input", updateProviderCredentialMeta);
  $("#provider-base-url").addEventListener("input", updateProviderCredentialMeta);
  updateProviderCredentialMeta();

  /* Server strings (id/base_url/label/error) are user-entered;
     always escapeHtml before innerHTML. The registry never returns a key. */
  async function loadProviders() {
    var tbody = $("#providers-body");
    if (!tbody) return;
    var empty = $("#providers-empty");
    var errEl = $("#providers-error");
    errEl.classList.add("hidden");
    showTableLoading(tbody, 6);
    try {
      var res = await api("/api/providers");
      var providers = (res && res.providers) || [];
      tbody.innerHTML = "";
      if (!providers.length) {
        empty.innerHTML = emptyState({
          icon: "add", title: UI_COPY_KO.emptyProviders.title,
          description: UI_COPY_KO.emptyProviders.description,
          action: { label: UI_COPY_KO.emptyProviders.action, focusTarget: "provider-id" },
        });
        empty.classList.remove("hidden");
        return;
      }
      empty.classList.add("hidden");
      for (var i = 0; i < providers.length; i++) {
        var p = providers[i];
        var keyBadge = p.key_present
          ? "<span class='badge st-verified'>설정됨</span>"
          : "<span class='badge st-proposed'>미설정</span>";
        var tr = document.createElement("tr");
        tr.innerHTML =
          "<td><code>api:" + escapeHtml(p.id) + "</code></td>" +
          "<td>" + escapeHtml(p.kind) + "</td>" +
          "<td class='copyable-identifier'><code title='" +
          escapeHtml(p.base_url) + "'>" + escapeHtml(shortIdentifier(p.base_url)) +
          "</code> <button type='button' class='btn-link' data-copy-identifier='" +
          escapeHtml(p.base_url) + "' aria-label='전체 기본 주소 복사'>복사</button></td>" +
          "<td>" + keyBadge + "</td>" +
          "<td>" + escapeHtml(String((p.models || []).length)) + "</td>" +
          "<td class='actions'>" +
          "<button type='button' class='btn provider-test-btn' data-id='" +
          escapeHtml(p.id) +
          "'>테스트</button> " +
          "<button type='button' class='btn btn-danger provider-remove-btn' data-id='" +
          escapeHtml(p.id) +
          "'>삭제</button>" +
          "</td>";
        tbody.appendChild(tr);
      }
    } catch (e) {
      tbody.innerHTML = "";
      errEl.textContent = friendlyError(e);
      errEl.classList.remove("hidden");
    }
  }

  /* Test / remove buttons (delegated: rows re-render on refresh). */
  $("#providers-body").addEventListener("click", async function (ev) {
    if (!ev.target.closest) return;
    var box = $("#provider-result");
    var testBtn = ev.target.closest(".provider-test-btn");
    if (testBtn) {
      var id = testBtn.dataset.id;
      testBtn.disabled = true;
      showResult(box, "<span class='muted'>" + escapeHtml(id) + " 테스트 중…</span>");
      try {
        var res = await apiSend(
          "/api/providers/" + encodeURIComponent(id) + "/test", {}
        );
        if (res && res.ok) {
          showResult(
            box,
            "<span class='ok-msg'>연결되었습니다.</span> <code>api:" +
              escapeHtml(id) +
              "</code> · " +
              escapeHtml(String(res.latency_ms)) +
              "ms · 응답: <code>" +
              escapeHtml(res.sample || "") +
              "</code>"
          );
        } else {
          showResult(
            box,
            escapeHtml((res && res.error) || "테스트에 실패했습니다."),
            true
          );
        }
      } catch (e) {
        showResult(box, escapeHtml(friendlyError(e)), true);
      } finally {
        testBtn.disabled = false;
      }
      return;
    }
    var rmBtn = ev.target.closest(".provider-remove-btn");
    if (rmBtn) {
      var rid = rmBtn.dataset.id;
      var confirmed = await requestConfirmation({
        title: "API 프로바이더를 삭제합니다",
        message: "프로바이더 설정을 삭제합니다. 저장된 자격 증명은 별도 보관 정책을 따릅니다.",
        confirmLabel: "프로바이더 삭제",
        danger: true,
        invoker: rmBtn,
      });
      if (!confirmed) return;
      rmBtn.disabled = true;
      try {
        await api("/api/providers/" + encodeURIComponent(rid), {
          method: "DELETE",
        });
        showResult(
          box,
          "<span class='ok-msg'>삭제했습니다.</span> <code>api:" +
            escapeHtml(rid) +
            "</code>"
        );
        await loadProviders();
      } catch (e) {
        rmBtn.disabled = false;
        showResult(box, escapeHtml(friendlyError(e)), true);
      }
    }
  });

  $("#provider-form").addEventListener("submit", async function (ev) {
    ev.preventDefault();
    var box = $("#provider-result");
    var btn = $("#provider-submit");
    var payload = {
      id: $("#provider-id").value.trim(),
      kind: $("#provider-kind").value,
      base_url: $("#provider-base-url").value.trim(),
      api_key_env: "",
      models: splitList($("#provider-models").value),
      label: $("#provider-label").value.trim(),
    };
    payload.api_key_env = await dedicatedProviderEnv(payload.id, payload.base_url);
    if (!payload.id || !payload.base_url) {
      showResult(box, "ID와 기본 주소를 입력해야 합니다.", true);
      return;
    }
    btn.disabled = true;
    showResult(box, "<span class='muted'>추가 중…</span>");
    try {
      var res = await apiSend("/api/providers", payload);
      if (res && res.ok) {
        showResult(
          box,
          "<span class='ok-msg'>프로바이더를 등록했습니다.</span> <code>api:" +
            escapeHtml(payload.id) +
            "</code> 엔진으로 사용할 수 있습니다. 키는 환경변수 <code>" +
            escapeHtml(payload.api_key_env) +
            "</code>에 설정해야 합니다."
        );
        $("#provider-id").value = "";
        $("#provider-base-url").value = "";
        $("#provider-models").value = "";
        $("#provider-label").value = "";
        await loadProviders();
      } else {
        showResult(box, escapeHtml(uiUtils.errorText(res, "추가에 실패했습니다.")), true);
      }
    } catch (e) {
      showResult(box, escapeHtml(friendlyError(e)), true);
    } finally {
      btn.disabled = false;
    }
  });

  var settingsEngineCatalogue = [];

  function fillSettingsModels(savedModel) {
    var engineName = $("#settings-default-engine").value;
    var engine = settingsEngineCatalogue.filter(function (item) {
      return item.name === engineName;
    })[0];
    var models = (engine && engine.models) || [];
    var select = $("#settings-default-model");
    select.innerHTML = "";
    var automatic = document.createElement("option");
    automatic.value = "";
    automatic.textContent = engine && engine.default_model
      ? "엔진 기본값 (" + engine.default_model + ")" : "엔진 기본값";
    select.appendChild(automatic);
    models.forEach(function (model) {
      var option = document.createElement("option");
      option.value = model;
      option.textContent = model;
      select.appendChild(option);
    });
    if (savedModel && models.indexOf(savedModel) >= 0) select.value = savedModel;
  }

  async function populateSettingsEngineModelSelects(settings) {
    settingsEngineCatalogue = ((await api("/api/engines")) || []).filter(function (engine) {
      return engine.available;
    });
    var select = $("#settings-default-engine");
    select.innerHTML = "";
    settingsEngineCatalogue.forEach(function (engine) {
      var option = document.createElement("option");
      option.value = engine.name;
      option.textContent = engine.name;
      select.appendChild(option);
    });
    var warning = $("#settings-engine-warning");
    warning.textContent = "";
    warning.classList.add("hidden");
    var savedEngine = String(settings.default_engine || "");
    var malformedSavedValue = !settingsEngineCatalogue.some(function (engine) {
      return engine.name === savedEngine;
    });
    var fallback = settingsEngineCatalogue.filter(function (engine) {
      return engine.name !== "mock";
    })[0] || settingsEngineCatalogue[0];
    if (malformedSavedValue && fallback) savedEngine = fallback.name;
    select.value = savedEngine;
    var selected = settingsEngineCatalogue.filter(function (engine) {
      return engine.name === savedEngine;
    })[0];
    var savedModel = String(settings.default_model || "");
    var malformedSavedModel = !!savedModel && (!selected ||
      (selected.models || []).indexOf(savedModel) < 0);
    fillSettingsModels(malformedSavedValue || malformedSavedModel ? "" : savedModel);
    if (malformedSavedValue || malformedSavedModel) {
      warning.textContent = malformedSavedValue
        ? "저장된 엔진 값이 현재 카탈로그에 없어 사용 가능한 엔진으로 복구했습니다."
        : "저장된 모델 값이 선택한 엔진의 카탈로그에 없어 엔진 기본값으로 복구했습니다.";
      warning.classList.remove("hidden");
    }
  }

  $("#settings-default-engine").addEventListener("change", function () {
    fillSettingsModels("");
  });

  async function loadSettings() {
    var box = $("#settings-result");
    try {
      var s = await api("/api/settings");
      await populateSettingsEngineModelSelects(s);
      renderEditablePath("settings-data-dir", s.data_dir || "", "전체 데이터 디렉터리 복사");
      renderEditablePath("settings-packs-dir", s.packs_dir || "", "전체 팩 디렉터리 복사");
      renderEditablePath("settings-searxng-url", s.searxng_url || "", "전체 SearXNG 주소 복사");
    } catch (e) {
      showResult(box, escapeHtml(friendlyError(e)), true);
    }
    loadSchema();
    loadTerms();
  }

  function renderEditablePath(inputId, value, copyLabel) {
    var input = document.getElementById(inputId);
    var resting = document.getElementById(inputId + "-rest");
    if (!input || !resting) return;
    input.value = value;
    input.classList.add("hidden");
    resting.innerHTML = copyableMachineValueHtml(value, copyLabel) +
      " <button type='button' class='btn-link' data-reveal-path='" +
      escapeHtml(inputId) + "'>편집</button>";
    resting.classList.remove("hidden");
  }

  document.addEventListener("click", function (event) {
    var reveal = event.target.closest && event.target.closest("[data-reveal-path]");
    if (!reveal) return;
    var input = document.getElementById(reveal.dataset.revealPath);
    var resting = document.getElementById(reveal.dataset.revealPath + "-rest");
    if (!input || !resting) return;
    resting.classList.add("hidden");
    input.classList.remove("hidden");
    input.focus();
    input.select();
  });

  /* -- 온톨로지 --------------------------------------------------------------
     추출기는 여기 적힌 타입만 찾는다. 그래서 이 화면에서 결과를 가장 크게
     바꾸는 설정인데, 지금까지 바꿀 방법이 없어서 모든 코퍼스가 소프트웨어
     문서용 어휘(Concept/Component/Technique)로 돌았다 — p53 논문 151편
     포함해서. */

  async function loadSchema() {
    var head = $("#schema-active");
    if (!head) return;
    try {
      var d = await api("/api/schema");
    } catch (e) {
      head.textContent = friendlyError(e);
      return;
    }
    var active = d.active || {};
    head.innerHTML = "지금 <code>" + escapeHtml(active.schema_label || "?") +
      "</code> — 개체 " + (active.entity_types || []).length + "종, 관계 " +
      (active.relation_types || []).length + "종 " +
      "<span class='muted'><small>" +
      escapeHtml((active.entity_types || []).map(function (e) {
         return ontologyLabelKo(e.name);
      }).join(" · ")) + "</small></span>";

    $("#schema-presets").innerHTML = (d.presets || []).map(function (p) {
      var on = p.label === active.schema_label;
      var button = "<button type='button' class='btn' data-schema-preset='" +
        escapeHtml(p.name) + "'" + (on ? " disabled" : "") + ">" +
        escapeHtml(p.label) + (on ? " (사용 중)" : "") +
        " <span class='muted'>개체 " + p.entity_types + "</span></button>";
      if (!on) return button;
      return "<span class='reason-control reason-disabled' tabindex='0'" +
        " data-reason-control='schema-active' aria-describedby='schema-active-reason'>" +
        button + "<span id='schema-active-reason' class='reason-tooltip' role='tooltip'>" +
        "현재 사용 중인 온톨로지입니다</span></span>";
    }).join("");

    // 제안이 딸린 온톨로지는 누군가의 판정이 기대고 있는 것이라, 개수를
    // 같이 보여준다. 되돌릴 때 무엇을 되돌리는지 알아야 한다.
    var others = (d.installed || []).filter(function (s) { return !s.active; });
    $("#schema-installed").innerHTML = !others.length ? "" :
      "<p class='muted'><small>이전에 쓰던 것</small></p><ul class='doc-items'>" +
      others.map(function (s) {
        return "<li><button type='button' class='doc-item' " +
          "data-schema-activate='" + s.id + "'>" + escapeHtml(s.label) +
          "</button> <span class='muted'><small>제안 " + s.items +
          "건이 이 어휘로 판정됨</small></span></li>";
      }).join("") + "</ul>";
  }

  async function applySchema(payload, path) {
    var box = $("#schema-result");
    try {
      var r = await apiSend(path || "/api/schema", payload);
      if (r && r.ok) {
        showResult(box, "온톨로지를 <code>" +
          escapeHtml((r.active || {}).schema_label || "") +
          "</code>로 변경했습니다. 다음 추출부터 적용됩니다.", false);
      } else {
        showResult(box, escapeHtml(uiUtils.errorText(r, "변경하지 못했습니다.")), true);
      }
    } catch (e) {
      showResult(box, escapeHtml(friendlyError(e)), true);
    }
    loadSchema();
  }

  document.addEventListener("click", function (ev) {
    var p = ev.target.closest("[data-schema-preset]");
    if (p) { applySchema({ preset: p.dataset.schemaPreset }); return; }
    var a = ev.target.closest("[data-schema-activate]");
    if (a) {
      applySchema(null,
        "/api/schema/" + encodeURIComponent(a.dataset.schemaActivate) +
        "/activate");
    }
  });

  /* -- 온톨로지 용어 수명주기 ------------------------------------------------
     위의 패널은 어휘 한 벌을 통째로 갈아끼우고, 여기는 그 안의 한 용어를
     고쳐 쓴다. 둘은 다른 일이다: 이름을 바꿔도 UUID·IRI는 그대로라 기존
     사실이 계속 같은 것을 가리키고, 뜻이 바뀌면 그건 이름 변경이 아니라
     대체다.

     서버가 돌려주는 값은 전부 바깥글이다 — 정의·별칭·외부 권위명·식별자는
     외부 어휘에서 온 산문이고, 검토자·출처는 사람이 타이핑한 문자열이다.
     그래서 이 파일의 규칙을 그대로 따른다: innerHTML에 넣는 것은 반드시
     escapeHtml, 그 외는 textContent. */

  var termCache = [];        // 마지막으로 받은 용어 목록(서버 순서 그대로)
  var termSelectedId = "";   // 지금 패널이 보여주는 용어

  var TERM_LIFECYCLE_KO = {
    active: "사용 중",
    deprecated: "폐기됨",
    replaced: "대체됨",
  };
  var TERM_ALIAS_KIND_KO = {
    alternative: "다른 이름",
    hidden: "검색용",
    "former-preferred": "예전 대표 이름",
  };
  var TERM_PREDICATE_KO = {
    exact: "정확히 같음", close: "거의 같음", broader: "더 넓음",
    narrower: "더 좁음", related: "관련", advisory: "참고",
  };
  var TERM_LICENSE_KO = {
    allow: "본문 허용", "identifier-only": "식별자만", "deny-text": "본문 금지",
  };

  function termLifecycleBadge(lifecycle) {
    var cls = lifecycle === "active" ? "st-verified"
      : lifecycle === "replaced" ? "st-rejected" : "st-proposed";
    return "<span class='badge " + cls + "'>" +
      escapeHtml(TERM_LIFECYCLE_KO[lifecycle] || lifecycle) + "</span>";
  }

  /* 옵션은 문자열 조립이 아니라 노드로 만든다. 대표 이름은 외부에서 온
     값이고, <option> 안은 무해해 보이기 때문에 이스케이프를 빼먹기 가장 쉬운
     자리다 — textContent면 그 실수 자체가 불가능해진다. */
  function termOption(term, includeBlank) {
    var option = document.createElement("option");
    option.value = includeBlank ? "" : term.id;
    if (includeBlank) {
      option.textContent = "— 없음 —";
      return option;
    }
    var suffix = term.lifecycle === "active"
      ? "" : " (" + (TERM_LIFECYCLE_KO[term.lifecycle] || term.lifecycle) + ")";
    option.textContent = term.preferred_label + " [" + term.language + "]" +
      suffix;
    return option;
  }

  function fillTermPickers() {
    var picker = $("#term-select");
    var replacement = $("#term-lifecycle-replacement");
    if (!picker || !replacement) return;
    picker.innerHTML = "";
    replacement.innerHTML = "";
    replacement.appendChild(termOption(null, true));
    termCache.forEach(function (term) {
      picker.appendChild(termOption(term, false));
      if (term.id !== termSelectedId) {
        replacement.appendChild(termOption(term, false));
      }
    });
    if (termSelectedId) picker.value = termSelectedId;
  }

  function termMetaLine(term) {
    var iri = String(term.iri || "");
    return "<small class='muted'>검토자 " + escapeHtml(term.reviewer) +
      " · 출처 " + escapeHtml(term.provenance) +
      " · IRI <code title='" + escapeHtml(iri) + "'>" +
      escapeHtml(shortIdentifier(term.iri)) + "</code>" +
      (iri ? " <button type='button' class='btn-link' data-copy-identifier='" +
        escapeHtml(iri) + "' aria-label='전체 IRI 복사'>복사</button>" : "") +
      "</small>";
  }

  function termAliasRow(alias) {
    return "<li><strong>" + escapeHtml(alias.label) + "</strong> " +
      "<small class='muted'>[" + escapeHtml(alias.language) + "] · " +
      escapeHtml(TERM_ALIAS_KIND_KO[alias.alias_kind] || alias.alias_kind) +
      " · 검토자 " + escapeHtml(alias.reviewer) + "</small></li>";
  }

  function termXrefRow(xref) {
    return "<li>" + termLifecycleBadge(xref.lifecycle) + " <strong>" +
      escapeHtml(xref.authority) + "</strong> <code>" +
      escapeHtml(xref.external_id) + "</code> " +
      "<small class='muted'>" +
      escapeHtml(TERM_PREDICATE_KO[xref.mapping_predicate] ||
                 xref.mapping_predicate) +
      " · " + escapeHtml(TERM_LICENSE_KO[xref.license_gate] ||
                          xref.license_gate) +
      " · 출처 " + escapeHtml(xref.source_uri) +
      " · 검토자 " + escapeHtml(xref.reviewer) +
      (xref.change_reason
        ? " · 사유 " + escapeHtml(xref.change_reason) : "") +
      "</small></li>";
  }

  var BUILTIN_DEFINITION_KO = {
    "An abstract idea, algorithm, pattern, or principle.":
      "알고리즘, 패턴, 원칙을 포함하는 추상적 개념입니다.",
    "A concrete software artifact: module, service, library, tool, API.":
      "모듈, 서비스, 라이브러리, 도구, API와 같은 구체적인 소프트웨어 산출물입니다.",
    "A method, procedure, or practice applied to build or operate systems.":
      "시스템을 구축하거나 운영할 때 적용하는 방법, 절차, 실무 방식입니다.",
  };

  function builtinDefinitionCopy(term) {
    var original = String(term && term.definition || "");
    if (term && (term.reviewer === "ontologylab-bundled-schema" ||
                 term.reviewer === "ontologylab-schema-migration")) {
      return {
        primary: BUILTIN_DEFINITION_KO[original] ||
          "번들 온톨로지에 포함된 기본 용어입니다.",
        original: original,
      };
    }
    return { primary: original, original: "" };
  }

  function renderTermDetail(payload) {
    var box = $("#term-detail");
    if (!box) return;
    if (!payload) { box.textContent = "용어를 선택하면 세부 정보가 표시됩니다."; return; }
    var term = payload.term || {};
    var html = "<p class='term-headline'><strong>" +
      escapeHtml(term.preferred_label) + "</strong> " +
      "<small class='muted'>[" + escapeHtml(term.language) + "]</small> " +
      termLifecycleBadge(term.lifecycle) + "</p>";
    var definitionCopy = builtinDefinitionCopy(term);
    html += "<p class='term-definition'" +
      (definitionCopy.original
        ? " title='원문: " + escapeHtml(definitionCopy.original) + "'" : "") +
      ">" + escapeHtml(definitionCopy.primary) + "</p>";
    if (term.change_reason) {
      html += "<p class='term-reason'><small>변경 사유: " +
        escapeHtml(term.change_reason) + "</small></p>";
    }
    if (payload.replacement) {
      html += "<p class='term-reason'><small>대체 용어: <strong>" +
        escapeHtml(payload.replacement.preferred_label) + "</strong> " +
        "<code>" + escapeHtml(payload.replacement.iri) +
        "</code></small></p>";
    }
    html += "<p>" + termMetaLine(term) + "</p>";
    var aliases = payload.aliases || [];
    html += "<h4>별칭 (" + escapeHtml(String(aliases.length)) + ")</h4>";
    html += aliases.length
      ? "<ul class='term-list'>" + aliases.map(termAliasRow).join("") + "</ul>"
      : emptyState({
          icon: "add", title: UI_COPY_KO.emptyAliases.title,
          description: UI_COPY_KO.emptyAliases.description,
          action: { label: UI_COPY_KO.emptyAliases.action, focusTarget: "term-alias-label" },
        });
    var xrefs = payload.xrefs || [];
    html += "<h4>외부 매핑 (" + escapeHtml(String(xrefs.length)) + ")</h4>";
    html += xrefs.length
      ? "<ul class='term-list'>" + xrefs.map(termXrefRow).join("") + "</ul>"
      : emptyState({
          icon: "add", title: UI_COPY_KO.emptyXrefs.title,
          description: UI_COPY_KO.emptyXrefs.description,
          action: { label: UI_COPY_KO.emptyXrefs.action, goto: "review" },
        });
    box.innerHTML = html;
  }

  function sanitizeErrorDetail(value) {
    var text = String(value == null ? "" : value)
      .replace(/[\u0000-\u001f\u007f]/g, " ")
      .replace(/(bearer|api[_ -]?key|token|secret)(\s*[:=]\s*)\S+/gi, "$1$2[가림]")
      .replace(/([?&](?:key|token|secret)=)[^&\s]+/gi, "$1[가림]")
      .replace(/\/(?:Users|home)\/[^\s/]+/g, "/[사용자]")
      .replace(/failed to fetch/gi, "네트워크 요청 실패")
      .replace(/\bunknown\b/gi, "세부 정보 없음")
      .replace(/\s+/g, " ")
      .trim();
    return text.slice(0, 2000) || "세부 정보가 제공되지 않았습니다.";
  }

  function classifyError(error, fallback) {
    var status = Number(error && (error.httpStatus || error.http_status)) || 0;
    var kind = String(error && (error.errorKind || error.error_kind) || "");
    var raw = error && error.responseBody
      ? uiUtils.errorText(error.responseBody, fallback)
      : String(error && (error.message || error.detail) || fallback || "");
    var network = /failed to fetch|networkerror|load failed|네트워크 요청 실패/i.test(raw);
    var variant = network ? "network"
      : status === 401 ? "auth"
      : status === 403 ? "forbidden"
      : status === 503 || kind === "busy" ? "busy"
      : status >= 500 ? "server"
      : "request";
    var messages = {
      network: "서버에 연결할 수 없습니다.",
      auth: "인증 세션이 만료되었습니다.",
      forbidden: "이 작업을 실행할 권한이 없습니다.",
      server: "서버에서 요청을 처리하지 못했습니다.",
      busy: "다른 작업이 진행 중이어서 지금 실행할 수 없습니다.",
      request: fallback || "요청을 처리하지 못했습니다.",
    };
    var help = {
      network: "서버 실행 상태를 확인한 뒤 다시 시도합니다.",
      auth: "화면을 새로고침하여 로컬 인증 세션을 다시 만듭니다.",
      forbidden: "현재 데이터 경로와 접근 권한을 확인합니다.",
      server: "잠시 후 다시 시도합니다. 같은 문제가 계속되면 세부 정보를 복사해 확인합니다.",
      busy: "진행 중인 작업이 끝난 뒤 다시 시도합니다.",
      request: "입력값을 확인한 뒤 다시 실행합니다.",
    };
    return {
      variant: variant,
      status: status,
      message: messages[variant],
      help: help[variant],
      detail: sanitizeErrorDetail((status ? "HTTP " + status + " · " : "") + raw),
    };
  }

  function renderErrorSurface(el, error, options) {
    options = options || {};
    var typed = classifyError(error, options.fallback);
    var key = typed.variant + "|" + typed.status + "|" + typed.detail;
    var panel = el.closest ? el.closest(".tab-panel") : null;
    var duplicate = panel && panel.querySelector(
      '.error-surface[data-error-key="' + CSS.escape(key) + '"]'
    );
    if (duplicate && !el.contains(duplicate)) {
      el.classList.add("hidden");
      return duplicate;
    }
    var surface = $("#error-surface-template").content.firstElementChild.cloneNode(true);
    surface.dataset.errorKey = key;
    surface.dataset.variant = typed.variant;
    surface.querySelector(".error-surface-message").textContent = typed.message;
    surface.querySelector(".error-help").textContent = typed.help;
    surface.querySelector(".error-detail pre").textContent = typed.detail;
    surface.querySelector(".error-copy").dataset.copy = "detail";
    var retry = surface.querySelector(".error-retry");
    retry.dataset.pendingLabel = "다시 시도 중…";
    retry.textContent = typed.variant === "auth" ? "화면 새로고침" : "다시 시도";
    var retryId = "retry-" + (++retrySequence);
    retry.dataset.retry = retryId;
    retryActions[retryId] = options.retry || (typed.variant === "auth"
      ? function () { window.location.reload(); }
      : null);
    retry.classList.toggle("hidden", !retryActions[retryId]);
    el.textContent = "";
    el.appendChild(surface);
    el.classList.add("result-error");
    el.classList.remove("hidden");
    return surface;
  }

  /* 용어 화면도 공용 오류 정규화를 쓴다. */
  function termErrorText(res) {
    return uiUtils.errorText(res);
  }

  /* 재시도 안내를 메시지 뒤에 붙인다. */
  function retryHint(e) {
    var s = e && e.retryAfter;
    if (s === undefined || s === null) return "";
    return " — " + s + "초 뒤에 다시 시도합니다.";
  }

  async function loadTerms(selectId) {
    var box = $("#term-detail");
    if (!box) return;
    try {
      var listed = await api("/api/ontology/terms");
      termCache = listed.terms || [];
    } catch (e) {
      box.textContent = friendlyError(e);
      return;
    }
    if (!termCache.length) {
      termSelectedId = "";
      fillTermPickers();
      box.textContent = "등록된 용어가 없습니다.";
      return;
    }
    var wanted = selectId || termSelectedId;
    var found = termCache.filter(function (t) { return t.id === wanted; })[0];
    termSelectedId = found ? found.id : termCache[0].id;
    fillTermPickers();
    await loadTermDetail(termSelectedId);
  }

  async function loadTermDetail(termId) {
    var box = $("#term-detail");
    if (!box) return;
    try {
      var payload = await api(
        "/api/ontology/terms/" + encodeURIComponent(termId));
    } catch (e) {
      box.textContent = friendlyError(e);
      return;
    }
    renderTermDetail(payload);
    var rename = $("#term-rename-label");
    var language = $("#term-rename-language");
    var lifecycle = $("#term-lifecycle-state");
    var replacement = $("#term-lifecycle-replacement");
    var reason = $("#term-lifecycle-reason");
    if (rename) rename.value = payload.term.preferred_label;
    if (language) language.value = payload.term.language;
    if (lifecycle) lifecycle.value = payload.term.lifecycle;
    if (replacement) replacement.value = payload.term.replacement_term_id || "";
    if (reason) reason.value = payload.term.change_reason || "";
  }

  /* 모든 변경은 사람이 버튼을 눌렀을 때만 일어난다. 자동 저장도, 목록을
     열었다는 이유로 생기는 레코드도 없다. */
  async function termMutate(path, payload) {
    var box = $("#term-result");
    var reviewer = ($("#term-reviewer").value || "").trim();
    var provenance = ($("#term-provenance").value || "").trim();
    if (!termSelectedId) {
      showResult(box, "먼저 용어를 선택해야 합니다.", true);
      return;
    }
    if (!reviewer || !provenance) {
      showResult(box, "검토자와 출처를 입력해야 기록할 수 있습니다.", true);
      return;
    }
    payload.reviewer = reviewer;
    payload.provenance = provenance;
    try {
      var res = await apiSend(
        "/api/ontology/terms/" + encodeURIComponent(termSelectedId) + path,
        payload);
      if (res && res.ok) {
        showResult(box, "반영했습니다.", false);
      } else {
        showResult(box, escapeHtml(termErrorText(res)), true);
      }
    } catch (e) {
      showResult(box, escapeHtml(friendlyError(e)), true);
      return;
    }
    await loadTerms(termSelectedId);
  }

  document.addEventListener("change", function (ev) {
    if (ev.target && ev.target.id === "term-select") {
      termSelectedId = ev.target.value;
      fillTermPickers();
      loadTermDetail(termSelectedId);
    }
  });

  document.addEventListener("click", async function (ev) {
    var target = ev.target.closest("button");
    if (!target) return;
    if (target.id === "term-rename-btn") {
      termMutate("/rename", {
        preferred_label: ($("#term-rename-label").value || "").trim(),
        language: ($("#term-rename-language").value || "").trim(),
      });
    } else if (target.id === "term-lifecycle-btn") {
      var state = $("#term-lifecycle-state").value;
      var replacement = ($("#term-lifecycle-replacement").value || "").trim();
      var reason = ($("#term-lifecycle-reason").value || "").trim();
      if (state === "deprecated" || state === "replaced") {
        reason = await requestConfirmation({
          title: state === "deprecated" ? "용어를 폐기합니다" : "용어를 대체합니다",
          message: "이 변경은 지식 팩의 해석 기준을 바꿉니다.",
          confirmLabel: "상태 변경",
          reasonRequired: true,
          reason: reason,
          danger: true,
          invoker: target,
        });
        if (!reason) return;
        $("#term-lifecycle-reason").value = reason;
      }
      termMutate("/lifecycle", {
        lifecycle: state,
        change_reason: reason || null,
        replacement_term_id: replacement || null,
      });
    } else if (target.id === "term-alias-btn") {
      termMutate("/aliases", {
        label: ($("#term-alias-label").value || "").trim(),
        language: ($("#term-alias-language").value || "").trim(),
        alias_kind: $("#term-alias-kind").value,
      });
    }
  });

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

  var UI_COPY_KO = {
    emptyAliases: {
      title: "등록된 별칭이 없습니다",
      description: "검색과 식별에 사용할 다른 이름을 추가합니다.",
      action: "별칭 추가",
    },
    emptyXrefs: {
      title: "등록된 외부 매핑이 없습니다",
      description: "검토 화면에서 외부 레코드를 조회하고 일치 여부를 결정합니다.",
      action: "외부 레코드 검토",
    },
    emptyRegistry: {
      title: "조회한 외부 레코드가 없습니다",
      description: "현재 개념을 지원하는 레지스트리에서 후보를 조회합니다.",
      action: "강화 실행",
    },
    emptyProviders: {
      title: "등록된 프로바이더가 없습니다",
      description: "호환 API 주소와 전용 환경변수를 등록합니다.",
      action: "프로바이더 추가",
    },
    selectionRequired: "선택한 항목이 없습니다",
  };

  function emptyState(options) {
    var action = options.action || {};
    var attrs = action.goto
      ? " data-goto='" + escapeHtml(action.goto) + "'"
      : action.focusTarget
        ? " data-focus-target='" + escapeHtml(action.focusTarget) + "'"
        : action.clickTarget
          ? " data-empty-click='" + escapeHtml(action.clickTarget) + "'" : "";
    var icon = "<svg class='empty-state-icon' viewBox='0 0 24 24' fill='none'" +
      " stroke='currentColor' stroke-width='1.7' aria-hidden='true'>" +
      "<path d='M5 12h14M12 5v14'/><rect x='3' y='3' width='18' height='18' rx='4'/></svg>";
    return "<div class='empty-state-card cta-empty'>" + icon +
      "<strong class='empty-state-title'>" + escapeHtml(options.title) + "</strong>" +
      "<p class='empty-state-description'>" + escapeHtml(options.description) + "</p>" +
      (action.label ? "<button type='button' class='btn btn-primary'" + attrs + ">" +
        escapeHtml(action.label) + "</button>" : "") + "</div>";
  }

  function credentialVerification(status) {
    var value = Number(status) || 0;
    var state = value === 200 ? "verified" : value === 401 ? "unauthorized"
      : value === 429 ? "throttled" : "unverified";
    var label = value === 200 ? "검증됨 · 200" : value === 401
      ? "인증 실패 · 401" : value === 429 ? "요청 제한 · 429" : "검증 실패";
    var mark = value === 200 ? "✓" : value === 429 ? "!" : "×";
    return "<span class='credential-verification cv-" + state + "'>" +
      "<span aria-hidden='true'>" + mark + "</span> " + label + "</span>";
  }

  /* POST helper that returns the JSON body even on non-2xx, so ok:false
     contract envelopes ({ok, error_kind, detail}) render instead of throwing. */
  async function apiSend(path, payload, method) {
    var init = { method: method || "POST" };
    // DELETE에 본문을 붙이지 않는다 — 일부 프록시가 그런 요청을 조용히
    // 버린다. 보낼 것이 없으면 헤더도 붙이지 않는다.
    if (payload !== null && payload !== undefined) {
      init.headers = { "Content-Type": "application/json" };
      init.body = JSON.stringify(payload);
    }
    var res = await fetch(path, init);
    var body = null;
    try {
      body = await res.json();
    } catch (_) {
      body = null;
    }
    if (body && typeof body === "object") {
      // 응답 상태를 본문에 싶어 넣는다. 이걸 버리면 호출부가 본문만 보고
      // 503과 200을 구별해야 하고, 서버가 보낸 Retry-After는 여기서 사라졌다
      // — "잠시 뒤에 다시"라고만 말하고 얼마 뒤인지는 못 말하게 된다.
      if (!("ok" in body)) body.ok = res.ok;
      body.http_status = res.status;
      var wait = retryAfterSeconds(res);
      if (wait !== null && body.retry_after === undefined) {
        body.retry_after = wait;
      }
      return body;
    }
    if (!res.ok) throw new Error(res.statusText || "HTTP " + res.status);
    return {};
  }

  /* 503은 "지금은 안 된다"이지 "안 된다"가 아니다. 서버가 몇 초를
     기다리라고 보냈으면 그 숫자를 그대로 전한다. HTTP는 날짜 형식도
     허용하지만 이 서버는 초 단위만 보내므로 숫자만 읽는다. */
  function retryAfterSeconds(res) {
    var raw = res && res.headers && res.headers.get
      ? res.headers.get("Retry-After")
      : null;
    if (!raw) return null;
    var n = parseInt(String(raw).trim(), 10);
    return isFinite(n) && n >= 0 ? n : null;
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

  function fmtRelative(ts, nowSeconds) {
    if (ts == null || ts === "") return "—";
    var value = Number(ts);
    if (!isFinite(value)) return "—";
    var now = nowSeconds == null ? Date.now() / 1000 : Number(nowSeconds);
    var seconds = Math.max(0, Math.floor(now - (value > 1e12 ? value / 1000 : value)));
    if (seconds < 60) return "방금";
    if (seconds < 3600) return Math.floor(seconds / 60) + "분 전";
    if (seconds < 86400) return Math.floor(seconds / 3600) + "시간 전";
    if (seconds < 604800) return Math.floor(seconds / 86400) + "일 전";
    if (seconds < 2592000) return Math.floor(seconds / 604800) + "주 전";
    if (seconds < 31536000) return Math.floor(seconds / 2592000) + "개월 전";
    return Math.floor(seconds / 31536000) + "년 전";
  }

  function timeHtml(ts) {
    if (ts == null || ts === "") return "<time>—</time>";
    var d = typeof ts === "number" ? new Date(ts < 1e12 ? ts * 1000 : ts) : new Date(ts);
    var datetime = isNaN(d.getTime()) ? "" : d.toISOString();
    return "<time datetime=\"" + escapeHtml(datetime) + "\" title=\"" +
      escapeHtml(fmtTs(ts)) + "\">" + escapeHtml(fmtRelative(ts)) + "</time>";
  }

  function shortIdentifier(value) {
    var full = String(value || "");
    if (!full) return "—";
    try {
      var parsed = new URL(full);
      var tail = parsed.pathname.split("/").filter(Boolean).pop() || "";
      return parsed.hostname + (tail ? "/…/" + tail.slice(-18) : "");
    } catch (_) {
      return full.length > 28 ? full.slice(0, 12) + "…" + full.slice(-12) : full;
    }
  }

  function shortMachineValue(value) {
    var full = String(value || "");
    if (!full) return "—";
    if (full.charAt(0) === "/") {
      var parts = full.split("/").filter(Boolean);
      return "…/" + parts.slice(-2).join("/");
    }
    if (/^[A-Za-z0-9_.-]+\s+/.test(full)) {
      var tokens = full.split(/\s+/);
      return tokens[0] + " … " + tokens[tokens.length - 1].slice(-18);
    }
    return shortIdentifier(full);
  }

  function copyableMachineValueHtml(value, label, display) {
    var full = String(value || "");
    if (!full) return "<code>—</code>";
    return "<span class='copyable-machine-value'>" +
      "<code data-primary-machine-value title='" + escapeHtml(full) + "'>" +
      escapeHtml(display || shortMachineValue(full)) + "</code> " +
      "<button type='button' class='btn-link' data-copy-identifier='" +
      escapeHtml(full) + "' aria-label='" + escapeHtml(label || "전체 값 복사") +
      "'>복사</button>" +
      "<details class='machine-value-detail' data-secondary-machine-value>" +
      "<summary>전체 값 보기</summary><pre class='code-block'>" +
      escapeHtml(full) + "</pre></details></span>";
  }

  function formatJobIdentity(job) {
    var id = String(job && job.job_id || "");
    var d = new Date(Number(job && job.started_ts || 0) * 1000);
    function pad(value) { return String(value).padStart(2, "0"); }
    var stamp = isNaN(d.getTime())
      ? "시각 미상"
      : pad(d.getMonth() + 1) + "-" + pad(d.getDate()) + " " +
        pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds());
    var prefix = id.indexOf("-") > 0 ? id.split("-", 1)[0] : "작업";
    var tail = id.length > 6 ? id.slice(-6) : id;
    return { full: id, stamp: stamp, short: prefix + "-…" + tail };
  }

  function jobIdentityHtml(job) {
    var identity = formatJobIdentity(job);
    return "<span class='job-identity' title='" + escapeHtml(identity.full) + "'>" +
      "<time>" + escapeHtml(identity.stamp) + "</time> " +
      "<code>" + escapeHtml(identity.short) + "</code>" +
      " <button type='button' class='btn-link copy-id' data-copy-job-id='" +
      escapeHtml(identity.full) + "' aria-label='전체 작업 ID 복사'>복사</button></span>";
  }

  // Fixed-enum display labels (Korean). The raw value is kept for CSS class
  // and any logic; only the visible text is localized. Unknown values fall
  // back to the raw string so data never breaks.
  var STATUS_KO = {
    proposed: "검토 대기", verified: "승인됨", rejected: "거부됨",
    invalidated: "무효화됨", merged: "병합됨", dismissed: "기각",
    stale: "만료", running: "실행 중", complete: "완료", failed: "실패",
    // 취소는 실패가 아니다 — 아무것도 고장나지 않았고, 그때까지의 결과는
    // 그대로 남는다. 그래서 별도 상태이고 별도 라벨이다.
    cancelled: "중단됨",
  };
  // 리서치 런의 단계. `status`에 넣지 않는 이유는 applyJobs의
  // running→종료 엣지 검출이 세 값 전제 위에 서 있기 때문 (조용히 깨진다).
  var PHASE_KO = { collect: "모으는 중", extract: "뽑는 중" };
  function statusKo(s) {
    var k = String(s || "").toLowerCase();
    return STATUS_KO[k] || s || "—";
  }
  function kindKo(k) {
    return k === "node" ? "개념" : k === "edge" ? "관계" : k || "";
  }

  function statusIcon(status) {
    var s = String(status || "").toLowerCase();
    if (s === "complete" || s === "verified" || s === "merged") return "✓";
    if (s === "failed" || s === "rejected" || s === "invalidated") return "×";
    if (s === "running") return "•";
    if (s === "cancelled") return "–";
    return "○";
  }

  function statusBadge(status) {
    var s = String(status || "").toLowerCase();
    return (
      "<span class='badge st-" + escapeHtml(s) + "'>" +
      "<span class='status-icon' aria-hidden='true'>" + statusIcon(s) + "</span> " +
      escapeHtml(statusKo(s)) + "</span>"
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
    if (isError) {
      var probe = document.createElement("div");
      probe.innerHTML = String(html || "");
      renderErrorSurface(el, { detail: probe.textContent }, {
        fallback: "요청을 처리하지 못했습니다.",
      });
      return;
    }
    el.innerHTML = html;
    el.classList.remove("result-error");
    el.classList.remove("hidden");
  }

  // 첫 로드 중 빈 테이블이 "데이터 없음"으로 오독되지 않게 placeholder 행
  function showTableLoading(tbody, cols) {
    tbody.innerHTML =
      "<tr><td colspan='" + cols + "' class='muted'>불러오는 중…</td></tr>";
  }

  // fetch 계열 네트워크 오류를 사람이 읽을 수 있는 안내로 (최빈 장애: 서버 꺼짐)
  function friendlyError(e) {
    return classifyError(e).message;
  }

  async function executeRetry(surface, retry, run) {
    retry.disabled = true;
    retry.dataset.state = "pending";
    retry.textContent = "다시 시도 중…";
    surface.setAttribute("aria-busy", "true");
    try {
      var result = await run();
      if (result && result.recovered === true) {
        retry.dataset.state = "terminal";
        (surface.closest(".result-box, .err-msg, .status-box") ||
          surface.parentElement).classList.add("hidden");
        return "recovered";
      }
      var failure = result && result.error
        ? result.error
        : new Error("재시도 결과가 복구 상태를 확인하지 못했습니다.");
      renderErrorSurface(surface.parentElement, failure, { retry: run });
      return "failed";
    } catch (error) {
      renderErrorSurface(surface.parentElement, error, { retry: run });
      return "failed";
    }
  }

  document.addEventListener("click", async function (ev) {
    var retry = ev.target.closest && ev.target.closest("[data-retry]");
    if (retry) {
      var run = retryActions[retry.dataset.retry];
      if (!run || retry.disabled) return;
      await executeRetry(retry.closest(".error-surface"), retry, run);
      return;
    }
    var help = ev.target.closest && ev.target.closest(".error-help-toggle");
    if (help) {
      var helpBody = help.closest(".error-surface").querySelector(".error-help");
      var opening = helpBody.classList.contains("hidden");
      helpBody.classList.toggle("hidden", !opening);
      help.setAttribute("aria-expanded", opening ? "true" : "false");
      return;
    }
    var copy = ev.target.closest && ev.target.closest(".error-copy");
    if (copy) {
      await copyText(copy.closest(".error-surface").querySelector("pre").textContent);
      flashButton(copy, "복사됨");
    }
  });

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
    var list = $("#documents-list");
    var empty = $("#sources-empty");
    var err = $("#sources-error");
    err.classList.add("hidden");
    empty.classList.add("hidden");
    try {
      var data = await api("/api/documents");
      var docs = (data && data.documents) || [];
      list.innerHTML = docs
        .map(function (doc) {
          // URI는 열이 아니라 제목 아래 한 줄이다. 열로 두면 표 폭이 URI
          // 길이에 끌려가고, 정작 훑는 대상인 제목이 잘린다.
          var uri = doc.source_uri || "";
          var title = plainDocumentTitle(doc.title, "제목 없음");
          return (
            "<li class='doc-row' data-doc='" + escapeHtml(doc.id || "") + "'" +
            " data-sync-title-aria" +
            " role='button' tabindex='0' aria-label='" +
            escapeHtml(title + " 원문 열기") + "'>" +
            "<span class='doc-src'>" +
            escapeHtml(ontologyLabelKo(doc.source_kind || "?")) + "</span>" +
            "<span class='doc-main'>" +
            "<span class='doc-title'>" +
            escapeHtml(title) + "</span>" +
            (uri ? "<span class='doc-uri' title='" + escapeHtml(uri) + "'>" +
              escapeHtml(shortIdentifier(uri)) +
              " <button type='button' class='btn-link' data-copy-identifier='" +
              escapeHtml(uri) + "' aria-label='전체 출처 URL 복사'>복사</button></span>" : "") +
            "</span>" +
            "<span class='doc-ts'>" + timeHtml(doc.fetched_ts) + "</span>" +
            "</li>"
          );
        })
        .join("");
      empty.classList.toggle("hidden", docs.length > 0);
    } catch (e) {
      list.innerHTML = "";
      err.textContent = friendlyError(e);
      err.classList.remove("hidden");
    }
  }

  /* -- 팬아웃 표시 ---------------------------------------------------------
     리서치는 한 주제를 여러 논문 소스에 동시에 던지는 일이고, 그게 이
     도구의 값이다. 그런데 화면에는 입력칸만 있어서 무엇이 벌어지는지
     보이지 않았다 — 누르기 전에는 어디에 묻는지 모르고, 끝난 뒤에는
     "왜 5개만 답했지"를 물을 곳이 없었다. 같은 자리에서 둘 다 답한다. */

  var fanoutSources = null;   // /api/paper-sources 캐시 (실행 중 재요청 방지)

  async function renderFanout(job) {
    var box = $("#research-fanout");
    if (!box) return;
    if (!fanoutSources) {
      try {
        fanoutSources = ((await api("/api/paper-sources")) || {}).sources || [];
      } catch (_) {
        box.innerHTML = "";
        return;
      }
    }
    var usable = fanoutSources.filter(function (s) { return s.available; });
    var locked = fanoutSources.filter(function (s) {
      return s.connectable && !s.available;
    });
    // 실행 중에는 소스별 결과를 서버가 이름으로 주지 않는다(실패만 이름이
    // 나온다). 그래서 있지도 않은 소스별 진행률을 지어내지 않고, 단계와
    // 실패한 소스만 사실대로 말한다.
    var failed = {};
    if (job) {
      (job.progress || []).forEach(function (line) {
        var m = /\[ontologylab\] (\S+) did not answer/.exec(line);
        if (m) failed[m[1]] = true;
      });
    }
    var running = job && job.status === "running";

    // 상태를 색으로만 말하지 않는다. 이 화면은 사람만 보는 게 아니라
    // Aside의 AI가 DOM을 읽어 조작한다 — 호박색은 텍스트로 읽히지 않고,
    // 색각 이상인 사람에게도 마찬가지다. 이름 옆에 글자로 붙인다.
    var chips = usable.map(function (s) {
      var name = escapeHtml(s.label || s.id);
      var state = "", mark = "", aria = name;
      if (failed[s.id]) {
        state = " is-failed";
        mark = "<span class='chip-mark' aria-hidden='true'>✕</span>";
        aria = name + ": 답하지 않음";
      } else if (running) {
        state = " is-live";
        aria = name + ": 질의 중";
      }
      return "<span class='src-chip" + state + "' role='listitem'" +
        " aria-label='" + aria + "'>" + name + mark + "</span>";
    }).join("");

    // 라벨은 세 가지 상태를 각각 다르게 말해야 한다. 끝난 실행에
    // "질의할 곳 5"가 남아 있으면 호박색 칩 두 개와 정면으로 모순된다 —
    // 화면이 스스로와 다투는 셈이라, 둘 중 하나는 거짓으로 읽힌다.
    var nFailed = Object.keys(failed).length;
    var label;
    if (running) {
      label = "질의 중 <b>" + usable.length + "</b>";
    } else if (nFailed) {
      label = "답함 <b>" + (usable.length - nFailed) + "</b>/" + usable.length;
    } else {
      label = "질의할 곳 <b>" + usable.length + "</b>";
    }

    var tail = "";
    if (nFailed) {
      // 실패의 원인은 대개 키 없는 익명 한도다. 물어볼 곳을 바로 옆에.
      tail =
        "<button type='button' class='btn-link fanout-more' data-goto='settings'>" +
        "키 연결 →</button>";
    } else if (locked.length) {
      tail =
        "<button type='button' class='btn-link fanout-more' data-goto='settings'>" +
        "+" + locked.length + "곳 연결 안 됨</button>";
    }
    box.innerHTML =
      "<span class='fanout-label'>" + label + "</span>" + chips + tail;
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
      showResult(box, "수집 입력이 없습니다. URL, 파일 경로, 논문 검색어 중 하나를 입력합니다.", true);
      return;
    }
    btn.disabled = true;
    showResult(box, "<span class='muted'>수집 중…</span>");
    try {
      var res = await apiSend("/api/collect", payload);
      if (res && res.ok) {
        showResult(
          box,
          "<span class='ok-msg'>문서를 수집했습니다.</span> 전체 문서 <code>" +
            escapeHtml(String(res.documents != null ? res.documents : "?")) +
            "</code>개 · 새로 추가 <code>" +
            escapeHtml(String(res.created != null ? res.created : "?")) +
            "</code>개 · 중복 건너뜀 <code>" +
            escapeHtml(String(res.duplicates != null ? res.duplicates : "?")) +
            "</code>개 <button type='button' class='btn btn-primary'" +
            " data-goto='review'>검토 →</button>"
        );
        await loadDocuments();
      } else {
        showResult(
          box,
          errorKindBadge(res && res.error_kind) +
            " " +
            escapeHtml(uiUtils.errorText(res, "수집 실패.")),
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
  var jobsStreamLive = false; // SSE 수신 중이면 true — 폴링 억제
  var jobsStreamRetryMs = 2000;
  var selectedJobId = null;
  var extractEnginesLoaded = false;
  var paperSourcesLoaded = false;
  // running→complete/failed 전환 감지용 (완료 순간 안내를 띄우기 위해)
  var prevJobStatuses = {};

  async function populateEngineSelect(selector) {
    var sel = $(selector || "#extract-engine");
    if (!sel) return;
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
      // 설정의 기본 엔진을 먼저 존중한다. "첫 번째 가용 엔진"은 목록 순서에
      // 따라 mock을 고르는데, mock은 CamelCase만 찾으므로 생의학 초록에서
      // 0건을 내고 그것을 오류가 아니라 결과로 보고한다 — 설정에 claude라고
      // 적어둔 사람이 화면에서는 mock으로 돌고 있는 상태가 만들어졌다.
      var preferred = null;
      try {
        preferred = ((await api("/api/settings")) || {}).default_engine;
      } catch (_) { /* 설정을 못 읽어도 선택지는 살아 있어야 한다 */ }
      var usable = engines.filter(function (e) { return e.available; });
      var pick = usable.filter(function (e) { return e.name === preferred; })[0]
        || usable.filter(function (e) { return e.name !== "mock"; })[0];
      if (pick) sel.value = pick.name;
      else sel.selectedIndex = -1;
    } catch (_) {
      sel.innerHTML = "";
    }
  }

  async function populatePaperSourceSelect() {
    // The dispatch table in paper_api is the registry; this select renders
    // whatever it holds. On failure the picker stays empty rather than
    // offering a guessed source that would fail the allowlist on submit.
    var sel = $("#collect-paper-source");
    try {
      var body = (await api("/api/paper-sources")) || {};
      var sources = body.sources || [];
      sel.innerHTML = "";
      sources.forEach(function (src) {
        var opt = document.createElement("option");
        opt.value = src.id;
        // 키가 필요한데 아직 연결 안 된 소스는 고를 수는 있게 두되 비활성으로
        // 표시한다 — 목록에서 아예 빼면 "연결하면 쓸 수 있다"는 사실 자체가
        // 화면 어디에도 나타나지 않는다.
        opt.textContent = src.label +
          (src.keyed && !src.available ? " — 저널 접근 연결 필요" : "");
        opt.disabled = src.available === false;
        sel.appendChild(opt);
      });
      if (body.default) sel.value = body.default;
    } catch (_) {
      sel.innerHTML = "";
    }
  }

  function totalsSummary(totals) {
    var t = totals || {};
    return (
      "개념 신규 " + (t.nodes_new || 0) + " · 병합 " + (t.nodes_merged || 0) +
      " / 관계 신규 " + (t.edges_new || 0) + " · 병합 " + (t.edges_merged || 0)
    );
  }

  /* 진행 로그를 단계별로 묶는다. 리서치 런 하나가 20줄을 쏟고 그중 절반이
     청크별 진행이라, 정작 읽어야 할 "어느 소스가 실패했나"가 그 안에
     묻혔다. 헤더가 요약을 담고 본문은 접힌다 — 단, 실패한 줄은 어느
     그룹에서도 접히지 않는다. 접혀서 안 보이는 실패는 없는 실패와 같다. */

  var CHUNK_LINE_RE = /#\d+:/;                       // "…#3: +2 nodes …"
  // `error`가 빠져 있었다. 추출기가 청크마다 내는 `engine error on <doc>#3:`
  // 이 정확히 그 형태라, 가장 흔한 실패가 청크 줄로 분류돼 요약 뒤로
  // 접혔다 — 접혀서 안 보이는 실패는 없는 실패와 같다.
  var TROUBLE_RE =
    /(did not answer|failed|error|rejected|오류|실패|stopped early|cancel)/i;

  function groupProgress(lines) {
    var groups = [];
    var current = null;
    lines.forEach(function (raw) {
      var line = String(raw).replace(/^\[ontologylab\]\s*/, "");
      var phase = line.match(/^(\S+) phase started$/);
      if (phase) {
        current = { title: phase[1], lines: [], chunks: 0, trouble: 0 };
        groups.push(current);
        return;
      }
      if (!current) {
        current = { title: "", lines: [], chunks: 0, trouble: 0 };
        groups.push(current);
      }
      var bad = TROUBLE_RE.test(line);
      if (bad) current.trouble += 1;
      // 청크 줄은 세기만 하고 본문에서 뺀다 — 개별 값이 아니라 총계가
      // 정보다. 다만 문제가 있는 줄이면 청크여도 남긴다.
      if (CHUNK_LINE_RE.test(line) && !bad) {
        current.chunks += 1;
        return;
      }
      current.lines.push({ text: line, bad: bad });
    });
    return groups;
  }

  var PHASE_KO_LOG = { collect: "수집", extract: "추출" };

  // job_id → 그 실행을 시작한 문장. 한 번 물어보고 기억한다.
  var jobAsked = {};

  async function renderJobAsked(jobId) {
    var el = $("#job-asked");
    if (!el || !jobId) return;
    if (!(jobId in jobAsked)) {
      jobAsked[jobId] = null;   // 재요청 방지 — 없는 것도 답이다.
      try {
        var data = await api("/api/jobs/" + encodeURIComponent(jobId) + "/asked");
        jobAsked[jobId] = (data && data.turn) || null;
      } catch (_) { /* 계보를 못 읽는다고 로그를 못 볼 이유는 없다. */ }
    }
    var turn = jobAsked[jobId];
    el.classList.toggle("hidden", !turn);
    if (turn) {
      // `research-20260728-071805` 는 아무도 알아보지 못하는 이름이고,
      // 그걸 시작한 문장은 알아본다.
      el.innerHTML = "<span class='muted'><small>시작한 질문</small></span> " +
        "<q>" + escapeHtml(turn.message) + "</q>" +
        "<span class='muted'><small> · " + timeHtml(turn.created_ts) +
        "</small></span>";
    }
  }

  function renderJobDetail(job) {
    $("#job-detail").classList.remove("hidden");
    var identity = formatJobIdentity(job);
    $("#job-detail-title").textContent =
      "작업 " + identity.stamp + " · " + identity.short + " — " + statusKo(job.status);
    renderJobAsked(job.job_id);
    renderJobSources(job);
    var reasoning = $("#job-research-summary");
    reasoning.textContent = "";
    reasoning.classList.toggle(
      "hidden", !job.research_summary && !job.research_summary_error
    );
    if (job.research_summary) {
      reasoning.appendChild(
        window.ontologylabBuildResearchSummary(job.research_summary)
      );
    } else if (job.research_summary_error) {
      var unavailable = document.createElement("p");
      unavailable.className = "err-msg";
      var unavailableReason =
        job.research_summary_error === "artifact_unavailable"
          ? "리서치 추론 산출물을 사용할 수 없습니다."
          : "리서치 추론 요약을 생성하지 못했습니다.";
      unavailable.textContent =
        "리서치 추론을 불러오지 못했습니다 · " +
        unavailableReason;
      reasoning.appendChild(unavailable);
    }
    var corpusLink = $("#job-corpus");
    var corpusReady =
      job.kind === "research" && job.corpus_available === true;
    corpusLink.classList.toggle("hidden", !corpusReady);
    if (corpusReady) {
      corpusLink.href =
        "/api/jobs/" + encodeURIComponent(job.job_id) + "/corpus";
    }

    var lines = (job.progress || []).slice();
    if (job.error) lines.push("오류: " + job.error);
    var box = $("#job-progress");
    box.textContent = "";
    if (!lines.length) {
      box.textContent = "(진행 내역 없음)";
      return;
    }

    groupProgress(lines).forEach(function (group) {
      var details = document.createElement("details");
      details.className = "log-group";
      // 문제가 있는 단계는 펼친 채로 연다. 사용자가 로그를 여는 이유는
      // 대개 뭔가 잘못됐기 때문이고, 그때 한 번 더 클릭하게 만들 이유가 없다.
      if (group.trouble > 0) details.open = true;

      var summary = document.createElement("summary");
      var name = document.createElement("span");
      name.className = "log-title";
      name.textContent = PHASE_KO_LOG[group.title] || group.title || "진행";
      summary.appendChild(name);

      var meta = document.createElement("span");
      meta.className = "log-meta";
      var bits = [];
      if (group.chunks) bits.push("청크 " + group.chunks);
      bits.push(group.lines.length + "줄");
      meta.textContent = bits.join(" · ");
      summary.appendChild(meta);

      if (group.trouble) {
        var warn = document.createElement("span");
        warn.className = "log-trouble";
        warn.textContent = group.trouble + " 실패";
        summary.appendChild(warn);
      }
      details.appendChild(summary);

      group.lines.forEach(function (entry) {
        var row = document.createElement("div");
        row.className = "log-line" + (entry.bad ? " log-line-bad" : "");
        /* textContent: 서버·크롤 유래 문자열이므로 절대 innerHTML이 아니다 */
        row.textContent = entry.text;
        details.appendChild(row);
      });
      box.appendChild(details);
    });
  }

  /* 소스별 상태 배지 — 팬아웃의 결과를 로그 줄 대신 요약으로.
     실행 중에는 "어느 소스가 아직 응답 중인가", 끝난 뒤에는 "몇 개가
     응답했는가"가 질문이다. 실패 배지에는 종류(FAIL_KO)를, 전부 실패면
     다음 행동을 바로 적는다. */
  function renderJobSources(job) {
    var box = $("#job-sources");
    if (!box) return;
    var sources = job.sources || [];
    if (!sources.length) {
      box.classList.add("hidden");
      return;
    }
    var ok = sources.filter(function (s) { return s.status === "ok"; }).length;
    var failed = sources.filter(function (s) { return s.status === "failed"; }).length;
    var running = sources.length - ok - failed;
    var allFailed = sources.length > 0 && failed === sources.length;
    var badges = sources.map(function (s) {
      var detail = s.detail || "";
      if (s.status === "failed") detail = FAIL_KO[detail] || detail;
      var mark = s.status === "ok" ? "✓"
        : s.status === "failed" ? "✕" : "•";
      return "<span class='src-badge src-" + escapeHtml(s.status) + "'>" +
        mark + " " + escapeHtml(toolKo(s.name)) +
        (detail ? " <small>" + escapeHtml(detail) + "</small>" : "") +
        "</span>";
    }).join("");
    var html =
      "<div class='src-badges'>" + badges + "</div>" +
      "<div class='src-aggregate muted'>" +
      "소스 " + sources.length + "개 중 " + ok + "개 응답" +
      (failed ? " · 실패 " + failed : "") +
      (running ? " · 진행 " + running : "") +
      "</div>";
    if (allFailed) {
      html += "<p class='src-allfailed'><strong>응답한 소스가 없습니다.</strong> " +
        "소스 연결 상태를 확인한 뒤 리서치를 다시 실행합니다.</p>";
    }
    box.innerHTML = html;
    box.classList.remove("hidden");
  }

  async function selectJob(jobId) {
    selectedJobId = jobId;
    try {
      var job = await api("/api/jobs/" + encodeURIComponent(jobId));
      if (job) renderJobDetail(job);
    } catch (e) {
      $("#job-detail").classList.remove("hidden");
      $("#job-detail-title").textContent = "작업 세부 정보를 불러오지 못했습니다";
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
        "<td>" + jobIdentityHtml(job) + "</td>" +
        "<td>" + escapeHtml(job.engine || "") +
        (job.model ? " <small class='muted'>" + escapeHtml(job.model) + "</small>" : "") +
        "</td>" +
        "<td aria-label='" + escapeHtml(statusIcon(job.status) + " " + statusKo(job.status)) + "'>" +
        statusBadge(job.status) +
        // 실행 중인 리서치 런만 단계를 덧붙인다. 끝난 작업에 "뽑는 중"이
        // 남아 있으면 아직 도는 것처럼 읽힌다.
        (job.status === "running" && PHASE_KO[job.phase]
          ? " <small class='muted'>" + escapeHtml(PHASE_KO[job.phase]) + "</small>"
          : "") +
        "</td>" +
        "<td><small>" + escapeHtml(totalsSummary(job.totals)) + "</small></td>" +
        "<td><small>" + timeHtml(job.started_ts) + "</small></td>" +
        "<td><small>" + timeHtml(job.finished_ts) + "</small></td>";
      tr.addEventListener("click", function () {
        selectJob(job.job_id);
      });
      tbody.appendChild(tr);
    });
    $("#jobs-empty").classList.toggle("hidden", jobs.length > 0);
  }

  document.addEventListener("click", async function (ev) {
    var copyJob = ev.target.closest && ev.target.closest("[data-copy-job-id]");
    var copyIdentifier = ev.target.closest && ev.target.closest("[data-copy-identifier]");
    var control = copyJob || copyIdentifier;
    if (!control) return;
    ev.stopPropagation();
    await copyText(copyJob ? copyJob.dataset.copyJobId : control.dataset.copyIdentifier);
    flashButton(control, "복사됨");
  });

  function scheduleJobsPoll(anyRunning) {
    if (jobsPollTimer) {
      clearTimeout(jobsPollTimer);
      jobsPollTimer = null;
    }
    // SSE 스트림이 살아 있으면 서버가 밀어주므로 폴링은 잡지 않는다.
    if (anyRunning && !jobsStreamLive) jobsPollTimer = setTimeout(loadJobs, 1500);
  }

  // 스냅샷 적용 공통 경로 — SSE 이벤트와 폴링 응답이 모두 여길 지난다.
  /* 실행 중인 작업을 상태바에 건다. 리서치 화면을 떠나면 진행이 보이지
     않던 것이 이 앱의 구조적 문제였다 — AI가 다른 화면으로 옮겨 가면
     사람은 실행이 도는지조차 알 수 없었다. 잡 스냅샷이 오는 모든
     경로(SSE·폴링)가 여기를 지나므로 갱신 지점은 하나로 족하다. */
  function renderStatusRun(jobs) {
    var el = document.getElementById("statusbar-run");
    if (!el) return;
    var live = (jobs || []).filter(function (j) {
      return j.status === "running";
    });
    if (!live.length) {
      el.classList.add("hidden");
      el.textContent = "";
      return;
    }
    var job = live[0];
    var kind = job.kind === "research" ? "리서치" : "추출";
    var phase = PHASE_KO[job.phase] || "";
    // 상태를 색이 아니라 글자로도 말한다. AI는 CSS 클래스가 아니라
    // 텍스트를 읽고, 사람은 곁눈으로 점을 본다 — 둘 다 만족해야 한다.
    el.textContent = kind + " 실행 중" + (phase ? " · " + phase : "") +
      (live.length > 1 ? " (+" + (live.length - 1) + ")" : "");
    el.classList.remove("hidden");
  }

  function applyJobs(jobs) {
    renderJobs(jobs);
    renderStatusRun(jobs);
    // 실행 갱신은 대화 말풍선에도 흘러들어야 한다. 여기서 부르지 않으면
    // 대화는 "시작했어요"에 멈춘 채, 진행은 옆 화면에서만 보이게 된다.
    jobs.forEach(updateChatJob);
    reconcileChatJobs(jobs);
    // running → 종료 전환 감지: 완료 순간에 다음 단계 안내 + 검토 배지 갱신
    jobs.forEach(function (job) {
      var prev = prevJobStatuses[job.job_id];
      // 리서치 런의 결과는 리서치 상자에, 수동 추출은 추출 상자에.
      var box = job.kind === "research" ? $("#research-result") : $("#extract-result");
      var t = job.totals || {};
      var produced =
        (t.nodes_new || 0) + (t.nodes_merged || 0) +
        (t.edges_new || 0) + (t.edges_merged || 0);
      if (prev === "running" && job.status === "complete") {
        showResult(
          box,
          "<span class='ok-msg'>" +
            (job.kind === "research" ? "리서치 완료!" : "추출 완료!") +
            "</span> " +
            escapeHtml(totalsSummary(job.totals)) +
            " <button type='button' class='btn btn-primary'" +
            " data-goto='review'>검토 →</button>"
        );
        loadProposals();
      } else if (prev === "running" && job.status === "failed") {
        // 청크 단위 실패는 전부 아니면 전무가 아니다. 엔진이 넌어졌어도 그
        // 전까지 성공한 청크는 진짜 제안을 이미 썼다. "실패"만 말하고
        // 끝내면 사람은 존재하는 결과를 버리게 된다 — 예전의 거짓된 성공
        // 배너와 방향만 반대인 같은 거짓이다. 나온 게 있으면 세서 보여주고
        // 검토로 가는 길을 열어 둔다.
        // 요청 오류 표면은 HTML을 텍스트로 바꾸므로 검토 버튼을 버린다.
        // 종료된 작업의 결과는 실패 상태와 실제 제어를 함께 유지한다.
        showResult(
          box,
          statusBadge("failed") + " " + escapeHtml(job.error || "실패") +
            (produced
              ? " — 현재까지 생성된 제안은 유지됩니다. " +
                escapeHtml(totalsSummary(job.totals)) +
                ". 추출 양식에서 나머지를 다시 실행할 수 있습니다." +
                " <button type='button' class='btn btn-primary'" +
                " data-goto='review'>검토 →</button>"
              : " — 새로 생성된 제안이 없습니다. 추출 양식에서 다시 시도합니다.")
        );
        // 제안이 실제로 쌓였으면 검토 목록과 배지도 그만큼 올라가 있어야 한다.
        if (produced) loadProposals();
      } else if (prev === "running" && job.status === "cancelled") {
        // 취소는 실패가 아니다. 여기까지 나온 제안은 그대로 남아 있으므로
        // 검토로 갈 수 있다고 알려준다.
        showResult(
          box,
          statusBadge("cancelled") +
            " 중단했습니다. " +
            (produced ? "현재까지 생성된 결과는 유지됩니다. " : "") +
            escapeHtml(totalsSummary(job.totals)) +
            (produced
              ? " <button type='button' class='btn btn-primary'" +
                " data-goto='review'>검토 →</button>"
              : "")
        );
        loadProposals();
      }
      if (job.kind === "research" && job.job_id === researchJobId) {
        // 팬아웃 칩이 이 스냅샷을 근거로 갱신된다 — 실패한 소스는
        // 이름이 로그에 나오므로 그 자리에서 붉게 바뀐다.
        renderFanout(job);
        if (job.status !== "running") setResearchRunning(null);
      }
      prevJobStatuses[job.job_id] = job.status;
    });
    if (selectedJobId) {
      var sel = jobs.filter(function (j) {
        return j.job_id === selectedJobId;
      })[0];
      if (sel) renderJobDetail(sel);
    }
    return jobs.some(function (j) {
      return j.status === "running";
    });
  }

  async function loadJobs(options) {
    var err = $("#jobs-error");
    if (!options || options.render !== false) err.classList.add("hidden");
    var jobsBody = $("#jobs-body");
    if (!jobsBody.children.length) showTableLoading(jobsBody, 6);
    try {
      var data = await api("/api/jobs");
      var anyRunning = applyJobs((data && data.jobs) || []);
      scheduleJobsPoll(anyRunning);
      return { recovered: true };
    } catch (e) {
      if (jobsBody.querySelector("td[colspan]")) jobsBody.innerHTML = "";
      if (!options || options.render !== false) {
        renderErrorSurface(err, e, {
          retry: function () { return loadJobs({ render: false }); },
        });
      }
      scheduleJobsPoll(false);
      return { recovered: false, error: e };
    }
  }

  // ---- SSE: 잡 상태 실시간 스트림 (실패 시 기존 폴링으로 폴백) ----
  function connectJobsStream() {
    if (!window.EventSource) return; // 미지원 브라우저: 폴링 유지
    var es = new EventSource("/api/jobs/stream");
    es.addEventListener("jobs", function (ev) {
      var jobs;
      try {
        jobs = (JSON.parse(ev.data) || {}).jobs || [];
      } catch (e) {
        return; // 손상 스냅샷은 버린다 — 다음 이벤트가 곧 온다
      }
      jobsStreamLive = true;
      jobsStreamRetryMs = 2000; // 실데이터 수신이 확인된 뒤에만 백오프 리셋
      $("#jobs-error").classList.add("hidden");
      applyJobs(jobs);
      scheduleJobsPoll(false); // 스트림 수신 중엔 폴링 타이머 해제
    });
    es.onerror = function () {
      es.close();
      var wasLive = jobsStreamLive;
      jobsStreamLive = false;
      if (wasLive) loadJobs(); // 즉시 한 번 동기화 + 폴링 재가동
      setTimeout(connectJobsStream, jobsStreamRetryMs);
      jobsStreamRetryMs = Math.min(jobsStreamRetryMs * 2, 30000);
    };
    // onopen에서 백오프를 리셋하지 않는다 — 연결만 되고 데이터가 안 오는
    // 프록시 상대로 2초 바닥에 고정되는 것을 막는다 (리셋은 jobs 수신 시).
  }

  $("#extract-form").addEventListener("submit", async function (ev) {
    ev.preventDefault();
    var box = $("#extract-result");
    var btn = $("#extract-submit");
    var model = $("#extract-model").value.trim();
    var payload = {
      model: model || null,
      doc_ids: [],
      /* mirror paths.DEFAULT_MAX_ENGINE_CALLS / DEFAULT_TIME_BUDGET_S —
         change there first, then here */
      /* max_engine_calls / time_budget 은 보내지 않는다. 스키마가
         paths.DEFAULT_* 로 채우므로, 여기서 값을 실어 보내면 서버 기본값이
         영원히 적용되지 않는다 — 상수를 바꿔도 브라우저 실행만 옛 예산을
         계속 쓰고 아무것도 실패하지 않는다. 주석으로 "여기도 고쳐라"라고
         적어 두는 것으로는 막히지 않는 종류의 드리프트다. */
      seed: toInt($("#extract-seed").value, 7),
    };
    var extractEngine = $("#extract-engine").value;
    if (extractEngine) payload.engine = extractEngine;
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
          escapeHtml(uiUtils.errorText(res, "추출 시작 실패.")),
          true
        );
      }
    } catch (e) {
      showResult(box, escapeHtml(friendlyError(e)), true);
    } finally {
      btn.disabled = false;
    }
  });

  /* -- 저널 접근: 연결/미연결 이진 상태. 값은 절대 되받지 않는다 -- */

  async function loadSources() {
    var tbody = $("#sources-body");
    if (!tbody) return;
    var badge = $("#sources-badge");
    try {
      // 목록의 출처는 /api/sources(= 연결된 것)가 아니라 /api/paper-sources
      // (= 연결할 수 있는 것)다. 전자는 이미 연결한 것만 보여주므로, 아직
      // 연결하지 않은 소스는 화면 어디에도 나타나지 않았다.
      var body = (await api("/api/paper-sources")) || {};
      var all = body.sources || [];
      var connectable = all.filter(function (s) { return s.connectable; });
      var registry = ((await api("/api/sources")) || {}).sources || [];
      var registered = {};
      registry.forEach(function (r) { registered[r.id] = r; });

      tbody.innerHTML = "";
      $("#sources-list-empty").classList.toggle("hidden", connectable.length > 0);
      var anyConnected = false;
      connectable.forEach(function (s) {
        if (s.key_present) anyConnected = true;
        // 서버는 key_present만 보낸다 — 여기서 그릴 수 있는 값 자체가 없다.
        var keyBadge = s.key_present
          ? "<span class='badge st-verified'>연결됨</span>"
          : "<span class='badge st-proposed'>미연결</span>";
        // 키가 없을 때 실제로 벌어지는 일. 같은 '미연결'이라도 결과가
        // 다르므로 배지 하나로 뭉뚱그리지 않는다.
        var consequence = s.keyed
          ? "<span class='muted'>응답 없음 — 전문 불가</span>"
          : "<span class='muted'>익명 한도 공유 — <code>429</code>가 자주 발생합니다</span>";
        var actions = "";
        if (s.key_present) {
          actions =
            "<button type='button' class='btn source-forget-btn' data-id='" +
            escapeHtml(s.id) + "'>키 지우기</button>";
          if (registered[s.id]) {
            actions +=
              " <button type='button' class='btn btn-danger source-remove-btn'" +
              " data-id='" + escapeHtml(s.id) + "'>연결 해제</button>";
          }
        }
        var tr = document.createElement("tr");
        tr.innerHTML =
          "<td>" + escapeHtml(s.label || s.id) +
          " <code class='muted'>" + escapeHtml(s.id) + "</code></td>" +
          "<td>" + keyBadge + "</td>" +
          "<td>" + consequence + "</td>" +
          "<td class='actions'>" + actions + "</td>";
        tbody.appendChild(tr);
      });

      populateSourceSelect(connectable);
      // 소스 구성이 바뀌었으니 팬아웃 캐시는 더 이상 사실이 아니다.
      fanoutSources = null;
      if (badge) {
        var pending = connectable.filter(function (s) {
          return s.keyed && !s.key_present;
        }).length;
        badge.textContent = anyConnected
          ? (pending ? pending + "곳 남음" : "연결됨")
          : "미연결";
        badge.className = "badge " + (anyConnected && !pending
          ? "st-verified" : "st-proposed");
      }
    } catch (e) {
      tbody.innerHTML = "";
      showResult($("#source-result"), escapeHtml(friendlyError(e)), true);
    }
  }

  var SOURCE_CREDENTIAL_META = {
    semanticscholar: { format: "s2k-로 시작하는 발급 키", url: "https://www.semanticscholar.org/product/api" },
    elsevier: { format: "Elsevier 개발자 API 키", url: "https://dev.elsevier.com/" },
    springer: { format: "Springer Nature Meta API 키", url: "https://dev.springernature.com/" },
    core: { format: "CORE API 키", url: "https://core.ac.uk/services/api" },
    pubmed: { format: "NCBI API 키", url: "https://www.ncbi.nlm.nih.gov/account/settings/" },
    openalex: { format: "OpenAlex 키 또는 메일 식별자", url: "https://docs.openalex.org/how-to-use-the-api/rate-limits-and-authentication" },
  };

  function renderSourceCredentialHelp(id) {
    var host = $("#source-credential-help");
    var meta = SOURCE_CREDENTIAL_META[id];
    if (!host || !meta) {
      if (host) host.textContent = "선택한 소스의 공식 발급 안내를 확인합니다.";
      return;
    }
    host.innerHTML = "<span><strong>형식</strong> " + escapeHtml(meta.format) +
      "</span> <a href='" + escapeHtml(meta.url) +
      "' target='_blank' rel='noopener noreferrer'>공식 발급 페이지</a>";
  }

  /* 연결 폼의 선택지도 같은 응답에서 만든다. 손으로 적은 이름은 어떤
     소스와도 매칭되지 않아 조용히 죽은 키가 되므로 입력 자체를 없앴다. */
  function populateSourceSelect(connectable) {
    var sel = $("#source-id");
    if (!sel) return;
    var previous = sel.value;
    sel.innerHTML = "";
    connectable.forEach(function (s) {
      var opt = document.createElement("option");
      opt.value = s.id;
      opt.textContent =
        (s.label || s.id) +
        (s.key_present ? " — 연결됨 (다시 넣으면 교체)"
                       : s.keyed ? " — 필요" : " — 선택");
      sel.appendChild(opt);
    });
    if (previous) sel.value = previous;
    renderSourceCredentialHelp(sel.value);
  }

  $("#source-id").addEventListener("change", function () {
    renderSourceCredentialHelp($("#source-id").value);
  });

  $("#source-form").addEventListener("submit", async function (ev) {
    ev.preventDefault();
    var box = $("#source-result");
    var keyField = $("#source-key");
    var key = keyField.value;
    var id = $("#source-id").value;
    if (!id) {
      showResult(box, "소스를 선택해야 합니다.", true);
      return;
    }
    if (!key.trim()) {
      showResult(box, "API 키를 입력해야 합니다.", true);
      return;
    }
    $("#source-submit").disabled = true;
    showResult(box, "<span class='muted'>키체인에 저장 중…</span>");
    try {
      var res = await apiSend("/api/sources", {
        id: id, role: "literature", key: key,
      });
      if (res && res.ok) {
        showResult(box, "<span class='muted'>자격 증명을 검증하고 있습니다.</span>");
        var verification = await apiSend(
          "/api/sources/" + encodeURIComponent(id) + "/test", {}
        );
        showResult(
          box,
          "<span class='ok-msg'>키체인에 저장했습니다.</span> " +
            credentialVerification(verification.verification_status)
        );
        await loadSources();
      } else {
        showResult(
          box,
          errorKindBadge(res && res.error_kind) + " " +
            escapeHtml(uiUtils.errorText(res, "연결 실패.")),
          true
        );
      }
    } catch (e) {
      showResult(box, escapeHtml(friendlyError(e)), true);
    } finally {
      // 성공이든 실패든 즉시 비운다. 남겨두면 DOM에 평문 키가 계속 머문다.
      keyField.value = "";
      key = "";
      $("#source-submit").disabled = false;
    }
  });

  $("#sources-body").addEventListener("click", async function (ev) {
    if (!ev.target.closest) return;
    var forget = ev.target.closest(".source-forget-btn");
    var remove = ev.target.closest(".source-remove-btn");
    if (!forget && !remove) return;
    var control = forget || remove;
    var id = control.dataset.id;
    var box = $("#source-result");
    var confirmed = await requestConfirmation({
      title: forget ? "저장된 소스 키를 삭제합니다" : "논문 소스 연결을 해제합니다",
      message: forget
        ? "키체인에서 이 키를 영구 삭제합니다. 삭제한 키는 복구할 수 없습니다."
        : "소스 설정만 해제합니다. 키체인에 저장된 키는 유지됩니다.",
      confirmLabel: forget ? "키 영구 삭제" : "연결 해제",
      danger: true,
      invoker: control,
    });
    if (!confirmed) return;
    try {
      if (forget) {
        var f = await api("/api/sources/" + encodeURIComponent(id) + "/key",
                          { method: "DELETE" });
        showResult(box, f && f.forgotten
          ? "키를 삭제했습니다. 설정은 유지되며 새 키로 다시 연결할 수 있습니다."
          : "삭제할 키가 없습니다.");
      } else {
        var r = await api("/api/sources/" + encodeURIComponent(id),
                          { method: "DELETE" });
        // 연결 해제는 설정만 지운다 — 자격증명 파기는 별도 결정이라 별도 버튼이다.
        showResult(box, r && r.key_retained
          ? "연결을 해제했습니다. 저장된 키는 키체인에 <strong>유지됩니다</strong>. 삭제하려면 다시 연결한 뒤 <em>키 지우기</em>를 실행합니다."
          : "연결을 해제했습니다.");
      }
      await loadSources();
    } catch (e) {
      showResult(box, escapeHtml(friendlyError(e)), true);
    }
  });

  /* -- 리서치 런: 주제 한 줄 → 수집 + 추출 한 작업 -- */

  // 실행 중인 리서치 작업 id. "중단" 버튼이 무엇을 취소해야 하는지 알아야
  // 하는데, 서버는 한 번에 하나만 허용하므로 하나면 충분하다.
  var researchJobId = null;

  function setResearchRunning(jobId) {
    researchJobId = jobId;
    $("#research-cancel").classList.toggle("hidden", !jobId);
    $("#research-submit").disabled = !!jobId;
  }

  $("#research-form").addEventListener("submit", async function (ev) {
    ev.preventDefault();
    var box = $("#research-result");
    var topic = $("#research-topic").value.trim();
    if (!topic) {
      showResult(box, "리서치 주제를 입력해야 합니다.", true);
      return;
    }
    var payload = {
      topic: topic,
      limit: toInt($("#research-limit").value, 100),
      fulltext: $("#research-fulltext").checked,
      citation_expansion: $("#research-citations").checked,
      /* 예산은 서버 스키마의 기본값에 맡긴다 (위 주석 참조). */
    };
    var researchEngine = $("#research-engine").value;
    if (researchEngine) payload.engine = researchEngine;
    $("#research-submit").disabled = true;
    showResult(box, "<span class='muted'>리서치 시작 중…</span>");
    try {
      var res = await apiSend("/api/research", payload);
      if (res && res.ok && res.job_id) {
        selectedJobId = res.job_id;
        setResearchRunning(res.job_id);
        showResult(
          box,
          "<span class='muted'>모으는 중…</span> 작업 <code>" +
            escapeHtml(String(res.job_id).slice(0, 12)) +
            "</code>"
        );
        await loadJobs();
      } else {
        // 게이트 실패는 200 + error_kind로 온다 — 배지로 분류를 보여준다.
        $("#research-submit").disabled = false;
        showResult(
          box,
          errorKindBadge(res && res.error_kind) +
            " " +
            escapeHtml(uiUtils.errorText(res, "리서치 시작 실패.")),
          true
        );
      }
    } catch (e) {
      $("#research-submit").disabled = false;
      showResult(box, escapeHtml(friendlyError(e)), true);
    }
  });

  $("#research-cancel").addEventListener("click", async function () {
    if (!researchJobId) return;
    var box = $("#research-result");
    $("#research-cancel").disabled = true;
    try {
      var res = await apiSend(
        "/api/jobs/" + encodeURIComponent(researchJobId) + "/cancel", {}
      );
      uiUtils.throwIfRefused(res);
      // 취소는 요청이지 강제 종료가 아니다. 워커는 다음 청크 경계에서 멈추고,
      // 이미 날아간 fetch는 소켓 타임아웃까지 돈다 — 그래서 여기서 상태를
      // 바꾸지 않고, 작업 스트림이 cancelled를 알려줄 때까지 기다린다.
      if (res && res.cancelled) {
        showResult(box, "<span class='muted'>중단을 요청했습니다. 다음 구간에서 중지됩니다…</span>");
      } else {
        showResult(box, "<span class='muted'>이미 종료된 작업입니다.</span>");
        setResearchRunning(null);
      }
    } catch (e) {
      if (res) e.httpStatus = res.http_status;
      var surface = renderErrorSurface(box, e);
      var hint = retryHint(e);
      if (hint) {
        var help = surface.querySelector(".error-help");
        help.textContent += hint;
        help.classList.remove("hidden");
        surface.querySelector(".error-help-toggle").setAttribute("aria-expanded", "true");
      }
    } finally {
      $("#research-cancel").disabled = false;
    }
  });

  /* -- Packs -- */

  /* 읽힐 수 없는 팩 디렉터리를 보고한다.

     서버는 검증에 실패한 디렉터리를 `unusable[]`로 따로 내려보낸다
     (`pack_dir`과 `reason` 둘뿐 — counts도 serve_command도 없다).
     팩으로 그리면 모든 칸이 0이나 — 인 행이 생기고, 섬기지도 못하는
     것에 연결 버튼을 내주게 된다. 그렇다고 조용히 버리면 방금 만든 팩이
     목록에 없는 이유를 사람이 알 길이 없다. 그래서 팩도 무음도 아닌
     세 번째 자리 — 안내 블록에 둔다. 비었으면 아예 그리지 않는다:
     항상 떠 있는 경고는 읽히지 않는 경고가 된다. */
  var PACK_FAILURE_KO = {
    "manifest invalid": "팩 매니페스트가 유효하지 않습니다.",
    "manifest is not an object": "팩 매니페스트 형식이 유효하지 않습니다.",
    "kg.sqlite is not a database": "팩 데이터베이스를 읽을 수 없습니다.",
  };

  function packFailureCopy(reason) {
    var raw = String(reason || "");
    return {
      primary: PACK_FAILURE_KO[raw.toLowerCase()] ||
        "팩 폴더를 읽을 수 없습니다.",
      raw: raw,
    };
  }

  function renderUnusablePacks(hostId, anchorId, unusable) {
    var host = document.getElementById(hostId);
    if (!host) {
      // 마크업에 자리를 미리 만들어 두지 않고 필요할 때 만든다. 비었을 때가
      // 정상이기 때문에, 항상 있는 빈 상자를 두는 것보다 이쪽이 정직하다.
      var anchor = document.getElementById(anchorId);
      if (!anchor || !anchor.parentNode) return;
      host = document.createElement("div");
      host.id = hostId;
      host.className = "hidden";
      anchor.parentNode.insertBefore(host, anchor);
    }
    var items = unusable || [];
    if (!items.length) {
      host.innerHTML = "";
      host.classList.add("hidden");
      return;
    }
    host.innerHTML =
      "<div class='mcp-card'>" +
      "<p class='eyebrow'>열 수 없는 팩 폴더 " + escapeHtml(String(items.length)) +
      "개</p>" +
      "<p class='muted'>다음 폴더는 팩으로 읽을 수 없어 목록과 비교에서 제외했습니다. " +
      "다시 빌드하거나 폴더를 정리하면 이 안내도 사라집니다.</p>" +
      "<ul class='term-list'>" +
      items
        .map(function (item) {
          var failure = packFailureCopy(item.reason);
          return (
            "<li><code>" + escapeHtml(item.pack_dir || "") + "</code> — " +
            "<span class='err-msg'>" + escapeHtml(failure.primary) +
            "</span>" + (failure.raw
              ? "<details class='prov'><summary>기술 세부 정보</summary><code>" +
                escapeHtml(failure.raw) + "</code></details>" : "") + "</li>"
          );
        })
        .join("") +
      "</ul></div>";
    host.classList.remove("hidden");
  }

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
            "<td><small>" + timeHtml(pack.created_ts) + "</small></td>" +
            "<td class='num'>" + escapeHtml(String(counts.documents || 0)) + "</td>" +
            "<td class='num'>" + escapeHtml(String(counts.nodes_verified || 0)) + "</td>" +
            "<td class='num'>" + escapeHtml(String(counts.edges_verified || 0)) + "</td>" +
            "<td title='기계 값: " + escapeHtml(pack.search_tier || "") + "'>" +
            escapeHtml(ontologyLabelKo(pack.search_tier || "—")) + "</td>" +
            // 지문은 전체를 title로 단다. 12자만 보이면 두 팩이 같은지
            // 눈으로 비교할 수는 있어도, 다른 곳에 붙여넣어 확인할 수 없다.
            "<td><code title='" +
            escapeHtml(String(pack.content_hash || "")) + "'>" +
            escapeHtml(String(pack.content_hash || "").slice(0, 12)) + "</code></td>" +
            "<td><button type='button' class='btn mcpb-btn' data-pack='" +
            escapeHtml(pack.pack_id || "") + "'>.mcpb</button></td>" +
            "</tr>" +
            // 팩의 계보 — 노드/엣지의 것과 같은 질문의 아티팩트 판이다.
            // "이 상자에 뭐가 어떤 스키마로 들어갔고 어느 빌드가 만들었나".
            // manifest는 이미 브라우저에 와 있으므로 추가 요청이 없다.
            "<tr class='pack-prov-row'><td colspan='8'>" +
            "<details class='prov'><summary>계보 — 무엇이 이 팩에 들어갔나</summary>" +
            "<dl class='prov-list'>" +
            "<dt>스키마</dt><dd>" + escapeHtml(pack.schema_label || "—") +
            " (v" + escapeHtml(String(pack.schema_version_id || "?")) + ")</dd>" +
            "<dt>빌드 작업</dt><dd>" + escapeHtml(pack.source_job_id || "—") + "</dd>" +
            "<dt>개체 종류</dt><dd>" +
            escapeHtml(String(counts.entity_types || 0)) + "종</dd>" +
            "<dt>관계 종류</dt><dd>" +
            escapeHtml(String(counts.relation_types || 0)) + "종</dd>" +
            "<dt>커뮤니티</dt><dd>" +
            escapeHtml(String(counts.communities || 0)) + "개</dd>" +
            "<dt>임베딩</dt><dd>" +
            escapeHtml(pack.embedding_model || "없음 (어휘 검색만)") + "</dd>" +
            "<dt>빌드 버전</dt><dd>" +
            escapeHtml(pack.ontologylab_version || "—") + "</dd>" +
            "<dt>지문</dt><dd>" + escapeHtml(pack.content_hash || "—") + "</dd>" +
            "</dl></details></td></tr>"
          );
        })
        .join("");
      empty.classList.toggle("hidden", packs.length > 0);
      // 비교 드롭다운에는 쓸 수 있는 팩만 들어간다 — 열지도 못하는 팩을
      // 고를 수 있게 하는 것은 실패할 diff 요청을 만들어 주는 일이다.
      populateDiffSelects(packs);
      renderUnusablePacks("packs-unusable", "packs-error", data && data.unusable);
      renderCompetencyReceipt(data && data.competency);
    } catch (e) {
      tbody.innerHTML = "";
      // 목록을 못 받았으면 지난번 안내도 근거가 없다. 남겨 두면 이미
      // 고친 폴더를 여전히 고장이라고 우기는 화면이 된다.
      renderUnusablePacks("packs-unusable", "packs-error", []);
      err.textContent = friendlyError(e);
      err.classList.remove("hidden");
    }
  }

  /* -- P2-A: Competency release receipt (Packs screen) -- */

  var COMPETENCY_QUESTION_KO = {
    Q1: "검증된 모든 사실을 정확한 출처 문서, 추출 흐름, 승인 기록까지 추적할 수 있습니까?",
    Q2: "알려진 문서에서 추출기가 예상한 개체와 관계를 정확하게 생성합니까?",
    Q3: "빌드된 팩이 사용자 질의에 정확한 답을 반환합니까?",
  };

  function competencyQuestionCopy(question) {
    var id = String(question && question.question_id || "");
    return COMPETENCY_QUESTION_KO[id] ||
      "등록된 역량 질문의 결과를 확인합니다.";
  }

  function renderCompetencyReceipt(comp) {
    var box = $("#competency-receipt");
    var body = $("#competency-body");
    if (!box || !body) return;
    if (!comp) {
      box.classList.add("hidden");
      return;
    }
    box.classList.remove("hidden");
    if (comp.available === false) {
      // 설치된 런타임에는 골드 픽스처가 없다. 게이트가 실패한 것이 아니라
      // 이 빌드에서는 계산할 수 없는 것 — 그 사실을 그대로 보여 준다.
      body.innerHTML =
        "<div class='muted'><small>릴리스 게이트 리포트는 이 빌드에 " +
        "포함되어 있지 않습니다. 소스 체크아웃에서만 계산됩니다.</small></div>";
      return;
    }
    var qs = comp.questions || [];
    var passed = comp.passed_count || 0;
    var total = comp.total_count || 0;
    var allOk = comp.all_passed;
    var status = allOk ? "PASS" : "FAIL";
    var statusPrimary = allOk ? "통과" : "실패";
    var cls = allOk ? "ok" : "fail";
    body.innerHTML =
      "<div class='status-row'><span class='" + cls + "'><strong" +
      " data-machine-status=\"" + escapeHtml(status) + "\"" +
      " title=\"기계 상태: " + escapeHtml(status) + "\">" +
      escapeHtml(statusPrimary) + "</strong> — " + passed + "/" + total +
      " 질문 통과</span></div>" +
      qs.map(function (q) {
        var qOk = q.passed;
        var qCls = qOk ? "ok" : "fail";
        var questionId = String(q.question_id || "");
        var original = String(q.question || "");
        var html =
          "<div class='status-row' data-question-id=\"" +
          escapeHtml(questionId) + "\"" +
          (original ? " title=\"원문: " + escapeHtml(original) + "\"" : "") +
          "><span class='" + qCls + "'>" +
          escapeHtml(questionId) + " " + (qOk ? "✓" : "✗") +
          "</span> <small>" + escapeHtml(competencyQuestionCopy(q)) +
          "</small></div>";
        if (!qOk && (q.missing || []).length > 0) {
          html += "<div class='muted'><small>누락: " +
            escapeHtml(JSON.stringify(q.missing.slice(0, 3))) +
            "</small></div>";
        }
        if (!qOk && (q.spurious || []).length > 0) {
          html += "<div class='muted'><small>과잉: " +
            escapeHtml(JSON.stringify(q.spurious.slice(0, 3))) +
            "</small></div>";
        }
        return html;
      }).join("");
  }

  /* -- Artifacts (문서·릴리스 열람): 산출물을 목록으로 -- */

  async function loadArtifacts() {
    var docsBody = $("#artifacts-docs");
    var releasesBox = $("#artifacts-releases");
    var empty = $("#artifacts-empty");
    var err = $("#artifacts-error");
    if (!docsBody) return;
    err.classList.add("hidden");
    empty.classList.add("hidden");
    docsBody.innerHTML =
      "<tr><td colspan='4' class='muted'>불러오는 중…</td></tr>";
    releasesBox.innerHTML =
      "<p class='muted artifact-empty-hint'>불러오는 중…</p>";
    try {
      var data = await api("/api/artifacts");
      var packs = ((await api("/api/packs")) || {}).packs || [];
      var byPack = {};
      packs.forEach(function (p) { byPack[p.pack_id] = p; });
      var artifacts = data.artifacts || [];
      var docs = artifacts.filter(function (a) { return a.kind === "source_doc"; });
      var releases = artifacts.filter(function (a) { return a.kind === "pack_release"; });
      docsBody.innerHTML = docs.map(function (a) {
        var title = plainDocumentTitle(
          a.title, a.source_uri || a.filename || (a.id || "").slice(0, 12)
        );
        return (
          "<tr>" +
          "<td>" + escapeHtml(title) + "</td>" +
          "<td class='copyable-identifier'><code title='" +
          escapeHtml(a.source_uri || "") + "'>" +
          escapeHtml(shortIdentifier(a.source_uri)) + "</code> " +
          (a.source_uri ? "<button type='button' class='btn-link' data-copy-identifier='" +
            escapeHtml(a.source_uri) + "' aria-label='전체 출처 URL 복사'>복사</button>" : "") +
          "</td>" +
          "<td>" + timeHtml(a.fetched_ts || a.created_ts) + "</td>" +
          "<td><button type='button' class='btn-link' data-open-doc='" +
          escapeHtml(a.source_doc_id || "") + "'>원문 열기</button></td>" +
          "</tr>"
        );
      }).join("");
      releasesBox.innerHTML = releases.map(function (a) {
        var pack = byPack[a.filename] || {};
        var counts = pack.counts || {};
        var hash = String(pack.content_hash || "");
        return (
          "<div class='artifact-pack-card status-box'>" +
          "<strong>" + escapeHtml(a.filename || (a.id || "").slice(0, 12)) + "</strong>" +
          "<div class='muted'><small>문서 " + (counts.documents || 0) +
          " · 개념 " + (counts.nodes_verified || 0) +
          " · 관계 " + (counts.edges_verified || 0) + "</small></div>" +
          "<code title='" + escapeHtml(hash) + "'>" +
          escapeHtml(hash.slice(0, 12) || "—") + "</code>" +
          "</div>"
        );
      }).join("");
      empty.classList.toggle("hidden", docs.length + releases.length > 0);
      // 한쪽 그룹만 비었을 때도 그 자리에 빈 상태를 알린다 — 둘 다 비었을
      // 때는 위의 전체 빈 상태 카드가 그 역할을 하므로 여기서는 중복하지
      // 않는다. 스모크 기준: "문서가 하나도 없거나 팩이 없어도 빈 채로
      // 멈추지 않는다".
      var hasAny = docs.length + releases.length > 0;
      if (docs.length === 0 && hasAny) {
        docsBody.innerHTML =
          "<tr><td colspan='4' class='muted'>수집한 문서가 없습니다 — " +
          "리서치로 문서를 수집합니다</td></tr>";
      }
      if (releases.length === 0 && hasAny) {
        releasesBox.innerHTML =
          "<p class='muted artifact-empty-hint'>빌드한 팩이 없습니다. " +
          "팩을 빌드하면 여기에 표시됩니다.</p>";
      }
    } catch (e) {
      docsBody.innerHTML = "";
      releasesBox.innerHTML = "";
      err.textContent = friendlyError(e) + retryHint(e);
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
        "<span class='ok-msg'>두 팩이 완전히 같습니다.</span> " +
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
      showResult(box, "비교할 팩 두 개를 선택해야 합니다.", true);
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
        errEl.textContent = uiUtils.errorText(res, "mcpb 번들 생성 실패");
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
    var allowIncomplete = $("#pack-allow-incomplete").checked;
    var overrideIntent = $("#pack-override-intent").value.trim();
    if (!name) {
      showResult(box, "팩 이름을 입력해야 합니다.", true);
      return;
    }
    if (allowIncomplete && !overrideIntent) {
      showResult(box, "미완료 추출을 허용하는 운영자 의도를 기록해야 합니다.", true);
      return;
    }
    btn.disabled = true;
    showResult(box, "<span class='muted'>팩 빌드 중…</span>");
    try {
      var res = await apiSend("/api/packs/build", {
        name: name,
        allow_incomplete_extraction: allowIncomplete,
        override_intent: allowIncomplete ? overrideIntent : null
      });
      if (res && res.ok) {
        var manifest = res.manifest || {};
        var counts = manifest.counts || {};
        showResult(
          box,
          "<span class='ok-msg'>팩을 만들었습니다.</span> <code>" +
            escapeHtml(manifest.pack_id || name) +
            "</code> · 문서 <code>" +
            escapeHtml(String(counts.documents || 0)) +
            "</code> · 개념 <code>" +
            escapeHtml(String(counts.nodes_verified || 0)) +
            "</code> · 관계 <code>" +
            escapeHtml(String(counts.edges_verified || 0)) +
            "</code> <button type='button' class='btn btn-primary'" +
            " data-goto='mcp'>연결 →</button>"
        );
        $("#pack-name").value = "";
        $("#pack-allow-incomplete").checked = false;
        $("#pack-override-intent").value = "";
        await loadPacks();
        await loadMcp();
      } else {
        showResult(box, escapeHtml(uiUtils.errorText(res, "팩 빌드 실패.")), true);
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
      $("#mcp-packs-dir").innerHTML = copyableMachineValueHtml((data && data.packs_dir) || "", "전체 팩 디렉터리 복사");
      var packs = (data && data.packs) || [];
      cards.innerHTML = "";
      packs.forEach(function (pack) {
        var counts = pack.counts || {};
        var card = document.createElement("div");
        card.className = "mcp-card";
        card.innerHTML =
          "<div class='row space-between'>" +
          "<strong><code>" + escapeHtml(pack.pack_id || "") + "</code></strong>" +
          "<span class='muted'>" + timeHtml(pack.created_ts) + "</span>" +
          "</div>" +
          "<p class='muted'>문서 " + escapeHtml(String(counts.documents || 0)) +
          " · 개념 " + escapeHtml(String(counts.nodes_verified || 0)) +
          " · 관계 " + escapeHtml(String(counts.edges_verified || 0)) +
          "</p>";
        var command = document.createElement("div");
        command.className = "mcp-command";
        command.innerHTML = "<span class='muted'>실행 명령</span> " +
          copyableMachineValueHtml(
            pack.serve_command || "", "전체 실행 명령 복사",
            shortMachineValue(pack.serve_command || "")
          );
        card.appendChild(command);
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
      renderUnusablePacks("mcp-unusable", "mcp-error", data && data.unusable);
    } catch (e) {
      renderUnusablePacks("mcp-unusable", "mcp-error", []);
      err.textContent = friendlyError(e) + retryHint(e);
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
          "<td><small class='muted' title='기계 값: " +
          escapeHtml(c.summary_method || "") + "'>" +
          escapeHtml(ontologyLabelKo(c.summary_method || "—")) + "</small></td>";
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
          "<td>" + escapeHtml(ontologyLabelKo(m.entity_type || "")) + "</td>" +
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
    var confirmed = await requestConfirmation({
      title: "승인된 관계를 무효화합니다",
      message: "관계는 삭제되지 않으며 더 이상 유효하지 않은 기록으로 남습니다.",
      confirmLabel: "관계 무효화",
      danger: true,
      invoker: document.activeElement,
    });
    if (!confirmed) return;
    var err = $("#entity-panel-error");
    err.classList.add("hidden");
    try {
      var res = await apiSend(
        "/api/edges/" + encodeURIComponent(edgeId) + "/invalidate",
        { note: "invalidated via dashboard" }
      );
      uiUtils.throwIfRefused(res);
      loadEntityPanel(entityId);
    } catch (e) {
      err.textContent = friendlyError(e) + retryHint(e);
      err.classList.remove("hidden");
    }
  }

  async function previewOntologyProposal(entityId, host) {
    host.textContent = "";
    var waiting = document.createElement("p");
    waiting.className = "muted";
    waiting.textContent = "온톨로지 제안을 만드는 중…";
    host.appendChild(waiting);

    var response;
    try {
      response = await apiSend("/api/ontology/proposals/preview", {
        source_ids: [entityId]
      });
    } catch (e) {
      host.textContent = friendlyError(e);
      return;
    }
    if (!response || !response.ok) {
      host.textContent = termErrorText(response);
      return;
    }
    var proposal = (response.proposals || [])[0];
    if (!proposal) {
      host.textContent = "검토할 제안이 없습니다.";
      return;
    }

    host.textContent = "";
    var summary = document.createElement("p");
    var title = document.createElement("strong");
    title.textContent = proposal.preferred_label || "";
    summary.appendChild(title);
    summary.appendChild(document.createTextNode(
      " · " + (proposal.action === "create" ? "새 용어" : "기존 용어 보강")
    ));
    host.appendChild(summary);

    var definition = document.createElement("p");
    definition.textContent = proposal.definition || "";
    host.appendChild(definition);
    if (Object.keys(proposal.qualifiers || {}).length) {
      var qualifiers = document.createElement("pre");
      qualifiers.className = "code-block";
      qualifiers.textContent = JSON.stringify(proposal.qualifiers, null, 2);
      host.appendChild(qualifiers);
    }

    var reviewer = document.createElement("input");
    reviewer.type = "text";
    reviewer.placeholder = "검토자";
    reviewer.setAttribute("aria-label", "온톨로지 제안 검토자");
    reviewer.setAttribute("data-ontology-proposal-reviewer", "");
    var provenance = document.createElement("input");
    provenance.type = "text";
    provenance.placeholder = "검토 출처";
    provenance.setAttribute("aria-label", "온톨로지 제안 검토 출처");
    provenance.setAttribute("data-ontology-proposal-provenance", "");
    var verify = document.createElement("button");
    verify.type = "button";
    verify.className = "btn btn-primary";
    verify.textContent = "사람이 확인하고 반영";
    verify.setAttribute("data-ontology-proposal-verify", proposal.id || "");
    host.appendChild(reviewer);
    host.appendChild(document.createTextNode(" "));
    host.appendChild(provenance);
    host.appendChild(document.createTextNode(" "));
    host.appendChild(verify);

    verify.addEventListener("click", async function () {
      var reviewerValue = reviewer.value.trim();
      var provenanceValue = provenance.value.trim();
      if (!reviewerValue || !provenanceValue) {
        var missing = document.createElement("p");
        missing.className = "err-msg";
        missing.textContent = "검토자와 검토 출처를 모두 입력해야 합니다.";
        host.appendChild(missing);
        return;
      }
      var confirmed = await requestConfirmation({
        title: "온톨로지 제안을 반영합니다",
        message: "사람 검토 기록과 함께 제안을 온톨로지에 반영합니다.",
        confirmLabel: "제안 반영",
        danger: false,
        invoker: verify,
      });
      if (!confirmed) return;
      verify.disabled = true;
      var applied;
      try {
        applied = await apiSend("/api/ontology/proposals/verify", {
          proposal: proposal,
          verification: {
            reviewer: reviewerValue,
            provenance: provenanceValue
          }
        });
      } catch (e) {
        host.textContent = friendlyError(e);
        return;
      } finally {
        verify.disabled = false;
      }
      if (!applied || !applied.ok) {
        host.textContent = termErrorText(applied);
        return;
      }
      host.textContent = "";
      var receipt = document.createElement("p");
      receipt.className = "ok-msg";
      receipt.textContent = "사람 검토를 기록하고 온톨로지에 반영했습니다.";
      host.appendChild(receipt);
      var identity = document.createElement("code");
      identity.textContent = (applied.term || {}).iri || (applied.term || {}).id || "";
      host.appendChild(identity);
      loadTerms((applied.term || {}).id || "");
    });
  }

  async function loadEntityPanel(entityId) {
    var panel = $("#entity-panel");
    var body = $("#entity-panel-body");
    var err = $("#entity-panel-error");
    err.classList.add("hidden");
    panel.classList.remove("hidden");
    // 자세히 보기는 같은 자리(우측 열)에서 근거 패널을 대신한다 — 두 패널이
    // 겹쳐 쌓이면 어느 쪽이 지금 항목인지 알 수 없다.
    $("#evidence-pane").classList.add("hidden");
    document.getElementById("tab-review").classList.add("inspector-open");
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
      " <small class='muted' title='기계 값: " +
      escapeHtml(ent.entity_type || "") + "'>" +
      escapeHtml(ontologyLabelKo(ent.entity_type || "")) +
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
          escapeHtml(
            plainDocumentTitle(
              m.doc_title,
              (m.source_doc_id || "").slice(0, 10)
            )
          ) +
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

    var proposalPanel = document.createElement("div");
    proposalPanel.className = "status-box";
    var proposalButton = document.createElement("button");
    proposalButton.type = "button";
    proposalButton.className = "btn";
    proposalButton.textContent = "온톨로지 제안 검토";
    proposalButton.setAttribute("data-ontology-proposal-preview", entityId);
    proposalButton.setAttribute("aria-label", "추출 항목을 온톨로지 제안으로 검토");
    var proposalResult = document.createElement("div");
    proposalResult.setAttribute("data-ontology-proposal-result", entityId);
    proposalPanel.appendChild(proposalButton);
    proposalPanel.appendChild(proposalResult);
    proposalButton.addEventListener("click", function () {
      proposalButton.disabled = true;
      previewOntologyProposal(entityId, proposalResult).finally(function () {
        proposalButton.disabled = false;
      });
    });
    body.appendChild(proposalPanel);
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
      "<br><small class='muted' title='기계 값: " +
      escapeHtml(node.entity_type || "") + "'>타입: " +
      escapeHtml(ontologyLabelKo(node.entity_type || "")) +
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
    var confirmed = await requestConfirmation({
      title: "중복 개념을 병합합니다",
      message: "원본 개념을 선택한 대표 개념으로 병합하고 계보를 기록합니다.",
      confirmLabel: "개념 병합",
      danger: true,
      invoker: document.activeElement,
    });
    if (!confirmed) return;
    actPending = true;
    var err = $("#merge-error");
    err.classList.add("hidden");
    try {
      var res = await apiSend(
        "/api/merge/candidates/" + encodeURIComponent(candidateId) + "/merge",
        { target_id: targetId, source_id: sourceId }
      );
      uiUtils.throwIfRefused(res);
      await loadMergeCandidates();
      await loadProposals();
    } catch (e) {
      err.textContent = friendlyError(e) + retryHint(e);
      err.classList.remove("hidden");
    } finally {
      actPending = false;
    }
  }

  async function mergeDismiss(candidateId) {
    if (actPending) return;
    var confirmed = await requestConfirmation({
      title: "중복 후보를 기각합니다",
      message: "이 개념 쌍을 중복이 아닌 것으로 기록합니다.",
      confirmLabel: "후보 기각",
      danger: true,
      invoker: document.activeElement,
    });
    if (!confirmed) return;
    actPending = true;
    var err = $("#merge-error");
    err.classList.add("hidden");
    try {
      var res = await apiSend(
        "/api/merge/candidates/" + encodeURIComponent(candidateId) + "/dismiss",
        {}
      );
      uiUtils.throwIfRefused(res);
      await loadMergeCandidates();
    } catch (e) {
      err.textContent = friendlyError(e) + retryHint(e);
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
      err.textContent = friendlyError(e) + retryHint(e);
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
        showResult(box, escapeHtml(uiUtils.errorText(res, "스캔 실패.")), true);
      }
    } catch (e) {
      showResult(box, escapeHtml(friendlyError(e)), true);
    } finally {
      btn.disabled = false;
    }
  });
  $("#merge-refresh-btn").addEventListener("click", loadMergeCandidates);

  /* -- Lazy loading + refresh wiring -- */

  /* -- 그래프 자유 탐색 (읽기 전용 — 결정은 항상 ② 검토에서) ---------- */

  var SVG_NS = "http://www.w3.org/2000/svg";
  var gNodes = [];            // {id,name,entity_type,status,x,y,vx,vy,fx,fy}
  var gEdges = [];            // {source,target,relation_type,status} (id 참조)
  var gIndex = {};            // id -> node
  var gDegree = {};           // id -> degree
  var gSelected = null;
  var gAlpha = 0;             // 시뮬레이션 온도 (0이면 정지)
  var gRaf = null;
  var gView = { x: 0, y: 0, k: 1 };
  var gTypeColor = {};
  var graphLoadedOnce = false;
  var gFitPending = false;    // 배치가 가라앉으면 한 번 화면에 맞출지 여부
                              // (사용자가 팬/줌하면 취소된다)

  function graphPalette() {
    var css = getComputedStyle(document.documentElement);
    var out = [];
    for (var i = 1; i <= 5; i++) {
      var v = css.getPropertyValue("--chart-" + i).trim();
      if (v) out.push(v);
    }
    return out.length ? out : ["#5b5bd6"];
  }

  function typeColor(type) {
    if (!gTypeColor[type]) {
      var palette = graphPalette();
      var idx = Object.keys(gTypeColor).length % palette.length;
      gTypeColor[type] = palette[idx];
    }
    return gTypeColor[type];
  }

  function graphSize() {
    var svg = $("#graph-svg");
    var rect = svg.getBoundingClientRect();
    return { w: rect.width || 900, h: rect.height || 520 };
  }

  function mergeGraphData(data, anchor) {
    // anchor가 있으면 새 노드를 그 근처에 흩뿌려 확장이 자연스럽게 보이게
    var size = graphSize();
    var cx = anchor ? anchor.x : size.w / 2;
    var cy = anchor ? anchor.y : size.h / 2;
    (data.nodes || []).forEach(function (n) {
      if (gIndex[n.id]) return;
      var node = {
        id: n.id,
        name: n.name || n.id.slice(0, 8),
        entity_type: n.entity_type || "?",
        status: n.status || "proposed",
        confidence: n.confidence,
        x: cx + (Math.random() - 0.5) * (anchor ? 90 : size.w * 0.7),
        y: cy + (Math.random() - 0.5) * (anchor ? 90 : size.h * 0.7),
        vx: 0,
        vy: 0,
      };
      gIndex[n.id] = node;
      gNodes.push(node);
    });
    var seen = {};
    gEdges.forEach(function (e) { seen[e.id] = true; });
    (data.edges || []).forEach(function (e) {
      if (seen[e.id]) return;
      // 양 끝이 화면에 있는 엣지만 (traverse가 limit로 끊겼을 때 대비)
      if (!gIndex[e.source_id] || !gIndex[e.target_id]) return;
      gEdges.push({
        id: e.id,
        source: e.source_id,
        target: e.target_id,
        relation_type: e.relation_type,
        status: e.status,
      });
    });
    gDegree = {};
    gEdges.forEach(function (e) {
      gDegree[e.source] = (gDegree[e.source] || 0) + 1;
      gDegree[e.target] = (gDegree[e.target] || 0) + 1;
    });
  }

  function graphTick() {
    var size = graphSize();
    var i, j, a, b, dx, dy, d2, d, f;
    // 반발 (O(n²) — limit 500 노드 스코프에선 충분)
    for (i = 0; i < gNodes.length; i++) {
      for (j = i + 1; j < gNodes.length; j++) {
        a = gNodes[i]; b = gNodes[j];
        dx = b.x - a.x; dy = b.y - a.y;
        d2 = dx * dx + dy * dy;
        if (d2 < 1) { dx = Math.random() - 0.5; dy = Math.random() - 0.5; d2 = 1; }
        if (d2 > 160000) continue; // 400px 밖은 무시
        f = 1400 / d2;
        d = Math.sqrt(d2);
        a.vx -= (dx / d) * f; a.vy -= (dy / d) * f;
        b.vx += (dx / d) * f; b.vy += (dy / d) * f;
      }
    }
    // 엣지 스프링 (자연 길이 90)
    gEdges.forEach(function (e) {
      var s = gIndex[e.source], t = gIndex[e.target];
      if (!s || !t) return;
      var ex = t.x - s.x, ey = t.y - s.y;
      var ed = Math.sqrt(ex * ex + ey * ey) || 1;
      var force = (ed - 90) * 0.02;
      s.vx += (ex / ed) * force; s.vy += (ey / ed) * force;
      t.vx -= (ex / ed) * force; t.vy -= (ey / ed) * force;
    });
    // 중심 중력 + 적분
    gNodes.forEach(function (n) {
      n.vx += (size.w / 2 - n.x) * 0.002;
      n.vy += (size.h / 2 - n.y) * 0.002;
      if (n.fx != null) { n.x = n.fx; n.y = n.fy; n.vx = 0; n.vy = 0; return; }
      n.vx *= 0.85; n.vy *= 0.85;
      n.x += n.vx * gAlpha; n.y += n.vy * gAlpha;
    });
    gAlpha *= 0.985;
  }

  function graphNodeRadius(n) {
    return Math.min(16, 6 + 1.6 * Math.sqrt(gDegree[n.id] || 0));
  }

  function drawGraph() {
    var svg = $("#graph-svg");
    svg.innerHTML = "";
    var root = document.createElementNS(SVG_NS, "g");
    root.setAttribute("id", "graph-root");
    svg.appendChild(root);
    var edgeGroup = document.createElementNS(SVG_NS, "g");
    var nodeGroup = document.createElementNS(SVG_NS, "g");
    root.appendChild(edgeGroup);
    root.appendChild(nodeGroup);
    gEdges.forEach(function (e) {
      var line = document.createElementNS(SVG_NS, "line");
      line.setAttribute("class", "g-edge" + (e.status === "verified" ? " g-edge-verified" : ""));
      line.dataset.source = e.source;
      line.dataset.target = e.target;
      var title = document.createElementNS(SVG_NS, "title");
      title.textContent = e.relation_type + " (" + statusKo(e.status) + ")";
      line.appendChild(title);
      edgeGroup.appendChild(line);
    });
    gNodes.forEach(function (n) {
      var g = document.createElementNS(SVG_NS, "g");
      g.setAttribute("class", "g-node" + (n.status === "verified" ? " g-verified" : " g-proposed"));
      g.setAttribute("role", "button");
      g.setAttribute("tabindex", "0");
      g.setAttribute("aria-label", ontologyLabelKo(n.name) + " · " +
        ontologyLabelKo(n.entity_type) + " · " + statusKo(n.status));
      g.dataset.id = n.id;
      var hit = document.createElementNS(SVG_NS, "circle");
      hit.setAttribute("class", "g-hit-target");
      hit.setAttribute("r", Math.max(22, graphNodeRadius(n) + 8));
      var circle = document.createElementNS(SVG_NS, "circle");
      circle.setAttribute("r", graphNodeRadius(n));
      circle.setAttribute("fill", typeColor(n.entity_type));
      var label = document.createElementNS(SVG_NS, "text");
      label.setAttribute("dy", graphNodeRadius(n) + 11);
      label.setAttribute("class", "g-label");
      label.textContent = ontologyLabelKo(n.name);
      var title = document.createElementNS(SVG_NS, "title");
      title.textContent =
        ontologyLabelKo(n.name) + " · " + ontologyLabelKo(n.entity_type) +
        " · " + statusKo(n.status);
      g.appendChild(title);
      g.appendChild(hit);
      g.appendChild(circle);
      g.appendChild(label);
      nodeGroup.appendChild(g);
    });
    renderGraphLegend();
    applyGraphSearch();
    positionGraph();
  }

  function positionGraph() {
    var root = document.getElementById("graph-root");
    if (!root) return;
    root.setAttribute(
      "transform",
      "translate(" + gView.x + "," + gView.y + ") scale(" + gView.k + ")"
    );
    var lines = root.querySelectorAll("line");
    lines.forEach(function (line) {
      var s = gIndex[line.dataset.source], t = gIndex[line.dataset.target];
      if (!s || !t) return;
      line.setAttribute("x1", s.x); line.setAttribute("y1", s.y);
      line.setAttribute("x2", t.x); line.setAttribute("y2", t.y);
    });
    root.querySelectorAll("g.g-node").forEach(function (g) {
      var n = gIndex[g.dataset.id];
      if (!n) return;
      g.setAttribute("transform", "translate(" + n.x + "," + n.y + ")");
      g.classList.toggle("g-selected", gSelected === n.id);
      var label = g.querySelector(".g-label");
      if (label) {
        label.style.fontSize =
          uiUtils.graphLabelFontSize(gView.k) + "px";
        label.setAttribute(
          "dy",
          graphNodeRadius(n) + 12 / Math.max(0.05, gView.k)
        );
      }
    });
    var visibleLabels = new Set(uiUtils.visibleGraphLabelIds(
      gNodes.map(function (n) {
        return {
          id: n.id,
          name: n.name,
          x: n.x,
          y: n.y,
          degree: gDegree[n.id] || 0,
        };
      }),
      gView,
      graphSize(),
      gSelected
    ));
    root.querySelectorAll("g.g-node").forEach(function (g) {
      var label = g.querySelector(".g-label");
      if (label) {
        label.classList.toggle("hidden", !visibleLabels.has(g.dataset.id));
      }
    });
  }

  function graphLoop() {
    // 탭이 숨겨지면(display:none → rect 0) 시뮬레이션을 멈춰 좌표 드리프트
    // 방지 — 돌아와서 드래그/새로고침하면 reheatGraph가 다시 돌린다.
    if ($("#graph-svg").getBoundingClientRect().width === 0) {
      gRaf = null;
      return;
    }
    if (gAlpha > 0.02) {
      graphTick();
      positionGraph();
      gRaf = requestAnimationFrame(graphLoop);
    } else {
      // 배치가 가라앉으면 한 번만 화면에 맞춘다. 스프링 길이가 90px로
      // 고정이라, 캔버스가 커도 그래프는 가운데 작게 뭉쳐 있고 나머지가
      // 통째로 빈 채로 남았다.
      if (gFitPending) { gFitPending = false; fitGraphToView(); }
      gRaf = null;
    }
  }

  /* 노드 바운딩 박스를 캔버스에 맞춰 gView(팬/줌)를 다시 잡는다.
     드래그·휠이 쓰는 것과 같은 gView를 갱신하므로 좌표 변환이 어긋나지
     않는다 — SVG에 viewBox나 CSS transform을 더하면 그 둘이 깨진다. */
  function fitGraphToView() {
    var nodes = Object.keys(gIndex).map(function (id) { return gIndex[id]; });
    if (nodes.length === 0) return;
    // graphSize()는 rect가 0일 때 900x520 대체값을 채워 주므로 그 반환값으로는
    // '보이지 않는 상태'를 알 수 없다. 실제 rect를 직접 본다.
    if ($("#graph-svg").getBoundingClientRect().width === 0) return;
    var size = graphSize();
    var minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    nodes.forEach(function (n) {
      if (typeof n.x !== "number" || typeof n.y !== "number") return;
      if (n.x < minX) minX = n.x;
      if (n.x > maxX) maxX = n.x;
      if (n.y < minY) minY = n.y;
      if (n.y > maxY) maxY = n.y;
    });
    if (!isFinite(minX) || !isFinite(minY)) return;
    var pad = 64;                       // 라벨이 잘리지 않도록 여백
    var w = Math.max(maxX - minX, 1), h = Math.max(maxY - minY, 1);
    var k = Math.min((size.w - pad * 2) / w, (size.h - pad * 2) / h);
    // 휠 줌 범위[0.2, 4]보다 상한을 좁게 — 노드가 서너 개뿐일 때 화면을
    // 꽉 채우겠다고 과확대되면 오히려 맥락이 사라진다.
    k = Math.min(1.6, Math.max(0.2, k));
    gView.k = k;
    gView.x = size.w / 2 - ((minX + maxX) / 2) * k;
    gView.y = size.h / 2 - ((minY + maxY) / 2) * k;
    positionGraph();
  }

  function reheatGraph(alpha) {
    gAlpha = Math.max(gAlpha, alpha);
    if (!gRaf) gRaf = requestAnimationFrame(graphLoop);
  }

  function renderGraphLegend() {
    var box = $("#graph-legend");
    var html = "";
    Object.keys(gTypeColor).forEach(function (type) {
      html +=
        "<span class='g-chip'><i style='background:" + gTypeColor[type] +
        "'></i>" + escapeHtml(ontologyLabelKo(type)) + "</span>";
    });
    // 링 색은 앱 전체의 상태 언어와 같다(호박=제안, 초록=검증됨). 범례가
    // 그 둘을 다 보여줘야 그래프만 보고도 무엇이 아직 승인 전인지 안다.
    html +=
      "<span class='g-chip g-chip-hint'><i class='g-chip-ring g-chip-proposed'></i>" +
      "점선 테두리 = 제안(미검증)</span>" +
      "<span class='g-chip g-chip-hint'><i class='g-chip-ring g-chip-verified'></i>" +
      "실선 테두리 = 승인됨</span>";
    box.innerHTML = html;
  }

  function graphStats() {
    $("#graph-stats").textContent =
      "노드 " + gNodes.length + " · 엣지 " + gEdges.length;
  }

  function selectGraphNode(id) {
    gSelected = id;
    var info = $("#graph-info");
    if (!id) { info.classList.add("hidden"); positionGraph(); return; }
    var n = gIndex[id];
    $("#graph-info-name").textContent = ontologyLabelKo(n.name);
    $("#graph-info-meta").textContent =
      ontologyLabelKo(n.entity_type) + " · " + statusKo(n.status) +
      (n.confidence == null ? "" : " · 확신도 " + Number(n.confidence).toFixed(2)) +
      " · 연결 " + (gDegree[id] || 0) + "개";
    info.classList.remove("hidden");
    positionGraph();
  }

  function activateGraphNode(id) {
    if (!gIndex[id]) return;
    selectGraphNode(id);
  }

  async function expandGraphNode(id) {
    var anchor = gIndex[id];
    if (!anchor) return;
    var err = $("#graph-error");
    err.classList.add("hidden");
    try {
      var verifiedOnly = $("#graph-status").value === "verified";
      var data = await api(
        "/api/graph/neighbors/" + encodeURIComponent(id) +
        "?hops=1&include_proposed=" + (verifiedOnly ? "false" : "true")
      );
      mergeGraphData(data, anchor);
      drawGraph();
      graphStats();
      reheatGraph(0.6);
    } catch (e) {
      err.textContent = friendlyError(e) + retryHint(e);
      err.classList.remove("hidden");
    }
  }

  function applyGraphSearch() {
    var q = $("#graph-search").value.trim().toLowerCase();
    var root = document.getElementById("graph-root");
    if (!root) return;
    root.querySelectorAll("g.g-node").forEach(function (g) {
      var n = gIndex[g.dataset.id];
      var hit = !q || (n && n.name.toLowerCase().indexOf(q) !== -1);
      g.classList.toggle("g-dim", Boolean(q) && !hit);
    });
  }

  async function loadGraph() {
    var err = $("#graph-error");
    err.classList.add("hidden");
    var verifiedOnly = $("#graph-status").value === "verified";
    var type = $("#graph-type").value;
    var url =
      "/api/graph?limit=200&include_proposed=" + (verifiedOnly ? "false" : "true") +
      (type ? "&entity_type=" + encodeURIComponent(type) : "");
    try {
      var data = await api(url);
      gNodes = []; gEdges = []; gIndex = {}; gDegree = {};
      gSelected = null; gView = { x: 0, y: 0, k: 1 }; gTypeColor = {};
      gFitPending = true;   // 이번 배치가 가라앉으면 화면에 맞춘다
      $("#graph-info").classList.add("hidden");
      var empty = !(data.nodes || []).length;
      $("#graph-empty").classList.toggle("hidden", !empty);
      $("#graph-wrap").classList.toggle("hidden", empty);
      if (empty) { $("#graph-stats").textContent = ""; return; }
      mergeGraphData(data, null);
      // 타입 필터 옵션 채우기 (전체 로드시에만 — 필터 적용 중엔 유지)
      if (!type) {
        var sel = $("#graph-type");
        var current = sel.value;
        sel.innerHTML = "<option value=''>전체</option>";
        Object.keys(
          gNodes.reduce(function (acc, n) { acc[n.entity_type] = 1; return acc; }, {})
        ).sort().forEach(function (t) {
          var opt = document.createElement("option");
          opt.value = t; opt.textContent = ontologyLabelKo(t);
          sel.appendChild(opt);
        });
        sel.value = current || "";
      }
      drawGraph();
      graphStats();
      reheatGraph(1);
    } catch (e) {
      err.textContent = friendlyError(e) + retryHint(e);
      err.classList.remove("hidden");
    }
  }

  (function wireGraph() {
    var svg = $("#graph-svg");
    var dragNode = null, panStart = null, downAt = null;

    svg.addEventListener("pointerdown", function (ev) {
      downAt = { x: ev.clientX, y: ev.clientY };
      var g = ev.target.closest("g.g-node");
      if (g) {
        dragNode = gIndex[g.dataset.id];
        if (dragNode) { dragNode.fx = dragNode.x; dragNode.fy = dragNode.y; }
      } else {
        panStart = { px: ev.clientX, py: ev.clientY, vx: gView.x, vy: gView.y };
      }
      try { svg.setPointerCapture(ev.pointerId); } catch (_) {}
    });
    svg.addEventListener("pointermove", function (ev) {
      if (dragNode) {
        var rect = svg.getBoundingClientRect();
        dragNode.fx = (ev.clientX - rect.left - gView.x) / gView.k;
        dragNode.fy = (ev.clientY - rect.top - gView.y) / gView.k;
        reheatGraph(0.35);
      } else if (panStart) {
        gView.x = panStart.vx + (ev.clientX - panStart.px);
        gView.y = panStart.vy + (ev.clientY - panStart.py);
        // 사용자가 직접 시야를 잡았으면 자동 맞춤을 취소한다. 배치가
        // 가라앉기까지 4초 남짓 걸리는데, 그 사이(혹은 탭을 옮겼다 와서
        // 대기 중이던 fit이 살아있을 때) 맞춰 둔 화면이 튕겨 나갔다.
        gFitPending = false;
        positionGraph();
      }
    });
    svg.addEventListener("pointerup", function (ev) {
      // movementX/Y는 pointerup에서 신뢰 불가 — 시작 좌표와의 거리로 판정
      var moved = downAt
        ? Math.abs(ev.clientX - downAt.x) + Math.abs(ev.clientY - downAt.y)
        : 0;
      if (dragNode) {
        var id = dragNode.id;
        dragNode.fx = null; dragNode.fy = null;
        dragNode = null;
        if (moved < 4) selectGraphNode(id); // 클릭으로 간주
      }
      panStart = null;
      downAt = null;
    });
    svg.addEventListener("dblclick", function (ev) {
      var g = ev.target.closest("g.g-node");
      if (g) { ev.preventDefault(); expandGraphNode(g.dataset.id); }
    });
    svg.addEventListener("keydown", function (ev) {
      if (ev.key !== "Enter" && ev.key !== " ") return;
      var g = ev.target.closest("g.g-node");
      if (!g) return;
      ev.preventDefault();
      activateGraphNode(g.dataset.id);
    });
    svg.addEventListener("wheel", function (ev) {
      ev.preventDefault();
      var rect = svg.getBoundingClientRect();
      var mx = ev.clientX - rect.left, my = ev.clientY - rect.top;
      var k2 = Math.min(4, Math.max(0.2, gView.k * Math.exp(-ev.deltaY * 0.0015)));
      gFitPending = false;          // 팬과 같은 이유 — 직접 잡은 배율을 지키다
      // 커서 아래 지점을 고정한 채 스케일
      gView.x = mx - ((mx - gView.x) / gView.k) * k2;
      gView.y = my - ((my - gView.y) / gView.k) * k2;
      gView.k = k2;
      positionGraph();
    }, { passive: false });

    $("#graph-refresh-btn").addEventListener("click", loadGraph);
    $("#graph-status").addEventListener("change", loadGraph);
    $("#graph-type").addEventListener("change", loadGraph);
    $("#graph-search").addEventListener("input", applyGraphSearch);
    $("#graph-info-close").addEventListener("click", function () {
      selectGraphNode(null);
    });
    $("#graph-expand-btn").addEventListener("click", function () {
      if (gSelected) expandGraphNode(gSelected);
    });
    $("#graph-review-btn").addEventListener("click", function () {
      if (!gSelected) return;
      var id = gSelected;
      document.querySelector('.tab-btn[data-tab="review"]').click();
      loadEntityPanel(id);
    });
  })();

  var tabLoaders = {
    review: function () {
      loadAnnotations();
      return loadProposals();
    },
    merge: loadMergeCandidates,
    // 수집과 추출이 한 화면이 되면서 두 로더도 하나가 된다. 둘 중 하나만
    // 돌면 화면 절반이 비어 있게 되므로 항상 같이 부른다.
    sources: function () {
      if (!paperSourcesLoaded) {
        paperSourcesLoaded = true;
        populatePaperSourceSelect();
      }
      if (!extractEnginesLoaded) {
        extractEnginesLoaded = true;
        populateEngineSelect("#extract-engine");
        populateEngineSelect("#research-engine");
      }
      return Promise.all([loadDocuments(), loadJobs(), renderFanout(null)]);
    },
    // 소스 키 UI가 설정으로 옮겨 왔다. loadSources는 표와 셀렉트만 채우고
    // 설정 폼 입력값은 건드리지 않으므로 "입력 중 GET 덮어쓰기" 예외와
    // 충돌하지 않는다.
    settings: loadSources,
    packs: loadPacks,
    artifacts: loadArtifacts,
    mcp: loadMcp,
    communities: loadCommunities,
    graph: function () {
      // 첫 진입에만 자동 로드 — 재진입 시 탐색 상태(뷰·선택) 유지,
      // 갱신은 새로고침 버튼으로 명시적으로
      if (!graphLoadedOnce) {
        graphLoadedOnce = true;
        return loadGraph();
      }
    },
    engines: loadEngines,
  };

  // 탭을 열 때마다 새로 로드 — 로컬 API라 비용이 없고, 다른 탭에서
  // 바꾼 데이터가 낡은 화면으로 남는 것(거짓 상태)을 막는다.
  // (settings는 입력 중 값이 GET으로 덮이지 않게 제외)
  // loadHome()은 매 전환마다 호출해 상단 크롬(스트립·지금 할 일·배지)을
  // 신선하게 유지한다 — 자체 catch가 있어 서버 다운도 내비를 깨지 않음.
  function maybeLoadTab(name) {
    var panel = document.querySelector(
      '.tab-panel[data-tab-panel="' + name + '"]'
    );
    if (panel) {
      panel.dataset.loadState = "loading";
      panel.setAttribute("aria-busy", "true");
    }
    var loader = name === "home" ? loadHome : tabLoaders[name];
    var primary = loader
      ? Promise.resolve().then(loader)
      : Promise.resolve();
    var chrome = name === "home"
      ? Promise.resolve()
      : Promise.resolve().then(loadHome);
    return Promise.all([primary, chrome]).finally(function () {
      if (!panel) return;
      panel.dataset.loadState = "settled";
      panel.setAttribute("aria-busy", "false");
    });
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
    // 이미 그 화면에 서 있으면 안내하지 않는다 — ② 검토 화면에서
    // "② 검토로 가기" 버튼이 떠 있는 건 화면 안의 같은 동작과 중복이다.
    box.classList.toggle("hidden", document.body.dataset.activeTab === gotoTab);
  }

  var HOME_STATS = [
    "#stat-sources", "#stat-packs", "#stat-mcp",
  ];

  function setStat(sel, text, state) {
    var el = $(sel);
    if (!el) return;
    el.textContent = text;
    // `step-stat`은 파이프라인 바와 함께 사라진 클래스다. 그대로 뒀다면
    // 값은 바뀌는데 스타일이 없어 레일에서 본문 크기로 튀었을 것이다.
    el.className = "nav-stat" + (state ? " " + state : "");
  }

  /* -- 홈은 이제 대화다. 여기 있던 현황판 렌더러(검토 큐 미리보기, 실행
        목록, KPI 네 칸)는 그리던 DOM과 함께 지웠다 — 셋 다 자기 화면이
        따로 있어서, 같은 값을 두 번째로 그리던 코드였다.

        loadHome()은 남는다: 레일의 개수, 검토 배지, 상태바, "다음 할 일"
        칩은 화면과 무관하게 계속 갱신돼야 한다. -- */

  async function loadHome(options) {
    var homeErr = $("#home-error");
    if (homeErr && (!options || options.render !== false)) {
      homeErr.classList.add("hidden");
    }
    try {
      // counts 하나만 쓴다. 목록은 검토 화면이 자기 정렬로 다시 받아간다.
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
      // 수집과 추출이 한 단계가 되면서 이 칸도 둘을 같이 말해야 한다.
      // 진행 여부는 '작업 이력'이 아니라 '제안이 존재하는가'로 판정한다.
      // 작업 이력은 서버가 재시작되면 비므로, 이력만 보면 제안 15건이
      // 쌓여 있는데도 "아직 없음"이라고 말하게 된다 — 실제로 홈의 ✓ 체크와
      // 파이프라인 바가 같은 화면에서 서로 반대를 주장했다.
      var extracted = pending + verified > 0;
      // 사이드바 항목 옆의 개수는 Claude Science의 `2 sessions`와 같은
      // 자리다 — 숫자 하나. 파이프라인 바가 있던 시절의 "문서 5개 · 제안
      // 있음"은 가로 폭이 남아돌 때의 문장이라 레일에서는 잘린다.
      setStat(
        "#stat-sources",
        running ? "진행 중" : docs ? String(docs) : "",
        running || !docs || !extracted ? "is-todo" : "is-ok"
      );
      // 검토 개수는 tab-badge가 이미 말한다 (updateReviewBadge).
      setStat("#stat-packs", packs.length ? String(packs.length) : "",
        packs.length ? "is-ok" : "is-todo");
      setStat("#stat-mcp", packs.length ? "가능" : "",
        packs.length ? "is-ok" : "is-todo");

      // 상태바 오른쪽: 저장소가 지금 어떤 상태인지 한 줄로. 어느 화면에
      // 있든 같은 자리에서 읽히므로 탭을 옮겨 확인할 필요가 없다.
      var storeEl = document.getElementById("statusbar-store");
      if (storeEl) {
        storeEl.textContent =
          "문서 " + docs + " · 대기 " + pending +
          " · 승인 " + verified + " · 팩 " + packs.length;
      }

      // 다음 할 일 — 헤더 칩 하나. 문장은 홈 현황판이 대신 말하므로
      // 여기는 동작 이름과 숫자만 남긴다.
      if (docs === 0) {
        setNextAction("먼저 문서를 넣기", "sources", "리서치 →");
      } else if (pending > 0) {
        setNextAction("제안 대기", "review", "검토 " + pending + " →");
      } else if (running) {
        setNextAction("실행 중", "sources", "실행 보기 →");
      } else if (verified === 0) {
        setNextAction("추출부터", "sources", "리서치 →");
      } else if (packs.length === 0) {
        setNextAction("승인분 묶기", "packs", "팩 빌드 →");
      } else {
        setNextAction("팩 준비됨", "mcp", "연결 →");
      }
      return { recovered: true };
    } catch (error) {
      $("#next-action").classList.add("hidden");
      if (homeErr && (!options || options.render !== false)) {
        renderErrorSurface(homeErr, error, {
          retry: function () { return loadHome({ render: false }); },
        });
      }
      HOME_STATS.forEach(function (sel) { setStat(sel, "확인 불가"); });
      return { recovered: false, error: error };
    }
  }

  // 홈 스텝 카드·"다음 단계" 링크·빈 상태 버튼의 탭 점프 (이벤트 위임)
  document.addEventListener("click", function (ev) {
    var focus = ev.target.closest("[data-focus-target]");
    if (focus) {
      var field = document.getElementById(focus.dataset.focusTarget);
      if (field) field.focus();
      return;
    }
    var click = ev.target.closest("[data-empty-click]");
    if (click) {
      var control = document.querySelector(click.dataset.emptyClick);
      if (control) control.click();
      return;
    }
    var target = ev.target.closest("[data-goto]");
    if (!target) return;
    var tab = target.dataset.goto;
    showTab(tab);
    maybeLoadTab(tab);
  });

  $("#sources-refresh-btn").addEventListener("click", loadDocuments);
  $("#jobs-refresh-btn").addEventListener("click", loadJobs);
  $("#packs-refresh-btn").addEventListener("click", loadPacks);
  $("#artifacts-refresh-btn").addEventListener("click", loadArtifacts);
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
  $("#entity-panel-close").addEventListener("click", function () {
    $("#entity-panel").classList.add("hidden");
    $("#evidence-pane").classList.remove("hidden");
    document.getElementById("tab-review").classList.remove("inspector-open");
  });

  /* -- 문서 패널 -----------------------------------------------------------
     제안을 승인한다는 건 "논문이 정말 그렇게 말했나"를 판정하는 일이다.
     그 질문은 근거 span 앞뒤 160자로는 절반만 답할 수 있다 — 그 창으로는
     한 문장이 맞는지는 보여도, 열한 개 제안이 전부 같은 문단에서 나왔다는
     것이나 저자가 바로 다음 줄에서 "관찰되지 않았다"고 적었다는 것은 보이지
     않는다. 그래서 원문 전체를 옆에 띄우고, 그 안에서 근거를 표시한다.

     서버는 텍스트와 오프셋만 준다. 마크업을 서버가 만들면 문서가 어떻게
     생겼는지를 서버가 정하게 되고, 그건 이 패널이 하는 일이다. */

  var docTabs = [];        // [{id, title, data, error}]
  var docActive = null;

  /* 근거는 서로 겹친다 — 관계의 근거 문장이 그 관계에 나오는 개념의 근거를
     통째로 품는 일이 흔하다. "겹치면 앞엣것만 칠한다"는 규칙은 태그가
     교차하지 않게 해주지만 실제로 근거의 3분의 1을 지웠다. 화면에서 사라진
     근거는 검토자가 확인할 수 없는 근거다.

     그래서 구간을 경계마다 쪼갠다. 각 조각은 그 지점에서 살아 있는 근거를
     전부 `data-items`에 달고 다니므로 아무것도 버려지지 않고, 태그도 겹치지
     않는다. 색은 가장 안쪽(가장 늦게 시작한) 근거의 상태를 쓴다 — 가장 좁은
     범위가 그 글자에 대해 가장 구체적인 주장이다. */
  function markSpans(text, items) {
    var spans = items.filter(function (i) {
      return i.span && i.span.end > i.span.start;
    }).map(function (i) {
      return { s: i.span.start, e: i.span.end, item: i };
    });
    var dropped = items.filter(function (i) { return i.span; }).length -
      spans.length;
    if (!spans.length) return { html: escapeHtml(text), dropped: dropped };

    var cuts = {};
    spans.forEach(function (sp) { cuts[sp.s] = true; cuts[sp.e] = true; });
    var points = Object.keys(cuts).map(Number).sort(function (a, b) {
      return a - b;
    });
    var out = escapeHtml(text.slice(0, points[0]));
    for (var k = 0; k < points.length - 1; k++) {
      var from = points[k], to = points[k + 1];
      var here = spans.filter(function (sp) {
        return sp.s <= from && sp.e >= to;
      });
      var piece = escapeHtml(text.slice(from, to));
      if (!here.length) { out += piece; continue; }
      var inner = here.reduce(function (a, b) { return b.s >= a.s ? b : a; });
      out += "<mark class='doc-span st-" + escapeHtml(inner.item.status) +
        "' data-items='" + escapeHtml(here.map(function (h) {
          return h.item.id;
        }).join(" ")) + "'>" + piece + "</mark>";
    }
    out += escapeHtml(text.slice(points[points.length - 1]));
    return { html: out, dropped: dropped };
  }

  function renderDocBody(d) {
    var marked = markSpans(d.text || "", d.items || []);
    var notes = [];
    if (d.truncated) {
      notes.push("문서가 길어 앞부분 " + (d.text || "").length.toLocaleString() +
        "자만 보여요 (전체 " + (d.total_chars || 0).toLocaleString() + "자).");
    }
    if (marked.dropped) {
      notes.push("근거 " + marked.dropped + "개는 범위가 비어 있어 표시하지 못했습니다.");
    }
    var unplaced = (d.items || []).filter(function (i) { return !i.span; }).length;
    if (unplaced) {
      // 근거 없는 제안은 추출기가 경고와 함께 낸 것이다. 조용히 목록에만
      // 두면 "본문 어딘가에 있는데 못 찾은 것"처럼 읽힌다.
      notes.push("제안 " + unplaced + "개는 본문에 근거 문장이 없습니다. 검토 시 주의합니다.");
    }
    var uri = d.source_uri || "";
    return "<div class='doc-meta'>" +
        "<h2>" + escapeHtml(plainDocumentTitle(d.title)) + "</h2>" +
      "<p class='muted'><small>" + escapeHtml(d.source_kind || "") +
      (uri ? " · <code title='" + escapeHtml(uri) + "'>" +
        escapeHtml(shortIdentifier(uri)) + "</code>" : "") +
      " · " + timeHtml(d.fetched_ts) + "</small></p>" +
      "</div>" +
      (d.items && d.items.length
        ? "<ul class='doc-items'>" + d.items.map(function (i) {
            return "<li><button type='button' class='doc-item'" +
              " data-item='" + escapeHtml(i.id) + "'" +
              (i.span ? "" : " disabled title='이 제안에는 원문 근거 문장이 없습니다'") +
              ">" + escapeHtml(i.label || "") + "</button> " +
              "<code>" + escapeHtml(i.type || "") + "</code> " +
              statusBadge(i.status) + "</li>";
          }).join("") + "</ul>"
        : "<p class='muted'>이 문서에서 생성된 제안이 없습니다.</p>") +
      notes.map(function (n) {
        return "<p class='muted'><small>" + escapeHtml(n) + "</small></p>";
      }).join("") +
      "<pre class='doc-text'>" + marked.html + "</pre>";
  }

  function renderDocPanel() {
    var panel = $("#doc-panel");
    if (!panel) return;
    if (!docTabs.length) {
      panel.classList.add("hidden");
      $("#doc-tabs").innerHTML = "";
      $("#doc-body").innerHTML = "";
      return;
    }
    panel.classList.remove("hidden");
    $("#doc-tabs").innerHTML = docTabs.map(function (t) {
      var on = t.id === docActive;
      return "<button type='button' class='doc-tab" + (on ? " active" : "") +
        "' role='tab' aria-selected='" + on + "' data-doc-tab='" +
          escapeHtml(t.id) + "'>" +
          escapeHtml(plainDocumentTitle(t.title)) + "</button>";
    }).join("");
    var cur = docTabs.filter(function (t) { return t.id === docActive; })[0];
    $("#doc-body").innerHTML = !cur ? ""
      : cur.error ? "<p class='err-msg'>" + escapeHtml(cur.error) + "</p>"
      : renderDocBody(cur.data);
  }

  // 특정 근거로 스크롤한 뒤 잠깐 표시한다. 제안 40개가 달린 문서에서
  // "이 제안"을 눈으로 찾게 두면 패널을 연 의미가 없다.
  function revealDocItem(itemId) {
    if (!itemId) return;
    var body = $("#doc-body");
    // 근거가 없는 제안(모델이 관계 끝점으로만 이름을 댄 경우)은 본문에 갈
    // 곳이 없다. 그럴 때 아무 일도 하지 않으면 클릭이 먹지 않은 것과
    // 구분되지 않으므로, 목록의 그 줄로 데려가 이유를 보게 한다.
    var target = body.querySelector("mark[data-items~='" + itemId + "']") ||
      body.querySelector(".doc-item[data-item='" + itemId + "']");
    if (!target) return;
    target.scrollIntoView({ block: "center", behavior: "smooth" });
    target.classList.add("is-focused");
    setTimeout(function () { target.classList.remove("is-focused"); }, 1600);
  }

  async function openDoc(docId, itemId) {
    var already = docTabs.filter(function (t) { return t.id === docId; })[0];
    if (already) {
      docActive = docId;
      renderDocPanel();
      revealDocItem(itemId);
      return;
    }
    try {
      var d = await api("/api/document/" + encodeURIComponent(docId) + "/review");
      // 탭이 무한정 늘어나지 않게 앞에서 밀어낸다. 탭 열두 개짜리 패널은
      // 문서를 읽는 자리가 아니라 탭을 고르는 자리가 된다.
      docTabs.push({
        id: docId,
        title: plainDocumentTitle(d.title, docId.slice(0, 8)),
        data: d,
      });
      if (docTabs.length > 4) docTabs.shift();
      docActive = docId;
      renderDocPanel();
      revealDocItem(itemId);
    } catch (e) {
      // 실패도 패널 안에서 말한다. 문서를 열어달라 했는데 아무 일도
      // 일어나지 않으면 클릭이 먹지 않은 것과 구분되지 않는다.
      docTabs.push({
        id: docId, title: docId.slice(0, 8), data: null,
        error: friendlyError(e),
      });
      docActive = docId;
      renderDocPanel();
    }
  }

  (function wireDocPanel() {
    var panel = $("#doc-panel");
    if (!panel) return;
    var close = $("#doc-close");
    if (close) {
      close.addEventListener("click", function () {
        docTabs = [];
        docActive = null;
        renderDocPanel();
      });
    }
    panel.addEventListener("click", function (ev) {
      var tab = ev.target.closest("[data-doc-tab]");
      if (tab) { docActive = tab.dataset.docTab; renderDocPanel(); return; }
      var item = ev.target.closest(".doc-item");
      if (item) revealDocItem(item.dataset.item);
    });
    // 검토 화면의 "원문 전체 보기" — 판정하던 그 항목 위치로 바로 데려간다.
    document.addEventListener("click", function (ev) {
      var open = ev.target.closest("[data-open-doc]");
      if (open) openDoc(open.dataset.openDoc, open.dataset.openItem);
    });
    // 레지스트리 강화 — 이름을 외부 DB에 확인한다(advisory).
    document.addEventListener("click", function (ev) {
      var btn = ev.target.closest("[data-enrich-id]");
      if (btn) runEnrichment(btn.dataset.enrichId);
    });
    var list = $("#documents-list");
    if (list) {
      list.addEventListener("click", function (ev) {
        var row = ev.target.closest("[data-doc]");
        if (row) openDoc(row.dataset.doc);
      });
      // role=button 을 붙였으면 키보드로도 눌려야 한다. 안 그러면 스크린
      // 리더에는 버튼이라고 말해놓고 실제로는 마우스 전용인 셈이다.
      list.addEventListener("keydown", function (ev) {
        if (ev.key !== "Enter" && ev.key !== " ") return;
        var row = ev.target.closest("[data-doc]");
        if (row) { ev.preventDefault(); openDoc(row.dataset.doc); }
      });
    }
  })();

  /* -- 대화 ---------------------------------------------------------------
     이 화면이 하는 일은 문장 하나를 받아서 실제 작업을 돌리는 것이다.
     그래서 답보다 과정이 먼저 온다: 무엇을 썼는지가 접힌 채로 위에 있고,
     펼치면 도구·동작·결과가 줄로 쌓인다. 서버는 값만 보내고(tool="arxiv",
     action="query") 한국어는 여기서 붙인다 — 화면의 오타를 고치려고 서버를
     다시 띄우게 되는 구조를 만들지 않는다. */

  var TERMINOLOGY_KO = {
    tools: {
      ontologylab: "파이프라인", store: "저장소", resources: "외부 자료",
      claude: "분류 엔진", mock: "모의 엔진",
      arxiv: "arXiv", crossref: "Crossref", openalex: "OpenAlex",
      semanticscholar: "Semantic Scholar", europepmc: "Europe PMC",
      biorxiv: "bioRxiv", pubmed: "PubMed",
      clinicaltrials: "ClinicalTrials.gov", searxng: "SearXNG",
      elsevier: "Elsevier", springer: "Springer", core: "CORE",
    },
    actions: {
      classify: "의도 파악", query: "조회", phase: "단계", research: "리서치",
      status: "상태 확인", build_pack: "팩 빌드", enrich: "강화",
      approve: "승인", reject: "거부", goto: "화면 이동", search: "검색",
      read: "읽기", lookup: "조회", build: "팩 빌드", formulate: "검색어 작성",
      gather: "수집", store: "저장", extract: "추출",
    },
    helpActions: {
      research: { name: "주제 리서치", summary: "논문 소스에서 주제를 조사하고 제안을 만듭니다." },
      show_review: { name: "검토 열기", summary: "검토 대기 목록을 엽니다." },
      show_graph: { name: "그래프 열기", summary: "지식그래프를 엽니다." },
      show_packs: { name: "팩 목록", summary: "빌드된 팩을 표시합니다." },
      show_sources: { name: "문서 목록", summary: "수집한 문서를 표시합니다." },
      search_entities: { name: "개체 검색", summary: "이름으로 그래프 개체를 검색합니다." },
      enrich: { name: "외부 자료 강화", summary: "검증된 개체를 외부 자료에서 확인합니다." },
      build_pack: { name: "팩 빌드", summary: "승인된 지식으로 팩을 만듭니다." },
      status: { name: "저장소 현황", summary: "현재 저장소와 실행 상태를 확인합니다." },
      help: { name: "지원 작업", summary: "요청할 수 있는 작업을 설명합니다." },
    },
  };
  var FAIL_KO = {
    failed: STATUS_KO.failed,
    unavailable: "쓸 수 없음", offline: "오프라인", no_topic: "주제 없음",
    no_query: "검색어 없음", fetch_failed: "응답 없음", busy: "이미 실행 중",
    shape: "형식 오류", unsupported: "지원 안 함", refused: "거절됨",
    unconfigured: "연결 안 됨", too_large: "응답이 너무 큼", rejected: "차단됨",
    // 이건 "응답 없음"이 아니다 — 인스턴스는 멀쩡히 답했고 JSON을 거절했을
    // 뿐이라, 네트워크를 확인하러 가면 아무것도 못 찾는다.
    no_json: "JSON 꺼져 있음", unknown: "원인을 확인할 수 없음",
  };
  function toolKo(t) { return TERMINOLOGY_KO.tools[t] || "도구"; }
  function actionKo(a) { return TERMINOLOGY_KO.actions[a] || "작업"; }

  function traceStepRow(step) {
    // 표시는 세 상태뿐이다: 됐다 / 안 됐다 / 하는 중. 그 이상으로 나누면
    // 훑을 때 색이 정보를 나르지 못한다.
    var mark = step.status === "ok" ? "✓"
      : step.status === "failed" ? "✕"
      : step.status === "skipped" ? "–" : "•";
    var detail = step.detail || "";
    if (step.status === "failed") detail = FAIL_KO[detail] || "실행하지 못함";
    if (step.action === "phase") detail = PHASE_KO[detail] || "진행 중";
    if (step.action === "classify" && detail) {
      detail = TERMINOLOGY_KO.actions[detail] || "분류 결과";
    }
    var label = toolKo(step.tool) + " " + actionKo(step.action) +
      (detail ? " " + detail : "");
    return "<li class='tstep st-" + escapeHtml(step.status) + "'" +
      " aria-label='" + escapeHtml(label) + "'>" +
      "<span class='tstep-mark' aria-hidden='true'>" + mark + "</span>" +
      "<span class='tstep-tool'>" + escapeHtml(toolKo(step.tool)) + "</span>" +
      "<span class='tstep-act'>" + escapeHtml(actionKo(step.action)) + "</span>" +
      (detail ? "<span class='tstep-detail'>" + escapeHtml(detail) + "</span>" : "") +
      "</li>";
  }

  function traceSummary(steps, running) {
    if (running) {
      // 실행 중에는 "지금 무엇을 하고 있나"가 요약이어야 한다. 개수는
      // 끝난 뒤에나 의미가 있다.
      var live = steps.filter(function (s) { return s.status === "running"; });
      var last = live[live.length - 1] || steps[steps.length - 1];
      if (last) {
        return last.action === "phase"
          ? (PHASE_KO[last.detail] || last.detail) + "…"
          : toolKo(last.tool) + " " + actionKo(last.action) + " 중…";
      }
    }
    var tools = {};
    steps.forEach(function (s) { if (s.action !== "phase") tools[s.tool] = 1; });
    var failed = steps.filter(function (s) { return s.status === "failed"; }).length;
    return "도구 " + Object.keys(tools).length + "개 사용함 · 단계 " +
      steps.length + "개" + (failed ? " · 실패 " + failed : "");
  }

  /* 서버는 사건을 그대로 보낸다: arXiv 조회 시작, 그리고 나중에 arXiv 5건.
     그걸 두 줄로 그리면 같은 소스를 두 번 조회한 것처럼 읽힌다. 도구·동작이
     같은 줄은 마지막 상태 하나로 접되, 처음 나타난 자리는 지킨다 — 팬아웃의
     순서가 곧 무엇을 먼저 물었는지이기 때문이다.

     단계(phase)는 접지 않는다. 그건 사건이 아니라 구간 표시라, 모으는 중과
     뽑는 중이 한 줄로 합쳐지면 순서가 사라진다.

     구분자는 U+0000이되 이스케이프로 적는다. 예전에는 소스에 진짜 0x00
     바이트가 박혀 있었다 — 화면에도 diff에도 보이지 않고, git·grep·에디터는
     이 파일을 바이너리로 취급했으며, 텍스트 파이프라인을 한 번만 통과해도
     키가 조용히 달라졌다. 키의 의미는 그대로 두고 표기만 바꾼다. */
  function collapseSteps(steps) {
    var order = [], byKey = {};
    steps.forEach(function (s) {
      var key = s.action === "phase"
        ? "phase:" + s.detail : s.tool + "\u0000" + s.action;
      if (!(key in byKey)) order.push(key);
      byKey[key] = s;
    });
    return order.map(function (k) { return byKey[k]; });
  }

  function renderLiveTraceChips(rows, elapsed) {
    return "<div class='live-trace-head'>" +
      "<div class='live-trace-chips'>" + rows.map(function (step) {
        var state = step.status === "ok" ? "완료"
          : step.status === "failed" ? "실패"
          : step.status === "skipped" ? "건너뜀" : "실행 중";
        return "<span class='live-tool-chip st-" + escapeHtml(step.status) +
          "' aria-label='" + escapeHtml(toolKo(step.tool) + " " +
          actionKo(step.action) + " " + state) + "'>" +
          escapeHtml(toolKo(step.tool)) + " · " + escapeHtml(actionKo(step.action)) +
          "</span>";
      }).join("") + "</div>" +
      "<span class='live-trace-elapsed' aria-label='경과 시간 " + elapsed +
      "초'>" + elapsed + "초</span></div>";
  }

  function renderTrace(steps, running, startedAt) {
    if (!steps || !steps.length) return "";
    var rows = collapseSteps(steps);
    var elapsed = Math.max(0, Math.floor((Date.now() - (startedAt || Date.now())) / 1000));
    return (running ? renderLiveTraceChips(rows, elapsed) : "") +
      "<details class='trace'" + (running ? " open" : "") + ">" +
      "<summary>" + escapeHtml(traceSummary(rows, running)) + "</summary>" +
      "<ol class='trace-steps'>" + rows.map(traceStepRow).join("") + "</ol>" +
      "</details>";
  }

  function hasClassifyFailure(res) {
    return (res.steps || []).some(function (step) {
      return step.action === "classify" && step.status === "failed";
    });
  }

  function chatFailureAction(res, message) {
    if (!hasClassifyFailure(res)) return "";
    return "<div class='chat-failure'><p><strong>요청의 목적을 분류하지 못했습니다.</strong> " +
      "질문을 더 구체적으로 적거나 같은 요청을 다시 시도합니다.</p>" +
      "<button type='button' class='btn btn-primary' data-chat-retry='" +
      escapeHtml(message || "") + "'>다시 시도</button></div>";
  }

  function chatAnswer(res) {
    var r = res.result || {};
    var reading = res.reading
      ? "<p>" + escapeHtml(res.reading) + "</p>" : "";

    if (r.kind === "job") {
      // 리서치는 답이 즉시 나오지 않는다. 말풍선이 실행에 묶이고, 이후
      // 갱신은 updateChatJob이 이 자리에 덮어쓴다. "묻는 중"이라고
      // 단정하지 않는 이유는 이 분기가 새로고침 뒤 기록에서도 지나가기
      // 때문이다 — 그때 그 실행은 이미 끝났을 수 있다.
      return reading + "<p class='muted'><small>‘" +
        escapeHtml(r.topic || "") + "’ 리서치를 시작했습니다.</small></p>";
    }
    if (r.kind === "confirm") {
      return reading +
        "<p>저장소를 변경하는 작업이므로 실행 전에 확인합니다.</p>" +
        "<p><button type='button' class='btn btn-primary' data-confirm='" +
        escapeHtml(r.action) + "'>실행합니다</button></p>";
    }
    if (r.kind === "blocked") {
      return reading + "<p class='err-msg'><strong>" +
        escapeHtml(FAIL_KO[r.error_kind] || r.error_kind || "실행 못 함") +
        "</strong></p>" + (r.detail
          ? "<p class='muted'><small>" + escapeHtml(r.detail) + "</small></p>" : "");
    }
    if (r.kind === "status") {
      var c = r.counts || {};
      var pending = (c.nodes_proposed || 0) + (c.edges_proposed || 0);
      var verified = (c.nodes_verified || 0) + (c.edges_verified || 0);
      return reading + "<div class='kpi-grid'>" +
        "<div class='kpi'><span class='kpi-n'>" + (c.documents || 0) +
        "</span><span class='kpi-l'>문서</span></div>" +
        "<div class='kpi'><span class='kpi-n is-pending'>" + pending +
        "</span><span class='kpi-l'>검토 대기</span></div>" +
        "<div class='kpi'><span class='kpi-n'>" + verified +
        "</span><span class='kpi-l'>승인됨</span></div>" +
        "</div>";
    }
    if (r.kind === "goto") {
      return reading + "<p><button type='button' class='btn btn-primary'" +
        " data-goto='" + escapeHtml(r.screen) + "'>열기 →</button></p>";
    }
    if (r.kind === "search") {
      var hits = r.results || [];
      if (!hits.length) {
        return reading + "<p class='muted'>‘" + escapeHtml(r.query || "") +
          "’ 검색 결과가 없습니다.</p>";
      }
      return reading + "<ul class='chat-hits'>" + hits.slice(0, 8).map(
        function (h) {
          return "<li>" + escapeHtml(h.name || h.label || "") +
            " <code>" + escapeHtml(h.entity_type || "") + "</code></li>";
        }).join("") + "</ul>";
    }
    if (r.kind === "pack") {
      var packId = (r.manifest || {}).pack_id || r.pack_id || "";
      return reading + "<p>팩 <code>" + escapeHtml(packId) +
        "</code>을 만들었습니다. <button type='button' class='btn-link'" +
        " data-goto='packs'>팩 보기 →</button></p>";
    }
    if (r.kind === "blocked") {
      // packs_build의 ok:false — 만들어진 게 없으니 성공 말풍선은 거짓.
      return reading + "<p class='err-msg'>팩을 만들지 못했습니다 — " +
        escapeHtml(r.detail || "알 수 없는 이유") + "</p>";
    }
    if (r.kind === "enrich") {
      return reading + "<p>외부 자료에서 <strong>" + (r.proposed || 0) +
        "건</strong>을 찾아 <em>제안</em>으로 기록했습니다. 승인은 검토에서 수행합니다." +
        " <button type='button' class='btn-link' data-goto='review'>검토 →" +
        "</button></p>";
    }
    if (r.kind === "text" && r.actions) {
      return reading + "<ul class='chat-actions'>" + r.actions.map(function (a) {
        var copy = TERMINOLOGY_KO.helpActions[a.name] || {
          name: "지원 작업", summary: "요청 내용을 확인해 알맞은 작업을 실행합니다.",
        };
        return "<li data-action-id='" + escapeHtml(a.name) + "'><strong>" +
          escapeHtml(copy.name) + "</strong> <code>" + escapeHtml(a.name) +
          "</code> — " + escapeHtml(copy.summary) + "</li>";
      }).join("") + "</ul>";
    }
    return reading || "<p class='muted'>답변을 생성하지 못했습니다.</p>";
  }

  function renderChatResult(res, message) {
    // 분류 실패는 도구 목록으로 위장하지 않는다. 행동 문장과 재시도만 보인다.
    var failure = chatFailureAction(res, message);
    return renderTrace(res.steps || [], false) + (failure || chatAnswer(res));
  }

  function announceChatMessage(text) {
    var host = $("#chat-announcements");
    if (!host) return;
    var announcement = document.createElement("span");
    announcement.setAttribute("role", "status");
    announcement.setAttribute("aria-live", "polite");
    announcement.setAttribute("aria-atomic", "true");
    announcement.textContent = String(text || "").trim();
    host.appendChild(announcement);
  }

  function chatBubble(who, html) {
    var log = $("#chat-log");
    var intro = log.querySelector(".chat-intro");
    if (intro) intro.remove();
    var el = document.createElement("div");
    el.className = "chat-msg chat-" + who;
    el.innerHTML = html;
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
    return el;
  }

  // job_id → 그 실행을 말하고 있는 말풍선. SSE 갱신이 별도 목록이 아니라
  // 원래 자리에 흘러들어야 대화가 끊기지 않는다.
  var chatJobBubbles = {};
  var chatQueue = [];
  var chatSending = false;

  function pendingTraceHtml(startedAt, queued) {
    var step = {
      tool: "ontologylab", action: "classify",
      status: queued ? "skipped" : "running", detail: "",
    };
    return renderTrace([step], true, startedAt) +
      "<p class='muted'>" + (queued
        ? "앞선 요청이 끝나면 이 요청을 순서대로 실행합니다."
        : "요청의 목적을 분류하고 있습니다.") + "</p>";
  }

  function renderBoundJob(bound, job) {
    var running = job.status === "running";
    var steps = (bound.res.steps || []).concat(job.steps || []);
    var tail = "";
    if (!running) {
      var t = job.totals || {};
      var added = (t.nodes_new || 0) + (t.edges_new || 0);
      var retained = added + (t.nodes_merged || 0) + (t.edges_merged || 0);
      tail = job.status === "complete"
        ? "<p>제안 <strong>" + added + "건</strong>이 도착했습니다. 승인은 " +
          "사용자가 결정합니다. <button type='button' class='btn btn-primary'" +
          " data-goto='review'>검토 열기</button></p>"
        : "<div class='chat-failure'><p><strong>" +
          escapeHtml(statusKo(job.status)) + "</strong> 작업을 완료하지 못했습니다.</p>" +
          (retained
            ? "<p>현재까지 생성된 제안은 유지됩니다. " +
              escapeHtml(totalsSummary(t)) +
              " <button type='button' class='btn btn-primary'" +
              " data-goto='review'>검토 열기</button></p>"
            : "") +
          "<button type='button' class='btn btn-primary' data-chat-retry='" +
          escapeHtml(bound.message) + "'>다시 시도</button></div>";
    }
    bound.el.innerHTML = renderTrace(steps, running, bound.startedAt) +
      "<p>" + escapeHtml(bound.res.reading || "") + "</p>" + tail;
    if (!running) {
      clearInterval(bound.timer);
      announceChatMessage(bound.el.textContent);
      delete chatJobBubbles[job.job_id];
    }
  }

  function updateChatJob(job) {
    var bound = chatJobBubbles[job.job_id];
    if (!bound) return;
    bound.lastJob = job;
    renderBoundJob(bound, job);
  }

  async function sendChat(item) {
    var message = item.message;
    var pending = item.pending;
    pending.innerHTML = pendingTraceHtml(item.startedAt, false);
    var timer = setInterval(function () {
      pending.innerHTML = pendingTraceHtml(item.startedAt, false);
    }, 1000);
    try {
      var payload = chatSession.attach({
        message: message,
        confirmed: false,
      });
      var eng = currentEngine();
      if (eng) payload.engine = eng;
      var res = await apiSend("/api/chat", payload);
      clearInterval(timer);
      pending.innerHTML = renderChatResult(res, message);
      announceChatMessage(pending.textContent);
      var r = res.result || {};
      if (r.kind === "job" && r.job_id) {
        var bound = {
          el: pending, res: res, message: message,
          startedAt: item.startedAt, lastJob: null, timer: null,
        };
        bound.timer = setInterval(function () {
          if (bound.lastJob) renderBoundJob(bound, bound.lastJob);
          else pending.innerHTML = renderTrace(res.steps || [], true, item.startedAt) +
            "<p class='muted'>실행 상태를 확인하고 있습니다.</p>";
        }, 1000);
        chatJobBubbles[r.job_id] = bound;
        loadJobs();
      }
      if (r.kind === "confirm") pending.dataset.message = message;
      renderSessionSwitcher();
    } catch (e) {
      clearInterval(timer);
      renderErrorSurface(pending, e, {
        retry: function () {
          enqueueChat(message);
          return { recovered: true };
        },
        fallback: "대화 요청을 처리하지 못했습니다.",
      });
      announceChatMessage(classifyError(e, "대화 요청을 처리하지 못했습니다.").message);
    }
  }

  function enqueueChat(message) {
    chatBubble("user", escapeHtml(message));
    var item = {
      message: message,
      pending: chatBubble("bot", pendingTraceHtml(Date.now(), chatSending)),
      startedAt: Date.now(),
    };
    chatQueue.push(item);
    drainChatQueue();
  }

  async function drainChatQueue() {
    if (chatSending || !chatQueue.length) return;
    chatSending = true;
    var item = chatQueue.shift();
    await sendChat(item);
    chatSending = false;
    drainChatQueue();
  }

  async function confirmChat(el) {
    var message = el.dataset.message;
    if (!message) return;
    el.innerHTML = "<p class='muted'>실행 중…</p>";
    try {
      // 확인 실행은 제안했던 것과 같은 엔진으로 돌아야 한다. 여기서도
      // 빈 값을 실으면 서버 기본값이 적용되지 않는다.
      var payload = chatSession.attach({
        message: message,
        confirmed: true,
      });
      var eng = currentEngine();
      if (eng) payload.engine = eng;
      var res = await apiSend("/api/chat", payload);
      el.innerHTML = renderChatResult(res, message);
      announceChatMessage(el.textContent);
    } catch (e) {
      el.innerHTML = "<p class='err-msg'>" + escapeHtml(friendlyError(e)) + "</p>";
    }
  }

  /* 채팅이 쓸 엔진. 예전에는 리서치/추출 탭의 select를 읽었는데, 그 탭을 한
     번도 열지 않으면 두 select 모두 비어 있어 "mock"으로 조용히 떨어졌다 —
     홈 화면에만 머무른 사람은 자기 질문이 전부 mock으로 돌고 있다는 걸 알
     방법이 없었다. 이제 대화창 자신의 select를 읽고, 그것이 비어 있으면
     엔진 목록을 아직 못 받은 것이므로 빈 문자열을 보내 서버 기본값에 맡긴다.
     "mock"을 폴백으로 쓰지 않는 것이 요점이다. */
  function currentEngine() {
    var sel = $("#chat-engine");
    return (sel && sel.value) || "";
  }

  /* 기록에서 대화를 되살린다. 지식이 아니라 사람이 보던 화면을 되살리는
     것이라, 이 경로로 그래프 상태는 아무것도 바뀌지 않는다. */
  async function loadChatHistory() {
    var log = $("#chat-log");
    if (!log) return;
    var turns;
    try {
      turns = ((await api(chatSession.historyPath())) || {}).turns || [];
    } catch (_) {
      return;   // 기록을 못 읽는다고 새 대화를 막을 이유는 없다.
    }
    if (!turns.length) return;
    turns.forEach(function (t) {
      // 시각은 장식이 아니다. 되살아난 답에는 그때의 수치가 들어 있고,
      // 날짜가 없으면 그게 지금 값으로 읽힌다. 다시 계산해서 채우는 건 더
      // 나쁘다 — 어제의 질문 밑에 오늘의 답을 붙이는 셈이라 둘 다 틀린다.
      chatBubble("user", escapeHtml(t.message) +
        "<div class='chat-when'><small>" + timeHtml(t.created_ts) +
        "</small></div>");
      var res = {
        result: t.result, reading: t.reading, steps: t.steps,
      };
      var el = chatBubble("bot", renderChatResult(res, t.message));
      // `restored` 표시가 있는 것만 "실행이 사라졌다" 판정 대상이다. 방금
      // 시작한 실행은 목록 폴링이 아직 못 따라잡았을 수 있고, 그걸 사라진
      // 것으로 처리하면 멀쩡한 실행을 죽었다고 말하게 된다.
      if (t.job_id) {
        chatJobBubbles[t.job_id] = {
          el: el, res: res, restored: true, message: t.message,
          startedAt: Number(t.created_ts || 0) * 1000 || Date.now(), timer: null,
        };
      }
    });
    log.scrollTop = log.scrollHeight;
    if (Object.keys(chatJobBubbles).length) loadJobs();
  }

  /* 실행 기록은 서버 메모리에만 있다. 서버가 다시 시작되면 그 실행은
     목록에서 사라지는데, 그것이 만든 문서와 제안은 저장소에 그대로 남는다.
     말풍선이 "시작했어요"에서 영원히 멈춰 있으면 두 사실이 다 안 보인다. */
  function reconcileChatJobs(jobs) {
    var live = {};
    jobs.forEach(function (j) { live[j.job_id] = true; });
    Object.keys(chatJobBubbles).forEach(function (id) {
      var bound = chatJobBubbles[id];
      if (live[id] || !bound.restored) return;
      bound.el.innerHTML =
        renderTrace(bound.res.steps || [], false) +
        "<p>" + escapeHtml(bound.res.reading || "") + "</p>" +
        "<p class='muted'><small>이 실행의 진행 기록이 남아 있지 않습니다." +
        " 그 사이 서버가 다시 시작되었습니다. 수집한 문서와 제안은 유지됩니다." +
        " <button type='button' class='btn-link' data-goto='review'>검토 열기 →" +
        "</button></small></p>";
      delete chatJobBubbles[id];
    });
  }

  function clearChatRuntime() {
    Object.keys(chatJobBubbles).forEach(function (id) {
      clearInterval(chatJobBubbles[id].timer);
    });
    chatJobBubbles = {};
    chatQueue = [];
  }

  function resetChatSurface() {
    clearChatRuntime();
    var log = $("#chat-log");
    if (log) log.innerHTML = initialChatHtml;
    var input = $("#chat-input");
    if (input) {
      input.value = "";
      input.style.height = "auto";
    }
  }

  function renderSessionSwitcher() {
    var select = $("#chat-session-select");
    if (!select) return;
    var sessions = chatSession.list();
    select.innerHTML = sessions.map(function (session) {
      return "<option value='" + escapeHtml(session.id) + "'>" +
        escapeHtml(session.title) + "</option>";
    }).join("");
    select.value = chatSession.current();
  }

  async function switchChatSession(id) {
    if (!chatSession.switchTo(id)) return;
    resetChatSurface();
    renderSessionSwitcher();
    await loadChatHistory();
  }

  function startNewChatSession() {
    chatSession.startNew();
    resetChatSurface();
    renderSessionSwitcher();
    $("#chat-input").focus();
  }

  /* ── 사이드바 폭 조절 ───────────────────────────────────────────
     폭은 --rail-w 하나로 결정된다. 격자의 첫 열이라 이 값만 바꾸면 문서
     패널이 열린 3열 상태도 함께 따라오고, 860px 아래에서는 아이콘 레일로
     접히는 미디어 쿼리가 이 값을 덮으므로 조절 자체가 사라진다.

     드래그 중에는 CSS 변수만 갱신하고 저장은 끝날 때 한 번 한다 —
     pointermove마다 localStorage에 쓰면 프레임이 눈에 띄게 밀린다. */
  (function wireRailResizer() {
    var handle = $("#rail-resizer");
    if (!handle) return;
    var root = document.documentElement;
    var KEY = "ontologylab.railWidth";
    var DEFAULT_W = 232;

    function limits() {
      var cs = getComputedStyle(root);
      return {
        min: parseInt(cs.getPropertyValue("--rail-w-min"), 10) || 168,
        max: parseInt(cs.getPropertyValue("--rail-w-max"), 10) || 420,
      };
    }
    function clamp(px) {
      var l = limits();
      return Math.max(l.min, Math.min(l.max, Math.round(px)));
    }
    function apply(px) { root.style.setProperty("--rail-w", clamp(px) + "px"); }
    function current() {
      return parseInt(getComputedStyle(root).getPropertyValue("--rail-w"), 10)
        || DEFAULT_W;
    }
    function persist() {
      try { localStorage.setItem(KEY, String(current())); } catch (_) {}
    }

    // 저장된 폭 복원. 값이 깨져 있으면 무시하고 기본값을 쓴다 —
    // 저장소의 문자열 하나 때문에 레일이 사라지면 안 된다.
    try {
      var saved = parseInt(localStorage.getItem(KEY), 10);
      if (saved) apply(saved);
    } catch (_) {}

    handle.addEventListener("pointerdown", function (ev) {
      ev.preventDefault();
      handle.setPointerCapture(ev.pointerId);
      handle.classList.add("is-dragging");
      document.body.classList.add("rail-resizing");

      function move(e) { apply(e.clientX); }
      function up(e) {
        handle.releasePointerCapture(e.pointerId);
        handle.classList.remove("is-dragging");
        document.body.classList.remove("rail-resizing");
        handle.removeEventListener("pointermove", move);
        handle.removeEventListener("pointerup", up);
        handle.removeEventListener("pointercancel", up);
        persist();
      }
      handle.addEventListener("pointermove", move);
      handle.addEventListener("pointerup", up);
      // 드래그 중 창을 벗어나거나 포인터를 빼앗기면 body의 클래스가 남아
      // 커서가 col-resize로 굳는다. cancel도 같은 정리를 거치게 한다.
      handle.addEventListener("pointercancel", up);
    });

    handle.addEventListener("dblclick", function () {
      apply(DEFAULT_W);
      persist();
    });

    // 포인터가 없는 사람에게도 열려 있어야 한다.
    handle.addEventListener("keydown", function (ev) {
      var step = ev.shiftKey ? 32 : 8;
      if (ev.key === "ArrowLeft") { apply(current() - step); }
      else if (ev.key === "ArrowRight") { apply(current() + step); }
      else if (ev.key === "Home") { apply(DEFAULT_W); }
      else { return; }
      ev.preventDefault();
      persist();
    });
  })();

  (function wireChat() {
    var form = $("#chat-form");
    var input = $("#chat-input");
    if (!form || !input) return;
    // 대화창은 첫 화면이므로 여기서 채운다. 다른 탭의 지연 로딩에 기대면
    // 그 탭을 열기 전까지 선택지가 없다.
    populateEngineSelect("#chat-engine");
    renderSessionSwitcher();
    chatSession.subscribe(renderSessionSwitcher);
    loadChatHistory();

    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var text = input.value.trim();
      if (!text) return;
      input.value = "";
      input.style.height = "auto";
      enqueueChat(text);
    });
    // Enter 보내기 / Shift+Enter 줄바꿈 — 대화창의 관습이다.
    input.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" && !ev.shiftKey) {
        ev.preventDefault();
        form.requestSubmit();
      }
    });
    input.addEventListener("input", function () {
      input.style.height = "auto";
      input.style.height = Math.min(input.scrollHeight, 200) + "px";
    });

    $("#chat-log").addEventListener("click", function (ev) {
      var chip = ev.target.closest(".chip[data-say]");
      if (chip) { enqueueChat(chip.dataset.say); return; }
      var retry = ev.target.closest("[data-chat-retry]");
      if (retry) { enqueueChat(retry.dataset.chatRetry); return; }
      var confirmBtn = ev.target.closest("[data-confirm]");
      if (confirmBtn) confirmChat(confirmBtn.closest(".chat-msg"));
    });

    $("#chat-session-new").addEventListener("click", startNewChatSession);
    $("#chat-session-select").addEventListener("change", function () {
      switchChatSession($("#chat-session-select").value);
    });
    $("#chat-session-rename").addEventListener("click", function () {
      var current = chatSession.list().filter(function (session) {
        return session.id === chatSession.current();
      })[0];
      $("#chat-session-title").value = current ? current.title : "";
      $("#chat-session-rename-box").classList.remove("hidden");
      $("#chat-session-title").focus();
    });
    $("#chat-session-save").addEventListener("click", function () {
      if (chatSession.rename(chatSession.current(), $("#chat-session-title").value)) {
        $("#chat-session-rename-box").classList.add("hidden");
        renderSessionSwitcher();
      }
    });
  })();

  /* 따라하기 1단계: 번들 샘플 문서 넣기 (오프라인·멱등) */
  var sampleBtn = $("#journey-sample-btn");
  if (sampleBtn) sampleBtn.addEventListener("click", async function () {
    var btn = $("#journey-sample-btn");
    var out = $("#journey-sample-result");
    btn.disabled = true;
    out.classList.remove("hidden");
    out.textContent = "샘플 문서를 추가하고 있습니다…";
    try {
      var res = await apiSend("/api/collect/sample", {});
      if (res && res.ok) {
        out.textContent = res.created
          ? "「" + (res.title || "샘플") + "」 문서를 추가했습니다."
          : "샘플 문서가 이미 등록되어 있습니다.";
      } else {
        out.textContent = uiUtils.errorText(res, "샘플을 추가하지 못했습니다.");
      }
      loadHome();
    } catch (e) {
      out.textContent = friendlyError(e);
    } finally {
      btn.disabled = false;
    }
  });

  /* Settings: editable form (GET populates, PUT saves) */
  $("#settings-form").addEventListener("submit", async function (ev) {
    ev.preventDefault();
    var box = $("#settings-result");
    var btn = $("#settings-save-btn");
    var model = $("#settings-default-model").value.trim();
    var dataDir = $("#settings-data-dir").value.trim();
    var packsDir = $("#settings-packs-dir").value.trim();
    var searxng = $("#settings-searxng-url").value.trim();
    var payload = {
      default_model: model || null,
      data_dir: dataDir || null,
      packs_dir: packsDir || null,
      searxng_url: searxng || null,
    };
    var settingsEngine = $("#settings-default-engine").value.trim();
    if (settingsEngine) payload.default_engine = settingsEngine;
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

  var translateVisibleBtn = $("#translate-visible-btn");
  if (translateVisibleBtn) {
    translateVisibleBtn.addEventListener("click", async function () {
      var box = $("#translate-visible-result");
      var engine = $("#settings-default-engine").value.trim();
      var model = $("#settings-default-model").value.trim();
      box.classList.remove("hidden", "err-msg");
      if (!engine || engine === "mock") {
        box.textContent =
          "실시간 번역 엔진을 먼저 선택해야 합니다. 원문은 유지됩니다.";
        box.classList.add("err-msg");
        return;
      }
      translateVisibleBtn.disabled = true;
      box.textContent = "현재 화면을 번역하고 있습니다…";
      try {
        var count = await window.ontologylabLocalizer.translateVisible({
          engine: engine,
          model: model || null,
        });
        box.textContent = count
          ? count + "개 문구를 번역했습니다."
          : "번역된 문구가 없습니다. 원문을 유지합니다.";
      } catch (error) {
        box.textContent =
          "번역하지 않았습니다. 원문을 유지합니다. " +
          friendlyError(error);
        box.classList.add("err-msg");
      } finally {
        translateVisibleBtn.disabled = false;
      }
    });
  }

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
      var preferred = null;
      try {
        preferred = ((await api("/api/settings")) || {}).default_engine;
      } catch (_) {}
      var usable = engines.filter(function (e) { return e.available; });
      var pick = usable.filter(function (e) { return e.name === preferred; })[0]
        || usable.filter(function (e) { return e.name !== "mock"; })[0];
      if (pick) sel.value = pick.name;
      else sel.selectedIndex = -1;
    } catch (_) {
      sel.innerHTML = "";
    }
  }

  $("#critic-run-btn").addEventListener("click", async function () {
    var box = $("#critic-result");
    var btn = $("#critic-run-btn");
    btn.disabled = true;
    showResult(box, "<span class='muted'>크리틱 채점 중… (참고용 점수 — 승인은 항상 사용자 몫)</span>");
    try {
      var criticPayload = {};
      var criticEngine = $("#critic-engine").value;
      if (criticEngine) criticPayload.engine = criticEngine;
      var res = await apiSend("/api/critic/run", criticPayload);
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
        showResult(box, escapeHtml(uiUtils.errorText(res, "크리틱 실행 실패.")), true);
      }
    } catch (e) {
      showResult(box, escapeHtml(friendlyError(e)), true);
    } finally {
      btn.disabled = false;
    }
  });
  populateCriticEngines();

  loadHome();
  setInterval(loadHome, 30000); // 상단 크롬(스트립·지금 할 일·배지) 주기 갱신
  connectJobsStream(); // 잡 상태는 SSE 우선, 폴링은 폴백
  loadProposals();
  loadEngines();
  loadSettings();
})();
