"""Full route audit — tests every meaningful URL in the app."""
import sys, traceback
sys.path.insert(0, '.')
from app import create_app
from models import Company, FollowUp

app = create_app()
app.config['TESTING'] = True
app.config['PROPAGATE_EXCEPTIONS'] = False
client = app.test_client()

passed = 0
failed = 0

def check(method, url, data=None, expected=None):
    global passed, failed
    expected = expected or [200, 201, 302]
    try:
        if method == 'POST':
            r = client.post(url, data=data or {}, follow_redirects=False,
                            content_type='application/x-www-form-urlencoded')
        elif method == 'PATCH':
            import json
            r = client.patch(url, data=json.dumps(data or {}),
                             content_type='application/json')
        else:
            r = client.get(url)
        ok = r.status_code in expected
        icon = 'OK' if ok else 'FAIL'
        print(f'[{icon}] {method} {url} -> {r.status_code}')
        if not ok:
            failed += 1
            body = r.data.decode('utf-8', errors='replace')
            # Try to find the Flask/Werkzeug error line
            import re
            m = re.search(r'TypeError|ValueError|AttributeError|NameError|KeyError|UndefinedError.*', body)
            if m:
                print(f'       ERROR: {m.group(0)[:120]}')
            else:
                print(f'       BODY[:200]: {body[:200]}')
        else:
            passed += 1
    except Exception as e:
        failed += 1
        print(f'[EXC] {method} {url} -> {e}')

with app.app_context():
    c = Company.query.first()
    cid = c.id if c else 1

    # Core pages
    check('GET', '/')
    check('GET', '/companies/')
    check('GET', f'/companies/{cid}')
    check('GET', '/linkedin/')
    check('GET', '/linkedin/auth')
    check('GET', '/settings')
    check('GET', '/api/stats')
    check('GET', '/api/reminders')
    check('GET', f'/api/companies/{cid}/timeline')

    # Company list filters
    check('GET', '/companies/?q=tech')
    check('GET', '/companies/?status=emailed')
    check('GET', '/companies/?sort=name_asc')
    check('GET', '/companies/?page=2')

    # Export
    check('GET', '/companies/export/csv')
    check('GET', '/companies/export/json')

    # Upload page
    check('GET', '/companies/upload')

    # Follow-up PATCH
    fu = FollowUp.query.first()
    if fu:
        check('PATCH', f'/companies/follow-ups/{fu.id}', {'status': 'done'})

    # Log email (JSON)
    import json
    r = client.post(f'/companies/{cid}/log-email',
                    data=json.dumps({'recipient_email': 'test@example.com', 'subject': 'Test'}),
                    content_type='application/json')
    icon = 'OK' if r.status_code in [200,201,302] else 'FAIL'
    print(f'[{icon}] POST /companies/{cid}/log-email -> {r.status_code}')
    if r.status_code not in [200,201,302]:
        failed += 1
    else:
        passed += 1

    # Schedule follow-up
    check('POST', f'/companies/{cid}/follow-up',
          {'due_on': '2026-07-20', 'notes': 'Test followup'})

    # Settings POST
    check('POST', '/settings', {
        'tab': 'reminders',
        'follow_up_cadence_days': '5',
        'quiet_hours_start': '21:00',
        'quiet_hours_end': '08:00',
        'daily_digest_time': '08:00',
    })

    # LinkedIn revoke (just check it doesn't crash)
    check('POST', '/linkedin/revoke', {}, expected=[200, 302])

    # Scraper
    check('POST', f'/scrape/jobs/{cid}', {}, expected=[200, 202])

print()
print(f'Results: {passed} passed, {failed} failed')
