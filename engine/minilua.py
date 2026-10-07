import math
import re


class LuaError(Exception):
    pass


class Sym:
    __slots__ = ("op", "args")

    def __init__(self, op, *args):
        self.op = op
        self.args = args

    def __repr__(self):
        return "%s(%s)" % (self.op, ",".join(repr(a) for a in self.args))


class Fork(Exception):
    pass


class Ctx:
    decisions = []
    pos = 0
    pending = []
    effects = []


def decide(sym):
    if Ctx.pos < len(Ctx.decisions):
        d = Ctx.decisions[Ctx.pos]
        Ctx.pos += 1
        Ctx.effects.append(("branch", sym, d))
        return d
    Ctx.decisions.append(True)
    Ctx.pos += 1
    Ctx.pending.append(len(Ctx.decisions) - 1)
    Ctx.effects.append(("branch", sym, True))
    return True


class Table:
    __slots__ = ("d", "meta")

    def __init__(self):
        self.d = {}
        self.meta = None

    def get(self, k):
        k = norm(k)
        v = self.d.get(k)
        if v is None and self.meta is not None:
            h = self.meta.d.get("__index")
            if h is not None:
                if isinstance(h, Table):
                    return h.get(k)
                return first(h(self, k))
        return v

    def set(self, k, v):
        k = norm(k)
        if v is None:
            self.d.pop(k, None)
        else:
            self.d[k] = v

    def length(self):
        n = 0
        while (n + 1) in self.d:
            n += 1
        return n


def norm(k):
    if isinstance(k, float) and k == int(k):
        return int(k)
    return k


def first(r):
    if isinstance(r, list):
        return r[0] if r else None
    return r


TOKEN = re.compile(
    r"""\s+|--\[(=*)\[.*?\]\1\]|--[^\n]*|(?P<num>0[xX][0-9a-fA-F]+|\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?)|(?P<name>[A-Za-z_]\w*)|(?P<str>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')|\[(?P<eq>=*)\[(?P<long>.*?)\](?P=eq)\]|(?P<op>\.\.\.|\.\.|==|~=|<=|>=|[-+*/%^#<>=(){}\[\];:,.])""",
    re.S,
)
KEYWORDS = {"and", "break", "do", "else", "elseif", "end", "false", "for", "function", "if", "in", "local", "nil", "not", "or", "repeat", "return", "then", "true", "until", "while"}
ESC = {"n": 10, "t": 9, "r": 13, "a": 7, "b": 8, "f": 12, "v": 11, "\\": 92, '"': 34, "'": 39, "\n": 10}


def unescape(body):
    out = bytearray()
    i = 0
    n = len(body)
    while i < n:
        c = body[i]
        if c == "\\":
            i += 1
            d = body[i]
            if d.isdigit():
                j = i
                while j < n and j < i + 3 and body[j].isdigit():
                    j += 1
                out.append(int(body[i:j]) & 255)
                i = j
                continue
            if d == "x":
                out.append(int(body[i + 1:i + 3], 16))
                i += 3
                continue
            out.append(ESC.get(d, ord(d)))
            i += 1
            continue
        out.append(ord(c) & 255)
        i += 1
    return bytes(out).decode("latin-1")


def lex(src):
    toks = []
    pos = 0
    n = len(src)
    while pos < n:
        m = TOKEN.match(src, pos)
        if not m:
            raise LuaError("lex error at %d: %r" % (pos, src[pos:pos + 30]))
        pos = m.end()
        if m.group("num"):
            t = m.group("num")
            toks.append(("num", float(int(t, 16)) if t[:2] in ("0x", "0X") else float(t)))
        elif m.group("name"):
            t = m.group("name")
            toks.append((t, t) if t in KEYWORDS else ("name", t))
        elif m.group("str"):
            toks.append(("str", unescape(m.group("str")[1:-1])))
        elif m.group("long") is not None:
            toks.append(("str", m.group("long")))
        elif m.group("op"):
            toks.append((m.group("op"), m.group("op")))
    toks.append(("eof", None))
    return toks


BINPRI = {"or": (1, 1), "and": (2, 2), "<": (3, 3), ">": (3, 3), "<=": (3, 3), ">=": (3, 3), "~=": (3, 3), "==": (3, 3), "..": (5, 4), "+": (6, 6), "-": (6, 6), "*": (7, 7), "/": (7, 7), "%": (7, 7), "^": (10, 9)}
UNPRI = 8


