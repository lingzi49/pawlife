#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PawLife 微信小程序后端（FastAPI + PostgreSQL）
==============================================
启动方式：uvicorn pawlife_backend:app --host 0.0.0.0 --port 8000
部署目标：Render / 任何支持 Python 的云服务
数据库：PostgreSQL（Supabase 免费版或 Render PostgreSQL）
"""
import csv, io, os, sys, json, re, hashlib, secrets, time, random
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Literal
from contextlib import contextmanager

import requests
from fastapi import FastAPI, HTTPException, Depends, Header, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, validator
from sqlalchemy import create_engine, Column, Integer, String, Float, Date, DateTime, Text, Index, text
from sqlalchemy.orm import declarative_base, sessionmaker, scoped_session, Session

# ============================================================
# 配置
# ============================================================
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost:5432/pawlife")
WX_APPID = os.getenv("WX_APPID", "")
WX_SECRET = os.getenv("WX_SECRET", "")
JWT_SECRET = os.getenv("JWT_SECRET", secrets.token_hex(32))
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
PHOTOS_DIR = os.path.join(DATA_DIR, "photos")
os.makedirs(PHOTOS_DIR, exist_ok=True)

# ============================================================
# 数据库
# ============================================================
engine = create_engine(DATABASE_URL, pool_size=10, max_overflow=20)
SessionLocal = scoped_session(sessionmaker(bind=engine))
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ============================================================
# 模型
# ============================================================
class User(Base):
    __tablename__ = "users"
    openid = Column(String(64), primary_key=True)
    session_key = Column(String(64))
    unionid = Column(String(64), nullable=True)
    nickname = Column(String(64), nullable=True)
    avatar_url = Column(String(512), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Dog(Base):
    __tablename__ = "dogs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_id = Column(String(64), nullable=False, index=True)
    name = Column(String(64), nullable=False)
    breed = Column(String(32), nullable=False)
    birthday = Column(Date, nullable=False)
    weight = Column(String(16), nullable=True)
    neutered = Column(String(8), nullable=True, default="未知")
    allergies = Column(String(256), nullable=True)
    gender = Column(String(10), nullable=True)
    photo = Column(String(128), nullable=True)
    bath_interval_days = Column(Integer, nullable=True)
    last_bath_date = Column(Date, nullable=True)
    diseases = Column(String(256), nullable=True)
    suspended_until = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Event(Base):
    __tablename__ = "events"
    id = Column(Integer, primary_key=True, autoincrement=True)
    dog_id = Column(Integer, nullable=False, index=True)
    type = Column(String(32), nullable=False)
    date = Column(Date, nullable=False)
    detail = Column(Text, nullable=True)
    high_risk = Column(Integer, nullable=False, default=0)
    risk_keyword = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class WeightLog(Base):
    __tablename__ = "weight_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    dog_id = Column(Integer, nullable=False)
    weight = Column(String(16), nullable=False)
    date = Column(Date, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class SupplementAlert(Base):
    __tablename__ = "supplement_alerts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    dog_id = Column(Integer, nullable=False)
    supplement_name = Column(String(64), nullable=False)
    reason = Column(String(256), nullable=False)
    woof_text = Column(String(512), nullable=False)
    priority = Column(Integer, nullable=False, default=2)
    is_active = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)

class RiskLog(Base):
    __tablename__ = "risk_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    dog_id = Column(Integer, nullable=False)
    input_text = Column(String(512), nullable=False)
    matched_keyword = Column(String(64), nullable=False)
    action_taken = Column(String(64), nullable=False, default="suspended_diet_and_supplements")
    warning_shown = Column(Integer, nullable=False, default=1)
    user_confirmed = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

class SubscribeTemplate(Base):
    __tablename__ = "subscribe_templates"
    id = Column(Integer, primary_key=True, autoincrement=True)
    openid = Column(String(64), nullable=False, index=True)
    template_id = Column(String(64), nullable=False)
    template_type = Column(String(32), nullable=False)
    is_active = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)

class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    idem_key = Column(String(128), primary_key=True)
    response = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

# ============================================================
# Pydantic 模型
# ============================================================
BREED_OPTIONS = ["金毛", "拉布拉多", "柯基", "贵宾", "豆柴", "混血", "其他"]

class DogCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    breed: str
    birthday: date
    weight: Optional[str] = None
    neutered: Optional[str] = "未知"
    allergies: Optional[str] = None
    gender: Optional[Literal["male", "female"]] = None
    diseases: Optional[str] = None

    @validator("breed")
    def breed_valid(cls, v):
        if v not in BREED_OPTIONS:
            raise ValueError(f"品种必须是以下之一：{'/'.join(BREED_OPTIONS)}")
        return v

class EventCreate(BaseModel):
    dog_id: int
    type: str
    date: date
    detail: Optional[Dict[str, Any]] = None
    idem_key: Optional[str] = None
    high_risk: Optional[int] = 0
    risk_keyword: Optional[str] = None

class LoginRequest(BaseModel):
    code: str
    nickname: Optional[str] = None
    avatar_url: Optional[str] = None

class SubscribeRequest(BaseModel):
    template_ids: List[str]
    template_type: str  # "vaccine" / "deworm" / "bath"

# ============================================================
# FastAPI 应用
# ============================================================
app = FastAPI(title="PawLife 小程序后端", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ============================================================
# 认证依赖
# ============================================================
def get_current_user(authorization: str = Header(None)) -> str:
    """从 Authorization header 中解析 token，返回 openid"""
    if not authorization:
        raise HTTPException(status_code=401, detail="主人，请先登录哦～")
    token = authorization.replace("Bearer ", "")
    try:
        # 简单 token：sha256(openid + secret)
        with SessionLocal() as db:
            user = db.query(User).first()
            if user:
                expected = hashlib.sha256((user.openid + JWT_SECRET).encode()).hexdigest()
                if secrets.compare_digest(token, expected):
                    return user.openid
    except Exception:
        pass
    raise HTTPException(status_code=401, detail="汪汪！登录过期了，主人重新进一下吧～")

# ============================================================
# 微信登录接口
# ============================================================
@app.post("/api/login")
def api_login(payload: LoginRequest):
    """微信登录：code 换 openid，生成 token"""
    if not WX_APPID or not WX_SECRET:
        # 开发阶段：直接用 code 作为 openid
        openid = hashlib.sha256(payload.code.encode()).hexdigest()[:32]
        session_key = "dev_session"
    else:
        url = "https://api.weixin.qq.com/sns/jscode2session"
        params = {"appid": WX_APPID, "secret": WX_SECRET, "js_code": payload.code, "grant_type": "authorization_code"}
        resp = requests.get(url, params=params, timeout=10).json()
        openid = resp.get("openid")
        session_key = resp.get("session_key", "")
        if not openid:
            raise HTTPException(status_code=400, detail=f"微信登录失败：{resp.get('errmsg', '未知错误')}")

    with SessionLocal() as db:
        user = db.query(User).filter(User.openid == openid).first()
        if not user:
            user = User(openid=openid, session_key=session_key, nickname=payload.nickname, avatar_url=payload.avatar_url)
            db.add(user)
        else:
            user.session_key = session_key
            if payload.nickname:
                user.nickname = payload.nickname
        db.flush()

    token = hashlib.sha256((openid + JWT_SECRET).encode()).hexdigest()
    return {"token": token, "openid": openid, "has_dog": _user_has_dog(openid)}

def _user_has_dog(openid: str) -> bool:
    with SessionLocal() as db:
        return db.query(Dog).filter(Dog.owner_id == openid).first() is not None

# ============================================================
# 狗狗档案 API（全部加上用户隔离）
# ============================================================
@app.get("/api/dog")
def api_get_dog(openid: str = Depends(get_current_user)):
    with SessionLocal() as db:
        dog = db.query(Dog).filter(Dog.owner_id == openid).order_by(Dog.created_at.desc()).first()
        if not dog:
            raise HTTPException(status_code=404, detail="还没有狗狗档案，主人先去建档吧～")
        return {
            "id": dog.id, "name": dog.name, "breed": dog.breed,
            "birthday": dog.birthday.isoformat(), "weight": dog.weight or "",
            "neutered": dog.neutered or "未知", "allergies": dog.allergies or "",
            "gender": dog.gender or "", "photo": dog.photo or "",
            "diseases": dog.diseases or "",
            "suspended_until": dog.suspended_until.isoformat() if dog.suspended_until else None,
        }

@app.post("/api/dog")
def api_create_dog(payload: DogCreate, openid: str = Depends(get_current_user)):
    with SessionLocal() as db:
        dog = Dog(
            owner_id=openid, name=payload.name, breed=payload.breed,
            birthday=payload.birthday, weight=payload.weight,
            neutered=payload.neutered or "未知", allergies=payload.allergies,
            gender=payload.gender, diseases=payload.diseases,
            bath_interval_days=_calc_bath_interval(payload.weight),
            last_bath_date=date.today(),
        )
        db.add(dog)
        db.flush()
        _refresh_supplement_alerts(db, dog)
        return {"message": f"汪汪！主人你好，我是{dog.name}！一只{dog.breed}宝宝～以后请多多关照我的小肉垫，我会陪你很久很久的！🐾", "dog_id": dog.id}

@app.put("/api/dog")
def api_update_dog(payload: DogCreate, openid: str = Depends(get_current_user)):
    with SessionLocal() as db:
        dog = db.query(Dog).filter(Dog.owner_id == openid).order_by(Dog.created_at.desc()).first()
        if not dog:
            raise HTTPException(status_code=404, detail="还没有狗狗档案，主人快去建档吧～")
        dog.name = payload.name; dog.breed = payload.breed; dog.birthday = payload.birthday
        dog.weight = payload.weight; dog.neutered = payload.neutered or "未知"
        dog.allergies = payload.allergies; dog.gender = payload.gender
        dog.diseases = payload.diseases
        dog.bath_interval_days = _calc_bath_interval(payload.weight)
        db.flush()
        _refresh_supplement_alerts(db, dog)
        return {"message": "汪汪！主人，我的档案更新好了～以后请继续多多关照我的小肉垫！🐾", "dog_id": dog.id}

@app.post("/api/dog/unsuspend")
def api_unsuspend_dog(openid: str = Depends(get_current_user)):
    with SessionLocal() as db:
        dog = db.query(Dog).filter(Dog.owner_id == openid).order_by(Dog.created_at.desc()).first()
        if not dog:
            raise HTTPException(status_code=404, detail="还没有狗狗档案，主人先去建档吧～")
        dog.suspended_until = None
        db.flush()
        return {"message": "汪汪！警报已解除，饮食和保健品建议已恢复正常～🐾"}

# ============================================================
# 事件 API
# ============================================================
@app.post("/api/event")
def api_create_event(payload: EventCreate, openid: str = Depends(get_current_user)):
    # 幂等检查
    if payload.idem_key:
        with SessionLocal() as db:
            cached = db.query(IdempotencyKey).filter(IdempotencyKey.idem_key == payload.idem_key).first()
            if cached and cached.response != "__processing__":
                return {"message": cached.response, "duplicate": True}
            if not cached:
                db.add(IdempotencyKey(idem_key=payload.idem_key, response="__processing__"))
                db.flush()

    with SessionLocal() as db:
        dog = db.query(Dog).filter(Dog.id == payload.dog_id, Dog.owner_id == openid).first()
        if not dog:
            raise HTTPException(status_code=404, detail="找不到这只狗狗，主人先建档吧～")
        if payload.type == "发情" and dog.gender == "male":
            raise HTTPException(status_code=400, detail="我是小王子，不会来姨妈哦～")

        detail_json = json.dumps(payload.detail, ensure_ascii=False) if payload.detail else None
        event = Event(dog_id=payload.dog_id, type=payload.type, date=payload.date,
                       detail=detail_json, high_risk=payload.high_risk or 0, risk_keyword=payload.risk_keyword or None)
        db.add(event)

        # 高风险事件：暂停建议 + 记录日志
        if payload.high_risk:
            today_end = datetime.utcnow().replace(hour=23, minute=59, second=59, microsecond=0)
            dog.suspended_until = today_end
            symptom_text = ""
            if payload.detail and isinstance(payload.detail, dict):
                symptoms = payload.detail.get("symptoms", [])
                if isinstance(symptoms, list):
                    symptom_text = "，".join(symptoms)
            db.add(RiskLog(dog_id=payload.dog_id, input_text=symptom_text[:512],
                           matched_keyword=payload.risk_keyword or "",
                           action_taken="suspended_diet_and_supplements", warning_shown=1, user_confirmed=1))

        detail_dict = payload.detail if isinstance(payload.detail, dict) else {}
        reaction = _generate_reaction(payload.type, dog, detail_dict)

        if payload.idem_key:
            ik = db.query(IdempotencyKey).filter(IdempotencyKey.idem_key == payload.idem_key).first()
            if ik:
                ik.response = reaction
        db.flush()
        return {"message": reaction, "event_id": event.id}

@app.put("/api/event/{event_id}")
def api_update_event(event_id: int, payload: EventCreate, openid: str = Depends(get_current_user)):
    with SessionLocal() as db:
        event = db.query(Event).filter(Event.id == event_id).first()
        if not event:
            raise HTTPException(status_code=404, detail="找不到这条事件记录，主人～")
        dog = db.query(Dog).filter(Dog.id == event.dog_id, Dog.owner_id == openid).first()
        if not dog:
            raise HTTPException(status_code=404, detail="找不到这只狗狗～")
        if payload.type == "发情" and dog.gender == "male":
            raise HTTPException(status_code=400, detail="我是小王子，不会来姨妈哦～")
        event.type = payload.type; event.date = payload.date
        event.detail = json.dumps(payload.detail, ensure_ascii=False) if payload.detail else None
        db.flush()
        return {"message": "汪汪！事件已更新，主人的记录越来越完整了～🐾", "event_id": event.id}

# ============================================================
# 时间线 API
# ============================================================
@app.get("/api/timeline")
def api_timeline(openid: str = Depends(get_current_user)):
    with SessionLocal() as db:
        dog = db.query(Dog).filter(Dog.owner_id == openid).order_by(Dog.created_at.desc()).first()
        if not dog:
            return {"has_dog": False, "timeline": []}
        events = db.query(Event).filter(Event.dog_id == dog.id).order_by(Event.date.desc()).all()
        return {"has_dog": True, "dog_name": dog.name, "timeline": [{
            "id": e.id, "type": e.type, "date": e.date.isoformat(),
            "detail": json.loads(e.detail) if e.detail else {},
            "high_risk": e.high_risk, "risk_keyword": e.risk_keyword,
        } for e in events]}

# ============================================================
# 饮食宝典 API（核心业务逻辑保持与网页版一致）
# ============================================================
@app.get("/api/dog/diet")
def api_dog_diet(openid: str = Depends(get_current_user)):
    import random
    with SessionLocal() as db:
        dog = db.query(Dog).filter(Dog.owner_id == openid).order_by(Dog.created_at.desc()).first()
        if not dog:
            raise HTTPException(status_code=404, detail="还没有狗狗档案，主人先建档吧～")
        if dog.suspended_until and dog.suspended_until > datetime.utcnow():
            return {"ready": False, "suspended": True, "message": "🚨 因您最近记录了高风险症状，今日饮食建议已暂停。"}
        weight_kg = _parse_weight_kg(dog.weight)
        if weight_kg is None:
            return {"ready": False, "message": "主人，我的档案里体重还没填呢～"}
        age_stage = _get_age_stage(dog.birthday)
        body_size = _get_body_size(dog.weight)
        foods = DIET_FOODS.get((age_stage, body_size))
        if foods is None:
            return {"ready": False, "message": "主人，我的档案还不够完整～"}
        plan = _calc_daily_grams(dog.birthday, weight_kg, dog.neutered or "未知", dog.gender)
        meals = foods["meals"]
        daily_recipe = random.choice(foods["daily"])
        allergies_str = dog.allergies or ""
        norm_protein = _normalize_food(foods["protein"])
        norm_veggie = _normalize_food(foods["veggie"])
        norm_carb = _normalize_food(foods["carb"])
        if not _filter_allergen_foods(norm_protein, allergies_str):
            norm_protein = _get_safe_fallback(allergies_str, "protein")
        if not _filter_allergen_foods(norm_veggie, allergies_str):
            norm_veggie = _get_safe_fallback(allergies_str, "veggie")
        if not _filter_allergen_foods(norm_carb, allergies_str):
            norm_carb = _get_safe_fallback(allergies_str, "carb")
        per_meal_protein = round(plan["protein_g"] / meals)
        per_meal_carb = round(plan["carb_g"] / meals)
        per_meal_veggie = round(plan["veggie_g"] / meals)

        def _build_item(name, weight):
            nut = FOOD_NUTRITION.get(name, FOOD_NUTRITION.get("鸡胸肉"))
            factor = weight / 100.0
            return {"name": name, "emoji": nut["emoji"], "weight": weight,
                    "protein": round(nut["protein"] * factor, 1),
                    "fat": round(nut["fat"] * factor, 1),
                    "carbs": round(nut["carbs"] * factor, 1)}
        items = [_build_item(norm_protein, per_meal_protein), _build_item(norm_veggie, per_meal_veggie), _build_item(norm_carb, per_meal_carb)]
        total_weight = sum(it["weight"] for it in items)
        total_protein = round(sum(it["protein"] for it in items), 1)
        total_fat = round(sum(it["fat"] for it in items), 1)
        total_carbs = round(sum(it["carbs"] for it in items), 1)
        meal_type_names = {4: "早餐", 3: "午餐", 2: "早餐"}
        meal_type = meal_type_names.get(meals, "一餐")
        meal_name = "".join(it["name"] for it in items) + "饭"
        fish_oil = "0.5ml/5kg体重，每周2-3次" if weight_kg < 15 else "1ml/5kg体重，每周2-3次"
        protein_options = "鸡胸肉、鸭肉、瘦牛肉、三文鱼、鳕鱼"
        carb_options = "糙米、燕麦、红薯、南瓜、藜麦"
        veggie_options = "胡萝卜、西兰花、菠菜、西葫芦、南瓜"
        if body_size == "小型犬":
            protein_options = "鸡胸肉、鱼肉、虾仁、蛋黄、鸭肉"
        protein_options = _filter_options(protein_options, allergies_str, "protein")
        carb_options = _filter_options(carb_options, allergies_str, "carb")
        veggie_options = _filter_options(veggie_options, allergies_str, "veggie")
        allergy_note = f"⚠️ 已避开你的过敏源（{allergies_str}），替换为安全的食材啦～" if allergies_str else ""
        hypoglycemia_note = ""
        if weight_kg is not None and weight_kg < 2 and age_stage == "幼犬":
            hypoglycemia_note = "⚠️ 超小型幼犬（<2kg）有低血糖风险，建议每天进食6-8次！"
        disease_note = ""
        if (dog.diseases or "").strip():
            disease_note = f"⚕️ 档案中记录有已知健康状况（{dog.diseases}），此饮食建议仅供兽医参考。"
        return {
            "ready": True, "dog_name": dog.name, "age_stage": age_stage, "body_size": body_size,
            "weight_kg": plan["weight_kg"], "meals_per_day": meals, "meal_type": meal_type,
            "meal_name": meal_name, "items": items, "total_weight": total_weight,
            "total_protein": total_protein, "total_fat": total_fat, "total_carbs": total_carbs,
            "daily_recipe": daily_recipe, "tip": foods["tip"], "fish_oil": fish_oil,
            "protein_options": protein_options, "carb_options": carb_options, "veggie_options": veggie_options,
            "allergy_note": allergy_note, "disease_note": disease_note, "hypoglycemia_note": hypoglycemia_note,
        }

# ============================================================
# 保健品 API
# ============================================================
@app.get("/api/supplements")
def api_supplements(openid: str = Depends(get_current_user)):
    with SessionLocal() as db:
        dog = db.query(Dog).filter(Dog.owner_id == openid).order_by(Dog.created_at.desc()).first()
        if not dog:
            return {"has_dog": False, "alerts": []}
        if dog.suspended_until and dog.suspended_until > datetime.utcnow():
            return {"has_dog": True, "suspended": True, "alerts": [], "message": "🚨 今日保健品建议已暂停。"}
        _refresh_supplement_alerts(db, dog)
        alerts = db.query(SupplementAlert).filter(
            SupplementAlert.dog_id == dog.id, SupplementAlert.is_active == 1
        ).order_by(SupplementAlert.priority).all()
        return {"has_dog": True, "dog_name": dog.name, "alerts": [
            {"id": a.id, "supplement_name": a.supplement_name, "reason": a.reason,
             "woof_text": a.woof_text, "priority": a.priority} for a in alerts
        ]}

# ============================================================
# 健康检查 API（今日汪汪 + 提醒）
# ============================================================
@app.get("/api/health_check")
def api_health_check(openid: str = Depends(get_current_user)):
    with SessionLocal() as db:
        dog = db.query(Dog).filter(Dog.owner_id == openid).order_by(Dog.created_at.desc()).first()
        if not dog:
            return {"has_dog": False, "reminders": [], "latest_event": None}
        events = db.query(Event).filter(Event.dog_id == dog.id).order_by(Event.date.desc()).all()
        last_vaccine = last_deworm = last_heat = None
        for e in events:
            if e.type == "疫苗" and (last_vaccine is None or e.date > last_vaccine): last_vaccine = e.date
            if e.type == "驱虫" and (last_deworm is None or e.date > last_deworm): last_deworm = e.date
            if e.type == "发情" and (last_heat is None or e.date > last_heat): last_heat = e.date
        latest_event = None
        if events:
            le = events[0]
            latest_event = {"id": le.id, "type": le.type, "date": le.date.isoformat()}
        reminders = _build_reminders(dog, last_vaccine, last_deworm, last_heat)
        return {"has_dog": True, "dog_name": dog.name, "reminders": reminders, "latest_event": latest_event,
                "pending_actions": len([r for r in reminders if r.get("urgent")]),
                "supplement_count": db.query(SupplementAlert).filter(
                    SupplementAlert.dog_id == dog.id, SupplementAlert.is_active == 1).count(),
                "suspended": bool(dog.suspended_until and dog.suspended_until > datetime.utcnow())}

# ============================================================
# 体重日志 API
# ============================================================
@app.get("/api/weight_logs")
def api_weight_logs(openid: str = Depends(get_current_user)):
    with SessionLocal() as db:
        dog = db.query(Dog).filter(Dog.owner_id == openid).order_by(Dog.created_at.desc()).first()
        if not dog:
            return []
        logs = db.query(WeightLog).filter(WeightLog.dog_id == dog.id).order_by(WeightLog.date.desc()).limit(30).all()
        return [{"id": l.id, "weight": l.weight, "date": l.date.isoformat()} for l in logs]

@app.post("/api/weight_log")
def api_add_weight_log(payload: dict, openid: str = Depends(get_current_user)):
    with SessionLocal() as db:
        dog = db.query(Dog).filter(Dog.owner_id == openid).order_by(Dog.created_at.desc()).first()
        if not dog:
            raise HTTPException(status_code=404, detail="主人，请先创建狗狗档案～")
        wl = WeightLog(dog_id=dog.id, weight=payload["weight"], date=date.fromisoformat(payload["date"]))
        db.add(wl)
        dog.weight = payload["weight"]
        db.flush()
        return {"message": "体重记录好啦，主人真细心～🐾"}

# ============================================================
# 订阅消息 API
# ============================================================
@app.post("/api/subscribe")
def api_subscribe(payload: SubscribeRequest, openid: str = Depends(get_current_user)):
    with SessionLocal() as db:
        for tid in payload.template_ids:
            existing = db.query(SubscribeTemplate).filter(
                SubscribeTemplate.openid == openid, SubscribeTemplate.template_id == tid).first()
            if not existing:
                db.add(SubscribeTemplate(openid=openid, template_id=tid, template_type=payload.template_type))
        db.flush()
    return {"message": "汪汪！已开启提醒，我会准时提醒主人的～🐾"}

# ============================================================
# 导出 API
# ============================================================
@app.get("/api/export")
def api_export(openid: str = Depends(get_current_user)):
    with SessionLocal() as db:
        dog = db.query(Dog).filter(Dog.owner_id == openid).order_by(Dog.created_at.desc()).first()
        if not dog:
            raise HTTPException(status_code=404, detail="还没有狗狗档案～")
        events = db.query(Event).filter(Event.dog_id == dog.id).order_by(Event.date.desc()).all()
        output = io.StringIO()
        output.write("=== 狗狗档案 ===\n")
        output.write(f"名字,品种,生日,体重,绝育,过敏源,性别,疾病\n")
        output.write(f"{dog.name},{dog.breed},{dog.birthday},{dog.weight},{dog.neutered},{dog.allergies},{dog.gender},{dog.diseases}\n\n")
        output.write("=== 大事记 ===\n类型,日期,备注\n")
        for e in events:
            detail = json.loads(e.detail) if e.detail else {}
            output.write(f"{e.type},{e.date},{json.dumps(detail, ensure_ascii=False)}\n")
        from fastapi.responses import Response
        return Response(content=output.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f"attachment; filename=pawlife_{dog.name}.csv"})

# ============================================================
# 健康状态 API（兽医摘要用）
# ============================================================
@app.get("/api/vet_summary/{event_id}")
def api_vet_summary(event_id: int, openid: str = Depends(get_current_user)):
    with SessionLocal() as db:
        event = db.query(Event).filter(Event.id == event_id).first()
        if not event:
            raise HTTPException(status_code=404, detail="找不到这条记录～")
        dog = db.query(Dog).filter(Dog.id == event.dog_id, Dog.owner_id == openid).first()
        if not dog:
            raise HTTPException(status_code=404, detail="找不到这只狗狗～")
        detail = json.loads(event.detail) if event.detail else {}
        symptoms = detail.get("symptoms", [])
        risk_level = "high" if event.high_risk else ("midhigh" if len(symptoms) >= 3 else ("mid" if len(symptoms) >= 1 else "low"))
        return {
            "dog_name": dog.name, "breed": dog.breed, "age": _calc_age(dog.birthday),
            "weight": dog.weight or "未知", "neutered": dog.neutered or "未知",
            "event_type": event.type, "event_date": event.date.isoformat(),
            "symptoms": symptoms, "risk_level": risk_level,
            "high_risk": bool(event.high_risk), "risk_keyword": event.risk_keyword,
        }

# ============================================================
# 照片上传 API
# ============================================================
@app.post("/api/dog/photo")
async def api_upload_photo(file: UploadFile = File(...), openid: str = Depends(get_current_user)):
    if file.content_type not in ("image/jpeg", "image/png", "image/jpg"):
        raise HTTPException(status_code=400, detail="主人，只支持 JPG 和 PNG 格式的图片哦～")
    content = await file.read()
    if len(content) > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="汪汪，图片不能超过 2MB 哦～")
    ext = "jpg" if "jpeg" in (file.content_type or "") else "png"
    filename = f"{openid}_{secrets.token_hex(8)}.{ext}"
    with open(os.path.join(PHOTOS_DIR, filename), "wb") as f:
        f.write(content)
    with SessionLocal() as db:
        dog = db.query(Dog).filter(Dog.owner_id == openid).order_by(Dog.created_at.desc()).first()
        if not dog:
            raise HTTPException(status_code=404, detail="还没有狗狗档案，主人先去建档吧～")
        old_photo = dog.photo
        dog.photo = filename
        db.flush()
        if old_photo:
            old_path = os.path.join(PHOTOS_DIR, old_photo)
            if os.path.exists(old_path):
                os.remove(old_path)
    return {"message": "汪汪！我的新照片太好看啦～🐾", "photo": filename}

# ============================================================
# 初始化
# ============================================================
@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)

# ============================================================
# --- 以下是从 pawlife_web.py 复用的业务逻辑函数（保持完全不变）---
# ============================================================

HIGH_RISK_SYMPTOMS = [
    "反复呕吐", "持续呕吐", "吐血", "呕血", "腹泻带血", "便血", "黑便",
    "抽搐", "癫痫", "昏厥", "晕倒", "瘫痪", "呼吸困难", "呼吸急促",
    "极度萎靡", "意识丧失", "瞳孔散大", "严重过敏", "面部肿胀",
    "车祸", "中毒", "误食巧克力", "误食洋葱", "误食葡萄", "误食木糖醇",
    "误食老鼠药", "被蛇咬", "严重外伤", "大出血", "骨折", "烫伤",
]

def _parse_weight_kg(weight_str):
    if not weight_str: return None
    m = re.search(r"[\d.]+", str(weight_str))
    return float(m.group()) if m else None

def _calc_age(birthday):
    today = date.today()
    years = today.year - birthday.year - ((today.month, today.day) < (birthday.month, birthday.day))
    months = (today.month - birthday.month) % 12
    if (today.month, today.day) < (birthday.month, birthday.day): months = (months - 1) % 12
    if years > 0: return f"{years}岁{months}个月" if months > 0 else f"{years}岁"
    return f"{max(months, 0)}个月" if months > 0 else "新生儿"

def _get_age_stage(birthday):
    today = date.today()
    years = today.year - birthday.year - ((today.month, today.day) < (birthday.month, birthday.day))
    months = (today.month - birthday.month) % 12
    if (today.month, today.day) < (birthday.month, birthday.day): months = (months - 1) % 12
    total_months = years * 12 + months
    if total_months < 12: return "幼犬"
    if years >= 7: return "老年犬"
    return "成犬"

def _get_body_size(weight_str):
    kg = _parse_weight_kg(weight_str)
    if kg is None: return "中型犬"
    if kg < 10: return "小型犬"
    if kg > 25: return "大型犬"
    return "中型犬"

def _calc_bath_interval(weight_str):
    kg = _parse_weight_kg(weight_str)
    if kg is None: return 14
    if kg < 5: return 14
    elif kg < 15: return 14
    else: return 10

def _calc_daily_grams(birthday, weight_kg, neutered, gender):
    age_stage = _get_age_stage(birthday)
    if age_stage == "幼犬":
        rer = 70 * (weight_kg ** 0.75)
        der = rer * 2.5
    elif age_stage == "老年犬":
        rer = 70 * (weight_kg ** 0.75)
        der = rer * 1.4
    else:
        rer = 30 * weight_kg + 70
        der = rer * (1.4 if neutered == "是" else 2.0)
    if gender == "female" and neutered != "是": der *= 0.95
    total_g = der / 1.2
    protein_g = round(total_g * 0.35)
    carb_g = round(total_g * 0.30)
    veggie_g = round(total_g * 0.35)
    protein_g = max(protein_g, 28)
    carb_g = max(carb_g, 15)
    veggie_g = max(veggie_g, 15)
    return {"weight_kg": weight_kg, "rer": round(rer, 1), "der": round(der, 1),
            "total_g": round(total_g), "protein_g": protein_g, "carb_g": carb_g, "veggie_g": veggie_g}

# --- 饮食数据库 ---
FOOD_NUTRITION = {
    "鸡胸肉": {"emoji": "🍗", "protein": 31, "fat": 3.6, "carbs": 0},
    "鸡胸肉丁": {"emoji": "🍗", "protein": 31, "fat": 3.6, "carbs": 0},
    "鸡胸肉丝": {"emoji": "🍗", "protein": 31, "fat": 3.6, "carbs": 0},
    "鸭肉": {"emoji": "🦆", "protein": 28, "fat": 7, "carbs": 0},
    "牛肉": {"emoji": "🥩", "protein": 26, "fat": 15, "carbs": 0},
    "瘦牛肉": {"emoji": "🥩", "protein": 28, "fat": 6, "carbs": 0},
    "牛肉糜": {"emoji": "🥩", "protein": 26, "fat": 15, "carbs": 0},
    "牛肉末": {"emoji": "🥩", "protein": 26, "fat": 15, "carbs": 0},
    "三文鱼": {"emoji": "🐟", "protein": 25, "fat": 8, "carbs": 0},
    "鳕鱼": {"emoji": "🐟", "protein": 23, "fat": 0.7, "carbs": 0},
    "鱼肉": {"emoji": "🐟", "protein": 22, "fat": 3, "carbs": 0},
    "鱼肉碎": {"emoji": "🐟", "protein": 22, "fat": 3, "carbs": 0},
    "虾仁": {"emoji": "🦐", "protein": 20, "fat": 1, "carbs": 0},
    "虾仁碎": {"emoji": "🦐", "protein": 20, "fat": 1, "carbs": 0},
    "蛋黄": {"emoji": "🥚", "protein": 15, "fat": 27, "carbs": 3},
    "鸡蛋": {"emoji": "🥚", "protein": 13, "fat": 11, "carbs": 1.1},
    "羊肉": {"emoji": "🐑", "protein": 25, "fat": 14, "carbs": 0},
    "糙米": {"emoji": "🍚", "protein": 7.5, "fat": 2.7, "carbs": 73},
    "燕麦": {"emoji": "🌾", "protein": 13, "fat": 6.5, "carbs": 63},
    "红薯": {"emoji": "🍠", "protein": 1.6, "fat": 0.1, "carbs": 20},
    "南瓜": {"emoji": "🎃", "protein": 1, "fat": 0.1, "carbs": 7},
    "藜麦": {"emoji": "🌾", "protein": 14, "fat": 6, "carbs": 64},
    "小米": {"emoji": "🌾", "protein": 9, "fat": 3.1, "carbs": 73},
    "胡萝卜": {"emoji": "🥕", "protein": 0.9, "fat": 0.2, "carbs": 10},
    "西兰花": {"emoji": "🥦", "protein": 2.8, "fat": 0.4, "carbs": 7},
    "菠菜": {"emoji": "🥬", "protein": 2.9, "fat": 0.4, "carbs": 3.6},
    "西葫芦": {"emoji": "🥒", "protein": 1.2, "fat": 0.2, "carbs": 3.1},
}

DIET_FOODS = {
    ("幼犬", "小型犬"): {"meals": 4, "protein": "鸡胸肉", "veggie": "胡萝卜", "carb": "燕麦",
        "daily": ["鸡胸肉粥", "鱼肉碎饭", "蛋黄粥"],
        "tip": "幼犬每天4餐，少量多餐，所有食材必须切碎蒸熟。"},
    ("幼犬", "中型犬"): {"meals": 3, "protein": "鸡胸肉", "veggie": "西兰花", "carb": "糙米",
        "daily": ["鸡胸肉丁糙米饭", "牛肉末饭", "三文鱼碎饭"],
        "tip": "中型幼犬每天3餐，注意钙磷比（1.1:1~1.8:1），保证充足蛋白质。"},
    ("幼犬", "大型犬"): {"meals": 3, "protein": "瘦牛肉", "veggie": "西兰花", "carb": "糙米",
        "daily": ["牛肉饭", "鸡胸糙米饭", "三文鱼意面"],
        "tip": "⚠️ 大型幼犬骨骼发育关键期：钙磷比需严格控制在1.1:1~1.8:1（NRC标准）。每500g食物建议添加约2g蛋壳粉（约400mg钙），过量或不足均可能导致骨骼发育异常。请务必咨询兽医确认具体剂量！"},
    ("成犬", "小型犬"): {"meals": 2, "protein": "鸡胸肉", "veggie": "菠菜", "carb": "南瓜",
        "daily": ["鸡胸肉南瓜饭", "三文鱼饭", "虾仁粥"],
        "tip": "成犬每天2餐，优质蛋白加适量蔬菜，保持理想体重哦～"},
    ("成犬", "中型犬"): {"meals": 2, "protein": "鸭肉", "veggie": "胡萝卜", "carb": "糙米",
        "daily": ["鸭肉糙米饭", "三文鱼胡萝卜饭", "牛肉蔬菜饭"],
        "tip": "中型成犬每天2餐，肉菜饭黄金比例3:3:4，保证营养均衡。"},
    ("成犬", "大型犬"): {"meals": 2, "protein": "牛肉", "veggie": "西葫芦", "carb": "藜麦",
        "daily": ["牛肉藜麦饭", "鸡胸糙米饭", "三文鱼蔬菜饭"],
        "tip": "大型成犬关节压力大，建议搭配鱼油和葡萄糖胺，控制体重减轻关节负担。"},
    ("老年犬", "小型犬"): {"meals": 2, "protein": "鳕鱼", "veggie": "南瓜", "carb": "小米",
        "daily": ["鳕鱼小米粥", "鸡胸南瓜泥", "鱼肉碎饭"],
        "tip": "老年小型犬消化力下降，食材需切得更细，蒸得更软，必要时打成泥。"},
    ("老年犬", "中型犬"): {"meals": 2, "protein": "三文鱼", "veggie": "胡萝卜", "carb": "燕麦",
        "daily": ["三文鱼燕麦粥", "鸡胸碎饭", "鳕鱼蔬菜饭"],
        "tip": "中型老年犬需增加Omega-3摄入抗炎护关节，食材务必蒸软。"},
    ("老年犬", "大型犬"): {"meals": 2, "protein": "三文鱼", "veggie": "西葫芦", "carb": "糙米",
        "daily": ["三文鱼糙米粥", "鸡胸胡萝卜饭", "鳕鱼软饭"],
        "tip": "大型老年犬关节和心脏负担重，鱼油和葡萄糖胺是好朋友，饭要蒸得软软的哦～"},
}

ALLERGY_FOOD_MAP = {
    "鸡": ["鸡胸肉", "鸡腿肉", "鸡胸肉丁", "鸡胸肉丝", "蛋黄", "鸡蛋"],
    "鸡肉": ["鸡胸肉", "鸡腿肉", "鸡胸肉丁", "鸡胸肉丝"],
    "禽": ["鸡胸肉", "鸡腿肉", "鸭肉", "蛋黄"],
    "鱼": ["三文鱼", "鳕鱼", "鱼肉", "鱼肉碎", "虾仁"],
    "海鲜": ["三文鱼", "鳕鱼", "鱼肉", "虾仁"],
    "三文鱼": ["三文鱼"], "鳕鱼": ["鳕鱼"],
    "牛": ["牛肉", "瘦牛肉", "牛肉糜", "牛肉末"], "牛肉": ["牛肉", "瘦牛肉", "牛肉糜", "牛肉末"],
    "羊": ["羊肉"], "羊肉": ["羊肉"],
    "虾": ["虾仁", "虾仁碎"], "虾仁": ["虾仁"],
    "蛋": ["蛋黄", "鸡蛋"], "蛋黄": ["蛋黄"],
    "谷物": ["燕麦", "糙米", "小米", "藜麦"],
    "麦": ["燕麦", "藜麦", "小麦"], "奶": [], "大豆": [], "玉米": [],
}

SAFE_FALLBACKS = {
    "protein": {"鸡胸肉": "鸭肉", "鸡胸肉丁": "鸭肉", "鸡胸肉丝": "鸭肉",
                 "牛肉": "鸭肉", "瘦牛肉": "鸭肉", "牛肉糜": "鸭肉", "牛肉末": "鸭肉",
                 "三文鱼": "鸭肉", "鳕鱼": "鸭肉", "鱼肉": "鸭肉", "鱼肉碎": "鸭肉",
                 "虾仁": "鸭肉", "虾仁碎": "鸭肉", "蛋黄": "鸭肉", "鸡蛋": "鸭肉", "羊肉": "鸭肉"},
    "veggie": {"胡萝卜": "西兰花", "西兰花": "胡萝卜", "菠菜": "南瓜", "西葫芦": "南瓜"},
    "carb": {"燕麦": "藜麦", "糙米": "藜麦", "小米": "藜麦", "南瓜": "红薯", "藜麦": "糙米", "红薯": "南瓜"},
}

def _normalize_food(name):
    if name in FOOD_NUTRITION: return name
    for key in FOOD_NUTRITION:
        if key.startswith(name) or name.startswith(key): return key
    return name

def _filter_allergen_foods(food_name, allergies_str):
    if not allergies_str: return True
    allergies = [a.strip() for a in allergies_str.replace("，", ",").split(",") if a.strip()]
    if not allergies: return True
    for allergen in allergies:
        blocked = ALLERGY_FOOD_MAP.get(allergen, [allergen])
        for b in blocked:
            if b in (food_name or ""): return False
    return True

def _get_safe_fallback(allergies_str, food_type):
    if not allergies_str: return "鸭肉" if food_type == "protein" else ("西兰花" if food_type == "veggie" else "藜麦")
    allergies = [a.strip() for a in allergies_str.replace("，", ",").split(",") if a.strip()]
    fallbacks = SAFE_FALLBACKS.get(food_type, {})
    for _, fallback in fallbacks.items():
        safe = True
        for allergen in allergies:
            blocked = ALLERGY_FOOD_MAP.get(allergen, [allergen])
            for b in blocked:
                if b in fallback: safe = False
        if safe: return fallback
    return "鸭肉" if food_type == "protein" else ("西兰花" if food_type == "veggie" else "藜麦")

def _filter_options(options_str, allergies_str, food_type):
    if not allergies_str: return options_str
    parts = [p.strip() for p in options_str.replace("，", ",").replace("、", ",").split(",") if p.strip()]
    filtered = [p for p in parts if _filter_allergen_foods(p, allergies_str)]
    return "、".join(filtered) if filtered else "暂无安全选项"

# --- 保健品计算 ---
SUPPLEMENT_RULES = [
    {"name": "关节保护", "supplement": "葡萄糖胺+软骨素", "priority": 1,
     "condition": lambda db, dog: _get_age_stage(dog.birthday) in ("老年犬",) or _get_body_size(dog.weight) == "大型犬",
     "reason": "关节保护（年龄/体型风险）", "woof": "主人，我的关节需要日常养护，葡萄糖胺和软骨素是我的好朋友！每天按体重喂就行，具体剂量问兽医哦～"},
    {"name": "鱼油Omega-3", "supplement": "鱼油（Omega-3）", "priority": 1,
     "condition": lambda db, dog: True,
     "reason": "Omega-3抗炎护心脑，全犬种推荐", "woof": "Omega-3让我的毛毛亮亮、关节灵活，每周吃2-3次，按体重0.5-1ml/5kg～"},
    {"name": "益生菌", "supplement": "益生菌", "priority": 2,
     "condition": lambda db, dog: _get_age_stage(dog.birthday) == "幼犬",
     "reason": "幼犬肠胃发育期，益生菌助消化", "woof": "我还在长肠胃呢～益生菌帮助我消化好、少拉肚子！"},
    {"name": "综合维生素", "supplement": "综合维生素粉", "priority": 2,
     "condition": lambda db, dog: _get_age_stage(dog.birthday) == "幼犬",
     "reason": "生长发育期需均衡营养（若吃市售全价狗粮则通常无需额外补充）",
     "woof": "我正在长身体～如果主人给我吃的是自制狗饭，可以加一点综合营养粉让骨骼牙齿棒棒的；如果吃的是市售全价狗粮，一般不需要额外补哦，具体听兽医的！"},
    {"name": "美毛护肤", "supplement": "卵磷脂/生物素", "priority": 2,
     "condition": lambda db, dog: dog.breed in ("金毛", "柯基"),
     "reason": "双层被毛品种需额外美毛支持", "woof": "我的双层被毛是颜值担当！卵磷脂让毛毛更亮更顺～"},
    {"name": "泌尿健康（母犬未绝育）", "supplement": "蔓越莓提取物", "priority": 2,
     "condition": lambda db, dog: (dog.gender == "female" and dog.neutered != "是" and
         _get_age_stage(dog.birthday) in ("成犬", "老年犬")),
     "reason": "未绝育母犬泌尿系统易感，蔓越莓辅助预防", "woof": "主人，蔓越莓可以帮我的泌尿系统保持健康哦～"},
    {"name": "前列腺健康（公犬未绝育）", "supplement": "南瓜籽提取物", "priority": 2,
     "condition": lambda db, dog: (dog.gender == "male" and dog.neutered != "是" and
         _get_age_stage(dog.birthday) in ("成犬", "老年犬")),
     "reason": "未绝育公犬前列腺风险，南瓜籽辅助保健", "woof": "主人，南瓜籽对我的前列腺有好处哦～"},
]

def _calc_supplements(db, dog):
    results = []
    for rule in SUPPLEMENT_RULES:
        try:
            if rule["condition"](db, dog):
                results.append({"supplement_name": rule["supplement"], "reason": rule["reason"],
                                "woof_text": rule["woof"], "priority": rule["priority"]})
        except Exception:
            pass
    return results

def _refresh_supplement_alerts(db, dog):
    alerts = _calc_supplements(db, dog)
    db.query(SupplementAlert).filter(SupplementAlert.dog_id == dog.id, SupplementAlert.is_active == 1).update({"is_active": 0})
    for a in alerts:
        db.add(SupplementAlert(dog_id=dog.id, supplement_name=a["supplement_name"],
                                reason=a["reason"], woof_text=a["woof_text"], priority=a["priority"]))

# --- 事件反应生成 ---
def _generate_reaction(event_type, dog, detail):
    if event_type == "疫苗":
        dose = detail.get("dose", "")
        brand = detail.get("brand", "")
        return f"💉 汪！主人带我去打疫苗了！{'（' + dose + '）' if dose else ''}{'品牌：' + brand if brand else ''} 我是勇敢的小家伙！打完疫苗24小时内要观察我的精神和食欲哦～"
    elif event_type == "驱虫":
        dt = detail.get("deworm_type", "体内")
        brand = detail.get("brand", "")
        return f"💊 驱虫日！主人帮我做了{dt}驱虫{'（' + brand + '）' if brand else ''}。体内驱虫后注意观察我的便便哦～体外驱虫24小时内不要洗澡！"
    elif event_type == "发情":
        note = detail.get("note", "")
        return f"💕 我来姨妈啦～{'备注：' + note if note else ''} 主人记得勤换尿垫，出门要牵好绳，别让臭小子靠近我哦～生理期一般持续7-14天。"
    elif event_type == "异常行为":
        symptoms = detail.get("symptoms", [])
        if not symptoms:
            return "⚠️ 主人记录了我的异常行为，但没写具体症状呢～再检查一下吧！"
        lines = []
        for s in symptoms:
            if s in HIGH_RISK_SYMPTOMS:
                lines.append(f"🔴【{s}·高风险】主人！这个症状很危险，请立即联系兽医！")
            elif any(kw in s for kw in ["吐", "血", "抽搐", "瘫痪", "昏", "中毒"]):
                lines.append(f"🟡【{s}·中风险】主人，{s}需要重视，建议尽快去看兽医。")
            else:
                lines.append(f"⚪【{s}·未分级风险】主人，我出现了「{s}」的症状，请多观察我的状态。如果情况没有好转，带我去看兽医是最稳妥的选择哦。")
        return "\n\n".join(lines)
    elif event_type == "洗澡澡":
        interval = dog.bath_interval_days or 10
        return f"🛁 洗香香啦！毛发蓬蓬的，我就是这条街最靓的崽！每隔{interval}天洗一次就够啦，太频繁会伤皮肤的哦～"
    return "汪汪，记录好了！"

def _build_reminders(dog, last_vaccine, last_deworm, last_heat):
    today = date.today()
    reminders = []
    # 疫苗提醒（核心疫苗3年周期，WSAVA指南）
    if last_vaccine:
        next_vaccine = last_vaccine + timedelta(days=1095)
        days_left = (next_vaccine - today).days
        if days_left <= 60:
            reminders.append({"type": "疫苗", "urgent": days_left <= 14, "days_left": days_left,
                              "last_date": last_vaccine.isoformat(),
                              "msg": f"💉 下次疫苗{'已过期' if days_left < 0 else f'还有{days_left}天'}（核心疫苗建议每3年加强一次，具体请遵医嘱）"})
    if last_deworm:
        next_deworm = last_deworm + timedelta(days=90)
        days_left = (next_deworm - today).days
        if days_left <= 14:
            reminders.append({"type": "驱虫", "urgent": days_left <= 3, "days_left": days_left,
                              "last_date": last_deworm.isoformat(),
                              "msg": f"💊 驱虫{'已过期' if days_left < 0 else f'还有{days_left}天'}（建议每3个月驱虫一次）"})
    if last_heat and dog.gender == "female":
        next_heat = last_heat + timedelta(days=180)
        days_left = (next_heat - today).days
        if 0 <= days_left <= 30:
            reminders.append({"type": "发情", "urgent": False, "days_left": days_left,
                              "last_date": last_heat.isoformat(),
                              "msg": f"💕 预计下次发情期约在{next_heat.month}月，提前准备好生理裤哦～"})
    return reminders

# ============================================================
# 启动
# ============================================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
