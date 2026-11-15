/* PawLife 展示版 — 首页仪表盘与宠物档案 */
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

  function relativeDate(iso) {
    var diff = D.diffDays(D.todayISO(), iso);
    if (diff === 0) return '今天';
    if (diff === 1) return '昨天';
    if (diff < 7) return diff + ' 天前';
    var d = D.parseISO(iso);
    return (d.getMonth() + 1) + '月' + d.getDate() + '日';
  }

  function greeting() {
    var h = new Date().getHours();
    if (h < 6) return '夜深了';
    if (h < 11) return '早上好';
    if (h < 14) return '中午好';
    if (h < 18) return '下午好';
    return '晚上好';
  }

  function reminderStatus(status) {
    var map = {
      overdue: ['status-overdue', '需处理'],
      soon: ['status-soon', '即将到期'],
      ok: ['status-ok', '状态正常'],
      none: ['status-none', '待补充']
    };
    return map[status] || map.none;
  }

  function renderHero(state) {
    var pet = state.pet;
    var range = D.idealRange(pet.breed);
    var bcs = D.latestBCS(state);
    var bcsText = bcs ? ({ ideal: '理想', heavy: '偏重', thin: '偏瘦' }[bcs.state] || '未评估') : '未评估';
    var bcsClass = bcs ? (bcs.state === 'ideal' ? 'chip-green' : bcs.state === 'thin' ? 'chip-amber' : 'chip-red') : 'chip-muted';
    return '' +
      '<section class="hero">' +
        '<div class="hero-glow" aria-hidden="true"></div>' +
        '<div class="hero-mark" aria-hidden="true">' + A.paw('hero-paw') + '</div>' +
        '<div class="hero-main">' +
          '<div class="pet-avatar pet-avatar-lg">' +
            '<img src="assets/images/tuantuan.svg" alt="' + esc(pet.name) + ' 的演示头像" />' +
          '</div>' +
          '<div class="hero-info">' +
            '<div class="hero-eyebrow">' + greeting() + '，' + esc(pet.name) + '的主人</div>' +
            '<h2>' + esc(pet.name) + '今天也要元气满满 <span class="hero-wave">🐾</span></h2>' +
            '<div class="hero-tags">' +
              '<span class="chip chip-brand">' + esc(pet.breed) + '</span>' +
              '<span class="chip">' + esc(D.ageText(pet.birthday)) + '</span>' +
              '<span class="chip">' + (pet.gender === 'male' ? '公犬' : '母犬') + '</span>' +
              '<span class="chip">' + (pet.neutered === '是' ? '已绝育' : pet.neutered === '否' ? '未绝育' : '绝育未知') + '</span>' +
            '</div>' +
            '<div class="hero-vitals">' +
              '<div class="vital"><span>当前体重</span><b>' + esc(pet.weight) + ' kg</b><em>' + (range ? '理想 ' + range[0] + '–' + range[1] + 'kg' : '暂无品种参考') + '</em></div>' +
              '<div class="vital"><span>体况评分</span><b>' + bcsText + '</b><em>' + (bcs ? '最近 ' + relativeDate(bcs.date) : '去趋势页评估') + '</em></div>' +
              '<div class="vital"><span>连续签到</span><b>' + D.currentStreak(state) + ' 天</b><em>累计 ' + pet.pawPoints + ' 枚爪印</em></div>' +
            '</div>' +
            '<div class="hero-actions">' +
              '<button type="button" class="btn btn-primary" data-action="openEventModal">' + A.icon('plus') + '记录健康事件</button>' +
              '<button type="button" class="btn btn-secondary" data-action="openWeightModal">' + A.icon('scale') + '更新体重</button>' +
              '<span class="hero-bcs ' + bcsClass + '">BCS · ' + bcsText + '</span>' +
            '</div>' +
          '</div>' +
        '</div>' +
      '</section>';
  }

  function renderStats(state) {
    var doneCount = (D.checkedToday(state) ? 1 : 0) + (D.dailyCheckDone(state) ? 1 : 0) + (D.taskDoneToday(state) ? 1 : 0);
    var reminders = D.buildReminders(state);
    var vaccine = reminders.filter(function (r) { return r.id === 'vaccine'; })[0];
    var deworm = reminders.filter(function (r) { return r.id === 'deworm'; })[0];
    var stats = D.weightStats(state.weightLogs, 30);
    var change = stats ? stats.change : 0;
    var changeClass = change > 0 ? 'trend-up' : change < 0 ? 'trend-down' : 'trend-flat';
    return '' +
      '<section class="stat-grid">' +
        '<div class="stat-tile">' +
          '<div class="stat-top"><span>今日待办</span><span class="stat-ico">' + A.icon('clipboard') + '</span></div>' +
          '<div class="stat-value">' + doneCount + '<small>/ 3 已完成</small></div>' +
          '<div class="progress" style="margin-top:12px"><i style="width:' + (doneCount / 3 * 100) + '%"></i></div>' +
        '</div>' +
        '<div class="stat-tile">' +
          '<div class="stat-top"><span>下次疫苗</span><span class="stat-ico">💉</span></div>' +
          '<div class="stat-value ' + (vaccine && vaccine.status === 'soon' ? 'text-amber' : '') + '">' + (vaccine ? daysText(vaccine.daysLeft) : '待补充') + '</div>' +
          '<div class="stat-foot">' + (vaccine ? esc(vaccine.category) + ' · 按 365 天周期估算' : '还没有疫苗记录') + '</div>' +
        '</div>' +
        '<div class="stat-tile">' +
          '<div class="stat-top"><span>下次驱虫</span><span class="stat-ico">🛡️</span></div>' +
          '<div class="stat-value ' + (deworm && deworm.status === 'soon' ? 'text-amber' : '') + '">' + (deworm ? daysText(deworm.daysLeft) : '待补充') + '</div>' +
          '<div class="stat-foot">' + (deworm ? '体内外驱虫 · 90 天间隔' : '还没有驱虫记录') + '</div>' +
        '</div>' +
        '<div class="stat-tile">' +
          '<div class="stat-top"><span>近 30 天体重</span><span class="stat-ico">' + A.icon('chart') + '</span></div>' +
          '<div class="stat-value">' + (stats ? stats.latest : esc(state.pet.weight)) + '<small> kg</small></div>' +
          '<div class="stat-foot"><span class="' + changeClass + '">' + (change > 0 ? '↑ +' : change < 0 ? '↓ ' : '→ ') + change + ' kg</span> 较区间起点</div>' +
        '</div>' +
      '</section>';
  }

  function renderTasks() {
    var items = [
      {
        id: 'checkin', title: '每日签到', desc: '签到可获得 1 枚爪印，保持记录习惯', done: D.checkedToday(A.state),
        action: 'checkinToday', icon: '🐾'
      },
      {
        id: 'daily', title: '今日健康检查', desc: '花 1 分钟摸摸头部、背部、四肢和腹部', done: D.dailyCheckDone(A.state),
        action: 'openDailyCheck', icon: '🩺'
      },
      {
        id: 'task', title: '每日小任务', desc: D.todayTask(A.state).task, done: D.taskDoneToday(A.state),
        action: 'completeTodayTask', icon: '✅'
      }
    ];
    var html = items.map(function (item) {
      return '<div class="task-row' + (item.done ? ' is-done' : '') + '">' +
        '<button type="button" class="task-check" data-action="' + item.action + '" aria-label="' + (item.done ? '已完成' : '完成') + esc(item.title) + '">' +
          (item.done ? A.icon('check') : '') +
        '</button>' +
        '<div class="task-body"><b>' + item.icon + ' ' + esc(item.title) + '</b><span>' + esc(item.desc) + '</span></div>' +
        (item.done
          ? '<span class="status status-done">已完成</span>'
          : '<button type="button" class="btn btn-soft btn-sm" data-action="' + item.action + '">去完成</button>') +
      '</div>';
    }).join('');
    return '<div class="card">' +
      '<div class="card-head"><div class="card-head-main">' +
        '<div class="card-title">' + A.icon('check') + '今日照护任务</div>' +
        '<div class="card-sub">完成每日小事，让健康管理变成习惯</div>' +
      '</div><span class="chip chip-brand">' + [D.checkedToday(A.state), D.dailyCheckDone(A.state), D.taskDoneToday(A.state)].filter(Boolean).length + ' / 3</span></div>' +
      '<div class="task-list">' + html + '</div>' +
    '</div>';
  }

  function renderRemindersCard(state) {
    var reminders = D.buildReminders(state)
      .filter(function (r) { return !r.done && r.status !== 'none'; })
      .sort(function (a, b) {
        var rank = { overdue: 0, soon: 1, ok: 2 };
        return (rank[a.status] - rank[b.status]) || ((a.daysLeft || 0) - (b.daysLeft || 0));
      })
      .slice(0, 4);
    var body = reminders.length
      ? reminders.map(function (r) {
        var st = reminderStatus(r.status);
        return '<button type="button" class="reminder-row" data-nav="' + r.actionPage + '">' +
          '<span class="reminder-ico">' + r.icon + '</span>' +
          '<span class="reminder-main"><b>' + esc(r.title) + '</b><em>' + esc(r.desc) + '</em></span>' +
          '<span class="reminder-right"><span class="status ' + st[0] + '">' + daysText(r.daysLeft) + '</span>' + A.icon('arrow') + '</span>' +
        '</button>';
      }).join('')
      : A.emptyState('✅', '当前没有待处理提醒', '疫苗、驱虫和洗澡计划都在正常范围内。');
    return '<div class="card">' +
      '<div class="card-head"><div class="card-head-main">' +
        '<div class="card-title">' + A.icon('bell') + '待处理提醒</div>' +
        '<div class="card-sub">基于健康记录自动计算</div>' +
      '</div><a class="card-link" href="#/reminders" data-nav="reminders">全部提醒 ' + A.icon('arrow') + '</a></div>' +
      '<div class="reminder-list">' + body + '</div>' +
    '</div>';
  }

  function renderRecentEvents(state) {
    var events = state.events.slice().sort(function (a, b) { return a.date < b.date ? 1 : -1; }).slice(0, 4);
    var body = events.map(function (e) {
      var meta = D.EVENT_META[e.type] || D.EVENT_META['每日检查'];
      return '<div class="event-row">' +
        '<span class="event-ico ' + meta.cls + '">' + meta.icon + '</span>' +
        '<span class="event-main"><b>' + esc(meta.label) + (e.high_risk ? ' <span class="status status-overdue">高风险</span>' : '') + '</b>' +
          '<em>' + esc(D.eventDetailText(e)) + '</em></span>' +
        '<span class="event-date">' + relativeDate(e.date) + '</span>' +
      '</div>';
    }).join('');
    return '<div class="card">' +
      '<div class="card-head"><div class="card-head-main">' +
        '<div class="card-title">' + A.icon('clipboard') + '最近健康事件</div>' +
        '<div class="card-sub">按日期倒序展示最新记录</div>' +
      '</div><a class="card-link" href="#/records" data-nav="records">查看时间线 ' + A.icon('arrow') + '</a></div>' +
      '<div class="event-list">' + (body || A.emptyState('📝', '还没有健康记录', '从记录一次疫苗或体重开始。')) + '</div>' +
    '</div>';
  }

  function renderMiniTrend(state) {
    var stats = D.weightStats(state.weightLogs, 90);
    var range = D.idealRange(state.pet.breed);
    var chart = stats
      ? A.weightChart(stats.logs, range, { rangeStart: D.daysAgoISO(90), height: 210, compact: true })
      : A.emptyState('⚖️', '还没有体重数据', '记录第一次体重后，这里会出现 90 天趋势。');
    return '<div class="card">' +
      '<div class="card-head"><div class="card-head-main">' +
        '<div class="card-title">' + A.icon('chart') + '体重趋势</div>' +
        '<div class="card-sub">近 90 天 · 当前 ' + esc(state.pet.weight) + ' kg' + (range ? ' · 理想 ' + range[0] + '–' + range[1] + ' kg' : '') + '</div>' +
      '</div><a class="card-link" href="#/trends" data-nav="trends">详细趋势 ' + A.icon('arrow') + '</a></div>' +
      chart +
    '</div>';
  }

  function renderQuickActions() {
    var items = [
      { label: '记录事件', hint: '疫苗 / 驱虫 / 异常', action: 'openEventModal', icon: '📝' },
      { label: '更新体重', hint: '同步趋势与营养', action: 'openWeightModal', icon: '⚖️' },
      { label: '营养方案', hint: 'RER / DER 与食谱', nav: 'nutrition', icon: '🍖' },
      { label: '照护提醒', hint: '今日与即将到期', nav: 'reminders', icon: '📅' },
      { label: '宠物档案', hint: '编辑基础资料', nav: 'profile', icon: '🐶' },
      { label: '成长激励', hint: '签到 / 任务 / 勋章', nav: 'growth', icon: '🎖️' }
    ];
    return '<div class="card">' +
      '<div class="card-head"><div class="card-head-main">' +
        '<div class="card-title">' + A.icon('sparkles') + '快捷操作</div>' +
        '<div class="card-sub">常用入口，一步直达</div>' +
      '</div></div>' +
      '<div class="quick-grid">' + items.map(function (it) {
        return '<button type="button" class="quick-item" ' +
          (it.nav ? 'data-nav="' + it.nav + '"' : 'data-action="' + it.action + '"') + '>' +
          '<span class="quick-ico">' + it.icon + '</span>' +
          '<span class="quick-text"><b>' + it.label + '</b><em>' + it.hint + '</em></span>' +
        '</button>';
      }).join('') + '</div>' +
    '</div>';
  }

  function renderTip() {
    var tip = D.tipOfToday();
    var labels = {
      food_danger: '饮食安全', food_good: '营养推荐', behavior: '行为解读',
      care: '日常护理', season: '季节提醒', health_tip: '健康冷知识'
    };
    return '<div class="card tip-card">' +
      '<div class="tip-badge">' + A.paw('tip-paw') + '</div>' +
      '<div class="tip-label">' + (labels[tip.category] || '今日贴士') + '</div>' +
      '<p class="tip-text">' + esc(tip.text) + '</p>' +
      '<div class="tip-foot">每日轮换 · 来自内置照护知识库</div>' +
    '</div>';
  }

  function renderDashboard(state) {
    return '<div class="page-stack">' +
      renderHero(state) +
      renderStats(state) +
      '<div class="dash-grid">' +
        '<div class="dash-col">' +
          renderTasks() +
          renderMiniTrend(state) +
          renderRecentEvents(state) +
        '</div>' +
        '<div class="dash-col">' +
          renderRemindersCard(state) +
          renderQuickActions() +
          renderTip() +
        '</div>' +
      '</div>' +
    '</div>';
  }

  /* ---------------- 宠物档案 ---------------- */
  function renderProfile(state) {
    var pet = state.pet;
    var range = D.idealRange(pet.breed);
    var weight = D.parseWeight(pet.weight);
    var allergies = (pet.allergies || '').split(/[,，]/).map(function (s) { return s.trim(); }).filter(Boolean);
    var diseases = (pet.diseases || '').split(/[,，]/).map(function (s) { return s.trim(); }).filter(Boolean);
    var ageStage = D.ageStage(pet.birthday, pet.breed);
    var events = state.events.length;
    var weights = state.weightLogs.length;
    var vaccines = state.events.filter(function (e) { return e.type === '疫苗'; }).length;
    var deworm = state.events.filter(function (e) { return e.type === '驱虫'; }).length;
    var rangePos = null;
    if (range && weight !== null) {
      rangePos = Math.max(0, Math.min(100, (weight - range[0] * 0.7) / (range[1] * 1.3 - range[0] * 0.7) * 100));
    }
    return '<div class="page-stack">' +
      '<section class="profile-hero card">' +
        '<div class="profile-head">' +
          '<div class="pet-avatar pet-avatar-lg"><img src="assets/images/tuantuan.svg" alt="' + esc(pet.name) + ' 的演示头像" /></div>' +
          '<div class="profile-title">' +
            '<div class="hero-eyebrow">宠物数字档案</div>' +
            '<h2>' + esc(pet.name) + '</h2>' +
            '<div class="hero-tags">' +
              '<span class="chip chip-brand">' + esc(pet.breed) + '</span>' +
              '<span class="chip">' + esc(D.ageText(pet.birthday)) + ' · ' + ageStage + '</span>' +
              '<span class="chip">' + (pet.gender === 'male' ? '公犬' : '母犬') + '</span>' +
              '<span class="chip">' + (pet.neutered === '是' ? '已绝育' : pet.neutered === '否' ? '未绝育' : '绝育未知') + '</span>' +
            '</div>' +
          '</div>' +
          '<div class="profile-actions">' +
            '<button type="button" class="btn btn-primary btn-sm" data-action="openProfileModal">' + A.icon('edit') + '编辑档案</button>' +
            '<button type="button" class="btn btn-secondary btn-sm" data-action="exportState">' + A.icon('download') + '导出演示数据</button>' +
          '</div>' +
        '</div>' +
        '<div class="profile-summary">' +
          '<div><span>档案创建</span><b>' + esc(pet.createdAt) + '</b></div>' +
          '<div><span>到家日期</span><b>' + esc(pet.homeDate || '未填写') + '</b></div>' +
          '<div><span>累计事件</span><b>' + events + ' 条</b></div>' +
          '<div><span>体重记录</span><b>' + weights + ' 次</b></div>' +
        '</div>' +
      '</section>' +

      '<div class="profile-grid">' +
        '<div class="card">' +
          '<div class="card-head"><div class="card-head-main">' +
            '<div class="card-title">' + A.icon('profile') + '基础资料</div>' +
            '<div class="card-sub">档案字段与原应用保持一致</div>' +
          '</div></div>' +
          '<dl class="detail-grid">' +
            '<div><dt>名字</dt><dd>' + esc(pet.name) + '</dd></div>' +
            '<div><dt>品种</dt><dd>' + esc(pet.breed) + '</dd></div>' +
            '<div><dt>生日</dt><dd>' + esc(pet.birthday) + ' <span class="tiny muted">(' + esc(D.ageText(pet.birthday)) + ')</span></dd></div>' +
            '<div><dt>性别</dt><dd>' + (pet.gender === 'male' ? '公犬' : '母犬') + '</dd></div>' +
            '<div><dt>绝育状态</dt><dd>' + (pet.neutered === '是' ? '已绝育' : pet.neutered === '否' ? '未绝育' : '未知') + '</dd></div>' +
            '<div><dt>当前体重</dt><dd>' + esc(pet.weight) + ' kg</dd></div>' +
            '<div><dt>建议洗澡间隔</dt><dd>' + (pet.bathIntervalDays || 24) + ' 天</dd></div>' +
            '<div><dt>上次洗澡</dt><dd>' + esc(pet.lastBathDate || '未记录') + '</dd></div>' +
          '</dl>' +
        '</div>' +

        '<div class="card">' +
          '<div class="card-head"><div class="card-head-main">' +
            '<div class="card-title">' + A.icon('heart') + '健康信息</div>' +
            '<div class="card-sub">过敏源与既往疾病会影响营养建议</div>' +
          '</div></div>' +
          '<div class="info-block">' +
            '<span class="info-label">过敏源</span>' +
            '<div class="tag-row">' + (allergies.length ? allergies.map(function (a) { return '<span class="chip chip-red">' + esc(a) + '</span>'; }).join('') : '<span class="chip chip-muted">未记录过敏源</span>') + '</div>' +
          '</div>' +
          '<div class="info-block">' +
            '<span class="info-label">既往疾病</span>' +
            '<div class="tag-row">' + (diseases.length ? diseases.map(function (a) { return '<span class="chip chip-amber">' + esc(a) + '</span>'; }).join('') : '<span class="chip chip-muted">未记录既往疾病</span>') + '</div>' +
          '</div>' +
          '<div class="info-block">' +
            '<span class="info-label">理想体重范围</span>' +
            (range
              ? '<div class="range-bar"><div class="range-track"><span class="range-fill"></span><i class="range-marker" style="left:' + rangePos + '%"></i></div>' +
                '<div class="range-labels"><span>' + range[0] + ' kg</span><span class="range-current">当前 ' + esc(pet.weight) + ' kg</span><span>' + range[1] + ' kg</span></div></div>'
              : '<p class="small muted">该品种暂无内置理想体重范围。</p>') +
          '</div>' +
          '<div class="notice notice-info">' + A.icon('alert') +
            '<span>健康信息与营养建议仅作日常照护参考，不构成兽医诊断。' + (pet.diseases ? '档案中记录的疾病情况请在兽医指导下管理。' : '') + '</span>' +
          '</div>' +
        '</div>' +
      '</div>' +

      '<div class="profile-grid">' +
        '<div class="card">' +
          '<div class="card-head"><div class="card-head-main">' +
            '<div class="card-title">' + A.icon('clipboard') + '照护数据概览</div>' +
            '<div class="card-sub">当前演示档案累计记录</div>' +
          '</div></div>' +
          '<div class="mini-stat-grid">' +
            '<div class="mini-stat"><b>' + vaccines + '</b><span>疫苗接种</span></div>' +
            '<div class="mini-stat"><b>' + deworm + '</b><span>驱虫记录</span></div>' +
            '<div class="mini-stat"><b>' + state.events.filter(function (e) { return e.type === '洗澡澡'; }).length + '</b><span>洗澡记录</span></div>' +
            '<div class="mini-stat"><b>' + state.badges.length + '</b><span>已解锁勋章</span></div>' +
          '</div>' +
          '<div class="card-actions">' +
            '<button type="button" class="btn btn-secondary btn-sm" data-nav="records">查看健康记录</button>' +
            '<button type="button" class="btn btn-secondary btn-sm" data-nav="trends">查看体重趋势</button>' +
          '</div>' +
        '</div>' +
        '<div class="card">' +
          '<div class="card-head"><div class="card-head-main">' +
            '<div class="card-title">' + A.icon('sparkles') + '演示说明</div>' +
            '<div class="card-sub">这是独立于原 Python 应用的静态展示层</div>' +
          '</div></div>' +
          '<ul class="plain-list">' +
            '<li>所有宠物资料、事件和趋势均为虚构演示数据。</li>' +
            '<li>编辑档案会实时影响营养计算、提醒和勋章判定。</li>' +
            '<li>操作保存在当前浏览器 localStorage，刷新后仍会保留。</li>' +
            '<li>点击侧边栏「重置演示数据」可恢复初始状态。</li>' +
          '</ul>' +
          '<div class="card-actions">' +
            '<button type="button" class="btn btn-ghost btn-sm" data-action="resetDemo">' + A.icon('reset') + '重置演示数据</button>' +
          '</div>' +
        '</div>' +
      '</div>' +
    '</div>';
  }

  /* ---------------- 动作 ---------------- */
  A.actions.checkinToday = function () {
    if (D.checkedToday(A.state)) {
      A.toast('今天已经签过到啦，明天再来～', 'warn');
      return;
    }
    var res = D.recordCheckin(A.state);
    var badges = D.checkBadges(A.state);
    A.commit({ keepScroll: true });
    A.toast('签到成功，获得 1 枚爪印 · 连续 ' + res.streak + ' 天');
    A.celebrate(badges);
  };

  A.actions.completeTodayTask = function () {
    var res = D.completeTask(A.state);
    if (res.already) {
      A.toast('今天的任务已经完成啦～', 'warn');
      return;
    }
    var badges = D.checkBadges(A.state);
    A.commit({ keepScroll: true });
    A.toast(res.task.thanks);
    if (res.autoChecked) A.toast('已自动补签，额外获得 1 枚爪印');
    A.celebrate(badges);
  };

  A.actions.openDailyCheck = function () {
    if (D.dailyCheckDone(A.state)) {
      A.toast('今天的健康检查已经完成了', 'warn');
      return;
    }
    A.openModal({
      title: '今日健康检查',
      subtitle: '用 1 分钟轻轻触摸狗狗，确认是否有异常',
      size: 'sm',
      body: '<p class="confirm-text">摸摸' + esc(A.state.pet.name) + '的头部、背部、四肢和腹部，留意硬块、红肿、脱毛或异常发热。</p>' +
        '<div class="notice notice-info">' + A.icon('sparkles') + '<span>完成后记录到健康时间线，并获得 1 枚爪印。</span></div>',
      footer: '<button type="button" class="btn btn-secondary" data-daily-normal>✅ 一切正常</button>' +
        '<button type="button" class="btn btn-primary" data-daily-abnormal>⚠️ 发现异常</button>'
    });
    document.querySelector('[data-daily-normal]').addEventListener('click', function () {
      finishDailyCheck('normal');
    });
    document.querySelector('[data-daily-abnormal]').addEventListener('click', function () {
      A.closeModal();
      A.setStateDailyCheckForm();
    });
  };

  A.setStateDailyCheckForm = function () {
    A.openModal({
      title: '记录异常发现',
      subtitle: '请描述观察到的情况，必要时及时联系兽医',
      size: 'sm',
      body: '<form data-form="dailyCheckAbnormal">' +
        '<div class="field"><label for="dcNote">观察到的情况</label>' +
        '<textarea class="textarea" id="dcNote" name="note" placeholder="例如：背部有一小块红肿，狗狗频繁抓挠…"></textarea></div>' +
        '<div class="form-error" data-error></div>' +
        '<div class="notice notice-warn" style="margin-top:14px">' + A.icon('alert') + '<span>如果出现持续呕吐、便血、抽搐、呼吸困难等情况，请立即就医。</span></div>' +
      '</form>',
      footer: '<button type="button" class="btn btn-ghost" data-modal-close>取消</button>' +
        '<button type="button" class="btn btn-primary" data-daily-submit>记录异常</button>'
    });
    document.querySelector('[data-daily-submit]').addEventListener('click', function () {
      var form = document.querySelector('form[data-form="dailyCheckAbnormal"]');
      var note = (form.querySelector('[name="note"]').value || '').trim();
      var err = form.querySelector('[data-error]');
      if (!note) {
        err.textContent = '请简单描述观察到的情况。';
        err.classList.add('show');
        return;
      }
      finishDailyCheck('abnormal', note);
    });
  };

  function finishDailyCheck(result, note) {
    var res = D.recordDailyCheck(A.state, result, note);
    if (res.already) {
      A.closeModal();
      A.toast('今天的健康检查已经完成了', 'warn');
      return;
    }
    var badges = D.checkBadges(A.state);
    A.closeModal();
    A.commit({ keepScroll: true });
    A.toast(result === 'normal' ? '健康检查已记录，获得 1 枚爪印' : '异常情况已记录，请持续观察');
    A.celebrate(badges);
  }

  A.actions.openProfileModal = function () {
    var pet = A.state.pet;
    var breedOptions = D.BREED_OPTIONS.map(function (b) {
      return '<option value="' + esc(b) + '"' + (b === pet.breed ? ' selected' : '') + '>' + esc(b) + '</option>';
    }).join('');
    A.openModal({
      title: '编辑宠物档案',
      subtitle: '修改后会立即影响营养计算、提醒与勋章判定',
      size: 'lg',
      body: '<form data-form="profileEdit">' +
        '<div class="form-grid">' +
          '<div class="field"><label for="pfName">名字 <em>*</em></label><input class="input" id="pfName" name="name" maxlength="64" value="' + esc(pet.name) + '" /></div>' +
          '<div class="field"><label for="pfBreed">品种 <em>*</em></label><select class="select" id="pfBreed" name="breed">' + breedOptions + '</select></div>' +
          '<div class="field"><label for="pfBirthday">生日 <em>*</em></label><input class="input" id="pfBirthday" name="birthday" type="date" value="' + esc(pet.birthday) + '" max="' + D.todayISO() + '" /></div>' +
          '<div class="field"><label for="pfHome">到家日期</label><input class="input" id="pfHome" name="homeDate" type="date" value="' + esc(pet.homeDate || '') + '" max="' + D.todayISO() + '" /></div>' +
          '<div class="field"><label for="pfGender">性别</label><select class="select" id="pfGender" name="gender">' +
            '<option value="female"' + (pet.gender === 'female' ? ' selected' : '') + '>母犬</option>' +
            '<option value="male"' + (pet.gender === 'male' ? ' selected' : '') + '>公犬</option></select></div>' +
          '<div class="field"><label for="pfNeutered">绝育状态</label><select class="select" id="pfNeutered" name="neutered">' +
            ['是', '否', '未知'].map(function (v) { return '<option value="' + v + '"' + (pet.neutered === v ? ' selected' : '') + '>' + v + '</option>'; }).join('') +
          '</select></div>' +
          '<div class="field"><label for="pfWeight">体重（kg）</label><input class="input" id="pfWeight" name="weight" inputmode="decimal" value="' + esc(pet.weight) + '" placeholder="例如 11.4" /></div>' +
          '<div class="field"><label for="pfBath">建议洗澡间隔（天）</label><input class="input" id="pfBath" name="bathInterval" inputmode="numeric" value="' + (pet.bathIntervalDays || 24) + '" /></div>' +
          '<div class="field span-2"><label for="pfAllergies">过敏源</label><input class="input" id="pfAllergies" name="allergies" value="' + esc(pet.allergies || '') + '" placeholder="多个用逗号分隔，例如：牛肉, 鸡肉" /><span class="hint">系统会自动过滤主食谱与备选食材中的过敏源。</span></div>' +
          '<div class="field span-2"><label for="pfDiseases">既往疾病</label><input class="input" id="pfDiseases" name="diseases" value="' + esc(pet.diseases || '') + '" placeholder="多个用逗号分隔" /></div>' +
        '</div>' +
        '<div class="form-error" data-error style="margin-top:14px"></div>' +
      '</form>',
      footer: '<button type="button" class="btn btn-ghost" data-modal-close>取消</button>' +
        '<button type="button" class="btn btn-primary" data-profile-save>保存档案</button>'
    });
    document.querySelector('[data-profile-save]').addEventListener('click', function () {
      saveProfile();
    });
  };

  function saveProfile() {
    var form = document.querySelector('form[data-form="profileEdit"]');
    var err = form.querySelector('[data-error]');
    var name = form.querySelector('[name="name"]').value.trim();
    var breed = form.querySelector('[name="breed"]').value;
    var birthday = form.querySelector('[name="birthday"]').value;
    var gender = form.querySelector('[name="gender"]').value;
    var neutered = form.querySelector('[name="neutered"]').value;
    var weight = form.querySelector('[name="weight"]').value.trim();
    var bathInterval = parseInt(form.querySelector('[name="bathInterval"]').value, 10);
    var allergies = form.querySelector('[name="allergies"]').value.trim();
    var diseases = form.querySelector('[name="diseases"]').value.trim();
    var homeDate = form.querySelector('[name="homeDate"]').value;

    function fail(msg) {
      err.textContent = msg;
      err.classList.add('show');
    }
    err.classList.remove('show');
    if (!name) return fail('请填写宠物名字。');
    if (!breed) return fail('请选择品种。');
    if (!birthday) return fail('请选择生日。');
    if (birthday > D.todayISO()) return fail('生日不能晚于今天。');
    if (weight && (D.parseWeight(weight) === null || D.parseWeight(weight) <= 0)) return fail('体重需要是有效的数字。');
    if (isNaN(bathInterval) || bathInterval < 1) return fail('洗澡间隔至少为 1 天。');

    var pet = A.state.pet;
    pet.name = name;
    pet.breed = breed;
    pet.birthday = birthday;
    pet.gender = gender;
    pet.neutered = neutered;
    pet.allergies = allergies;
    pet.diseases = diseases;
    pet.homeDate = homeDate;
    pet.bathIntervalDays = bathInterval;
    if (weight) D.addWeight(A.state, weight, D.todayISO());

    var badges = D.checkBadges(A.state);
    A.closeModal();
    A.commit({ keepScroll: true });
    A.toast('档案已更新，营养与提醒已同步');
    A.celebrate(badges);
  }

  A.actions.exportState = A.exportState;
  A.actions.resetDemo = function () {
    A.confirm({
      title: '重置演示数据',
      message: '将清除本浏览器中保存的全部演示操作，恢复初始档案。',
      note: '不会影响任何真实数据或原 Python 应用。',
      confirmText: '重置',
      danger: true
    }).then(function (ok) {
      if (!ok) return;
      A.state = D.Store.reset();
      D.checkBadges(A.state);
      D.Store.save(A.state);
      A.navigate('dashboard');
      A.render();
      A.toast('演示数据已重置');
    });
  };

  A.registerPage('dashboard', {
    title: '首页',
    subtitle: function (state) { return state.pet.name + ' · ' + state.pet.breed + ' · ' + D.ageText(state.pet.birthday); },
    render: renderDashboard
  });

  A.registerPage('profile', {
    title: '宠物档案',
    subtitle: '一只狗狗的完整数字档案',
    render: renderProfile
  });
})();
