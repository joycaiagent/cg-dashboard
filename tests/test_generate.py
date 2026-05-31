import json
import generate


def test_build_month_progress_html_shows_percentage_and_values():
    html = generate.build_month_progress_html(250000, 500000)
    assert '$250,000' in html
    assert '$500,000' in html
    assert '50%' in html
    assert 'width:50%' in html


def test_build_month_progress_html_caps_fill_at_100_when_over_goal():
    html = generate.build_month_progress_html(650000, 500000)
    assert '130%' in html
    assert 'width:100%' in html


def test_get_monthly_invoice_progress_uses_prior_year_same_month_goal():
    calls = []

    def fake_fetcher(url):
        calls.append(url)
        if '2026-05-01' in url:
            return [{'Amount': 100000}]
        if '2025-01-01' in url and '2025-12-31' in url:
            return [{'Amount': 2000000}]
        raise AssertionError(f'unexpected url: {url}')

    result = generate.get_monthly_invoice_progress(
        today=generate.datetime.date(2026, 5, 30),
        fetcher=fake_fetcher,
    )

    assert result['invoiced'] == 100000
    assert round(result['goal']) == 191667
    assert result['pct'] == 52
    assert len(calls) == 2


def test_get_ytd_invoice_progress_uses_prorated_annual_goal():
    calls = []

    def fake_fetcher(url):
        calls.append(url)
        if '2026-01-01' in url and '2026-05-30' in url:
            return [{'Amount': 1200000}]
        if '2025-01-01' in url and '2025-12-31' in url:
            return [{'Amount': 2000000}]
        raise AssertionError(f'unexpected url: {url}')

    result = generate.get_ytd_invoice_progress(
        today=generate.datetime.date(2026, 5, 30),
        fetcher=fake_fetcher,
    )

    assert result['invoiced'] == 1200000
    assert round(result['goal']) == 945205
    assert result['pct'] == 127
    assert len(calls) == 2


def test_get_ops_health_reads_all_weekly_tickets_with_pagination():
    calls = []

    class FakeDate(generate.datetime.date):
        @classmethod
        def today(cls):
            return cls(2026, 5, 27)

    def make_ticket(status, branch='Anaheim', revenue=100):
        return {'WorkTicketStatusName': status, 'BranchName': branch, 'Revenue': revenue}

    def fake_fetcher(url):
        calls.append(url)
        if 'ClientComplaints' in url:
            return []
        if '$skip=0' in url:
            return [make_ticket('Complete')] * 1000
        if '$skip=1000' in url:
            return [make_ticket('Open')]
        raise AssertionError(f'unexpected url: {url}')

    original_date = generate.datetime.date
    original_aspire_api = generate.aspire_api
    generate.datetime.date = FakeDate
    generate.aspire_api = fake_fetcher
    try:
        result = generate.get_ops_health()
    finally:
        generate.datetime.date = original_date
        generate.aspire_api = original_aspire_api

    assert result['total'] == 1001
    assert result['complete'] == 1000
    assert result['open'] == 1
    assert result['rate'] == 100
    assert len([c for c in calls if 'WorkTickets' in c]) == 2


def test_get_safety_returns_summary_and_manager_from_scanner_output():
    payload = [{
        'subject': 'FW: Margarito Martinez Sprained Ankle 5/20/26',
        'from': 'josecontreras@cglandscape.net',
        'date': '2026-05-20',
        'description': 'Employee: Margarito Martinez sprained his ankle while working.',
        'emailType': 'original',
        'manager': 'Antonio Taylor',
        'summary': 'Employee: Margarito Martinez sprained his ankle while working.'
    }]

    class FakeRunResult:
        def __init__(self, stdout):
            self.stdout = stdout

    original_run = generate.subprocess.run
    generate.subprocess.run = lambda *args, **kwargs: FakeRunResult(json.dumps(payload))
    try:
        items = generate.get_safety()
    finally:
        generate.subprocess.run = original_run

    assert len(items) == 1
    assert items[0]['manager'] == 'Antonio Taylor'
    assert 'sprained his ankle' in items[0]['summary']
    assert items[0]['emailType'] == 'original'


