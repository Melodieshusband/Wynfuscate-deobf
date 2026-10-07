import argparse
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile

BASELINE = set(['', '%*', '%*:%*', '-inf', '.*%:(%-?%d+)%:', '.*%:(%-?%d+)%:%s', '.*:%s*(%-%d+):%s', '1', '42', '=[C]', 'C', 'S', '[C]', "^%[string%s+'(.*)'%]$", '^%[string%s+\\"(.*)\\"%]$', '^[^:]+:%d+:', '^[^:]+:(%d+):', '^[^:]+:([a-z0-9]+)$', '^__no_match__$', '_ENV', '__call', '__idiv', '__index', '__ipairs', '__iter', '__len', '__metatable', '__mode', '__namecall', '__newindex', '__pairs', '__tostring', '__uv', 'a:7', 'abs', 'bad argument', 'boolean', 'byte', 'ceil', 'char', 'closed', 'concat', 'create', 'currentline', 'debug', 'delay', 'dump', 'error', 'f', 'floor', 'fmod', 'format', 'func', 'function', 'getfenv', 'getgenv', 'gethook', 'getinfo', 'getupvalue', 'gfvs', 'gmatch', 'hookfunc', 'hookfunction', 'hookmetamethod', 'huge', 'inf', 'info', 'insert', 'islclosure', 'jgc', 'jic', 'jit', 'k', 'l', 'lastlinedefined', 'linedefined', 'locked', 'match', 'max', 'min', 'missing argument', 'n', 'nSl', 'name', 'nan', 'newcclosure', 'nsl', 'number', 'number expected', 'nups', 'nv', 'nv_inline', 'nv_uv', 'owner', 'pack', 'pcall', 'pow', 'random', 'rawget', 'rawset', 'reg', 'replaceclosure', 'restorefunction', 'resume', 'running', 's', 'setfenv', 'setreadonly', 'setupvalue', 'source', 'sqrt', 'string', 'string expected', 'sub', 'table', 'table expected', 'test error message', 'tostring', 'traceback', 'unpack', 'v', 'value', 'what', 'x'])

API_WORDS = set("""assert collectgarbage error getfenv getmetatable ipairs loadstring newproxy next pairs pcall print rawequal rawget rawset rawlen select setfenv setmetatable tonumber tostring type typeof unpack xpcall require warn wait spawn delay tick time version settings game workspace script plugin shared task Instance Vector3 Vector2 CFrame Color3 UDim UDim2 Enum Random Ray Region3 TweenInfo BrickColor NumberRange NumberSequence ColorSequence Rect Axes Faces PhysicalProperties Vector3int16 Vector2int16 RaycastParams OverlapParams Font DateTime coroutine bit32 buffer debug math os string table utf8
create wrap yield resume status running isyieldable close abs acos asin atan atan2 ceil clamp cos deg exp floor fmod frexp ldexp log log10 map max min modf noise pi pow rad random randomseed round sign sin sinh sqrt tan tanh huge
byte char find format gmatch gsub len lower match rep reverse split sub upper pack unpack concat insert remove sort getn foreach move clear clone freeze isfrozen band bnot bor btest bxor extract lrotate lshift replace rrotate rshift arshift
getinfo traceback info profilebegin profileend clock date difftime charpattern codepoint codes offset
Players LocalPlayer GetService FindFirstChild WaitForChild Heartbeat RenderStepped Stepped RunService UserInputService ReplicatedStorage Workspace Lighting TweenService HttpService StarterGui CoreGui TeleportService MarketplaceService
Connect Disconnect Destroy Clone GetChildren GetDescendants IsA Name Parent ClassName Character Humanoid HumanoidRootPart Position Size
getgenv getrenv getreg getgc getinstances getnilinstances getloadedmodules getconnections firesignal fireclickdetector firetouchinterest fireproximityprompt getrawmetatable setrawmetatable setreadonly isreadonly make_writeable make_readonly hookfunction hookmetamethod newcclosure iscclosure islclosure checkcaller getnamecallmethod setnamecallmethod identifyexecutor getexecutorname request http_request syn readfile writefile appendfile isfile isfolder listfiles makefolder delfile delfolder loadfile dofile setclipboard toclipboard queue_on_teleport saveinstance decompile getscripts getscriptbytecode getcallingscript getscriptclosure cloneref clonefunction compareinstances Drawing mouse1click mouse1press mouse1release mousemoverel mousemoveabs keypress keyrelease isrbxactive setfpscap getfpscap gethui gethiddenproperty sethiddenproperty setscriptable isscriptable getcustomasset base64encode base64decode crypt getupvalue getupvalues setupvalue getconstant getconstants setconstant getproto getprotos getstack setstack restorefunction isfunctionhooked getsenv getthreadidentity setthreadidentity isexecutorclosure replaceclosure rconsoleprint rconsolewarn rconsoleinfo rconsoleerr consoleclear rconsolename WebSocket HttpGet HttpGetAsync HttpPost""".split())

