import streamlit as st
import json
import uuid
from datetime import date, timedelta
from database import (
    get_db_cursor, 
    upload_attachment_file, 
    save_project_draft, 
    get_project_draft, 
    delete_project_draft,
    check_idempotency_status,
    PRODUCTION_POLICIES,
    PRODUCTION_POLICY_DESCRIPTIONS,
    POLICY_DESC_MAP
)
from services.deadline import calculate_initial_deadlines
from services.action_runner import (
    is_busy,
    set_pending_action,
    get_pending_action,
    clear_pending_action,
    set_flash_message
)

MEDIA_CATALOG_SALES_WELLNESS = {
    '楽天市場': [
        'メイン画像※YS兼用',
        'サブ画像※YS・アマゾン兼用',
        '商品ページ内LP画像※YS兼用',
        'クーポンバナー',
        'イベント用バナー',
        '店舗トップページ用バナー',
        'コンテンツページ用バナー',
        'メルマガ用バナー',
        '楽天TDA※4枚で登録',
        '楽天ROOM用バナー',
        'お知らせ系バナー（配送や仕様変更など）',
        'メニューボタン',
        'その他（自由入力）'
    ],
    'Yahoo!ショッピング': [
        'メイン画像',
        'サブ画像',
        '商品ページ内LP画像',
        'クーポンバナー',
        'イベント用バナー',
        '店舗トップページ用バナー',
        'お知らせ系バナー（配送や仕様変更など）',
        'メルマガ用バナー',
        'メニューボタン',
        'その他（自由入力）'
    ],
    'Amazon': [
        'メイン画像',
        'サブ画像',
        '商品ページ内LP画像',
        'ストアフロント用バナー',
        'お知らせ系バナー（配送や仕様変更など）',
        '商品紹介コンテンツ（A+）バナー',
        'その他（自由入力）'
    ],
    'SNS広告（Instagram / LINE 等）': [
        'インスタ投稿・フィード用',
        'インスタストーリーズ・リール用（9:16）',
        'LINE カードタイプ',
        'LINEリッチメニュー',
        'その他（自由入力）'
    ],
    '印刷物（チラシ・パンフ・同梱物・POP）': [
        'チラシ（サイズ）',
        'パッケージ',
        'POP',
        'シール',
        'パンフレット・冊子',
        '取扱説明書',
        'ポスター',
        'ハガキサイズ',
        '看板など大型印刷',
        '印刷・刻印用ロゴ',
        'その他（自由入力）'
    ],
    'その他（自由に媒体名を変更可）': [
        'Shopify用バナー',
        'その他（自由入力）'
    ]
}

MEDIA_CATALOG_KANRI = {
    'SNS広告（Instagram / LINE 等）': [
        'インスタ投稿・フィード用',
        'インスタストーリーズ・リール用（9:16）',
        'LINE カードタイプ',
        'LINEリッチメニュー',
        'その他（自由入力）'
    ],
    '印刷物（チラシ・パンフ・POP 等）': [
        'チラシ（サイズ）',
        'POP',
        'パンフレット・冊子',
        '看板など大型印刷',
        'ポスター',
        'ハガキ',
        '印刷・刻印用ロゴ',
        'その他（自由入力）'
    ],
    'その他（自由に媒体名を変更可）': [
        'その他（自由入力）'
    ]
}

