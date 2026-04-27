/**
 * 使用说明：
 * 1) 把你 386 道菜名按时段填进下面 4 个数组。
 * 2) 运行: node tools/build-foods-json.js
 * 3) 生成: tools/foods.import.json
 * 4) 到微信云开发控制台 -> 数据库 -> foods -> 导入 JSON 文件。
 */

module.exports = {
  breakfast: [
    "花椒叶贝果",
  ],
  lunch: [
    "宫保鸡丁",
    "番茄牛腩",
  ],
  dinner: [
    "红烧肉",
    "清蒸鲈鱼",
  ],
  nightSnack: [
    "酸辣粉",
    "烤冷面",
    "红烧鱼片",
  ],
};
