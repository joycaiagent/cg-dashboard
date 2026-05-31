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
