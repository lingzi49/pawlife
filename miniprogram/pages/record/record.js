// 记录事件页面
const api = require('../../utils/api');
const util = require('../../utils/util');

Page({
  data: {
    hasDog: false,
    dog: null,
    eventTypes: ['💉 疫苗', '💊 驱虫', '💕 发情', '⚠️ 异常行为', '🛁 洗澡澡'],
    eventTypeIndex: 0,
    eventType: '疫苗',
    eventSubtitle: '记录疫苗、驱虫、发情或异常行为，我会立刻给你反馈',
    eventDate: '',
    today: '',
    // 动态表单字段
    dose: '', brand: '',
    dewormTypes: ['体内', '体外', '内外同驱'],
    dewormTypeIndex: 0,
    note: '',
    symptomOptions: ['呕吐', '腹泻', '食欲不振', '精神萎靡', '跛行', '抓痒', '咳嗽', '打喷嚏', '发热', '抽搐', '便血', '吐血', '呼吸困难', '昏厥', '其他'],
    symptoms: [],
    // 状态
    submitting: false,
    reaction: '',
    // 高危警告
    showRiskWarning: false,
    riskKeyword: '',
    pendingSubmit: null,
  },

  onShow() {
    const now = new Date();
    const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
    this.setData({ today, eventDate: today });
    this.loadDog();
  },

  async loadDog() {
    try {
      const dog = await api.getDog();
      const subtitle = dog.gender === 'male'
        ? `${dog.name} 小王子，记录你的每一个重要时刻～`
        : dog.gender === 'female'
        ? `${dog.name} 小公主，记录你的每一个重要时刻～`
        : `${dog.name}，记录你的每一个重要时刻～`;
      this.setData({ hasDog: true, dog, eventSubtitle: subtitle });
      // 隐藏公犬的发情选项
      if (dog.gender === 'male') {
        const types = this.data.eventTypes.filter(t => t !== '💕 发情');
        this.setData({ eventTypes: types });
      }
    } catch (e) {
      this.setData({ hasDog: false });
    }
  },

  onTypeChange(e) {
    const idx = parseInt(e.detail.value);
    // 从 eventTypes 数组提取事件类型名（去掉 emoji 前缀）
    const selectedLabel = this.data.eventTypes[idx];
    const type = selectedLabel.replace(/^[^一-龥]+/, '');
    this.setData({ eventTypeIndex: idx, eventType: type, reaction: '' });
  },
  onDateChange(e) { this.setData({ eventDate: e.detail.value }); },
  onDoseInput(e) { this.setData({ dose: e.detail.value }); },
  onBrandInput(e) { this.setData({ brand: e.detail.value }); },
  onNoteInput(e) { this.setData({ note: e.detail.value }); },
  onDewormTypeChange(e) { this.setData({ dewormTypeIndex: parseInt(e.detail.value) }); },

  onSymptomsChange(e) {
    this.setData({ symptoms: e.detail.value });
  },

  // 提交事件
  submitEvent() {
    const { eventType, eventDate, today, dog } = this.data;
    if (new Date(eventDate) > new Date()) {
      wx.showToast({ title: '事件日期不能是未来的日子哦～', icon: 'none' });
      return;
    }
    if (!dog) {
      wx.showToast({ title: '主人，请先创建狗狗档案～', icon: 'none' });
      return;
    }

    // 收集详情
    let detail = {};
    if (eventType === '疫苗') {
      detail.dose = this.data.dose.trim();
      detail.brand = this.data.brand.trim();
    } else if (eventType === '驱虫') {
      detail.brand = this.data.brand.trim();
      detail.deworm_type = this.data.dewormTypes[this.data.dewormTypeIndex];
    } else if (eventType === '发情') {
      detail.note = this.data.note.trim();
    } else if (eventType === '异常行为') {
      detail.symptoms = [...this.data.symptoms];
      // 高风险检查
      const symptomText = detail.symptoms.join('，');
      const matched = util.checkHighRisk(symptomText);
      if (matched) {
        this.setData({
          showRiskWarning: true,
          riskKeyword: matched,
          pendingSubmit: { eventType, eventDate, detail, idemKey: util.genIdemKey() },
        });
        return;
      }
    } else if (eventType === '洗澡澡') {
      detail.note = '洗香香啦～';
    }

    this._doSubmit({
      dog_id: dog.id,
      type: eventType,
      date: eventDate,
      detail,
      idem_key: util.genIdemKey(),
      high_risk: 0,
    });
  },

  // 确认高风险：带 high_risk=1 提交
  confirmRisk() {
    const ctx = this.data.pendingSubmit;
    if (!ctx) return;
    this.setData({ showRiskWarning: false, submitting: true });
    this._doSubmit({
      dog_id: this.data.dog.id,
      type: ctx.eventType,
      date: ctx.eventDate,
      detail: ctx.detail,
      idem_key: ctx.idemKey,
      high_risk: 1,
      risk_keyword: this.data.riskKeyword,
    });
  },

  closeRiskWarning() { /* 不关闭，强制用户确认 */ },

  async _doSubmit(payload) {
    this.setData({ submitting: true, reaction: '' });
    try {
      const r = await api.createEvent(payload);
      if (r.duplicate) {
        wx.showToast({ title: '这条记录已经提交过啦～', icon: 'none' });
      } else {
        wx.showToast({ title: '✅ 记录已添加！', icon: 'none' });
      }
      this.setData({
        reaction: r.message,
        submitting: false,
        dose: '', brand: '', note: '', symptoms: [],
        pendingSubmit: null, riskKeyword: '',
      });
    } catch (e) {
      wx.showToast({ title: e.message || '提交失败', icon: 'none' });
      this.setData({ submitting: false, showRiskWarning: false, pendingSubmit: null });
    }
  },

  goProfile() { wx.switchTab({ url: '/pages/profile/profile' }); },
});
