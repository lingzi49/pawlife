// 保健品页面
const api = require('../../utils/api');

Page({
  data: {
    hasDog: false,
    suspended: false,
    dogName: '',
    alerts: [],
  },

  onShow() { this.loadSupplements(); },

  async loadSupplements() {
    try {
      const data = await api.getSupplements();
      if (!data.has_dog) {
        this.setData({ hasDog: false });
        return;
      }
      if (data.suspended) {
        this.setData({ hasDog: true, suspended: true, alerts: [] });
        return;
      }
      this.setData({ hasDog: true, suspended: false, dogName: data.dog_name, alerts: data.alerts });
    } catch (e) {
      this.setData({ hasDog: false });
    }
  },

  async restoreSuggestions() {
    try {
      await api.unsuspend();
      wx.showToast({ title: '已恢复建议～🐾', icon: 'none' });
      this.loadSupplements();
    } catch (e) {
      wx.showToast({ title: e.message || '恢复失败', icon: 'none' });
    }
  },

  onPullDownRefresh() {
    this.loadSupplements().then(() => wx.stopPullDownRefresh());
  },
});
