import streamlit as st
import streamlit.components.v1 as components

def render_desktop_notification_prompt():
    """
    デスクトップ通知の許可案内コンポーネント (iframe経由)
    「通知を有効にする」ボタンからブラウザのNotification許可をリクエストする。
    """
    html_code = """
    <div style="font-family: sans-serif; background-color: #f8f9fa; border: 1px solid #e9ecef; border-radius: 8px; padding: 12px 16px; margin-bottom: 16px;">
        <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
            <div style="font-size: 13px; color: #495057;">
                🔔 <strong>パソコンへの通知</strong>: コメントや進捗の変更を、画面外にいても通知でお知らせします。
            </div>
            <div>
                <button id="enable-btn" onclick="requestNotificationPermission()" style="
                    background-color: #0d6efd; color: white; border: none; border-radius: 4px; padding: 6px 12px; font-size: 12px; cursor: pointer; font-weight: bold;
                ">通知を有効にする</button>
                <button id="test-btn" onclick="sendTestNotification()" style="
                    background-color: #6c757d; color: white; border: none; border-radius: 4px; padding: 6px 12px; font-size: 12px; cursor: pointer; margin-left: 6px; display: none;
                ">テスト通知</button>
            </div>
        </div>
        <div id="status-msg" style="font-size: 11px; color: #6c757d; margin-top: 6px;"></div>
    </div>

    <script>
    function updateStatus() {
        const msg = document.getElementById('status-msg');
        const enableBtn = document.getElementById('enable-btn');
        const testBtn = document.getElementById('test-btn');
        
        if (!("Notification" in window)) {
            msg.innerText = "このブラウザはデスクトップ通知に対応していません。";
            enableBtn.style.display = "none";
            return;
        }
        
        if (Notification.permission === "granted") {
            msg.innerText = "✅ 通知は許可されています（デスクトップ通知が有効です）。";
            msg.style.color = "#198754";
            enableBtn.style.display = "none";
            testBtn.style.display = "inline-block";
        } else if (Notification.permission === "denied") {
            msg.innerText = "⚠️ 通知がブラウザでブロックされています。ブラウザのアドレスバー左側の鍵アイコン等から許可してください。";
            msg.style.color = "#dc3545";
            enableBtn.style.display = "none";
        } else {
            msg.innerText = "※「通知を有効にする」をクリック後、ブラウザに表示される画面で『許可』を選んでください。";
            enableBtn.style.display = "inline-block";
            testBtn.style.display = "none";
        }
    }

    function requestNotificationPermission() {
        if (!("Notification" in window)) return;
        Notification.requestPermission().then(function (permission) {
            updateStatus();
            if (permission === "granted") {
                new Notification("バナー制作デスク", {
                    body: "デスクトップ通知が有効になりました！",
                    icon: "https://cdn-icons-png.flaticon.com/512/1827/1827349.png"
                });
            }
        });
    }

    function sendTestNotification() {
        if (Notification.permission === "granted") {
            new Notification("バナー制作デスク", {
                body: "テスト通知: 案件の更新やコメントをここでお知らせします。",
                icon: "https://cdn-icons-png.flaticon.com/512/1827/1827349.png"
            });
        }
    }

    updateStatus();
    </script>
    """
    components.html(html_code, height=95)
