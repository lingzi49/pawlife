// Toast 提示组件
Component({
  properties: {
    message: { type: String, value: '' },
    visible: { type: Boolean, value: false },
    duration: { type: Number, value: 2000 },
  },

  observers: {
    'visible'(val) {
      if (val && this.data.duration > 0) {
        setTimeout(() => {
          this.setData({ visible: false });
        }, this.data.duration);
      }
    },
  },

  methods: {
    show(msg, dur) {
      this.setData({ message: msg, visible: true, duration: dur || 2000 });
    },
    hide() {
      this.setData({ visible: false });
    },
  },
});
