// 首页：今日汪汪 + 档案摘要
const api = require('../../utils/api');
const util = require('../../utils/util');

Page({
  data: {
    hasDog: false,
    dog: null,
    dogAge: '',
    breedIcon: '🐶',
    greeting: '🐾 汪汪，你好！',
    todayMessage: '汪汪正在赶来...',
    urgent: false,
    pendingActions: 0,
    supplementCount: 0,
    suspended: false,
    loading: true,
    baseUrl: getApp().globalData.baseUrl,
  },

  onShow() {
    this.loadAll();
  },

  async loadAll() {
    try {
      const dog = await api.getDog();
      const age = util.calcAge(dog.birthday);
      this.setData({
        hasDog: true,
        dog,
        dogAge: dog.weight ? `${age} · ${dog.weight}` : age,
        breedIcon: util.getBreedIcon(dog.breed),
        suspended: !!dog.suspended_until,
      });
      this.updateGreeting(dog);
      await this.loadHealthCheck();
    } catch (e) {
      this.setData({
        hasDog: false,
        loading: false,
        todayMessage: '主人，快帮我建个档案，让我认识你吧～🐾',
      });
    }
  },

  async loadHealthCheck() {
    try {
      const data = await api.getHealthCheck();
      let msg = '';
      let urgent = false;

      if (data.suspended) {
        msg = '🚨 今天因高风险症状，建议已暂停。主人，请先确认我的状况稳定哦！';
        urgent = true;
      } else if (data.reminders && data.reminders.length > 0) {
        const urgentReminders = data.reminders.filter(r => r.urgent);
        if (urgentReminders.length > 0) {
          msg = '🚨 ' + urgentReminders.map(r => r.msg).join('\n');
          urgent = true;
        } else {
          msg = data.reminders.map(r => r.msg).join('\n');
        }
      } else {
        msg = '🐾 今天又是元气满满的一天！主人，我的档案一切正常，继续保持哦～';
      }

      this.setData({
        todayMessage: msg,
        urgent,
        pendingActions: data.pending_actions || 0,
        supplementCount: data.supplement_count || 0,
        loading: false,
      });
    } catch (e) {
      this.setData({ loading: false, todayMessage: '汪汪，健康数据加载失败了，点↻刷新吧～' });
    }
  },

  updateGreeting(dog) {
    const hour = new Date().getHours();
    let g;
    if (hour >= 5 && hour < 12) g = '早安，主人！☀️';
    else if (hour >= 12 && hour < 18) g = '午安，主人！🌤️';
    else if (hour >= 18 && hour < 22) g = '晚安，主人！🌙';
    else g = '夜深了，主人也要好好休息哦～🌙';

    if (dog.gender === 'male') g = dog.name + ' 小王子：' + g;
    else if (dog.gender === 'female') g = dog.name + ' 小公主：' + g;
    else g = dog.name + '：' + g;

    this.setData({ greeting: g });
  },

  refreshToday() {
    this.setData({ loading: true });
    this.loadHealthCheck();
  },

  async restoreSuggestions() {
    try {
      const r = await api.unsuspend();
      wx.showToast({ title: '已恢复建议～🐾', icon: 'none' });
      this.loadAll();
    } catch (e) {
      wx.showToast({ title: e.message || '恢复失败', icon: 'none' });
    }
  },

  goProfile() { wx.switchTab({ url: '/pages/profile/profile' }); },
  goRecord() { wx.switchTab({ url: '/pages/record/record' }); },
  goTimeline() { wx.navigateTo({ url: '/pages/timeline/timeline' }); },
  goDiet() { wx.navigateTo({ url: '/pages/diet/diet' }); },
  goSupplement() { wx.navigateTo({ url: '/pages/supplement/supplement' }); },
});
