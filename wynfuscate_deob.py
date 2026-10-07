import argparse
import os
import re
import shutil
import subprocess
import sys

HOOK_LUA = r'''local PAYLOAD_SLOT=nil

local realG=getfenv(0)
for _,libname in ipairs({"string","table","math","os","coroutine","bit32","utf8","debug"}) do
  local lib=realG[libname]
  if type(lib)=="table" then
    local copy={}
    for k,v in pairs(lib) do copy[k]=v end
    realG[libname]=copy
  end
end
if type(realG._G)=="table" then
  local gcopy={}
  for k,v in pairs(realG._G) do gcopy[k]=v end
  realG._G=gcopy
end
local rawprint=print
local rawget,rawset,rawequal=rawget,rawset,rawequal
local setmetatable,getmetatable=setmetatable,getmetatable
local tostring,type,select,pairs,ipairs=tostring,type,select,pairs,ipairs
local newproxy,pcall=newproxy,pcall
local sfmt,sgsub,ssub,srep=string.format,string.gsub,string.sub,string.rep
local sconcat=table.concat
local mfloor,mhuge=math.floor,math.huge

local indent=0
local varcount=0
local sigwaits=0
local httpmap={}
local lastkey=nil
local instances={}
local handlers={}
local probepart=nil
local probedone=false
local interacted=false
local interact=nil
local installloader=nil
local names=setmetatable({},{__mode="k"})
local parents=setmetatable({},{__mode="k"})

local reserved={}
for _,w in ipairs({"and","break","do","else","elseif","end","false","for","function","if","in","local","nil","not","or","repeat","return","then","true","until","while","continue"}) do
  reserved[w]=true
end

local cap=nil
local capdepth=0
local fncache=setmetatable({},{__mode="k"})
local function emit(s)
  local first=true
  for line in (s.."\n"):gmatch("(.-)\n") do
    local text
    if first then text=srep("  ",indent)..line else text=line end
    first=false
    if cap then cap[#cap+1]=text else rawprint("DEOB\t"..text) end
  end
end

local function isident(k)
  return type(k)=="string" and ssub(k,1,1)~="" and not reserved[k] and k:match("^[%a_][%w_]*$")~=nil
end

local function quote(s)
  local r=sgsub(s,'[%c"\\\127-\255]',function(c)
    if c=='"' then return '\\"' end
    if c=="\\" then return "\\\\" end
    if c=="\n" then return "\\n" end
    if c=="\r" then return "\\r" end
    if c=="\t" then return "\\t" end
    return sfmt("\\%03d",c:byte())
  end)
  return '"'..r..'"'
end

local newspy
local paramspies
local paramnames
local ser
ser=function(v,depth)
  depth=depth or 0
  local t=type(v)
  if t=="nil" then return "nil" end
  if t=="boolean" then return tostring(v) end
  if t=="number" then
    if v~=v then return "(0/0)" end
    if v==mhuge then return "math.huge" end
    if v==-mhuge then return "-math.huge" end
    if v==mfloor(v) and v>-1e15 and v<1e15 then return sfmt("%d",v) end
    for prec=1,17 do
      local str=sfmt("%."..prec.."g",v)
      if tonumber(str)==v then return str end
    end
    return sfmt("%.17g",v)
  end
  if t=="string" then
    local hm=httpmap[v]
    if hm then return hm end
    return quote(v)
  end
  local nm=names[v]
  if nm then return nm end
  if t=="table" then
    if depth>=3 then return "{}" end
    local parts={}
    local n=#v
    for i=1,n do parts[#parts+1]=ser(v[i],depth+1) end
    local extra=0
    for k,val in pairs(v) do
      if not (type(k)=="number" and k>=1 and k<=n and k==mfloor(k)) then
        extra=extra+1
        if extra>40 then break end
        if isident(k) then
          parts[#parts+1]=k.." = "..ser(val,depth+1)
        else
          parts[#parts+1]="["..ser(k,depth+1).."] = "..ser(val,depth+1)
        end
      end
    end
    return "{"..sconcat(parts,", ").."}"
  end
  if t=="function" then
    if fncache[v] then return fncache[v] end
    if capdepth>=6 then return "function() end" end
    local spies=paramspies(v)
    local saved=cap
    local buf={}
    cap=buf
    capdepth=capdepth+1
    local savedindent=indent
    indent=indent+1
    pcall(v,table.unpack and table.unpack(spies) or unpack(spies))
    indent=savedindent
    capdepth=capdepth-1
    cap=saved
    local text="function("..paramnames(spies)..")"
    if #buf>0 then text=text.."\n"..sconcat(buf,"\n").."\n"..srep("  ",indent).."end" else text=text.." end" end
    fncache[v]=text
    return text
  end
  return "nil"
end

local function serargs(args,from,to)
  local parts={}
  for i=from,to do parts[#parts+1]=ser(args[i]) end
  return sconcat(parts,", ")
end

local waits=0
paramspies=function(f)
  local ok,np,va=pcall(debug.info,f,"a")
  local list={}
  if ok and type(np)=="number" then
    for i=1,np do list[i]=newspy("arg"..i,nil) end
    if np==0 and va then list[1]=newspy("arg1",nil) end
  end
  return list
end

paramnames=function(list)
  local t={}
  for i=1,#list do t[i]="arg"..i end
  return sconcat(t,", ")
end

local function emitwithfn(head,args,start,n)
  local f=nil
  for i=start,n do
    if type(args[i])=="function" then f=i break end
  end
  if not f then
    emit(head..serargs(args,start,n)..")")
    return
  end
  local spies=paramspies(args[f])
  local pre=head
  if f>start then pre=pre..serargs(args,start,f-1)..", " end
  emit(pre.."function("..paramnames(spies)..")")
  indent=indent+1
  pcall(args[f],table.unpack and table.unpack(spies) or unpack(spies))
  indent=indent-1
  local tail=""
  if f<n then tail=", "..serargs(args,f+1,n) end
  emit("end"..tail..")")
end

local function binop(op)
  return function(a,b)
    return newspy("("..ser(a).." "..op.." "..ser(b)..")",nil)
  end
end

local propsof=setmetatable({},{__mode="k"})
local nilkeys={Parent=true,[""]=true}

newspy=function(name,parent,props)
  local p=newproxy(true)
  local mt=getmetatable(p)
  names[p]=name
  parents[p]=parent
  if props then propsof[p]=props end
  local children={}
  mt.__index=function(_,k)
    if props then
      local pv=props[k]
      if pv~=nil then return pv end
      if nilkeys[k] then return nil end
    end
    local c=children[k]
    if c==nil then
      local nm
      if isident(k) then nm=name.."."..k else nm=name.."["..ser(k).."]" end
      c=newspy(nm,p)
      children[k]=c
    end
    return c
  end
  mt.__newindex=function(_,k,v)
    local lhs
    if isident(k) then lhs=name.."."..k else lhs=name.."["..ser(k).."]" end
    if props then props[k]=v end
    emit(lhs.." = "..ser(v))
  end
  mt.__call=function(self,...)
    local n=select("#",...)
    local args={...}
    local callee=name
    local start=1
    local par=parents[self]
    if par and n>=1 and rawequal(args[1],par) then
      local pn=names[par]
      if ssub(name,#pn+1,#pn+1)=="." then
        callee=pn..":"..ssub(name,#pn+2)
        start=2
      end
    end
    if ssub(callee,-5)==":Wait" then
      sigwaits=sigwaits+1
      if sigwaits>200 then error("wait limit reached") end
    end
    if type(args[start])=="function" and ssub(callee,-8)==":Connect" then
      local evn=callee:match("%.([%w_]+):Connect$")
      handlers[#handlers+1]={fn=args[start],ev=evn,head=callee}
    end
    varcount=varcount+1
    local vn="v"..varcount
    emitwithfn("local "..vn.." = "..callee.."(",args,start,n)
    return newspy(vn,nil)
  end
  mt.__tostring=function() return name end
  mt.__concat=binop("..")
  mt.__add=binop("+")
  mt.__sub=binop("-")
  mt.__mul=binop("*")
  mt.__div=binop("/")
  mt.__mod=binop("%")
  mt.__pow=binop("^")
  mt.__unm=function(a) return newspy("(-"..name..")",nil) end
  mt.__len=function() return 0 end
  mt.__eq=function(a,b) return rawequal(a,b) end
  mt.__lt=function() return false end
  mt.__le=function() return false end
  return p
end

local function logstmt(name)
  return function(...)
    local n=select("#",...)
    local args={...}
    emit(name.."("..serargs(args,1,n)..")")
  end
end

local function logvalue(name)
  return function(...)
    local n=select("#",...)
    local args={...}
    varcount=varcount+1
    local vn="v"..varcount
    emit("local "..vn.." = "..name.."("..serargs(args,1,n)..")")
    return newspy(vn,nil)
  end
end

local function blockcall(name)
  local iswait=ssub(name,-4)=="wait"
  return function(...)
    local n=select("#",...)
    local args={...}
    if iswait then
      waits=waits+1
      if waits==3 and interact then interact() end
      if waits>400 then error("wait limit reached") end
    end
    emitwithfn(name.."(",args,1,n)
  end
end

local function mkvec(x,y,z,ctor)
  local v={X=x,Y=y,Z=z}
  names[v]=(ctor or "Vector3")..".new("..ser(x)..", "..ser(y)..", "..ser(z)..")"
  return setmetatable(v,{__tostring=function() return tostring(x)..", "..tostring(y)..", "..tostring(z) end})
end

local function rayhit(part,origin,dir)
  local pr=propsof[part]
  if not pr or not pr.Size or not pr.CFrame or not pr.CFrame.Position then return nil end
  local c=pr.CFrame.Position
  local o={origin.X,origin.Y,origin.Z}
  local d={dir.X,dir.Y,dir.Z}
  local mn={c.X-pr.Size.X/2,c.Y-pr.Size.Y/2,c.Z-pr.Size.Z/2}
  local mx={c.X+pr.Size.X/2,c.Y+pr.Size.Y/2,c.Z+pr.Size.Z/2}
  local tmin,tmax=0,1
  local axis,sign=0,0
  for i=1,3 do
    if d[i]==0 then
      if o[i]<mn[i] or o[i]>mx[i] then return nil end
    else
      local t1=(mn[i]-o[i])/d[i]
      local t2=(mx[i]-o[i])/d[i]
      local s1=-1
      if t1>t2 then t1,t2=t2,t1 s1=1 end
      if t1>tmin then tmin=t1 axis=i sign=s1 end
      if t2<tmax then tmax=t2 end
      if tmin>tmax then return nil end
    end
  end
  local pos=mkvec(o[1]+d[1]*tmin,o[2]+d[2]*tmin,o[3]+d[3]*tmin)
  local nrm={0,0,0}
  if axis>0 then nrm[axis]=sign end
  local len=(d[1]^2+d[2]^2+d[3]^2)^0.5
  return pos,mkvec(nrm[1],nrm[2],nrm[3]),tmin*len
end

local includeItem={Name="Include",Value=0}
local excludeItem={Name="Exclude",Value=1}

local genv=setmetatable({},{
  __index=realG,
  __newindex=function(t,k,v)
    if isident(k) then emit("getgenv()."..k.." = "..ser(v)) else emit("getgenv()["..ser(k).."] = "..ser(v)) end
    rawset(t,k,v)
  end,
})

local stub={}
local gameprops={ClassName="DataModel",Name="Game"}
realG.__deobhttp=function(hv)
  varcount=varcount+1
  local lv="v"..varcount
  emit("local "..lv.." = loadstring("..hv..")")
  varcount=varcount+1
  local rv="v"..varcount
  emit("local "..rv.." = "..lv.."()")
  return newspy(rv,nil)
end
local function httpget(self,url,...)
  varcount=varcount+1
  local vn="v"..varcount
  emit("local "..vn.." = game:HttpGet("..ser(url)..")")
  if not probedone then
    probedone=true
    installloader()
  end
  local token='return __deobhttp("'..vn..'")'
  httpmap[token]=vn
  lastkey=token
  return token
end
gameprops.HttpGet=httpget
gameprops.HttpGetAsync=httpget
gameprops.GetService=function(self,svc)
  varcount=varcount+1
  local vn="v"..varcount
  emit("local "..vn.." = game:GetService("..ser(svc)..")")
  return newspy(vn,nil,{ClassName=svc,Name=svc})
end
stub.game=newspy("game",nil,gameprops)
local wsprops={ClassName="Workspace",Name="Workspace"}
wsprops.Raycast=function(self,origin,dir,params)
  varcount=varcount+1
  local vn="v"..varcount
  emit("local "..vn.." = workspace:Raycast("..ser(origin)..", "..ser(dir)..(params~=nil and (", "..ser(params)) or "")..")")
  local list=params and params.FilterDescendantsInstances or {}
  local include=params and params.FilterType and params.FilterType.Name=="Include"
  if include then
    for _,inst in ipairs(list) do
      local pos,nrm,dist=rayhit(inst,origin,dir)
      if pos then
        local res={Instance=inst,Position=pos,Normal=nrm,Distance=dist,Material={Name="Plastic"}}
        names[res]=vn
        return res
      end
    end
  end
  return nil
end
stub.workspace=newspy("workspace",nil,wsprops)
stub.script=newspy("script",nil)
stub.Instance={new=function(class,parent)
  varcount=varcount+1
  local vn="v"..varcount
  if parent~=nil then
    emit("local "..vn.." = Instance.new("..ser(class)..", "..ser(parent)..")")
  else
    emit("local "..vn.." = Instance.new("..ser(class)..")")
  end
  local props={ClassName=class,Name=class,Parent=parent}
  local obj=newspy(vn,nil,props)
  props.Destroy=function(self)
    emit(vn..":Destroy()")
    if probepart~=nil and rawequal(obj,probepart) and not probedone then
      probedone=true
      installloader()
    end
  end
  instances[#instances+1]=obj
  if class=="Part" and probepart==nil and not probedone then probepart=obj end
  return obj
end}
stub.Vector3int16={new=function(x,y,z) return mkvec(x or 0,y or 0,z or 0,"Vector3int16") end}
stub.RaycastParams={new=function() return {FilterType=excludeItem,FilterDescendantsInstances={}} end}
stub.Enum=newspy("Enum",nil,{RaycastFilterType={Include=includeItem,Exclude=excludeItem}})
stub.CFrame={new=function(x,y,z)
  local c={Position=mkvec(x or 0,y or 0,z or 0)}
  names[c]="CFrame.new("..ser(x or 0)..", "..ser(y or 0)..", "..ser(z or 0)..")"
  return c
end}
stub.Vector3={new=function(x,y,z) return mkvec(x or 0,y or 0,z or 0) end}
stub.Vector2={new=function(x,y)
  local v={X=x or 0,Y=y or 0}
  names[v]="Vector2.new("..ser(x or 0)..", "..ser(y or 0)..")"
  return v
end}

for _,nm in ipairs({"Color3","UDim2","UDim","TweenInfo","Rect","BrickColor","Random","Ray","Region3","OverlapParams","NumberRange","NumberSequence","ColorSequence","ColorSequenceKeypoint","NumberSequenceKeypoint","DateTime","Font","PhysicalProperties","Axes","Faces","Drawing"}) do
  stub[nm]=newspy(nm,nil)
end

stub.print=logstmt("print")
stub.warn=logstmt("warn")
stub.wait=blockcall("wait")
stub.spawn=blockcall("spawn")
stub.delay=blockcall("delay")
stub.task={
  wait=blockcall("task.wait"),
  spawn=blockcall("task.spawn"),
  defer=blockcall("task.defer"),
  delay=blockcall("task.delay"),
  cancel=logstmt("task.cancel"),
}
stub.getgenv=function() return genv end
stub.getrenv=function() return realG end

for _,nm in ipairs({"setclipboard","toclipboard","writefile","appendfile","delfile","makefolder","delfolder","queue_on_teleport","setfpscap","firesignal","fireclickdetector","firetouchinterest","fireproximityprompt","mouse1click","mouse1press","mouse1release","mousemoverel","keypress","keyrelease","rconsoleprint","rconsolewarn","rconsoleinfo","rconsoleerr","consoleclear","saveinstance"}) do
  stub[nm]=logstmt(nm)
end

for _,nm in ipairs({"request","http_request","readfile","isfile","isfolder","listfiles","loadfile","dofile","getgc","getinstances","getnilinstances","getconnections","getscripts","getloadedmodules","gethui","checkcaller","getcustomasset","base64encode","base64decode"}) do
  stub[nm]=logvalue(nm)
end

stub.identifyexecutor=function() return "Wave","1.0" end
stub.getexecutorname=function() return "Wave" end
stub.require=logvalue("require")

do
  local mt=getmetatable(realG)
  local idx=mt and mt.__index
  if type(idx)=="table" then
    for k,v in pairs(idx) do
      if rawget(realG,k)==nil then rawset(realG,k,v) end
    end
  end
end

local clicklike={MouseButton1Click=true,Activated=true,MouseButton1Down=true,MouseButton1Up=true,FocusLost=true}

interact=function()
  if interacted then return end
  interacted=true
  local key=lastkey or "deobkey"
  for _,inst in ipairs(instances) do
    local pr=propsof[inst]
    if pr and pr.ClassName=="TextBox" then pr.Text=key end
  end
  local list=handlers
  handlers={}
  for _,h in ipairs(list) do
    if h.ev and clicklike[h.ev] then
      local spies=paramspies(h.fn)
      emit(h.head.."(function("..paramnames(spies)..")")
      indent=indent+1
      pcall(h.fn,table.unpack and table.unpack(spies) or unpack(spies))
      indent=indent-1
      emit("end)")
    end
  end
end

installloader=function()
  local function ident(x) return x end
  realG.cloneref=ident
  realG.clonefunction=ident
  realG.newcclosure=ident
  realG.isexecutorclosure=function() return true end
  realG.checkcaller=function() return true end
  realG.getnamecallmethod=function() return "" end
  realG.setreadonly=function() end
  realG.make_writeable=function() end
  realG.getconnections=function() return {} end
  realG.getrawmetatable=function(x)
    varcount=varcount+1
    return newspy("v"..varcount,nil)
  end
  realG.hookfunction=function(f,h)
    emit("hookfunction("..ser(f)..", "..ser(h)..")")
    return f
  end
  realG.hookmetamethod=function(obj,method,h)
    emit("hookmetamethod("..ser(obj)..", "..ser(method)..", "..ser(h)..")")
    return function() end
  end
  local deny={restorefunction=true,isfunctionhooked=true,getfunctionhash=true,iscclosure=true,islclosure=true,is_synapse_function=true,isourclosure=true,checkclosure=true,getreg=true,getregistry=true,syn=true,http=true,fluxus=true,KRNL_LOADED=true,pebc_execute=true}
  local oldmt=getmetatable(realG)
  local oldidx=oldmt and oldmt.__index
  setmetatable(realG,{__index=function(t,k)
    local v
    if type(oldidx)=="function" then v=oldidx(t,k) elseif type(oldidx)=="table" then v=oldidx[k] end
    if v~=nil then return v end
    if type(k)=="string" and isident(k) and not deny[k] and #k<48 then
      local sp=newspy(k,nil)
      rawset(realG,k,sp)
      return sp
    end
    return nil
  end})
  local orig=realG.loadstring
  realG.loadstring=function(code,chunk)
    if type(code)~="string" then return orig(code,chunk) end
    varcount=varcount+1
    local vn="v"..varcount
    emit("local "..vn.." = loadstring("..ser(code)..")")
    local fn,err=orig(code,chunk)
    if not fn then return fn,err end
    return function(...)
      if httpmap[code] then
        varcount=varcount+1
        local vr="v"..varcount
        emit("local "..vr.." = "..vn.."()")
        return newspy(vr,nil)
      end
      emit(vn.."()")
      return fn(...)
    end
  end
end

for k,v in pairs(stub) do realG[k]=v end

__payload()
'''

