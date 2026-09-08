(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory;
  } else {
    root.ontologylabCreateChatSession = factory;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function (root) {
  "use strict";

  var STORAGE_KEY = "ontologylab.chat-sessions.v2";
  var DEFAULT_TITLE = "새 대화";

  function nextId() {
    if (root.crypto && typeof root.crypto.randomUUID === "function") {
      return root.crypto.randomUUID();
    }
    return Date.now().toString(36) + "-" + Math.random().toString(36).slice(2);
  }

  function now() {
    return Date.now();
  }

  function cleanTitle(value) {
    return String(value || "").replace(/\s+/g, " ").trim().slice(0, 40);
  }

  function automaticTitle(message) {
    var title = cleanTitle(message);
    return title ? title.slice(0, 32) : DEFAULT_TITLE;
  }

  function freshState() {
    var id = nextId();
    return {
      active: id,
      sessions: [{ id: id, title: DEFAULT_TITLE, updatedAt: now() }],
    };
  }

  function normalize(raw) {
    if (!raw || !Array.isArray(raw.sessions)) return freshState();
    var seen = {};
    var sessions = raw.sessions.filter(function (item) {
      if (!item || typeof item.id !== "string" || seen[item.id]) return false;
      seen[item.id] = true;
      return true;
    }).map(function (item) {
      return {
        id: item.id,
        title: cleanTitle(item.title) || DEFAULT_TITLE,
        updatedAt: Number(item.updatedAt) || 0,
      };
    });
    if (!sessions.length) return freshState();
    var active = sessions.some(function (item) { return item.id === raw.active; })
      ? raw.active : sessions[0].id;
    return { active: active, sessions: sessions };
  }

  function read() {
    try {
      return normalize(JSON.parse(root.localStorage.getItem(STORAGE_KEY) || "null"));
    } catch (_) {
      return freshState();
    }
  }

  var state = read();
  var listeners = [];

  function write() {
    try {
      root.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch (_) {
      // Storage can be unavailable in a private context. In-memory metadata
      // still preserves the active conversation for this page.
    }
    listeners.forEach(function (listener) { listener(api.list()); });
  }

  function updateSession(id, updater) {
    state.sessions = state.sessions.map(function (session) {
      return session.id === id ? updater(session) : session;
    });
  }

  var api = {
    current: function () {
      return state.active;
    },
    list: function () {
      return state.sessions.slice().sort(function (a, b) {
        if (a.id === state.active) return -1;
        if (b.id === state.active) return 1;
        return b.updatedAt - a.updatedAt;
      });
    },
    startsNewOnEntry: function () {
      return false;
    },
    startNew: function () {
      var id = nextId();
      state.active = id;
      state.sessions.push({ id: id, title: DEFAULT_TITLE, updatedAt: now() });
      write();
      return id;
    },
    switchTo: function (id) {
      if (!state.sessions.some(function (session) { return session.id === id; })) {
        return false;
      }
      state.active = id;
      updateSession(id, function (session) {
        return { id: session.id, title: session.title, updatedAt: now() };
      });
      write();
      return true;
    },
    rename: function (id, title) {
      var cleaned = cleanTitle(title);
      if (!cleaned) return false;
      updateSession(id, function (session) {
        return { id: session.id, title: cleaned, updatedAt: now() };
      });
      write();
      return true;
    },
    touch: function (message) {
      var id = state.active;
      updateSession(id, function (session) {
        return {
          id: session.id,
          title: session.title === DEFAULT_TITLE
            ? automaticTitle(message) : session.title,
          updatedAt: now(),
        };
      });
      write();
    },
    subscribe: function (listener) {
      listeners.push(listener);
      return function () {
        listeners = listeners.filter(function (item) { return item !== listener; });
      };
    },
    attach: function (payload) {
      api.touch(payload.message || "");
      payload.session_id = state.active;
      return payload;
    },
    historyPath: function () {
      return "/api/chat/history?session_id=" + encodeURIComponent(state.active);
    },
  };

  if (root.addEventListener) {
    root.addEventListener("storage", function (event) {
      if (event.key && event.key !== STORAGE_KEY) return;
      state = read();
      listeners.forEach(function (listener) { listener(api.list()); });
    });
  }

  write();
  return api;
});
