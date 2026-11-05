"""Step 5a: the grounding check on its own. No API key, no database."""

from agent import grounding


def _sql(preview, error=None):
    return {"type": "sql", "preview": preview, "error": error}


def _answer(value=None, text="", status="answered"):
    return {"status": status, "numeric_value": value, "answer": text}


ROWS = [_sql("revenue,orders\n671425.37,1234\n")]


def test_exact_number_is_grounded():
    assert grounding.check(_answer(671425.37, "Revenue was $671,425.37."), "q", ROWS) == []


def test_rounded_number_is_grounded_at_the_stated_precision():
    assert grounding.check(_answer(671425.4, "About 671,425.4"), "q", ROWS) == []
    assert grounding.check(_answer(671425, "671,425"), "q", ROWS) == []


def test_invented_number_is_flagged():
    problems = grounding.check(_answer(1234567.89, "Revenue was $1,234,567.89."), "q", ROWS)
    assert any("numeric_value" in p for p in problems) and any("1,234,567.89" in p for p in problems)


def test_no_query_is_flagged_even_if_the_number_looks_plausible():
    assert "without a successful query" in grounding.check(_answer(5.0, "5"), "q", [])[0]
    failed = [_sql("", error="Binder Error")]
    assert "without a successful query" in grounding.check(_answer(5.0, "5"), "q", failed)[0]


def test_numbers_only_in_a_failed_query_do_not_count():
    steps = [_sql("x\n999.5\n", error="boom"), _sql("x\n1\n")]
    assert grounding.check(_answer(999.5, ""), "q", steps)


def test_only_answered_status_is_checked():
    assert grounding.check(_answer(1234567.89, "x", status="cannot_answer"), "q", []) == []
    assert grounding.check(_answer(None, "which month?", status="needs_clarification"), "q", []) == []


def test_percent_and_simple_derivations_are_grounded():
    steps = [_sql("q,rev\nq2,200.0\nq3,100.0\n")]
    assert grounding.check(_answer(-50.0, "Down 50.0%"), "q", steps) == []  # (100-200)/200*100
    assert grounding.check(_answer(100.0, "A drop of 100.0"), "q", steps) == []  # difference
    ratio = [_sql("share\n0.2574\n")]
    assert grounding.check(_answer(25.74, "25.74%"), "q", ratio) == []  # ratio shown as a percent


def test_adjacent_csv_values_are_not_merged_into_one_number():
    steps = [_sql("a,b\n100,200\n")]
    assert grounding.check(_answer(100.0, "100"), "q", steps) == []
    assert grounding.check(_answer(100200.0, "100,200"), "q", steps)  # would pass if "100,200" were read as one number


def test_small_integers_years_scaled_and_question_numbers_are_not_checked():
    text = "In 2025, the top 5 products made $1.2M across 12 stores; for order 987654 see below."
    assert grounding.check(_answer(None, text), "Show order 987654", ROWS) == []


def test_a_large_unqueried_integer_in_the_text_is_flagged():
    assert grounding.check(_answer(None, "We had 48,213 customers."), "q", ROWS)


def test_digits_inside_ids_are_checked_as_numbers():
    assert grounding.check(_answer(None, "Order ord_55512 was largest."), "q", ROWS)
    assert grounding.check(_answer(None, "Order ord_1234 was largest."), "q", ROWS) == []
