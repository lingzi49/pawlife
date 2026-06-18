#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PawLife — 狗狗健康管理网页应用（单文件版）
============================================
产品定位：用狗狗第一人称口吻，为新手铲屎官提供即时情绪安抚与科学指导的防焦虑伴侣。

启动方式：
    python pawlife_web.py

功能：
  1. 狗狗小档案（1 分钟极速建档）
  2. 首页「今日汪汪」（紧急提醒 + 每日生存指南）
  3. 记录事件（疫苗 / 驱虫 / 发情 / 异常行为）+ 幂等防重
  4. 异常行为自动分析（品种决策树）
  5. 汪生时间线（纪念日卡片）
  6. 我的档案 + 重置演示数据

技术栈：Python 3 + FastAPI + SQLAlchemy + SQLite + 内嵌单页 HTML
"""

import csv
import io
import os
import sys
import json
import re
import threading
import time
from urllib.parse import quote

import webbrowser
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Literal

# ============================================================
# 自动安装缺失依赖
# ============================================================
def _ensure_deps():
    missing = []
    for mod in ("fastapi", "uvicorn", "sqlalchemy", "pydantic", "multipart"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        print(f"[PawLife] 检测到缺失依赖: {', '.join(missing)}，正在安装...")
        pkgs = "fastapi uvicorn sqlalchemy pydantic python-multipart"
        code = os.system(f'"{sys.executable}" -m pip install -q {pkgs}')
        if code != 0:
            print("[PawLife] 依赖安装失败，请手动执行：")
            print(f"    {sys.executable} -m pip install fastapi uvicorn sqlalchemy pydantic python-multipart")
            sys.exit(1)
        print("[PawLife] 依赖安装完成！")


_ensure_deps()

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
from sqlalchemy import Column, Date, DateTime, Integer, String, Text, create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base

# ============================================================
# 数据库设置
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 云端部署：通过 DATA_DIR 环境变量指定持久化数据目录（Fly.io /data、Render 等）
# 本地开发：使用项目目录
cloud_dir = os.environ.get("DATA_DIR", "")
if cloud_dir:
    DATA_DIR = cloud_dir
    os.makedirs(DATA_DIR, exist_ok=True)
else:
    DATA_DIR = BASE_DIR

DB_PATH = os.path.join(DATA_DIR, "pawlife_web.db")
engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
    echo=False,
)
SessionLocal = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()


class Dog(Base):
    """狗狗档案表"""
    __tablename__ = "dogs"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(64), nullable=False, comment="狗狗名字")
    breed = Column(String(32), nullable=False, comment="品种")
    birthday = Column(Date, nullable=False, comment="生日")
    weight = Column(String(16), nullable=True, comment="体重")
    neutered = Column(String(8), nullable=True, comment="绝育情况：是/否/未知")
    allergies = Column(String(256), nullable=True, comment="过敏源，逗号分隔")
    gender = Column(String(10), nullable=True, comment="性别：male/female")
    photo = Column(String(128), nullable=True, comment="照片文件名")
    bath_interval_days = Column(Integer, nullable=True, comment="建议洗澡间隔天数")
    last_bath_date = Column(Date, nullable=True, comment="上次洗澡日期")
    diseases = Column(String(256), nullable=True, comment="已知疾病，逗号分隔")
    suspended_until = Column(DateTime, nullable=True, comment="高风险事件暂停建议截止时间")
    badges = Column(Text, nullable=True, comment="已解锁勋章，JSON列表")
    paw_points = Column(Integer, nullable=False, default=0, comment="爪印积分")
    photos = Column(Text, nullable=True, comment="头像盲盒照片列表，JSON数组存Base64图片")
    today_avatar_index = Column(Integer, nullable=True, comment="今日头像索引")
    avatar_date = Column(Date, nullable=True, comment="今日头像日期")
    avatar_unlocked = Column(Integer, nullable=False, default=0, comment="是否已解锁健康成长相册 0=未解锁 1=已解锁")
    home_date = Column(Date, nullable=True, comment="狗狗到家日期")
    health_photos = Column(Text, nullable=True, comment="健康成长相册，JSON: [{filename, event_type, event_date, label}]")
    created_at = Column(DateTime, default=datetime.utcnow)


class Event(Base):
    """事件记录表"""
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True)
    dog_id = Column(Integer, nullable=False, comment="关联狗狗ID")
    type = Column(String(32), nullable=False, comment="事件类型：疫苗/驱虫/发情/异常行为")
    date = Column(Date, nullable=False, comment="事件日期")
    detail = Column(Text, nullable=True, comment="JSON 格式的详情")
    high_risk = Column(Integer, nullable=False, default=0, comment="是否高风险事件 1=是")
    risk_keyword = Column(String(64), nullable=True, comment="命中的高危症状关键词")
    photo = Column(String(128), nullable=True, comment="关联照片文件名")
    created_at = Column(DateTime, default=datetime.utcnow)


class WeightLog(Base):
    """体重记录表（用于幼犬体重追踪）"""
    __tablename__ = "weight_logs"

    id = Column(Integer, primary_key=True, index=True)
    dog_id = Column(Integer, nullable=False, comment="关联狗狗ID")
    weight = Column(String(16), nullable=False, comment="体重值")
    date = Column(Date, nullable=False, comment="记录日期")
    created_at = Column(DateTime, default=datetime.utcnow)


class SupplementAlert(Base):
    """保健品提醒表"""
    __tablename__ = "supplement_alerts"

    id = Column(Integer, primary_key=True, index=True)
    dog_id = Column(Integer, nullable=False, comment="关联狗狗ID")
    supplement_name = Column(String(64), nullable=False, comment="保健品名称")
    reason = Column(String(256), nullable=False, comment="推荐原因")
    woof_text = Column(String(512), nullable=False, comment="狗狗话术")
    priority = Column(Integer, nullable=False, default=2, comment="优先级1-3")
    is_active = Column(Integer, nullable=False, default=1, comment="1活跃 0过期")
    created_at = Column(DateTime, default=datetime.utcnow)


class RiskLog(Base):
    """高风险事件拦截日志表（法律合规追溯）"""
    __tablename__ = "risk_logs"

    id = Column(Integer, primary_key=True, index=True)
    dog_id = Column(Integer, nullable=False, comment="关联狗狗ID")
    input_text = Column(String(512), nullable=False, comment="用户输入的原始文本")
    matched_keyword = Column(String(64), nullable=False, comment="命中的高危词")
    action_taken = Column(String(64), nullable=False, default="suspended_diet_and_supplements")
    warning_shown = Column(Integer, nullable=False, default=1, comment="警告是否已展示")
    user_confirmed = Column(Integer, nullable=False, default=0, comment="用户是否确认 0=未确认 1=已确认")
    created_at = Column(DateTime, default=datetime.utcnow)


class PawPointsLog(Base):
    """爪印积分流水表"""
    __tablename__ = "paw_points_logs"

    id = Column(Integer, primary_key=True, index=True)
    pet_id = Column(Integer, nullable=False, comment="关联狗狗ID")
    amount = Column(Integer, nullable=False, comment="积分变动量（正数=获得）")
    reason = Column(String(64), nullable=False, comment="获取原因：签到/任务/答题等")
    created_at = Column(DateTime, default=datetime.utcnow)


class CheckIn(Base):
    """每日签到表"""
    __tablename__ = "checkins"

    id = Column(Integer, primary_key=True, index=True)
    pet_id = Column(Integer, nullable=False, comment="关联狗狗ID")
    check_date = Column(Date, nullable=False, comment="签到日期")
    streak = Column(Integer, nullable=False, default=1, comment="连续签到天数")
    task_completed = Column(Integer, nullable=False, default=0, comment="0=未完成今日任务 1=已完成")
    created_at = Column(DateTime, default=datetime.utcnow)


PHOTOS_DIR = os.path.join(DATA_DIR, "photos")
os.makedirs(PHOTOS_DIR, exist_ok=True)


def init_db():
    Base.metadata.create_all(bind=engine)
    # 迁移：为已有 dogs 表添加新增字段
    from sqlalchemy import text
    with engine.connect() as conn:
        existing = [r[1] for r in conn.execute(text("PRAGMA table_info(dogs)")).fetchall()]
        if "bath_interval_days" not in existing:
            conn.execute(text("ALTER TABLE dogs ADD COLUMN bath_interval_days INTEGER"))
        if "last_bath_date" not in existing:
            conn.execute(text("ALTER TABLE dogs ADD COLUMN last_bath_date DATE"))
        if "gender" not in existing:
            conn.execute(text("ALTER TABLE dogs ADD COLUMN gender VARCHAR(10)"))
        if "diseases" not in existing:
            conn.execute(text("ALTER TABLE dogs ADD COLUMN diseases VARCHAR(256)"))
        if "suspended_until" not in existing:
            conn.execute(text("ALTER TABLE dogs ADD COLUMN suspended_until DATETIME"))
        if "badges" not in existing:
            conn.execute(text("ALTER TABLE dogs ADD COLUMN badges TEXT"))
        if "paw_points" not in existing:
            conn.execute(text("ALTER TABLE dogs ADD COLUMN paw_points INTEGER DEFAULT 0"))
        if "photos" not in existing:
            conn.execute(text("ALTER TABLE dogs ADD COLUMN photos TEXT"))
        if "today_avatar_index" not in existing:
            conn.execute(text("ALTER TABLE dogs ADD COLUMN today_avatar_index INTEGER"))
        if "avatar_date" not in existing:
            conn.execute(text("ALTER TABLE dogs ADD COLUMN avatar_date DATE"))
        if "avatar_unlocked" not in existing:
            conn.execute(text("ALTER TABLE dogs ADD COLUMN avatar_unlocked INTEGER DEFAULT 0"))
        if "home_date" not in existing:
            conn.execute(text("ALTER TABLE dogs ADD COLUMN home_date DATE"))
        if "health_photos" not in existing:
            conn.execute(text("ALTER TABLE dogs ADD COLUMN health_photos TEXT"))
        # checkins 表迁移
        existing_ci = [r[1] for r in conn.execute(text("PRAGMA table_info(checkins)")).fetchall()]
        if "task_completed" not in existing_ci:
            conn.execute(text("ALTER TABLE checkins ADD COLUMN task_completed INTEGER DEFAULT 0"))
        existing_evt = [r[1] for r in conn.execute(text("PRAGMA table_info(events)")).fetchall()]
        if "high_risk" not in existing_evt:
            conn.execute(text("ALTER TABLE events ADD COLUMN high_risk INTEGER DEFAULT 0"))
        if "risk_keyword" not in existing_evt:
            conn.execute(text("ALTER TABLE events ADD COLUMN risk_keyword VARCHAR(64)"))
        if "photo" not in existing_evt:
            conn.execute(text("ALTER TABLE events ADD COLUMN photo VARCHAR(128)"))
        conn.commit()


# ============================================================
# FakeRedis — 内存幂等键实现（5 分钟 TTL）
# ============================================================
class FakeRedis:
    """模拟 Redis，用内存字典实现幂等键，线程安全 + 每 120 秒自动清理过期键。"""

    def __init__(self):
        self._store: Dict[str, tuple] = {}  # key -> (value, expire_timestamp)
        self._lock = threading.Lock()
        self._start_cleanup_thread()

    def set(self, key: str, value: Any, ex: int = 300):
        with self._lock:
            self._store[key] = (value, time.time() + ex)

    def get(self, key: str):
        with self._lock:
            item = self._store.get(key)
            if item is None:
                return None
            if time.time() > item[1]:
                del self._store[key]
                return None
            return item[0]

    def delete(self, key: str):
        with self._lock:
            self._store.pop(key, None)

    def _cleanup(self):
        with self._lock:
            now = time.time()
            expired = [k for k, v in self._store.items() if now > v[1]]
            for k in expired:
                del self._store[k]

    def _start_cleanup_thread(self):
        def _loop():
            while True:
                time.sleep(120)
                self._cleanup()

        t = threading.Thread(target=_loop, daemon=True)
        t.start()


fake_redis = FakeRedis()


# ============================================================
# Pydantic 校验模型
# ============================================================
BREED_OPTIONS = ["金毛", "拉布拉多", "柯基", "贵宾", "豆柴", "混血", "其他"]
EVENT_TYPES = ["疫苗", "驱虫", "发情", "异常行为", "洗澡澡", "每日检查"]
ABNORMAL_SYMPTOMS = ["跛行", "呕吐", "拉稀", "抓痒", "猛喝水", "不吃东西"]

# 高危症状词库 — 命中任一关键词即触发紧急拦截（不可修改）
HIGH_RISK_SYMPTOMS = [
    "反复呕吐", "持续呕吐", "吐血", "呕血", "腹泻带血", "便血", "黑便",
    "抽搐", "癫痫", "昏厥", "晕倒", "瘫痪", "呼吸困难", "呼吸急促",
    "极度萎靡", "意识丧失", "瞳孔散大", "严重过敏", "面部肿胀",
    "车祸", "中毒", "误食巧克力", "误食洋葱", "误食葡萄", "误食木糖醇",
    "误食老鼠药", "被蛇咬", "严重外伤", "大出血", "骨折", "烫伤",
]

# 品种理想体重范围 (kg)，用于 黄金体重 勋章判定
BREED_IDEAL_WEIGHT = {
    "金毛": (25.0, 34.0),
    "拉布拉多": (25.0, 36.0),
    "柯基": (10.0, 14.0),
    "贵宾": (3.0, 8.0),
    "豆柴": (7.0, 10.0),
    "混血": None,
    "其他": None,
}

# 勋章定义列表
BADGE_DEFINITIONS = [
    # ===== 第一次系列 =====
    {"name": "初来乍到", "icon": "🐾", "category": "第一次", "condition": "我们第一次相遇，创建了狗狗档案"},
    {"name": "第一针疫苗", "icon": "💉", "category": "第一次", "condition": "我们完成了第一次疫苗接种"},
    {"name": "第一次驱虫", "icon": "🛡️", "category": "第一次", "condition": "我们完成了第一次驱虫"},
    {"name": "第一次洗澡", "icon": "🛁", "category": "第一次", "condition": "我们第一次洗香香啦"},
    {"name": "到家第一天", "icon": "🏠", "category": "第一次", "condition": "我们有了共同的家"},
    # ===== 守护者系列 =====
    {"name": "免疫完成", "icon": "💉", "category": "守护者", "condition": "我们完成了3次疫苗接种，建立了坚固的免疫防线"},
    {"name": "驱虫达标", "icon": "🛡️", "category": "守护者", "condition": "我们完成了6次驱虫，把寄生虫挡在门外"},
    {"name": "洁齿坚持", "icon": "🦷", "category": "守护者", "condition": "我们30天内坚持了15天洁齿好习惯"},
    {"name": "肠胃稳定", "icon": "🍽️", "category": "守护者", "condition": "我们度过了连续60天肠胃无恙的安稳日子"},
    {"name": "体重管理", "icon": "⚖️", "category": "守护者", "condition": "我们3个月保持理想体重，身材管理大师"},
    # ===== 健康里程碑系列 =====
    {"name": "生日快乐", "icon": "🎂", "category": "健康里程碑", "condition": "我们一起吹了生日蜡烛"},
    {"name": "绝育勇敢", "icon": "🌟", "category": "健康里程碑", "condition": "我们一起经历了成长的重要一步"},
    {"name": "百日相伴", "icon": "💯", "category": "健康里程碑", "condition": "我们互相陪伴了100天"},
    {"name": "健康大满贯", "icon": "🏆", "category": "健康里程碑", "condition": "我们集齐了全部守护者系列勋章"},
    {"name": "守护之星", "icon": "⭐", "category": "健康里程碑", "condition": "我们攒下了30个爪印，每一天都在守护彼此"},
]

# ============================================================
# 每日生存指南库 — 50+条，带category标签用于个性化推荐
# ============================================================
SURVIVAL_TIPS = [
    # ===== food_danger：禁食警告（全年通用）=====
    {"text": "今天别喂我吃葡萄哦，一颗就可能让我肾受伤，葡萄干也一样危险！", "category": "food_danger"},
    {"text": "巧克力对我们狗狗来说是毒药，越纯越危险，主人一定要收好～", "category": "food_danger"},
    {"text": "洋葱、大蒜、韭菜这些东西会破坏我的红血球，千万别混在我的饭里。", "category": "food_danger"},
    {"text": "木糖醇（无糖口香糖里常有）对我超级毒，一点点就可能让我低血糖甚至肝衰竭。", "category": "food_danger"},
    {"text": "夏威夷果我也不行，吃了会发抖、发烧、走不动路。", "category": "food_danger"},
    {"text": "牛油果含有persin，对我不好，别给我尝鲜哦。", "category": "food_danger"},
    {"text": "咖啡和茶里面的咖啡因会让我心跳过快、抽搐，杯子要放高高的。", "category": "food_danger"},
    {"text": "生面团在我肚子里会发酵膨胀，还会产生酒精，非常危险！", "category": "food_danger"},
    {"text": "煮熟的鸡骨头会裂成尖刺，千万别喂我，生骨头也要在主人监督下吃～", "category": "food_danger"},
    {"text": "过多的盐分对我们狗狗肾脏负担很大，人吃的菜不要分给我哦～", "category": "food_danger"},
    {"text": "酒精对我们狗狗是致命的，一口啤酒都可能让我中毒，永远别给我尝！", "category": "food_danger"},
    {"text": "坚果类除了夏威夷果，核桃和山核桃也对我们有毒，会导致神经症状～", "category": "food_danger"},
    {"text": "发霉的食物里可能有霉菌毒素，对我们肝脏伤害极大，垃圾桶要盖好哦～", "category": "food_danger"},
    # ===== food_good：推荐食物 =====
    {"text": "三文鱼油富含Omega-3，对我的皮肤、毛发和关节都好，每周加几滴在饭里吧～", "category": "food_good"},
    {"text": "绿唇贻贝是天然的关节保护神器，含有葡萄糖胺和软骨素，大型犬宝宝尤其需要！", "category": "food_good"},
    {"text": "蓝莓是狗狗超级食物！抗氧化、低糖、一口一个，夏天冻一冻更美味～", "category": "food_good"},
    {"text": "南瓜泥（不是南瓜派馅哦）对消化超好，便秘或拉稀都能调节，一勺就见效～", "category": "food_good"},
    {"text": "胡萝卜生吃嘎嘣脆还能洁牙，煮熟了更好吸收β-胡萝卜素，都对眼睛好～", "category": "food_good"},
    {"text": "鸡胸肉是优质低脂蛋白，训练奖励和病号饭的首选，水煮无盐就超级好吃！", "category": "food_good"},
    {"text": "鸡蛋（全熟）是完美蛋白质来源，蛋壳磨成粉还能补钙，一周两三个刚刚好～", "category": "food_good"},
    {"text": "红薯富含纤维和维生素A，比白米饭更健康，蒸熟压成泥混在饭里甜甜的～", "category": "food_good"},
    # ===== behavior：行为解读 =====
    {"text": "我歪头不只是在卖萌，其实是在调整耳朵方向，努力听清你在说什么哦～", "category": "behavior"},
    {"text": "我追尾巴不一定是无聊，可能是焦虑、过敏、甚至肛门腺堵了，主人帮我查查原因。", "category": "behavior"},
    {"text": "我害怕打雷和鞭炮声的时候，请让我躲到我觉得安全的地方，安静陪着我就好～", "category": "behavior"},
    {"text": "社会化训练从小开始！3-16周是黄金期，多见不同的人和狗狗，长大更自信～", "category": "behavior"},
    {"text": "分离焦虑不是我在'作'，是真的害怕一个人。从短时间开始练习，留一件有你味道的旧衣服陪着我～", "category": "behavior"},
    {"text": "我闻闻别的狗狗的屁屁是在交换名片！每只狗狗的肛门腺气味都是独一无二的身份信息～", "category": "behavior"},
    {"text": "我在草地上打滚可能是想掩盖自己的气味（狩猎本能），也可能是单纯的开心和舒服～", "category": "behavior"},
    {"text": "给你叼来玩具不一定是想玩，有时候是我在表达'我爱你'——这是分享礼物的本能哦～", "category": "behavior"},
    # ===== care：护理知识 =====
    {"text": "每天出门散步时让我闻一闻世界，闻闻是狗狗的社交网络，一次散步胜过刷一小时手机～", "category": "care"},
    {"text": "剪指甲不要剪到粉红色的部分，那里有血管和神经，会疼也会出血，深色指甲要格外小心～", "category": "care"},
    {"text": "每天帮我刷刷牙，牙结石会导致心脏病和肾病，小牙刷大健康！", "category": "care"},
    {"text": "每周帮我清洁一次耳朵，金毛、拉布拉多等垂耳狗狗尤其容易耳道感染～", "category": "care"},
    {"text": "定期帮我梳毛不仅能减少掉毛，还能促进血液循环，是我们之间的亲密时光～", "category": "care"},
    {"text": "出门一定要牵绳！不是我不听话，是外面的世界诱惑太多啦，绳绳是我的生命线～", "category": "care"},
    {"text": "给我准备一些咬胶和玩具，换牙期的小狗和无聊的大狗都需要发泄，否则家具要遭殃～", "category": "care"},
    {"text": "训练我的时候用零食奖励比惩罚有效一万倍，正向强化让我们关系更好～", "category": "care"},
    {"text": "给我一个固定的作息吧，定时吃饭、散步、睡觉会让我很有安全感，焦虑少很多～", "category": "care"},
    # ===== season：季节提醒 =====
    {"text": "夏天千万别把我留在车里，即使开了窗，车内温度几分钟就能致命。", "category": "season"},
    {"text": "柏油路面夏天温度能到60度以上，主人用手背贴地试试，烫的话我也不要光脚走～", "category": "season"},
    {"text": "夏天带水碗出门，我散热主要靠喘气和脚垫，随时补水超重要！", "category": "season"},
    {"text": "夏天草丛里蜱虫超多，每次散步回来帮我全身摸一遍，重点检查耳朵、腋下、趾间～", "category": "season"},
    {"text": "中午最热的时段不要带我出门，清晨和傍晚散步才是对我们的关节和脚垫最好的～", "category": "season"},
    {"text": "冬天短毛狗狗出门可以穿件小衣服，但不要穿太紧，回家记得脱掉防潮湿～", "category": "season"},
    {"text": "下雪天出门后记得帮我擦脚！融雪剂会刺激脚垫，雪块夹在趾间也超级疼～", "category": "season"},
    {"text": "冬天家里开暖气空气干燥，我可能会皮肤发痒，加湿器能帮大忙～", "category": "season"},
    {"text": "春天花粉飘散，我可能会过敏打喷嚏、眼睛发红，主人帮我留意一下～", "category": "season"},
    {"text": "春天是跳蚤和蜱虫复苏的季节，记得每月按时做好体外驱虫～", "category": "season"},
    # ===== health_tip：健康冷知识 =====
    {"text": "正常狗狗体温在38-39.2度之间，鼻子湿凉不是判断健康的标准，精神状态和食欲才是～", "category": "health_tip"},
    {"text": "每年至少一次全面体检，7岁以上的狗狗建议半年一次，早期发现问题治疗效果好多啦！", "category": "health_tip"},
    {"text": "刷牙是最好的牙周病预防！口臭不是正常的，可能是牙结石或口腔感染的信号～", "category": "health_tip"},
    {"text": "观察我的便便很重要——颜色、形状、次数变化都可能反映健康问题，主人帮我多看一眼～", "category": "health_tip"},
    {"text": "疫苗接种后24小时内我可能会犯困、食欲略差，这是正常的，但脸肿或呼吸困难要立刻就医！", "category": "health_tip"},
    {"text": "狗狗也会得糖尿病和甲减！突然多饮多尿、体重变化要找兽医检查内分泌～", "category": "health_tip"},
    {"text": "我吃便便有时候是因为缺乏微量元素或者消化不好，不是变态行为啦，补充益生菌可能有帮助～", "category": "health_tip"},
]

# ============================================================
# 每日小测验题库 — 10道狗狗知识选择题
# ============================================================
QUIZZES = [
    {"question": "狗狗歪头主要是因为？", "options": ["单纯卖萌", "努力听清声音", "脖子痒"], "answer": 1, "explanation": "我歪头是为了调整耳朵方向，听清你在说什么哦～这个动作让我能更准确地定位声音来源！"},
    {"question": "狗狗的嗅觉比人类强多少倍？", "options": ["约10倍", "约100倍", "约10,000-100,000倍"], "answer": 2, "explanation": "我们狗狗的嗅觉比人类强约10,000到100,000倍！我的鼻子里有3亿个嗅觉受体，而人类只有约600万个～"},
    {"question": "以下哪种食物对狗狗是安全的？", "options": ["葡萄", "煮熟的胡萝卜", "巧克力"], "answer": 1, "explanation": "胡萝卜对我们超级安全又健康！生吃嘎嘣脆还能洁牙，煮熟更好吸收营养。但葡萄和巧克力可是要命的毒药哦！"},
    {"question": "狗狗的正常体温范围是？", "options": ["36-37°C", "38-39.2°C", "40-41°C"], "answer": 1, "explanation": "我们狗狗正常体温在38-39.2°C之间，比人类高一些。所以别用你的体温感觉来判断我有没有发烧哦～"},
    {"question": "狗狗摇尾巴一定代表开心吗？", "options": ["是的，摇尾巴就是开心", "不一定，还可能是紧张或警惕", "摇尾巴代表饿了"], "answer": 1, "explanation": "我摇尾巴不一定是开心哦！尾巴高高快速摇动才是兴奋，低低慢慢摇可能是紧张，僵直摇动可能是警惕。主人要学会看我的整体身体语言～"},
    {"question": "狗狗每天需要睡多久？", "options": ["4-6小时", "8-10小时", "12-14小时"], "answer": 2, "explanation": "成年狗狗每天需要12-14小时睡眠！幼犬和老年犬更需要16-18小时。所以看到我白天打盹不要觉得我懒，这是正常的生理需求～"},
    {"question": "以下哪个行为最可能是狗狗分离焦虑的表现？", "options": ["独自在家时乱咬东西和吠叫", "见到陌生人摇尾巴", "玩球时很兴奋"], "answer": 0, "explanation": "独自在家时破坏家具、不停吠叫、随地大小便，可能是因为分离焦虑。我不是在'作'，是真的害怕被抛弃。从短时间离开开始练习，慢慢会好的～"},
    {"question": "给狗狗剪指甲时最需要注意什么？", "options": ["剪得越短越好", "避开粉红色的血线", "用什么工具都行"], "answer": 1, "explanation": "指甲里粉红色的部分是血线（血管和神经），剪到会出血而且超级疼！深色指甲看不清血线，更要一小点一小点剪，或者请美容师帮忙～"},
    {"question": "狗狗的汗腺主要在哪里？", "options": ["全身皮肤", "舌头", "脚垫"], "answer": 2, "explanation": "我们狗狗的汗腺主要长在脚垫上！散热主要靠喘气和脚垫出汗。夏天脚底湿湿的是正常的，那是在帮你散发体温呢～"},
    {"question": "怀孕的狗狗孕期大约多久？", "options": ["约2个月（58-68天）", "约3个月（90天）", "约4个月（120天）"], "answer": 0, "explanation": "狗狗孕期大约58-68天，平均63天（刚好9周），比人类的9个月短多啦～如果发现妈妈狗狗怀孕了，记得前6周正常饮食，后3周逐渐增加营养哦！"},
]

# ============================================================
# 每日小任务库 — 15+条护理小任务
# ============================================================
# 每日小任务库 — 带 action_type 和任务 ID
# action_type: "navigate_weight" (跳转体重), "check_confirm" (确认弹窗), "navigate_photo" (拍照)
DAILY_TASKS = [
    {"id": "weigh", "task": "今天给我称一下体重，记录在档案里，监控体重防肥胖～", "action_type": "navigate_weight", "button_text": "去记录体重", "thanks": "体重记录好了！主人帮我监控身材，我要做最健康的小狗～"},
    {"id": "groom", "task": "今天给我梳毛5分钟吧，我会舒服得咕噜咕噜的～", "action_type": "check_confirm", "button_text": "我梳过了", "thanks": "梳完毛浑身轻松！主人梳得好舒服，毛毛也亮亮的～"},
    {"id": "ears", "task": "检查一下我的耳朵脏不脏，垂耳小朋友要格外注意哦！", "action_type": "check_confirm", "button_text": "我检查过了", "thanks": "耳朵干干净净！主人细心检查，我的耳朵不会发炎啦～"},
    {"id": "social", "task": "带我去认识一个新朋友（人或狗狗都行），社交让人快乐！", "action_type": "check_confirm", "button_text": "认识啦", "thanks": "新朋友真有趣！社交让狗狗更自信，主人是最好的社交教练～"},
    {"id": "photo", "task": "给我拍一张今天的照片，记录我的成长瞬间～", "action_type": "navigate_photo", "button_text": "去拍照", "thanks": "拍到了我的美照！主人镜头下的我永远最可爱～"},
    {"id": "trick", "task": "今天教我一个新指令吧，比如'趴下'或'握手'，我超爱学习的！", "action_type": "check_confirm", "button_text": "教过了", "thanks": "我又变聪明了一点！用零食训练我，我会学得更快哦～"},
    {"id": "water", "task": "检查我的水碗是不是满的、干净的，每天换新鲜水很重要～", "action_type": "check_confirm", "button_text": "换过了", "thanks": "新鲜的水真好喝！干净的水碗是对我最基本的爱～"},
    {"id": "body_check", "task": "摸一摸我的全身，看看有没有疙瘩、红肿或异常的热点。", "action_type": "check_confirm", "button_text": "检查过了", "thanks": "全身检查过关！主人这么细心，任何小问题都逃不过你的手掌～"},
    {"id": "walk", "task": "今天多绕一条街散步，换个路线让我闻闻新鲜的气味～", "action_type": "check_confirm", "button_text": "走过了", "thanks": "散步好开心！新路线新气味，狗狗的社交网络又更新啦～"},
    {"id": "teeth", "task": "检查一下我的牙齿，看看有没有牙结石或牙龈红肿。", "action_type": "check_confirm", "button_text": "看过了", "thanks": "牙齿亮晶晶！定期检查牙齿，我的笑容永远灿烂～"},
    {"id": "toys", "task": "帮我清洗一下玩具，玩具上的细菌比厕所还多呢！", "action_type": "check_confirm", "button_text": "洗好了", "thanks": "玩具又变干净了！啃干净的玩具，做干净的狗狗～"},
    {"id": "hide_seek", "task": "今天陪我玩一次捉迷藏，在家藏起来让我找你，这能锻炼我的嗅觉～", "action_type": "check_confirm", "button_text": "玩过了", "thanks": "找到主人啦！捉迷藏不仅好玩，还能锻炼我的嗅觉追踪能力～"},
    {"id": "nails", "task": "检查我的指甲长度，太长了走路会疼还会导致关节问题哦。", "action_type": "check_confirm", "button_text": "检查过了", "thanks": "指甲长度刚好！太长的指甲会让走路姿势变形，主人真细心～"},
    {"id": "food_check", "task": "看看狗粮包装上的保质期，过期了就不能吃了，会让我生病的。", "action_type": "check_confirm", "button_text": "看过了", "thanks": "狗粮都在保质期内！吃新鲜的粮，做健康的好狗狗～"},
    {"id": "petting", "task": "抚摸我十五分钟，从头到背慢慢摸，这能降低我们的压力荷尔蒙。", "action_type": "check_confirm", "button_text": "抚摸过了", "thanks": "被摸得好舒服～十五分钟的抚摸让我们的压力都飞走了～"},
    {"id": "gear", "task": "检查我的项圈和胸背带有没有磨损，安全第一哦！", "action_type": "check_confirm", "button_text": "查过了", "thanks": "装备完好！安全的项圈和胸背带是散步的第一道防线～"},
    {"id": "plants", "task": "家里有没有对我有毒的植物？比如百合、滴水观音、龟背竹，放高一点～", "action_type": "check_confirm", "button_text": "排查过了", "thanks": "家里没有危险植物！主人把有毒的植物都放得高高的，我好安全～"},
]

# 默认感谢语（兜底）
TASK_THANKS_DEFAULT = "主人你太棒了！完成了今天的任务，我感觉被爱包围了～"

# 签到里程碑勋章
CHECKIN_MILESTONES = [
    (7, "🐾 忠实爪印"),
    (14, "🦴 黄金骨头"),
    (30, "👑 汪汪守护神"),
    (60, "🌟 传说铲屎官"),
]


class DogCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    breed: str
    birthday: date
    weight: Optional[str] = None
    neutered: Optional[str] = "未知"
    allergies: Optional[str] = None
    gender: Optional[Literal["male", "female"]] = None
    diseases: Optional[str] = None
    home_date: Optional[date] = None

    @validator("breed")
    def breed_must_be_valid(cls, v):
        if v not in BREED_OPTIONS:
            raise ValueError(f"品种必须是以下之一：{'/'.join(BREED_OPTIONS)}")
        return v

    @validator("birthday")
    def birthday_not_future(cls, v):
        if v > date.today():
            raise ValueError("生日不能是未来的日子哦，主人～")
        return v

    @validator("weight")
    def weight_format_valid(cls, v):
        if v is not None and v.strip():
            stripped = v.strip()
            if not any(c.isdigit() for c in stripped):
                raise ValueError("体重需要包含数字哦，主人～比如：28kg、12.5kg")
        return v


class WeightLogCreate(BaseModel):
    dog_id: int
    weight: str = Field(..., min_length=1, max_length=16)
    date: date

    @validator("date")
    def date_not_future(cls, v):
        if v > date.today():
            raise ValueError("日期不能是未来的日子哦，主人～")
        if v < date(2000, 1, 1):
            raise ValueError("日期太遥远了，主人检查一下是不是填错了～")
        return v

    @validator("weight")
    def weight_format_valid(cls, v):
        if not any(c.isdigit() for c in v.strip()):
            raise ValueError("体重需要包含数字哦，主人～比如：28kg、12.5kg")
        return v


class EventCreate(BaseModel):
    dog_id: int
    type: str
    date: date
    detail: Optional[Dict[str, Any]] = None
    idem_key: Optional[str] = None  # 幂等键，前端生成
    high_risk: Optional[int] = 0
    risk_keyword: Optional[str] = None
    photo: Optional[str] = None  # Base64照片（可选）

    @validator("type")
    def type_must_be_valid(cls, v):
        if v not in EVENT_TYPES:
            raise ValueError(f"事件类型必须是以下之一：{'/'.join(EVENT_TYPES)}")
        return v

    @validator("date")
    def date_not_future(cls, v):
        if v > date.today():
            raise ValueError("事件日期不能是未来的日子，主人～")
        if v < date(2000, 1, 1):
            raise ValueError("事件日期太遥远了，主人检查一下是不是填错了～")
        return v


# ============================================================
# 品种 × 症状决策树（可扩展）
# ============================================================
# 结构：DECISION_TREE[品种][症状] = {"advice": str, "level": str}
# "默认" 键提供通用兜底建议。
DECISION_TREE: Dict[str, Dict[str, Dict[str, str]]] = {
    "金毛": {
        "跛行": {
            "advice": "我们金毛家族容易有髋关节问题，主人请让我安静休息几天，不要给我吃人用止痛药（尤其是布洛芬，对我们有毒！）。如果两天后还跛着，就带我去医院拍个片子吧。",
            "level": "中高",
        },
        "猛喝水": {
            "advice": "突然喝很多水可能是肾脏或内分泌在抗议，我们金毛有时也会得糖尿病。主人帮我留意一下尿量是不是也变多了，持续的话要验血哦。",
            "level": "中",
        },
        "抓痒": {
            "advice": "我的双层被毛容易藏污纳垢，可能是皮肤过敏或湿疹。主人检查一下我身上有没有红点或皮屑，不要频繁洗澡，必要时去看看皮肤科兽医。",
            "level": "中",
        },
    },
    "拉布拉多": {
        "不吃东西": {
            "advice": "连我拉布拉多都不想吃饭了，那问题可能不小！我们拉布可是出名的贪吃鬼。主人请观察我有没有呕吐或腹泻，超过24小时不进食一定要去医院。",
            "level": "高",
        },
        "呕吐": {
            "advice": "我可能又偷吃了不该吃的东西……我们拉布对食物没什么抵抗力。主人请先禁食6-8小时，只给少量水，如果还吐或者精神萎靡就去医院。",
            "level": "中",
        },
        "跛行": {
            "advice": "我们拉布爱跑爱跳，可能是扭伤或韧带问题。主人请限制我的活动，冷敷关节部位，如果肿胀明显就去看医生。",
            "level": "中",
        },
    },
    "柯基": {
        "跛行": {
            "advice": "我的小短腿和长脊椎是天生的，但也是弱点。跛行可能是椎间盘问题！主人千万不要让我爬楼梯或跳沙发，尽快带我去医院检查脊椎。",
            "level": "高",
        },
        "拉稀": {
            "advice": "主人，我的肠胃比较敏感，拉稀可能是吃坏了东西或者着凉了。先给我禁食半天，喂点益生菌，如果便便有血丝或持续拉水就要看医生。",
            "level": "中",
        },
    },
    "贵宾": {
        "抓痒": {
            "advice": "我们贵宾皮肤比较娇气，容易过敏。主人看看是不是换了新沐浴露、狗粮，或者环境里多了什么新东西。可以给我补充Omega-3脂肪酸帮助皮肤健康。",
            "level": "中低",
        },
        "呕吐": {
            "advice": "我可能是吃太快了或者毛球堵住了。主人试试用慢食碗，定期帮我梳毛。如果呕吐物带黄绿色（胆汁），且一天多次，就去看医生。",
            "level": "中",
        },
    },
    "默认": {
        "跛行": {
            "advice": "主人先帮我检查一下脚垫和指间有没有扎到东西，比如小石子、碎玻璃。如果只是轻微扭伤，限制活动一两天就好。如果肿胀、不敢着地或持续超过两天，请一定带我去看兽医哦。",
            "level": "中",
        },
        "呕吐": {
            "advice": "偶尔吐一次可能是吃太快或舔了脏东西，主人先别急着喂食，观察6小时。但如果我反复呕吐、精神很差、或者呕吐物里有血丝，请马上带我去医院！",
            "level": "中",
        },
        "拉稀": {
            "advice": "软便或拉稀通常是肠胃不适。主人给我禁食半天，保证有干净的水喝。可以喂一点南瓜泥帮助固便。如果拉稀超过48小时、带血、或者我又拉又吐，就去看医生。",
            "level": "中",
        },
        "抓痒": {
            "advice": "我痒得厉害可能是跳蚤、皮肤过敏或者真菌感染。主人帮我翻翻毛发看看有没有小黑点（跳蚤粪便）或红疹。定期驱虫和换低敏狗粮可能有帮助～",
            "level": "中低",
        },
        "猛喝水": {
            "advice": "突然大量喝水加上尿多，可能是糖尿病、肾病或子宫蓄脓（如果我是未绝育的母狗狗）的信号。主人记录一下我一天的饮水量，尽快带我去做血液检查。",
            "level": "中高",
        },
        "不吃东西": {
            "advice": "我平时最爱吃饭了，突然不吃一定是有原因的。可能是牙齿痛、肠胃不舒服，或者情绪不好。主人检查一下我的牙龈有没有红肿，尝试用手喂一点，如果超过24小时还是不吃，就要去看医生了。",
            "level": "中",
        },
    },
}


def analyze_behavior(breed: str, symptoms: List[str]) -> Dict[str, Any]:
    """
    根据品种和症状列表进行决策树匹配。
    优先精确匹配品种，找不到则降级到 "默认"。
    连默认都找不到的未知症状也会给出通用兜底文案。
    """
    results = []
    for symptom in symptoms:
        entry = None
        # 精确品种匹配
        if breed in DECISION_TREE and symptom in DECISION_TREE[breed]:
            entry = DECISION_TREE[breed][symptom]
        # 降级到默认
        elif "默认" in DECISION_TREE and symptom in DECISION_TREE["默认"]:
            entry = DECISION_TREE["默认"][symptom]

        if entry:
            results.append({
                "symptom": symptom,
                "advice": entry["advice"],
                "level": entry["level"],
            })
        else:
            # 兜底文案
            results.append({
                "symptom": symptom,
                "advice": f"主人，我出现了「{symptom}」的症状，虽然我不太确定是怎么回事，但请多观察我的状态。如果情况没有好转或者变严重了，带我去看兽医是最稳妥的选择哦。",
                "level": "未分级",
            })
    return {"results": results}


# ============================================================
# 狗狗第一人称反应生成
# ============================================================
def generate_vaccine_reaction(dog_name: str, detail: Optional[Dict] = None) -> str:
    dose = ""
    if detail and isinstance(detail, dict):
        d = detail.get("dose", "")
        if d:
            dose = f"这是我第{d}针，"
    return (
        f"汪汪，主人！{dose}疫苗打完啦～我超勇敢的！"
        f"这两天记得不要给我洗澡哦，也别让我着凉。我可能会有点犯困或者食欲差一点点，这是正常的。"
        f"但如果我脸肿了、呼吸困难或者一直吐，请马上联系兽医。主人陪我一起度过观察期吧～"
    )


def generate_deworm_reaction(dog_name: str, detail: Optional[Dict] = None) -> str:
    brand = ""
    if detail and isinstance(detail, dict):
        b = detail.get("brand", "")
        if b:
            brand = f"吃了{brand}"
    return (
        f"主人，{brand}驱虫药已经下肚啦！接下来几天帮我留意一下便便哦，"
        "可能会看到一些「不速之客」被赶出来。如果便便正常就没事啦～"
        "定期驱虫才能让我健健康康地陪在你身边！"
    )


def generate_heat_reaction(dog_name: str, detail: Optional[Dict] = None) -> str:
    return (
        f"主人，我现在进入特殊时期了，情绪可能会像过山车一样～"
        f"我可能会变得特别黏人，也可能会有点烦躁。"
        f"出门一定一定要牵好绳子，别让我乱跑！也暂时离其他狗狗远一点哦。"
        f"如果我不打算当妈妈，可以考虑在发情结束后做绝育手术，对我长期健康更好呢。"
    )


def generate_abnormal_reaction(dog_name: str, breed: str, detail: Optional[Dict] = None) -> str:
    symptoms: List[str] = []
    if detail and isinstance(detail, dict):
        symptoms = detail.get("symptoms", [])
    if not symptoms:
        return f"主人，我有点不舒服但我也说不清楚哪里不对，请多观察我，有任何异常带我去看兽医哦～"

    analysis = analyze_behavior(breed, symptoms)
    lines = []
    for r in analysis["results"]:
        emoji = {"高": "🔴", "中高": "🟠", "中": "🟡", "中低": "🟢", "未分级": "⚪"}.get(r["level"], "⚪")
        lines.append(f"{emoji}【{r['symptom']}·{r['level']}风险】{r['advice']}")
    return "\n\n".join(lines)


def generate_bath_reaction(dog_name: str, bath_interval: int, last_bath: date) -> str:
    """生成洗澡事件的狗狗第一人称反馈"""
    next_bath = last_bath + timedelta(days=bath_interval)
    month_str = f"{next_bath.month}月{next_bath.day}日"
    return f"主人，{dog_name}洗得好舒服呀，现在香喷喷的！下次我们大约 {month_str} 再洗香香，记得提前准备毛巾和宠物沐浴露哦～🛁"


# ============================================================
# FastAPI 应用
# ============================================================
app = FastAPI(title="PawLife", description="狗狗健康管理 · 防焦虑伴侣", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi.staticfiles import StaticFiles  # noqa: E402 — 必须在 app 创建后挂载
app.mount("/photos", StaticFiles(directory=PHOTOS_DIR), name="photos")


# 全局异常处理 — 返回狗狗安抚语，不暴露技术细节
@app.exception_handler(Exception)
async def global_exc_handler(request: Request, exc: Exception):
    import traceback
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"message": "汪汪，主人不要慌～服务器打了个小喷嚏，我在这里陪着你，稍后再试一次就好！"},
    )


# 404 处理
@app.exception_handler(404)
async def not_found_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=404,
        content={"message": "汪汪，这个页面被我藏起来了，主人检查一下地址对不对～"},
    )


@contextmanager
def get_db():
    """数据库会话上下文管理器，自动 commit/rollback/close/remove"""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
        SessionLocal.remove()


def create_demo_data():
    """创建演示狗狗「曦曦」和一条示例疫苗记录"""
    with get_db() as db:
        existing = db.query(Dog).filter(Dog.name == "曦曦").first()
        if existing:
            return
        # 如果存在旧演示数据「布丁」，先删除
        old = db.query(Dog).filter(Dog.name == "布丁").first()
        if old:
            db.query(Event).filter(Event.dog_id == old.id).delete()
            db.delete(old)
            db.flush()
        demo_dog = Dog(
            name="曦曦",
            breed="豆柴",
            birthday=date(2024, 12, 28),
            weight="7.8kg",
            neutered="否",
            allergies="",
            gender="female",
        )
        db.add(demo_dog)
        db.flush()
        demo_event = Event(
            dog_id=demo_dog.id,
            type="疫苗",
            date=date.today() - timedelta(days=90),
            detail=json.dumps({"dose": "3", "brand": "卫佳捌"}, ensure_ascii=False),
        )
        db.add(demo_event)


@app.on_event("startup")
def on_startup():
    init_db()
    create_demo_data()


# ============================================================
# 统一爪印积分函数
# ============================================================

def add_paw_points(db, pet_id: int, amount: int, reason: str = ""):
    """统一的爪印积分累加函数。所有爪印来源（签到/任务/答题）均通过此函数记录。"""
    dog = db.query(Dog).filter(Dog.id == pet_id).first()
    if dog:
        dog.paw_points = (dog.paw_points or 0) + amount
        log = PawPointsLog(pet_id=pet_id, amount=amount, reason=reason)
        db.add(log)
        db.commit()


def check_badges(db, pet_id: int) -> list:
    """检查并授予新勋章。在事件/签到/体重/任务后调用。返回新解锁的勋章列表。"""
    import json as _json
    from sqlalchemy import func as sa_func
    dog = db.query(Dog).filter(Dog.id == pet_id).first()
    if not dog:
        return []

    # 解析已有勋章，兼容旧格式
    unlocked_badges = []
    if dog.badges:
        try:
            unlocked_badges = _json.loads(dog.badges)
        except (_json.JSONDecodeError, TypeError):
            unlocked_badges = []
    # 旧格式兼容：字符串列表 → 字典列表，也兼容旧的 rarity 字段
    if unlocked_badges and isinstance(unlocked_badges[0], str):
        migrated = []
        for b_name in unlocked_badges:
            migrated.append({"name": b_name, "icon": "🐾", "date": str(dog.created_at.date()) if dog.created_at else "", "category": "健康里程碑"})
        unlocked_badges = migrated
        dog.badges = _json.dumps(unlocked_badges, ensure_ascii=False)

    # 构建名称→定义映射
    bdef_map = {b["name"]: b for b in BADGE_DEFINITIONS}
    unlocked_names = {b["name"] for b in unlocked_badges}
    today = date.today()
    new_badges = []

    def _unlock(name):
        nonlocal unlocked_badges, unlocked_names, new_badges
        if name in unlocked_names:
            return
        bdef = bdef_map.get(name)
        if not bdef:
            return
        entry = {"name": name, "icon": bdef["icon"], "date": today.isoformat(), "category": bdef["category"]}
        unlocked_badges.append(entry)
        unlocked_names.add(name)
        new_badges.append(entry)

    # ===== 第一次系列 =====
    # 1. 初来乍到：档案创建即解锁
    _unlock("初来乍到")

    # 2. 第一针疫苗：完成 >= 1 次疫苗
    vc = db.query(Event).filter(Event.dog_id == pet_id, Event.type == "疫苗").count()
    if vc >= 1:
        _unlock("第一针疫苗")

    # 3. 第一次驱虫：完成 >= 1 次驱虫
    dc = db.query(Event).filter(Event.dog_id == pet_id, Event.type == "驱虫").count()
    if dc >= 1:
        _unlock("第一次驱虫")

    # 4. 第一次洗澡：完成 >= 1 次洗澡
    bath_count = db.query(Event).filter(Event.dog_id == pet_id, Event.type == "洗澡澡").count()
    if bath_count >= 1:
        _unlock("第一次洗澡")

    # 5. 到家第一天：设置了到家日期
    if dog.home_date:
        _unlock("到家第一天")

    # ===== 守护者系列 =====
    # 6. 免疫完成：完成 >= 3 次疫苗
    if vc >= 3:
        _unlock("免疫完成")

    # 7. 驱虫达标：完成 >= 6 次驱虫
    if dc >= 6:
        _unlock("驱虫达标")

    # 8. 洁齿坚持：30天内 >= 15次任务完成
    thirty_days_ago = today - timedelta(days=30)
    task_count = db.query(CheckIn).filter(
        CheckIn.pet_id == pet_id,
        CheckIn.task_completed == 1,
        CheckIn.check_date >= thirty_days_ago
    ).count()
    if task_count >= 15:
        _unlock("洁齿坚持")

    # 9. 肠胃稳定：曾有异常行为，最近60天无复发
    abnormal_events = db.query(Event).filter(
        Event.dog_id == pet_id, Event.type == "异常行为"
    ).order_by(Event.date.desc()).all()
    if abnormal_events:
        last_abnormal_date = abnormal_events[0].date
        if (today - last_abnormal_date).days >= 60:
            recent = db.query(Event).filter(
                Event.dog_id == pet_id, Event.type == "异常行为",
                Event.date > today - timedelta(days=60)
            ).count()
            if recent == 0:
                _unlock("肠胃稳定")

    # 10. 体重管理：>=3条体重记录，跨度>=90天，全部在品种理想范围
    weight_range = BREED_IDEAL_WEIGHT.get(dog.breed)
    if weight_range:
        wlogs = db.query(WeightLog).filter(WeightLog.dog_id == pet_id).order_by(WeightLog.date.asc()).all()
        if len(wlogs) >= 3:
            try:
                spans = [w for w in wlogs if w.date and w.weight]
                if len(spans) >= 3 and (spans[-1].date - spans[0].date).days >= 90:
                    low, high = weight_range
                    if all(_weight_in_range(w.weight, low, high) for w in spans):
                        _unlock("体重管理")
            except Exception:
                pass

    # ===== 健康里程碑系列 =====
    # 11. 生日快乐：生日当天签到
    if dog.birthday:
        bday = db.query(CheckIn).filter(
            CheckIn.pet_id == pet_id,
            sa_func.strftime("%m-%d", CheckIn.check_date) == dog.birthday.strftime("%m-%d")
        ).first()
        if bday:
            _unlock("生日快乐")

    # 12. 绝育勇敢：已绝育
    if dog.neutered == "是":
        _unlock("绝育勇敢")

    # 13. 百日相伴：从创建日期起 >= 100天 且今天签到
    if dog.created_at:
        days_since_created = (today - dog.created_at.date()).days
        if days_since_created >= 100:
            today_checkin = db.query(CheckIn).filter(
                CheckIn.pet_id == pet_id, CheckIn.check_date == today
            ).first()
            if today_checkin:
                _unlock("百日相伴")

    # 14. 健康大满贯：集齐全部「守护者」系列（6枚守护者勋章）
    guardian_names = {b["name"] for b in BADGE_DEFINITIONS if b["category"] == "守护者"}
    unlocked_guardians = [b for b in unlocked_badges if b["name"] in guardian_names]
    if len(unlocked_guardians) >= len(guardian_names):
        _unlock("健康大满贯")

    # 15. 守护之星：累积30个爪印
    if (dog.paw_points or 0) >= 30:
        _unlock("守护之星")

    if new_badges:
        dog.badges = _json.dumps(unlocked_badges, ensure_ascii=False)
        db.flush()
    return new_badges


def _weight_in_range(weight_str, low, high):
    """解析体重字符串，检查是否在 [low*0.85, high*1.15] 范围内"""
    try:
        wv = float(weight_str.replace("kg", "").replace("Kg", "").replace("KG", "").strip())
    except (ValueError, AttributeError):
        return False
    return low * 0.85 <= wv <= high * 1.15


# ============================================================
# API 路由
# ============================================================

@app.get("/api/dog")
def api_get_dog():
    """获取当前狗狗档案（取最新创建的一只）"""
    with get_db() as db:
        dog = db.query(Dog).order_by(Dog.created_at.desc()).first()
        if not dog:
            raise HTTPException(status_code=404, detail="还没有狗狗档案，主人快去建档吧～")
        return {
            "id": dog.id,
            "name": dog.name,
            "breed": dog.breed,
            "birthday": dog.birthday.isoformat(),
            "weight": dog.weight or "",
            "neutered": dog.neutered or "未知",
            "allergies": dog.allergies or "",
            "gender": dog.gender or "",
            "photo": dog.photo or "",
            "diseases": dog.diseases or "",
            "suspended_until": dog.suspended_until.isoformat() if dog.suspended_until else None,
            "home_date": dog.home_date.isoformat() if dog.home_date else None,
            "health_photos": json.loads(dog.health_photos) if dog.health_photos else [],
            "paw_points": dog.paw_points or 0,
            "photo_count": len(json.loads(dog.photos)) if dog.photos else 0,
            "avatar_unlocked": bool(dog.avatar_unlocked),
        }


@app.post("/api/dog")
def api_create_dog(payload: DogCreate):
    """创建狗狗档案"""
    with get_db() as db:
        dog = Dog(
            name=payload.name,
            breed=payload.breed,
            birthday=payload.birthday,
            weight=payload.weight,
            neutered=payload.neutered or "未知",
            allergies=payload.allergies,
            gender=payload.gender,
            diseases=payload.diseases,
            home_date=payload.home_date,
            bath_interval_days=_calc_bath_interval(payload.weight),
            last_bath_date=date.today(),
        )
        db.add(dog)
        db.flush()
        _refresh_supplement_alerts(db, dog)
        # 检查勋章（初来乍到会在创建档案后立即解锁）
        new_badges = check_badges(db, dog.id)
        return {
            "message": f"汪汪！主人你好，我是{dog.name}！一只{dog.breed}宝宝～以后请多多关照我的小肉垫，我会陪你很久很久的！🐾",
            "dog_id": dog.id,
            "new_badges": new_badges or [],
        }


@app.put("/api/dog")
def api_update_dog(payload: DogCreate):
    """更新狗狗档案（更新最新创建的一只）"""
    with get_db() as db:
        dog = db.query(Dog).order_by(Dog.created_at.desc()).first()
        if not dog:
            raise HTTPException(status_code=404, detail="还没有狗狗档案，主人快去建档吧～")
        dog.name = payload.name
        dog.breed = payload.breed
        dog.birthday = payload.birthday
        dog.weight = payload.weight
        dog.neutered = payload.neutered or "未知"
        dog.allergies = payload.allergies
        dog.gender = payload.gender
        dog.diseases = payload.diseases
        dog.home_date = payload.home_date
        dog.bath_interval_days = _calc_bath_interval(payload.weight)
        db.flush()
        _refresh_supplement_alerts(db, dog)
        # 检查勋章（如勇敢完成、到家纪念日等在编辑后可能触发）
        new_badges = check_badges(db, dog.id)
        return {
            "message": f"汪汪！主人，我的档案更新好了～以后请继续多多关照我的小肉垫！🐾",
            "dog_id": dog.id,
            "new_badges": new_badges or [],
        }


@app.post("/api/dog/unsuspend")
def api_unsuspend_dog():
    """解除高风险事件导致的建议暂停"""
    with get_db() as db:
        dog = db.query(Dog).order_by(Dog.created_at.desc()).first()
        if not dog:
            raise HTTPException(status_code=404, detail="还没有狗狗档案，主人先去建档吧～")
        dog.suspended_until = None
        db.flush()
        return {"message": "汪汪！警报已解除，饮食和保健品建议已恢复正常～🐾"}
ALLERGY_FOOD_MAP = {
    "鸡": ["鸡胸肉", "鸡腿肉", "鸡胸肉丁", "鸡胸肉丝", "蛋黄", "鸡蛋"],
    "鸡肉": ["鸡胸肉", "鸡腿肉", "鸡胸肉丁", "鸡胸肉丝"],
    "禽": ["鸡胸肉", "鸡腿肉", "鸭肉", "蛋黄"],
    "鱼": ["三文鱼", "鳕鱼", "鱼肉", "鱼肉碎", "虾仁"],
    "海鲜": ["三文鱼", "鳕鱼", "鱼肉", "虾仁"],
    "三文鱼": ["三文鱼"],
    "鳕鱼": ["鳕鱼"],
    "牛": ["牛肉", "瘦牛肉", "牛肉糜", "牛肉末"],
    "牛肉": ["牛肉", "瘦牛肉", "牛肉糜", "牛肉末"],
    "羊": ["羊肉"],
    "羊肉": ["羊肉"],
    "虾": ["虾仁", "虾仁碎"],
    "虾仁": ["虾仁"],
    "蛋": ["蛋黄", "鸡蛋"],
    "蛋黄": ["蛋黄"],
    "谷物": ["燕麦", "糙米", "小米", "藜麦"],
    "麦": ["燕麦", "藜麦", "小麦"],
    "米": ["糙米", "小米"],
    "奶": [],
    "乳": [],
    "大豆": [],
    "豆": [],
}


def _filter_allergen_foods(food_name: str, allergies_str: str) -> bool:
    """检查某个食物是否在过敏源排除列表中，返回 True 表示应保留"""
    if not allergies_str or not allergies_str.strip():
        return True
    allergy_keys = [a.strip() for a in allergies_str.replace("，", ",").split(",") if a.strip()]
    exclude_set = set()
    for key in allergy_keys:
        if key in ALLERGY_FOOD_MAP:
            exclude_set.update(ALLERGY_FOOD_MAP[key])
        else:
            # 模糊匹配：过敏关键词出现在食物名中则排除
            for food in FOOD_NUTRITION:
                if key in food:
                    exclude_set.add(food)
    return food_name not in exclude_set


def _filter_options(options_str: str, allergies_str: str, category: str = "") -> str:
    """过滤替换选择字符串中的过敏食物，若全部被过滤则返回安全兜底食材"""
    if not allergies_str or not allergies_str.strip():
        return options_str
    items = [item.strip() for item in options_str.replace("，", ",").split(",") if item.strip()]
    filtered = [item for item in items if _filter_allergen_foods(item, allergies_str)]
    if filtered:
        return "、".join(filtered)
    # 全部被过滤时，返回安全的兜底食材
    if category:
        fallback = _get_safe_fallback(allergies_str, category)
        return fallback
    return "暂无安全选项"


def _get_safe_fallback(allergies_str: str, category: str) -> str:
    """为过敏狗狗找一个安全的替代食材"""
    if category == "protein":
        candidates = ["鸡胸肉", "鸭肉", "牛肉", "三文鱼", "羊肉", "鳕鱼", "虾仁"]
    elif category == "veggie":
        candidates = ["南瓜", "胡萝卜", "西兰花", "菠菜", "西葫芦"]
    else:
        candidates = ["红薯", "糙米", "燕麦", "南瓜", "藜麦", "小米", "山药"]
    for c in candidates:
        if _filter_allergen_foods(c, allergies_str):
            return c
    return candidates[0]  # 极端情况：所有都过敏，返回第一个


@app.get("/api/dog/diet")
def api_dog_diet():
    """返回基于狗狗档案的饮食推荐方案（含每餐食材清单 + 营养计算）"""
    import random
    with get_db() as db:
        dog = db.query(Dog).order_by(Dog.created_at.desc()).first()
        if not dog:
            raise HTTPException(status_code=404, detail="还没有狗狗档案，主人先去建档吧～")

        # 检查是否被高风险事件暂停
        if dog.suspended_until and dog.suspended_until > datetime.utcnow():
            return {
                "ready": False,
                "suspended": True,
                "message": "🚨 因您最近记录了高风险症状，今日饮食建议已暂停。请优先联系兽医，确认宠物状况稳定后可点击下方按钮恢复建议。",
            }

        weight_kg = _parse_weight_kg(dog.weight)
        if weight_kg is None:
            return {
                "ready": False,
                "message": "主人，我的档案里体重还没填呢，记得帮我补上，我才知道每天该吃多少哦～",
            }

        age_stage = _get_age_stage(dog.birthday)
        body_size = _get_body_size(dog.weight)
        foods = DIET_FOODS.get((age_stage, body_size))

        if foods is None:
            return {
                "ready": False,
                "message": "主人，我的档案还不够完整，记得帮我补上体重和生日，我才知道怎么吃更健康哦～",
            }

        plan = _calc_daily_grams(dog.birthday, weight_kg, dog.neutered or "未知", dog.gender)

        meals = foods["meals"]
        daily_recipe = random.choice(foods["daily"])

        # 过敏源检查
        allergies_str = dog.allergies or ""

        # 标准化食材名，若过敏则替换为安全食材
        norm_protein = _normalize_food(foods["protein"])
        norm_veggie  = _normalize_food(foods["veggie"])
        norm_carb    = _normalize_food(foods["carb"])

        if not _filter_allergen_foods(norm_protein, allergies_str):
            norm_protein = _get_safe_fallback(allergies_str, "protein")
        if not _filter_allergen_foods(norm_veggie, allergies_str):
            norm_veggie = _get_safe_fallback(allergies_str, "veggie")
        if not _filter_allergen_foods(norm_carb, allergies_str):
            norm_carb = _get_safe_fallback(allergies_str, "carb")

        # 每餐克数
        per_meal_protein = round(plan["protein_g"] / meals)
        per_meal_carb    = round(plan["carb_g"] / meals)
        per_meal_veggie  = round(plan["veggie_g"] / meals)

        # 构建食材清单（含营养计算）
        def _build_item(name: str, weight: int) -> dict:
            nut = FOOD_NUTRITION.get(name, FOOD_NUTRITION.get("鸡胸肉"))
            factor = weight / 100.0
            return {
                "name": name,
                "emoji": nut["emoji"],
                "weight": weight,
                "protein": round(nut["protein"] * factor, 1),
                "fat": round(nut["fat"] * factor, 1),
                "carbs": round(nut["carbs"] * factor, 1),
            }

        items = [
            _build_item(norm_protein, per_meal_protein),
            _build_item(norm_veggie, per_meal_veggie),
            _build_item(norm_carb, per_meal_carb),
        ]

        total_weight = sum(it["weight"] for it in items)
        total_protein = round(sum(it["protein"] for it in items), 1)
        total_fat = round(sum(it["fat"] for it in items), 1)
        total_carbs = round(sum(it["carbs"] for it in items), 1)

        # 餐次名称
        meal_type_names = {4: "早餐", 3: "午餐", 2: "早餐"}
        meal_type = meal_type_names.get(meals, "一餐")

        # 主菜名：用三个食材拼合
        meal_name = "".join(it["name"] for it in items) + "饭"

        # 按体型推荐鱼油补充
        fish_oil = "0.5ml/5kg体重，每周2-3次" if weight_kg < 15 else "1ml/5kg体重，每周2-3次"

        # 各营养素可选食材（根据过敏源过滤）
        protein_options = "鸡胸肉、鸭肉、瘦牛肉、三文鱼、鳕鱼"
        carb_options = "糙米、燕麦、红薯、南瓜、藜麦"
        veggie_options = "胡萝卜、西兰花、菠菜、西葫芦、南瓜"
        if body_size == "小型犬":
            protein_options = "鸡胸肉、鱼肉、虾仁、蛋黄、鸭肉"
        protein_options = _filter_options(protein_options, allergies_str, "protein")
        carb_options    = _filter_options(carb_options, allergies_str, "carb")
        veggie_options  = _filter_options(veggie_options, allergies_str, "veggie")

        # 心里话根据阶段个性化
        heartfelt_map = {
            "幼犬": f"主人，照着这个喂我，我会长得壮壮、毛亮亮哦！每天{meals}顿饭，陪我一起长大～🐾",
            "老年犬": f"主人，我的牙口不如从前啦，记得把食材切碎蒸软哦～每天{meals}顿饭，和你在一起的每一天都是好时光～🐾",
        }
        # 按性别区分称呼
        gender_title = ""
        if dog.gender == "male":
            gender_title = "小王子"
        elif dog.gender == "female":
            gender_title = "小公主"
        heartfelt = heartfelt_map.get(age_stage,
            f"主人，照着这个喂我，我会长得壮壮、毛亮亮哦！每天陪我一起吃饭，是我最开心的时光～🐾")
        if gender_title:
            heartfelt = f"适合活泼的{gender_title}～ " + heartfelt

        # 极小型犬低血糖风险提示
        hypoglycemia_note = ""
        if weight_kg is not None and weight_kg < 2 and age_stage == "幼犬":
            hypoglycemia_note = "⚠️ 超小型幼犬（<2kg）有低血糖风险，建议每天进食6-8次，如出现精神萎靡、走路不稳、牙龈苍白，立即喂少量蜂蜜水并联系兽医！"

        # 过敏提示
        allergy_note = ""
        if allergies_str:
            allergy_note = f"⚠️ 已避开你的过敏源（{allergies_str}），替换为安全的食材啦～"

        # 疾病状态提示
        disease_note = ""
        diseases_str = (dog.diseases or "").strip()
        if diseases_str:
            disease_note = f"⚕️ 档案中记录有已知健康状况（{diseases_str}），此饮食建议仅供兽医参考，请在兽医指导下调整饮食方案。"

        return {
            "ready": True,
            "dog_name": dog.name,
            "age_stage": age_stage,
            "body_size": body_size,
            "weight_kg": plan["weight_kg"],
            "meals_per_day": meals,
            "meal_type": meal_type,
            "meal_name": meal_name,
            "items": items,
            "total_weight": total_weight,
            "total_protein": total_protein,
            "total_fat": total_fat,
            "total_carbs": total_carbs,
            # 保留兼容字段
            "daily_recipe": daily_recipe,
            "tip": foods["tip"],
            "fish_oil": fish_oil,
            "heartfelt": heartfelt,
            "protein_options": protein_options,
            "carb_options": carb_options,
            "veggie_options": veggie_options,
            "allergy_note": allergy_note,
            "disease_note": disease_note,
            "hypoglycemia_note": hypoglycemia_note,
        }


@app.post("/api/dog/photo")
async def api_upload_photo(file: UploadFile = File(...)):
    """上传/更换狗狗照片"""
    # 校验文件类型
    if file.content_type not in ("image/jpeg", "image/png", "image/jpg"):
        raise HTTPException(status_code=400, detail="主人，只支持 JPG 和 PNG 格式的图片哦～")

    # 读取并校验大小（最大 2MB）
    contents = await file.read()
    if len(contents) > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="主人，图片太大了（不能超过 2MB），压缩一下再上传吧～")

    # 校验文件名
    if not file.filename:
        raise HTTPException(status_code=400, detail="主人，请选择一个文件哦～")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".jpg", ".jpeg", ".png"):
        raise HTTPException(status_code=400, detail="主人，只支持 .jpg 和 .png 格式的图片哦～")

    # 生成唯一文件名
    import uuid
    filename = f"{uuid.uuid4().hex}{ext}"
    filepath = os.path.join(PHOTOS_DIR, filename)

    # 保存文件
    with open(filepath, "wb") as f:
        f.write(contents)

    # 更新狗狗档案
    with get_db() as db:
        dog = db.query(Dog).order_by(Dog.created_at.desc()).first()
        if not dog:
            # 没有狗狗档案，删除刚上传的文件
            os.remove(filepath)
            raise HTTPException(status_code=404, detail="还没有狗狗档案，主人先去建档吧～")

        # 删除旧照片
        old_photo = dog.photo
        if old_photo:
            old_path = os.path.join(PHOTOS_DIR, old_photo)
            if os.path.isfile(old_path):
                try:
                    os.remove(old_path)
                except OSError:
                    pass

        dog.photo = filename
        db.flush()

    return {"message": "汪汪！我的新照片上传成功啦，主人把我拍得真好看～📸", "photo": filename}


@app.post("/api/dog/health_photo")
async def api_upload_health_photo(
    pet_id: int = Form(...),
    event_type: str = Form(...),
    event_date: str = Form(...),
    label: str = Form(""),
    file: UploadFile = File(...),
    event_id: int = Form(None),
):
    """上传健康事件纪念照，可选绑定到具体事件记录"""
    if file.content_type not in ("image/jpeg", "image/png", "image/jpg"):
        raise HTTPException(status_code=400, detail="主人，只支持 JPG 和 PNG 格式的图片哦～")
    contents = await file.read()
    if len(contents) > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="主人，图片太大了（不能超过 2MB），压缩一下再上传吧～")
    if not file.filename:
        raise HTTPException(status_code=400, detail="主人，请选择一个文件哦～")
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".jpg", ".jpeg", ".png"):
        raise HTTPException(status_code=400, detail="主人，只支持 .jpg 和 .png 格式的图片哦～")
    import uuid as _uuid2
    filename = f"{_uuid2.uuid4().hex}{ext}"
    filepath = os.path.join(PHOTOS_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(contents)
    with get_db() as db:
        dog = db.query(Dog).filter(Dog.id == pet_id).first()
        if not dog:
            os.remove(filepath)
            raise HTTPException(status_code=404, detail="还没有狗狗档案，主人先去建档吧～")
        import json as _json2
        hp = _json2.loads(dog.health_photos) if dog.health_photos else []
        entry = {"filename": filename, "event_type": event_type, "event_date": event_date, "label": label or event_type}
        hp.append(entry)
        dog.health_photos = _json2.dumps(hp, ensure_ascii=False)
        if dog.avatar_unlocked != 1:
            dog.avatar_unlocked = 1
        # 如果指定了事件ID，同时更新事件记录的照片
        if event_id:
            evt = db.query(Event).filter(Event.id == event_id).first()
            if evt:
                if evt.photo:
                    old_path = os.path.join(PHOTOS_DIR, evt.photo)
                    if os.path.exists(old_path):
                        os.remove(old_path)
                evt.photo = filename
        add_paw_points(db, pet_id, 1, "上传健康照")
        new_badges = check_badges(db, pet_id)
        db.flush()
        paw_pts = dog.paw_points
    event_label = label or event_type
    return {
        "message": f"汪汪！{event_label}的纪念照保存成功啦～主人你真好！📸",
        "health_photo_count": len(hp),
        "paw_points": paw_pts,
        "new_badges": new_badges or [],
    }


@app.delete("/api/dog/health_photo")
def api_delete_health_photo(pet_id: int = 1, index: int = 0):
    """删除健康纪念照"""
    import json as _json3
    with get_db() as db:
        dog = db.query(Dog).filter(Dog.id == pet_id).first()
        if not dog:
            raise HTTPException(status_code=404, detail="还没有狗狗档案")
        hp = _json3.loads(dog.health_photos) if dog.health_photos else []
        if index < 0 or index >= len(hp):
            raise HTTPException(status_code=400, detail="照片不存在")
        removed = hp.pop(index)
        dog.health_photos = _json3.dumps(hp, ensure_ascii=False) if hp else None
        # 删除文件
        old_path = os.path.join(PHOTOS_DIR, removed["filename"])
        if os.path.isfile(old_path):
            try:
                os.remove(old_path)
            except OSError:
                pass
        db.flush()
    return {"message": "纪念照已删除", "health_photo_count": len(hp)}


# 勋章→事件照片映射：(事件类型, 第N次)
_BADGE_EVENT_PHOTO_MAP = {
    "第一针疫苗": ("疫苗", 1),
    "第一次驱虫": ("驱虫", 1),
    "第一次洗澡": ("洗澡澡", 1),
    "免疫完成": ("疫苗", 3),
    "驱虫达标": ("驱虫", 6),
}

@app.get("/api/badges")
def api_get_badges(pet_id: int = 1):
    """返回所有勋章及解锁状态，按故事线分类"""
    import json as _json4
    with get_db() as db:
        dog = db.query(Dog).filter(Dog.id == pet_id).first()
        if not dog:
            return {"badges": [], "total_unlocked": 0, "categories": []}
        unlocked_badges = []
        if dog.badges:
            try:
                unlocked_badges = _json4.loads(dog.badges)
            except (_json4.JSONDecodeError, TypeError):
                unlocked_badges = []
        # 兼容旧格式
        if unlocked_badges and isinstance(unlocked_badges[0], str):
            unlocked_badges = [{"name": b, "icon": "🐾", "date": "", "category": "健康里程碑"} for b in unlocked_badges]
        unlocked_names = {b["name"] for b in unlocked_badges}

        # 预查询所有事件（按日期排序），用于勋章照片匹配
        from sqlalchemy import asc as sa_asc
        all_events = db.query(Event).filter(
            Event.dog_id == pet_id, Event.photo.isnot(None), Event.photo != ""
        ).order_by(sa_asc(Event.date)).all()
        # 按类型分组：{类型: [event, ...]}
        events_by_type = {}
        for ev in all_events:
            events_by_type.setdefault(ev.type, []).append(ev)

        result = []
        for bdef in BADGE_DEFINITIONS:
            is_unlocked = bdef["name"] in unlocked_names
            unlock_info = next((u for u in unlocked_badges if u["name"] == bdef["name"]), None)
            # 查找对应事件照片
            photo = None
            if is_unlocked and bdef["name"] in _BADGE_EVENT_PHOTO_MAP:
                ev_type, ev_n = _BADGE_EVENT_PHOTO_MAP[bdef["name"]]
                ev_list = events_by_type.get(ev_type, [])
                if len(ev_list) >= ev_n:
                    photo = ev_list[ev_n - 1].photo
            result.append({
                "name": bdef["name"],
                "icon": bdef["icon"],
                "category": bdef["category"],
                "condition": bdef.get("condition", ""),
                "unlocked": is_unlocked,
                "date": unlock_info["date"] if unlock_info and unlock_info.get("date") else None,
                "photo": photo,
            })
        categories = sorted(set(b["category"] for b in result))
        return {"badges": result, "total_unlocked": len(unlocked_badges), "categories": categories}


@app.post("/api/event")
def api_create_event(payload: EventCreate):
    """记录事件，返回狗狗第一人称反应"""
    # 幂等检查
    if payload.idem_key:
        cached = fake_redis.get(payload.idem_key)
        if cached and cached != "__processing__":
            return {"message": cached, "duplicate": True}
        # 设占位符防并发重复提交（30秒短TTL，失败后自动过期）
        fake_redis.set(payload.idem_key, "__processing__", ex=30)

    try:
        with get_db() as db:
            dog = db.query(Dog).filter(Dog.id == payload.dog_id).first()
            if not dog:
                raise HTTPException(status_code=404, detail="找不到这只狗狗，主人先建档吧～")

            # 发情期事件：仅母犬可记录
            if payload.type == "发情" and dog.gender == "male":
                raise HTTPException(status_code=400, detail="我是小王子，不会来姨妈哦～")

            detail_json = json.dumps(payload.detail, ensure_ascii=False) if payload.detail else None
            # 处理Base64照片（如有）
            photo_filename = None
            if payload.photo:
                try:
                    import base64 as _b64
                    photo_data = _b64.b64decode(payload.photo)
                    if len(photo_data) > 2 * 1024 * 1024:
                        raise HTTPException(status_code=400, detail="主人，图片太大了（不能超过 2MB）～")
                    import uuid as _uuid_evt
                    photo_filename = f"{_uuid_evt.uuid4().hex}.jpg"
                    photo_path = os.path.join(PHOTOS_DIR, photo_filename)
                    with open(photo_path, "wb") as pf:
                        pf.write(photo_data)
                except HTTPException:
                    raise
                except Exception:
                    photo_filename = None  # 无效Base64则忽略
            event = Event(
                dog_id=payload.dog_id,
                type=payload.type,
                date=payload.date,
                detail=detail_json,
                high_risk=payload.high_risk or 0,
                risk_keyword=payload.risk_keyword or None,
                photo=photo_filename,
            )
            db.add(event)

            # 高风险事件：暂停饮食和保健品建议至当天结束
            if payload.high_risk:
                today_end = datetime.utcnow().replace(hour=23, minute=59, second=59, microsecond=0)
                dog.suspended_until = today_end
                # 记录风险日志
                symptom_text = ""
                if payload.detail and isinstance(payload.detail, dict):
                    symptoms = payload.detail.get("symptoms", [])
                    if isinstance(symptoms, list):
                        symptom_text = "，".join(symptoms)
                risk_log = RiskLog(
                    dog_id=payload.dog_id,
                    input_text=symptom_text[:512],
                    matched_keyword=payload.risk_keyword or "",
                    action_taken="suspended_diet_and_supplements",
                    warning_shown=1,
                    user_confirmed=1,
                )
                db.add(risk_log)

            # 生成狗狗第一人称反应
            detail_dict = payload.detail if isinstance(payload.detail, dict) else {}
            if payload.type == "疫苗":
                reaction = generate_vaccine_reaction(dog.name, detail_dict)
            elif payload.type == "驱虫":
                reaction = generate_deworm_reaction(dog.name, detail_dict)
            elif payload.type == "发情":
                reaction = generate_heat_reaction(dog.name, detail_dict)
            elif payload.type == "异常行为":
                reaction = generate_abnormal_reaction(dog.name, dog.breed, detail_dict)
                # 异常行为后刷新保健品推荐（高风险事件也要刷新）
                _refresh_supplement_alerts(db, dog)
            elif payload.type == "洗澡澡":
                interval = dog.bath_interval_days or 10
                dog.last_bath_date = payload.date
                reaction = generate_bath_reaction(dog.name, interval, payload.date)
            else:
                reaction = "汪汪，记录好了！"

            # 缓存反应到幂等键，重复提交时直接返回相同文案
            if payload.idem_key:
                fake_redis.set(payload.idem_key, reaction, ex=300)

            # 记录事件奖励爪印（每日每种事件类型最多奖励一次，通过幂等键自然去重）
            if payload.idem_key:
                add_paw_points(db, payload.dog_id, 1, "记录事件")

            # 自动解锁健康成长相册
            if dog.avatar_unlocked != 1:
                dog.avatar_unlocked = 1
                dog.today_avatar_index = None
                dog.avatar_date = None
                db.flush()

            # 检查并授予勋章
            new_badges = check_badges(db, payload.dog_id)

            return {
                "message": reaction,
                "event_id": event.id,
                "avatar_unlocked": True,
                "new_badges": new_badges or [],
                "prompt_health_photo": payload.type != "异常行为",
            }
    except Exception:
        # DB 失败时清除占位符，允许重试
        if payload.idem_key:
            fake_redis.delete(payload.idem_key)
        raise


@app.put("/api/event/{event_id}")
def api_update_event(event_id: int, payload: EventCreate):
    """编辑已有事件"""
    with get_db() as db:
        event = db.query(Event).filter(Event.id == event_id).first()
        if not event:
            raise HTTPException(status_code=404, detail="找不到这条事件记录，主人～")

        # 发情期事件：仅母犬可记录
        dog = db.query(Dog).filter(Dog.id == event.dog_id).first()
        if payload.type == "发情" and dog and dog.gender == "male":
            raise HTTPException(status_code=400, detail="我是小王子，不会来姨妈哦～")

        event.type = payload.type
        event.date = payload.date
        event.detail = json.dumps(payload.detail, ensure_ascii=False) if payload.detail else None
        db.flush()

        return {"message": "汪汪！事件已更新，主人的记录越来越完整了～🐾", "event_id": event.id}


@app.delete("/api/event/{event_id}")
def api_delete_event(event_id: int):
    """删除事件"""
    with get_db() as db:
        event = db.query(Event).filter(Event.id == event_id).first()
        if not event:
            raise HTTPException(status_code=404, detail="找不到这条事件记录，主人～")
        # 清理关联的照片文件
        if event.photo:
            photo_path = os.path.join(PHOTOS_DIR, event.photo)
            if os.path.exists(photo_path):
                os.remove(photo_path)
        db.delete(event)
        return {"message": "汪汪，这条记录已经被我删掉了，主人的大事记保持整洁很重要～"}


@app.post("/api/records/{record_id}/photo")
async def api_upload_record_photo(record_id: int, file: UploadFile = File(...), symptom_only: bool = False):
    """为已有事件记录上传/更新照片。symptom_only=True时仅存于事件记录，不入健康相册。"""
    if file.content_type not in ("image/jpeg", "image/png", "image/jpg"):
        raise HTTPException(status_code=400, detail="主人，只支持 JPG 和 PNG 格式的图片哦～")
    contents = await file.read()
    if len(contents) > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="主人，图片太大了（不能超过 2MB），压缩一下再上传吧～")
    if not file.filename:
        raise HTTPException(status_code=400, detail="主人，请选择一个文件哦～")
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".jpg", ".jpeg", ".png"):
        raise HTTPException(status_code=400, detail="主人，只支持 .jpg 和 .png 格式的图片哦～")
    import uuid as _uuid_rec
    filename = f"{_uuid_rec.uuid4().hex}{ext}"
    filepath = os.path.join(PHOTOS_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(contents)
    with get_db() as db:
        event = db.query(Event).filter(Event.id == record_id).first()
        if not event:
            os.remove(filepath)
            raise HTTPException(status_code=404, detail="找不到这条事件记录，主人～")
        # 删除旧照片文件（如有）
        if event.photo:
            old_path = os.path.join(PHOTOS_DIR, event.photo)
            if os.path.exists(old_path):
                os.remove(old_path)
        event.photo = filename
        evt_type = event.type
        # 异常行为/症状照片不进入健康相册
        if not symptom_only and evt_type != "异常行为":
            dog = db.query(Dog).filter(Dog.id == event.dog_id).first()
            if dog:
                import json as _json_rec
                hp = _json_rec.loads(dog.health_photos) if dog.health_photos else []
                hp.append({"filename": filename, "event_type": evt_type, "event_date": event.date.isoformat(), "label": evt_type})
                dog.health_photos = _json_rec.dumps(hp, ensure_ascii=False)
        db.flush()
        photo_url = f"/photos/{filename}"
    if symptom_only or evt_type == "异常行为":
        return {
            "message": "汪汪！症状照片已保存，可以在兽医就诊时出示给医生看哦～📋",
            "photo": filename,
            "photo_url": photo_url,
        }
    return {
        "message": f"汪汪！{evt_type}的照片已保存，我的健康成长相册又丰富啦～📸",
        "photo": filename,
        "photo_url": photo_url,
    }


@app.get("/api/events")
def api_list_events():
    """获取当前狗狗所有事件，按日期倒序"""
    with get_db() as db:
        dog = db.query(Dog).order_by(Dog.created_at.desc()).first()
        if not dog:
            return []
        events = db.query(Event).filter(Event.dog_id == dog.id).order_by(Event.date.desc()).all()
        result = []
        for e in events:
            result.append({
                "id": e.id,
                "dog_id": e.dog_id,
                "type": e.type,
                "date": e.date.isoformat(),
                "detail": e.detail,
                "photo": f"/photos/{e.photo}" if e.photo else None,
            })
        return result


@app.get("/api/weight_logs")
def api_list_weight_logs():
    """获取最新狗狗的体重记录，按日期倒序"""
    with get_db() as db:
        dog = db.query(Dog).order_by(Dog.created_at.desc()).first()
        if not dog:
            return []
        logs = db.query(WeightLog).filter(WeightLog.dog_id == dog.id).order_by(WeightLog.date.desc()).all()
        return [{"id": l.id, "weight": l.weight, "date": l.date.isoformat()} for l in logs]


@app.post("/api/weight_log")
def api_create_weight_log(payload: WeightLogCreate):
    """记录一次体重"""
    with get_db() as db:
        dog = db.query(Dog).filter(Dog.id == payload.dog_id).first()
        if not dog:
            raise HTTPException(status_code=404, detail="找不到这只狗狗，主人先建档吧～")
        wl = WeightLog(dog_id=payload.dog_id, weight=payload.weight, date=payload.date)
        db.add(wl)
        # 同步更新狗狗档案中的最新体重
        dog.weight = payload.weight
        db.flush()
        # 检查并授予勋章
        new_badges = check_badges(db, payload.dog_id)
        return {
            "message": f"汪汪！体重 {payload.weight} 已记录，主人要帮我保持健康身材哦～🐾",
            "id": wl.id,
            "new_badges": new_badges or [],
        }


def _get_deworm_interval(dog_birthday: date, breed: str) -> int:
    """根据狗狗年龄和品种返回驱虫间隔天数。幼犬（<6个月）每月一次，成年犬按品种。"""
    today = date.today()
    age_months = (today.year - dog_birthday.year) * 12 + (today.month - dog_birthday.month)
    if age_months < 6:
        return 30
    # 成年犬品种映射（当前统一90天，预留扩展入口）
    breed_map = {"金毛": 90, "拉布拉多": 90, "柯基": 90, "贵宾": 90, "豆柴": 90, "混血": 90, "其他": 90}
    return breed_map.get(breed, 90)


def _calc_bath_interval(weight_str: Optional[str]) -> int:
    """根据体重计算建议洗澡间隔天数。体重为空时默认10天。"""
    if not weight_str or not weight_str.strip():
        return 10
    try:
        kg = float(weight_str.strip().replace("kg", "").replace("KG", "").strip())
    except ValueError:
        return 10
    if kg < 5:
        return 14
    elif kg < 15:
        return 14
    else:
        return 10


def _get_age_stage(birthday: date) -> str:
    """根据生日返回年龄阶段：幼犬/成犬/老年犬"""
    today = date.today()
    age_months = (today.year - birthday.year) * 12 + (today.month - birthday.month)
    if age_months <= 12:
        return "幼犬"
    elif age_months < 84:  # 7岁 = 84个月
        return "成犬"
    else:
        return "老年犬"


def _get_body_size(weight_str: Optional[str]) -> str:
    """根据体重返回体型：小型/中型/大型/未知"""
    if not weight_str or not weight_str.strip():
        return "未知"
    try:
        kg = float(weight_str.strip().replace("kg", "").replace("KG", "").strip())
    except ValueError:
        return "未知"
    if kg < 5:
        return "小型犬"
    elif kg < 15:
        return "中型犬"
    else:
        return "大型犬"


# 饮食食材推荐表（克数由 RER→DER 公式动态计算）
# {(年龄阶段, 体型): {"meals": 餐数, "protein": 蛋白食材, "veggie": 蔬菜, "carb": 碳水, "daily": [示例食谱]}}
DIET_FOODS = {
    ("幼犬", "小型犬"): {
        "meals": 4,
        "protein": "鸡胸肉（白肉低脂）",
        "veggie":  "南瓜",
        "carb":    "燕麦",
        "daily": [
            "鸡胸肉丁 + 南瓜泥 + 燕麦糊",
            "蛋黄半个 + 胡萝卜泥 + 小米粥",
            "鱼肉碎 + 西兰花泥 + 红薯泥",
        ],
        "tip": "幼犬肠胃娇嫩，所有食材需煮软打成泥糊状，少食多餐～",
    },
    ("幼犬", "中型犬"): {
        "meals": 3,
        "protein": "牛肉糜（红肉补铁）",
        "veggie":  "胡萝卜",
        "carb":    "糙米",
        "daily": [
            "牛肉糜 + 胡萝卜丁 + 糙米饭",
            "鸡胸肉 + 菠菜碎 + 红薯块",
            "三文鱼 + 南瓜 + 藜麦",
        ],
        "tip": "幼犬活动量大，碳水比例可稍高，保证能量供给～",
    },
    ("幼犬", "大型犬"): {
        "meals": 3,
        "protein": "鸡胸肉",  "veggie": "菠菜",    "carb": "红薯",
        "daily": [
            "鸡胸肉 + 菠菜 + 红薯泥",
            "牛肉 + 西兰花 + 糙米饭",
            "羊肉 + 胡萝卜 + 燕麦",
        ],
        "tip": "⚠️ 大型幼犬骨骼发育关键期：钙磷比需严格控制在1.1:1~1.8:1（NRC标准）。每500g食物建议添加约2g蛋壳粉（约400mg钙），过量或不足均可能导致骨骼发育异常。请务必咨询兽医确认具体剂量！",
    },
    ("成犬", "小型犬"): {
        "meals": 2,
        "protein": "鱼肉（Omega-3 美毛）",
        "veggie":  "西兰花",
        "carb":    "红薯",
        "daily": [
            "鱼肉 + 西兰花 + 红薯块",
            "鸡胸肉 + 南瓜 + 小米饭",
            "虾仁 + 胡萝卜 + 藜麦",
        ],
        "tip": "小型成犬代谢快，注意控制零食，避免超重～",
    },
    ("成犬", "中型犬"): {
        "meals": 2,
        "protein": "牛肉",    "veggie": "西兰花",  "carb": "红薯",
        "daily": [
            "牛肉 + 西兰花 + 红薯",
            "鸡腿肉 + 菠菜 + 糙米饭",
            "三文鱼 + 南瓜 + 燕麦",
        ],
        "tip": "每周2-3次红肉、1-2次鱼类，食材轮换营养更均衡～",
    },
    ("成犬", "大型犬"): {
        "meals": 2,
        "protein": "牛肉",    "veggie": "胡萝卜",  "carb": "糙米",
        "daily": [
            "牛肉 + 胡萝卜 + 糙米饭",
            "鸡胸肉 + 菠菜 + 红薯",
            "羊肉 + 西兰花 + 藜麦",
        ],
        "tip": "大型犬食量大，一次可备2-3天量分装冷冻，吃时加热～",
    },
    ("老年犬", "小型犬"): {
        "meals": 2,
        "protein": "鱼肉",    "veggie": "菠菜",    "carb": "南瓜",
        "daily": [
            "鱼肉 + 菠菜 + 南瓜羹",
            "鸡胸肉丝 + 胡萝卜泥 + 小米粥",
            "虾仁碎 + 西兰花 + 山药泥",
        ],
        "tip": "老年牙口不好，食材要软烂细碎，南瓜和山药助消化～",
    },
    ("老年犬", "中型犬"): {
        "meals": 2,
        "protein": "鱼肉",    "veggie": "菠菜",    "carb": "糙米",
        "daily": [
            "鱼肉 + 菠菜 + 糙米饭",
            "鸡胸肉 + 南瓜 + 小米粥",
            "牛肉末 + 胡萝卜 + 山药",
        ],
        "tip": "老年代谢慢，蛋白质选低脂易消化的鱼肉和鸡胸肉为主～",
    },
    ("老年犬", "大型犬"): {
        "meals": 2,
        "protein": "鱼肉",    "veggie": "菠菜",    "carb": "糙米",
        "daily": [
            "鱼肉 + 菠菜 + 糙米饭",
            "鸡胸肉 + 西兰花 + 红薯",
            "瘦牛肉 + 南瓜 + 藜麦",
        ],
        "tip": "老年大型犬关节负担重，鱼肉 Omega-3 有助抗炎护关节～",
    },
}


# 食材营养数据库（每100g含量：蛋白质g、脂肪g、碳水g）
FOOD_NUTRITION = {
    "鸡胸肉":   {"emoji": "🍗", "protein": 23.0, "fat": 1.5,  "carbs": 0},
    "鸭肉":     {"emoji": "🦆", "protein": 20.0, "fat": 12.0, "carbs": 0},
    "牛肉":     {"emoji": "🥩", "protein": 22.0, "fat": 8.0,  "carbs": 0},
    "瘦牛肉":   {"emoji": "🥩", "protein": 22.0, "fat": 8.0,  "carbs": 0},
    "三文鱼":   {"emoji": "🐟", "protein": 20.0, "fat": 14.0, "carbs": 0},
    "鳕鱼":     {"emoji": "🐟", "protein": 20.0, "fat": 0.5,  "carbs": 0},
    "虾仁":     {"emoji": "🦐", "protein": 20.0, "fat": 1.0,  "carbs": 0},
    "蛋黄":     {"emoji": "🥚", "protein": 16.0, "fat": 27.0, "carbs": 3.6},
    "羊肉":     {"emoji": "🐑", "protein": 20.0, "fat": 14.0, "carbs": 0},
    "鸡腿肉":   {"emoji": "🍗", "protein": 20.0, "fat": 10.0, "carbs": 0},
    "南瓜":     {"emoji": "🎃", "protein": 1.0,  "fat": 0.1,  "carbs": 7.0},
    "胡萝卜":   {"emoji": "🥕", "protein": 1.0,  "fat": 0.2,  "carbs": 10.0},
    "西兰花":   {"emoji": "🥦", "protein": 2.8,  "fat": 0.4,  "carbs": 7.0},
    "菠菜":     {"emoji": "🥬", "protein": 2.9,  "fat": 0.4,  "carbs": 3.6},
    "西葫芦":   {"emoji": "🥒", "protein": 1.2,  "fat": 0.3,  "carbs": 3.1},
    "燕麦":     {"emoji": "🌾", "protein": 13.5, "fat": 6.5,  "carbs": 66.0},
    "糙米":     {"emoji": "🍚", "protein": 7.5,  "fat": 2.7,  "carbs": 73.0},
    "红薯":     {"emoji": "🍠", "protein": 1.6,  "fat": 0.1,  "carbs": 20.0},
    "藜麦":     {"emoji": "🌾", "protein": 14.0, "fat": 6.0,  "carbs": 64.0},
    "小米":     {"emoji": "🌾", "protein": 11.0, "fat": 4.0,  "carbs": 73.0},
    "山药":     {"emoji": "🥔", "protein": 2.0,  "fat": 0.2,  "carbs": 28.0},
}

# 食材名标准化映射（去掉括号里的附注，统一别名）
def _normalize_food(name: str) -> str:
    """把带括号或别名的食材名标准化为 FOOD_NUTRITION 的 key"""
    if not name:
        return ""
    # 去掉中文括号里的附注
    name = re.sub(r"[（(][^)）]*[)）]", "", name).strip()
    # 别名映射
    aliases = {
        "鱼肉": "三文鱼", "鱼肉碎": "三文鱼", "牛肉糜": "牛肉",
        "鸡胸肉丁": "鸡胸肉", "鸡胸肉丝": "鸡胸肉",
        "虾仁碎": "虾仁", "牛肉末": "牛肉", "瘦牛肉": "牛肉",
    }
    return aliases.get(name, name)


def _parse_weight_kg(weight_str: Optional[str]) -> Optional[float]:
    """从体重字符串解析公斤数，无法解析返回 None"""
    if not weight_str or not weight_str.strip():
        return None
    try:
        return float(weight_str.strip().replace("kg", "").replace("KG", "").strip())
    except ValueError:
        return None


def _calc_rer(weight_kg: float) -> float:
    """计算静息能量需求 RER (kcal/day)"""
    if 2 <= weight_kg <= 45:
        return 30.0 * weight_kg + 70.0
    else:
        return 70.0 * (weight_kg ** 0.75)


def _calc_daily_grams(dog_birthday: date, weight_kg: float, neutered: str, gender: Optional[str] = None) -> dict:
    """根据 RER → DER → 喂食量 计算每日各食材克数，返回详细字典"""
    # Step 1: RER
    rer = _calc_rer(weight_kg)

    # Step 2: 生命阶段系数
    age_stage = _get_age_stage(dog_birthday)
    if age_stage == "幼犬":
        coeff = 2.5
    elif neutered == "是":
        coeff = 1.6
    else:
        coeff = 1.8

    # 性别系数：公犬基础代谢略高于母犬
    gender_coeff = 1.1 if gender == "male" else 1.0
    der = rer * coeff * gender_coeff

    # Step 3: 每日总喂食量（熟自制能量密度取 1.5 kcal/g）
    total_g = round(der / 1.5)

    # Step 4: 宏量营养素配比
    # 蛋白质 55% | 碳水 25% | 纤维+维生素 15% | 脂肪 5%（肉类自带+鱼油补充）
    protein_g = round(total_g * 0.55)
    carb_g    = round(total_g * 0.25)
    veggie_g  = round(total_g * 0.15)

    return {
        "weight_kg": weight_kg,
        "rer": round(rer),
        "coefficient": coeff,
        "der": round(der),
        "total_g": total_g,
        "protein_g": protein_g,
        "carb_g": carb_g,
        "veggie_g": veggie_g,
        "age_stage": age_stage,
    }


# ============================================================
# 保健品规则引擎
# ============================================================
SUPPLEMENT_RULES = [
    {
        "id": "joint_large_breed",
        "supplement": "关节保护（葡萄糖胺 + 软骨素）",
        "priority": 1,
        "condition": lambda dog, stats: (
            dog.breed and any(b in dog.breed for b in ["金毛", "拉布拉多", "德牧", "德国牧羊犬", "阿拉斯加", "萨摩耶", "伯恩山", "罗威纳"])
            and stats["age_months"] >= 6
        ),
        "reason": "大型犬髋关节发育风险高，预防关节问题",
        "woof": "主人，像我这样的大型犬，髋关节容易累，给我吃点葡萄糖胺和软骨素，老了还能陪你跑！",
    },
    {
        "id": "joint_senior",
        "supplement": "关节保护 + 抗氧化剂（葡萄糖胺、维生素E、辅酶Q10）",
        "priority": 1,
        "condition": lambda dog, stats: stats["age_stage"] == "老年犬",
        "reason": "老年关节退化、免疫力下降，需综合养护",
        "woof": "我步入黄金老年啦，关节需要好好养护，再来点抗氧化的东西，让我老得慢一点～",
    },
    {
        "id": "joint_long_body",
        "supplement": "关节保护（葡萄糖胺 + 软骨素，尤其脊椎）",
        "priority": 1,
        "condition": lambda dog, stats: (
            dog.breed and any(b in dog.breed for b in ["柯基", "腊肠", "巴吉度", "斗牛犬", "法斗", "英斗"])
            and stats["age_months"] >= 12
        ),
        "reason": "短腿长身犬种易患椎间盘疾病",
        "woof": "我们短腿家族腰背容易受伤，日常的关节保健品可不能停哦。",
    },
    {
        "id": "joint_heavy",
        "supplement": "关节保护（葡萄糖胺 + 软骨素）",
        "priority": 2,
        "condition": lambda dog, stats: (
            stats["weight_kg"] is not None and stats["weight_kg"] >= 30
            and stats["age_months"] >= 12
        ),
        "reason": "体重对关节压力大，需额外保护",
        "woof": "我太壮啦，关节天天扛着我跑，得补补！",
    },
    {
        "id": "multi_vitamin_puppy",
        "supplement": "综合维生素/矿物质（钙磷比均衡）",
        "priority": 1,
        "condition": lambda dog, stats: stats["age_stage"] == "幼犬",
        "reason": "生长发育期需均衡营养（若吃市售全价狗粮则通常无需额外补充）",
        "woof": "我正在长身体～如果主人给我吃的是自制狗饭，可以加一点综合营养粉让骨骼牙齿棒棒的；如果吃的是市售全价狗粮，一般不需要额外补哦，具体听兽医的！",
    },
    {
        "id": "omega3_itchy",
        "supplement": "Omega-3 鱼油",
        "priority": 2,
        "condition": lambda dog, stats: stats.get("scratching_count", 0) >= 2,
        "reason": "曾有多次抓痒记录，皮肤干燥或过敏瘙痒",
        "woof": "我之前老是挠痒痒，鱼油可以让我的皮肤不那么干痒，毛也亮！",
    },
    {
        "id": "probiotics_digest",
        "supplement": "益生菌",
        "priority": 2,
        "condition": lambda dog, stats: stats.get("vomit_count", 0) >= 1 or stats.get("diarrhea_count", 0) >= 1,
        "reason": "曾有呕吐/腹泻记录，需调理肠胃",
        "woof": "上次吐/拉肚子好难受，每天吃点益生菌，肚子会舒服很多～",
    },
    {
        "id": "beauty_curly",
        "supplement": "美毛产品（卵磷脂 + 生物素）",
        "priority": 3,
        "condition": lambda dog, stats: (
            dog.breed and any(b in dog.breed for b in ["贵宾", "泰迪", "比熊", "马尔济斯", "雪纳瑞", "约克夏"])
            and stats["age_months"] >= 6
        ),
        "reason": "卷毛易打结、皮肤脆弱，需养护毛发",
        "woof": "我这一身卷毛要勤打理，吃点美毛的，梳毛时就不会那么疼啦。",
    },
    {
        "id": "urinary_female_unneutered",
        "supplement": "蔓越莓提取物（泌尿/生殖健康）",
        "priority": 2,
        "condition": lambda dog, stats: (
            dog.gender == "female"
            and dog.neutered not in ("是",)
            and stats["age_months"] >= 36
        ),
        "reason": "未绝育母犬随年龄增长，子宫蓄脓和泌尿道感染风险增加",
        "woof": "主人，我还没绝育，年纪大了尿尿的地方容易不舒服，给我吃点蔓越莓保护一下吧～",
    },
    {
        "id": "prostate_male_unneutered",
        "supplement": "南瓜籽提取物（前列腺保健）",
        "priority": 2,
        "condition": lambda dog, stats: (
            dog.gender == "male"
            and dog.neutered not in ("是",)
            and stats["age_months"] >= 36
        ),
        "reason": "未绝育公犬易出现前列腺肥大等问题",
        "woof": "主人，我们没绝育的男孩子，前列腺要早点保养，南瓜籽就很好哦～",
    },
]

# 保健品去重 key：归并同一种保健品的多个原因
SUPPLEMENT_MERGE_KEYS = {
    "关节保护（葡萄糖胺 + 软骨素）": "joint_protect",
    "关节保护（葡萄糖胺 + 软骨素，尤其脊椎）": "joint_protect",
    "关节保护 + 抗氧化剂（葡萄糖胺、维生素E、辅酶Q10）": "joint_protect",
}


def _calc_supplements(db, dog: Dog) -> List[dict]:
    """根据规则引擎计算当前应推荐的保健品列表，返回去重后的活跃提醒"""
    today = date.today()
    age_months = (today.year - dog.birthday.year) * 12 + (today.month - dog.birthday.month)
    weight_kg = _parse_weight_kg(dog.weight)
    age_stage = _get_age_stage(dog.birthday)

    # 统计异常行为次数
    events = db.query(Event).filter(Event.dog_id == dog.id, Event.type == "异常行为").all()
    scratching_count = 0
    vomit_count = 0
    diarrhea_count = 0
    for e in events:
        detail_str = e.detail or ""
        detail_lower = detail_str.lower()
        if "scratch" in detail_lower or "抓痒" in detail_lower or "挠" in detail_lower:
            scratching_count += 1
        if "vomit" in detail_lower or "吐" in detail_lower:
            vomit_count += 1
        if "diarrhea" in detail_lower or "拉稀" in detail_lower or "腹泻" in detail_lower:
            diarrhea_count += 1

    stats = {
        "age_months": age_months,
        "age_stage": age_stage,
        "weight_kg": weight_kg,
        "scratching_count": scratching_count,
        "vomit_count": vomit_count,
        "diarrhea_count": diarrhea_count,
    }

    # 检查过敏源
    allergies_raw = (dog.allergies or "").strip()
    allergies_lower = allergies_raw.lower()
    has_fish_allergy = any(a in allergies_lower for a in ["鱼", "海鲜", "三文鱼", "鳕鱼"])
    has_chicken_allergy = any(a in allergies_lower for a in ["鸡", "禽"])
    has_grain_allergy = any(a in allergies_lower for a in ["谷物", "麦", "米", "麸"])
    has_beef_allergy = any(a in allergies_lower for a in ["牛"])
    has_egg_allergy = any(a in allergies_lower for a in ["蛋"])

    # 构建通用过敏提示
    def _build_allergy_warning() -> str:
        if not allergies_raw:
            return ""
        parts = []
        if has_chicken_allergy:
            parts.append("避开含鸡/禽成分的产品")
        if has_fish_allergy:
            parts.append("避开含鱼油/鱼成分的产品")
        if has_beef_allergy:
            parts.append("避开含牛成分的产品")
        if has_grain_allergy:
            parts.append("避开含谷物成分的产品")
        if has_egg_allergy:
            parts.append("避开含蛋成分的产品")
        if parts:
            return "（⚠️ 狗狗对" + allergies_raw + "过敏，选择保健品时" + "、".join(parts) + "）"
        return "（⚠️ 狗狗有过敏源：" + allergies_raw + "，选择保健品时请留意成分表）"

    allergy_warning = _build_allergy_warning()

    # 评估规则
    merged = {}  # merge_key -> {supplement, reasons, woofs, priority}
    for rule in SUPPLEMENT_RULES:
        try:
            if not rule["condition"](dog, stats):
                continue
        except Exception:
            continue

        supp_name = rule["supplement"]
        merge_key = SUPPLEMENT_MERGE_KEYS.get(supp_name, supp_name)

        # 过敏检查：鱼过敏跳过鱼油
        if has_fish_allergy and "鱼油" in supp_name:
            continue

        if merge_key in merged:
            entry = merged[merge_key]
            if rule["reason"] not in entry["reasons"]:
                entry["reasons"].append(rule["reason"])
            entry["priority"] = min(entry["priority"], rule["priority"])
            if rule["priority"] < entry.get("_best_pri", 99):
                entry["woof"] = rule["woof"]
                entry["_best_pri"] = rule["priority"]
                entry["supplement"] = supp_name
        else:
            merged[merge_key] = {
                "supplement": supp_name,
                "reasons": [rule["reason"]],
                "woof": rule["woof"],
                "priority": rule["priority"],
                "_best_pri": rule["priority"],
            }

    # 按优先级排序
    result = sorted(merged.values(), key=lambda x: x["priority"])
    for item in result:
        item.pop("_best_pri", None)
        item["reasons_text"] = "；".join(item["reasons"])
        suffix = "\n（参考剂量请遵兽医指导，不可使用人用保健品替代哦～）"
        if allergy_warning:
            suffix = "\n" + allergy_warning + suffix
        item["woof_full"] = item["woof"] + suffix
    return result


def _refresh_supplement_alerts(db, dog: Dog):
    """重新计算并更新保健品提醒表"""
    alerts = _calc_supplements(db, dog)

    # 标记所有旧提醒为过期
    db.query(SupplementAlert).filter(
        SupplementAlert.dog_id == dog.id, SupplementAlert.is_active == 1
    ).update({"is_active": 0})

    # 插入新提醒
    for a in alerts:
        alert = SupplementAlert(
            dog_id=dog.id,
            supplement_name=a["supplement"],
            reason=a["reasons_text"],
            woof_text=a["woof_full"],
            priority=a["priority"],
            is_active=1,
        )
        db.add(alert)
    db.flush()


@app.get("/api/supplements")
def api_supplements():
    """返回当前狗狗的保健品推荐列表"""
    with get_db() as db:
        dog = db.query(Dog).order_by(Dog.created_at.desc()).first()
        if not dog:
            return {"has_dog": False, "alerts": []}

        # 检查是否被高风险事件暂停
        if dog.suspended_until and dog.suspended_until > datetime.utcnow():
            return {"has_dog": True, "suspended": True, "alerts": [], "message": "🚨 因您最近记录了高风险症状，今日保健品建议已暂停。请优先联系兽医，确认宠物状况稳定后可点击下方按钮恢复建议。"}

        # 每次请求时刷新计算
        _refresh_supplement_alerts(db, dog)

        alerts = db.query(SupplementAlert).filter(
            SupplementAlert.dog_id == dog.id, SupplementAlert.is_active == 1
        ).order_by(SupplementAlert.priority).all()

        return {
            "has_dog": True,
            "dog_name": dog.name,
            "alerts": [
                {
                    "id": a.id,
                    "supplement_name": a.supplement_name,
                    "reason": a.reason,
                    "woof_text": a.woof_text,
                    "priority": a.priority,
                }
                for a in alerts
            ],
        }


@app.get("/api/health_check")
def api_health_check():
    """后端健康状态检查 + 紧急提醒判断 + 最新大事记"""
    with get_db() as db:
        dog = db.query(Dog).order_by(Dog.created_at.desc()).first()
        if not dog:
            return {"has_dog": False, "reminders": [], "latest_event": None}

        events = db.query(Event).filter(Event.dog_id == dog.id).order_by(Event.date.desc()).all()

        # 按类型找最近一次日期
        last_vaccine = None
        last_deworm = None
        last_heat = None
        for e in events:
            if e.type == "疫苗" and (last_vaccine is None or e.date > last_vaccine):
                last_vaccine = e.date
            if e.type == "驱虫" and (last_deworm is None or e.date > last_deworm):
                last_deworm = e.date
            if e.type == "发情" and (last_heat is None or e.date > last_heat):
                last_heat = e.date

        # 最新一条大事记（供前端个性化今日汪汪）
        latest_event = None
        if events:
            le = events[0]
            latest_event = {
                "id": le.id,
                "type": le.type,
                "date": le.date.isoformat(),
                "detail": le.detail,
            }

        reminders: List[Dict[str, str]] = []
        today = date.today()

        # 疫苗：核心疫苗（犬瘟/细小/腺病毒）默认3年周期（WSAVA指南），非核心疫苗遵兽医建议
        if last_vaccine:
            next_vaccine = last_vaccine + timedelta(days=1095)  # 3年 = 1095天
            days_left = (next_vaccine - today).days
            if days_left <= 60:
                if days_left < 0:
                    reminders.append({
                        "type": "疫苗",
                        "text": f"主人，掐爪一算，我的核心疫苗保护已超过推荐周期啦！快带我去看兽医，让医生决定我是需要加强还是做抗体检测～不同的疫苗加强周期不同，遵医嘱最重要！",
                    })
                else:
                    reminders.append({
                        "type": "疫苗",
                        "text": f"主人，掐爪一算，我的核心疫苗大约还有{days_left}天需要关注，不同疫苗加强周期不同（核心疫苗通常每3年，非核心疫苗可能每年），记得问兽医我的具体情况哦～",
                    })
        else:
            reminders.append({
                "type": "疫苗",
                "text": "主人，我还没有打过疫苗呢！幼犬首免通常在6-8周龄开始，每2-4周加强至16周龄以上；成年后核心疫苗遵医嘱每1-3年加强。快带我去看兽医制定免疫计划吧～",
            })

        # 驱虫：根据年龄+品种动态间隔，提前 14 天提醒
        deworm_interval = _get_deworm_interval(dog.birthday, dog.breed)
        if last_deworm:
            next_deworm = last_deworm + timedelta(days=deworm_interval)
            days_left = (next_deworm - today).days
            days_since_last = (today - last_deworm).days
            if days_left <= 14:
                if days_left == 0:
                    reminders.append({
                        "type": "驱虫",
                        "text": f"主人，距离上次驱虫已经{days_since_last}天了，又到了给我驱虫的时间啦！快帮我准备药药，把讨厌的小虫子都赶走～",
                    })
                elif days_left < 0:
                    reminders.append({
                        "type": "驱虫",
                        "text": f"主人，距离上次驱虫已经{days_since_last}天啦！体内外的小虫子可能在偷偷捣乱，快给我安排驱虫药吧～",
                    })
                else:
                    reminders.append({
                        "type": "驱虫",
                        "text": f"主人，还有{days_left}天又该驱虫啦，提前买好药药，让那些「不速之客」没有可乘之机！",
                    })
        else:
            reminders.append({
                "type": "驱虫",
                "text": "主人，我还没做过驱虫呢！体内外驱虫从小就要开始做，让我远离寄生虫的困扰～",
            })

        # 发情：未绝育母犬约 6 个月一次（仅母犬）
        if dog.gender == "female" and dog.neutered not in ("是",):
            if last_heat:
                next_heat = last_heat + timedelta(days=180)
                days_left = (next_heat - today).days
                if days_left <= 21:
                    if days_left < 0:
                        reminders.append({
                            "type": "发情",
                            "text": "主人，我可能已经进入发情期了！出门一定要牵好我，给我穿好生理裤，不要让陌生的公狗狗靠近我哦～",
                        })
                    else:
                        reminders.append({
                            "type": "发情",
                            "text": f"主人，掐爪一算，我的发情期快到了（大约还有{days_left}天），提前准备好生理裤和小垫垫吧～",
                        })

        # 洗澡提醒：优先级低于疫苗/驱虫/发情，高于随机tip
        bath_interval = dog.bath_interval_days or 10
        if dog.last_bath_date:
            next_bath = dog.last_bath_date + timedelta(days=bath_interval)
            days_overdue = (today - next_bath).days
            if days_overdue >= 0:
                days_since = (today - dog.last_bath_date).days
                reminders.append({
                    "type": "洗澡澡",
                    "text": f"主人，掐爪一算我都{days_since}天没洗澡啦，身上都有小狗味儿了！快带我洗香香吧～🛁",
                })

        # 保健品提醒：刷新计算并随机加入一条（优先级低于洗澡）
        _refresh_supplement_alerts(db, dog)
        active_supps = db.query(SupplementAlert).filter(
            SupplementAlert.dog_id == dog.id, SupplementAlert.is_active == 1
        ).order_by(SupplementAlert.priority).all()
        if active_supps:
            import random as _random
            pick = _random.choice(active_supps)
            reminders.append({
                "type": "保健品",
                "text": f"💊 {pick.woof_text.split(chr(10))[0]}",
            })

        # 最后洗澡日期和下次洗澡到期日
        last_bath_date = dog.last_bath_date
        next_bath_due = None
        if last_bath_date:
            next_bath_due = (last_bath_date + timedelta(days=dog.bath_interval_days or 10)).isoformat()
            last_bath_date = last_bath_date.isoformat()
        last_vaccine_date = last_vaccine.isoformat() if last_vaccine else None

        # 活跃保健品数量（用于入口角标）
        active_supp_count = db.query(SupplementAlert).filter(
            SupplementAlert.dog_id == dog.id, SupplementAlert.is_active == 1
        ).count()

        return {
            "has_dog": True,
            "dog": {
                "id": dog.id,
                "name": dog.name,
                "breed": dog.breed,
                "birthday": dog.birthday.isoformat(),
                "weight": dog.weight or "",
                "neutered": dog.neutered or "未知",
                "allergies": dog.allergies or "",
                "photo": dog.photo or "",
                "gender": dog.gender or "",
            },
            "reminders": reminders,
            "latest_event": latest_event,
            "pending_actions": len(reminders),
            "last_vaccine_date": last_vaccine_date,
            "last_bath_date": last_bath_date,
            "next_bath_due": next_bath_due,
            "active_supplements_count": active_supp_count,
        }


@app.get("/api/vet_summary/{event_id}")
def api_vet_summary(event_id: int):
    """为异常行为事件生成兽医摘要卡片数据"""
    with get_db() as db:
        event = db.query(Event).filter(Event.id == event_id).first()
        if not event:
            raise HTTPException(status_code=404, detail="找不到这条事件记录，主人～")
        if event.type != "异常行为":
            raise HTTPException(status_code=400, detail="只有异常行为事件才能生成兽医摘要哦，主人～")
        dog = db.query(Dog).filter(Dog.id == event.dog_id).first()
        if not dog:
            raise HTTPException(status_code=404, detail="找不到关联的狗狗档案，主人～")

        symptoms = []
        detail_dict = {}
        if event.detail:
            try:
                detail_dict = json.loads(event.detail)
            except (json.JSONDecodeError, TypeError):
                pass
            if isinstance(detail_dict, dict):
                symptoms = detail_dict.get("symptoms", [])

        analysis = analyze_behavior(dog.breed, symptoms)

        today = date.today()
        age_months = (today.year - dog.birthday.year) * 12 + (today.month - dog.birthday.month)
        if age_months < 12:
            age_str = f"{age_months}个月"
        else:
            years = age_months // 12
            m = age_months % 12
            age_str = f"{years}岁" + (f"{m}个月" if m > 0 else "")

        # 计算最高风险等级
        level_order = {"高": 4, "中高": 3, "中": 2, "中低": 1, "未分级": 0}
        max_level = "未分级"
        for r in analysis["results"]:
            if level_order.get(r["level"], 0) > level_order.get(max_level, 0):
                max_level = r["level"]

        level_label = {"高": "🔴 建议尽快就诊", "中高": "🟠 建议近期就诊", "中": "🟡 持续观察", "中低": "🟢 居家护理", "未分级": "⚪ 仅供参考"}.get(max_level, "⚪ 仅供参考")

        return {
            "dog": {
                "name": dog.name,
                "breed": dog.breed,
                "birthday": dog.birthday.isoformat(),
                "age": age_str,
                "weight": dog.weight or "未记录",
                "neutered": dog.neutered or "未知",
                "allergies": dog.allergies or "无",
                "gender": dog.gender or "",
            },
            "event_date": event.date.isoformat(),
            "symptoms": symptoms,
            "overall_risk": max_level,
            "overall_label": level_label,
            "analysis": analysis["results"],
        }


@app.get("/api/export")
def api_export_data():
    """导出全部数据为 CSV（Excel 可直接打开）"""
    with get_db() as db:
        dog = db.query(Dog).order_by(Dog.created_at.desc()).first()
        if not dog:
            raise HTTPException(status_code=404, detail="还没有狗狗档案，主人先去建档吧～")
        events = db.query(Event).filter(Event.dog_id == dog.id).order_by(Event.date.desc()).all()
        weight_logs = db.query(WeightLog).filter(WeightLog.dog_id == dog.id).order_by(WeightLog.date.desc()).all()

        output = io.StringIO()
        output.write("﻿")
        writer = csv.writer(output)

        writer.writerow(["=== 狗狗档案 ==="])
        writer.writerow(["名字", "品种", "生日", "体重", "绝育", "过敏源"])
        writer.writerow([dog.name, dog.breed, dog.birthday.isoformat(), dog.weight or "", dog.neutered or "未知", dog.allergies or ""])
        writer.writerow([])

        writer.writerow(["=== 大事记 ==="])
        writer.writerow(["类型", "日期", "备注"])
        for e in events:
            detail_str = ""
            if e.detail:
                try:
                    d = json.loads(e.detail)
                    if e.type == "疫苗":
                        parts = []
                        if d.get("dose"): parts.append(f"第{d['dose']}针")
                        if d.get("brand"): parts.append(d["brand"])
                        detail_str = " · ".join(parts)
                    elif e.type == "驱虫":
                        detail_str = d.get("brand", "") or d.get("deworm_type", "")
                    elif e.type == "发情":
                        detail_str = d.get("note", "")
                    elif e.type == "异常行为":
                        symptoms = d.get("symptoms", [])
                        detail_str = "、".join(symptoms) if symptoms else ""
                except (json.JSONDecodeError, TypeError):
                    pass
            writer.writerow([e.type, e.date.isoformat(), detail_str])
        writer.writerow([])

        writer.writerow(["=== 体重记录 ==="])
        writer.writerow(["日期", "体重"])
        for w in weight_logs:
            writer.writerow([w.date.isoformat(), w.weight])

        csv_content = output.getvalue()
        safe_name = quote(dog.name)
        filename = f"attachment; filename*=UTF-8''PawLife_{safe_name}_{date.today().isoformat()}.csv"
        return Response(content=csv_content, media_type="text/csv; charset=utf-8-sig", headers={"Content-Disposition": filename})


# ============================================================
# 第一层习惯层 API：每日tip、测验、任务、签到
# ============================================================

@app.get("/api/daily_tip")
def api_daily_tip():
    """返回一条个性化每日生存指南，根据品种/年龄/季节加权"""
    with get_db() as db:
        dog = db.query(Dog).order_by(Dog.created_at.desc()).first()
        breed = dog.breed if dog else None
        birthday = dog.birthday if dog else None
    today = date.today()
    month = today.month

    # 计算年龄阶段
    age_stage = None
    if birthday:
        age_months = (today.year - birthday.year) * 12 + (today.month - birthday.month)
        if age_months <= 12:
            age_stage = "puppy"
        elif age_months < 84:
            age_stage = "adult"
        else:
            age_stage = "senior"

    # 品种关节风险列表
    joint_breeds = ["金毛", "拉布拉多", "柯基"]

    # 构建加权池
    weighted: List[tuple] = []
    for tip in SURVIVAL_TIPS:
        w = 1.0
        cat = tip["category"]

        # 季节权重
        if month in (6, 7, 8) and cat == "season":
            if any(kw in tip["text"] for kw in ["夏天", "防中暑", "中暑", "补水", "柏油", "蜱虫", "游泳"]):
                w *= 3.0
        elif month in (12, 1, 2) and cat == "season":
            if any(kw in tip["text"] for kw in ["冬天", "保暖", "暖气", "擦脚", "衣服"]):
                w *= 3.0
        elif month in (3, 4, 5) and cat == "season":
            if any(kw in tip["text"] for kw in ["春天", "花粉", "换毛", "跳蚤"]):
                w *= 3.0

        # 品种权重：关节相关品种 + health_tip 中关节内容
        if breed and breed in joint_breeds and cat == "health_tip":
            if any(kw in tip["text"] for kw in ["关节", "髋关节", "骨骼", "软骨"]):
                w *= 2.0

        # 年龄权重
        if age_stage == "puppy" and cat in ("food_good", "care"):
            w *= 1.8
        elif age_stage == "senior" and cat == "health_tip":
            w *= 1.5

        weighted.append((tip, w))

    # 按权重随机选择
    total_w = sum(w for _, w in weighted)
    import random as _random
    r = _random.uniform(0, total_w)
    cumulative = 0.0
    chosen = weighted[0][0]
    for tip, w in weighted:
        cumulative += w
        if r <= cumulative:
            chosen = tip
            break

    return {"text": chosen["text"], "category": chosen["category"]}


@app.get("/api/quiz")
def api_quiz(pet_id: int = 1):
    """返回今日测验题目（同一天同一只狗同一题）"""
    import random as _random
    from sqlalchemy import func as sa_func
    today = date.today()
    seed = today.year * 10000 + today.month * 100 + today.day + pet_id * 7
    _random.seed(seed)
    quiz = _random.choice(QUIZZES)
    _random.seed()

    # 检查今日是否已答对过
    with get_db() as db:
        already = db.query(PawPointsLog).filter(
            PawPointsLog.pet_id == pet_id,
            PawPointsLog.reason == "答对测验",
            sa_func.date(PawPointsLog.created_at) == today
        ).first()

    return {
        "question": quiz["question"], "options": quiz["options"],
        "explanation": quiz["explanation"], "answer": quiz["answer"],
        "already_answered": already is not None,
    }


@app.post("/api/quiz/complete")
def api_quiz_complete(pet_id: int = 1, correct: int = 0):
    """答对测验，奖励爪印积分（每天只计一次）"""
    from sqlalchemy import func as sa_func
    with get_db() as db:
        dog = db.query(Dog).filter(Dog.id == pet_id).first()
        if not dog:
            raise HTTPException(status_code=404, detail="狗狗档案不存在")
        # 检查今日是否已答对过
        today = date.today()
        already = db.query(PawPointsLog).filter(
            PawPointsLog.pet_id == pet_id,
            PawPointsLog.reason == "答对测验",
            sa_func.date(PawPointsLog.created_at) == today
        ).first()
        if already:
            return {"paw_points": dog.paw_points or 0, "earned": 0, "already_done": True}
        if correct == 1:
            add_paw_points(db, pet_id, 2, "答对测验")
            return {"paw_points": dog.paw_points, "earned": 2}
        return {"paw_points": dog.paw_points or 0, "earned": 0}


@app.get("/api/task")
def api_task(pet_id: int = 1):
    """返回今日小任务（同一天同一只狗同一任务，带 action_type）"""
    import random as _random
    today = date.today()
    seed = today.year * 10000 + today.month * 100 + today.day + pet_id * 13
    _random.seed(seed)
    task = _random.choice(DAILY_TASKS)
    _random.seed()

    # 检查今日是否已完成任务
    with get_db() as db:
        ci = db.query(CheckIn).filter(
            CheckIn.pet_id == pet_id,
            CheckIn.check_date == today
        ).first()
        done = ci.task_completed == 1 if ci else False

    return {
        "task_id": task["id"],
        "task": task["task"],
        "action_type": task["action_type"],
        "button_text": task["button_text"],
        "thanks": task["thanks"],
        "done": done,
    }


@app.get("/api/checkin/status")
def api_checkin_status(pet_id: int = 1):
    """返回当前签到状态：连续天数、今日是否已签到、勋章列表、爪印积分"""
    with get_db() as db:
        dog = db.query(Dog).filter(Dog.id == pet_id).first()
        if not dog:
            return {"pet_id": pet_id, "streak": 0, "checked_today": False, "badges": [], "paw_points": 0, "task_done": False}

        today = date.today()
        checkin = db.query(CheckIn).filter(
            CheckIn.pet_id == pet_id,
            CheckIn.check_date == today
        ).first()

        last = db.query(CheckIn).filter(
            CheckIn.pet_id == pet_id
        ).order_by(CheckIn.check_date.desc()).first()

        streak = last.streak if last else 0
        if not checkin:
            if last and last.check_date < today - timedelta(days=1):
                streak = 0

        badges = []
        if dog.badges:
            try:
                badges = json.loads(dog.badges)
            except (json.JSONDecodeError, TypeError):
                badges = []

        return {
            "pet_id": pet_id,
            "streak": streak,
            "checked_today": checkin is not None,
            "badges": badges,
            "badge_count": len(badges),
            "paw_points": dog.paw_points or 0,
            "task_done": checkin.task_completed == 1 if checkin else False,
        }


@app.post("/api/checkin")
def api_checkin(pet_id: int = 1):
    """执行签到。奖励+1爪印积分。返回streak和可能的里程碑。"""
    with get_db() as db:
        dog = db.query(Dog).filter(Dog.id == pet_id).first()
        if not dog:
            raise HTTPException(status_code=404, detail="狗狗档案不存在")

        today = date.today()

        existing = db.query(CheckIn).filter(
            CheckIn.pet_id == pet_id,
            CheckIn.check_date == today
        ).first()
        if existing:
            badges = []
            if dog.badges:
                try:
                    badges = json.loads(dog.badges)
                except (json.JSONDecodeError, TypeError):
                    badges = []
            return {"already_checked": True, "streak": existing.streak, "badges": badges, "milestone": None, "paw_points": dog.paw_points or 0}

        last = db.query(CheckIn).filter(
            CheckIn.pet_id == pet_id
        ).order_by(CheckIn.check_date.desc()).first()

        new_streak = 1
        if last:
            if last.check_date == today - timedelta(days=1):
                new_streak = last.streak + 1
            elif last.check_date == today:
                new_streak = last.streak
            else:
                new_streak = 1

        ci = CheckIn(pet_id=pet_id, check_date=today, streak=new_streak)
        db.add(ci)
        add_paw_points(db, pet_id, 1, "签到")

        milestone = None
        for days, badge_name in CHECKIN_MILESTONES:
            if new_streak == days:
                milestone = badge_name
                badges = []
                if dog.badges:
                    try:
                        badges = json.loads(dog.badges)
                    except (json.JSONDecodeError, TypeError):
                        badges = []
                if badge_name not in badges:
                    badges.append(badge_name)
                    dog.badges = json.dumps(badges, ensure_ascii=False)
                break

        db.commit()

        # 检查并授予勋章
        new_badges = check_badges(db, pet_id)

        badges = []
        if dog.badges:
            try:
                badges = json.loads(dog.badges)
            except (json.JSONDecodeError, TypeError):
                badges = []
        return {
            "already_checked": False,
            "streak": new_streak,
            "milestone": milestone,
            "badges": badges,
            "paw_points": dog.paw_points,
            "new_badges": new_badges or [],
        }


@app.post("/api/task/complete")
def api_task_complete(pet_id: int = 1, task_id: str = ""):
    """完成任务。如果今天还没签到，自动补签。奖励+1爪印积分（任务奖励）。防重复提交。"""
    with get_db() as db:
        dog = db.query(Dog).filter(Dog.id == pet_id).first()
        if not dog:
            raise HTTPException(status_code=404, detail="狗狗档案不存在")

        today = date.today()
        existing = db.query(CheckIn).filter(
            CheckIn.pet_id == pet_id,
            CheckIn.check_date == today
        ).first()

        auto_checked = False
        new_streak = 0
        milestone = None

        if not existing:
            last = db.query(CheckIn).filter(
                CheckIn.pet_id == pet_id
            ).order_by(CheckIn.check_date.desc()).first()

            new_streak = 1
            if last:
                if last.check_date == today - timedelta(days=1):
                    new_streak = last.streak + 1
                else:
                    new_streak = 1

            ci = CheckIn(pet_id=pet_id, check_date=today, streak=new_streak, task_completed=1)
            db.add(ci)
            auto_checked = True
            add_paw_points(db, pet_id, 1, "签到")
            add_paw_points(db, pet_id, 2, "任务完成")

            for days, badge_name in CHECKIN_MILESTONES:
                if new_streak == days:
                    milestone = badge_name
                    badges = []
                    if dog.badges:
                        try:
                            badges = json.loads(dog.badges)
                        except (json.JSONDecodeError, TypeError):
                            badges = []
                    if badge_name not in badges:
                        badges.append(badge_name)
                        dog.badges = json.dumps(badges, ensure_ascii=False)
                    break
        else:
            new_streak = existing.streak
            if existing.task_completed == 1:
                # 今天已完成过任务，不重复奖励
                badges = []
                if dog.badges:
                    try:
                        badges = json.loads(dog.badges)
                    except (json.JSONDecodeError, TypeError):
                        badges = []
                return {"auto_checked": False, "streak": new_streak, "milestone": None, "badges": badges, "already_done": True, "paw_points": dog.paw_points or 0}
            # 标记任务完成，+2分
            existing.task_completed = 1
            add_paw_points(db, pet_id, 2, "任务完成")

        db.commit()

        # 检查并授予勋章
        new_badges = check_badges(db, pet_id)

        badges = []
        if dog.badges:
            try:
                badges = json.loads(dog.badges)
            except (json.JSONDecodeError, TypeError):
                badges = []
        return {"auto_checked": auto_checked, "streak": new_streak, "milestone": milestone, "badges": badges, "already_done": False, "paw_points": dog.paw_points, "new_badges": new_badges or []}


@app.get("/api/daily_check")
def api_get_daily_check(pet_id: int = 1):
    """获取今日健康检查状态"""
    with get_db() as db:
        today = date.today()
        event = db.query(Event).filter(
            Event.dog_id == pet_id,
            Event.type == "每日检查",
            Event.date == today
        ).first()
        if event:
            import json
            detail = {}
            try:
                detail = json.loads(event.detail) if event.detail else {}
            except (json.JSONDecodeError, TypeError):
                pass
            return {"done": True, "result": detail.get("result", "normal"), "detail": detail.get("note", "")}
        return {"done": False, "result": None}


@app.post("/api/daily_check")
def api_record_daily_check(pet_id: int = 1, result: str = "normal", note: str = ""):
    """记录今日健康检查。result: normal / abnormal"""
    if result not in ("normal", "abnormal"):
        raise HTTPException(status_code=400, detail="result 必须是 normal 或 abnormal")
    with get_db() as db:
        dog = db.query(Dog).filter(Dog.id == pet_id).first()
        if not dog:
            raise HTTPException(status_code=404, detail="狗狗档案不存在")
        today = date.today()
        existing = db.query(Event).filter(
            Event.dog_id == pet_id,
            Event.type == "每日检查",
            Event.date == today
        ).first()
        if existing:
            return {"already_done": True, "message": "今日已完成健康检查，明天再来吧～"}
        import json
        detail_map = {
            "normal": json.dumps({"result": "normal", "note": "主人摸摸了头部、背部、四肢和腹部，一切正常 ✅"}, ensure_ascii=False),
            "abnormal": json.dumps({"result": "abnormal", "note": note or "主人发现异常，需要进一步检查 ⚠️"}, ensure_ascii=False),
        }
        event = Event(
            dog_id=pet_id,
            type="每日检查",
            date=today,
            detail=detail_map[result],
        )
        db.add(event)
        add_paw_points(db, pet_id, 1, "每日健康检查")
        db.commit()
        check_badges(db, pet_id)
        return {"message": "健康检查记录成功！+1 爪印 🐾", "paw_points": dog.paw_points or 0}


# ============================================================
# 头像盲盒 — 照片上传 / 删除 / 兑换 / 每日头像 API
# ============================================================

@app.post("/api/pets/{pet_id}/photos")
async def api_upload_blindbox_photo(pet_id: int, file: UploadFile = File(...)):
    """上传照片到肉垫影集。零门槛，最多6张。存Base64。"""
    import base64

    if file.content_type not in ("image/jpeg", "image/png", "image/jpg"):
        raise HTTPException(status_code=400, detail="主人，只支持 JPG 和 PNG 格式的图片哦～")

    contents = await file.read()
    if len(contents) > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="主人，图片太大了（不能超过 2MB），压缩一下再上传吧～")

    ext = os.path.splitext(file.filename or "photo.jpg")[1].lower()
    if ext not in (".jpg", ".jpeg", ".png"):
        raise HTTPException(status_code=400, detail="主人，只支持 .jpg 和 .png 格式的图片哦～")

    with get_db() as db:
        dog = db.query(Dog).filter(Dog.id == pet_id).first()
        if not dog:
            raise HTTPException(status_code=404, detail="狗狗档案不存在")

        photos = json.loads(dog.photos) if dog.photos else []
        if len(photos) >= 6:
            raise HTTPException(status_code=400, detail="主人，百变秀已经装满啦（最多6张），可以删除旧照片再上传新的～")

        mime = file.content_type or "image/jpeg"
        b64 = base64.b64encode(contents).decode("utf-8")
        data_url = f"data:{mime};base64,{b64}"
        photos.append(data_url)
        dog.photos = json.dumps(photos, ensure_ascii=False)

        # 如果已兑换盲盒且这是第一张照片，初始化头像
        if len(photos) == 1 and dog.avatar_unlocked == 1:
            dog.today_avatar_index = 0
            dog.avatar_date = date.today()

        db.commit()
        return {"message": f"汪汪！照片已加入～现在共有 {len(photos)} 张照片啦！", "photo_count": len(photos), "avatar_unlocked": bool(dog.avatar_unlocked)}


@app.delete("/api/pets/{pet_id}/photos")
def api_delete_blindbox_photo(pet_id: int, index: int = -1):
    """删除肉垫影集中指定索引的照片。"""
    with get_db() as db:
        dog = db.query(Dog).filter(Dog.id == pet_id).first()
        if not dog:
            raise HTTPException(status_code=404, detail="狗狗档案不存在")

        photos = json.loads(dog.photos) if dog.photos else []
        if index < 0 or index >= len(photos):
            raise HTTPException(status_code=400, detail="主人，找不到这张照片哦～")

        removed = photos.pop(index)

        if dog.today_avatar_index is not None:
            if dog.today_avatar_index == index:
                dog.avatar_date = None
                dog.today_avatar_index = None
            elif dog.today_avatar_index > index:
                dog.today_avatar_index -= 1

        dog.photos = json.dumps(photos, ensure_ascii=False) if photos else None
        if not photos:
            dog.today_avatar_index = None
            dog.avatar_date = None

        db.commit()
        return {"message": "照片已删除～", "photo_count": len(photos)}


@app.get("/api/pets/{pet_id}/avatar")
def api_get_daily_avatar(pet_id: int, idx: int = -1):
    """获取今日头像。优先使用健康事件照片；若无则使用档案照。自动解锁后即可使用。
    idx>=0时返回指定索引的Base64照片（用于相册缩略图）。"""
    import random as _random
    with get_db() as db:
        dog = db.query(Dog).filter(Dog.id == pet_id).first()
        if not dog:
            raise HTTPException(status_code=404, detail="狗狗档案不存在")

        photos = json.loads(dog.photos) if dog.photos else []
        hphotos = json.loads(dog.health_photos) if dog.health_photos else []

        # 同时从事件表中拉取带照片的事件（尚未同步到health_photos的，排除异常行为）
        event_photos = db.query(Event).filter(
            Event.dog_id == pet_id, Event.photo.isnot(None), Event.photo != "",
            Event.type != "异常行为"
        ).order_by(Event.date.desc()).all()
        # 合并：hphotos中已有的filename跳过，避免重复
        existing_filenames = {hp.get("filename", "") for hp in hphotos}
        for ep in event_photos:
            if ep.photo and ep.photo not in existing_filenames:
                hphotos.append({
                    "filename": ep.photo,
                    "event_type": ep.type,
                    "event_date": ep.date.isoformat(),
                    "label": ep.type,
                })
                existing_filenames.add(ep.photo)

        # 指定索引模式：返回Base64盲盒照片（兼容旧相册缩略图）
        if idx >= 0 and idx < len(photos):
            return {
                "avatar": photos[idx],
                "photo_count": len(photos),
                "health_photo_count": len(hphotos),
                "index": idx,
                "avatar_unlocked": bool(dog.avatar_unlocked),
            }

        # 合并所有照片：健康照片优先（文件路径），然后是旧盲盒照片（Base64）
        all_photos = []
        for hp in hphotos:
            filename = hp.get("filename", "")
            if filename:
                all_photos.append({
                    "url": f"/photos/{filename}",
                    "type": "health",
                    "event_type": hp.get("event_type", ""),
                    "event_date": hp.get("event_date", ""),
                    "label": hp.get("label", ""),
                })
        for i, p in enumerate(photos):
            all_photos.append({"url": p, "type": "legacy", "index": i})

        # 如果没有任何照片（健康照+旧照），但有档案照 → 返回档案照
        if not all_photos:
            if dog.photo:
                return {
                    "avatar": f"/photos/{dog.photo}",
                    "photo_count": len(photos),
                    "health_photo_count": len(hphotos),
                    "avatar_unlocked": bool(dog.avatar_unlocked),
                    "avatar_hint": "我的档案照",
                }
            return {
                "avatar": None,
                "photo_count": len(photos),
                "health_photo_count": len(hphotos),
                "avatar_unlocked": bool(dog.avatar_unlocked),
                "message": "还没有照片哦，主人快去记录事件后上传纪念照吧～",
            }

        # 未解锁（无健康事件记录）→ 只返回档案照，不随机
        if dog.avatar_unlocked != 1:
            # 如果有档案照(photo字段)，返回它
            if dog.photo:
                return {
                    "avatar": f"/photos/{dog.photo}",
                    "photo_count": len(photos),
                    "health_photo_count": len(hphotos),
                    "avatar_unlocked": False,
                    "message": "主人，记录一次健康事件就能解锁每日头像哦～",
                }
            return {
                "avatar": None,
                "photo_count": len(photos),
                "health_photo_count": len(hphotos),
                "avatar_unlocked": False,
                "message": "主人，记录一次健康事件就能解锁每日头像哦～",
            }

        today = date.today()

        # 每日头像选择：优先选今天日期匹配的健康照片
        today_str = today.isoformat()
        today_matches = [p for p in all_photos if p.get("event_date") == today_str and p["type"] == "health"]
        if today_matches:
            chosen = _random.choice(today_matches)
            return {
                "avatar": chosen["url"],
                "photo_count": len(photos),
                "health_photo_count": len(hphotos),
                "index": all_photos.index(chosen),
                "date": today_str,
                "avatar_unlocked": True,
                "avatar_hint": f"这是我{chosen.get('label', chosen.get('event_type', ''))}那天的照片哦～",
            }

        # 没有今天匹配的健康照片 → 优先使用档案照
        if dog.photo:
            return {
                "avatar": f"/photos/{dog.photo}",
                "photo_count": len(photos),
                "health_photo_count": len(hphotos),
                "avatar_unlocked": True,
                "avatar_hint": "我的档案照",
            }

        # 否则随机选一张（优先健康照片）
        if dog.avatar_date == today and dog.today_avatar_index is not None and dog.today_avatar_index < len(all_photos):
            chosen_idx = dog.today_avatar_index
        else:
            # 新一天：随机选择
            health_indices = [i for i, p in enumerate(all_photos) if p["type"] == "health"]
            if health_indices and len(all_photos) > 1:
                # 避免连续两天同一张
                if dog.avatar_date == today - timedelta(days=1) and dog.today_avatar_index is not None:
                    available = [i for i in range(len(all_photos)) if i != dog.today_avatar_index]
                else:
                    available = list(range(len(all_photos)))
                # 健康照片权重更高（出现概率加倍）
                weighted = available + [i for i in health_indices if i in available]
                chosen_idx = _random.choice(weighted)
            elif health_indices:
                chosen_idx = _random.choice(health_indices)
            else:
                chosen_idx = _random.randint(0, len(all_photos) - 1)
            dog.today_avatar_index = chosen_idx
            dog.avatar_date = today
            db.commit()

        chosen = all_photos[chosen_idx]
        result = {
            "avatar": chosen["url"],
            "photo_count": len(photos),
            "health_photo_count": len(hphotos),
            "index": chosen_idx,
            "date": today_str,
            "avatar_unlocked": True,
        }
        if chosen["type"] == "health":
            result["avatar_hint"] = f"这是我{chosen.get('label', chosen.get('event_type', ''))}那天的照片哦～"
        return result


@app.get("/api/pets/{pet_id}/paw-history")
def api_paw_points_history(pet_id: int, limit: int = 50):
    """返回爪印积分获取历史（含签到、任务、答题等）"""
    with get_db() as db:
        dog = db.query(Dog).filter(Dog.id == pet_id).first()
        if not dog:
            raise HTTPException(status_code=404, detail="狗狗档案不存在")

        logs = db.query(PawPointsLog).filter(
            PawPointsLog.pet_id == pet_id
        ).order_by(PawPointsLog.created_at.desc()).limit(limit).all()

        history = []
        for log in logs:
            history.append({
                "id": log.id,
                "amount": log.amount,
                "reason": log.reason,
                "date": log.created_at.strftime("%Y-%m-%d %H:%M") if log.created_at else "",
            })

        return {
            "pet_id": pet_id,
            "total_paw_points": dog.paw_points or 0,
            "history": history,
        }


# ============================================================
# 根路由 — 完整的单页 HTML 应用
# ============================================================
@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(content=_HTML_CONTENT, status_code=200)


_HTML_CONTENT = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>PawLife — 我的汪生小助手 🐾</title>
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=Gaegu:wght@400;700&display=swap" rel="stylesheet" />
<style>
/* ===== 全局变量与基础 ===== */
:root {
  --cream: #FFF7E6;
  --card: #FFFDF8;
  --orange: #FF8A00;
  --orange-dark: #E07800;
  --orange-light: #FFF0D9;
  --brown: #5A3A2A;
  --brown-light: #8B5E3C;
  --muted: #8A6A55;
  --border: #F0DCC8;
  --green: #6B9B37;
  --red: #D94A4A;
  --yellow: #E8A838;
  --shadow: 0 3px 12px rgba(100, 60, 20, 0.06);
  --radius: 16px;
  --radius-sm: 10px;
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", "Helvetica Neue", sans-serif;
  background: var(--cream);
  color: var(--brown);
  line-height: 1.6;
  min-height: 100vh;
}

/* ===== 头部 ===== */
.app-header {
  text-align: center;
  padding: 14px 16px 6px;
  position: relative;
}
.app-header .logo {
  font-size: 2.2em;
  font-weight: 800;
  color: var(--orange);
  letter-spacing: 1px;
}
/* 狗狗照片已移入今日卡片 .today-avatar */
.subtitle {
  text-align: center;
  color: var(--muted);
  font-size: 0.92em;
  letter-spacing: 1px;
  margin: 2px 0 4px;
}

/* 欢迎条已移除 — 问候语及头像融合进今日卡片 */
/* ===== 今日卡片内嵌狗狗头像 ===== */
.today-avatar {
  width: 64px; height: 64px; border-radius: 50%;
  background: #FDF8F2; border: 2px solid var(--border);
  display: flex; align-items: center; justify-content: center;
  font-size: 2em; cursor: pointer; overflow: hidden;
  transition: border-color 0.2s, box-shadow 0.2s;
  flex-shrink: 0;
}
.today-avatar:hover {
  border-color: var(--orange);
  box-shadow: 0 0 0 4px rgba(255,138,0,0.12);
}
.today-avatar img {
  width: 100%; height: 100%; object-fit: cover; display: block;
}
.today-avatar-sm {
  width: 61px; height: 61px;
  font-size: 2em;
  border: 2px solid var(--border);
  border-radius: 50%;
  background: #FDF8F2;
  display: flex; align-items: center; justify-content: center;
  overflow: hidden;
}
.today-avatar-sm img {
  width: 100%; height: 100%; object-fit: cover; display: block;
}
.today-greeting {
  font-weight: 700; font-size: 1em; color: var(--brown);
  margin-bottom: 6px;
}

/* ===== 今日汪汪卡片（对话气泡设计） ===== */
/* ===== 品牌价值区（tagline 在 app-header 内）===== */
.hero-tagline {
  font-size: 0.88em; color: var(--muted); letter-spacing: 0.5px;
  margin-top: 2px;
}

/* ===== 今日状态卡 ===== */
.today-dashboard {
  background: var(--card); border-radius: var(--radius);
  padding: 14px 16px; margin-bottom: 12px;
  box-shadow: var(--shadow); border: 1px solid var(--border);
}
.today-dashboard-main {
  display: flex; align-items: center; gap: 12px;
}
.today-dashboard-main .today-avatar {
  width: 56px; height: 56px; font-size: 2em; flex-shrink: 0;
  cursor: pointer; transition: transform 0.2s;
}
.today-dashboard-main .today-avatar:hover { transform: scale(1.08); }
.today-dashboard-info {
  flex: 1; min-width: 0;
  font-size: 0.95em; color: var(--brown); line-height: 1.6;
}
.today-dashboard-info b { color: var(--brown); }
.today-dashboard-info .td-recent { font-size: 0.82em; color: var(--muted); display: block; }
.today-dashboard-info .td-reminder { font-size: 0.8em; color: var(--red); display: block; margin-top: 1px; }
.today-dashboard-meta {
  display: flex; flex-direction: column; align-items: center; gap: 4px; flex-shrink: 0;
}
.td-paw {
  cursor: pointer; font-size: 0.85em; color: var(--brown-light);
  padding: 4px 10px; border-radius: 14px; background: var(--orange-light);
  transition: transform 0.2s; white-space: nowrap;
}
.td-paw:hover { transform: scale(1.05); }
.td-streak { font-size: 0.82em; color: var(--brown-light); white-space: nowrap; }

.today-pending {
  margin-top: 10px; padding-top: 10px;
  border-top: 1px dashed var(--border);
  font-size: 0.92em; font-weight: 600; color: var(--orange);
  line-height: 1.5;
}
.today-pending .pending-count {
  display: inline-block; background: var(--orange); color: #fff;
  border-radius: 50%; width: 24px; height: 24px; line-height: 24px;
  text-align: center; font-size: 0.88em; margin-right: 4px;
}

/* ===== 今日健康检查（主CTA） ===== */
.daily-check-card {
  background: linear-gradient(135deg, #FFF8F0, #FFFDF7);
  border: 2px solid var(--orange);
  border-radius: var(--radius);
  padding: 18px 18px 14px;
  margin-bottom: 16px;
  box-shadow: 0 3px 16px rgba(255,138,0,0.12);
}
.daily-check-header {
  display: flex; align-items: center; gap: 8px; margin-bottom: 10px;
}
.daily-check-icon { font-size: 1.5em; }
.daily-check-title { font-size: 1.1em; font-weight: 700; color: var(--brown); }
.daily-check-badge {
  margin-left: auto; font-size: 0.78em; font-weight: 600;
  background: var(--green); color: #fff; padding: 3px 10px; border-radius: 12px;
}
.daily-check-desc {
  font-size: 0.88em; color: var(--brown-light); line-height: 1.7; margin-bottom: 14px;
}
.pet-name-inline { font-weight: 700; color: var(--brown); }
.daily-check-actions {
  display: flex; gap: 10px; margin-bottom: 10px;
}
.btn-check-ok {
  flex: 1; padding: 13px 16px; border: none; border-radius: var(--radius);
  background: linear-gradient(135deg, var(--orange), #FFB74D);
  color: #fff; font-size: 1em; font-weight: 700; cursor: pointer;
  font-family: inherit; transition: all 0.2s;
  box-shadow: 0 3px 12px rgba(255,138,0,0.2);
}
.btn-check-ok:hover { transform: translateY(-1px); box-shadow: 0 5px 18px rgba(255,138,0,0.3); }
.btn-check-ok:active { transform: scale(0.97); }
.btn-check-warn {
  flex: 1; padding: 13px 16px; border: 2px solid var(--red); border-radius: var(--radius);
  background: transparent; color: var(--red); font-size: 1em; font-weight: 600;
  cursor: pointer; font-family: inherit; transition: all 0.2s;
}
.btn-check-warn:hover { background: #FFF5F5; border-color: #C62828; }
.btn-check-warn:active { transform: scale(0.97); }
.daily-check-completed {
  text-align: center; padding: 12px; margin-bottom: 8px;
  background: #E8F5E9; border-radius: var(--radius-sm);
  font-size: 0.92em; font-weight: 600; color: #2E7D32;
}
.daily-check-note {
  font-size: 0.76em; color: var(--muted); text-align: center;
}

/* ===== 首页功能入口网格 ===== */
/* 第一行：2 列主功能卡片 */
.quick-record-grid {
  display: grid; grid-template-columns: 1fr 1fr; gap: 8px;
  margin-bottom: 8px;
}
.quick-record-card {
  background: var(--card); border-radius: var(--radius);
  padding: 14px 12px; text-align: center; cursor: pointer;
  box-shadow: var(--shadow); border: 1px solid var(--border);
  transition: transform 0.2s, box-shadow 0.2s, border-color 0.2s;
  user-select: none; position: relative;
}
.quick-record-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 18px rgba(100,60,20,0.1);
  border-color: var(--orange);
}
.quick-record-card:active { transform: scale(0.97); }
.qr-icon { font-size: 1.6em; display: block; margin-bottom: 4px; }
.qr-label { font-size: 0.9em; font-weight: 700; color: var(--brown); display: block; }
.qr-hint { font-size: 0.72em; color: var(--muted); display: block; margin-top: 2px; }

/* 第二行：4 列辅功能卡片（无副标题，紧凑） */
.quick-record-grid-sm {
  display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 6px;
  margin-bottom: 16px;
}
.quick-record-card-sm {
  background: var(--card); border-radius: var(--radius);
  padding: 12px 6px; text-align: center; cursor: pointer;
  box-shadow: var(--shadow); border: 1px solid var(--border);
  transition: transform 0.2s, box-shadow 0.2s, border-color 0.2s;
  user-select: none; position: relative;
}
.quick-record-card-sm:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 18px rgba(100,60,20,0.1);
  border-color: var(--orange);
}
.quick-record-card-sm:active { transform: scale(0.97); }
.qr-icon-sm { font-size: 1.5em; display: block; margin-bottom: 3px; }
.qr-label-sm { font-size: 0.82em; font-weight: 700; color: var(--brown); display: block; }
@media (max-width: 520px) {
  .quick-record-grid-sm { grid-template-columns: 1fr 1fr; }
}

.btn-secondary {
  background: transparent;
  border: 2px solid var(--orange);
  color: var(--orange);
}
.btn-secondary:hover {
  background: var(--orange-light);
  border-color: var(--orange-dark);
  color: var(--orange-dark);
}
.btn-text {
  background: transparent; border: none; color: var(--brown-light);
  cursor: pointer; font-family: inherit; padding: 4px 8px;
  font-size: 0.88em; text-decoration: underline; text-underline-offset: 2px;
}
.btn-text:hover { color: var(--orange); }

/* 返回按钮 - 文字版 */
.btn-back-text {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 6px 12px; border-radius: 20px;
  border: 1.5px solid var(--border); background: var(--card);
  color: var(--brown-light); cursor: pointer;
  font-size: 0.85em; font-family: inherit; font-weight: 600;
  transition: all 0.2s; white-space: nowrap;
}
.btn-back-text:hover {
  background: var(--orange-light); border-color: var(--orange);
  color: var(--orange);
}

/* ===== 首页档案卡片 ===== */
/* ===== 健康档案卡 ===== */
.health-profile-card {
  background: var(--card); border-radius: var(--radius);
  padding: 16px 18px; margin-bottom: 16px;
  box-shadow: var(--shadow); border: 1px solid var(--border);
}
.hp-card-inner { }
.hp-card-header {
  display: flex; align-items: center; gap: 8px; margin-bottom: 12px;
}
.hp-icon { font-size: 1.5em; }
.hp-name { font-size: 1.05em; font-weight: 700; color: var(--brown); }
.hp-snapshot { margin-bottom: 4px; }
.hp-insight {
  display: flex; align-items: flex-start; gap: 8px;
  padding: 8px 0; border-bottom: 1px dotted var(--border);
  font-size: 0.88em; line-height: 1.55; color: var(--brown-light);
}
.hp-insight:last-child { border-bottom: none; }
.hp-insight-icon { flex-shrink: 0; font-size: 1.1em; }
.hp-insight-text { flex: 1; }
.hp-insight-muted { opacity: 0.65; font-size: 0.83em; }
.hp-insight-action {
  color: var(--orange); font-weight: 600; cursor: pointer;
  white-space: nowrap; font-size: 0.92em;
}
.hp-insight-action:hover { text-decoration: underline; }
.hp-empty { text-align: center; padding: 16px 0; }
.hp-empty-icon { font-size: 2.8em; margin-bottom: 6px; }
.hp-empty-title { font-weight: 700; color: var(--brown); font-size: 1em; margin-bottom: 4px; }
.hp-empty-desc { color: var(--muted); font-size: 0.88em; margin-bottom: 12px; }

/* ===== 成长记录压缩版 ===== */
.growth-compact {
  margin-bottom: 16px;
}
.growth-photos-row {
  display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 8px;
}
.growth-photo-thumb {
  width: calc((100% - 12px) / 3); min-width: 70px; aspect-ratio: 1;
  border-radius: 10px; overflow: hidden; border: 2px solid var(--border);
  cursor: pointer; transition: transform 0.2s;
}
.growth-photo-thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.growth-photo-thumb:hover { transform: scale(1.05); border-color: var(--orange); }
.growth-photo-thumb-placeholder {
  width: calc((100% - 12px) / 3); min-width: 70px; aspect-ratio: 1;
  border-radius: 10px; border: 2px dashed var(--border);
  display: flex; align-items: center; justify-content: center;
  font-size: 1.4em; color: var(--muted); background: #FDFBF7;
}
.growth-badges-row {
  display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 8px;
}
.growth-badge-mini {
  display: flex; align-items: center; gap: 4px;
  background: #FFFDF7; border: 1.5px solid #A67B5B;
  border-radius: 20px; padding: 4px 10px;
  font-size: 0.8em; font-weight: 600; color: #5D3A1A;
  transition: transform 0.2s;
}
.growth-badge-mini.locked { filter: grayscale(100%); opacity: 0.4; border-style: dashed; border-color: #CCC; }
.growth-more-link {
  display: block; text-align: center; font-size: 0.85em; font-weight: 600;
  color: var(--orange); cursor: pointer; padding: 8px; text-decoration: none;
  transition: opacity 0.2s;
}
.growth-more-link:hover { opacity: 0.75; }

/* ===== 功能入口链接 ===== */

/* ===== 体重管理页 ===== */
.weight-chart-container { margin: 8px 0; overflow-x: auto; }
.weight-chart {
  display: flex; align-items: flex-end; gap: 6px;
  min-height: 140px; padding: 8px 0;
}
.weight-bar-col {
  display: flex; flex-direction: column; align-items: center; gap: 2px;
  flex: 1; min-width: 32px;
}
.weight-bar-val { font-size: 0.72em; color: var(--brown); font-weight: 600; }
.weight-bar {
  width: 100%; max-width: 36px; min-height: 4px;
  background: linear-gradient(180deg, var(--orange), #FFB74D);
  border-radius: 4px 4px 0 0; transition: height 0.3s;
}
.weight-bar-label { font-size: 0.68em; color: var(--muted); }
.weight-stats-row {
  display: flex; gap: 12px; flex-wrap: wrap;
  margin-top: 10px; padding-top: 10px; border-top: 1px dashed var(--border);
}
.weight-stat {
  background: #FFFDF7; border-radius: 8px;
  padding: 8px 14px; text-align: center;
}
.weight-stat-label { display: block; font-size: 0.75em; color: var(--muted); margin-bottom: 2px; }
.weight-stat-value { font-weight: 700; color: var(--brown); font-size: 0.95em; }
.weight-frequency-hint {
  margin-top: 8px; font-size: 0.82em; color: var(--brown-light);
  padding: 6px 10px; background: #FFFDF7; border-radius: 6px;
}

/* ===== BCS 体况评分 ===== */
.bcs-guide { font-size: 0.88em; }
.bcs-intro { color: var(--brown-light); margin-bottom: 12px; line-height: 1.5; }
.bcs-scale { display: flex; flex-direction: column; gap: 6px; }
.bcs-item {
  display: flex; align-items: center; gap: 10px;
  padding: 8px 12px; border-radius: 8px; background: #FFFDF7;
  border: 1px solid var(--border);
}
.bcs-dot {
  width: 14px; height: 14px; border-radius: 50%; flex-shrink: 0;
}
.bcs-dot.too-thin { background: #FFC107; }
.bcs-dot.ideal { background: #4CAF50; }
.bcs-dot.overweight { background: #FF9800; }
.bcs-dot.obese { background: #F44336; }
.bcs-desc { margin-left: auto; font-size: 0.82em; color: var(--muted); }

/* ===== 健康提醒页 ===== */
.reminders-intro {
  font-size: 0.88em; color: var(--brown-light);
  padding: 0 0 10px 0; margin-bottom: 6px;
  line-height: 1.5;
}
.reminder-card {
  display: flex; gap: 10px; align-items: flex-start;
  padding: 14px 16px; margin-bottom: 8px;
  background: var(--card); border-radius: var(--radius);
  border: 1px solid var(--border); box-shadow: var(--shadow);
  transition: border-color 0.2s;
}
.reminder-card.reminder-urgent {
  border-color: #FF6B6B; background: #FFF5F5;
}
.reminder-icon { font-size: 1.5em; flex-shrink: 0; }
.reminder-body { flex: 1; }
.reminder-title { font-weight: 700; color: var(--brown); margin-bottom: 2px; font-size: 0.95em; }
.reminder-desc { font-size: 0.85em; color: var(--brown-light); line-height: 1.5; }
.reminder-action {
  display: inline-block; margin-top: 6px; font-size: 0.85em;
  color: var(--orange); font-weight: 600; cursor: pointer;
}
.reminder-action:hover { text-decoration: underline; }

/* 保留旧版勋章墙/相册样式 - 它们被子页面使用 */

/* ===== 汪的百变秀 - 毛玻璃胶片条 ===== */
.photo-gallery-section {
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px dashed var(--border);
}
.photo-gallery-header {
  display: flex; align-items: center; gap: 6px;
  margin-bottom: 10px;
  font-weight: 700; font-size: 0.95em; color: var(--brown);
}
.photo-gallery-unlocked-badge {
  margin-left: auto;
  font-size: 0.72em; font-weight: 600;
  background: linear-gradient(135deg, #FF8A00, #FFB74D);
  color: #fff; padding: 3px 10px; border-radius: 12px;
  animation: badgeGlow 2s ease-in-out infinite alternate;
}
@keyframes badgeGlow {
  0%   { box-shadow: 0 0 4px rgba(255,138,0,0.3); }
  100% { box-shadow: 0 0 12px rgba(255,138,0,0.6); }
}
.photo-gallery-count {
  margin-left: auto;
  font-size: 0.78em; font-weight: 600;
  background: var(--green); color: #fff;
  padding: 2px 10px; border-radius: 12px;
  letter-spacing: 0.5px;
}
.photo-gallery-count.full { background: var(--orange); }
.photo-gallery-locked {
  display: flex; flex-direction: column; gap: 8px;
  padding: 10px 0;
  color: var(--muted); font-size: 0.88em;
}
.photo-gallery-locked-intro {
  display: flex; align-items: center; gap: 8px;
}
.photo-gallery-empty-actions {
  display: flex; gap: 10px; padding: 4px 0;
}
.photo-gallery-exchange-area {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  padding: 8px 0 4px;
}
.photo-gallery-exchange-hint {
  font-size: 0.85em; color: var(--muted);
  white-space: nowrap;
}
.photo-gallery-exchange-btn {
  display: inline-block;
  padding: 6px 16px;
  border-radius: 20px; border: none;
  cursor: pointer; font-size: 0.85em; font-weight: 700;
  color: #fff; font-family: inherit;
  background: linear-gradient(135deg, #FF8A00, #FFB74D);
  box-shadow: 0 3px 12px rgba(255,138,0,0.25);
  transition: transform 0.2s, box-shadow 0.2s;
  white-space: nowrap;
  animation: btnPulse 1.5s ease-in-out infinite alternate;
}
@keyframes btnPulse {
  0%   { box-shadow: 0 3px 12px rgba(255,138,0,0.25); }
  100% { box-shadow: 0 3px 22px rgba(255,138,0,0.5); }
}
.photo-gallery-exchange-btn:hover {
  transform: scale(1.05);
  box-shadow: 0 5px 24px rgba(255,138,0,0.45);
}
.photo-gallery-exchange-btn:active { transform: scale(0.95); }
.photo-gallery-exchange-btn-disabled {
  background: #CCC !important; cursor: not-allowed !important;
  animation: none !important; box-shadow: none !important;
}
.photo-gallery-filmtrip {
  display: flex; gap: 8px; flex-wrap: wrap;
  padding: 4px 0;
  align-items: flex-start;
}
.photo-film-item {
  position: relative;
  width: calc((100% - 40px) / 6); min-width: 72px;
  aspect-ratio: 1;
  border-radius: 12px;
  overflow: hidden;
  border: 2px solid var(--border);
  cursor: pointer;
  transition: border-color 0.2s, transform 0.2s;
  flex-shrink: 1;
}
.photo-film-item img {
  width: 100%; height: 100%;
  object-fit: cover;
  display: block;
}
/* hover 放大提示 */
.photo-film-item:hover {
  border-color: var(--orange);
  transform: scale(1.05);
}
/* 脉冲动画 — 上传瞬间 */
.photo-film-item.pulse {
  animation: filmPulse 2s ease-out;
}
@keyframes filmPulse {
  0%   { transform: scale(0.3); opacity: 0; }
  30%  { transform: scale(1.15); opacity: 1; }
  70%  { transform: scale(1.08); opacity: 1; }
  100% { transform: scale(1); opacity: 1; }
}
.photo-film-item .photo-film-delete {
  position: absolute; top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(217,74,74,0.82); color: #fff;
  font-size: 0.65em; display: flex; align-items: center; justify-content: center;
  text-align: center; line-height: 1.2;
  opacity: 0; transition: opacity 0.2s;
  pointer-events: none;
}
.photo-film-item:hover .photo-film-delete { opacity: 1; }
.photo-film-item .photo-film-label {
  position: absolute; bottom: 0; left: 0; right: 0;
  background: linear-gradient(transparent, rgba(0,0,0,0.65));
  color: #fff; font-size: 0.6em; text-align: center;
  padding: 8px 4px 4px; line-height: 1.2;
  border-radius: 0 0 10px 10px;
}
.photo-film-add {
  width: calc((100% - 40px) / 6); min-width: 72px;
  aspect-ratio: 1; flex-shrink: 1;
  border-radius: 12px;
  border: 2px dashed var(--border);
  display: flex; align-items: center; justify-content: center;
  cursor: pointer; font-size: 1.6em; color: var(--muted);
  transition: border-color 0.2s, color 0.2s, background 0.2s;
  background: #FDFBF7;
}
.photo-film-add:hover {
  border-color: var(--orange);
  color: var(--orange);
  background: #FFF8F0;
}

/* ===== 荣誉勋章墙 ===== */
/* ===== 荣誉勋章页 ===== */
/* 情绪安抚区 */
.badge-emotion-card {
  background: linear-gradient(135deg, #FFF8EF 0%, #FEF0DD 100%);
  border-radius: 20px; padding: 20px 18px; margin-bottom: 16px;
  border: 1px solid #F0DCC0;
  box-shadow: 0 2px 12px rgba(180,140,100,0.08);
}
.badge-emotion-inner {
  display: flex; align-items: center; gap: 16px;
}
.badge-emotion-left {
  display: flex; flex-direction: column; align-items: center;
  gap: 4px; flex-shrink: 0;
}
.badge-emotion-avatar {
  width: 52px; height: 52px; border-radius: 50%;
  background: #FBE8D0; display: flex; align-items: center; justify-content: center;
  font-size: 1.6em; border: 2px solid #F0D0A0;
}
.badge-emotion-name {
  font-size: 0.88em; font-weight: 700; color: var(--brown);
}
.badge-emotion-days {
  font-size: 0.72em; color: var(--brown-light);
}
.badge-emotion-right {
  flex: 1;
}
.badge-emotion-count {
  font-size: 1.15em; font-weight: 700; color: #C98A4B; margin-bottom: 4px;
}
.badge-emotion-text {
  font-size: 0.88em; color: #8B6E5A; line-height: 1.6;
}

/* 故事线分类 Tab */
.badge-story-tabs {
  display: flex; gap: 6px; margin-bottom: 14px; overflow-x: auto;
  padding-bottom: 4px; -webkit-overflow-scrolling: touch;
}
.badge-story-tab {
  flex-shrink: 0; padding: 6px 14px; border-radius: 20px;
  font-size: 0.82em; font-weight: 600; cursor: pointer; user-select: none;
  background: #F5F0E8; color: var(--brown-light);
  border: 1px solid transparent; transition: all 0.2s;
}
.badge-story-tab:hover { background: #EDE4D5; }
.badge-story-tab.active {
  background: #FFF; color: var(--brown); border-color: #E0C8A0;
  box-shadow: 0 1px 4px rgba(0,0,0,0.04);
}

/* 勋章墙网格 */
.badge-wall {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 12px;
}
.badge-memento {
  background: #FFFDF9; border-radius: 16px; padding: 16px 10px 12px;
  text-align: center; cursor: pointer; user-select: none;
  border: 1.5px solid #EDE0CC; transition: all 0.25s;
  box-shadow: 0 1px 4px rgba(0,0,0,0.03);
  position: relative;
}
.badge-memento:hover { transform: translateY(-3px); box-shadow: 0 4px 16px rgba(0,0,0,0.07); }
.badge-memento.unlocked { }
.badge-memento.locked {
  background: #FCFAF7; border: 1.5px dashed #E0D5C5;
  cursor: default;
}
.badge-memento.locked:hover { transform: none; box-shadow: 0 1px 4px rgba(0,0,0,0.03); }
.badge-memento-photo-area {
  position: relative; display: inline-block; margin: 0 auto 8px;
}
.badge-memento-icon {
  width: 72px; height: 72px;
  border-radius: 50%; overflow: hidden;
  border: 3px solid #D4A853;
  box-shadow: 0 0 0 3px #F5E6C8, 0 0 0 5px #D4A853, 0 2px 10px rgba(180,130,50,0.25);
}
.badge-memento-icon img {
  width: 100%; height: 100%; object-fit: cover; display: block;
}
.badge-memento-icon-placeholder {
  width: 100%; height: 100%; display: flex; align-items: center; justify-content: center;
  font-size: 2em; background: linear-gradient(135deg, #F5F0EB, #EDE5DA);
}
.badge-memento-pin {
  position: absolute; bottom: -6px; left: 50%; transform: translateX(-50%);
  width: 24px; height: 24px; border-radius: 50%;
  background: linear-gradient(135deg, #FFD54F, #FFA000);
  border: 2px solid #FFF; box-shadow: 0 1px 4px rgba(0,0,0,0.2);
  display: flex; align-items: center; justify-content: center;
  font-size: 0.7em; line-height: 1; z-index: 2;
  pointer-events: none;
}
.badge-memento.locked .badge-memento-icon {
  border-color: #D8CFC0;
  box-shadow: 0 0 0 3px #F5F1EC, 0 0 0 5px #D8CFC0, 0 1px 6px rgba(0,0,0,0.08);
}
.badge-memento.locked .badge-memento-icon-placeholder {
  background: linear-gradient(135deg, #F8F6F3, #EEEAE4);
  font-size: 2em; opacity: 0.5;
}
.badge-memento.locked .badge-memento-pin {
  background: linear-gradient(135deg, #E8E4DE, #D0C8BC);
  border-color: #F0EDE8; box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}
.badge-memento-name {
  font-size: 0.85em; font-weight: 700; color: var(--brown); margin-bottom: 3px;
  display: block;
}
.badge-memento.locked .badge-memento-name {
  color: #B8A494;
}
.badge-memento-date {
  font-size: 0.68em; color: #B8A494;
  display: block;
}
.badge-memento.locked .badge-memento-date {
  color: #C8BCAA; font-style: italic;
}

/* 空状态 */
.badge-empty {
  text-align: center; padding: 32px 16px;
}
.badge-empty-icon { font-size: 3em; margin-bottom: 12px; }
.badge-empty-title {
  font-size: 1.1em; font-weight: 700; color: var(--brown); margin-bottom: 8px;
}
.badge-empty-desc {
  font-size: 0.88em; color: var(--brown-light); line-height: 1.7;
  max-width: 340px; margin: 0 auto 18px;
}
.badge-empty-foot {
  margin-top: 12px; font-size: 0.82em; color: var(--muted);
}

/* 勋章详情弹窗 */
.badge-detail-card {
  background: #FFFDF9; border-radius: 20px;
  padding: 32px 24px 24px; max-width: 380px; width: 92vw;
  text-align: center; position: relative;
  box-shadow: 0 12px 40px rgba(0,0,0,0.15);
  border: 1px solid #EDE0CC;
  animation: modalSlideUp 0.35s ease;
}
.badge-detail-close {
  position: absolute; top: 12px; right: 14px;
  background: none; border: none; font-size: 1.1em; cursor: pointer;
  color: #B8A494; padding: 4px; font-family: inherit;
}
.badge-detail-icon { font-size: 3.5em; margin-bottom: 10px; }
.badge-detail-name {
  font-size: 1.2em; font-weight: 700; color: var(--brown); margin-bottom: 10px;
}
.badge-detail-story {
  font-size: 0.9em; color: var(--brown-light); line-height: 1.7;
  margin-bottom: 12px; padding: 0 4px;
}
.badge-detail-date {
  font-size: 0.82em; color: #B8A494; margin-bottom: 14px;
}
.badge-detail-woof {
  font-size: 0.85em; color: #C98A4B; line-height: 1.6;
  padding: 10px 14px; background: #FFFBF5; border-radius: 12px;
  border: 1px solid #F0E0C0; font-style: italic;
}

/* 勋章解锁 Toast（轻柔版） */
.badge-unlock-toast {
  position: fixed; top: 16px; left: 50%; transform: translateX(-50%);
  z-index: 9999; background: #FFFBF5; border: 1.5px solid #F0D0A0;
  border-radius: 14px; padding: 10px 22px; font-size: 0.88em; font-weight: 600;
  color: var(--brown); box-shadow: 0 4px 20px rgba(180,140,100,0.12);
  animation: fadeIn 0.5s ease; white-space: nowrap;
}

/* ===== 功能入口标记（保健品角标等）===== */
.feature-paw-badge {
  position: absolute; top: 2px; right: 4px; font-size: 1.1em;
  cursor: pointer; z-index: 2; user-select: none;
  animation: pawBadgeBounce 2s ease-in-out infinite;
}
.feature-paw-badge:hover { transform: scale(1.3); }
@keyframes pawBadgeBounce {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-4px); }
}
.feature-badge {
  position: absolute; top: 4px; right: 4px;
  width: 10px; height: 10px; border-radius: 50%;
  background: #E53935;
  box-shadow: 0 0 0 3px rgba(229,57,53,0.2);
  animation: badgePulse 2s infinite;
}
@keyframes badgePulse {
  0%, 100% { box-shadow: 0 0 0 3px rgba(229,57,53,0.2); }
  50% { box-shadow: 0 0 0 6px rgba(229,57,53,0.1); }
}

/* ===== 签到状态条（档案卡片内）===== */
/* ===== 签到状态条（档案卡片内）===== */
.streak-bar {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  margin-top: 8px; padding: 6px 10px;
  background: linear-gradient(135deg, #FFF8E1, #FFF3E0);
  border-radius: 10px; font-size: 0.88em;
}
#pawPointsDisplay {
  font-size: 1.15em; font-weight: 700; color: var(--orange);
  cursor: pointer; transition: color 0.2s;
}
#pawPointsDisplay:hover { color: var(--orange-dark); }

/* ===== 测验卡片 ===== */
.quiz-card {
  background: #E3F2FD;
  border: 1.5px solid #BBDEFB;
  border-radius: var(--radius);
  padding: 20px 18px;
  margin-bottom: 14px;
  box-shadow: var(--shadow);
  transition: all 0.3s;
}
.quiz-card.correct { background: #E8F5E9; border-color: #A5D6A7; }
.quiz-card.wrong { background: #FFEBEE; border-color: #EF9A9A; }
.quiz-header {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 10px;
}
.quiz-title { font-weight: 700; color: #1565C0; font-size: 0.95em; }
.quiz-toggle {
  background: none; border: none; cursor: pointer;
  color: #1565C0; font-size: 1.2em; padding: 2px 6px;
}
.quiz-collapsed .quiz-body { display: none; }
.quiz-question { font-weight: 600; color: var(--brown); margin-bottom: 10px; font-size: 0.93em; }
.quiz-option {
  display: block; width: 100%; text-align: left;
  background: #fff; border: 1.5px solid #BBDEFB; border-radius: 10px;
  padding: 10px 14px; margin-bottom: 6px; cursor: pointer;
  font-size: 0.9em; color: var(--brown);
  transition: all 0.15s;
}
.quiz-option:hover { border-color: #1565C0; background: #F5F9FF; }
.quiz-option:active { transform: scale(0.98); }
.quiz-option.chosen { border-color: #1565C0; background: #E3F2FD; font-weight: 600; }
.quiz-option.correct-answer { border-color: #2E7D32; background: #C8E6C9; }
.quiz-option.wrong-answer { border-color: #C62828; background: #FFCDD2; }
.quiz-option:disabled { cursor: default; opacity: 0.7; }
.quiz-option:disabled:hover { border-color: #BBDEFB; background: #fff; }
.quiz-feedback { margin-top: 10px; font-weight: 600; font-size: 0.92em; }
.quiz-feedback .quiz-explain { font-weight: 400; font-size: 0.85em; color: var(--muted); margin-top: 4px; }

/* ===== 每日小任务卡片 ===== */
/* ===== 彩蛋入口（保健品小队底部）===== */
.easter-egg-entry, .easter-subpage-entry {
  text-align: center; padding: 14px; margin-top: 14px;
  cursor: pointer; opacity: 0.85; transition: all 0.3s;
  position: relative;
  background: #FFF9E6; border: 1.5px dashed #E8C54A;
  border-radius: 12px;
}
.easter-egg-entry:hover, .easter-subpage-entry:hover { opacity: 1; transform: scale(1.04); background: #FFF3CD; border-color: #D4A017; }
.easter-paw { font-size: 1.4em; display: block; margin-bottom: 2px; animation: pawBounce 1.5s ease-in-out infinite; }
@keyframes pawBounce {
  0%, 100% { transform: translateY(0); }
  30% { transform: translateY(-8px); }
  50% { transform: translateY(0); }
  70% { transform: translateY(-4px); }
}
.easter-label { font-size: 0.82em; color: var(--muted); }
/* 已答题 — 变为知识卡片 */
.easter-egg-entry.quiz-answered, .easter-subpage-entry.quiz-answered {
  cursor: default; opacity: 0.92;
  background: #F0F7FF; border: 1.5px solid #B3D4FF;
  pointer-events: none;
}
.easter-egg-entry.quiz-answered:hover, .easter-subpage-entry.quiz-answered:hover {
  opacity: 0.92; transform: none; background: #F0F7FF; border-color: #B3D4FF;
}
.quiz-answered .easter-paw { animation: none; }
.quiz-answered .easter-label { font-size: 0.85em; color: #4A6FA5; line-height: 1.5; }

/* ===== 彩蛋提示（首页偶现）===== */
.easter-hint {
  text-align: center; padding: 8px 12px; margin-bottom: 10px;
  font-size: 0.82em; color: var(--muted);
  background: #FFFDE7; border-radius: 12px;
  animation: fadeInUp 0.5s ease;
}

/* ===== 彩蛋测验弹窗 ===== */
.quiz-modal-card { max-width: 420px; }
.quiz-modal-card .quiz-question { font-weight: 600; font-size: 1em; margin-bottom: 12px; color: var(--brown); }
.quiz-modal-card .quiz-option {
  display: block; width: 100%; text-align: left;
  background: #F5F5F5; border: 1.5px solid #E0E0E0; border-radius: 10px;
  padding: 10px 14px; margin-bottom: 6px; cursor: pointer;
  font-size: 0.9em; transition: all 0.15s;
}
.quiz-modal-card .quiz-option:hover { border-color: #1565C0; background: #F5F9FF; }
.quiz-modal-card .quiz-option.correct-answer { border-color: #2E7D32; background: #C8E6C9; }
.quiz-modal-card .quiz-option.wrong-answer { border-color: #C62828; background: #FFCDD2; }
.quiz-modal-card .quiz-feedback { margin-top: 10px; font-weight: 600; font-size: 0.92em; }
.modal-close-btn {
  position: absolute; top: 10px; right: 14px;
  background: none; border: none; font-size: 1.3em;
  cursor: pointer; color: var(--muted); padding: 4px 8px;
}
.modal-close-btn:hover { color: var(--red); }

/* ===== 爪印历史弹窗 ===== */
.paw-history-overlay {
  position: fixed; top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(90, 58, 42, 0.55);
  z-index: 2000; display: flex; align-items: center; justify-content: center;
}
.paw-history-card {
  background: var(--card); border-radius: var(--radius);
  width: 380px; max-width: 92vw; max-height: 70vh;
  display: flex; flex-direction: column;
  box-shadow: 0 8px 32px rgba(90, 58, 42, 0.2);
}
.paw-history-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 16px 18px 12px;
  border-bottom: 1px solid var(--border);
}
.paw-history-title {
  font-weight: 700; font-size: 1.05em; color: var(--brown);
}
.paw-history-close {
  background: none; border: none; font-size: 1.3em;
  cursor: pointer; color: var(--muted); padding: 4px 8px;
}
.paw-history-close:hover { color: var(--red); }
.paw-history-list {
  flex: 1; overflow-y: auto; padding: 8px 0;
}
.paw-history-item {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 18px;
  border-bottom: 1px solid #F5EDE2;
}
.paw-history-item:last-child { border-bottom: none; }
.paw-history-item-left { display: flex; flex-direction: column; gap: 2px; }
.paw-history-item-reason {
  font-size: 0.93em; font-weight: 600; color: var(--brown);
}
.paw-history-item-date {
  font-size: 0.78em; color: var(--muted);
}
.paw-history-item-amount {
  font-size: 1em; font-weight: 700; color: var(--orange);
  white-space: nowrap;
}
.paw-history-empty {
  text-align: center; padding: 32px 18px; color: var(--muted);
}

/* ===== 任务确认弹窗 ===== */
.task-confirm-card {
  background: #FFFBF5;
  border-radius: 18px;
  padding: 28px 24px 20px;
  max-width: 340px; width: 90%;
  text-align: center;
  box-shadow: 0 12px 40px rgba(0,0,0,0.18);
  animation: modalSlideUp 0.25s ease;
}
.task-confirm-icon { font-size: 2.8em; margin-bottom: 10px; }
.task-confirm-task {
  font-size: 1.08em; font-weight: 700; color: var(--dark);
  margin-bottom: 4px; line-height: 1.5;
}
.task-confirm-question { font-size: 0.92em; color: var(--muted); margin-bottom: 6px; }
.task-confirm-reward {
  font-size: 0.9em; color: var(--orange); margin-bottom: 18px;
}
.task-confirm-actions { display: flex; gap: 10px; justify-content: center; }
.task-confirm-cancel {
  background: #f0f0f0; color: #666; border: none;
  padding: 10px 22px; border-radius: 25px; font-size: 0.95em; cursor: pointer;
  transition: background 0.2s;
}
.task-confirm-cancel:hover { background: #e0e0e0; }
.task-confirm-ok {
  background: var(--orange); color: #fff; border: none;
  padding: 10px 22px; border-radius: 25px; font-size: 0.95em; cursor: pointer;
  font-weight: 600; transition: background 0.2s, transform 0.15s;
}
.task-confirm-ok:hover { background: #e0762d; transform: scale(1.03); }
.task-confirm-ok:active { transform: scale(0.97); }

/* ===== 兑换确认弹窗 ===== */
.exchange-confirm-card {
  background: #FFFBF5;
  border-radius: 20px;
  padding: 30px 24px 22px;
  max-width: 360px; width: 90%;
  text-align: center;
  box-shadow: 0 14px 44px rgba(0,0,0,0.2);
  animation: modalSlideUp 0.28s ease;
}
.exchange-confirm-avatar {
  width: 100px; height: 100px;
  margin: 0 auto 14px;
  border-radius: 50%;
  overflow: hidden;
  border: 3px solid var(--orange);
  background: var(--warm-bg);
  display: flex; align-items: center; justify-content: center;
}
.exchange-confirm-avatar img {
  width: 100%; height: 100%; object-fit: cover;
}
.exchange-confirm-placeholder { font-size: 2.6em; }
.exchange-confirm-name {
  font-size: 1.05em; font-weight: 700; color: var(--brown); margin-bottom: 10px;
}
.exchange-confirm-text {
  font-size: 0.95em; color: var(--dark); margin-bottom: 4px; line-height: 1.5;
}
.exchange-confirm-sub {
  font-size: 0.84em; color: var(--muted); margin-bottom: 20px; line-height: 1.5;
}
.exchange-confirm-actions { display: flex; gap: 10px; justify-content: center; }
.exchange-confirm-cancel {
  background: #f0f0f0; color: #666; border: none;
  padding: 10px 22px; border-radius: 25px; font-size: 0.93em; cursor: pointer;
  transition: background 0.2s;
}
.exchange-confirm-cancel:hover { background: #e0e0e0; }
.exchange-confirm-ok {
  background: linear-gradient(135deg, #E8893A, #F5A623); color: #fff; border: none;
  padding: 10px 22px; border-radius: 25px; font-size: 0.95em; cursor: pointer;
  font-weight: 700; transition: all 0.2s;
}
.exchange-confirm-ok:hover { transform: scale(1.04); box-shadow: 0 4px 14px rgba(232,137,58,0.35); }
.exchange-confirm-ok:active { transform: scale(0.96); }

/* ===== Toast 优化版 ===== */
.toast-container {
  position: fixed; top: 20px; left: 50%; transform: translateX(-50%);
  z-index: 10000; display: flex; flex-direction: column; gap: 8px;
  pointer-events: none;
}
.toast-msg {
  background: var(--brown); color: #fff; padding: 12px 24px;
  border-radius: 30px; font-weight: 600; font-size: 0.92em;
  box-shadow: 0 6px 20px rgba(0,0,0,0.18);
  animation: toastSlideIn 0.35s ease, toastSlideOut 0.35s ease 2.5s forwards;
  pointer-events: auto; white-space: nowrap; text-align: center;
  max-width: 90vw;
}
@keyframes toastSlideIn {
  from { opacity: 0; transform: translateY(-30px); }
  to { opacity: 1; transform: translateY(0); }
}
@keyframes toastSlideOut {
  from { opacity: 1; transform: translateY(0); }
  to { opacity: 0; transform: translateY(-30px); }
}

/* ===== 子页面 ===== */
.sub-page { animation: pageIn 0.25s ease; }
@keyframes pageIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}
.sub-page-header {
  margin-bottom: 12px;
}
.sub-page-title {
  font-size: 1.15em; font-weight: 700; color: var(--brown);
}
.sub-page-header-row {
  display: flex; align-items: center; justify-content: space-between;
  gap: 10px;
}
.sub-page-header-row .btn { flex-shrink: 0; }
.sub-page-header-row .today-avatar-sm { flex-shrink: 0; }

/* ===== 容器与卡片 ===== */
.container {
  max-width: 720px;
  margin: 0 auto;
  padding: 0 14px 40px;
}
.card {
  background: var(--card);
  border-radius: var(--radius);
  padding: 18px 20px;
  margin-bottom: 14px;
  box-shadow: var(--shadow);
  border: 1px solid var(--border);
  transition: box-shadow 0.2s;
}
.card:hover {
  box-shadow: 0 6px 20px rgba(100, 60, 20, 0.1);
}
.card-title {
  font-size: 1.1em;
  font-weight: 700;
  color: var(--brown);
  margin-bottom: 2px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.card-subtitle {
  color: var(--muted);
  font-size: 0.85em;
  margin-bottom: 10px;
}
.card-header-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}
.btn-collapse-toggle {
  width: 32px; height: 32px;
  border: 1px solid var(--border);
  border-radius: 50%;
  background: #FFF;
  color: var(--muted);
  font-size: 0.8em;
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: all 0.2s;
  flex-shrink: 0;
  line-height: 1;
}
.btn-collapse-toggle:hover {
  border-color: var(--orange);
  color: var(--orange);
  background: #FFF8F0;
}
.btn-collapse-toggle.collapsed {
  transform: rotate(180deg);
}

/* ===== 表单 ===== */
.form-row {
  display: flex;
  gap: 12px;
  margin-bottom: 10px;
}
.form-col { flex: 1; min-width: 0; }
.form-col label {
  display: block;
  font-size: 0.85em;
  font-weight: 600;
  color: var(--brown-light);
  margin-bottom: 3px;
}
.form-col label .required { color: var(--red); }
input, select, textarea {
  width: 100%;
  padding: 9px 12px;
  border: 1.5px solid var(--border);
  border-radius: var(--radius-sm);
  font-size: 0.95em;
  color: var(--brown);
  background: #FFFAF2;
  transition: border-color 0.2s, box-shadow 0.2s;
  font-family: inherit;
}
input:focus, select:focus, textarea:focus {
  outline: none;
  border-color: var(--orange);
  box-shadow: 0 0 0 3px rgba(255, 138, 0, 0.12);
}
input::placeholder { color: #C8B8A8; }
textarea { resize: vertical; min-height: 60px; }
input[type="file"] {
  width: auto;
  max-width: 100%;
  padding: 7px 10px;
  border: 1.5px dashed var(--border);
  border-radius: var(--radius-sm);
  background: #FFFBF5;
  font-size: 0.85em;
  color: var(--brown);
  cursor: pointer;
}
input[type="file"]:hover {
  border-color: var(--orange);
  background: var(--orange-light);
}
input[type="file"]::file-selector-button {
  padding: 5px 14px;
  margin-right: 10px;
  border: none;
  border-radius: 6px;
  background: var(--orange);
  color: #fff;
  font-size: 0.9em;
  font-weight: 600;
  cursor: pointer;
  font-family: inherit;
}
input[type="file"]::file-selector-button:hover {
  background: var(--orange-dark);
}

/* 复选框组 */
.checkbox-group {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.checkbox-group label {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 6px 12px;
  border: 1.5px solid var(--border);
  border-radius: 20px;
  font-size: 0.88em;
  cursor: pointer;
  user-select: none;
  background: #FFFAF2;
  transition: all 0.15s;
}
.checkbox-group label:hover { border-color: var(--orange); background: var(--orange-light); }
.checkbox-group input[type="checkbox"] { width: auto; accent-color: var(--orange); }

/* ===== 按钮 ===== */
.btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 10px 18px;
  border: none;
  border-radius: 24px;
  font-size: 0.95em;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.2s;
  font-family: inherit;
  letter-spacing: 0.3px;
}
.btn:active { transform: scale(0.96); }
.btn-primary { background: var(--orange); color: #fff; }
.btn-primary:hover { background: var(--orange-dark); }
.btn-primary:disabled { background: #E0C8A8; cursor: not-allowed; transform: none; }
.btn-outline {
  background: transparent;
  border: 2px solid var(--orange);
  color: var(--orange);
}
.btn-outline:hover { background: var(--orange-light); }
.btn-sm { padding: 6px 14px; font-size: 0.85em; }
.btn-danger { background: var(--red); color: #fff; }
.btn-danger:hover { background: #C13A3A; }
.btn-back {
  width: 38px; height: 38px; border-radius: 50%;
  background: var(--orange);
  color: #fff; border: none;
  font-size: 1.3em; cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: transform 0.2s, box-shadow 0.2s;
  flex-shrink: 0;
}
.btn-back:hover {
  transform: scale(1.08);
  box-shadow: 0 2px 8px rgba(255,138,0,0.35);
}

/* ===== 今日汪汪区 ===== */
.today-box {
  background: linear-gradient(135deg, #FFF8ED 0%, #FFF0D9 100%);
  border: 1.5px dashed var(--orange);
  border-radius: var(--radius);
  padding: 18px;
  margin-bottom: 14px;
  text-align: center;
  transition: border-color 0.3s, box-shadow 0.3s;
}
.today-box.urgent {
  border: 2px solid var(--red);
  background: linear-gradient(135deg, #FFF5F0 0%, #FFEDE4 100%);
  box-shadow: 0 0 0 6px rgba(217, 74, 74, 0.07);
}
.today-text {
  font-size: 1.08em;
  color: var(--brown);
  padding: 10px 0;
  line-height: 1.8;
}
.today-text.urgent {
  color: var(--red);
  font-weight: 600;
  animation: pawShake 0.5s ease-in-out;
}
@keyframes pawShake {
  0%, 100% { transform: translateX(0); }
  25% { transform: translateX(-4px); }
  75% { transform: translateX(4px); }
}

/* ===== 反应区 ===== */
.reaction-box {
  background: var(--orange-light);
  border-radius: var(--radius-sm);
  padding: 14px 16px;
  margin-top: 12px;
  font-size: 0.95em;
  color: var(--brown);
  line-height: 1.8;
  white-space: pre-line;
  display: none;
  border-left: 4px solid var(--orange);
}
.reaction-box.show { display: block; animation: fadeInUp 0.35s ease; }
.reaction-box .reaction-text { white-space: pre-line; line-height: 1.8; }
.reaction-box.error { background: #FFF0F0; border-left-color: var(--red); color: #8B2020; }

@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

/* ===== 时间线 ===== */
.timeline-item {
  display: flex;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px solid var(--border);
  align-items: flex-start;
}
.timeline-item:last-child { border-bottom: none; }
.timeline-icon {
  width: 40px; height: 40px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.2em;
  flex-shrink: 0;
}
.timeline-icon.vaccine { background: #E8F5E9; }
.timeline-icon.deworm { background: #FFF3E0; }
.timeline-icon.heat { background: #FCE4EC; }
.timeline-icon.abnormal { background: #FFEBEE; }
.timeline-icon.bath { background: #E0F7FA; }
.timeline-body { flex: 1; min-width: 0; }
.timeline-date { font-size: 0.8em; color: var(--muted); }
.timeline-desc { font-size: 0.88em; color: var(--brown-light); margin-top: 2px; }
.timeline-actions {
  display: flex;
  gap: 6px;
  align-items: center;
  flex-shrink: 0;
  opacity: 0;
  transition: opacity 0.2s;
  position: relative;
}
.timeline-item:hover .timeline-actions { opacity: 1; }
.timeline-btn {
  width: 28px; height: 28px;
  border-radius: 50%;
  border: 1px solid var(--border);
  background: var(--card);
  cursor: pointer;
  font-size: 0.78em;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
  padding: 0;
}
.timeline-btn:hover { background: #F5F0EB; border-color: var(--brown-light); }
.timeline-btn.del:hover { background: #FFF0F0; border-color: #E53935; }

/* 时间轴操作菜单 */
.timeline-btn-more {
  opacity: 1 !important;
  font-weight: 700; letter-spacing: 1px;
}
.timeline-menu {
  position: absolute; right: 100%; top: 50%; transform: translateY(-50%);
  margin-right: 8px;
  background: var(--card); border: 1px solid var(--border);
  border-radius: var(--radius-sm); box-shadow: 0 4px 16px rgba(0,0,0,0.12);
  z-index: 50; min-width: 130px; padding: 4px 0;
}
@media (max-width: 520px) {
  .timeline-menu {
    right: auto; left: 0; top: auto; bottom: 100%;
    transform: none; margin-right: 0; margin-bottom: 4px;
  }
}
.timeline-menu-item {
  display: block; width: 100%; padding: 8px 14px;
  border: none; background: none; cursor: pointer;
  font-size: 0.88em; color: var(--brown); font-family: inherit;
  text-align: left; transition: background 0.15s;
}
.timeline-menu-item:hover { background: var(--orange-light); }
.timeline-menu-item-del { color: var(--red); }
.timeline-menu-item-del:hover { background: #FFF0F0; }

.tl-photo-thumb {
  width: 60px; height: 60px;
  border-radius: 8px;
  object-fit: cover;
  cursor: pointer;
  border: 2px solid var(--border);
  margin-top: 6px;
  transition: transform 0.2s, box-shadow 0.2s;
}
.tl-photo-thumb:hover { transform: scale(1.05); box-shadow: 0 2px 8px rgba(0,0,0,0.15); }
.tl-add-photo-btn {
  margin-top: 6px;
  font-size: 0.8em;
  padding: 4px 10px;
  cursor: pointer;
}
.symptom-photo-link {
  font-size: 0.78em;
  color: var(--muted);
  text-decoration: none;
  cursor: pointer;
}
.symptom-photo-link:hover { color: var(--orange); text-decoration: underline; }

.empty-state {
  text-align: center;
  padding: 30px 16px;
  color: var(--muted);
  font-size: 0.95em;
}

/* ===== 档案卡片 ===== */
.profile-pill {
  display: inline-block;
  background: var(--orange-light);
  color: var(--orange-dark);
  padding: 3px 10px;
  border-radius: 12px;
  font-size: 0.82em;
  font-weight: 600;
  margin-right: 4px;
  margin-bottom: 4px;
}

/* ===== Toast ===== */
.toast {
  position: fixed;
  top: 20px;
  left: 50%;
  transform: translateX(-50%);
  background: var(--brown);
  color: #fff;
  padding: 12px 24px;
  border-radius: 24px;
  font-weight: 600;
  font-size: 0.93em;
  z-index: 999;
  box-shadow: 0 6px 20px rgba(0,0,0,0.2);
  animation: toastIn 0.3s ease, toastOut 0.3s ease 2.5s forwards;
  pointer-events: none;
}
@keyframes toastIn { from { opacity: 0; transform: translateX(-50%) translateY(-12px); } }
@keyframes toastOut { to { opacity: 0; transform: translateX(-50%) translateY(-8px); } }

/* ===== 骨架屏 ===== */
.skeleton {
  background: linear-gradient(90deg, #f0e8d8 25%, #e8dcc8 50%, #f0e8d8 75%);
  background-size: 200% 100%;
  animation: shimmer 1.5s infinite;
  border-radius: 6px;
  height: 16px;
  margin: 6px 0;
}
@keyframes shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }

/* ===== 兽医摘要卡片 ===== */
.vet-summary-overlay {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(90, 58, 42, 0.6);
  z-index: 1100;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  animation: fadeIn 0.3s ease;
}
.vet-summary-card {
  background: #FFFFFF;
  border-radius: 16px;
  padding: 0;
  max-width: 480px;
  width: 100%;
  max-height: 90vh;
  overflow-y: auto;
  box-shadow: 0 16px 48px rgba(0,0,0,0.22);
  animation: modalSlideUp 0.35s ease;
  border: 2px solid var(--orange);
}
.vet-card-header {
  background: linear-gradient(135deg, #FF8A00 0%, #FF6B35 100%);
  color: #FFFFFF;
  padding: 20px 20px 16px;
  text-align: center;
}
.vet-card-header .vet-badge {
  display: inline-block;
  background: rgba(255,255,255,0.25);
  border-radius: 12px;
  padding: 3px 12px;
  font-size: 0.78em;
  letter-spacing: 0.5px;
  margin-bottom: 8px;
}
.vet-card-header h3 {
  font-size: 1.2em;
  margin: 0 0 2px;
  font-weight: 700;
}
.vet-card-header .vet-date {
  font-size: 0.85em;
  opacity: 0.85;
}
.vet-card-body {
  padding: 16px 20px;
}
.vet-info-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 14px;
}
.vet-info-tag {
  background: #FFF8F0;
  border: 1px solid #FFE0C0;
  border-radius: 8px;
  padding: 6px 12px;
  font-size: 0.82em;
  color: var(--brown);
}
.vet-info-tag strong { color: var(--orange); }
.vet-section-title {
  font-size: 0.85em;
  font-weight: 700;
  color: var(--brown);
  margin: 14px 0 8px;
  padding-bottom: 6px;
  border-bottom: 2px dashed #F0E0D0;
}
.vet-symptom-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}
.vet-symptom-tag {
  background: #FFEBEE;
  color: #C62828;
  border-radius: 14px;
  padding: 4px 12px;
  font-size: 0.85em;
  font-weight: 600;
}
.vet-risk-banner {
  border-radius: 10px;
  padding: 10px 14px;
  margin-bottom: 12px;
  font-size: 0.9em;
  font-weight: 600;
  text-align: center;
}
.vet-risk-banner.high { background: #FFEBEE; color: #C62828; }
.vet-risk-banner.midhigh { background: #FFF3E0; color: #E65100; }
.vet-risk-banner.mid { background: #FFFDE7; color: #F57F17; }
.vet-risk-banner.low { background: #E8F5E9; color: #2E7D32; }
.vet-risk-banner.unknown { background: #F5F5F5; color: #757575; }
.vet-advice-item {
  background: #FAFAFA;
  border-radius: 10px;
  padding: 10px 14px;
  margin-bottom: 8px;
  border-left: 4px solid var(--orange);
  font-size: 0.88em;
  color: var(--brown);
  line-height: 1.7;
}
.vet-advice-item .vet-level-dot {
  display: inline-block;
  width: 8px; height: 8px;
  border-radius: 50%;
  margin-right: 6px;
  vertical-align: middle;
}
.vet-card-footer {
  padding: 12px 20px 16px;
  display: flex;
  gap: 10px;
  justify-content: center;
  flex-wrap: wrap;
}
.vet-btn {
  padding: 10px 20px;
  border-radius: 24px;
  font-size: 0.9em;
  font-weight: 600;
  cursor: pointer;
  border: none;
  transition: all 0.2s;
}
.vet-btn-close {
  background: #F5F5F5;
  color: var(--brown);
}
.vet-btn-close:hover { background: #E0E0E0; }
.vet-btn-screen {
  background: var(--orange);
  color: #FFFFFF;
}
.vet-btn-screen:hover { background: #E07800; }
@media (max-width: 520px) {
  .vet-summary-card { max-width: 100%; margin: 8px; }
  .vet-card-body { padding: 12px 14px; }
  .vet-card-footer { padding: 10px 14px 14px; }
}

/* ===== 页脚 ===== */
.app-footer {
  text-align: center;
  padding: 20px;
  color: var(--muted);
  font-size: 0.82em;
}

/* ===== 建档弹窗 ===== */
.modal-overlay {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(90, 58, 42, 0.55);
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  animation: fadeIn 0.3s ease;
}
@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }

.modal-card {
  background: var(--card);
  border-radius: var(--radius);
  padding: 28px 24px 22px;
  max-width: 520px;
  width: 100%;
  max-height: 90vh;
  overflow-y: auto;
  box-shadow: 0 12px 40px rgba(0,0,0,0.18);
  border: 1px solid var(--border);
  animation: modalSlideUp 0.35s ease;
}
@keyframes modalSlideUp {
  from { opacity: 0; transform: translateY(24px); }
  to { opacity: 1; transform: translateY(0); }
}

.modal-header {
  position: relative;
  text-align: center;
  margin-bottom: 18px;
}
.modal-logo { font-size: 2.8em; margin-bottom: 4px; }
.modal-header h2 {
  font-size: 1.35em;
  color: var(--orange);
  margin-bottom: 4px;
}
.modal-sub {
  color: var(--muted);
  font-size: 0.9em;
  line-height: 1.6;
}

.modal-body { margin-bottom: 16px; }

.modal-footer { text-align: center; }

.btn-lg { padding: 12px 28px; font-size: 1.05em; }

/* ===== 日期选择器 ===== */
.date-picker-container {
  background: var(--card);
  border-radius: var(--radius);
  width: 340px; max-width: 94vw;
  box-shadow: 0 12px 40px rgba(0,0,0,0.18);
  border: 1px solid var(--border);
  overflow: hidden;
}
.dp-layer { padding: 16px 18px 12px; }
.dp-header {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 14px;
}
.dp-nav-arrow {
  width: 32px; height: 32px; display: flex; align-items: center; justify-content: center;
  background: none; border: none; cursor: pointer;
  font-size: 0.75em; color: #333; font-weight: 400;
  border-radius: 50%; transition: background 0.15s;
  font-family: inherit;
}
.dp-nav-arrow:hover { background: #f0ebe4; }
.dp-title {
  font-size: 1.05em; font-weight: 700; color: var(--brown);
  cursor: pointer; user-select: none; padding: 4px 12px; border-radius: 6px;
  transition: background 0.15s;
}
.dp-title:hover { background: #f5f0e8; }
.dp-weekdays {
  display: grid; grid-template-columns: repeat(7, 1fr);
  text-align: center; font-size: 0.78em; color: var(--muted);
  margin-bottom: 6px; padding-bottom: 6px; border-bottom: 1px solid var(--border);
}
.dp-days-grid {
  display: grid; grid-template-columns: repeat(7, 1fr);
  gap: 2px; text-align: center;
}
.dp-day {
  aspect-ratio: 1; display: flex; align-items: center; justify-content: center;
  font-size: 0.88em; color: var(--brown); border-radius: 8px;
  cursor: pointer; transition: all 0.12s; user-select: none;
}
.dp-day:hover { background: #f5f0e8; }
.dp-day.other-month { color: #ccc; pointer-events: none; }
.dp-day.today { border: 1.5px solid var(--orange); font-weight: 700; }
.dp-day.selected { background: var(--orange); color: #fff; font-weight: 700; }
.dp-day.selected.today { background: var(--orange); color: #fff; border-color: var(--orange); }
.dp-footer {
  display: flex; justify-content: space-between; align-items: center;
  margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--border);
}
/* 第二层：月份网格 */
.dp-months-grid {
  display: grid; grid-template-columns: repeat(3, 1fr);
  gap: 10px; padding: 4px 0;
}
.dp-month {
  aspect-ratio: 1.4; display: flex; align-items: center; justify-content: center;
  font-size: 0.95em; font-weight: 600; color: var(--brown);
  border-radius: 10px; cursor: pointer; user-select: none;
  border: 2px solid transparent; transition: all 0.12s;
}
.dp-month:hover { background: #f5f0e8; }
.dp-month.current { border-color: #B3D4FC; background: #F0F7FF; }
.dp-month.selected { border-color: var(--orange); background: var(--orange-light); }

/* 移除旧的滚轮日期选择器样式 */
/* 生日三连下拉（保留兼容） */
.triple-select {
  display: flex;
  gap: 8px;
}
.triple-select select { flex: 1; }
.triple-select select:first-child { flex: 2; }

/* 隐藏主界面（建档前） */
.main-hidden { display: none; }

/* ===== 时间线分类筛选 ===== */
.timeline-filters { margin-top: 4px; }
.tl-filter {
  display: inline-block;
  padding: 4px 12px;
  border-radius: 20px;
  font-size: 0.82em;
  font-weight: 600;
  cursor: pointer;
  user-select: none;
  border: 1.5px solid var(--border);
  color: var(--muted);
  background: #FFFAF2;
  transition: all 0.2s;
}
.tl-filter:hover {
  border-color: var(--orange);
  color: var(--brown);
}
.tl-filter.active {
  background: var(--orange);
  color: #fff;
  border-color: var(--orange);
}

/* ===== 饮食宝典：双栏食谱区 ===== */
.recipe-wrap {
  display: flex;
  gap: 18px;
  flex-wrap: wrap;
  align-items: stretch;
}
/* 左栏：食谱主卡 */
.recipe-main {
  flex: 5;
  min-width: 260px;
  background: #FFFBF5;
  background-image: radial-gradient(circle, #EBE0CF 0.5px, transparent 0.5px);
  background-size: 14px 14px;
  border-radius: var(--radius-sm);
  border: 2px solid #E0D2B8;
  padding: 18px 20px;
  display: flex;
  flex-direction: column;
}
/* 顶部双装饰线 */
.recipe-deco {
  text-align: center;
  margin-bottom: 10px;
}
.recipe-deco-line {
  height: 1px;
  background: var(--border);
  margin: 5px 0;
}
.recipe-deco-line:nth-child(2) {
  height: 1.5px;
  background: #D4C0A8;
}
.recipe-deco-title {
  font-family: "Gaegu", "KaiTi", "STKaiti", "Comic Sans MS", sans-serif;
  font-size: 1.1em;
  color: var(--brown-light);
  padding: 2px 0;
  letter-spacing: 0.5px;
}
/* 日期行 */
.recipe-date {
  font-size: 0.82em;
  color: var(--muted);
  margin-bottom: 6px;
  text-align: center;
}
/* 主菜名 */
.recipe-meal-name {
  font-family: "Gaegu", "KaiTi", "STKaiti", "Comic Sans MS", sans-serif;
  font-size: 1.3em;
  font-weight: 700;
  color: var(--brown);
  text-align: center;
  margin-bottom: 14px;
  letter-spacing: 1px;
}
/* 食材清单 */
.recipe-items {
  margin-bottom: 8px;
}
.recipe-item {
  display: flex;
  align-items: baseline;
  padding: 7px 12px;
  border-radius: 8px;
  margin-bottom: 3px;
}
.recipe-item:nth-child(odd) {
  background: rgba(255, 240, 215, 0.45);
}
.recipe-item:nth-child(even) {
  background: rgba(255, 255, 250, 0.5);
}
.recipe-item-name {
  font-size: 0.92em;
  color: var(--brown);
  flex-shrink: 0;
}
.recipe-item-dots {
  flex: 1;
  border-bottom: 1px dotted #D0C0A8;
  margin: 0 10px;
  min-width: 20px;
}
.recipe-item-weight {
  font-weight: 700;
  font-size: 0.95em;
  color: var(--brown);
  flex-shrink: 0;
}
/* 总重行 */
.recipe-total {
  display: flex;
  align-items: baseline;
  padding: 7px 12px;
  border-top: 1.5px solid var(--border);
  margin-top: 4px;
  font-size: 0.92em;
}
.recipe-total-label {
  color: var(--brown-light);
}
.recipe-total-weight {
  margin-left: auto;
  font-weight: 800;
  color: var(--brown);
  font-size: 1em;
}
/* 营养摘要标签 */
.recipe-nutrition {
  display: flex;
  flex-wrap: nowrap;
  gap: 6px;
  margin: 12px 0;
  justify-content: center;
}
.recipe-nutrition .nut-tag {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 3px 10px;
  border-radius: 20px;
  font-size: 0.75em;
  font-weight: 600;
  white-space: nowrap;
}
.nut-tag-protein { background: #FDECEA; color: #C0392B; }
.nut-tag-fat    { background: #FFF5E0; color: #B8860B; }
.nut-tag-carbs  { background: #E8F0FE; color: #2471A3; }
/* 烹饪小贴士 */
.recipe-cooking-tip {
  text-align: center;
  font-family: "Gaegu", "KaiTi", "STKaiti", "Comic Sans MS", sans-serif;
  font-size: 0.85em;
  color: var(--muted);
  line-height: 1.5;
  margin-top: auto;
  padding-top: 4px;
}

/* 饮食计算依据折叠区 */
.diet-basis-toggle {
  text-align: center; font-size: 0.82em; color: var(--brown-light);
  cursor: pointer; padding: 8px; margin-top: 8px;
  border-radius: var(--radius-sm); border: 1px dashed var(--border);
  transition: background 0.2s;
}
.diet-basis-toggle:hover { background: var(--orange-light); }
.diet-basis-detail {
  background: #FAFAFA; border-radius: var(--radius-sm);
  padding: 10px 14px; margin-top: 4px;
  border: 1px solid var(--border);
}
.diet-basis-row {
  display: flex; justify-content: space-between;
  font-size: 0.82em; line-height: 2;
  border-bottom: 1px dotted #EEE;
}
.diet-basis-row:last-child { border-bottom: none; }
.diet-basis-row span:first-child { color: var(--muted); }
.diet-basis-row span:last-child { color: var(--brown); font-weight: 600; }

/* 右栏：补充信息 */
.recipe-side {
  flex: 5;
  min-width: 200px;
  background: #FFFBF5;
  border-radius: var(--radius-sm);
  padding: 18px 20px;
  font-size: 0.95em;
  line-height: 2.2;
  display: flex;
  flex-direction: column;
}
.recipe-side .side-section {
  margin-bottom: 14px;
}
.recipe-side .side-label {
  font-weight: 600;
  font-size: 1em;
  color: var(--brown-light);
  margin-bottom: 3px;
}
.recipe-side .side-text {
  color: var(--brown);
}
/* 保健品小队 */
.supp-alert-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  margin-bottom: 8px;
  background: #FFFBF5;
  border: 1px solid var(--border);
}
.supp-alert-icon {
  font-size: 1.4em;
  flex-shrink: 0;
  line-height: 1;
}
.supp-alert-body {
  flex: 1;
  font-size: 0.9em;
  line-height: 1.7;
  color: var(--brown);
}
.supp-alert-name {
  font-weight: 700;
  color: var(--brown);
}
.supp-alert-reason {
  font-size: 0.85em;
  color: var(--brown-light);
  margin-top: 2px;
}
.supp-alert-woof {
  font-family: "Gaegu", "KaiTi", "STKaiti", "Comic Sans MS", sans-serif;
  font-size: 0.88em;
  color: var(--muted);
  margin-top: 4px;
  line-height: 1.5;
}
.supp-empty {
  text-align: center;
  font-size: 0.9em;
  color: var(--muted);
  padding: 12px 0;
  line-height: 1.8;
}

/* 保健品空状态 - 解释型布局 */
.supp-empty-state {
  text-align: center; padding: 16px 8px;
}
.supp-empty-icon { font-size: 2.5em; margin-bottom: 8px; }
.supp-empty-title {
  font-weight: 700; color: var(--brown); font-size: 1em; margin-bottom: 6px;
}
.supp-empty-desc {
  font-size: 0.85em; color: var(--muted); margin-bottom: 14px; line-height: 1.6;
}
.supp-empty-checklist {
  text-align: left; max-width: 360px; margin: 0 auto 12px;
  background: #F9FFF5; border-radius: var(--radius-sm); padding: 10px 14px;
  border: 1px solid #D4EDC9;
}
.supp-check-item {
  font-size: 0.82em; color: var(--brown-light); line-height: 1.8;
}
.supp-check-icon { color: var(--green); margin-right: 4px; font-weight: 700; }
.supp-empty-divider {
  height: 1px; background: var(--border); max-width: 200px; margin: 12px auto;
}
.supp-empty-subtitle {
  font-weight: 700; color: var(--brown); font-size: 0.88em; margin-bottom: 6px;
}
.supp-empty-hints {
  font-size: 0.8em; color: var(--muted); line-height: 1.9;
}

/* ===== 响应式：桌面端 (≥1024px) ===== */
@media (min-width: 1024px) {
  .container { max-width: 900px; }
  .badge-grid { grid-template-columns: repeat(5, 1fr); }
  .quick-record-grid { grid-template-columns: repeat(4, 1fr); }
  .growth-photos-row { gap: 10px; }
  .growth-photo-thumb { width: calc((100% - 30px) / 4); min-width: 100px; }
  .growth-photo-thumb-placeholder { width: calc((100% - 30px) / 4); min-width: 100px; }
}

/* ===== 响应式：移动端适配 ===== */
/* 平板/小屏设备 (≤600px) */
@media (max-width: 600px) {
  /* 头部 */
  .app-header { padding: 10px 10px 4px; }
  .app-header .logo { font-size: 1.7em; }
  .subtitle { font-size: 0.82em; }

  .today-avatar-sm { width: 46px; height: 46px; font-size: 1.5em; }

  /* 容器 */
  .container { padding: 0 8px 40px; }

  /* 今日状态卡 */
  .today-dashboard { padding: 12px 12px; }
  .today-dashboard-main .today-avatar { width: 48px; height: 48px; font-size: 1.6em; }
  .today-dashboard-info { font-size: 0.88em; }
  .today-pending { font-size: 0.85em; }

  /* 今日健康检查 */
  .daily-check-card { padding: 14px 14px 12px; }
  .daily-check-desc { font-size: 0.84em; }
  .btn-check-ok, .btn-check-warn { padding: 11px 12px; font-size: 0.92em; }

  /* 快速记录 */
  .quick-record-card { padding: 12px 8px; }
  .qr-icon { font-size: 1.4em; }
  .qr-label { font-size: 0.82em; }
  .qr-hint { font-size: 0.68em; }

  /* 健康档案 */
  .health-profile-card { padding: 12px 12px; }

  /* 成长记录 */
  .growth-photo-thumb { min-width: 60px; }
  .growth-photo-thumb-placeholder { min-width: 60px; }

  /* 卡片 */
  .card { padding: 14px 12px; margin-bottom: 10px; }
  .card-title { font-size: 1em; }
  .card-subtitle { font-size: 0.8em; }

  /* 子页面标题 */
  .sub-page-title { font-size: 1.05em; }
  .sub-page-header-row { flex-wrap: wrap; gap: 6px; }

  /* 表单：移动端纵排 */
  .form-row { flex-direction: column; gap: 8px; margin-bottom: 8px; }
  .form-col { flex: none; width: 100%; }
  input, select, textarea { padding: 8px 10px; font-size: 0.9em; }
  input[type="file"] { width: 100%; }

  /* 三连下拉 */
  .triple-select { gap: 4px; }
  .triple-select select { font-size: 0.82em; padding: 7px 4px; }

  /* 按钮 */
  .btn { padding: 8px 14px; font-size: 0.88em; border-radius: 20px; }
  .btn-lg { padding: 10px 22px; font-size: 0.95em; }
  .btn-sm { padding: 5px 10px; font-size: 0.8em; }

  /* 弹窗 */
  .modal-overlay { padding: 8px; }
  .modal-card { padding: 20px 14px 16px; max-width: 100%; border-radius: 12px; }
  .modal-header { margin-bottom: 12px; }
  .modal-logo { font-size: 2.2em; }
  .modal-header h2 { font-size: 1.15em; }
  .modal-sub { font-size: 0.82em; }
  .modal-body { margin-bottom: 12px; }

  /* 饮食宝典 */
  .recipe-wrap { flex-direction: column; gap: 10px; }
  .recipe-main, .recipe-side { min-width: auto; padding: 14px 12px; }
  .recipe-meal-name { font-size: 1.1em; }
  .recipe-deco-title { font-size: 1em; }
  .recipe-item { padding: 5px 8px; }
  .recipe-item-name { font-size: 0.85em; }
  .recipe-item-weight { font-size: 0.88em; }
  .recipe-nutrition { flex-wrap: wrap; }
  .recipe-nutrition .nut-tag { font-size: 0.7em; padding: 2px 8px; }
  .recipe-side { font-size: 0.88em; line-height: 2; }
  .recipe-side .side-section { margin-bottom: 10px; }

  /* 保健品 */
  .supp-alert-item { padding: 8px 10px; gap: 8px; }
  .supp-alert-icon { font-size: 1.2em; }
  .supp-alert-body { font-size: 0.85em; }

  /* 时间线 */
  .timeline-item { gap: 8px; padding: 8px 0; }
  .timeline-icon { width: 34px; height: 34px; font-size: 1em; }
  .timeline-body { font-size: 0.82em; }
  .timeline-date { font-size: 0.72em; }
  .timeline-desc { font-size: 0.8em; }
  .timeline-actions { opacity: 1; }
  .timeline-btn { width: 26px; height: 26px; font-size: 0.72em; }

  /* 时间线筛选标签 */
  .tl-filter { padding: 3px 8px; font-size: 0.75em; }

  /* 体重管理页 */
  #wlWeight, #wlDate { font-size: 0.85em; }

  /* 兽医摘要 */
  .vet-summary-card { max-width: 100%; margin: 4px; }
  .vet-card-header { padding: 14px 14px 12px; }
  .vet-card-body { padding: 10px 12px; }
  .vet-card-footer { padding: 8px 12px 12px; gap: 6px; }
  .vet-btn { padding: 8px 14px; font-size: 0.82em; }
  .vet-card-header h3 { font-size: 1.05em; }
  .vet-advice-item { padding: 8px 10px; font-size: 0.82em; }
  .vet-symptom-tag { font-size: 0.78em; padding: 3px 8px; }
  .vet-info-tag { font-size: 0.76em; padding: 4px 8px; }

  /* 反应区 */
  .reaction-box { padding: 10px 12px; font-size: 0.88em; }

  /* Toast */
  .toast { font-size: 0.85em; padding: 10px 18px; left: 12px; right: 12px; transform: none; max-width: none; border-radius: 14px; text-align: center; }
  @keyframes toastIn { from { opacity: 0; transform: translateY(-12px); } }
  @keyframes toastOut { to { opacity: 0; transform: translateY(-8px); } }

  /* 页脚 */
  .app-footer { padding: 14px 8px; font-size: 0.74em; }
}

/* 小屏手机 (≤420px) */
@media (max-width: 420px) {
  /* 今日状态卡 */
  .today-dashboard { padding: 10px 10px; }
  .today-dashboard-main .today-avatar { width: 44px; height: 44px; font-size: 1.4em; }
  .today-dashboard-info { font-size: 0.84em; }
  .td-paw { font-size: 0.78em; padding: 3px 8px; }
  .td-streak { font-size: 0.76em; }

  /* 今日健康检查 */
  .daily-check-actions { flex-direction: column; gap: 6px; }

  /* 快速记录 */
  .quick-record-card { padding: 10px 6px; }
  .qr-icon { font-size: 1.2em; }
  .qr-label { font-size: 0.78em; }
  .qr-hint { font-size: 0.66em; }

  /* 档案 */
  .health-profile-card { padding: 10px 10px; }

  /* 复选框组 */
  .checkbox-group label { padding: 5px 8px; font-size: 0.8em; }

  /* 弹窗更紧凑 */
  .modal-card { padding: 16px 10px 12px; }

  /* 按钮更易点击 */
  .btn { min-height: 40px; }
  .btn-sm { min-height: 34px; }

  /* 食材清单 */
  .recipe-item-dots { margin: 0 4px; min-width: 8px; }
}

/* 超小屏 (≤360px) */
@media (max-width: 360px) {
  .today-dashboard-main .today-avatar { width: 40px; height: 40px; font-size: 1.3em; }
  .today-dashboard-info { font-size: 0.8em; }
  .quick-record-card { padding: 8px 4px; }
  .qr-icon { font-size: 1.1em; }
  .qr-label { font-size: 0.74em; }
}
</style>
</head>
<body>

<!-- ===== 建档弹窗（首次访问） ===== -->
<div class="modal-overlay" id="modalOverlay" style="display:none;">
  <div class="modal-card">
    <div class="modal-header">
      <div class="modal-logo">🐾</div>
      <h2>欢迎来到 PawLife！</h2>
      <p class="modal-sub">在开始之前，让我先认识一下你吧～<br/>填写下面的小档案，只需要 1 分钟！</p>
    </div>
    <div class="modal-body">
      <div class="form-row">
        <div class="form-col"><label>我的名字 <span class="required">*</span></label><input id="mName" placeholder="汪！我的名字是…" maxlength="64" /></div>
        <div class="form-col"><label>我的品种 <span class="required">*</span></label>
          <select id="mBreed"><option value="金毛">金毛</option><option value="拉布拉多">拉布拉多</option><option value="柯基">柯基</option><option value="贵宾">贵宾</option><option value="豆柴">豆柴</option><option value="混血">混血</option><option value="其他">其他</option></select>
        </div>
      </div>
      <div class="form-row">
        <div class="form-col"><label>我的生日 <span class="required">*</span></label>
          <input type="text" id="mBirthday" readonly placeholder="点击选择生日" style="width:100%;padding:10px 12px;font-size:0.95em;cursor:pointer;background:#FFFDF7;border:1px solid var(--border);border-radius:8px;" onclick="openDatePicker('mBirthday')" />
        </div>
      </div>
      <div class="form-row">
        <div class="form-col"><label>我的体重</label><input id="mWeight" placeholder="例：28kg" /></div>
        <div class="form-col"><label>我的性别</label>
          <select id="mGender"><option value="">保密</option><option value="male">公</option><option value="female">母</option></select>
        </div>
      </div>
      <div class="form-row">
        <div class="form-col"><label>绝育情况</label>
          <select id="mNeutered"><option value="未知">未知</option><option value="是">是</option><option value="否">否</option></select>
        </div>
        <div class="form-col"><label>过敏源</label><input id="mAllergies" placeholder="逗号分隔，如：鸡肉,谷物" /></div>
      </div>
      <div class="form-row">
        <div class="form-col"><label>已知健康状况 <span style="color:var(--muted);font-weight:400;">（可选）</span></label><input id="mDiseases" placeholder="如：慢性肾病、胰腺炎、心脏病等" /></div>
        <div class="form-col"><label>到家日期 <span style="color:var(--muted);font-weight:400;">（可选）</span></label><input type="text" id="mHomeDate" readonly placeholder="点击选择日期" style="width:100%;padding:10px 12px;font-size:0.95em;cursor:pointer;background:#FFFDF7;border:1px solid var(--border);border-radius:8px;" onclick="openDatePicker('mHomeDate')" /></div>
      </div>
      <div class="form-row">
        <div class="form-col"><label>我的照片 <span style="color:var(--muted);font-weight:400;">（可选）</span></label>
          <input type="file" id="mPhoto" accept="image/jpeg,image/png" />
        </div>
      </div>
      <div style="background:#FFFBF5;border:1px solid #FFE0C0;border-radius:8px;padding:10px 14px;margin-top:12px;font-size:0.82em;color:var(--brown-light);line-height:1.6;">
        ⚠️ 免责声明：本应用提供的所有内容（包括饮食建议、保健品提醒、事件提醒等）仅供参考和教育目的，不能替代执业兽医的专业诊断、治疗或建议。如您的宠物出现任何健康问题或紧急情况，请立即联系持证兽医。
      </div>
      <div style="margin-top:8px;font-size:0.9em;">
        <label style="cursor:pointer;display:flex;align-items:center;gap:6px;color:var(--brown);">
          <input type="checkbox" id="mDisclaimerAgree" style="width:auto;accent-color:var(--orange);" />
          我已阅读并理解上述免责声明
        </label>
      </div>
    </div>
    <div class="modal-footer">
      <button class="btn btn-primary btn-lg" id="btnModalCreate">🐾 完成建档，开启汪生！</button>
    </div>
  </div>
</div>

<div class="app-header main-hidden" id="mainContent">
  <div class="logo">🐾 PawLife</div>
  <div class="hero-tagline">记录每一次照护，守护宠物健康成长</div>
</div>

<!-- ===== 狗狗照片上传 input（隐藏）===== -->
<input type="file" id="dogPhotoInput" accept="image/jpeg,image/png" style="display:none;" />

<div class="container">

  <!-- ==================== 首页 ==================== -->
  <div id="page-home">

    <!-- ===== 今日状态卡 ===== -->
    <div class="today-dashboard" id="todayDashboard">
      <div class="today-dashboard-main">
        <div class="today-avatar" id="todayAvatar" title="点击查看/编辑档案" onclick="openEditModal()">🐶</div>
        <div class="today-dashboard-info" id="todayDashboardInfo">
          <div class="skeleton" style="width:120px;"></div>
        </div>
        <div class="today-dashboard-meta">
          <span class="td-paw" id="statusPawPoints" style="display:none;" onclick="openPawHistory()">🐾 <b id="statusPawCount">0</b></span>
          <span class="td-streak" id="statusStreak" style="display:none;">🔥 <b id="statusStreakCount">0</b>天</span>
        </div>
      </div>
      <div class="today-pending" id="todayPending">
        <div class="skeleton" style="width:60%;height:18px;margin:4px 0;"></div>
      </div>
    </div>

    <!-- ===== 今日健康检查（主CTA） ===== -->
    <div class="daily-check-card" id="dailyCheckCard">
      <div class="daily-check-header">
        <span class="daily-check-icon" id="dailyCheckIcon">🩺</span>
        <span class="daily-check-title">今日健康检查</span>
        <span class="daily-check-badge" id="dailyCheckBadge" style="display:none;">✅ 已完成</span>
      </div>
      <div class="daily-check-desc" id="dailyCheckDesc">
        用 1 分钟轻轻摸摸<span class="pet-name-inline">狗狗</span>的头部、背部、四肢和腹部，确认是否有硬块、红肿、脱毛或异常发热。
      </div>
      <div class="daily-check-actions" id="dailyCheckActions">
        <button class="btn btn-check-ok" id="btnCheckOk" onclick="recordDailyCheck('normal')">✅ 一切正常</button>
        <button class="btn btn-check-warn" id="btnCheckWarn" onclick="recordDailyCheck('abnormal')">⚠️ 发现异常</button>
      </div>
      <div class="daily-check-completed" id="dailyCheckCompleted" style="display:none;"></div>
      <div class="daily-check-note">完成后将自动记录到健康时间轴，并获得 1 枚爪印。</div>
    </div>

    <!-- ===== 汪汪日常 ===== -->
    <div class="section-label">🐶 汪汪日常</div>
    <!-- 第一行：2 个主功能 -->
    <div class="quick-record-grid">
      <div class="quick-record-card" onclick="navigateTo('record')">
        <span class="qr-icon">📝</span>
        <span class="qr-label">记录健康事件</span>
        <span class="qr-hint">疫苗、驱虫、异常，事事有迹可循</span>
      </div>
      <div class="quick-record-card" onclick="navigateTo('diet')">
        <span class="qr-icon">🍖</span>
        <span class="qr-label">饮食指导</span>
        <span class="qr-hint">按品种、年龄和体重量身推荐</span>
      </div>
    </div>
    <!-- 第二行：4 个辅功能 -->
    <div class="quick-record-grid-sm">
      <div class="quick-record-card-sm" onclick="navigateTo('weight')">
        <span class="qr-icon-sm">⚖️</span>
        <span class="qr-label-sm">体重管理</span>
      </div>
      <div class="quick-record-card-sm" onclick="navigateTo('reminders')">
        <span class="qr-icon-sm">📅</span>
        <span class="qr-label-sm">照护提醒</span>
      </div>
      <div class="quick-record-card-sm" onclick="navigateTo('badges')">
        <span class="qr-icon-sm">🎖️</span>
        <span class="qr-label-sm">健康成就</span>
      </div>
      <div class="quick-record-card-sm" id="cardSuppHome" onclick="navigateTo('supplement')">
        <span class="feature-badge" id="badgeSupplement" style="display:none;"></span>
        <span class="feature-paw-badge" id="badgePawSupplement" style="display:none;" onclick="event.stopPropagation();openEasterEgg();">🐾</span>
        <span class="qr-icon-sm">🛡️</span>
        <span class="qr-label-sm">营养补充</span>
      </div>
    </div>

    <!-- ===== 健康档案卡 ===== -->
    <div class="section-label">📋 健康档案</div>
    <div class="health-profile-card" id="healthProfileCard">
      <div class="hp-card-inner" id="hpCardInner" style="display:none;">
        <div class="hp-card-header" id="hpCardHeader" style="display:none;">
          <span class="hp-icon">🐶</span>
          <span class="hp-name" id="hpName"></span>
          <button class="btn btn-text btn-sm" style="margin-left:auto;" onclick="openEditModal()">✏️ 编辑</button>
        </div>
        <div class="hp-snapshot" id="hpSnapshot"></div>
      </div>
      <!-- 未建档状态 -->
      <div class="hp-empty" id="hpEmpty" style="display:none;">
        <div class="hp-empty-icon">🐶</div>
        <div class="hp-empty-title">创建狗狗档案</div>
        <div class="hp-empty-desc">主人，快帮我建个档案吧，这样你就能看到我的全部健康信息啦～</div>
        <button class="btn btn-primary" id="btnCreateProfileHome">🐾 建立档案</button>
      </div>
    </div>

    <!-- ===== 成长记录（压缩版） ===== -->
    <div class="section-label">📸 成长记录</div>
    <div class="growth-compact" id="growthCompact">
      <div class="skeleton" style="width:50%;"></div>
    </div>

    <!-- 彩蛋提示 -->
    <div class="easter-hint" id="easterHint" style="display:none;">
      💡 嘘…在 <b>营养补充</b> 里藏了一个小彩蛋 🐾
    </div>

    <!-- 备份按钮 -->
    <div style="text-align:right;margin-top:6px;">
      <button class="btn btn-text btn-sm" id="btnExport">📥 备份数据</button>
    </div>
  </div>

  <!-- ==================== 子页面：记录事件 ==================== -->
  <div id="page-record" class="sub-page" style="display:none;">
    <div class="sub-page-header">
      <div class="sub-page-header-row">
        <button class="btn-back-text" onclick="navigateTo('home')">← 返回首页</button>
        <span class="sub-page-title">📝 记录事件</span>
        <div class="today-avatar-sm" id="greetingAvatarSub">🐶</div>
      </div>
    </div>
    <div class="card" id="cardEvent">
      <div class="card-header-row">
        <div class="card-subtitle" id="eventSubtitle" style="flex:1;margin-bottom:0;">记录疫苗、驱虫、发情或异常行为，我会立刻给你反馈</div>
        <button class="btn-collapse-toggle" id="btnCollapseEvent" onclick="toggleEventForm()" title="折叠/展开记录表单">▲</button>
      </div>
      <div id="eventFormBody">
      <div class="form-row">
        <div class="form-col"><label>事件类型</label>
          <select id="fEType"><option value="疫苗">💉 疫苗</option><option value="驱虫">💊 驱虫</option><option value="发情">💕 发情</option><option value="异常行为">⚠️ 异常行为</option><option value="洗澡澡">🛁 洗澡澡</option><option value="每日检查">🩺 每日检查</option></select>
        </div>
        <div class="form-col"><label>日期</label>
          <input type="text" id="eventDate" readonly placeholder="选择日期" style="width:100%;padding:10px 12px;font-size:0.95em;cursor:pointer;background:#FFFDF7;border:1px solid var(--border);border-radius:8px;" onclick="openDatePicker('eventDate')" />
        </div>
      </div>
      <div id="extraFields" style="margin-bottom:4px;"></div>
      <div style="text-align:right;">
        <button class="btn btn-primary" id="btnSubmitEvent">🐾 提交记录</button>
      </div>
      <div class="reaction-box" id="eventReaction"></div>
      </div><!-- end #eventFormBody -->
    </div>
    <!-- 时间线也放在记录页面 -->
    <div class="card" id="cardTimeline">
      <div class="card-title" id="timelineTitle">📅 汪生时间线</div>
      <div class="timeline-filters" id="timelineFilters" style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px;">
        <span class="tl-filter active" data-filter="全部">全部</span>
        <span class="tl-filter" data-filter="疫苗">💉 疫苗</span>
        <span class="tl-filter" data-filter="驱虫">💊 驱虫</span>
        <span class="tl-filter" data-filter="异常行为">⚠️ 异常</span>
        <span class="tl-filter" data-filter="每日检查">🩺 摸摸</span>
        <span class="tl-filter" data-filter="发情">💕 发情</span>
        <span class="tl-filter" data-filter="洗澡澡">🛁 洗澡</span>
      </div>
      <div id="timelineArea" style="margin-top:8px;">
        <div class="skeleton" style="width:60%;"></div>
        <div class="skeleton" style="width:45%;"></div>
        <div class="skeleton" style="width:55%;"></div>
      </div>
    </div>
    <!-- 彩蛋入口（按日随机出现） -->
    <div class="easter-subpage-entry" id="easterEntryRecord" style="display:none;" onclick="openEasterEgg()">
      <span class="easter-paw">🐾</span>
      <span class="easter-label">发现隐藏彩蛋？</span>
    </div>
  </div>

  <!-- ==================== 子页面：饮食宝典 ==================== -->
  <div id="page-diet" class="sub-page" style="display:none;">
    <div class="sub-page-header">
      <div class="sub-page-header-row">
        <button class="btn-back-text" onclick="navigateTo('home')">← 返回首页</button>
        <span class="sub-page-title">🍖 饮食宝典</span>
        <div class="today-avatar-sm" id="greetingAvatarSub">🐶</div>
      </div>
    </div>
    <div class="card" id="cardDiet">
      <div id="dietArea" style="margin-top:8px;">
        <div class="skeleton" style="width:60%;"></div>
      </div>
    </div>
    <div class="easter-subpage-entry" id="easterEntryDiet" style="display:none;" onclick="openEasterEgg()">
      <span class="easter-paw">🐾</span>
      <span class="easter-label">发现隐藏彩蛋？</span>
    </div>
  </div>

  <!-- ==================== 子页面：大事记 ==================== -->
  <!-- ==================== 子页面：荣誉勋章墙 ==================== -->
  <div id="page-badges" class="sub-page" style="display:none;">
    <div class="sub-page-header">
      <div class="sub-page-header-row">
        <button class="btn-back-text" onclick="navigateTo('home')">← 返回首页</button>
        <span class="sub-page-title">🏵️ 我们的荣誉墙</span>
        <div class="today-avatar-sm" id="greetingAvatarSub">🐶</div>
      </div>
    </div>

    <!-- 情绪安抚区 -->
    <div class="badge-emotion-card" id="badgeEmotionCard">
      <div class="badge-emotion-inner">
        <div class="badge-emotion-left">
          <div class="badge-emotion-avatar" id="badgeEmotionAvatar">🐶</div>
          <div class="badge-emotion-name" id="badgeEmotionName">正在加载…</div>
          <div class="badge-emotion-days" id="badgeEmotionDays"></div>
        </div>
        <div class="badge-emotion-right">
          <div class="badge-emotion-count" id="badgeEmotionCount">✨</div>
          <div class="badge-emotion-text" id="badgeEmotionText">每一枚勋章，都是我们一起认真生活的证据。</div>
        </div>
      </div>
    </div>

    <!-- 故事线分类区 -->
    <div class="badge-story-tabs" id="badgeStoryTabs">
      <span class="badge-story-tab active" data-cat="all">全部</span>
      <span class="badge-story-tab" data-cat="第一次">🐣 我们的第一次</span>
      <span class="badge-story-tab" data-cat="守护者">🛡️ 守护者联盟</span>
      <span class="badge-story-tab" data-cat="健康里程碑">🌱 成长里程碑</span>
    </div>

    <!-- 勋章墙 -->
    <div class="badge-wall" id="badgeWall">
      <div class="skeleton" style="width:60%;"></div>
    </div>

    <!-- 空状态 -->
    <div class="badge-empty" id="badgeEmpty" style="display:none;">
      <div class="badge-empty-icon">🐶📖</div>
      <div class="badge-empty-title">我们的第一枚小纪念，还在路上</div>
      <div class="badge-empty-desc">主人不用着急呀。从第一次疫苗、第一次驱虫，到每一次认真照顾我，都会慢慢变成属于我们的小勋章。</div>
      <button class="btn btn-primary" onclick="navigateTo('record')">📝 记录一次健康事件</button>
      <div class="badge-empty-foot">按我们的节奏来，就很好。</div>
    </div>

    <!-- 勋章详情弹窗 -->
    <div class="modal-overlay" id="badgeDetailOverlay" style="display:none;">
      <div class="badge-detail-card" id="badgeDetailCard">
        <button class="badge-detail-close" onclick="closeBadgeDetail()">✕</button>
        <div class="badge-detail-icon" id="badgeDetailIcon"></div>
        <div class="badge-detail-name" id="badgeDetailName"></div>
        <div class="badge-detail-story" id="badgeDetailStory"></div>
        <div class="badge-detail-date" id="badgeDetailDate"></div>
        <div class="badge-detail-woof" id="badgeDetailWoof"></div>
      </div>
    </div>

    <!-- 彩蛋入口 -->
    <div class="easter-subpage-entry" id="easterEntryTimeline" style="display:none;" onclick="openEasterEgg()">
      <span class="easter-paw">🐾</span>
      <span class="easter-label">发现隐藏彩蛋？</span>
    </div>
  </div>

  <!-- ==================== 子页面：保健品小队 ==================== -->
  <div id="page-supplement" class="sub-page" style="display:none;">
    <div class="sub-page-header">
      <div class="sub-page-header-row">
        <button class="btn-back-text" onclick="navigateTo('home')">← 返回首页</button>
        <span class="sub-page-title">🛡️ 保健品小队</span>
        <div class="today-avatar-sm" id="greetingAvatarSub">🐶</div>
      </div>
    </div>
    <div class="card" id="cardSupplements">
      <div id="supplementsArea" style="margin-top:8px;">
        <div class="skeleton" style="width:50%;"></div>
      </div>
    </div>

    <!-- 隐藏彩蛋入口 -->
    <div class="easter-egg-entry" id="easterEggEntry" onclick="openEasterEgg()">
      <span class="easter-paw">🐾</span>
      <span class="easter-label">发现隐藏彩蛋？</span>
    </div>
  </div>

  <!-- ==================== 子页面：体重管理 ==================== -->
  <div id="page-weight" class="sub-page" style="display:none;">
    <div class="sub-page-header">
      <div class="sub-page-header-row">
        <button class="btn-back-text" onclick="navigateTo('home')">← 返回首页</button>
        <span class="sub-page-title">⚖️ 体重管理</span>
        <div class="today-avatar-sm" id="greetingAvatarSub">🐶</div>
      </div>
    </div>

    <!-- 体重趋势图 -->
    <div class="card" id="cardWeightChart">
      <div class="card-title">📈 体重趋势</div>
      <div class="weight-chart-container" id="weightChartContainer">
        <div class="skeleton" style="width:60%;"></div>
      </div>
      <div class="weight-stats-row" id="weightStatsRow" style="display:none;"></div>
    </div>

    <!-- 记录体重 -->
    <div class="card" id="cardWeightRecord">
      <div class="card-title">📝 记录体重</div>
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
        <input id="wlWeight" placeholder="体重，如：12.5kg" style="flex:2;min-width:120px;padding:10px 12px;font-size:0.95em;" />
        <input type="text" id="wlDate" readonly placeholder="选择日期" style="flex:1;min-width:120px;padding:10px 12px;font-size:0.95em;cursor:pointer;background:#FFFDF7;border:1px solid var(--border);border-radius:8px;" onclick="openDatePicker('wlDate')" />
        <button class="btn btn-primary" id="btnAddWeight" style="flex:0 0 auto;">+ 记录体重</button>
      </div>
      <div class="weight-frequency-hint" id="weightFreqHint"></div>
    </div>

    <!-- BCS 体况评分引导 -->
    <div class="card" id="cardBCS">
      <div class="card-title">🤚 体况评分（BCS）</div>
      <div class="bcs-guide">
        <div class="bcs-intro">用 1-9 分评估狗狗体态。轻轻触摸肋骨来判断——这是比体重数字更科学的胖瘦标准。</div>
        <div class="bcs-scale">
          <div class="bcs-item"><span class="bcs-dot too-thin"></span><span>1-3 偏瘦</span><span class="bcs-desc">肋骨明显可见</span></div>
          <div class="bcs-item"><span class="bcs-dot ideal"></span><span>4-5 理想</span><span class="bcs-desc">肋骨可摸到，覆薄脂肪</span></div>
          <div class="bcs-item"><span class="bcs-dot overweight"></span><span>6-7 偏胖</span><span class="bcs-desc">肋骨难摸到，腰不明显</span></div>
          <div class="bcs-item"><span class="bcs-dot obese"></span><span>8-9 肥胖</span><span class="bcs-desc">肋骨摸不到，腹部膨大</span></div>
        </div>
      </div>
    </div>

    <!-- 历史记录 -->
    <div class="card" id="cardWeightHistory">
      <div class="card-title">📋 历史记录</div>
      <div id="weightLogList"></div>
    </div>
  </div>

  <!-- ==================== 子页面：健康提醒 ==================== -->
  <div id="page-reminders" class="sub-page" style="display:none;">
    <div class="sub-page-header">
      <div class="sub-page-header-row">
        <button class="btn-back-text" onclick="navigateTo('home')">← 返回首页</button>
        <span class="sub-page-title">📅 健康提醒</span>
        <div class="today-avatar-sm" id="greetingAvatarSub">🐶</div>
      </div>
    </div>
    <div class="reminders-intro">📋 根据健康记录自动整理的照护提醒，关键节点不错过</div>
    <div id="remindersArea">
      <div class="skeleton" style="width:60%;"></div>
      <div class="skeleton" style="width:40%;"></div>
    </div>
  </div>

</div>

<!-- ===== 日期选择器弹窗 ===== -->
<div class="modal-overlay" id="datePickerOverlay" style="display:none;">
  <div class="date-picker-container" id="datePickerContainer">
    <!-- 第一层：单月日历 -->
    <div class="dp-layer" id="dpLayerMonth">
      <div class="dp-header">
        <button class="dp-nav-arrow" id="dpPrevMonth" onclick="dpNavMonth(-1)">&#9664;</button>
        <span class="dp-title" id="dpMonthTitle" onclick="dpSwitchToYear()">2026年6月</span>
        <button class="dp-nav-arrow" id="dpNextMonth" onclick="dpNavMonth(1)">&#9654;</button>
      </div>
      <div class="dp-weekdays">
        <span>一</span><span>二</span><span>三</span><span>四</span><span>五</span><span>六</span><span>日</span>
      </div>
      <div class="dp-days-grid" id="dpDaysGrid"></div>
      <div class="dp-footer">
        <button class="btn btn-text btn-sm" onclick="dpSelectToday()">今天</button>
        <button class="btn btn-primary btn-sm" onclick="dpConfirm()">确认</button>
      </div>
    </div>
    <!-- 第二层：年份总览 -->
    <div class="dp-layer" id="dpLayerYear" style="display:none;">
      <div class="dp-header">
        <button class="dp-nav-arrow" id="dpPrevYear" onclick="dpNavYear(-1)">&#9664;</button>
        <span class="dp-title" id="dpYearTitle">2026年</span>
        <button class="dp-nav-arrow" id="dpNextYear" onclick="dpNavYear(1)">&#9654;</button>
      </div>
      <div class="dp-months-grid" id="dpMonthsGrid"></div>
    </div>
  </div>
</div>

<!-- ===== 彩蛋测验弹窗 ===== -->
<div class="modal-overlay" id="easterEggModal" style="display:none;">
  <div class="modal-card quiz-modal-card">
    <div class="modal-header">
      <div class="modal-logo">🥚</div>
      <h2>发现隐藏彩蛋！</h2>
      <button class="modal-close-btn" onclick="closeEasterEgg()">✕</button>
    </div>
    <div class="modal-body" id="easterQuizBody">
      <div class="quiz-question" id="eqQuestion">加载中...</div>
      <div id="eqOptions"></div>
      <div class="quiz-feedback" id="eqFeedback" style="display:none;"></div>
    </div>
  </div>
</div>

<!-- ===== 编辑档案弹窗 ===== -->
<div class="modal-overlay" id="editModalOverlay" style="display:none;">
  <div class="modal-card">
    <div class="modal-header">
      <div class="modal-logo" style="font-size:1.8em;">✏️</div>
      <h2 style="font-size:1.15em;color:var(--brown);">主人，帮我更新一下最新的信息吧～</h2>
    </div>
    <div class="modal-body">
      <div class="form-row">
        <div class="form-col"><label>我的名字 <span class="required">*</span></label><input id="eName" placeholder="汪！我的名字是…" maxlength="64" /></div>
        <div class="form-col"><label>我的品种 <span class="required">*</span></label>
          <select id="eBreed"><option value="金毛">金毛</option><option value="拉布拉多">拉布拉多</option><option value="柯基">柯基</option><option value="贵宾">贵宾</option><option value="豆柴">豆柴</option><option value="混血">混血</option><option value="其他">其他</option></select>
        </div>
      </div>
      <div class="form-row">
        <div class="form-col"><label>我的生日 <span class="required">*</span></label>
          <input type="text" id="eBirthday" readonly placeholder="点击选择生日" style="width:100%;padding:10px 12px;font-size:0.95em;cursor:pointer;background:#FFFDF7;border:1px solid var(--border);border-radius:8px;" onclick="openDatePicker('eBirthday')" />
          </div>
        </div>
      </div>
      <div class="form-row">
        <div class="form-col"><label>我的体重</label><input id="eWeight" placeholder="例：28kg" /></div>
        <div class="form-col"><label>我的性别</label>
          <select id="eGender"><option value="">保密</option><option value="male">公</option><option value="female">母</option></select>
        </div>
      </div>
      <div class="form-row">
        <div class="form-col"><label>绝育情况</label>
          <select id="eNeutered"><option value="未知">未知</option><option value="是">是</option><option value="否">否</option></select>
        </div>
        <div class="form-col"><label>过敏源</label><input id="eAllergies" placeholder="逗号分隔，如：鸡肉,谷物" /></div>
      </div>
      <div class="form-row">
        <div class="form-col"><label>已知健康状况 <span style="color:var(--muted);font-weight:400;">（可选）</span></label><input id="eDiseases" placeholder="如：慢性肾病、胰腺炎、心脏病等" /></div>
        <div class="form-col"><label>到家日期 <span style="color:var(--muted);font-weight:400;">（可选）</span></label><input type="text" id="eHomeDate" readonly placeholder="点击选择日期" style="width:100%;padding:10px 12px;font-size:0.95em;cursor:pointer;background:#FFFDF7;border:1px solid var(--border);border-radius:8px;" onclick="openDatePicker('eHomeDate')" /></div>
      </div>
      <div class="form-row">
        <div class="form-col"><label>我的照片 <span style="color:var(--muted);font-weight:400;">（可选）</span></label>
          <input type="file" id="ePhoto" accept="image/jpeg,image/png" />
        </div>
      </div>
    </div>
    <div class="modal-footer" style="display:flex;gap:8px;justify-content:flex-end;">
      <button class="btn btn-outline" id="btnEditCancel">取消</button>
      <button class="btn btn-primary" id="btnEditSave">💾 保存更新</button>
    </div>
  </div>
</div>

<!-- ===== 高风险紧急警告弹窗 ===== -->
<div class="modal-overlay" id="riskWarningOverlay" style="display:none;">
  <div class="modal-card" style="max-width:480px;border:2px solid var(--red);">
    <div class="modal-header">
      <div style="font-size:2.5em;">🚨</div>
      <h2 style="color:var(--red);">紧急提醒：请立即联系兽医</h2>
    </div>
    <div class="modal-body" style="font-size:0.92em;line-height:1.8;color:var(--brown);">
      <p>您记录的症状（包含"<strong id="riskMatchedKeyword" style="color:var(--red);"></strong>"）可能表明宠物存在严重的健康风险，甚至危及生命。</p>
      <p>本应用无法诊断或治疗疾病。请立即采取以下行动：</p>
      <ol style="padding-left:18px;">
        <li>立即联系您的兽医或最近的24小时宠物医院</li>
        <li>不要等待观察，不要自行用药</li>
        <li>本应用今天的饮食与保健品建议已自动暂停，直到您确认宠物状况稳定</li>
      </ol>
    </div>
    <div class="modal-footer">
      <button class="btn btn-danger btn-lg" id="btnRiskConfirm">我知道了，已联系兽医</button>
    </div>
  </div>
</div>

<!-- ===== 兽医摘要卡片弹窗 ===== -->
<div class="vet-summary-overlay" id="vetSummaryOverlay" style="display:none;">
  <div class="vet-summary-card" id="vetSummaryCard">
    <div class="vet-card-header">
      <div class="vet-badge">📋 兽医摘要</div>
      <h3 id="vetTitle"></h3>
      <div class="vet-date" id="vetDate"></div>
    </div>
    <div class="vet-card-body">
      <div class="vet-info-row" id="vetInfoRow"></div>
      <div class="vet-section-title">⚠️ 报告症状</div>
      <div class="vet-symptom-list" id="vetSymptoms"></div>
      <div class="vet-risk-banner" id="vetRiskBanner"></div>
      <div class="vet-section-title">💬 分项分析与建议</div>
      <div id="vetAdviceList"></div>
    </div>
    <div class="vet-card-footer">
      <button class="vet-btn vet-btn-close" onclick="$('vetSummaryOverlay').style.display='none'">关闭</button>
      <button class="vet-btn vet-btn-screen" id="btnVetScreenshot" onclick="captureVetCard()">📸 保存截图给兽医</button>
    </div>
  </div>
</div>

<!-- ===== 任务确认弹窗 ===== -->
<div class="modal-overlay" id="taskConfirmOverlay" style="display:none;" onclick="if(event.target===this)closeTaskConfirm()">
  <div class="task-confirm-card">
    <div class="task-confirm-icon">🐾</div>
    <div class="task-confirm-task" id="taskConfirmTask"></div>
    <div class="task-confirm-question">完成了吗？我会帮你记录下来的！</div>
    <div class="task-confirm-reward">✨ 完成奖励：<b>+2 爪印</b>🐾</div>
    <div class="task-confirm-actions">
      <button class="btn task-confirm-cancel" onclick="closeTaskConfirm()">还没呢</button>
      <button class="btn task-confirm-ok" id="btnTaskConfirmOk" onclick="confirmAndCompleteTask()">✅ 完成啦！</button>
    </div>
  </div>
</div>

<!-- ===== 百变秀兑换确认弹窗 ===== -->
<!-- ===== 爪印历史弹窗 ===== -->
<div class="modal-overlay" id="pawHistoryOverlay" style="display:none;" onclick="if(event.target===this)closePawHistory()">
  <div class="paw-history-card">
    <div class="paw-history-header">
      <span class="paw-history-title">🐾 爪印获取记录</span>
      <button class="paw-history-close" onclick="closePawHistory()">✕</button>
    </div>
    <div class="paw-history-list" id="pawHistoryList">
      <div class="paw-history-empty">加载中...</div>
    </div>
  </div>
</div>

<div class="app-footer">
  <div style="max-width:720px;margin:0 auto;font-size:0.78em;color:var(--muted);line-height:1.6;padding:8px 14px;background:#FFFBF5;border-radius:8px;border:1px solid var(--border);">
    ⚠️ 免责声明：本应用提供的所有内容（包括饮食建议、保健品提醒、事件提醒等）仅供参考和教育目的，不能替代执业兽医的专业诊断、治疗或建议。如您的宠物出现任何健康问题或紧急情况，请立即联系持证兽医。
  </div>
  <div style="margin-top:8px;">© PawLife · 汪星人出品 · 用爱守护每一只狗狗 🐾 <span style="opacity:0.4;font-size:0.75em;">v2505.3</span></div>
</div>

</div><!-- /#mainContent -->

<script>
// ============================================================
// PawLife 前端 JS
// ============================================================

const $ = id => document.getElementById(id);

// ---- 高危症状词库（前端匹配，与服务端保持一致） ----
const HIGH_RISK_SYMPTOMS = [
  "反复呕吐", "持续呕吐", "吐血", "呕血", "腹泻带血", "便血", "黑便",
  "抽搐", "癫痫", "昏厥", "晕倒", "瘫痪", "呼吸困难", "呼吸急促",
  "极度萎靡", "意识丧失", "瞳孔散大", "严重过敏", "面部肿胀",
  "车祸", "中毒", "误食巧克力", "误食洋葱", "误食葡萄", "误食木糖醇",
  "误食老鼠药", "被蛇咬", "严重外伤", "大出血", "骨折", "烫伤",
];

// 检查文本是否包含高危症状关键词，返回命中的关键词（null 表示通过）
function checkHighRisk(text) {
  for (const kw of HIGH_RISK_SYMPTOMS) {
    if (text.indexOf(kw) !== -1) return kw;
  }
  return null;
}

// ---- 工具函数 ----
function genIdemKey() {
  // 幂等键：时间戳 + 随机串
  const t = Date.now().toString(36);
  const r = Math.random().toString(36).substring(2, 10);
  return `idem_${t}_${r}`;
}

function showToast(msg, isError) {
  const old = document.querySelector('.toast');
  if (old) old.remove();
  const el = document.createElement('div');
  el.className = 'toast';
  el.textContent = msg;
  if (isError) el.style.background = 'var(--red)';
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 3000);
}

async function api(path, opts) {
  try {
    const r = await fetch(path, opts);
    const data = await r.json();
    if (!r.ok) {
      throw new Error(data.message || data.detail || '汪汪，信号被狗吃了～');
    }
    return data;
  } catch (e) {
    if (e.message && e.message.includes('汪汪')) throw e;
    if (e.name === 'TypeError' && e.message.includes('fetch')) {
      throw new Error('汪汪，信号被狗吃了，点我重试～');
    }
    throw e;
  }
}

// ---- 每日生存指南数据（按季节/品种/类别标记） ----
const DAILY_TIPS = [
  // ===== 食品安全（全年通用）=====
  { text: "今天别喂我吃葡萄哦，一颗就可能让我肾受伤，葡萄干也一样危险！", tags: ["food"] },
  { text: "巧克力对我们狗狗来说是毒药，越纯越危险，主人一定要收好～", tags: ["food"] },
  { text: "洋葱、大蒜、韭菜这些东西会破坏我的红血球，千万别混在我的饭里。", tags: ["food"] },
  { text: "木糖醇（无糖口香糖里常有）对我超级毒，一点点就可能让我低血糖甚至肝衰竭。", tags: ["food"] },
  { text: "夏威夷果我也不行，吃了会发抖、发烧、走不动路。", tags: ["food"] },
  { text: "牛油果含有persin，对我不好，别给我尝鲜哦。", tags: ["food"] },
  { text: "咖啡和茶里面的咖啡因会让我心跳过快、抽搐，杯子要放高高的。", tags: ["food"] },
  { text: "生面团在我肚子里会发酵膨胀，还会产生酒精，非常危险！", tags: ["food"] },
  { text: "煮熟的鸡骨头会裂成尖刺，千万别喂我，生骨头也要在主人监督下吃～", tags: ["food"] },
  { text: "过多的盐分对我们狗狗肾脏负担很大，人吃的菜不要分给我哦～", tags: ["food"] },

  // ===== 日常护理（全年通用）=====
  { text: "每天出门散步时让我闻一闻世界，闻闻是狗狗的社交网络哦～", tags: ["care"] },
  { text: "我摇尾巴不一定是开心，也可能是紧张，主人要学会读懂我的身体语言。", tags: ["care"] },
  { text: "给我一个固定的作息吧，定时吃饭、散步、睡觉会让我很有安全感。", tags: ["care"] },
  { text: "剪指甲不要剪到粉红色的部分，那里有血管和神经，会疼也会出血。", tags: ["care"] },
  { text: "每天帮我刷刷牙，牙结石会导致心脏病和肾病，小牙刷大健康！", tags: ["care"] },
  { text: "训练我的时候用零食奖励比惩罚有效一万倍，我超好收买的～", tags: ["care"] },
  { text: "我吃便便有时候是因为缺乏微量元素或者消化不好，不是变态行为啦。", tags: ["care"] },
  { text: "我舔脚掌太频繁可能是过敏或者焦虑，主人帮我查查原因。", tags: ["care"] },
  { text: "给我准备一些咬胶和玩具，换牙期的小狗和无聊的大狗都需要发泄。", tags: ["care"] },
  { text: "每周帮我清洁一次耳朵，金毛、拉布拉多等垂耳狗狗尤其容易耳道感染～", tags: ["care"] },
  { text: "定期帮我梳毛不仅能减少掉毛，还能促进血液循环，是我们之间的亲密时光～", tags: ["care"] },
  { text: "出门一定要牵绳！不是我不听话，是外面的世界诱惑太多啦，绳绳是我的生命线～", tags: ["care"] },

  // ===== 夏季专属（6-8月）=====
  { text: "夏天千万别把我留在车里，即使开了窗，车内温度几分钟就能致命。", tags: ["summer"] },
  { text: "柏油路面夏天温度能到60度以上，主人用手背贴地试试，烫的话我也不要光脚走～", tags: ["summer"] },
  { text: "夏天带水碗出门，我散热主要靠喘气和脚垫，随时补水超重要！", tags: ["summer"] },
  { text: "冰水不要直接给我喝，太冰的水可能引起胃痉挛，常温凉白开就很好～", tags: ["summer"] },
  { text: "游泳是夏天最好的运动！但要穿救生衣，游完用清水冲洗，别让池水或海水刺激我的皮肤～", tags: ["summer"] },
  { text: "夏天草丛里蜱虫超多，每次散步回来帮我全身摸一遍，重点检查耳朵、腋下、趾间～", tags: ["summer"] },
  { text: "中午最热的时段不要带我出门，清晨和傍晚散步才是对我们的关节和脚垫最好的～", tags: ["summer"] },
  { text: "夏天我会掉更多毛来换夏装，这是正常的！多梳毛帮我去掉死毛，也会凉快很多～", tags: ["summer"] },

  // ===== 冬季专属（12-2月）=====
  { text: "冬天短毛狗狗出门可以穿件小衣服，但不要穿太紧，回家记得脱掉防潮湿～", tags: ["winter"] },
  { text: "下雪天出门后记得帮我擦脚！融雪剂会刺激脚垫，雪块夹在趾间也超级疼～", tags: ["winter"] },
  { text: "冬天家里开暖气空气干燥，我可能会皮肤发痒，加湿器能帮大忙～", tags: ["winter"] },
  { text: "冬天我消耗更多热量保暖，可以稍微加一点狗粮，但别过量导致肥胖哦～", tags: ["winter"] },
  { text: "不要因为我怕冷就让我整天窝着不动！适当的室内游戏和运动对身心健康都重要～", tags: ["winter"] },

  // ===== 春季专属（3-5月）=====
  { text: "春天花粉飘散，我可能会过敏打喷嚏、眼睛发红、皮肤痒，主人帮我留意一下～", tags: ["spring"] },
  { text: "春天是跳蚤和蜱虫复苏的季节，记得每月按时做好体外驱虫～", tags: ["spring"] },
  { text: "春天换毛季来啦！每天多花5分钟帮我梳毛，不仅家里少飞毛，我也更舒服～", tags: ["spring"] },
  { text: "春天户外活动增多，别忘了检查我的疫苗有效期，出去玩才有保障～", tags: ["spring"] },

  // ===== 秋季专属（9-11月）=====
  { text: "秋天也在换毛，为了长冬毛做准备～梳毛频率别减，帮我把旧毛清理干净！", tags: ["autumn"] },
  { text: "秋天气温忽冷忽热，关节不好的狗狗（尤其是老年犬和金毛、柯基等品种）要多注意保暖～", tags: ["autumn"] },
  { text: "秋天是贴秋膘的季节，但主人别让我吃太多！肥胖会加重关节负担和心脏病风险～", tags: ["autumn"] },

  // ===== 品种专属 =====
  { text: "我们金毛双层被毛需要定期梳理，耳朵也要每周检查和清洁，不然容易藏污纳垢发炎～", tags: ["金毛"] },
  { text: "金毛和拉布拉多都容易髋关节发育不良，控制体重是关键！过重会加速关节退化～", tags: ["金毛", "拉布拉多"] },
  { text: "拉布拉多是著名贪吃鬼，但也是最容易吃出胰腺炎的品种！高油高脂的人食千万别喂我～", tags: ["拉布拉多"] },
  { text: "柯基的小短腿很可爱，但上下楼梯和跳沙发会严重损伤我们的脊椎！主人给我准备个小斜坡吧～", tags: ["柯基"] },
  { text: "柯基掉毛量非常惊人，每天梳毛和补充Omega-3对减少掉毛有帮助哦～", tags: ["柯基"] },
  { text: "贵宾的卷毛虽然好看但不打理容易打结，6-8周美容一次，在家也要天天梳～", tags: ["贵宾"] },
  { text: "贵宾皮肤敏感，换低敏狗粮、用温和沐浴露能减少瘙痒和皮屑～", tags: ["贵宾"] },
  { text: "豆柴虽然是小型犬但精力充沛，每天至少30分钟运动加脑力游戏，否则可能会拆家哦～", tags: ["豆柴"] },
  { text: "豆柴换毛期掉毛量不比大型犬少！用底绒梳把底层绒毛梳掉能减少家里到处是毛～", tags: ["豆柴"] },
  { text: "混血狗狗通常比纯种更健康（杂交优势！），但还是要定期体检，每个汪星人都是独一无二的～", tags: ["混血", "其他"] },

  // ===== 行为与训练 =====
  { text: "我害怕打雷和鞭炮声的时候，请让我躲到我觉得安全的地方，不要强行拉我出来，安静陪着我就好～", tags: ["behavior"] },
  { text: "社会化训练从小开始！3-16周是黄金期，让我多见不同的人、狗狗和环境，长大后会更自信从容～", tags: ["behavior"] },
  { text: "如果我不停追尾巴、舔同一个地方、或者转圈圈停不下来，可能是焦虑或强迫行为，主人帮我找找原因～", tags: ["behavior"] },
  { text: "给我一个专属的安全角落（一个垫子或小窝），当我感到压力时可以躲进去，这让我有安全感～", tags: ["behavior"] },
  { text: "分离焦虑不是我在'作'，是真的害怕一个人。从短时间开始练习，留一件有你味道的旧衣服陪着我～", tags: ["behavior"] },

  // ===== 健康监测 =====
  { text: "正常狗狗体温在38-39.2度之间，鼻子湿凉不是判断健康的标准，精神状态和食欲才是～", tags: ["health"] },
  { text: "每年至少一次全面体检，7岁以上的狗狗建议半年一次，早期发现问题治疗效果好多啦！", tags: ["health"] },
  { text: "刷牙是最好的牙周病预防！口臭不是正常的，可能是牙结石或口腔感染的信号～", tags: ["health"] },
  { text: "观察我的便便很重要——颜色、形状、次数变化都可能反映健康问题，主人帮我多看一眼～", tags: ["health"] },
  { text: "疫苗接种后24小时内我可能会犯困、食欲略差、注射部位有点肿，这是正常的，但如果脸肿或呼吸困难要立刻就医！", tags: ["health"] },
];

let lastTipIndex = -1;

function getRandomTip() {
  let idx;
  do {
    idx = Math.floor(Math.random() * DAILY_TIPS.length);
  } while (idx === lastTipIndex && DAILY_TIPS.length > 1);
  lastTipIndex = idx;
  return DAILY_TIPS[idx].text;
}

function getSmartTip(breed, month) {
  // 根据当前月份确定季节标签
  let seasonTag = null;
  if (month >= 6 && month <= 8) seasonTag = 'summer';
  else if (month >= 12 || month <= 2) seasonTag = 'winter';
  else if (month >= 3 && month <= 5) seasonTag = 'spring';
  else seasonTag = 'autumn';

  // 三级匹配：品种 > 季节 > 通用
  let pool = DAILY_TIPS.filter(t => t.tags.includes(breed));
  if (pool.length < 3) {
    const seasonal = DAILY_TIPS.filter(t => t.tags.includes(seasonTag) && !pool.includes(t));
    pool = pool.concat(seasonal);
  }
  if (pool.length < 5) {
    const general = DAILY_TIPS.filter(t =>
      (t.tags.includes('care') || t.tags.includes('health') || t.tags.includes('food') || t.tags.includes('behavior'))
      && !pool.includes(t)
    );
    pool = pool.concat(general);
  }
  // 兜底：全部贴士
  if (pool.length === 0) pool = DAILY_TIPS;

  // 避免与上一条重复
  let idx;
  let attempts = 0;
  do {
    idx = Math.floor(Math.random() * pool.length);
    attempts++;
  } while (attempts < 20 && DAILY_TIPS.indexOf(pool[idx]) === lastTipIndex && pool.length > 1);
  lastTipIndex = DAILY_TIPS.indexOf(pool[idx]);
  return pool[idx].text;
}

// ---- 个性化今日汪汪 ----
function getPersonalizedMessage(latestEvent, dogName) {
  if (!latestEvent) return null;
  const eventDate = new Date(latestEvent.date);
  const today = new Date();
  const daysSince = Math.floor((today - eventDate) / (1000 * 60 * 60 * 24));
  if (daysSince < 0) return null; // 未来日期异常

  const type = latestEvent.type;
  let detail = {};
  try {
    detail = typeof latestEvent.detail === 'string' ? JSON.parse(latestEvent.detail) : (latestEvent.detail || {});
  } catch (e) {}

  if (type === '疫苗') {
    const doseText = detail.dose ? `第${detail.dose}针` : '疫苗';
    if (daysSince <= 7) return `汪汪！${daysSince}天前我刚打完${doseText}，现在身体里有好多小卫士在站岗，感觉超安心的～谢谢主人保护我！`;
    if (daysSince <= 365) return `距离我上次打${doseText}已经过去${daysSince}天了，主人记得查看一下下一次该什么时候加强哦，我想一直做一只健康有防护的好狗狗～`;
    return `我上次打${doseText}已经是${daysSince}天前了，保护力可能在悄悄下降……主人，有空带我去见兽医爷爷吧～`;
  }

  if (type === '驱虫') {
    const brandText = detail.brand ? `（${detail.brand}）` : '';
    if (daysSince <= 7) return `${daysSince === 0 ? '今天' : daysSince + '天前'}我刚吃完驱虫药${brandText}，现在肚子里干干净净的，吃嘛嘛香～谢谢主人帮我赶走那些讨厌的小虫子！`;
    if (daysSince <= 90) return `距离上次驱虫已经${daysSince}天了${brandText}，我现在状态还不错，主人继续保持好卫生习惯哦～`;
    return `已经${daysSince}天没驱虫了，小虫子们可能正在我肚子里偷偷开派对……主人，快帮我安排一下驱虫药吧！`;
  }

  if (type === '发情') {
    if (daysSince <= 30) return `${daysSince}天前主人帮我记录了发情期，我的成长印记又多了一笔～主人这么细心，我好幸福呀！`;
    return `距离上次记录发情已经${daysSince}天了，主人对我的生理周期了如指掌，真是个靠谱的铲屎官～`;
  }

  if (type === '异常行为') {
    const symptoms = detail.symptoms || [];
    const sympText = symptoms.length > 0 ? `「${symptoms.join('、')}」` : '';
    if (daysSince <= 7) return `${daysSince === 0 ? '今天' : daysSince + '天前'}我有点小状况${sympText}，主人这几天多观察我一下，希望能很快好起来～`;
    if (daysSince <= 30) return `上次我的小状况${sympText}已经过去${daysSince}天了，现在应该恢复得差不多了吧～谢谢主人那段时间的照顾！`;
    return `距离上次不舒服${sympText}已经${daysSince}天了，回头看都是成长的小插曲，谢谢主人一直陪在我身边～`;
  }

  if (type === '洗澡澡') {
    if (daysSince <= 3) { const title = (_cachedDog && _cachedDog.gender === 'male') ? '小王子' : '小公主'; return `${daysSince === 0 ? '今天' : daysSince + '天前'}主人刚给我洗过澡，我现在毛毛蓬蓬的、香喷喷的，走在路上都是${title}的味道～🛁`; }
    if (daysSince <= 14) return `距离上次洗澡已经${daysSince}天了，我还算干净啦，不过主人可以开始帮我留意下次洗澡的时间哦～`;
    return `我都${daysSince}天没洗澡啦，身上有点小狗味儿了！主人有空带我去洗香香吧～🛁`;
  }

  return null;
}

// ---- 汪星人冷知识池 ----
const DOG_KNOWLEDGE = [
  '狗狗的鼻子纹路和人类指纹一样，每只狗都是独一无二的哦～',
  '狗狗最多能听懂250个单词和手势，相当于2岁小孩的理解力！',
  '狗狗喝水时会把舌头卷成小勺状，每秒可以舀水4次～',
  '比格犬的耳朵非常灵敏，能分辨出百万分之一浓度的气味——相当于一滴香水放进一个游泳池里！',
  '狗狗不是色盲哦，它们能看到蓝色和黄色，只是分辨不出红色和绿色～',
  '狗狗的嗅觉比人类强1万到10万倍，大脑中负责分析气味的区域是人类的40倍大！',
  '你的狗狗真的能感受到你的情绪——它们会读取你的面部表情和语调变化，然后调整自己的行为～',
  '狗狗有三个眼睑：上眼睑、下眼睑，还有一个藏在眼角内侧的第三眼睑（瞬膜）！',
  '拉布拉多寻回犬连续30年蝉联全球最受欢迎犬种第一名～',
  '狗狗也会做梦！小型犬比大型犬做梦更频繁，幼犬和老年犬做梦也比成年犬多～',
  '狗的耳朵有18块肌肉独立控制，所以它们可以像雷达一样灵活转动耳朵追踪声音！',
  '刚出生的幼犬既看不见也听不见，眼睛和耳道要到2周左右才会打开～',
  '狗狗的体温比人类高，正常体温在38°C到39.2°C之间，所以不要用人类标准判断它们是否发烧哦～',
  '边境牧羊犬被认为是地球上最聪明的犬种，可以记住超过1000个玩具的名字！',
  '狗狗的胡须不仅仅是装饰，它们能感知气流变化和物体远近，帮助狗狗在黑暗中导航～',
  '狗的平均寿命在10-13年左右，小型犬通常比大型犬活得长～',
  '你的狗狗歪头看你的时候，可能是在努力理解你在说什么，也可能是在调整角度看得更清楚哦！',
  '狗狗的爪垫上有汗腺，它们主要通过脚底和喘气来调节体温～',
  '舔人是狗狗表达爱意的方式之一，舔你等同于给你一个毛茸茸的湿吻！',
  '狗狗每天需要12-14小时的睡眠，幼犬则需要睡到18-20小时～',
  '松狮犬的舌头是蓝黑色的，而沙皮狗的舌头也是深色的——这在其他犬种中非常罕见！',
  '狗狗能探测到人类情绪变化时释放的化学信号，所以它们会在你难过时过来安慰你～',
  '灵缇犬是跑得最快的犬种，时速可达72公里，比很多汽车在城市里的速度还快！',
  '狗狗尾巴向右摇表示开心，向左摇表示警觉——这是大脑半球分工决定的哦～',
];

// ---- 紧急提醒 / 今日汪汪 ----
async function loadToday() {
  // 新版本中提醒和待办事项已整合进 updateTodayDashboard()
  // 此函数保留兼容性，调用新函数
  try {
    const data = await api('/api/health_check');
    if (!data.has_dog) return;
    updateBadges(data);
  } catch (e) {}
}

// ---- 从提醒快捷跳转到记录 ----
let _editingEventId = null;  // 当前正在编辑的事件ID

function editEvent(eventId) {
  const ev = _allEvents.find(e => e.id === eventId);
  if (!ev) { showToast('找不到这条记录，主人刷新页面试试～', true); return; }

  // 填入表单
  $('fEType').value = ev.type;
  renderExtraFields();

  // 设置日期
  $('eventDate').value = ev.date;

  // 填入扩展字段
  let detail = {};
  try {
    detail = typeof ev.detail === 'string' ? JSON.parse(ev.detail) : (ev.detail || {});
  } catch (x) { detail = {}; }

  setTimeout(() => {
    if (ev.type === '疫苗') {
      if ($('efDose')) $('efDose').value = detail.dose || '';
      if ($('efBrand')) $('efBrand').value = detail.brand || '';
    } else if (ev.type === '驱虫') {
      if ($('efBrand')) $('efBrand').value = detail.brand || '';
      if ($('efDewormType')) $('efDewormType').value = detail.deworm_type || '体内';
    } else if (ev.type === '发情') {
      if ($('efNote')) $('efNote').value = detail.note || '';
    } else if (ev.type === '异常行为') {
      const symptoms = detail.symptoms || [];
      document.querySelectorAll('#symptomGroup input[type="checkbox"]').forEach(cb => {
        cb.checked = symptoms.includes(cb.value);
      });
    }
  }, 100);

  // 修改提交按钮
  _editingEventId = eventId;
  const btn = $('btnSubmitEvent');
  btn.textContent = '✏️ 更新记录';
  btn.style.background = '#5A3A2A';
  $('eventSubtitle').innerHTML = '正在编辑 <strong style="color:var(--orange);">' + ev.type + '</strong> 记录（' + ev.date + '）— <a href="javascript:cancelEdit()" style="color:var(--muted);">取消编辑</a>';

  // 滚动到表单
  $('cardEvent').scrollIntoView({ behavior: 'smooth', block: 'center' });
  $('cardEvent').style.transition = 'box-shadow 0.3s';
  $('cardEvent').style.boxShadow = '0 0 0 4px rgba(90,58,42,0.3)';
  setTimeout(() => { $('cardEvent').style.boxShadow = ''; }, 1500);
}

function cancelEdit() {
  _editingEventId = null;
  $('btnSubmitEvent').textContent = '🐾 提交记录';
  $('btnSubmitEvent').style.background = '';
  $('eventDate').value = new Date().toISOString().slice(0, 10);
  renderExtraFields();
  const dogName = (_cachedDog && _cachedDog.name) ? _cachedDog.name : '汪星人';
  $('eventSubtitle').innerHTML = '帮 <strong style="color:var(--orange);">' + escHtml(dogName) + '</strong> 记录疫苗、驱虫、发情或异常行为，我会立刻给你反馈';
}

async function deleteEvent(eventId) {
  if (!confirm('确定要删除这条大事记吗？\n\n虽然记录不复杂，但每一段回忆都很珍贵哦～确认删除后不可恢复。')) return;

  try {
    const r = await api('/api/event/' + eventId, { method: 'DELETE' });
    showToast(r.message);
    loadTimeline();
    loadToday();
    // 如果正在编辑这条，取消编辑
    if (_editingEventId === eventId) cancelEdit();
  } catch (e) {
    showToast('删除失败：' + (e.message || '未知错误'), true);
  }
}

function quickRecord(type) {
  $('fEType').value = type;
  renderExtraFields();
  navigateTo('record');
  // 闪烁高亮提示
  setTimeout(() => {
    $('cardEvent').style.transition = 'box-shadow 0.3s';
    $('cardEvent').style.boxShadow = '0 0 0 4px rgba(255,138,0,0.3)';
    setTimeout(() => { $('cardEvent').style.boxShadow = ''; }, 1500);
  }, 300);
  showToast('汪汪！事件类型已帮你选好了，填上日期就能记录～');
}

// ---- 兽医摘要卡片 ----
async function showVetSummary(eventId) {
  const overlay = $('vetSummaryOverlay');
  overlay.style.display = 'flex';
  // 显示加载状态
  $('vetTitle').textContent = '正在生成摘要...';
  $('vetDate').textContent = '';
  $('vetInfoRow').innerHTML = '';
  $('vetSymptoms').innerHTML = '';
  $('vetRiskBanner').textContent = '';
  $('vetRiskBanner').className = 'vet-risk-banner';
  $('vetAdviceList').innerHTML = '<div class="empty-state">汪汪，正在连线我的大脑...</div>';

  try {
    const data = await api('/api/vet_summary/' + eventId);
    renderVetCard(data);
  } catch (e) {
    $('vetAdviceList').innerHTML = '<div class="empty-state">哎呀，摘要生成失败了（' + escHtml(e.message || '未知错误') + '），主人点一下重试吧～</div>';
  }
}

function renderVetCard(data) {
  const d = data.dog;
  $('vetTitle').textContent = d.name + ' · 异常行为就诊摘要';
  $('vetDate').textContent = '记录日期：' + data.event_date + '   就诊时出示给兽医';

  // 信息标签
  let infoHtml = '<span class="vet-info-tag">🐶 <strong>' + escHtml(d.breed) + '</strong></span>';
  infoHtml += '<span class="vet-info-tag">🎂 ' + escHtml(d.age) + '</span>';
  infoHtml += '<span class="vet-info-tag">⚖️ ' + escHtml(d.weight) + '</span>';
  infoHtml += '<span class="vet-info-tag">✂️ ' + (d.neutered === '是' ? '已绝育' : (d.neutered === '否' ? '未绝育' : '绝育未知')) + '</span>';
  if (d.gender) {
    infoHtml += '<span class="vet-info-tag">⚥ ' + (d.gender === 'male' ? '公' : '母') + '</span>';
  }
  if (d.allergies && d.allergies !== '无') {
    infoHtml += '<span class="vet-info-tag">⚠️ 过敏：' + escHtml(d.allergies) + '</span>';
  }
  $('vetInfoRow').innerHTML = infoHtml;

  // 症状标签
  const symptoms = data.symptoms || [];
  if (symptoms.length > 0) {
    $('vetSymptoms').innerHTML = symptoms.map(s => '<span class="vet-symptom-tag">' + escHtml(s) + '</span>').join('');
  } else {
    $('vetSymptoms').innerHTML = '<span style="color:var(--muted);font-size:0.85em;">（主人未选择具体症状）</span>';
  }

  // 风险横幅
  const riskClassMap = { '高': 'high', '中高': 'midhigh', '中': 'mid', '中低': 'low', '未分级': 'unknown' };
  $('vetRiskBanner').textContent = '综合风险评估：' + data.overall_label;
  $('vetRiskBanner').className = 'vet-risk-banner ' + (riskClassMap[data.overall_risk] || 'unknown');

  // 分析建议列表
  const analysis = data.analysis || [];
  if (analysis.length > 0) {
    const levelDotColors = { '高': '#C62828', '中高': '#E65100', '中': '#F57F17', '中低': '#2E7D32', '未分级': '#9E9E9E' };
    $('vetAdviceList').innerHTML = analysis.map(a => {
      const dotColor = levelDotColors[a.level] || '#9E9E9E';
      return '<div class="vet-advice-item"><span class="vet-level-dot" style="background:' + dotColor + ';"></span><strong>' + escHtml(a.symptom) + '</strong> · ' + a.level + '风险<br>' + escHtml(a.advice) + '</div>';
    }).join('');
  } else {
    $('vetAdviceList').innerHTML = '<div class="empty-state">汪汪，没有匹配到具体分析，但任何异常都值得重视哦～</div>';
  }

  // 滚动到顶部
  $('vetSummaryCard').scrollTop = 0;
}

function captureVetCard() {
  // 手机端引导用户截图，桌面端使用 toast 提示
  showToast('📸 请用手机截屏功能保存这张卡片，就可以直接给兽医看啦！');
  // 短暂高亮卡片边框提示
  const card = $('vetSummaryCard');
  card.style.transition = 'border-color 0.3s';
  card.style.borderColor = '#FF8A00';
  card.style.boxShadow = '0 0 0 8px rgba(255,138,0,0.2)';
  setTimeout(() => {
    card.style.borderColor = '';
    card.style.boxShadow = '';
  }, 2000);
}

// ---- 品种图标映射 ----
const BREED_ICONS = {
  '金毛': '🦮', '拉布拉多': '🐕‍🦺', '柯基': '🐕',
  '贵宾': '🐩', '豆柴': '🐕', '混血': '🐶', '其他': '🐶',
};
function getBreedIcon(breed) { return BREED_ICONS[breed] || '🐶'; }

// ---- 加载档案信息 ----
let _cachedDog = null;  // 缓存狗狗信息，供其他模块使用
let _cachedHealthData = null;  // 缓存健康检查数据

function updateTodayDashboard(dog, age) {
  const info = $('todayDashboardInfo');
  const pawEl = $('statusPawPoints');
  const streakEl = $('statusStreak');
  const pawCount = $('statusPawCount');
  const streakCount = $('statusStreakCount');
  if (info && dog) {
    info.innerHTML = '<b>' + escHtml(dog.name) + '</b> · ' + escHtml(dog.breed) + ' · ' + escHtml(age) +
      (dog.weight ? ' · ' + escHtml(dog.weight) : '') +
      '<br><span class="td-recent" id="statusRecent">正在加载…</span>' +
      '<span class="td-reminder" id="tdReminder"></span>';
  }
  if (pawEl && dog) { pawEl.style.display = ''; if (pawCount) pawCount.textContent = dog.paw_points || 0; }
  loadStatusBarStreak();
  loadStatusBarRecent();
  loadDailyCheckStatus();
  loadPendingCount();
}

async function loadStatusBarRecent() {
  try {
    const events = await api('/api/events');
    const el = $('statusRecent');
    if (!el) return;
    if (events && events.length > 0) {
      const latest = events[0];
      const typeLabels = {'疫苗':'💉 疫苗','驱虫':'💊 驱虫','发情':'💕 发情','异常行为':'⚠️ 异常','洗澡澡':'🛁 洗澡澡','每日检查':'🩺 每日检查'};
      const label = typeLabels[latest.type] || latest.type;
      el.textContent = '最近记录：' + label + ' · ' + latest.date;
    } else {
      el.textContent = '还没有健康记录，去记录第一件事吧～';
    }
  } catch (e) {
    const el = $('statusRecent');
    if (el) el.textContent = '';
  }
}

async function loadStatusBarStreak() {
  try {
    const status = await api('/api/checkin/status?pet_id=' + (_cachedDog?.id || 1));
    const streakEl = $('statusStreak');
    const streakCount = $('statusStreakCount');
    if (streakEl && status) {
      streakEl.style.display = '';
      if (streakCount) streakCount.textContent = status.streak || 0;
    }
  } catch (e) {}
}

const _dailyCheckPrompts = [
  { icon: '🩺', title: '全身快检', desc: '用 1 分钟轻轻摸摸<span class="pet-name-inline">狗狗</span>的头部、背部、四肢和腹部，确认是否有硬块、红肿、脱毛或异常发热。' },
  { icon: '🦷', title: '口腔检查', desc: '翻开<span class="pet-name-inline">狗狗</span>的嘴唇，看看牙龈颜色是否粉红、有没有牙结石或口臭加重的情况。' },
  { icon: '👂', title: '耳朵检查', desc: '闻一闻<span class="pet-name-inline">狗狗</span>的耳朵，看看有没有异味、分泌物或者频繁甩头、挠耳朵的行为。' },
  { icon: '🐾', title: '爪爪检查', desc: '检查<span class="pet-name-inline">狗狗</span>的爪垫是否干裂、指甲是否过长、趾间有没有红肿或异物。' },
  { icon: '👁️', title: '眼睛检查', desc: '看看<span class="pet-name-inline">狗狗</span>的眼睛是否清澈明亮，有没有分泌物增多、发红或者频繁眯眼的情况。' },
  { icon: '✨', title: '毛发皮肤检查', desc: '逆着毛发方向轻轻拨开<span class="pet-name-inline">狗狗</span>的毛，检查底层皮肤有没有皮屑、红点、寄生虫或异常脱毛。' },
  { icon: '👃', title: '鼻子观察', desc: '观察<span class="pet-name-inline">狗狗</span>的鼻子是否湿润（不是越湿越好哦），有没有异常分泌物或颜色变化。' },
  { icon: '💩', title: '排便观察', desc: '今天遛<span class="pet-name-inline">狗狗</span>时留意一下便便的形状、颜色和气味，是否成型、有无异物或寄生虫。' },
];

function getDailyCheckPrompt() {
  const now = new Date();
  const startOfYear = new Date(now.getFullYear(), 0, 0);
  const dayOfYear = Math.floor((now - startOfYear) / (1000 * 60 * 60 * 24));
  return _dailyCheckPrompts[dayOfYear % _dailyCheckPrompts.length];
}

async function loadDailyCheckStatus() {
  try {
    const data = await api('/api/daily_check?pet_id=' + (_cachedDog?.id || 1));
    const actions = $('dailyCheckActions');
    const completed = $('dailyCheckCompleted');
    const badge = $('dailyCheckBadge');
    const desc = $('dailyCheckDesc');
    const icon = $('dailyCheckIcon');
    if (data.done) {
      if (actions) actions.style.display = 'none';
      if (badge) badge.style.display = '';
      if (completed) {
        completed.style.display = '';
        completed.innerHTML = '✅ 今日健康检查已完成！' + (data.result === 'normal' ? '一切正常，' + (_cachedDog?.name || '狗狗') + '今天也很健康～' : '已记录异常，请注意观察。');
      }
      if (desc) desc.style.opacity = '0.6';
    } else {
      if (actions) actions.style.display = '';
      if (completed) completed.style.display = 'none';
      if (badge) badge.style.display = 'none';
      if (desc) desc.style.opacity = '1';
      // 旋转每日检查项目
      const prompt = getDailyCheckPrompt();
      if (desc && _cachedDog) {
        desc.innerHTML = prompt.desc.replace('<span class="pet-name-inline">狗狗</span>', '<span class="pet-name-inline">' + escHtml(_cachedDog.name) + '</span>');
      }
      if (icon) icon.textContent = prompt.icon;
    }
  } catch (e) {}
}

async function loadPendingCount() {
  try {
    const data = await api('/api/health_check');
    const pendingEl = $('todayPending');
    if (!pendingEl) return;
    let count = 0;
    let items = [];
    // 检查每日健康检查
    try {
      const dc = await api('/api/daily_check?pet_id=' + (_cachedDog?.id || 1));
      if (!dc.done) { count++; items.push('今日健康检查'); }
    } catch (e) {}
    // 检查提醒
    if (data.reminders && data.reminders.length > 0) {
      count += data.reminders.length;
      data.reminders.forEach(r => items.push(r.type === '疫苗' ? '疫苗需要关注' : r.type === '驱虫' ? '驱虫需要关注' : r.type));
    }
    const name = _cachedDog?.name || '狗狗';
    if (count > 0) {
      pendingEl.innerHTML = '<span class="pending-count">' + count + '</span>' + escHtml(name) + '今天有 <b>' + count + '</b> 项健康任务待完成';
      // 显示最新提醒
      if (data.reminders && data.reminders.length > 0) {
        const reminderEl = $('tdReminder');
        if (reminderEl) {
          reminderEl.textContent = '⏰ ' + data.reminders[0].text;
        }
      }
    } else {
      pendingEl.innerHTML = '✨ ' + escHtml(name) + '今天所有健康任务都完成啦，太棒了！';
      const reminderEl = $('tdReminder');
      if (reminderEl) reminderEl.textContent = '';
    }
  } catch (e) {
    const pendingEl = $('todayPending');
    if (pendingEl) pendingEl.innerHTML = '';
  }
}

async function recordDailyCheck(result) {
  try {
    const data = await api('/api/daily_check?pet_id=' + (_cachedDog?.id || 1) + '&result=' + result, { method: 'POST' });
    if (data.already_done) {
      showToast('今日健康检查已完成，明天再来吧～');
      return;
    }
    showToast(data.message || '健康检查记录成功！');
    // 更新UI
    const actions = $('dailyCheckActions');
    const completed = $('dailyCheckCompleted');
    const badge = $('dailyCheckBadge');
    const desc = $('dailyCheckDesc');
    if (actions) actions.style.display = 'none';
    if (badge) badge.style.display = '';
    if (completed) {
      completed.style.display = '';
      completed.innerHTML = '✅ 今日健康检查已完成！' + (result === 'normal' ? '一切正常，' + (_cachedDog?.name || '狗狗') + '今天也很健康～' : '已记录异常，建议前往"添加健康记录"补充详细信息。');
    }
    if (desc) desc.style.opacity = '0.6';
    // 更新爪印和待办计数
    if (_cachedDog) { _cachedDog.paw_points = data.paw_points; }
    updateTodayDashboard(_cachedDog, calcAge(_cachedDog?.birthday));
    // 如果发现异常，引导记录
    if (result === 'abnormal') {
      setTimeout(() => {
        if (confirm('需要记录详细的异常情况吗？')) {
          navigateTo('record');
          setTimeout(() => {
            const sel = $('fEType');
            if (sel) sel.value = '异常行为';
          }, 300);
        }
      }, 500);
    }
  } catch (e) {
    showToast('记录失败，请稍后再试');
  }
}

async function loadProfile() {
  const hpInner = $('hpCardInner');
  const hpEmpty = $('hpEmpty');
  const hpHeader = $('hpCardHeader');
  try {
    const dog = await api('/api/dog');
    _cachedDog = dog;
    const age = calcAge(dog.birthday);

    // 缓存健康数据
    try { _cachedHealthData = await api('/api/health_check'); } catch (e) {}

    // 更新今日状态卡
    updateTodayDashboard(dog, age);

    // 显示档案内容
    if (hpEmpty) hpEmpty.style.display = 'none';
    if (hpInner) hpInner.style.display = '';
    if (hpHeader) hpHeader.style.display = '';

    // 健康快照
    loadHealthSnapshot(dog);

    // 显示狗狗照片
    showDogPhoto(dog.photo, dog.breed);
    loadDailyAvatar();
    updateGreeting(dog.name);

    // 更新事件卡片副标题和发情选项
    updateEventSubtitle(dog.name);
    updateEstrusOption(dog.gender);

    // 预加载饮食和保健品数据
    loadDietCard();
    loadSupplements();

    // 加载签到状态、成长记录和彩蛋提示
    loadCheckinStatus();
    loadCompactGrowth();
    showEasterHint();
    syncQuizEntryVisibility();
  } catch (e) {
    // 未建档状态
    if (hpInner) hpInner.style.display = 'none';
    if (hpEmpty) hpEmpty.style.display = '';
    if (hpHeader) hpHeader.style.display = 'none';
  }
}

// ---- 健康快照 ----
function loadHealthSnapshot(dog) {
  const hpName = $('hpName');
  if (hpName) hpName.textContent = dog.name + ' 的健康档案';

  const snapshot = $('hpSnapshot');
  if (!snapshot) return;

  const ageMonths = calcAgeMonths(dog.birthday);
  const insights = [];

  // 体重状态
  if (dog.weight && dog.weight.trim()) {
    const w = parseFloat(dog.weight.trim().replace(/[^0-9.]/g, ''));
    if (!isNaN(w) && dog.breed) {
      const range = getBreedWeightRange(dog.breed);
      if (range && w < range[0]) {
        insights.push({ icon: '⚖️', text: '体重偏轻（' + dog.weight + '），' + dog.breed + '标准体重约 ' + range[0] + '-' + range[1] + 'kg，建议增加营养摄入。' });
      } else if (range && w > range[1]) {
        insights.push({ icon: '⚖️', text: '体重偏重（' + dog.weight + '），' + dog.breed + '标准体重约 ' + range[0] + '-' + range[1] + 'kg，建议控制饮食和增加运动。' });
      } else {
        insights.push({ icon: '✅', text: '体重 ' + dog.weight + '，在健康范围内～' });
      }
    } else {
      insights.push({ icon: '⚖️', text: '当前体重：' + dog.weight });
    }
  } else {
    insights.push({ icon: '⚖️', text: '还没记录体重，填写后可生成饮食建议和成长曲线。', action: '去记录', target: 'weight' });
  }

  // 过敏源
  if (dog.allergies && dog.allergies.trim()) {
    insights.push({ icon: '⚠️', text: '过敏源：' + dog.allergies + ' — 注意避开相关食物和用品。' });
  }

  // 已知疾病
  if (dog.diseases && dog.diseases.trim()) {
    insights.push({ icon: '🏥', text: '已知疾病：' + dog.diseases + ' — 日常照护中请持续关注。' });
  }

  // 绝育状态
  if (dog.neutered === '已绝育') {
    insights.push({ icon: '✅', text: '已完成绝育。' });
  } else if (dog.neutered === '未绝育' && ageMonths >= 6 && ageMonths <= 18) {
    insights.push({ icon: '💡', text: '未绝育，' + ageMonths + '月龄正处于绝育适龄期，可咨询兽医。' });
  } else if (dog.neutered === '未绝育' && ageMonths < 6) {
    insights.push({ icon: '🐶', text: '幼犬阶段（' + ageMonths + '月龄），暂无需考虑绝育。' });
  }

  // 如果没有特殊事项，显示一个正面总结
  if (insights.length <= 1 && dog.weight && dog.weight.trim()) {
    insights.push({ icon: '💚', text: '狗狗基础健康信息齐全，主人真贴心～继续做好日常照护吧！' });
  }

  // 渲染快照
  let html = '';
  insights.forEach(item => {
    if (item.action) {
      html += '<div class="hp-insight"><span class="hp-insight-icon">' + item.icon + '</span><span class="hp-insight-text">' + escHtml(item.text) + ' <a class="hp-insight-action" onclick="navigateTo(\'' + item.target + '\')">' + item.action + ' →</a></span></div>';
    } else {
      html += '<div class="hp-insight"><span class="hp-insight-icon">' + item.icon + '</span><span class="hp-insight-text">' + escHtml(item.text) + '</span></div>';
    }
  });

  // 如果档案基础信息缺失较多，在底部添加温和的完善引导
  const missingCritical = [];
  if (!dog.breed || !dog.breed.trim()) missingCritical.push('品种');
  if (!dog.birthday) missingCritical.push('生日');
  if (missingCritical.length > 0) {
    html += '<div class="hp-insight hp-insight-muted"><span class="hp-insight-icon">📋</span><span class="hp-insight-text">建议补充' + missingCritical.join('、') + '信息，以获取更精准的健康建议。<a class="hp-insight-action" onclick="openEditModal()">完善档案 →</a></span></div>';
  }

  snapshot.innerHTML = html;
}

// 品种标准体重参考（kg）
function getBreedWeightRange(breed) {
  const map = {
    '金毛': [25, 34], '拉布拉多': [25, 36], '柯基': [10, 14], '贵宾': [3, 8],
    '泰迪': [2, 5], '豆柴': [6, 10], '柴犬': [8, 12], '哈士奇': [20, 27],
    '萨摩耶': [20, 30], '边牧': [14, 22], '德牧': [22, 40], '法斗': [8, 14],
    '英斗': [18, 25], '比熊': [3, 6], '博美': [1.5, 3.5], '雪纳瑞': [5, 9],
    '吉娃娃': [1, 3], '约克夏': [1.5, 3], '巴哥': [6, 9], '中华田园犬': [12, 25],
  };
  const key = Object.keys(map).find(k => breed.includes(k));
  return key ? map[key] : null;
}

// ---- 成长记录压缩版 ----
async function loadCompactGrowth() {
  if (!_cachedDog) return;
  const container = $('growthCompact');
  if (!container) return;
  const dog = _cachedDog;
  let html = '';

  // 最近照片
  const healthPhotos = dog.health_photos || [];
  if (healthPhotos.length > 0) {
    html += '<div class="growth-photos-row">';
    const recentPhotos = healthPhotos.slice(-3).reverse();
    recentPhotos.forEach(p => {
      const src = p.filename ? ('/photos/' + p.filename) : '';
      const label = p.label || p.event_type || '';
      html += '<div class="growth-photo-thumb" title="' + label + '">' +
        (src ? '<img src="' + src + '" alt="' + label + '" />' : '<span style="font-size:2em;">🐶</span>') +
        '</div>';
    });
    html += '</div>';
  } else {
    html += '<div class="growth-photos-row">' +
      '<div class="growth-photo-thumb-placeholder">📸</div>' +
      '<div class="growth-photo-thumb-placeholder">📸</div>' +
      '<div class="growth-photo-thumb-placeholder">📸</div>' +
      '</div>';
  }

  // 最近勋章
  try {
    const badgeData = await api('/api/badges?pet_id=' + dog.id);
    const unlocked = badgeData.badges.filter(b => b.unlocked);
    if (unlocked.length > 0) {
      html += '<div class="growth-badges-row">';
      const recentBadges = unlocked.slice(-3).reverse();
      recentBadges.forEach(b => {
        html += '<span class="growth-badge-mini">' + b.icon + ' ' + b.name + '</span>';
      });
      html += '</div>';
    }
    // 下一枚锁定的勋章
    const nextLocked = badgeData.badges.find(b => !b.unlocked);
    if (nextLocked) {
      html += '<div class="growth-badges-row">';
      html += '<span class="growth-badge-mini locked">🔒 ' + nextLocked.icon + ' ' + nextLocked.name + '</span>';
      html += '</div>';
    }
  } catch (e) {}

  container.innerHTML = html;
}

// ---- 狗狗照片 ----
function showDogPhoto(photoFilename, breed) {
  const breedIcon = getBreedIcon(breed || '') || '🐶';

  // 更新今日卡片头像 — 直接显示
  const avatar = $('todayAvatar');
  if (avatar) {
    avatar.setAttribute('data-breed-icon', breedIcon);
    avatar.setAttribute('data-photo-filename', photoFilename || '');
    if (photoFilename) {
      avatar.style.backgroundImage = `url('/photos/${photoFilename}')`;
      avatar.style.backgroundSize = 'cover';
      avatar.style.backgroundPosition = 'center';
      avatar.textContent = '';
    } else {
      avatar.style.backgroundImage = '';
      avatar.textContent = breedIcon;
    }
  }

  // 同步更新所有子页面小头像
  const subAvatars = document.querySelectorAll('.today-avatar-sm');
  subAvatars.forEach(a => {
    if (photoFilename) {
      a.style.backgroundImage = `url('/photos/${photoFilename}')`;
      a.style.backgroundSize = 'cover';
      a.style.backgroundPosition = 'center';
      a.textContent = '';
    } else {
      a.style.backgroundImage = '';
      a.textContent = breedIcon;
    }
  });
}

// ---- 健康成长相册 - 每日头像 ----
async function loadDailyAvatar() {
  if (!_cachedDog) return;
  try {
    const data = await api(`/api/pets/${_cachedDog.id}/avatar`);
    const avatar = $('todayAvatar');
    if (!avatar) return;
    // 有健康相册头像时覆盖显示
    if (data.avatar) {
      avatar.style.backgroundImage = `url('${data.avatar}')`;
      avatar.style.backgroundSize = 'cover';
      avatar.style.backgroundPosition = 'center';
      avatar.textContent = '';
      // 设置悬停提示
      const hint = data.avatar_hint || '健康成长纪念照';
      avatar.title = '📸 ' + hint + ' — 点击可更换档案照';
    } else {
      // 无健康相册头像 → fallback 到档案照或品种图标
      avatar.title = '🐶 记录健康事件解锁纪念照哦～';
      const breedIcon = avatar.getAttribute('data-breed-icon') || '🐶';
      const photoFile = avatar.getAttribute('data-photo-filename') || '';
      if (photoFile) {
        avatar.style.backgroundImage = `url('/photos/${photoFile}')`;
        avatar.style.backgroundSize = 'cover';
        avatar.style.backgroundPosition = 'center';
        avatar.textContent = '';
      } else {
        avatar.style.backgroundImage = '';
        avatar.textContent = breedIcon;
      }
    }
  } catch (e) { /* 静默失败，保留档案照 */ }
}

// ---- 健康成长相册 - 照片画廊 ----
// 展示 health_photos（健康事件纪念照），直接在 /api/dog 返回中携带

async function loadPhotoGallery() {
  if (!_cachedDog) return;
  const section = $('photoGallerySection');
  const locked = $('photoGalleryLocked');
  const strip = $('photoGalleryStrip');
  const countEl = $('photoGalleryCount');
  if (!section || !strip) return;

  try {
    // 重新获取最新狗狗数据（含 health_photos）
    const dog = await api('/api/dog');
    if (dog) _cachedDog = dog;
    const healthPhotos = _cachedDog.health_photos || [];
    const photoCount = healthPhotos.length;

    section.style.display = '';

    // 0. 空相册 → 引导文案
    if (photoCount === 0) {
      if (locked) locked.style.display = '';
      if (strip) strip.style.display = 'none';
      if (countEl) countEl.style.display = 'none';
      return;
    }

    // 有照片 → 隐藏引导，显示胶片条
    if (locked) locked.style.display = 'none';
    if (strip) strip.style.display = '';
    if (countEl) {
      countEl.style.display = '';
      countEl.textContent = `${photoCount} 张纪念照`;
      countEl.className = 'photo-gallery-count';
    }

    renderFilmStrip(healthPhotos);

  } catch (e) {
    section.style.display = 'none';
  }
}

function renderFilmStrip(healthPhotos) {
  const strip = $('photoGalleryStrip');
  if (!strip) return;

  let html = '';
  healthPhotos.forEach((p, i) => {
    const label = p.label || p.event_type || '纪念照';
    const date = p.event_date || '';
    const src = p.filename ? ('/photos/' + p.filename) : '';
    html += `<div class="photo-film-item" id="filmItem${i}"
        onclick="handleFilmItemClick(${i})"
        title="${label} · ${date} — 点击删除照片">
      ${src ? `<img src="${src}" alt="${label}" />` : `<span style="color:var(--muted);font-size:0.7em;">🐶</span>`}
      <span class="photo-film-label">${label}</span>
      <span class="photo-film-delete">🗑</span>
    </div>`;
  });
  strip.innerHTML = html;
}

function handleFilmItemClick(index) {
  const photos = _cachedDog?.health_photos || [];
  const p = photos[index];
  const label = p ? (p.label || '纪念照') : ('第' + (index + 1) + '张');
  if (confirm(`确定要删除「${label}」这张纪念照吗？`)) {
    confirmDeletePhoto(index);
  }
}

async function confirmDeletePhoto(index) {
  if (!_cachedDog) return;
  try {
    const resp = await fetch(`/api/dog/health_photo?pet_id=${_cachedDog.id}&index=${index}`, { method: 'DELETE' });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || '删除失败');
    showToast(data.message);
    await loadProfile();
    loadPhotoGallery();
  } catch (e) {
    showToast('删除失败：' + (e.message || '未知错误'), true);
  }
}

// ---- 快捷操作 ----
function openPawHistory() {
  if (_cachedDog) showPawHistory();
}

function scrollToWeight() {
  navigateTo('weight');
}

function openEditModal() {
  if (!_cachedDog) {
    showToast('主人，请先建立档案哦～', true);
    return;
  }
  $('editModalOverlay').style.display = 'flex';
}

// ---- 爪印历史弹窗 ----
async function showPawHistory() {
  if (!_cachedDog) return;
  const overlay = $('pawHistoryOverlay');
  const list = $('pawHistoryList');
  if (!overlay || !list) return;

  overlay.style.display = 'flex';
  list.innerHTML = '<div class="paw-history-empty">加载中...</div>';

  try {
    const data = await api(`/api/pets/${_cachedDog.id}/paw-history`);
    const history = data.history || [];

    if (history.length === 0) {
      list.innerHTML = '<div class="paw-history-empty">还没有爪印记录哦～<br/>签到、做任务、答题都能赚爪印！</div>';
      return;
    }

    const REASON_ICONS = {
      '签到': '📅', '任务完成': '✅', '答对测验': '🎁', '记录事件': '📝',
    };
    let html = '';
    for (const h of history) {
      const icon = REASON_ICONS[h.reason] || '🐾';
      html += `<div class="paw-history-item">
        <div class="paw-history-item-left">
          <span class="paw-history-item-reason">${icon} ${h.reason}</span>
          <span class="paw-history-item-date">${h.date}</span>
        </div>
        <span class="paw-history-item-amount">+${h.amount}🐾</span>
      </div>`;
    }
    list.innerHTML = html;
  } catch (e) {
    list.innerHTML = '<div class="paw-history-empty">加载失败，等会再试试吧～</div>';
  }
}

function closePawHistory() {
  $('pawHistoryOverlay').style.display = 'none';
}

function uploadDogPhoto(file) {
  return new Promise(async (resolve, reject) => {
    const formData = new FormData();
    formData.append('file', file);
    try {
      const resp = await fetch('/api/dog/photo', { method: 'POST', body: formData });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || data.message || '上传失败');
      resolve(data);
    } catch (e) {
      reject(e);
    }
  });
}

// 点击今日卡片头像触发更换
$('todayAvatar').addEventListener('click', function() {
  if (!_cachedDog) { showToast('主人，请先创建狗狗档案～', true); return; }
  $('dogPhotoInput').click();
});

// 子页面小头像点击也可上传
document.addEventListener('click', function(e) {
  if (e.target.closest('.today-avatar-sm')) {
    if (!_cachedDog) { showToast('主人，请先创建狗狗档案～', true); return; }
    $('dogPhotoInput').click();
  }
});

$('dogPhotoInput').addEventListener('change', async function() {
  const file = this.files[0];
  if (!file) return;
  // 前端预校验
  if (!['image/jpeg', 'image/png', 'image/jpg'].includes(file.type)) {
    showToast('主人，只支持 JPG 和 PNG 格式的图片哦～', true);
    this.value = '';
    return;
  }
  if (file.size > 2 * 1024 * 1024) {
    showToast('主人，图片太大了（不能超过 2MB），压缩一下再上传吧～', true);
    this.value = '';
    return;
  }
  try {
    showToast('正在上传照片...');
    const result = await uploadDogPhoto(file);
    showToast(result.message);
    // 刷新显示
    if (_cachedDog) {
      _cachedDog.photo = result.photo;
      showDogPhoto(result.photo, _cachedDog.breed);
    }
    loadProfile();
    // 检查是否有待完成的拍照任务
    setTimeout(() => checkPendingTask(), 300);
  } catch (e) {
    showToast('照片上传失败：' + (e.message || '未知错误'), true);
  }
  this.value = '';
});


function calcIsPuppy(birthStr) {
  const birth = new Date(birthStr);
  const now = new Date();
  const months = (now.getFullYear() - birth.getFullYear()) * 12 + (now.getMonth() - birth.getMonth());
  return months < 12;
}

function updateEstrusOption(gender) {
  // 根据狗狗性别控制"发情期"事件选项的显示
  const estrusOption = document.querySelector('#fEType option[value="发情"]');
  if (estrusOption) {
    if (gender === 'male') {
      estrusOption.style.display = 'none';
      if ($('fEType').value === '发情') {
        $('fEType').value = '疫苗';
        renderExtraFields();
      }
    } else {
      estrusOption.style.display = '';
    }
  }
  // 同步隐藏时间线筛选中的发情选项
  document.querySelectorAll('.tl-filter[data-filter="发情"]').forEach(f => {
    f.style.display = (gender === 'male') ? 'none' : '';
  });
}

function updateEventSubtitle(dogName) {
  const sub = $('eventSubtitle');
  if (sub && dogName) {
    sub.innerHTML = `帮 <strong style="color:var(--orange);">${escHtml(dogName)}</strong> 记录疫苗、驱虫、发情、洗澡澡或异常行为，我会立刻给你反馈`;
  }
}

function calcAge(birthStr) {
  const birth = new Date(birthStr);
  const now = new Date();
  const months = (now.getFullYear() - birth.getFullYear()) * 12 + (now.getMonth() - birth.getMonth());
  if (months < 1) return '小奶狗';
  if (months < 12) return `${months}个月大`;
  const years = Math.floor(months / 12);
  const remainMonths = months % 12;
  return remainMonths > 0 ? `${years}岁${remainMonths}个月` : `${years}岁`;
}

function calcAgeMonths(birthStr) {
  if (!birthStr) return 0;
  const birth = new Date(birthStr);
  const now = new Date();
  return (now.getFullYear() - birth.getFullYear()) * 12 + (now.getMonth() - birth.getMonth());
}

function escHtml(s) {
  if (!s) return '';
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

// ---- 饮食宝典 ----
async function loadDietCard() {
  const card = $('cardDiet');
  const area = $('dietArea');
  if (!card || !area) return;
  try {
    const data = await api('/api/dog/diet');
    if (!data.ready) {
      card.style.display = '';
      const suspendedHtml = data.suspended ? `<div style="margin-top:10px;"><button class="btn btn-outline btn-sm" onclick="restoreSuggestions()" style="color:var(--orange);border-color:var(--orange);">✅ 已联系兽医，恢复建议</button></div>` : '';
      area.innerHTML = `<div style="font-size:0.9em;color:var(--brown-light);line-height:1.8;">🐾 ${escHtml(data.message)}</div>${suspendedHtml}`;
      return;
    }
    card.style.display = '';
    const today = new Date();
    const dateStr = `${today.getFullYear()}年${today.getMonth()+1}月${today.getDate()}日`;

    // 更新卡标题中的餐数
    const mealsLabel = $('dietMealsLabel');
    if (mealsLabel) mealsLabel.textContent = `· 每天${data.meals_per_day}餐`;

    // 构建食材行 HTML
    const itemsHTML = data.items.map(it => `
      <div class="recipe-item">
        <span class="recipe-item-name">${it.emoji} ${escHtml(it.name)}</span>
        <span class="recipe-item-dots"></span>
        <span class="recipe-item-weight">${it.weight}g</span>
      </div>`).join('');

    area.innerHTML = `
      <div class="recipe-wrap">
        <!-- 左侧：食谱主卡 -->
        <div class="recipe-main">
          <div class="recipe-deco">
            <div class="recipe-deco-line"></div>
            <div class="recipe-deco-title">🐶 ${escHtml(data.dog_name)}的一餐食谱</div>
            <div class="recipe-deco-line"></div>
          </div>
          <div class="recipe-date">📅 ${dateStr}</div>
          <div class="recipe-meal-name">${escHtml(data.meal_name)}</div>

          <div class="recipe-items">
            ${itemsHTML}
          </div>

          <div class="recipe-total">
            <span class="recipe-total-label">⚖️ 本餐总重</span>
            <span class="recipe-total-weight">${data.total_weight}g</span>
          </div>

          <div class="recipe-nutrition">
            <span class="nut-tag nut-tag-protein">🥩 蛋白质 ${data.total_protein}g</span>
            <span class="nut-tag nut-tag-fat">🧈 脂肪 ${data.total_fat}g</span>
            <span class="nut-tag nut-tag-carbs">🍚 碳水 ${data.total_carbs}g</span>
          </div>

          <div class="recipe-cooking-tip">💡 所有食材切碎蒸熟，不放盐哦～</div>
          ${data.allergy_note ? `<div style="text-align:center;font-size:0.78em;color:#C0392B;margin-top:6px;">${escHtml(data.allergy_note)}</div>` : ''}
          ${data.hypoglycemia_note ? `<div style="text-align:center;font-size:0.78em;color:#E67E22;margin-top:6px;font-weight:600;">${escHtml(data.hypoglycemia_note)}</div>` : ''}
          ${data.disease_note ? `<div style="text-align:center;font-size:0.78em;color:#8B4513;margin-top:6px;">${escHtml(data.disease_note)}</div>` : ''}
        </div>

        <!-- 右侧：辅助信息 -->
        <div class="recipe-side">
          <div class="side-section">
            <div class="side-label">🔄 替换选择</div>
            <div class="side-text" style="line-height:1.7;">
              🥩 ${escHtml(data.protein_options)}<br/>
              🥬 ${escHtml(data.veggie_options)}<br/>
              🍚 ${escHtml(data.carb_options)}
            </div>
          </div>

          <div class="side-section">
            <div class="side-label">🐟 鱼油补充</div>
            <div class="side-text">${escHtml(data.fish_oil)}</div>
          </div>

          <div class="side-section">
            <div class="side-label">💡 小贴士</div>
            <div class="side-text">${escHtml(data.tip)}</div>
          </div>

          <div style="margin-top:auto;padding-top:8px;font-size:0.92em;color:var(--muted);font-family:'Gaegu','KaiTi','STKaiti','Comic Sans MS',sans-serif;line-height:1.6;border-top:1px dotted var(--border);">
            💬 ${escHtml(data.heartfelt)}
          </div>
        </div>
      </div>
      <div style="display:flex;gap:8px;justify-content:center;margin-top:12px;flex-wrap:wrap;">
        <button class="btn btn-secondary btn-sm" onclick="scrollToWeight()">⚖️ 更新体重重新计算</button>
        <button class="btn btn-primary btn-sm" id="btnRecordFed">✅ 记录已喂食</button>
      </div>
      <div class="diet-basis-toggle" onclick="this.nextElementSibling.style.display=this.nextElementSibling.style.display==='none'?'block':'none'">
        📐 为什么是 ${data.total_weight}g ？点击查看计算依据 ▼
      </div>
      <div class="diet-basis-detail" style="display:none;">
        <div class="diet-basis-row"><span>体重</span><span>${data.weight_kg || '?'} kg</span></div>
        <div class="diet-basis-row"><span>年龄阶段</span><span>${escHtml(data.age_stage || '未知')}</span></div>
        <div class="diet-basis-row"><span>绝育情况</span><span>${escHtml(data.neutered || '未知')}</span></div>
        <div class="diet-basis-row"><span>活动水平</span><span>标准（系数 ×${data.activity_coeff || '1.8'}）</span></div>
        <div class="diet-basis-row"><span>RER（静息能耗）</span><span>${data.rer || '?'} kcal</span></div>
        <div class="diet-basis-row"><span>DER（每日能耗）</span><span>${data.der || '?'} kcal</span></div>
        <div class="diet-basis-row"><span>总喂食量</span><span>${data.total_weight || '?'} g（1.5 kcal/g估算）</span></div>
      </div>
      <div style="margin-top:12px;font-size:0.75em;color:var(--muted);text-align:center;line-height:1.5;padding:6px 8px;background:#FFFBF5;border-radius:6px;border:1px solid #FFE0C0;">
        📋 此饮食建议基于您填写的档案信息自动生成，仅供参考，不能替代兽医的专业诊断。如有健康问题请立即联系兽医。
      </div>`;
  } catch (e) {
    card.style.display = 'none';
  }
}
// ---- 保健品小队 ----
async function loadSupplements() {
  const card = $('cardSupplements');
  const area = $('supplementsArea');
  if (!card || !area) return;
  try {
    const data = await api('/api/supplements');
    if (data.suspended) {
      card.style.display = '';
      area.innerHTML = `<div class="supp-empty" style="color:var(--red);">${escHtml(data.message)}</div>
        <div style="text-align:center;margin-top:10px;"><button class="btn btn-outline btn-sm" onclick="restoreSuggestions()" style="color:var(--orange);border-color:var(--orange);">✅ 已联系兽医，恢复建议</button></div>`;
      return;
    }
    if (!data.has_dog || data.alerts.length === 0) {
      card.style.display = '';
      const dogInfo = _cachedDog || {};
      const age = dogInfo.birthday ? calcAge(dogInfo.birthday) : '未知';
      const weight = dogInfo.weight || '未填写';
      const checkData = _cachedHealthData || {};
      area.innerHTML = `<div class="supp-empty-state">
        <div class="supp-empty-icon">🛡️</div>
        <div class="supp-empty-title">主人把我照顾得很好，暂时不需要额外补给～</div>
        <div class="supp-empty-desc">根据当前档案和记录，没有发现需要特别补充保健品的情况。</div>
        <div class="supp-empty-checklist">
          <div class="supp-check-item"><span class="supp-check-icon">✓</span> 年龄：${escHtml(age)}，非特殊风险阶段</div>
          <div class="supp-check-item"><span class="supp-check-icon">✓</span> 体重：${escHtml(weight)}，暂无明显体重风险</div>
          <div class="supp-check-item"><span class="supp-check-icon">✓</span> 最近无高风险异常记录</div>
          <div class="supp-check-item"><span class="supp-check-icon">✓</span> 皮肤/肠胃/关节暂无持续异常</div>
        </div>
        <div class="supp-empty-divider"></div>
        <div class="supp-empty-subtitle">什么时候需要考虑保健品？</div>
        <div class="supp-empty-hints">
          <div>· 经常抓痒、掉毛严重</div>
          <div>· 频繁软便、腹泻</div>
          <div>· 关节疼痛、跛行</div>
          <div>· 老年犬活动力下降</div>
        </div>
        <div style="display:flex;gap:8px;justify-content:center;margin-top:14px;flex-wrap:wrap;">
          <button class="btn btn-primary btn-sm" onclick="navigateTo('record')">📝 记录异常行为</button>
          <button class="btn btn-secondary btn-sm" onclick="scrollToWeight()">⚖️ 更新体重</button>
        </div>
      </div>`;
      return;
    }
    card.style.display = '';
    const iconMap = {
      '关节': '🦴', '维生素': '💊', '鱼油': '🐟', '益生菌': '🥛',
      '美毛': '✨', '泌尿': '💧',
    };
    function getIcon(name) {
      for (const [k, v] of Object.entries(iconMap)) {
        if (name.includes(k)) return v;
      }
      return '💊';
    }
    area.innerHTML = data.alerts.map(a => `
      <div class="supp-alert-item">
        <span class="supp-alert-icon">${getIcon(a.supplement_name)}</span>
        <div class="supp-alert-body">
          <div class="supp-alert-name">${escHtml(a.supplement_name)}</div>
          <div class="supp-alert-reason">📌 ${escHtml(a.reason)}</div>
          <div class="supp-alert-woof">${escHtml(a.woof_text)}</div>
        </div>
      </div>`).join('') + `
      <div style="margin-top:12px;font-size:0.75em;color:var(--muted);text-align:center;line-height:1.5;padding:6px 8px;background:#FFFBF5;border-radius:6px;border:1px solid #FFE0C0;">
        💊 保健品提醒基于一般营养学知识生成，具体服用方案请咨询兽医确认。
      </div>`;
  } catch (e) {
    card.style.display = 'none';
  }
}
// ---- 体重日志 ----
// ---- 体重管理页面 ----
async function loadWeightPage() {
  if (!_cachedDog) return;
  $('wlDate').value = new Date().toISOString().slice(0, 10);
  loadWeightLogs();
  updateWeightFrequencyHint();
}

function updateWeightFrequencyHint() {
  if (!_cachedDog || !_cachedDog.birthday) return;
  const ageMonths = calcAgeMonths(_cachedDog.birthday);
  const hint = $('weightFreqHint');
  if (!hint) return;
  if (ageMonths < 12) {
    hint.textContent = '💡 幼犬建议每周记录 1-2 次体重，密切跟踪生长曲线。';
  } else if (ageMonths < 84) {
    hint.textContent = '💡 成年犬建议每月记录 1 次体重，监测肥胖趋势。';
  } else {
    hint.textContent = '💡 老年犬建议每 2-4 周记录 1 次，体重突然下降可能是健康预警信号。';
  }
}

async function loadWeightLogs() {
  const list = $('weightLogList');
  const chartContainer = $('weightChartContainer');
  const statsRow = $('weightStatsRow');
  try {
    const logs = await api('/api/weight_logs');
    if (!logs || logs.length === 0) {
      if (chartContainer) chartContainer.innerHTML = '<div style="font-size:0.88em;color:var(--muted);text-align:center;padding:20px 0;">还没有体重记录，主人快帮我添加第一条吧～</div>';
      if (statsRow) statsRow.style.display = 'none';
      if (list) list.innerHTML = '';
      return;
    }
    // 趋势图（简易柱状图）
    if (chartContainer) {
      const sorted = [...logs].sort((a, b) => a.date.localeCompare(b.date));
      const recent = sorted.slice(-12); // 最近12条
      const weights = recent.map(l => parseFloat(l.weight.replace(/[^0-9.]/g, '')));
      const maxW = Math.max(...weights);
      const minW = Math.min(...weights);
      const range = maxW - minW || 1;
      let chartHTML = '<div class="weight-chart">';
      recent.forEach((l, i) => {
        const w = parseFloat(l.weight.replace(/[^0-9.]/g, ''));
        const h = Math.max(15, ((w - minW) / range) * 100);
        const label = l.date.slice(5); // MM-DD
        chartHTML += '<div class="weight-bar-col"><div class="weight-bar-val">' + l.weight + '</div><div class="weight-bar" style="height:' + h + 'px;"></div><div class="weight-bar-label">' + label + '</div></div>';
      });
      chartHTML += '</div>';
      chartContainer.innerHTML = chartHTML;
    }
    // 统计行
    if (statsRow) {
      statsRow.style.display = '';
      const firstLog = logs[logs.length - 1];
      const lastLog = logs[0];
      const firstW = parseFloat(firstLog.weight.replace(/[^0-9.]/g, ''));
      const lastW = parseFloat(lastLog.weight.replace(/[^0-9.]/g, ''));
      const change = lastW - firstW;
      let changeHTML = '';
      if (logs.length >= 2 && change !== 0) {
        const sign = change > 0 ? '+' : '';
        const arrow = change > 0 ? '↗' : '↘';
        changeHTML = '<div class="weight-stat"><span class="weight-stat-label">体重变化</span><span class="weight-stat-value">' + arrow + ' ' + sign + change.toFixed(1) + ' kg</span></div>';
      }
      statsRow.innerHTML = '<div class="weight-stat"><span class="weight-stat-label">最新体重</span><span class="weight-stat-value">' + lastLog.weight + '</span></div>' +
        '<div class="weight-stat"><span class="weight-stat-label">记录次数</span><span class="weight-stat-value">' + logs.length + ' 次</span></div>' +
        changeHTML;
    }
    // 历史列表
    if (list) {
      list.innerHTML = logs.map(l => `
        <div style="display:flex;justify-content:space-between;font-size:0.85em;padding:6px 0;border-bottom:1px dotted var(--border);">
          <span>${l.date}</span>
          <span style="font-weight:600;color:var(--brown);">${escHtml(l.weight)}</span>
        </div>`).join('');
    }
  } catch (e) {
    if (chartContainer) chartContainer.innerHTML = '<div style="font-size:0.88em;color:var(--muted);">加载体重记录失败</div>';
    if (list) list.innerHTML = '';
  }
}

$('btnAddWeight').addEventListener('click', async function() {
  const btn = this;
  const weight = $('wlWeight').value.trim();
  const dateVal = $('wlDate').value || new Date().toISOString().slice(0, 10);
  if (!weight) { showToast('汪汪，请填写体重哦～', true); return; }
  if (!_cachedDog) { showToast('主人，请先创建狗狗档案～', true); return; }

  btn.disabled = true;
  btn.textContent = '...';
  try {
    const r = await api('/api/weight_log', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dog_id: _cachedDog.id, weight, date: dateVal }),
    });
    showToast(r.message);
    $('wlWeight').value = '';
    $('wlDate').value = new Date().toISOString().slice(0, 10);
    loadWeightLogs();
    loadProfile();
    if (r.new_badges && r.new_badges.length > 0) {
      handleNewBadges(r.new_badges);
    }
  } catch (e) {
    showToast(e.message || '记录体重失败', true);
  }
  btn.disabled = false;
  btn.textContent = '+ 记录体重';
});

// ---- 健康提醒页面 ----
async function loadRemindersPage() {
  if (!_cachedDog) return;
  const area = $('remindersArea');
  if (!area) return;
  area.innerHTML = '<div class="skeleton" style="width:60%;"></div>';

  try {
    const events = await api('/api/events?pet_id=' + _cachedDog.id);
    const today = new Date().toISOString().slice(0, 10);

    // 推算各类提醒
    const reminders = [];

    // 疫苗提醒：最近一次疫苗 + 标准间隔
    const vaccineEvents = events.filter(e => e.type === '疫苗');
    if (vaccineEvents.length > 0) {
      const lastVax = vaccineEvents.reduce((a, b) => a.date > b.date ? a : b);
      const nextVax = new Date(lastVax.date);
      nextVax.setDate(nextVax.getDate() + 365); // 标准年度疫苗
      const daysLeft = Math.ceil((nextVax - new Date()) / (1000 * 60 * 60 * 24));
      if (daysLeft <= 0) {
        reminders.push({ icon: '🔴', title: '疫苗已过期', desc: '距上次疫苗已超过 1 年（' + lastVax.date + '），请尽快联系兽医安排接种。', urgent: true });
      } else if (daysLeft <= 30) {
        reminders.push({ icon: '🟡', title: '疫苗即将到期', desc: '下次疫苗建议在 ' + nextVax.toISOString().slice(0, 10) + '（还有 ' + daysLeft + ' 天），可以提前预约了。', urgent: false });
      } else {
        reminders.push({ icon: '🟢', title: '疫苗状态正常', desc: '上次接种：' + lastVax.date + '，下次建议：' + nextVax.toISOString().slice(0, 10) + '（还有 ' + daysLeft + ' 天）。', urgent: false });
      }
    } else {
      reminders.push({ icon: '📋', title: '暂无疫苗记录', desc: '还没有记录过疫苗接种，建议首次接种后在此查看提醒。', action: '去记录', target: 'record' });
    }

    // 驱虫提醒：最近一次驱虫 + 根据年龄计算的间隔
    const dewormEvents = events.filter(e => e.type === '驱虫');
    const ageMonths = calcAgeMonths(_cachedDog.birthday);
    const dewormInterval = ageMonths < 6 ? 30 : 90;
    if (dewormEvents.length > 0) {
      const lastDeworm = dewormEvents.reduce((a, b) => a.date > b.date ? a : b);
      const nextDeworm = new Date(lastDeworm.date);
      nextDeworm.setDate(nextDeworm.getDate() + dewormInterval);
      const daysLeft = Math.ceil((nextDeworm - new Date()) / (1000 * 60 * 60 * 24));
      if (daysLeft <= 0) {
        reminders.push({ icon: '🔴', title: '驱虫已过期', desc: '距上次驱虫已超过 ' + dewormInterval + ' 天（' + lastDeworm.date + '），请尽快安排驱虫。', urgent: true });
      } else if (daysLeft <= 14) {
        reminders.push({ icon: '🟡', title: '驱虫即将到期', desc: '下次驱虫建议在 ' + nextDeworm.toISOString().slice(0, 10) + '（还有 ' + daysLeft + ' 天）。', urgent: false });
      } else {
        reminders.push({ icon: '🟢', title: '驱虫状态正常', desc: '上次驱虫：' + lastDeworm.date + '，下次建议：' + nextDeworm.toISOString().slice(0, 10) + '（还有 ' + daysLeft + ' 天）。', urgent: false });
      }
    } else {
      reminders.push({ icon: '📋', title: '暂无驱虫记录', desc: '还没有记录过驱虫，建议首次驱虫后在此查看提醒。', action: '去记录', target: 'record' });
    }

    // 发情提醒
    if (_cachedDog.gender === '母') {
      const heatEvents = events.filter(e => e.type === '发情');
      if (heatEvents.length > 0) {
        const lastHeat = heatEvents.reduce((a, b) => a.date > b.date ? a : b);
        const daysSince = Math.ceil((new Date() - new Date(lastHeat.date)) / (1000 * 60 * 60 * 24));
        reminders.push({ icon: '💕', title: '发情记录', desc: '上次发情：' + lastHeat.date + '（距今 ' + daysSince + ' 天），一般每 6-8 个月发情一次，请留意下次发情迹象。', urgent: false });
      }
    }

    // 体重提醒
    const weightLogs = await api('/api/weight_logs');
    if (weightLogs && weightLogs.length > 0) {
      const lastWeight = weightLogs.reduce((a, b) => a.date > b.date ? a : b);
      const daysSinceWeight = Math.ceil((new Date() - new Date(lastWeight.date)) / (1000 * 60 * 60 * 24));
      const maxGap = ageMonths < 12 ? 10 : 35;
      if (daysSinceWeight > maxGap) {
        reminders.push({ icon: '🟡', title: '该记录体重了', desc: '距上次记录体重已过 ' + daysSinceWeight + ' 天，建议定期记录以跟踪健康趋势。', action: '去记录', target: 'weight' });
      }
    } else {
      reminders.push({ icon: '⚖️', title: '开始记录体重', desc: '定期记录体重可以及时发现健康问题，现在开始记录第一笔吧。', action: '去记录', target: 'weight' });
    }

    // 每日检查提醒
    try {
      const checkData = await api('/api/daily_check?pet_id=' + _cachedDog.id);
      if (!checkData.done) {
        reminders.push({ icon: '🩺', title: '今日健康检查未完成', desc: '花 1 分钟摸摸狗狗，确认没有异常。', action: '去做检查', target: 'home' });
      } else {
        reminders.push({ icon: '✅', title: '今日健康检查已完成', desc: '一切正常，' + _cachedDog.name + '今天也很健康～', urgent: false });
      }
    } catch (e) {}

    // 渲染
    let html = '';
    reminders.forEach(r => {
      const urgentClass = r.urgent ? ' reminder-urgent' : '';
      html += '<div class="reminder-card' + urgentClass + '">' +
        '<div class="reminder-icon">' + r.icon + '</div>' +
        '<div class="reminder-body">' +
        '<div class="reminder-title">' + escHtml(r.title) + '</div>' +
        '<div class="reminder-desc">' + escHtml(r.desc) + '</div>' +
        (r.action ? '<a class="reminder-action" onclick="navigateTo(\'' + r.target + '\')">' + r.action + ' →</a>' : '') +
        '</div></div>';
    });

    if (reminders.length === 0) {
      html = '<div style="text-align:center;color:var(--muted);padding:20px;">还没有足够的数据来生成提醒，主人先记录一些事件吧～</div>';
    }

    area.innerHTML = html;
  } catch (e) {
    area.innerHTML = '<div style="text-align:center;color:var(--muted);padding:20px;">加载提醒失败，请稍后再试</div>';
  }
}

// ---- 加载时间线 ----
function getTimelineTitle(type, dogName) {
  const titles = {
    '疫苗': `${dogName}的勇敢日`,
    '驱虫': '驱虫保卫日',
    '发情': `${dogName}的成长印记`,
    '异常行为': `${dogName}的小状况`,
    '洗澡澡': '洗香香日',
  };
  return titles[type] || `${type}`;
}

function getTimelineIconClass(type) {
  const map = { '疫苗': 'vaccine', '驱虫': 'deworm', '发情': 'heat', '异常行为': 'abnormal', '洗澡澡': 'bath' };
  return map[type] || '';
}

function getTimelineIconEmoji(type) {
  const map = { '疫苗': '💉', '驱虫': '💊', '发情': '💕', '异常行为': '⚠️', '洗澡澡': '🛁' };
  return map[type] || '📌';
}

let _allEvents = [];
let _currentFilter = '全部';

async function loadTimeline() {
  const area = $('timelineArea');
  area.innerHTML = '<div class="skeleton" style="width:60%;"></div><div class="skeleton" style="width:40%;"></div>';

  try {
    let dogName = '汪星人';
    try {
      const dog = await api('/api/dog');
      dogName = dog.name;
    } catch (e) { /* 无狗狗时使用默认名 */ }

    const events = await api('/api/events');
    _allEvents = events || [];
    renderTimeline(dogName);
  } catch (e) {
    area.innerHTML = `<div class="empty-state">汪汪，加载回忆失败了，<a href="javascript:loadTimeline()" style="color:var(--orange);cursor:pointer;">点我重试</a></div>`;
  }
}

function renderTimeline(dogName) {
  const area = $('timelineArea');
  const area2 = $('timelineArea2');
  const html = _buildTimelineHTML(dogName);
  if (area) area.innerHTML = html;
  if (area2) area2.innerHTML = html;
}

function _buildTimelineHTML(dogName) {
  let events = _allEvents;
  if (_currentFilter !== '全部') {
    events = _allEvents.filter(e => e.type === _currentFilter);
  }
  updateFilterCounts();

  if (!events || events.length === 0) {
    const msg = _currentFilter === '全部'
      ? '🐾 我的一生刚开始，主人快帮我记录第一次吧～'
      : '🐾 这个分类还没有记录哦，主人快去添加吧～';
    return `<div class="empty-state">${msg}</div>`;
  }

  let html = '';
  for (const e of events) {
    let desc = '';
    try {
      const detail = typeof e.detail === 'string' ? JSON.parse(e.detail) : (e.detail || {});
      if (e.type === '疫苗') {
        desc = detail.brand ? `第${detail.dose || '?'}针 · ${detail.brand}` : (detail.dose ? `第${detail.dose}针` : '完成接种');
      } else if (e.type === '驱虫') {
        desc = detail.brand || '完成驱虫';
      } else if (e.type === '发情') {
        desc = '记录发情期';
      } else if (e.type === '异常行为') {
        const symptoms = detail.symptoms || [];
        desc = symptoms.length > 0 ? `症状：${symptoms.join('、')}` : '记录异常情况';
      } else if (e.type === '洗澡澡') {
        desc = '洗香香啦～🛁';
      }
    } catch (x) { desc = ''; }

    html += `
      <div class="timeline-item">
        <div class="timeline-icon ${getTimelineIconClass(e.type)}">${getTimelineIconEmoji(e.type)}</div>
        <div class="timeline-body">
          <strong>${getTimelineTitle(e.type, dogName)}</strong>
          <div class="timeline-date">${e.date}</div>
          <div class="timeline-desc">${escHtml(desc)}</div>
          ${e.photo ? '<div class="timeline-photo"><img src="' + escHtml(e.photo) + '" alt="photo" onclick="viewTimelinePhoto(\'' + escHtml(e.photo) + '\')" class="tl-photo-thumb" /></div>' : ''}
        </div>
        <div class="timeline-actions">
          <button class="timeline-btn timeline-btn-more" title="更多操作" onclick="toggleTimelineMenu(event, ${e.id}, ${e.type === '异常行为' ? 'true' : 'false'})">⋯</button>
          <div class="timeline-menu" id="timelineMenu_${e.id}" style="display:none;">
            ${e.type !== '异常行为' ? '<button class="timeline-menu-item" onclick="uploadRecordPhoto(' + e.id + ')">📷 上传照片</button>' : ''}
            <button class="timeline-menu-item" onclick="editEvent(${e.id})">✏️ 编辑</button>
            <button class="timeline-menu-item timeline-menu-item-del" onclick="deleteEvent(${e.id})">🗑 删除</button>
          </div>
        </div>
      </div>`;
  }
  return html;
}

function toggleTimelineMenu(event, eventId, isAbnormal) {
  event.stopPropagation();
  // 关闭其他打开的菜单
  document.querySelectorAll('.timeline-menu').forEach(m => {
    if (m.id !== 'timelineMenu_' + eventId) m.style.display = 'none';
  });
  const menu = document.getElementById('timelineMenu_' + eventId);
  if (menu) {
    menu.style.display = menu.style.display === 'none' ? 'block' : 'none';
  }
}

// 点击页面其他位置关闭所有时间轴菜单
document.addEventListener('click', function(e) {
  if (!e.target.closest('.timeline-actions')) {
    document.querySelectorAll('.timeline-menu').forEach(m => m.style.display = 'none');
  }
});

function updateFilterCounts() {
  const filters = document.querySelectorAll('.tl-filter');
  const counts = {};
  counts['全部'] = _allEvents.length;
  for (const e of _allEvents) {
    counts[e.type] = (counts[e.type] || 0) + 1;
  }
  filters.forEach(f => {
    const key = f.dataset.filter;
    const cnt = counts[key] || 0;
    if (key === '全部') {
      f.textContent = '全部' + (cnt > 0 ? ` (${cnt})` : '');
    } else {
      const emoji = f.textContent.split(' ')[0];
      f.textContent = emoji + ' ' + key + (cnt > 0 ? ` (${cnt})` : '');
    }
  });
}

// 时间线分类筛选点击
document.addEventListener('click', function(e) {
  if (e.target.classList.contains('tl-filter')) {
    document.querySelectorAll('.tl-filter').forEach(f => f.classList.remove('active'));
    e.target.classList.add('active');
    _currentFilter = e.target.dataset.filter;
    let dogName = (_cachedDog && _cachedDog.name) || '汪星人';
    renderTimeline(dogName);
  }
});

// ---- 建档弹窗逻辑 ----

// 初始化生日三连下拉选择器（年/月/日）
function initBirthdaySelects() {
  // 默认设置为一年前的今天
  const d = new Date();
  d.setFullYear(d.getFullYear() - 1);
  const input = $('mBirthday');
  if (input) input.value = d.toISOString().slice(0, 10);
}

// 弹窗建档提交
$('btnModalCreate').addEventListener('click', async function() {
  const btn = this;
  const name = $('mName').value.trim();
  const breed = $('mBreed').value;
  const birthday = $('mBirthday').value;
  const weight = $('mWeight').value.trim();
  const neutered = $('mNeutered').value;
  const allergies = $('mAllergies').value.trim();
  const gender = $('mGender').value;
  const diseases = $('mDiseases').value.trim();

  if (!name || !breed) {
    showToast('汪汪，名字和品种是必填的哦，主人再检查一下～', true);
    return;
  }
  if (new Date(birthday) > new Date()) {
    showToast('生日不能是未来的日子哦，主人～', true);
    return;
  }
  if (!$('mDisclaimerAgree').checked) {
    showToast('请先阅读并勾选免责声明哦，主人～', true);
    return;
  }

  const homeDate = $('mHomeDate').value || null;

  btn.disabled = true;
  btn.textContent = '正在建档...';
  try {
    const r = await api('/api/dog', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, breed, birthday, weight, neutered, allergies, gender: gender || null, diseases: diseases || null, home_date: homeDate }),
    });
    showToast(r.message);
    // 隐藏弹窗，显示主界面
    $('modalOverlay').style.display = 'none';
    $('mainContent').classList.remove('main-hidden');
    loadProfile();
    loadTimeline();
    loadToday();
    // 如果有上传照片，建档后自动上传
    const photoFile = $('mPhoto').files[0];
    if (photoFile) {
      try {
        await uploadDogPhoto(photoFile);
        loadProfile();
      } catch (pe) { /* 照片上传失败不影响建档流程 */ }
    }
  } catch (e) {
    showToast(e.message || '汪汪，信号被狗吃了，点我重试～', true);
  }
  btn.disabled = false;
  btn.textContent = '🐾 完成建档，开启汪生！';
});

// ---- 编辑档案弹窗逻辑 ----
function setEditBirthday(dateStr) {
  const input = $('eBirthday');
  if (input) input.value = dateStr;
}

// 打开编辑弹窗（首页编辑按钮）
const _btnEditProfile = $('btnEditProfile');
if (_btnEditProfile) _btnEditProfile.addEventListener('click', async function() {
  try {
    const dog = await api('/api/dog');
    // 预填所有字段
    $('eName').value = dog.name;
    $('eBreed').value = dog.breed;
    $('eWeight').value = dog.weight || '';
    $('eNeutered').value = dog.neutered || '未知';
    $('eAllergies').value = dog.allergies || '';
    $('eGender').value = dog.gender || '';
    $('eDiseases').value = dog.diseases || '';
    $('eHomeDate').value = dog.home_date || '';
    // 预填生日
    $('eBirthday').value = dog.birthday;
    // 显示弹窗
    $('editModalOverlay').style.display = 'flex';
  } catch (e) {
    showToast('汪汪，读取档案失败了，点我重试～', true);
  }
});

// 取消编辑
$('btnEditCancel').addEventListener('click', function() {
  $('editModalOverlay').style.display = 'none';
});
$('editModalOverlay').addEventListener('click', function(e) {
  if (e.target === this) $('editModalOverlay').style.display = 'none';
});

// 保存编辑
$('btnEditSave').addEventListener('click', async function() {
  const btn = this;
  const name = $('eName').value.trim();
  const breed = $('eBreed').value;
  const birthday = $('eBirthday').value;
  const weight = $('eWeight').value.trim();
  const neutered = $('eNeutered').value;
  const allergies = $('eAllergies').value.trim();
  const gender = $('eGender').value;
  const diseases = $('eDiseases').value.trim();
  const homeDate = $('eHomeDate').value || null;

  if (!name || !breed) {
    showToast('汪汪，名字和品种是必填的哦，主人再检查一下～', true);
    return;
  }
  if (new Date(birthday) > new Date()) {
    showToast('生日不能是未来的日子哦，主人～', true);
    return;
  }

  btn.disabled = true;
  btn.textContent = '正在保存...';
  try {
    const r = await api('/api/dog', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, breed, birthday, weight, neutered, allergies, gender: gender || null, diseases: diseases || null, home_date: homeDate }),
    });
    showToast(r.message);
    $('editModalOverlay').style.display = 'none';
    loadProfile();
    loadPhotoGallery();
    loadTimeline();
    loadToday();
    // 检查是否有从任务跳转来的待完成操作
    setTimeout(() => checkPendingTask(), 300);
    // 如果有上传照片，编辑后自动上传
    const photoFile = $('ePhoto').files[0];
    if (photoFile) {
      try {
        await uploadDogPhoto(photoFile);
        loadProfile();
      } catch (pe) { /* 照片上传失败不影响编辑流程 */ }
    }
  } catch (e) {
    showToast(e.message || '汪汪，信号被狗吃了，点我重试～', true);
  }
  btn.disabled = false;
  btn.textContent = '💾 保存更新';
});

// ---- 动态欢迎语 ----
function updateGreeting(dogName) {
  const hour = new Date().getHours();
  let greeting;
  if (hour >= 5 && hour < 12) greeting = '☀️ 早安，主人！';
  else if (hour >= 12 && hour < 18) greeting = '🌤️ 午安，主人！';
  else if (hour >= 18 && hour < 22) greeting = '🌙 晚安，主人！';
  else greeting = '🌙 月亮都睡着啦，主人也该休息了～';
  // 知道性别和名字时加入称呼
  if (dogName && _cachedDog && _cachedDog.gender) {
    const title = _cachedDog.gender === 'male' ? '小王子' : '小公主';
    greeting = dogName + title + '说：' + greeting;
  } else if (dogName) {
    greeting = dogName + '说：' + greeting;
  }
  const el = $('todayGreeting');
  if (el) { el.textContent = greeting; }
  // Fallback: 如果状态条存在，更新状态条标题
  const statusInfo = $('statusBarInfo');
  if (statusInfo && _cachedDog) {
    const age = calcAge(_cachedDog.birthday);
    updateTodayDashboard(_cachedDog, age);
  }
}

// ---- 更新功能入口角标 ----
function updateBadges(data) {
  if (!data) return;
  // 记录事件角标：有提醒时显示红点
  const badgeRecord = $('badgeRecord');
  if (badgeRecord) {
    if (data.pending_actions > 0) {
      badgeRecord.style.display = '';
    } else {
      badgeRecord.style.display = 'none';
    }
  }
  // 保健品角标：有活跃保健品时显示红点
  const badgeSupp = $('badgeSupplement');
  if (badgeSupp) {
    if (data.active_supplements_count > 0) {
      badgeSupp.style.display = '';
    } else {
      badgeSupp.style.display = 'none';
    }
  }
}

// ---- 子页面导航 ----
function navigateTo(page) {
  const subPages = document.querySelectorAll('.sub-page');
  subPages.forEach(p => p.style.display = 'none');
  const homePage = $('page-home');

  if (page === 'home') {
    if (homePage) homePage.style.display = '';
    loadToday();
    // 刷新状态条数据
    if (_cachedDog) { updateTodayDashboard(_cachedDog, calcAge(_cachedDog.birthday)); }
    // 检查是否有从其他页面带回的待完成任务
    setTimeout(() => checkPendingTask(), 500);
    return;
  }

  // 进入子页面：隐藏首页
  if (homePage) homePage.style.display = 'none';

  const targetPage = $('page-' + page);
  if (targetPage) {
    targetPage.style.display = '';
    targetPage.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  // 按需加载子页面数据
  if (page === 'record') {
    loadTimeline();
  } else if (page === 'diet') {
    loadDietCard();
  } else if (page === 'badges') {
    loadBadgeWall();
  } else if (page === 'supplement') {
    loadSupplements();
  } else if (page === 'weight') {
    loadWeightPage();
  } else if (page === 'reminders') {
    loadRemindersPage();
  }
}

// ---- 大事记子页面时间线 ----
// ---- 荣誉勋章墙 ----
let _badgeData = null;

async function loadBadgeWall() {
  if (!_cachedDog) return;
  try {
    const data = await api('/api/badges?pet_id=' + _cachedDog.id);
    _badgeData = data;

    // 情绪安抚区
    const emotionCard = $('badgeEmotionCard');
    const emptyState = $('badgeEmpty');
    const wall = $('badgeWall');

    if (data.total_unlocked === 0 && data.badges.length === 0) {
      if (emotionCard) emotionCard.style.display = 'none';
      if (wall) wall.style.display = 'none';
      if (emptyState) emptyState.style.display = '';
      return;
    }
    if (emotionCard) emotionCard.style.display = '';
    if (wall) wall.style.display = '';
    if (emptyState) emptyState.style.display = 'none';

    // 更新情绪区
    const nameEl = $('badgeEmotionName');
    if (nameEl) nameEl.textContent = _cachedDog.name || '狗狗';
    const daysEl = $('badgeEmotionDays');
    if (daysEl && _cachedDog.created_at) {
      const companionDays = Math.floor((new Date() - new Date(_cachedDog.created_at)) / (1000 * 60 * 60 * 24));
      daysEl.textContent = '已经一起走过 ' + companionDays + ' 天啦';
    }
    const countEl = $('badgeEmotionCount');
    if (countEl) countEl.textContent = '✨ 我们已经收集了 ' + data.total_unlocked + ' 枚健康小勋章啦';
    const textEl = $('badgeEmotionText');
    if (textEl) textEl.textContent = data.total_unlocked > 0 ? '这些不是比赛的奖牌，是我和主人一起努力生活的回忆。' : '每一枚勋章，都是我们一起认真生活的证据。';

    // 头像
    if (_cachedDog.photo) {
      const avatarEl = $('badgeEmotionAvatar');
      if (avatarEl) avatarEl.innerHTML = '<img src="/photos/' + _cachedDog.photo + '" style="width:100%;height:100%;border-radius:50%;object-fit:cover;" />';
    }

    // Tab 切换事件
    document.querySelectorAll('.badge-story-tab').forEach(tab => {
      tab.onclick = function() {
        document.querySelectorAll('.badge-story-tab').forEach(t => t.classList.remove('active'));
        this.classList.add('active');
        renderBadgeWall(this.dataset.cat);
      };
    });

    // 默认渲染全部
    renderBadgeWall('all');
  } catch (e) {
    console.error('loadBadgeWall error:', e);
  }
}

function renderBadgeWall(category) {
  if (!_badgeData || !_badgeData.badges) return;
  const wall = $('badgeWall');
  if (!wall) return;

  const categoryNames = {
    '第一次': '🐣 我们的第一次',
    '守护者': '🛡️ 守护者联盟',
    '健康里程碑': '🌱 成长里程碑',
  };

  // 按分类过滤
  let badges = _badgeData.badges;
  if (category && category !== 'all') {
    badges = badges.filter(b => b.category === category);
  }
  if (badges.length === 0) {
    wall.innerHTML = '<div style="text-align:center;color:var(--muted);padding:20px;font-size:0.88em;">这一组的小纪念还在慢慢收集，按我们的节奏来～</div>';
    return;
  }

  // 按分类分组渲染
  let html = '';
  const categories = category === 'all' ? ['第一次', '守护者', '健康里程碑'] : [category];
  categories.forEach(cat => {
    const catBadges = badges.filter(b => b.category === cat);
    if (catBadges.length === 0) return;
    if (category === 'all') {
      html += '<div class="badge-wall-cat-title" style="grid-column:1/-1;font-size:0.88em;font-weight:700;color:var(--brown);margin:4px 0 2px;">' + (categoryNames[cat] || cat) + '</div>';
    }
    catBadges.forEach(b => {
      const dateStr = b.date || '';
      // 照片优先级：勋章对应事件照片 > 狗狗头像 > 占位符
      const badgePhoto = b.photo || (_cachedDog && _cachedDog.photo) || null;
      let iconHtml = '';
      if (b.unlocked && badgePhoto) {
        iconHtml = '<div class="badge-memento-photo-area">' +
          '<div class="badge-memento-icon">' +
          '<img src="/photos/' + badgePhoto + '" alt="' + escHtml(b.name) + '" />' +
          '</div>' +
          '<span class="badge-memento-pin">' + b.icon + '</span>' +
          '</div>';
      } else if (b.unlocked) {
        iconHtml = '<div class="badge-memento-photo-area">' +
          '<div class="badge-memento-icon">' +
          '<div class="badge-memento-icon-placeholder">' + b.icon + '</div>' +
          '</div>' +
          '<span class="badge-memento-pin">🐾</span>' +
          '</div>';
      } else {
        iconHtml = '<div class="badge-memento-photo-area">' +
          '<div class="badge-memento-icon">' +
          '<div class="badge-memento-icon-placeholder">' + b.icon + '</div>' +
          '</div>' +
          '<span class="badge-memento-pin">🔒</span>' +
          '</div>';
      }
      html += '<div class="badge-memento ' + (b.unlocked ? 'unlocked' : 'locked') + '" ' +
        (b.unlocked ? 'data-badge-name="' + escHtml(b.name) + '" data-badge-icon="' + b.icon + '" data-badge-date="' + dateStr + '" data-badge-cat="' + b.category + '" onclick="openBadgeDetailFromEl(this)"' : '') + '>' +
        iconHtml +
        '<span class="badge-memento-name">' + escHtml(b.name) + '</span>' +
        '<span class="badge-memento-date">' + (b.unlocked ? dateStr : '未来可期') + '</span>' +
        '</div>';
    });
  });
  wall.innerHTML = html;
}

// 勋章详情文案
const _badgeDetailStories = {
  '初来乍到':     { story: '我们一起跨进了同一扇家门。从那天起，你就是我的全世界啦。', woof: '主人，谢谢你给了我一个家。我会用摇尾巴把每一天都填满快乐～' },
  '第一针疫苗':   { story: '我们一起完成了第一针疫苗。那天我可能有一点点紧张，但主人一直陪着我，我就勇敢多啦。', woof: '主人，谢谢你带我去保护自己。我们都是小勇士！' },
  '第一次驱虫':   { story: '我们一起完成了第一次驱虫，肚肚安心啦。这对我的健康特别重要。', woof: '虽然药药不好吃，但我知道主人是为了让我更健康呀。' },
  '第一次洗澡':   { story: '我们第一次洗香香！水花四溅，主人也被我甩了一身，但我们都好开心。', woof: '毛蓬蓬的我是不是特别帅气？主人一边吹毛一边夸我呢～' },
  '到家第一天':   { story: '从那天开始，这里不再只是房子，而是我们的家。', woof: '主人的味道，就是家的味道。从那一天起，我就在心里给主人留了最大的位置。' },
  '免疫完成':     { story: '我们一起完成了3次疫苗接种，建起了坚固的免疫防线。主人为我的健康操了好多心。', woof: '有主人的守护，我可以放心地探索这个美丽的世界啦！' },
  '驱虫达标':     { story: '我们完成了6次驱虫，把寄生虫牢牢挡在门外。这是耐心和坚持换来的健康。', woof: '主人的每一次提醒和记录，都是在认真守护我。我都记得哦～' },
  '洁齿坚持':     { story: '我们一起坚持了30天的牙齿护理。每一次刷牙，都是主人在认真守护我的笑容。', woof: '虽然牙刷有点奇怪，但我知道主人是为了让我更健康呀。' },
  '肠胃稳定':     { story: '我们度过了连续60天肠胃无恙的安稳日子。从之前的波折到现在的平稳，主人都陪着我。', woof: '肚肚舒舒服服的感觉真好！谢谢主人帮我找到适合我的生活方式～' },
  '体重管理':     { story: '我们3个月保持了理想体重。这不是数字的变化，是每一天认真喂养和陪伴的结果。', woof: '主人你看，我们一起坚持的每一天，都在我健康的身体上留下了痕迹～' },
  '生日快乐':     { story: '我们一起吹了生日蜡烛。又长大一岁啦，但主人陪着我，长大就不怕了。', woof: '谢谢主人记得这个特别的日子。我们要一起过好多好多个生日！' },
  '绝育勇敢':     { story: '我们一起经历了成长的重要一步。那天主人比我还紧张，但我们一起撑过来了。', woof: '恢复期的时候，主人一直在旁边摸我的头。那是我最安心的时刻～' },
  '百日相伴':     { story: '我们已经互相陪伴了100天。从陌生到熟悉，从小心翼翼到互相信任，这些日子都值得被纪念。', woof: '主人，我已经把这里当成家，也把你当成全世界啦。100天只是一个开始！' },
  '健康大满贯':   { story: '我们集齐了全部守护者系列勋章！这是主人和我一起完成的一件了不起的事。', woof: '主人你看，我们真的一起做到了好多事呀。每一个勋章都是你爱我的证据～' },
  '守护之星':     { story: '我们攒下了30个爪印。每一个爪印都是一天认真照护的记录，是主人爱我的痕迹。', woof: '30个爪印，30天被主人认真照顾。我是被爱包围的小狗，谢谢主人一直守护我～' },
};

function openBadgeDetail(name, icon, dateStr, category) {
  const overlay = $('badgeDetailOverlay');
  if (!overlay) return;
  $('badgeDetailIcon').textContent = icon;
  $('badgeDetailName').textContent = name;
  const detail = _badgeDetailStories[name] || { story: '这是我们一起度过的一段美好时光。', woof: '能和主人一起经历这一切，就是我最大的幸福～' };
  $('badgeDetailStory').textContent = detail.story;
  $('badgeDetailDate').textContent = dateStr ? '纪念日：' + dateStr : '';
  $('badgeDetailWoof').textContent = '🐾 ' + detail.woof;
  overlay.style.display = 'flex';
}

function closeBadgeDetail() {
  $('badgeDetailOverlay').style.display = 'none';
}

function openBadgeDetailFromEl(el) {
  openBadgeDetail(el.dataset.badgeName, el.dataset.badgeIcon, el.dataset.badgeDate, el.dataset.badgeCat);
}

$('badgeDetailOverlay')?.addEventListener('click', function(e) {
  if (e.target === this) closeBadgeDetail();
});

function showBadgeUnlockToast(badge) {
  if (!badge || !badge.name) return;
  const toast = document.createElement('div');
  toast.className = 'badge-unlock-toast';
  toast.textContent = '🐾 汪！我们又多了一枚小纪念——「' + badge.name + '」' + badge.icon + ' 谢谢主人认真照顾我。';
  document.body.appendChild(toast);
  setTimeout(() => { toast.remove(); }, 4000);
  const badgePage = $('page-badges');
  if (badgePage && badgePage.style.display !== 'none') {
    loadBadgeWall();
  }
}

function promptHealthPhotoUpload(eventId, eventType, eventDate) {
  // 创建健康照上传弹窗
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.style.cssText = 'display:flex;z-index:9999;';
  overlay.innerHTML = `<div class="modal-card" style="max-width:400px;text-align:center;">
    <div class="modal-header"><div class="modal-logo" style="font-size:2em;">📸</div>
      <h2>记录这份勇敢吧～</h2></div>
    <div class="modal-body"><p style="color:var(--muted);margin-bottom:12px;">主人，帮我拍一张「${eventType}」纪念照，<br/>放进我的健康成长相册吧！</p>
      <input type="file" id="healthPhotoFileInput" accept="image/jpeg,image/png" style="display:block;margin:0 auto 12px;" />
      <div id="healthPhotoUploadStatus" style="font-size:0.85em;color:var(--muted);"></div>
    </div>
    <div class="modal-actions">
      <button class="btn btn-outline" id="btnSkipHealthPhoto">下次吧</button>
      <button class="btn btn-primary" id="btnUploadHealthPhoto">📸 上传纪念照</button>
    </div>
  </div>`;
  document.body.appendChild(overlay);

  const close = () => overlay.remove();
  overlay.addEventListener('click', function(e) { if (e.target === overlay) close(); });

  const skipBtn = overlay.querySelector('#btnSkipHealthPhoto');
  skipBtn.addEventListener('click', close);

  const uploadBtn = overlay.querySelector('#btnUploadHealthPhoto');
  const fileInput = overlay.querySelector('#healthPhotoFileInput');
  const statusEl = overlay.querySelector('#healthPhotoUploadStatus');

  uploadBtn.addEventListener('click', async () => {
    const file = fileInput.files[0];
    if (!file) { statusEl.textContent = '请先选择一张照片哦～'; return; }
    if (!['image/jpeg','image/png','image/jpg'].includes(file.type)) { statusEl.textContent = '只支持 JPG/PNG 格式哦～'; return; }
    if (file.size > 2*1024*1024) { statusEl.textContent = '图片太大了（不能超过2MB）～'; return; }
    statusEl.textContent = '正在上传...';
    try {
      const formData = new FormData();
      formData.append('pet_id', _cachedDog.id);
      formData.append('event_type', eventType);
      formData.append('event_date', eventDate);
      formData.append('label', eventType);
      formData.append('file', file);
      if (eventId) formData.append('event_id', eventId);
      const resp = await fetch('/api/dog/health_photo', { method: 'POST', body: formData });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || '上传失败');
      showToast(data.message);
      if (data.new_badges && data.new_badges.length > 0) {
        data.new_badges.forEach(b => showBadgeUnlockToast(b));
      }
      close();
      loadProfile();
      loadTimeline();
    } catch (e) {
      statusEl.textContent = '上传失败：' + (e.message || '未知错误');
    }
  });
}

// 处理 API 响应中的新勋章
function handleNewBadges(newBadges) {
  if (newBadges && newBadges.length > 0) {
    newBadges.forEach(b => showBadgeUnlockToast(b));
  }
}

// ---- 时间线照片操作 ----
function uploadSymptomPhoto(eventId) {
  // 仅为异常行为事件上传症状照片，不入健康相册
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = 'image/jpeg,image/png';
  input.onchange = async function() {
    const file = input.files[0];
    if (!file) return;
    if (!['image/jpeg','image/png','image/jpg'].includes(file.type)) { showToast('只支持 JPG/PNG 格式哦～', true); return; }
    if (file.size > 2*1024*1024) { showToast('图片太大了（不能超过2MB）～', true); return; }
    showToast('📋 正在上传症状照片...');
    try {
      const formData = new FormData();
      formData.append('file', file);
      const resp = await fetch('/api/records/' + eventId + '/photo?symptom_only=true', { method: 'POST', body: formData });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || '上传失败');
      showToast(data.message);
      loadTimeline();
    } catch (e) {
      showToast('上传失败：' + (e.message || '未知错误'), true);
    }
  };
  input.click();
}

function uploadRecordPhoto(eventId) {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = 'image/jpeg,image/png';
  input.onchange = async function() {
    const file = input.files[0];
    if (!file) return;
    if (!['image/jpeg','image/png','image/jpg'].includes(file.type)) { showToast('只支持 JPG/PNG 格式哦～', true); return; }
    if (file.size > 2*1024*1024) { showToast('图片太大了（不能超过2MB）～', true); return; }
    showToast('📸 正在上传纪念照...');
    try {
      const formData = new FormData();
      formData.append('file', file);
      const resp = await fetch('/api/records/' + eventId + '/photo', { method: 'POST', body: formData });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || '上传失败');
      showToast(data.message);
      loadTimeline();
      loadProfile();
    } catch (e) {
      showToast('上传失败：' + (e.message || '未知错误'), true);
    }
  };
  input.click();
}

function viewTimelinePhoto(url) {
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.style.cssText = 'display:flex;z-index:9999;';
  overlay.innerHTML = '<div class="modal-card" style="max-width:90vw;max-height:90vh;padding:8px;background:transparent;box-shadow:none;"><img src="' + url + '" style="max-width:100%;max-height:85vh;border-radius:12px;" /><button onclick="this.closest(\'.modal-overlay\').remove()" style="position:absolute;top:8px;right:12px;width:32px;height:32px;border-radius:50%;background:rgba(0,0,0,0.5);color:#fff;border:none;font-size:1.2em;cursor:pointer;">✕</button></div>';
  overlay.addEventListener('click', function(e) { if (e.target === overlay) overlay.remove(); });
  document.body.appendChild(overlay);
}

// ============================================================
// 第一层习惯层 JS：签到、测验、任务、Toast
// ============================================================

// ---- 优化版 Toast ----
function showToast(msg, isError) {
  let container = document.querySelector('.toast-container');
  if (!container) {
    container = document.createElement('div');
    container.className = 'toast-container';
    document.body.appendChild(container);
  }
  const el = document.createElement('div');
  el.className = 'toast-msg';
  el.textContent = msg;
  if (isError) { el.style.background = '#D94A4A'; }
  container.appendChild(el);
  setTimeout(() => { if (el.parentNode) el.remove(); }, 3000);
}

// ---- 加载签到状态 ----
async function loadCheckinStatus() {
  try {
    const data = await api('/api/checkin/status?pet_id=' + (_cachedDog?.id || 1));
    // 同步爪印积分到缓存
    if (_cachedDog) _cachedDog.paw_points = data.paw_points || 0;

    // 爪印积分展示
    const ptsEl = $('pawPointsDisplay');
    if (ptsEl) {
      ptsEl.textContent = `🐾 已收集 ${data.paw_points || 0} 枚爪印`;
      ptsEl.title = '点击查看爪印获取记录';
      ptsEl.onclick = showPawHistory;
    }
  } catch (e) { /* 静默处理 */ }
}

// ---- 执行签到 ----
async function doCheckIn() {
  try {
    const data = await api('/api/checkin?pet_id=' + (_cachedDog?.id || 1), { method: 'POST' });
    if (data.already_checked) {
      showToast('今天已经打过卡啦，明天再来吧～🐾');
      return;
    }
    let msg = `签到成功！连续第 ${data.streak} 天`;
    // 计算离下一个里程碑还有几天
    const milestones = [7, 14, 30, 60];
    for (const m of milestones) {
      if (data.streak < m) {
        msg += `，再坚持 ${m - data.streak} 天就能解锁新勋章啦～`;
        break;
      }
    }
    if (data.milestone) {
      msg = `🎉 太厉害了！你解锁了 ${data.milestone}！连续签到 ${data.streak} 天！`;
    }
    showToast(msg);
    // 处理新勋章
    if (data.new_badges && data.new_badges.length > 0) {
      handleNewBadges(data.new_badges);
    }
    loadCheckinStatus();
  } catch (e) {
    showToast(e.message || '签到失败，等会再试试吧～', true);
  }
}

// ---- 彩蛋测验 ----
let _easterQuizData = null;

// ---- 彩蛋入口可见性（每日随机出现在四个功能页面之一） ----
const QUIZ_LOCATIONS = ['cardSuppHome'];
const QUIZ_HOME_BADGE_IDS = {
  cardSuppHome: 'badgePawSupplement',
};
const QUIZ_PAGE_ENTRY_IDS = {
  cardSuppHome: 'easterEggEntry',
};

function getDailyQuizLocation() {
  const today = new Date();
  const seed = today.getFullYear() * 10000 + (today.getMonth() + 1) * 100 + today.getDate() + (_cachedDog?.id || 1) * 7;
  return QUIZ_LOCATIONS[seed % QUIZ_LOCATIONS.length];
}

function syncQuizEntryVisibility() {
  if (!_cachedDog) return;
  // 已答过 → 显示今日知识点
  if (sessionStorage.getItem('pawlife_quiz_done') === new Date().toDateString()) {
    const explanation = sessionStorage.getItem('pawlife_quiz_explanation') || '今天已经考过我啦，明天再来吧～';
    showQuizExplanationForToday(explanation);
    return;
  }
  // 今日未答 → 在随机位置显示彩蛋入口
  const target = getDailyQuizLocation();
  // 主页爪印角标
  Object.values(QUIZ_HOME_BADGE_IDS).forEach(id => {
    const el = $(id); if (el) el.style.display = 'none';
  });
  const homeBadge = $(QUIZ_HOME_BADGE_IDS[target]);
  if (homeBadge) homeBadge.style.display = '';
  // 子页面彩蛋入口
  Object.values(QUIZ_PAGE_ENTRY_IDS).forEach(id => {
    const el = $(id); if (el) el.style.display = 'none';
  });
  const pageEntry = $(QUIZ_PAGE_ENTRY_IDS[target]);
  if (pageEntry) { pageEntry.style.display = ''; pageEntry.classList.remove('quiz-answered'); }
}

function hideQuizEntryForToday() {
  // 隐藏主页所有爪印角标
  Object.values(QUIZ_HOME_BADGE_IDS).forEach(id => {
    const el = $(id); if (el) el.style.display = 'none';
  });
  // 隐藏所有子页面彩蛋入口
  Object.values(QUIZ_PAGE_ENTRY_IDS).forEach(id => {
    const el = $(id); if (el) el.style.display = 'none';
  });
  sessionStorage.setItem('pawlife_quiz_done', new Date().toDateString());
}

function showQuizExplanationForToday(explanation) {
  // 隐藏主页所有爪印角标（回答后不显示入口）
  Object.values(QUIZ_HOME_BADGE_IDS).forEach(id => {
    const el = $(id); if (el) el.style.display = 'none';
  });
  // 在今日随机位置显示知识点
  const target = getDailyQuizLocation();
  const entryId = QUIZ_PAGE_ENTRY_IDS[target];
  // 先隐藏所有入口
  Object.values(QUIZ_PAGE_ENTRY_IDS).forEach(id => {
    const el = $(id); if (el) el.style.display = 'none';
  });
  const entry = $(entryId);
  if (!entry) return;
  entry.style.display = '';
  entry.classList.add('quiz-answered');
  entry.onclick = null;
  const pawEl = entry.querySelector('.easter-paw');
  const labelEl = entry.querySelector('.easter-label');
  if (pawEl) pawEl.textContent = '💡';
  if (labelEl) labelEl.textContent = explanation;
}

async function loadEasterQuiz() {
  // 检查是否今日已答题
  if (sessionStorage.getItem('pawlife_quiz_done') === new Date().toDateString()) {
    const explanation = sessionStorage.getItem('pawlife_quiz_explanation') || '今天已经考过我啦，明天再来吧～';
    showQuizExplanationForToday(explanation);
    return;
  }
  try {
    _easterQuizData = await api('/api/quiz?pet_id=' + (_cachedDog?.id || 1));
    if (_easterQuizData.already_answered) {
      sessionStorage.setItem('pawlife_quiz_done', new Date().toDateString());
      if (_easterQuizData.explanation) {
        sessionStorage.setItem('pawlife_quiz_explanation', _easterQuizData.explanation);
      }
      const explanation = _easterQuizData.explanation || '今天已经考过我啦，明天再来吧～';
      showQuizExplanationForToday(explanation);
      $('easterEggModal').style.display = 'none';
      return;
    }
    $('eqQuestion').textContent = _easterQuizData.question;
    let html = '';
    for (let i = 0; i < _easterQuizData.options.length; i++) {
      html += `<button class="quiz-option" onclick="answerEasterQuiz(${i})">${String.fromCharCode(65 + i)}. ${escHtml(_easterQuizData.options[i])}</button>`;
    }
    $('eqOptions').innerHTML = html;
    $('eqFeedback').style.display = 'none';
  } catch (e) {
    $('eqQuestion').textContent = '彩蛋还没准备好，明天再来看看吧～';
  }
}

function openEasterEgg() {
  // 今日已答过 → 不再打开弹窗
  if (sessionStorage.getItem('pawlife_quiz_done') === new Date().toDateString()) {
    return;
  }
  $('easterEggModal').style.display = 'flex';
  loadEasterQuiz();
}

function closeEasterEgg() {
  $('easterEggModal').style.display = 'none';
}

function answerEasterQuiz(chosen) {
  if (!_easterQuizData) return;
  const correct = _easterQuizData.answer;
  const feedbackDiv = $('eqFeedback');
  const options = document.querySelectorAll('#eqOptions .quiz-option');

  for (const opt of options) { opt.disabled = true; }

  // 存储解释，标记今日已答
  sessionStorage.setItem('pawlife_quiz_explanation', _easterQuizData.explanation);
  sessionStorage.setItem('pawlife_quiz_done', new Date().toDateString());
  // 将彩蛋入口变为今日知识点
  showQuizExplanationForToday(_easterQuizData.explanation);

  if (chosen === correct) {
    feedbackDiv.innerHTML = '<span style="color:#2E7D32;">✅ 主人好懂我！+2 爪印🐾</span><div class="quiz-explain">💡 ' + escHtml(_easterQuizData.explanation) + '</div>';
    api('/api/quiz/complete?pet_id=' + (_cachedDog?.id || 1) + '&correct=1', { method: 'POST' }).then(() => {
      loadCheckinStatus();
    }).catch(() => {});
  } else {
    options[chosen].classList.add('wrong-answer');
    feedbackDiv.innerHTML = '<span style="color:#C62828;">❌ 没关系，现在你更懂我啦～</span><div class="quiz-explain">💡 ' + escHtml(_easterQuizData.explanation) + '</div>';
  }
  options[correct].classList.add('correct-answer');
  feedbackDiv.style.display = 'block';
  _easterQuizData = null; // 防止重复答题
}

// ---- 加载每日小任务（新版：带 action_type） ----
let _currentTaskData = null;

async function loadTask() {
  try {
    const data = await api('/api/task?pet_id=' + (_cachedDog?.id || 1));
    _currentTaskData = data;
    $('taskBody').textContent = '📋 ' + data.task;
    $('taskThanks').style.display = 'none';

    const btn = $('taskActionBtn');
    if (data.done) {
      // 今日已完成
      btn.className = 'btn task-action-btn done';
      btn.textContent = '✅ 已完成';
      btn.onclick = null;
      $('taskThanks').textContent = '🐾 ' + data.thanks;
      $('taskThanks').style.display = 'block';
      $('taskCard').classList.add('done');
    } else {
      btn.className = 'btn task-action-btn';
      btn.textContent = data.button_text || '去完成';
      btn.onclick = doTaskAction;
      $('taskCard').classList.remove('done');
    }
  } catch (e) {
    $('taskBody').textContent = '任务加载中，等等再来看～';
  }
}

// ---- 执行任务操作 ----
function doTaskAction() {
  if (!_currentTaskData || _currentTaskData.done) return;
  const action = _currentTaskData.action_type;

  if (action === 'navigate_weight') {
    // 跳转到档案页面，并标记任务上下文
    localStorage.setItem('pendingTaskId', _currentTaskData.task_id);
    localStorage.setItem('pendingTaskThanks', _currentTaskData.thanks);
    navigateTo('profile');
    // 滚动到体重区域（延迟执行）
    setTimeout(() => {
      const el = document.getElementById('profileWeightHint');
      if (el) { el.scrollIntoView({ behavior: 'smooth' }); el.style.background = '#FFF9C4'; setTimeout(() => el.style.background = '', 2000); }
    }, 400);
  } else if (action === 'navigate_photo') {
    // 触发照片上传
    const input = $('dogPhotoInput');
    if (input) { input.click(); }
    // 照片上传后会触发 loadProfile，在那里检查 pendingTaskId
    localStorage.setItem('pendingTaskId', _currentTaskData.task_id);
    localStorage.setItem('pendingTaskThanks', _currentTaskData.thanks);
  } else {
    // check_confirm：弹出确认框
    _confirmTaskComplete(_currentTaskData);
  }
}

// ---- 确认完成任务（check_confirm 类型） ----
let _pendingTaskConfirm = null;

function _confirmTaskComplete(taskData) {
  _pendingTaskConfirm = taskData;
  $('taskConfirmTask').textContent = '📋 ' + taskData.task;
  $('taskConfirmOverlay').style.display = 'flex';
}

function closeTaskConfirm() {
  _pendingTaskConfirm = null;
  $('taskConfirmOverlay').style.display = 'none';
}

function confirmAndCompleteTask() {
  if (_pendingTaskConfirm) {
    const taskData = _pendingTaskConfirm;
    closeTaskConfirm();
    _markTaskDone(taskData.task_id, taskData.thanks);
  }
}

// ---- 标记任务完成并调用后端 ----
async function _markTaskDone(taskId, thanksText) {
  try {
    const data = await api('/api/task/complete?pet_id=' + (_cachedDog?.id || 1) + '&task_id=' + encodeURIComponent(taskId), {
      method: 'POST',
    });
    if (data.already_done) {
      showToast('今天已经完成过这个任务啦，明天再来吧～🐾');
      return;
    }

    // 更新UI
    const btn = $('taskActionBtn');
    btn.className = 'btn task-action-btn done';
    btn.textContent = '✅ 已完成';
    btn.onclick = null;
    $('taskThanks').textContent = '🐾 ' + (thanksText || '主人你太棒了！');
    $('taskThanks').style.display = 'block';
    $('taskCard').classList.add('done');
    _currentTaskData.done = true;

    // 提示
    if (data.auto_checked) {
      showToast('任务完成！今天还没签到，已自动帮你打卡啦～🔥 +3 爪印🐾（签到+1，任务+2）');
    } else {
      showToast('任务完成！+2 爪印🐾');
    }
    if (data.milestone) {
      setTimeout(() => showToast(`🎉 太厉害了！你解锁了 ${data.milestone}！`), 1500);
    }
    if (data.new_badges && data.new_badges.length > 0) {
      handleNewBadges(data.new_badges);
    }
    loadCheckinStatus();
  } catch (e) {
    showToast('任务完成！主人对我真好～🐾');
    // 即使失败也更新UI（离线友好）
    const btn = $('taskActionBtn');
    btn.className = 'btn task-action-btn done';
    btn.textContent = '✅ 已完成';
    btn.onclick = null;
  }
}

// ---- 从档案页返回时检查是否有待完成任务 ----
function checkPendingTask() {
  const taskId = localStorage.getItem('pendingTaskId');
  if (taskId) {
    const thanks = localStorage.getItem('pendingTaskThanks') || '';
    localStorage.removeItem('pendingTaskId');
    localStorage.removeItem('pendingTaskThanks');
    _markTaskDone(taskId, thanks);
  }
}

// ---- 彩蛋提示（限制3次） ----
function showEasterHint() {
  const key = 'easterHintCount';
  let count = parseInt(localStorage.getItem(key) || '0');
  if (count >= 3) return;
  count++;
  localStorage.setItem(key, String(count));
  $('easterHint').style.display = 'block';
}

// 应用初始化：检查是否已有狗狗档案
async function initApp() {
  try {
    await api('/api/dog');
    // 有档案 → 隐藏弹窗，显示主界面
    $('modalOverlay').style.display = 'none';
    $('mainContent').classList.remove('main-hidden');
    return true;
  } catch (e) {
    // 无档案 → 显示建档弹窗
    $('modalOverlay').style.display = 'flex';
    $('mainContent').classList.add('main-hidden');
    initBirthdaySelects();
    return false;
  }
}

// ---- 动态额外字段 ----
function renderExtraFields() {
  const type = $('fEType').value;
  const container = $('extraFields');
  let html = '';
  if (type === '疫苗') {
    html = `
      <div class="form-row">
        <div class="form-col"><label>第几针</label><input id="efDose" placeholder="如：1 / 2 / 加强" /></div>
        <div class="form-col"><label>备注</label><input id="efBrand" placeholder="如：品牌、批号等" /></div>
      </div>`;
  } else if (type === '驱虫') {
    html = `
      <div class="form-row">
        <div class="form-col"><label>驱虫药品牌</label><input id="efBrand" placeholder="如：拜宠清、犬心保" /></div>
        <div class="form-col"><label>类型</label><select id="efDewormType"><option>体内</option><option>体外</option><option>内外同驱</option></select></div>
      </div>`;
  } else if (type === '发情') {
    html = `
      <div class="form-row">
        <div class="form-col"><label>备注（可选）</label><input id="efNote" placeholder="如：第一天、分泌物颜色等" /></div>
      </div>`;
  } else if (type === '异常行为') {
    html = `
      <label style="font-size:0.85em;font-weight:600;color:var(--brown-light);">选择症状（可多选）</label>
      <div class="checkbox-group" id="symptomGroup">
        <label><input type="checkbox" value="跛行" /> 🦴 跛行</label>
        <label><input type="checkbox" value="呕吐" /> 🤮 呕吐</label>
        <label><input type="checkbox" value="拉稀" /> 💩 拉稀</label>
        <label><input type="checkbox" value="抓痒" /> 🐛 抓痒</label>
        <label><input type="checkbox" value="猛喝水" /> 💧 猛喝水</label>
        <label><input type="checkbox" value="不吃东西" /> 🍽️ 不吃东西</label>
      </div>`;
  } else if (type === '洗澡澡') {
    html = `<div style="font-size:0.88em;color:var(--brown-light);margin:8px 0;">🛁 今天给我洗香香了吗？选好日期，主人就帮我记下来吧～</div>`;
  }
  container.innerHTML = html;
}
$('fEType').addEventListener('change', renderExtraFields);
// 初始渲染
renderExtraFields();

// ---- 双层日期选择器 ----
let _dpTarget = null;
let _dpYear, _dpMonth, _dpDay;
let _dpLayer = 'month'; // 'month' | 'year'

function openDatePicker(targetId) {
  _dpTarget = targetId;
  const input = $(targetId);
  const val = input ? input.value : '';
  if (val && /^\d{4}-\d{2}-\d{2}$/.test(val)) {
    const parts = val.split('-');
    _dpYear = parseInt(parts[0]);
    _dpMonth = parseInt(parts[1]);
    _dpDay = parseInt(parts[2]);
  } else {
    const now = new Date();
    _dpYear = now.getFullYear();
    _dpMonth = now.getMonth() + 1;
    _dpDay = now.getDate();
  }
  _dpLayer = 'month';
  $('dpLayerMonth').style.display = '';
  $('dpLayerYear').style.display = 'none';
  renderMonthCalendar();
  $('datePickerOverlay').style.display = 'flex';
}

function closeDatePicker() {
  $('datePickerOverlay').style.display = 'none';
  _dpTarget = null;
}

$('datePickerOverlay').addEventListener('click', function(e) {
  if (e.target === this) closeDatePicker();
});

function renderMonthCalendar() {
  $('dpMonthTitle').textContent = _dpYear + '年' + _dpMonth + '月';
  const firstDay = new Date(_dpYear, _dpMonth - 1, 1).getDay(); // 0=Sun
  const daysInMonth = new Date(_dpYear, _dpMonth, 0).getDate();
  const daysInPrevMonth = new Date(_dpYear, _dpMonth - 1, 0).getDate();
  const today = new Date();
  const todayStr = today.getFullYear() + '-' + String(today.getMonth()+1).padStart(2,'0') + '-' + String(today.getDate()).padStart(2,'0');

  // 转换周日为7，周一到周六为1-6
  const startOffset = firstDay === 0 ? 6 : firstDay - 1;

  let html = '';
  // 上月填充
  for (let i = startOffset - 1; i >= 0; i--) {
    const d = daysInPrevMonth - i;
    html += '<div class="dp-day other-month">' + d + '</div>';
  }
  // 当月日期
  for (let d = 1; d <= daysInMonth; d++) {
    const dateStr = _dpYear + '-' + String(_dpMonth).padStart(2,'0') + '-' + String(d).padStart(2,'0');
    let cls = 'dp-day';
    if (dateStr === todayStr) cls += ' today';
    if (d === _dpDay && _dpMonth === (_dpMonth) && _dpYear === _dpYear) cls += ' selected';
    html += '<div class="' + cls + '" data-day="' + d + '" onclick="dpSelectDay(' + d + ')">' + d + '</div>';
  }
  // 下月填充（补齐到7的倍数）
  const totalCells = startOffset + daysInMonth;
  const remaining = totalCells % 7 === 0 ? 0 : 7 - (totalCells % 7);
  for (let d = 1; d <= remaining; d++) {
    html += '<div class="dp-day other-month">' + d + '</div>';
  }
  $('dpDaysGrid').innerHTML = html;
}

function dpSelectDay(day) {
  _dpDay = day;
  renderMonthCalendar();
}

function dpSelectToday() {
  const now = new Date();
  _dpYear = now.getFullYear();
  _dpMonth = now.getMonth() + 1;
  _dpDay = now.getDate();
  renderMonthCalendar();
}

function dpNavMonth(delta) {
  _dpMonth += delta;
  if (_dpMonth > 12) { _dpMonth = 1; _dpYear++; }
  if (_dpMonth < 1) { _dpMonth = 12; _dpYear--; }
  renderMonthCalendar();
}

function dpConfirm() {
  if (!_dpTarget) return;
  const input = $(_dpTarget);
  if (input) {
    input.value = _dpYear + '-' + String(_dpMonth).padStart(2,'0') + '-' + String(_dpDay).padStart(2,'0');
  }
  closeDatePicker();
}

// ---- 切换到第二层：年份总览 ----
function dpSwitchToYear() {
  _dpLayer = 'year';
  $('dpLayerMonth').style.display = 'none';
  $('dpLayerYear').style.display = '';
  renderYearOverview();
}

function renderYearOverview() {
  $('dpYearTitle').textContent = _dpYear + '年';
  const curMonth = new Date().getMonth() + 1;
  const curYear = new Date().getFullYear();
  let html = '';
  for (let m = 1; m <= 12; m++) {
    let cls = 'dp-month';
    if (m === _dpMonth && _dpYear === (_dpYear)) cls += ' selected';
    if (m === curMonth && _dpYear === curYear) cls += ' current';
    html += '<div class="' + cls + '" onclick="dpSelectMonth(' + m + ')">' + m + '月</div>';
  }
  $('dpMonthsGrid').innerHTML = html;
}

function dpSelectMonth(month) {
  _dpMonth = month;
  _dpLayer = 'month';
  $('dpLayerYear').style.display = 'none';
  $('dpLayerMonth').style.display = '';
  renderMonthCalendar();
}

function dpNavYear(delta) {
  _dpYear += delta;
  renderYearOverview();
}

// 初始化：为事件记录页设置默认日期
(function() {
  const now = new Date();
  const todayStr = now.getFullYear() + '-' + String(now.getMonth()+1).padStart(2,'0') + '-' + String(now.getDate()).padStart(2,'0');
  const eventDateEl = $('eventDate');
  if (eventDateEl && !eventDateEl.value) eventDateEl.value = todayStr;
  const wlDateEl = $('wlDate');
  if (wlDateEl && !wlDateEl.value) wlDateEl.value = todayStr;
})();

// ---- 折叠/展开记录表单 ----
function toggleEventForm() {
  const body = $('eventFormBody');
  const btn = $('btnCollapseEvent');
  if (!body || !btn) return;
  if (body.style.display === 'none') {
    body.style.display = '';
    btn.classList.remove('collapsed');
  } else {
    body.style.display = 'none';
    btn.classList.add('collapsed');
  }
}

// ---- 提交事件 ----
let _pendingHighRiskSubmit = null;  // 暂存被高风险拦截的提交上下文

$('btnSubmitEvent').addEventListener('click', async function() {
  const btn = this;
  const type = $('fEType').value;
  const dateVal = $('eventDate').value;

  // 前端校验日期
  if (new Date(dateVal) > new Date()) {
    showToast('事件日期不能是未来的日子哦，主人～', true);
    return;
  }

  // 收集详情
  let detail = {};
  if (type === '疫苗') {
    detail.dose = ($('efDose')?.value || '').trim();
    detail.brand = ($('efBrand')?.value || '').trim();
  } else if (type === '驱虫') {
    detail.brand = ($('efBrand')?.value || '').trim();
    detail.deworm_type = ($('efDewormType')?.value || '体内');
  } else if (type === '发情') {
    detail.note = ($('efNote')?.value || '').trim();
  } else if (type === '异常行为') {
    const checks = document.querySelectorAll('#symptomGroup input[type="checkbox"]:checked');
    detail.symptoms = Array.from(checks).map(c => c.value);
    // 高风险症状检查：检查所有选中症状文本
    const symptomText = detail.symptoms.join('，');
    const matched = checkHighRisk(symptomText);
    if (matched) {
      // 暂存提交上下文，弹出高风险警告
      _pendingHighRiskSubmit = { type, dateVal, detail, dog_id: null };
      $('riskMatchedKeyword').textContent = matched;
      $('riskWarningOverlay').style.display = 'flex';
      return;
    }
  } else if (type === '洗澡澡') {
    detail.note = '洗香香啦～';
  }

  // 幂等键
  const idemKey = genIdemKey();

  // 获取当前狗狗
  let dog;
  try {
    dog = await api('/api/dog');
  } catch (e) {
    showToast('主人，请先创建狗狗档案再记录事件哦～', true);
    return;
  }

  btn.disabled = true;
  btn.textContent = '正在提交...';
  const reactionBox = $('eventReaction');
  reactionBox.className = 'reaction-box';
  reactionBox.style.display = 'none';

  const isEditing = _editingEventId !== null;

  try {
    let r;
    if (isEditing) {
      r = await api('/api/event/' + _editingEventId, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          dog_id: dog.id,
          type: type,
          date: dateVal,
          detail: detail,
        }),
      });
    } else {
      r = await api('/api/event', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          dog_id: dog.id,
          type: type,
          date: dateVal,
          detail: detail,
          idem_key: idemKey,
        }),
      });
    }

    if (r.duplicate) {
      showToast('这条记录已经提交过啦，不用重复操作哦～');
    } else if (isEditing) {
      showToast('✅ 记录已更新！');
    } else {
      const typeNames = { '疫苗': '疫苗记录', '驱虫': '驱虫记录', '发情': '发情记录', '异常行为': '异常行为记录', '洗澡澡': '洗澡记录' };
      showToast('✅ ' + (typeNames[type] || '事件') + '已添加！向下滑动查看大事记～');
    }
    reactionBox.innerHTML = '<div class="reaction-text">' + escHtml(r.message).replace(/\n/g, '<br>') + '</div>';
    if (type === '异常行为' && r.event_id) {
      reactionBox.innerHTML += '<div style="margin-top:12px;text-align:center;"><button class="vet-btn vet-btn-screen" style="font-size:0.9em;" onclick="showVetSummary(' + r.event_id + ')">📋 生成兽医摘要，方便就医时出示</button></div>';
      reactionBox.innerHTML += '<div style="margin-top:8px;text-align:center;"><a href="javascript:void(0)" class="symptom-photo-link" onclick="uploadSymptomPhoto(' + r.event_id + ')">📋 记录症状照片（方便给兽医看）</a></div>';
    }
    reactionBox.className = 'reaction-box show';
    // 重置表单和编辑状态
    cancelEdit();
    $('eventDate').value = new Date().toISOString().slice(0, 10);
    renderExtraFields();
    loadTimeline();
    loadCheckinStatus();
    sessionStorage.setItem('pawlife_show_knowledge', '1');
    loadToday();
    // 处理新勋章
    if (r.new_badges && r.new_badges.length > 0) {
      handleNewBadges(r.new_badges);
    }
    // 提示上传健康纪念照
    if (r.prompt_health_photo) {
      setTimeout(() => promptHealthPhotoUpload(r.event_id, type, dateVal), 1500);
    }
  } catch (e) {
    reactionBox.textContent = '汪汪，信号被狗吃了，点我重试～';
    reactionBox.className = 'reaction-box show error';
    reactionBox.style.cursor = 'pointer';
    reactionBox.onclick = () => $('btnSubmitEvent').click();
  }
  btn.disabled = false;
  btn.textContent = '🐾 提交记录';
});

// ---- 高风险警告弹窗：确认按钮 ----
$('btnRiskConfirm').addEventListener('click', async function() {
  const btn = this;
  if (!_pendingHighRiskSubmit) return;

  const ctx = _pendingHighRiskSubmit;
  btn.disabled = true;
  btn.textContent = '正在处理...';

  try {
    // 获取狗狗信息
    const dog = await api('/api/dog');
    ctx.dog_id = dog.id;

    // 找到命中的关键词
    const symptomText = ctx.detail.symptoms.join('，');
    const matched = checkHighRisk(symptomText);

    // 提交高风险事件
    const idemKey = genIdemKey();
    const r = await api('/api/event', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        dog_id: dog.id,
        type: ctx.type,
        date: ctx.dateVal,
        detail: ctx.detail,
        idem_key: idemKey,
        high_risk: 1,
        risk_keyword: matched || '',
      }),
    });

    // 关闭警告弹窗
    $('riskWarningOverlay').style.display = 'none';
    _pendingHighRiskSubmit = null;

    if (r.duplicate) {
      showToast('这条记录已经提交过啦，不用重复操作哦～');
    } else {
      showToast('✅ 已记录高风险事件，今日饮食与保健品建议已暂停。请务必联系兽医！');
    }

    const reactionBox = $('eventReaction');
    reactionBox.innerHTML = '<div class="reaction-text" style="color:var(--red);">' + escHtml(r.message).replace(/\n/g, '<br>') + '</div>';
    if (r.event_id) {
      reactionBox.innerHTML += '<div style="margin-top:12px;text-align:center;"><button class="vet-btn vet-btn-screen" style="font-size:0.9em;" onclick="showVetSummary(' + r.event_id + ')">📋 生成兽医摘要，方便就医时出示</button></div>';
      reactionBox.innerHTML += '<div style="margin-top:8px;text-align:center;"><a href="javascript:void(0)" class="symptom-photo-link" onclick="uploadSymptomPhoto(' + r.event_id + ')">📋 记录症状照片（方便给兽医看）</a></div>';
    }
    reactionBox.className = 'reaction-box show';

    // 重置表单
    cancelEdit();
    $('eventDate').value = new Date().toISOString().slice(0, 10);
    renderExtraFields();
    loadTimeline();
    loadCheckinStatus();
    sessionStorage.setItem('pawlife_show_knowledge', '1');
    loadToday();
    loadDietCard();
    loadSupplements();
    // 处理新勋章
    if (r.new_badges && r.new_badges.length > 0) {
      handleNewBadges(r.new_badges);
    }
    if (r.prompt_health_photo) {
      setTimeout(() => promptHealthPhotoUpload(r.event_id, ctx.type, ctx.dateVal), 1500);
    }
  } catch (e) {
    showToast(e.message || '汪汪，提交失败了，点我重试～', true);
    $('riskWarningOverlay').style.display = 'none';
    _pendingHighRiskSubmit = null;
  }
  btn.disabled = false;
  btn.textContent = '我知道了，已联系兽医';
});

// ---- 恢复建议按钮（解除暂停） ----
async function restoreSuggestions() {
  try {
    const r = await api('/api/dog/unsuspend', { method: 'POST' });
    showToast(r.message);
    loadDietCard();
    loadSupplements();
    loadToday();
  } catch (e) {
    showToast(e.message || '汪汪，恢复失败了，点我重试～', true);
  }
}

// ---- 导出备份数据（CSV 格式，Excel 可直接打开） ----
$('btnExport').addEventListener('click', async function() {
  const btn = this;
  btn.disabled = true;
  btn.textContent = '导出中...';
  try {
    const resp = await fetch('/api/export');
    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.message || '导出失败');
    }
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    const disp = resp.headers.get('Content-Disposition') || '';
    const m = disp.match(/filename\*?=UTF-8''(.+)/) || disp.match(/filename=(.+)/);
    a.download = m ? m[1] : 'PawLife_backup.csv';
    a.click();
    URL.revokeObjectURL(url);
    showToast('汪汪！数据已备份为 Excel 可打开的 CSV 文件，主人要好好保管哦～🐾');
  } catch (e) {
    showToast('备份失败：' + (e.message || '未知错误'), true);
  }
  btn.disabled = false;
  btn.textContent = '📥 备份数据';
});

// ---- 首页"建立档案"按钮 ----
$('btnCreateProfileHome').addEventListener('click', function() {
  $('modalOverlay').style.display = 'flex';
  initBirthdaySelects();
});

// ---- 初始加载 ----
(async function() {
  updateGreeting(null);
  const hasDog = await initApp();
  if (hasDog) {
    loadToday();
    loadProfile();
    loadTimeline();
  }
})();
</script>
</body>
</html>"""


# ============================================================
# 服务器启动
# ============================================================
def _safe_print(*args, **kwargs):
    """安全打印，避免 Windows GBK 终端因 emoji 崩溃"""
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        msg = " ".join(str(a) for a in args)
        print(msg.encode("ascii", errors="replace").decode("ascii"), **kwargs)


def run_server():
    import uvicorn

    def _open_browser():
        time.sleep(1.2)
        webbrowser.open("http://127.0.0.1:8000")

    threading.Thread(target=_open_browser, daemon=True).start()

    _safe_print("=" * 56)
    _safe_print("  🐾  PawLife — 狗狗健康管理 · 防焦虑伴侣")
    _safe_print("=" * 56)
    _safe_print(f"  数据库路径: {DB_PATH}")
    _safe_print(f"  访问地址:   http://127.0.0.1:8000")
    _safe_print()
    _safe_print("  功能：")
    _safe_print("    1. 狗狗小档案（1分钟极速建档）")
    _safe_print("    2. 今日汪汪（紧急提醒 + 每日生存指南）")
    _safe_print("    3. 记录事件（疫苗/驱虫/发情/异常行为）")
    _safe_print("    4. 异常行为自动分析（品种决策树）")
    _safe_print("    5. 汪生时间线（纪念日卡片）")
    _safe_print("    6. 我的档案 + 重置演示数据")
    _safe_print()
    _safe_print("  按 Ctrl+C 停止服务器")
    _safe_print("=" * 56)

    host = "0.0.0.0"
    port = int(os.environ.get("PORT", 8000))
    _safe_print(f"  监听地址:   http://{host}:{port}")
    uvicorn.run("pawlife_web:app", host=host, port=port, log_level="info", reload=True)


if __name__ == "__main__":
    run_server()
