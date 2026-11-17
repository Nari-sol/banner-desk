import json
from datetime import datetime, date, timedelta, time

def is_business_day(target_date: date, business_hours: dict, holidays: list) -> bool:
    date_str = target_date.strftime('%Y-%m-%d')
    if date_str in holidays:
        return False
    work_days = business_hours.get('work_days', [1, 2, 3, 4, 5])
    return target_date.isoweekday() in work_days

def next_business_day(start_date: date, business_hours: dict, holidays: list) -> date:
    cur = start_date + timedelta(days=1)
    while not is_business_day(cur, business_hours, holidays):
        cur += timedelta(days=1)
    return cur

def add_business_days(start_date: date, num_days: int, business_hours: dict, holidays: list) -> date:
    cur = start_date
    added = 0
    while added < num_days:
        cur += timedelta(days=1)
        if is_business_day(cur, business_hours, holidays):
            added += 1
    return cur

def calculate_initial_deadlines(settings_map: dict, reception_dt: datetime = None) -> dict:
    """
    受付期限・一次返信期限の算出
    仕様:
    ・12:00ちょうどを含む「12時まで」の受付: 当日 16:00
    ・「12時を過ぎた場合」または休業日受付: 翌営業日 16:00
    ・初稿目安: 3営業日後（18:00）
    """
    if reception_dt is None:
        reception_dt = datetime.now()

    bh = settings_map.get('business_hours', {
        'work_days': [1, 2, 3, 4, 5],
        'start_time': '09:00',
        'end_time': '18:00',
        'reception_cutoff': '12:00'
    })
    holidays = settings_map.get('holidays', [])
    rules = settings_map.get('deadline_rules', {
        'first_draft_business_days': 3,
        'revision_business_days': 2
    })

    cutoff_hour, cutoff_min = map(int, bh.get('reception_cutoff', '12:00').split(':'))
    cutoff_t = time(cutoff_hour, cutoff_min)
    base_date = reception_dt.date()

    # 12:00ちょうどは「12時まで」に含める（> cutoff_t で判定）
    if not is_business_day(base_date, bh, holidays) or reception_dt.time() > cutoff_t:
        target_reply_date = next_business_day(base_date, bh, holidays)
    else:
        target_reply_date = base_date

    # 一次返信期限: 対象日の16:00
    first_reply_deadline = datetime.combine(target_reply_date, time(16, 0))

    # 初稿目安: 営業日加算（18:00）
    first_draft_days = rules.get('first_draft_business_days', 3)
    draft_date = add_business_days(target_reply_date, first_draft_days, bh, holidays)
    first_draft_deadline = datetime.combine(draft_date, time(18, 0))

    return {
        'first_reply_deadline': first_reply_deadline.strftime('%Y-%m-%d %H:%M:%S'),
        'first_draft_deadline': first_draft_deadline.strftime('%Y-%m-%d %H:%M:%S')
    }
