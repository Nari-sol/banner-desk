import json
import streamlit as st
import streamlit.components.v1 as components
from database import get_db_cursor
from utils import format_datetime_jst
from services.action_runner import is_busy

@st.fragment(run_every="10s")
def render_notification_bell(user_id: int):
    """
    ベル通知コンポーネント (st.fragmentにより10秒ごとに自動更新)
    未読通知を取得し、新着通知があればデスクトップ通知 (Web Notification API) を自動発行する。
    """
    # デスクトップ通知済みIDのセッション管理
    if "notified_notification_ids" not in st.session_state:
        st.session_state.notified_notification_ids = None

    unreads = []
    reads = []
    unread_count = 0
    try:
        with get_db_cursor(commit=False) as cur:
            # 未読通知（最大20件）
            cur.execute("""
                SELECT id, project_id, title, message, link_url, created_at, is_read
                FROM notifications
                WHERE user_id = %s AND is_read = FALSE
                ORDER BY id DESC LIMIT 20
            """, (user_id,))
            unreads = cur.fetchall()
            unread_count = len(unreads)

            # 既読通知（直近10件）
            cur.execute("""
                SELECT id, project_id, title, message, link_url, created_at, is_read
                FROM notifications
                WHERE user_id = %s AND is_read = TRUE
                ORDER BY id DESC LIMIT 10
            """, (user_id,))
            reads = cur.fetchall()
    except Exception:
        unread_count = 0
        unreads = []
        reads = []

    # 新着デスクトップ通知の判定
    current_unread_ids = {n["id"] for n in unreads}
    new_notifications_to_show = []

    if st.session_state.notified_notification_ids is None:
        # 初回ロード時: 現在の未読を「既知」として記録（古い通知が一斉に鳴らないようにする）
        st.session_state.notified_notification_ids = set(current_unread_ids)
    else:
        # 10秒ごとの自動更新時: 未通知の新着があれば抽出
        for n in unreads:
            if n["id"] not in st.session_state.notified_notification_ids:
                new_notifications_to_show.append(n)
                st.session_state.notified_notification_ids.add(n["id"])

    # 新着通知がある場合、デスクトップ通知を発行する JavaScript を iframe で実行
    if new_notifications_to_show:
        notif_scripts = []
        for n in new_notifications_to_show:
            safe_title = json.dumps(f"【バナー制作デスク】{n['title']}")
            safe_msg = json.dumps(n['message'])
            notif_scripts.append(f"""
            try {{
                if ("Notification" in window && Notification.permission === "granted") {{
                    new Notification({safe_title}, {{
                        body: {safe_msg},
                        icon: "https://cdn-icons-png.flaticon.com/512/1827/1827349.png"
                    }});
                }}
            }} catch(e) {{
                console.error("Desktop Notification error:", e);
            }}
            """)

        js_code = f"""
        <script>
        (function() {{
            {''.join(notif_scripts)}
        }})();
        </script>
        """
        components.html(js_code, height=0, width=0)

    badge = f"🔔 ({unread_count})" if unread_count > 0 else "🔔 (0)"
    
    with st.popover(badge, use_container_width=False):
        st.markdown("**🔔 お知らせ・通知**")
        st.caption("通知から内容を確認すると既読になります")
        
        col_hdr1, col_hdr2 = st.columns([6, 4])
        with col_hdr1:
            st.markdown(f"**未読通知 ({unread_count}件)**")
        with col_hdr2:
            if unread_count > 0:
                if st.button("すべて既読にする", key=f"mark_all_read_{user_id}", type="secondary", use_container_width=True, disabled=is_busy()):
                    try:
                        with get_db_cursor(commit=True) as cur:
                            cur.execute("UPDATE notifications SET is_read = TRUE WHERE user_id = %s AND is_read = FALSE", (user_id,))
                        st.rerun()
                    except Exception as e:
                        st.error(f"一括既読エラー: {e}")

        if unread_count == 0:
            st.info("未読の通知はありません")
        else:
            for n in unreads:
                with st.container(border=True):
                    st.markdown(f"🔵 **{n['title']}**")
                    created_str = format_datetime_jst(n['created_at'], '%m/%d %H:%M')
                    st.caption(f"{n['message']} ({created_str})")
                    
                    btn_c1, btn_c2 = st.columns(2)
                    with btn_c1:
                        if st.button("確認する", key=f"view_notif_{n['id']}", type="primary", use_container_width=True, disabled=is_busy()):
                            try:
                                # 対象通知のみを既読化（バックエンドでも自ユーザー限定）
                                with get_db_cursor(commit=True) as cur:
                                    cur.execute("UPDATE notifications SET is_read = TRUE WHERE id = %s AND user_id = %s", (n["id"], user_id))
                                if n.get("project_id"):
                                    st.session_state.current_project_id = n["project_id"]
                                    st.session_state.page = "project_detail"
                                    st.session_state.active_notification_info = {
                                        "id": n["id"],
                                        "title": n["title"],
                                        "message": n["message"]
                                    }
                                st.rerun()
                            except Exception as e:
                                st.error(f"通知確認エラー: {e}")
                    with btn_c2:
                        if st.button("既読にする", key=f"mark_one_read_{n['id']}", type="secondary", use_container_width=True, disabled=is_busy()):
                            try:
                                with get_db_cursor(commit=True) as cur:
                                    cur.execute("UPDATE notifications SET is_read = TRUE WHERE id = %s AND user_id = %s", (n["id"], user_id))
                                st.rerun()
                            except Exception as e:
                                st.error(f"既読更新エラー: {e}")

        # 既読通知の表示（直近10件）
        if reads:
            st.divider()
            with st.expander(f"既読の通知 ({len(reads)}件)", expanded=False):
                for n in reads:
                    st.markdown(f"⚪ <span style='color: gray;'>**{n['title']}**</span>", unsafe_allow_html=True)
                    created_str = format_datetime_jst(n['created_at'], '%m/%d %H:%M')
                    st.caption(f"{n['message']} ({created_str})")
                    if n.get("project_id"):
                        if st.button("案件を開く", key=f"view_read_notif_{n['id']}", use_container_width=True, disabled=is_busy()):
                            st.session_state.current_project_id = n["project_id"]
                            st.session_state.page = "project_detail"
                            st.rerun()
                    st.divider()

def render_header(current_user: dict):
    col1, col2, col3, col4 = st.columns([5, 2, 3, 2])
    with col1:
        st.markdown("### 🎨 バナー制作デスク")
    
    if current_user:
        with col2:
            render_notification_bell(current_user["id"])
        with col3:
            st.markdown(f"👤 **{current_user['display_name']}**")
        with col4:
            if st.button("ログアウト", key="logout_btn", type="secondary", disabled=is_busy()):
                st.session_state.current_user = None
                st.session_state.page = "login"
                st.session_state.current_project_id = None
                st.rerun()
    st.divider()
