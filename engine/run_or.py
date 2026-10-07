import re, sys, os
HERE = os.path.dirname(os.path.abspath(__file__))
import harness as h, minilua as m, wyn_static as w
from luastr import unescape

path = sys.argv[1]
SV = float(sys.argv[2])
N3_21 = float(sys.argv[3])
src = h.load_src(path)
it = h.make_interp()
h.run_xr(it, src)
h.lz_native(it)
p = w.parse(src)
ma = re.search(r'local \w+="((?:[^"\\]|\\.)*)"for \w+=1,91 do \w+\[', src)
alpha = {ord(ch): i for i, ch in enumerate(unescape(ma.group(1)).decode("latin-1") if isinstance(unescape(ma.group(1)), bytes) else unescape(ma.group(1)))}
ny = it.g.get("Ny")
n3 = m.Table()
n3.set(21.0, N3_21)
it.g.set("N3", n3)
it.g.set("BM", 4294967296.0)
it.g.set("Gv", 1.0)
it.g.set("b", lambda *a: [True])
it.g.set("Su", "x")
Om = m.Table()
it.g.set("Om", Om)
lmv = open(os.path.join(HERE, "stream_lm.txt")).read().split()
lm = m.Table()
for i, v in enumerate(lmv):
    lm.set(float(i + 1), float(v))
it.g.set("lm", lm)


def b91fn(s, *a):
    out = w.b91(s.encode("latin-1"), alpha)
    r = m.Table()
    for k, v in enumerate(out):
        r.set(float(k + 1), float(v))
    return [r]


ny.set(24518, b91fn)
ny.set(43336, lambda *a: [SV])
i = src.find("Ny[lQ[64093]]=function(Og,SV)")
fnast = h.parse_func_at(src, i + len("Ny[lQ[64093]]="))
ny.set(64093, m.Func(it, fnast[1], fnast[2], fnast[3], m.Scope()))
mth = m.Table()
mth.set("floor", lambda x, *a: [float(int(x // 1))])
ny.set(34931, mth)


def strdisp(self_, k):
    def f(*a):
        if len(a) == 1 and isinstance(a[0], float):
            return [chr(int(a[0]) & 255)]
        if len(a) == 1 and isinstance(a[0], m.Table):
            return ["".join(m.tostr(a[0].get(float(j))) if isinstance(a[0].get(float(j)), str) else chr(int(a[0].get(float(j)))) for j in range(1, a[0].length() + 1))]
        if len(a) >= 2 and isinstance(a[0], str):
            return [float(ord(a[0][int(a[1]) - 1]))]
        raise m.LuaError("strdisp %r" % (a,))
    return [f]


for key in (20891, 45729):
    t = m.Table()
    t.meta = m.Table()
    t.meta.set("__index", strdisp)
    ny.set(key, t)
env_stmts = []
for nm in ("X2", "OD", "OK", "Ou", "Or"):
    st = h.parse_localfunc(src, nm)
    env_stmts.append(st)
sc = m.Scope()
for st in env_stmts:
    it.exec(st, sc)
Or = sc.v["Or"]
mm = re.search(r'Ni:sub\((\d+),(\d+)\)', src)
slices = re.findall(r'Ni:sub\((\d+),(\d+)\)', src)
a, bb = int(slices[-1][0]), int(slices[-1][1])
mm = re.search(r'local Ni="((?:[^"\\]|\\.)*)"', src)
Ni = unescape(mm.group(1))
Ni = Ni.decode("latin-1") if isinstance(Ni, bytes) else Ni
OS = Ni[a - 1:bb]
try:
    r = Or(OS, None, None, Om, 0.0)
    print("ok", len(r))
    t = r[0]
    print("protos", t.length())
    import pickle
except m.LuaError as e:
    print("LuaError", e)


def show(v, depth=0, maxd=2):
    if isinstance(v, m.Table):
        if depth >= maxd:
            return "{...%d}" % len(v.d)
        items = list(v.d.items())
        return "{" + ", ".join("%s=%s" % (k, show(x, depth + 1, maxd)) for k, x in items[:14]) + (", ..+%d" % (len(items) - 14) if len(items) > 14 else "") + "}"
    if isinstance(v, str):
        return repr(v[:40])
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return repr(v)


if __name__ == "__main__":
    t = r[0]
    print(sorted(t.d.keys()))
    for k, v in t.d.items():
        print(k, show(v, 0, 3))
