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
from typing import Any, Dict, List, Optional

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

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
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
    photo = Column(String(128), nullable=True, comment="照片文件名")
    bath_interval_days = Column(Integer, nullable=True, comment="建议洗澡间隔天数")
    last_bath_date = Column(Date, nullable=True, comment="上次洗澡日期")
    created_at = Column(DateTime, default=datetime.utcnow)


class Event(Base):
    """事件记录表"""
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True)
    dog_id = Column(Integer, nullable=False, comment="关联狗狗ID")
    type = Column(String(32), nullable=False, comment="事件类型：疫苗/驱虫/发情/异常行为")
    date = Column(Date, nullable=False, comment="事件日期")
    detail = Column(Text, nullable=True, comment="JSON 格式的详情")
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
EVENT_TYPES = ["疫苗", "驱虫", "发情", "异常行为", "洗澡澡"]
ABNORMAL_SYMPTOMS = ["跛行", "呕吐", "拉稀", "抓痒", "猛喝水", "不吃东西"]


class DogCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    breed: str
    birthday: date
    weight: Optional[str] = None
    neutered: Optional[str] = "未知"
    allergies: Optional[str] = None

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
            "photo": dog.photo or "",
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
            bath_interval_days=_calc_bath_interval(payload.weight),
            last_bath_date=date.today(),
        )
        db.add(dog)
        db.flush()
        _refresh_supplement_alerts(db, dog)
        return {
            "message": f"汪汪！主人你好，我是{dog.name}！一只{dog.breed}宝宝～以后请多多关照我的小肉垫，我会陪你很久很久的！🐾",
            "dog_id": dog.id,
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
        dog.bath_interval_days = _calc_bath_interval(payload.weight)
        db.flush()
        _refresh_supplement_alerts(db, dog)
        return {
            "message": f"汪汪！主人，我的档案更新好了～以后请继续多多关照我的小肉垫！🐾",
            "dog_id": dog.id,
        }


# 过敏源 → 需排除的食物列表
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

        plan = _calc_daily_grams(dog.birthday, weight_kg, dog.neutered or "未知")

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
        heartfelt = heartfelt_map.get(age_stage,
            f"主人，照着这个喂我，我会长得壮壮、毛亮亮哦！每天陪我一起吃饭，是我最开心的时光～🐾")

        # 过敏提示
        allergy_note = ""
        if allergies_str:
            allergy_note = f"⚠️ 已避开你的过敏源（{allergies_str}），替换为安全的食材啦～"

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

            detail_json = json.dumps(payload.detail, ensure_ascii=False) if payload.detail else None
            event = Event(
                dog_id=payload.dog_id,
                type=payload.type,
                date=payload.date,
                detail=detail_json,
            )
            db.add(event)

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
                # 异常行为后刷新保健品推荐
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

            return {"message": reaction, "event_id": event.id}
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
        db.delete(event)
        return {"message": "汪汪，这条记录已经被我删掉了，主人的大事记保持整洁很重要～"}


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
        return {
            "message": f"汪汪！体重 {payload.weight} 已记录，主人要帮我保持健康身材哦～🐾",
            "id": wl.id,
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
        return 10
    else:
        return 7


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
        "tip": "大型幼犬骨骼发育快，注意钙磷平衡，可适量添加蛋壳粉～",
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


def _calc_daily_grams(dog_birthday: date, weight_kg: float, neutered: str) -> dict:
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

    der = rer * coeff

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
        "reason": "生长发育期需均衡营养",
        "woof": "我正在长身体，给我一点综合营养粉，让我骨骼牙齿棒棒的！",
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
        "id": "urinary_female",
        "supplement": "泌尿健康（蔓越莓提取物）",
        "priority": 3,
        "condition": lambda dog, stats: (
            stats["age_months"] >= 60
            and dog.neutered not in ("是",)
        ),
        "reason": "中老年未绝育母犬泌尿道感染风险较高",
        "woof": "主人，我年纪大了，给我吃点蔓越莓保护尿尿的地方吧～",
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
        suffix = "\n（记得先问问兽医再给我吃哦～）"
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

        # 疫苗：每年一次，提前 30 天提醒
        if last_vaccine:
            next_vaccine = last_vaccine + timedelta(days=365)
            days_left = (next_vaccine - today).days
            if days_left <= 30:
                if days_left < 0:
                    reminders.append({
                        "type": "疫苗",
                        "text": f"主人，掐爪一算，我的疫苗保护已经过期{abs(days_left)}天啦！快带我去补打吧，没有疫苗护体我出门都会害怕的～",
                    })
                else:
                    reminders.append({
                        "type": "疫苗",
                        "text": f"主人，掐爪一算，我的疫苗保护还有{days_left}天就到期啦，记得提前预约医院哦，我想做一只健康有防护的好狗狗～",
                    })
        else:
            reminders.append({
                "type": "疫苗",
                "text": "主人，我还没有打过疫苗呢！幼犬需要打三针基础疫苗，成年后每年加强一针。快帮我建档记录起来吧～",
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

        # 发情：未绝育母犬约 6 个月一次
        if dog.neutered not in ("是",):
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
  --muted: #A0846C;
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
.dog-photo-wrapper {
  text-align: center;
  margin: 0 0 4px;
}
.dog-photo-circle {
  width: 120px; height: 120px;
  border-radius: 50%;
  margin: 0 auto;
  position: relative;
  overflow: hidden;
  border: 3px solid var(--border);
  background: #FDF8F2;
  cursor: pointer;
  transition: border-color 0.25s, box-shadow 0.25s;
}
.dog-photo-circle:hover {
  border-color: var(--orange);
  box-shadow: 0 0 0 4px rgba(255,138,0,0.12);
}
.dog-photo-circle img {
  width: 100%; height: 100%;
  object-fit: cover;
  display: block;
}
.dog-photo-circle .dog-photo-placeholder {
  position: absolute;
  top: 50%; left: 50%;
  transform: translate(-50%, -50%);
  font-size: 3em;
  pointer-events: none;
}
.dog-photo-circle .dog-photo-camera {
  position: absolute;
  bottom: 0; left: 0; right: 0;
  text-align: center;
  background: rgba(0,0,0,0.45);
  color: #FFFFFF;
  font-size: 0.9em;
  padding: 4px 0 5px;
  opacity: 0;
  transition: opacity 0.25s;
  pointer-events: none;
}
.dog-photo-circle:hover .dog-photo-camera { opacity: 1; }
.subtitle {
  text-align: center;
  color: var(--muted);
  font-size: 0.92em;
  letter-spacing: 1px;
  margin: 2px 0 4px;
}

/* ===== 欢迎条 ===== */
.greeting-bar {
  max-width: 720px; margin: 0 auto 8px;
  display: flex; align-items: center; justify-content: center; gap: 10px;
}
.greeting-bar.main-hidden { display: none; }
.greeting-text {
  font-size: 1.05em; font-weight: 600; color: var(--brown);
  letter-spacing: 0.3px;
  white-space: nowrap;
}
.greeting-bubble {
  position: relative;
  background: #FFFBF5;
  border: 1.5px solid #E0D2B8;
  border-radius: 20px;
  padding: 8px 16px;
  flex: 0 1 auto;
  box-shadow: 0 2px 8px rgba(100,60,20,0.06);
  animation: bubbleBounce 0.6s ease-out;
}
@keyframes bubbleBounce {
  0%   { transform: scale(0.3); opacity: 0; }
  45%  { transform: scale(1.06); }
  65%  { transform: scale(0.94); }
  85%  { transform: scale(1.03); }
  100% { transform: scale(1); opacity: 1; }
}
.greeting-bubble::before {
  content: '';
  position: absolute; left: -7px; top: 50%;
  transform: translateY(-50%);
  width: 0; height: 0;
  border-top: 7px solid transparent;
  border-bottom: 7px solid transparent;
  border-right: 7px solid #E0D2B8;
}
.greeting-bubble::after {
  content: '';
  position: absolute; left: -5px; top: 50%;
  transform: translateY(-50%);
  width: 0; height: 0;
  border-top: 6px solid transparent;
  border-bottom: 6px solid transparent;
  border-right: 6px solid #FFFBF5;
}
.greeting-avatar {
  width: 84px; height: 84px; border-radius: 50%;
  background: #FFFBF5; border: 2px solid var(--border);
  display: flex; align-items: center; justify-content: center;
  font-size: 2.5em; cursor: pointer;
  transition: border-color 0.2s, box-shadow 0.2s;
  flex-shrink: 0; overflow: hidden;
}
.greeting-avatar:hover {
  border-color: var(--orange);
  box-shadow: 0 0 0 5px rgba(255,138,0,0.12);
}
.greeting-avatar-sm {
  width: 61px; height: 61px;
  font-size: 2em;
}

/* ===== 今日汪汪卡片（重新设计） ===== */
.today-card {
  background: #FFF3E0;
  border-radius: var(--radius);
  padding: 14px 16px;
  margin-bottom: 14px;
  display: flex;
  gap: 12px;
  align-items: flex-start;
  box-shadow: var(--shadow);
  border: 1px solid var(--border);
  transition: background 0.3s, border-color 0.3s;
}
.today-card.reminder {
  background: #FFE0B2;
  border-color: #FFB74D;
}
.today-card-left {
  flex-shrink: 0; padding-top: 2px;
}
.today-card-icon {
  font-size: 1.6em;
}
.today-card-body { flex: 1; min-width: 0; }
.today-card-title {
  font-weight: 700; font-size: 1em; color: var(--brown);
  margin-bottom: 4px;
}
.today-card-text {
  font-size: 0.98em; color: var(--brown-light); line-height: 1.7;
}
.today-card-text.urgent {
  color: var(--red); font-weight: 600;
}
.today-card-action { margin-top: 6px; }
.today-card-refresh {
  flex-shrink: 0;
  padding: 5px 14px; border-radius: 16px;
  border: 1px solid var(--border);
  background: rgba(255,255,255,0.6);
  cursor: pointer; font-size: 0.82em; font-weight: 600;
  color: var(--brown-light);
  transition: all 0.2s; font-family: inherit;
}
.today-card-refresh:hover { background: #fff; border-color: var(--orange); color: var(--orange); }

/* ===== 首页档案卡片 ===== */
.profile-card-home {
  background: var(--card);
  border-radius: var(--radius);
  padding: 16px 18px;
  margin-bottom: 14px;
  box-shadow: var(--shadow);
  border: 1px solid var(--border);
}
.profile-card-header {
  display: flex; align-items: center; gap: 8px;
  margin-bottom: 10px;
}
.profile-mood-emoji { font-size: 1.5em; }
.profile-card-title-text {
  font-size: 1.05em; font-weight: 700; color: var(--brown);
}
.profile-card-body {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px 16px;
  font-size: 0.9em; color: var(--brown-light); line-height: 2;
}
@media (max-width: 480px) {
  .profile-card-body { grid-template-columns: 1fr; }
}
.profile-info-item {
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.profile-card-empty { }

/* ===== 功能入口网格 ===== */
.feature-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-bottom: 14px;
}
.feature-card {
  background: var(--card);
  border-radius: var(--radius);
  padding: 18px 14px;
  text-align: center;
  cursor: pointer;
  box-shadow: var(--shadow);
  border: 1px solid var(--border);
  transition: transform 0.2s, box-shadow 0.2s, border-color 0.2s;
  position: relative;
  user-select: none;
}
.feature-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(100,60,20,0.12);
  border-color: var(--orange);
}
.feature-card:active { transform: scale(0.97); }
.feature-icon { font-size: 2em; margin-bottom: 6px; }
.feature-label {
  font-size: 1em; font-weight: 700; color: var(--brown);
  margin-bottom: 2px;
}
.feature-subtitle {
  font-size: 0.78em; color: var(--muted);
}
.feature-badge {
  position: absolute; top: 8px; right: 8px;
  width: 10px; height: 10px; border-radius: 50%;
  background: #E53935;
  box-shadow: 0 0 0 3px rgba(229,57,53,0.2);
  animation: badgePulse 2s infinite;
}
@keyframes badgePulse {
  0%, 100% { box-shadow: 0 0 0 3px rgba(229,57,53,0.2); }
  50% { box-shadow: 0 0 0 6px rgba(229,57,53,0.1); }
}

/* ===== 子页面 ===== */
.sub-page { animation: fadeInUp 0.3s ease; }
.sub-page-header {
  text-align: center;
  margin-bottom: 12px;
}
.sub-page-title {
  display: block;
  font-size: 1.15em; font-weight: 700; color: var(--brown);
  margin-bottom: 10px;
}
.sub-page-header-row {
  display: flex; align-items: center; justify-content: space-between;
}

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

/* 生日三连下拉 */
.triple-select {
  display: flex;
  gap: 8px;
}
.triple-select select { flex: 1; }
.triple-select select:first-child { flex: 2; }

/* 隐藏主界面（建档前） */
.main-hidden { display: none; }

/* ===== 滚轮日期选择器 ===== */
.wheel-picker {
  display: flex;
  position: relative;
  height: 172px;
  background: #FFFAF2;
  border: 1.5px solid var(--border);
  border-radius: var(--radius-sm);
  overflow: hidden;
}
.wheel-col {
  flex: 1;
  overflow-y: auto;
  scroll-snap-type: y mandatory;
  -webkit-overflow-scrolling: touch;
  padding: 66px 0;
  position: relative;
  z-index: 1;
}
.wheel-col::-webkit-scrollbar { display: none; }
.wheel-col { scrollbar-width: none; }
.wheel-item {
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  scroll-snap-align: center;
  font-size: 0.9em;
  color: #A0846C;
  cursor: pointer;
  user-select: none;
}
.wheel-col:first-child .wheel-item { font-size: 0.85em; }
.wheel-item.active {
  color: var(--brown);
  font-weight: 700;
  font-size: 1em;
}
.wheel-col:first-child .wheel-item.active { font-size: 0.92em; }
.wheel-picker::after {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0; bottom: 0;
  pointer-events: none;
  z-index: 2;
  background:
    linear-gradient(to bottom, #FFFAF2 0%, transparent 35%, transparent 65%, #FFFAF2 100%);
}
.wheel-highlight-line {
  position: absolute;
  top: 66px;
  left: 6px;
  right: 6px;
  height: 40px;
  border-top: 1.5px solid var(--orange);
  border-bottom: 1.5px solid var(--orange);
  pointer-events: none;
  z-index: 2;
  background: rgba(255, 138, 0, 0.04);
  border-radius: 4px;
}

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

/* 响应式 */
@media (max-width: 600px) {
  .recipe-wrap { flex-direction: column; }
  .recipe-main, .recipe-side { min-width: auto; }
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
          <div class="triple-select">
            <select id="mBirthYear"></select>
            <select id="mBirthMonth"></select>
            <select id="mBirthDay"></select>
          </div>
        </div>
      </div>
      <div class="form-row">
        <div class="form-col"><label>我的体重</label><input id="mWeight" placeholder="例：28kg" /></div>
        <div class="form-col"><label>绝育情况</label>
          <select id="mNeutered"><option value="未知">未知</option><option value="是">是</option><option value="否">否</option></select>
        </div>
      </div>
      <div class="form-row">
        <div class="form-col"><label>过敏源</label><input id="mAllergies" placeholder="逗号分隔，如：鸡肉,谷物" /></div>
      </div>
      <div class="form-row">
        <div class="form-col"><label>我的照片 <span style="color:var(--muted);font-weight:400;">（可选）</span></label>
          <input type="file" id="mPhoto" accept="image/jpeg,image/png" />
        </div>
      </div>
    </div>
    <div class="modal-footer">
      <button class="btn btn-primary btn-lg" id="btnModalCreate">🐾 完成建档，开启汪生！</button>
    </div>
  </div>
</div>

<div class="app-header main-hidden" id="mainContent">
  <div class="logo">🐾 PawLife</div>
</div>

<!-- ===== 欢迎条 ===== -->
<div class="greeting-bar main-hidden" id="greetingBar">
  <div class="greeting-avatar" id="greetingAvatar" title="点击更换我的照片">🐶</div>
  <div class="greeting-bubble">
    <span class="greeting-text" id="greetingText">🐾 汪汪，你好！</span>
  </div>
  <input type="file" id="dogPhotoInput" accept="image/jpeg,image/png" style="display:none;" />
</div>

<div class="container">

  <!-- ==================== 首页 ==================== -->
  <div id="page-home">

    <!-- 今日汪汪卡片 -->
    <div class="today-card" id="todayCard">
      <div class="today-card-left">
        <span class="today-card-icon" id="todayCardIcon">💡</span>
      </div>
      <div class="today-card-body">
        <div class="today-card-title">今日汪汪 <span style="color:var(--muted);font-size:0.78em;font-weight:400;">— 快把耳朵凑过来…</span></div>
        <div class="today-card-text" id="todayCardText">
          <div class="skeleton" style="width:80%;margin:6px 0;"></div>
        </div>
        <div class="today-card-action" id="todayCardAction" style="display:none;"></div>
      </div>
      <button class="today-card-refresh" id="btnRefreshToday" title="换一句汪汪">↻</button>
    </div>

    <!-- 我的档案卡片 -->
    <div class="profile-card-home" id="profileCardHome">
      <div class="profile-card-header" id="profileCardHeader">
        <span class="profile-mood-emoji" id="profileMoodEmoji">📋</span>
        <span class="profile-card-title-text">我的小档案</span>
        <button class="btn btn-outline btn-sm" id="btnEditProfile" style="display:none;margin-left:auto;">✏️ 编辑</button>
      </div>
      <div class="profile-card-body" id="profileCardBody">
        <div class="skeleton" style="width:70%;"></div>
        <div class="skeleton" style="width:50%;"></div>
      </div>
      <!-- 未建档状态 -->
      <div class="profile-card-empty" id="profileCardEmpty" style="display:none;">
        <div style="text-align:center;padding:12px 0;">
          <div style="font-size:2.5em;margin-bottom:6px;">🐶</div>
          <div style="font-weight:700;color:var(--brown);margin-bottom:4px;">创建我的档案</div>
          <div style="color:var(--muted);font-size:0.88em;margin-bottom:10px;">主人，快帮我建个档案吧，这样你就能看到我的全部信息啦～</div>
          <button class="btn btn-primary" id="btnCreateProfileHome">🐾 建立档案</button>
        </div>
      </div>
    </div>

    <!-- 功能入口网格 -->
    <div class="feature-grid">
      <div class="feature-card" id="featRecord" onclick="navigateTo('record')">
        <span class="feature-badge" id="badgeRecord" style="display:none;"></span>
        <div class="feature-icon">📝</div>
        <div class="feature-label">记录事件</div>
        <div class="feature-subtitle">疫苗、驱虫、洗澡澡</div>
      </div>
      <div class="feature-card" id="featDiet" onclick="navigateTo('diet')">
        <div class="feature-icon">🍖</div>
        <div class="feature-label">饮食宝典</div>
        <div class="feature-subtitle">吃什么，怎么吃</div>
      </div>
      <div class="feature-card" id="featTimeline" onclick="navigateTo('timeline')">
        <div class="feature-icon">📅</div>
        <div class="feature-label">大事记</div>
        <div class="feature-subtitle">我的汪生纪念册</div>
      </div>
      <div class="feature-card" id="featSupplement" onclick="navigateTo('supplement')">
        <span class="feature-badge" id="badgeSupplement" style="display:none;"></span>
        <div class="feature-icon">🛡️</div>
        <div class="feature-label">保健品小队</div>
        <div class="feature-subtitle">我的营养护盾</div>
      </div>
    </div>

    <!-- 体重成长记录（幼犬时显示） -->
    <div class="card" id="weightLogSection" style="display:none;">
      <div style="font-weight:700;font-size:0.95em;color:var(--brown-light);margin-bottom:8px;">📈 体重成长记录</div>
      <div id="weightLogList" style="max-height:160px;overflow-y:auto;margin-bottom:8px;"></div>
      <div style="display:flex;gap:6px;align-items:center;">
        <input id="wlWeight" placeholder="体重，如：12.5kg" style="flex:2;padding:6px 10px;font-size:0.85em;" />
        <input type="date" id="wlDate" style="flex:1;padding:6px 8px;font-size:0.85em;" />
        <button class="btn btn-primary btn-sm" id="btnAddWeight" style="flex:0 0 auto;white-space:nowrap;">+ 记录</button>
      </div>
    </div>

    <!-- 备份按钮 -->
    <div style="text-align:right;margin-top:6px;">
      <button class="btn btn-outline btn-sm" id="btnExport">📥 备份数据</button>
    </div>
  </div>

  <!-- ==================== 子页面：记录事件 ==================== -->
  <div id="page-record" class="sub-page" style="display:none;">
    <div class="sub-page-header">
      <span class="sub-page-title">📝 记录事件</span>
      <div class="sub-page-header-row">
        <button class="btn btn-outline btn-sm" onclick="navigateTo('home')">← 返回首页</button>
        <div class="greeting-avatar greeting-avatar-sm" id="greetingAvatarSub">🐶</div>
      </div>
    </div>
    <div class="card" id="cardEvent">
      <div class="card-subtitle" id="eventSubtitle">记录疫苗、驱虫、发情或异常行为，我会立刻给你反馈</div>
      <div class="form-row">
        <div class="form-col"><label>事件类型</label>
          <select id="fEType"><option value="疫苗">💉 疫苗</option><option value="驱虫">💊 驱虫</option><option value="发情">💕 发情</option><option value="异常行为">⚠️ 异常行为</option><option value="洗澡澡">🛁 洗澡澡</option></select>
        </div>
        <div class="form-col"><label>日期</label>
          <div class="wheel-picker" id="wheelPicker">
            <div class="wheel-col" id="wheelYear"></div>
            <div class="wheel-col" id="wheelMonth"></div>
            <div class="wheel-col" id="wheelDay"></div>
            <div class="wheel-highlight-line"></div>
          </div>
        </div>
      </div>
      <div id="extraFields" style="margin-bottom:4px;"></div>
      <div style="text-align:right;">
        <button class="btn btn-primary" id="btnSubmitEvent">🐾 提交记录</button>
      </div>
      <div class="reaction-box" id="eventReaction"></div>
    </div>
    <!-- 时间线也放在记录页面 -->
    <div class="card" id="cardTimeline">
      <div class="card-title" id="timelineTitle">📅 汪生时间线</div>
      <div class="timeline-filters" id="timelineFilters" style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px;">
        <span class="tl-filter active" data-filter="全部">全部</span>
        <span class="tl-filter" data-filter="疫苗">💉 疫苗</span>
        <span class="tl-filter" data-filter="驱虫">💊 驱虫</span>
        <span class="tl-filter" data-filter="发情">💕 发情</span>
        <span class="tl-filter" data-filter="异常行为">⚠️ 异常</span>
        <span class="tl-filter" data-filter="洗澡澡">🛁 洗澡</span>
      </div>
      <div id="timelineArea" style="margin-top:8px;">
        <div class="skeleton" style="width:60%;"></div>
        <div class="skeleton" style="width:45%;"></div>
        <div class="skeleton" style="width:55%;"></div>
      </div>
    </div>
  </div>

  <!-- ==================== 子页面：饮食宝典 ==================== -->
  <div id="page-diet" class="sub-page" style="display:none;">
    <div class="sub-page-header">
      <span class="sub-page-title">🍖 饮食宝典</span>
      <div class="sub-page-header-row">
        <button class="btn btn-outline btn-sm" onclick="navigateTo('home')">← 返回首页</button>
        <div class="greeting-avatar greeting-avatar-sm" id="greetingAvatarSub">🐶</div>
      </div>
    </div>
    <div class="card" id="cardDiet">
      <div id="dietArea" style="margin-top:8px;">
        <div class="skeleton" style="width:60%;"></div>
      </div>
    </div>
  </div>

  <!-- ==================== 子页面：大事记 ==================== -->
  <div id="page-timeline" class="sub-page" style="display:none;">
    <div class="sub-page-header">
      <span class="sub-page-title">📅 大事记</span>
      <div class="sub-page-header-row">
        <button class="btn btn-outline btn-sm" onclick="navigateTo('home')">← 返回首页</button>
        <div class="greeting-avatar greeting-avatar-sm" id="greetingAvatarSub">🐶</div>
      </div>
    </div>
    <div class="card">
      <div class="timeline-filters" style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px;">
        <span class="tl-filter active" data-filter="全部">全部</span>
        <span class="tl-filter" data-filter="疫苗">💉 疫苗</span>
        <span class="tl-filter" data-filter="驱虫">💊 驱虫</span>
        <span class="tl-filter" data-filter="发情">💕 发情</span>
        <span class="tl-filter" data-filter="异常行为">⚠️ 异常</span>
        <span class="tl-filter" data-filter="洗澡澡">🛁 洗澡</span>
      </div>
      <div id="timelineArea2" style="margin-top:8px;">
        <div class="skeleton" style="width:60%;"></div>
      </div>
    </div>
  </div>

  <!-- ==================== 子页面：保健品小队 ==================== -->
  <div id="page-supplement" class="sub-page" style="display:none;">
    <div class="sub-page-header">
      <span class="sub-page-title">🛡️ 保健品小队</span>
      <div class="sub-page-header-row">
        <button class="btn btn-outline btn-sm" onclick="navigateTo('home')">← 返回首页</button>
        <div class="greeting-avatar greeting-avatar-sm" id="greetingAvatarSub">🐶</div>
      </div>
    </div>
    <div class="card" id="cardSupplements">
      <div id="supplementsArea" style="margin-top:8px;">
        <div class="skeleton" style="width:50%;"></div>
      </div>
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
          <div class="triple-select">
            <select id="eBirthYear"></select>
            <select id="eBirthMonth"></select>
            <select id="eBirthDay"></select>
          </div>
        </div>
      </div>
      <div class="form-row">
        <div class="form-col"><label>我的体重</label><input id="eWeight" placeholder="例：28kg" /></div>
        <div class="form-col"><label>绝育情况</label>
          <select id="eNeutered"><option value="未知">未知</option><option value="是">是</option><option value="否">否</option></select>
        </div>
      </div>
      <div class="form-row">
        <div class="form-col"><label>过敏源</label><input id="eAllergies" placeholder="逗号分隔，如：鸡肉,谷物" /></div>
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

<div class="app-footer">
  © PawLife · 汪星人出品 · 用爱守护每一只狗狗 🐾 <span style="opacity:0.4;font-size:0.75em;">v2505.3</span>
</div>

</div><!-- /#mainContent -->

<script>
// ============================================================
// PawLife 前端 JS
// ============================================================

const $ = id => document.getElementById(id);

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
    if (daysSince <= 3) return `${daysSince === 0 ? '今天' : daysSince + '天前'}主人刚给我洗过澡，我现在毛毛蓬蓬的、香喷喷的，走在路上都是小公主/小王子的味道～🛁`;
    if (daysSince <= 14) return `距离上次洗澡已经${daysSince}天了，我还算干净啦，不过主人可以开始帮我留意下次洗澡的时间哦～`;
    return `我都${daysSince}天没洗澡啦，身上有点小狗味儿了！主人有空带我去洗香香吧～🛁`;
  }

  return null;
}

// ---- 紧急提醒 / 今日汪汪 ----
async function loadToday() {
  const textEl = $('todayCardText');
  const card = $('todayCard');
  const iconEl = $('todayCardIcon');
  textEl.innerHTML = '<div class="skeleton" style="width:80%;margin:6px 0;"></div>';

  try {
    const data = await api('/api/health_check');
    if (!data.has_dog) {
      textEl.innerHTML = '🐾 主人，我还没来到你身边呢，快去建档让我出现吧！';
      textEl.className = 'today-card-text';
      card.classList.remove('reminder');
      iconEl.textContent = '💡';
      return;
    }
    // 有紧急提醒 → 优先展示 + 快捷记录按钮
    if (data.reminders && data.reminders.length > 0) {
      const r = data.reminders[Math.floor(Math.random() * data.reminders.length)];
      textEl.innerHTML = r.text;
      textEl.className = 'today-card-text urgent';
      card.classList.add('reminder');
      iconEl.textContent = '🔔';
      const actionEl = $('todayCardAction');
      if (r.type && r.type !== '发情') {
        actionEl.style.display = '';
        const typeLabel = r.type === '疫苗' ? '💉' : r.type === '驱虫' ? '💊' : '📝';
        actionEl.innerHTML = `<button class="btn btn-primary btn-sm" onclick="quickRecord('${r.type}')">${typeLabel} 已完成，帮我记录</button>`;
      } else {
        actionEl.style.display = 'none';
      }
      // 更新角标
      updateBadges(data);
      return;
    }
    // 无提醒 → 根据最新大事记生成个性化消息
    $('todayCardAction').style.display = 'none';
    const dogName = (data.dog && data.dog.name) || '汪星人';
    const personalized = getPersonalizedMessage(data.latest_event, dogName);
    if (personalized) {
      textEl.innerHTML = '💬 ' + personalized;
      textEl.className = 'today-card-text';
      card.classList.remove('reminder');
      iconEl.textContent = '💡';
      updateBadges(data);
      return;
    }
    // 兜底：智能匹配贴士
    const tipBreed = (data.dog && data.dog.breed) || '其他';
    const tipMonth = new Date().getMonth() + 1;
    textEl.innerHTML = '💬 ' + getSmartTip(tipBreed, tipMonth);
    textEl.className = 'today-card-text';
    card.classList.remove('reminder');
    iconEl.textContent = '💡';
    updateBadges(data);
  } catch (e) {
    textEl.innerHTML = '汪汪，信号被狗吃了，<a href="javascript:loadToday()" style="color:var(--orange);cursor:pointer;">点我重试</a>';
    textEl.className = 'today-card-text';
  }
}

$('btnRefreshToday').addEventListener('click', async () => {
  const data = await api('/api/health_check').catch(() => null);
  const textEl = $('todayCardText');
  const card = $('todayCard');
  const iconEl = $('todayCardIcon');
  const tipBreed = (data && data.dog && data.dog.breed) || (_cachedDog && _cachedDog.breed) || '其他';
  const tipMonth = new Date().getMonth() + 1;
  if (!data || !data.has_dog) {
    textEl.innerHTML = '💬 ' + getSmartTip(tipBreed, tipMonth);
    textEl.className = 'today-card-text';
    card.classList.remove('reminder');
    iconEl.textContent = '💡';
    return;
  }
  if (data.reminders && data.reminders.length > 0) {
    const currentText = textEl.textContent;
    const others = data.reminders.filter(r => r.text !== currentText);
    const pick = others.length > 0 ? others[Math.floor(Math.random() * others.length)] : data.reminders[0];
    textEl.innerHTML = pick.text;
    textEl.className = 'today-card-text urgent';
    card.classList.add('reminder');
    iconEl.textContent = '🔔';
    const actionEl = $('todayCardAction');
    if (pick.type && pick.type !== '发情') {
      actionEl.style.display = '';
      const typeLabel = pick.type === '疫苗' ? '💉' : pick.type === '驱虫' ? '💊' : '📝';
      actionEl.innerHTML = `<button class="btn btn-primary btn-sm" onclick="quickRecord('${pick.type}')">${typeLabel} 已完成，帮我记录</button>`;
    } else {
      actionEl.style.display = 'none';
    }
  } else {
    $('todayCardAction').style.display = 'none';
    textEl.innerHTML = '💬 ' + getSmartTip(tipBreed, tipMonth);
    textEl.className = 'today-card-text';
    card.classList.remove('reminder');
    iconEl.textContent = '💡';
  }
});

// ---- 从提醒快捷跳转到记录 ----
let _editingEventId = null;  // 当前正在编辑的事件ID

function editEvent(eventId) {
  const ev = _allEvents.find(e => e.id === eventId);
  if (!ev) { showToast('找不到这条记录，主人刷新页面试试～', true); return; }

  // 填入表单
  $('fEType').value = ev.type;
  renderExtraFields();

  // 设置日期滚轮
  const parts = ev.date.split('-');
  if (parts.length === 3) {
    scrollWheelToValue('wheelYear', parseInt(parts[0]));
    scrollWheelToValue('wheelMonth', parseInt(parts[1]));
    scrollWheelToValue('wheelDay', parseInt(parts[2]));
  }

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
  resetWheelDate();
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

async function loadProfile() {
  const area = $('profileCardBody');
  const empty = $('profileCardEmpty');
  const editBtn = $('btnEditProfile');
  const header = $('profileCardHeader');
  try {
    const dog = await api('/api/dog');
    _cachedDog = dog;
    const age = calcAge(dog.birthday);

    // 缓存健康数据
    try { _cachedHealthData = await api('/api/health_check'); } catch (e) {}

    // 显示档案内容
    if (empty) empty.style.display = 'none';
    if (area) area.style.display = '';
    if (header) header.style.display = '';

    area.innerHTML = `
      <div class="profile-info-item">🐶 <strong>名字：</strong>${escHtml(dog.name)}</div>
      <div class="profile-info-item">🐕 <strong>品种：</strong>${escHtml(dog.breed)}</div>
      <div class="profile-info-item">🎂 <strong>生日：</strong>${dog.birthday}<span style="color:var(--muted);font-size:0.85em;">（${age}）</span></div>
      <div class="profile-info-item">⚖️ <strong>体重：</strong>${dog.weight || '未填写'}</div>
      <div class="profile-info-item">✂️ <strong>绝育：</strong>${dog.neutered || '未知'}</div>
      <div class="profile-info-item">⚠️ <strong>过敏源：</strong>${dog.allergies || '未填写'}</div>
    `;

    if (editBtn) editBtn.style.display = '';

    // 显示狗狗照片和欢迎条
    showDogPhoto(dog.photo, dog.breed);
    updateGreeting(dog.name);

    // 更新事件卡片副标题
    updateEventSubtitle(dog.name);

    // 预加载饮食和保健品数据
    loadDietCard();
    loadSupplements();

    // 幼犬显示体重追踪
    if (calcIsPuppy(dog.birthday)) {
      $('weightLogSection').style.display = '';
      $('wlDate').value = new Date().toISOString().slice(0, 10);
      loadWeightLogs();
    } else {
      $('weightLogSection').style.display = 'none';
    }
  } catch (e) {
    // 未建档状态
    if (area) area.style.display = 'none';
    if (empty) empty.style.display = '';
    if (editBtn) editBtn.style.display = 'none';
    if (header) header.style.display = 'none';
    $('weightLogSection').style.display = 'none';
  }
}

// ---- 狗狗照片 ----
function showDogPhoto(photoFilename, breed) {
  const breedIcon = getBreedIcon(breed || '') || '🐶';

  // 更新欢迎条头像
  const avatar = $('greetingAvatar');
  if (avatar) {
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
  const subAvatars = document.querySelectorAll('.greeting-avatar-sm');
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

// 点击 header 照片触发更换
$('greetingAvatar').addEventListener('click', function() {
  if (!_cachedDog) { showToast('主人，请先创建狗狗档案～', true); return; }
  $('dogPhotoInput').click();
});

// 子页面小头像点击也可上传
document.addEventListener('click', function(e) {
  if (e.target.closest('.greeting-avatar-sm')) {
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
      area.innerHTML = `<div style="font-size:0.9em;color:var(--brown-light);line-height:1.8;">🐾 ${escHtml(data.message)}</div>`;
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
        </div>

        <!-- 右侧：辅助信息 -->
        <div class="recipe-side">
          <div class="side-section">
            <div class="side-label">🔄 替换选择</div>
            <div class="side-text" style="font-size:0.82em;line-height:1.7;">
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
    if (!data.has_dog || data.alerts.length === 0) {
      card.style.display = '';
      area.innerHTML = '<div class="supp-empty">🛡️ 主人把我照顾得很好，暂时不需要额外补给，继续保持哦～</div>';
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
      </div>`).join('');
  } catch (e) {
    card.style.display = 'none';
  }
}
// ---- 体重日志 ----
async function loadWeightLogs() {
  const list = $('weightLogList');
  try {
    const logs = await api('/api/weight_logs');
    if (!logs || logs.length === 0) {
      list.innerHTML = '<div style="font-size:0.82em;color:var(--muted);padding:4px 0;">还没有体重记录，主人快帮我添加第一条吧～</div>';
      return;
    }
    list.innerHTML = logs.map(l => `
      <div style="display:flex;justify-content:space-between;font-size:0.85em;padding:3px 0;border-bottom:1px dotted var(--border);">
        <span>${l.date}</span>
        <span style="font-weight:600;color:var(--brown);">${escHtml(l.weight)}</span>
      </div>`).join('');
  } catch (e) {
    list.innerHTML = '<div style="font-size:0.82em;color:var(--muted);">加载体重记录失败</div>';
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
    loadProfile(); // 刷新档案中显示的体重
  } catch (e) {
    showToast(e.message || '记录体重失败', true);
  }
  btn.disabled = false;
  btn.textContent = '+ 记录';
});

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
        </div>
        <div class="timeline-actions">
          <button class="timeline-btn" title="编辑" onclick="editEvent(${e.id})" style="font-size:0.85em;">✏️</button>
          <button class="timeline-btn del" title="删除" onclick="deleteEvent(${e.id})" style="font-size:0.85em;">🗑</button>
        </div>
      </div>`;
  }
  return html;
}

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
  const yearSel = $('mBirthYear');
  const monthSel = $('mBirthMonth');
  const daySel = $('mBirthDay');
  const now = new Date();
  const curYear = now.getFullYear();

  // 年份：从当前年往前20年
  for (let y = curYear; y >= curYear - 20; y--) {
    const opt = document.createElement('option');
    opt.value = y;
    opt.textContent = y + '年';
    if (y === curYear - 1) opt.selected = true; // 默认1岁
    yearSel.appendChild(opt);
  }

  // 月份：1-12
  for (let m = 1; m <= 12; m++) {
    const opt = document.createElement('option');
    opt.value = m;
    opt.textContent = m + '月';
    if (m === 6) opt.selected = true;
    monthSel.appendChild(opt);
  }

  // 日期：根据年月动态更新
  function updateDays() {
    const y = parseInt(yearSel.value);
    const m = parseInt(monthSel.value);
    const daysInMonth = new Date(y, m, 0).getDate();
    const curDay = parseInt(daySel.value) || 15;
    daySel.innerHTML = '';
    for (let d = 1; d <= daysInMonth; d++) {
      const opt = document.createElement('option');
      opt.value = d;
      opt.textContent = d + '日';
      if (d === Math.min(curDay, daysInMonth)) opt.selected = true;
      daySel.appendChild(opt);
    }
  }

  yearSel.addEventListener('change', updateDays);
  monthSel.addEventListener('change', updateDays);
  updateDays();
}

// 弹窗建档提交
$('btnModalCreate').addEventListener('click', async function() {
  const btn = this;
  const name = $('mName').value.trim();
  const breed = $('mBreed').value;
  const year = $('mBirthYear').value;
  const month = String($('mBirthMonth').value).padStart(2, '0');
  const day = String($('mBirthDay').value).padStart(2, '0');
  const birthday = year + '-' + month + '-' + day;
  const weight = $('mWeight').value.trim();
  const neutered = $('mNeutered').value;
  const allergies = $('mAllergies').value.trim();

  if (!name || !breed) {
    showToast('汪汪，名字和品种是必填的哦，主人再检查一下～', true);
    return;
  }
  if (new Date(birthday) > new Date()) {
    showToast('生日不能是未来的日子哦，主人～', true);
    return;
  }

  btn.disabled = true;
  btn.textContent = '正在建档...';
  try {
    const r = await api('/api/dog', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, breed, birthday, weight, neutered, allergies }),
    });
    showToast(r.message);
    // 隐藏弹窗，显示主界面
    $('modalOverlay').style.display = 'none';
    $('mainContent').classList.remove('main-hidden');
    $('greetingBar').classList.remove('main-hidden');
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
function initEditBirthdaySelects(preYear, preMonth, preDay) {
  const yearSel = $('eBirthYear');
  const monthSel = $('eBirthMonth');
  const daySel = $('eBirthDay');
  yearSel.innerHTML = '';
  monthSel.innerHTML = '';
  daySel.innerHTML = '';
  const now = new Date();
  const curYear = now.getFullYear();

  for (let y = curYear; y >= curYear - 20; y--) {
    const opt = document.createElement('option');
    opt.value = y;
    opt.textContent = y + '年';
    if (y === preYear) opt.selected = true;
    yearSel.appendChild(opt);
  }
  for (let m = 1; m <= 12; m++) {
    const opt = document.createElement('option');
    opt.value = m;
    opt.textContent = m + '月';
    if (m === preMonth) opt.selected = true;
    monthSel.appendChild(opt);
  }
  function updateDays() {
    const y = parseInt(yearSel.value);
    const m = parseInt(monthSel.value);
    const daysInMonth = new Date(y, m, 0).getDate();
    const curDay = parseInt(daySel.value) || preDay;
    daySel.innerHTML = '';
    for (let d = 1; d <= daysInMonth; d++) {
      const opt = document.createElement('option');
      opt.value = d;
      opt.textContent = d + '日';
      if (d === Math.min(curDay, daysInMonth)) opt.selected = true;
      daySel.appendChild(opt);
    }
  }
  yearSel.addEventListener('change', updateDays);
  monthSel.addEventListener('change', updateDays);
  updateDays();
}

// 打开编辑弹窗
$('btnEditProfile').addEventListener('click', async function() {
  try {
    const dog = await api('/api/dog');
    // 预填所有字段
    $('eName').value = dog.name;
    $('eBreed').value = dog.breed;
    $('eWeight').value = dog.weight || '';
    $('eNeutered').value = dog.neutered || '未知';
    $('eAllergies').value = dog.allergies || '';
    // 解析生日
    const parts = dog.birthday.split('-');
    initEditBirthdaySelects(parseInt(parts[0]), parseInt(parts[1]), parseInt(parts[2]));
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
  const year = $('eBirthYear').value;
  const month = String($('eBirthMonth').value).padStart(2, '0');
  const day = String($('eBirthDay').value).padStart(2, '0');
  const birthday = year + '-' + month + '-' + day;
  const weight = $('eWeight').value.trim();
  const neutered = $('eNeutered').value;
  const allergies = $('eAllergies').value.trim();

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
      body: JSON.stringify({ name, breed, birthday, weight, neutered, allergies }),
    });
    showToast(r.message);
    $('editModalOverlay').style.display = 'none';
    loadProfile();
    loadTimeline();
    loadToday();
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
  if (hour >= 5 && hour < 12) greeting = '早安，主人！';
  else if (hour >= 12 && hour < 18) greeting = '午安，主人！';
  else if (hour >= 18 && hour < 22) greeting = '晚安，主人！🌙';
  else greeting = '月亮都睡着啦，主人也该休息了～🌙';
  $('greetingText').textContent = greeting;
  $('greetingBar').classList.remove('main-hidden');
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
  const greetingBar = $('greetingBar');

  if (page === 'home') {
    if (homePage) homePage.style.display = '';
    if (greetingBar) greetingBar.classList.remove('main-hidden');
    loadToday();
    return;
  }

  // 进入子页面：隐藏首页和欢迎条
  if (homePage) homePage.style.display = 'none';
  if (greetingBar) greetingBar.classList.add('main-hidden');

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
  } else if (page === 'timeline') {
    loadTimeline2();
  } else if (page === 'supplement') {
    loadSupplements();
  }
}

// ---- 大事记子页面时间线 ----
async function loadTimeline2() {
  // 复用主时间线加载逻辑，然后同步到 timelineArea2
  await loadTimeline();
  const area1 = $('timelineArea');
  const area2 = $('timelineArea2');
  if (area1 && area2) {
    area2.innerHTML = area1.innerHTML;
  }
}

// 应用初始化：检查是否已有狗狗档案
async function initApp() {
  try {
    await api('/api/dog');
    // 有档案 → 隐藏弹窗，显示主界面
    $('modalOverlay').style.display = 'none';
    $('mainContent').classList.remove('main-hidden');
    $('greetingBar').classList.remove('main-hidden');
    return true;
  } catch (e) {
    // 无档案 → 显示建档弹窗
    $('modalOverlay').style.display = 'flex';
    $('mainContent').classList.add('main-hidden');
    $('greetingBar').classList.add('main-hidden');
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

// ---- 滚轮日期选择器 ----
function initWheelPicker() {
  const yearWheel = $('wheelYear');
  const monthWheel = $('wheelMonth');
  const dayWheel = $('wheelDay');
  const now = new Date();
  const curYear = now.getFullYear();

  for (let y = curYear; y >= curYear - 20; y--) {
    const div = document.createElement('div');
    div.className = 'wheel-item';
    div.textContent = y + '年';
    div.dataset.value = y;
    yearWheel.appendChild(div);
  }
  for (let m = 1; m <= 12; m++) {
    const div = document.createElement('div');
    div.className = 'wheel-item';
    div.textContent = m + '月';
    div.dataset.value = m;
    monthWheel.appendChild(div);
  }

  function getDaysInMonth(y, m) {
    return new Date(y, m, 0).getDate();
  }

  function populateDays(y, m) {
    const daysInMonth = getDaysInMonth(y, m);
    const curSelected = getWheelSelected(dayWheel);
    const curDay = parseInt(curSelected) || 15;
    dayWheel.innerHTML = '';
    for (let d = 1; d <= daysInMonth; d++) {
      const div = document.createElement('div');
      div.className = 'wheel-item';
      div.textContent = d + '日';
      div.dataset.value = d;
      dayWheel.appendChild(div);
    }
    requestAnimationFrame(() => {
      scrollToWheelValue(dayWheel, Math.min(curDay, daysInMonth));
    });
  }

  let scrollTimer;
  function onYearMonthScroll() {
    clearTimeout(scrollTimer);
    scrollTimer = setTimeout(() => {
      const y = parseInt(getWheelSelected(yearWheel)) || curYear;
      const m = parseInt(getWheelSelected(monthWheel)) || (now.getMonth() + 1);
      populateDays(y, m);
    }, 150);
  }

  yearWheel.addEventListener('scroll', onYearMonthScroll);
  monthWheel.addEventListener('scroll', onYearMonthScroll);

  // Highlight active item on scroll
  [yearWheel, monthWheel, dayWheel].forEach(w => {
    w.addEventListener('scroll', () => updateWheelHighlight(w));
  });

  // Default: today
  scrollToWheelValue(yearWheel, curYear);
  scrollToWheelValue(monthWheel, now.getMonth() + 1);
  populateDays(curYear, now.getMonth() + 1);
  setTimeout(() => {
    scrollToWheelValue(dayWheel, now.getDate());
    updateWheelHighlight(yearWheel);
    updateWheelHighlight(monthWheel);
    updateWheelHighlight(dayWheel);
  }, 100);
}

function getWheelSelected(wheel) {
  const container = wheel;
  const center = container.scrollTop + container.clientHeight / 2;
  const items = container.querySelectorAll('.wheel-item');
  let closest = null;
  let minDist = Infinity;
  items.forEach(item => {
    const itemCenter = item.offsetTop + item.offsetHeight / 2;
    const dist = Math.abs(itemCenter - center);
    if (dist < minDist) {
      minDist = dist;
      closest = item;
    }
  });
  return closest ? closest.dataset.value : '';
}

function scrollToWheelValue(wheel, value) {
  const items = wheel.querySelectorAll('.wheel-item');
  for (const item of items) {
    if (item.dataset.value == value) {
      wheel.scrollTo({ top: item.offsetTop - wheel.clientHeight / 2 + item.offsetHeight / 2, behavior: 'instant' });
      return;
    }
  }
}

function updateWheelHighlight(wheel) {
  const items = wheel.querySelectorAll('.wheel-item');
  const center = wheel.scrollTop + wheel.clientHeight / 2;
  items.forEach(item => {
    const itemCenter = item.offsetTop + item.offsetHeight / 2;
    if (Math.abs(itemCenter - center) < 20) {
      item.classList.add('active');
    } else {
      item.classList.remove('active');
    }
  });
}

function getWheelDate() {
  const y = getWheelSelected($('wheelYear'));
  const m = String(getWheelSelected($('wheelMonth'))).padStart(2, '0');
  const d = String(getWheelSelected($('wheelDay'))).padStart(2, '0');
  return y + '-' + m + '-' + d;
}

function resetWheelDate() {
  const now = new Date();
  scrollToWheelValue($('wheelYear'), now.getFullYear());
  scrollToWheelValue($('wheelMonth'), now.getMonth() + 1);
  // repopulate days for current month
  const curYear = now.getFullYear();
  const curMonth = now.getMonth() + 1;
  const daysInMonth = new Date(curYear, curMonth, 0).getDate();
  const dayWheel = $('wheelDay');
  dayWheel.innerHTML = '';
  for (let d = 1; d <= daysInMonth; d++) {
    const div = document.createElement('div');
    div.className = 'wheel-item';
    div.textContent = d + '日';
    div.dataset.value = d;
    dayWheel.appendChild(div);
  }
  setTimeout(() => {
    scrollToWheelValue(dayWheel, now.getDate());
    ['wheelYear','wheelMonth','wheelDay'].forEach(id => updateWheelHighlight($(id)));
  }, 50);
}

// 页面加载时初始化滚轮
initWheelPicker();

// ---- 提交事件 ----
$('btnSubmitEvent').addEventListener('click', async function() {
  const btn = this;
  const type = $('fEType').value;
  const dateVal = getWheelDate();

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
    }
    reactionBox.className = 'reaction-box show';
    // 重置表单和编辑状态
    cancelEdit();
    resetWheelDate();
    renderExtraFields();
    loadTimeline();
    loadToday();
  } catch (e) {
    reactionBox.textContent = '汪汪，信号被狗吃了，点我重试～';
    reactionBox.className = 'reaction-box show error';
    reactionBox.style.cursor = 'pointer';
    reactionBox.onclick = () => $('btnSubmitEvent').click();
  }
  btn.disabled = false;
  btn.textContent = '🐾 提交记录';
});

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
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    run_server()
