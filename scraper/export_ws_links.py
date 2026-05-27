"""
Generate a clickable HTML price-research file for all top-rated RVF wines.
Opens wine-searcher.com search for each wine in one click.
"""
import json, re
from pathlib import Path

data = json.loads((Path(__file__).parent / "raw/rvf_pages/rvf_ratings_sorted.json").read_text(encoding="utf-8"))

# Deduplicate
seen = {}
for r in data:
    key = (r["producer"], r["cuvee"])
    if key not in seen or r["score_100"] > seen[key]["score_100"]:
        seen[key] = r
unique = sorted(seen.values(), key=lambda x: -x["score_100"])

# Known prices from our research sessions
known_prices = {
    ("Domaine Guffens-Heynen", "Clos de Mornantely"): "not listed",
    ("Domaine Macle", "Côtes du Jura Tradition"): "€38",
    ("Clos du Mont-Olivet", "Côtes du Rhône Vieilles Vignes"): "€12",
    ("Domaine Ganevat", "Côtes du Jura"): "€55",
    ("Domaine Comtes Lafon", "Meursault Genevrières"): "€356",
    ("Domaine Roulot", "Meursault Perrières"): "€470",
    ("Domaine Benoît Moreau", "Chassagne-Montrachet Village"): "€99",
    ("Domaine Matrot", "Blagny"): "€129",
    ("Domaine Guffens-Heynen", "Clos du Cros 2023"): "not listed",
    ("Domaine Henri & Gilles Buisson", "Meursault Premier Cru"): "€92",
    ("Domaine des Lambrays", "Clos des Lambrays"): "€420",
    ("Clos du Mont-Olivet", "La Cuvée du Papet"): "€60 (auction)",
    ("Domaine Dujac", "Chambertin"): "€1,667",
    ("Domaine Comtes Lafon", "Le Montrachet"): "€1,799",
    ("Domaine Ramonet", "Chassagne-Montrachet Morgeot"): "€222",
    ("Domaine Roulot", "Meursault Charmes"): "€636",
    ("Domaine de Marcoux", "Châteauneuf-du-Pape Blanc"): "€50",
    ("Domaine Santa Duc", "Gigondas Aux Lieux-Dits"): "€30",
    ("William Fèvre", "Les Clos"): "€91",
    ("Ridge", "Monte Bello"): "€241",
    ("Domaine Huet", "Vouvray"): "€32",
    ("Domaine Valette", "Le Clos de Mornantely Noly"): "not listed",
    ("Domaine Leflaive", "Puligny-Montrachet Clavoillon"): "€284",
    ("Domaine Ramonet", "Chassagne-Montrachet Ruchottes"): "€243",
    ("Château Montrose", "La Dame de Montrose"): "€33 (EP)",
    ("Château Mouton Rothschild", "Château Mouton Rothshild"): "€419",
    ("Ridge Vineyards", "Monte Bello - Ridge Vineyard"): "€241",
    ("Domaine Ganevat", "En Bilat"): "not listed",
    ("Domaine Macle", "Côtes du Jura Chardonnay"): "€33",
    ("Domaine Claude Dugat", "Griotte-Chambertin"): "€623",
    ("Domaine Joseph Colin", "Chassagne-Montrachet Village"): "€81",
    ("Domaine Bosquet des Papes", "Châteauneuf-du-Pape Blanc"): "€34",
    ("Domaine Jérôme Gradassi", "Châteauneuf-du-Pape Rouge"): "€31",
    ("Maison Jane Eyre", "Gevrey-Chambertin 1er cru"): "€153",
    ("Château Mont-Redon", "Châteauneuf, Vacqueyras, Cairanne, il coche toutes les cases"): "€52",
    ("Le Clos du Caillou", "Réserve le Clos du Caillou"): "€111",
    ("D'Autrefois", "Pinot Noir"): "€15",
    ("Domaine de Nizas", "Le Mas"): "€21",
    ("Château Margaux", "Pavillon Blanc de Château Margau"): "€313",
    ("Domaine Georges Chicotot", "Nuits-Saint-Georges à Nuits-Saint-Georges"): "€47",
    ("Domaine Bois de Boursan", "BOIS DE BOURSAN"): "€27",
    ("Domaine Roger Sabon", "ROGER SABON"): "€44",
    ("Maison Chantereves", "Savigny-lès-Beaune"): "€85",
    ("Domaine Arlaud", "Clos de la Roche Grand Cru"): "€318",
    ("Domaine Arlaud", "Chambolle-Musigny 1er cru"): "€151",
    ("Nicolas Maillet", "Le L'Humin blanc"): "€19",
    ("Domaine Chanterves", "Gevrey-Chambertin"): "not found",
    ("Château Guadet", "La verticale de Château Guadet"): "€66",
    ("Domaine Louis-Claude Desvignes", "Charnu et profond"): "€21",
    ("Domaine Arlaud", "Bonnes-Mares Grand Cru"): "€588",
    ("Domaine Claude Dugat", "Chapelle-Chambertin"): "~€800",
    ("Domaine de la Romanée-Conti", "Montrachet Grand Cru"): "€22,000+",
}

