// bridge.js — minimal Solus bridge client (protocol v1), copied from
// docs/extensions/getting-started.md. Not injected by Solus; every bundle ships it.
(function () {
  const pending = new Map();
  const listeners = new Map();
  let counter = 0;
  let resolveInit;
  const initPromise = new Promise((r) => (resolveInit = r));

  window.addEventListener("message", (event) => {
    if (event.source !== window.parent) return;
    const msg = event.data;
    if (!msg || msg.v !== 1) return;
    if (typeof msg.event === "string") {
      if (msg.event === "init") resolveInit(msg.data);
      for (const fn of listeners.get(msg.event) || []) fn(msg.data);
      return;
    }
    const entry = pending.get(msg.id);
    if (!entry) return;
    pending.delete(msg.id);
    if (msg.ok) entry.resolve(msg.result);
    else entry.reject(Object.assign(new Error(msg.error.message), { code: msg.error.code }));
  });

  function call(method, params) {
    const id = "r" + ++counter;
    return new Promise((resolve, reject) => {
      pending.set(id, { resolve, reject });
      window.parent.postMessage({ v: 1, id, method, params: params || {} }, "*");
    });
  }

  function on(event, handler) {
    listeners.set(event, [...(listeners.get(event) || []), handler]);
    return () => listeners.set(event, (listeners.get(event) || []).filter((h) => h !== handler));
  }

  const ready = () => initPromise.then((init) => call("ui.ready").then(() => init));

  window.solus = { call, on, ready };
})();
