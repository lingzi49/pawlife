// 自定义导航栏组件
Component({
  properties: {
    title: { type: String, value: 'PawLife' },
    showBack: { type: Boolean, value: false },
  },

  data: {
    statusBarHeight: 20,
    navBarHeight: 44,
    totalHeight: 64,
  },

  lifetimes: {
    attached() {
      const sysInfo = wx.getSystemInfoSync();
      const statusBarHeight = sysInfo.statusBarHeight || 20;
      // 胶囊按钮信息用于对齐高度
      const menuBtnInfo = wx.getMenuButtonBoundingClientRect();
      const navBarHeight = menuBtnInfo ? (menuBtnInfo.height + (menuBtnInfo.top - statusBarHeight) * 2) : 44;
      this.setData({
        statusBarHeight,
        navBarHeight,
        totalHeight: statusBarHeight + navBarHeight,
      });
    },
  },

  methods: {
    goBack() {
      const pages = getCurrentPages();
      if (pages.length > 1) {
        wx.navigateBack();
      } else {
        wx.switchTab({ url: '/pages/index/index' });
      }
    },
  },
});
