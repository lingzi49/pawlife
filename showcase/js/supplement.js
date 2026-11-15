/* PawLife 展示版 — 元气补给（保健品推荐） */
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

  function isSuspended(state) {
    return !!(state.suspendedUntil && state.suspendedUntil >= D.todayISO());
  }

  function renderSuspended() {
    return '<div class="card">' +
      '<div class="supp-suspended">🚨 因您最近记录了高风险症状，今日保健品建议已暂停。请优先联系兽医，确认宠物状况稳定后可恢复建议。</div>' +
      '<div class="suspended-actions">' +
        '<button type="button" class="btn btn-secondary btn-sm" data-nav="record">查看记录</button>' +
        '<button type="button" class="btn btn-primary btn-sm" data-action="restoreSupplements">✅ 已联系兽医，恢复建议</button>' +
      '</div>' +
    '</div>';
  }

  function renderEmpty(state) {
    var age = D.ageText(state.pet.birthday);
    return '<div class="card">' +
      '<div class="supp-empty-state">' +
        '<div class="supp-empty-icon">🛡️</div>' +
        '<div class="supp-empty-title">主人把我照顾得很好，暂时不需要额外补给～</div>' +
        '<div class="supp-empty-desc">根据当前档案和记录，没有发现需要特别补充保健品的情况。</div>' +
        '<div class="supp-empty-checklist">' +
          '<div>✓ 年龄：' + esc(age) + '，非特殊风险阶段</div>' +
          '<div>✓ 体重：' + esc(state.pet.weight) + 'kg，暂无明显体重风险</div>' +
          '<div>✓ 最近无高风险异常记录</div>' +
          '<div>✓ 皮肤 / 肠胃 / 关节暂无持续异常</div>' +
        '</div>' +
        '<div class="supp-empty-hints">什么时候需要考虑保健品？<br/>· 经常抓痒、掉毛严重　· 频繁软便、腹泻<br/>· 关节疼痛、跛行　· 老年犬活动力下降</div>' +
        '<div class="supp-empty-actions">' +
          '<button type="button" class="btn btn-primary btn-sm" data-nav="record">📝 记录异常行为</button>' +
          '<button type="button" class="btn btn-secondary btn-sm" data-nav="weight">⚖️ 更新体重</button>' +
        '</div>' +
      '</div>' +
    '</div>';
  }

  function renderList(state, list) {
    return '<div class="card">' +
      '<div class="card-title">⚡ 当前推荐</div>' +
      '<div class="card-subtitle">根据年龄、品种、体重、异常记录与档案病史规则匹配</div>' +
      list.map(function (item) {
        return '<div class="supp-alert-item">' +
          '<div class="supp-alert-icon">' + (item.icon || '💊') + '</div>' +
          '<div class="supp-alert-body">' +
            '<div class="supp-alert-name">' + esc(item.name) + '</div>' +
            '<div class="supp-alert-reason">📌 ' + esc(item.reasonText) + '</div>' +
            '<div class="supp-alert-woof">' + esc(item.woofFull) + '</div>' +
          '</div>' +
        '</div>';
      }).join('') +
      '<div class="supp-disclaimer">💊 保健品提醒基于一般营养学知识生成，具体服用方案请咨询兽医确认。</div>' +
    '</div>';
  }

  function renderSupplement(state) {
    var header = subHeader('⚡ ' + esc(state.pet.name) + '的元气补给');
    if (isSuspended(state)) return '<div class="sub-page">' + header + renderSuspended() + '</div>';
    var list = D.calcSupplements(state);
    return '<div class="sub-page">' + header +
      '<div class="reminders-intro">⚡ 根据当前档案与健康记录，判断是否需要额外营养补充。</div>' +
      (list.length ? renderList(state, list) : renderEmpty(state)) +
    '</div>';
  }

  A.actions.restoreSupplements = function () {
    A.state.suspendedUntil = null;
    A.commit({ keepScroll: true });
    A.toast('已恢复保健品建议展示，请继续观察宠物状态');
  };

  A.registerPage('supplement', {
    title: '元气补给',
    render: renderSupplement
  });
})();
