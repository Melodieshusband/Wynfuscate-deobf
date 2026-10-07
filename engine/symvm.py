import re, json, sys
import search_traps as S
import run_cx as C
import wyn_static as w
import minilua as m
import harness as h

it = C.it
ny = C.ny
src = C.src
sw = w.parse(src)
QE = 1849543054
pool = {}
for le in range(1, len(sw.offsets) + 1):
    n, d = w.record(sw, le)
    pool[le] = w.stream(sw, QE, le, n, d)

rows = S.decode([True] * 11, 0)
proto = S.LAST
slices = re.findall(r"Ni:sub\((\d+),(\d+)\)", src)
mm = re.search(r'local Ni="((?:[^"\\]|\\.)*)"', src)
Ni = C.R.unescape(mm.group(1))
Ni = Ni.decode("latin-1") if isinstance(Ni, bytes) else Ni
a, b_ = int(slices[2][0]), int(slices[2][1])
xx = w.lz_expand(w.b91(Ni[a - 1:b_].encode("latin-1"), sw.alphabet), 405)
Xw = m.Table()
gc = 1
cur = 0
sh = 0
for byte in xx:
    cur += (byte % 128) * (2 ** sh)
    if byte < 128:
        Xw.set(float(gc), float(cur))
        gc += 1
        cur = 0
        sh = 0
    else:
        sh += 7
    if gc > 307:
        break


def fetch(le, xr=None, *a):
    s = pool.get(int(le))
    if s is None:
        it.g.set("Su", None)
        return [False]
    it.g.set("Su", s.decode("latin-1"))
    return [True]


it.g.set("b", fetch)
ny.set(19140, fetch)
it.g.set("Gv", 1.0)
