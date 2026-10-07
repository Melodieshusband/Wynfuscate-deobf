import argparse
import json
import math
import os
import re
import sys

sys.setrecursionlimit(100000)

HERE = os.path.dirname(os.path.abspath(__file__))
for extra in (HERE, os.path.join(HERE, "static", "interp"), os.path.join(HERE, "interp")):
    if os.path.isdir(extra) and extra not in sys.path:
        sys.path.insert(0, extra)

import minilua as ml

BINPRI = {"or": 1, "and": 2, "<": 3, ">": 3, "<=": 3, ">=": 3, "~=": 3, "==": 3, "..": 4, "+": 5, "-": 5, "*": 6, "/": 6, "%": 6, "^": 8}
UNPRI = 7
RIGHT = {"..", "^"}
LUA_KEYWORDS = {"and", "break", "do", "else", "elseif", "end", "false", "for", "function", "if", "in", "local", "nil", "not", "or", "repeat", "return", "then", "true", "until", "while"}


def find_dispatcher(src):
    pat = re.compile(r"local (\w+)=false local (\w+)=false local ((?:\w+,){2,}\w+) if (\w+)<=(\d+) then")
    best = None
    for mt in pat.finditer(src):
        best = mt
    if best is None:
        raise SystemExit("dispatcher not found")
    return {
        "start": best.start() + len(best.group(0)) - len("if %s<=%s then" % (best.group(4), best.group(5))),
        "var": best.group(4),
        "locals": best.group(3).split(","),
        "flags": [best.group(1), best.group(2)],
    }


def find_decode_formula(src, var):
    pat = re.compile(r"local (\w+)=\(\(\(\w+ or 0\)\*(\d+)\+(\d+)\)%(\d+)\)local VARNAME=\1".replace("VARNAME", re.escape(var)))
    mt = pat.search(src)
    if not mt:
        return None
    return {"mul": int(mt.group(2)), "add": int(mt.group(3)), "mod": int(mt.group(4))}


def num_fmt(v):
    if v != v:
        return "(0/0)"
    if v == math.inf:
        return "math.huge"
    if v == -math.inf:
        return "-math.huge"
    if v == int(v) and abs(v) < 1e15:
        return str(int(v))
    return repr(v)


def quote(s):
    out = ['"']
    for ch in s:
        o = ord(ch)
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif o < 32 or o >= 127:
            out.append("\\%03d" % o)
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def lmod(a, b):
    if b == 0:
        return None
    return a - math.floor(a / b) * b


def fold(e):
    if not isinstance(e, tuple):
        return e
    k = e[0]
    if k == "paren":
        inner = fold(e[1])
        if inner[0] in ("const", "name", "index", "call", "method", "paren", "table", "vararg"):
            if inner[0] != "vararg":
                return inner
        return ("paren", inner)
    if k == "binop":
        a = fold(e[2])
        b = fold(e[3])
        if a[0] == "const" and b[0] == "const" and isinstance(a[1], float) and isinstance(b[1], float) and not isinstance(a[1], bool) and not isinstance(b[1], bool):
            op = e[1]
            try:
                if op == "+":
                    return ("const", a[1] + b[1])
                if op == "-":
                    return ("const", a[1] - b[1])
                if op == "*":
                    return ("const", a[1] * b[1])
                if op == "/" and b[1] != 0:
                    return ("const", a[1] / b[1])
                if op == "%":
                    r = lmod(a[1], b[1])
                    if r is not None:
                        return ("const", r)
                if op == "^":
                    return ("const", a[1] ** b[1])
            except (OverflowError, ValueError, ZeroDivisionError):
                pass
        return ("binop", e[1], a, b)
    if k == "unop":
        a = fold(e[2])
        if e[1] == "-" and a[0] == "const" and isinstance(a[1], float) and not isinstance(a[1], bool):
            return ("const", -a[1])
        return ("unop", e[1], a)
    if k == "index":
        return ("index", fold(e[1]), fold(e[2]))
    if k == "call":
        return ("call", fold(e[1]), [fold(x) for x in e[2]])
    if k == "method":
        return ("method", fold(e[1]), e[2], [fold(x) for x in e[3]])
    if k == "table":
        items = []
        for it in e[1]:
            if it[0] == "kv":
                items.append(("kv", fold(it[1]), fold(it[2])))
            else:
                items.append(("pos", fold(it[1])))
        return ("table", items)
    if k == "function":
        return ("function", e[1], e[2], fold_block(e[3]))
    return e


def fold_block(b):
    return [fold_stmt(s) for s in b]


def fold_stmt(s):
    k = s[0]
    if k == "if":
        return ("if", [(fold(c), fold_block(b)) for c, b in s[1]], fold_block(s[2]) if s[2] is not None else None)
    if k == "while":
        return ("while", fold(s[1]), fold_block(s[2]))
    if k == "do":
        return ("do", fold_block(s[1]))
    if k == "fornum":
        return ("fornum", s[1], fold(s[2]), fold(s[3]), fold(s[4]) if s[4] is not None else None, fold_block(s[5]))
    if k == "forin":
        return ("forin", s[1], [fold(x) for x in s[2]], fold_block(s[3]))
    if k == "repeat":
        return ("repeat", fold_block(s[1]), fold(s[2]))
    if k == "assign":
        return ("assign", [fold(x) for x in s[1]], [fold(x) for x in s[2]])
    if k == "local":
        return ("local", s[1], [fold(x) for x in s[2]])
    if k == "localfunc":
        return ("localfunc", s[1], fold(s[2]))
    if k == "return":
        return ("return", [fold(x) for x in s[1]])
    if k == "exprstmt":
        return ("exprstmt", fold(s[1]))
    return s


