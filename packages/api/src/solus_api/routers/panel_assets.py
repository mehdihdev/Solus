"""The panel's static assets — SOLUS-A7-01.

Split three ways — HTML, CSS, JS — so the CSP can stay `script-src 'self';
style-src 'self'` with no `'unsafe-inline'` and no hand-maintained hashes.
An inline `<style>` would have forced `'unsafe-inline'`, and the whole point
of the policy is to be the backstop for the mistake we think we did not make.

Python string constants rather than files on disk: the API's Dockerfile copies
`packages/api/src` and hatchling packages `src/solus_api`, so a `.html` sitting
beside a module is a packaging question with no upside for two small assets.

**Dependency-free and `textContent`-only, deliberately.** The panel token lives
in this page's (partitioned) `localStorage`, so an XSS here IS credential theft.
Part names are connector-ingested untrusted content — CLAUDE.md §7's "no raw
markup injection into the UI" applies to this page literally, and the CSP served
with it is `default-src 'none'` precisely so a mistake fails closed.
"""

from typing import Final

PANEL_CSS: Final = """
:root { color-scheme: light dark; font-family: ui-sans-serif, system-ui, sans-serif; }
body { margin: 0; padding: 12px; font-size: 13px; }
h1 { font-size: 13px; margin: 0 0 10px; font-weight: 600; }
.muted { color: #6b7280; }
.code { font-family: ui-monospace, monospace; font-size: 20px; letter-spacing: 2px;
        padding: 8px; border: 1px solid #9ca3af; border-radius: 6px; text-align: center; }
ul { list-style: none; margin: 8px 0 0; padding: 0; }
li { padding: 6px 4px; border-bottom: 1px solid rgba(127,127,127,.25); }
button { font-size: 12px; padding: 6px 10px; cursor: pointer; }
.row { display: flex; gap: 8px; align-items: center; justify-content: space-between; }
"""

PANEL_HTML: Final = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Solus</title>
<link rel="stylesheet" href="/panel/app.css">
</head>
<body>
  <h1>Solus</h1>
  <div id="view" class="muted">Loading…</div>
  <script src="/panel/app.js"></script>
</body>
</html>
"""

PANEL_JS: Final = """'use strict';
// Onshape panel client (SOLUS-A7-01).
//
// `userId` from the query string is NEVER sent as a credential. Its only job is
// choosing which stored token to use, so that two Onshape accounts on one
// machine do not share a binding. The server would reject it as authentication
// anyway — this is defence in depth, not the defence.
(function () {
  var q = new URLSearchParams(location.search);
  var onshapeUserId = q.get('userId') || '';
  var documentId = q.get('documentId') || '';
  var elementId = q.get('elementId') || '';
  var view = document.getElementById('view');
  var storageKey = 'solus.panel.token.' + onshapeUserId;

  function el(tag, text, cls) {
    var n = document.createElement(tag);
    if (text !== undefined && text !== null) n.textContent = String(text); // the only render path
    if (cls) n.className = cls;
    return n;
  }
  function clear() { while (view.firstChild) view.removeChild(view.firstChild); }
  function show() {
    clear();
    for (var i = 0; i < arguments.length; i++) view.appendChild(arguments[i]);
  }

  function token() {
    try { return localStorage.getItem(storageKey); } catch (e) { return null; }
  }
  function storeToken(value) {
    // Firefox strict mode / Safari ITP may deny an iframe localStorage entirely.
    // Re-pairing each session is the correct degradation; there is no weaker
    // fallback worth having.
    try { localStorage.setItem(storageKey, value); } catch (e) { /* re-pair next load */ }
  }

  function api(path, opts) {
    opts = opts || {};
    var headers = opts.headers || {};
    var t = token();
    if (t) headers['Authorization'] = 'Bearer ' + t;
    return fetch(path, { method: opts.method || 'GET', headers: headers, body: opts.body });
  }

  function pair() {
    show(el('p', 'Connect this panel to your Solus account.'));
    var start = el('button', 'Connect');
    view.appendChild(start);
    start.addEventListener('click', function () {
      fetch('/api/v1/panel/pair/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ onshape_user_id: onshapeUserId })
      }).then(function (r) { return r.json(); }).then(function (payload) {
        var d = payload.data;
        show(
          el('p', 'In Solus, open Settings and enter this code:'),
          el('div', d.user_code, 'code'),
          el('p', 'Waiting for approval…', 'muted')
        );
        poll(d.device_code, d.interval || 5);
      }).catch(function () {
        show(el('p', 'Could not reach Solus. Try again.'));
      });
    });
  }

  function poll(deviceCode, interval) {
    fetch('/api/v1/panel/pair/poll', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + deviceCode }
    }).then(function (r) {
      if (r.status === 404) { pair(); return null; }  // expired or already used
      return r.json();
    }).then(function (payload) {
      if (!payload) return;
      if (payload.data.status === 'linked') { storeToken(payload.data.token); load(); return; }
      setTimeout(function () { poll(deviceCode, interval); }, interval * 1000);
    }).catch(function () {
      setTimeout(function () { poll(deviceCode, interval); }, interval * 1000);
    });
  }

  function load() {
    if (!token()) { pair(); return; }
    if (!documentId) {
      // Opened directly rather than framed by Onshape, so there is no document
      // to be in a project. Say that, instead of reporting no match.
      show(
        el('p', 'Open this panel from an Onshape document.'),
        el('p', 'Onshape supplies the document it is showing; '
          + 'on its own there is nothing to look up.', 'muted')
      );
      return;
    }
    api('/api/v1/panel/context?document_id=' + encodeURIComponent(documentId)).then(function (r) {
      if (r.status === 401) { pair(); return null; }   // revoked or expired
      return r.json();
    }).then(function (payload) {
      if (!payload) return;
      var projects = payload.data.projects;
      if (!projects.length) {
        show(el('p', "This document isn't in a Solus project you can see."));
        return;
      }
      parts(projects[0]);
    }).catch(function () { show(el('p', 'Could not reach Solus.')); });
  }

  function parts(project) {
    var url = '/api/v1/panel/projects/' + encodeURIComponent(project.id) + '/parts'
      + '?document_id=' + encodeURIComponent(documentId)
      + '&element_id=' + encodeURIComponent(elementId);
    api(url).then(function (r) { return r.json(); }).then(function (payload) {
      show(el('p', project.name, 'muted'));
      var list = el('ul');
      (payload.data || []).forEach(function (entity) {
        var row = el('li');
        var wrap = el('div', null, 'row');
        wrap.appendChild(el('span', entity.name));   // untrusted -> textContent
        wrap.appendChild(el('span', entity.type || '', 'muted'));
        row.appendChild(wrap);
        list.appendChild(row);
      });
      if (!list.childNodes.length) list.appendChild(el('li', 'Nothing indexed for this tab yet.'));
      view.appendChild(list);
    }).catch(function () { show(el('p', 'Could not load parts.')); });
  }

  load();
})();
"""

__all__ = ["PANEL_CSS", "PANEL_HTML", "PANEL_JS"]
