import re,sys
import wyn_static as w
from luastr import unescape
src=w.load(sys.argv[1])
p=w.parse(src)
m=re.search(r'local lj=\{([\d,]+)\}local lv=(\d+) for le=1,#lj do lv=\(\(lv\*(\d+)\)\+(\d+)\+\(le\*(\d+)\)\)%2147483647 lj\[le\]=\(lj\[le\]\+256-\(lv%256\)\)%256 end',src)
lj=[int(x) for x in m.group(1).split(',')];lv=int(m.group(2));A=int(m.group(3));B=int(m.group(4));C=int(m.group(5))
for i in range(1,len(lj)+1):
    lv=(lv*A+B+i*C)%2147483647
    lj[i-1]=(lj[i-1]+256-(lv%256))%256
lm=[0]*18
lM=0
for le in range(1,18):
    g=lambda k: lj[k] if k<len(lj) else 0
    lm[le]=((((g(lM+3)*256+g(lM+2))*256+g(lM+1))*256+g(lM)))%4294967296
    lM+=4
sl=re.findall(r'Ni:sub\((\d+),(\d+)\)',src)
a,b=int(sl[-1][0]),int(sl[-1][1])
mm=re.search(r'local Ni="((?:[^"\\]|\\.)*)"',src)
Ni=unescape(mm.group(1))
ma=re.search(r'local \w+="((?:[^"\\]|\\.)*)"for \w+=1,91 do \w+\[',src)
alpha2={ch:i for i,ch in enumerate(unescape(ma.group(1)))}
cipher=w.b91(Ni[a-1:b],alpha2)
print(len(cipher),lm[1:],file=sys.stderr)
open('stream_cipher.bin','wb').write(cipher)
open('stream_lm.txt','w').write(' '.join(str(x) for x in lm[1:]))
