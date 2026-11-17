import os
import json
import uuid
import streamlit as st
import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool
from contextlib import contextmanager
from supabase import create_client, Client

# ========================================================
# Supabase & PostgreSQL 接続管理 (コネクションプール)
# ========================================================

def get_secret(key, default=None):
    """Streamlit secrets または環境変数から設定値を取得"""
    try:
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return os.environ.get(key, default)

import re

def sanitize_db_url(url: str) -> str:
    """[YOUR-PASSWORD]置換時に角括弧が残ってしまった場合を自動救済"""
    if not url:
        return url
    m = re.match(r'^(?P<scheme>[^:]+://)(?P<user>[^:]+):(?P<password>[^@]+)@(?P<host>[^:/]+)(?::(?P<port>\d+))?(?P<rest>.*)$', url)
    if m:
        raw_pw = m.group('password')
        if raw_pw.startswith('[') and raw_pw.endswith(']'):
            clean_pw = raw_pw[1:-1]
            port_part = f":{m.group('port')}" if m.group('port') else ""
            return f"{m.group('scheme')}{m.group('user')}:{clean_pw}@{m.group('host')}{port_part}{m.group('rest')}"
    return url

@st.cache_resource
def get_db_pool():
    """
    スレッドセーフな PostgreSQL 接続プールを取得・キャッシュ。
    ※ 接続失敗時にSQLiteへの自動フォールバックは行わず、例外を送出して停止する。
    """
    raw_db_url = get_secret("SUPABASE_DB_URL")
    if not raw_db_url:
        raise ConnectionError("SUPABASE_DB_URL が設定されていません。.streamlit/secrets.toml をご確認ください。")
    db_url = sanitize_db_url(raw_db_url)
    try:
        # minconn=1, maxconn=10
        pool = ThreadedConnectionPool(1, 10, db_url, connect_timeout=10)
        return pool
    except Exception as e:
        raise ConnectionError(f"データベース（Supabase PostgreSQL）への接続に失敗しました: {e}")

@contextmanager
def get_db_cursor(commit=False):
    """
    DB接続プールから接続を取得し、処理終了時に確実に返却するコンテキストマネージャ。
    正常終了時は必要に応じてコミット、例外発生時はロールバックして確実に返却する。
    """
    pool = get_db_pool()
    conn = pool.getconn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            yield cur
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)

def get_supabase_client() -> Client:
    """Supabase クライアント（Storage操作・署名付きURL発行用）を取得"""
    url = get_secret("SUPABASE_URL")
    key = get_secret("SUPABASE_KEY")
    if not url or not key:
        raise ConnectionError("SUPABASE_URL または SUPABASE_KEY が設定されていません。")
    try:
        return create_client(url, key)
    except Exception as e:
        raise ConnectionError(f"Supabase クライアントの初期化に失敗しました: {e}")

# ========================================================
# 操作ID（Idempotency Key）による保存状態の厳格確認
# 戻り値:
#  - {"status": "saved", "data": dict}      : 保存済み
#  - {"status": "not_found", "data": None}  : 未登録（安全に新規登録可能）
#  - {"status": "error", "error": str}      : 確認失敗（通信障害等。未登録とみなしてはならない）
# ========================================================

def check_idempotency_status(table_name: str, idempotency_key: str) -> dict:
    """
    指定テーブルにおける操作IDの保存状態を確認。
    対応テーブル: projects, project_posts, schedule_proposals, project_versions, project_evaluations
    """
    if not idempotency_key:
        return {"status": "not_found", "data": None}

    allowed_tables = {
        "projects": "SELECT id, title, status FROM projects WHERE idempotency_key = %s",
        "project_posts": "SELECT id, content FROM project_posts WHERE idempotency_key = %s",
        "schedule_proposals": "SELECT id, status FROM schedule_proposals WHERE idempotency_key = %s",
        "project_versions": "SELECT id, version_number, version_label FROM project_versions WHERE idempotency_key = %s",
        "project_evaluations": "SELECT id, quality_score FROM project_evaluations WHERE idempotency_key = %s"
    }

    query = allowed_tables.get(table_name)
    if not query:
        return {"status": "error", "error": f"未対応のテーブル名です: {table_name}"}

    try:
        with get_db_cursor(commit=False) as cur:
            cur.execute(query, (idempotency_key,))
            row = cur.fetchone()
            if row:
                return {"status": "saved", "data": dict(row)}
            else:
                return {"status": "not_found", "data": None}
    except Exception as e:
        return {"status": "error", "error": str(e)}

# ========================================================
# 権限チェック付き Private Storage 署名URL発行
# ========================================================

