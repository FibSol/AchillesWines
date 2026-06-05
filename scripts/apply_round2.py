"""Round-2 updater: upgrade ratings to verified (Vivino avg+count, pro scores),
drop estimations once a verified rating exists, fill ABV and classification (organic).
Idempotent and safe to re-run. Owner: cave import round 2."""
import sqlite3, json, re, unicodedata, hashlib, glob, os, sys
sys.stdout.reconfigure(encoding="utf-8")
DB=r"C:\Claude\achilles-wines\data\achilles.db"
BATCH="cave_manual_import_20260605"
RDIR=r"C:\Claude\achilles-wines\scripts\research2"

def norm_text(s):
    if not s: return ""
    out="".join(c for c in unicodedata.normalize("NFKD",str(s)) if not unicodedata.combining(c)).lower()
    out=re.sub(r"[,.'\"/\-()\[\]_&+]"," ",out); return re.sub(r"\s+"," ",out).strip()
def normp(name):
    n=re.sub(r"\b(19|20)\d{2}\b"," ",norm_text(name)); n=re.sub(r"\s+"," ",n).strip()
    for pat,repl in [(r"^d\s+","domaine "),(r"^dom\s+","domaine "),(r"^ch\s+","chateau ")]:
        if re.match(pat,n): n=re.sub(pat,repl,n);break
    return n
TAILS=[r"\b1\s*er\s+(grand\s+)?cru(\s+classe)?\b",r"\b[2-5](\s*e|eme|ème)\s+cru(\s+classe)?\b",r"\bgrand\s+cru(\s+classe)?\b",r"\b(19|20)\d{2}\b",r"\b\d+\s*ml\b",r"\b\d+\s*cl\b",r"\b(magnum|jeroboam|mathusalem|salmanazar|balthazar|nabuchodonosor)\b"]
def cct(n):
    for p in TAILS: n=re.sub(p," ",n)
    return re.sub(r"\s+"," ",n).strip()
def saff(name):
    n=norm_text(name); n=re.sub(r"\b(aoc|aop|igp|igt|doc|docg|do|dop|vdp|vdf)\b"," ",n)
    return re.sub(r"\s+"," ",n).strip()
def ncuvee(name,sw):
    b=norm_text(name)
    for w in sw:
        if w: b=re.sub(rf"\b{re.escape(w)}\b"," ",b)
    return cct(re.sub(r"\s+"," ",b).strip())
def wkey(pn,cn,v,ml):
    return hashlib.sha1(f"{pn}|{cn}|{'NV' if v is None else v}|{ml}".encode()).hexdigest()[:16]

VALID_CODES={'WA','Vinous','BH','JMIB','RVF','Decanter','JS','JG','WS','Hachette','CT','XW','WE','VI','SM'}
VALID_SCALES={'/100','/20','/5','stars'}
AGG={'VI','CT','XW'}
def norm100(scale,score,cc):
    if score is None: return None
    if scale=="/100": v=score
    elif scale=="/20": v=score/20*100
    elif scale=="/5": v=score/5*100
    elif scale=="stars": v=score/3*100 if cc=="Hachette" else score/5*100
    else: v=score
    return max(0.0,min(100.0,round(v,1)))

cave=json.load(open(r"C:\Claude\achilles-wines\scripts\_cave.json",encoding="utf-8"))
out={}
for f in sorted(glob.glob(os.path.join(RDIR,"out_*.json"))):
    for o in json.load(open(f,encoding="utf-8")): out[o["id"]]=o

db=sqlite3.connect(DB); db.execute("PRAGMA foreign_keys=ON"); cur=db.cursor()
def sc(q,*a):
    r=cur.execute(q,a).fetchone(); return r[0] if r else None
SRC_R=sc("SELECT source_key FROM dim_source WHERE source_code='cave_research'")
SRC_E=sc("SELECT source_key FROM dim_source WHERE source_code='cave_estimate'")

st={k:0 for k in ["vivino_set","pro_set","abv_set","class_set","est_dropped","cuvee_fix","grapes_added","skipped_bad"]}
CLASS_OK={"Biodynamie","Bio","Bio (conversion)","Durable/HVE","Conventionnel"}

def resolve_variety(vname,color):
    vn=norm_text(vname)
    if not vn: return None
    k=sc("SELECT variety_key FROM dim_variety WHERE variety_norm=?",vn)
    if not k:
        fam={"red":"red","white":"white","rosé":"red","sparkling":"white"}.get(color,"other")
        cur.execute("INSERT INTO dim_variety(variety_name,variety_norm,color_family) VALUES(?,?,?)",(vname.strip(),vn,fam))
        k=cur.lastrowid
    return k

