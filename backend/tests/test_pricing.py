from app.pricing import calc_total


def test_no_coupon():
    _, total = calc_total([("1-A-1", "S"), ("3-A-10", "A")], 0)
    assert total == 1500


def test_coupon_per_ticket():
    _, total = calc_total([("1-A-1", "S"), ("1-A-2", "S")], 2)
    assert total == 1000


def test_coupon_makes_a_seat_free():
    lines, total = calc_total([("3-A-10", "A"), ("WC-1", "W")], 2)
    assert total == 0
    assert all(line.subtotal == 0 for line in lines)


def test_partial_coupon_applies_to_expensive_first():
    lines, total = calc_total([("3-A-10", "A"), ("1-A-1", "S")], 1)
    assert lines[0].category == "S" and lines[0].discount == 500
    assert total == 1000