def prec(e):
    if e[0] == "binop":
        return BINPRI[e[1]]
    if e[0] == "unop":
        return UNPRI
    return 100


def ex(e):
    k = e[0]
    if k == "const":
        v = e[1]
        if v is None:
            return "nil"
        if v is True:
            return "true"
        if v is False:
            return "false"
        if isinstance(v, float):
            return num_fmt(v)
        return quote(v)
    if k == "name":
        return e[1]
    if k == "vararg":
        return "..."
    if k == "paren":
        return "(" + ex(e[1]) + ")"
    if k == "index":
        o = ex_prefix(e[1])
        key = e[2]
        if key[0] == "const" and isinstance(key[1], str) and re.match(r"^[A-Za-z_]\w*$", key[1]) and key[1] not in LUA_KEYWORDS:
            return o + "." + key[1]
        return o + "[" + ex(key) + "]"
    if k == "call":
        return ex_prefix(e[1]) + "(" + ", ".join(ex(a) for a in e[2]) + ")"
    if k == "method":
        return ex_prefix(e[1]) + ":" + e[2] + "(" + ", ".join(ex(a) for a in e[3]) + ")"
    if k == "table":
        parts = []
        for it in e[1]:
            if it[0] == "kv":
                key = it[1]
                if key[0] == "const" and isinstance(key[1], str) and re.match(r"^[A-Za-z_]\w*$", key[1]) and key[1] not in LUA_KEYWORDS:
                    parts.append(key[1] + " = " + ex(it[2]))
                else:
                    parts.append("[" + ex(key) + "] = " + ex(it[2]))
            else:
                parts.append(ex(it[1]))
        return "{" + ", ".join(parts) + "}"
    if k == "unop":
        inner = ex(e[2])
        if prec(e[2]) < UNPRI:
            inner = "(" + inner + ")"
        if e[1] == "not":
            return "not " + inner
        return e[1] + inner
    if k == "binop":
        op = e[1]
        p = BINPRI[op]
        left = ex(e[2])
        right = ex(e[3])
        lp = prec(e[2])
        rp = prec(e[3])
        if lp < p or (lp == p and op in RIGHT):
            left = "(" + left + ")"
        if rp < p or (rp == p and op not in RIGHT):
            right = "(" + right + ")"
        if op == "-" and right.startswith("-"):
            right = "(" + right + ")"
        return left + " " + op + " " + right
    if k == "function":
        params = list(e[1])
        if e[2]:
            params.append("...")
        body = e[3]
        if not body:
            return "function(" + ", ".join(params) + ") end"
        return "function(" + ", ".join(params) + ")\n" + block(body, 1, True) + "\nend"
    return "nil"


def ex_prefix(e):
    s = ex(e)
    if e[0] in ("name", "index", "call", "method", "paren"):
        return s
    return "(" + s + ")"


def block(stmts, depth, inline=False):
    lines = []
    for s in stmts:
        lines.append(stmt(s, depth))
    return "\n".join(lines)


def indent_multiline(text, depth):
    pad = "  " * depth
    parts = text.split("\n")
    return parts[0] + "".join("\n" + pad + p for p in parts[1:])


def stmt(s, depth):
    pad = "  " * depth
    k = s[0]
    if k == "if":
        out = []
        for i, (c, b) in enumerate(s[1]):
            head = ("if " if i == 0 else pad + "elseif ") + ex(c) + " then"
            out.append(head)
            if b:
                out.append(block(b, depth + 1))
        if s[2]:
            out.append(pad + "else")
            out.append(block(s[2], depth + 1))
        out.append(pad + "end")
        return "\n".join([pad + out[0]] + out[1:])
    if k == "while":
        return pad + "while " + ex(s[1]) + " do\n" + (block(s[2], depth + 1) + "\n" if s[2] else "") + pad + "end"
    if k == "do":
        return pad + "do\n" + (block(s[1], depth + 1) + "\n" if s[1] else "") + pad + "end"
    if k == "fornum":
        step = ", " + ex(s[4]) if s[4] is not None else ""
        return pad + "for %s = %s, %s%s do\n" % (s[1], ex(s[2]), ex(s[3]), step) + (block(s[5], depth + 1) + "\n" if s[5] else "") + pad + "end"
    if k == "forin":
        return pad + "for %s in %s do\n" % (", ".join(s[1]), ", ".join(ex(x) for x in s[2])) + (block(s[3], depth + 1) + "\n" if s[3] else "") + pad + "end"
    if k == "repeat":
        return pad + "repeat\n" + (block(s[1], depth + 1) + "\n" if s[1] else "") + pad + "until " + ex(s[2])
    if k == "assign":
        return pad + indent_multiline(", ".join(ex(x) for x in s[1]) + " = " + ", ".join(ex(x) for x in s[2]), depth)
    if k == "local":
        text = "local " + ", ".join(s[1])
        if s[2]:
            text += " = " + ", ".join(ex(x) for x in s[2])
        return pad + indent_multiline(text, depth)
    if k == "localfunc":
        f = s[2]
        params = list(f[1])
        if f[2]:
            params.append("...")
        head = pad + "local function %s(%s)" % (s[1], ", ".join(params))
        if not f[3]:
            return head + " end"
        return head + "\n" + block(f[3], depth + 1) + "\n" + pad + "end"
    if k == "return":
        return pad + ("return " + ", ".join(ex(x) for x in s[1]) if s[1] else "return")
    if k == "break":
        return pad + "break"
    if k == "exprstmt":
        return pad + indent_multiline(ex(s[1]), depth)
    return pad + "nil"


