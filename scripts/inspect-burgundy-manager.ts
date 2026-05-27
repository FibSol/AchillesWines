import Database from "better-sqlite3";

const BM_DB = "C:\\Users\\Nicolas\\Bourgogne\\burgundy-manager\\data\\burgundy.db";
const db = new Database(BM_DB, { readonly: true });

for (const tbl of ["appellations","cuvees","ratings","vintage_scores","vintages"]) {
  const cols = (db.prepare(`PRAGMA table_info("${tbl}")`).all() as {name:string;type:string}[]).map(c=>c.name);
  const sample = db.prepare(`SELECT * FROM "${tbl}" LIMIT 3`).all();
  console.log(`\n=== ${tbl} — columns: ${cols.join(", ")} ===`);
  console.log(JSON.stringify(sample, null, 2));
}
db.close();
