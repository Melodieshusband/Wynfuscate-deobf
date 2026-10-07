#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <math.h>
static double LM[18];
static unsigned char *cip;static int n;
#define BQ 2147483647.0
static inline double md(double a,double b){return a-floor(a/b)*b;}
static inline double X(double a,double b){return (double)((uint32_t)(uint64_t)a^(uint32_t)(uint64_t)b);}
#define lm(i) LM[i]
static int dec(double SV,int count,unsigned char*out){
double Le=SV,Oi,OT,Oh,OC,Ob;
Oi=md(md(Le,BQ)+md((double)n,BQ)*lm(1)+lm(2),BQ);if(Oi==0)Oi=1;
OT=md(md(Le,BQ)*lm(3)+md((double)n,BQ)*lm(4)+lm(5),BQ);if(OT==0)OT=1;
Oh=md(X(Oi,OT)+md(Le,BQ)*lm(6)+lm(7),BQ);if(Oh==0)Oh=1;
OC=md(Oh*lm(8)+X(md(md((double)n,BQ)+lm(9),BQ),Oi)+lm(10),BQ);if(OC==0)OC=1;
Ob=md(OC*lm(11)+OT*lm(12)+X(Oh,lm(13))+lm(14),BQ);if(Ob==0)Ob=1;
for(int xN=1;xN<=count;xN++){
double xn=md((double)xN,BQ);
double OV=X((double)cip[xN-1],md(Le,256.0));
out[xN-1]=(unsigned char)OV;
double Op=md(X(X(Ob,md(OV+lm(6),BQ)),md((double)xN+lm(7),BQ))+lm(8),3.0);
if(Op!=0){
if(Op==1){
Ob=md(X(Ob,Ob)*lm(9)+OV*lm(10)+xn*lm(11)+OC+lm(12),BQ);if(Ob==0)Ob=1;
OT=md(Oh*lm(1)+X(OT,md(OT+OV+lm(2),BQ))+xn*lm(3)+lm(4),BQ);if(OT==0)OT=1;
Oh=md(Oh*lm(5)+X(Oh,md(OV*lm(6)+xn,BQ))+Ob+lm(7),BQ);if(Oh==0)Oh=1;
Oi=md(Oi*lm(1)+X(Oh,md(OV*lm(2)+xn,BQ))+Oi+lm(3),BQ);if(Oi==0)Oi=1;
Oi=md(Oi+X(Oi,md(xn+lm(13),BQ))+OT*lm(14)+OV*lm(15)+lm(16),BQ);if(Oi==0)Oi=1;
OC=md(OC*lm(13)+X(OC,md(OT+OV+lm(14),BQ))+xn*lm(15)+lm(16),BQ);if(OC==0)OC=1;
}else{
Oi=md(X(Oi,md(OV+lm(13),BQ))*lm(14)+X(Oi,Oh)+xn*lm(15)+lm(16),BQ);if(Oi==0)Oi=1;
Oh=md(X(Oh,Oh)*lm(2)+OV*lm(3)+xn*lm(4)+Oh+lm(5),BQ);if(Oh==0)Oh=1;
OC=md(OC+X(OC,md(xn+lm(10),BQ))+OC*lm(11)+OV*lm(12)+lm(13),BQ);if(OC==0)OC=1;
Ob=md(Ob*lm(6)+X(Ob,md(Ob+OV+lm(7),BQ))+xn*lm(8)+lm(9),BQ);if(Ob==0)Ob=1;
Oi=md(X(Oi,Ob)*lm(1)+OV*lm(2)+xn*lm(3)+Oi+lm(4),BQ);if(Oi==0)Oi=1;
OT=md(X(OT,md(OV+lm(14),BQ))*lm(15)+X(OT,OT)+xn*lm(16)+lm(1),BQ);if(OT==0)OT=1;
}
}else{
Oi=md(Oi*lm(13)+X(Oi,md(OC+OV+lm(14),BQ))+xn*lm(15)+lm(16),BQ);if(Oi==0)Oi=1;
OC=md(OC*lm(16)+OC*lm(1)+X(Oh,md(OV+xn+lm(2),BQ))+lm(3),BQ);if(OC==0)OC=1;
Oh=md(OC*lm(8)+X(Oh,md(Oh+OV+lm(9),BQ))+xn*lm(10)+lm(11),BQ);if(Oh==0)Oh=1;
OT=md(X(OT,md(Ob+lm(4),BQ))+OT*lm(5)+OV*lm(6)+xn+lm(7),BQ);if(OT==0)OT=1;
Oi=md(Oi*lm(1)+X(Oi,md(OT+OV+lm(2),BQ))+xn*lm(3)+lm(4),BQ);if(Oi==0)Oi=1;
Ob=md(Ob*lm(12)+X(Ob,md(OV*lm(13)+xn,BQ))+OT+lm(14),BQ);if(Ob==0)Ob=1;
}
double OP=md(md(OC+X(Oh,OC)+Oh*lm(11)+OV*lm(12)+md((double)xN,BQ)*lm(13)+lm(5),BQ),3.0);
Le=md(Le*48271.0+81.0,BQ);
if(OP==1){Le=md(Le*48271.0+81.0,BQ);}
else if(OP==2){Le=md(Le*48271.0+81.0,BQ);Le=md(Le*48271.0+81.0,BQ);}
}
return 0;}

