import os
import streamlit as st
import uuid
from datetime import date, timedelta
from database import (
    get_db_cursor, 
    can_access_project, 
    get_signed_file_url, 
    upload_attachment_file,
    check_idempotency_status,
    POLICY_DESC_MAP
)
from utils import format_datetime_jst
from services.action_runner import (
    is_busy,
    set_pending_action,
    get_pending_action,
    clear_pending_action,
    set_flash_message
)

STATUS_LABELS = {
    'waiting_acceptance': ('受付待ち', '#fd7e14'),
    'reviewing': ('日程承認待ち', '#0dcaf0'),
    'in_progress': ('制作中', '#0d6efd'),
    'waiting_client_review': ('依頼者確認待ち', '#6f42c1'),
    'revising': ('修正対応待ち', '#d63384'),
    'waiting_delivery': ('校了（納品待ち）', '#20c997'),
    'delivered': ('納品完了', '#198754'),
    'cancelled': ('取消', '#6c757d')
}

# 確定した評価基準マスター（各4点満点・合計12点満点）
EVALUATION_CRITERIA_OPTIONS = {
    'careless_mistakes': {
        'label': 'ケアレスミスの少なさ',
        'note': '※依頼後の追加変更や、デザインを良くするための相談・微調整は、ケアレスミスには含めません。',
        'options': {
            4: "4点: 初稿の制作ミスが0件で、依頼者の原稿・支給資料にあった表記や枚数の誤り、不整合を事前に発見して指摘・修正した。",
            3: "3点: 初稿の制作ミスが0件で、4点の追加条件には該当しない。",
            2: "2点: 初稿に制作ミスがあり、依頼者による指摘・修正の手間が発生したが、最終納品までに修正された。",
            1: "1点: 最終納品として提出されたデータに制作ミスがあった。（初稿の点数にかかわらず1点を優先。その後修正されても1点とする）"
        }
    },
    'quality': {
        'label': '品質・デザイン完成度',
        'note': '※1点の条件に該当する場合は1点を優先し、それ以外は条件を満たす最も高い点数を選択してください。（※修正回数は減点対象に含みません）',
        'options': {
            4: "4点: 目的・意図と必須要素を満たした高品質な仕上がりに加え、目標達成に向けたデザインアイデアを2件以上提案した。",
            3: "3点: 目的・意図と必須要素を満たした高品質な仕上がりに加え、目標達成に向けたデザインアイデアを1件提案した。",
            2: "2点: 目的・意図と必須要素を満たし、実用上の問題がない。",
            1: "1点: 目的・意図や必須要素の反映に不足があり、修正が必要だった。"
        }
    },
    'communication': {
        'label': 'やりとり・レスポンス',
        'note': '【適用ルール】\n・1点に該当する場合は1点を優先する。\n・通常の質問や追加依頼を「催促」として減点しない。\n・報告・相談すべき事項がなかった案件は、自発的な連絡がないことだけで2点に下げない。\n・期限内に「確認中であることと回答予定」を伝え、その予定を守った場合は、最終回答が当日でなくても減点しない。\n・12時ちょうどは「12時まで（当日16時一次返信）」に含め、次の区分は「12時を過ぎた場合（翌営業日16時一次返信）」とする。',
        'options': {
            4: "4点: 3点の条件を満たしたうえで、問題になりそうな点について先回りした確認や解決案の提示があった。",
            3: "3点: 必要な連絡が定められた期限内に行われ、依頼者の問いかけを待たずに必要な報告・相談があった。",
            2: "2点: 連絡期限の超過や必要事項の共有漏れはなかったが、やりとりは依頼者の問いかけへの返答が中心で、自発的な報告・相談がなかった。",
            1: "1点: 必要な確認・共有の連絡に漏れや遅れがあった。（依頼者が催促せず待っていた場合も含む）"
        }
    }
}

