import json
from pathlib import Path

import server


def test_record_safety_review_upserts_backend_tracker(tmp_path):
    tracker = tmp_path / 'reviewed-safety.json'

    first = server.record_safety_review(
        {
            'id': 'inc-123',
            'subject': 'FW: Broken Window - The Commons',
            'from': 'josecontreras@cglandscape.net',
            'date': '2026-05-19',
            'summary': 'Worker struck a window with a weed eater.',
            'manager': 'Juan Hurbano Martinez',
            'emailType': 'forwarded',
        },
        tracker_path=tracker,
        source='dashboard-review',
        reviewed_at='2026-05-20T12:34:56Z',
    )

    second = server.record_safety_review(
        {
            'id': 'inc-123',
            'subject': 'FW: Broken Window - The Commons',
            'summary': 'Updated summary should replace the old one.',
        },
        tracker_path=tracker,
        source='dashboard-review',
        reviewed_at='2026-05-21T01:02:03Z',
    )

    assert first['id'] == 'inc-123'
    assert first['source'] == 'dashboard-review'
    assert first['reviewed_at'] == '2026-05-20T12:34:56Z'
    assert second['reviewed_at'] == '2026-05-21T01:02:03Z'
    assert second['summary'] == 'Updated summary should replace the old one.'

    data = json.loads(tracker.read_text())
    assert len(data) == 1
    assert data[0]['id'] == 'inc-123'
    assert data[0]['summary'] == 'Updated summary should replace the old one.'
    assert data[0]['manager'] == 'Juan Hurbano Martinez'


def test_load_reviewed_safety_returns_empty_list_when_tracker_missing(tmp_path):
    tracker = tmp_path / 'reviewed-safety.json'

    assert server.load_reviewed_safety(tracker_path=tracker) == []