ESC = {"n": 10, "t": 9, "r": 13, "a": 7, "b": 8, "f": 12, "v": 11, "\\": 92, '"': 34, "'": 39, "\n": 10}
STR_RE = re.compile(r'"((?:[^"\\]|\\.)*)"', re.S)


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
    return bytes(out)


def literals(src):
    return [(m.start(), m.end(), unescape(m.group(1))) for m in STR_RE.finditer(src)]


def find_alphabet(src):
    m = re.search(r"local \w+=\{((?:\[\d+\]=\d+,?){80,})\}local \w+=function\(\w+\)return", src)
    if not m:
        raise SystemExit("base91 alphabet table not found: unsupported build layout")
    return {int(k): int(v) for k, v in re.findall(r"\[(\d+)\]=(\d+)", m.group(1))}


def b91(data, alphabet):
    out = []
    pending = -1
    acc = 0
    nbits = 0
    for ch in data:
        v = alphabet.get(ch)
        if v is None:
            continue
        if pending < 0:
            pending = v
        else:
            pending += v * 91
            acc += pending << nbits
            nbits += 13 if (pending % 8192) > 88 else 14
            while nbits >= 8:
                out.append(acc & 255)
                acc >>= 8
                nbits -= 8
            pending = -1
    if pending >= 0:
        acc += pending << nbits
        nbits += 7
        while nbits >= 8:
            out.append(acc & 255)
            acc >>= 8
            nbits -= 8
    return bytes(out)


def lz_expand(data, total):
    out = bytearray()

    def at(i):
        return data[i] if i < len(data) else 0

    pos = 0
    while len(out) < total:
        flags = at(pos)
        pos += 1
        for _ in range(8):
            if len(out) >= total:
                break
            bit = flags & 1
            flags >>= 1
            if bit:
                lo = at(pos)
                hi = at(pos + 1)
                pos += 2
                top = hi // 16
                dist = top * 256 + lo
                if top == 15:
                    dist = at(pos) * 256 + lo
                    pos += 1
                low = hi - top * 16
                length = low + 3
                if low == 15:
                    extra = 0
                    while True:
                        x = at(pos)
                        pos += 1
                        extra += x
                        if x != 255:
                            break
                    length = 18 + extra
                start = len(out) - (dist + 1)
                for k in range(length):
                    if len(out) >= total:
                        break
                    out.append(out[start + k] if 0 <= start + k < len(out) else 0)
            else:
                out.append(at(pos))
                pos += 1
    return bytes(out)


def varints(data, count):
    vals = []
    acc = 0
    cur = 0
    shift = 0
    for byte in data:
        cur += (byte % 128) << shift
        if byte < 128:
            acc += cur
            vals.append(acc)
            cur = 0
            shift = 0
        else:
            shift += 7
        if len(vals) >= count:
            break
    return vals


def find_x6(src):
    for m in re.finditer(r"local (\w+)=\{([\d,]{20,})\};local (\w+)=(\d+);for \w+=1,#\1 do \3=\(\(\3\*(\d+)\)\+(\d+)\+\(\w+\*(\d+)\)\)%2147483647", src):
        return [int(v) for v in m.group(2).split(",")], int(m.group(4)), int(m.group(5)), int(m.group(6)), int(m.group(7))
    return None


def keys_from_x6(info):
    data, state, mul, add, idx = info
    data = list(data)
    for i in range(1, len(data) + 1):
        state = ((state * mul) + add + (i * idx)) % 2147483647
        data[i - 1] ^= state % 256
    k1 = sum(data[j] << (8 * j) for j in range(4))
    k2 = sum(data[4 + j] << (8 * j) for j in range(4))
    return k1, k2


