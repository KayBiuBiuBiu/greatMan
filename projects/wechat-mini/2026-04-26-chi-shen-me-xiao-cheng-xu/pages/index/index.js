const PERIOD_BUTTONS = [
  { label: "早餐", value: "早餐" },
  { label: "午餐", value: "午餐" },
  { label: "晚餐", value: "晚餐" },
  { label: "夜宵", value: "夜宵" },
  { label: "随便吃点", value: "" },
];

const ZODIACS = [
  "白羊座",
  "金牛座",
  "双子座",
  "巨蟹座",
  "狮子座",
  "处女座",
  "天秤座",
  "天蝎座",
  "射手座",
  "摩羯座",
  "水瓶座",
  "双鱼座",
];

const MOCK_FOODS = [
  { name: "豆浆油条", period: "早餐", image: "" },
  { name: "鸡蛋灌饼", period: "早餐", image: "" },
  { name: "宫保鸡丁", period: "午餐", image: "" },
  { name: "番茄牛腩饭", period: "午餐", image: "" },
  { name: "红烧排骨", period: "晚餐", image: "" },
  { name: "清蒸鲈鱼", period: "晚餐", image: "" },
  { name: "酸辣粉", period: "夜宵", image: "" },
  { name: "烤冷面", period: "夜宵", image: "" },
];

function pickRandomOne(list) {
  if (!list.length) return null;
  const idx = Math.floor(Math.random() * list.length);
  return list[idx];
}

Page({
  data: {
    periodButtons: PERIOD_BUTTONS,
    zodiacs: ZODIACS,
    zodiacIndex: 0,
    activePeriod: "",
    activePeriodLabel: "随便吃点",
    resultFood: null,
    isLoading: false,
    hasTried: false,
    useMockFood: false,
  },

  onShow() {
    const app = getApp();
    const useMockFood = app && app.globalData ? !!app.globalData.useMockFood : false;
    this.setData({
      useMockFood,
    });
  },

  onPickPeriod(e) {
    const period = e.currentTarget.dataset.period || "";
    const label = e.currentTarget.dataset.label || "随便吃点";
    this.setData({
      activePeriod: period,
      activePeriodLabel: label,
      hasTried: true,
    });
    this.fetchRandomFood(period);
  },

  onPickAnother() {
    if (!this.data.hasTried) {
      wx.showToast({
        title: "先选一个时段吧",
        icon: "none",
      });
      return;
    }
    this.fetchRandomFood(this.data.activePeriod);
  },

  onZodiacChange(e) {
    this.setData({
      zodiacIndex: Number(e.detail.value),
    });
  },

  async fetchRandomFood(period) {
    if (this.data.isLoading) return;

    this.setData({ isLoading: true });
    wx.showLoading({ title: "正在推荐..." });

    try {
      const app = getApp();
      const useMockFood = app && app.globalData ? !!app.globalData.useMockFood : false;

      if (useMockFood) {
        const source = period ? MOCK_FOODS.filter((item) => item.period === period) : MOCK_FOODS;
        const randomFood = pickRandomOne(source);
        if (!randomFood) {
          wx.showToast({
            title: "本地演示数据为空",
            icon: "none",
          });
          this.setData({ resultFood: null });
          return;
        }
        this.setData({ resultFood: randomFood });
        return;
      }

      const res = await wx.cloud.callFunction({
        name: "getRandomFood",
        data: { period: period || "" },
      });
      const result = res.result || {};

      if (!result.ok) {
        wx.showToast({
          title: result.message || "暂无可推荐菜品",
          icon: "none",
        });
        this.setData({ resultFood: null });
        return;
      }

      this.setData({
        resultFood: result.data,
      });
    } catch (err) {
      wx.showToast({
        title: "网络开小差了，请重试",
        icon: "none",
      });
    } finally {
      wx.hideLoading();
      this.setData({ isLoading: false });
    }
  },
});