def is_var_cmp(c, var, ops):
    return c[0] == "binop" and c[1] in ops and c[2] == ("name", var) and c[3][0] == "const" and isinstance(c[3][1], float)


def collect(node, var, out, path):
    if node[0] != "if":
        return False
    clauses, els = node[1], node[2]
    handled = False
    for c, b in clauses:
        if is_var_cmp(c, var, ("==",)):
            out.setdefault(int(c[3][1]), []).append(b)
            handled = True
        elif is_var_cmp(c, var, ("<=", "<", ">=", ">")):
            for s in b:
                if collect(s, var, out, path):
                    handled = True
        else:
            for s in b:
                if collect(s, var, out, path):
                    handled = True
    if els:
        for s in els:
            if collect(s, var, out, path):
                handled = True
    return handled


def used_names(stmts, acc):
    def walk(n):
        if isinstance(n, tuple):
            if n and n[0] == "name":
                acc.add(n[1])
            for x in n:
                walk(x)
        elif isinstance(n, list):
            for x in n:
                walk(x)
    walk(stmts)
    return acc


def classify(body, local_names, field_names):
    names = used_names(body, set())
    text = "\n".join(stmt(s, 0) for s in body)
    tags = []
    if "Zp(" in text or re.search(r"Zp\(", text):
        tags.append("closure")
    if re.search(r"\bVE\[[^\]]+\]\s*=\s*", text):
        tags.append("writes_reg")
    if re.search(r"\bVE\[", text):
        tags.append("reads_reg")
    if re.search(r"\(\s*VE\[[^\]]+\]\s*[,)]", text) or re.search(r"=\s*VE\[[^\]]+\]\(", text):
        tags.append("call")
    if re.search(r"\bVY\s*=\s*", text):
        tags.append("sets_pc")
    if re.search(r"\bwhile\b|\bfor\b", text):
        tags.append("loop")
    if re.search(r"\bpcall\b|\bxpcall\b", text):
        tags.append("protected")
    return tags



TEMPS={"ij","ie","iv","iM","iQ","iy","i0","i3","i6"}

def walk_names(n, acc):
    if isinstance(n, tuple):
        if n and n[0]=="name": acc.append(n[1])
        for x in n: walk_names(x, acc)
    elif isinstance(n, list):
        for x in n: walk_names(x, acc)

def contains_tamper(b):
    t=block(b,0)
    return bool(re.search(r"\biN\[[^\]]+\]\s*=\s*\d+", t))

def fetch_idx(e):
    if e[0]=="paren": e=e[1]
    if e[0]=="binop" and e[1]=="or" and e[3]==("const",None):
        a=e[2]
        if a[0]=="binop" and a[1]=="and" and a[3]==("name","Su"):
            c=a[2]
            if c[0]=="call" and len(c[2])==2 and c[2][1]==("name","Gv"):
                return c[2][0]
    return None

def sub_expr(e, f):
    if not isinstance(e, tuple): return e
    r=f(e)
    if r is not None: return r
    k=e[0]
    if k=="binop": return ("binop",e[1],sub_expr(e[2],f),sub_expr(e[3],f))
    if k=="unop": return ("unop",e[1],sub_expr(e[2],f))
    if k=="paren": return ("paren",sub_expr(e[1],f))
    if k=="index": return ("index",sub_expr(e[1],f),sub_expr(e[2],f))
    if k=="call": return ("call",sub_expr(e[1],f),[sub_expr(x,f) for x in e[2]])
    if k=="method": return ("method",sub_expr(e[1],f),e[2],[sub_expr(x,f) for x in e[3]])
    if k=="table": return ("table",[(it[0],)+tuple(sub_expr(x,f) for x in it[1:]) for it in e[1]])
    return e

def map_stmt(s, f):
    k=s[0]
    if k=="if": return ("if",[(sub_expr(c,f),[map_stmt(x,f) for x in b]) for c,b in s[1]],[map_stmt(x,f) for x in s[2]] if s[2] is not None else None)
    if k=="assign": return ("assign",[sub_expr(x,f) for x in s[1]],[sub_expr(x,f) for x in s[2]])
    if k=="local": return ("local",s[1],[sub_expr(x,f) for x in s[2]])
    if k=="exprstmt": return ("exprstmt",sub_expr(s[1],f))
    if k=="return": return ("return",[sub_expr(x,f) for x in s[1]])
    if k=="while": return ("while",sub_expr(s[1],f),[map_stmt(x,f) for x in s[2]])
    if k=="do": return ("do",[map_stmt(x,f) for x in s[1]])
    return s

