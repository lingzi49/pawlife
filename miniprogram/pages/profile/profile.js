// 我的档案页面
const api = require('../../utils/api');
const util = require('../../utils/util');

Page({
  data: {
    hasDog: false,
    dog: null,
    dogAge: '',
    genderLabel: '',
    breedIcon: '🐶',
    baseUrl: getApp().globalData.baseUrl,
    today: '',
    // 建档表单
    breeds: ['金毛', '拉布拉多', '柯基', '贵宾', '豆柴', '混血', '其他'],
    breedIndex: 0,
    genders: ['保密', '公', '母'],
    genderIndex: 0,
    neuterOptions: ['未知', '是', '否'],
    neuterIndex: 0,
    form: { name: '', breed: '金毛', birthday: '', weight: '', gender: '', neutered: '未知', allergies: '', diseases: '' },
    disclaimerAgreed: false,
    saving: false,
    // 编辑弹窗
    showEdit: false,
    editForm: {},
  },

  onShow() {
    const now = new Date();
    this.setData({ today: `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')}` });
    this.loadDog();
  },

  async loadDog() {
    try {
      const dog = await api.getDog();
      this.setData({
        hasDog: true, dog,
        dogAge: util.calcAge(dog.birthday),
        genderLabel: dog.gender === 'male' ? '公 🚹' : dog.gender === 'female' ? '母 🚺' : '保密',
        breedIcon: util.getBreedIcon(dog.breed),
      });
    } catch (e) {
      this.setData({ hasDog: false });
    }
  },

  // 建档表单事件
  onFieldInput(e) {
    const { field } = e.currentTarget.dataset;
    this.setData({ [`form.${field}`]: e.detail.value });
  },
  onFieldChange(e) {
    const { field } = e.currentTarget.dataset;
    this.setData({ [`form.${field}`]: e.detail.value });
  },
  onBreedChange(e) { this.setData({ breedIndex: parseInt(e.detail.value), 'form.breed': this.data.breeds[e.detail.value] }); },
  onGenderChange(e) {
    const idx = parseInt(e.detail.value);
    const genderMap = { 0: '', 1: 'male', 2: 'female' };
    this.setData({ genderIndex: idx, 'form.gender': genderMap[idx] });
  },
  onNeuterChange(e) { this.setData({ neuterIndex: parseInt(e.detail.value), 'form.neutered': this.data.neuterOptions[e.detail.value] }); },
  toggleDisclaimer() { this.setData({ disclaimerAgreed: !this.data.disclaimerAgreed }); },

  // 创建档案
  async createProfile() {
    const { form, disclaimerAgreed } = this.data;
    if (!form.name || !form.breed) {
      wx.showToast({ title: '汪汪，名字和品种是必填的哦～', icon: 'none' }); return;
    }
    if (!form.birthday) {
      wx.showToast({ title: '请选择我的生日哦～', icon: 'none' }); return;
    }
    if (!disclaimerAgreed) {
      wx.showToast({ title: '请先阅读并勾选免责声明哦～', icon: 'none' }); return;
    }
    this.setData({ saving: true });
    try {
      await api.createDog(form);
      wx.showToast({ title: '汪汪！档案创建成功～🐾', icon: 'none' });
      this.loadDog();
    } catch (e) {
      wx.showToast({ title: e.message || '建档失败', icon: 'none' });
    }
    this.setData({ saving: false });
  },

  // 编辑档案
  openEdit() {
    const d = this.data.dog;
    this.setData({
      showEdit: true,
      editForm: { name: d.name, weight: d.weight || '',
        allergies: d.allergies || '', diseases: d.diseases || '' },
    });
  },
  closeEdit() { this.setData({ showEdit: false }); },
  onEditInput(e) {
    const { field } = e.currentTarget.dataset;
    this.setData({ [`editForm.${field}`]: e.detail.value });
  },
  async saveEdit() {
    this.setData({ saving: true });
    try {
      await api.updateDog(this.data.editForm);
      wx.showToast({ title: '档案更新好了～🐾', icon: 'none' });
      this.setData({ showEdit: false });
      this.loadDog();
    } catch (e) {
      wx.showToast({ title: e.message || '保存失败', icon: 'none' });
    }
    this.setData({ saving: false });
  },

  // 换照片
  choosePhoto() {
    wx.chooseImage({
      count: 1, sizeType: ['compressed'],
      sourceType: ['album', 'camera'],
      success: async (res) => {
        try {
          await api.uploadPhoto(res.tempFilePaths[0]);
          wx.showToast({ title: '新照片太好看啦～🐾', icon: 'none' });
          this.loadDog();
        } catch (e) {
          wx.showToast({ title: e.message || '上传失败', icon: 'none' });
        }
      },
    });
  },

  // 导出
  async exportData() {
    try {
      const csv = await api.exportData();
      wx.setClipboardData({ data: csv, success: () => {
        wx.showToast({ title: '数据已复制到剪贴板！', icon: 'none' });
      }});
    } catch (e) {
      wx.showToast({ title: '导出失败', icon: 'none' });
    }
  },

  goTimeline() { wx.navigateTo({ url: '/pages/timeline/timeline' }); },
  goDiet() { wx.navigateTo({ url: '/pages/diet/diet' }); },
  goSupplement() { wx.navigateTo({ url: '/pages/supplement/supplement' }); },
});
