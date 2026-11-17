-- =========================================================
-- 社内バナー制作デスク (Banner Production Desk)
-- Supabase (PostgreSQL) 初期化 & 非破壊マイグレーション用 DDL
-- ※ 何度再実行しても既存データや変更済み設定を上書き・巻き戻ししません
-- =========================================================

-- 1. ユーザーテーブル
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    display_name VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL CHECK (role IN ('requester', 'designer', 'admin')),
    email VARCHAR(255),
    password_hash TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 2. 案件テーブル
CREATE TABLE IF NOT EXISTS projects (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    purpose TEXT NOT NULL,
    appeal_point TEXT NOT NULL,
    required_elements TEXT NOT NULL,
    placement TEXT NOT NULL,
    size TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    desired_delivery_date VARCHAR(50) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'waiting_acceptance' 
        CHECK (status IN ('waiting_acceptance', 'reviewing', 'in_progress', 'waiting_client_review', 'revising', 'waiting_delivery', 'delivered', 'cancelled')),
    waiting_for VARCHAR(50) NOT NULL DEFAULT 'admin'
        CHECK (waiting_for IN ('requester', 'designer', 'admin', 'none')),
    requester_id INTEGER NOT NULL REFERENCES users(id),
    designer_id INTEGER REFERENCES users(id),
    schedule_confirmed BOOLEAN NOT NULL DEFAULT FALSE,
    first_draft_deadline VARCHAR(50),
    final_delivery_deadline VARCHAR(50),
    first_reply_deadline VARCHAR(50),
    first_reply_actual VARCHAR(50),
    first_draft_actual VARCHAR(50),
    final_delivery_actual VARCHAR(50),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 既存の projects テーブルに対する非破壊列追加
ALTER TABLE projects ADD COLUMN IF NOT EXISTS form_type VARCHAR(50) DEFAULT 'sales_wellness';
ALTER TABLE projects ADD COLUMN IF NOT EXISTS request_date VARCHAR(50);
ALTER TABLE projects ADD COLUMN IF NOT EXISTS requester_person_name VARCHAR(100);
ALTER TABLE projects ADD COLUMN IF NOT EXISTS desired_first_draft_date VARCHAR(50);
ALTER TABLE projects ADD COLUMN IF NOT EXISTS target_launch_date VARCHAR(50);
ALTER TABLE projects ADD COLUMN IF NOT EXISTS delivery_notes TEXT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS item_name TEXT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS product_code TEXT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS product_spec_url TEXT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS product_description TEXT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS target_audience TEXT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS target_environment TEXT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS selling_point TEXT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS customer_benefit TEXT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS content_text TEXT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS production_policy TEXT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS purpose_and_problem TEXT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS designer_confirmed_quantity INTEGER;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS designer_confirmed_notes TEXT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS print_specifications TEXT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS destination_url_qr TEXT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS delivery_destination_path TEXT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS materials_provided TEXT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS materials_url_path TEXT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS shooting_required TEXT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS materials_delivery_date VARCHAR(50);
ALTER TABLE projects ADD COLUMN IF NOT EXISTS design_taste TEXT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS reference_design_url TEXT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS other_requests TEXT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS meeting_required TEXT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(100);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_projects_idempotency_key'
    ) THEN
        ALTER TABLE projects ADD CONSTRAINT uq_projects_idempotency_key UNIQUE (idempotency_key);
    END IF;
END $$;

