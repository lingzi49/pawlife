/* PawLife 展示版 — 应用外壳、路由、通用组件与图表 */
window.PawApp = (function () {
  'use strict';

  var D = window.PawData;
  var pages = {};
  var actions = {};
  var forms = {};
  var state = null;
  var currentRoute = 'dashboard';

  var ICONS = {
    home: '<path d="M3 10.8 12 3l9 7.8"/><path d="M5.5 9.5V21h13V9.5"/><path d="M9.5 21v-6h5v6"/>',
    profile: '<circle cx="12" cy="8" r="3.4"/><path d="M5 20c.6-3.5 3.3-5.4 7-5.4s6.4 1.9 7 5.4"/>',
    bowl: '<path d="M3.5 11.5h17"/><path d="M5 11.5c.4 4.4 3.2 7 7 7s6.6-2.6 7-7"/><path d="M8.5 8.4c.8-2.2 2-3.4 3.5-3.4s2.7 1.2 3.5 3.4"/>',
    clipboard: '<rect x="5" y="4.5" width="14" height="16" rx="2.4"/><path d="M9 4.5V3h6v1.5"/><path d="M8.5 9.5h7M8.5 13h7M8.5 16.5h4"/>',
    chart: '<path d="M4 4v16h16"/><path d="m7 15 4-4 3 2.5 4.5-6"/>',
    bell: '<path d="M18 9a6 6 0 1 0-12 0c0 5-2 6.5-2 6.5h16S18 14 18 9Z"/><path d="M10 19.2a2.2 2.2 0 0 0 4 0"/>',
    trophy: '<path d="M8 4h8v4.5a4 4 0 0 1-8 0V4Z"/><path d="M8 5.5H5.2c0 3 1.3 4.6 3.2 5M16 5.5h2.8c0 3-1.3 4.6-3.2 5"/><path d="M12 12.5V16M8.5 20h7M10 20c0-2 .8-4 2-4s2 2 2 4"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    edit: '<path d="M4 20h4l10.5-10.5a2.1 2.1 0 0 0-3-3L5 17v3Z"/><path d="m13.5 7.5 3 3"/>',
    download: '<path d="M12 4v10"/><path d="m8 10 4 4 4-4"/><path d="M5 19h14"/>',
    reset: '<path d="M4 5v5h5"/><path d="M4.8 10a8 8 0 1 1 .4 5.5"/>',
    menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
    close: '<path d="m6 6 12 12M18 6 6 18"/>',
    check: '<path d="m5 12.5 4.5 4.5L19 7"/>',
    arrow: '<path d="M5 12h14"/><path d="m13 6 6 6-6 6"/>',
    scale: '<rect x="4" y="5" width="16" height="15" rx="3"/><path d="M8 10.5a4 4 0 0 1 8 0"/><path d="M12 6v4"/>',
    calendar: '<rect x="4" y="5.5" width="16" height="15" rx="2.4"/><path d="M8 3.5v4M16 3.5v4M4 10h16"/>',
    alert: '<path d="M12 4 3 20h18L12 4Z"/><path d="M12 9.5v4.5M12 17.2v.1"/>',
    sparkles: '<path d="m12 3 1.5 4.5L18 9l-4.5 1.5L12 15l-1.5-4.5L6 9l4.5-1.5L12 3Z"/><path d="m18.5 15 .8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8.8-2.2Z"/>',
    shield: '<path d="M12 3 5 6v5c0 4.5 3 7.5 7 9 4-1.5 7-4.5 7-9V6l-7-3Z"/><path d="m9 12 2 2 4-4"/>',
    trash: '<path d="M5 7h14M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
    heart: '<path d="M12 20s-7-4.4-7-9.2A3.9 3.9 0 0 1 12 8a3.9 3.9 0 0 1 7 2.8C19 15.6 12 20 12 20Z"/>',
    paw: '<ellipse cx="6.2" cy="10.2" rx="2.1" ry="2.7" transform="rotate(-18 6.2 10.2)"/><ellipse cx="10" cy="6.6" rx="2.1" ry="2.8"/><ellipse cx="14.4" cy="6.6" rx="2.1" ry="2.8"/><ellipse cx="18" cy="10.4" rx="2.1" ry="2.7" transform="rotate(18 18 10.4)"/><path d="M12.1 12.2c2.4 0 4.3 1.7 4.5 3.6.2 1.6-1.1 2.7-2.7 2.5-.8-.1-1.2-.4-1.8-.4s-1 .3-1.8.4c-1.6.2-2.9-.9-2.7-2.5.2-1.9 2.1-3.6 4.5-3.6Z"/>'
  };

  function esc(v) {
    return String(v === null || v === undefined ? '' : v)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function icon(name, cls) {
    return '<svg class="icon' + (cls ? ' ' + cls : '') + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + (ICONS[name] || '') + '</svg>';
  }

  function svgPaw(cls) {
    return '<svg class="' + (cls || '') + '" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">' + ICONS.paw + '</svg>';
  }

  function toast(message, type) {
    var root = document.getElementById('toastRoot');
    var el = document.createElement('div');
    el.className = 'toast toast-' + (type || 'success');
    el.innerHTML = '<span class="toast-dot"></span><span>' + esc(message) + '</span>';
    root.appendChild(el);
    requestAnimationFrame(function () { el.classList.add('show'); });
    setTimeout(function () {
      el.classList.remove('show');
      setTimeout(function () { el.remove(); }, 240);
    }, 3200);
  }

  function celebrate(newBadges) {
    if (!newBadges || !newBadges.length) return;
    newBadges.forEach(function (b, i) {
      setTimeout(function () { toast('解锁勋章「' + b.name + '」' + b.icon, 'badge'); }, i * 420);
    });
  }

  function openModal(opts) {
    var root = document.getElementById('modalRoot');
    var footer = opts.footer ? '<div class="modal-footer">' + opts.footer + '</div>' : '';
    root.innerHTML =
      '<div class="modal-overlay" data-modal-overlay>' +
        '<div class="modal modal-' + (opts.size || 'md') + '" role="dialog" aria-modal="true" aria-labelledby="modalTitle">' +
          '<div class="modal-head">' +
            '<div><h2 id="modalTitle">' + esc(opts.title || '') + '</h2>' +
            (opts.subtitle ? '<p>' + esc(opts.subtitle) + '</p>' : '') + '</div>' +
            '<button type="button" class="icon-btn modal-x" data-modal-close aria-label="关闭">' + icon('close') + '</button>' +
          '</div>' +
          '<div class="modal-body">' + (opts.body || '') + '</div>' +
          footer +
        '</div>' +
      '</div>';
    document.body.classList.add('modal-open');
    var overlay = root.querySelector('.modal-overlay');
    requestAnimationFrame(function () { overlay.classList.add('open'); });
    var focusable = root.querySelector('input, select, textarea, button');
    if (focusable) setTimeout(function () { focusable.focus(); }, 60);
    if (opts.onMount) opts.onMount(root);
    return root;
  }

  function closeModal() {
    var root = document.getElementById('modalRoot');
    var overlay = root.querySelector('.modal-overlay');
    if (!overlay) return;
    overlay.classList.remove('open');
    document.body.classList.remove('modal-open');
    setTimeout(function () { root.innerHTML = ''; }, 180);
  }

  function confirmDialog(opts) {
    return new Promise(function (resolve) {
      var root = openModal({
        title: opts.title || '确认操作',
        subtitle: opts.subtitle || '',
        size: 'sm',
        body: '<p class="confirm-text">' + esc(opts.message || '') + '</p>' +
          (opts.note ? '<div class="notice notice-' + (opts.danger ? 'danger' : 'warn') + '">' + opts.note + '</div>' : ''),
        footer: '<button type="button" class="btn btn-ghost" data-confirm-cancel>取消</button>' +
          '<button type="button" class="btn ' + (opts.danger ? 'btn-danger' : 'btn-primary') + '" data-confirm-ok>' + esc(opts.confirmText || '确认') + '</button>'
      });
      function finish(v) { closeModal(); resolve(v); }
      root.querySelector('[data-confirm-ok]').addEventListener('click', function () { finish(true); });
      root.querySelector('[data-confirm-cancel]').addEventListener('click', function () { finish(false); });
      root.querySelector('[data-modal-overlay]').addEventListener('click', function (e) {
        if (e.target === e.currentTarget) finish(false);
      });
      root.querySelector('[data-modal-close]').addEventListener('click', function () { finish(false); });
    });
  }

  /* ---------------- 路由与渲染 ---------------- */
  function registerPage(name, def) { pages[name] = def; }

  function routeFromHash() {
    var raw = (location.hash || '').replace(/^#\/?/, '');
    return pages[raw] ? raw : 'dashboard';
  }

  function navigate(name) {
    if (!pages[name]) name = 'dashboard';
    if (location.hash === '#/' + name) {
      render();
    } else {
      location.hash = '#/' + name;
    }
    document.body.classList.remove('sidebar-open');
  }

  function pageTitle(route) {
    var p = pages[route];
    if (!p) return 'PawLife';
    return typeof p.title === 'function' ? p.title(state) : p.title;
  }

  function render() {
    currentRoute = routeFromHash();
    var page = pages[currentRoute] || pages.dashboard;
    var view = document.getElementById('view');
    if (!view || !page) return;
    view.innerHTML = page.render(state);
    document.getElementById('topbarTitle').textContent = pageTitle(currentRoute);
    document.getElementById('topbarSubtitle').textContent =
      typeof page.subtitle === 'function' ? page.subtitle(state) : (page.subtitle || '');
    document.title = pageTitle(currentRoute) + ' · PawLife';
    renderChrome();
    if (page.mount) page.mount(state);
  }

  function renderChrome() {
    var navItems = document.querySelectorAll('[data-route]');
    navItems.forEach(function (el) {
      var active = el.getAttribute('data-route') === currentRoute;
      el.classList.toggle('active', active);
      if (active) el.setAttribute('aria-current', 'page');
      else el.removeAttribute('aria-current');
    });
    var d = new Date();
    var week = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][d.getDay()];
    var dateEl = document.getElementById('topbarDate');
    if (dateEl) dateEl.textContent = d.getFullYear() + '年' + (d.getMonth() + 1) + '月' + d.getDate() + '日 · ' + week;
    var points = document.getElementById('pointsChip');
    if (points) points.querySelector('b').textContent = state.pet.pawPoints;
    var streak = document.getElementById('streakChip');
    if (streak) streak.querySelector('b').textContent = D.currentStreak(state);
    var avatar = document.getElementById('avatarBtn');
    if (avatar) avatar.setAttribute('title', state.pet.name + ' · 查看档案');
    var sidebarPet = document.getElementById('sidebarPet');
    if (sidebarPet) {
      sidebarPet.querySelector('b').textContent = state.pet.name;
      sidebarPet.querySelector('span').textContent = state.pet.breed + ' · 演示档案';
    }
    var reminderBadge = document.getElementById('navReminderBadge');
    if (reminderBadge) {
      var urgent = D.buildReminders(state).filter(function (r) {
        return !r.done && (r.status === 'overdue' || r.status === 'soon');
      }).length;
      reminderBadge.textContent = urgent;
      reminderBadge.style.display = urgent ? '' : 'none';
    }
  }

  function commit(opts) {
    D.Store.save(state);
    var y = window.scrollY;
    render();
    if (opts && opts.keepScroll) window.scrollTo(0, y);
    else window.scrollTo(0, 0);
  }

  function resetDemo() {
    confirmDialog({
      title: '重置演示数据',
      message: '将清除本浏览器中保存的全部演示操作，恢复到初始演示档案。',
      note: '该操作不会影响任何真实数据或原 Python 应用。',
      confirmText: '重置',
      danger: true
    }).then(function (ok) {
      if (!ok) return;
      state = D.Store.reset();
      PawApp.state = state;
      navigate('dashboard');
      render();
      toast('演示数据已重置');
    });
  }

  function exportState() {
    var blob = new Blob([JSON.stringify(state, null, 2)], { type: 'application/json;charset=utf-8' });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'pawlife-demo-' + D.todayISO() + '.json';
    document.body.appendChild(a);
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 0);
    toast('演示数据已导出为 JSON');
  }

  /* ---------------- SVG 折线图 ---------------- */
  function weightChart(logs, idealRange, opts) {
    opts = opts || {};
    var w = 760, h = opts.height || 280;
    var pad = { l: 52, r: 26, t: 22, b: 38 };
    var pw = w - pad.l - pad.r, ph = h - pad.t - pad.b;
    if (!logs || !logs.length) {
      return '<div class="chart-empty">这个时间段还没有体重记录</div>';
    }
    var values = logs.map(function (l) { return Number(l.weight); });
    var minV = Math.min.apply(null, values);
    var maxV = Math.max.apply(null, values);
    var spread = Math.max(0.5, maxV - minV);
    var yMin = Math.max(0, minV - spread * 0.35);
    var yMax = maxV + spread * 0.35;

    var start = D.parseISO(opts.rangeStart || logs[0].date).getTime();
    var end = D.parseISO(D.todayISO()).getTime();
    if (end - start < 86400000) { end = start + 86400000; }
    var dates = logs.map(function (l) { return D.parseISO(l.date).getTime(); });
    var minD = Math.min.apply(null, dates);
    var maxD = Math.max.apply(null, dates);
    if (minD < start) start = minD;
    if (maxD > end) end = maxD;

    function sx(t) { return pad.l + (t - start) / (end - start) * pw; }
    function sy(v) { return pad.t + (yMax - v) / (yMax - yMin) * ph; }

    var svg = '<svg class="weight-svg" viewBox="0 0 ' + w + ' ' + h + '" role="img" aria-label="体重趋势图">';
    svg += '<defs><linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">' +
      '<stop offset="0%" stop-color="#E87722" stop-opacity="0.22"/>' +
      '<stop offset="100%" stop-color="#E87722" stop-opacity="0"/></linearGradient></defs>';

    if (idealRange) {
      var bandTop = Math.max(pad.t, sy(idealRange[1]));
      var bandBottom = Math.min(pad.t + ph, sy(idealRange[0]));
      if (bandBottom > bandTop) {
        svg += '<rect x="' + pad.l + '" y="' + bandTop + '" width="' + pw + '" height="' + (bandBottom - bandTop) + '" fill="#5F8D4E" opacity="0.09" rx="4"/>';
        svg += '<line x1="' + pad.l + '" y1="' + bandTop + '" x2="' + (pad.l + pw) + '" y2="' + bandTop + '" stroke="#5F8D4E" stroke-opacity="0.35" stroke-dasharray="4 4"/>';
        if (bandBottom < pad.t + ph) {
          svg += '<line x1="' + pad.l + '" y1="' + bandBottom + '" x2="' + (pad.l + pw) + '" y2="' + bandBottom + '" stroke="#5F8D4E" stroke-opacity="0.35" stroke-dasharray="4 4"/>';
        }
        svg += '<text x="' + (pad.l + pw - 6) + '" y="' + Math.max(pad.t + 12, bandTop - 5) + '" text-anchor="end" class="chart-band-label">理想 ' + idealRange[0] + '–' + idealRange[1] + 'kg</text>';
      }
    }

    var gridCount = opts.compact ? 3 : 4;
    for (var g = 0; g <= gridCount; g++) {
      var gy = pad.t + ph * g / gridCount;
      var gv = yMax - (yMax - yMin) * g / gridCount;
      svg += '<line x1="' + pad.l + '" y1="' + gy + '" x2="' + (pad.l + pw) + '" y2="' + gy + '" class="chart-grid"/>';
      if (!opts.compact) {
        svg += '<text x="' + (pad.l - 10) + '" y="' + (gy + 4) + '" text-anchor="end" class="chart-axis">' + gv.toFixed(1) + '</text>';
      }
    }

    var labelCount = opts.compact ? 3 : 5;
    for (var i = 0; i < labelCount; i++) {
      var t = start + (end - start) * i / (labelCount - 1);
      var lx = sx(t);
      var ld = new Date(t);
      var label = (ld.getMonth() + 1) + '/' + ld.getDate();
      if (opts.compact) {
        if (i !== 0 && i !== labelCount - 1) continue;
      }
      svg += '<text x="' + lx + '" y="' + (pad.t + ph + 22) + '" text-anchor="' + (i === 0 ? 'start' : i === labelCount - 1 ? 'end' : 'middle') + '" class="chart-axis">' + label + '</text>';
    }

    var pts = logs.map(function (l) {
      return { x: sx(D.parseISO(l.date).getTime()), y: sy(Number(l.weight)), l: l };
    });

    if (pts.length > 1) {
      var area = 'M' + pts[0].x + ' ' + (pad.t + ph) + ' ';
      pts.forEach(function (p) { area += 'L' + p.x + ' ' + p.y + ' '; });
      area += 'L' + pts[pts.length - 1].x + ' ' + (pad.t + ph) + ' Z';
      svg += '<path d="' + area + '" fill="url(#areaGrad)"/>';
      svg += '<polyline points="' + pts.map(function (p) { return p.x + ',' + p.y; }).join(' ') + '" fill="none" stroke="#E87722" stroke-width="2.6" stroke-linejoin="round" stroke-linecap="round"/>';
    }

    pts.forEach(function (p, idx) {
      var isLast = idx === pts.length - 1;
      svg += '<circle cx="' + p.x + '" cy="' + p.y + '" r="' + (isLast ? 5.4 : 3.8) + '" fill="#fff" stroke="#E87722" stroke-width="2.2" class="chart-dot"/>';
      if (isLast) {
        svg += '<text x="' + p.x + '" y="' + (p.y - 13) + '" text-anchor="' + (p.x > pad.l + pw - 40 ? 'end' : 'middle') + '" class="chart-last-label">' + p.l.weight + 'kg</text>';
      }
      var tip = p.l.date + ' · ' + p.l.weight + 'kg';
      svg += '<circle cx="' + p.x + '" cy="' + p.y + '" r="14" fill="transparent" data-chart-tip="' + esc(tip) + '" class="chart-hit"/>';
    });

    svg += '</svg>';
    return '<div class="chart-wrap">' + svg + '<div class="chart-tip" id="chartTip"></div></div>';
  }

  function emptyState(iconName, title, desc, actionHtml) {
    return '<div class="empty-state"><div class="empty-icon">' + (iconName || '🐾') + '</div>' +
      '<h3>' + esc(title) + '</h3><p>' + esc(desc || '') + '</p>' + (actionHtml || '') + '</div>';
  }

  /* ---------------- 初始化与事件 ---------------- */
  function bindEvents() {
    var view = document.getElementById('view');

    view.addEventListener('click', function (e) {
      var nav = e.target.closest('[data-nav]');
      if (nav) {
        e.preventDefault();
        navigate(nav.getAttribute('data-nav'));
        return;
      }
      var act = e.target.closest('[data-action]');
      if (act) {
        var fn = actions[act.getAttribute('data-action')];
        if (fn) {
          e.preventDefault();
          fn(act.dataset, act, e);
        }
      }
    });

    view.addEventListener('submit', function (e) {
      var form = e.target.closest('form[data-form]');
      if (!form) return;
      e.preventDefault();
      var fn = forms[form.getAttribute('data-form')];
      if (fn) fn(form, e);
    });

    var sidebarNav = document.getElementById('sidebarNav');
    if (sidebarNav) {
      sidebarNav.addEventListener('click', function (e) {
        if (e.target.closest('[data-route]')) document.body.classList.remove('sidebar-open');
      });
    }

    document.getElementById('menuBtn').addEventListener('click', function () {
      document.body.classList.toggle('sidebar-open');
    });
    document.getElementById('sidebarScrim').addEventListener('click', function () {
      document.body.classList.remove('sidebar-open');
    });

    document.getElementById('pointsChip').addEventListener('click', function () { navigate('growth'); });
    document.getElementById('streakChip').addEventListener('click', function () { navigate('growth'); });
    document.getElementById('avatarBtn').addEventListener('click', function () { navigate('profile'); });

    document.getElementById('resetDemoBtn').addEventListener('click', resetDemo);

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        closeModal();
        document.body.classList.remove('sidebar-open');
      }
    });

    document.getElementById('modalRoot').addEventListener('click', function (e) {
      if (e.target.closest('[data-modal-close]')) closeModal();
      if (e.target.hasAttribute('data-modal-overlay')) closeModal();
    });

    document.getElementById('modalRoot').addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey && e.target && e.target.tagName === 'INPUT') {
        var primary = document.querySelector('.modal-footer .btn-primary');
        if (primary) {
          e.preventDefault();
          primary.click();
        }
      }
    });

    view.addEventListener('mousemove', function (e) {
      var tip = document.getElementById('chartTip');
      if (!tip) return;
      var hit = e.target.closest('[data-chart-tip]');
      if (!hit) { tip.classList.remove('show'); return; }
      var wrap = hit.closest('.chart-wrap');
      if (!wrap) return;
      var rect = wrap.getBoundingClientRect();
      tip.textContent = hit.getAttribute('data-chart-tip');
      tip.style.left = (e.clientX - rect.left) + 'px';
      tip.style.top = (e.clientY - rect.top) + 'px';
      tip.classList.add('show');
    });
    view.addEventListener('mouseleave', function () {
      var tip = document.getElementById('chartTip');
      if (tip) tip.classList.remove('show');
    });

    window.addEventListener('hashchange', function () {
      render();
      window.scrollTo(0, 0);
    });
  }

  function init() {
    state = D.Store.load();
    D.checkBadges(state);
    D.Store.save(state);
    document.querySelectorAll('[data-icon]').forEach(function (el) {
      el.innerHTML = icon(el.getAttribute('data-icon'));
    });
    bindEvents();
    if (!location.hash) {
      history.replaceState(null, '', '#/dashboard');
    }
    render();
  }

  var PawApp = {
    registerPage: registerPage,
    actions: actions,
    forms: forms,
    state: null,
    icon: icon,
    paw: svgPaw,
    esc: esc,
    toast: toast,
    celebrate: celebrate,
    openModal: openModal,
    closeModal: closeModal,
    confirm: confirmDialog,
    navigate: navigate,
    commit: commit,
    render: render,
    exportState: exportState,
    weightChart: weightChart,
    emptyState: emptyState,
    currentRoute: function () { return currentRoute; },
    D: D
  };

  PawApp.state = state;
  document.addEventListener('DOMContentLoaded', function () {
    init();
    PawApp.state = state;
  });

  /* 页面模块在 DOMContentLoaded 之前注册，init 时 state 已就绪 */
  Object.defineProperty(PawApp, 'state', {
    get: function () { return state; },
    set: function (v) { state = v; },
    configurable: true
  });

  return PawApp;
})();
