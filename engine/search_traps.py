import json, itertools, os
HERE = os.path.dirname(os.path.abspath(__file__))
import run_cx as C

m = C.m
ny = C.ny
it = C.it
tr = json.load(open(os.path.join(HERE, "traps.json")))
cons = {int(a): float(b) for a, b in tr["cons"]}
fields = [1821, 7186, 9298, 6675, 9036, 3417, 3104, 9557]
state = {"t6": 0, "calls": 0}


def clone(v):
    if isinstance(v, m.Table):
        t = m.Table()
        for k, x in v.d.items():
            t.d[k] = clone(x)
        t.meta = v.meta
        return t
    return v


base = clone(C.proto)


def configure(mask, t6):
    tp = m.Table()
    td = m.Table()
    for i in range(1, 12):
        if mask[i - 1]:
            marker = "P%d" % i
            tp.set(float(i), (lambda mk: lambda *a: [mk])(marker))
            td.set(marker, cons[i])
        else:
            tp.set(float(i), lambda *a: [])
    ny.set(6677, tp)
    ny.set(57606, td)
    t = m.Table()
    for k, v in ((0, 1620346357.0), (1, 83614515.0), (2, 1261801663.0), (3, 1946740386.0)):
        t.set(float(k), v)
    ny.set(28662, t)
    state["t6"] = t6
    state["calls"] = 0

    def probe(*a):
        state["calls"] += 1
        bit = (state["t6"] >> ((state["calls"] - 1) % 2)) & 1
        return [True if bit else None]

    ny.set(24958, lambda *a: [True])
    ny.set(51452, probe)


def decode(mask, t6, count=101):
    configure(mask, t6)
    p = clone(base)
    for xo in range(1, count + 1):
        C.cx(p, float(xo), None)
    global LAST
    LAST = p
    rows = []
    for xo in range(1, count + 1):
        rows.append([int(p.d[f].d.get(xo)) if p.d[f].d.get(xo) is not None else None for f in fields])
    return rows


def score(rows):
    return sum(1 for r in rows for v in r[4:] if v == 0)


if __name__ == "__main__":
    mask = [True] * 11
    best = (score(decode(mask, 0)), mask[:], 0)
    print("start", best[0], flush=True)
    improved = True
    while improved:
        improved = False
        for i in range(11):
            cand = best[1][:]
            cand[i] = not cand[i]
            s = score(decode(cand, best[2]))
            if s > best[0]:
                best = (s, cand, best[2])
                improved = True
                print("mask flip", i, s, flush=True)
        for t6 in range(4):
            if t6 == best[2]:
                continue
            s = score(decode(best[1], t6))
            if s > best[0]:
                best = (s, best[1], t6)
                improved = True
                print("t6", t6, s, flush=True)
    print("best", best)
    rows = decode(best[1], best[2])
    json.dump(rows, open(os.path.join(os.getcwd(), "skib_rows.json"), "w"))
    for i, r in enumerate(rows, 1):
        print(i, r)
