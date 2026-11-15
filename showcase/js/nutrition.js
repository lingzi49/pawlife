/* PawLife 展示版 — 伙食搭配
 * 计算逻辑移植自 pawlife_web.py：_calc_rer / _calc_daily_grams / _filter_allergen_foods
 */
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

  function renderSuspended(state) {
    return '<div class="card">' +
      '<div class="supp-suspended">🚨 ' +
        '因您最近记录了高风险症状，今日饮食建议已暂停。请优先联系兽医，确认宠物状况稳定后可恢复建议。' +
      '</div>' +
      '<div class="suspended-actions">' +
        '<button type="button" class="btn btn-secondary btn-sm" data-nav="record">查看记录</button>' +
        '<button type="button" class="btn btn-primary btn-sm" data-action="restoreNutrition">✅ 已联系兽医，恢复建议</button>' +
      '</div>' +
    '</div>';
  }

  function renderEmpty() {
    return '<div class="card">' +
      '<div class="diet-empty">🐾 主人，我的档案里体重或生日还没填完整，补齐后我才知道每天该吃多少哦～</div>' +
      '<div style="text-align:center;margin-top:12px;">' +
        '<button type="button" class="btn btn-primary btn-sm" data-action="openProfileModal">完善档案</button>' +
      '</div>' +
    '</div>';
  }

  function heartfelt(state, p) {
    var gender = state.pet.gender === 'male' ? '小王子' : '小公主';
    if (p.plan.stage === '幼犬') return '适合活泼的' + gender + '～ 照着这个喂我，我会长得壮壮、毛亮亮哦！每天 ' + p.meals + ' 顿饭，陪我一起长大～🐾';
    if (p.plan.stage === '老年犬') return '我的牙口不如从前啦，记得把食材切碎蒸软哦～每天 ' + p.meals + ' 顿饭，和你在一起的每一天都是好时光～🐾';
    return '适合活泼的' + gender + '～ 照着这个喂我，我会长得壮壮、毛亮亮哦！每天陪我一起吃饭，是我最开心的时光～🐾';
  }

  function bcsNote(state) {
    var bcs = D.latestBCS(state);
    if (!bcs) return '';
    if (bcs.state === 'heavy') return '<div class="diet-note warm">⚖️ 当前体态评估为<b>偏胖</b>，建议适当控制食量、增加运动量。</div>';
    if (bcs.state === 'thin') return '<div class="diet-note warm">⚖️ 当前体态评估为<b>偏瘦</b>，建议适当增加优质蛋白摄入。</div>';
    return '<div class="diet-note good">✅ 当前体态理想，继续保持当前饮食节奏～</div>';
  }

  function renderRecipe(state, p) {
    var date = new Date();
    var dateStr = date.getFullYear() + '年' + (date.getMonth() + 1) + '月' + date.getDate() + '日';
    var items = p.items.map(function (it) {
      return '<div class="recipe-item">' +
        '<span class="recipe-item-name">' + it.emoji + ' ' + esc(it.name) + '</span>' +
        '<span class="recipe-item-dots"></span>' +
        '<span class="recipe-item-weight">' + it.grams + 'g</span>' +
      '</div>';
    }).join('');
    var allergy = state.pet.allergies
      ? '<div class="diet-note alert">⚠️ 已避开过敏源（' + esc(state.pet.allergies) + '），并替换为安全食材。</div>'
      : '';
    var disease = state.pet.diseases
      ? '<div class="diet-note muted">⚕️ 档案记录有「' + esc(state.pet.diseases) + '」，饮食方案请在兽医指导下调整。</div>'
      : '';
    var plan = p.plan;

    return '<div class="card diet-card">' +
      '<div class="recipe-wrap">' +
        '<div class="recipe-main">' +
          '<div class="recipe-deco"><span class="recipe-deco-line"></span>' +
            '<span class="recipe-deco-title">🐶 ' + esc(state.pet.name) + '的一餐食谱</span>' +
            '<span class="recipe-deco-line"></span></div>' +
          '<div class="recipe-date">📅 ' + dateStr + ' · 每天 ' + p.meals + ' 餐</div>' +
          '<div class="recipe-meal-name">' + esc(p.mealName) + '</div>' +
          '<div class="recipe-items">' + items + '</div>' +
          '<div class="recipe-total"><span class="recipe-total-label">⚖️ 本餐总重</span><span class="recipe-total-weight">' + p.totalWeight + 'g</span></div>' +
          '<div class="recipe-nutrition">' +
            '<span class="nut-tag nut-tag-protein">🥩 蛋白质 ' + p.totalProtein + 'g</span>' +
            '<span class="nut-tag nut-tag-fat">🧈 脂肪 ' + p.totalFat + 'g</span>' +
            '<span class="nut-tag nut-tag-carbs">🍚 碳水 ' + p.totalCarbs + 'g</span>' +
          '</div>' +
          '<div class="recipe-cooking-tip">💡 所有食材切碎蒸熟，不放盐哦～</div>' +
          allergy + disease + bcsNote(state) +
          '<div class="diet-actions">' +
            '<button type="button" class="btn btn-secondary btn-sm" data-action="openWeightModal">⚖️ 更新体重重新计算</button>' +
          '</div>' +
          '<details class="diet-basis">' +
            '<summary>📐 为什么是 ' + p.totalWeight + 'g？点击查看计算依据</summary>' +
            '<div class="diet-basis-detail">' +
              '<div class="diet-basis-row"><span>体重</span><span>' + plan.weightKg + ' kg</span></div>' +
              '<div class="diet-basis-row"><span>年龄阶段</span><span>' + esc(plan.stage) + '</span></div>' +
              '<div class="diet-basis-row"><span>绝育情况</span><span>' + esc(state.pet.neutered || '未知') + '</span></div>' +
              '<div class="diet-basis-row"><span>活动水平</span><span>标准（系数 ×' + plan.coefficient + '）</span></div>' +
              '<div class="diet-basis-row"><span>RER（静息能耗）</span><span>' + plan.rer + ' kcal</span></div>' +
              '<div class="diet-basis-row"><span>DER（每日能耗）</span><span>' + plan.der + ' kcal</span></div>' +
              '<div class="diet-basis-row"><span>每日总喂食量</span><span>' + plan.totalG + ' g（1.5 kcal/g 估算）</span></div>' +
            '</div>' +
          '</details>' +
          '<div class="diet-disclaimer">📋 此饮食建议基于档案信息自动生成，仅供参考，不能替代兽医的专业诊断。如有健康问题请立即联系兽医。</div>' +
        '</div>' +

        '<div class="recipe-side">' +
          '<div class="side-section">' +
            '<div class="side-label">🔄 替换选择</div>' +
            '<div class="side-text">🥩 ' + esc(p.proteinOptions) + '</div>' +
            '<div class="side-text">🥬 ' + esc(p.veggieOptions) + '</div>' +
            '<div class="side-text">🍚 ' + esc(p.carbOptions) + '</div>' +
          '</div>' +
          '<div class="side-section">' +
            '<div class="side-label">🐟 鱼油补充</div>' +
            '<div class="side-text">' + esc(p.fishOil) + '</div>' +
          '</div>' +
          '<div class="side-section">' +
            '<div class="side-label">💡 小贴士</div>' +
            (p.breedTip ? '<div class="side-text breed-tip">🐕 ' + esc(p.breedTip) + '</div>' : '') +
            '<div class="side-text">' + esc(state.pet.allergies
              ? '已避开记录中的过敏源，请优先使用当前安全食材；更换蛋白源时建议逐步过渡并观察 3-5 天。'
              : p.foods.tip) + '</div>' +
          '</div>' +
          (p.hypoglycemiaNote ? '<div class="side-section"><div class="notice notice-warn">' + esc(p.hypoglycemiaNote) + '</div></div>' : '') +
          '<div class="side-heartfelt">💬 ' + esc(heartfelt(state, p)) + '</div>' +
        '</div>' +
      '</div>' +
    '</div>';
  }

  function renderDiet(state) {
    var header = subHeader('🍖 ' + esc(state.pet.name) + '的伙食搭配');
    if (isSuspended(state)) return '<div class="sub-page">' + header + renderSuspended(state) + '</div>';
    var p = D.dietPlan(state.pet);
    if (!p) return '<div class="sub-page">' + header + renderEmpty() + '</div>';
    return '<div class="sub-page">' + header + renderRecipe(state, p) + '</div>';
  }

  A.actions.restoreNutrition = function () {
    A.state.suspendedUntil = null;
    A.commit({ keepScroll: true });
    A.toast('已恢复营养建议展示，请继续观察宠物状态');
  };

  A.registerPage('diet', {
    title: '伙食搭配',
    render: renderDiet
  });
})();
