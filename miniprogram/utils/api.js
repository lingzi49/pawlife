// PawLife API 请求封装
const app = getApp();

const BASE_URL = app.globalData.baseUrl;

// 通用请求方法，自动带 token 和狗狗口吻错误提示
function request(url, options = {}) {
  return new Promise((resolve, reject) => {
    const token = wx.getStorageSync('token') || app.globalData.token;
    wx.request({
      url: `${BASE_URL}${url}`,
      method: options.method || 'GET',
      data: options.data || {},
      header: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
        ...(options.header || {}),
      },
      success(res) {
        if (res.statusCode === 200) {
          resolve(res.data);
        } else if (res.statusCode === 401) {
          // token 过期，重新登录
          app.wxLogin().then(() => {
            // 重试请求
            request(url, options).then(resolve).catch(reject);
          }).catch(() => {
            wx.showToast({ title: '登录失败，请重试～', icon: 'none' });
            reject(res.data);
          });
        } else if (res.statusCode === 404) {
          reject({ message: res.data.detail || '汪汪，没找到哦～' });
        } else {
          reject({ message: res.data.detail || '汪汪，信号被狗吃了，点我重试～' });
        }
      },
      fail(err) {
        reject({ message: '网络连接失败，主人检查一下网络哦～' });
      },
    });
  });
}

// API 方法
const api = {
  // 狗狗档案
  getDog: () => request('/api/dog'),
  createDog: (data) => request('/api/dog', { method: 'POST', data }),
  updateDog: (data) => request('/api/dog', { method: 'PUT', data }),
  unsuspend: () => request('/api/dog/unsuspend', { method: 'POST' }),
  uploadPhoto: (filePath) => {
    return new Promise((resolve, reject) => {
      const token = wx.getStorageSync('token') || app.globalData.token;
      wx.uploadFile({
        url: `${BASE_URL}/api/dog/photo`,
        filePath: filePath,
        name: 'file',
        header: { 'Authorization': `Bearer ${token}` },
        success(res) {
          if (res.statusCode === 200) {
            resolve(JSON.parse(res.data));
          } else {
            reject(JSON.parse(res.data));
          }
        },
        fail: reject,
      });
    });
  },

  // 事件
  createEvent: (data) => request('/api/event', { method: 'POST', data }),
  updateEvent: (id, data) => request(`/api/event/${id}`, { method: 'PUT', data }),

  // 时间线
  getTimeline: () => request('/api/timeline'),

  // 饮食
  getDiet: () => request('/api/dog/diet'),

  // 保健品
  getSupplements: () => request('/api/supplements'),

  // 健康检查
  getHealthCheck: () => request('/api/health_check'),

  // 体重日志
  getWeightLogs: () => request('/api/weight_logs'),
  addWeightLog: (data) => request('/api/weight_log', { method: 'POST', data }),

  // 订阅消息
  subscribe: (data) => request('/api/subscribe', { method: 'POST', data }),

  // 兽医摘要
  getVetSummary: (eventId) => request(`/api/vet_summary/${eventId}`),

  // 导出
  exportData: () => request('/api/export'),
};

module.exports = api;
