"""Authoritative Vivino enrichment via the explore API (search_term).
Conservative matching: producer token must match; color must not conflict;
cuvee overlap or single-candidate required. Writes _vivino_matches.json."""
import httpx, json, re, unicodedata, time, sys
sys.stdout.reconfigure(encoding="utf-8")
UA=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
H={"User-Agent":UA,"Accept":"application/json","Accept-Language":"fr-FR,fr;q=0.9,en;q=0.8","Referer":"https://www.vivino.com/fr/explore"}
URL="https://www.vivino.com/api/explore/explore"
TYPE_COLOR={1:"red",2:"white",3:"sparkling",4:"rosé",7:"sweet",24:"fortified"}

def nt(s):
    if not s: return ""
    out="".join(c for c in unicodedata.normalize("NFKD",str(s)) if not unicodedata.combining(c)).lower()
    return re.sub(r"\s+"," ",re.sub(r"[^a-z0-9 ]"," ",out)).strip()
PSTOP={"domaine","chateau","champagne","clos","vignoble","vignobles","fils","freres","scev","et","de","du","des","la","le","les","famille","cave","caves","maison","by","m"}
CSTOP={"aoc","aop","igp","igt","doc","docg","cuvee","rouge","blanc","rose","vin","de","la","le","les","du","des","et","aop","brut"}
def ptoks_list(s): return [t for t in nt(s).split() if t not in PSTOP and len(t)>2]
def ptok(s): return set(ptoks_list(s))
def distinctive(s):
    """Estate/surname token = last significant producer token (len>=4)."""
    toks=[t for t in ptoks_list(s) if len(t)>=4]
    return toks[-1] if toks else (ptoks_list(s)[-1] if ptoks_list(s) else None)
def ctok(s,app,prod):
    aw=set(nt(app).split()); pw=ptok(prod)
    return set(t for t in nt(s).split() if t not in CSTOP and t not in aw and t not in pw and len(t)>2)

def map_color(c,app):
    a=nt(app)
    if any(x in a for x in ["champagne","cremant","prosecco","cava","franciacorta","spumante","sekt"]): return "sparkling"
    c=(c or "").lower()
    if c.startswith("roug"): return "red"
    if c.startswith("ros"): return "rosé"
    if c.startswith("blan"): return "white"
    if c=="sake": return "sake"
    return "white"

cave=json.load(open(r"C:\Claude\achilles-wines\scripts\_cave.json",encoding="utf-8"))

def search(term,per=12):
    for attempt in range(3):
        try:
            r=httpx.get(URL,params={"search_term":term,"min_rating":1,"price_range_min":0,"price_range_max":5000,"per_page":per},headers=H,timeout=40,follow_redirects=True)
            if r.is_success: return (r.json().get("explore_vintage") or {}).get("matches") or []
        except Exception:
            time.sleep(2)
    return []

results={}
for i,d in enumerate(cave):
    ccolor=map_color(d["color"],d["appellation"])
    if ccolor=="sake":
        results[i]={"match":None,"reason":"sake-skip"}; continue
    cave_dist=distinctive(d["producer"]); ct=ctok(d["wine_name"],d["appellation"],d["producer"])
    vtg=d["vintage"]; vtg=int(vtg) if (vtg is not None and str(vtg).strip().isdigit()) else None
    q1=re.sub(r"\(.*?\)"," ",f'{d["producer"]} {d["wine_name"]}')
    cands=search(q1)
    if not cands:
        cands=search(d["producer"])
    best=None
    for m in cands:
        vo=m.get("vintage") or {}; wo=vo.get("wine") or {}; stx=vo.get("statistics") or {}
        winery=(wo.get("winery") or {}).get("name") or ""
        wname=wo.get("name") or ""
        tid=wo.get("type_id"); vcolor=TYPE_COLOR.get(tid)
        # STRICT producer gate: estate/surname token must be present in winery
        if not cave_dist or cave_dist not in ptok(winery):
            continue
        if vcolor and ccolor in ("red","white","rosé","sparkling") and vcolor!=ccolor:
            continue                 # color conflict -> reject
        wct=ctok(wname,d["appellation"],winery)
        overlap=ct & wct
        # cuvee gate: if cave has a cuvee, require overlap; if cave is pure-appellation,
        # the vivino wine must also be pure-appellation (no extra distinctive cuvee tokens)
        if ct:
            if not overlap: continue
        else:
            if wct: continue
        y=vo.get("year")
        try: y=int(y)
        except: y=None
        avg=stx.get("ratings_average"); cnt=stx.get("ratings_count")
        if not avg or avg<=0: continue
        score=(2 if overlap else 0)+(1 if (y and vtg and y==vtg) else 0)+(0.3 if vcolor==ccolor else 0)
        cand={"winery":winery,"wname":wname,"year":y,"avg5":round(float(avg),2),"count":cnt,
              "wine_id":wo.get("id"),"vcolor":vcolor,"overlap":sorted(overlap),"score":score}
        if best is None or score>best["score"] or (score==best["score"] and (cand["count"] or 0)>(best["count"] or 0)):
            best=cand
    if best:
        best["url"]=f"https://www.vivino.com/w/{best['wine_id']}"
        results[i]={"match":best,"reason":"matched"}
    else:
        results[i]={"match":None,"reason":"no-confident-match","ncands":len(cands)}
    time.sleep(0.6)

json.dump(results, open(r"C:\Claude\achilles-wines\scripts\_vivino_matches.json","w",encoding="utf-8"), ensure_ascii=False, indent=1)
matched=sum(1 for v in results.values() if v["match"])
print(f"matched {matched}/{len(cave)}")
print("\n=== MATCHES ===")
for i,d in enumerate(cave):
    v=results[i]
    if v["match"]:
        m=v["match"]
        print(f"  id{i:2d} {d['producer'][:24]:24s} | {d['wine_name'][:26]:26s} {d['vintage']} -> VIV {m['winery'][:20]}/{m['wname'][:24]} {m['year']} avg{m['avg5']} n{m['count']} (ov={m['overlap']})")
print("\n=== NO MATCH ===")
for i,d in enumerate(cave):
    if not results[i]["match"]:
        print(f"  id{i:2d} {d['producer'][:26]:26s} | {d['wine_name'][:30]:30s} {d['vintage']}  [{results[i]['reason']}]")