SLOT = "local PAYLOAD_SLOT=nil"

dZ=4294967296
LR,LH,LI=1664525,1013904223,256
MODS={'dZ':4294967296,'BM':4294967296,'BQ':2147483647}
def ev(e):
    e=re.sub(r'%([A-Za-z]+)\)',lambda m:'%'+str(MODS.get(m.group(1),4294967296))+')',e)
    return eval(e.replace('^','**'))
def x8(a,b): return (int(a)&255)^(int(b)&255)
def lua_str(src,i):
    q=src[i];j=i+1;out=bytearray()
    while src[j]!=q:
        c=src[j]
        if c=='\\':
            j+=1;c=src[j]
            if c.isdigit():
                k=j
                while k<j+3 and src[k].isdigit(): k+=1
                out.append(int(src[j:k])&255);j=k;continue
            m={'n':10,'t':9,'r':13,'a':7,'b':8,'f':12,'v':11,'\\':92,'"':34,"'":39,'\n':10}
            if c=='x':
                out.append(int(src[j+1:j+3],16));j+=3;continue
            out.append(m[c]);j+=1;continue
        out.append(ord(c));j+=1
    return bytes(out),j+1
def load_key_blob(d):
    i=d.index('local d0={')
    j=i+len('local d0={')
    parts={}
    while True:
        m=re.match(r'\[(\d+)\]=',d[j:])
        if not m: break
        j+=m.end()
        s,j=lua_str(d,j)
        parts[int(m.group(1))]=s
        if d[j]==',': j+=1
        else: break
    return b''.join(parts[k] for k in sorted(parts))
