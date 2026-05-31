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