class Pool:
    pass


def parse(src):
    p = Pool()
    p.alphabet = find_alphabet(src)
    lits = literals(src)
    m = re.search(r"=(\w+):sub\(1,(\d+)\)local \w+=\1:sub\((\d+),(\d+)\)", src)
    if not m:
        raise SystemExit("data container slices not found: unsupported build layout")
    cut1, cut2, cut3 = int(m.group(2)), int(m.group(3)), int(m.group(4))
    packed = None
    for mm in re.finditer(r"local %s=\"((?:[^\"\\]|\\.)*)\"" % m.group(1), src):
        packed = unescape(mm.group(1))
        break
    m = re.search(r"=\w+\(\w+,(\d+)\)return \w+\[\w+\]end", src)
    total = int(m.group(1))
    m = re.search(r"while \w+<=(\d+) do local \w+=\w+\[\w+\]if not", src)
    count = int(m.group(1))
    p.buffer = lz_expand(b91(packed[:cut1], p.alphabet), total)
    p.offsets = varints(b91(packed[cut2 - 1:cut3], p.alphabet), count)
    x6 = find_x6(src)
    p.keys = keys_from_x6(x6) if x6 else None
    m = re.search(r"\+\(\w+\*131\)\+(?:(\d+)\+(\d+)|\(\w+\[\w+\[\d+\]\]%65536\)\+\(\w+\[\w+\[\d+\]\]%65536\))\+\(\((\d+)%65536\)\*17\)\+(\d+)\)", src)
    z = int(m.group(3))
    if m.group(1) is not None:
        p.base = int(m.group(1)) + int(m.group(2)) + (z % 65536) * 17 + int(m.group(4))
    else:
        p.base = (p.keys[0] % 65536) + (p.keys[1] % 65536) + (z % 65536) * 17 + int(m.group(4))
    p.z = z
    p.table = None
    for a, b, s in lits:
        if len(s) >= 256 and re.match(r"\s*(local|for)", src[b:b + 20]) is not None:
            tail = src[b:b + 120]
            if "1,256" in tail:
                p.table = s[:256]
                break
    if p.table is None:
        raise SystemExit("substitution table not found: unsupported build layout")
    return p


def record(p, le):
    off = p.offsets[le - 1] - 1
    n = struct.unpack_from("<I", p.buffer, off)[0]
    return n, p.buffer[off + 4:off + 4 + n]


def stream(p, qe, le, n, data):
    mask = 0xFFFFFFFF
    s = (qe + le * 257 + n * 131 + p.base) & mask
    s = (s * 1664525 + 1013904223 + le * 40503 + n * 11117) & mask
    out = bytearray()
    for xf in range(1, n + 1):
        s = (s * 1664525 + 1013904223 + le * 257 + xf * 131 + n * 17 + 1831565813) & mask
        s2 = s & 255
        s8 = (s >> 8) & 255
        s4 = (s >> 16) & 255
        s9 = (s >> 24) & 255
        sv = s2 ^ ((s8 + xf) & 255) ^ s4 ^ ((s9 + le + n) & 255)
        out.append(p.table[data[xf - 1] ^ sv])
    return bytes(out)


C_TEMPLATE = r"""
#include <stdio.h>
#include <stdint.h>
typedef uint32_t u32;
static const unsigned char tab[256]={TAB};
static int okc(int c){return (c>=48&&c<=57)||(c>=65&&c<=90)||(c>=97&&c<=122)||c==95||c==46;}
static int test(u32 qe,int le,int n,const unsigned char*d){
u32 s=qe+(u32)(BASE)+(u32)le*257u+(u32)n*131u;
s=s*1664525u+1013904223u+(u32)le*40503u+(u32)n*11117u;
for(int xf=1;xf<=n;xf++){
s=s*1664525u+1013904223u+(u32)le*257u+(u32)xf*131u+(u32)n*17u+1831565813u;
u32 s2=s&255,s8=(s>>8)&255,s4=(s>>16)&255,s9=(s>>24)&255;
u32 sv=s2^((s8+xf)&255)^s4^((s9+le+n)&255);
if(!okc(tab[(d[xf-1]^sv)&255]))return 0;}
return 1;}
RECS
int main(){u32 q=0;do{int ok=1;int cnt=0;
MAINBODY
if(ok&&cnt>=NEED)printf("%u %d\n",q,cnt);q++;}while(q!=0);return 0;}
"""