def fetch_rule(e):
    i=fetch_idx(e)
    if i is not None:
        return ("call",("name","K"),[i])
    return None

def selector_names(b):
    out=set()
    for s in b:
        if s[0]=="assign" and len(s[1])==1 and s[1][0][0]=="name" and s[1][0][1] in TEMPS:
            t=ex(s[2][0])
            if re.search(r"% 3\)?$",t): out.add(s[1][0][1])
    return out

def normalize(b, sel0=frozenset()):
    b=fold_block(b)
    sel=set(sel0)|selector_names(b)
    out=[]
    for s in b:
        if s[0]=="assign" and len(s[1])==1 and s[1][0]==("name","Vz"): continue
        if s[0]=="assign" and len(s[1])==1 and s[1][0][0]=="name" and s[1][0][1] in sel: continue
        if s[0]=="assign" and len(s[1])==1 and s[1][0][0]=="name" and s[1][0][1] in TEMPS and s[2]==[("const",None)]: continue
        if s[0]=="if" and contains_tamper(s[1][0][1]): continue
        if s[0]=="if" and s[1][0][0]==("const",False): continue
        if s[0]=="if" and s[1][0][0][0]=="binop" and s[1][0][0][2]==("const",False): continue
        if s[0]=="local" and len(s[1])==1 and s[2] and "Ny[" in ex(s[2][0]) and s[1][0] in ("VU",): continue
        if s[0]=="local" and s[1]==["hS"]: continue
        if s[0]=="if" and s[1][0][0][0]=="binop" and s[1][0][0][1]=="==" and s[1][0][0][2][0]=="name" and s[1][0][0][2][1] in sel:
            body=s[1][0][1]
            out.extend(normalize(body,sel)); continue
        if s[0]=="if":
            s=("if",[(c,normalize(bb,sel)) for c,bb in s[1]],normalize(s[2],sel) if s[2] is not None else None)
        out.append(map_stmt(s,fetch_rule))
    return out

def uses(b):
    acc=[]; walk_names(b,acc); return acc

def dead_store(b):
    changed=True
    while changed:
        changed=False
        names=uses(b)
        new=[]
        for s in b:
            if s[0]=="assign" and len(s[1])==1 and s[1][0][0]=="name" and s[1][0][1] in TEMPS:
                n=s[1][0][1]
                rhs=ex(s[2][0])
                if names.count(n)==1 and not re.search(r"\(", rhs.replace("K(","")):
                    changed=True; continue
            new.append(s)
        b=new
    return b

def inline(b):
    changed=True
    while changed:
        changed=False
        for i,s in enumerate(b):
            if s[0]=="assign" and len(s[1])==1 and s[1][0][0]=="name" and s[1][0][1] in TEMPS and len(s[2])==1:
                n=s[1][0][1]
                rest=b[i+1:]
                cnt=uses(rest).count(n)
                total=uses(b).count(n)
                writes=sum(1 for x in b if x[0]=="assign" and x[1][0]==("name",n))
                if writes==1 and cnt==1 and total==2 and all(x[0]!="if" or n not in uses(x) for x in rest[:0]):
                    rhs=s[2][0]
                    def f(e,n=n,rhs=rhs):
                        if e==("name",n): return rhs
                        return None
                    nb=b[:i]+[map_stmt(x,f) for x in rest]
                    b=nb; changed=True; break
    return b

def const_prop(b):
    changed=True
    while changed:
        changed=False
        for i,s in enumerate(b):
            if s[0]=="assign" and len(s[1])==1 and s[1][0][0]=="name" and s[1][0][1] in TEMPS and len(s[2])==1 and s[2][0][0]=="const":
                n=s[1][0][1]
                writes=sum(1 for x in b if x[0]=="assign" and x[1][0]==("name",n))
                if writes==1:
                    val=s[2][0]
                    f=lambda e,n=n,val=val: val if e==("name",n) else None
                    b=b[:i]+[map_stmt(x,f) for x in b[i+1:]]
                    changed=True
                    break
        b=fold_block(b)
        nb=[]
        for s in b:
            if s[0]=="if":
                s=("if",[(c,const_prop(bb)) for c,bb in s[1]],const_prop(s[2]) if s[2] is not None else None)
                c0=s[1][0][0]
                if c0[0]=="binop" and c0[2][0]=="const" and c0[3][0]=="const":
                    a,bv=c0[2][1],c0[3][1]
                    try:
                        r={"==":a==bv,"~=":a!=bv,">":a>bv,"<":a<bv,">=":a>=bv,"<=":a<=bv}[c0[1]]
                    except Exception:
                        r=None
                    if r is True and len(s[1])==1:
                        nb.extend(s[1][0][1]); changed=True; continue
                    if r is False and len(s[1])==1:
                        if s[2]: nb.extend(s[2])
                        changed=True; continue
            nb.append(s)
        b=nb
    return b

def clean(b):
    return inline(dead_store(const_prop(normalize(b))))


