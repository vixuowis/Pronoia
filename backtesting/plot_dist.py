"""可视化 PAPV 5k 数据分布 → backtesting/plots/data_distribution_5k.png"""
import json, collections, datetime
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

E=[json.loads(l) for l in open("/workspace/backtesting/events_papv_5k.jsonl") if l.strip()]
L=[json.loads(l) for l in open("/workspace/backtesting/labels_papv_5k.jsonl") if l.strip()]

plt.rcParams.update({"font.size":9,"axes.titlesize":11,"figure.facecolor":"white"})
fig,axes=plt.subplots(3,3,figsize=(15,12))
fig.suptitle("PAPV 5k Dataset Distribution  (events=labels=5171)",y=0.98,fontsize=13,fontweight="bold")

def tidy(c,top=None):
    m=c.most_common(top)
    return [x for x in m if x[1]>0]

# 1 market
ax=axes[0,0]
m=collections.Counter(r.get("market") for r in E)
labs=[f"{k} ({v})" for k,v in m.items()]
ax.pie(m.values(),labels=labs,autopct="%.1f%%",startangle=90,colors=["#4e79a7","#f28e2b"])
ax.set_title("Market Split")

# 2 event_type
ET_EN={"财报超预期/不及预期":"Earnings Beat/Miss","并购/分拆/再融资":"M&A/Spinoff/Refi","公司指引上调/下调":"Guidance Up/Down","增长/就业数据意外":"Growth/Jobs Surprise","通胀数据意外":"Inflation Surprise","政策利率调整":"Policy Rate Move"}
ax=axes[0,1]
e=collections.Counter(ET_EN.get(r.get("event_type_l2"),r.get("event_type_l2")) for r in E)
top=tidy(e,8); labs=[x[0] for x in top]; vals=[x[1] for x in top]
ax.barh(labs[::-1],vals[::-1],color="#59a14f")
ax.set_title("Event Type (L2)")
for i,v in enumerate(vals[::-1]): ax.text(v+10,i,str(v),va="center",fontsize=8)

# 3 top symbols
ax=axes[0,2]
s=collections.Counter(r.get("symbol") for r in E)
top=s.most_common(12); labs=[x[0] for x in top][::-1]; vals=[x[1] for x in top][::-1]
ax.barh(labs,vals,color="#76b7b2")
ax.set_title("Top 12 Symbols")
for i,v in enumerate(vals): ax.text(v+2,i,str(v),va="center",fontsize=8)

# 4 year
ax=axes[1,0]
yrs=collections.Counter(r.get("event_date","")[:4] for r in E)
labs=[k for k,v in sorted(yrs.items())]; vals=[v for k,v in sorted(yrs.items())]
ax.bar(labs,vals,color="#edc948")
ax.set_title("Events by Year"); ax.set_ylabel("count")
for i,v in enumerate(vals): ax.text(i,v+15,str(v),ha="center",fontsize=8)

# 5 consensus direction
ax=axes[1,1]
lab={0:"up",1:"down",2:"neutral"}
net=C=collections.Counter()
for r in L:
    v=r.get("consensus_net")
    if v is None: continue
    if v>0.05: C["up"]+=1
    elif v<-0.05: C["down"]+=1
    else: C["neutral"]+=1
order=["up","down","neutral"]
vals=[C[k] for k in order]
cols=["#59a14f","#e15759","#b7b7b7"]
ax.bar(order,vals,color=cols)
ax.set_title("Label Consensus Direction (consensus_net)")
for i,v in enumerate(vals): ax.text(i,v+20,str(v),ha="center",fontsize=9)

# 6 horizon labels t3/t15/t60 stacked
ax=axes[1,2]
hs=["label_t3","label_t15","label_t60"]
ups=[];downs=[];neus=[];na=[]
for h in hs:
    c=collections.Counter(r.get(h) for r in L)
    ups.append(c.get("up",0));downs.append(c.get("down",0));neus.append(c.get("neutral",0));na.append(c.get("",0))
x=range(len(hs))
ax.bar(x,ups,label="up",color="#59a14f")
ax.bar(x,downs,bottom=ups,label="down",color="#e15759")
ax.bar(x,neus,bottom=[u+d for u,d in zip(ups,downs)],label="neutral",color="#b7b7b7")
ax.set_xticks(list(x)); ax.set_xticklabels(["t3","t15","t60"])
ax.set_title("Per-Horizon Label Direction"); ax.legend(fontsize=8)

# 7 n_horizons_valid
ax=axes[2,0]
nv=collections.Counter(r.get("n_horizons_valid") for r in L)
labs=[str(k) for k,v in sorted(nv.items())];vals=[v for k,v in sorted(nv.items())]
ax.bar(labs,vals,color="#4e79a7")
ax.set_title("Valid Horizons per Event"); ax.set_xlabel("# valid windows")
for i,v in enumerate(vals): ax.text(i,v+20,str(v),ha="center",fontsize=8)

# 8 n_horizons_signed
ax=axes[2,1]
ns=collections.Counter(r.get("n_horizons_signed") for r in L)
labs=[str(k) for k,v in sorted(ns.items())];vals=[v for k,v in sorted(ns.items())]
ax.bar(labs,vals,color="#f28e2b")
ax.set_title("Signed Horizons per Event"); ax.set_xlabel("# signed windows")
for i,v in enumerate(vals): ax.text(i,v+20,str(v),ha="center",fontsize=8)

# 9 date timeline monthly
ax=axes[2,2]
mon=collections.defaultdict(int)
for r in E:
    d=r.get("event_date","")
    if len(d)>=7: mon[d[:7]]+=1
mon=dict(sorted(mon.items()))
ax.fill_between(range(len(mon)),[mon[k] for k in mon],color="#e15759",alpha=0.6)
ax.set_xticks(range(0,len(mon),8))
ax.set_xticklabels([list(mon.keys())[i][:7] for i in range(0,len(mon),8)],rotation=45,fontsize=7)
ax.set_title("Events per Month (2024-01 ~ 2026-06)")

plt.tight_layout(rect=[0,0,1,0.96])
out="/workspace/backtesting/data_distribution_5k.png"
plt.savefig(out,dpi=130)
print("saved",out)