import csv, random, time
from pathlib import Path
import matplotlib.pyplot as plt
import networkx as nx
import pulp

USERS={"A":{"owns":"bike","wants":"guitar","weight":.9},"B":{"owns":"guitar","wants":"camera","weight":.7},"C":{"owns":"camera","wants":"bike","weight":.8},"D":{"owns":"headphones","wants":"bike","weight":.4}}

def build_exchange_graph(users):
    owners={v["owns"]:u for u,v in users.items()}; G=nx.DiGraph(); G.add_nodes_from(users)
    for u,v in users.items():
        if v["wants"] in owners and owners[v["wants"]]!=u:
            G.add_edge(u,owners[v["wants"]],weight=float(v["weight"]),item=v["wants"])
    return G

def cycle_edges(c): return list(zip(c,c[1:]+c[:1]))
def cycle_weight(G,c): return sum(G[u][v]["weight"] for u,v in cycle_edges(c))
def egalitarian_score(G,c): return min(G[u][v]["weight"] for u,v in cycle_edges(c))
def find_cycles(G,max_len=4): return [c for c in nx.simple_cycles(G) if 2<=len(c)<=max_len]

def bounded_greedy_cycle_cover(G,max_len=4):
    remaining=set(G.nodes()); matched=[]
    while True:
        sub=G.subgraph(remaining); candidates=[c for c in nx.simple_cycles(sub) if 2<=len(c)<=max_len]
        if not candidates: break
        best=max(candidates,key=lambda c:cycle_weight(G,c)); matched.append(best); remaining-=set(best)
    return matched,remaining

def exact_ilp_cycle_cover(G,max_len=4):
    cs=find_cycles(G,max_len)
    if not cs:return [],0.0
    p=pulp.LpProblem("L_CYCLE_COVER",pulp.LpMaximize); x={i:pulp.LpVariable(f"x_{i}",cat="Binary") for i in range(len(cs))}
    p += pulp.lpSum(cycle_weight(G,cs[i])*x[i] for i in x)
    for v in G.nodes():
        ids=[i for i,c in enumerate(cs) if v in c]
        if ids:p += pulp.lpSum(x[i] for i in ids)<=1
    p.solve(pulp.PULP_CBC_CMD(msg=0)); selected=[cs[i] for i in x if pulp.value(x[i])==1]
    return selected,sum(cycle_weight(G,c) for c in selected)

def make_synthetic_instance(n=15,edge_prob=.15,seed=42):
    rng=random.Random(seed); nodes=[chr(65+i) if i<26 else f"U{i}" for i in range(n)]; G=nx.DiGraph(); G.add_nodes_from(nodes)
    for u in nodes:
        for v in nodes:
            if u!=v and rng.random()<edge_prob:G.add_edge(u,v,weight=round(rng.uniform(.3,1),2))
    return G

def draw_exchange_graph(G,title="SwapCycle — Exchange Graph"):
    plt.figure(figsize=(9,7)); pos=nx.spring_layout(G,seed=42)
    nx.draw_networkx_nodes(G,pos,node_size=2200,node_color="lightblue",edgecolors="black",linewidths=1.5)
    nx.draw_networkx_edges(G,pos,arrows=True,arrowsize=25,width=2,connectionstyle="arc3,rad=.08")
    nx.draw_networkx_labels(G,pos,font_size=15,font_weight="bold")
    nx.draw_networkx_edge_labels(G,pos,edge_labels={(u,v):f"{d['weight']:.1f}" for u,v,d in G.edges(data=True)},font_size=11)
    plt.title(title,fontsize=16,fontweight="bold"); plt.axis("off"); plt.tight_layout(); plt.show()

