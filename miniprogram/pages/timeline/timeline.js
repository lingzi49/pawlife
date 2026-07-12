// 大事记（时间线）页面
const api = require('../../utils/api');

Page({
  data: {
    hasDog: false,
    dogName: '',
    events: [],
    filteredEvents: [],
    activeFilter: '全部',
  },

  onShow() { this.loadTimeline(); },

  async loadTimeline() {
    try {
      const data = await api.getTimeline();
      if (!data.has_dog) {
        this.setData({ hasDog: false });
        return;
      }
      const typeIcons = { '疫苗': '💉', '驱虫': '💊', '发情': '💕', '异常行为': '⚠️', '洗澡澡': '🛁' };
      const events = data.timeline.map(e => {
        let desc = '';
        const d = e.detail || {};
        if (e.type === '疫苗' && d.dose) desc = d.dose + (d.brand ? ' · ' + d.brand : '');
        else if (e.type === '驱虫') desc = (d.deworm_type || '') + (d.brand ? ' · ' + d.brand : '');
        else if (e.type === '发情' && d.note) desc = d.note;
        else if (e.type === '异常行为' && d.symptoms) desc = d.symptoms.join('、');
        else if (e.type === '洗澡澡') desc = '洗香香啦～';
        return { ...e, typeIcon: typeIcons[e.type] || '📌', description: desc };
      });
      this.setData({ hasDog: true, dogName: data.dog_name, events, filteredEvents: events });
    } catch (e) {
      this.setData({ hasDog: false });
    }
  },

  setFilter(e) {
    const type = e.currentTarget.dataset.type;
    const filtered = type === '全部' ? this.data.events : this.data.events.filter(ev => ev.type === type);
    this.setData({ activeFilter: type, filteredEvents: filtered });
  },
});
