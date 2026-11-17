import streamlit as st
import json
from database import get_db_cursor
from services.action_runner import (
    is_busy,
    set_pending_action,
    get_pending_action,
    clear_pending_action,
    set_flash_message
)

def render_settings_view(current_user: dict):
    if current_user["role"] != "admin":
        st.error("業務設定は岡本（管理者）のみ変更できます。")
        if st.button("案件一覧に戻る"):
            st.session_state.page = "projects_list"
            st.rerun()
        return

    st.markdown("### ⚙️ 業務ルール・各種設定")
    if st.button("← 案件一覧に戻る", disabled=is_busy()):
        st.session_state.page = "projects_list"
        st.rerun()

    try:
        with get_db_cursor(commit=False) as cur:
            cur.execute("SELECT key, value FROM system_settings")
            settings_map = {row["key"]: json.loads(row["value"]) for row in cur.fetchall()}
    except Exception as e:
        st.error(f"設定の読み込みに失敗しました: {e}")
        return

    b_hours = settings_map.get("business_hours", {})
    d_rules = settings_map.get("deadline_rules", {})

    with st.form("settings_form"):
        st.markdown("#### 1. 営業時間と受付締切（カットオフ）")
        st.caption("※合意仕様: 12:00までの受付は当日16:00一次返信、12:00以降は翌営業日16:00一次返信")
        c1, c2, c3 = st.columns(3)
        with c1:
            start_t = st.text_input("業務開始時刻", value=b_hours.get("start_time", "09:00"))
        with c2:
            end_t = st.text_input("業務終了時刻", value=b_hours.get("end_time", "18:00"))
        with c3:
            cutoff_t = st.text_input("当日受付カットオフ時刻", value=b_hours.get("reception_cutoff", "12:00"))

        st.markdown("#### 2. 目安リードタイム（営業日数）")
        c4, c5 = st.columns(2)
        with c4:
            draft_days = st.number_input("初稿提出標準目安（日）", min_value=1, max_value=14, value=d_rules.get("first_draft_business_days", 3))
        with c5:
            rev_days = st.number_input("修正版提出標準目安（日）", min_value=1, max_value=14, value=d_rules.get("revision_business_days", 2))

        submitted = st.form_submit_button("設定を保存する", type="primary", disabled=is_busy())

    if submitted:
        b_hours["start_time"] = start_t
        b_hours["end_time"] = end_t
        b_hours["reception_cutoff"] = cutoff_t
        d_rules["first_draft_business_days"] = draft_days
        d_rules["revision_business_days"] = rev_days

        set_pending_action(
            "save_settings",
            "⚙️ 業務ルール設定を保存しています…",
            payload={"b_hours": b_hours, "d_rules": d_rules}
        )

    # 保留アクションの実行
    pending = get_pending_action()
    if pending.get("action") == "save_settings":
        with st.spinner(pending.get("message", "⚙️ 業務ルール設定を保存しています…")):
            try:
                payload = pending["payload"]
                with get_db_cursor(commit=True) as cur:
                    cur.execute("UPDATE system_settings SET value = %s, updated_at = CURRENT_TIMESTAMP WHERE key = 'business_hours'", (json.dumps(payload["b_hours"]),))
                    cur.execute("UPDATE system_settings SET value = %s, updated_at = CURRENT_TIMESTAMP WHERE key = 'deadline_rules'", (json.dumps(payload["d_rules"]),))
                clear_pending_action()
                set_flash_message("success", "業務ルール設定を保存しました。")
                st.rerun()
            except Exception as e:
                clear_pending_action()
                st.error(f"設定保存エラー: {e}")