-- 2-1. 媒体・制作物選択テーブル
CREATE TABLE IF NOT EXISTS project_media_items (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    media_category VARCHAR(100) NOT NULL,
    custom_media_name TEXT,
    item_name VARCHAR(100) NOT NULL,
    custom_item_name TEXT,
    quantity INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 2-2. 案件下書き保存テーブル
CREATE TABLE IF NOT EXISTS project_drafts (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    form_type VARCHAR(50) NOT NULL,
    draft_data_json TEXT NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_user_draft UNIQUE (user_id, form_type)
);

-- 3. 案件添付ファイル
CREATE TABLE IF NOT EXISTS project_attachments (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    file_type VARCHAR(50) NOT NULL DEFAULT 'brief_material',
    original_name TEXT NOT NULL,
    stored_name TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    file_size BIGINT NOT NULL,
    mime_type VARCHAR(100),
    uploaded_by INTEGER NOT NULL REFERENCES users(id),
    uploaded_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE project_attachments ADD COLUMN IF NOT EXISTS storage_path TEXT;

-- 4. 日程提案・合意履歴
CREATE TABLE IF NOT EXISTS schedule_proposals (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    first_draft_date VARCHAR(50) NOT NULL,
    final_delivery_date VARCHAR(50) NOT NULL,
    reason TEXT,
    proposed_by INTEGER NOT NULL REFERENCES users(id),
    proposed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(50) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    reviewed_by INTEGER REFERENCES users(id),
    reviewed_at TIMESTAMP WITH TIME ZONE,
    review_comment TEXT,
    idempotency_key VARCHAR(100)
);
ALTER TABLE schedule_proposals ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(100);
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_schedule_proposals_idempotency_key'
    ) THEN
        ALTER TABLE schedule_proposals ADD CONSTRAINT uq_schedule_proposals_idempotency_key UNIQUE (idempotency_key);
    END IF;
END $$;

-- 5. 提出画像・版管理
CREATE TABLE IF NOT EXISTS project_versions (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    version_label VARCHAR(50) NOT NULL,
    file_path TEXT NOT NULL,
    original_name TEXT NOT NULL,
    file_size BIGINT NOT NULL,
    comment TEXT,
    submitted_by INTEGER NOT NULL REFERENCES users(id),
    submitted_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    is_final BOOLEAN NOT NULL DEFAULT FALSE,
    is_approved BOOLEAN DEFAULT FALSE,
    approved_by INTEGER REFERENCES users(id),
    approved_at TIMESTAMP WITH TIME ZONE,
    approval_comment TEXT,
    idempotency_key VARCHAR(100)
);
ALTER TABLE project_versions ADD COLUMN IF NOT EXISTS is_approved BOOLEAN DEFAULT FALSE;
ALTER TABLE project_versions ADD COLUMN IF NOT EXISTS approved_by INTEGER REFERENCES users(id);
ALTER TABLE project_versions ADD COLUMN IF NOT EXISTS approved_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE project_versions ADD COLUMN IF NOT EXISTS approval_comment TEXT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS approved_version_id INTEGER REFERENCES project_versions(id);
ALTER TABLE project_versions ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(100);
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_project_versions_idempotency_key'
    ) THEN
        ALTER TABLE project_versions ADD CONSTRAINT uq_project_versions_idempotency_key UNIQUE (idempotency_key);
    END IF;
END $$;

-- 6. 案件タイムライン
CREATE TABLE IF NOT EXISTS project_posts (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    post_type VARCHAR(50) NOT NULL CHECK (post_type IN ('comment', 'question', 'answer', 'revision_request', 'system_event', 'action_log')),
    content TEXT NOT NULL,
    created_by INTEGER NOT NULL REFERENCES users(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    parent_post_id INTEGER REFERENCES project_posts(id),
    action_label VARCHAR(100),
    idempotency_key VARCHAR(100)
);
ALTER TABLE project_posts ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(100);
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_project_posts_idempotency_key'
    ) THEN
        ALTER TABLE project_posts ADD CONSTRAINT uq_project_posts_idempotency_key UNIQUE (idempotency_key);
    END IF;
END $$;

