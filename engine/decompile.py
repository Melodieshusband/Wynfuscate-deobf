import sys
ARGS = list(sys.argv)
import io, contextlib, re, json
with contextlib.redirect_stdout(io.StringIO()):
    import symrun as R
m = R.m
src = R.src

COMMON = """print warn error assert task game workspace script wait spawn delay pcall xpcall loadstring require tostring tonumber typeof type pairs ipairs next select unpack setmetatable getmetatable rawget rawset rawequal string table math os coroutine Instance Vector3 Vector2 CFrame Color3 BrickColor Enum UDim UDim2 Drawing getgenv getrenv getfenv setfenv debug utf8 bit32 http_request request syn fluxus identifyexecutor getgc hookfunction newcclosure checkcaller islclosure setclipboard queue_on_teleport isfile readfile writefile makefolder listfiles Random tick time os os Ray Region3 TweenInfo NumberSequence NumberRange ColorSequence Rect Axes Faces PhysicalProperties RaycastParams OverlapParams Players ReplicatedStorage Workspace Lighting HttpService RunService UserInputService TweenService""".split()

ny40210 = None


def table_entries():
    out = {}
    mm = re.search(r"Ny\[lQ\[40210\]\]=\{((?:\[\d+\]=\{[\d,]+\},?)+)\}", src)
    for k, body in re.findall(r"\[(\d+)\]=\{([\d,]+)\}", mm.group(1)):
        out[int(k)] = [int(x) for x in body.split(",")]
    return out


ENT = table_entries()
YA = 1755017262
YZ = 2147483647


def hashname(s):
    a = YA
    for ch in s.encode("latin-1"):
        a = (a * 131 + ch) % YZ
    return a


def resolve(idx):
    e = ENT.get(idx)
    if not e:
        return None
    n = e[0]
    res = []
    for j in range(n):
        h, ln, f, l = e[1 + j * 4:5 + j * 4]
        for c in COMMON:
            if len(c) == ln and ord(c[0]) == f and ord(c[-1]) == l and hashname(c) == h:
                res.append(c)
    return res[0] if res else "global_%d" % idx


def lua_str(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def render(e):
    if e is None:
        return "nil"
    if isinstance(e, bool):
        return "true" if e else "false"
    if isinstance(e, float):
        return str(int(e)) if e == int(e) else repr(e)
    if isinstance(e, str):
        return lua_str(e)
    if isinstance(e, m.Sym):
        if e.op == "call":
            f, args = e.args
            if isinstance(f, m.Sym) and f.op == "env" and f.args[0] == 58104:
                nm = resolve(int(args[0]))
                return nm or "global_%d" % int(args[0])
            if isinstance(f, m.Sym) and f.op == "env":
                return "?env%s(%s)" % (f.args[0], ", ".join(render(a) for a in args))
            return "%s(%s)" % (render(f), ", ".join(render(a) for a in args))
        if e.op == "index":
            o, k = e.args
            if isinstance(k, str) and re.match(r"^[A-Za-z_]\w*$", k):
                return "%s.%s" % (render(o), k)
            return "%s[%s]" % (render(o), render(k))
        if e.op == "reg":
            return "R%d" % int(e.args[0])
        if e.op == "env":
            return "?env%s" % e.args[0]
        return "?%s" % e.op
    return "?"


def rooted(e):
    if isinstance(e, m.Sym):
        if e.op == "call":
            f, args = e.args
            if isinstance(f, m.Sym) and f.op == "env" and f.args[0] == 58104:
                return True
            return rooted(f)
        if e.op == "index":
            return rooted(e.args[0])
    return False


def main():
    n = int(ARGS[1]) if len(ARGS) > 1 else 101
    regs = {}
    lines = []
    for pc in range(1, n + 1):
        vw, vy, eff, err, newregs = R.run_instr(pc, None, regs)
        calls_consumed = set()
        for k, v in newregs.items():
            if isinstance(v, m.Sym) and v.op == "call":
                calls_consumed.add(id(v))
        for e in eff:
            if e[0] == "call" and id(e[1]) not in calls_consumed and rooted(e[1]):
                text = render(e[1])
                if "restorefunction" not in text:
                    lines.append(text)
        regs = {k: v for k, v in newregs.items() if k != 40487}
    return lines


if __name__ == "__main__":
    for l in main():
        print(l)
