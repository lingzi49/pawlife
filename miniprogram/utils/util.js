// PawLife 工具函数

// 幂等键生成（防重复提交）
function genIdemKey() {
  const ts = Date.now().toString(36);
  const r = Math.random().toString(36).substring(2, 8);
  return `idem_${ts}_${r}`;
}

// 计算年龄
function calcAge(birthday) {
  const today = new Date();
  const b = new Date(birthday);
  let years = today.getFullYear() - b.getFullYear();
  let months = today.getMonth() - b.getMonth();
  if (today.getDate() < b.getDate()) months--;
  if (months < 0) { years--; months += 12; }
  if (years > 0) return months > 0 ? `${years}岁${months}个月` : `${years}岁`;
  return months > 0 ? `${months}个月` : '新生儿';
}

// 判断是否幼犬（<12个月）
function isPuppy(birthday) {
  const today = new Date();
  const b = new Date(birthday);
  const months = (today.getFullYear() - b.getFullYear()) * 12 + (today.getMonth() - b.getMonth());
  return months < 12;
}

// 解析体重（kg）
function parseWeightKg(weightStr) {
  if (!weightStr) return null;
  const m = ('' + weightStr).match(/[\d.]+/);
  return m ? parseFloat(m[0]) : null;
}

// 高危症状词库（前端匹配）
const HIGH_RISK_SYMPTOMS = [
  "反复呕吐", "持续呕吐", "吐血", "呕血", "腹泻带血", "便血", "黑便",
  "抽搐", "癫痫", "昏厥", "晕倒", "瘫痪", "呼吸困难", "呼吸急促",
  "极度萎靡", "意识丧失", "瞳孔散大", "严重过敏", "面部肿胀",
  "车祸", "中毒", "误食巧克力", "误食洋葱", "误食葡萄", "误食木糖醇",
  "误食老鼠药", "被蛇咬", "严重外伤", "大出血", "骨折", "烫伤",
];

function checkHighRisk(text) {
  for (const kw of HIGH_RISK_SYMPTOMS) {
    if (text.indexOf(kw) !== -1) return kw;
  }
  return null;
}

// 品种图标映射
const BREED_ICONS = {
  '金毛': '🦮', '拉布拉多': '🐕‍🦺', '柯基': '🐕', '贵宾': '🐩',
  '豆柴': '🐶', '混血': '🐕', '其他': '🐶',
};
function getBreedIcon(breed) { return BREED_ICONS[breed] || '🐶'; }

// 时间问候语
function getTimeGreeting() {
  const h = new Date().getHours();
  if (h >= 5 && h < 12) return '早安，主人！';
  if (h >= 12 && h < 18) return '午安，主人！';
  if (h >= 18 && h < 22) return '晚安，主人！🌙';
  return '月亮都睡着啦，主人也该休息了～🌙';
}

// HTML 转义（小程序用 text 组件，通常不需要，但保留备用）
function escHtml(s) {
  return ('' + s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

module.exports = {
  genIdemKey, calcAge, isPuppy, parseWeightKg,
  HIGH_RISK_SYMPTOMS, checkHighRisk, getBreedIcon,
  getTimeGreeting, escHtml,
};
