"""Apply authoritative Vivino matches (real avg + count) from _vivino_matches.json.
Replaces snippet-based VI ratings; then drops estimations where a verified rating exists."""
import sqlite3, json, re, unicodedata, hashlib, sys
sys.stdout.reconfigure(encoding="utf-8")
DB=r"C:\Claude\achilles-wines\data\achilles.db"; BATCH="cave_manual_import_20260605"
EXCLUDE={51}  # id51 Pure Clairette wrongly hit the Pure Roussanne page

def nt(s):
    if not s: return ""
    out="".join(c for c in unicodedata.normalize("NFKD",str(s)) if not unicodedata.combining(c)).lower()
    return re.sub(r"\s+"," ",re.sub(r"[,.'\"/\-()\[\]_&+]"," ",out)).strip()
def normp(name):
    n=re.sub(r"\b(19|20)\d{2}\b"," ",nt(name)); n=re.sub(r"\s+"," ",n).strip()
    for pat,repl in [(r"^d\s+","domaine "),(r"^dom\s+","domaine "),(r"^ch\s+","chateau ")]:
        if re.match(pat,n): n=re.sub(pat,repl,n);break
    return n
TAILS=[r"\b1\s*er\s+(grand\s+)?cru(\s+classe)?\b",r"\b[2-5](\s*e|eme|ème)\s+cru(\s+classe)?\b",r"\bgrand\s+cru(\s+classe)?\b",r"\b(19|20)\d{2}\b",r"\b\d+\s*ml\b",r"\b\d+\s*cl\b",r"\b(magnum|jeroboam|mathusalem|salmanazar|balthazar|nabuchodonosor)\b"]
def cct(n):
    for p in TAILS: n=re.sub(p," ",n)
    return re.sub(r"\s+"," ",n).strip()
def saff(name):
    n=nt(name); n=re.sub(r"\b(aoc|aop|igp|igt|doc|docg|do|dop|vdp|vdf)\b"," ",n); return re.sub(r"\s+"," ",n).strip()
def ncuvee(name,sw):
    b=nt(name)
    for w in sw:
        if w: b=re.sub(rf"\b{re.escape(w)}\b"," ",b)
    return cct(re.sub(r"\s+"," ",b).strip())
def wkey(pn,cn,v,ml): return hashlib.sha1(f"{pn}|{cn}|{'NV' if v is None else v}|{ml}".encode()).hexdigest()[:16]

cave=json.load(open(r"C:\Claude\achilles-wines\scripts\_cave.json",encoding="utf-8"))
matches=json.load(open(r"C:\Claude\achilles-wines\scripts\_vivino_matches.json",encoding="utf-8"))
db=sqlite3.connect(DB); db.execute("PRAGMA foreign_keys=ON"); cur=db.cursor()
def sc(q,*a):
    r=cur.execute(q,a).fetchone(); return r[0] if r else None
SRC_R=sc("SELECT source_key FROM dim_source WHERE source_code='cave_research'")
SRC_E=sc("SELECT source_key FROM dim_source WHERE source_code='cave_estimate'")

applied=0
for i,d in enumerate(cave):
    if i in EXCLUDE: continue
    mm=matches.get(str(i)) or {}
    m=mm.get("match")
    if not m or not m.get("avg5"): continue
    pn=normp(d["producer"]); an=saff(d["appellation"]); cn=ncuvee(d["wine_name"],[pn,an]) or nt(d["wine_name"])
    vraw=d["vintage"]; v=int(vraw) if (vraw is not None and str(vraw).strip().isdigit()) else None
    wk=wkey(pn,cn,v,int(d["format_ml"]))
    avg5=float(m["avg5"]); n100=round(avg5/5*100,1)
    url=m.get("url") or ""
    if m.get("year"): url+=f"  (millesime {m['year']})"
    cur.execute("DELETE FROM fact_rating WHERE wine_key=? AND batch_id=? AND critic_code='VI'",(wk,BATCH))
    cur.execute("""INSERT INTO fact_rating(wine_key,source_key,critic_code,reviewer_type,score,scale,
        score_normalized_100,rating_count,source_url,content_hash,batch_id)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (wk,SRC_R,"VI","user_aggregate",round(avg5,2),"/5",n100,m.get("count"),url,"vivino api",BATCH))
    applied+=1

# drop estimations where a verified rating now exists
dropped=0
seen=set()
for i,d in enumerate(cave):
    pn=normp(d["producer"]); an=saff(d["appellation"]); cn=ncuvee(d["wine_name"],[pn,an]) or nt(d["wine_name"])
    vraw=d["vintage"]; v=int(vraw) if (vraw is not None and str(vraw).strip().isdigit()) else None
    wk=wkey(pn,cn,v,int(d["format_ml"]))
    if wk in seen: continue
    seen.add(wk)
    if sc("SELECT COUNT(*) FROM fact_rating WHERE wine_key=? AND batch_id=? AND source_key=?",wk,BATCH,SRC_R):
        c=sc("SELECT COUNT(*) FROM fact_rating WHERE wine_key=? AND batch_id=? AND source_key=?",wk,BATCH,SRC_E)
        if c:
            cur.execute("DELETE FROM fact_rating WHERE wine_key=? AND batch_id=? AND source_key=?",(wk,BATCH,SRC_E))
            dropped+=c
db.commit()
print(f"vivino applied: {applied}   estimations dropped: {dropped}")
# final coverage
wks=set()
for i,d in enumerate(cave):
    pn=normp(d["producer"]); an=saff(d["appellation"]); cn=ncuvee(d["wine_name"],[pn,an]) or nt(d["wine_name"])
    vraw=d["vintage"]; v=int(vraw) if (vraw is not None and str(vraw).strip().isdigit()) else None
    wks.add(wkey(pn,cn,v,int(d["format_ml"])))
ph=",".join("?"*len(wks))
print("cave unique wines:",len(wks))
print("  total ratings(batch):", sc("SELECT COUNT(*) FROM fact_rating WHERE batch_id=?",BATCH))
print("  verified rows:", sc("SELECT COUNT(*) FROM fact_rating WHERE batch_id=? AND source_key=?",BATCH,SRC_R))
print("  estimate rows:", sc("SELECT COUNT(*) FROM fact_rating WHERE batch_id=? AND source_key=?",BATCH,SRC_E))
print("  VI with count:", sc("SELECT COUNT(*) FROM fact_rating WHERE batch_id=? AND critic_code='VI' AND rating_count IS NOT NULL",BATCH))
print("  wines w/ verified:", sc(f"SELECT COUNT(DISTINCT wine_key) FROM fact_rating WHERE batch_id=? AND source_key=? AND wine_key IN ({ph})",BATCH,SRC_R,*wks))
print("  wines w/ estimation only:", sc(f"SELECT COUNT(DISTINCT wine_key) FROM fact_rating WHERE batch_id=? AND source_key=? AND wine_key IN ({ph}) AND wine_key NOT IN (SELECT wine_key FROM fact_rating WHERE batch_id=? AND source_key=?)",BATCH,SRC_E,*wks,BATCH,SRC_R))
print("  wines w/ NO rating:", len(wks)-sc(f"SELECT COUNT(DISTINCT wine_key) FROM fact_rating WHERE batch_id=? AND wine_key IN ({ph})",BATCH,*wks))
db.close()
