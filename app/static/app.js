(function () {
  var csrf = document.body.dataset.csrf;

  // ---- ordenación de tablas ----
  document.querySelectorAll('table.sortable').forEach(function (table) {
    var heads = table.tHead ? table.tHead.rows[0].cells : [];
    Array.prototype.forEach.call(heads, function (th, idx) {
      th.addEventListener('click', function () {
        var dir = th.classList.contains('desc') ? 'asc' : 'desc';
        Array.prototype.forEach.call(heads, function (h) { h.classList.remove('asc', 'desc'); });
        th.classList.add(dir);
        var body = table.tBodies[0];
        var rows = Array.prototype.slice.call(body.rows);
        var val = function (r) {
          var c = r.cells[idx]; if (!c) return null;
          var v = c.dataset.v !== undefined ? c.dataset.v : c.textContent.trim();
          if (v === '' || v === '–') return null;
          var n = Number(v); return isNaN(n) ? v.toLowerCase() : n;
        };
        rows.sort(function (a, b) {
          var x = val(a), y = val(b);
          if (x === null && y === null) return 0;
          if (x === null) return 1; if (y === null) return -1;
          var r = (typeof x === 'number' && typeof y === 'number') ? x - y : String(x).localeCompare(String(y), 'es');
          return dir === 'asc' ? r : -r;
        });
        rows.forEach(function (r) { body.appendChild(r); });
      });
    });
  });

  // ---- pestañas de grupos de columnas ----
  document.querySelectorAll('[data-tabs]').forEach(function (tabs) {
    var table = document.getElementById(tabs.dataset.tabs);
    tabs.querySelectorAll('button').forEach(function (b) {
      b.addEventListener('click', function () {
        tabs.querySelectorAll('button').forEach(function (x) { x.classList.remove('on'); });
        b.classList.add('on'); table.dataset.show = b.dataset.g;
      });
    });
  });

  // ---- botón de actualizar ----
  var btn = document.getElementById('update-btn');
  if (!btn) return;
  var info = document.getElementById('update-info'), msg = document.getElementById('update-msg');
  var timer = null;
  function fmtDate(s) { return s && s.length >= 10 ? s.slice(8, 10) + '/' + s.slice(5, 7) + '/' + s.slice(0, 4) : ''; }
  function render(d) {
    if (d.last_update) {
      info.textContent = 'Última actualización: ' + d.last_update +
        (d.last_matchday ? ' · hasta la jornada ' + d.last_matchday + (d.last_matchday_date ? ' (' + fmtDate(d.last_matchday_date) + ')' : '') : '');
    }
  }
  function poll() {
    fetch('/update/status', { credentials: 'same-origin' }).then(function (r) { return r.json(); }).then(function (d) {
      render(d);
      if (d.running) { msg.textContent = d.message; return; }
      clearInterval(timer); timer = null; btn.disabled = false;
      if (d.result) {
        var e = d.result.errors || [];
        msg.textContent = d.result.added + ' partido(s) nuevo(s)' + (e.length ? ' · ' + e.length + ' aviso(s): ' + e[0] : '');
        if (d.result.added > 0) setTimeout(function () { location.reload(); }, 1200);
      }
    });
  }
  btn.addEventListener('click', function () {
    btn.disabled = true; msg.textContent = 'Actualizando…';
    fetch('/update', { method: 'POST', credentials: 'same-origin', headers: { 'X-CSRF-Token': csrf } })
      .then(function (r) { return r.json(); })
      .then(function () { timer = setInterval(poll, 1500); poll(); })
      .catch(function () { btn.disabled = false; msg.textContent = 'Error de conexión'; });
  });
})();
