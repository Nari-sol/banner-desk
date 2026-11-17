import streamlit as st
from database import get_db_cursor, get_secret

def render_login_view():
    st.markdown("<h2 style='text-align: center; margin-bottom: 24px;'>ログイン</h2>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #666; margin-bottom: 32px;'>ご利用の部署または担当者を選択してください。</p>", unsafe_allow_html=True)

    if st.session_state.get("show_passcode_input", False):
        render_passcode_form()
        return

    col1, col2 = st.columns([1, 1])
    with col1:
        st.markdown("#### 🏢 依頼部署（ワンクリックログイン）")
        st.caption("パスワード入力なしで自部署の管理画面を開きます。")
        
        if st.button("🛒 販売促進課（依頼者）", use_container_width=True, key="login_hansoku"):
            login_user_by_username("hansoku")
            
        if st.button("🌿 ウェルネス事業部（依頼者）", use_container_width=True, key="login_wellness"):
            login_user_by_username("wellness")
            
        if st.button("📑 管理部（依頼者）", use_container_width=True, key="login_kanri"):
            login_user_by_username("kanri")

    with col2:
        st.markdown("#### 🎨 制作・管理者")
        st.caption("全案件の確認・日程調整・制作担当を行います。")
        
        if st.button("👤 岡本（管理者 / デザイナー）", use_container_width=True, type="primary", key="login_okamoto_trigger"):
            st.session_state.show_passcode_input = True
            st.rerun()

def render_passcode_form():
    st.markdown("#### 🔒 管理者認証")
    st.caption("岡本の専用画面を開くには、6桁のパスコードを入力してください。")

    with st.form("admin_passcode_form"):
        passcode = st.text_input("パスコード（数字6桁）", type="password", max_chars=6, placeholder="例: 123456")
        col_btn1, col_btn2 = st.columns([1, 1])
        with col_btn1:
            submitted = st.form_submit_button("認証してログイン", type="primary", use_container_width=True)
        with col_btn2:
            cancel = st.form_submit_button("戻る", use_container_width=True)

    if submitted:
        expected_passcode = str(get_secret("ADMIN_PASSCODE", "930519"))
        if passcode == expected_passcode:
            st.session_state.show_passcode_input = False
            login_user_by_username("okamoto")
        else:
            st.error("パスコードが正しくありません。")

    if cancel:
        st.session_state.show_passcode_input = False
        st.rerun()

def login_user_by_username(username: str):
    try:
        with get_db_cursor(commit=False) as cur:
            cur.execute("SELECT id, username, display_name, role, email FROM users WHERE username = %s", (username,))
            user = cur.fetchone()
            if user:
                st.session_state.current_user = dict(user)
                st.session_state.page = "projects_list"
                st.rerun()
            else:
                st.error(f"ユーザー情報（{username}）が見つかりません。")
    except Exception as e:
        st.error(f"ログイン処理に失敗しました: {e}")
