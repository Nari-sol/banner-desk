import streamlit as st
import time

def is_busy() -> bool:
    """現在、保留中または実行中のアクションがあるかを判定"""
    return bool(st.session_state.get("pending_action"))

def get_pending_action() -> dict:
    """現在のアクション情報を取得"""
    return st.session_state.get("pending_action") or {}

def set_pending_action(action: str, message: str, payload: dict = None):
    """
    アクションを予約し、即時再描画を行う。
    次の再描画時にすべてのボタンが無効化（disabled）され、処理中スピナーが表示された状態で実行される。
    """
    if is_busy():
        # 既に別のアクションが進行中の場合は重複予約を防止
        return
    st.session_state.pending_action = {
        "action": action,
        "message": message,
        "payload": payload or {},
        "created_at": time.time()
    }
    st.rerun()

def clear_pending_action():
    """保留中アクションを解除（ロック解除）"""
    st.session_state.pending_action = None

def set_flash_message(level: str, message: str):
    """
    再描画後に表示するフラッシュメッセージを保存
    level: 'success', 'error', 'warning', 'info'
    """
    if "flash_messages" not in st.session_state:
        st.session_state.flash_messages = []
    st.session_state.flash_messages.append({"level": level, "message": message})

def render_flash_messages():
    """保存されたフラッシュメッセージを描画し、クリアする"""
    messages = st.session_state.get("flash_messages", [])
    if messages:
        for msg in messages:
            lvl = msg.get("level", "info")
            txt = msg.get("message", "")
            if lvl == "success":
                st.success(txt)
            elif lvl == "error":
                st.error(txt)
            elif lvl == "warning":
                st.warning(txt)
            else:
                st.info(txt)
        st.session_state.flash_messages = []

def render_processing_banner():
    """
    処理中フラグが立っている場合、画面上部に目立つ処理中案内を表示。
    万が一30秒以上経過している場合は自動でロック解除し操作不能を防ぐ。
    """
    if is_busy():
        action = get_pending_action()
        msg = action.get("message", "処理を実行しています…")
        created_at = action.get("created_at", time.time())
        
        # 30秒セーフティガード（処理スタック防止）
        if time.time() - created_at > 30:
            clear_pending_action()
            st.error("⚠️ 処理がタイムアウトしたため、操作ロックを自動解除しました。もう一度お試しください。")
            return
            
        st.info(f"⏳ **{msg}**\n\n処理中は二重送信防止のため操作が制限されています。そのまま少々お待ちください…")