def draw_bgcc_result(G,matched,unmatched,title="SwapCycle — BGCC Selected Exchange Cycles"):
    plt.figure(figsize=(10,8)); pos=nx.spring_layout(G,seed=42); mu=set().union(*matched) if matched else set()
    if unmatched:nx.draw_networkx_nodes(G,pos,nodelist=list(unmatched),node_size=2200,node_color="lightgrey",edgecolors="black",linewidths=1.5)
    if mu:nx.draw_networkx_nodes(G,pos,nodelist=list(mu),node_size=2200,node_color="lightgreen",edgecolors="black",linewidths=1.5)
    nx.draw_networkx_edges(G,pos,arrows=True,arrowsize=22,width=1.5,alpha=.3,connectionstyle="arc3,rad=.08")
    selected=[]
    for c in matched:selected+=cycle_edges(c)
    if selected:nx.draw_networkx_edges(G,pos,edgelist=selected,arrows=True,arrowsize=28,width=4,edge_color="green",connectionstyle="arc3,rad=.08")
    nx.draw_networkx_labels(G,pos,font_size=15,font_weight="bold")
    nx.draw_networkx_edge_labels(G,pos,edge_labels={(u,v):f"{d['weight']:.1f}" for u,v,d in G.edges(data=True)},font_size=10)
    lines=[f"Cycle {i}: {' → '.join(c)} → {c[0]} | utility={cycle_weight(G,c):.2f} | fairness={egalitarian_score(G,c):.2f}" for i,c in enumerate(matched,1)]
    if unmatched:lines.append(f"Unmatched: {', '.join(sorted(unmatched))}")
    if lines:plt.figtext(.5,.02,"\n".join(lines),ha="center",fontsize=10)
    plt.title(title,fontsize=17,fontweight="bold"); plt.axis("off"); plt.tight_layout(rect=[0,.08,1,1]); plt.show()

def benchmark_instance(G,max_len=4):
    t=time.perf_counter(); bc,un=bounded_greedy_cycle_cover(G,max_len); bt=time.perf_counter()-t; bw=sum(cycle_weight(G,c) for c in bc)
    t=time.perf_counter(); ic,iw=exact_ilp_cycle_cover(G,max_len); it=time.perf_counter()-t
    gap=0 if iw==0 else (iw-bw)/iw
    return {"n":G.number_of_nodes(),"edges":G.number_of_edges(),"bgcc_cycles":len(bc),"bgcc_weight":bw,"bgcc_time_s":bt,"ilp_cycles":len(ic),"ilp_weight":iw,"ilp_time_s":it,"gap":gap,"unmatched":len(un)}

def run_benchmark_suite(out="benchmark_results.csv"):
    rows=[]
    for n,p in [(10,.10),(10,.20),(15,.10),(15,.20),(20,.10),(20,.15),(25,.08)]:
        for seed in range(3):
            r=benchmark_instance(make_synthetic_instance(n,p,1000+seed+n)); r.update(edge_prob=p,seed=1000+seed+n); rows.append(r)
    with open(out,"w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=rows[0].keys()); w.writeheader(); w.writerows(rows)
    print(f"Benchmark CSV: {out}"); print(f"Mean gap: {sum(r['gap'] for r in rows)/len(rows):.2%}"); print(f"Worst gap: {max(r['gap'] for r in rows):.2%}")
    return rows

def main():
    G=build_exchange_graph(USERS); print("Edges in exchange graph:")
    for u,v,d in G.edges(data=True):print(f"  {u} -> {v} (wants '{d['item']}', weight={d['weight']})")
    print("\nAll simple cycles found (length 2-4):")
    for c in find_cycles(G):print(f"  {' -> '.join(c)} -> {c[0]} | utilitarian={cycle_weight(G,c):.2f} | egalitarian={egalitarian_score(G,c):.2f}")
    matched,un=bounded_greedy_cycle_cover(G); print("\nBGCC result:")
    for c in matched:print(f"  Matched cycle: {' -> '.join(c)} -> {c[0]} (utility={cycle_weight(G,c):.2f})")
    print(f"  Unmatched users: {sorted(un)}"); draw_exchange_graph(G); draw_bgcc_result(G,matched,un)
    r=benchmark_instance(G); print(f"\nToy benchmark: BGCC={r['bgcc_weight']:.2f} | ILP={r['ilp_weight']:.2f} | gap={r['gap']:.2%}")
    run_benchmark_suite()
if __name__=="__main__":main()
