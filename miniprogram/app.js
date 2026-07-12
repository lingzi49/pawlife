// PawLife 微信小程序 — 应用入口
App({
  globalData: {
    token: '',
    openid: '',
    baseUrl: 'https://pawlife-api.onrender.com', // 替换为实际后端地址
    dog: null,
  },

  onLaunch() {
    // 尝试从 storage 恢复登录态
    const token = wx.getStorageSync('token');
    if (token) {
      this.globalData.token = token;
    }
    // 每次启动都重新登录，确保 token 有效
    this.wxLogin();
  },

  wxLogin() {
    return new Promise((resolve, reject) => {
      wx.login({
        success: (res) => {
          if (res.code) {
            wx.request({
              url: `${this.globalData.baseUrl}/api/login`,
              method: 'POST',
              data: { code: res.code },
              success: (resp) => {
                if (resp.statusCode === 200 && resp.data.token) {
                  this.globalData.token = resp.data.token;
                  this.globalData.openid = resp.data.openid;
                  wx.setStorageSync('token', resp.data.token);
                  resolve(resp.data);
                } else {
                  reject(resp.data);
                }
              },
              fail: (err) => reject(err),
            });
          } else {
            reject(res);
          }
        },
        fail: (err) => reject(err),
      });
    });
  },

  // 获取认证 header
  getAuthHeader() {
    return {
      'Authorization': `Bearer ${this.globalData.token}`,
      'Content-Type': 'application/json',
    };
  },
});
