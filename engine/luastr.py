import re
ESC={'n':10,'t':9,'r':13,'a':7,'b':8,'f':12,'v':11,'\\':92,'"':34,"'":39,'\n':10}
def unescape(body):
    out=bytearray();i=0;n=len(body)
    while i<n:
        c=body[i]
        if c=='\\':
            i+=1;d=body[i]
            if d.isdigit():
                j=i
                while j<n and j<i+3 and body[j].isdigit():j+=1
                out.append(int(body[i:j])&255);i=j;continue
            if d=='x':
                out.append(int(body[i+1:i+3],16));i+=3;continue
            out.append(ESC.get(d,ord(d)));i+=1;continue
        out.append(ord(c)&255);i+=1
    return bytes(out)
STR=re.compile(r'"((?:[^"\\]|\\.)*)"',re.S)
def literals(src):
    return [(m.start(),m.end(),unescape(m.group(1))) for m in STR.finditer(src)]