static int strict_lz(unsigned char*d,int dn,int total,unsigned char*out,int*used){
int o=0,pos=0;
#define AT(i) ((i)<dn?d[i]:0)
while(o<total){
if(pos>=dn)return 0;
int flags=d[pos++];
for(int b=0;b<8&&o<total;b++){
int bit=flags&1;flags>>=1;
if(bit){
if(pos+1>=dn+1)return 0;
int lo=AT(pos),hi=AT(pos+1);pos+=2;
int top=hi/16;int dist=top*256+lo;
if(top==15){dist=AT(pos)*256+lo;pos++;}
int low=hi-top*16;int len=low+3;
if(low==15){int ex=0;for(;;){int x=AT(pos);pos++;ex+=x;if(x!=255)break;if(pos>dn)return 0;}len=18+ex;}
int st=o-(dist+1);
if(st<0)return 0;
for(int k=0;k<len&&o<total;k++){out[o]=out[st+k];o++;}
}else{
if(pos>=dn)return 0;
out[o++]=d[pos++];
}
}
}
*used=pos;
return 1;}

static int partial_lz(unsigned char*d,int dn,unsigned char*out){
int o=0,pos=0;
while(pos<dn-12){
int flags=d[pos++];
for(int b=0;b<8&&pos<dn-12;b++){
int bit=flags&1;flags>>=1;
if(bit){
int lo=d[pos],hi=d[pos+1];pos+=2;
int top=hi/16;int dist=top*256+lo;
if(top==15){dist=d[pos]*256+lo;pos++;}
int low=hi-top*16;int len=low+3;
if(low==15){int ex=0;for(;;){int x=d[pos];pos++;ex+=x;if(x!=255)break;if(pos>=dn-12)return 0;}len=18+ex;}
int st=o-(dist+1);
if(st<0)return 0;
if(o+len>4000)return 0;
for(int k=0;k<len;k++){out[o]=out[st+k];o++;}
}else{out[o++]=d[pos++];}
}
}
return 1;}
int main(int argc,char**argv){
FILE*f=fopen("stream_cipher.bin","rb");cip=malloc(1<<20);n=fread(cip,1,1<<20,f);fclose(f);
f=fopen("stream_lm.txt","r");for(int i=1;i<=16;i++){double v;if(fscanf(f,"%lf",&v)!=1)return 1;LM[i]=v;}fclose(f);
int total=atoi(argv[1]);
unsigned char o[256],out[8192];
unsigned char*plain=malloc(n+8),*out2=malloc(total+64);
for(uint32_t sv=1;sv<2147483647u;sv++){
if(((sv^cip[0])&31)!=0)continue;
dec((double)sv,6,o);
if(!((o[4]>=50&&o[4]<=55)&&(o[0]&31)==0))continue;
dec((double)sv,80,o);
if(!partial_lz(o,80,out))continue;
dec((double)sv,n,plain);
int used=0;
if(strict_lz(plain,n,total,out2,&used))printf("%u used=%d of %d hdr=%02x%02x%02x%02x%02x%02x\n",sv,used,n,out2[0],out2[1],out2[2],out2[3],out2[4],out2[5]);
}
return 0;}
