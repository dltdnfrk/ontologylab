(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory;
  } else {
    root.ontologylabCreateChatSession = factory;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function (root) {
  "use strict";

  var STORAGE_KEY = "ontologylab.chat-session.v1";

  function nextId() {
    if (root.crypto && typeof root.crypto.randomUUID === "function") {
      return root.crypto.randomUUID();
    }
    return (
      Date.now().toString(36) + "-" +
      Math.random().toString(36).slice(2)
    );
  }

  function readStored() {
    try {
      return root.sessionStorage.getItem(STORAGE_KEY);
    } catch (_) {
      return null;
    }
  }

  function store(value) {
    try {
      root.sessionStorage.setItem(STORAGE_KEY, value);
    } catch (_) {
      // A private browser context may deny storage. The in-memory session
      // still isolates this tab without blocking the conversation.
    }
  }

  var sessionId = readStored() || nextId();
  store(sessionId);

  return {
    current: function () {
      return sessionId;
    },
    startsNewOnEntry: function (activeTab, targetTab) {
      return Boolean(activeTab) && targetTab === "home";
    },
    startNew: function () {
      sessionId = nextId();
      store(sessionId);
      return sessionId;
    },
    attach: function (payload) {
      payload.session_id = sessionId;
      return payload;
    },
    historyPath: function () {
      return "/api/chat/history?session_id=" + encodeURIComponent(sessionId);
    },
  };
});
