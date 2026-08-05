(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.ontologylabUiUtils = factory();
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

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
    graphLabelFontSize: graphLabelFontSize,
    plainText: plainText,
    visibleGraphLabelIds: visibleGraphLabelIds,
  };
});
