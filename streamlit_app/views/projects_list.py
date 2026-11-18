import streamlit as st
from database import get_db_cursor
from services.action_runner import is_busy

STATUS_LABELS = {
    'waiting_acceptance': ('受付待ち', '#fd7e14'),
    'reviewing': ('日程承認待ち', '#0dcaf0'),
    'in_progress': ('制作中', '#0d6efd'),
    'waiting_client_review': ('依頼者確認待ち', '#6f42c1'),
    'revising': ('修正対応待ち', '#d63384'),
    'waiting_delivery': ('校了（納品待ち）', '#20c997'),
    'delivered': ('納品完了', '#198754'),
    'cancelled': ('取消済み', '#6c757d')
}

def render_projects_list(current_user: dict):
    col_t, col_a = st.columns([7, 3])
    with col_t:
        st.markdown("### 📋 案件一覧")
        if current_user["role"] == "admin":
            st.caption("全依頼部署の案件が表示されています。")
        else:
            st.caption(f"{current_user['display_name']} の依頼案件が表示されています。")
            
    with col_a:
        if current_user["role"] != "admin":
            if st.button("➕ 新規制作依頼", type="primary", use_container_width=True, disabled=is_busy()):
                st.session_state.page = "project_create"
                st.rerun()
        else:
            if st.button("⚙️ 業務ルール設定", use_container_width=True, disabled=is_busy()):
                st.session_state.page = "settings"
                st.rerun()

    try:
        with get_db_cursor(commit=False) as cur:
            if current_user["role"] == "admin":
                cur.execute("""
                    SELECT p.*, u.display_name as requester_name
                    FROM projects p
                    JOIN users u ON p.requester_id = u.id
                    ORDER BY p.id DESC
                """)
            else:
                cur.execute("""
                    SELECT p.*, u.display_name as requester_name
                    FROM projects p
                    JOIN users u ON p.requester_id = u.id
                    WHERE p.requester_id = %s
                    ORDER BY p.id DESC
                """, (current_user["id"],))
            projects = cur.fetchall()
    except Exception as e:
        st.error(f"案件の取得に失敗しました: {e}")
        return

    # 通常案件と取り消し済み案件の分離
    active_projects = [p for p in projects if p["status"] != "cancelled"]
    cancelled_projects = [p for p in projects if p["status"] == "cancelled"]

    # 取り消し済み案件の表示切り替えチェックボックス
    col_filter1, col_filter2 = st.columns([7, 3])
    with col_filter2:
        show_cancelled = st.checkbox(
            f"取り消し済みを表示 ({len(cancelled_projects)}件)",
            value=False,
            key="show_cancelled_projects_checkbox"
        )

    display_projects = list(active_projects)
    if show_cancelled:
        display_projects.extend(cancelled_projects)

    if not display_projects:
        if show_cancelled or not cancelled_projects:
            st.info("現在、表示できる案件はありません（0件）。")
        else:
            st.info(f"進行中の案件はありません（取り消し済み案件が {len(cancelled_projects)} 件あります。「取り消し済みを表示」をオンにすると確認できます）。")
        return

    for p in display_projects:
        status_text, status_color = STATUS_LABELS.get(p["status"], (p["status"], "#6c757d"))
        is_cancelled = (p["status"] == "cancelled")
        
        with st.container(border=True):
            c1, c2, c3, c4 = st.columns([5, 2, 3, 2])
            with c1:
                st.markdown(f"**#{p['id']} {p['title']}**")
                st.caption(f"依頼部署: {p['requester_name']} | 担当者: {p['requester_person_name'] or '未指定'}")
                if is_cancelled and p.get("cancel_reason"):
                    st.caption(f"取り消し理由: {p['cancel_reason']}")
            with c2:
                st.markdown(f"<span style='background-color: {status_color}; color: white; padding: 3px 8px; border-radius: 4px; font-size: 12px;'>{status_text}</span>", unsafe_allow_html=True)
            with c3:
                if is_cancelled:
                    st.caption("※ 進行停止")
                else:
                    deliv = p["desired_delivery_date"] or "未定"
                    st.caption(f"希望納品日: **{deliv}**")
                    if p["first_draft_deadline"]:
                        st.caption(f"初稿目安: {p['first_draft_deadline']}")
            with c4:
                if st.button("詳細を見る", key=f"view_p_{p['id']}", use_container_width=True, disabled=is_busy()):
                    st.session_state.current_project_id = p["id"]
                    st.session_state.page = "project_detail"
                    st.rerun()