-- 7. 投稿の編集・削除履歴
CREATE TABLE IF NOT EXISTS post_edit_history (
    id SERIAL PRIMARY KEY,
    post_id INTEGER NOT NULL REFERENCES project_posts(id) ON DELETE CASCADE,
    previous_content TEXT NOT NULL,
    action_type VARCHAR(50) NOT NULL CHECK (action_type IN ('edit', 'delete')),
    changed_by INTEGER NOT NULL REFERENCES users(id),
    changed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 8. 投稿添付ファイル
CREATE TABLE IF NOT EXISTS post_attachments (
    id SERIAL PRIMARY KEY,
    post_id INTEGER NOT NULL REFERENCES project_posts(id) ON DELETE CASCADE,
    original_name TEXT NOT NULL,
    stored_name TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    file_size BIGINT NOT NULL,
    mime_type VARCHAR(100)
);

-- 9. アプリ内通知
CREATE TABLE IF NOT EXISTS notifications (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    link_url TEXT,
    is_read BOOLEAN NOT NULL DEFAULT FALSE,
    email_sent BOOLEAN NOT NULL DEFAULT FALSE,
    email_status VARCHAR(50) NOT NULL DEFAULT 'unconfigured',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 10. システム業務ルール・設定テーブル
CREATE TABLE IF NOT EXISTS system_settings (
    key VARCHAR(100) PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_by INTEGER REFERENCES users(id)
);

-- 11. 評価・納期遵守記録 (各4点満点制約)
CREATE TABLE IF NOT EXISTS project_evaluations (
    id SERIAL PRIMARY KEY,
    project_id INTEGER UNIQUE NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    quality_score INTEGER NOT NULL CHECK (quality_score BETWEEN 1 AND 4),
    communication_score INTEGER NOT NULL CHECK (communication_score BETWEEN 1 AND 4),
    careless_mistake_score INTEGER NOT NULL CHECK (careless_mistake_score BETWEEN 1 AND 4),
    overall_comment TEXT,
    on_time_status VARCHAR(50) NOT NULL CHECK (on_time_status IN ('on_time', 'delayed_designer', 'delayed_requester', 'delayed_other')),
    delay_reason TEXT,
    mistake_responsibility TEXT,
    evaluated_by INTEGER NOT NULL REFERENCES users(id),
    evaluated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    idempotency_key VARCHAR(100)
);
ALTER TABLE project_evaluations ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(100);
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_project_evaluations_idempotency_key'
    ) THEN
        ALTER TABLE project_evaluations ADD CONSTRAINT uq_project_evaluations_idempotency_key UNIQUE (idempotency_key);
    END IF;
END $$;

-- =========================================================
-- セキュリティ強化: RLS 有効化
-- =========================================================
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE project_media_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE project_drafts ENABLE ROW LEVEL SECURITY;
ALTER TABLE project_attachments ENABLE ROW LEVEL SECURITY;
ALTER TABLE schedule_proposals ENABLE ROW LEVEL SECURITY;
ALTER TABLE project_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE project_posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE post_edit_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE post_attachments ENABLE ROW LEVEL SECURITY;
ALTER TABLE notifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE system_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE project_evaluations ENABLE ROW LEVEL SECURITY;

-- ---------------------------------------------------------
-- 初期マスターデータの登録 (存在しない新規DB時のみ実行・既存変更を上書きしない)
-- ---------------------------------------------------------

INSERT INTO users (id, username, display_name, role, email, password_hash)
VALUES
    (1, 'okamoto', '岡本（管理者 / デザイナー）', 'admin', 'okamoto@example.com', 'scrypt:32768:8:1$01p1ewVAMjDBNTuk$654028beca2b7193fa9b60b6d9ff57b7693cfc0c8371550f07a2088fee5aececbeb0da5be99f14ddb490d4dc6de6fdaea9798797ac21a066bcbb6602aac78531'),
    (2, 'hansoku', '販売促進課（依頼者）', 'requester', 'hansoku@example.com', 'scrypt:32768:8:1$2uuUuCyXlqe0DC5J$8e169a9071b37870214c3f14826628a9e575a2a58470c5ef0c047299f443acceb61c93094ad2cb63676c1b8e6f2e6e5a846c582dae47cac1d555629de1c565f0'),
    (3, 'wellness', 'ウェルネス事業部（依頼者）', 'requester', 'wellness@example.com', 'scrypt:32768:8:1$SEXaXQcbwKFEyvfR$2c583ff54a35e958518072a0ead4a441a342fc4c44e8ddb859c2632296addb03e737f1b90ba348a7795e939e897157582f2fa5e0d5aec15de1e05662fb8bd4cd'),
    (4, 'kanri', '管理部（依頼者）', 'requester', 'kanri@example.com', 'scrypt:32768:8:1$14ZNmEjaDQi6JG8p$fd7276f7ada58f54ef9216d25b5e1fc4841755f674c4ad8253fd1ce514f71028ddd56d424fa6c0ae55050758aad0a2a34f613d125edad1a1368bb266cb40ed19')
ON CONFLICT (id) DO NOTHING;

SELECT setval('users_id_seq', COALESCE((SELECT MAX(id) FROM users), 1));

-- システム設定初期値 (すでに存在する場合は一切上書きせず既存値を保護)
INSERT INTO system_settings (key, value, updated_at)
VALUES
    ('business_hours', '{"work_days": [1, 2, 3, 4, 5], "start_time": "09:00", "end_time": "18:00", "reception_cutoff": "12:00"}', CURRENT_TIMESTAMP),
    ('holidays', '["2026-01-01", "2026-01-12", "2026-02-11", "2026-02-23", "2026-03-20", "2026-04-29", "2026-05-03", "2026-05-04", "2026-05-05", "2026-05-06", "2026-07-20", "2026-08-11", "2026-09-21", "2026-09-22", "2026-09-23", "2026-10-12", "2026-11-03", "2026-11-23"]', CURRENT_TIMESTAMP),
    ('deadline_rules', '{"first_draft_business_days": 3, "revision_business_days": 2}', CURRENT_TIMESTAMP),
    ('evaluation_criteria', '{"careless_mistakes": {"label": "ケアレスミスの少なさ", "max_score": 4, "options": {"4": "初稿の制作ミスが0件で、依頼者の原稿・支給資料にあった表記や枚数の誤り、不整合を事前に発見して指摘・修正した。", "3": "初稿の制作ミスが0件で、4点の追加条件には該当しない。", "2": "初稿に制作ミスがあり、依頼者による指摘・修正の手間が発生したが、最終納品までに修正された。", "1": "最終納品として提出されたデータに制作ミスがあった。（初稿の点数にかかわらず1点を優先。その後修正されても1点とする）"}}, "quality": {"label": "品質・デザイン完成度", "max_score": 4, "options": {"4": "目的・意図と必須要素を満たした高品質な仕上がりに加え、目標達成に向けたデザインアイデアを2件以上提案した。", "3": "目的・意図と必須要素を満たした高品質な仕上がりに加え、目標達成に向けたデザインアイデアを1件提案した。", "2": "目的・意図と必須要素を満たし、実用上の問題がない。", "1": "目的・意図や必須要素の反映に不足があり、修正が必要だった。"}}, "communication": {"label": "やりとり・レスポンス", "max_score": 4, "options": {"4": "定められた連絡期限・ルールを遵守したうえで、疑問点や確認事項を先回りして確認・解決案を提示した。", "3": "定められた一次返信期限や業務連絡ルールをすべて遵守し、遅延なく進行した。", "2": "連絡期限や共有ルールに遅れがあったが、事前の連絡または自発的な連絡が行われた。", "1": "依頼者からの催促が必要な期限超過が発生した、または無断での遅延があった。"}}}', CURRENT_TIMESTAMP),
    ('mail_settings', '{"enabled": false, "smtp_server": "", "smtp_port": 587, "smtp_user": "", "smtp_password": "", "from_address": "banner-desk@example.com", "use_tls": true}', CURRENT_TIMESTAMP)
ON CONFLICT (key) DO NOTHING;
