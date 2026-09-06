// app.js — the fixture page: complete the handshake, show what the host sent.
// Everything rendered goes through textContent (never markup).
(function () {
  const text = (id, value) => {
    document.getElementById(id).textContent = String(value);
  };
  window.solus
    .ready()
    .then((init) => {
      text("status", "ready");
      text("mode", init.mode);
      text("version", init.version);
      text("settings", JSON.stringify(init.settings));
      window.solus.on("settings.changed", (settings) => text("settings", JSON.stringify(settings)));
    })
    .catch((error) => text("status", "bridge error: " + (error && error.code)));
})();
