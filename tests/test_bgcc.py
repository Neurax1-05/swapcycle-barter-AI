"""Unit tests for the Bounded Greedy Cycle Cover (BGCC) engine."""

import random

import networkx as nx
import pytest

import bgcc_prototype as bp
from cycle_arbitration import enumerate_cycles


def edges_of(cycle):
    return list(zip(cycle, cycle[1:] + cycle[:1]))


@pytest.mark.parametrize("seed", range(15))
@pytest.mark.parametrize("max_len", [2, 3, 4])
def test_cycles_are_valid_disjoint_and_bounded(seed, max_len):
    G = bp.make_synthetic_instance(n=14, edge_prob=0.18, seed=seed)
    matched, unmatched = bp.bounded_greedy_cycle_cover(G, max_len)

    used = [u for c in matched for u in c]
    assert len(used) == len(set(used)), "cycles must be vertex-disjoint"
    assert set(used) | set(unmatched) == set(G.nodes())
    assert not set(used) & set(unmatched)

    for c in matched:
        assert 2 <= len(c) <= max_len
        for u, v in edges_of(c):
            assert G.has_edge(u, v), "every step of a cycle must be a real edge"


def test_pairwise_only_bound_matches_only_swaps():
    G = nx.DiGraph()
    # A->B->C->A is a 3-cycle; D<->E is a direct swap
    for u, v in [("A", "B"), ("B", "C"), ("C", "A"), ("D", "E"), ("E", "D")]:
        G.add_edge(u, v, weight=0.8)
    matched, _ = bp.bounded_greedy_cycle_cover(G, max_len=2)
    assert [sorted(c) for c in matched] == [["D", "E"]]


def test_three_way_cycle_found_when_bound_allows_it():
    G = nx.DiGraph()
    for u, v in [("A", "B"), ("B", "C"), ("C", "A")]:
        G.add_edge(u, v, weight=0.7)
    matched, unmatched = bp.bounded_greedy_cycle_cover(G, max_len=3)
    assert len(matched) == 1 and sorted(matched[0]) == ["A", "B", "C"]
    assert unmatched == set()


def test_no_cycles_means_nobody_matched():
    G = nx.DiGraph()
    G.add_edge("A", "B", weight=0.9)
    G.add_edge("B", "C", weight=0.9)
    matched, unmatched = bp.bounded_greedy_cycle_cover(G, 4)
    assert matched == [] and unmatched == {"A", "B", "C"}


def test_empty_graph():
    matched, unmatched = bp.bounded_greedy_cycle_cover(nx.DiGraph(), 4)
    assert matched == [] and unmatched == set()


def test_utilitarian_and_egalitarian_scores():
    G = nx.DiGraph()
    G.add_edge("A", "B", weight=0.9)
    G.add_edge("B", "C", weight=0.4)
    G.add_edge("C", "A", weight=0.7)
    cycle = ["A", "B", "C"]
    assert bp.cycle_weight(G, cycle) == pytest.approx(2.0)
    assert bp.egalitarian_score(G, cycle) == pytest.approx(0.4)


@pytest.mark.parametrize("seed", range(10))
def test_bgcc_never_beats_the_exact_ilp(seed):
    G = bp.make_synthetic_instance(n=12, edge_prob=0.2, seed=seed)
    matched, _ = bp.bounded_greedy_cycle_cover(G, 4)
    _, ilp_weight = bp.exact_ilp_cycle_cover(G, 4)
    bgcc_weight = sum(bp.cycle_weight(G, c) for c in matched)
    assert bgcc_weight <= ilp_weight + 1e-9


@pytest.mark.parametrize("seed", range(10))
def test_bounded_enumeration_equals_filtered_full_enumeration(seed):
    G = bp.make_synthetic_instance(n=12, edge_prob=0.15, seed=seed)
    full = {frozenset(c) for c in nx.simple_cycles(G) if 2 <= len(c) <= 4}
    bounded = {frozenset(c) for c in enumerate_cycles(G, 4)}
    assert full == bounded


def test_result_is_deterministic():
    G = bp.make_synthetic_instance(n=16, edge_prob=0.15, seed=7)
    a = bp.bounded_greedy_cycle_cover(G, 4)
    b = bp.bounded_greedy_cycle_cover(G, 4)
    assert sorted(map(sorted, a[0])) == sorted(map(sorted, b[0]))
