(function (root, factory) {
  "use strict";

  var api = factory(root);
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  } else {
    root.ontologylabLocalizer = api;
  }
})(
  typeof window === "undefined" ? null : window,
  function (root) {
    "use strict";

    var CACHE_KEY = "ontologylab.ko-translations.v1";
    var MAX_CACHE_ITEMS = 1000;
    var BATCH_SIZE = 50;
    var ONTOLOGY_KO = {
      activates: "활성화함",
      Assay: "분석법",
      associated_with: "연관됨",
      binds: "결합함",
      CellLine: "세포주",
      Disease: "질환",
      Drug: "약물",
      encodes: "암호화함",
      expressed_in: "발현 위치",
      Gene: "유전자",
      has_variant: "변이 보유",
      inhibits: "억제함",
      measured_by: "측정 방법",
      "PARP-inhibitors": "PARP 억제제",
      paper_api: "논문 API",
      participates_in: "경로 참여",
      Pathway: "경로",
      Platinum: "백금",
      Protein: "단백질",
      apoptosis: "세포자멸사",
      cancer: "암",
      "pseudo-senescence": "유사 노화",
      senescence: "세포 노화",
      spliceosome: "스플라이소솜",
      treats: "치료함",
      Variant: "변이",
    };

    function ontologyLabelKo(value) {
      var label = String(value || "");
      return ONTOLOGY_KO[label] || label;
    }

    function shouldTranslate(value) {
      var text = String(value || "").trim();
      if (text.length < 4 || text.length > 4000) return false;
      if (/https?:\/\/|^www\.|@/.test(text)) return false;
      if (/_/.test(text)) return false;

      var words = text.match(/[A-Za-z][A-Za-z'-]*/g) || [];
      if (words.length < 2) return false;
      if (
        words.every(function (word) {
          return word.length <= 5 && word === word.toUpperCase();
        })
      ) {
        return false;
      }
      return true;
    }

    if (!root || !root.document) {
      return {
        ontologyLabelKo: ontologyLabelKo,
        shouldTranslate: shouldTranslate,
      };
    }

    var document = root.document;
    var cache = loadCache();
    var pending = new Map();
    var translatedNodes = new WeakSet();
    var failed = new Set();
    var timer = null;

    function loadCache() {
      try {
        var parsed = JSON.parse(root.localStorage.getItem(CACHE_KEY) || "{}");
        return parsed && typeof parsed === "object" ? parsed : {};
      } catch (_) {
        return {};
      }
    }

    function saveCache() {
      try {
        var entries = Object.entries(cache);
        if (entries.length > MAX_CACHE_ITEMS) {
          cache = Object.fromEntries(entries.slice(-MAX_CACHE_ITEMS));
        }
        root.localStorage.setItem(CACHE_KEY, JSON.stringify(cache));
      } catch (_) {
        // Translation still works when private browsing disables storage.
      }
    }

    function skipped(node) {
      var parent = node.parentElement;
      return (
        !parent ||
        parent.closest(
          "code, pre, kbd, script, style, textarea, input, select, option, " +
            "[data-no-translate]"
        )
      );
    }

    function applyTranslation(node, translated) {
      if (!node.isConnected) return;
      var current = node.nodeValue || "";
      var leading = (current.match(/^\s*/) || [""])[0];
      var trailing = (current.match(/\s*$/) || [""])[0];
      translatedNodes.add(node);
      node.nodeValue = leading + translated + trailing;
      if (node.parentElement) node.parentElement.lang = "ko";
      var title = node.parentElement &&
        node.parentElement.closest(".doc-title");
      var row = title && title.closest("[data-sync-title-aria]");
      if (row) {
        row.setAttribute(
          "aria-label",
          title.textContent.trim() + " 원문 열기"
        );
      }
    }

    function queueNode(node) {
      if (
        translatedNodes.has(node) ||
        skipped(node) ||
        !shouldTranslate(node.nodeValue)
      ) {
        return;
      }
      var text = node.nodeValue.trim();
      if (cache[text]) {
        applyTranslation(node, cache[text]);
        return;
      }
      if (failed.has(text)) return;
      if (!pending.has(text)) pending.set(text, new Set());
      pending.get(text).add(node);
      schedule();
    }

    function scan(target) {
      if (!target) return;
      if (target.nodeType === root.Node.TEXT_NODE) {
        queueNode(target);
        return;
      }
      if (target.nodeType !== root.Node.ELEMENT_NODE) return;

      var walker = document.createTreeWalker(
        target,
        root.NodeFilter.SHOW_TEXT
      );
      var node;
      while ((node = walker.nextNode())) queueNode(node);
    }

    function schedule() {
      if (timer !== null) return;
      timer = root.setTimeout(function () {
        timer = null;
        flush();
      }, 120);
    }

    async function flush() {
      var texts = Array.from(pending.keys()).slice(0, BATCH_SIZE);
      if (!texts.length) return;

      var nodesByText = {};
      texts.forEach(function (text) {
        nodesByText[text] = Array.from(pending.get(text) || []);
        pending.delete(text);
      });

      try {
        var response = await root.fetch("/api/translate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ texts: texts, engine: "auto" }),
        });
        if (!response.ok) throw new Error("translation request failed");
        var body = await response.json();
        if (
          !body ||
          !Array.isArray(body.translations) ||
          body.translations.length !== texts.length
        ) {
          throw new Error("translation response shape mismatch");
        }

        texts.forEach(function (text, index) {
          var translated = body.translations[index];
          if (typeof translated !== "string" || !translated.trim()) return;
          cache[text] = translated;
          nodesByText[text].forEach(function (node) {
            applyTranslation(node, translated);
          });
        });
        saveCache();
      } catch (error) {
        texts.forEach(function (text) {
          failed.add(text);
        });
        root.console.warn("화면 번역에 실패했습니다.", error);
      }

      if (pending.size) schedule();
    }

    function start() {
      scan(document.body);
      new root.MutationObserver(function (mutations) {
        mutations.forEach(function (mutation) {
          if (mutation.type === "characterData") {
            queueNode(mutation.target);
          } else {
            mutation.addedNodes.forEach(scan);
          }
        });
      }).observe(document.body, {
        childList: true,
        subtree: true,
        characterData: true,
      });
    }

    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", start, { once: true });
    } else {
      start();
    }

    return {
      ontologyLabelKo: ontologyLabelKo,
      shouldTranslate: shouldTranslate,
      scan: scan,
    };
  }
);