TRAILER = re.compile(r" ; if lo and lR\(VE\[[^\]]+\]+\) == lx and Ny\[lQ\[\d+\]\]\(VE\[[^\]]+\]+\) == VE\[[^\]]+\]+ then ; +VE\[[^\]]+\]+ = Ny\[lQ\[\d+\]\]\(VE\[[^\]]+\]+\) ; end$")

ARITH = {"+": "ADD", "-": "SUB", "*": "MUL", "/": "DIV", "%": "MOD", "^": "POW"}
NEG = {"==": "~=", "~=": "==", "<": ">=", "<=": ">", ">": "<=", ">=": "<"}
CMPNAME = {"==": "JEQ", "~=": "JNE", "<": "JLT", "<=": "JLE", ">": "JGT", ">=": "JGE"}


def flat(text):
    return " ; ".join(x.strip() for x in text.split("\n") if x.strip())


def classify_semantic(t):
    t = TRAILER.sub("", t)
    if t == "" or t == "VY = VY + 1" or t == "VY = VY + 1 ; VV = true":
        return "NOP", "no operation"
    if t == "VY = im[VY] ; VV = true":
        return "JMP", "pc = jump_table[pc]"
    if t in ("VE[il[VY]] = VE[iB[VY]]", "VE[il[VY]] = ({VE[iB[VY]]})[1]"):
        return "MOVE", "R[A] = R[B]"
    if t == "VE[iB[VY]] = VE[il[VY]]":
        return "MOVE", "R[B] = R[A]"
    if t == "VE[il[VY]] = VE[iB[VY]] ; VE[iG[VY]] = VE[ix[VY]]":
        return "MOVE2", "R[A] = R[B]; R[C] = R[D]"
    if t == "VE[il[VY]] = nil":
        return "LOADNIL", "R[A] = nil"
    if t == "VE[iB[VY]] = nil":
        return "LOADNIL", "R[B] = nil"
    if t == "VE[il[VY]] = nil ; VE[il[VY]] = nil":
        return "LOADNIL", "R[A] = nil"
    if t.startswith("ie = iB[VY] + (iG[VY] * 256) + (ix[VY] * 65536)") or t.startswith("ij = iB[VY] + (iG[VY] * 256) + (ix[VY] * 65536)"):
        return "LOADI32", "R[A] = int32(B | C<<8 | D<<16 | E<<24)"
    if t == "VE[il[VY]] = {}":
        return "NEWTABLE", "R[A] = {}"
    if t.startswith("ie = {} ; iM = Ny"):
        return "NEWTABLE_SHAPED", "R[A] = {preset keys}"
    if t == "VE[il[VY]] = ({K(Xw[iB[VY] + (iG[VY] * 256) + 1])})[1]":
        return "LOADK", "R[A] = K[B | C<<8]"
    if re.match(r"^ij = iB\[VY\] \+ \(iG\[VY\] \* 256\) ; if ij >= 32768 then ; +ij = ij - 65536 ; end ; VE\[il\[VY\]\] = ij$", t):
        return "LOADI", "R[A] = int16(B | C<<8)"
    if t.startswith("ij = iB[VY] + (iG[VY] * 256) ; if ij >= 32768 then ;") and "VE[ix[VY]] = ij" in t:
        return "LOADI2", "R[A] = int16(B|C<<8); R[D] = int16(E|F<<8)"
    if t == "VE[il[VY]] = -VE[iB[VY]]":
        return "UNM", "R[A] = -R[B]"
    if t == "VE[il[VY]] = not VE[iB[VY]]":
        return "NOT", "R[A] = not R[B]"
    if t == "VE[il[VY]] = #VE[iB[VY]]":
        return "LEN", "R[A] = #R[B]"
    m = re.match(r"^VE\[il\[VY\]\] = VE\[iB\[VY\]\] ([-+*/%^]) VE\[iG\[VY\]\]$", t)
    if m:
        return ARITH[m.group(1)], "R[A] = R[B] %s R[C]" % m.group(1)
    if t.startswith("if lR(VE[iB[VY]]) == lx and lR(VE[iG[VY]]) == lx then ; VE[il[VY]] = Ng.pow"):
        return "POW", "R[A] = R[B] ^ R[C]"
    m = re.search(r"VE\[ij\] = ie ([-+*/%^]) iv ; else ; +VE\[ij\] = iv \1 ie", t)
    if m and "iq[VY] ~= 0" in t:
        return ARITH[m.group(1)] + "_I", "R[A] = R[B] %s imm16(C|D<<8), E selects operand order" % m.group(1)
    m = re.search(r"VE\[ij\] = iQ ([-+*/%^]) iv ; else", t)
    if m and "iq[VY] ~= 0" in t:
        return ARITH[m.group(1)] + "_I", "R[A] = R[B] %s imm16(C|D<<8), E selects operand order" % m.group(1)
    if t.startswith("ie = iG[VY] + (ix[VY] * 256) ;") and "iy = ie / iv" in t and "iK[iD[VY] + 8]" in t:
        return "DIV_I_JMP", "R[A] = R[B] / imm16; then jump"
    m = re.match(r"^ij = 0 ; ij = \(iG\[VY\] or 0\) \+ \(\(ix\[VY\] or 0\) \* 256\) ; VE\[il\[VY\]\] = VE\[iB\[VY\]\] ([-+*/%^]) \(\(AL\[ij\] or Ad\(ij\)\) or 0\)", t)
    if m:
        return ARITH[m.group(1)] + "_K", "R[A] = R[B] %s NK[C|D<<8]" % m.group(1)
    if t.startswith("iM = iB[VY] + (iG[VY] * 256) ; VE[il[VY]] = (AL[iM] or Ad(iM)) or 0"):
        return "LOADNUM", "R[A] = NK[B|C<<8]"
    m = re.match(r"^iQ = iu ; if (not )?\(?VE\[il\[VY\]\] (==|~=|<=|>=|<|>) VE\[ix\[VY\]\]\)? then ; +iy = iQ and iQ\[\(VY \+ ia\)\] or nil ;", t)
    if m:
        op = NEG[m.group(2)] if m.group(1) else m.group(2)
        return CMPNAME[op], "if R[A] %s R[D] then jump" % op
    if t.startswith("if VE[il[VY]] then ; VY = im[VY]") or t.startswith("ij = VE[il[VY]] ; if ij ~= nil and ij then ; VY = im[VY]"):
        return "JT", "if R[A] then jump"
    if t.startswith("if not VE[il[VY]] then ; VY = im[VY]") or t.startswith("if (VE[il[VY]] == nil or not VE[il[VY]]) then ; VY = im[VY]"):
        return "JF", "if not R[A] then jump"
    if t.startswith("VE[il[VY]] = VE[iB[VY]] ; if not VE[il[VY]] then ; VY = im[VY]"):
        return "TESTSET_JF", "R[A] = R[B]; if not R[A] then jump"
    if t.startswith("ij = VE[iB[VY]] ; if ij then ; VE[il[VY]] = VE[iG[VY]] ; else ; VE[il[VY]] = ij ; end"):
        return "AND", "R[A] = R[B] and R[C]"
    if t.startswith("ij = VE[iB[VY]] ; ie = VE[iG[VY]] ; if ij then ; ie = ij ; end ; VE[il[VY]] = ie"):
        return "OR", "R[A] = R[B] or R[C]"
    if t.startswith("VE[il[VY]] = (iB[VY] ~= 0) ; if iG[VY] ~= 0 then ; VY = VY + 1"):
        return "LOADBOOL", "R[A] = (B ~= 0); if C ~= 0 then skip next"
    if t.startswith("VE[iG[VY]] = (ix[VY] ~= 0)"):
        return "LOADBOOL_JMP", "R[C] = (D ~= 0); then relative jump"
    if t.startswith("VE[il[VY]] = (iB[VY] ~= 0) ; if not VE[il[VY]]"):
        return "LOADBOOL_JF", "R[A] = (B ~= 0); if not R[A] then jump"
    if t == "VE[il[VY]] = VE[iB[VY]][VE[iG[VY]]]" or t == "iM = 0 ; if iM > 0 then ; iM = iM - 1 ; end ; VE[il[VY]] = VE[iB[VY]][VE[iG[VY]]]":
        return "GETTABLE", "R[A] = R[B][R[C]]"
    if t == "VE[il[VY]] = VE[iB[VY]][iG[VY] + 1]":
        return "GETINDEX", "R[A] = R[B][C + 1]"
    if t.startswith("ij = iG[VY] + (ix[VY] * 256) ; ie = VC[VY]") and t.endswith("VE[il[VY]] = VE[iB[VY]][ie]"):
        return "GETFIELD", "R[A] = R[B][K[C|D<<8]]"
    if t.startswith("ij = il[VY] ; iv = iG[VY] + (ix[VY] * 256) ; iM = VE[iB[VY]] ; iQ = K(Xw[iv + 1]) ; iy = iM and iM[iQ] or nil"):
        return "GETFIELD_META", "R[A] = R[B][K[C|D<<8]] with fallback lookup"
    if t.startswith("ij = VE[iB[VY]] ; if ij then ; ij[VE[iG[VY]]] = VE[il[VY]]"):
        return "SETTABLE", "R[B][R[C]] = R[A]"
    if t.startswith("ij = VE[il[VY]] ; if ij then ; ij[iB[VY] + 1] = VE[iG[VY]]"):
        return "SETINDEX", "R[A][B + 1] = R[C]"
    if t.startswith("ie = K(Xw[ix[VY] + (iq[VY] * 256) + 1]) ; VE[il[VY]] = ie ; iv = VE[iB[VY]]"):
        return "LOADK_SETTABLE", "R[A] = K[D|E<<8]; R[B][R[C]] = R[A]"
    if re.match(r"^Ny\[lQ\[\d+\]\]\[K\(Xw\[iB\[VY\] \+ \(iG\[VY\] \* 256\) \+ 1\]\)\] = VE\[il\[VY\]\]$", t):
        return "SETGLOBAL", "G[K[B|C<<8]] = R[A]"
    if ("i6 = Ny[lQ[40210]]" in t and "[^.]+" not in t) or re.search(r"if i6 and i6\[i[je]\] then", t):
        if "Ny[lQ[" in t and ("K(Xw[ij + 1])" in t or "VE[il[VY]] = Ny[lQ[" in t):
            return "GETGLOBAL", "R[A] = G[name(B|C<<8)]"
    if "Vc[" in t and "iv[4595] = i3" in t:
        return "SETUPVAL", "UV[B] = R[A]"
    if "Vc[" in t and "iv[6096]" in t:
        return "GETUPVAL", "R[A] = UV[B]"
    if "Zp(" in t:
        return "CLOSURE", "R[A] = closure(proto[B|C<<8]) with captured upvalues"
    if "VF = {}" in t:
        return "VARARG_PACK", "pack extra args from R[A+1]"
    if "VF[lt]" in t and "VF[T7]" in t:
        return "VARARG", "R[A..] = ..."
    if "iy[iM + i0] = VE[ie + i0]" in t:
        return "SETLIST", "R[A][offset+i] = R[B+i]"
    if "Vh[ij] = iy" in t:
        return "FORPREP", "numeric for prepare"
    if "VE[ij + 2] = iy" in t and "iQ > 0 and iy <= iM" in t:
        return "FORLOOP", "numeric for step"
    if "iM = iM .. VE[iQ]" in t:
        return "CONCAT", "R[A] = R[B] .. ... .. R[C]"
    if "return Ib(VE" in t:
        return "RETURN", "return R[A..A+B-2]"
    if t.startswith("local Ib = N8 ;") and "iM(Ib(VE, ij + 1" in t:
        return "CALL", "R[A](R[A+1..]) with B args, C results"
    if t.startswith("ij = il[VY] ; ie = iB[VY] ; iv = iG[VY] ; local h9 = VJ or 0"):
        return "CALL", "R[A](R[A+1..]) with B args, C results"
    if t.startswith("local Ib = N8 ; ij = il[VY] ; iv = ((iB[VY] - iG[VY]) % 256)"):
        return "CALL_ENC", "R[A](R[A+1]); results (B-C)%256"
    if t.startswith("local iQ = VE[iG[VY]] ; VE[il[VY]] = VE[iB[VY]](iQ)") or t == "local iQ = VE[iG[VY]] ; VE[il[VY]] = VE[iB[VY]](iQ)":
        return "CALL_1", "R[A] = R[B](R[C])"
    if t == "VE[il[VY]] = VE[iB[VY]]()":
        return "CALL_0", "R[A] = R[B]()"
    if t == "iv = iG[VY] ; local iQ = VE[iv] ; local iy = VE[iv + 1] ; VE[il[VY]] = VE[iB[VY]](iQ, iy)":
        return "CALL_2", "R[A] = R[B](R[C], R[C+1])"
    if t == "iv = iG[VY] ; local iQ = VE[iv] ; local iy = VE[iv + 1] ; VE[iB[VY]](iQ, iy)":
        return "CALL_2_NORET", "R[B](R[C], R[C+1])"
    if t == "local iQ = VE[iG[VY]] ; VE[iB[VY]](iQ)":
        return "CALL_1_NORET", "R[B](R[C])"
    if "local ho = K(Xw[iS[VY] + (iX[VY] * 256) + 1])" in t and "VE[ij + 2] = ho" in t:
        return "CALL_METHOD_K", "R[A+1] = R[B]; R[A+2] = K[F|G<<8]; R[A+1][K[D|E<<8]](R[A+1], R[A+2]); results C; then jump"
    if "local iM = K(Xw[iG[VY] + (ix[VY] * 256) + 1]) ; VE[ij + 1] = iM" in t:
        return "CALL_K1", "R[A+1] = K[C|D<<8]; R[A](R[A+1]); results B; then jump"
    if "VE[ij + 1] = iv ; iM = VE[ij]" in t:
        return "CALL_I1", "R[A+1] = imm16(C|D<<8); R[A](R[A+1]); results B; then jump"
    if "VE[ij + 2] = iM ; iQ = VE[ij + 1] ; iy = VE[ij]" in t:
        return "CALL_SELF_R", "R[A+2] = R[B]; R[A](R[A+1], R[A+2]); results C; then jump"
    if "VE[ij + 1] = iQ ; iy = VE[iG[VY]] ; VE[ij + 2] = iy" in t:
        return "CALL_R2", "R[A+1] = R[B]; R[A+2] = R[C]; R[A](R[A+1], R[A+2]); results D; then jump"
    if "VE[ij + 1] = iM ; iQ = VE[ij]" in t:
        return "CALL_R1", "R[A+1] = R[B]; R[A](R[A+1]); results C; then jump"
    if "VE[ij + 1] = " in t and "lR(" in t:
        return "SELF_CALL", "method call: R[A+1] = obj; R[A] = obj[K]; call"
    if t.startswith("ij = il[VY] ; if iN[VY + 1] == 51") and "Ng.floor" in t:
        return "CALL_BUILTIN", "fused builtin lookup for the following CALL"
    if re.search(r"T1\((ie|qt)\)", t) and "iK[iD[VY] + 4 + iv]" in t:
        return "TFORPREP", "generic for: resolve iterator, then jump"
    if "T9 ~= 0" in t and "VE[ij + 2] = T1" in t:
        return "TFORCALL", "generic for: call iterator, assign loop variables"
    if "iy = Ny[lQ[l3[46726]]]" in t or ("match(" in t and "VE[" not in t):
        return "ANTI_TAMPER_NOP", "environment probe, no VM effect"
    if "[6096] = " in t and "Vw[iQ]" in t:
        return "UPVAL_CAPTURE", "describe one captured upvalue for the preceding CLOSURE"
    if "ij = ((ij * 256) + ie)" in t and "16777216" in t:
        return "LOADI24", "R[A] = int24(B | C<<8 | D<<16) big-endian"
    if "iM = iM(ij, ie)" in t or ("iv[K(136)]" in t and "ij / ie" in t):
        return "IDIV", "R[A] = floor(R[B] / R[C]) with metamethod"
    if "for iQ in NK[" in t and "[^.]+" in t:
        return "GETGLOBAL_PATH", "R[A] = G.a.b.c resolved from dotted name"
    m = re.match(r"^ij = il\[VY\] ; ie = iG\[VY\] \+ \(ix\[VY\] \* 256\) ;.*VE\[ij\] = ie ([-+*/%^]) iQ ; else ; +VE\[ij\] = iQ \1 ie.*iK\[iD\[VY\] \+ 8\]", t)
    if m:
        return ARITH[m.group(1)] + "_I_JMP", "R[A] = R[B] %s imm16; then jump" % m.group(1)
    if "while ie ~= 0 do" in t:
        return "LOADNIL_MASK", "clear registers selected by bitmask"
    if "iK[iQ]" in t and "iD[VY]" in t and "+ 4" in t:
        return "JMP_REL", "pc += offset(B|C<<8)"
    if "VE[" not in t and "return" not in t:
        return "ANTI_TAMPER_NOP", "environment probe, no VM effect"
    if t.startswith("hs = iB ;") or t.startswith("local T1 = cn[6154]"):
        return "ANTI_TAMPER_NOP", "integrity probe"
    return "UNKNOWN", "not classified"


