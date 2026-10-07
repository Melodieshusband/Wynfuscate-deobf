import re
import minilua as m


def load_src(path):
    return open(path, encoding="latin-1").read()


def parse_func_at(src, idx):
    p = m.Parser(m.lex(src[idx:]))
    p.expect("function")
    return p.funcbody(False)


def make_interp():
    it = m.Interp()
    lq = m.Table()
    lq.meta = m.Table()
    lq.meta.set("__index", lambda t, k: [k])
    ny = m.Table()
    it.g.set("lQ", lq)
    it.g.set("Ny", ny)
    it.g.set("N4", lambda a, b, *r: [float((int(a) & 0xFFFFFFFF) ^ (int(b) & 0xFFFFFFFF))])
    it.g.set("BQ", 2147483647.0)
    return it


def run_xr(it, src):
    a = src.find("Ny[lQ[62052]]=(2^31)-1 local Xr={}")
    b = src.find("Xr[17]=N5(Xr[13])", a)
    e = src.find("end", b)
    end = src.find("if Xr[17]==0 then Xr[17]=1 end", b) + len("if Xr[17]==0 then Xr[17]=1 end")
    it.run(src[a:end].replace("local Xr={}", "Xr={}", 1))
    return it


def parse_localfunc(src, name):
    i = src.find("local function %s(" % name)
    p = m.Parser(m.lex(src[i:]))
    return p.stmt()


def lz_native(it):
    import wyn_static as w

    def xs(t, total=None, *a):
        data = bytes(int(t.get(float(k))) for k in range(1, t.length() + 1))
        out = w.lz_expand(data, int(total))
        r = m.Table()
        for k, v in enumerate(out):
            r.set(float(k + 1), float(v))
        return [r]

    it.g.set("xs", xs)


def b91_native(it, alphabet):
    import wyn_static as w

    def dec(s, *a):
        out = w.b91(s.encode("latin-1"), {ord(ch): v for ch, v in alphabet.items()} if False else alphabet)
        r = m.Table()
        for k, v in enumerate(out):
            r.set(float(k + 1), float(v))
        return [r]

    return dec
