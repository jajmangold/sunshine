from flaky.tags import priority_tag
def test_priority():
    assert priority_tag({"urgent", "normal"}) == "urgent"
