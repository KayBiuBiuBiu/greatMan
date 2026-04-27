const fs = require("fs");
const path = require("path");
const source = require("./foods-source.example");

function toDocs(names, period) {
  return names
    .map((name) => String(name || "").trim())
    .filter(Boolean)
    .map((name) => ({
      name,
      period,
      image: "",
    }));
}

const docs = [
  ...toDocs(source.breakfast || [], "早餐"),
  ...toDocs(source.lunch || [], "午餐"),
  ...toDocs(source.dinner || [], "晚餐"),
  ...toDocs(source.nightSnack || [], "夜宵"),
];

if (!docs.length) {
  console.error("没有可导出的菜品，请先在 foods-source.example.js 填数据。");
  process.exit(1);
}

const outPath = path.resolve(__dirname, "foods.import.json");
fs.writeFileSync(outPath, JSON.stringify(docs, null, 2), "utf8");

console.log(`已生成: ${outPath}`);
console.log(`共 ${docs.length} 条菜品记录`);
