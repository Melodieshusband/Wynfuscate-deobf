import re, sys, os
HERE = os.path.dirname(os.path.abspath(__file__))
ARGS = list(sys.argv)
import symvm as V
import search_traps as ST
import minilua as m
import harness as h

it = V.it
ny = V.ny


def n4(a=None, b=None, *r):
    if isinstance(a, m.Sym) or isinstance(b, m.Sym):
        return [m.Sym("xor", a, b)]
    return [float((int(a or 0) & 0xFFFFFFFF) ^ (int(b or 0) & 0xFFFFFFFF))]


it.g.set("N4", n4)
import json
l3t = m.Table()
for k, v in json.load(open(os.path.join(HERE, "l3.json"))).items():
    l3t.set(float(k), float(v))
it.g.set("l3", l3t)
it.g.set("N2", m.Table())
it.g.set("VC", m.Table())
it.g.set("Vb", m.Table())
it.g.set("Zp", lambda k=None, *a: [m.Sym("proto", k)])
it.g.set("l9", lambda *a: [m.Sym("l9", a)])
ny.meta = m.Table()
ny.meta.set("__index", lambda t, k: [m.Sym("env", k)])
src = V.src
p = V.proto


class Regs(m.Table):
    __slots__ = ("vals",)

    def __init__(self):
        super().__init__()
        self.vals = {}

    def get(self, k):
        k = m.norm(k)
        if k in self.vals:
            return self.vals[k]
        if isinstance(k, int) or isinstance(k, float):
            return m.Sym("reg", k)
        return None

    def set(self, k, v):
        k = m.norm(k)
        self.vals[k] = v
        m.Ctx.effects.append(("setreg", k, v))


def tbl(d):
    t = m.Table()
    for k, v in d.items():
        t.set(k, v)
    return t


field_names = {"iN": 1821, "il": 7186, "iB": 9298, "iG": 6675, "ix": 9036, "iq": 3417, "iS": 3104, "iX": 9557, "it": 8709, "iD": 1802, "iK": 2254}
glob = {}
for nm, key in field_names.items():
    glob[nm] = p.d[key]
it.g.set("Xw", V.Xw)
for nm, val in glob.items():
    it.g.set(nm, val)
it.g.set("VE", Regs())
it.g.set("ia", 17 + (((550842723 + 0 * 131 + 29) % 997)))
it.g.set("ir", 31 + (((550842723 - (550842723 % 997)) / 997 + 0 * 257 + 71) % 991))
it.g.set("iu", p.d[2262])
it.g.set("im", p.d[3817])
it.g.set("cn", p)
it.g.set("VF", None)
it.g.set("FB", 101.0)

for nm, idn in (("lx", 68), ("lq", 60), ("ln", 123), ("lS", 132), ("lX", 78)):
    pass


def tstr(i):
    s = V.pool.get(i)
    return s.decode("latin-1") if s else None


for nm, idn in (("lx", 68), ("lq", 60), ("ln", 123), ("lS", 132), ("lX", 78)):
    it.g.set(nm, tstr(idn))
print("type names", [it.g.get(n) for n in ("lx", "lq", "ln", "lS", "lX")])

i0 = src.find("if VW<=84 then")
disp = m.Parser(m.lex(src[i0:])).stmt()
LOCALS = ["ij", "ie", "iv", "iM", "iQ", "iy", "i0", "i3", "i6"]


PRISTINE = {nm: ST.clone(glob[nm]) for nm in glob}
it.g.set("Ib", lambda *a: [m.Sym("Ib", a)])
it.g.set("hl", m.Table())
it.g.set("N0", m.Sym("N0"))
it.g.set("lL", lambda t=None, *a: [m.Sym("concat", t)])


def run_instr(pc, decisions=None, regs=None):
    m.Ctx.decisions = list(decisions or [])
    m.Ctx.pos = 0
    m.Ctx.pending = []
    m.Ctx.effects = []
    raw = p.d[1821].d[pc]
    vw = ((raw * 23 + 63) % 256)
    ve = Regs()
    if regs:
        ve.vals = dict(regs)
    it.g.set("VE", ve)
    for nm in PRISTINE:
        it.g.set(nm, ST.clone(PRISTINE[nm]))
    sc = m.Scope()
    sc.v["VY"] = float(pc)
    sc.v["VW"] = float(vw)
    sc.v["VV"] = False
    sc.v["Vz"] = False
    for n in LOCALS:
        sc.v[n] = None
    err = None
    try:
        it.exec(disp, sc)
    except m.LuaError as e:
        err = str(e)[:200]
    except Exception as e:
        err = "PY " + repr(e)[:200]
    return vw, sc.v["VY"], list(m.Ctx.effects), err, ve.vals


if __name__ == "__main__":
    for pc in range(1, int(ARGS[1]) + 1):
        vw, vy, eff, err, _ = run_instr(pc)
        print(pc, "raw", int(p.d[1821].d[pc]), "VW", vw, "-> VY", vy, "err", err)
        for e in eff:
            print("    ", e)
