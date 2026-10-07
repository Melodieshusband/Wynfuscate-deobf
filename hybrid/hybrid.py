import io
import contextlib
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ENGINE = os.path.join(ROOT, "engine")
sys.path.insert(0, ENGINE)
ARGS = list(sys.argv)
with contextlib.redirect_stdout(io.StringIO()):
    import symrun as R
    import wyn_opcodes as wo
    import decompile as DC
m = R.m
src = R.src
p = R.p
V = R.V

CMP = {"==": "CEQ", "~=": "CNE", "<": "CLT", ">": "CGT", "<=": "CLE", ">=": "CGE"}


def tx_expr(e):
    k = e[0]
    if k == "binop":
        a = tx_expr(e[2])
        b = tx_expr(e[3])
        if e[1] in CMP:
            return ("call", ("name", CMP[e[1]]), [a, b])
        return ("binop", e[1], a, b)
    if k == "unop":
        x = tx_expr(e[2])
        if e[1] == "not":
            return ("call", ("name", "NOT"), [x])
        return ("unop", e[1], x)
    if k == "index":
        return ("index", tx_expr(e[1]), tx_expr(e[2]))
    if k == "call":
        return ("call", tx_expr(e[1]), [tx_expr(a) for a in e[2]])
    if k == "method":
        return ("method", tx_expr(e[1]), e[2], [tx_expr(a) for a in e[3]])
    if k == "paren":
        return ("paren", tx_expr(e[1]))
    if k == "function":
        return ("function", e[1], e[2], tx_block(e[3]))
    if k == "table":
        items = []
        for it in e[1]:
            if it[0] == "kv":
                items.append(("kv", tx_expr(it[1]), tx_expr(it[2])))
            else:
                items.append(("pos", tx_expr(it[1])))
        return ("table", items)
    return e


def cond(c):
    return ("call", ("name", "D"), [tx_expr(c)])


def tx_stmt(s):
    k = s[0]
    if k == "local":
        return ("local", s[1], [tx_expr(x) for x in s[2]])
    if k == "assign":
        return ("assign", [tx_expr(x) for x in s[1]], [tx_expr(x) for x in s[2]])
    if k == "exprstmt":
        return ("exprstmt", tx_expr(s[1]))
    if k == "if":
        return ("if", [(cond(c), tx_block(b)) for c, b in s[1]], tx_block(s[2]) if s[2] is not None else None)
    if k == "while":
        return ("while", cond(s[1]), tx_block(s[2]))
    if k == "repeat":
        return ("repeat", tx_block(s[1]), cond(s[2]))
    if k == "fornum":
        return ("fornum", s[1], tx_expr(s[2]), tx_expr(s[3]), tx_expr(s[4]) if s[4] is not None else None, tx_block(s[5]))
    if k == "forin":
        return ("forin", s[1], [tx_expr(x) for x in s[2]], tx_block(s[3]))
    if k == "do":
        return ("do", tx_block(s[1]))
    if k == "return":
        return ("return", [tx_expr(x) for x in s[1]])
    if k == "localfunc":
        return ("localfunc", s[1], tx_expr(s[2]))
    return s


def tx_block(b):
    return [tx_stmt(s) for s in b]


def lua_value(v, depth=0):
    if isinstance(v, m.Table):
        items = []
        for k, x in v.d.items():
            if isinstance(k, str):
                ks = "[%s]" % lua_value(k)
            else:
                ks = "[%d]" % int(k)
            items.append("%s=%s" % (ks, lua_value(x, depth + 1)))
        return "{" + ",".join(items) + "}"
    if v is None:
        return "nil"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return str(int(v)) if v == int(v) else repr(v)
    if isinstance(v, int):
        return str(v)
    if isinstance(v, str):
        return '"' + "".join("\\%03d" % ord(c) if (c in '\\"' or ord(c) < 32 or ord(c) > 126) else c for c in v) + '"'
    return "nil"


