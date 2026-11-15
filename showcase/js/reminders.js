/* PawLife 展示版 — 照护提醒中心 */
(function () {
  'use strict';

  var A = window.PawApp;
  var D = window.PawData;
  var esc = A.esc;

  function daysText(n) {
    if (n === null || n === undefined) return '待补充';
    if (n < 0) return '已逾期 ' + Math.abs(n) + ' 天';
    if (n === 0) return '今天到期';
    return n + ' 天后';
  }

  function statusMeta(status) {
    return {
      overdue: ['status-overdue', '需处理'],
      soon: ['status-soon', '即将到期'],
      ok: ['status-ok', '状态正常'],
      none: ['status-none', '待补充']
    }[status] || ['status-none', '待补充'];
  }

  function actionButton(r) {
    if (r.id === 'weight') {
      return '<button type="button" class="btn btn-primary btn-sm" data-action="openWeightModal">去记录体重</button>';
    }
    if (r.id === 'bcs') {
      return '<button type="button" class="btn btn-primary btn-sm" data-nav="trends">去评估体况</button>';
    }
    var typeMap = { vaccine: '疫苗', deworm: '驱虫', bath: '洗澡澡' };
    var type = typeMap[r.id] || '疫苗';
    return '<button type="button" class="btn btn-primary btn-sm" data-action="openEventModal" data-type="' + type + '">' + esc(r.actionText) + '</button>';
  }

  function renderCareCard(r) {
    var st = statusMeta(r.status);
    return '<div class="care-card' + (r.done ? ' is-done' : '') + '">' +
      '<span class="care-ico">' + r.icon + '</span>' +
      '<div class="care-main">' +
        '<div class="care-top"><b>' + esc(r.title) + '</b>' +
          '<span class="status ' + (r.done ? 'status-done' : st[0]) + '">' + (r.done ? '已处理' : (r.daysLeft === null ? st[1] : daysText(r.daysLeft))) + '</span>' +
        '</div>' +
        '<p>' + esc(r.desc) + '</p>' +
        '<div class="care-meta">' + esc(r.category) + ' · 基于最近记录自动计算</div>' +
      '</div>' +
      '<div class="care-actions">' +
        (r.done
          ? '<button type="button" class="btn btn-ghost btn-sm" data-action="toggleReminder" data-id="' + r.id + '" data-done="true">撤销已处理</button>'
          : actionButton(r) + '<button type="button" class="btn btn-ghost btn-sm" data-action="toggleReminder" data-id="' + r.id + '" data-done="false">标记已处理</button>') +
      '</div>' +
    '</div>';
  }

  function renderTodayItems(state) {
    var rows = [
      {
        icon: '🐾',
        title: '每日签到',
        desc: '签到获得 1 枚爪印，连续签到累计天数',
        done: D.checkedToday(state),
        action: 'checkinToday',
        button: '立即签到 +1'
      },
      {
        icon: '🩺',
        title: '今日健康检查',
        desc: '触摸头部、背部、四肢和腹部，确认是否有异常',
        done: D.dailyCheckDone(state),
        action: 'openDailyCheck',
        button: '开始检查'
      },
      {
        icon: '✅',
        title: '每日小任务',
        desc: D.todayTask(state).task,
        done: D.taskDoneToday(state),
        action: 'completeTodayTask',
        button: D.todayTask(state).action
      }
    ];
    return rows.map(function (r) {
      return '<div class="care-card today-card' + (r.done ? ' is-done' : '') + '">' +
        '<span class="care-ico">' + r.icon + '</span>' +
        '<div class="care-main"><div class="care-top"><b>' + esc(r.title) + '</b>' +
          '<span class="status ' + (r.done ? 'status-done' : 'status-soon') + '">' + (r.done ? '已完成' : '待完成') + '</span></div>' +
          '<p>' + esc(r.desc) + '</p></div>' +
        '<div class="care-actions">' +
          (r.done
            ? '<button type="button" class="btn btn-secondary btn-sm" disabled>今天已完成</button>'
            : '<button type="button" class="btn btn-primary btn-sm" data-action="' + r.action + '">' + esc(r.button) + '</button>') +
        '</div>' +
      '</div>';
    }).join('');
  }

  function renderReminders(state) {
    var all = D.buildReminders(state);
    var pending = all.filter(function (r) { return !r.done && (r.status === 'overdue' || r.status === 'soon'); })
      .sort(function (a, b) { return (a.daysLeft || 0) - (b.daysLeft || 0); });
    var normal = all.filter(function (r) { return !r.done && r.status === 'ok'; })
      .sort(function (a, b) { return (a.daysLeft || 0) - (b.daysLeft || 0); });
    var doneCare = all.filter(function (r) { return r.done; });
    var todayDone = [D.checkedToday(state), D.dailyCheckDone(state), D.taskDoneToday(state)].filter(Boolean).length;
    var completedCount = doneCare.length + todayDone;
    var suspended = state.suspendedUntil && state.suspendedUntil >= D.todayISO();

    var pendingCount = pending.length + (3 - todayDone);
    return '<div class="page-intro">' +
      '<div><h2>照护提醒中心</h2><p>根据健康记录计算今日任务、即将到期事项与已完成记录。</p></div>' +
      '<button type="button" class="btn btn-primary btn-sm" data-action="openEventModal">' + A.icon('plus') + '记录事件</button>' +
    '</div>' +

    (suspended
      ? '<div class="notice notice-danger" style="margin-bottom:18px">' + A.icon('alert') +
        '<span>最近记录了高风险症状，今日营养建议处于暂停状态。请优先联系兽医，稳定后可在营养页恢复展示。</span></div>'
      : '') +

    '<div class="reminder-summary">' +
      '<div class="summary-tile"><span>待完成</span><b>' + pendingCount + '</b><em>今日任务与需处理事项</em></div>' +
      '<div class="summary-tile"><span>即将到期</span><b>' + pending.length + '</b><em>逾期或 30 天内到期</em></div>' +
      '<div class="summary-tile"><span>已完成</span><b>' + completedCount + '</b><em>今日已处理的照护事项</em></div>' +
    '</div>' +

    '<div class="reminder-section card">' +
      '<div class="card-head"><div class="card-head-main">' +
        '<div class="card-title">' + A.icon('check') + '今日任务</div>' +
        '<div class="card-sub">签到、健康检查与每日小任务</div>' +
      '</div><span class="chip chip-brand">' + todayDone + ' / 3</span></div>' +
      renderTodayItems(state) +
    '</div>' +

    '<div class="reminder-section card">' +
      '<div class="card-head"><div class="card-head-main">' +
        '<div class="card-title">' + A.icon('alert') + '需处理 / 即将到期</div>' +
        '<div class="card-sub">按剩余天数排序</div>' +
      '</div><span class="chip ' + (pending.length ? 'chip-amber' : 'chip-green') + '">' + pending.length + ' 项</span></div>' +
      (pending.length ? pending.map(renderCareCard).join('') : A.emptyState('✅', '没有逾期或即将到期的事项', '疫苗、驱虫、洗澡和体重记录都在正常节奏内。')) +
    '</div>' +

    '<div class="reminder-section card">' +
      '<div class="card-head"><div class="card-head-main">' +
        '<div class="card-title">' + A.icon('calendar') + '状态正常</div>' +
        '<div class="card-sub">仍在建议周期内，可提前了解下一次时间</div>' +
      '</div><span class="chip chip-green">' + normal.length + ' 项</span></div>' +
      (normal.length ? normal.map(renderCareCard).join('') : '<p class="small muted" style="padding:8px 4px">暂无状态正常的长周期提醒。</p>') +
    '</div>' +

    '<div class="reminder-section card">' +
      '<div class="card-head"><div class="card-head-main">' +
        '<div class="card-title">' + A.icon('check') + '已完成</div>' +
        '<div class="card-sub">今日已处理的照护事项，可撤销</div>' +
      '</div><span class="chip chip-green">' + completedCount + ' 项</span></div>' +
      (completedCount
        ? '<div class="done-list">' +
            [D.checkedToday(state) ? '每日签到' : '', D.dailyCheckDone(state) ? '今日健康检查' : '', D.taskDoneToday(state) ? '每日小任务' : ''].filter(Boolean)
              .map(function (t) { return '<span class="done-item">' + A.icon('check') + t + '</span>'; }).join('') +
          '</div>' +
          (doneCare.length ? '<div class="done-care-list">' + doneCare.map(renderCareCard).join('') + '</div>' : '')
        : '<p class="small muted" style="padding:8px 4px">还没有完成的事项，从今日任务开始吧。</p>') +
    '</div>' +

    '<div class="notice notice-info" style="margin-top:18px">' + A.icon('alert') +
      '<span>提醒规则：疫苗按 365 天估算；驱虫幼犬 30 天 / 成犬 90 天；洗澡按档案建议间隔；体重幼犬 10 天 / 成犬 35 天；BCS 偏瘦或偏重 14 天、理想 30 天。展示版不使用推送或短信。</span>' +
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
    title: '照护提醒',
    subtitle: '今日与即将到期的照护事项',
    render: renderReminders
  });
})();
