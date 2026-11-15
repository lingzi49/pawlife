/* PawLife 展示版 — 贴心闹钟 */
(function () {
  'use strict';

  var A = window.PawApp;
  var D = window.PawData;
  var esc = A.esc;

  function subHeader(title) {
    return '<div class="sub-page-header"><div class="sub-page-header-row">' +
      '<button type="button" class="btn-back-icon" data-nav="home" title="返回首页">←</button>' +
      '<span class="sub-page-title">' + title + '</span>' +
      '<button type="button" class="today-avatar-sm" data-action="openProfileModal" title="查看/编辑档案">' +
        '<img src="assets/images/tuantuan.svg" alt="' + esc(A.state.pet.name) + ' 的演示头像" />' +
      '</button>' +
    '</div></div>';
  }

  function daysText(n) {
    if (n === null || n === undefined) return '待补充';
    if (n < 0) return '已逾期 ' + Math.abs(n) + ' 天';
    if (n === 0) return '今天到期';
    return n + ' 天后';
  }

  function actionFor(r) {
    if (r.id === 'weight') {
      return '<button type="button" class="reminder-action" data-action="openWeightModal">去记录体重 →</button>';
    }
    if (r.id === 'bcs') {
      return '<button type="button" class="reminder-action" data-action="openWeightModal">去评估体况 →</button>';
    }
    var typeMap = { vaccine: '疫苗', deworm: '驱虫', bath: '洗澡澡' };
    var type = typeMap[r.id] || '疫苗';
    return '<button type="button" class="reminder-action" data-action="quickRecord" data-type="' + type + '">去记录 →</button>';
  }

  function renderReminder(r, done) {
    var urgent = r.status === 'overdue';
    return '<div class="reminder-card' + (urgent ? ' reminder-urgent' : '') + (done ? ' is-done' : '') + '">' +
      '<div class="reminder-icon">' + r.icon + '</div>' +
      '<div class="reminder-body">' +
        '<div class="reminder-title">' + esc(r.title) + '</div>' +
        '<div class="reminder-desc">' + esc(r.desc) + '</div>' +
        (r.daysLeft !== null ? '<div class="reminder-days">' + (done ? '已处理' : daysText(r.daysLeft)) + '</div>' : '') +
        '<div class="reminder-actions-row">' +
          (done
            ? '<button type="button" class="reminder-action muted" data-action="toggleReminder" data-id="' + r.id + '" data-done="true">撤销已处理</button>'
            : actionFor(r) + '<button type="button" class="reminder-action muted" data-action="toggleReminder" data-id="' + r.id + '" data-done="false">标记已处理</button>') +
        '</div>' +
      '</div>' +
    '</div>';
  }

  function renderReminders(state) {
    var all = D.buildReminders(state);
    var pending = all.filter(function (r) { return !r.done; })
      .sort(function (a, b) {
        var rank = { overdue: 0, soon: 1, ok: 2, none: 3 };
        return (rank[a.status] - rank[b.status]) || ((a.daysLeft || 0) - (b.daysLeft || 0));
      });
    var done = all.filter(function (r) { return r.done; });

    return '<div class="sub-page">' +
      subHeader('📅 ' + esc(state.pet.name) + '的贴心闹钟') +
      '<div class="reminders-intro">📋 根据健康记录自动生成提醒，疫苗、驱虫、洗澡和体况评估都不遗漏。</div>' +
      (pending.length
        ? pending.map(function (r) { return renderReminder(r, false); }).join('')
        : A.emptyState('✅', '当前没有待处理提醒', '疫苗、驱虫和洗澡计划都在正常范围内。')) +
      (done.length
        ? '<div class="reminders-done-title">已处理</div>' + done.map(function (r) { return renderReminder(r, true); }).join('')
        : '') +
      '<div class="notice notice-info">提醒规则：疫苗按 365 天估算；驱虫幼犬 30 天 / 成犬 90 天；洗澡按档案建议间隔；体重幼犬 10 天 / 成犬 35 天；BCS 偏瘦或偏重 14 天、理想 30 天。展示版不使用推送或短信。</div>' +
    '</div>';
  }

  A.actions.toggleReminder = function (dataset) {
    var id = dataset.id;
    var currentlyDone = dataset.done === 'true';
    D.markReminderDone(A.state, id, !currentlyDone);
    A.commit({ keepScroll: true });
    A.toast(currentlyDone ? '已恢复为待处理' : '已标记为已处理');
  };

  A.registerPage('reminders', {
    title: '贴心闹钟',
    render: renderReminders
  });
})();