PRELUDE = r'''
local ENV = getfenv(1)
local OUT = {}
local function emit(...)
  local a = {...}
  for i = 1, #a do a[i] = tostring(a[i]) end
  OUT[#OUT + 1] = table.concat(a, "\t")
end
local P = {}
local function isp(v) return type(v) == "table" and getmetatable(v) == P end
local function q(s)
  return '"' .. s:gsub("\\", "\\\\"):gsub('"', '\\"'):gsub("\n", "\\n"):gsub("\r", "\\r") .. '"'
end
local function txt(v)
  if isp(v) then return v.__t end
  local t = type(v)
  if t == "string" then return q(v) end
  if t == "number" then
    if v == math.floor(v) then return string.format("%d", v) end
    return tostring(v)
  end
  if v == nil then return "nil" end
  if t == "boolean" then return tostring(v) end
  return "<" .. t .. ">"
end
local function mk(s) return setmetatable({__t = s}, P) end
local function keytxt(k)
  if type(k) == "string" and k:match("^[%a_][%w_]*$") then return "." .. k end
  return "[" .. txt(k) .. "]"
end
P.__index = function(t, k) return mk(t.__t .. keytxt(k)) end
P.__newindex = function(t, k, v) emit("SI", t.__t .. keytxt(k), txt(v)) end
P.__call = function(t, ...)
  local n = select("#", ...)
  local args = {}
  for i = 1, n do args[i] = txt((select(i, ...))) end
  local s = t.__t .. "(" .. table.concat(args, ", ") .. ")"
  emit("C", s)
  return mk(s)
end
local ops = {add = "+", sub = "-", mul = "*", div = "/", mod = "%", pow = "^", concat = ".."}
for n, sym in pairs(ops) do
  P["__" .. n] = function(a, b) return mk("(" .. txt(a) .. " " .. sym .. " " .. txt(b) .. ")") end
end
P.__unm = function(a) return mk("-" .. txt(a)) end
P.__len = function(a) return 1 end
local function decide(s)
  emit("B", s)
  return true
end
function D(v)
  if isp(v) then return decide(v.__t) end
  return v ~= nil and v ~= false
end
function NOT(v)
  if isp(v) then return not decide(v.__t) end
  return not v
end
local function cmp(sym)
  return function(a, b)
    if isp(a) or isp(b) then return decide(txt(a) .. " " .. sym .. " " .. txt(b)) end
    if sym == "==" then return a == b end
    if sym == "~=" then return a ~= b end
    if sym == "<" then return a < b end
    if sym == ">" then return a > b end
    if sym == "<=" then return a <= b end
    return a >= b
  end
end
CEQ = cmp("==") CNE = cmp("~=") CLT = cmp("<") CGT = cmp(">") CLE = cmp("<=") CGE = cmp(">=")
local store = {}
VE = setmetatable({}, {
  __index = function(t, k)
    local v = store[k]
    if v ~= nil then return v end
    return mk("R" .. tostring(k))
  end,
  __newindex = function(t, k, v)
    store[k] = v
    emit("S", tostring(k), txt(v))
  end
})
local function deepcopy(v)
  if type(v) ~= "table" then return v end
  local r = {}
  for k, x in pairs(v) do r[k] = deepcopy(x) end
  return r
end
lQ = setmetatable({}, {__index = function(t, k) return k end})
Ny = setmetatable({}, {__index = function(t, k) return mk("env" .. tostring(k)) end})
N4 = function(a, b)
  if isp(a) or isp(b) then return mk("xor(" .. txt(a) .. ", " .. txt(b) .. ")") end
  return bit32.bxor(a or 0, b or 0)
end
local function dispatcher()
  return setmetatable({}, {__index = function(t, k)
    return function(a, b)
      if type(a) == "number" then return string.char(a) end
      if type(a) == "string" and type(b) == "number" then return string.byte(a, b) end
      if type(a) == "table" then return table.concat(a) end
      return mk("strfn")
    end
  end})
end
Ny[20891] = dispatcher()
Ny[45729] = dispatcher()
Ny[34931] = setmetatable({}, {__index = function() return math.floor end})
Ny[30925] = function(v) return nil end
Ny[58104] = function(i) return mk(GN[i] or ("global_" .. tostring(i))) end
local function fetch(id)
  Su = POOL[id]
  return Su ~= nil
end
Ny[19140] = fetch
b = fetch
Gv = 1
type_ = type
lR = type
Zp = function(k) return mk("proto(" .. txt(k) .. ")") end
l9 = function(...) return mk("l9") end
Ib = function(...) return mk("Ib") end
hl = {}
N0 = mk("N0")
lL = function(t) return mk("concat") end
N2 = {}
VC = {}
Vb = {}
'''