def render_project_detail(current_user: dict, project_id: int):
    if not can_access_project(current_user, project_id):
        st.error("この案件の閲覧権限がありません。")
        if st.button("案件一覧に戻る", disabled=is_busy()):
            st.session_state.page = "projects_list"
            st.rerun()
        return

    try:
        with get_db_cursor(commit=False) as cur:
            cur.execute("""
                SELECT p.*, u.display_name as requester_name
                FROM projects p
                JOIN users u ON p.requester_id = u.id
                WHERE p.id = %s
            """, (project_id,))
            p = cur.fetchone()

            cur.execute("SELECT * FROM project_media_items WHERE project_id = %s", (project_id,))
            media_items = cur.fetchall()

            cur.execute("SELECT * FROM project_attachments WHERE project_id = %s ORDER BY id ASC", (project_id,))
            attachments = cur.fetchall()

            cur.execute("""
                SELECT sp.*, u.display_name as proposer_name, r.display_name as reviewer_name
                FROM schedule_proposals sp
                LEFT JOIN users u ON sp.proposed_by = u.id
                LEFT JOIN users r ON sp.reviewed_by = r.id
                WHERE sp.project_id = %s
                ORDER BY sp.id DESC
            """, (project_id,))
            all_schedules = cur.fetchall()
            latest_schedule = all_schedules[0] if (all_schedules and p["status"] != "waiting_acceptance") else None

            cur.execute("""
                SELECT pv.*, u.display_name as approved_by_name
                FROM project_versions pv
                LEFT JOIN users u ON pv.approved_by = u.id
                WHERE pv.project_id = %s
                ORDER BY pv.version_number ASC
            """, (project_id,))
            versions = cur.fetchall()

            cur.execute("""
                SELECT post.*, u.display_name as author_name
                FROM project_posts post
                JOIN users u ON post.created_by = u.id
                WHERE post.project_id = %s AND post.is_deleted = FALSE
                ORDER BY post.id ASC
            """, (project_id,))
            posts = cur.fetchall()

            cur.execute("""
                SELECT pa.*, pp.project_id
                FROM post_attachments pa
                JOIN project_posts pp ON pa.post_id = pp.id
                WHERE pp.project_id = %s
                ORDER BY pa.id ASC
            """, (project_id,))
            all_post_attachments = cur.fetchall()
            post_attachments_map = {}
            for pa in all_post_attachments:
                post_attachments_map.setdefault(pa["post_id"], []).append(pa)

            cur.execute("SELECT * FROM project_evaluations WHERE project_id = %s", (project_id,))
            evaluation = cur.fetchone()

    except Exception as e:
        st.error(f"データ取得エラー: {e}")
        return

    if not p:
        st.error("指定された案件が見つかりません。")
        return

    status_text, status_color = STATUS_LABELS.get(p["status"], (p["status"], "#6c757d"))
    c_back, c_title = st.columns([2, 8])
    with c_back:
        if st.button("← 案件一覧へ", use_container_width=True, disabled=is_busy()):
            st.session_state.page = "projects_list"
            st.session_state.current_project_id = None
            st.rerun()
    with c_title:
        st.markdown(f"### #{p['id']} {p['title']} <span style='background-color: {status_color}; color: white; padding: 4px 10px; border-radius: 4px; font-size: 14px;'>{status_text}</span>", unsafe_allow_html=True)

    if p["status"] == "cancelled":
        with st.container(border=True):
            st.error("⛔ **この案件は取り消されました（取消済み）**")
            st.markdown(f"・**取り消し日時**: {format_datetime_jst(p['cancelled_at']) if p.get('cancelled_at') else '日時記録なし'}")
            st.markdown(f"・**取り消し理由**: **{p.get('cancel_reason') or '未記載'}**")
            st.caption("※ 取り消された案件は制作進行・連絡操作（日程・提出・承認・納品・評価・コメント）を停止しています。")

    if "active_notification_info" in st.session_state and st.session_state.active_notification_info:
        notif_info = st.session_state.active_notification_info
        c_notif, c_close = st.columns([9, 1])
        with c_notif:
            st.info(f"🔔 **通知の確認**: 「{notif_info['title']}」 {notif_info['message']}")
        with c_close:
            if st.button("✕", key="close_active_notif", help="案内を閉じる"):
                st.session_state.active_notification_info = None
                st.rerun()

    tab1, tab2, tab3, tab4 = st.tabs(["📄 依頼内容・制作物", "⚡ アクション・日程", "💬 連絡タイムライン", "⭐ 納品物・評価"])

    # TAB 1: 依頼内容・制作物
    with tab1:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f"**依頼部署**: {p['requester_name']}")
            st.markdown(f"**ご担当者**: {p['requester_person_name'] or '未指定'}")
            st.markdown(f"**登録日**: {format_datetime_jst(p['created_at'], '%Y-%m-%d %H:%M')}")
        with c2:
            st.markdown(f"**初稿希望日**: {p['desired_first_draft_date'] or '未指定'}")
            st.markdown(f"**最終納品希望日**: **{p['desired_delivery_date']}**")
            st.markdown(f"**一次返信目標**: {p['first_reply_deadline'] or '未定'}")

        st.divider()
        st.markdown("#### 制作物リスト")
        if media_items:
            for m in media_items:
                cat_display = m.get("custom_media_name") or m["media_category"]
                item_display = m.get("custom_item_name") or m["item_name"]
                st.write(f"・{cat_display} : **{item_display}** （{m['quantity']}点）")
        else:
            st.write(f"・{p['placement']} / {p['size']} （{p['quantity']}点）")

        st.divider()
        st.markdown("#### 依頼詳細")
        if p["selling_point"]:
            st.markdown(f"**アピールポイント**: {p['selling_point']}")
        if p["customer_benefit"]:
            st.markdown(f"**顧客メリット**: {p['customer_benefit']}")
        if p["content_text"]:
            st.markdown(f"**掲載原稿・文言**:\n```\n{p['content_text']}\n```")
        if p["required_elements"]:
            st.markdown(f"**必須掲載要素**: {p['required_elements']}")

        policy = p.get("production_policy")
        if policy:
            desc = POLICY_DESC_MAP.get(policy, "")
            if desc:
                st.markdown(f"**制作方針**: :blue-background[**{policy}**]  \n<span style='color: gray; font-size: 13px;'>└ {desc}</span>", unsafe_allow_html=True)
            else:
                st.markdown(f"**制作方針**: :blue-background[**{policy}**]")
        else:
            st.markdown("**制作方針**: 未設定")

        if p["design_taste"]:
            st.markdown(f"**希望テイスト**: {p['design_taste']}")

        st.divider()
        st.markdown("#### 📎 依頼添付ファイル")
        if attachments:
            for att in attachments:
                signed_url = get_signed_file_url(current_user, p["id"], att["storage_path"], download_filename=att["original_name"], expires_in=300)
                if signed_url:
                    st.markdown(f"・[{att['original_name']}]({signed_url}) （ダウンロード / 所属確認済み）")
                else:
                    st.markdown(f"・{att['original_name']} (アクセス拒否)")
        else:
            st.caption("添付ファイルはありません。")

    # TAB 2: アクション・日程調整
    with tab2:
        is_admin = (current_user["role"] == "admin")
        
        if p["status"] == "cancelled":
            st.warning("⛔ **この案件は取り消されているため、制作日程の調整・制作物提出・納品等の進行操作は停止されています。**")
        else:
            st.markdown("#### 📅 制作日程の状況")
            
            # 1. 現在の日程状態の表示
            if p["schedule_confirmed"]:
                st.success(f"✅ **制作日程が確定しています**\n・初稿予定: **{p['first_draft_deadline']}**\n・最終納品予定: **{p['final_delivery_deadline']}**")
            elif latest_schedule and latest_schedule["status"] == "pending":
                st.info(f"⏳ **デザイナーより制作日程が提示されています（日程承認待ち）**\n・初稿提示日: **{latest_schedule['first_draft_date']}**\n・最終納品予定日: **{latest_schedule['final_delivery_date']}**\n・提示理由・連絡事項: {latest_schedule['reason'] or '特になし'}")
            elif latest_schedule and latest_schedule["status"] == "rejected":
                st.warning(f"🔄 **日程変更相談中**\n前回の相談内容: {latest_schedule['review_comment'] or 'なし'}\n岡本（デザイナー）からの日程再提示をお待ちください。")
            else:
                st.warning("⚠️ **制作日程はまだ提示されていません。** 岡本（デザイナー）からの日程提示をお待ちください。")

            # 2. 依頼部署（not is_admin）のアクション: 日程の確認・承認
            if not is_admin and latest_schedule and latest_schedule["status"] == "pending":
                prop_key_name = f"review_schedule_{latest_schedule['id']}_idempotency_key"
                if prop_key_name not in st.session_state:
                    st.session_state[prop_key_name] = str(uuid.uuid4())

                with st.container(border=True):
                    st.markdown("##### 📝 提示日程の確認・承認")
                    st.write("提示された上記日程を確認し、「承認」または「変更相談」を選択してください。")
                    review_comment = st.text_input("コメント（変更相談の場合はご希望日程や理由をご記入ください）", key="schedule_review_comment", placeholder="例: 11/22までの初稿提出は可能でしょうか？")
                    col_a1, col_a2 = st.columns(2)
                    with col_a1:
                        if st.button("✅ この日程で承認する（制作開始）", type="primary", use_container_width=True, disabled=is_busy()):
                            set_pending_action(
                                "review_schedule",
                                "✅ 制作日程を承認しています…",
                                payload={
                                    "proposal_id": latest_schedule["id"],
                                    "decision": "approved",
                                    "comment": review_comment,
                                    "op_id": st.session_state[prop_key_name]
                                }
                            )
                    with col_a2:
                        if st.button("🔄 日程の変更相談をする", use_container_width=True, disabled=is_busy()):
                            set_pending_action(
                                "review_schedule",
                                "🔄 日程変更相談を送信しています…",
                                payload={
                                    "proposal_id": latest_schedule["id"],
                                    "decision": "rejected",
                                    "comment": review_comment,
                                    "op_id": st.session_state[prop_key_name]
                                }
                            )

            # 3. 岡本（is_admin）のアクション: 制作日程の提示・再提示
            if is_admin:
                st.markdown("##### 📌 デザイナー操作: 制作日程の提示")
                if "prop_schedule_idempotency_key" not in st.session_state:
                    st.session_state.prop_schedule_idempotency_key = str(uuid.uuid4())

                is_rejected = (latest_schedule and latest_schedule["status"] == "rejected")
                is_pending = (latest_schedule and latest_schedule["status"] == "pending")
                form_exp_title = "🔄 制作日程の再提示" if (is_rejected or is_pending) else "📌 制作日程の提示"
                
                with st.expander(form_exp_title, expanded=(not p["schedule_confirmed"])):
                    if is_rejected:
                        st.warning(f"※ 依頼部署から変更相談が届いています: {latest_schedule['review_comment'] or 'なし'}")
                    elif is_pending:
                        st.info("※ 現在、依頼部署の日程承認待ちです。日程を変更する場合は再提示してください。")
                    
                    with st.form("propose_schedule_form"):
                        default_draft = date.today() + timedelta(days=3)
                        default_deliv = date.today() + timedelta(days=7)
                        p_draft = st.date_input("初稿提示日", value=default_draft)
                        p_deliv = st.date_input("最終納品日", value=default_deliv)
                        p_reason = st.text_input("提示理由・コメント", placeholder="制作スケジュール調整完了のため提示します。")
                        submit_prop = st.form_submit_button("日程を依頼者へ提示する", type="primary", disabled=is_busy())
                        
                    if submit_prop:
                        if not p_draft or not p_deliv:
                            st.error("初稿提示日と最終納品日を入力してください。")
                        elif str(p_draft) > str(p_deliv):
                            st.error("初稿日は最終納品日以前の日付を指定してください。")
                        else:
                            set_pending_action(
                                "propose_schedule",
                                "📅 制作日程を提示しています…",
                                payload={"draft_date": str(p_draft), "deliv_date": str(p_deliv), "reason": p_reason}
                            )

            # 4. 過去の日程提示・合意履歴の一覧表示
            if all_schedules:
                with st.expander("📜 日程提示・合意の履歴一覧", expanded=False):
                    for s in all_schedules:
                        status_badge = "✅ 承認済み" if s["status"] == "approved" else ("🔄 変更相談" if s["status"] == "rejected" else "⏳ 承認待ち")
                        st.markdown(f"**第{s['id']}回提示** ({status_badge}) - 提示日時: {format_datetime_jst(s['proposed_at'])}")
                        st.caption(f"・提示者: {s.get('proposer_name') or '岡本'} | 初稿: {s['first_draft_date']} | 最終納品: {s['final_delivery_date']}")
                        if s["reason"]:
                            st.caption(f"・提示理由: {s['reason']}")
                        if s["reviewed_at"]:
                            st.caption(f"・回答者: {s.get('reviewer_name') or '依頼部署'} ({format_datetime_jst(s['reviewed_at'])})")
                            if s["review_comment"]:
                                st.caption(f"・回答コメント: {s['review_comment']}")
                        st.divider()

            st.divider()

            # 5. 岡本（is_admin）: 制作物の提出・納品
            if is_admin:
                st.markdown("##### 🎨 デザイナー操作: 制作物の提出・納品")
                col_act1, col_act2 = st.columns(2)
                with col_act1:
                    st.markdown("**初稿／修正版の提出**")
                    can_submit = (p["status"] in ("in_progress", "revising"))
                    if not can_submit:
                        if not p["schedule_confirmed"]:
                            st.caption("※ 依頼部署による日程の承認完了後に提出できます。")
                        elif p["status"] == "waiting_client_review":
                            st.info("※ 現在、依頼者の確認待ちです。")
                        elif p["status"] == "waiting_delivery":
                            st.success("※ 校了済みです。最終データを納品してください。")
                        elif p["status"] == "delivered":
                            st.caption("※ 納品完了済みです。")
                        else:
                            st.caption(f"※ 現在のステータス（{STATUS_LABELS.get(p['status'], (p['status'], ''))[0]}）では提出できません。")
                    else:
                        v_file = st.file_uploader("提出画像・ファイル", key="v_upload_file")
                        v_comment = st.text_input("提出コメント", placeholder="初稿デザインを作成しました。ご確認ください。")
                        if st.button("制作物を提出する", type="primary", key="btn_submit_version", disabled=is_busy()):
                            if not v_file:
                                st.error("ファイルを指定してください。")
                            else:
                                set_pending_action(
                                    "submit_version",
                                    "📤 制作物をアップロードして提出しています…",
                                    payload={
                                        "file_bytes": v_file.getvalue(),
                                        "file_name": v_file.name,
                                        "comment": v_comment,
                                        "is_final": False
                                    }
                                )

                with col_act2:
                    st.markdown("**納品完了**")
                    can_deliver = (p["status"] == "waiting_delivery")
                    if not can_deliver:
                        if p["status"] == "delivered":
                            st.success("※ 既に最終データが納品完了しています。")
                        else:
                            st.caption("※ 依頼者による制作物の承認（校了）完了後に納品可能になります。")
                    else:
                        st.info("※ 依頼者による校了が完了しました。最終納品データを登録してください。")
                        final_file = st.file_uploader("最終納品ファイル（任意）", key="final_upload_file")
                        final_comment = st.text_input("納品コメント", placeholder="最終納品データです。ありがとうございました。")
                        if st.button("納品完了として記録する", type="primary", key="btn_complete_delivery", disabled=is_busy()):
                            set_pending_action(
                                "submit_version",
                                "📦 最終納品データを登録しています…",
                                payload={
                                    "file_bytes": final_file.getvalue() if final_file else None,
                                    "file_name": final_file.name if final_file else None,
                                    "comment": final_comment,
                                    "is_final": True
                                }
                            )

            # 6. 依頼部署（not is_admin）: 提出制作物の確認・承認（校了）または修正依頼
            if not is_admin and p["status"] == "waiting_client_review":
                latest_v = versions[-1] if versions else None
                with st.container(border=True):
                    st.markdown("##### 🔍 提出された制作物の確認・承認（校了）")
                    if latest_v:
                        st.info(f"現在、**第{latest_v['version_number']}版（{latest_v['version_label']}）** が提出されています。")
                        if latest_v["comment"]:
                            st.caption(f"デザイナーからのコメント: {latest_v['comment']}")
                        signed_v_url = get_signed_file_url(current_user, p["id"], latest_v["file_path"], download_filename=latest_v["original_name"], expires_in=300)
                        if signed_v_url:
                            st.markdown(f"[📥 提出ファイルをダウンロード / 確認（{latest_v['original_name']}）]({signed_v_url})")

                    st.write("内容をご確認の上、「この内容で承認する（校了）」または「修正を依頼する」を選択してください。")
                    col_c1, col_c2 = st.columns(2)
                    with col_c1:
                        with st.container(border=True):
                            st.markdown("**【修正なし】承認して納品へ進む**")
                            st.caption("修正箇所がなく、この内容で制作を進めてよろしければ承認（校了）してください。デザイナーへ最終納品が依頼されます。")
                            approve_comment = st.text_input("承認コメント（任意）", key="approve_version_comment", placeholder="例: こちらの内容で進めてください。")
                            if st.button("✅ この内容で承認する（校了）", type="primary", use_container_width=True, key="btn_approve_version", disabled=is_busy()):
                                if not latest_v:
                                    st.error("承認対象の提出版が見つかりません。")
                                else:
                                    set_pending_action(
                                        "approve_version",
                                        "✅ 制作物を承認（校了）しています…",
                                        payload={"version_id": latest_v["id"], "comment": approve_comment}
                                    )

                    with col_c2:
                        with st.container(border=True):
                            st.markdown("**【修正あり】修正を依頼する**")
                            st.caption("修正・変更が必要な点がある場合は、具体的な指示を入力して送信してください。")
                            rev_comment = st.text_area("修正指示・気になる点（必須）", key="revision_instruction_text", placeholder="例: キャッチコピーの文字色を赤に変更してください。")
                            if st.button("✏️ 修正を依頼する", use_container_width=True, key="btn_request_revision", disabled=is_busy()):
                                if not rev_comment.strip():
                                    st.error("修正指示・気になる点を入力してください。")
                                else:
                                    set_pending_action(
                                        "request_revision",
                                        "✏️ 修正依頼を送信しています…",
                                        payload={"comment": rev_comment.strip()}
                                    )

    # TAB 3: 連絡タイムライン
    with tab3:
        st.markdown("#### 💬 コメント・質問・連絡履歴")
        if posts:
            for post in posts:
                with st.chat_message(name="assistant" if "岡本" in post["author_name"] else "user"):
                    act_badge = f" `[{post['action_label']}]`" if post.get("action_label") else ""
                    st.markdown(f"**{post['author_name']}**{act_badge} ({format_datetime_jst(post['created_at'], '%m/%d %H:%M')})")
                    if post["content"]:
                        st.markdown(post["content"])

                    # 添付ファイルの表示（画像プレビュー & ダウンロードリンク）
                    atts = post_attachments_map.get(post["id"], [])
                    if atts:
                        st.markdown("📎 **共有された参考資料・素材:**")
                        for att in atts:
                            download_url = get_signed_file_url(current_user, p["id"], att["storage_path"], download_filename=att["original_name"], expires_in=300)
                            preview_url = get_signed_file_url(current_user, p["id"], att["storage_path"], download_filename=False, expires_in=300)

                            ext = os.path.splitext(att["original_name"])[1].lower()
                            if preview_url and ext in [".png", ".jpg", ".jpeg", ".gif", ".webp", ".jfif"]:
                                st.image(preview_url, caption=att["original_name"], width=260)

                            if download_url:
                                st.markdown(f"・[{att['original_name']}]({download_url}) （ダウンロード）")
                            else:
                                st.markdown(f"・{att['original_name']} (アクセス不可)")
        else:
            st.caption("タイムラインの投稿はまだありません。")

        st.divider()
        if p["status"] == "cancelled":
            st.info("※ この案件は取り消されているため、新しいコメントの投稿は停止されています。")
        else:
            if "post_idempotency_key" not in st.session_state:
                st.session_state.post_idempotency_key = str(uuid.uuid4())

            with st.form("new_post_form", clear_on_submit=True):
                post_content = st.text_area("新しいコメント・質問・連絡を入力", placeholder="案件に関する連絡事項をご記入ください（参考ファイルのみの送信も可能です）。")
                uploaded_files = st.file_uploader(
                    "参考資料・追加素材ファイルの添付（任意・複数可）",
                    accept_multiple_files=True,
                    help="依頼後に追加したい指示書、画像、PDF、ZIPなどを添付できます。"
                )
                submit_post = st.form_submit_button("コメント・ファイルを送信", type="primary", disabled=is_busy())

            if submit_post:
                if not post_content.strip() and not uploaded_files:
                    st.error("コメントを入力するか、参考ファイルを添付してください。")
                else:
                    att_payload = []
                    if uploaded_files:
                        for uf in uploaded_files:
                            att_payload.append({
                                "name": uf.name,
                                "bytes": uf.getvalue(),
                                "type": uf.type
                            })
                    set_pending_action(
                        "add_post",
                        "💬 連絡内容とファイルを送信しています…",
                        payload={
                            "content": post_content.strip(),
                            "attachments": att_payload
                        }
                    )

    # TAB 4: 納品物・評価
    with tab4:
        st.markdown("#### 🖼️ 提出バージョン一覧")
        if versions:
            for v in versions:
                st.markdown(f"**第{v['version_number']}版 ({v['version_label']})** - {format_datetime_jst(v['submitted_at'], '%Y-%m-%d %H:%M')}")
                if v.get("is_approved"):
                    st.success(f"✅ **校了（承認済み）** - 承認日時: {format_datetime_jst(v['approved_at'])} | 承認者: {v.get('approved_by_name') or '依頼者'}")
                    if v.get("approval_comment"):
                        st.caption(f"承認コメント: {v['approval_comment']}")
                if v["comment"]:
                    st.caption(f"提出コメント: {v['comment']}")
                # プレビュー表示用（インラインURL: download_filename=False）
                preview_v_url = get_signed_file_url(current_user, p["id"], v["file_path"], download_filename=False, expires_in=300)
                # ダウンロード用（ダウンロードヘッダー付きURL: download_filename=v["original_name"]）
                download_v_url = get_signed_file_url(current_user, p["id"], v["file_path"], download_filename=v["original_name"], expires_in=300)
                
                if preview_v_url and v.get("file_path", "").lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".jfif")):
                    st.image(preview_v_url, width=300)
                if download_v_url:
                    st.markdown(f"[📥 ファイルをダウンロード（{v['original_name']}）]({download_v_url})")
                st.divider()
        else:
            st.caption("提出された制作物はまだありません。")

        st.divider()
        st.markdown("#### ⭐ 案件評価（納品完了後・各4点満点 / 合計12点満点）")

        if evaluation:
            q = evaluation['quality_score']
            c = evaluation['communication_score']
            m = evaluation['careless_mistake_score']
            total = q + c + m
            st.success(f"**評価結果**: 合計 **{total} / 12点**\n- 品質・デザイン完成度: **{q} / 4点**\n- やりとり・レスポンス: **{c} / 4点**\n- ケアレスミスの少なさ: **{m} / 4点**\n\nコメント: {evaluation['overall_comment'] or 'なし'}")

        elif p["status"] == "delivered" and not is_admin:
            if "eval_idempotency_key" not in st.session_state:
                st.session_state.eval_idempotency_key = str(uuid.uuid4())

            st.caption("各項目の判定基準をご確認の上、該当する点数を選択してください（※すべて必須選択です）。")

            with st.form("eval_form"):
                # 1. ケアレスミス（確定）
                cm_data = EVALUATION_CRITERIA_OPTIONS['careless_mistakes']
                st.markdown(f"##### 1. {cm_data['label']} (4点満点)")
                st.caption(cm_data['note'])
                m_score = st.radio(
                    "ケアレスミス採点",
                    options=[4, 3, 2, 1],
                    format_func=lambda x: cm_data['options'][x],
                    index=None,
                    key="eval_m_radio"
                )

                st.divider()

                # 2. 品質（確定）
                q_data = EVALUATION_CRITERIA_OPTIONS['quality']
                st.markdown(f"##### 2. {q_data['label']} (4点満点)")
                st.caption(q_data['note'])
                q_score = st.radio(
                    "品質採点",
                    options=[4, 3, 2, 1],
                    format_func=lambda x: q_data['options'][x],
                    index=None,
                    key="eval_q_radio"
                )

                st.divider()

                # 3. やりとり（確定）
                c_data = EVALUATION_CRITERIA_OPTIONS['communication']
                st.markdown(f"##### 3. {c_data['label']} (4点満点)")
                st.info(c_data['note'])
                c_score = st.radio(
                    "やりとり採点",
                    options=[4, 3, 2, 1],
                    format_func=lambda x: c_data['options'][x],
                    index=None,
                    key="eval_c_radio"
                )

                st.divider()
                eval_comment = st.text_area("総合コメント・振り返り（任意）", placeholder="案件の振り返りや感想をご記入ください。")
                submit_eval = st.form_submit_button("評価を送信する", type="primary", disabled=is_busy())

            if submit_eval:
                if m_score is None or q_score is None or c_score is None:
                    st.error("すべての評価項目を選択してください（未選択の項目があります）。")
                else:
                    set_pending_action(
                        "submit_eval",
                        "⭐ 評価を保存しています…",
                        payload={"q": q_score, "c": c_score, "m": m_score, "comment": eval_comment}
                    )

        elif p["status"] == "cancelled":
            st.caption("※ 取り消された案件の評価は行えません。")
        else:
            st.caption("納品完了後に依頼部署から評価を入力いただけます。")

    # 依頼部署による案件取り消しUI（未完了案件のみ）
    if not is_admin and current_user["id"] == p["requester_id"] and p["status"] not in ("delivered", "cancelled"):
        st.divider()
        if "cancel_project_idempotency_key" not in st.session_state:
            st.session_state.cancel_project_idempotency_key = str(uuid.uuid4())

        with st.expander("⚠️ この制作依頼を取り消す", expanded=False):
            st.warning("⚠️ **誤って登録した案件を取り消します**\n取り消しを行うと、案件の制作進行・連絡は停止します（物理削除はされず「取消済み」として保存されます）。")
            st.markdown(f"・**対象案件**: `#{p['id']}` **{p['title']}**")
            
            cancel_reason_input = st.text_area(
                "取り消し理由（必須）",
                key="cancel_project_reason_input",
                placeholder="例: 施策変更のため取り消します / 誤って二重登録したため"
            )
            
            c_c1, c_c2 = st.columns([6, 4])
            with c_c1:
                st.caption("※ 取り消し操作は元に戻せません。理由をご確認の上、実行してください。")
            with c_c2:
                if st.button("⛔ 案件の取り消しを確定する", type="primary", use_container_width=True, key="btn_confirm_cancel_project", disabled=is_busy()):
                    if not cancel_reason_input.strip():
                        st.error("取り消し理由を必ず入力してください。")
                    else:
                        set_pending_action(
                            "cancel_project",
                            "⛔ 案件を取り消しています…",
                            payload={
                                "reason": cancel_reason_input.strip(),
                                "op_id": st.session_state.cancel_project_idempotency_key
                            }
                        )

    # 保留アクションの実行（二段階実行により全ボタンがdisabledの状態でスピナー実行）
    pending = get_pending_action()
    if pending:
        act = pending.get("action")
        payload = pending.get("payload", {})
        msg = pending.get("message", "処理を実行しています…")

        with st.spinner(msg):
            if act == "propose_schedule":
                execute_propose_schedule(project_id, current_user, payload["draft_date"], payload["deliv_date"], payload["reason"])
            elif act == "review_schedule":
                execute_review_schedule(project_id, current_user, payload["proposal_id"], payload["decision"], payload["comment"], payload.get("op_id"))
            elif act == "cancel_project":
                execute_cancel_project(project_id, current_user, payload["reason"], payload.get("op_id"))
            elif act == "submit_version":
                execute_submit_version(project_id, current_user, payload.get("file_bytes"), payload.get("file_name"), payload["comment"], payload.get("is_final", False))
            elif act == "approve_version":
                execute_approve_version(project_id, current_user, payload["version_id"], payload["comment"])
            elif act == "request_revision":
                execute_request_revision(project_id, current_user["id"], payload["comment"])
            elif act == "add_post":
                execute_add_post(project_id, current_user, payload["content"], payload.get("attachments", []))
            elif act == "submit_eval":
                execute_submit_evaluation(project_id, current_user["id"], payload["q"], payload["c"], payload["m"], payload["comment"])

