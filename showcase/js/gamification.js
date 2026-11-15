/* PawLife 展示版 — 成长与激励 */
(function () {
  'use strict';

  var A = window.PawApp;
  var D = window.PawData;
  var esc = A.esc;

  var LEVELS = [
    { min: 0, name: '新手铲屎官', desc: '刚刚开始记录，好的习惯正在形成' },
    { min: 30, name: '日常守护者', desc: '已经建立稳定的日常照护节奏' },
    { min: 80, name: '健康管理者', desc: '记录完整，能够看到长期趋势' },
    { min: 150, name: '资深伙伴', desc: '长期坚持，把照护变成默契' },
    { min: 300, name: '传说铲屎官', desc: '稳定、细致、持续陪伴' }
  ];

  function levelOf(points) {
    var idx = 0;
    for (var i = 0; i < LEVELS.length; i++) if (points >= LEVELS[i].min) idx = i;
    var next = LEVELS[idx + 1] || null;
    var spanStart = LEVELS[idx].min;
    var pct = next ? Math.round((points - spanStart) / (next.min - spanStart) * 100) : 100;
    return { idx: idx, level: LEVELS[idx], next: next, pct: pct };
  }

  function renderHero(state) {
    var lv = levelOf(state.pet.pawPoints);
    var unlocked = state.badges.length;
    var total = D.BADGES.length;
    return '<section class="growth-hero">' +
      '<div class="growth-hero-main">' +
        '<div class="growth-eyebrow">成长与激励</div>' +
        '<h2>' + esc(state.pet.name) + '已经陪伴你 ' + Math.max(0, D.diffDays(D.todayISO(), state.pet.createdAt)) + ' 天</h2>' +
        '<p>' + lv.level.desc + '</p>' +
        '<div class="growth-level"><span class="level-chip">Lv.' + (lv.idx + 1) + ' ' + lv.level.name + '</span>' +
          (lv.next ? '<span class="tiny muted">距 ' + lv.next.name + ' 还需 ' + (lv.next.min - state.pet.pawPoints) + ' 枚爪印</span>' : '<span class="tiny muted">已达到最高阶段</span>') +
        '</div>' +
        '<div class="progress" style="margin-top:10px;max-width:420px"><i style="width:' + lv.pct + '%"></i></div>' +
      '</div>' +
      '<div class="growth-kpis">' +
        '<div class="growth-kpi"><span>🐾 爪印积分</span><b>' + state.pet.pawPoints + '</b></div>' +
        '<div class="growth-kpi"><span>🔥 连续签到</span><b>' + D.currentStreak(state) + '<small> 天</small></b></div>' +
        '<div class="growth-kpi"><span>🎖️ 勋章</span><b>' + unlocked + '<small> / ' + total + '</small></b></div>' +
      '</div>' +
    '</section>';
  }

  function renderCheckin(state) {
    var checked = D.checkedToday(state);
    var days = state.checkin.checkinDays || [];
    var last14 = [];
    for (var i = 13; i >= 0; i--) {
      var iso = D.daysAgoISO(i);
      last14.push({ iso: iso, checked: days.indexOf(iso) !== -1, today: i === 0, day: D.parseISO(iso).getDate() });
    }
    return '<div class="card">' +
      '<div class="card-head"><div class="card-head-main">' +
        '<div class="card-title">' + A.icon('calendar') + '每日签到</div>' +
        '<div class="card-sub">每天签到获得 1 枚爪印，连续签到会累计天数</div>' +
      '</div><span class="chip ' + (checked ? 'chip-green' : 'chip-brand') + '">' + (checked ? '今日已签到' : '今日待签到') + '</span></div>' +
      '<div class="checkin-calendar">' + last14.map(function (d) {
        return '<div class="checkin-day' + (d.checked ? ' is-checked' : '') + (d.today ? ' is-today' : '') + '">' +
          '<span>' + d.day + '</span><i>' + (d.checked ? '✓' : '') + '</i></div>';
      }).join('') + '</div>' +
      '<div class="checkin-footer">' +
        '<div><b>连续 ' + D.currentStreak(state) + ' 天</b><span>签到里程碑：7 / 14 / 30 / 60 天</span></div>' +
        (checked
          ? '<button type="button" class="btn btn-secondary btn-sm" disabled>今天已签到</button>'
          : '<button type="button" class="btn btn-primary" data-action="checkinToday">🐾 立即签到 +1</button>') +
      '</div>' +
    '</div>';
  }

  function renderTask(state) {
    var task = D.todayTask(state);
    var done = D.taskDoneToday(state);
    return '<div class="card">' +
      '<div class="card-head"><div class="card-head-main">' +
        '<div class="card-title">' + A.icon('check') + '今日小任务</div>' +
        '<div class="card-sub">每天轮换一项轻量照护任务</div>' +
      '</div><span class="chip ' + (done ? 'chip-green' : 'chip-amber') + '">' + (done ? '已完成 +2' : '待完成 +2') + '</span></div>' +
      '<p class="daily-task-text">' + esc(task.task) + '</p>' +
      '<div class="card-actions" style="margin-top:16px">' +
        (done
          ? '<button type="button" class="btn btn-secondary btn-sm" disabled>今天已完成</button>'
          : '<button type="button" class="btn btn-primary btn-sm" data-action="completeTodayTask">' + esc(task.action) + '</button>') +
        (task.page && !done ? '<button type="button" class="btn btn-ghost btn-sm" data-nav="' + task.page + '">前往相关页面</button>' : '') +
      '</div>' +
      '<div class="notice notice-info" style="margin-top:16px">' + A.icon('sparkles') + '<span>完成任务会自动补签，并同时获得签到 +1 与任务 +2 爪印。</span></div>' +
    '</div>';
  }

  function badgeStatus(state, name) {
    return state.badges.filter(function (b) { return b.name === name; })[0] || null;
  }

  function formatLogDate(value) {
    var parts = String(value).split('T');
    var d = parts[0].split('-');
    if (d.length !== 3) return value;
    return Number(d[1]) + '月' + Number(d[2]) + '日' + (parts[1] ? ' ' + parts[1] : '');
  }

  function renderBadgeWall(state) {
    var cats = ['第一次', '守护者', '健康里程碑'];
    var html = cats.map(function (cat) {
      var list = D.BADGES.filter(function (b) { return b.category === cat; });
      var unlocked = list.filter(function (b) { return badgeStatus(state, b.name); }).length;
      return '<div class="badge-group">' +
        '<div class="badge-group-head"><span>' + cat + '</span><em>' + unlocked + ' / ' + list.length + '</em></div>' +
        '<div class="badge-grid">' + list.map(function (b) {
          var got = badgeStatus(state, b.name);
          return '<button type="button" class="badge-tile' + (got ? ' unlocked' : ' locked') + '" data-action="openBadge" data-name="' + esc(b.name) + '">' +
            '<span class="badge-icon">' + b.icon + '</span>' +
            '<b>' + esc(b.name) + '</b>' +
            '<em>' + (got ? esc(got.date) : '未解锁') + '</em>' +
          '</button>';
        }).join('') + '</div>' +
      '</div>';
    }).join('');
    return '<div class="card">' +
      '<div class="card-head"><div class="card-head-main">' +
        '<div class="card-title">' + A.icon('trophy') + '勋章墙</div>' +
        '<div class="card-sub">共 ' + D.BADGES.length + ' 枚 · 已解锁 ' + state.badges.length + ' 枚</div>' +
      '</div><span class="chip chip-brand">' + Math.round(state.badges.length / D.BADGES.length * 100) + '%</span></div>' +
      html +
    '</div>';
  }

  function nextBadge(state) {
    var vc = state.events.filter(function (e) { return e.type === '疫苗'; }).length;
    var dc = state.events.filter(function (e) { return e.type === '驱虫'; }).length;
    var taskCount = state.checkin.taskDates.filter(function (d) { return d >= D.daysAgoISO(30); }).length;
    var bcsIdeal = state.bcsLogs.slice().sort(function (a, b) { return a.date < b.date ? 1 : -1; }).slice(0, 3).filter(function (l) { return l.state === 'ideal'; }).length;
    var guardians = D.BADGES.filter(function (b) { return b.category === '守护者'; });
    var unlockedGuardians = guardians.filter(function (b) { return badgeStatus(state, b.name); }).length;
    var candidates = [
      { name: '免疫完成', have: vc, need: 3, unit: '次疫苗' },
      { name: '驱虫达标', have: dc, need: 6, unit: '次驱虫' },
      { name: '洁齿坚持', have: taskCount, need: 15, unit: '次任务' },
      { name: '体态管理', have: bcsIdeal, need: 3, unit: '次理想 BCS' },
      { name: '健康大满贯', have: unlockedGuardians, need: guardians.length, unit: '枚守护者勋章' }
    ].filter(function (c) { return !badgeStatus(state, c.name); });
    if (!candidates.length) return null;
    candidates.sort(function (a, b) { return (b.have / b.need) - (a.have / a.need); });
    return candidates[0];
  }

  function renderNextBadge(state) {
    var next = nextBadge(state);
    if (!next) {
      return '<div class="card">' + A.emptyState('🏆', '全部勋章已解锁', '这份档案已经完成当前所有可判定的成就。') + '</div>';
    }
    var def = D.BADGES.filter(function (b) { return b.name === next.name; })[0];
    var pct = Math.min(100, Math.round(next.have / next.need * 100));
    return '<div class="card next-badge-card">' +
      '<div class="card-head"><div class="card-head-main">' +
        '<div class="card-title">' + A.icon('sparkles') + '下一枚勋章</div>' +
        '<div class="card-sub">距离最近的成就</div>' +
      '</div></div>' +
      '<div class="next-badge-main">' +
        '<span class="next-badge-icon">' + def.icon + '</span>' +
        '<div><b>' + esc(def.name) + '</b><p>' + esc(def.condition) + '</p></div>' +
      '</div>' +
      '<div class="next-badge-progress"><span>' + next.have + ' / ' + next.need + ' ' + next.unit + '</span><em>' + pct + '%</em></div>' +
      '<div class="progress" style="margin-top:6px"><i style="width:' + pct + '%"></i></div>' +
    '</div>';
  }

  function renderPoints(state) {
    var logs = state.pointsLog.slice(0, 8);
    return '<div class="card">' +
      '<div class="card-head"><div class="card-head-main">' +
        '<div class="card-title">' + A.icon('paw') + '爪印明细</div>' +
        '<div class="card-sub">签到 +1 · 任务 +2 · 记录事件 / 健康检查 +1</div>' +
      '</div><span class="chip chip-brand">' + state.pet.pawPoints + ' 枚</span></div>' +
      '<ul class="points-list">' + logs.map(function (p) {
        return '<li><span class="point-ico">🐾</span><div><b>' + esc(p.reason) + '</b><em>' + esc(formatLogDate(p.date)) + '</em></div><strong>+' + p.amount + '</strong></li>';
      }).join('') + '</ul>' +
    '</div>';
  }

  function renderTimeline(state) {
    var items = state.badges.map(function (b) {
      var def = D.BADGES.filter(function (d) { return d.name === b.name; })[0] || {};
      return { date: b.date, name: b.name, icon: def.icon || '🎖️', type: 'badge' };
    }).concat(state.weightLogs.slice(-6).map(function (w) {
      return { date: w.date, name: '体重记录 ' + w.weight + ' kg', icon: '⚖️', type: 'weight' };
    }));
    items.sort(function (a, b) { return a.date < b.date ? 1 : -1; });
    items = items.slice(0, 8);
    return '<div class="card">' +
      '<div class="card-head"><div class="card-head-main">' +
        '<div class="card-title">' + A.icon('clipboard') + '成长印记</div>' +
        '<div class="card-sub">勋章解锁与体重记录</div>' +
      '</div></div>' +
      '<ul class="growth-timeline">' + items.map(function (it) {
        return '<li><span class="gt-ico">' + it.icon + '</span><div><b>' + esc(it.name) + '</b><em>' + esc(it.date) + '</em></div></li>';
      }).join('') + '</ul>' +
    '</div>';
  }

  function renderGrowth(state) {
    return '<div class="page-stack">' +
      renderHero(state) +
      '<div class="growth-grid">' +
        '<div class="growth-col">' + renderCheckin(state) + renderTask(state) + renderPoints(state) + '</div>' +
        '<div class="growth-col">' + renderNextBadge(state) + renderTimeline(state) + '</div>' +
      '</div>' +
      renderBadgeWall(state) +
    '</div>';
  }

  A.actions.openBadge = function (dataset) {
    var name = dataset.name;
    var def = D.BADGES.filter(function (b) { return b.name === name; })[0];
    if (!def) return;
    var got = badgeStatus(A.state, name);
    A.openModal({
      title: def.name,
      subtitle: def.category + ' · ' + (got ? '已解锁' : '未解锁'),
      size: 'sm',
      body: '<div class="badge-modal">' +
        '<div class="badge-modal-icon' + (got ? '' : ' locked') + '">' + def.icon + '</div>' +
        '<p class="badge-modal-condition">' + esc(def.condition) + '</p>' +
        (got
          ? '<div class="notice notice-green">' + A.icon('check') + '<span>解锁日期：' + esc(got.date) + '。这枚勋章已记录在你的成长档案中。</span></div>'
          : '<div class="notice notice-info">' + A.icon('sparkles') + '<span>继续完成对应照护记录即可解锁。展示版会在数据满足条件时自动判定。</span></div>') +
      '</div>',
      footer: '<button type="button" class="btn btn-primary" data-modal-close>知道了</button>'
    });
  };

  A.registerPage('growth', {
    title: '成长与激励',
    subtitle: '签到、任务、爪印与勋章',
    render: renderGrowth
  });
})();
