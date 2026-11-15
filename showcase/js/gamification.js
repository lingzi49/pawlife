/* PawLife 展示版 — 高光时刻与每日任务 */
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

  function renderEmotion(state) {
    var pet = state.pet;
    var next = D.nextBadgeInfo(state);
    var progress = next ? '<div class="badge-next-line">下一枚：' + next.def.icon + ' ' + esc(next.name) + ' · ' + next.have + '/' + next.need + ' ' + next.unit + '</div>' +
      '<div class="progress"><i style="width:' + next.pct + '%"></i></div>' : '<div class="badge-next-line">全部勋章已解锁 🏆</div>';
    return '<div class="badge-emotion-card">' +
      '<div class="badge-emotion-inner">' +
        '<div class="badge-emotion-left">' +
          '<div class="badge-emotion-avatar"><img src="assets/images/tuantuan.svg" alt="' + esc(pet.name) + '" /></div>' +
          '<div class="badge-emotion-name">' + esc(pet.name) + '</div>' +
          '<div class="badge-emotion-days">相伴 ' + D.daysTogether(state) + ' 天</div>' +
        '</div>' +
        '<div class="badge-emotion-right">' +
          '<div class="badge-emotion-count">✨ 已收获 ' + state.badges.length + ' / ' + D.BADGES.length + ' 枚勋章</div>' +
          '<div class="badge-emotion-text">每一枚勋章，都是我们一起认真生活的证据。</div>' +
          progress +
        '</div>' +
      '</div>' +
    '</div>';
  }

  function renderDailyTask(state) {
    var task = D.todayTask(state);
    var done = D.taskDoneToday(state);
    return '<div class="card daily-task-card">' +
      '<div class="card-title">✅ 今日小任务</div>' +
      '<p class="daily-task-text">' + esc(task.task) + '</p>' +
      '<div class="daily-task-actions">' +
        (done
          ? '<button type="button" class="btn btn-secondary btn-sm" disabled>✅ 已完成</button>'
          : '<button type="button" class="btn btn-primary btn-sm" data-action="completeTodayTask">' + esc(task.action) + '</button>') +
      '</div>' +
      '<div class="daily-task-note">完成任务 +2 爪印；如果今天还没签到，会自动补签并获得签到 +1。</div>' +
    '</div>';
  }

  function renderBadgeWall(state) {
    var tab = state.ui.badgeTab || 'all';
    var cats = [
      { key: 'all', label: '全部' },
      { key: '第一次', label: '🐣 我们的第一次' },
      { key: '守护者', label: '🛡️ 守护者联盟' },
      { key: '健康里程碑', label: '🌱 成长里程碑' }
    ];
    var tabs = cats.map(function (c) {
      return '<button type="button" class="badge-story-tab' + (tab === c.key ? ' active' : '') + '" data-action="setBadgeTab" data-cat="' + c.key + '">' + c.label + '</button>';
    }).join('');
    var list = D.BADGES.filter(function (b) { return tab === 'all' || b.category === tab; });
    var wall = list.map(function (b) {
      var got = D.unlockedBadge(state, b.name);
      return '<button type="button" class="badge-memento ' + (got ? 'unlocked' : 'locked') + '" data-action="openBadge" data-name="' + esc(b.name) + '">' +
        '<div class="badge-memento-photo-area">' +
          '<div class="badge-memento-icon"><span class="badge-memento-icon-placeholder">' + b.icon + '</span></div>' +
          (got ? '<div class="badge-memento-pin">🏅</div>' : '') +
        '</div>' +
        '<span class="badge-memento-name">' + esc(b.name) + '</span>' +
        '<span class="badge-memento-date">' + (got ? esc(got.date) : '未解锁') + '</span>' +
      '</button>';
    }).join('');
    return '<div class="badge-story-tabs">' + tabs + '</div>' +
      '<div class="badge-wall">' + wall + '</div>';
  }

  function renderBadges(state) {
    return '<div class="sub-page">' +
      subHeader('🏵️ ' + esc(state.pet.name) + '的高光时刻') +
      renderEmotion(state) +
      renderDailyTask(state) +
      renderBadgeWall(state) +
    '</div>';
  }

  A.actions.setBadgeTab = function (dataset) {
    A.state.ui.badgeTab = dataset.cat || 'all';
    A.commit({ keepScroll: true });
  };

  A.actions.openBadge = function (dataset) {
    var def = D.BADGES.filter(function (b) { return b.name === dataset.name; })[0];
    if (!def) return;
    var got = D.unlockedBadge(A.state, def.name);
    A.openModal({
      title: def.name,
      subtitle: def.category + ' · ' + (got ? '已解锁' : '未解锁'),
      icon: def.icon,
      size: 'sm',
      body: '<div class="badge-detail-body">' +
        '<div class="badge-detail-condition">' + esc(def.condition) + '</div>' +
        (got
          ? '<div class="notice notice-green">✅ 解锁日期：' + esc(got.date) + '。这枚勋章已记录在成长档案中。</div>'
          : '<div class="notice notice-info">继续完成对应照护记录即可解锁。展示版会在数据满足条件时自动判定。</div>') +
      '</div>',
      footer: '<button type="button" class="btn btn-primary" data-modal-close>知道了</button>'
    });
  };

  A.registerPage('badges', {
    title: '高光时刻',
    render: renderBadges
  });
})();