def render_project_create(current_user: dict):
    st.markdown("### 📝 新規制作依頼の登録")
    
    if current_user["role"] == "admin":
        st.warning("岡本（管理者兼デザイナー）は依頼を受ける側のため、新規依頼は登録できません。")
        if st.button("案件一覧に戻る"):
            st.session_state.page = "projects_list"
            st.rerun()
        return

    # 操作IDの保持（未確定時のみ新規発行。再試行時は同一IDを維持）
    if "project_idempotency_key" not in st.session_state or not st.session_state.project_idempotency_key:
        st.session_state.project_idempotency_key = str(uuid.uuid4())

    form_type = "admin" if current_user["username"] == "kanri" else "sales_wellness"

    col_d1, col_d2, col_d3 = st.columns([6, 2, 2])
    with col_d1:
        st.caption("※ ブラウザの再読み込みを行うと画面の入力内容がリセットされます。「下書き保存」をご活用ください。")
    with col_d2:
        if st.button("💾 下書きを保存", use_container_width=True, disabled=is_busy()):
            save_current_draft(current_user["id"], form_type)
            st.success("下書きを保存しました。")
    with col_d3:
        if st.button("📂 下書きを復元", use_container_width=True, disabled=is_busy()):
            draft = get_project_draft(current_user["id"], form_type)
            if draft:
                apply_draft_to_session(draft)
                st.success("下書きを復元しました。")
                st.rerun()
            else:
                st.info("保存された下書きはありません。")

    st.divider()

    st.markdown("#### 1. 基本情報")
    c1, c2 = st.columns(2)
    with c1:
        requester_name = st.text_input("ご担当者名（必須）", value=st.session_state.get("f_req_name", ""))
    with c2:
        target_launch = st.date_input("公開・使用開始予定日", value=date.today() + timedelta(days=14))

    c3, c4 = st.columns(2)
    with c3:
        desired_first_draft = st.date_input("初稿希望日", value=date.today() + timedelta(days=5))
    with c4:
        desired_delivery = st.date_input("最終納品希望日（必須）", value=date.today() + timedelta(days=10))

    st.divider()

    st.markdown("#### 2. 制作物の選択 & 依頼点数自動集計")
    st.caption("依頼する媒体と制作物を選び、必要点数を指定して「制作物リストに追加」してください。複数媒体・複数制作物を自由に追加でき、合計点数が自動集計されます。")

    if "media_items" not in st.session_state:
        st.session_state.media_items = []

    catalog = MEDIA_CATALOG_SALES_WELLNESS if form_type == "sales_wellness" else MEDIA_CATALOG_KANRI

    m_c1, m_c2, m_c3, m_c4 = st.columns([3, 4, 2, 2])
    with m_c1:
        selected_cat = st.selectbox("掲載媒体", list(catalog.keys()))
    with m_c2:
        selected_items = catalog[selected_cat]
        selected_item = st.selectbox("制作物・バナー名", selected_items)
    with m_c3:
        qty = st.number_input("依頼点数", min_value=1, max_value=99, value=1)
    with m_c4:
        st.write("")
        st.write("")
        add_btn = st.button("＋ リストに追加", type="secondary", use_container_width=True, disabled=is_busy())

    # 自由入力欄の表示制御
    is_custom_media = (selected_cat == "その他（自由に媒体名を変更可）")
    is_custom_item = (selected_item == "その他（自由入力）")

    custom_media_val = None
    custom_item_val = None

    if is_custom_media or is_custom_item:
        cf_c1, cf_c2 = st.columns(2)
        with cf_c1:
            if is_custom_media:
                custom_media_val = st.text_input("媒体名を指定（自由入力）", placeholder="例: 自社公式EC、TikTok、チラシ折り込み 等", key="custom_media_input")
        with cf_c2:
            if is_custom_item:
                custom_item_val = st.text_input("制作物名・仕様を指定（自由入力）", placeholder="例: A4三つ折りパンフレット、商品POP 等", key="custom_item_input")

    if add_btn:
        final_cat = selected_cat
        final_custom_media = None
        if is_custom_media:
            if custom_media_val and custom_media_val.strip():
                final_cat = custom_media_val.strip()
                final_custom_media = custom_media_val.strip()
            else:
                final_cat = "その他"

        final_item = selected_item
        final_custom_item = None
        if is_custom_item:
            if custom_item_val and custom_item_val.strip():
                final_item = custom_item_val.strip()
                final_custom_item = custom_item_val.strip()
            else:
                st.error("制作物の名称を入力してください（その他（自由入力）が選択されています）。")
                st.stop()

        st.session_state.media_items.append({
            "media_category": final_cat,
            "custom_media_name": final_custom_media,
            "item_name": final_item,
            "custom_item_name": final_custom_item,
            "quantity": int(qty)
        })
        st.rerun()

    total_quantity = sum(item["quantity"] for item in st.session_state.media_items)
    if st.session_state.media_items:
        st.markdown(f"**現在の依頼制作物リスト（合計: :blue[{total_quantity} 点]）**")
        for idx, item in enumerate(st.session_state.media_items):
            ic1, ic2, ic3 = st.columns([6, 2, 2])
            with ic1:
                st.write(f"・{item['media_category']} : **{item['item_name']}**")
            with ic2:
                st.write(f"{item['quantity']} 点")
            with ic3:
                if st.button("削除", key=f"del_item_{idx}", disabled=is_busy()):
                    st.session_state.media_items.pop(idx)
                    st.rerun()
    else:
        st.warning("⚠️ 制作物がまだ追加されていません。最低1点追加してください。")

    st.divider()

    st.markdown("#### 3. 依頼内容の詳細")
    if form_type == "sales_wellness":
        item_name = st.text_input("商品名・企画名（必須）", value=st.session_state.get("f_item_name", ""), placeholder="例: サプリメントX 新発売記念バナー")
        product_desc = st.text_area("商品の特徴・詳細", value=st.session_state.get("f_product_desc", ""))
        selling_point = st.text_input("一番アピールしたいこと（セールスポイント）", value=st.session_state.get("f_selling_point", ""))
        customer_benefit = st.text_input("顧客メリット", value=st.session_state.get("f_customer_benefit", ""))
        content_text = st.text_area("原稿・掲載文言（キャッチコピー等）", value=st.session_state.get("f_content_text", ""))
        required_elements = st.text_area("必須掲載要素（ロゴ、写真、注記等）", value=st.session_state.get("f_required_elements", ""))
        purpose_problem = ""
    else:
        item_name = st.text_input("案件名・目的（必須）", value=st.session_state.get("f_item_name", ""), placeholder="例: 2027年卒新卒採用 マイナビ掲載バナー")
        purpose_problem = st.text_area("目的・課題", value=st.session_state.get("f_purpose_problem", ""))
        content_text = st.text_area("原稿・文言", value=st.session_state.get("f_content_text", ""))
        required_elements = st.text_area("必須要素", value=st.session_state.get("f_required_elements", ""))
        product_desc = ""
        selling_point = ""
        customer_benefit = ""

    # 制作方針（単一選択・初期未選択・必須）
    current_policy = st.session_state.get("f_production_policy")
    default_policy_idx = PRODUCTION_POLICIES.index(current_policy) if current_policy in PRODUCTION_POLICIES else None

    production_policy = st.radio(
        "制作方針（必須）",
        options=PRODUCTION_POLICIES,
        captions=PRODUCTION_POLICY_DESCRIPTIONS,
        index=default_policy_idx,
        key="production_policy_radio"
    )

    design_taste = st.text_input("デザインの希望テイスト（任意）", value=st.session_state.get("f_design_taste", ""), placeholder="例: 明るく清潔感のある雰囲気、高級感")
    uploaded_files = st.file_uploader("参考素材・指示書ファイルの添付（任意・複数可）", accept_multiple_files=True)

    st.divider()

    col_s1, col_s2 = st.columns([7, 3])
    with col_s1:
        if st.button("キャンセル（一覧へ戻る）", disabled=is_busy()):
            st.session_state.page = "projects_list"
            st.rerun()
            
    with col_s2:
        submit_btn = st.button("🚀 制作依頼を送信する", type="primary", use_container_width=True, disabled=is_busy())

    if submit_btn:
        if not requester_name.strip():
            st.error("ご担当者名を入力してください。")
            return
        if not item_name.strip():
            st.error("商品名・案件名を入力してください。")
            return
        if not st.session_state.media_items:
            st.error("制作物を最低1点リストに追加してください。")
            return
        if not production_policy:
            st.error("制作方針を選択してください（必須）。")
            return

        # 添付ファイルの展開
        att_payload = []
        if uploaded_files:
            for uf in uploaded_files:
                att_payload.append({
                    "name": uf.name,
                    "bytes": uf.getvalue()
                })

        set_pending_action(
            "create_project",
            "🚀 制作依頼と添付ファイルを送信しています…",
            payload={
                "requester_name": requester_name,
                "item_name": item_name,
                "product_desc": product_desc,
                "selling_point": selling_point,
                "customer_benefit": customer_benefit,
                "content_text": content_text,
                "required_elements": required_elements,
                "purpose_problem": purpose_problem,
                "production_policy": production_policy,
                "design_taste": design_taste,
                "desired_first_draft": str(desired_first_draft),
                "target_launch": str(target_launch),
                "desired_delivery": str(desired_delivery),
                "total_quantity": total_quantity,
                "media_items": list(st.session_state.media_items),
                "attachments": att_payload
            }
        )

    # 保留アクションの実行（二段階実行によりボタンがdisabled状態で画面描画後に実行される）
    pending = get_pending_action()
    if pending.get("action") == "create_project":
        with st.spinner(pending.get("message", "🚀 制作依頼と添付ファイルを送信しています…")):
            execute_create_project_pending(current_user, pending["payload"], form_type)