def can_access_project(user: dict, project_id: int, cur=None) -> bool:
    """
    ユーザーが該当案件にアクセス可能か判定。
    ・岡本（admin）: 全案件アクセス可
    ・依頼者（requester）: 自部署（requester_id == user.id）の案件のみ
    ※ cur が渡された場合は同一トランザクション内の未コミット行も正しく参照可能
    """
    if not user:
        return False
    if user.get("role") == "admin":
        return True
    try:
        def _get_req_id(c):
            c.execute("SELECT requester_id FROM projects WHERE id = %s", (project_id,))
            row = c.fetchone()
            if not row:
                return None
            if hasattr(row, "keys") and "requester_id" in row:
                return row["requester_id"]
            return row[0]

        if cur is not None:
            req_id = _get_req_id(cur)
        else:
            with get_db_cursor(commit=False) as cursor:
                req_id = _get_req_id(cursor)

        return req_id == user.get("id")
    except Exception:
        return False

def verify_file_belongs_to_project(project_id: int, storage_path: str, cur=None) -> bool:
    """
    指定された storage_path が、本当に該当案件（project_id）の
    project_attachments / project_versions / post_attachments に登録されているか確認
    """
    try:
        def _check(c):
            # 1. project_attachments
            c.execute("SELECT 1 FROM project_attachments WHERE project_id = %s AND storage_path = %s", (project_id, storage_path))
            if c.fetchone():
                return True
            # 2. project_versions
            c.execute("SELECT 1 FROM project_versions WHERE project_id = %s AND file_path = %s", (project_id, storage_path))
            if c.fetchone():
                return True
            # 3. post_attachments (project_posts経由)
            c.execute("""
                SELECT 1 FROM post_attachments pa
                JOIN project_posts pp ON pa.post_id = pp.id
                WHERE pp.project_id = %s AND pa.storage_path = %s
            """, (project_id, storage_path))
            if c.fetchone():
                return True
            return False

        if cur is not None:
            return _check(cur)
        else:
            with get_db_cursor(commit=False) as cursor:
                return _check(cursor)
    except Exception:
        return False

def get_signed_file_url(user: dict, project_id: int, storage_path: str, expires_in: int = 300, cur=None) -> str:
    """
    案件閲覧権限に加え、指定ファイルが実際にその案件に属することをDB記録で確認してから署名URLを発行。
    """
    if not can_access_project(user, project_id, cur=cur):
        st.error("この案件へのアクセス権限がありません。")
        return None

    if not verify_file_belongs_to_project(project_id, storage_path, cur=cur):
        st.error("指定されたファイルはこの案件に登録されていません。アクセスを拒否しました。")
        return None

    try:
        supabase = get_supabase_client()
        res = supabase.storage.from_("attachments").create_signed_url(storage_path, expires_in)
        if isinstance(res, dict) and "signedURL" in res:
            return res["signedURL"]
        elif hasattr(res, "signed_url"):
            return res.signed_url
        elif isinstance(res, dict) and "signedUrl" in res:
            return res["signedUrl"]
        return res
    except Exception as e:
        st.error(f"ファイル署名URLの発行に失敗しました: {e}")
        return None

def upload_attachment_file(user: dict, project_id: int, file_bytes: bytes, file_name: str, folder: str = "briefs", cur=None) -> str:
    """Private バケット `attachments` にファイルをアップロード"""
    if not can_access_project(user, project_id, cur=cur):
        raise PermissionError("ファイルアップロード権限がありません。")
    try:
        supabase = get_supabase_client()
        ext = os.path.splitext(file_name)[1]
        unique_name = f"{uuid.uuid4().hex}{ext}"
        storage_path = f"projects/{project_id}/{folder}/{unique_name}"
        
        supabase.storage.from_("attachments").upload(
            path=storage_path,
            file=file_bytes,
            file_options={"content-type": "application/octet-stream"}
        )
        return storage_path
    except Exception as e:
        raise RuntimeError(f"Storageへのファイルアップロードに失敗しました: {e}")

# ========================================================
# 下書き保存 & 復元 (project_drafts)
# ========================================================

def save_project_draft(user_id: int, form_type: str, draft_data: dict):
    """ブラウザ再読み込みに備えて下書きをDBに保存"""
    try:
        draft_json = json.dumps(draft_data, ensure_ascii=False)
        with get_db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO project_drafts (user_id, form_type, draft_data_json, updated_at)
                VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (user_id, form_type)
                DO UPDATE SET draft_data_json = EXCLUDED.draft_data_json, updated_at = CURRENT_TIMESTAMP
            """, (user_id, form_type, draft_json))
        return True
    except Exception as e:
        st.error(f"下書きの保存に失敗しました: {e}")
        return False

def get_project_draft(user_id: int, form_type: str) -> dict:
    """保存された下書きを取得"""
    try:
        with get_db_cursor(commit=False) as cur:
            cur.execute("SELECT draft_data_json FROM project_drafts WHERE user_id = %s AND form_type = %s", (user_id, form_type))
            row = cur.fetchone()
            if row and row[0]:
                return json.loads(row[0])
    except Exception as e:
        st.error(f"下書きの読み込みに失敗しました: {e}")
    return None

def delete_project_draft(user_id: int, form_type: str):
    """依頼完了後に下書きを削除"""
    try:
        with get_db_cursor(commit=True) as cur:
            cur.execute("DELETE FROM project_drafts WHERE user_id = %s AND form_type = %s", (user_id, form_type))
    except Exception:
        pass
