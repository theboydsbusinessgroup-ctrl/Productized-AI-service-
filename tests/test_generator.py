from app.generator import build_content_pack

def test_generator_produces_complete_pack():
    text=build_content_pack({'business_name':'Acme','industry':'Home Services','target_customer':'homeowners','location':'Houston','services':['Repairs'],'platforms':['Instagram']},'ord_test')
    assert '# 30-Day Social Content Pack — Acme' in text
    assert '## 10 Hooks' in text
    assert '## 10 Social Posts' in text
    assert '## 10 Captions' in text
    assert '## 5 Promotional Ideas' in text
    assert '## 5 Google Business Profile Posts' in text
    assert 'Day 30:' in text
    assert 'Houston' in text
