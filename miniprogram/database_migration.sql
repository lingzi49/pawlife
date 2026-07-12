-- ============================================================
-- PawLife 微信小程序 — 数据库迁移 SQL（SQLite → PostgreSQL）
-- 目标：Supabase PostgreSQL（免费版）或 Render PostgreSQL
-- ============================================================

-- 1. 用户表（新增）
CREATE TABLE IF NOT EXISTS users (
    openid          VARCHAR(64) PRIMARY KEY,
    session_key     VARCHAR(64),
    unionid         VARCHAR(64),
    nickname        VARCHAR(64),
    avatar_url      VARCHAR(512),
    created_at      TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_users_created_at ON users(created_at);

-- 2. 狗狗档案表（从 dogs 迁移，增加 owner_id）
CREATE TABLE IF NOT EXISTS dogs (
    id              SERIAL PRIMARY KEY,
    owner_id        VARCHAR(64) NOT NULL REFERENCES users(openid),
    name            VARCHAR(64) NOT NULL,
    breed           VARCHAR(32) NOT NULL,
    birthday        DATE NOT NULL,
    weight          VARCHAR(16),
    neutered        VARCHAR(8) DEFAULT '未知',
    allergies       VARCHAR(256),
    gender          VARCHAR(10),
    photo           VARCHAR(128),
    bath_interval_days INTEGER,
    last_bath_date  DATE,
    diseases        VARCHAR(256),
    suspended_until TIMESTAMP,
    created_at      TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_dogs_owner ON dogs(owner_id);
CREATE INDEX idx_dogs_created ON dogs(created_at);

-- 3. 事件记录表
CREATE TABLE IF NOT EXISTS events (
    id              SERIAL PRIMARY KEY,
    dog_id          INTEGER NOT NULL REFERENCES dogs(id) ON DELETE CASCADE,
    type            VARCHAR(32) NOT NULL,
    date            DATE NOT NULL,
    detail          TEXT,
    high_risk       INTEGER DEFAULT 0,
    risk_keyword    VARCHAR(64),
    created_at      TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_events_dog ON events(dog_id);
CREATE INDEX idx_events_date ON events(date DESC);

-- 4. 体重记录表
CREATE TABLE IF NOT EXISTS weight_logs (
    id              SERIAL PRIMARY KEY,
    dog_id          INTEGER NOT NULL REFERENCES dogs(id) ON DELETE CASCADE,
    weight          VARCHAR(16) NOT NULL,
    date            DATE NOT NULL,
    created_at      TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_weight_logs_dog ON weight_logs(dog_id);

-- 5. 保健品提醒表
CREATE TABLE IF NOT EXISTS supplement_alerts (
    id              SERIAL PRIMARY KEY,
    dog_id          INTEGER NOT NULL REFERENCES dogs(id) ON DELETE CASCADE,
    supplement_name VARCHAR(64) NOT NULL,
    reason          VARCHAR(256) NOT NULL,
    woof_text       VARCHAR(512) NOT NULL,
    priority        INTEGER DEFAULT 2,
    is_active       INTEGER DEFAULT 1,
    created_at      TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_supp_alerts_dog ON supplement_alerts(dog_id);

-- 6. 高风险事件合规日志表
CREATE TABLE IF NOT EXISTS risk_logs (
    id              SERIAL PRIMARY KEY,
    dog_id          INTEGER NOT NULL REFERENCES dogs(id) ON DELETE CASCADE,
    input_text      VARCHAR(512) NOT NULL,
    matched_keyword VARCHAR(64) NOT NULL,
    action_taken    VARCHAR(64) DEFAULT 'suspended_diet_and_supplements',
    warning_shown   INTEGER DEFAULT 1,
    user_confirmed  INTEGER DEFAULT 0,
    created_at      TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_risk_logs_dog ON risk_logs(dog_id);

-- 7. 订阅消息模板记录表（新增）
CREATE TABLE IF NOT EXISTS subscribe_templates (
    id              SERIAL PRIMARY KEY,
    openid          VARCHAR(64) NOT NULL REFERENCES users(openid),
    template_id     VARCHAR(64) NOT NULL,
    template_type   VARCHAR(32) NOT NULL,
    is_active       INTEGER DEFAULT 1,
    created_at      TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_sub_tpl_openid ON subscribe_templates(openid);

-- ============================================================
-- 幂等键表（替代原 fake_redis）
-- ============================================================
CREATE TABLE IF NOT EXISTS idempotency_keys (
    idem_key        VARCHAR(128) PRIMARY KEY,
    response        TEXT,
    created_at      TIMESTAMP DEFAULT NOW()
);
-- 定期清理过期幂等键（超过1小时的）
CREATE INDEX idx_idem_created ON idempotency_keys(created_at);

-- ============================================================
-- 定期清理函数（每天清理过期幂等键和旧日志）
-- ============================================================
CREATE OR REPLACE FUNCTION cleanup_old_data()
RETURNS void AS $$
BEGIN
    DELETE FROM idempotency_keys WHERE created_at < NOW() - INTERVAL '1 hour';
    DELETE FROM risk_logs WHERE created_at < NOW() - INTERVAL '2 years';
END;
$$ LANGUAGE plpgsql;