def test_build_html_shows_safety_summary_and_manager():
    html = generate.build_html(
        events=[],
        stats={
            'health': 'yellow', 'health_label': 'Watch',
            'complete': 1, 'canceled': 0, 'open': 0, 'scheduled': 1,
            'total': 1, 'rate': 100, 'sched_revenue': 0, 'total_revenue': 0,
            'complaints': [], 'by_branch': {}, 'week_start': '2026-05-25', 'week_end': '2026-05-31'
        },
        safety_incidents=[{
            'id': 's1',
            'subject': 'FW: Margarito Martinez Sprained Ankle 5/20/26',
            'from': 'josecontreras@cglandscape.net',
            'date': '2026-05-20',
            'description': 'Employee: Margarito Martinez sprained his ankle while working.',
            'summary': 'Employee: Margarito Martinez sprained his ankle while working.',
            'manager': 'Antonio Taylor',
            'team_member': 'Margarito Martinez',
            'emailType': 'original',
            'link': 'https://example.com/item'
        }],
    )

    assert 'Employee: Margarito Martinez sprained his ankle while working.' in html
    assert '👔 Manager: Antonio Taylor' in html
    assert '👷 Team member: Margarito Martinez' in html
    assert '📩 Original' in html
    assert 'data-manager="Antonio Taylor"' in html
    assert '🩼 Modified Duty' in html
    assert '✅ Close Incident' in html
    assert '/api/incident/reviews' in html


def test_get_safety_auto_detects_modified_duty_from_scanner_text():
    payload = [{
        'subject': 'FW: Margarito Martinez Sprained Ankle 5/20/26',
        'from': 'josecontreras@cglandscape.net',
        'date': '2026-05-20',
        'description': 'Employee Margarito Martinez is on modified duty. No walking more than 15 minutes.',
        'emailType': 'forwarded',
        'manager': 'Juan Carlos Garcia',
        'summary': 'Employee Margarito Martinez is on modified duty. No walking more than 15 minutes.'
    }]

    class FakeRunResult:
        def __init__(self, stdout):
            self.stdout = stdout

    original_run = generate.subprocess.run
    generate.subprocess.run = lambda *args, **kwargs: FakeRunResult(json.dumps(payload))
    try:
        items = generate.get_safety()
    finally:
        generate.subprocess.run = original_run

    assert len(items) == 1
    assert items[0]['status'] == 'modified_duty'
    assert 'modified duty' in items[0]['summary'].lower()
    assert items[0]['modified_duty']
    assert items[0]['manager'] == 'Juan Carlos Garcia'


