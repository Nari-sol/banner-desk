import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")

def format_datetime_jst(dt, fmt='%Y-%m-%d %H:%M') -> str:
    """
    日時データを Asia/Tokyo (JST) タイムゾーンに変換してフォーマットする。
    
    - dt が None の場合は空文字を返す。
    - PostgreSQL の timestamptz (tz-aware な UTC datetime) は astimezone(JST) で正しく変換。
    - tz-naive の場合は UTC として解釈してから JST に変換。
    - 単純な 9時間加算ではなく、標準ライブラリ zoneinfo による正確なタイムゾーン計算を行う。
    """
    if dt is None:
        return ""
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except Exception:
            return dt

    if hasattr(dt, "tzinfo"):
        if dt.tzinfo is None:
            # tz-naive の場合、UTC とみなして JST へ変換
            dt = dt.replace(tzinfo=timezone.utc).astimezone(JST)
        else:
            # tz-aware の場合、JST へ変換
            dt = dt.astimezone(JST)
        return dt.strftime(fmt)

    return str(dt)
