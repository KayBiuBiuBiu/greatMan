const cloud = require("wx-server-sdk");

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV });

const db = cloud.database();
const FOODS_COLLECTION = "foods";
const VALID_PERIODS = ["早餐", "午餐", "晚餐", "夜宵"];

exports.main = async (event) => {
  const rawPeriod = (event && event.period ? String(event.period) : "").trim();
  const isAll = !rawPeriod || rawPeriod === "随便吃点";

  if (!isAll && !VALID_PERIODS.includes(rawPeriod)) {
    return {
      ok: false,
      code: "INVALID_PERIOD",
      message: "时段参数不合法",
    };
  }

  const where = isAll ? {} : { period: rawPeriod };

  try {
    const countRes = await db.collection(FOODS_COLLECTION).where(where).count();
    const total = countRes.total || 0;

    if (total === 0) {
      return {
        ok: false,
        code: "EMPTY_DATA",
        message: isAll ? "菜品库为空，请先导入 foods 数据" : `${rawPeriod} 暂无菜品，请补充后再试`,
      };
    }

    // 当前项目体量（约 386 条）下，count + 随机 skip 足够稳定且简单。
    // 若后续数据量特别大，可在 foods 增加随机索引字段进行优化。
    const randomSkip = Math.floor(Math.random() * total);
    const listRes = await db
      .collection(FOODS_COLLECTION)
      .where(where)
      .skip(randomSkip)
      .limit(1)
      .field({
        name: true,
        period: true,
        image: true,
      })
      .get();

    const food = listRes.data && listRes.data[0];
    if (!food) {
      return {
        ok: false,
        code: "NOT_FOUND",
        message: "随机失败，请重试",
      };
    }

    return {
      ok: true,
      code: "SUCCESS",
      data: food,
    };
  } catch (error) {
    return {
      ok: false,
      code: "DB_ERROR",
      message: error.message || "数据库异常",
    };
  }
};
