/* PawLife 展示版 — 演示数据与规则逻辑
 * 所有数据均为虚构演示数据，仅保存在浏览器 localStorage。
 * 营养与提醒规则移植自 pawlife_web.py（以代码实际实现为准）。
 */
window.PawData = (function () {
  'use strict';

  var STORAGE_KEY = 'pawlife.showcase.v2';
  var DAY_MS = 86400000;

  /* ---------------- 日期工具 ---------------- */
  function pad(n) { return n < 10 ? '0' + n : '' + n; }
  function isoOf(d) {
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
  }
  function parseISO(s) {
    var p = String(s).split('-');
    return new Date(Number(p[0]), Number(p[1]) - 1, Number(p[2]), 12, 0, 0, 0);
  }
  function todayISO() {
    var d = new Date();
    d.setHours(12, 0, 0, 0);
    return isoOf(d);
  }
  function daysAgoISO(n) {
    var d = new Date();
    d.setHours(12, 0, 0, 0);
    d.setDate(d.getDate() - n);
    return isoOf(d);
  }
  function addDaysISO(s, n) {
    var d = parseISO(s);
    d.setDate(d.getDate() + n);
    return isoOf(d);
  }
  function diffDays(a, b) {
    return Math.round((parseISO(a) - parseISO(b)) / DAY_MS);
  }
  function nowISO() {
    var d = new Date();
    return isoOf(d) + 'T' + pad(d.getHours()) + ':' + pad(d.getMinutes());
  }

  /* ---------------- 基础常量（移植自后端） ---------------- */
  var BREED_OPTIONS = [
    '泰迪', '比熊', '博美', '吉娃娃', '约克夏', '迷你雪纳瑞', '巴哥', '京巴', '西施',
    '马尔济斯', '迷你杜宾', '柴犬', '豆柴', '柯基', '法斗', '英斗', '贵宾', '中华田园犬',
    '银狐', '比格', '金毛', '拉布拉多', '德牧', '萨摩耶', '边牧', '哈士奇', '阿拉斯加',
    '秋田', '松狮', '罗威纳', '杜宾', '大白熊', '混血', '其他'
  ];

  var BREED_IDEAL_WEIGHT = {
    '泰迪': [2.0, 5.0], '比熊': [5.0, 8.5], '博美': [1.5, 3.5], '吉娃娃': [1.0, 3.0],
    '约克夏': [1.5, 3.0], '迷你雪纳瑞': [5.0, 9.0], '巴哥': [6.0, 9.0], '京巴': [3.0, 6.0],
    '西施': [4.0, 8.0], '马尔济斯': [2.0, 3.5], '迷你杜宾': [4.0, 6.0], '柴犬': [8.0, 12.0],
    '豆柴': [6.0, 10.0], '柯基': [10.0, 14.0], '法斗': [8.0, 13.0], '英斗': [18.0, 25.0],
    '贵宾': [2.0, 32.0], '中华田园犬': [12.0, 25.0], '银狐': [5.0, 10.0], '比格': [9.0, 16.0],
    '金毛': [25.0, 34.0], '拉布拉多': [25.0, 36.0], '德牧': [22.0, 40.0], '萨摩耶': [16.0, 30.0],
    '边牧': [14.0, 22.0], '哈士奇': [16.0, 27.0], '阿拉斯加': [34.0, 45.0], '秋田': [32.0, 55.0],
    '松狮': [20.0, 32.0], '罗威纳': [35.0, 60.0], '杜宾': [27.0, 45.0], '大白熊': [36.0, 54.0],
    '混血': null, '其他': null
  };

  var HIGH_RISK_SYMPTOMS = [
    '反复呕吐', '持续呕吐', '吐血', '呕血', '腹泻带血', '便血', '黑便', '抽搐', '癫痫',
    '昏厥', '晕倒', '瘫痪', '呼吸困难', '呼吸急促', '极度萎靡', '意识丧失', '瞳孔散大',
    '严重过敏', '面部肿胀', '车祸', '中毒', '误食巧克力', '误食洋葱', '误食葡萄',
    '误食木糖醇', '误食老鼠药', '被蛇咬', '严重外伤', '大出血', '骨折', '烫伤'
  ];

  var ABNORMAL_SYMPTOMS = ['跛行', '呕吐', '拉稀', '抓痒', '猛喝水', '不吃东西'];

  var EVENT_META = {
    '疫苗': { icon: '💉', cls: 'vaccine', label: '疫苗接种' },
    '驱虫': { icon: '🛡️', cls: 'deworm', label: '驱虫' },
    '发情': { icon: '💗', cls: 'heat', label: '生理周期' },
    '异常行为': { icon: '🩺', cls: 'abnormal', label: '异常观察' },
    '洗澡澡': { icon: '🛁', cls: 'bath', label: '洗澡护理' },
    '每日检查': { icon: '✅', cls: 'daily', label: '每日健康检查' },
    '体重': { icon: '⚖️', cls: 'weight', label: '体重记录' }
  };

  var BADGES = [
    { name: '初来乍到', icon: '🐾', category: '第一次', condition: '创建狗狗档案，我们第一次相遇' },
    { name: '第一针疫苗', icon: '💉', category: '第一次', condition: '完成第一次疫苗接种' },
    { name: '第一次驱虫', icon: '🛡️', category: '第一次', condition: '完成第一次驱虫' },
    { name: '第一次洗澡', icon: '🛁', category: '第一次', condition: '完成第一次洗澡护理' },
    { name: '到家第一天', icon: '🏠', category: '第一次', condition: '记录到家日期，有了共同的家' },
    { name: '免疫完成', icon: '💉', category: '守护者', condition: '累计完成 3 次疫苗接种' },
    { name: '驱虫达标', icon: '🛡️', category: '守护者', condition: '累计完成 6 次驱虫' },
    { name: '洁齿坚持', icon: '🦷', category: '守护者', condition: '30 天内完成 15 次每日任务' },
    { name: '肠胃稳定', icon: '🍽️', category: '守护者', condition: '最近一次异常后 60 天无复发' },
    { name: '体重管理', icon: '⚖️', category: '守护者', condition: '3 次以上体重记录跨越 90 天且都在理想范围' },
    { name: '体态管理', icon: '🤚', category: '守护者', condition: '连续 3 次 BCS 评估为理想体态' },
    { name: '生日快乐', icon: '🎂', category: '健康里程碑', condition: '生日当天完成签到' },
    { name: '绝育勇敢', icon: '🌟', category: '健康里程碑', condition: '档案记录为已绝育' },
    { name: '百日相伴', icon: '💯', category: '健康里程碑', condition: '建档满 100 天并完成当日签到' },
    { name: '健康大满贯', icon: '🏆', category: '健康里程碑', condition: '集齐全部守护者系列勋章' },
    { name: '守护之星', icon: '⭐', category: '健康里程碑', condition: '累计获得 30 个爪印积分' }
  ];

  var DAILY_TASKS = [
    { id: 'weigh', task: '今天给我称一下体重，记录在档案里，监控体重防肥胖～', action: '去记录体重', page: 'trends', thanks: '体重记录好了！主人帮我监控身材，我要做最健康的小狗～' },
    { id: 'groom', task: '今天给我梳毛 5 分钟吧，我会舒服得咕噜咕噜的～', action: '我梳过了', thanks: '梳完毛浑身轻松！毛毛也亮亮的～' },
    { id: 'ears', task: '检查一下我的耳朵脏不脏，垂耳小朋友要格外注意哦！', action: '我检查过了', thanks: '耳朵干干净净！主人细心检查，我的耳朵不会发炎啦～' },
    { id: 'social', task: '带我去认识一个新朋友（人或狗狗都行），社交让人快乐！', action: '认识啦', thanks: '新朋友真有趣！社交让狗狗更自信～' },
    { id: 'photo', task: '给我拍一张今天的照片，记录我的成长瞬间～', action: '拍好啦', thanks: '拍到了我的美照！主人镜头下的我永远最可爱～' },
    { id: 'trick', task: '今天教我一个新指令吧，比如「趴下」或「握手」，我超爱学习的！', action: '教过了', thanks: '我又变聪明了一点！用零食训练我，我会学得更快哦～' },
    { id: 'water', task: '检查我的水碗是不是满的、干净的，每天换新鲜水很重要～', action: '换过了', thanks: '新鲜的水真好喝！干净的水碗是最基本的爱～' },
    { id: 'body_check', task: '摸一摸我的全身，看看有没有疙瘩、红肿或异常的热点。', action: '检查过了', thanks: '全身检查过关！任何小问题都逃不过你的手掌～' },
    { id: 'walk', task: '今天多绕一条街散步，换个路线让我闻闻新鲜的气味～', action: '走过了', thanks: '散步好开心！新路线新气味，我的社交网络又更新啦～' },
    { id: 'teeth', task: '检查一下我的牙齿，看看有没有牙结石或牙龈红肿。', action: '看过了', thanks: '牙齿亮晶晶！定期检查，我的笑容永远灿烂～' },
    { id: 'toys', task: '帮我清洗一下玩具，玩具上的细菌比厕所还多呢！', action: '洗好了', thanks: '玩具又变干净了！啃干净的玩具，做干净的狗狗～' },
    { id: 'hide_seek', task: '今天陪我玩一次捉迷藏，在家藏起来让我找你，这能锻炼我的嗅觉～', action: '玩过了', thanks: '找到主人啦！捉迷藏还能锻炼我的嗅觉追踪能力～' },
    { id: 'nails', task: '检查我的指甲长度，太长了走路会疼还会导致关节问题哦。', action: '检查过了', thanks: '指甲长度刚好！主人真细心～' },
    { id: 'food_check', task: '看看狗粮包装上的保质期，过期了就不能吃了，会让我生病的。', action: '看过了', thanks: '狗粮都在保质期内！吃新鲜的粮，做健康的好狗狗～' },
    { id: 'petting', task: '抚摸我十五分钟，从头到背慢慢摸，这能降低我们的压力荷尔蒙。', action: '抚摸过了', thanks: '被摸得好舒服～十五分钟的抚摸让压力都飞走了～' },
    { id: 'gear', task: '检查我的项圈和胸背带有没有磨损，安全第一哦！', action: '查过了', thanks: '装备完好！安全的项圈和胸背带是散步的第一道防线～' },
    { id: 'plants', task: '家里有没有对我有毒的植物？比如百合、滴水观音，放高一点～', action: '排查过了', thanks: '家里没有危险植物！我好安全～' }
  ];

  var SURVIVAL_TIPS = [
    { text: '葡萄和葡萄干可能损伤肾脏，一颗都不要给。', category: 'food_danger' },
    { text: '巧克力、洋葱、木糖醇对狗狗有毒，记得收进高处柜子。', category: 'food_danger' },
    { text: '三文鱼油富含 Omega-3，对皮肤、毛发和关节都有帮助。', category: 'food_good' },
    { text: '南瓜泥对消化友好，便秘或软便时都能少量调节。', category: 'food_good' },
    { text: '每天散步时让狗狗闻一闻世界，嗅闻是它们重要的社交方式。', category: 'care' },
    { text: '每天刷一次牙，牙结石可能牵连心脏和肾脏健康。', category: 'care' },
    { text: '夏季柏油路面温度可能超过 60℃，出门前先用手背试温。', category: 'season' },
    { text: '草丛蜱虫多，散步回来重点检查耳朵、腋下和趾间。', category: 'season' },
    { text: '正常狗狗体温约 38–39.2℃，精神状态和食欲比鼻头干湿更可靠。', category: 'health_tip' },
    { text: '口臭不是正常现象，可能是牙结石或口腔感染的信号。', category: 'health_tip' },
    { text: '摇尾巴不一定代表开心，低而慢的摆动可能是紧张。', category: 'behavior' },
    { text: '分离焦虑不是「作」，从短时间离开开始循序练习。', category: 'behavior' }
  ];

  var DIET_FOODS = {
    '幼犬|小型犬': { meals: 4, protein: '鸡胸肉（白肉低脂）', veggie: '南瓜', carb: '燕麦', tip: '幼犬肠胃娇嫩，所有食材需煮软打成泥糊状，少食多餐～', daily: ['鸡胸肉丁 + 南瓜泥 + 燕麦糊', '蛋黄半个 + 胡萝卜泥 + 小米粥', '鱼肉碎 + 西兰花泥 + 红薯泥'] },
    '幼犬|中型犬': { meals: 3, protein: '牛肉糜（红肉补铁）', veggie: '胡萝卜', carb: '糙米', tip: '幼犬活动量大，碳水比例可稍高，保证能量供给～', daily: ['牛肉糜 + 胡萝卜丁 + 糙米饭', '鸡胸肉 + 菠菜碎 + 红薯块', '三文鱼 + 南瓜 + 藜麦'] },
    '幼犬|大型犬': { meals: 3, protein: '鸡胸肉', veggie: '菠菜', carb: '红薯', tip: '大型幼犬骨骼发育关键期：钙磷比需严格控制在 1.1:1~1.8:1（NRC 标准）。每 500g 食物建议添加约 2g 蛋壳粉（约 400mg 钙），具体剂量请咨询兽医。', daily: ['鸡胸肉 + 菠菜 + 红薯泥', '牛肉 + 西兰花 + 糙米饭', '羊肉 + 胡萝卜 + 燕麦'] },
    '成犬|小型犬': { meals: 2, protein: '鱼肉（Omega-3 美毛）', veggie: '西兰花', carb: '红薯', tip: '小型成犬代谢快，注意控制零食，避免超重～', daily: ['鱼肉 + 西兰花 + 红薯块', '鸡胸肉 + 南瓜 + 小米饭', '虾仁 + 胡萝卜 + 藜麦'] },
    '成犬|中型犬': { meals: 2, protein: '牛肉', veggie: '西兰花', carb: '红薯', tip: '每周 2-3 次红肉、1-2 次鱼类，食材轮换营养更均衡～', daily: ['牛肉 + 西兰花 + 红薯', '鸡腿肉 + 菠菜 + 糙米饭', '三文鱼 + 南瓜 + 燕麦'] },
    '成犬|大型犬': { meals: 2, protein: '牛肉', veggie: '胡萝卜', carb: '糙米', tip: '大型犬食量大，一次可备 2-3 天量分装冷冻，吃时加热～', daily: ['牛肉 + 胡萝卜 + 糙米饭', '鸡胸肉 + 菠菜 + 红薯', '羊肉 + 西兰花 + 藜麦'] },
    '老年犬|小型犬': { meals: 2, protein: '鱼肉', veggie: '菠菜', carb: '南瓜', tip: '老年牙口不好，食材要软烂细碎，南瓜和山药助消化～', daily: ['鱼肉 + 菠菜 + 南瓜羹', '鸡胸肉丝 + 胡萝卜泥 + 小米粥', '虾仁碎 + 西兰花 + 山药泥'] },
    '老年犬|中型犬': { meals: 2, protein: '鱼肉', veggie: '菠菜', carb: '糙米', tip: '老年代谢慢，蛋白质选低脂易消化的鱼肉和鸡胸肉为主～', daily: ['鱼肉 + 菠菜 + 糙米饭', '鸡胸肉 + 南瓜 + 小米粥', '牛肉末 + 胡萝卜 + 山药'] },
    '老年犬|大型犬': { meals: 2, protein: '鱼肉', veggie: '菠菜', carb: '糙米', tip: '老年大型犬关节负担重，鱼肉 Omega-3 有助抗炎护关节～', daily: ['鱼肉 + 菠菜 + 糙米饭', '鸡胸肉 + 西兰花 + 红薯', '瘦牛肉 + 南瓜 + 藜麦'] }
  };

  var FOOD_NUTRITION = {
    '鸡胸肉': { emoji: '🍗', protein: 23.0, fat: 1.5, carbs: 0 },
    '鸭肉': { emoji: '🦆', protein: 20.0, fat: 12.0, carbs: 0 },
    '牛肉': { emoji: '🥩', protein: 22.0, fat: 8.0, carbs: 0 },
    '瘦牛肉': { emoji: '🥩', protein: 22.0, fat: 8.0, carbs: 0 },
    '三文鱼': { emoji: '🐟', protein: 20.0, fat: 14.0, carbs: 0 },
    '鳕鱼': { emoji: '🐟', protein: 20.0, fat: 0.5, carbs: 0 },
    '虾仁': { emoji: '🦐', protein: 20.0, fat: 1.0, carbs: 0 },
    '蛋黄': { emoji: '🥚', protein: 16.0, fat: 27.0, carbs: 3.6 },
    '羊肉': { emoji: '🐑', protein: 20.0, fat: 14.0, carbs: 0 },
    '鸡腿肉': { emoji: '🍗', protein: 20.0, fat: 10.0, carbs: 0 },
    '南瓜': { emoji: '🎃', protein: 1.0, fat: 0.1, carbs: 7.0 },
    '胡萝卜': { emoji: '🥕', protein: 1.0, fat: 0.2, carbs: 10.0 },
    '西兰花': { emoji: '🥦', protein: 2.8, fat: 0.4, carbs: 7.0 },
    '菠菜': { emoji: '🥬', protein: 2.9, fat: 0.4, carbs: 3.6 },
    '西葫芦': { emoji: '🥒', protein: 1.2, fat: 0.3, carbs: 3.1 },
    '燕麦': { emoji: '🌾', protein: 13.5, fat: 6.5, carbs: 66.0 },
    '糙米': { emoji: '🍚', protein: 7.5, fat: 2.7, carbs: 73.0 },
    '红薯': { emoji: '🍠', protein: 1.6, fat: 0.1, carbs: 20.0 },
    '藜麦': { emoji: '🌾', protein: 14.0, fat: 6.0, carbs: 64.0 },
    '小米': { emoji: '🌾', protein: 11.0, fat: 4.0, carbs: 73.0 },
    '山药': { emoji: '🥔', protein: 2.0, fat: 0.2, carbs: 28.0 }
  };

  var ALLERGY_FOOD_MAP = {
    '鸡': ['鸡胸肉', '鸡腿肉', '鸡胸肉丁', '鸡胸肉丝', '蛋黄', '鸡蛋'],
    '鸡肉': ['鸡胸肉', '鸡腿肉', '鸡胸肉丁', '鸡胸肉丝'],
    '禽': ['鸡胸肉', '鸡腿肉', '鸭肉', '蛋黄'],
    '鱼': ['三文鱼', '鳕鱼', '鱼肉', '鱼肉碎', '虾仁'],
    '海鲜': ['三文鱼', '鳕鱼', '鱼肉', '虾仁'],
    '三文鱼': ['三文鱼'], '鳕鱼': ['鳕鱼'],
    '牛': ['牛肉', '瘦牛肉', '牛肉糜', '牛肉末'],
    '牛肉': ['牛肉', '瘦牛肉', '牛肉糜', '牛肉末'],
    '羊': ['羊肉'], '羊肉': ['羊肉'],
    '虾': ['虾仁', '虾仁碎'], '虾仁': ['虾仁'],
    '蛋': ['蛋黄', '鸡蛋'], '蛋黄': ['蛋黄'],
    '谷物': ['燕麦', '糙米', '小米', '藜麦'],
    '麦': ['燕麦', '藜麦', '小麦'], '米': ['糙米', '小米'],
    '奶': [], '乳': [], '大豆': [], '豆': []
  };

  var BREED_DIET_TIPS = {
    '法斗': '短鼻犬吃饭容易呛到，建议用小颗粒狗粮或把食物切碎；少食多餐有助于防止胀气和反流～',
    '英斗': '英斗容易发胖给关节增加负担，请严格控制每日喂食量，少给零食，用慢食碗能防止吃太快～',
    '巴哥': '巴哥也是短鼻犬，食物切小块更安全，体重管理很关键——过胖会进一步压迫呼吸！',
    '金毛': '金毛是著名「吃货」但容易吃出胰腺炎和髋关节问题，控制总热量、保持理想体重就是最好的保健品～',
    '拉布拉多': '拉布是贪吃界冠军，也是最容易肥胖的品种之一！严格控制喂食量，高油高脂的人食绝对禁止～',
    '德牧': '德牧肠胃较敏感，建议选择易消化的食材、添加益生菌。饭后至少休息 1 小时再运动，预防胃扭转！',
    '柯基': '柯基体质容易发胖，胖起来对长脊椎是灾难。每天精准称重喂食，零食控制在总热量 10% 以内～',
    '贵宾': '贵宾皮肤敏感，饮食中多加 Omega-3 脂肪酸（鱼油）有助于皮肤健康和毛发光泽～',
    '泰迪': '泰迪皮肤敏感，饮食中多加 Omega-3 脂肪酸（鱼油）有助于皮肤健康和毛发光泽～',
    '比熊': '比熊容易食物过敏导致皮肤痒，建议选择单一蛋白源的低敏配方，逐步排查过敏原～',
    '柴犬': '柴犬是过敏体质高发品种，如果频繁抓痒，可以尝试排除法饮食——从单一蛋白 + 单一碳水开始排查～',
    '豆柴': '柴犬是过敏体质高发品种，如果频繁抓痒，可以尝试排除法饮食——从单一蛋白 + 单一碳水开始排查～',
    '哈士奇': '哈士奇有锌缺乏倾向，可能导致皮肤问题和脱毛。饮食中可添加适量牛肉、羊肉等富锌食材～',
    '阿拉斯加': '阿拉斯加容易锌缺乏，牛肉、羊肉等红肉是补锌好选择。大型犬关节保护也很重要～',
    '杜宾': '杜宾心脏健康需关注牛磺酸摄入。鸡心、火鸡肉等富含牛磺酸，对心肌保护有帮助～',
    '边牧': '边牧运动量大、代谢率高，需要充足的优质蛋白维持肌肉和体力，运动日可适当增加喂食量～',
    '秋田': '秋田是深胸犬，胃扭转风险高于平均水平。每天 2-3 顿分食，饭后至少 1 小时不运动～',
    '松狮': '松狮容易过敏和皮肤问题，饮食以简单、天然为主，避免过多添加剂和频繁更换狗粮～',
    '大白熊': '大白熊是巨型犬，胃扭转风险不容忽视。每天分 2-3 顿喂，饭后至少休息 1.5 小时～',
    '萨摩耶': '萨摩耶有锌缺乏倾向，富锌食材（牛肉、羊肉）对皮肤和被毛健康很重要～',
    '博美': '博美气管脆弱，进食时不要催促，食物切小块防呛。维持理想体重也能减轻气管压力～',
    '吉娃娃': '吉娃娃嘴巴小、新陈代谢快，尤其幼犬时期容易低血糖。每天多分几顿，保证能量供应～',
    '约克夏': '约克夏牙齿容易出问题，不要长期只吃软食，适当给磨牙零食帮助洁牙～',
    '迷你雪纳瑞': '雪纳瑞易患胰腺炎和高血脂，饮食一定要低脂！避开肥肉、油炸食物，选择瘦蛋白来源～',
    '京巴': '京巴扁平脸吃饭费劲，食物切小、饭碗浅一些更容易吃到。保持体重对呼吸健康很重要～',
    '西施': '西施扁平脸和京巴类似，食物切小粒更方便。皮肤敏感，避开人工色素和防腐剂～',
    '马尔济斯': '马尔济斯几乎不掉毛但对添加剂敏感，选择天然成分的狗粮，泪痕问题和饮食也有关联～',
    '迷你杜宾': '迷你杜宾虽小但精力旺盛、代谢快，优质蛋白和适量脂肪能维持理想体态和能量～',
    '中华田园犬': '田园犬基因多样性高、消化能力通常不错，但也要避免喂人食（高盐高油），保持定时定量～',
    '银狐': '银狐双层被毛换毛量大，饮食中加 Omega-3 能让皮肤更健康、毛发更亮泽～',
    '比格': '比格也是超级吃货，嗅觉驱使它们到处找吃的！严格控制喂食量、少吃多餐，否则分分钟变胖～',
    '罗威纳': '罗威纳作为大型工作犬，幼犬期生长快但关节脆弱，不要过度补钙或喂食过多导致生长过快～'
  };

  /* ---------------- 初始演示数据 ---------------- */
  function createInitialState() {
    var today = todayISO();
    var state = {
      version: 2,
      pet: {
        id: 1,
        name: '团团',
        breed: '柯基',
        birthday: '2023-05-18',
        weight: '11.4',
        gender: 'female',
        neutered: '是',
        allergies: '牛肉, 鸡肉',
        diseases: '皮肤敏感',
        homeDate: daysAgoISO(840),
        bathIntervalDays: 24,
        lastBathDate: daysAgoISO(9),
        pawPoints: 128,
        createdAt: daysAgoISO(840)
      },
      events: [
        { id: 101, type: '疫苗', date: daysAgoISO(360), detail: { dose: '加强针', brand: '卫佳捌' } },
        { id: 102, type: '疫苗', date: daysAgoISO(725), detail: { dose: '第 3 针', brand: '' } },
        { id: 103, type: '驱虫', date: daysAgoISO(82), detail: { deworm_type: '体内外' } },
        { id: 104, type: '驱虫', date: daysAgoISO(175), detail: { deworm_type: '体内外' } },
        { id: 105, type: '驱虫', date: daysAgoISO(268), detail: { deworm_type: '体内' } },
        { id: 106, type: '驱虫', date: daysAgoISO(360), detail: { deworm_type: '体内外' } },
        { id: 107, type: '洗澡澡', date: daysAgoISO(9), detail: { note: '换季洗护，吹干后梳毛 10 分钟' } },
        { id: 108, type: '洗澡澡', date: daysAgoISO(33), detail: { note: '日常清洁' } },
        { id: 109, type: '洗澡澡', date: daysAgoISO(58), detail: { note: '夏季清洁' } },
        { id: 110, type: '洗澡澡', date: daysAgoISO(90), detail: {} },
        { id: 111, type: '洗澡澡', date: daysAgoISO(120), detail: {} },
        { id: 112, type: '异常行为', date: daysAgoISO(44), detail: { symptoms: ['抓痒'], note: '换季时背部轻微抓痒，已观察两天，无红肿' } },
        { id: 113, type: '异常行为', date: daysAgoISO(150), detail: { symptoms: ['拉稀'], note: '换粮后软便两天，补充益生菌后恢复' } },
        { id: 114, type: '每日检查', date: today, detail: { result: 'normal', note: '主人摸摸了头部、背部、四肢和腹部，一切正常 ✅' } }
      ],
      weightLogs: [
        { id: 201, date: daysAgoISO(3), weight: 11.4 },
        { id: 202, date: daysAgoISO(20), weight: 11.5 },
        { id: 203, date: daysAgoISO(45), weight: 11.6 },
        { id: 204, date: daysAgoISO(75), weight: 11.8 },
        { id: 205, date: daysAgoISO(105), weight: 11.9 },
        { id: 206, date: daysAgoISO(140), weight: 12.0 },
        { id: 207, date: daysAgoISO(175), weight: 12.2 },
        { id: 208, date: daysAgoISO(210), weight: 12.4 },
        { id: 209, date: daysAgoISO(250), weight: 12.6 },
        { id: 210, date: daysAgoISO(290), weight: 12.5 },
        { id: 211, date: daysAgoISO(330), weight: 12.0 },
        { id: 212, date: daysAgoISO(365), weight: 11.8 }
      ],
      bcsLogs: [
        { id: 301, date: daysAgoISO(20), state: 'ideal' },
        { id: 302, date: daysAgoISO(95), state: 'ideal' },
        { id: 303, date: daysAgoISO(170), state: 'heavy' }
      ],
      checkin: {
        streak: 12,
        lastCheckinDate: daysAgoISO(1),
        taskDoneDate: null,
        checkinDays: (function () {
          var arr = [];
          for (var i = 12; i >= 1; i--) arr.push(daysAgoISO(i));
          return arr;
        })(),
        taskDates: [daysAgoISO(2), daysAgoISO(4), daysAgoISO(6), daysAgoISO(9), daysAgoISO(12), daysAgoISO(15), daysAgoISO(18), daysAgoISO(21), daysAgoISO(24)]
      },
      badges: [
        { name: '初来乍到', date: daysAgoISO(840) },
        { name: '到家第一天', date: daysAgoISO(840) },
        { name: '第一针疫苗', date: daysAgoISO(725) },
        { name: '绝育勇敢', date: daysAgoISO(500) },
        { name: '第一次驱虫', date: daysAgoISO(360) },
        { name: '第一次洗澡', date: daysAgoISO(120) },
        { name: '体重管理', date: daysAgoISO(60) },
        { name: '守护之星', date: daysAgoISO(30) }
      ],
      pointsLog: [
        { date: daysAgoISO(1) + 'T20:12', amount: 1, reason: '签到' },
        { date: daysAgoISO(2) + 'T19:40', amount: 2, reason: '完成每日任务' },
        { date: daysAgoISO(4) + 'T08:31', amount: 1, reason: '记录健康事件' },
        { date: daysAgoISO(5) + 'T21:05', amount: 1, reason: '每日健康检查' },
        { date: daysAgoISO(9) + 'T18:20', amount: 1, reason: '记录健康事件' }
      ],
      doneReminders: {},
      riskLogs: [],
      suspendedUntil: null,
      nextEventId: 115,
      nextWeightId: 213,
      nextBcsId: 304,
      ui: { recipeIndex: 0, badgeTab: 'all', weightRange: 90 }
    };
    return state;
  }

  /* ---------------- 本地存储 ---------------- */
  function isValid(s) {
    return s && s.version === 2 && s.pet && Array.isArray(s.events) && Array.isArray(s.weightLogs) && s.checkin;
  }

  function ensureIds(state) {
    if (!state.ui) state.ui = { recipeIndex: 0, badgeTab: 'all', weightRange: 90 };
    if (!state.ui.badgeTab) state.ui.badgeTab = 'all';
    if (!state.ui.weightRange) state.ui.weightRange = 90;
    if (!state.bcsLogs) state.bcsLogs = [];
    if (!state.badges) state.badges = [];
    if (!state.pointsLog) state.pointsLog = [];
    if (!state.doneReminders) state.doneReminders = {};
    if (!state.riskLogs) state.riskLogs = [];
    if (!state.checkin) state.checkin = { streak: 0, lastCheckinDate: null, taskDoneDate: null, checkinDays: [], taskDates: [] };
    if (!state.checkin.checkinDays) state.checkin.checkinDays = [];
    if (!state.checkin.taskDates) state.checkin.taskDates = [];
    if (!state.nextWeightId) {
      state.nextWeightId = Math.max.apply(null, state.weightLogs.map(function (l) { return l.id || 0; }).concat([200])) + 1;
    }
    if (!state.nextBcsId) {
      state.nextBcsId = Math.max.apply(null, state.bcsLogs.map(function (l) { return l.id || 0; }).concat([300])) + 1;
    }
    if (!state.nextEventId) {
      state.nextEventId = Math.max.apply(null, state.events.map(function (e) { return e.id || 0; }).concat([100])) + 1;
    }
    return state;
  }

  var Store = {
    load: function () {
      try {
        var raw = localStorage.getItem(STORAGE_KEY);
        if (raw) {
          var parsed = JSON.parse(raw);
          if (isValid(parsed)) return ensureIds(parsed);
        }
      } catch (e) { /* 忽略损坏数据并按初始数据重置 */ }
      var fresh = createInitialState();
      Store.save(fresh);
      return fresh;
    },
    save: function (state) {
      try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); } catch (e) { /* 存储不可用时仅内存运行 */ }
    },
    reset: function () {
      try { localStorage.removeItem(STORAGE_KEY); } catch (e) { /* noop */ }
      var fresh = createInitialState();
      Store.save(fresh);
      return fresh;
    }
  };

  /* ---------------- 领域计算 ---------------- */
  function parseWeight(v) {
    if (v === null || v === undefined) return null;
    var n = parseFloat(String(v).replace(/kg|KG|Kg/g, '').trim());
    return isNaN(n) ? null : n;
  }

  function ageMonths(birthday) {
    if (!birthday) return 0;
    var b = parseISO(birthday);
    var t = new Date();
    return (t.getFullYear() - b.getFullYear()) * 12 + (t.getMonth() - b.getMonth());
  }

  function ageText(birthday) {
    var m = Math.max(0, ageMonths(birthday));
    if (m < 12) return m + ' 个月';
    var y = Math.floor(m / 12);
    var rest = m % 12;
    return rest ? y + ' 岁 ' + rest + ' 个月' : y + ' 岁';
  }

  function ageStage(birthday, breed) {
    var m = ageMonths(birthday);
    if (m <= 12) return '幼犬';
    var large = ['金毛', '拉布拉多', '德牧', '德国牧羊犬', '阿拉斯加', '萨摩耶', '罗威纳', '杜宾', '大白熊', '秋田', '哈士奇', '边牧', '松狮', '伯恩山', '大丹犬', '英斗'];
    var giant = ['大白熊', '伯恩山', '大丹犬', '阿拉斯加', '罗威纳'];
    var senior = (breed && giant.some(function (b) { return breed.indexOf(b) !== -1; })) ? 72
      : (breed && large.some(function (b) { return breed.indexOf(b) !== -1; })) ? 78 : 84;
    return m < senior ? '成犬' : '老年犬';
  }

  function bodySize(weightStr) {
    var kg = parseWeight(weightStr);
    if (kg === null) return '未知';
    if (kg < 5) return '小型犬';
    if (kg < 15) return '中型犬';
    return '大型犬';
  }

  function idealRange(breed) {
    return BREED_IDEAL_WEIGHT[breed] || null;
  }

  function calcRER(kg) {
    if (kg >= 2 && kg <= 45) return 30.0 * kg + 70.0;
    return 70.0 * Math.pow(kg, 0.75);
  }

  function normalizeFood(name) {
    if (!name) return '';
    var clean = String(name).replace(/[（(][^)）]*[)）]/g, '').trim();
    var aliases = {
      '鱼肉': '三文鱼', '鱼肉碎': '三文鱼', '牛肉糜': '牛肉',
      '鸡胸肉丁': '鸡胸肉', '鸡胸肉丝': '鸡胸肉',
      '虾仁碎': '虾仁', '牛肉末': '牛肉', '瘦牛肉': '牛肉'
    };
    return aliases[clean] || clean;
  }

  function filterAllergen(foodName, allergiesStr) {
    if (!allergiesStr || !allergiesStr.trim()) return true;
    var keys = allergiesStr.replace(/，/g, ',').split(',').map(function (s) { return s.trim(); }).filter(Boolean);
    var exclude = {};
    keys.forEach(function (key) {
      if (ALLERGY_FOOD_MAP[key]) {
        ALLERGY_FOOD_MAP[key].forEach(function (f) { exclude[f] = true; });
      } else {
        Object.keys(FOOD_NUTRITION).forEach(function (food) {
          if (food.indexOf(key) !== -1) exclude[food] = true;
        });
      }
    });
    return !exclude[foodName];
  }

  function safeFallback(allergiesStr, category) {
    var candidates = category === 'protein'
      ? ['鸡胸肉', '鸭肉', '牛肉', '三文鱼', '羊肉', '鳕鱼', '虾仁']
      : category === 'veggie'
        ? ['南瓜', '胡萝卜', '西兰花', '菠菜', '西葫芦']
        : ['红薯', '糙米', '燕麦', '南瓜', '藜麦', '小米', '山药'];
    for (var i = 0; i < candidates.length; i++) {
      if (filterAllergen(candidates[i], allergiesStr)) return candidates[i];
    }
    return candidates[0];
  }

  function allergenMatches(text, allergiesStr) {
    if (!text || !allergiesStr || !allergiesStr.trim()) return false;
    var keys = allergiesStr.replace(/，/g, ',').split(',').map(function (s) { return s.trim(); }).filter(Boolean);
    for (var i = 0; i < keys.length; i++) {
      var key = keys[i];
      if (text.indexOf(key) !== -1) return true;
      var mapped = ALLERGY_FOOD_MAP[key];
      if (mapped && mapped.some(function (f) { return text.indexOf(f) !== -1; })) return true;
    }
    return false;
  }

  function filterOptions(optionsStr, allergiesStr) {
    if (!allergiesStr || !allergiesStr.trim()) return optionsStr;
    var items = optionsStr.split(/[、,，]/).map(function (s) { return s.trim(); }).filter(Boolean);
    var kept = items.filter(function (item) { return filterAllergen(item, allergiesStr); });
    return kept.length ? kept.join('、') : '暂无安全选项';
  }

  function calcPlan(pet) {
    var kg = parseWeight(pet.weight);
    if (kg === null || kg <= 0) return null;
    var rer = calcRER(kg);
    var stage = ageStage(pet.birthday);
    var coeff = stage === '幼犬' ? 2.5 : (pet.neutered === '是' ? 1.6 : 1.8);
    var genderCoeff = pet.gender === 'male' ? 1.1 : 1.0;
    var der = rer * coeff * genderCoeff;
    var total = Math.round(der / 1.5);
    return {
      weightKg: kg,
      rer: Math.round(rer),
      rerRaw: rer,
      coefficient: coeff,
      genderCoefficient: genderCoeff,
      der: Math.round(der),
      derRaw: der,
      totalG: total,
      proteinG: Math.round(total * 0.55),
      carbG: Math.round(total * 0.25),
      veggieG: Math.round(total * 0.15),
      stage: stage,
      size: bodySize(pet.weight)
    };
  }

  function dietPlan(pet) {
    var plan = calcPlan(pet);
    if (!plan) return null;
    var stage = ageStage(pet.birthday, pet.breed);
    var size = bodySize(pet.weight);
    var foods = DIET_FOODS[stage + '|' + size];
    if (!foods) return null;
    var allergies = pet.allergies || '';
    var protein = normalizeFood(foods.protein);
    var veggie = normalizeFood(foods.veggie);
    var carb = normalizeFood(foods.carb);
    if (!filterAllergen(protein, allergies)) protein = safeFallback(allergies, 'protein');
    if (!filterAllergen(veggie, allergies)) veggie = safeFallback(allergies, 'veggie');
    if (!filterAllergen(carb, allergies)) carb = safeFallback(allergies, 'carb');

    var meals = foods.meals;
    var portions = {
      protein: Math.round(plan.proteinG / meals),
      veggie: Math.round(plan.veggieG / meals),
      carb: Math.round(plan.carbG / meals)
    };

    function build(name, grams) {
      var nut = FOOD_NUTRITION[name] || FOOD_NUTRITION['鸡胸肉'];
      var f = grams / 100;
      return {
        name: name,
        emoji: nut.emoji,
        grams: grams,
        protein: Math.round(nut.protein * f * 10) / 10,
        fat: Math.round(nut.fat * f * 10) / 10,
        carbs: Math.round(nut.carbs * f * 10) / 10
      };
    }

    var items = [build(protein, portions.protein), build(veggie, portions.veggie), build(carb, portions.carb)];
    var totalWeight = items.reduce(function (a, b) { return a + b.grams; }, 0);
    var totalProtein = Math.round(items.reduce(function (a, b) { return a + b.protein; }, 0) * 10) / 10;
    var totalFat = Math.round(items.reduce(function (a, b) { return a + b.fat; }, 0) * 10) / 10;
    var totalCarbs = Math.round(items.reduce(function (a, b) { return a + b.carbs; }, 0) * 10) / 10;

    var proteinOptions = size === '小型犬'
      ? '鸡胸肉、鱼肉、虾仁、蛋黄、鸭肉'
      : '鸡胸肉、鸭肉、瘦牛肉、三文鱼、鳕鱼';

    var breedTip = '';
    if (pet.breed) {
      Object.keys(BREED_DIET_TIPS).forEach(function (key) {
        if (!breedTip && pet.breed.indexOf(key) !== -1) breedTip = BREED_DIET_TIPS[key];
      });
    }

    return {
      plan: plan,
      foods: foods,
      items: items,
      meals: meals,
      mealName: items.map(function (i) { return i.name; }).join('') + '饭',
      totalWeight: totalWeight,
      totalProtein: totalProtein,
      totalFat: totalFat,
      totalCarbs: totalCarbs,
      allergyNote: allergies ? '已避开过敏源（' + allergies + '），并替换为安全食材。' : '',
      proteinOptions: filterOptions(proteinOptions, allergies),
      carbOptions: filterOptions('糙米、燕麦、红薯、南瓜、藜麦', allergies),
      veggieOptions: filterOptions('胡萝卜、西兰花、菠菜、西葫芦、南瓜', allergies),
      breedTip: breedTip,
      fishOil: plan.weightKg < 15 ? '0.5ml / 5kg 体重，每周 2-3 次' : '1ml / 5kg 体重，每周 2-3 次',
      hypoglycemiaNote: (plan.weightKg < 2 && plan.stage === '幼犬')
        ? '超小型幼犬（<2kg）有低血糖风险，建议每天进食 6-8 次；若出现精神萎靡、走路不稳，请立即联系兽医。' : ''
    };
  }

  /* ---------------- 提醒计算 ---------------- */
  function lastEventOfType(state, type) {
    var list = state.events.filter(function (e) { return e.type === type; });
    if (!list.length) return null;
    return list.slice().sort(function (a, b) { return a.date < b.date ? 1 : -1; })[0];
  }

  function isDoneToday(state, id) {
    var t = todayISO();
    return !!(state.doneReminders[t] && state.doneReminders[t].indexOf(id) !== -1);
  }

  function markReminderDone(state, id, done) {
    var t = todayISO();
    if (!state.doneReminders[t]) state.doneReminders[t] = [];
    var arr = state.doneReminders[t];
    var idx = arr.indexOf(id);
    if (done && idx === -1) arr.push(id);
    if (!done && idx !== -1) arr.splice(idx, 1);
  }

  function statusOf(daysLeft, soonWindow) {
    if (daysLeft < 0) return 'overdue';
    if (daysLeft <= soonWindow) return 'soon';
    return 'ok';
  }

  function reminderItem(state, opts) {
    return {
      id: opts.id,
      category: opts.category,
      title: opts.title,
      desc: opts.desc,
      daysLeft: opts.daysLeft,
      status: opts.status,
      actionPage: opts.actionPage || null,
      actionText: opts.actionText || '去处理',
      done: isDoneToday(state, opts.id),
      completable: opts.completable !== false,
      icon: opts.icon || '📌'
    };
  }

  function buildReminders(state) {
    var pet = state.pet;
    var list = [];
    var months = ageMonths(pet.birthday);

    var lastVax = lastEventOfType(state, '疫苗');
    if (lastVax) {
      var nextVax = addDaysISO(lastVax.date, 365);
      var vaxLeft = diffDays(nextVax, todayISO());
      list.push(reminderItem(state, {
        id: 'vaccine', category: '疫苗', icon: '💉', title: '疫苗加强',
        desc: '上次接种 ' + lastVax.date + '，下次建议 ' + nextVax + '。不同疫苗加强周期不同，请遵医嘱。',
        daysLeft: vaxLeft, status: statusOf(vaxLeft, 30), actionPage: 'records', actionText: '去记录'
      }));
    } else {
      list.push(reminderItem(state, {
        id: 'vaccine', category: '疫苗', icon: '💉', title: '还没有疫苗记录',
        desc: '建议完成首次接种后在此查看提醒。', daysLeft: null, status: 'none', actionPage: 'records', actionText: '去记录'
      }));
    }

    var lastDeworm = lastEventOfType(state, '驱虫');
    var dewormInterval = months < 6 ? 30 : 90;
    if (lastDeworm) {
      var nextDeworm = addDaysISO(lastDeworm.date, dewormInterval);
      var dewormLeft = diffDays(nextDeworm, todayISO());
      list.push(reminderItem(state, {
        id: 'deworm', category: '驱虫', icon: '🛡️', title: '体内外驱虫',
        desc: '上次驱虫 ' + lastDeworm.date + '，间隔 ' + dewormInterval + ' 天，下次建议 ' + nextDeworm + '。',
        daysLeft: dewormLeft, status: statusOf(dewormLeft, 14), actionPage: 'records', actionText: '去记录'
      }));
    } else {
      list.push(reminderItem(state, {
        id: 'deworm', category: '驱虫', icon: '🛡️', title: '还没有驱虫记录',
        desc: '体内外驱虫应从小开始，建议完成首次驱虫后在此查看。', daysLeft: null, status: 'none', actionPage: 'records', actionText: '去记录'
      }));
    }

    var bathInterval = pet.bathIntervalDays || 24;
    if (pet.lastBathDate) {
      var nextBath = addDaysISO(pet.lastBathDate, bathInterval);
      var bathLeft = diffDays(nextBath, todayISO());
      list.push(reminderItem(state, {
        id: 'bath', category: '洗澡', icon: '🛁', title: '洗澡护理',
        desc: '上次洗澡 ' + pet.lastBathDate + '，建议间隔 ' + bathInterval + ' 天，下次 ' + nextBath + '。',
        daysLeft: bathLeft, status: statusOf(bathLeft, 7), actionPage: 'records', actionText: '去记录'
      }));
    } else {
      list.push(reminderItem(state, {
        id: 'bath', category: '洗澡', icon: '🛁', title: '还没有洗澡记录',
        desc: '记录第一次洗澡后，会按品种与体重生成洗护间隔。', daysLeft: null, status: 'none', actionPage: 'records', actionText: '去记录'
      }));
    }

    var weights = state.weightLogs.slice().sort(function (a, b) { return a.date < b.date ? 1 : -1; });
    if (weights.length) {
      var lastW = weights[0];
      var maxGap = months < 12 ? 10 : 35;
      var nextW = addDaysISO(lastW.date, maxGap);
      var wLeft = diffDays(nextW, todayISO());
      list.push(reminderItem(state, {
        id: 'weight', category: '体重', icon: '⚖️', title: '体重记录',
        desc: '上次记录 ' + lastW.date + '（' + lastW.weight + 'kg），建议每 ' + maxGap + ' 天记录一次。',
        daysLeft: wLeft, status: statusOf(wLeft, 7), actionPage: 'trends', actionText: '去记录'
      }));
    } else {
      list.push(reminderItem(state, {
        id: 'weight', category: '体重', icon: '⚖️', title: '开始记录体重',
        desc: '定期记录体重可以及时发现健康问题。', daysLeft: null, status: 'none', actionPage: 'trends', actionText: '去记录'
      }));
    }

    var bcs = state.bcsLogs.slice().sort(function (a, b) { return a.date < b.date ? 1 : -1; });
    var lastBcs = bcs[0];
    var bcsInterval = lastBcs && lastBcs.state !== 'ideal' ? 14 : 30;
    if (lastBcs) {
      var nextBcs = addDaysISO(lastBcs.date, bcsInterval);
      var bLeft = diffDays(nextBcs, todayISO());
      list.push(reminderItem(state, {
        id: 'bcs', category: '体况', icon: '🤚', title: 'BCS 体况复查',
        desc: '上次评估 ' + lastBcs.date + '，' + (lastBcs.state === 'ideal' ? '建议 30 天复查。' : '偏瘦或偏重建议 14 天复查。'),
        daysLeft: bLeft, status: statusOf(bLeft, 7), actionPage: 'trends', actionText: '去评估'
      }));
    } else {
      list.push(reminderItem(state, {
        id: 'bcs', category: '体况', icon: '🤚', title: '做一次 BCS 评估',
        desc: '触摸肋骨与腰线，判断当前体况。', daysLeft: null, status: 'none', actionPage: 'trends', actionText: '去评估'
      }));
    }

    return list;
  }

  function dailyCheckDone(state) {
    var t = todayISO();
    return state.events.some(function (e) { return e.type === '每日检查' && e.date === t; });
  }

  function checkedToday(state) {
    return state.checkin.lastCheckinDate === todayISO();
  }

  function currentStreak(state) {
    if (checkedToday(state)) return state.checkin.streak;
    if (state.checkin.lastCheckinDate === daysAgoISO(1)) return state.checkin.streak;
    return 0;
  }

  function taskDoneToday(state) {
    return state.checkin.taskDoneDate === todayISO();
  }

  function todayTask(state) {
    var d = new Date();
    var seed = d.getFullYear() * 10000 + (d.getMonth() + 1) * 100 + d.getDate() + 13;
    return DAILY_TASKS[seed % DAILY_TASKS.length];
  }

  function addPoints(state, amount, reason) {
    state.pet.pawPoints = (state.pet.pawPoints || 0) + amount;
    state.pointsLog.unshift({ date: nowISO(), amount: amount, reason: reason });
    if (state.pointsLog.length > 60) state.pointsLog.length = 60;
  }

  /* ---------------- 勋章判定（移植核心条件） ---------------- */
  function weightInRange(weightStr, low, high) {
    var v = parseWeight(weightStr);
    if (v === null) return false;
    return v >= low * 0.85 && v <= high * 1.15;
  }

  function checkBadges(state) {
    var pet = state.pet;
    var today = todayISO();
    var unlocked = {};
    state.badges.forEach(function (b) { unlocked[b.name] = true; });
    var newOnes = [];

    function unlock(name) {
      if (unlocked[name]) return;
      var def = BADGES.filter(function (b) { return b.name === name; })[0];
      if (!def) return;
      state.badges.push({ name: name, date: today });
      unlocked[name] = true;
      newOnes.push(def);
    }

    var vc = state.events.filter(function (e) { return e.type === '疫苗'; }).length;
    var dc = state.events.filter(function (e) { return e.type === '驱虫'; }).length;
    var bathCount = state.events.filter(function (e) { return e.type === '洗澡澡'; }).length;

    unlock('初来乍到');
    if (vc >= 1) unlock('第一针疫苗');
    if (dc >= 1) unlock('第一次驱虫');
    if (bathCount >= 1) unlock('第一次洗澡');
    if (pet.homeDate) unlock('到家第一天');
    if (vc >= 3) unlock('免疫完成');
    if (dc >= 6) unlock('驱虫达标');

    var monthAgo = daysAgoISO(30);
    var tasksIn30 = state.checkin.taskDates.filter(function (d) { return d >= monthAgo; }).length;
    if (tasksIn30 >= 15) unlock('洁齿坚持');

    var abnormal = state.events.filter(function (e) { return e.type === '异常行为'; })
      .sort(function (a, b) { return a.date < b.date ? 1 : -1; });
    if (abnormal.length && diffDays(today, abnormal[0].date) >= 60) unlock('肠胃稳定');

    var range = idealRange(pet.breed);
    if (range) {
      var logs = state.weightLogs.slice().sort(function (a, b) { return a.date < b.date ? -1 : 1; });
      if (logs.length >= 3 && diffDays(logs[logs.length - 1].date, logs[0].date) >= 90
        && logs.every(function (l) { return weightInRange(String(l.weight), range[0], range[1]); })) {
        unlock('体重管理');
      }
    }

    var bcs = state.bcsLogs.slice().sort(function (a, b) { return a.date < b.date ? 1 : -1; });
    if (bcs.length >= 3 && bcs.slice(0, 3).every(function (l) { return l.state === 'ideal'; })) unlock('体态管理');

    if (pet.birthday && pet.birthday.slice(5) === today.slice(5) && checkedToday(state)) unlock('生日快乐');
    if (pet.neutered === '是') unlock('绝育勇敢');
    if (pet.createdAt && diffDays(today, pet.createdAt) >= 100 && checkedToday(state)) unlock('百日相伴');

    var guardians = BADGES.filter(function (b) { return b.category === '守护者'; });
    if (guardians.every(function (b) { return unlocked[b.name]; })) unlock('健康大满贯');
    if ((pet.pawPoints || 0) >= 30) unlock('守护之星');

    return newOnes;
  }

  /* ---------------- 操作 ---------------- */
  function recordCheckin(state) {
    if (checkedToday(state)) return { already: true };
    var today = todayISO();
    var yesterday = daysAgoISO(1);
    state.checkin.streak = state.checkin.lastCheckinDate === yesterday ? state.checkin.streak + 1 : 1;
    state.checkin.lastCheckinDate = today;
    if (state.checkin.checkinDays.indexOf(today) === -1) state.checkin.checkinDays.push(today);
    addPoints(state, 1, '签到');
    return { already: false, streak: state.checkin.streak };
  }

  function completeTask(state) {
    if (taskDoneToday(state)) return { already: true };
    var autoChecked = false;
    if (!checkedToday(state)) {
      recordCheckin(state);
      autoChecked = true;
    }
    var task = todayTask(state);
    state.checkin.taskDoneDate = todayISO();
    if (state.checkin.taskDates.indexOf(todayISO()) === -1) state.checkin.taskDates.push(todayISO());
    addPoints(state, 2, '完成每日任务');
    return { already: false, autoChecked: autoChecked, task: task };
  }

  function recordDailyCheck(state, result, note) {
    var today = todayISO();
    if (dailyCheckDone(state)) return { already: true };
    var text = result === 'normal'
      ? '主人摸摸了头部、背部、四肢和腹部，一切正常 ✅'
      : (note || '主人发现异常，需要进一步检查 ⚠️');
    var event = {
      id: state.nextEventId++,
      type: '每日检查',
      date: today,
      detail: { result: result, note: text }
    };
    state.events.unshift(event);
    addPoints(state, 1, '每日健康检查');
    return { already: false, event: event };
  }

  function scanHighRisk(text) {
    for (var i = 0; i < HIGH_RISK_SYMPTOMS.length; i++) {
      if (text.indexOf(HIGH_RISK_SYMPTOMS[i]) !== -1) return HIGH_RISK_SYMPTOMS[i];
    }
    return null;
  }

  function addEvent(state, payload) {
    var event = {
      id: state.nextEventId++,
      type: payload.type,
      date: payload.date || todayISO(),
      detail: payload.detail || {}
    };
    if (payload.highRisk) {
      event.high_risk = 1;
      event.risk_keyword = payload.riskKeyword || '';
      state.riskLogs.unshift({
        date: event.date,
        keyword: payload.riskKeyword || '',
        text: (payload.detail && payload.detail.note) || '',
        highRisk: true
      });
      state.suspendedUntil = todayISO();
    }
    state.events.unshift(event);
    if (event.type === '洗澡澡') state.pet.lastBathDate = event.date;
    addPoints(state, 1, '记录健康事件');
    var newBadges = checkBadges(state);
    return { event: event, newBadges: newBadges };
  }

  function addWeight(state, weightStr, dateStr) {
    var kg = parseWeight(weightStr);
    if (kg === null || kg <= 0) return { error: '请输入有效的体重数值' };
    var date = dateStr || todayISO();
    var existing = state.weightLogs.filter(function (l) { return l.date === date; })[0];
    if (existing) {
      existing.weight = kg;
    } else {
      state.weightLogs.push({ id: state.nextWeightId++, date: date, weight: kg });
    }
    var latest = state.weightLogs.slice().sort(function (a, b) { return a.date < b.date ? 1 : -1; })[0];
    state.pet.weight = String(latest.weight);
    var newBadges = checkBadges(state);
    return { weight: kg, date: date, newBadges: newBadges };
  }

  function recordBCS(state, bcsState, dateStr) {
    var date = dateStr || todayISO();
    var existing = state.bcsLogs.filter(function (l) { return l.date === date; })[0];
    if (existing) existing.state = bcsState;
    else state.bcsLogs.push({ id: state.nextBcsId++, date: date, state: bcsState });
    var newBadges = checkBadges(state);
    return { newBadges: newBadges };
  }

  function updateEvent(state, id, payload) {
    var event = state.events.filter(function (e) { return e.id === id; })[0];
    if (!event) return { error: '找不到这条记录' };
    event.type = payload.type;
    event.date = payload.date;
    event.detail = payload.detail || {};
    if (payload.highRisk) {
      event.high_risk = 1;
      event.risk_keyword = payload.riskKeyword || '';
      state.suspendedUntil = todayISO();
      state.riskLogs.unshift({
        date: event.date,
        keyword: payload.riskKeyword || '',
        text: (payload.detail && payload.detail.note) || '',
        highRisk: true
      });
    } else {
      delete event.high_risk;
      delete event.risk_keyword;
    }
    var lastBath = state.events.filter(function (e) { return e.type === '洗澡澡'; })
      .sort(function (a, b) { return a.date < b.date ? 1 : -1; })[0];
    state.pet.lastBathDate = lastBath ? lastBath.date : null;
    var newBadges = checkBadges(state);
    return { event: event, newBadges: newBadges };
  }

  function unlockedBadge(state, name) {
    return state.badges.filter(function (b) { return b.name === name; })[0] || null;
  }

  function nextBadgeInfo(state) {
    var vc = state.events.filter(function (e) { return e.type === '疫苗'; }).length;
    var dc = state.events.filter(function (e) { return e.type === '驱虫'; }).length;
    var taskCount = state.checkin.taskDates.filter(function (d) { return d >= daysAgoISO(30); }).length;
    var bcsIdeal = state.bcsLogs.slice().sort(function (a, b) { return a.date < b.date ? 1 : -1; })
      .slice(0, 3).filter(function (l) { return l.state === 'ideal'; }).length;
    var guardians = BADGES.filter(function (b) { return b.category === '守护者'; });
    var unlockedGuardians = guardians.filter(function (b) { return unlockedBadge(state, b.name); }).length;
    var candidates = [
      { name: '免疫完成', have: vc, need: 3, unit: '次疫苗' },
      { name: '驱虫达标', have: dc, need: 6, unit: '次驱虫' },
      { name: '洁齿坚持', have: taskCount, need: 15, unit: '次任务' },
      { name: '体态管理', have: bcsIdeal, need: 3, unit: '次理想 BCS' },
      { name: '健康大满贯', have: unlockedGuardians, need: guardians.length, unit: '枚守护者勋章' }
    ].filter(function (c) { return !unlockedBadge(state, c.name); });
    if (!candidates.length) return null;
    candidates.sort(function (a, b) { return (b.have / b.need) - (a.have / a.need); });
    var best = candidates[0];
    var def = BADGES.filter(function (b) { return b.name === best.name; })[0];
    best.def = def;
    best.pct = Math.min(100, Math.round(best.have / best.need * 100));
    return best;
  }

  function daysTogether(state) {
    if (!state.pet.createdAt) return 0;
    return Math.max(0, diffDays(todayISO(), state.pet.createdAt));
  }

  /* ---------------- 保健品规则（移植自后端） ---------------- */
  function calcSupplements(state) {
    var pet = state.pet;
    var months = ageMonths(pet.birthday);
    var stage = ageStage(pet.birthday, pet.breed);
    var kg = parseWeight(pet.weight);
    var abnormal = state.events.filter(function (e) { return e.type === '异常行为'; });
    var scratch = 0, vomit = 0, diarrhea = 0;
    abnormal.forEach(function (e) {
      var d = e.detail || {};
      var text = ((d.symptoms || []).join(' ') + ' ' + (d.note || '')).toLowerCase();
      if (text.indexOf('抓痒') !== -1 || text.indexOf('挠') !== -1 || text.indexOf('scratch') !== -1) scratch++;
      if (text.indexOf('吐') !== -1 || text.indexOf('vomit') !== -1) vomit++;
      if (text.indexOf('拉稀') !== -1 || text.indexOf('腹泻') !== -1 || text.indexOf('diarrhea') !== -1) diarrhea++;
    });
    var diseases = (pet.diseases || '').toLowerCase();
    var allergies = pet.allergies || '';
    var allergiesLower = allergies.toLowerCase();
    var hasFish = ['鱼', '海鲜', '三文鱼', '鳕鱼'].some(function (k) { return allergiesLower.indexOf(k) !== -1; });
    var merged = {};

    function add(key, name, reason, woof, priority, icon) {
      if (hasFish && name.indexOf('鱼油') !== -1) return;
      if (!merged[key]) {
        merged[key] = { key: key, name: name, reasons: [reason], woof: woof, priority: priority, icon: icon };
      } else {
        var item = merged[key];
        if (item.reasons.indexOf(reason) === -1) item.reasons.push(reason);
        if (priority < item.priority) {
          item.priority = priority;
          item.name = name;
          item.woof = woof;
        }
      }
    }

    var shortBody = ['柯基', '法斗', '英斗', '京巴', '西施'];
    var curly = ['贵宾', '泰迪', '比熊', '马尔济斯', '迷你雪纳瑞', '约克夏'];
    var skinBreeds = ['法斗', '英斗', '巴哥', '京巴', '西施'];
    var eyeBreeds = ['巴哥', '京巴', '西施', '比熊', '马尔济斯'];
    var heartBreeds = ['杜宾', '金毛', '拉布拉多', '德牧', '德国牧羊犬', '大丹犬'];
    function breedIn(list) {
      return pet.breed && list.some(function (b) { return pet.breed.indexOf(b) !== -1; });
    }

    if (stage === '老年犬') {
      add('joint', '关节保护 + 抗氧化剂（葡萄糖胺、维生素E、辅酶Q10）', '老年关节退化、免疫力下降，需综合养护', '我步入黄金老年啦，关节需要好好养护，再来点抗氧化的东西，让我老得慢一点～', 1, '🦴');
      add('multi', '综合维生素/矿物质', '老年犬营养吸收能力下降，建议综合补充', '年纪大了，吃饭吸收不如从前，综合营养能帮我补齐缺口～', 2, '💊');
    }
    if (breedIn(shortBody) && months >= 12) {
      add('joint', '关节保护（葡萄糖胺 + 软骨素，尤其脊椎）', '短腿长身犬种易患椎间盘疾病', '我们短腿家族腰背容易受伤，日常的关节保健品可不能停哦。', 1, '🦴');
    }
    if (kg !== null && kg >= 30 && months >= 12) {
      add('joint', '关节保护（葡萄糖胺 + 软骨素）', '体重对关节压力大，需额外保护', '我太壮啦，关节天天扛着我跑，得补补！', 2, '🦴');
    }
    if (stage === '幼犬') {
      add('multi', '综合维生素/矿物质（钙磷比均衡）', '生长发育期需均衡营养（若吃市售全价狗粮则通常无需额外补充）', '我正在长身体～如果主人给我吃的是自制狗饭，可以加一点综合营养粉；如果吃的是市售全价狗粮，一般不需要额外补哦，具体听兽医的！', 1, '💊');
    }
    if (scratch >= 2) {
      add('skin', 'Omega-3 鱼油', '曾有多次抓痒记录，皮肤干燥或过敏瘙痒', '我之前老是挠痒痒，鱼油可以让我的皮肤不那么干痒，毛也亮！', 2, '🐟');
    }
    if (vomit >= 1 || diarrhea >= 1) {
      add('digest', '益生菌', '曾有呕吐/腹泻记录，需调理肠胃', '上次吐/拉肚子好难受，每天吃点益生菌，肚子会舒服很多～', 2, '🥛');
    }
    if (breedIn(curly) && months >= 6) {
      add('beauty', '美毛产品（卵磷脂 + 生物素）', '卷毛易打结、皮肤脆弱，需养护毛发', '我这一身卷毛要勤打理，吃点美毛的，梳毛时就不会那么疼啦。', 3, '✨');
    }
    if (pet.gender === 'female' && pet.neutered !== '是' && months >= 36) {
      add('urinary', '蔓越莓提取物（泌尿/生殖健康）', '未绝育母犬随年龄增长，子宫蓄脓和泌尿道感染风险增加', '主人，我还没绝育，年纪大了尿尿的地方容易不舒服，给我吃点蔓越莓保护一下吧～', 2, '💧');
    }
    if (pet.gender === 'male' && pet.neutered !== '是' && months >= 36) {
      add('prostate', '南瓜籽提取物（前列腺保健）', '未绝育公犬易出现前列腺肥大等问题', '主人，我们没绝育的男孩子，前列腺要早点保养，南瓜籽就很好哦～', 2, '🌰');
    }
    if (breedIn(skinBreeds) && months >= 6) {
      add('skin', '皮肤养护（Omega-3 鱼油 + 维生素E）', '皮肤皱褶多/敏感品种易患皮炎，需养护皮肤屏障', '我们这种皮肤敏感的狗狗，Omega-3 加维E能让皮肤抵抗力更强，减少痒痒和红疹～', 2, '🐟');
    }
    if (breedIn(eyeBreeds) && months >= 12) {
      add('eye', '眼部护理（叶黄素 + 维生素A + Omega-3）', '眼球突出/大眼睛品种易患角膜损伤、干眼症和泪痕问题', '我的大眼睛虽然萌萌的但也脆弱，容易干涩和流眼泪。叶黄素和维A能保护我的视力和角膜健康哦～', 2, '👁️');
    }
    if (breedIn(heartBreeds) && months >= 24) {
      add('heart', '心脏保健（辅酶Q10 + 牛磺酸 + 左旋肉碱）', '大型/巨型犬扩张型心肌病(DCM)风险较高，需心脏保养', '像我们这样的大型犬，心脏要扛起整个身体很辛苦的。辅酶Q10和牛磺酸能帮心脏跳得更有力～', 1, '❤️');
    }

    if (/关节|髋|髌骨|跛行|arthritis/.test(diseases)) {
      add('joint', '关节保护（葡萄糖胺 + 软骨素）', '档案中有关节相关病史，需特别关注关节养护', '主人，我以前的关节不舒服过，日常养护可不能偷懒哦～', 1, '🦴');
    }
    if (/心脏|心|heart|dcm/.test(diseases)) {
      add('heart', '心脏保护（辅酶Q10 + 牛磺酸 + 左旋肉碱）', '档案中有心脏相关病史，需关注心脏健康', '主人，保护心脏要从日常做起，辅酶Q10对我很重要～', 1, '❤️');
    }
    if (/皮肤|过敏|皮炎|红疹|痒|allergy|skin/.test(diseases)) {
      add('skin', '皮肤养护（Omega-3 鱼油 + 维生素E）', '档案中有皮肤或过敏相关病史', '主人，皮肤问题容易反复，Omega-3 能让我的皮肤更健康～', 2, '🐟');
    }
    if (/胰腺|pancreatitis/.test(diseases)) {
      add('digest', '消化养护（益生菌 + 消化酶）', '档案中有胰腺相关病史，需低脂饮食和消化支持', '主人，我的胰腺需要特别呵护，益生菌和低脂饮食对我很重要～', 1, '🥛');
    }
    if (/眼|白内障|青光眼|视力/.test(diseases)) {
      add('eye', '眼部护理（叶黄素 + 维生素A + Omega-3）', '档案中有眼部相关病史，需加强眼部保健', '主人，保护眼睛从现在开始，叶黄素对我很重要～', 2, '👁️');
    }

    var month = new Date().getMonth() + 1;
    if (month >= 6 && month <= 8 || month === 12 || month === 1 || month === 2) {
      if (merged.joint) merged.joint.priority -= 0.5;
      if (merged.skin) merged.skin.priority -= 0.5;
    }

    var list = Object.keys(merged).map(function (k) { return merged[k]; })
      .sort(function (a, b) { return a.priority - b.priority; });

    list.forEach(function (item) {
      item.reasonText = item.reasons.join('；');
      item.woofFull = item.woof + '（参考剂量请遵兽医指导，不可用人用保健品替代）';
      if (allergies) item.woofFull += ' ⚠️ 选择产品时请避开：' + allergies + '。';
    });
    return list;
  }

  function latestWeight(state) {
    var logs = state.weightLogs.slice().sort(function (a, b) { return a.date < b.date ? -1 : 1; });
    return logs.length ? logs[logs.length - 1] : null;
  }

  function latestBCS(state) {
    var logs = state.bcsLogs.slice().sort(function (a, b) { return a.date < b.date ? -1 : 1; });
    return logs.length ? logs[logs.length - 1] : null;
  }

  function weightStats(logs, days) {
    var cutoff = daysAgoISO(days);
    var filtered = logs.filter(function (l) { return l.date >= cutoff; })
      .slice().sort(function (a, b) { return a.date < b.date ? -1 : 1; });
    if (!filtered.length) return null;
    var values = filtered.map(function (l) { return Number(l.weight); });
    var sum = values.reduce(function (a, b) { return a + b; }, 0);
    return {
      logs: filtered,
      latest: values[values.length - 1],
      first: values[0],
      change: Math.round((values[values.length - 1] - values[0]) * 10) / 10,
      min: Math.min.apply(null, values),
      max: Math.max.apply(null, values),
      avg: Math.round((sum / values.length) * 10) / 10
    };
  }

  function tipOfToday() {
    var seed = new Date().getFullYear() * 10000 + (new Date().getMonth() + 1) * 100 + new Date().getDate();
    return SURVIVAL_TIPS[seed % SURVIVAL_TIPS.length];
  }

  function eventDetailText(event) {
    var d = event.detail || {};
    if (event.type === '疫苗') return [d.dose, d.brand].filter(Boolean).join(' · ') || '疫苗接种';
    if (event.type === '驱虫') return (d.deworm_type || '体内外') + '驱虫';
    if (event.type === '洗澡澡') return d.note || '完成洗澡护理';
    if (event.type === '异常行为') {
      var s = Array.isArray(d.symptoms) ? d.symptoms.join('、') : '';
      return [s, d.note].filter(Boolean).join(' · ') || '异常观察记录';
    }
    if (event.type === '发情') return d.note || '生理周期记录';
    if (event.type === '每日检查') return d.note || (d.result === 'normal' ? '一切正常' : '发现异常');
    return d.note || '';
  }

  return {
    STORAGE_KEY: STORAGE_KEY,
    BREED_OPTIONS: BREED_OPTIONS,
    BREED_IDEAL_WEIGHT: BREED_IDEAL_WEIGHT,
    HIGH_RISK_SYMPTOMS: HIGH_RISK_SYMPTOMS,
    ABNORMAL_SYMPTOMS: ABNORMAL_SYMPTOMS,
    EVENT_META: EVENT_META,
    BADGES: BADGES,
    DAILY_TASKS: DAILY_TASKS,
    SURVIVAL_TIPS: SURVIVAL_TIPS,
    Store: Store,
    createInitialState: createInitialState,
    todayISO: todayISO,
    nowISO: nowISO,
    daysAgoISO: daysAgoISO,
    addDaysISO: addDaysISO,
    diffDays: diffDays,
    parseISO: parseISO,
    parseWeight: parseWeight,
    ageMonths: ageMonths,
    ageText: ageText,
    ageStage: ageStage,
    bodySize: bodySize,
    idealRange: idealRange,
    calcRER: calcRER,
    calcPlan: calcPlan,
    dietPlan: dietPlan,
    filterAllergen: filterAllergen,
    allergenMatches: allergenMatches,
    filterOptions: filterOptions,
    normalizeFood: normalizeFood,
    buildReminders: buildReminders,
    markReminderDone: markReminderDone,
    dailyCheckDone: dailyCheckDone,
    checkedToday: checkedToday,
    currentStreak: currentStreak,
    taskDoneToday: taskDoneToday,
    todayTask: todayTask,
    checkBadges: checkBadges,
    recordCheckin: recordCheckin,
    completeTask: completeTask,
    recordDailyCheck: recordDailyCheck,
    scanHighRisk: scanHighRisk,
    addEvent: addEvent,
    updateEvent: updateEvent,
    addWeight: addWeight,
    recordBCS: recordBCS,
    calcSupplements: calcSupplements,
    unlockedBadge: unlockedBadge,
    nextBadgeInfo: nextBadgeInfo,
    daysTogether: daysTogether,
    latestWeight: latestWeight,
    latestBCS: latestBCS,
    weightStats: weightStats,
    tipOfToday: tipOfToday,
    eventDetailText: eventDetailText
  };
})();