def load_params(d):
    i=d.index('local dG=function(d3,d6)')
    j=d.index('local Lg=',i)
    body=d[i:j]
    c={}
    for name in ['Lk','LB','Lf','LG','Lx','Lq','Ln']:
        m=re.search(r'local '+name+r'=(\(\([^()]*\)%dZ\))',body)
        c[name]=ev(m.group(1))
    m=re.search(r'local dx=(\(\([^()]*\)%dZ\))',d)
    c['dx']=ev(m.group(1))
    return c
class Decryptor:
    def __init__(self,d):
        self.df=load_key_blob(d)
        self.c=load_params(d)
    def B(self,k):
        return self.df[k-1] if 0<k<=len(self.df) else None
    def step(self,d2,LU,dn):
        c=self.c
        d1=(self.B(d2) or 0)+(self.B(d2+1) or 0)*LI
        LS=(c['dx']+dn+(LU*c['Lf'])+(d1%65536)+c['Lk'])%dZ
        LS=((LS*LR)+LH+(LU*c['Lq'])+((c['dx']%65536)*c['Ln']))%dZ
        if LS==0: LS=(c['dx']+1)%dZ
        LS=((LS*LR)+LH+(LU*c['Lf'])+c['Lx']+(d1%65536))%dZ
        return d1,LS
    @staticmethod
    def parts(LS):
        LX=LS%LI;Lt=((LS-LX)//LI)%LI;Lc=((LS-(LS%65536))//65536)%LI;LE=((LS-(LS%16777216))//16777216)%LI
        return LX,Lt,Lc,LE
    def decrypt(self,n,key,dn=0):
        c=self.c
        d2=1;LU=0;Ls=n
        while Ls>0:
            d1,LS=self.step(d2,LU,dn)
            LX,Lt,Lc,LE=self.parts(LS)
            d9=self.B(d2+2)
            if d9 is None: return None
            d4=x8(d9,x8(x8(LX,Lt),x8(Lc,(LE+LU)%LI)))
            d2=d2+3+d4;LU+=1;Ls-=1
        d1,LS=self.step(d2,LU,dn)
        LX,Lt,Lc,LE=self.parts(LS)
        d9=self.B(d2+2)
        if d9 is None: return None
        d4=x8(d9,x8(x8(LX,Lt),x8(Lc,(LE+LU)%LI)))
        out=bytearray()
        for LF in range(1,d4+1):
            LS=((LS*LR)+LH+(LU*c['Lf'])+(LF*c['LB'])+(d4*c['LG'])+(d1%65536)+c['Lx'])%dZ
            LX,Lt,Lc,LE=self.parts(LS)
            d9=self.B(d2+2+LF)
            if d9 is None: return None
            d7=(key+(LF*37)+(d4*13)+(LU*17)+(((key-(key%257))//257)%LI))%LI
            out.append(x8(d9,x8(x8(x8(LX,(Lt+LF)%LI),x8(Lc,(LE+LU+d4)%LI)),d7)))
        return bytes(out)
DG_RE=re.compile(r'dG\((\d+),(\(\(\d+\*3015\+\d+\*7866[-+]\d+\)%[A-Za-z]+\))\)')
def lua_quote(b):
    return '"'+''.join(chr(c) if 32<=c<127 and chr(c) not in '"\\' else '\\%03d'%c for c in b)+'"'
def replace_all(d,dec):
    cache={}
    def rep(m):
        n=int(m.group(1));k=ev(m.group(2))
        if (n,k) not in cache:
            v=dec.decrypt(n,k)
            cache[(n,k)]=lua_quote(v) if v is not None else m.group(0)
        return cache[(n,k)]
    return DG_RE.sub(rep,d),cache


def find_luau(explicit):
    if explicit:
        return explicit
    here = os.path.dirname(os.path.abspath(__file__))
    bundled = "luau.exe" if sys.platform.startswith("win") else "luau"
    for folder in (os.path.join(here, "..", "bin"), here):
        cand = os.path.join(folder, bundled)
        if os.path.isfile(cand):
            return os.path.normpath(cand)
    found = shutil.which("luau")
    if found:
        return found
    raise SystemExit("luau binary not found, pass it with --luau")


def build_runner(source):
    payload = "local __payload=function(...)\n" + source + "\nend"
    return HOOK_LUA.replace(SLOT, payload, 1)


def run_luau(luau, runner_path, timeout):
    cmd = [luau, runner_path]
    if shutil.which("stdbuf"):
        cmd = ["stdbuf", "-o0"] + cmd
    try:
        res = subprocess.run(cmd, capture_output=True, timeout=timeout)
        return res.stdout.decode("latin-1"), res.stderr.decode("latin-1"), False
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or b"").decode("latin-1")
        err = (exc.stderr or b"").decode("latin-1")
        return out, err, True


def extract_log(stdout):
    lines = []
    for line in stdout.split("\n"):
        if line.startswith("DEOB\t"):
            lines.append(line[5:].rstrip("\r"))
    return lines


def prune_unused(lines):
    text = "\n".join(lines)
    out = []
    pat = re.compile(r"^(\s*)local (v\d+) = (.*)$")
    for line in lines:
        m = pat.match(line)
        if m:
            name = m.group(2)
            uses = len(re.findall(r"\b" + name + r"\b", text))
            if uses <= 1:
                out.append(m.group(1) + m.group(3))
                continue
        out.append(line)
    return out


CTOR_RE = re.compile(r"^(UDim2|UDim|Color3|Vector2|Vector3|CFrame|TweenInfo|Rect|BrickColor|NumberRange|NumberSequence|ColorSequence|ColorSequenceKeypoint|NumberSequenceKeypoint|Font)\.\w+\(.*\)$")


def inline_constructors(lines):
    pat = re.compile(r"^(\s*)local (v\d+) = (.*)$")
    text = "\n".join(lines)
    result = list(lines)
    for i, line in enumerate(lines):
        m = pat.match(line)
        if not m or not CTOR_RE.match(m.group(3)):
            continue
        name = m.group(2)
        if len(re.findall(r"\b" + name + r"\b", text)) != 2:
            continue
        for j in range(i + 1, len(result)):
            if re.search(r"\b" + name + r"\b", result[j]):
                result[j] = re.sub(r"\b" + name + r"\b", lambda _m: m.group(3), result[j], count=1)
                result[i] = None
                break
    return [l for l in result if l is not None]


def merge_loaders(lines):
    out = []
    i = 0
    pat = re.compile(r"^(\s*)local (v\d+) = loadstring\((.*)\)$")
    while i < len(lines):
        m = pat.match(lines[i])
        if m and i + 1 < len(lines) and lines[i + 1].strip() == m.group(2) + "()":
            out.append(m.group(1) + "loadstring(" + m.group(3) + ")()")
            i += 2
            continue
        out.append(lines[i])
        i += 1
    return out


def inline_http(lines):
    pat = re.compile(r"^(\s*)local (v\d+) = (game:HttpGet\(.*\))$")
    text = "\n".join(lines)
    result = list(lines)
    for i, line in enumerate(lines):
        m = pat.match(line)
        if not m:
            continue
        name = m.group(2)
        if len(re.findall(r"\b" + name + r"\b", text)) != 2:
            continue
        for j in range(i + 1, len(result)):
            if re.search(r"\b" + name + r"\b", result[j]):
                result[j] = re.sub(r"\b" + name + r"\b", lambda _m: m.group(3), result[j], count=1)
                result[i] = None
                break
    return [l for l in result if l is not None]


def strip_probes(lines):
    part_var = None
    for i, line in enumerate(lines):
        m = re.match(r"^local (v\d+) = Instance\.new\(\"Part\"\)$", line)
        if m:
            part_var = m.group(1)
            start = i
            break
    if part_var is None:
        return lines
    props = set()
    end = None
    for j in range(start + 1, len(lines)):
        line = lines[j]
        pm = re.match(r"^" + part_var + r"\.(\w+) = ", line)
        if pm:
            props.add(pm.group(1))
            continue
        if line == part_var + ":Destroy()":
            end = j
            break
    if end is None or not {"Anchored", "CanCollide", "Transparency", "Size", "CFrame"} <= props:
        return lines
    return lines[end + 1:]


def dump_strings(source, path):
    dec = Decryptor(source)
    out, cache = replace_all(source, dec)
    lines = []
    for (n, k), v in sorted(cache.items()):
        lines.append("%d\t%s" % (n, v))
    open(path, "w", encoding="latin-1").write("\n".join(lines) + "\n")
    return len(cache)


def main():
    ap = argparse.ArgumentParser(description="wYnFuscate dynamic deobfuscator")
    ap.add_argument("input")
    ap.add_argument("-o", "--output")
    ap.add_argument("--luau")
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--keep-runner", action="store_true")
    ap.add_argument("--keep-probes", action="store_true")
    ap.add_argument("--dump-strings")
    args = ap.parse_args()

    source = open(args.input, encoding="latin-1").read()
    luau = find_luau(args.luau)

    base = os.path.splitext(args.input)[0]
    runner_path = base + "_runner.lua"
    open(runner_path, "w", encoding="latin-1").write(build_runner(source))

    stdout, stderr, timed_out = run_luau(luau, runner_path, args.timeout)
    if not args.keep_runner:
        try:
            os.remove(runner_path)
        except OSError:
            pass

    log = prune_unused(extract_log(stdout))
    log = inline_constructors(log)
    log = merge_loaders(log)
    log = inline_http(log)
    if not args.keep_probes:
        log = strip_probes(log)
    output = args.output or (base + "_deobfuscated.lua")
    open(output, "w", encoding="latin-1").write("\n".join(log) + ("\n" if log else ""))

    if args.dump_strings:
        try:
            count = dump_strings(source, args.dump_strings)
            print("decoded %d strings to %s" % (count, args.dump_strings))
        except Exception as exc:
            print("string dump failed: %s" % exc)

    print("recorded %d statements -> %s" % (len(log), output))
    if timed_out:
        print("warning: execution timed out after %d seconds, the log may be incomplete" % args.timeout)
    err_lines = [l for l in (stdout + "\n" + stderr).split("\n") if l and not l.startswith("DEOB\t")]
    if err_lines:
        print("runtime messages:")
        for l in err_lines[:10]:
            print("  " + l)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
