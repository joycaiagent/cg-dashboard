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