def test_get_safety_dedupes_against_roster_and_active_history(tmp_path):
    roster = tmp_path / 'team-roster.md'
    roster.write_text(
        '# Team\n\n'
        '|| Name | Email ||\n'
        '|| Margarito Martinez | margaritomartinez@cglandscape.net ||\n'
        '|| Juan Carlos Garcia | juancgarcia@cglandscape.net ||\n'
    )
    history = tmp_path / 'reviewed-safety.json'
    history.write_text(json.dumps([
        {
            'id': 'inc-old',
            'status': 'open',
            'subject': 'Margarito Martinez Sprained Ankle',
            'summary': 'Employee Margarito Martinez is on modified duty.',
            'manager': 'Juan Carlos Garcia'
        }
    ]))
    payload = [
        {
            'subject': 'FW: Margarito Martinez Sprained Ankle 5/20/26',
            'from': 'josecontreras@cglandscape.net',
            'date': '2026-05-20',
            'description': 'Employee Margarito Martinez is on modified duty. No walking more than 15 minutes.',
            'emailType': 'forwarded',
            'manager': 'Juan Carlos Garcia',
            'summary': 'Employee Margarito Martinez is on modified duty. No walking more than 15 minutes.'
        },
        {
            'subject': 'FW: Margarito Martinez Follow Up 5/21/26',
            'from': 'josecontreras@cglandscape.net',
            'date': '2026-05-21',
            'description': 'Margarito Martinez is still restricted from lifting more than 10 pounds.',
            'emailType': 'forwarded',
            'manager': 'Juan Carlos Garcia',
            'summary': 'Margarito Martinez is still restricted from lifting more than 10 pounds.'
        },
        {
            'subject': 'FW: Juan Carlos Garcia Sprained Wrist 5/20/26',
            'from': 'josecontreras@cglandscape.net',
            'date': '2026-05-20',
            'description': 'Juan Carlos Garcia sprained his wrist on site.',
            'emailType': 'forwarded',
            'manager': 'Antonio Taylor',
            'summary': 'Juan Carlos Garcia sprained his wrist on site.'
        }
    ]

    class FakeRunResult:
        def __init__(self, stdout):
            self.stdout = stdout

    original_run = generate.subprocess.run
    generate.subprocess.run = lambda *args, **kwargs: FakeRunResult(json.dumps(payload))
    try:
        items = generate.get_safety(team_roster_path=roster, review_history_path=history)
    finally:
        generate.subprocess.run = original_run

    assert len(items) == 1
    assert items[0]['subject'] == 'FW: Juan Carlos Garcia Sprained Wrist 5/20/26'
    assert items[0]['manager'] == 'Antonio Taylor'


def test_get_safety_dedupes_repeat_team_member_in_same_scan(tmp_path):
    roster = tmp_path / 'team-roster.md'
    roster.write_text(
        '# Team\n\n'
        '|| Name | Email ||\n'
        '|| Margarito Martinez | margaritomartinez@cglandscape.net ||\n'
        '|| Juan Carlos Garcia | juancgarcia@cglandscape.net ||\n'
    )
    history = tmp_path / 'reviewed-safety.json'
    history.write_text('[]')
    payload = [
        {
            'subject': 'FW: Margarito Martinez Sprained Ankle 5/20/26',
            'from': 'josecontreras@cglandscape.net',
            'date': '2026-05-20',
            'description': 'Employee Margarito Martinez is on modified duty. No walking more than 15 minutes.',
            'emailType': 'forwarded',
            'manager': 'Juan Carlos Garcia',
            'summary': 'Employee Margarito Martinez is on modified duty. No walking more than 15 minutes.'
        },
        {
            'subject': 'FW: Margarito Martinez Follow Up 5/21/26',
            'from': 'josecontreras@cglandscape.net',
            'date': '2026-05-21',
            'description': 'Margarito Martinez is still restricted from lifting more than 10 pounds.',
            'emailType': 'forwarded',
            'manager': 'Juan Carlos Garcia',
            'summary': 'Margarito Martinez is still restricted from lifting more than 10 pounds.'
        },
        {
            'subject': 'FW: Juan Carlos Garcia Sprained Wrist 5/20/26',
            'from': 'josecontreras@cglandscape.net',
            'date': '2026-05-20',
            'description': 'Juan Carlos Garcia sprained his wrist on site.',
            'emailType': 'forwarded',
            'manager': 'Antonio Taylor',
            'summary': 'Juan Carlos Garcia sprained his wrist on site.'
        }
    ]

    class FakeRunResult:
        def __init__(self, stdout):
            self.stdout = stdout

    original_run = generate.subprocess.run
    generate.subprocess.run = lambda *args, **kwargs: FakeRunResult(json.dumps(payload))
    try:
        items = generate.get_safety(team_roster_path=roster, review_history_path=history)
    finally:
        generate.subprocess.run = original_run

    assert len(items) == 2
    assert [item['subject'] for item in items] == [
        'FW: Margarito Martinez Sprained Ankle 5/20/26',
        'FW: Juan Carlos Garcia Sprained Wrist 5/20/26',
    ]
