/* PawLife 展示版 — 成长日记与身材管理 */
(function () {
  'use strict';

  var A = window.PawApp;
  var D = window.PawData;
  var esc = A.esc;

  var recordFilter = '全部';
  var recordDraft = { id: null, type: '疫苗', date: D.todayISO(), detail: {} };
  var pendingRisk = null;

  var BCS_META = {
    thin: { label: '偏瘦', icon: '🦴', hint: '肋骨明显可见<br>腰线深陷', range: 'BCS 1-3', desc: '建议增加优质蛋白摄入，14 天后复查。' },
    ideal: { label: '理想', icon: '🐕', hint: '肋骨可摸到<br>覆薄层脂肪', range: 'BCS 4-5', desc: '肋骨可触及但不可见，腰线清晰，保持当前饮食节奏。' },
    heavy: { label: '偏胖', icon: '🦭', hint: '肋骨难摸到<br>腰线不明显', range: 'BCS 6-9', desc: '建议控制食量、增加运动，14 天后复查。' }
  };

  function subHeader(title) {
    return '<div class="sub-page-header"><div class="sub-page-header-row">' +
      '<button type="button" class="btn-back-icon" data-nav="home" title="返回首页">←</button>' +
      '<span class="sub-page-title">' + title + '</span>' +
      '<button type="button" class="today-avatar-sm" data-action="openProfileModal" title="查看/编辑档案">' +
        '<img src="assets/images/tuantuan.svg" alt="' + esc(A.state.pet.name) + ' 的演示头像" />' +
      '</button>' +
    '</div></div>';
  }

  /* ---------------- 成长日记 ---------------- */
  function renderEventForm(state) {
    var d = recordDraft;
    var type = d.type || '疫苗';
    var detail = d.detail || {};
    var date = d.date || D.todayISO();
    var editing = !!d.id;
    var typeOptions = ['疫苗', '驱虫', '发情', '异常行为', '洗澡澡', '每日检查'].map(function (t) {
      return '<option value="' + t + '"' + (t === type ? ' selected' : '') + '>' +
        ({ '疫苗': '💉 疫苗', '驱虫': '💊 驱虫', '发情': '💕 发情', '异常行为': '⚠️ 异常行为', '洗澡澡': '🛁 洗澡澡', '每日检查': '🩺 每日检查' }[t]) + '</option>';
    }).join('');
    var symptoms = D.ABNORMAL_SYMPTOMS.map(function (s) {
      var checked = (detail.symptoms || []).indexOf(s) !== -1 ? ' checked' : '';
      return '<label class="check-chip"><input type="checkbox" name="symptoms" value="' + s + '"' + checked + ' />' + s + '</label>';
    }).join('');
    var showFields = function (list) {
      return list.split(' ').indexOf(type) !== -1 ? '' : ' style="display:none"';
    };

    return '<div class="card event-card">' +
      '<div class="card-header-row">' +
        '<div class="card-subtitle" style="flex:1;margin-bottom:0;">' +
          (editing
            ? '正在编辑 <strong style="color:var(--orange);">' + esc(type) + '</strong> 记录（' + esc(date) + '）· <a href="javascript:void(0)" data-action="cancelEventEdit" style="color:var(--muted);">取消编辑</a>'
            : '帮 <strong style="color:var(--orange);">' + esc(state.pet.name) + '</strong> 记录疫苗、驱虫、发情或异常行为，我会立刻给你反馈') +
        '</div>' +
      '</div>' +
      '<form data-form="eventInline">' +
        '<div class="form-row">' +
          '<div class="form-col"><label>事件类型</label><select class="select" id="evType" data-event-type>' + typeOptions + '</select></div>' +
          '<div class="form-col"><label>日期</label><input class="input" id="evDate" type="date" value="' + esc(date) + '" max="' + D.todayISO() + '" /></div>' +
        '</div>' +

        '<div class="event-fields" data-fields="疫苗"' + showFields('疫苗') + '>' +
          '<div class="form-row">' +
            '<div class="form-col"><label>针次</label><select class="select" id="evDose">' +
              ['第 1 针', '第 2 针', '第 3 针', '加强针'].map(function (v) { return '<option' + (detail.dose === v ? ' selected' : '') + '>' + v + '</option>'; }).join('') +
            '</select></div>' +
            '<div class="form-col"><label>疫苗品牌</label><input class="input" id="evBrand" placeholder="例如 卫佳捌" value="' + esc(detail.brand || '') + '" /></div>' +
          '</div>' +
        '</div>' +

        '<div class="event-fields" data-fields="驱虫"' + showFields('驱虫') + '>' +
          '<div class="form-col"><label>驱虫范围</label><select class="select" id="evDeworm">' +
            ['体内外', '体内', '体外'].map(function (v) { return '<option' + (detail.deworm_type === v ? ' selected' : '') + '>' + v + '</option>'; }).join('') +
          '</select></div>' +
        '</div>' +

        '<div class="event-fields" data-fields="洗澡澡 发情"' + showFields('洗澡澡 发情') + '>' +
          '<div class="form-col"><label>备注</label><textarea class="textarea" id="evNote" placeholder="记录护理方式、观察到的情况等">' + esc(detail.note || '') + '</textarea></div>' +
        '</div>' +

        '<div class="event-fields" data-fields="异常行为"' + showFields('异常行为') + '>' +
          '<div class="form-col"><label>观察到的情况</label><div class="symptom-grid">' + symptoms + '</div>' +
          '<span class="field-hint">出现高风险关键词时会弹出紧急就医提醒。</span></div>' +
          '<div class="form-col"><label>补充描述</label><textarea class="textarea" id="evAbnormalNote" placeholder="例如：今天散步后持续呕吐两次，精神较差…">' + esc(detail.note || '') + '</textarea></div>' +
        '</div>' +

        '<div class="event-fields" data-fields="每日检查"' + showFields('每日检查') + '>' +
          '<div class="form-row">' +
            '<div class="form-col"><label>检查结果</label><select class="select" id="evCheckResult">' +
              '<option value="normal"' + (detail.result !== 'abnormal' ? ' selected' : '') + '>一切正常</option>' +
              '<option value="abnormal"' + (detail.result === 'abnormal' ? ' selected' : '') + '>发现异常</option>' +
            '</select></div>' +
            '<div class="form-col"><label>备注</label><input class="input" id="evCheckNote" placeholder="可选" value="' + esc(detail.note || '') + '" /></div>' +
          '</div>' +
        '</div>' +

        '<div class="event-form-actions">' +
          '<button type="submit" class="btn btn-primary">' + (editing ? '✏️ 更新记录' : '🐾 提交记录') + '</button>' +
        '</div>' +
      '</form>' +
      (state.ui.lastReaction ? '<div class="reaction-box show">' + esc(state.ui.lastReaction) + '</div>' : '') +
    '</div>';
  }

  function reactionOf(state, type, highRisk) {
    if (highRisk) return '高风险情况已记录，请优先联系兽医确认状况。';
    var name = state.pet.name;
    if (type === '疫苗') return name + '今天超勇敢！打完针记得留观，回家好好休息～';
    if (type === '驱虫') return '小虫子都赶走啦！记得按周期继续驱虫～';
    if (type === '洗澡澡') return '洗香香啦！记得把皮肤褶皱和脚趾间彻底吹干～';
    if (type === '异常行为') return '记录好啦，我会继续观察自己的状态，主人也多留意～';
    if (type === '发情') return '成长印记已记录，出门记得牵好绳～';
    return '健康检查已记录，获得 1 枚爪印。';
  }

  function readEventForm(form, type) {
    var detail = {};
    if (type === '疫苗') {
      detail.dose = form.querySelector('#evDose').value;
      detail.brand = form.querySelector('#evBrand').value.trim();
    } else if (type === '驱虫') {
      detail.deworm_type = form.querySelector('#evDeworm').value;
    } else if (type === '洗澡澡' || type === '发情') {
      detail.note = form.querySelector('#evNote').value.trim();
    } else if (type === '异常行为') {
      detail.symptoms = Array.prototype.map.call(form.querySelectorAll('input[name="symptoms"]:checked'), function (i) { return i.value; });
      detail.note = form.querySelector('#evAbnormalNote').value.trim();
    } else if (type === '每日检查') {
      detail.result = form.querySelector('#evCheckResult').value;
      detail.note = form.querySelector('#evCheckNote').value.trim();
    }
    return detail;
  }

  function saveEvent(payload, forceHighRisk) {
    var riskKeyword = payload.type === '异常行为' ? D.scanHighRisk((payload.detail.symptoms || []).join('，') + '，' + (payload.detail.note || '')) : null;
    if (riskKeyword && !forceHighRisk) {
      pendingRisk = payload;
      A.openModal({
        title: '紧急提醒：请立即联系兽医',
        subtitle: '检测到高风险症状关键词「' + riskKeyword + '」',
        icon: '🚨',
        size: 'sm',
        body: '<div class="risk-modal-body">' +
          '<p>您记录的症状可能表明宠物存在严重健康风险，甚至危及生命。本应用无法诊断或治疗疾病。</p>' +
          '<ol class="risk-steps"><li>立即联系您的兽医或最近的 24 小时宠物医院</li><li>不要等待观察，不要自行用药</li><li>本次记录后，今日饮食与保健品建议将自动暂停</li></ol>' +
          '<div class="notice notice-danger">请优先就医，不要仅依赖应用内建议。</div>' +
        '</div>',
        footer: '<button type="button" class="btn btn-secondary" data-modal-close>取消</button>' +
          '<button type="button" class="btn btn-danger" data-risk-confirm>我知道了，已联系兽医</button>'
      });
      document.querySelector('[data-risk-confirm]').addEventListener('click', function () {
        var p = pendingRisk;
        pendingRisk = null;
        A.closeModal();
        commitEvent(p, riskKeyword);
      });
      return;
    }
    commitEvent(payload, riskKeyword);
  }

  function commitEvent(payload, riskKeyword) {
    var result;
    if (payload.id) {
      result = D.updateEvent(A.state, payload.id, {
        type: payload.type, date: payload.date, detail: payload.detail,
        highRisk: !!riskKeyword, riskKeyword: riskKeyword || ''
      });
      if (result.error) { A.toast(result.error, 'error'); return; }
    } else {
      result = D.addEvent(A.state, {
        type: payload.type, date: payload.date, detail: payload.detail,
        highRisk: !!riskKeyword, riskKeyword: riskKeyword || ''
      });
    }
    A.state.ui.lastReaction = reactionOf(A.state, payload.type, !!riskKeyword);
    recordDraft = { id: null, type: payload.type, date: D.todayISO(), detail: {} };
    var badges = D.checkBadges(A.state);
    A.commit({ keepScroll: true });
    A.toast(riskKeyword ? '高风险记录已保存，今日营养建议已暂停' : '记录已保存，获得 1 枚爪印', riskKeyword ? 'warn' : 'success');
    A.celebrate(badges);
  }

  A.forms.eventInline = function (form) {
    var type = form.querySelector('#evType').value;
    var date = form.querySelector('#evDate').value;
    var err = form.parentNode.querySelector('.form-error');
    if (!date) { A.toast('请选择事件日期。', 'error'); return; }
    if (date > D.todayISO()) { A.toast('事件日期不能晚于今天。', 'error'); return; }
    var payload = { id: recordDraft.id, type: type, date: date, detail: readEventForm(form, type) };
    saveEvent(payload, false);
  };

  function mountRecord() {
    var sel = document.getElementById('evType');
    if (!sel) return;
    function toggle() {
      var t = sel.value;
      document.querySelectorAll('.event-fields').forEach(function (el) {
        el.style.display = el.getAttribute('data-fields').split(' ').indexOf(t) !== -1 ? '' : 'none';
      });
    }
    sel.addEventListener('change', toggle);
    toggle();
  }

  A.actions.quickRecord = function (dataset) {
    recordDraft = { id: null, type: (dataset && dataset.type) || '疫苗', date: D.todayISO(), detail: {} };
    A.navigate('record');
  };

  A.actions.openEventModal = function () {
    A.navigate('record');
  };

  A.actions.editEvent = function (dataset) {
    var event = A.state.events.filter(function (e) { return e.id === Number(dataset.id); })[0];
    if (!event) return;
    recordDraft = {
      id: event.id,
      type: event.type,
      date: event.date,
      detail: event.detail || {}
    };
    A.commit({ keepScroll: true });
    var card = document.querySelector('.event-card');
    if (card) card.scrollIntoView({ behavior: 'smooth', block: 'center' });
  };

  A.actions.cancelEventEdit = function () {
    recordDraft = { id: null, type: '疫苗', date: D.todayISO(), detail: {} };
    A.commit({ keepScroll: true });
  };

  /* ---------------- 时间线 ---------------- */
  function recordTitle(event) {
    var name = A.state.pet.name;
    var map = {
      '疫苗': name + '的勇敢日',
      '驱虫': '驱虫保卫日',
      '发情': name + '的成长印记',
      '异常行为': name + '的小状况',
      '洗澡澡': '洗香香日',
      '每日检查': '每日健康检查'
    };
    return map[event.type] || event.type;
  }

  function renderTimeline(state) {
    var types = ['全部', '疫苗', '驱虫', '异常行为', '每日检查', '发情', '洗澡澡'];
    var events = state.events.slice().sort(function (a, b) { return a.date < b.date ? 1 : -1; });
    if (recordFilter !== '全部') {
      events = events.filter(function (e) { return e.type === recordFilter; });
    }
    var filters = types.map(function (t) {
      var labels = { '全部': '全部', '疫苗': '💉 疫苗', '驱虫': '💊 驱虫', '异常行为': '⚠️ 异常', '每日检查': '🩺 摸摸', '发情': '💕 发情', '洗澡澡': '🛁 洗澡' };
      return '<button type="button" class="tl-filter' + (recordFilter === t ? ' active' : '') + '" data-action="setRecordFilter" data-filter="' + t + '">' + labels[t] + '</button>';
    }).join('');

    var list = events.length
      ? '<div class="timeline">' + events.map(function (e) {
        var meta = D.EVENT_META[e.type] || D.EVENT_META['每日检查'];
        var d = D.parseISO(e.date);
        return '<article class="timeline-item">' +
          '<div class="timeline-date"><b>' + ('0' + d.getDate()).slice(-2) + '</b><span>' + (d.getMonth() + 1) + '月</span></div>' +
          '<div class="timeline-line"><span class="timeline-dot ' + meta.cls + '">' + meta.icon + '</span></div>' +
          '<div class="timeline-card">' +
            '<div class="timeline-top"><h3>' + esc(recordTitle(e)) + '</h3>' +
              (e.high_risk ? '<span class="status status-overdue">高风险 · ' + esc(e.risk_keyword || '') + '</span>' : '') +
              '<span class="chip chip-muted">' + esc(e.type) + '</span></div>' +
            '<p>' + esc(D.eventDetailText(e)) + '</p>' +
            '<div class="timeline-foot"><span>' + esc(e.date) + '</span>' +
              '<div class="timeline-actions">' +
                '<button type="button" class="btn btn-text btn-sm" data-action="openRecordDetail" data-id="' + e.id + '">详情</button>' +
                '<button type="button" class="btn btn-text btn-sm" data-action="editEvent" data-id="' + e.id + '">编辑</button>' +
                '<button type="button" class="btn btn-text btn-sm danger-text" data-action="deleteEvent" data-id="' + e.id + '">删除</button>' +
              '</div>' +
            '</div>' +
          '</div>' +
        '</article>';
      }).join('') + '</div>'
      : A.emptyState('📝', '这个分类还没有记录', '可以新增一条演示事件，时间线会立即更新。');

    return '<div class="card">' +
      '<div class="card-title">📅 汪生时间线</div>' +
      '<div class="timeline-filters">' + filters + '</div>' +
      list +
    '</div>';
  }

  A.actions.setRecordFilter = function (dataset) {
    recordFilter = dataset.filter || '全部';
    A.commit({ keepScroll: true });
  };

  A.actions.openRecordDetail = function (dataset) {
    var event = A.state.events.filter(function (e) { return e.id === Number(dataset.id); })[0];
    if (!event) return;
    var d = event.detail || {};
    var rows = [['记录类型', event.type], ['日期', event.date]];
    if (event.type === '疫苗') {
      rows.push(['针次', d.dose || '未填写']);
      rows.push(['品牌', d.brand || '未填写']);
    } else if (event.type === '驱虫') {
      rows.push(['驱虫范围', d.deworm_type || '未填写']);
    } else if (event.type === '异常行为') {
      rows.push(['症状', (d.symptoms || []).join('、') || '未选择']);
      rows.push(['描述', d.note || '无']);
    } else if (event.type === '每日检查') {
      rows.push(['结果', d.result === 'abnormal' ? '发现异常' : '一切正常']);
      rows.push(['备注', d.note || '无']);
    } else {
      rows.push(['备注', d.note || '无']);
    }
    if (event.high_risk) rows.push(['风险标记', '高风险 · ' + (event.risk_keyword || '')]);
    A.openModal({
      title: '记录详情',
      subtitle: event.date + ' · ' + event.type,
      icon: (D.EVENT_META[event.type] || {}).icon || '📝',
      size: 'sm',
      body: '<dl class="detail-grid single">' + rows.map(function (r) {
        return '<div><dt>' + esc(r[0]) + '</dt><dd>' + esc(r[1]) + '</dd></div>';
      }).join('') + '</dl>',
      footer: '<button type="button" class="btn btn-primary" data-modal-close>关闭</button>'
    });
  };

  A.actions.deleteEvent = function (dataset) {
    var id = Number(dataset.id);
    var event = A.state.events.filter(function (e) { return e.id === id; })[0];
    if (!event) return;
    A.confirm({
      title: '删除演示记录',
      message: '确定删除 ' + event.date + ' 的「' + event.type + '」吗？',
      note: '删除后趋势、提醒与勋章进度会重新计算，但已解锁勋章不会回收。',
      confirmText: '删除',
      danger: true
    }).then(function (ok) {
      if (!ok) return;
      A.state.events = A.state.events.filter(function (e) { return e.id !== id; });
      if (event.type === '洗澡澡' || event.type === '每日检查') {
        var lastBath = A.state.events.filter(function (e) { return e.type === '洗澡澡'; })
          .sort(function (a, b) { return a.date < b.date ? 1 : -1; })[0];
        A.state.pet.lastBathDate = lastBath ? lastBath.date : null;
      }
      A.commit({ keepScroll: true });
      A.toast('记录已删除');
    });
  };

  function renderRecord(state) {
    return '<div class="sub-page">' + subHeader('📝 ' + esc(state.pet.name) + '的成长日记') +
      renderEventForm(state) +
      renderTimeline(state) +
    '</div>';
  }

  /* ---------------- 身材管理 ---------------- */
  function renderWeightChartCard(state) {
    var range = state.ui.weightRange || 90;
    var stats = D.weightStats(state.weightLogs, range);
    var ideal = D.idealRange(state.pet.breed);
    var chart = stats
      ? A.weightChart(stats.logs, ideal, { rangeStart: D.daysAgoISO(range), height: 300 })
      : '<div class="chart-empty">该区间暂无记录，请切换时间范围或新增体重。</div>';
    var statsHtml = stats
      ? '<div class="weight-stats-row">' +
          '<div><span>最新</span><b>' + stats.latest + '<small>kg</small></b></div>' +
          '<div><span>变化</span><b>' + (stats.change > 0 ? '+' : '') + stats.change + '<small>kg</small></b></div>' +
          '<div><span>最低 / 最高</span><b>' + stats.min + '–' + stats.max + '<small>kg</small></b></div>' +
          '<div><span>平均</span><b>' + stats.avg + '<small>kg</small></b></div>' +
        '</div>'
      : '';
    var alert = '';
    if (stats) {
      if (stats.change > 0.3) alert = '近 ' + range + ' 天体重上升 ' + stats.change + ' kg，建议复核每日喂食量与零食占比。';
      else if (stats.change < -0.3) alert = '近 ' + range + ' 天体重下降 ' + Math.abs(stats.change) + ' kg，建议关注食欲与消化情况。';
      else alert = '近 ' + range + ' 天体重整体平稳，继续保持规律记录。';
      if (ideal) {
        var current = D.parseWeight(state.pet.weight);
        if (current !== null && (current < ideal[0] || current > ideal[1])) {
          alert += ' 当前体重' + (current < ideal[0] ? '低于' : '高于') + '该品种参考范围 ' + ideal[0] + '–' + ideal[1] + ' kg。';
        }
      }
    }
    return '<div class="card">' +
      '<div class="card-title">📈 体重趋势</div>' +
      '<div class="chart-range">' + [30, 90, 180, 365].map(function (d) {
        return '<button type="button" class="' + (range === d ? 'active' : '') + '" data-action="setWeightRange" data-days="' + d + '">' + d + ' 天</button>';
      }).join('') + '</div>' +
      chart + statsHtml +
      (alert ? '<div class="weight-trend-alert">💡 ' + esc(alert) + '</div>' : '') +
      '<div class="chart-legend"><span><i class="legend-line"></i>体重曲线</span>' + (ideal ? '<span><i class="legend-band"></i>理想体重区间</span>' : '') + '<span class="muted">悬停数据点查看日期与数值</span></div>' +
    '</div>';
  }

  function renderWeightRecordCard(state) {
    return '<div class="card">' +
      '<div class="card-title">📝 记录体重</div>' +
      '<form data-form="weightInline" class="weight-inline-form">' +
        '<span class="weight-input-wrap"><input id="wlWeight" name="weight" inputmode="decimal" placeholder="体重，如：11.4" /><span class="weight-unit">kg</span></span>' +
        '<input class="input weight-date" id="wlDate" name="date" type="date" value="' + D.todayISO() + '" max="' + D.todayISO() + '" />' +
        '<button type="submit" class="btn btn-primary">+ 记录</button>' +
      '</form>' +
      '<div class="weight-frequency-hint">建议每 30 天左右记录一次，幼犬可更频繁。同一天重复记录会覆盖当天数值。</div>' +
    '</div>';
  }

  function renderBCS(state) {
    var latest = D.latestBCS(state);
    var selected = latest ? latest.state : '';
    var cards = Object.keys(BCS_META).map(function (key) {
      var m = BCS_META[key];
      return '<button type="button" class="bcs-state-card' + (selected === key ? ' selected' : '') + '" data-action="recordBCS" data-state="' + key + '">' +
        '<div class="bcs-icon">' + m.icon + '</div>' +
        '<div class="bcs-label">' + m.label + '</div>' +
        '<div class="bcs-hint">' + m.hint + '</div>' +
        '<div class="bcs-range">' + m.range + '</div>' +
      '</button>';
    }).join('');
    return '<div class="card">' +
      '<div class="card-title">🤚 体况评分（BCS）</div>' +
      '<div class="bcs-intro">摸摸肋骨来判断胖瘦——比体重数字更科学。' +
        (latest ? ' 当前评估：<b>' + BCS_META[latest.state].label + '</b>（' + latest.date + '）' : ' 还没有评估记录。') +
      '</div>' +
      '<div class="bcs-state-cards">' + cards + '</div>' +
      '<div class="bcs-tip">' + (latest ? BCS_META[latest.state].desc : '选择最符合当前体况的一档即可记录。') + '</div>' +
      '<div class="notice notice-info">BCS 是主观体况筛查，结果为演示判断，不替代兽医体检。</div>' +
    '</div>';
  }

  function renderWeightHistory(state) {
    var logs = state.weightLogs.slice().sort(function (a, b) { return a.date < b.date ? 1 : -1; });
    var body = logs.length
      ? logs.map(function (l, i) {
        var prev = logs[i + 1];
        var diff = prev ? Math.round((l.weight - prev.weight) * 10) / 10 : null;
        return '<div class="weight-log-row">' +
          '<span class="wl-date">' + l.date + '</span>' +
          '<span class="wl-weight">' + l.weight + ' kg</span>' +
          '<span class="wl-diff">' + (diff === null ? '—' : (diff > 0 ? '+' : '') + diff + ' kg') + '</span>' +
          '<button type="button" class="btn btn-text btn-sm danger-text" data-action="deleteWeight" data-id="' + l.id + '">删除</button>' +
        '</div>';
      }).join('')
      : '<p class="small muted">暂无体重记录。</p>';
    return '<div class="card">' +
      '<div class="card-title">📋 历史记录</div>' +
      '<div class="weight-log-head"><span>日期</span><span>体重</span><span>较上次</span><span></span></div>' +
      body +
    '</div>';
  }

  function renderWeight(state) {
    return '<div class="sub-page">' + subHeader('⚖️ ' + esc(state.pet.name) + '的身材管理') +
      renderWeightChartCard(state) +
      renderWeightRecordCard(state) +
      renderBCS(state) +
      renderWeightHistory(state) +
    '</div>';
  }

  A.actions.setWeightRange = function (dataset) {
    A.state.ui.weightRange = Number(dataset.days) || 90;
    A.commit({ keepScroll: true });
  };

  A.forms.weightInline = function (form) {
    var value = form.querySelector('#wlWeight').value.trim();
    var date = form.querySelector('#wlDate').value;
    if (D.parseWeight(value) === null) { A.toast('请输入有效的体重数值。', 'error'); return; }
    if (!date || date > D.todayISO()) { A.toast('请选择不晚于今天的日期。', 'error'); return; }
    var res = D.addWeight(A.state, value, date);
    if (res.error) { A.toast(res.error, 'error'); return; }
    var badges = D.checkBadges(A.state);
    A.commit({ keepScroll: true });
    A.toast('体重已更新为 ' + res.weight + ' kg');
    A.celebrate(badges);
  };

  A.actions.deleteWeight = function (dataset) {
    var id = Number(dataset.id);
    var log = A.state.weightLogs.filter(function (l) { return l.id === id; })[0];
    if (!log) return;
    A.confirm({
      title: '删除体重记录',
      message: '确定删除 ' + log.date + ' 的 ' + log.weight + ' kg 记录吗？',
      confirmText: '删除',
      danger: true
    }).then(function (ok) {
      if (!ok) return;
      A.state.weightLogs = A.state.weightLogs.filter(function (l) { return l.id !== id; });
      var latest = D.latestWeight(A.state);
      if (latest) A.state.pet.weight = String(latest.weight);
      A.commit({ keepScroll: true });
      A.toast('体重记录已删除');
    });
  };

  A.actions.recordBCS = function (dataset) {
    if (!BCS_META[dataset.state]) return;
    D.recordBCS(A.state, dataset.state);
    var badges = D.checkBadges(A.state);
    A.commit({ keepScroll: true });
    A.toast('已记录体况：' + BCS_META[dataset.state].label);
    A.celebrate(badges);
  };

  A.actions.openWeightModal = function () {
    A.navigate('weight');
    setTimeout(function () {
      var input = document.getElementById('wlWeight');
      if (input) {
        input.focus();
        input.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    }, 120);
  };

  A.registerPage('record', {
    title: '成长日记',
    render: renderRecord,
    mount: mountRecord
  });

  A.registerPage('weight', {
    title: '身材管理',
    render: renderWeight
  });
})();
