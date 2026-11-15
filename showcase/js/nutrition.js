/* PawLife 展示版 — 营养管理
 * 计算逻辑移植自 pawlife_web.py：_calc_rer / _calc_daily_grams / _filter_allergen_foods
 */
(function () {
  'use strict';

  var A = window.PawApp;
  var D = window.PawData;
  var esc = A.esc;

  function isSuspended(state) {
    return !!(state.suspendedUntil && state.suspendedUntil >= D.todayISO());
  }

  function renderSuspended(state) {
    return '<div class="card suspended-card">' +
      '<div class="suspended-icon">🚨</div>' +
      '<div class="suspended-main">' +
        '<h2>今日营养与补充建议已暂停</h2>' +
        '<p>因为最近记录了高风险症状，系统暂停给出饮食建议。请优先联系兽医确认宠物状况，稳定后可手动恢复展示。</p>' +
        '<div class="suspended-actions">' +
          '<button type="button" class="btn btn-secondary" data-nav="records">查看风险记录</button>' +
          '<button type="button" class="btn btn-primary" data-action="restoreNutrition">已联系兽医，恢复建议</button>' +
        '</div>' +
      '</div>' +
    '</div>' +
    '<div class="notice notice-danger" style="margin-top:16px">' + A.icon('alert') +
      '<span>如果 ' + esc(state.pet.name) + ' 出现持续呕吐、便血、抽搐、呼吸困难、意识不清等情况，请立即就医。展示版不会执行任何医疗处置。</span>' +
    '</div>';
  }

  function renderEmpty() {
    return '<div class="card">' + A.emptyState('⚖️', '还缺少体重信息',
      '营养计算需要先填写体重与生日，完善档案后即可生成每日能量与食谱参考。',
      '<button type="button" class="btn btn-primary" data-action="openProfileModal">完善档案</button>') + '</div>';
  }

  function renderEnergy(p) {
    var plan = p.plan;
    return '<div class="card">' +
      '<div class="card-head"><div class="card-head-main">' +
        '<div class="card-title">' + A.icon('chart') + '每日能量计算</div>' +
        '<div class="card-sub">依据档案体重、年龄阶段与绝育状态</div>' +
      '</div><span class="chip chip-brand">' + esc(plan.stage) + ' · ' + esc(plan.size) + '</span></div>' +
      '<div class="energy-flow">' +
        '<div class="energy-step">' +
          '<span class="energy-label">静息能量 RER</span>' +
          '<b>' + plan.rer + '<small> kcal</small></b>' +
          '<em>' + (plan.weightKg >= 2 && plan.weightKg <= 45 ? '30 × ' + plan.weightKg + ' + 70' : '70 × ' + plan.weightKg + '^0.75') + '</em>' +
        '</div>' +
        '<span class="energy-arrow">→</span>' +
        '<div class="energy-step">' +
          '<span class="energy-label">活动 / 生理系数</span>' +
          '<b>×' + plan.coefficient + '</b>' +
          '<em>' + (plan.stage === '幼犬' ? '幼犬生长期' : p.planStageNote || (A.state.pet.neutered === '是' ? '已绝育成犬' : '未绝育成犬')) + '</em>' +
        '</div>' +
        '<span class="energy-arrow">→</span>' +
        '<div class="energy-step">' +
          '<span class="energy-label">性别系数</span>' +
          '<b>×' + plan.genderCoefficient.toFixed(1) + '</b>' +
          '<em>' + (A.state.pet.gender === 'male' ? '公犬基础代谢略高' : '母犬') + '</em>' +
        '</div>' +
        '<span class="energy-arrow">→</span>' +
        '<div class="energy-step highlight">' +
          '<span class="energy-label">每日能量 DER</span>' +
          '<b>' + plan.der + '<small> kcal</small></b>' +
          '<em>' + plan.rer + ' × ' + plan.coefficient + ' × ' + plan.genderCoefficient.toFixed(1) + '</em>' +
        '</div>' +
      '</div>' +
      '<div class="energy-result">' +
        '<div class="energy-kcal"><span>每日喂食量参考</span><b>' + plan.totalG + '<small> g</small></b><em>按 1.5 kcal/g 熟自制能量密度估算</em></div>' +
        '<div class="energy-split">' +
          '<span>蛋白 ' + plan.proteinG + 'g</span><span>碳水 ' + plan.carbG + 'g</span><span>蔬果 ' + plan.veggieG + 'g</span>' +
        '</div>' +
      '</div>' +
      '<p class="formula-note">公式说明：RER 在 2–45kg 区间使用 30×体重+70，其余区间使用 70×体重^0.75；幼犬系数 2.5，已绝育成犬 1.6，未绝育成犬 1.8；公犬再乘 1.1。计算为日常参考值，不代表临床处方。</p>' +
    '</div>';
  }

  function renderMacro(p) {
    var plan = p.plan;
    var macros = [
      { name: '优质蛋白', pct: 55, grams: plan.proteinG, color: 'var(--brand)' },
      { name: '碳水', pct: 25, grams: plan.carbG, color: '#C9A15E' },
      { name: '蔬果纤维', pct: 15, grams: plan.veggieG, color: 'var(--green)' },
      { name: '脂肪', pct: 5, grams: '由肉类与鱼油提供', color: '#B08A6A' }
    ];
    return '<div class="card">' +
      '<div class="card-head"><div class="card-head-main">' +
        '<div class="card-title">' + A.icon('bowl') + '每日配比</div>' +
        '<div class="card-sub">蛋白 55% · 碳水 25% · 蔬果 15% · 脂肪 5%</div>' +
      '</div></div>' +
      '<div class="macro-list">' + macros.map(function (m) {
        return '<div class="macro-row">' +
          '<div class="macro-top"><span>' + m.name + '</span><b>' + (typeof m.grams === 'number' ? m.grams + ' g' : m.grams) + '</b></div>' +
          '<div class="macro-bar"><i style="width:' + m.pct + '%;background:' + m.color + '"></i></div>' +
          '<span class="macro-pct">' + m.pct + '%</span>' +
        '</div>';
      }).join('') + '</div>' +
    '</div>';
  }

  function renderMeals(state, p) {
    var items = p.items.map(function (it) {
      return '<div class="meal-item">' +
        '<span class="meal-emoji">' + it.emoji + '</span>' +
        '<span class="meal-name">' + esc(it.name) + '</span>' +
        '<span class="meal-grams">' + it.grams + ' g</span>' +
        '<span class="meal-nut">蛋白 ' + it.protein + 'g · 脂肪 ' + it.fat + 'g · 碳水 ' + it.carbs + 'g</span>' +
      '</div>';
    }).join('');
    var recipeIndex = state.ui.recipeIndex || 0;
    var recipeList = p.foods.daily.filter(function (r) {
      return !D.allergenMatches(r, state.pet.allergies || '');
    });
    var fallbackRecipe = p.items.map(function (i) { return i.name; }).join(' + ');
    if (recipeList.indexOf(fallbackRecipe) === -1) recipeList.unshift(fallbackRecipe);
    var recipes = recipeList.map(function (r, i) {
      return '<li class="' + (i === recipeIndex % recipeList.length ? 'active' : '') + '"><span class="recipe-dot"></span>' + esc(r) + '</li>';
    }).join('');
    var mealTip = p.foods.tip;
    if (state.pet.allergies) {
      mealTip = '已避开记录中的过敏源，请优先使用当前安全食材；更换蛋白源时建议逐步过渡并观察 3-5 天。';
    }
    return '<div class="card">' +
      '<div class="card-head"><div class="card-head-main">' +
        '<div class="card-title">' + A.icon('bowl') + '今日食谱参考</div>' +
        '<div class="card-sub">每天 ' + p.meals + ' 餐 · 每餐约 ' + p.totalWeight + ' g · ' + esc(p.mealName) + ' · 已过滤过敏源</div>' +
      '</div><button type="button" class="btn btn-soft btn-sm" data-action="rotateRecipe">换一份搭配</button></div>' +
      '<div class="meal-list">' + items + '</div>' +
      '<div class="meal-totals">' +
        '<div><span>每餐总重</span><b>' + p.totalWeight + ' g</b></div>' +
        '<div><span>蛋白</span><b>' + p.totalProtein + ' g</b></div>' +
        '<div><span>脂肪</span><b>' + p.totalFat + ' g</b></div>' +
        '<div><span>碳水</span><b>' + p.totalCarbs + ' g</b></div>' +
      '</div>' +
      '<div class="recipe-block">' +
        '<span class="info-label">搭配灵感</span>' +
        '<ul class="recipe-list">' + recipes + '</ul>' +
      '</div>' +
      '<div class="notice notice-info">' + A.icon('alert') + '<span>' + esc(mealTip) + '</span></div>' +
    '</div>';
  }

  function renderAllergy(state, p) {
    var allergies = (state.pet.allergies || '').split(/[,，]/).map(function (s) { return s.trim(); }).filter(Boolean);
    return '<div class="card">' +
      '<div class="card-head"><div class="card-head-main">' +
        '<div class="card-title">' + A.icon('shield') + '过敏源过滤</div>' +
        '<div class="card-sub">主食谱与备选食材会自动避开已记录过敏源</div>' +
      '</div><button type="button" class="btn btn-ghost btn-sm" data-action="openProfileModal">' + A.icon('edit') + '编辑过敏源</button></div>' +
      '<div class="tag-row" style="margin-bottom:14px">' +
        (allergies.length ? allergies.map(function (a) { return '<span class="chip chip-red">' + esc(a) + '</span>'; }).join('') : '<span class="chip chip-muted">未记录过敏源</span>') +
      '</div>' +
      (p.allergyNote ? '<div class="notice notice-warn" style="margin-bottom:14px">' + A.icon('alert') + '<span>' + esc(p.allergyNote) + '</span></div>' : '') +
      '<div class="option-grid">' +
        '<div class="option-block"><span class="info-label">蛋白备选</span><p>' + esc(p.proteinOptions) + '</p></div>' +
        '<div class="option-block"><span class="info-label">碳水备选</span><p>' + esc(p.carbOptions) + '</p></div>' +
        '<div class="option-block"><span class="info-label">蔬果备选</span><p>' + esc(p.veggieOptions) + '</p></div>' +
      '</div>' +
    '</div>';
  }

  function renderTips(state, p) {
    var notes = [];
    if (p.breedTip) notes.push({ icon: '🐕', title: '品种专属提示', text: p.breedTip });
    notes.push({ icon: '🐟', title: '鱼油补充参考', text: p.fishOil + '。添加前请确认狗狗没有鱼类过敏。' });
    if (p.hypoglycemiaNote) notes.push({ icon: '⚠️', title: '低血糖风险提示', text: p.hypoglycemiaNote });
    if (state.pet.diseases) notes.push({ icon: '⚕️', title: '疾病状态提示', text: '档案中记录有「' + state.pet.diseases + '」，饮食方案仅供兽医参考，请在兽医指导下调整。' });
    return '<div class="card">' +
      '<div class="card-head"><div class="card-head-main">' +
        '<div class="card-title">' + A.icon('heart') + '个性化提示</div>' +
        '<div class="card-sub">基于品种、年龄和档案信息</div>' +
      '</div></div>' +
      '<div class="tip-list">' + notes.map(function (n) {
        return '<div class="tip-item"><span class="tip-item-ico">' + n.icon + '</span><div><b>' + n.title + '</b><p>' + esc(n.text) + '</p></div></div>';
      }).join('') + '</div>' +
      '<div class="notice notice-info">' + A.icon('alert') + '<span>营养结果是规则引擎的日常参考，不是兽医处方。若狗狗有疾病、怀孕、哺乳或特殊用药，请先咨询兽医。</span></div>' +
    '</div>';
  }

  function renderNutrition(state) {
    var pet = state.pet;
    var header = '<div class="page-intro">' +
      '<div><h2>为 ' + esc(pet.name) + ' 计算的每日营养参考</h2>' +
      '<p>基于当前档案：' + esc(pet.breed) + ' · ' + esc(D.ageText(pet.birthday)) + ' · ' + esc(pet.weight) + 'kg · ' + (pet.neutered === '是' ? '已绝育' : '未绝育/未知') + '</p></div>' +
      '<button type="button" class="btn btn-secondary btn-sm" data-nav="profile">' + A.icon('edit') + '调整档案</button>' +
    '</div>';

    if (isSuspended(state)) return header + renderSuspended(state);
    var p = D.dietPlan(pet);
    if (!p) return header + renderEmpty();

    return header +
      '<div class="nutrition-grid">' +
        '<div class="nutrition-col">' +
          renderEnergy(p) +
          renderMeals(state, p) +
        '</div>' +
        '<div class="nutrition-col">' +
          renderMacro(p) +
          renderAllergy(state, p) +
          renderTips(state, p) +
        '</div>' +
      '</div>';
  }

  A.actions.rotateRecipe = function () {
    var idx = (A.state.ui.recipeIndex || 0);
    A.state.ui.recipeIndex = (idx + 1) % 12;
    A.commit({ keepScroll: true });
    A.toast('已切换一份搭配灵感');
  };

  A.actions.restoreNutrition = function () {
    A.state.suspendedUntil = null;
    A.commit({ keepScroll: true });
    A.toast('已恢复营养建议展示，请继续观察宠物状态');
  };

  A.registerPage('nutrition', {
    title: '营养管理',
    subtitle: function (state) { return state.pet.name + ' 的每日能量与食谱参考'; },
    render: renderNutrition
  });
})();
