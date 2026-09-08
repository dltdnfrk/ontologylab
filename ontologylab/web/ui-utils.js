(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.ontologylabUiUtils = factory();
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  /* 서버가 4xx를 돌려주면 detail은 문자열이 아니라 {error_kind, field,
     detail} 이거나, 422일 때는 [{loc, msg}, …] 배열이다. 어느 칸이
     틀렸는지까지 말해야 고칠 수 있으므로 그대로 풀어서 보여 준다.

     이 함수는 화면 전체가 함께 쓴다. 예전엔 열세 곳이 각자
     `(res && res.detail) || "…"` 로 detail을 문자열에 그대로 이어
     붙였는데, 422의 detail은 배열이라 그 자리에 `[object Object]` 가
     찍혔다 — 어느 칸이 왜 거절됐는지 말해야 할 바로 그 자리에서. 정규화는
     한 곳에만 둔다. 두 벌이 되면 두 벌이 서로 다르게 말한다. */
  function errorText(res, fallback) {
    var miss = fallback || "요청을 처리하지 못했습니다.";
    var detail = res && res.detail;
    if (detail && typeof detail === "object" && !Array.isArray(detail)) {
      return (detail.field ? detail.field + ": " : "") +
        (detail.detail || miss);
    }
    if (Array.isArray(detail)) {
      return detail.map(function (item) {
        return (item.loc || []).slice(-1).join("") + ": " + (item.msg || "");
      }).join(" · ");
    }
    // detail이 아예 없는 응답도 있다 (`error`만 오는 경로). 마지막으로
    // 그쪽을 보고, 그것도 없으면 호출부가 준 문장을 쓴다.
    return String(detail || (res && res.error) || miss);
  }

  /* 쓰기가 정말 일어난 것인지 판정한다. 아니면 던진다.

     `apiSend`는 비-2xx에도 본문을 돌려준다 — {ok:false} 계약 봉투를 화면에
     그리려고 일부러 그러기로 한 것이다. 그래서 예전 방버인
     `res.ok === undefined` 은 정확히 그 봉투를 놓친다: 거절된 쓰기의
     ok는 undefined가 아니라 false다. 때린 KB에 503을 받고도 목록만
     새로 불러와, 사람은 무효화가 된 줄 알았다 — 화면은 성공과 똑같았고
     기록은 그대로였다. 이제 ok를 직접 본다. */
  function throwIfRefused(res) {
    if (!res) return;
    if (res.ok === true) return;
    if (res.ok === false || res.detail || res.error) {
      var e = new Error(errorText(res, "서버가 요청을 받아들이지 않았습니다."));
      e.errorKind = res.error_kind || null;
      // busy는 다시 보내면 되는 실패다. 몇 초인지까지 말해야 "잠시 뒤"가
      // 추측이 아니게 된다.
      if (res.retry_after !== undefined && res.retry_after !== null) {
        e.retryAfter = res.retry_after;
      }
      throw e;
    }
  }

  var ENTITIES = {
    amp: "&",
    apos: "'",
    gt: ">",
    lt: "<",
    nbsp: " ",
    quot: '"',
  };

  function plainText(value) {
    return String(value == null ? "" : value)
      .replace(/<[^>]*>/g, " ")
      .replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, function (_, entity) {
        var lowered = entity.toLowerCase();
        if (lowered.slice(0, 2) === "#x") {
          return String.fromCodePoint(parseInt(lowered.slice(2), 16));
        }
        if (lowered.charAt(0) === "#") {
          return String.fromCodePoint(parseInt(lowered.slice(1), 10));
        }
        return ENTITIES[lowered] || _;
      })
      .replace(/\s+/g, " ")
      .trim();
  }

  function overlaps(a, b) {
    return !(
      a.right + 6 < b.left ||
      b.right + 6 < a.left ||
      a.bottom + 4 < b.top ||
      b.bottom + 4 < a.top
    );
  }

  function graphLabelFontSize(scale) {
    return 11 / Math.max(0.05, Number(scale) || 1);
  }

  function visibleGraphLabelIds(nodes, view, size, selectedId) {
    var scale = Math.max(0.05, Number(view.k) || 1);
    var maxLabels = scale < 0.55 ? 14 : scale < 0.9 ? 24 : scale < 1.4 ? 40 : 70;
    var boxes = [];
    var visible = [];

    nodes
      .slice()
      .sort(function (a, b) {
        if (a.id === selectedId) return -1;
        if (b.id === selectedId) return 1;
        return (b.degree || 0) - (a.degree || 0) ||
          String(a.name).localeCompare(String(b.name));
      })
      .some(function (node) {
        if (visible.length >= maxLabels && node.id !== selectedId) return true;
        var x = Number(view.x || 0) + Number(node.x || 0) * scale;
        var y = Number(view.y || 0) + Number(node.y || 0) * scale + 14;
        var width = Math.max(24, plainText(node.name).length * 7);
        var height = 14;
        var box = {
          left: x - width / 2,
          right: x + width / 2,
          top: y - height / 2,
          bottom: y + height / 2,
        };
        var inView =
          box.right >= 0 &&
          box.left <= size.w &&
          box.bottom >= 0 &&
          box.top <= size.h;
        if (!inView && node.id !== selectedId) return false;
        if (
          node.id !== selectedId &&
          boxes.some(function (placed) { return overlaps(box, placed); })
        ) {
          return false;
        }
        boxes.push(box);
        visible.push(node.id);
        return false;
      });

    return visible;
  }

  return {
    errorText: errorText,
    graphLabelFontSize: graphLabelFontSize,
    plainText: plainText,
    throwIfRefused: throwIfRefused,
    visibleGraphLabelIds: visibleGraphLabelIds,
  };
});