def pick_records(p, probe):
    recs = []
    for le in range(1, min(probe, len(p.offsets)) + 1):
        n, d = record(p, le)
        recs.append((le, n, d))
    return recs


def solve_qe_c(p, compiler, recs, first, need):
    decl = "\n".join("static const unsigned char r%d[]={%s};" % (le, ",".join(str(b) for b in (d or b"\0"))) for le, n, d in recs)
    body = []
    for le, n, d in recs:
        if le <= first:
            body.append("if(ok&&!test(q,%d,%d,r%d))ok=0;" % (le, n, le))
        else:
            body.append("if(ok&&test(q,%d,%d,r%d))cnt++;" % (le, n, le))
    code = (C_TEMPLATE.replace("TAB", ",".join(str(b) for b in p.table))
            .replace("BASE", str(p.base)).replace("RECS", decl)
            .replace("MAINBODY", "\n".join(body)).replace("NEED", str(need)))
    d = tempfile.mkdtemp()
    cpath = os.path.join(d, "bf.c")
    exe = os.path.join(d, "bf")
    open(cpath, "w").write(code)
    subprocess.check_call([compiler, "-O2", "-o", exe, cpath], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    out = subprocess.check_output([exe]).decode().split("\n")
    shutil.rmtree(d, ignore_errors=True)
    best = None
    for line in out:
        if line.strip():
            q, c = line.split()
            if best is None or int(c) > best[1]:
                best = (int(q), int(c))
    return best


def solve_qe_numpy(p, recs, first, need, lo=0, hi=1 << 32):
    import numpy as np
    okc = np.zeros(256, dtype=bool)
    for c in range(256):
        okc[c] = (48 <= c <= 57) or (65 <= c <= 90) or (97 <= c <= 122) or c in (95, 46)
    tab = np.frombuffer(p.table, dtype=np.uint8)
    okt = okc[tab]
    A = np.uint32(1664525)
    B = np.uint32(1013904223)

    def survive(q, le, n, d):
        with np.errstate(over="ignore"):
            s = q + np.uint32((p.base + le * 257 + n * 131) & 0xFFFFFFFF)
            s = s * A + np.uint32((1013904223 + le * 40503 + n * 11117) & 0xFFFFFFFF)
            alive = np.ones(len(q), dtype=bool)
            for xf in range(1, n + 1):
                s = s * A + np.uint32((1013904223 + le * 257 + xf * 131 + n * 17 + 1831565813) & 0xFFFFFFFF)
                s2 = s & np.uint32(255)
                s8 = (s >> np.uint32(8)) & np.uint32(255)
                s4 = (s >> np.uint32(16)) & np.uint32(255)
                s9 = s >> np.uint32(24)
                sv = s2 ^ ((s8 + np.uint32(xf)) & np.uint32(255)) ^ s4 ^ ((s9 + np.uint32(le + n)) & np.uint32(255))
                idx = (np.uint32(d[xf - 1]) ^ sv) & np.uint32(255)
                alive &= okt[idx]
        return alive

    best = None
    chunk = 1 << 22
    for start in range(lo, hi, chunk):
        q = np.arange(start, start + chunk, dtype=np.uint32)
        for le, n, d in recs:
            if le > first:
                break
            if n == 0:
                continue
            q = q[survive(q, le, n, d)]
            if len(q) == 0:
                break
        if len(q) == 0:
            continue
        counts = np.zeros(len(q), dtype=np.int32)
        for le, n, d in recs:
            if le <= first or n == 0:
                continue
            counts += survive(q, le, n, d).astype(np.int32)
        for qi, ci in zip(q.tolist(), counts.tolist()):
            if ci >= need and (best is None or ci > best[1]):
                best = (qi, ci)
    return best


def find_bf():
    name = "bf.exe" if sys.platform.startswith("win") else "bf"
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin", name)
    return os.path.normpath(path) if os.path.isfile(path) else None


def solve_qe_binary(path, p, recs, first, need):
    lines = ["%d %d %d %d" % (p.base, first, need, len(recs)), " ".join(str(b) for b in p.table)]
    for le, n, d in recs:
        lines.append("%d %d %s" % (le, n, " ".join(str(b) for b in d)))
    out = subprocess.run([path], input="\n".join(lines) + "\n", capture_output=True, text=True, check=True)
    best = None
    for line in out.stdout.split("\n"):
        if line.strip():
            q, c = line.split()
            q, c = int(q), int(c)
            if best is None or c > best[1] or (c == best[1] and q < best[0]):
                best = (q, c)
    return best


def solve_qe(p, probe=30, need=5):
    recs = pick_records(p, probe)
    bf = find_bf()
    compiler = None
    for name in ("gcc", "cc", "clang"):
        if shutil.which(name):
            compiler = name
            break
    for first in (2, 3, 1):
        if bf:
            best = solve_qe_binary(bf, p, recs, first, need)
        elif compiler:
            best = solve_qe_c(p, compiler, recs, first, need)
        else:
            best = solve_qe_numpy(p, recs, first, need)
        if best is not None:
            return best
    return None


HASH_MOD = 2147483647


def hash_name(word, seed):
    a = seed
    for c in word.encode("latin-1"):
        a = (a * 131 + c) % HASH_MOD
    return a


def find_hashed_table(src):
    m = re.search(r"\w+\[\w+\[\d+\]\]=\{((?:\[\d+\]=\{\d+(?:,\d+)+\},?)+)\}", src)
    if not m:
        return {}
    entries = {}
    for em in re.finditer(r"\[(\d+)\]=\{(\d+(?:,\d+)+)\}", m.group(1)):
        nums = [int(x) for x in em.group(2).split(",")]
        parts = []
        for i in range(nums[0]):
            seg = nums[1 + i * 4:5 + i * 4]
            if len(seg) == 4:
                parts.append(seg)
        entries[int(em.group(1))] = parts
    return entries


def resolve_hashed(src, extra_words):
    entries = find_hashed_table(src)
    if not entries:
        return {}
    seeds = set()
    for m in re.finditer(r"local \w+=(\d{9,10}) local \w+=2147483647", src):
        seeds.add(int(m.group(1)))
    for m in re.finditer(r"\*131\+", src):
        window = src[max(0, m.start() - 400):m.start()]
        for s in re.findall(r"\b(\d{9,10})\b", window):
            v = int(s)
            if v < HASH_MOD:
                seeds.add(v)
    words = set(API_WORDS) | set(extra_words)
    best_seed = None
    best_hits = 0
    for seed in seeds:
        table = {hash_name(w, seed): w for w in words}
        hits = 0
        for parts in entries.values():
            for part in parts:
                if part[0] in table:
                    hits += 1
        if hits > best_hits:
            best_hits = hits
            best_seed = seed
    if best_seed is None:
        return {}
    table = {}
    for w in words:
        table.setdefault(hash_name(w, best_seed), []).append(w)
    resolved = {}
    for idx, parts in entries.items():
        names = []
        for h, ln, first, last in parts:
            cand = [w for w in table.get(h, []) if len(w) == ln and ord(w[0]) == first and ord(w[-1]) == last]
            names.append(cand[0] if cand else "?(len=%d,%s..%s)" % (ln, chr(first), chr(last)))
        resolved[idx] = ".".join(names)
    return resolved


URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.I)
DISCORD_RE = re.compile(r"discord(?:app)?\.(?:gg|com/invite)/[\w-]+", re.I)
DOMAIN_RE = re.compile(r"^[\w.-]+\.(?:com|net|org|io|gg|dev|app|xyz|cc|me|ly|co|sh|ink|pro)(?:/\S*)?$", re.I)
JUNK_RES = [
    re.compile(r"^_[A-Za-z0-9]{8,16}$"),
    re.compile(r"^LocalScript:\d+: \w+$"),
    re.compile(r"^[a-z0-9]{4,12}:.*:[a-z0-9]{3,8}$"),
]