# ================= 業務ロジック実行関数 =================

def execute_propose_schedule(project_id, current_user, draft_date, deliv_date, reason):
    # 1. 権限検証（管理者・デザイナーのみ）
    if current_user.get("role") != "admin":
        clear_pending_action()
        st.error("日程提示の権限がありません（管理者・デザイナー専用操作です）。")
        return

    # 2. 入力値の検証
    if not draft_date or not deliv_date:
        clear_pending_action()
        st.error("初稿提示日と最終納品日を入力してください。")
        return
    if str(draft_date) > str(deliv_date):
        clear_pending_action()
        st.error("初稿日は最終納品日以前の日付を指定してください。")
        return

    op_id = st.session_state.get("prop_schedule_idempotency_key", str(uuid.uuid4()))
    check = check_idempotency_status("schedule_proposals", op_id)
    if check["status"] == "saved":
        clear_pending_action()
        set_flash_message("info", "日程提示は既に正常に保存されています。")
        st.session_state.prop_schedule_idempotency_key = str(uuid.uuid4())
        st.rerun()
        return
    if check["status"] == "error":
        clear_pending_action()
        st.error(f"日程提示の保存状態確認に失敗しました: {check['error']}")
        return

    try:
        with get_db_cursor(commit=True) as cur:
            # 3. 案件の現在状態を検証
            cur.execute("SELECT id, title, status, requester_id, first_reply_actual FROM projects WHERE id = %s FOR UPDATE", (project_id,))
            p = cur.fetchone()
            if not p:
                clear_pending_action()
                st.error("該当案件が存在しません。")
                return
            if p["status"] == "cancelled":
                clear_pending_action()
                st.error("この案件は取り消されているため、日程提示を行えません。")
                return
            if p["status"] not in ("waiting_acceptance", "reviewing"):
                clear_pending_action()
                st.error(f"現在のステータス（{p['status']}）では日程提示を行えません。")
                return

            # 4. schedule_proposals に追加（pending状態）
            cur.execute("""
                INSERT INTO schedule_proposals (project_id, first_draft_date, final_delivery_date, reason, proposed_by, idempotency_key, status)
                VALUES (%s, %s, %s, %s, %s, %s, 'pending')
                RETURNING id;
            """, (project_id, draft_date, deliv_date, reason, current_user["id"], op_id))

            # 5. projects を更新（status='reviewing': 日程承認待ち, waiting_for='requester'）
            cur.execute("""
                UPDATE projects 
                SET status = 'reviewing',
                    waiting_for = 'requester',
                    first_draft_deadline = %s,
                    final_delivery_deadline = %s,
                    first_reply_actual = COALESCE(first_reply_actual, TO_CHAR(CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Tokyo', 'YYYY-MM-DD HH24:MI:SS')),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (f"{draft_date} 18:00:00", f"{deliv_date} 18:00:00", project_id))

            # 6. タイムライン投稿の記録（操作ログ）
            post_content = f"【日程提示】初稿提出予定: {draft_date} / 最終納品予定: {deliv_date}\n理由・連絡事項: {reason or 'なし'}"
            cur.execute("""
                INSERT INTO project_posts (project_id, post_type, content, action_label, created_by)
                VALUES (%s, 'action_log', %s, '日程提示', %s)
            """, (project_id, post_content, current_user["id"]))

            # 7. 依頼部署へ通知発行
            cur.execute("""
                INSERT INTO notifications (user_id, project_id, title, message)
                VALUES (%s, %s, '制作日程が提示されました', %s)
            """, (p["requester_id"], project_id, f"「{p['title']}」の日程が提示されました（初稿: {draft_date} / 納品: {deliv_date}）。内容をご確認の上、承認または変更相談をお願いします。"))

        st.session_state.prop_schedule_idempotency_key = str(uuid.uuid4())
        clear_pending_action()
        set_flash_message("success", "制作日程を依頼部署へ提示しました（日程承認待ち）。")
        st.rerun()
    except Exception as e:
        clear_pending_action()
        st.error(f"日程提示エラー: {e}")

def execute_review_schedule(project_id, current_user, proposal_id, decision, comment, op_id=None):
    if op_id:
        check = check_idempotency_status("schedule_review", op_id)
        if check["status"] == "saved":
            clear_pending_action()
            set_flash_message("info", "この日程への回答は既に正常に保存されています。")
            st.session_state[f"review_schedule_{proposal_id}_idempotency_key"] = str(uuid.uuid4())
            st.rerun()
            return
        if check["status"] == "error":
            clear_pending_action()
            st.error(f"日程確認の保存状態確認に失敗しました: {check['error']}")
            return

    flash_info = None
    try:
        with get_db_cursor(commit=True) as cur:
            # 1. 案件の閲覧・操作権限検証（行ロック取得）
            cur.execute("SELECT id, title, status, requester_id FROM projects WHERE id = %s FOR UPDATE", (project_id,))
            p = cur.fetchone()
            if not p:
                clear_pending_action()
                st.error("該当案件が存在しません。")
                return

            # バックエンド厳格権限検証: 依頼部署の担当者本人のみ許可（他部署・デザイナー本人承認は拒否）
            if current_user["id"] != p["requester_id"]:
                clear_pending_action()
                st.error("この案件の日程を承認・変更相談する権限がありません（依頼部署専用の操作です）。")
                return

            if p["status"] == "cancelled":
                clear_pending_action()
                st.error("この案件は取り消されているため、日程の確認・承認は行えません。")
                return

            # 2. 案件ステータス検証
            if p["status"] != "reviewing":
                clear_pending_action()
                st.error(f"現在のステータス（{STATUS_LABELS.get(p['status'], (p['status'], ''))[0]}）では日程の確認操作を行えません。")
                return

            # 3. 最新の日程提案であるかの厳格検証
            cur.execute("""
                SELECT id, status, first_draft_date, final_delivery_date 
                FROM schedule_proposals 
                WHERE project_id = %s 
                ORDER BY id DESC LIMIT 1 FOR UPDATE
            """, (project_id,))
            latest_prop = cur.fetchone()

            if not latest_prop or latest_prop["id"] != proposal_id:
                clear_pending_action()
                st.error("指定された日程提案は最新のものではありません。画面を再読み込みして最新の日程をご確認ください。")
                return

            if latest_prop["status"] != "pending":
                clear_pending_action()
                set_flash_message("warning", f"この日程提案は既に回答済みです（現在の状態: {latest_prop['status']}）。")
                st.rerun()
                return

            clean_comment = (comment or "").strip()

            if decision == "approved":
                # 提案を承認
                cur.execute("""
                    UPDATE schedule_proposals 
                    SET status = 'approved',
                        reviewed_by = %s,
                        reviewed_at = CURRENT_TIMESTAMP,
                        review_comment = %s,
                        review_idempotency_key = %s
                    WHERE id = %s AND status = 'pending'
                """, (current_user["id"], clean_comment, op_id, proposal_id))

                # 案件を「制作中」へ遷移
                cur.execute("""
                    UPDATE projects 
                    SET status = 'in_progress',
                        waiting_for = 'designer',
                        schedule_confirmed = TRUE,
                        first_draft_deadline = %s,
                        final_delivery_deadline = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s AND status = 'reviewing'
                """, (f"{latest_prop['first_draft_date']} 18:00:00", f"{latest_prop['final_delivery_date']} 18:00:00", project_id))

                # タイムライン記録
                log_content = f"【日程承認】提示された日程を承認しました（初稿: {latest_prop['first_draft_date']} / 最終納品: {latest_prop['final_delivery_date']}）。制作を開始してください。"
                if clean_comment:
                    log_content += f"\nコメント: {clean_comment}"
                cur.execute("""
                    INSERT INTO project_posts (project_id, post_type, content, action_label, created_by)
                    VALUES (%s, 'action_log', %s, '日程承認', %s)
                """, (project_id, log_content, current_user["id"]))

                # 岡本（admin, id=1）へ通知
                cur.execute("""
                    INSERT INTO notifications (user_id, project_id, title, message)
                    VALUES (1, %s, '日程が承認されました（制作中）', %s)
                """, (project_id, f"#{project_id}「{p['title']}」の日程が依頼部署により承認されました。制作を開始してください。"))

                flash_info = ("success", "日程を承認しました。ステータスが「制作中」になりました！")

            elif decision == "rejected":
                # 提案を変更相談（差戻し）
                cur.execute("""
                    UPDATE schedule_proposals 
                    SET status = 'rejected',
                        reviewed_by = %s,
                        reviewed_at = CURRENT_TIMESTAMP,
                        review_comment = %s,
                        review_idempotency_key = %s
                    WHERE id = %s AND status = 'pending'
                """, (current_user["id"], clean_comment, op_id, proposal_id))

                # 案件は制作中にせず、日程承認待ち／再調整へ（waiting_for='admin'）
                cur.execute("""
                    UPDATE projects 
                    SET status = 'reviewing',
                        waiting_for = 'admin',
                        schedule_confirmed = FALSE,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s AND status = 'reviewing'
                """, (project_id,))

                # タイムライン記録
                log_content = "【日程変更相談】提示された日程について変更・再調整を希望します。"
                if clean_comment:
                    log_content += f"\nご要望・相談内容: {clean_comment}"
                cur.execute("""
                    INSERT INTO project_posts (project_id, post_type, content, action_label, created_by)
                    VALUES (%s, 'action_log', %s, '日程変更相談', %s)
                """, (project_id, log_content, current_user["id"]))

                # 岡本（admin, id=1）へ通知
                cur.execute("""
                    INSERT INTO notifications (user_id, project_id, title, message)
                    VALUES (1, %s, '日程の変更相談が届きました', %s)
                """, (project_id, f"#{project_id}「{p['title']}」の日程について変更相談が届きました。再提示をお願いします。相談内容: {clean_comment or 'なし'}"))

                flash_info = ("info", "日程の変更相談を送信しました。岡本からの日程再提示をお待ちください。")

        # DBコミット完了後にUI更新・画面再描画を実行
        if op_id:
            st.session_state[f"review_schedule_{proposal_id}_idempotency_key"] = str(uuid.uuid4())
        clear_pending_action()
        if flash_info:
            set_flash_message(flash_info[0], flash_info[1])
        st.rerun()

    except Exception as e:
        clear_pending_action()
        st.error(f"日程確認エラー: {e}")

def execute_cancel_project(project_id, current_user, reason, op_id=None):
    clean_reason = (reason or "").strip()
    if not clean_reason:
        clear_pending_action()
        st.error("取り消し理由を入力してください。")
        return

    if op_id:
        check = check_idempotency_status("projects_cancel", op_id)
        if check["status"] == "saved":
            clear_pending_action()
            set_flash_message("info", "この案件は既に取り消し処理が完了しています。")
            st.session_state.cancel_project_idempotency_key = str(uuid.uuid4())
            st.rerun()
            return
        if check["status"] == "error":
            clear_pending_action()
            st.error(f"案件取り消しの保存状態確認に失敗しました: {check['error']}")
            return

    try:
        with get_db_cursor(commit=True) as cur:
            # 1. 案件の閲覧・操作権限検証（行ロック取得）
            cur.execute("SELECT id, title, status, requester_id FROM projects WHERE id = %s FOR UPDATE", (project_id,))
            p = cur.fetchone()
            if not p:
                clear_pending_action()
                st.error("該当案件が存在しません。")
                return

            # バックエンド厳格権限検証: 自部署の依頼者のみ取り消し可能
            if current_user["id"] != p["requester_id"]:
                clear_pending_action()
                st.error("自部署以外の案件を取り消す権限はありません。")
                return

            # 2. 案件ステータス検証（納品完了・すでに取り消し済みの場合は不可）
            if p["status"] == "delivered":
                clear_pending_action()
                st.error("納品完了済みの案件を取り消すことはできません。")
                return

            if p["status"] == "cancelled":
                clear_pending_action()
                set_flash_message("warning", "この案件は既に取り消し済みです。")
                st.rerun()
                return

            # 3. projects テーブルを取り消し済みに更新
            cur.execute("""
                UPDATE projects 
                SET status = 'cancelled',
                    waiting_for = 'none',
                    cancelled_at = CURRENT_TIMESTAMP,
                    cancelled_by = %s,
                    cancel_reason = %s,
                    cancel_idempotency_key = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s AND status != 'delivered'
            """, (current_user["id"], clean_reason, op_id, project_id))

            # 4. タイムライン投稿の記録（操作ログ）
            log_content = f"【案件取り消し】この制作依頼は依頼部署（{current_user['display_name']}）により取り消されました。\n取り消し理由: {clean_reason}"
            cur.execute("""
                INSERT INTO project_posts (project_id, post_type, content, action_label, created_by)
                VALUES (%s, 'action_log', %s, '案件取り消し', %s)
            """, (project_id, log_content, current_user["id"]))

            # 5. デザイナー（岡本, id=1）へ通知発行
            cur.execute("""
                INSERT INTO notifications (user_id, project_id, title, message)
                VALUES (1, %s, '案件が取り消されました', %s)
            """, (project_id, f"#{project_id}「{p['title']}」が依頼部署（{current_user['display_name']}）により取り消されました。理由: {clean_reason}"))

        # DBコミット完了後にUI更新・画面再描画を実行
        if op_id:
            st.session_state.cancel_project_idempotency_key = str(uuid.uuid4())
        clear_pending_action()
        set_flash_message("warning", "案件を取り消しました（ステータス: 取消済み）。")
        st.rerun()

    except Exception as e:
        clear_pending_action()
        st.error(f"案件取り消しエラー: {e}")

def execute_submit_version(project_id, user, file_bytes, file_name, comment, is_final=False):
    # 1. 権限検証（管理者・デザイナー専用）
    if user.get("role") != "admin":
        clear_pending_action()
        st.error("制作物の提出・納品権限がありません（デザイナー専用操作です）。")
        return

    key_name = "final_submit_idempotency_key" if is_final else "version_submit_idempotency_key"
    if key_name not in st.session_state:
        st.session_state[key_name] = str(uuid.uuid4())
    op_id = st.session_state[key_name]

    check = check_idempotency_status("project_versions", op_id)
    if check["status"] == "saved":
        clear_pending_action()
        set_flash_message("info", "提出データは既に正常に保存されています。")
        st.session_state[key_name] = str(uuid.uuid4())
        st.rerun()
        return
    if check["status"] == "error":
        clear_pending_action()
        st.error(f"提出データの保存状態確認に失敗しました: {check['error']}")
        return

    success_msg = None
    try:
        with get_db_cursor(commit=True) as cur:
            # 2. 案件の現在状態を厳格に検証
            cur.execute("SELECT id, title, status, requester_id, schedule_confirmed FROM projects WHERE id = %s FOR UPDATE", (project_id,))
            p = cur.fetchone()
            if not p:
                clear_pending_action()
                st.error("該当案件が存在しません。")
                return

            if p["status"] == "cancelled":
                clear_pending_action()
                st.error("この案件は取り消されているため、制作物の提出・納品は行えません。")
                return

            if is_final:
                # 最終納品は、依頼者による校了（waiting_delivery）完了後のみ許可
                if p["status"] != "waiting_delivery":
                    clear_pending_action()
                    st.error(f"校了（承認）前に納品完了として記録することはできません（現在のステータス: {STATUS_LABELS.get(p['status'], (p['status'], ''))[0]}）。依頼者による校了をお待ちください。")
                    return
            else:
                # 初稿・修正版提出は、制作中（in_progress）または修正対応待ち（revising）のみ許可
                if p["status"] not in ("in_progress", "revising"):
                    clear_pending_action()
                    st.error(f"現在のステータス（{STATUS_LABELS.get(p['status'], (p['status'], ''))[0]}）では制作物の提出を行えません。")
                    return

            cur.execute("SELECT COALESCE(MAX(version_number), 0) + 1 FROM project_versions WHERE project_id = %s", (project_id,))
            v_num = cur.fetchone()[0]
            v_label = "最終納品版" if is_final else ("初稿" if v_num == 1 else f"修正版 (第{v_num}版)")
            
            storage_path = ""
            final_file_name = file_name or ("最終納品完了" if is_final else "提出ファイル")
            file_size = len(file_bytes) if file_bytes else 0
            if file_bytes and file_name:
                storage_path = upload_attachment_file(user, project_id, file_bytes, file_name, "versions", cur=cur)

            cur.execute("""
                INSERT INTO project_versions (project_id, version_number, version_label, file_path, original_name, file_size, comment, submitted_by, is_final, idempotency_key)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (project_id, v_num, v_label, storage_path, final_file_name, file_size, comment, user["id"], is_final, op_id))

            if is_final:
                cur.execute("""
                    UPDATE projects 
                    SET status = 'delivered',
                        waiting_for = 'none',
                        final_delivery_actual = COALESCE(final_delivery_actual, TO_CHAR(CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Tokyo', 'YYYY-MM-DD HH24:MI:SS')),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (project_id,))

                # タイムライン記録
                log_content = f"【納品完了】最終納品データを登録しました。"
                if comment:
                    log_content += f"\n納品コメント: {comment}"
                cur.execute("""
                    INSERT INTO project_posts (project_id, post_type, content, action_label, created_by)
                    VALUES (%s, 'action_log', %s, '納品完了', %s)
                """, (project_id, log_content, user["id"]))

                # 依頼者へ通知
                cur.execute("""
                    INSERT INTO notifications (user_id, project_id, title, message)
                    VALUES (%s, %s, '制作物が納品されました（納品完了）', %s)
                """, (p["requester_id"], project_id, f"#{project_id}「{p['title']}」の最終データが納品されました。内容をご確認の上、案件の評価をお願いします。"))

                success_msg = "最終納品データの登録が完了しました（納品完了）。"

            else:
                if v_num == 1:
                    cur.execute("""
                        UPDATE projects 
                        SET status = 'waiting_client_review',
                            waiting_for = 'requester',
                            first_draft_actual = COALESCE(first_draft_actual, TO_CHAR(CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Tokyo', 'YYYY-MM-DD HH24:MI:SS')),
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                    """, (project_id,))
                else:
                    cur.execute("""
                        UPDATE projects 
                        SET status = 'waiting_client_review',
                            waiting_for = 'requester',
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                    """, (project_id,))

                # タイムライン記録
                act_label = "初稿提出" if v_num == 1 else f"修正版提出 (第{v_num}版)"
                log_content = f"【{act_label}】制作物を提出しました。"
                if comment:
                    log_content += f"\n提出コメント: {comment}"
                cur.execute("""
                    INSERT INTO project_posts (project_id, post_type, content, action_label, created_by)
                    VALUES (%s, 'action_log', %s, %s, %s)
                """, (project_id, log_content, act_label, user["id"]))

                # 依頼者へ通知
                cur.execute("""
                    INSERT INTO notifications (user_id, project_id, title, message)
                    VALUES (%s, %s, %s, %s)
                """, (p["requester_id"], project_id, f"制作物が提出されました（{act_label}）", f"#{project_id}「{p['title']}」の制作物（{v_label}）が提出されました。内容をご確認の上、承認または修正依頼をお願いします。"))

                success_msg = f"制作物（{v_label}）の提出が完了しました。依頼者確認待ちになります。"

        # DBコミット完了後にUI更新・画面再描画を実行
        st.session_state[key_name] = str(uuid.uuid4())
        clear_pending_action()
        if success_msg:
            set_flash_message("success", success_msg)
        st.rerun()

    except Exception as e:
        clear_pending_action()
        st.error(f"提出エラー: {e}")

def execute_approve_version(project_id, current_user, version_id, comment):
    key_name = f"approve_v_{version_id}_idempotency_key"
    if key_name not in st.session_state:
        st.session_state[key_name] = str(uuid.uuid4())
    op_id = st.session_state[key_name]

    try:
        with get_db_cursor(commit=True) as cur:
            # 1. 権限検証（依頼者本人または管理者）
            cur.execute("SELECT id, title, status, requester_id FROM projects WHERE id = %s FOR UPDATE", (project_id,))
            p = cur.fetchone()
            if not p:
                clear_pending_action()
                st.error("該当案件が存在しません。")
                return

            if p["status"] == "cancelled":
                clear_pending_action()
                st.error("この案件は取り消されているため、校了操作は行えません。")
                return

            if current_user["role"] != "admin" and current_user["id"] != p["requester_id"]:
                clear_pending_action()
                st.error("制作物の承認権限がありません（依頼者専用操作です）。")
                return

            # 2. 状態検証（依頼者確認待ちであること）
            if p["status"] != "waiting_client_review":
                clear_pending_action()
                st.error(f"現在のステータス（{STATUS_LABELS.get(p['status'], (p['status'], ''))[0]}）では校了操作を行えません。")
                return

            # 3. 承認対象が最新の提出版かを検証
            cur.execute("""
                SELECT id, version_number, version_label, is_approved
                FROM project_versions
                WHERE project_id = %s
                ORDER BY version_number DESC
                LIMIT 1
            """, (project_id,))
            latest_v = cur.fetchone()
            if not latest_v or latest_v["id"] != version_id:
                clear_pending_action()
                st.error("承認対象の提出版が最新版と一致しません。画面を更新して最新の内容をご確認ください。")
                return
            if latest_v["is_approved"]:
                clear_pending_action()
                set_flash_message("warning", "このバージョンは既に承認（校了）されています。")
                st.rerun()
                return

            clean_comment = (comment or "").strip()

            # 4. バージョンの承認状態を更新
            cur.execute("""
                UPDATE project_versions 
                SET is_approved = TRUE,
                    approved_by = %s,
                    approved_at = CURRENT_TIMESTAMP,
                    approval_comment = %s
                WHERE id = %s
            """, (current_user["id"], clean_comment, version_id))

            # 5. 案件を「納品待ち」（waiting_delivery, waiting_for='designer'）へ更新
            cur.execute("""
                UPDATE projects 
                SET status = 'waiting_delivery',
                    waiting_for = 'designer',
                    approved_version_id = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (version_id, project_id))

            # 6. タイムライン記録
            log_content = f"【校了】第{latest_v['version_number']}版（{latest_v['version_label']}）を承認（校了）しました。最終データの納品をお願いします。"
            if clean_comment:
                log_content += f"\nコメント: {clean_comment}"
            cur.execute("""
                INSERT INTO project_posts (project_id, post_type, content, action_label, created_by)
                VALUES (%s, 'action_log', %s, '制作物承認（校了）', %s)
            """, (project_id, log_content, current_user["id"]))

            # 7. 岡本（admin, id=1）へ通知
            cur.execute("""
                INSERT INTO notifications (user_id, project_id, title, message)
                VALUES (1, %s, '制作物が校了（承認）されました', %s)
            """, (project_id, f"#{project_id}「{p['title']}」の制作物（第{latest_v['version_number']}版）が依頼部署により承認（校了）されました。最終データの納品をお願いします。"))

        st.session_state[key_name] = str(uuid.uuid4())
        clear_pending_action()
        set_flash_message("success", "制作物を承認（校了）しました！ ステータスが「校了（納品待ち）」になりました。")
        st.rerun()
    except Exception as e:
        clear_pending_action()
        st.error(f"承認エラー: {e}")

def execute_request_revision(project_id, user_id, comment):
    key_name = "revision_request_idempotency_key"
    if key_name not in st.session_state:
        st.session_state[key_name] = str(uuid.uuid4())

    try:
        with get_db_cursor(commit=True) as cur:
            # 1. 案件情報と状態・権限の検証
            cur.execute("SELECT id, title, status, requester_id FROM projects WHERE id = %s FOR UPDATE", (project_id,))
            p = cur.fetchone()
            if not p:
                clear_pending_action()
                st.error("該当案件が存在しません。")
                return
            if p["status"] == "cancelled":
                clear_pending_action()
                st.error("この案件は取り消されているため、修正依頼を行えません。")
                return
            if user_id != p["requester_id"]:
                clear_pending_action()
                st.error("この案件の修正を依頼する権限がありません（依頼者専用操作です）。")
                return
            if p["status"] != "waiting_client_review":
                clear_pending_action()
                st.error(f"現在のステータス（{STATUS_LABELS.get(p['status'], (p['status'], ''))[0]}）では修正依頼を行えません。")
                return

            clean_comment = comment.strip()

            # 2. projects を更新（status='revising', waiting_for='designer'）
            cur.execute("""
                UPDATE projects 
                SET status = 'revising',
                    waiting_for = 'designer',
                    updated_at = CURRENT_TIMESTAMP 
                WHERE id = %s
            """, (project_id,))

            # 3. タイムライン記録
            cur.execute("""
                INSERT INTO project_posts (project_id, post_type, content, action_label, created_by)
                VALUES (%s, 'revision_request', %s, '修正依頼', %s)
            """, (project_id, f"【修正依頼】{clean_comment}", user_id))

            # 4. 岡本（admin, id=1）へ通知
            cur.execute("""
                INSERT INTO notifications (user_id, project_id, title, message)
                VALUES (1, %s, '修正依頼が届きました', %s)
            """, (project_id, f"#{project_id}「{p['title']}」について修正依頼が届きました。内容をご確認ください。指示内容: {clean_comment}"))

        st.session_state[key_name] = str(uuid.uuid4())
        clear_pending_action()
        set_flash_message("success", "修正依頼を送信しました。ステータスが「修正対応待ち」になりました。")
        st.rerun()
    except Exception as e:
        clear_pending_action()
        st.error(f"修正依頼エラー: {e}")

def execute_add_post(project_id, user, content, attachments=None):
    attachments = attachments or []
    op_id = st.session_state.get("post_idempotency_key", str(uuid.uuid4()))
    check = check_idempotency_status("project_posts", op_id)
    if check["status"] == "saved":
        saved_post_id = check["data"]["id"]
        # 添付ファイルのアップロードが一部未完了だった場合の安全な補完
        if attachments:
            try:
                with get_db_cursor(commit=True) as cur:
                    cur.execute("SELECT original_name FROM post_attachments WHERE post_id = %s", (saved_post_id,))
                    existing_att_names = {r[0] for r in cur.fetchall()}
                    for att in attachments:
                        if att["name"] not in existing_att_names:
                            file_bytes = att["bytes"]
                            storage_path = upload_attachment_file(user, project_id, file_bytes, att["name"], "posts", cur=cur)
                            cur.execute("""
                                INSERT INTO post_attachments (post_id, original_name, stored_name, storage_path, file_size, mime_type)
                                VALUES (%s, %s, %s, %s, %s, %s)
                            """, (saved_post_id, att["name"], storage_path.split("/")[-1], storage_path, len(file_bytes), att.get("type", "application/octet-stream")))
            except Exception as att_err:
                st.warning(f"コメントは保存されていますが、一部添付ファイルの保存に失敗しました: {att_err}")

        clear_pending_action()
        set_flash_message("info", "コメント・参考ファイルは既に正常に保存されています。")
        st.session_state.post_idempotency_key = str(uuid.uuid4())
        st.rerun()
        return

    if check["status"] == "error":
        clear_pending_action()
        st.error(f"コメントの保存状態確認に失敗しました: {check['error']}")
        return

    try:
        with get_db_cursor(commit=True) as cur:
            cur.execute("SELECT title, status, requester_id FROM projects WHERE id = %s", (project_id,))
            p_chk = cur.fetchone()
            if not p_chk or p_chk["status"] == "cancelled":
                clear_pending_action()
                st.error("この案件は取り消されているため、コメントの投稿は行えません。")
                return

            if not can_access_project(user, project_id, cur=cur):
                clear_pending_action()
                st.error("この案件へのコメント投稿権限がありません。")
                return

            action_label = "参考資料共有" if attachments else None
            # content は空文字列を許可（NOT NULL 制約対応）
            clean_content = content.strip() if content else ""

            cur.execute("""
                INSERT INTO project_posts (project_id, post_type, content, action_label, created_by, idempotency_key)
                VALUES (%s, 'comment', %s, %s, %s, %s)
                RETURNING id;
            """, (project_id, clean_content, action_label, user["id"], op_id))
            new_post_id = cur.fetchone()[0]

            # 添付ファイルを Storage と post_attachments に保存
            if attachments:
                for att in attachments:
                    file_bytes = att["bytes"]
                    storage_path = upload_attachment_file(user, project_id, file_bytes, att["name"], "posts", cur=cur)
                    cur.execute("""
                        INSERT INTO post_attachments (post_id, original_name, stored_name, storage_path, file_size, mime_type)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (new_post_id, att["name"], storage_path.split("/")[-1], storage_path, len(file_bytes), att.get("type", "application/octet-stream")))

            # 相手ユーザーの特定
            if user["role"] == "admin":
                target_user = p_chk["requester_id"]
            else:
                target_user = 1  # 岡本（デザイナー）

            # 通知タイトル・メッセージの作成
            if clean_content and attachments:
                notif_title = "新しい連絡と参考資料が届きました"
                notif_msg = f"#{project_id}「{p_chk['title']}」: {clean_content[:35]}（添付{len(attachments)}件: {attachments[0]['name']}等）"
            elif attachments:
                notif_title = "参考資料が共有されました"
                notif_msg = f"#{project_id}「{p_chk['title']}」: 参考資料{len(attachments)}件（{attachments[0]['name']}等）が追加されました。"
            else:
                notif_title = "新しい連絡があります"
                notif_msg = f"#{project_id}「{p_chk['title']}」: {clean_content[:50]}"

            cur.execute("""
                INSERT INTO notifications (user_id, project_id, title, message)
                VALUES (%s, %s, %s, %s)
            """, (target_user, project_id, notif_title, notif_msg))

        st.session_state.post_idempotency_key = str(uuid.uuid4())
        clear_pending_action()
        set_flash_message("success", "連絡内容・参考ファイルを送信しました。")
        st.rerun()
    except Exception as e:
        clear_pending_action()
        st.error(f"投稿エラー: {e}")

def execute_submit_evaluation(project_id, user_id, q, c, m, comment):
    for name, val in [("品質", q), ("やりとり", c), ("ケアレスミス", m)]:
        if not (1 <= val <= 4):
            clear_pending_action()
            st.error(f"{name}の点数は1〜4点で入力してください。")
            return

    op_id = st.session_state.get("eval_idempotency_key", str(uuid.uuid4()))
    check = check_idempotency_status("project_evaluations", op_id)
    if check["status"] == "saved":
        clear_pending_action()
        set_flash_message("info", "評価は既に正常に保存されています。")
        st.session_state.eval_idempotency_key = str(uuid.uuid4())
        st.rerun()
        return
    if check["status"] == "error":
        clear_pending_action()
        st.error(f"評価の保存状態確認に失敗しました: {check['error']}")
        return

    try:
        with get_db_cursor(commit=True) as cur:
            cur.execute("SELECT id, requester_id, status FROM projects WHERE id = %s", (project_id,))
            p = cur.fetchone()
            if not p:
                clear_pending_action()
                st.error("該当案件が存在しません。")
                return
            if user_id != p["requester_id"]:
                clear_pending_action()
                st.error("この案件の評価権限がありません（依頼者専用操作です）。")
                return
            if p["status"] == "cancelled":
                clear_pending_action()
                st.error("この案件は取り消されているため、評価を送信することはできません。")
                return
            if p["status"] != "delivered":
                clear_pending_action()
                st.error("納品完了前の案件には評価を送信できません。")
                return

            cur.execute("""
                INSERT INTO project_evaluations (
                    project_id, quality_score, communication_score, careless_mistake_score,
                    overall_comment, on_time_status, evaluated_by, idempotency_key
                ) VALUES (%s, %s, %s, %s, %s, 'on_time', %s, %s)
            """, (project_id, q, c, m, comment, user_id, op_id))
            cur.execute("INSERT INTO notifications (user_id, project_id, title, message) VALUES (1, %s, '案件の評価が届きました', '納品案件に対する評価が登録されました。')", (project_id,))

        st.session_state.eval_idempotency_key = str(uuid.uuid4())
        clear_pending_action()
        set_flash_message("success", "評価を送信しました。ご協力ありがとうございました！")
        st.rerun()
    except Exception as e:
        clear_pending_action()
        st.error(f"評価送信エラー: {e}")
