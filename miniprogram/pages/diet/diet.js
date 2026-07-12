// 饮食宝典页面
const api = require('../../utils/api');

Page({
  data: {
    suspended: false,
    diet: { ready: false },
    todayStr: '',
  },

  onShow() {
    const now = new Date();
    const y = now.getFullYear();
    const m = now.getMonth() + 1;
    const d = now.getDate();
    this.setData({ todayStr: `${y}年${m}月${d}日` });
    this.loadDiet();
  },

  async loadDiet() {
    try {
      const data = await api.getDiet();
      if (data.suspended) {
        this.setData({ suspended: true, diet: { ready: false } });
        return;
      }
      this.setData({ suspended: false, diet: data });
    } catch (e) {
      this.setData({ diet: { ready: false, message: '汪汪，食谱加载失败了，下拉刷新吧～' } });
    }
  },

  async restoreSuggestions() {
    try {
      await api.unsuspend();
      wx.showToast({ title: '已恢复建议～🐾', icon: 'none' });
      this.loadDiet();
    } catch (e) {
      wx.showToast({ title: e.message || '恢复失败', icon: 'none' });
    }
  },

  onPullDownRefresh() {
    this.loadDiet().then(() => wx.stopPullDownRefresh());
  },
});