def build():
    fields = {k: v for k, v in R.glob.items()}
    parts = [PRELUDE]
    parts.append("GN = %s" % ("{" + ",".join("[%d]=%s" % (i, lua_value(DC.resolve(i) or "global_%d" % i)) for i in sorted(DC.ENT)) + "}"))
    pool = {}
    for le, s in V.pool.items():
        pool[le] = s.decode("latin-1")
    parts.append("POOL = {" + ",".join("[%d]=%s" % (k, lua_value(v)) for k, v in pool.items()) + "}")
    parts.append("Xw = " + lua_value(V.Xw))
    parts.append("FIELDS = {" + ",".join("%s=%s" % (nm, lua_value(tab)) for nm, tab in fields.items()) + "}")
    parts.append("cn = " + lua_value(p))
    parts.append("l3 = " + lua_value(R.l3t))
    for nm in ("ia", "ir"):
        parts.append("%s = %s" % (nm, lua_value(R.it.g.get(nm))))
    parts.append("iu = " + lua_value(p.d[2262]))
    parts.append("im = " + lua_value(p.d[3817]))
    for nm in ("lx", "lq", "ln", "lS", "lX"):
        parts.append("%s = %s" % (nm, lua_value(R.it.g.get(nm))))
    node = R.disp
    body = wo.block(tx_block([node]), 1)
    parts.append("local function dispatch()\n%s\nend" % body)
    n = int(p.d[5741])
    parts.append(
        """
local locals_ = {"ij","ie","iv","iM","iQ","iy","i0","i3","i6"}
for pc = 1, %d do
  for name, tab in pairs(FIELDS) do ENV[name] = deepcopy(tab) end
  VY = pc
  VW = (FIELDS.iN[pc] * 23 + 63) %% 256
  VV = false
  Vz = false
  for _, nme in ipairs(locals_) do ENV[nme] = nil end
  local ok, err = pcall(dispatch)
  emit("I", pc, VW, VY, ok and "" or tostring(err))
end
print(table.concat(OUT, "\\n"))
"""
        % n
    )
    return "\n".join(parts)


def find_luau(explicit):
    if explicit:
        return explicit
    name = "luau.exe" if sys.platform.startswith("win") else "luau"
    path = os.path.join(ROOT, "bin", name)
    if os.path.isfile(path):
        return path
    import shutil
    found = shutil.which("luau")
    if found:
        return found
    raise SystemExit("luau binary not found, pass its path as the first argument")


def run(luau):
    code = build()
    wrapped = "local env = setmetatable({}, {__index = _G})\nlocal f = loadstring([=====[\n" + code + "\n]=====])\nsetfenv(f, env)\nf()\n"
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "hybrid_run.lua")
        with open(path, "w") as f:
            f.write(wrapped)
        out = subprocess.run([luau, path], capture_output=True, text=True, timeout=300)
    return out.stdout, out.stderr


def decompile(stdout):
    names = set(v for v in (DC.resolve(i) for i in DC.ENT) if v)
    lines = []
    pending = []
    calls = []
    consumed = set()
    for ln in stdout.split("\n"):
        f = ln.split("\t")
        if f[0] == "C":
            calls.append(f[1])
            pending.append(f[1])
        elif f[0] == "S":
            consumed.add(f[2])
        elif f[0] == "I":
            for c in pending:
                if c in consumed:
                    continue
                if "restorefunction" in c:
                    continue
                if any(re.match(r"^%s\b" % re.escape(n), c) for n in names):
                    lines.append(c)
            pending = []
            consumed = set()
    return lines


if __name__ == "__main__":
    so, se = run(find_luau(ARGS[1] if len(ARGS) > 1 else None))
    if se.strip():
        print(se[:800], file=sys.stderr)
    for l in decompile(so):
        print(l)
