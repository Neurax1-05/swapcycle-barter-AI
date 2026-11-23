"""The fast cycle enumerator must find exactly the cycles networkx finds."""
import random

import networkx as nx
import pytest

from cycle_arbitration import enumerate_cycles_capped, select_cycles


def canon(c):
    i = c.index(min(c))
    return tuple(c[i:] + c[:i])


@pytest.mark.parametrize("seed", range(12))
@pytest.mark.parametrize("L", [2, 3, 4])
def test_same_cycles_as_networkx(seed, L):
    r = random.Random(seed)
    n = r.randint(5, 25)
    G = nx.DiGraph()
    G.add_nodes_from(range(n))
    for u in range(n):
        for v in range(n):
            if u != v and r.random() < 0.2:
                G.add_edge(u, v, weight=r.uniform(.5, 1))
    mine, trunc = enumerate_cycles_capped(G, L)
    ref = [list(c) for c in nx.simple_cycles(G, length_bound=L) if len(c) >= 2]
    assert not trunc
    assert sorted(map(canon, mine)) == sorted(map(canon, ref))
    assert len(mine) == len(set(map(canon, mine)))  # no duplicates


def test_string_nodes_and_cap():
    G = nx.DiGraph()
    for u, v in [("a", "b"), ("b", "a"), ("b", "c"), ("c", "b")]:
        G.add_edge(u, v, weight=.9)
    cycles, trunc = enumerate_cycles_capped(G, 4, max_cycles=1)
    assert trunc and len(cycles) == 1


def test_ilp_never_worse_than_greedy():
    pytest.importorskip("pulp")
    from cycle_arbitration import cycle_weight
    for seed in range(6):
        r = random.Random(seed)
        G = nx.DiGraph(); G.add_nodes_from(range(30))
        for u in range(30):
            for v in range(30):
                if u != v and r.random() < .12:
                    G.add_edge(u, v, weight=round(r.uniform(.5, 1), 2))
        g, _, _ = select_cycles(G, 4, log=lambda *a: None, solver="greedy")
        i, _, _ = select_cycles(G, 4, log=lambda *a: None, solver="ilp")
        assert sum(cycle_weight(G, c) for c in i) >= sum(cycle_weight(G, c) for c in g) - 1e-9
        used = [u for c in i for u in c]
        assert len(used) == len(set(used))  # vertex-disjoint


def test_prune_only_removes_edges_that_cannot_matter():
    """Pruning to the SCCs must not change the set of cycles."""
    from cycle_arbitration import prune_graph, trim_to_sccs
    r = random.Random(7)
    G = nx.DiGraph(); G.add_nodes_from(range(40))
    for u in range(40):
        for v in range(40):
            if u != v and r.random() < .06:
                G.add_edge(u, v, weight=r.uniform(.5, 1))
    full, _ = enumerate_cycles_capped(G, 4)
    trimmed, _ = enumerate_cycles_capped(trim_to_sccs(G), 4)
    assert sorted(map(canon, full)) == sorted(map(canon, trimmed))
    P = prune_graph(G, 3)
    assert all(P.out_degree(u) <= 3 for u in P.nodes())
    assert all(G.has_edge(u, v) for u, v in P.edges())
