/** 通用空态/错误态 + 可选重试按钮 */
Component({
  properties: {
    icon: {
      type: String,
      value: '',
    },
    title: {
      type: String,
      value: '',
    },
    desc: {
      type: String,
      value: '',
    },
    retry: {
      type: Boolean,
      value: false,
    },
  },

  methods: {
    onRetry() {
      this.triggerEvent('retry');
    },
  },
});
