import streamlit as st
import sys
import os

# モジュール検索パスにカレントディレクトリを追加
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from database import get_secret
from components.header import render_header
from components.footer import render_footer
from components.desktop_notification import render_desktop_notification_prompt
from services.action_runner import render_processing_banner, render_flash_messages
from views.login_view import render_login_view
from views.projects_list import render_projects_list
from views.project_create import render_project_create
from views.project_detail import render_project_detail
from views.settings_view import render_settings_view

# Streamlit 基本ページ設定
st.set_page_config(
    page_title="社内バナー制作デスク",
    page_icon="🎨",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# セッション状態の初期化
if "current_user" not in st.session_state:
    st.session_state.current_user = None

if "page" not in st.session_state:
    st.session_state.page = "login"

if "current_project_id" not in st.session_state:
    st.session_state.current_project_id = None

# 接続設定の確認
db_url = get_secret("SUPABASE_DB_URL")
if not db_url:
    st.error("⚠️ データベース接続情報（SUPABASE_DB_URL）が未設定です。")
    st.info("""
    **初期セットアップが必要です**:
    1. `streamlit_app/.streamlit/secrets.toml.example` をコピーして `secrets.toml` を作成してください。
    2. Supabase の接続情報（`SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_DB_URL`）を設定してください。
    3. Community Cloud デプロイ時は、Streamlit の App Settings -> Secrets に同様に設定してください。
    """)
    render_footer()
    st.stop()

# 処理中表示・視認性向上のためのCSS注入（白く薄くなりすぎず、画面内容を読める程度に残す）
st.markdown("""
<style>
/* Streamlit実行中の過度な透過を防ぎ、処理中も内容を読めるようにする */
div[data-testid="stApp"] [data-st-loading="true"],
.stApp.st-emotion-cache-1wmy9hl,
div[data-testid="stAppViewContainer"] > section[data-testid="stMain"] {
    transition: opacity 0.2s ease-in-out;
}
/* 処理中の操作ボタン無効化時の明確なスタイル */
button:disabled {
    cursor: not-allowed !important;
    opacity: 0.65 !important;
}
</style>
""", unsafe_allow_html=True)

# 共通ヘッダー（ログインユーザー表示・ベル通知・ログアウト）
render_header(st.session_state.current_user)

# 処理中バナー・フラッシュメッセージの表示
render_processing_banner()
render_flash_messages()

# ログイン時のみデスクトップ通知案内を表示
if st.session_state.current_user:
    render_desktop_notification_prompt()

# ページルーティング
if not st.session_state.current_user:
    render_login_view()
else:
    page = st.session_state.page
    if page == "projects_list":
        render_projects_list(st.session_state.current_user)
    elif page == "project_create":
        render_project_create(st.session_state.current_user)
    elif page == "project_detail":
        render_project_detail(st.session_state.current_user, st.session_state.current_project_id)
    elif page == "settings":
        render_settings_view(st.session_state.current_user)
    else:
        render_projects_list(st.session_state.current_user)

# 共通フッター
render_footer()
