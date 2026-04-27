App({
  globalData: {
    // 本地预览模式：true = 使用本地模拟数据，不连接云开发。
    // 联调云开发时改成 false。
    useMockFood: true,
    // 填你的真实云环境 ID（云开发控制台可复制），例如: "eat-what-1gxxxxxx"
    cloudEnvId: "YOUR_CLOUD_ENV_ID",
  },
  onLaunch() {
    if (this.globalData.useMockFood) {
      console.log("[app] Mock mode enabled, skip wx.cloud.init");
      return;
    }

    if (!wx.cloud) {
      console.error("[app] wx.cloud is unavailable. 请使用 2.2.3 及以上基础库。");
      return;
    }

    if (!this.globalData.cloudEnvId || this.globalData.cloudEnvId === "YOUR_CLOUD_ENV_ID") {
      console.warn("[app] cloudEnvId 未配置，已跳过云开发初始化。");
      return;
    }

    try {
      wx.cloud.init({
        env: this.globalData.cloudEnvId,
        traceUser: true,
      });
      console.log(`[app] wx.cloud.init success, env=${this.globalData.cloudEnvId}`);
    } catch (error) {
      console.error("[app] wx.cloud.init failed", error);
    }
  },
});