def semantic_table(found):
    families = {}
    rows = {}
    for op in sorted(found):
        merged = []
        for b in found[op]:
            merged.extend(b)
        text = block(clean(merged), 0)
        name, desc = classify_semantic(flat(text))
        rows[op] = {"name": name, "desc": desc, "canon": hash(text) & 0xFFFFFFFF, "text": text}
    groups = {}
    for op, r in rows.items():
        groups.setdefault(r["text"], []).append(op)
    for text, ops in groups.items():
        for op in ops:
            rows[op]["aliases"] = [x for x in ops if x != op]
    return rows



def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("-o", "--out", default=None)
    ap.add_argument("--var", default=None)
    ap.add_argument("--no-fold", action="store_true")
    args = ap.parse_args()

    src = open(args.source, encoding="latin-1").read()
    info = find_dispatcher(src)
    var = args.var or info["var"]
    formula = find_decode_formula(src, var)

    toks = ml.lex(src[info["start"]:])
    parser = ml.Parser(toks)
    tree = parser.stmt()

    found = {}
    collect(tree, var, found, [])

    base = args.out or os.path.splitext(os.path.basename(args.source))[0]
    out_dir = os.path.dirname(os.path.abspath(base)) if os.path.dirname(base) else os.getcwd()
    stem = os.path.basename(base)
    os.makedirs(out_dir, exist_ok=True)

    handlers_path = os.path.join(out_dir, stem + "_handlers.lua")
    clean_path = os.path.join(out_dir, stem + "_clean.lua")
    index_path = os.path.join(out_dir, stem + "_opcodes.json")
    table_path = os.path.join(out_dir, stem + "_optable.txt")

    index = {}
    chunks = []
    for op in sorted(found):
        bodies = found[op]
        merged = []
        for b in bodies:
            merged.extend(b)
        if not args.no_fold:
            merged = fold_block(merged)
        text = block(merged, 1)
        tags = classify(merged, info["locals"], [])
        index[op] = {"variants": len(bodies), "lines": text.count("\n") + 1, "tags": tags}
        chunks.append("if %s == %d then\n%s\nend" % (var, op, text))

    with open(handlers_path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(chunks) + "\n")

    sem = semantic_table(found)
    clean_chunks = []
    for op in sorted(sem):
        clean_chunks.append("if %s == %d then\n%s\nend" % (var, op, block(clean(sum([list(b) for b in found[op]], [])), 1)))
        index[op]["name"] = sem[op]["name"]
        index[op]["desc"] = sem[op]["desc"]
        index[op]["aliases"] = sem[op]["aliases"]
    with open(clean_path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(clean_chunks) + "\n")

    lines = []
    for op in sorted(sem):
        r = sem[op]
        lines.append("%3d  %-16s %s%s" % (op, r["name"], r["desc"], ("  [alias of %s]" % ",".join(str(x) for x in r["aliases"])) if r["aliases"] else ""))
    with open(table_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    meta = {
        "dispatch_var": var,
        "locals": info["locals"],
        "decode": formula,
        "opcodes": index,
    }
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1)

    unknown = [op for op in sem if sem[op]["name"] == "UNKNOWN"]
    names = sorted({sem[op]["name"] for op in sem})
    print("dispatch variable: %s" % var)
    print("decode formula: %s" % (formula,))
    print("handlers found: %d" % len(found))
    print("distinct operations: %d" % len(names))
    print("unclassified: %s" % unknown)
    print("files: %s, %s, %s, %s" % (handlers_path, clean_path, table_path, index_path))


if __name__ == "__main__":
    main()