def classify(value):
    try:
        text = value.decode("utf-8")
    except UnicodeDecodeError:
        return "binary", value.decode("latin-1")
    if any(ord(c) < 32 and c not in "\t\n\r" for c in text):
        return "binary", text
    if text in BASELINE:
        return "protector", text
    for r in JUNK_RES:
        if r.match(text):
            return "protector", text
    return "payload", text


def build_report(path, p, qe, pool, resolved, show_all):
    cats = {}
    for idx, text in pool:
        cats.setdefault(classify(text)[0], []).append(idx)
    rows = {idx: classify(text) for idx, text in pool}
    lines = []
    lines.append("source: %s" % os.path.basename(path))
    lines.append("records: %d, qE: %d (%d confirmations)" % (len(pool), qe[0], qe[1]))
    lines.append("payload candidates: %d, protector strings: %d, binary blobs: %d" % (
        len(cats.get("payload", [])), len(cats.get("protector", [])), len(cats.get("binary", []))))
    lines.append("")
    urls = []
    discords = []
    domains = []
    apis = []
    for idx, text in pool:
        cat, s = rows[idx]
        if cat == "binary":
            continue
        for u in URL_RE.findall(s):
            urls.append((idx, u))
        for dd in DISCORD_RE.findall(s):
            discords.append((idx, dd))
        if DOMAIN_RE.match(s) and not URL_RE.search(s):
            domains.append((idx, s))
        if s in API_WORDS and cat != "protector":
            apis.append((idx, s))
    lines.append("[urls]")
    for idx, u in urls:
        lines.append("%d\t%s" % (idx, u))
    lines.append("")
    lines.append("[discord]")
    for idx, u in discords:
        lines.append("%d\t%s" % (idx, u))
    lines.append("")
    lines.append("[domains and paths]")
    for idx, u in domains:
        lines.append("%d\t%s" % (idx, u))
    lines.append("")
    lines.append("[api names in the constant pool]")
    for idx, u in apis:
        lines.append("%d\t%s" % (idx, u))
    lines.append("")
    lines.append("[api names resolved from hashes]")
    for idx in sorted(resolved):
        lines.append("%d\t%s" % (idx, resolved[idx]))
    lines.append("")
    lines.append("[payload candidates in constant order]")
    for idx, text in pool:
        cat, s = rows[idx]
        if cat == "payload":
            lines.append("%d\t%s" % (idx, ascii(s)))
    if show_all:
        lines.append("")
        lines.append("[protector strings]")
        for idx, text in pool:
            cat, s = rows[idx]
            if cat == "protector":
                lines.append("%d\t%s" % (idx, ascii(s)))
        lines.append("")
        lines.append("[binary blobs]")
        for idx, text in pool:
            cat, s = rows[idx]
            if cat == "binary":
                lines.append("%d\t%d bytes" % (idx, len(text)))
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description="wYnFuscate static string-pool extractor")
    ap.add_argument("input")
    ap.add_argument("-o", "--out-dir")
    ap.add_argument("--qe", type=int, help="skip the key search and use this qE value")
    ap.add_argument("--all", action="store_true", help="include protector strings and blobs in the report")
    args = ap.parse_args()

    src = open(args.input, encoding="latin-1").read()
    p = parse(src)
    print("records: %d, data buffer: %d bytes" % (len(p.offsets), len(p.buffer)))
    if args.qe is not None:
        qe = (args.qe, 0)
    else:
        print("searching for the pool key qE (this takes about a minute)...")
        qe = solve_qe(p)
    if qe is None:
        print("qE was not found")
        return 1
    print("qE: %d" % qe[0])
    pool = []
    for le in range(1, len(p.offsets) + 1):
        n, d = record(p, le)
        pool.append((le, stream(p, qe[0], le, n, d)))
    words = set()
    for idx, text in pool:
        try:
            words.add(text.decode("ascii"))
        except UnicodeDecodeError:
            pass
    resolved = resolve_hashed(src, words)
    base = os.path.splitext(os.path.basename(args.input))[0]
    out_dir = args.out_dir or os.path.dirname(os.path.abspath(args.input))
    os.makedirs(out_dir, exist_ok=True)
    strings_path = os.path.join(out_dir, base + "_strings.txt")
    report_path = os.path.join(out_dir, base + "_static_report.txt")
    with open(strings_path, "w", encoding="utf-8") as f:
        for idx, text in pool:
            cat, s = classify(text)
            f.write("%d\t%s\t%s\n" % (idx, cat, ascii(s) if cat != "binary" else "<%d bytes>" % len(text)))
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(build_report(args.input, p, qe, pool, resolved, args.all))
    print("strings: %s" % strings_path)
    print("report: %s" % report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