class Parser:
    def __init__(self, toks):
        self.t = toks
        self.i = 0

    def peek(self):
        return self.t[self.i][0]

    def next(self):
        tok = self.t[self.i]
        self.i += 1
        return tok

    def accept(self, k):
        if self.t[self.i][0] == k:
            self.i += 1
            return True
        return False

    def expect(self, k):
        tok = self.next()
        if tok[0] != k:
            raise LuaError("expected %s got %s at token %d" % (k, tok[0], self.i))
        return tok

    def block(self):
        stmts = []
        while self.peek() not in ("eof", "end", "else", "elseif", "until"):
            if self.peek() == "return":
                self.next()
                exprs = []
                if self.peek() not in ("eof", "end", "else", "elseif", "until", ";"):
                    exprs = self.exprlist()
                self.accept(";")
                stmts.append(("return", exprs))
                break
            s = self.stmt()
            if s is not None:
                stmts.append(s)
        return stmts

    def stmt(self):
        k = self.peek()
        if k == ";":
            self.next()
            return None
        if k == "if":
            self.next()
            clauses = []
            cond = self.expr()
            self.expect("then")
            clauses.append((cond, self.block()))
            els = None
            while True:
                if self.accept("elseif"):
                    c = self.expr()
                    self.expect("then")
                    clauses.append((c, self.block()))
                elif self.accept("else"):
                    els = self.block()
                    self.expect("end")
                    break
                else:
                    self.expect("end")
                    break
            return ("if", clauses, els)
        if k == "while":
            self.next()
            c = self.expr()
            self.expect("do")
            b = self.block()
            self.expect("end")
            return ("while", c, b)
        if k == "do":
            self.next()
            b = self.block()
            self.expect("end")
            return ("do", b)
        if k == "for":
            self.next()
            n1 = self.expect("name")[1]
            if self.accept("="):
                a = self.expr()
                self.expect(",")
                b = self.expr()
                c = self.expr() if self.accept(",") else None
                self.expect("do")
                body = self.block()
                self.expect("end")
                return ("fornum", n1, a, b, c, body)
            names = [n1]
            while self.accept(","):
                names.append(self.expect("name")[1])
            self.expect("in")
            exprs = self.exprlist()
            self.expect("do")
            body = self.block()
            self.expect("end")
            return ("forin", names, exprs, body)
        if k == "repeat":
            self.next()
            b = self.block()
            self.expect("until")
            c = self.expr()
            return ("repeat", b, c)
        if k == "function":
            self.next()
            target = ("name", self.expect("name")[1])
            isself = False
            while self.peek() in (".", ":"):
                sep = self.next()[0]
                nm = self.expect("name")[1]
                target = ("index", target, ("const", nm))
                if sep == ":":
                    isself = True
                    break
            f = self.funcbody(isself)
            return ("assign", [target], [f])
        if k == "local":
            self.next()
            if self.accept("function"):
                nm = self.expect("name")[1]
                f = self.funcbody(False)
                return ("localfunc", nm, f)
            names = [self.expect("name")[1]]
            while self.accept(","):
                names.append(self.expect("name")[1])
            exprs = self.exprlist() if self.accept("=") else []
            return ("local", names, exprs)
        if k == "break":
            self.next()
            return ("break",)
        e = self.suffixed()
        if self.peek() in ("=", ","):
            targets = [e]
            while self.accept(","):
                targets.append(self.suffixed())
            self.expect("=")
            return ("assign", targets, self.exprlist())
        return ("exprstmt", e)

    def funcbody(self, isself):
        self.expect("(")
        params = ["self"] if isself else []
        vararg = False
        if self.peek() != ")":
            while True:
                if self.accept("..."):
                    vararg = True
                    break
                params.append(self.expect("name")[1])
                if not self.accept(","):
                    break
        self.expect(")")
        body = self.block()
        self.expect("end")
        return ("function", params, vararg, body)

    def exprlist(self):
        es = [self.expr()]
        while self.accept(","):
            es.append(self.expr())
        return es

    def primary(self):
        tok = self.next()
        if tok[0] == "name":
            return ("name", tok[1])
        if tok[0] == "(":
            e = self.expr()
            self.expect(")")
            return ("paren", e)
        raise LuaError("unexpected %s at token %d" % (tok[0], self.i))

    def suffixed(self):
        e = self.primary()
        while True:
            k = self.peek()
            if k == ".":
                self.next()
                e = ("index", e, ("const", self.expect("name")[1]))
            elif k == "[":
                self.next()
                idx = self.expr()
                self.expect("]")
                e = ("index", e, idx)
            elif k == ":":
                self.next()
                nm = self.expect("name")[1]
                e = ("method", e, nm, self.callargs())
            elif k in ("(", "str", "{"):
                e = ("call", e, self.callargs())
            else:
                return e

    def callargs(self):
        k = self.peek()
        if k == "str":
            return [("const", self.next()[1])]
        if k == "{":
            return [self.table()]
        self.expect("(")
        args = []
        if self.peek() != ")":
            args = self.exprlist()
        self.expect(")")
        return args

    def table(self):
        self.expect("{")
        items = []
        while self.peek() != "}":
            if self.peek() == "[":
                self.next()
                kx = self.expr()
                self.expect("]")
                self.expect("=")
                items.append(("kv", kx, self.expr()))
            elif self.peek() == "name" and self.t[self.i + 1][0] == "=":
                nm = self.next()[1]
                self.next()
                items.append(("kv", ("const", nm), self.expr()))
            else:
                items.append(("pos", self.expr()))
            if not (self.accept(",") or self.accept(";")):
                break
        self.expect("}")
        return ("table", items)

    def simple(self):
        k = self.peek()
        if k == "num":
            return ("const", self.next()[1])
        if k == "str":
            return ("const", self.next()[1])
        if k == "nil":
            self.next()
            return ("const", None)
        if k == "true":
            self.next()
            return ("const", True)
        if k == "false":
            self.next()
            return ("const", False)
        if k == "...":
            self.next()
            return ("vararg",)
        if k == "{":
            return self.table()
        if k == "function":
            self.next()
            return self.funcbody(False)
        return self.suffixed()

    def expr(self, limit=0):
        k = self.peek()
        if k in ("not", "-", "#"):
            self.next()
            operand = self.expr(UNPRI)
            left = ("unop", k, operand)
        else:
            left = self.simple()
        while True:
            op = self.peek()
            pri = BINPRI.get(op)
            if pri is None or pri[0] <= limit:
                return left
            self.next()
            right = self.expr(pri[1])
            left = ("binop", op, left, right)


