import sys, re, os
HERE = os.path.dirname(os.path.abspath(__file__))
sys.argv = ["x", os.environ.get("WYN_SRC", os.path.join(HERE, "..", "samples", "input.lua")), os.environ.get("WYN_SV", "1887746136"), os.environ.get("WYN_N3", "834411669")]
import io, contextlib
with contextlib.redirect_stdout(io.StringIO()):
    import run_or as R
m = R.m
h = R.h
src = R.src
it = R.it
ny = R.ny
sc = R.sc
w = R.w
i = src.find("Ny[lQ[19558]]=function(GT,Gh)")
fn = h.parse_func_at(src, i + len("Ny[lQ[19558]]="))
n9 = m.Func(it, fn[1], fn[2], fn[3], m.Scope())
it.g.set("N9", n9)
ny.set(19558, n9)
ny.set(5637, 463318758.0)
mt = m.Table()
mt.set("floor", lambda x, *a: [float(int(x // 1))])
mt.meta = m.Table()
mt.meta.set("__index", lambda t, k: [t.d["floor"]])
ny.set(34931, mt)
ny.set(48920, lambda s=None, b=None, *a: [it.tonumber(s, b)])
it.g.set("lR", lambda v=None, *a: [{type(None): "nil", bool: "boolean", float: "number", str: "string", m.Table: "table"}.get(type(v), "function")])
ny.set(19140, lambda *a: [True])
ny.set(6677, None)


def alpha85(src):
    mm = re.search(r'local \w+="((?:[^"\\]|\\.)*)"for \w+=1,85 do', src)
    s = R.unescape(mm.group(1))
    s = s.decode("latin-1") if isinstance(s, bytes) else s
    return {ord(c): i for i, c in enumerate(s)}


A85 = alpha85(src)


def rd32(xl, xd, xL, xR, *a):
    xd = int(xd)
    blk = xd // 4
    k = xd % 4
    ent = xL.get(float(blk))
    if ent is None:
        xk = blk * 5
        xx = 0
        for j in range(5):
            xx = xx * 85 + A85.get(ord(xl[xk + j]) if xk + j < len(xl) else 0, 0)
        ent = m.Table()
        vals = [(xx // 16777216) % 256, (xx // 65536) % 256, (xx // 256) % 256, xx % 256]
        for j, v in enumerate(vals):
            ent.set(float(j + 1), float(v))
        xL.set(float(blk), ent)
    return [ent.get(float(k + 1)) or 0.0]


ny.set(32613, rd32)
for nm in ("XQ", "X6", "X5", "tk", "tf", "tB", "tq", "tn", "cx"):
    st = h.parse_localfunc(src, nm)
    it.exec(st, sc)
cx = sc.v["cx"]
proto = R.r[0].d[0]
