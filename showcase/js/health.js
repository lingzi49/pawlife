/* PawLife 展示版 — 健康记录与健康趋势 */
(function () {
  'use strict';

  var A = window.PawApp;
  var D = window.PawData;
  var esc = A.esc;

  var recordFilter = '全部';
  var trendRange = 90;
  var eventRiskArmed = false;

  var BCS_META = {
    thin: { label: '偏瘦', cls: 'bcs-thin', desc: '肋骨与腰线明显，建议增加优质蛋白并 14 天后复查。' },
    ideal: { label: '理想', cls: 'bcs-ideal', desc: '肋骨可触及但不可见，腰线清晰，保持当前饮食节奏。' },
    heavy: { label: '偏重', cls: 'bcs-heavy', desc: '肋骨不易触及，腰线不明显，建议控制食量并增加运动。' }
  };

  function dateParts(iso) {
    var d = D.parseISO(iso);
    var now = new Date();
    return {
      day: ('0' + d.getDate()).slice(-2),
      month: (d.getMonth() + 1) + '月',
      year: d.getFullYear() !== now.getFullYear() ? d.getFullYear() : ''
    };
  }

  function mergedRecords(state) {
    var events = state.events.map(function (e) {
      return { id: e.id, kind: 'event', type: e.type, date: e.date, detail: e.detail, high_risk: e.high_risk, risk_keyword: e.risk_keyword };
    });
    var weights = state.weightLogs.map(function (w) {
      return { id: w.id, kind: 'weight', type: '体重', date: w.date, detail: { weight: w.weight } };
    });
    return events.concat(weights).sort(function (a, b) {
      if (a.date !== b.date) return a.date < b.date ? 1 : -1;
      return b.id - a.id;
    });
  }

  function recordTitle(record) {
    if (record.kind === 'weight') return '体重记录 · ' + record.detail.weight + ' kg';
    var meta = D.EVENT_META[record.type] || D.EVENT_META['每日检查'];
    return meta.label;
  }

  function recordDetail(record) {
    if (record.kind === 'weight') return '同步更新档案中的当前体重。';
    return D.eventDetailText(record);
  }

  function renderRecordStats(state) {
    function lastOf(type) {
      var list = state.events.filter(function (e) { return e.type === type; }).sort(function (a, b) { return a.date < b.date ? 1 : -1; });
      return list[0] || null;
    }
    var vax = lastOf('疫苗');
    var deworm = lastOf('驱虫');
    var bath = lastOf('洗澡澡');
    return '<div class="record-stats">' +
      '<div class="record-stat"><span>健康事件</span><b>' + state.events.length + '<small> 条</small></b><em>含体重以外的全部记录</em></div>' +
      '<div class="record-stat"><span>最近疫苗</span><b>' + (vax ? vax.date : '未记录') + '</b><em>' + (vax ? '共 ' + state.events.filter(function (e) { return e.type === '疫苗'; }).length + ' 次接种' : '建议咨询兽医制定计划') + '</em></div>' +
      '<div class="record-stat"><span>最近驱虫</span><b>' + (deworm ? deworm.date : '未记录') + '</b><em>' + (deworm ? '共 ' + state.events.filter(function (e) { return e.type === '驱虫'; }).length + ' 次' : '体内外驱虫从小开始') + '</em></div>' +
      '<div class="record-stat"><span>最近洗澡</span><b>' + (bath ? bath.date : '未记录') + '</b><em>' + (bath ? '建议间隔 ' + (state.pet.bathIntervalDays || 24) + ' 天' : '记录后可计算洗护间隔') + '</em></div>' +
    '</div>';
  }

  function renderFilter() {
    var types = ['全部', '疫苗', '驱虫', '洗澡澡', '异常行为', '每日检查', '体重'];
    return '<div class="segmented record-filter">' + types.map(function (t) {
      return '<button type="button" class="' + (recordFilter === t ? 'active' : '') + '" data-action="setRecordFilter" data-filter="' + t + '">' + t + '</button>';
    }).join('') + '</div>';
  }

  function renderTimeline(state) {
    var records = mergedRecords(state);
    var filtered = recordFilter === '全部'
      ? records
      : recordFilter === '体重'
        ? records.filter(function (r) { return r.kind === 'weight'; })
        : records.filter(function (r) { return r.kind === 'event' && r.type === recordFilter; });

    if (!filtered.length) {
      return A.emptyState('📝', '这个分类还没有记录', '可以新增一条演示事件，时间线会立即更新。',
        '<button type="button" class="btn btn-primary" data-action="openEventModal">记录健康事件</button>');
    }
    return '<div class="timeline">' + filtered.map(function (r) {
      var dp = dateParts(r.date);
      var meta = D.EVENT_META[r.type] || D.EVENT_META['每日检查'];
      return '<article class="timeline-item">' +
        '<div class="timeline-date"><b>' + dp.day + '</b><span>' + dp.month + (dp.year ? ' ' + dp.year : '') + '</span></div>' +
        '<div class="timeline-line"><span class="timeline-dot ' + meta.cls + '">' + meta.icon + '</span></div>' +
        '<div class="timeline-card">' +
          '<div class="timeline-top">' +
            '<h3>' + esc(recordTitle(r)) + '</h3>' +
            (r.high_risk ? '<span class="status status-overdue">高风险 · ' + esc(r.risk_keyword || '') + '</span>' : '') +
            '<span class="chip chip-muted">' + esc(r.type) + '</span>' +
          '</div>' +
          '<p>' + esc(recordDetail(r)) + '</p>' +
          '<div class="timeline-foot">' +
            '<span>' + esc(r.date) + '</span>' +
            '<div class="timeline-actions">' +
              '<button type="button" class="btn btn-ghost btn-sm" data-action="openRecordDetail" data-kind="' + r.kind + '" data-id="' + r.id + '">详情</button>' +
              '<button type="button" class="btn btn-ghost btn-sm danger-text" data-action="deleteRecord" data-kind="' + r.kind + '" data-id="' + r.id + '">删除</button>' +
            '</div>' +
          '</div>' +
        '</div>' +
      '</article>';
    }).join('') + '</div>';
  }

  function renderRecords(state) {
    return '<div class="page-intro">' +
      '<div><h2>健康事件时间线</h2><p>疫苗、驱虫、洗澡、异常观察与体重记录集中管理。</p></div>' +
      '<div class="intro-actions">' +
        '<button type="button" class="btn btn-secondary btn-sm" data-action="openWeightModal">' + A.icon('scale') + '记录体重</button>' +
        '<button type="button" class="btn btn-primary btn-sm" data-action="openEventModal">' + A.icon('plus') + '记录事件</button>' +
      '</div>' +
    '</div>' +
    renderRecordStats(state) +
    '<div class="card records-card">' +
      '<div class="card-head"><div class="card-head-main">' +
        '<div class="card-title">' + A.icon('clipboard') + '全部记录</div>' +
        '<div class="card-sub">按日期倒序排列 · 点击「详情」查看完整字段</div>' +
      '</div>' + renderFilter() + '</div>' +
      renderTimeline(state) +
    '</div>';
  }

  /* ---------------- 新增事件 ---------------- */
  function reactionOf(state, type, highRisk) {
    if (highRisk) return '高风险情况已记录，请优先联系兽医确认状况';
    var name = state.pet.name;
    if (type === '疫苗') return name + '今天超勇敢！打完针记得留观，回家好好休息～';
    if (type === '驱虫') return '小虫子都赶走啦！记得按周期继续驱虫～';
    if (type === '洗澡澡') return '洗香香啦！记得把皮肤褶皱和脚趾间彻底吹干～';
    if (type === '异常行为') return '记录好啦，我会继续观察自己的状态，主人也多留意～';
    if (type === '发情') return '成长印记已记录，出门记得牵好绳～';
    return '健康检查已记录，获得 1 枚爪印';
  }

  A.actions.openEventModal = function (dataset) {
    eventRiskArmed = false;
    var prefill = (dataset && dataset.type) || '疫苗';
    var typeOptions = ['疫苗', '驱虫', '洗澡澡', '异常行为', '发情', '每日检查'].map(function (t) {
      return '<option value="' + t + '"' + (t === prefill ? ' selected' : '') + '>' + t + '</option>';
    }).join('');
    var symptoms = D.ABNORMAL_SYMPTOMS.map(function (s) {
      return '<label class="check-chip"><input type="checkbox" name="symptoms" value="' + s + '" />' + s + '</label>';
    }).join('');
    A.openModal({
      title: '记录健康事件',
      subtitle: '演示记录会写入浏览器本地，不会进入原应用数据库',
      size: 'lg',
      body: '<form data-form="eventCreate">' +
        '<div class="form-grid">' +
          '<div class="field"><label for="evType">事件类型 <em>*</em></label><select class="select" id="evType" data-event-type>' + typeOptions + '</select></div>' +
          '<div class="field"><label for="evDate">日期 <em>*</em></label><input class="input" id="evDate" type="date" value="' + D.todayISO() + '" max="' + D.todayISO() + '" /></div>' +

          '<div class="field span-2 event-fields" data-fields="疫苗">' +
            '<div class="form-grid">' +
              '<div class="field"><label for="evDose">针次</label><select class="select" id="evDose"><option>第 1 针</option><option>第 2 针</option><option>第 3 针</option><option selected>加强针</option></select></div>' +
              '<div class="field"><label for="evBrand">疫苗品牌</label><input class="input" id="evBrand" placeholder="例如 卫佳捌" /></div>' +
            '</div>' +
          '</div>' +

          '<div class="field span-2 event-fields" data-fields="驱虫">' +
            '<label>驱虫范围</label>' +
            '<select class="select" id="evDeworm"><option>体内外</option><option>体内</option><option>体外</option></select>' +
          '</div>' +

          '<div class="field span-2 event-fields" data-fields="洗澡澡 发情">' +
            '<label for="evNote">备注</label>' +
            '<textarea class="textarea" id="evNote" placeholder="记录护理方式、观察到的情况等"></textarea>' +
          '</div>' +

          '<div class="field span-2 event-fields" data-fields="异常行为">' +
            '<label>观察到的情况</label>' +
            '<div class="symptom-grid">' + symptoms + '</div>' +
            '<span class="hint">请选择或补充描述；出现高风险关键词时会触发就医提醒。</span>' +
          '</div>' +

          '<div class="field span-2 event-fields" data-fields="异常行为">' +
            '<label for="evAbnormalNote">补充描述</label>' +
            '<textarea class="textarea" id="evAbnormalNote" placeholder="例如：今天散步后持续呕吐两次，精神较差…"></textarea>' +
          '</div>' +

          '<div class="field span-2 event-fields" data-fields="每日检查">' +
            '<div class="form-grid">' +
              '<div class="field"><label for="evCheckResult">检查结果</label><select class="select" id="evCheckResult"><option value="normal">一切正常</option><option value="abnormal">发现异常</option></select></div>' +
              '<div class="field"><label for="evCheckNote">备注</label><input class="input" id="evCheckNote" placeholder="可选" /></div>' +
            '</div>' +
          '</div>' +
        '</div>' +
        '<div class="event-risk-warning" data-risk-warning></div>' +
        '<div class="form-error" data-error style="margin-top:12px"></div>' +
        '<div class="notice notice-info" style="margin-top:14px">' + A.icon('alert') +
          '<span>高风险关键词包括：持续呕吐、便血、抽搐、呼吸困难、中毒、车祸等。命中后会暂停今日营养建议并提示就医。</span>' +
        '</div>' +
      '</form>',
      footer: '<button type="button" class="btn btn-ghost" data-modal-close>取消</button>' +
        '<button type="button" class="btn btn-primary" data-event-save>保存记录</button>'
    });

    var typeSelect = document.querySelector('[data-event-type]');
    function updateFields() {
      var t = typeSelect.value;
      document.querySelectorAll('.event-fields').forEach(function (el) {
        el.style.display = el.getAttribute('data-fields').split(' ').indexOf(t) !== -1 ? '' : 'none';
      });
      var warning = document.querySelector('[data-risk-warning]');
      if (warning) warning.classList.remove('show');
      eventRiskArmed = false;
      var saveBtn = document.querySelector('[data-event-save]');
      if (saveBtn) saveBtn.textContent = '保存记录';
    }
    typeSelect.addEventListener('change', updateFields);
    updateFields();

    document.querySelector('[data-event-save]').addEventListener('click', function () {
      submitEvent(typeSelect.value, false);
    });
  };

  function submitEvent(type, forceHighRisk) {
    var form = document.querySelector('form[data-form="eventCreate"]');
    var date = form.querySelector('#evDate').value;
    var err = form.querySelector('[data-error]');
    var warning = form.querySelector('[data-risk-warning]');
    err.classList.remove('show');
    if (!date) return showErr('请选择事件日期。');
    if (date > D.todayISO()) return showErr('事件日期不能晚于今天。');

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

    var riskText = type === '异常行为'
      ? ((detail.symptoms || []).join('，') + '，' + (detail.note || ''))
      : '';
    var riskKeyword = type === '异常行为' ? D.scanHighRisk(riskText) : null;

    if (riskKeyword && !eventRiskArmed && !forceHighRisk) {
      eventRiskArmed = true;
      warning.innerHTML = '<b>⚠️ 检测到高风险关键词「' + esc(riskKeyword) + '」</b>' +
        '<p>请优先联系兽医或前往宠物医院，不要仅依赖应用内建议。再次点击「保存记录」将记录该事件，并暂停今日营养与补充建议。</p>';
      warning.classList.add('show');
      var btn = document.querySelector('[data-event-save]');
      btn.textContent = '我已了解风险，仍然记录';
      return;
    }

    var res = D.addEvent(A.state, {
      type: type, date: date, detail: detail,
      highRisk: !!riskKeyword, riskKeyword: riskKeyword || ''
    });
    var badges = D.checkBadges(A.state);
    A.closeModal();
    A.commit({ keepScroll: true });
    A.toast(reactionOf(A.state, type, !!riskKeyword), riskKeyword ? 'warn' : 'success');
    if (riskKeyword) {
      A.toast('今日营养建议已暂停，可在营养页手动恢复', 'error');
    }
    A.celebrate(badges);

    function showErr(msg) {
      err.textContent = msg;
      err.classList.add('show');
    }
  }

  /* ---------------- 体重与体况 ---------------- */
  A.actions.openWeightModal = function () {
    A.openModal({
      title: '记录体重',
      subtitle: '保存后会同步档案、体重趋势与营养计算',
      size: 'sm',
      body: '<form data-form="weightCreate">' +
        '<div class="form-grid">' +
          '<div class="field"><label for="wWeight">体重（kg） <em>*</em></label><input class="input" id="wWeight" inputmode="decimal" value="' + esc(A.state.pet.weight) + '" placeholder="例如 11.4" /></div>' +
          '<div class="field"><label for="wDate">日期 <em>*</em></label><input class="input" id="wDate" type="date" value="' + D.todayISO() + '" max="' + D.todayISO() + '" /></div>' +
        '</div>' +
        '<div class="form-error" data-error style="margin-top:14px"></div>' +
        '<div class="notice notice-info" style="margin-top:14px">' + A.icon('chart') + '<span>同一天重复记录会覆盖当天的体重数值。</span></div>' +
      '</form>',
      footer: '<button type="button" class="btn btn-ghost" data-modal-close>取消</button>' +
        '<button type="button" class="btn btn-primary" data-weight-save>保存体重</button>'
    });
    document.querySelector('[data-weight-save]').addEventListener('click', function () {
      var form = document.querySelector('form[data-form="weightCreate"]');
      var value = form.querySelector('#wWeight').value.trim();
      var date = form.querySelector('#wDate').value;
      var err = form.querySelector('[data-error]');
      err.classList.remove('show');
      if (D.parseWeight(value) === null) {
        err.textContent = '请输入有效的体重数值。';
        err.classList.add('show');
        return;
      }
      if (!date || date > D.todayISO()) {
        err.textContent = '请选择不晚于今天的日期。';
        err.classList.add('show');
        return;
      }
      var res = D.addWeight(A.state, value, date);
      if (res.error) {
        err.textContent = res.error;
        err.classList.add('show');
        return;
      }
      var badges = D.checkBadges(A.state);
      A.closeModal();
      A.commit({ keepScroll: true });
      A.toast('体重已更新为 ' + res.weight + ' kg');
      A.celebrate(badges);
    });
  };

  A.actions.recordBCS = function (dataset) {
    var state = dataset.state;
    if (!BCS_META[state]) return;
    var res = D.recordBCS(A.state, state);
    var badges = D.checkBadges(A.state);
    A.commit({ keepScroll: true });
    A.toast('已记录体况：' + BCS_META[state].label);
    A.celebrate(badges);
  };

  /* ---------------- 记录筛选、详情、删除 ---------------- */
  A.actions.setRecordFilter = function (dataset) {
    recordFilter = dataset.filter || '全部';
    A.commit({ keepScroll: true });
  };

  A.actions.openRecordDetail = function (dataset) {
    var record = findRecord(dataset.kind, Number(dataset.id));
    if (!record) return;
    var rows = [];
    if (record.kind === 'weight') {
      rows.push(['记录类型', '体重记录']);
      rows.push(['日期', record.date]);
      rows.push(['体重', record.detail.weight + ' kg']);
    } else {
      rows.push(['记录类型', record.type]);
      rows.push(['日期', record.date]);
      var d = record.detail || {};
      if (record.type === '疫苗') {
        rows.push(['针次', d.dose || '未填写']);
        rows.push(['品牌', d.brand || '未填写']);
      } else if (record.type === '驱虫') {
        rows.push(['驱虫范围', d.deworm_type || '未填写']);
      } else if (record.type === '异常行为') {
        rows.push(['症状', (d.symptoms || []).join('、') || '未选择']);
        rows.push(['描述', d.note || '无']);
      } else if (record.type === '每日检查') {
        rows.push(['结果', d.result === 'abnormal' ? '发现异常' : '一切正常']);
        rows.push(['备注', d.note || '无']);
      } else {
        rows.push(['备注', d.note || '无']);
      }
      if (record.high_risk) rows.push(['风险标记', '高风险 · ' + (record.risk_keyword || '')]);
    }
    var root = A.openModal({
      title: '记录详情',
      subtitle: record.date + ' · ' + (record.kind === 'weight' ? '体重记录' : record.type),
      size: 'sm',
      body: '<dl class="detail-grid single">' + rows.map(function (r) {
        return '<div><dt>' + esc(r[0]) + '</dt><dd>' + esc(r[1]) + '</dd></div>';
      }).join('') + '</dl>' +
        '<div class="notice notice-info" style="margin-top:16px">' + A.icon('alert') + '<span>这是演示记录，不包含真实用户数据。</span></div>',
      footer: '<button type="button" class="btn btn-secondary" data-detail-delete>删除这条记录</button>' +
        '<button type="button" class="btn btn-primary" data-modal-close>关闭</button>'
    });
    root.querySelector('[data-detail-delete]').addEventListener('click', function () {
      A.closeModal();
      A.actions.deleteRecord({ kind: record.kind, id: String(record.id) });
    });
  };

  function findRecord(kind, id) {
    if (kind === 'weight') {
      var w = A.state.weightLogs.filter(function (x) { return x.id === id; })[0];
      return w ? { id: w.id, kind: 'weight', type: '体重', date: w.date, detail: { weight: w.weight } } : null;
    }
    var e = A.state.events.filter(function (x) { return x.id === id; })[0];
    return e ? { id: e.id, kind: 'event', type: e.type, date: e.date, detail: e.detail, high_risk: e.high_risk, risk_keyword: e.risk_keyword } : null;
  }

  A.actions.deleteRecord = function (dataset) {
    var kind = dataset.kind;
    var id = Number(dataset.id);
    var record = findRecord(kind, id);
    if (!record) return;
    A.confirm({
      title: '删除演示记录',
      message: '确定删除 ' + record.date + ' 的「' + (kind === 'weight' ? '体重记录' : record.type) + '」吗？',
      note: '删除后趋势、提醒与勋章进度会重新计算，但已解锁勋章不会回收。',
      confirmText: '删除',
      danger: true
    }).then(function (ok) {
      if (!ok) return;
      if (kind === 'weight') {
        A.state.weightLogs = A.state.weightLogs.filter(function (x) { return x.id !== id; });
        var latest = D.latestWeight(A.state);
        if (latest) A.state.pet.weight = String(latest.weight);
      } else {
        A.state.events = A.state.events.filter(function (x) { return x.id !== id; });
        if (record.type === '洗澡澡') {
          var lastBath = A.state.events.filter(function (x) { return x.type === '洗澡澡'; })
            .sort(function (a, b) { return a.date < b.date ? 1 : -1; })[0];
          A.state.pet.lastBathDate = lastBath ? lastBath.date : null;
        }
      }
      A.closeModal();
      A.commit({ keepScroll: true });
      A.toast('记录已删除');
    });
  };

  /* ---------------- 趋势页 ---------------- */
  function renderTrendKPIs(state) {
    var stats = D.weightStats(state.weightLogs, trendRange);
    if (!stats) {
      return '<div class="kpi-grid">' + A.emptyState('⚖️', '这个区间没有体重记录', '切换更长时间范围，或新增一条体重记录。') + '</div>';
    }
    var changeClass = stats.change > 0 ? 'text-amber' : stats.change < 0 ? 'text-green' : '';
    return '<div class="kpi-grid">' +
      '<div class="kpi"><span>最新体重</span><b>' + stats.latest + '<small> kg</small></b><em>' + esc(stats.logs[stats.logs.length - 1].date) + '</em></div>' +
      '<div class="kpi"><span>区间变化</span><b class="' + changeClass + '">' + (stats.change > 0 ? '+' : '') + stats.change + '<small> kg</small></b><em>较 ' + stats.logs[0].date + '</em></div>' +
      '<div class="kpi"><span>平均体重</span><b>' + stats.avg + '<small> kg</small></b><em>' + stats.logs.length + ' 次记录</em></div>' +
      '<div class="kpi"><span>波动范围</span><b>' + stats.min + '–' + stats.max + '<small> kg</small></b><em>最低 / 最高</em></div>' +
    '</div>';
  }

  function renderTrendChart(state) {
    var stats = D.weightStats(state.weightLogs, trendRange);
    var range = D.idealRange(state.pet.breed);
    var chart = stats
      ? A.weightChart(stats.logs, range, { rangeStart: D.daysAgoISO(trendRange), height: 300 })
      : '<div class="chart-empty">该区间暂无记录，请切换时间范围或新增体重。</div>';
    return '<div class="card trend-chart-card">' +
      '<div class="card-head"><div class="card-head-main">' +
        '<div class="card-title">' + A.icon('chart') + '体重变化曲线</div>' +
        '<div class="card-sub">' + esc(state.pet.breed) + (range ? ' · 绿色区间为品种参考 ' + range[0] + '–' + range[1] + ' kg' : '') + '</div>' +
      '</div>' +
      '<div class="segmented">' + [30, 90, 180, 365].map(function (d) {
        return '<button type="button" class="' + (trendRange === d ? 'active' : '') + '" data-action="setTrendRange" data-days="' + d + '">' + d + ' 天</button>';
      }).join('') + '</div></div>' +
      chart +
      '<div class="chart-legend"><span><i class="legend-line"></i>体重曲线</span>' + (range ? '<span><i class="legend-band"></i>理想体重区间</span>' : '') + '<span class="muted">悬停数据点查看日期与数值</span></div>' +
    '</div>';
  }

  function renderBCS(state) {
    var latest = D.latestBCS(state);
    var meta = latest ? BCS_META[latest.state] : null;
    var history = state.bcsLogs.slice().sort(function (a, b) { return a.date < b.date ? 1 : -1; }).slice(0, 4);
    return '<div class="card">' +
      '<div class="card-head"><div class="card-head-main">' +
        '<div class="card-title">' + A.icon('heart') + 'BCS 体况评分</div>' +
        '<div class="card-sub">通过触摸肋骨与观察腰线判断</div>' +
      '</div>' + (latest ? '<span class="chip ' + (latest.state === 'ideal' ? 'chip-green' : latest.state === 'heavy' ? 'chip-red' : 'chip-amber') + '">' + meta.label + '</span>' : '') + '</div>' +
      (latest
        ? '<div class="bcs-current ' + meta.cls + '"><b>' + meta.label + '</b><p>' + meta.desc + '</p><em>最近评估：' + latest.date + '</em></div>'
        : '<div class="notice notice-info">' + A.icon('alert') + '<span>还没有 BCS 评估记录，选择下方状态即可记录今天的判断。</span></div>') +
      '<div class="bcs-options">' +
        Object.keys(BCS_META).map(function (key) {
          var m = BCS_META[key];
          return '<button type="button" class="bcs-option ' + m.cls + (latest && latest.state === key ? ' active' : '') + '" data-action="recordBCS" data-state="' + key + '">' +
            '<span class="bcs-option-title">' + m.label + '</span><em>' + (key === 'thin' ? '摸得到明显肋骨' : key === 'ideal' ? '肋骨可触及不可见' : '肋骨不易触及') + '</em></button>';
        }).join('') +
      '</div>' +
      '<div class="bcs-history"><span class="info-label">评估历史</span>' +
        (history.length
          ? '<ul class="history-list">' + history.map(function (h) {
            var m = BCS_META[h.state];
            return '<li><span>' + h.date + '</span><b class="' + m.cls + '-text">' + m.label + '</b></li>';
          }).join('') + '</ul>'
          : '<p class="small muted">暂无历史</p>') +
      '</div>' +
      '<div class="notice notice-info" style="margin-top:14px">' + A.icon('alert') + '<span>BCS 是主观体况筛查，结果为演示判断，不替代兽医体检。</span></div>' +
    '</div>';
  }

  function renderInsight(state) {
    var stats = D.weightStats(state.weightLogs, trendRange);
    var range = D.idealRange(state.pet.breed);
    var current = D.parseWeight(state.pet.weight);
    var lines = [];
    if (stats) {
      if (stats.change > 0.3) lines.push('近 ' + trendRange + ' 天体重上升 ' + stats.change + ' kg，建议复核每日喂食量与零食占比。');
      else if (stats.change < -0.3) lines.push('近 ' + trendRange + ' 天体重下降 ' + Math.abs(stats.change) + ' kg，建议关注食欲与消化情况。');
      else lines.push('近 ' + trendRange + ' 天体重整体平稳，继续保持规律记录。');
    }
    if (range && current !== null) {
      if (current < range[0]) lines.push('当前体重低于该品种参考下限 ' + range[0] + ' kg，建议结合 BCS 与兽医意见评估。');
      else if (current > range[1]) lines.push('当前体重高于该品种参考上限 ' + range[1] + ' kg，建议关注体况与关节负担。');
      else lines.push('当前体重处于该品种参考范围 ' + range[0] + '–' + range[1] + ' kg 内。');
    }
    return '<div class="card">' +
      '<div class="card-head"><div class="card-head-main">' +
        '<div class="card-title">' + A.icon('sparkles') + '趋势解读</div>' +
        '<div class="card-sub">规则化解读，仅作日常参考</div>' +
      '</div></div>' +
      '<ul class="plain-list">' + lines.map(function (l) { return '<li>' + esc(l) + '</li>'; }).join('') + '</ul>' +
      '<div class="card-actions">' +
        '<button type="button" class="btn btn-primary btn-sm" data-action="openWeightModal">' + A.icon('plus') + '新增体重</button>' +
        '<button type="button" class="btn btn-secondary btn-sm" data-nav="records">查看全部记录</button>' +
      '</div>' +
    '</div>';
  }

  function renderWeightHistory(state) {
    var logs = state.weightLogs.slice().sort(function (a, b) { return a.date < b.date ? 1 : -1; }).slice(0, 6);
    return '<div class="card">' +
      '<div class="card-head"><div class="card-head-main">' +
        '<div class="card-title">' + A.icon('scale') + '最近体重记录</div>' +
        '<div class="card-sub">最多展示最近 6 条</div>' +
      '</div></div>' +
      '<table class="data-table"><thead><tr><th>日期</th><th>体重</th><th>较上次</th><th></th></tr></thead><tbody>' +
        logs.map(function (l, i) {
          var prev = logs[i + 1];
          var diff = prev ? Math.round((l.weight - prev.weight) * 10) / 10 : null;
          return '<tr><td>' + l.date + '</td><td><strong>' + l.weight + ' kg</strong></td>' +
            '<td>' + (diff === null ? '—' : (diff > 0 ? '+' : '') + diff + ' kg') + '</td>' +
            '<td class="row-actions"><button type="button" class="btn btn-ghost btn-sm" data-action="openRecordDetail" data-kind="weight" data-id="' + l.id + '">查看</button></td></tr>';
        }).join('') +
      '</tbody></table>' +
      (logs.length ? '' : '<p class="small muted" style="padding:12px 4px">暂无体重记录。</p>') +
    '</div>';
  }

  function renderTrends(state) {
    return '<div class="page-intro">' +
      '<div><h2>体重与体况趋势</h2><p>观察长期变化，比单次数字更有参考价值。</p></div>' +
      '<button type="button" class="btn btn-primary btn-sm" data-action="openWeightModal">' + A.icon('plus') + '记录体重</button>' +
    '</div>' +
    renderTrendKPIs(state) +
    '<div class="trend-grid">' +
      '<div class="trend-col">' + renderTrendChart(state) + renderWeightHistory(state) + '</div>' +
      '<div class="trend-col">' + renderBCS(state) + renderInsight(state) + '</div>' +
    '</div>';
  }

  A.actions.setTrendRange = function (dataset) {
    trendRange = Number(dataset.days) || 90;
    A.commit({ keepScroll: true });
  };

  A.registerPage('records', {
    title: '健康记录',
    subtitle: '疫苗、驱虫、洗澡与异常观察',
    render: renderRecords
  });

  A.registerPage('trends', {
    title: '健康趋势',
    subtitle: function (state) { return state.pet.name + ' 的体重变化与体况评分'; },
    render: renderTrends
  });
})();