def execute_create_project_pending(current_user, payload, form_type):
    idempotency_key = st.session_state.project_idempotency_key
    check_res = check_idempotency_status("projects", idempotency_key)

    # 1. 保存済みの場合 -> 成功画面へ復帰（添付ファイル未完了時の補完処理含む）
    if check_res["status"] == "saved":
        saved_id = check_res["data"]["id"]
        attachments = payload.get("attachments", [])
        if attachments:
            try:
                with get_db_cursor(commit=True) as cur:
                    cur.execute("SELECT original_name FROM project_attachments WHERE project_id = %s", (saved_id,))
                    existing_att_names = {r[0] for r in cur.fetchall()}
                    for att in attachments:
                        if att["name"] not in existing_att_names:
                            file_bytes = att["bytes"]
                            storage_path = upload_attachment_file(current_user, saved_id, file_bytes, att["name"], "briefs", cur=cur)
                            cur.execute("""
                                INSERT INTO project_attachments (project_id, original_name, stored_name, storage_path, file_size, uploaded_by)
                                VALUES (%s, %s, %s, %s, %s, %s)
                            """, (saved_id, att["name"], storage_path.split("/")[-1], storage_path, len(file_bytes), current_user["id"]))
            except Exception as att_err:
                st.warning(f"案件は保存されていますが、一部添付ファイルの保存に失敗しました: {att_err}")

        delete_project_draft(current_user["id"], form_type)
        st.session_state.project_idempotency_key = str(uuid.uuid4())
        clear_pending_action()
        set_flash_message("info", f"この依頼は既に正常に保存されています（案件番号: #{saved_id}）。")
        st.session_state.current_project_id = saved_id
        st.session_state.page = "project_detail"
        st.rerun()
        return

    # 2. 確認失敗の場合 -> 未登録と決めつけずに停止
    if check_res["status"] == "error":
        clear_pending_action()
        st.error(f"データベースの保存状態確認に失敗しました: {check_res['error']}")
        st.warning("※ データが既に保存されている可能性があるため、重複送信を防止しました。ネットワーク環境をご確認のうえ、再度送信ボタンを押してください。")
        return

    # 3. 未登録（status == 'not_found'）の場合 -> 新規登録を実行
    try:
        settings_map = {}
        with get_db_cursor(commit=False) as cur:
            cur.execute("SELECT key, value FROM system_settings")
            for row in cur.fetchall():
                try:
                    settings_map[row["key"]] = json.loads(row["value"])
                except Exception:
                    settings_map[row["key"]] = row["value"]

        deadlines = calculate_initial_deadlines(settings_map)

        with get_db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO projects (
                    title, purpose, appeal_point, required_elements, placement, size, quantity,
                    desired_delivery_date, status, waiting_for, requester_id,
                    first_reply_deadline, first_draft_deadline,
                    form_type, request_date, requester_person_name, desired_first_draft_date,
                    target_launch_date, item_name, product_description, selling_point, customer_benefit,
                    content_text, purpose_and_problem, design_taste, idempotency_key,
                    production_policy
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s,
                    %s, 'waiting_acceptance', 'admin', %s,
                    %s, %s,
                    %s, CURRENT_DATE, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s
                ) RETURNING id;
            """, (
                payload["item_name"], payload["purpose_problem"] or payload["item_name"], payload["selling_point"] or "特になし", payload["required_elements"] or "特になし",
                "指定媒体", "指定サイズ", payload["total_quantity"], payload["desired_delivery"], current_user["id"],
                deadlines['first_reply_deadline'], deadlines['first_draft_deadline'],
                form_type, payload["requester_name"], payload["desired_first_draft"], payload["target_launch"],
                payload["item_name"], payload["product_desc"], payload["selling_point"], payload["customer_benefit"],
                payload["content_text"], payload["purpose_problem"], payload["design_taste"], idempotency_key,
                payload.get("production_policy")
            ))
            new_project_id = cur.fetchone()[0]

            for item in payload["media_items"]:
                cur.execute("""
                    INSERT INTO project_media_items (project_id, media_category, custom_media_name, item_name, custom_item_name, quantity)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (new_project_id, item["media_category"], item.get("custom_media_name"), item["item_name"], item.get("custom_item_name"), item["quantity"]))

            attachments = payload.get("attachments", [])
            if attachments:
                for att in attachments:
                    file_bytes = att["bytes"]
                    storage_path = upload_attachment_file(current_user, new_project_id, file_bytes, att["name"], "briefs", cur=cur)
                    cur.execute("""
                        INSERT INTO project_attachments (project_id, original_name, stored_name, storage_path, file_size, uploaded_by)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (new_project_id, att["name"], storage_path.split("/")[-1], storage_path, len(file_bytes), current_user["id"]))

            cur.execute("""
                INSERT INTO notifications (user_id, project_id, title, message)
                VALUES (1, %s, '新しい制作依頼が届きました', %s)
            """, (new_project_id, f"{current_user['display_name']}より「{payload['item_name']}」の依頼が届きました。"))

        # 成功時
        delete_project_draft(current_user["id"], form_type)
        st.session_state.project_idempotency_key = str(uuid.uuid4())
        st.session_state.media_items = []
        if "f_production_policy" in st.session_state:
            del st.session_state["f_production_policy"]
        if "production_policy_radio" in st.session_state:
            del st.session_state["production_policy_radio"]
        clear_pending_action()
        set_flash_message("success", "制作依頼が正常に送信されました！")
        st.session_state.current_project_id = new_project_id
        st.session_state.page = "project_detail"
        st.rerun()

    except Exception as e:
        clear_pending_action()
        st.error(f"⚠️ 送信処理中にエラーが発生しました: {e}")
        st.info("※ 送信結果が不明な場合は、画面を更新せずそのまま再度「制作依頼を送信する」を押してください。操作IDによる二重送信防止と状態確認が自動で行われます。")

def save_current_draft(user_id: int, form_type: str):
    draft_data = {
        "media_items": st.session_state.get("media_items", []),
        "f_req_name": st.session_state.get("f_req_name", ""),
        "f_item_name": st.session_state.get("f_item_name", ""),
        "f_product_desc": st.session_state.get("f_product_desc", ""),
        "f_selling_point": st.session_state.get("f_selling_point", ""),
        "f_customer_benefit": st.session_state.get("f_customer_benefit", ""),
        "f_content_text": st.session_state.get("f_content_text", ""),
        "f_required_elements": st.session_state.get("f_required_elements", ""),
        "f_purpose_problem": st.session_state.get("f_purpose_problem", ""),
        "f_design_taste": st.session_state.get("f_design_taste", ""),
        "f_production_policy": st.session_state.get("production_policy_radio") or st.session_state.get("f_production_policy")
    }
    save_project_draft(user_id, form_type, draft_data)

def apply_draft_to_session(draft: dict):
    if "media_items" in draft:
        st.session_state.media_items = draft["media_items"]
    for k, v in draft.items():
        if k != "media_items":
            st.session_state[k] = v
    if "f_production_policy" in draft:
        st.session_state["f_production_policy"] = draft["f_production_policy"]
        if "production_policy_radio" in st.session_state:
            del st.session_state["production_policy_radio"]
        if k != "media_items":
            st.session_state[k] = v