for i,d in enumerate(cave):
    e=out.get(i)
    if not e: continue
    pn=normp(d["producer"]); an=saff(d["appellation"]); cn=ncuvee(d["wine_name"],[pn,an]) or norm_text(d["wine_name"])
    vraw=d["vintage"]; v=int(vraw) if (vraw is not None and str(vraw).strip().isdigit()) else None
    wk=wkey(pn,cn,v,int(d["format_ml"]))
    color=cur.execute("SELECT color FROM dim_wine WHERE wine_key=?",(wk,)).fetchone()
    color=color[0] if color else "red"

    # 1. Vivino -> verified VI (replace any VI rows for this wine in batch)
    viv=e.get("vivino")
    if viv and viv.get("avg5") is not None:
        avg5=float(viv["avg5"])
        if 0<avg5<=5:
            cur.execute("DELETE FROM fact_rating WHERE wine_key=? AND batch_id=? AND critic_code='VI'",(wk,BATCH))
            cur.execute("""INSERT INTO fact_rating(wine_key,source_key,critic_code,reviewer_type,score,scale,
                score_normalized_100,rating_count,source_url,content_hash,batch_id)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (wk,SRC_R,"VI","user_aggregate",round(avg5,2),"/5",norm100("/5",avg5,"VI"),
                 viv.get("count"),viv.get("url"),"vivino round2",BATCH))
            st["vivino_set"]+=1

    # 2. pro_ratings -> verified (upsert per critic_code)
    for r in (e.get("pro_ratings") or []):
        cc=r.get("critic_code"); scale=r.get("scale"); score=r.get("score")
        if cc not in VALID_CODES or scale not in VALID_SCALES or score is None:
            st["skipped_bad"]+=1; continue
        if cc=="VI": continue  # handled above
        n100=norm100(scale,score,cc)
        if n100 is None: continue
        rtype="user_aggregate" if cc in AGG else "critic"
        cur.execute("DELETE FROM fact_rating WHERE wine_key=? AND batch_id=? AND critic_code=? AND source_key=?",
                    (wk,BATCH,cc,SRC_R))
        cur.execute("""INSERT INTO fact_rating(wine_key,source_key,critic_code,reviewer_type,score,scale,
            score_normalized_100,rating_count,source_url,content_hash,batch_id)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (wk,SRC_R,cc,rtype,float(score),scale,n100,None,r.get("source_url"),"pro round2",BATCH))
        st["pro_set"]+=1

    # 3. drop estimations if wine now has a verified rating
    nver=sc("SELECT COUNT(*) FROM fact_rating WHERE wine_key=? AND batch_id=? AND source_key=?",wk,BATCH,SRC_R)
    if nver and nver>0:
        dele=sc("SELECT COUNT(*) FROM fact_rating WHERE wine_key=? AND batch_id=? AND source_key=?",wk,BATCH,SRC_E)
        if dele:
            cur.execute("DELETE FROM fact_rating WHERE wine_key=? AND batch_id=? AND source_key=?",(wk,BATCH,SRC_E))
            st["est_dropped"]+=dele

    # 4. ABV fill if null
    abv=e.get("abv_pct")
    if abv is not None:
        cur.execute("UPDATE dim_wine SET alcohol_pct=? WHERE wine_key=? AND alcohol_pct IS NULL",(abv,wk))
        if cur.rowcount: st["abv_set"]+=1

    # 5. classification
    cl=e.get("classification")
    if cl in CLASS_OK:
        cur.execute("UPDATE dim_wine SET classification=? WHERE wine_key=?",(cl,wk))
        st["class_set"]+=1

    # 6. cuvee/grape corrections
    cf=e.get("cuvee_correction")
    if cf and isinstance(cf,str) and cf.strip().lower() not in ("null","none",""):
        if str(d["wine_name"]).strip().lower()=="a confirmer":
            cur.execute("UPDATE dim_wine SET cuvee_name=? WHERE wine_key=?",(cf.strip()[:120],wk))
            st["cuvee_fix"]+=1
        # if it looks like a grape list, add to bridge
        grapes=re.findall(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ \-']{2,}", cf)
        known=["Gewurztraminer","Petit Manseng","Chardonnay","Pinot Noir","Pinot Blanc","Feteasca Alba","Sauvignon Blanc","Grenache","Syrah","Mourvedre","Roussanne","Marsanne","Clairette","Viognier"]
        for g in known:
            if g.lower() in cf.lower():
                vk=resolve_variety(g,color)
                if vk:
                    cur.execute("INSERT OR IGNORE INTO bridge_wine_variety(wine_key,variety_key,share_pct,source_confidence) VALUES(?,?,?,0.7)",(wk,vk,None))
                    if cur.rowcount: st["grapes_added"]+=1

db.commit()
print("=== ROUND 2 APPLIED ===")
for k,v in st.items(): print(f"  {k:16s} {v}")
# final state
print("\n=== FINAL fact_rating (batch) ===")
for r in cur.execute("""SELECT s.source_code, COUNT(*) FROM fact_rating fr JOIN dim_source s ON s.source_key=fr.source_key
                        WHERE fr.batch_id=? GROUP BY 1""",(BATCH,)): print("  ",r)
print("  total:", sc("SELECT COUNT(*) FROM fact_rating WHERE batch_id=?",BATCH))
print("  VI with count:", sc("SELECT COUNT(*) FROM fact_rating WHERE batch_id=? AND critic_code='VI' AND rating_count IS NOT NULL",BATCH))
# wines coverage
wks=set()
for i,d in enumerate(cave):
    pn=normp(d["producer"]); an=saff(d["appellation"]); cn=ncuvee(d["wine_name"],[pn,an]) or norm_text(d["wine_name"])
    vraw=d["vintage"]; v=int(vraw) if (vraw is not None and str(vraw).strip().isdigit()) else None
    wks.add(wkey(pn,cn,v,int(d["format_ml"])))
ph=",".join("?"*len(wks))
print("\n  cave wines:",len(wks))
print("  wines w/ verified rating:", sc(f"SELECT COUNT(DISTINCT wine_key) FROM fact_rating WHERE batch_id=? AND source_key=? AND wine_key IN ({ph})",BATCH,SRC_R,*wks))
print("  wines w/ estimation only:", sc(f"SELECT COUNT(DISTINCT wine_key) FROM fact_rating WHERE batch_id=? AND source_key=? AND wine_key IN ({ph})",BATCH,SRC_E,*wks))
print("  wines w/ alcohol_pct:", sc(f"SELECT COUNT(*) FROM dim_wine WHERE wine_key IN ({ph}) AND alcohol_pct IS NOT NULL",*wks))
print("  wines w/ classification:", sc(f"SELECT COUNT(*) FROM dim_wine WHERE wine_key IN ({ph}) AND classification IS NOT NULL",*wks))
db.close()