class Scope:
    __slots__ = ("v", "p")

    def __init__(self, p=None):
        self.v = {}
        self.p = p

    def find(self, name):
        s = self
        while s is not None:
            if name in s.v:
                return s
            s = s.p
        return None


class Break(Exception):
    pass


class Func:
    def __init__(self, interp, params, vararg, body, scope):
        self.interp = interp
        self.params = params
        self.vararg = vararg
        self.body = body
        self.scope = scope

    def __call__(self, *args):
        sc = Scope(self.scope)
        for i, p in enumerate(self.params):
            sc.v[p] = args[i] if i < len(args) else None
        sc.v["..."] = list(args[len(self.params):]) if self.vararg else []
        r = self.interp.run_block(self.body, sc)
        if r is not None and r[0] == "ret":
            return r[1]
        return []


def truthy(v):
    if isinstance(v, Sym):
        return decide(v)
    return v is not None and v is not False


def lmod(a, b):
    if b == 0:
        return float("nan")
    return a - math.floor(a / b) * b


def tostr(v):
    if isinstance(v, Sym):
        return v
    if v is None:
        return "nil"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, float):
        if v == int(v) and abs(v) < 1e15:
            return str(int(v))
        return repr(v)
    return str(v)


def tonum(v):
    if isinstance(v, (float, Sym)):
        return v
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            raise LuaError("cannot convert string to number")
    raise LuaError("arithmetic on %s" % type(v).__name__)


