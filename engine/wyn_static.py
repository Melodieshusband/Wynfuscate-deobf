import os
import re
import struct
import subprocess
import sys
import tempfile
from luastr import literals, unescape


def load(path):
    return open(path, encoding="latin-1").read()


def find_alphabet(src):
    m = re.search(r"local \w+=\{((?:\[\d+\]=\d+,?){80,})\}local \w+=function\(\w+\)return", src)
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


def find_bf():
    name = "bf.exe" if sys.platform.startswith("win") else "bf"
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin", name)
    return path if os.path.isfile(path) else None


def pick_best(lines):
    best = None
    for line in lines:
        if line.strip():
            q, c = line.split()
            q, c = int(q), int(c)
            if best is None or c > best[1] or (c == best[1] and q < best[0]):
                best = (q, c)
    return best


def solve_qe_binary(path, p, recs, first, need):
    lines = ["%d %d %d %d" % (p.base, first, need, len(recs)), " ".join(str(b) for b in p.table)]
    for le, n, d in recs:
        lines.append("%d %d %s" % (le, n, " ".join(str(b) for b in d)))
    out = subprocess.run([path], input="\n".join(lines) + "\n", capture_output=True, text=True, check=True)
    return pick_best(out.stdout.split("\n"))


def solve_qe_gcc(p, recs, first, need):
    base = p.base
    decl = "\n".join("static const unsigned char r%d[]={%s};" % (le, ",".join(str(b) for b in (d or b"\0"))) for le, n, d in recs)
    body = []
    for le, n, d in recs:
        if le <= first:
            body.append("if(ok&&!test(q,%d,%d,r%d))ok=0;" % (le, n, le))
        else:
            body.append("if(ok&&test(q,%d,%d,r%d))cnt++;" % (le, n, le))
    code = C_TEMPLATE.replace("TAB", ",".join(str(b) for b in p.table)).replace("BASE", str(base)).replace("RECS", decl).replace("MAINBODY", "\n".join(body)).replace("NEED", str(need))
    d = tempfile.mkdtemp()
    cpath = os.path.join(d, "bf.c")
    exe = os.path.join(d, "bf")
    open(cpath, "w").write(code)
    subprocess.check_call(["gcc", "-O2", "-o", exe, cpath])
    out = subprocess.check_output([exe]).decode().split("\n")
    return pick_best(out)


def solve_qe(p, probe=30, first=2, need=5):
    recs = []
    for le in range(1, probe + 1):
        n, d = record(p, le)
        recs.append((le, n, d))
    path = find_bf()
    if path:
        return solve_qe_binary(path, p, recs, first, need)
    return solve_qe_gcc(p, recs, first, need)


def main():
    src = load(sys.argv[1])
    p = parse(src)
    print("records:", len(p.offsets), "buffer:", len(p.buffer), "base:", p.base, "z:", p.z, "table:", p.table is not None)
    qe = solve_qe(p)
    print("qE:", qe)
    if qe is None:
        return 1
    for le in range(1, len(p.offsets) + 1):
        n, d = record(p, le)
        print(le, repr(stream(p, qe[0], le, n, d)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
