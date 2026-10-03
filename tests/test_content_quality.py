from app.generator import build_content_pack


def test_all_services_and_promotions_are_used_and_calendar_maps_to_content():
    pack = build_content_pack({'business_name':'Oak Home Care','industry':'home services',
        'services':['Window cleaning','Gutter cleaning','Pressure washing'],
        'promotions':['Spring window package','Annual maintenance plan'],
        'tone':'friendly','website':'https://example.com','instructions':'No hashtags. No discounts.'}, 'ord_quality')
    for service in ['Window cleaning','Gutter cleaning','Pressure washing']:
        assert service in pack.split('## 10 Social Posts')[1].split('## 10 Captions')[0]
    assert '#' not in pack.split('## 10 Captions')[1].split('## 5 Promotional Ideas')[0]
    assert 'without discounts' in pack
    assert 'Day 30:' in pack and 'use GBP Post' in pack
    assert 'https://example.com' in pack
    assert 'No website research' in pack


def test_tone_changes_body_and_instructions_are_visible_without_false_compliance_claim():
    intake = {'business_name':'Acme','services':['Consulting'],'instructions':'Never mention a guarantee.'}
    friendly = build_content_pack({**intake,'tone':'friendly'}, 'ord_1')
    professional = build_content_pack({**intake,'tone':'professional'}, 'ord_1')
    assert 'Let’s make this easier.' in friendly
    assert 'A useful planning step:' in professional
    assert 'Never mention a guarantee.' in friendly
    assert 'Free-form instructions are retained' in friendly
