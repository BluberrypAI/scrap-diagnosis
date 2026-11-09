import itertools

import pytest

from app.rules.evaluator import TV, kleene_all, kleene_any, kleene_not

T, F, U = TV.TRUE, TV.FALSE, TV.UNKNOWN

AND = {(T, T): T, (T, F): F, (T, U): U, (F, F): F, (F, U): F, (U, U): U}
OR = {(T, T): T, (T, F): T, (T, U): T, (F, F): F, (F, U): U, (U, U): U}


@pytest.mark.parametrize("a, b", list(itertools.product([T, F, U], repeat=2)))
def test_binary_truth_tables(a, b):
    key = (a, b) if (a, b) in AND else (b, a)
    assert kleene_all([a, b]) == AND[key]
    assert kleene_any([a, b]) == OR[key]


def test_not():
    assert kleene_not(T) == F
    assert kleene_not(F) == T
    assert kleene_not(U) == U


@pytest.mark.parametrize("vals", list(itertools.product([T, F, U], repeat=3)))
def test_de_morgan(vals):
    vals = list(vals)
    assert kleene_not(kleene_all(vals)) == kleene_any([kleene_not(v) for v in vals])