class Interp:
    def __init__(self):
        self.g = Table()
        self.install()

    def install(self):
        g = self.g

        def reg(name, fn):
            g.set(name, fn)

        reg("type", lambda v=None, *a: [Sym("type", v) if isinstance(v, Sym) else {type(None): "nil", bool: "boolean", float: "number", str: "string", Table: "table"}.get(type(v), "function")])
        reg("tostring", lambda v=None, *a: [tostr(v)])
        reg("tonumber", lambda v=None, b=None, *a: [self.tonumber(v, b)])
        reg("pairs", lambda t, *a: [self.next_fn, t, None])
        reg("ipairs", lambda t, *a: [self.inext, t, 0.0])
        reg("next", self.next_fn)
        reg("select", self.select)
        reg("rawget", lambda t, k, *a: [t.d.get(norm(k))])
        reg("rawset", lambda t, k, v, *a: [t.set(k, v), t][1:])
        reg("setmetatable", self.setmeta)
        reg("getmetatable", lambda t, *a: [t.meta if isinstance(t, Table) else None])
        reg("unpack", lambda t, i=1.0, j=None, *a: [t.get(float(k)) for k in range(int(i), int(j if j is not None else t.length()) + 1)])
        reg("error", self.error)
        reg("pcall", self.pcall)
        math_t = Table()
        for nm in ("floor", "ceil", "sqrt", "abs", "sin", "cos", "tan", "log", "exp"):
            fn = abs if nm == "abs" else getattr(math, nm)
            math_t.set(nm, (lambda f: lambda x=0.0, *a: [float(f(x))])(fn))
        math_t.set("max", lambda *a: [max(a)])
        math_t.set("min", lambda *a: [min(a)])
        math_t.set("fmod", lambda a, b, *r: [math.fmod(a, b)])
        math_t.set("huge", float("inf"))
        math_t.set("pi", math.pi)
        reg("math", math_t)
        st = Table()
        st.set("byte", lambda s, i=1.0, j=None, *a: [float(ord(s[int(k) - 1])) for k in range(int(i), int(j if j is not None else i) + 1) if 0 < int(k) <= len(s)])
        st.set("char", lambda *a: ["".join(chr(int(x) & 255) for x in a)])
        st.set("sub", self.ssub)
        st.set("len", lambda s, *a: [float(len(s))])
        st.set("rep", lambda s, n, *a: [s * int(n)])
        st.set("reverse", lambda s, *a: [s[::-1]])
        reg("string", st)
        tb = Table()
        tb.set("insert", self.tinsert)
        tb.set("concat", self.tconcat)
        tb.set("unpack", lambda t, i=1.0, j=None, *a: [t.get(float(k)) for k in range(int(i), int(j if j is not None else t.length()) + 1)])
        reg("table", tb)
        b32 = Table()
        b32.set("bxor", lambda *a: [float(self.fold(a, lambda x, y: x ^ y))])
        b32.set("band", lambda *a: [float(self.fold(a, lambda x, y: x & y))])
        b32.set("bor", lambda *a: [float(self.fold(a, lambda x, y: x | y))])
        b32.set("lshift", lambda a, n, *r: [float((int(a) << int(n)) & 0xFFFFFFFF)])
        b32.set("rshift", lambda a, n, *r: [float((int(a) & 0xFFFFFFFF) >> int(n))])
        reg("bit32", b32)
        reg("_G", g)

    def fold(self, a, f):
        r = int(a[0]) & 0xFFFFFFFF
        for x in a[1:]:
            r = f(r, int(x) & 0xFFFFFFFF)
        return r

    def tonumber(self, v, b):
        if isinstance(v, float):
            return v
        try:
            if b is not None:
                return float(int(v, int(b)))
            return float(v)
        except (ValueError, TypeError):
            return None

    def next_fn(self, t, k=None, *a):
        keys = list(t.d.keys())
        if k is None:
            idx = 0
        else:
            k = norm(k)
            idx = keys.index(k) + 1 if k in t.d else len(keys)
        if idx >= len(keys):
            return [None]
        kk = keys[idx]
        return [float(kk) if isinstance(kk, int) else kk, t.d[kk]]

    def inext(self, t, i, *a):
        i = int(i) + 1
        v = t.get(float(i))
        if v is None:
            return [None]
        return [float(i), v]

    def select(self, n, *a):
        if n == "#":
            return [float(len(a))]
        return list(a[int(n) - 1:])

    def setmeta(self, t, m, *a):
        t.meta = m
        return [t]

    def error(self, msg=None, *a):
        raise LuaError(tostr(msg))

    def pcall(self, f, *a):
        try:
            return [True] + list(f(*a))
        except LuaError as e:
            return [False, str(e)]

    def ssub(self, s, i, j=None, *a):
        n = len(s)
        i = int(i)
        j = n if j is None else int(j)
        if i < 0:
            i = max(n + i + 1, 1)
        if j < 0:
            j = n + j + 1
        if i < 1:
            i = 1
        return [s[i - 1:j]]

    def tinsert(self, t, a, b=None, *r):
        if b is None:
            t.set(float(t.length() + 1), a)
        else:
            n = t.length()
            for k in range(n, int(a) - 1, -1):
                t.set(float(k + 1), t.get(float(k)))
            t.set(a, b)
        return []

    def tconcat(self, t, sep="", i=1.0, j=None, *a):
        j = t.length() if j is None else int(j)
        return [sep.join(tostr(t.get(float(k))) for k in range(int(i), j + 1))]

    def run(self, src, env=None):
        body = Parser(lex(src)).block()
        sc = Scope()
        r = self.run_block(body, sc)
        return r

    def run_block(self, body, sc):
        for st in body:
            r = self.exec(st, sc)
            if r is not None:
                return r
        return None

    def lookup(self, name, sc):
        s = sc.find(name)
        if s is not None:
            return s.v[name]
        return self.g.get(name)

    def assign(self, tgt, v, sc):
        if tgt[0] == "name":
            s = sc.find(tgt[1])
            if s is not None:
                s.v[tgt[1]] = v
            else:
                self.g.set(tgt[1], v)
        else:
            t = self.ev(tgt[1], sc)
            k = self.ev(tgt[2], sc)
            if isinstance(t, Sym):
                Ctx.effects.append(("setindex", t, k, v))
                return
            if not isinstance(t, Table):
                raise LuaError("index non-table")
            t.set(k, v)

    def evlist(self, exprs, sc):
        out = []
        for i, e in enumerate(exprs):
            if i == len(exprs) - 1 and e[0] in ("call", "method", "vararg"):
                out.extend(self.evmulti(e, sc))
            else:
                out.append(self.ev(e, sc))
        return out

    def evmulti(self, e, sc):
        if e[0] == "vararg":
            return list(self.lookup("...", sc))
        if e[0] == "call":
            f = self.ev(e[1], sc)
            args = self.evlist(e[2], sc)
            if f is None:
                raise LuaError("call nil: %r" % (e[1],))
            return self.callf(f, args)
        if e[0] == "method":
            o = self.ev(e[1], sc)
            args = self.evlist(e[3], sc)
            if isinstance(o, Sym):
                f = Sym("index", o, e[2])
            elif isinstance(o, str):
                f = self.g.get("string").get(e[2])
            else:
                f = o.get(e[2])
            return self.callf(f, [o] + args)
        return [self.ev(e, sc)]

    def callf(self, f, args):
        if f is None:
            raise LuaError("call nil value")
        if isinstance(f, Sym):
            node = Sym("call", f, tuple(args))
            Ctx.effects.append(("call", node))
            return [node]
        if isinstance(f, Table):
            h = f.meta.d.get("__call") if f.meta else None
            return self.callf(h, [f] + args)
        r = f(*args)
        if r is None:
            return []
        return r

    def exec(self, st, sc):
        k = st[0]
        if k == "local":
            vals = self.evlist(st[2], sc)
            for i, n in enumerate(st[1]):
                sc.v[n] = vals[i] if i < len(vals) else None
            return None
        if k == "assign":
            vals = self.evlist(st[2], sc)
            for i, t in enumerate(st[1]):
                self.assign(t, vals[i] if i < len(vals) else None, sc)
            return None
        if k == "exprstmt":
            self.evmulti(st[1], sc)
            return None
        if k == "if":
            for c, b in st[1]:
                if truthy(self.ev(c, sc)):
                    return self.run_block(b, Scope(sc))
            if st[2] is not None:
                return self.run_block(st[2], Scope(sc))
            return None
        if k == "while":
            while truthy(self.ev(st[1], sc)):
                r = self.run_block(st[2], Scope(sc))
                if r is not None:
                    if r[0] == "brk":
                        break
                    return r
            return None
        if k == "repeat":
            while True:
                inner = Scope(sc)
                r = self.run_block(st[1], inner)
                if r is not None:
                    if r[0] == "brk":
                        break
                    return r
                if truthy(self.ev(st[2], inner)):
                    break
            return None
        if k == "fornum":
            a = tonum(self.ev(st[2], sc))
            b = tonum(self.ev(st[3], sc))
            c = tonum(self.ev(st[4], sc)) if st[4] is not None else 1.0
            x = a
            while (c > 0 and x <= b) or (c < 0 and x >= b):
                inner = Scope(sc)
                inner.v[st[1]] = x
                r = self.run_block(st[5], inner)
                if r is not None:
                    if r[0] == "brk":
                        break
                    return r
                x += c
            return None
        if k == "forin":
            vals = self.evlist(st[2], sc)
            f, s, ctl = (vals + [None, None, None])[:3]
            while True:
                rs = self.callf(f, [s, ctl])
                if not rs or rs[0] is None:
                    break
                ctl = rs[0]
                inner = Scope(sc)
                for i, n in enumerate(st[1]):
                    inner.v[n] = rs[i] if i < len(rs) else None
                r = self.run_block(st[3], inner)
                if r is not None:
                    if r[0] == "brk":
                        break
                    return r
            return None
        if k == "do":
            return self.run_block(st[1], Scope(sc))
        if k == "return":
            return ("ret", self.evlist(st[1], sc))
        if k == "break":
            return ("brk",)
        if k == "localfunc":
            sc.v[st[1]] = None
            sc.v[st[1]] = self.ev(st[2], sc)
            return None
        raise LuaError("bad stmt %s" % k)

    def ev(self, e, sc):
        k = e[0]
        if k == "const":
            return e[1]
        if k == "name":
            s = sc.find(e[1])
            if s is not None:
                return s.v[e[1]]
            return self.g.get(e[1])
        if k == "binop":
            op = e[1]
            if op == "and":
                a = self.ev(e[2], sc)
                return self.ev(e[3], sc) if truthy(a) else a
            if op == "or":
                a = self.ev(e[2], sc)
                return a if truthy(a) else self.ev(e[3], sc)
            a = self.ev(e[2], sc)
            b = self.ev(e[3], sc)
            if isinstance(a, Sym) or isinstance(b, Sym):
                return Sym("bin" + op, a, b)
            if op == "+":
                return tonum(a) + tonum(b)
            if op == "-":
                return tonum(a) - tonum(b)
            if op == "*":
                return tonum(a) * tonum(b)
            if op == "/":
                x, y = tonum(a), tonum(b)
                if y == 0:
                    return float("nan") if x == 0 else math.copysign(float("inf"), x)
                return x / y
            if op == "%":
                return lmod(tonum(a), tonum(b))
            if op == "^":
                return math.pow(tonum(a), tonum(b))
            if op == "..":
                return tostr(a) + tostr(b)
            if op == "==":
                return a == b and type(a) == type(b) if isinstance(a, (bool,)) or isinstance(b, bool) else a == b
            if op == "~=":
                return not (a == b and (type(a) == type(b) or not (isinstance(a, bool) or isinstance(b, bool))))
            if op == "<":
                return a < b
            if op == ">":
                return a > b
            if op == "<=":
                return a <= b
            if op == ">=":
                return a >= b
        if k == "unop":
            v = self.ev(e[2], sc)
            if isinstance(v, Sym):
                return Sym("un" + e[1], v)
            if e[1] == "not":
                return not truthy(v)
            if e[1] == "-":
                return -tonum(v)
            if isinstance(v, str):
                return float(len(v))
            return float(v.length())
        if k == "index":
            t = self.ev(e[1], sc)
            key = self.ev(e[2], sc)
            if isinstance(t, Sym):
                return Sym("index", t, key)
            if isinstance(t, Table):
                return t.get(key)
            if isinstance(t, str):
                return self.g.get("string").get(key)
            raise LuaError("index non-table %r key %r expr %r" % (type(t).__name__, key, e[1]))
        if k in ("call", "method", "vararg"):
            r = self.evmulti(e, sc)
            return r[0] if r else None
        if k == "paren":
            return self.ev(e[1], sc)
        if k == "function":
            return Func(self, e[1], e[2], e[3], sc)
        if k == "table":
            t = Table()
            n = 1
            items = e[1]
            for i, it in enumerate(items):
                if it[0] == "kv":
                    t.set(self.ev(it[1], sc), self.ev(it[2], sc))
                else:
                    if i == len(items) - 1 and it[1][0] in ("call", "method", "vararg"):
                        for v in self.evmulti(it[1], sc):
                            t.set(float(n), v)
                            n += 1
                    else:
                        t.set(float(n), self.ev(it[1], sc))
                        n += 1
            return t
        raise LuaError("bad expr %s" % k)
