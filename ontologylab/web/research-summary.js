(function (root) {
  "use strict";

  root.ontologylabBuildResearchSummary = function (summary) {
    var container = document.createElement("div");
    container.className = "research-summary-grid";

    function text(tag, value, className) {
      var node = document.createElement(tag);
      if (className) node.className = className;
      node.textContent = value;
      return node;
    }

    function card(label, value, className, noTranslateLabel) {
      var node = document.createElement("div");
      node.className = "research-summary-card" + (className ? " " + className : "");
      var labelNode = text("span", label, "research-summary-label");
      if (noTranslateLabel) labelNode.dataset.noTranslate = "";
      node.appendChild(labelNode);
      node.appendChild(text("p", value, "research-summary-value"));
      container.appendChild(node);
    }

    card("연구 목표", String(summary.goal || "—"), "research-summary-goal");
    var lineage = "v" + String(summary.current_plan_version || 1);
    if (summary.parent_plan_id) {
      lineage += " · parent " + String(summary.parent_plan_id);
    } else {
      lineage += " · root";
    }
    card("계획 계보", lineage);
    if (summary.degraded_reason) {
      card("저하된 계획", String(summary.degraded_reason), "research-summary-warning");
    }

    var occupancy = summary.need_occupancy || [];
    var byNeed = {};
    occupancy.forEach(function (item) { byNeed[item.need_id] = item; });
    var needs = document.createElement("div");
    needs.className = "research-summary-card research-summary-needs";
    needs.appendChild(text("span", "근거 요구", "research-summary-label"));
    var list = document.createElement("ul");
    (summary.evidence_needs || []).forEach(function (need) {
      var state = byNeed[need.need_id];
      var occupied = Boolean(state && state.occupied);
      var item = document.createElement("li");
      item.className = occupied ? "is-occupied" : "is-missing";
      item.textContent = (occupied ? "확보 · " : "미충족 · ") +
        String(need.description || need.kind || need.need_id || "근거") +
        (need.mandatory ? " · 필수" : " · 선택") +
        " · " + String(need.kind || "unknown") +
        " · min " + String(need.minimum_content || "unknown") +
        " · docs " + String(state ? state.eligible_document_count || 0 : 0);
      list.appendChild(item);
    });
    if (!list.childNodes.length) {
      list.appendChild(text("li", "표시할 근거 요구 없음", "muted"));
    }
    needs.appendChild(list);
    container.appendChild(needs);

    var assumptions = summary.assumptions || [];
    if (assumptions.length) {
      var assumptionCard = document.createElement("div");
      assumptionCard.className = "research-summary-card";
      assumptionCard.appendChild(text("span", "가정", "research-summary-label"));
      var assumptionList = document.createElement("ul");
      assumptions.forEach(function (value) {
        assumptionList.appendChild(text("li", String(value)));
      });
      assumptionCard.appendChild(assumptionList);
      container.appendChild(assumptionCard);
    }

    var decision = String(summary.recommendation || "—");
    if (summary.stop_reason) decision += " · stop: " + String(summary.stop_reason);
    card("수집 판단", decision, summary.stop_reason ? "research-summary-warning" : "");

    var counts = summary.post_extraction_counts;
    if (counts) {
      var support = counts.support || {};
      var contradiction = counts.contradiction || {};
      var advisory = Object.keys(support).sort().map(function (key) {
        return "support " + key + " " + String(support[key] || 0);
      }).concat(Object.keys(contradiction).sort().map(function (key) {
        return "contradiction " + key + " " + String(contradiction[key] || 0);
      })).join(" · ");
      card(
        "advisory—not approval",
        advisory,
        "research-summary-advisory",
        true
      );
    }
    return container;
  };
})(typeof globalThis !== "undefined" ? globalThis : this);