def make_ws_slug(producer, cuvee):
    text = f"{producer} {cuvee}"
    text = re.sub(r"[^a-zA-Z0-9\s]", " ", text)
    text = re.sub(r"\s+", "-", text.strip().lower())
    return text[:80]

html_rows = []
for i, r in enumerate(unique, 1):
    slug = make_ws_slug(r["producer"], r["cuvee"])
    ws_url = f"https://www.wine-searcher.com/find/{slug}"
    v = r["vintage"] or "NV"
    sc = r["score_20"]
    prod = r["producer"]
    cuv = r["cuvee"]
    app = r["appellation"] or ""

    key = (prod, cuv)
    price = known_prices.get(key, "")
    price_cell = f'<td class="price known">{price}</td>' if price else f'<td class="price"><a href="{ws_url}" target="_blank">🔍 lookup</a></td>'

    row_class = "known-row" if price else ""
    html_rows.append(f"""  <tr class="{row_class}">
    <td>{i}</td>
    <td>{sc}</td>
    <td>{prod}</td>
    <td>{cuv}</td>
    <td>{v}</td>
    <td>{app}</td>
    {price_cell}
  </tr>""")

html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>RVF Top Wines — Price Research ({len(unique)} wines)</title>
<style>
  body {{ font-family: Arial, sans-serif; font-size: 13px; background: #1a1a1a; color: #eee; margin: 20px; }}
  h1 {{ color: #E5B25D; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th {{ background: #A53860; color: white; padding: 8px 6px; text-align: left; position: sticky; top: 0; }}
  td {{ padding: 5px 6px; border-bottom: 1px solid #333; }}
  tr:hover td {{ background: #2a2a2a; }}
  .known-row td {{ background: #1a2a1a; }}
  .price.known {{ color: #E5B25D; font-weight: bold; }}
  .price a {{ color: #88aaff; text-decoration: none; }}
  .price a:hover {{ color: #aaccff; }}
  .score {{ font-weight: bold; color: #E5B25D; white-space: nowrap; }}
  input {{ background: #333; color: #eee; border: 1px solid #555; padding: 6px; width: 300px; margin-bottom: 10px; }}
</style>
<script>
function filterTable() {{
  var q = document.getElementById('search').value.toLowerCase();
  var rows = document.querySelectorAll('tbody tr');
  rows.forEach(function(row) {{
    row.style.display = row.textContent.toLowerCase().includes(q) ? '' : 'none';
  }});
}}
</script>
</head>
<body>
<h1>🍷 RVF Top Wines — Price Research</h1>
<p>{len(unique)} unique wines · {sum(1 for r in unique if (r["producer"], r["cuvee"]) in known_prices)} prices already found</p>
<input id="search" onkeyup="filterTable()" placeholder="Filter by producer, wine, appellation...">
<table>
<thead>
  <tr>
    <th>#</th><th>Score</th><th>Producer</th><th>Wine / Cuvée</th><th>Vintage</th><th>Appellation</th><th>Price</th>
  </tr>
</thead>
<tbody>
{''.join(html_rows)}
</tbody>
</table>
</body>
</html>
"""

out = Path(__file__).parent / "raw" / "rvf_pages" / "rvf_price_research.html"
out.write_text(html, encoding="utf-8")
print(f"Written: {out}")
print(f"Total wines: {len(unique)}")
print(f"Prices already known: {sum(1 for r in unique if (r['producer'], r['cuvee']) in known_prices)}")
