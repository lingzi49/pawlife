/* PawLife 展示版 — 首页与档案编辑 */
(function () {
  'use strict';

  var A = window.PawApp;
  var D = window.PawData;
  var esc = A.esc;

  function relativeDate(iso) {
    var diff = D.diffDays(D.todayISO(), iso);
    if (diff === 0) return '今天';
    if (diff === 1) return '昨天';
    if (diff < 7) return diff + ' 天前';
    var d = D.parseISO(iso);
    return (d.getMonth() + 1) + '月' + d.getDate() + '日';
  }

  function daysText(n) {
    if (n === null || n === undefined) return '待补充';
    if (n < 0) return '已逾期 ' + Math.abs(n) + ' 天';
    if (n === 0) return '今天到期';
    return n + ' 天后';
  }

  function latestEvent(state) {
    var list = state.events.slice().sort(function (a, b) { return a.date < b.date ? 1 : -1; });
    return list[0] || null;
  }

  function careReminders(state) {
    return D.buildReminders(state).filter(function (r) { return !r.done && r.status !== 'none'; });
  }

  function pendingCount(state) {
    var count = D.dailyCheckDone(state) ? 0 : 1;
    count += careReminders(state).filter(function (r) { return r.status === 'overdue' || r.status === 'soon'; }).length;
    return count;
  }

  function renderTodayCard(state) {
    var pet = state.pet;
    var latest = latestEvent(state);
    var reminders = careReminders(state).sort(function (a, b) {
      var rank = { overdue: 0, soon: 1, ok: 2 };
      return (rank[a.status] - rank[b.status]) || ((a.daysLeft || 0) - (b.daysLeft || 0));
    });
    var reminder = reminders[0];
    var checked = D.checkedToday(state);
    var pending = pendingCount(state);
    var latestText = latest
      ? '最近记录：' + (D.EVENT_META[latest.type] ? D.EVENT_META[latest.type].icon + ' ' + latest.type : latest.type) + ' · ' + relativeDate(latest.date)
      : '还没有健康记录，去记录第一件事吧～';
    return '<div class="today-dashboard">' +
      '<div class="today-dashboard-main">' +
        '<button type="button" class="today-avatar" data-action="openProfileModal" title="查看/编辑档案">' +
          '<img src="assets/images/tuantuan.svg" alt="' + esc(pet.name) + ' 的演示头像" />' +
        '</button>' +
        '<div class="today-dashboard-info">' +
          '<div class="td-name"><b>' + esc(pet.name) + '</b> · ' + esc(pet.breed) + ' · ' + esc(D.ageText(pet.birthday)) + ' · ' + esc(pet.weight) + 'kg</div>' +
          '<span class="td-recent">' + esc(latestText) + '</span>' +
          (reminder ? '<span class="td-reminder">⏰ ' + esc(reminder.title) + ' · ' + daysText(reminder.daysLeft) + '</span>' : '') +
        '</div>' +
        '<div class="today-dashboard-meta">' +
          '<button type="button" class="td-paw" data-action="openPawHistory" title="查看爪印获取记录">🐾 <b>' + pet.pawPoints + '</b></button>' +
          (checked
            ? '<span class="td-streak" title="已连续签到 ' + D.currentStreak(state) + ' 天">🔥 <b>' + D.currentStreak(state) + '</b> 天</span>'
            : '<button type="button" class="td-checkin-btn" data-action="checkinToday">📅 签到</button>') +
        '</div>' +
      '</div>' +
      (pending > 0
        ? '<div class="today-pending"><span class="pending-count">' + pending + '</span>' + esc(pet.name) + '今天有 <b>' + pending + '</b> 项健康任务待完成</div>'
        : '') +
    '</div>';
  }

  function renderDailyCheck(state) {
    var done = D.dailyCheckDone(state);
    var abnormal = state.events.filter(function (e) {
      return e.type === '每日检查' && e.date === D.todayISO() && e.detail && e.detail.result === 'abnormal';
    })[0];
    return '<div class="daily-check-card' + (done ? ' is-done' : '') + '">' +
      '<div class="daily-check-header">' +
        '<span class="daily-check-icon">🩺</span>' +
        '<span class="daily-check-title">今日健康检查</span>' +
        (done ? '<span class="daily-check-badge">✅ 已完成</span>' : '') +
      '</div>' +
      '<div class="daily-check-body">' +
        (done
          ? '<div class="daily-check-completed">' + (abnormal ? '⚠️ 今日检查已完成 · 已记录异常' : '✅ 今日检查已完成 · ' + esc(state.pet.name) + '状态很好～') + '</div>'
          : '<div class="daily-check-desc">用 1 分钟轻轻摸摸<span class="pet-name-inline">' + esc(state.pet.name) + '</span>的头部、背部、四肢和腹部，确认是否有硬块、红肿、脱毛或异常发热。</div>' +
            '<div class="daily-check-actions">' +
              '<button type="button" class="btn btn-check-ok" data-action="dailyCheckNormal">✅ 一切正常</button>' +
              '<button type="button" class="btn btn-check-warn" data-action="openDailyCheckAbnormal">⚠️ 发现异常</button>' +
            '</div>') +
        '<div class="daily-check-note">完成后将自动记录到健康时间轴，并获得 1 枚爪印。</div>' +
      '</div>' +
    '</div>';
  }

  function renderQuickGrid(state) {
    var weight = D.latestWeight(state);
    var reminders = careReminders(state);
    var dueCount = reminders.filter(function (r) { return r.status === 'overdue' || r.status === 'soon'; }).length;
    var suppCount = D.calcSupplements(state).length;
    return '<div class="quick-record-grid">' +
      '<button type="button" class="quick-record-card qr-span-2" data-nav="record">' +
        '<span class="qr-icon">📝</span><span class="qr-label">记录健康事件</span>' +
        '<span class="qr-hint">疫苗、驱虫、异常，事事有迹可循</span>' +
      '</button>' +
      '<button type="button" class="quick-record-card qr-span-2" data-nav="diet">' +
        '<span class="qr-icon">🍖</span><span class="qr-label">饮食指导</span>' +
        '<span class="qr-hint">按品种、年龄和体重量身推荐</span>' +
      '</button>' +
    '</div>' +
    '<div class="quick-record-grid-sm">' +
      '<button type="button" class="quick-record-card-sm" data-nav="weight">' +
        '<span class="qr-icon-sm">⚖️</span><span class="qr-label-sm">体重管理</span>' +
        '<span class="qr-hint">' + (weight ? weight.weight + 'kg · ' + relativeDate(weight.date) : '摸肋骨评估胖瘦') + '</span>' +
      '</button>' +
      '<button type="button" class="quick-record-card-sm" data-nav="reminders">' +
        '<span class="qr-icon-sm">📅</span><span class="qr-label-sm">照护提醒</span>' +
        '<span class="qr-hint">' + (dueCount ? dueCount + ' 项需关注' : '暂无紧急提醒') + '</span>' +
      '</button>' +
      '<button type="button" class="quick-record-card-sm" data-nav="badges">' +
        '<span class="qr-icon-sm">🎖️</span><span class="qr-label-sm">健康成就</span>' +
        '<span class="qr-hint">' + state.badges.length + ' / ' + D.BADGES.length + ' 枚勋章</span>' +
      '</button>' +
      '<button type="button" class="quick-record-card-sm" data-nav="supplement">' +
        '<span class="qr-icon-sm">🛡️</span><span class="qr-label-sm">营养补充</span>' +
        '<span class="qr-hint">' + (suppCount ? suppCount + ' 项建议' : '暂无额外补给') + '</span>' +
      '</button>' +
    '</div>';
  }

  function renderHealthProfile(state) {
    var pet = state.pet;
    var kg = D.parseWeight(pet.weight);
    var range = D.idealRange(pet.breed);
    var bcs = D.latestBCS(state);
    var bcsLabel = bcs ? ({ ideal: '理想', thin: '偏瘦', heavy: '偏胖' }[bcs.state] || '未评估') : '未评估';
    var tags = [];

    if (kg !== null && range) {
      if (kg < range[0]) tags.push('<span class="hp-tag hp-tag-warn">⚖ ' + esc(pet.weight) + 'kg 偏轻</span>');
      else if (kg > range[1]) tags.push('<span class="hp-tag hp-tag-warn">⚖ ' + esc(pet.weight) + 'kg 偏重</span>');
      else tags.push('<span class="hp-tag hp-tag-good">⚖ ' + esc(pet.weight) + 'kg 正常</span>');
    } else if (kg !== null) {
      tags.push('<span class="hp-tag hp-tag-good">⚖ ' + esc(pet.weight) + 'kg</span>');
    } else {
      tags.push('<span class="hp-tag hp-tag-missing" data-action="openProfileModal">⚖ 未记录</span>');
    }

    if (pet.neutered === '是') tags.push('<span class="hp-tag hp-tag-good">✂ 已绝育</span>');
    else if (pet.neutered === '否') tags.push('<span class="hp-tag hp-tag-warn">✂ 未绝育</span>');
    else tags.push('<span class="hp-tag hp-tag-missing" data-action="openProfileModal">✂ 绝育未知</span>');

    tags.push('<span class="hp-tag ' + (bcs && bcs.state === 'ideal' ? 'hp-tag-good' : bcs ? 'hp-tag-warn' : 'hp-tag-missing') + '">🤚 BCS ' + bcsLabel + '</span>');

    if (pet.allergies && pet.allergies.trim()) tags.push('<span class="hp-tag hp-tag-warn">⚠ ' + esc(pet.allergies) + '</span>');
    else tags.push('<span class="hp-tag hp-tag-missing" data-action="openProfileModal">📋 过敏源</span>');

    if (pet.diseases && pet.diseases.trim()) tags.push('<span class="hp-tag hp-tag-info">🏥 ' + esc(pet.diseases) + '</span>');
    else tags.push('<span class="hp-tag hp-tag-missing" data-action="openProfileModal">🏥 健康状况</span>');

    var missing = [];
    if (!pet.allergies) missing.push('过敏源');
    if (!pet.diseases) missing.push('健康状况');
    if (pet.neutered === '未知') missing.push('绝育状态');

    return '<div class="health-profile-card">' +
      '<div class="hp-card-header">' +
        '<span class="hp-icon">🐶</span>' +
        '<span class="hp-name">' + esc(pet.name) + ' 的健康档案</span>' +
        '<button type="button" class="btn btn-text btn-sm" data-action="openProfileModal">✏️ 编辑</button>' +
      '</div>' +
      '<div class="hp-tags">' + tags.join('') + '</div>' +
      (range ? '<div class="hp-range-note">' + esc(pet.breed) + '理想体重参考：' + range[0] + '–' + range[1] + ' kg</div>' : '') +
      (missing.length ? '<div class="hp-action-row" data-action="openProfileModal">📋 补全' + missing.join('、') + '，让建议更精准 →</div>' : '') +
    '</div>';
  }

  function renderGrowthCompact(state) {
    var unlocked = state.badges.slice(-3).reverse();
    var next = D.nextBadgeInfo(state);
    var badges = unlocked.map(function (b) {
      var def = D.BADGES.filter(function (d) { return d.name === b.name; })[0] || {};
      return '<span class="growth-badge-mini">' + (def.icon || '🎖️') + ' ' + esc(b.name) + '</span>';
    }).join('');
    if (next) badges += '<span class="growth-badge-mini locked">🔒 ' + next.def.icon + ' ' + esc(next.name) + '</span>';
    var latest = latestEvent(state);
    return '<div class="section-label">📸 成长记录</div>' +
      '<div class="growth-compact">' +
        (badges
          ? '<div class="growth-badges-row">' + badges + '</div>'
          : '<div class="growth-empty"><div class="growth-empty-icon">🎖️</div><div class="growth-empty-text">第一枚勋章还在路上</div><div class="growth-empty-hint">记录一次健康事件，就会开始积累成长印记。</div></div>') +
        (latest ? '<div class="growth-latest">最近一次：' + esc(D.EVENT_META[latest.type] ? D.EVENT_META[latest.type].label : latest.type) + ' · ' + esc(latest.date) + '</div>' : '') +
        '<button type="button" class="growth-more-link" data-nav="badges">查看全部成长记录 →</button>' +
      '</div>';
  }

  function renderHome(state) {
    return '<div id="page-home">' +
      renderTodayCard(state) +
      renderDailyCheck(state) +
      renderQuickGrid(state) +
      renderHealthProfile(state) +
      renderGrowthCompact(state) +
      '<div class="home-footer-actions">' +
        '<button type="button" class="btn btn-text btn-sm" data-action="exportState">📥 备份数据</button>' +
        '<span class="footer-dot">·</span>' +
        '<button type="button" class="btn btn-text btn-sm" data-action="resetDemo">重置演示数据</button>' +
      '</div>' +
    '</div>';
  }

  /* ---------------- 签到 / 任务 / 健康检查 ---------------- */
  A.actions.checkinToday = function () {
    if (D.checkedToday(A.state)) {
      A.toast('今天已经打过卡啦，明天再来吧～', 'warn');
      return;
    }
    var res = D.recordCheckin(A.state);
    var badges = D.checkBadges(A.state);
    A.commit({ keepScroll: true });
    A.toast('签到成功！连续第 ' + res.streak + ' 天');
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

  A.actions.dailyCheckNormal = function () {
    finishDailyCheck('normal');
  };

  A.actions.openDailyCheckAbnormal = function () {
    A.openModal({
      title: '记录异常发现',
      subtitle: '请描述观察到的情况，必要时及时联系兽医',
      icon: '⚠️',
      size: 'sm',
      body: '<form data-form="dailyCheckAbnormal">' +
        '<div class="form-col"><label for="dcNote">观察到的情况</label>' +
        '<textarea class="textarea" id="dcNote" name="note" placeholder="例如：背部有一小块红肿，狗狗频繁抓挠…"></textarea></div>' +
        '<div class="form-error" data-error></div>' +
        '<div class="notice notice-warn">如果出现持续呕吐、便血、抽搐、呼吸困难等情况，请立即就医。</div>' +
      '</form>',
      footer: '<button type="button" class="btn btn-secondary" data-modal-close>取消</button>' +
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

  /* ---------------- 爪印明细 ---------------- */
  A.actions.openPawHistory = function () {
    var logs = A.state.pointsLog.slice(0, 30);
    A.openModal({
      title: '爪印获取记录',
      subtitle: '当前累计 ' + A.state.pet.pawPoints + ' 枚爪印',
      icon: '🐾',
      size: 'sm',
      body: '<div class="paw-history-list">' +
        (logs.length
          ? logs.map(function (p) {
            var parts = String(p.date).split('T');
            var d = parts[0].split('-');
            var dateText = d.length === 3 ? Number(d[1]) + '月' + Number(d[2]) + '日' + (parts[1] ? ' ' + parts[1] : '') : p.date;
            return '<div class="paw-history-item"><div class="paw-history-item-left">' +
              '<span class="paw-history-item-reason">' + esc(p.reason) + '</span>' +
              '<span class="paw-history-item-date">' + esc(dateText) + '</span></div>' +
              '<span class="paw-history-item-amount">+' + p.amount + '</span></div>';
          }).join('')
          : '<div class="paw-history-empty">还没有爪印记录哦～<br/>签到、做任务、记录事件都能赚爪印！</div>') +
      '</div>',
      footer: '<button type="button" class="btn btn-primary" data-modal-close>知道了</button>'
    });
  };

  /* ---------------- 档案编辑 ---------------- */
  A.actions.openProfileModal = function () {
    var pet = A.state.pet;
    var breedOptions = D.BREED_OPTIONS.map(function (b) {
      return '<option value="' + esc(b) + '"' + (b === pet.breed ? ' selected' : '') + '>' + esc(b) + '</option>';
    }).join('');
    A.openModal({
      title: '更新宠物档案',
      subtitle: '修改后会立即影响营养计算、提醒与勋章判定',
      icon: '✏️',
      size: 'lg',
      body: '<form data-form="profileEdit">' +
        '<div class="form-row">' +
          '<div class="form-col"><label for="pfName">我的名字 <span class="required">*</span></label><input class="input" id="pfName" name="name" maxlength="64" value="' + esc(pet.name) + '" /></div>' +
          '<div class="form-col"><label for="pfBreed">我的品种 <span class="required">*</span></label><select class="select" id="pfBreed" name="breed">' + breedOptions + '</select></div>' +
        '</div>' +
        '<div class="form-row">' +
          '<div class="form-col"><label for="pfBirthday">我的生日 <span class="required">*</span></label><input class="input" id="pfBirthday" name="birthday" type="date" value="' + esc(pet.birthday) + '" max="' + D.todayISO() + '" /></div>' +
          '<div class="form-col"><label for="pfHome">到家日期</label><input class="input" id="pfHome" name="homeDate" type="date" value="' + esc(pet.homeDate || '') + '" max="' + D.todayISO() + '" /></div>' +
        '</div>' +
        '<div class="form-row">' +
          '<div class="form-col"><label for="pfWeight">我的体重</label><span class="weight-input-wrap"><input id="pfWeight" name="weight" inputmode="decimal" value="' + esc(pet.weight) + '" placeholder="例：11.4" /><span class="weight-unit">kg</span></span></div>' +
          '<div class="form-col"><label for="pfGender">我的性别</label><select class="select" id="pfGender" name="gender">' +
            '<option value="female"' + (pet.gender === 'female' ? ' selected' : '') + '>母</option>' +
            '<option value="male"' + (pet.gender === 'male' ? ' selected' : '') + '>公</option></select></div>' +
        '</div>' +
        '<div class="form-row">' +
          '<div class="form-col"><label for="pfNeutered">绝育情况</label><select class="select" id="pfNeutered" name="neutered">' +
            ['是', '否', '未知'].map(function (v) { return '<option value="' + v + '"' + (pet.neutered === v ? ' selected' : '') + '>' + v + '</option>'; }).join('') +
          '</select></div>' +
          '<div class="form-col"><label for="pfAllergies">过敏源</label><input class="input" id="pfAllergies" name="allergies" value="' + esc(pet.allergies || '') + '" placeholder="逗号分隔，如：鸡肉,谷物" /></div>' +
        '</div>' +
        '<div class="form-row">' +
          '<div class="form-col"><label for="pfDiseases">已知健康状况</label><input class="input" id="pfDiseases" name="diseases" value="' + esc(pet.diseases || '') + '" placeholder="如：慢性肾病、胰腺炎、心脏病等" /></div>' +
          '<div class="form-col"><label for="pfBath">建议洗澡间隔</label><span class="weight-input-wrap"><input id="pfBath" name="bathInterval" inputmode="numeric" value="' + (pet.bathIntervalDays || 24) + '" /><span class="weight-unit">天</span></span></div>' +
        '</div>' +
        '<div class="form-error" data-error></div>' +
        '<div class="notice notice-info">健康档案中的过敏源、疾病与体重会同步影响饮食、保健品与提醒计算。</div>' +
      '</form>',
      footer: '<button type="button" class="btn btn-secondary" data-modal-close>取消</button>' +
        '<button type="button" class="btn btn-primary" data-profile-save>保存档案</button>'
    });
    document.querySelector('[data-profile-save]').addEventListener('click', saveProfile);
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
    var weightChanged = weight && String(D.parseWeight(weight)) !== String(D.parseWeight(pet.weight));
    pet.name = name;
    pet.breed = breed;
    pet.birthday = birthday;
    pet.gender = gender;
    pet.neutered = neutered;
    pet.allergies = allergies;
    pet.diseases = diseases;
    pet.homeDate = homeDate;
    pet.bathIntervalDays = bathInterval;
    if (weightChanged) D.addWeight(A.state, weight, D.todayISO());

    var badges = D.checkBadges(A.state);
    A.closeModal();
    A.commit({ keepScroll: true });
    A.toast('档案已更新，营养与提醒已同步');
    A.celebrate(badges);
  }

  A.actions.exportState = A.exportState;
  A.actions.resetDemo = A.resetDemo;

  A.registerPage('home', {
    title: '首页',
    render: renderHome
  });
})();
