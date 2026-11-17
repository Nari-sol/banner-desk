import streamlit as st

def render_footer():
    """
    共通フッターの描画
    表示文言: 「アプリ改修・不具合のご相談　販売促進課 成田」
    仕様:
    ・ページ最下部の右寄せ
    ・文字サイズ 11〜12px、控えめなグレー (#888888)
    ・太字、背景色、枠線、©マークなし
    ・本文の後に配置し、スクロール末尾に表示
    ・本文や操作ボタンと重ならない余白を確保
    """
    footer_html = """
    <div style="
        margin-top: 60px;
        padding-top: 20px;
        padding-bottom: 24px;
        text-align: right;
        font-size: 11px;
        color: #888888;
        font-weight: normal;
        background: transparent;
        border: none;
        line-height: 1.5;
        word-break: break-all;
    ">
        アプリ改修・不具合のご相談　販売促進課 成田
    </div>
    """
    st.markdown(footer_html, unsafe_allow_html=True)
