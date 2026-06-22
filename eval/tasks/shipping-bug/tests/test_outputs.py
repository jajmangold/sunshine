from shipping.pricing import total_cost


def test_gold_gets_ten_percent_off():
    assert total_cost([50.0, 50.0], "gold") == 90.0


def test_silver_gets_five_percent_off():
    assert total_cost([100.0], "silver") == 95.0


def test_bronze_pays_full():
    assert total_cost([100.0], "bronze") == 100.0
