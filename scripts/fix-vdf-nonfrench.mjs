#!/usr/bin/env node
/**
 * Delete 355 non-French wines misclassified as "Vin de France" in dim_wine.
 *
 * Source: appellation_vin_de_france_mixed_portfolio entries whose cuvée name
 * contains non-French region/appellation keywords (Napa, Barolo, Marlborough…)
 * AND whose producer's other appellations are all non-French.
 *
 * 11 French Malbec VdF producers are explicitly excluded:
 *   - Château de Gaudou (Cahors/VdF Malbec)
 *   - Fat Bastard (Pays d'Oc Malbec)
 *   - Le Petit Cochonnet (Pays d'Oc Malbec)
 *   - Les Domaines Auriol (Pays d'Oc/CdR Malbec)
 *   - Lionel Osmin & Cie (SW France Malbec)
 *
 * Defaults to DRY-RUN. Pass --apply to mutate.
 */
import Database from 'better-sqlite3';
import { argv } from 'node:process';

const DB_PATH = 'C:/Claude/achilles-wines/data/achilles.db';
const APPLY = argv.includes('--apply');

const db = new Database(DB_PATH, APPLY ? undefined : { readonly: true });
if (APPLY) db.pragma('foreign_keys = OFF');

// French Malbec VdF false positives — keep these, they ARE French wines.
const KEEP_KEYS = new Set([
  // Château de Gaudou (Cahors/VdF Malbec)
  '81f336ad6d5054d0', '0bb1e49b73cc6a84', '9f1667a9e7a3e2ec',
  // Fat Bastard (Pays d'Oc)
  '94180b8add9913aa',
  // Le Petit Cochonnet (Pays d'Oc)
  'a69562a6b0421485',
  // Les Domaines Auriol (Pays d'Oc / Côtes du Rhône)
  'bcb119e7254aa1f0',
  // Lionel Osmin & Cie (SW France: Gaillac, Cahors, Irrouléguy…)
  'e443c8f1f5fff1a8', '9115d13049304c0b', '1b65898c4f3c4ea1',
  '2187200c08f4b613', '28d704565ad958b3',
]);

// All 366 wine_keys identified by the _vdf_nonfrench analysis script,
// minus the 11 KEEP_KEYS above → 355 true non-French wines.
const ALL_NON_FRENCH_KEYS = [
  // #RIVETTI
  '09d91b773d5e71dc',
  // Acaibo
  '7f1f3f40af5584e8',
  // Agricola Punica
  'c81f5d689fbcc9bd','331b5fa4c77da518','30418f7a828b9bbd','0bb33c779510a030',
  // Allegrini
  '858d06ad9944dcc5',
  // Almaviva
  '05571b25d654c162','4b6e2f68859a2f63','c350dbfc7c1d33d0','064ecdce01b6357f',
  // Antinori
  'c67b1e0c8deb8067','5dfffcc7c30c4e09','5b0b5f20f75c2723','a4b13fe5211ed1c8',
  '2de8ebcd65a46619','c359cdb1bb0d0442','996ee488376969f3','46f6e16341235da7',
  '10849c527fa57aa2','d0c58217da3045cf','5dbba30f95ea8aab','e39129103774024a',
  'a078ebb6b0b82be0','68a3ec95413dbc76','6e27c31f25282f38',
  // Antinori Castello della Sala
  '7148410fd8655a31','a7eccb642da412ee','0bc1ca59a8400240','f6e61e8bc62128c3',
  '312c69cf8a8388b2','e991246d4dc50899','8a47b934c8ea895c',
  // Argiano
  '04c849b4293ff12a',
  // Azelia di Luigi Scavino
  '1bbeaf1cdd9ccd26','8fae1f3ba4984fe8','ede40ea463548312',
  // Beaulieu Vineyard
  'f35e6abdcb67f83e',
  // Bibi Graetz
  '688bf354a5547471','1efa35d35cf1474d','27ade7834e140793','0a9eb0853c6a53d5',
  '56c112a0d8cc5acb','146cb086b2cd8548',
  // Bodega Contador
  '78e02c00a668e868','1c3e2df17b65f67e',
  // Bodega Mas Doix
  '072e44798846ca99',
  // Bodegas Caro
  '28546fdc43881bb0','cf9affd1fa7b32ed','433d7507f0d3b588',
  // Bruno Giacosa
  'd21a682cc22410d2',
  // C.V.N.E
  '3ef73cceddf0ae58',
  // Cardinale
  '026422a5b4793ce9','56ac174aa225d3c6',
  // Cascina delle rose
  'ffac5d4e98f616aa',
  // Castellare di Castellina
  '7784a4ce13988d91','5b9051b0793f0de5',
  // Castello di Ama
  'afe6105ea3a01271','29841b9f30600c7c','58cfa648ca7bf67e','944af9253cbc0353',
  '0429989ac315d418',
  // Catena Zapata
  'f1edfb3d915f9efd','4ad838bbb541c3b5','97b4a8c5c931dc70',
  // Ceretto
  'de0ca78f6c4b9183',
  // CHEVAL DES ANDES
  'b48d28db51e015e1','9197ce86f26ecce8','09850557f8b92eb1','53680288ade558f2',
  '0cedff602ca1f5d6',
  // Cloudburst
  '4249a15d31affd67','ab54c68e300ce081',
  // Cloudy Bay
  'b3d6806d867c2d8b','b63b829f15007d92',
  // Domaine Angelo Gaja
  '8dbc0d85922520b6',
  // Domaine Vega Sicilia
  '1157cf7c5a2af0c7',
  // Dominio de Pingus
  '8272a5674c47dd81','e4578fc9167b7409','faf0ceecf0383bea',
  // Dominus Estate
  '8b5b27188169f7f8','c128be90b71b296b','d4cdaa0f33ba392c','9e6f8bde50be8cb6',
  '2a07bef5f2403f4d','a04f37758373ffbf','e63a55dab01acf13',
  // Duemani
  '35f9c21c089502a3','07494734c2d8c5ba',
  // Eisele Vineyard
  'ad3217fa022547b2','cf87b08353aebed6','3ef6bb5428e218ee',
  // Eisele Vineyards
  'dca39792f3c6b35f',
  // Elio Altare
  'ba4017b4e1b17e2f','3b224f476479bc3b',
  // Felsina
  'f415af7a788a5ef1',
  // Felton Road
  '2db665a498743a23','81ed163e4e4c0c28','7b7b72f2c87dd6f1','da62f6ebca89b555',
  // Fontodi
  'e75ea00f2287d045','db20f3387a70fe8e',
  // Fratelli Alessandria
  'c9426449b7c3de2f','9a779eb902ac5726','c63bf0f437f4cf8e','804692a185c4bc2d',
  '5095005bde2a03e7','0167978cdc13d697','3a07c751c073b61d','f79a3407bbdce39f',
  // G.D. Vajra
  '6bc2d88cec020af8',
  // Gaja
  'feaee4d9c9253382','bef02fcc8e6c14a0','e7b777480d4773f9',
  // Giacomo Conterno
  '5cb3209bee5493e5',
  // Giacomo Fenocchio
  '1465856c16177c88',
  // Giacosa Bruno
  '7785c740e2aeca14',
  // Giant Steps
  '823d6bbfdff0dbdc','abd3ba029f192b3a',
  // Giulia Negri
  '6d78d2f5e7f3d3d3','bc1ddd38206d1ea7',
  // Giuseppe Cortese
  '2d8c61d2454535aa','51fb446a3b918d72','6f29685890f6db9a',
  // Giuseppe Mascarello
  '0bddd05dfaeb174f','15cd397854680b0a','90bd3be56be503cd','cab65b01db782d5f',
  // Giuseppe Quintarelli
  '55c5ffffa8a2072c',
  // Giuseppe Rinaldi
  '271d4ad013bf9b13','c84d20fc6378e2d9',
  // Glenelly
  'fb9c9feddb763c72',
  // Grahams
  '56b9507e224cc2c3',
  // Greywacke
  '5a3d609224c128b1','6bf0892a01bbc5b2','3e6f02410d4466ea','2d9af985cf73153e',
  '200580a2725d8766','cc59bc6cd326dc8c','8c7c26809a999c75','a64c4f971bb94757',
  '8623a4e8ddcb61db','a68503193bf09d3a',
  // Henschke
  '3511026c11d24b16','e5796cc384f284bc','fc74b04eb72e6a49','29659573d7c6bf24',
  '86cad265a3072e5f',
  // Inglenook
  '2ddc39227b74ebc5','25900d5da661bd64','5d4712b55346d258','813ed42097db09de',
  'ff6113895e9ea5e8',
  // Joseph Phelps Vineyards
  '8fc6c0780fa22d0d',
  // Kanonkop
  '6f2241e50bf04262',
  // Kanonkop Estate
  '87cf9a89f6117f03','39a2b629594ff6d0','7139e7eeb133b189','249866d0968e36df',
  'e807f40ddb5443cf','973e436de25ca8a5',
  // Kanonkop Wine Estate
  'a53734ef19122741','4d37f4be53b955f1',
  // L'Aventure
  'bd510305070c9279','7772408887a45d54','1de6a6b6fb3dc7fb','412bae28518454c2',
  'ff5f92e4bfd941ae','ea911b5e80d57da1',
  // La Spinetta
  'ed633f19ed3da8aa','bda5cfa222490447','acc3927443dacaa7','f64bc089f52a023c',
  // Le Macchiole
  '10c0e80843444e80',
  // Luciano Sandrone
  'cae597d8fe4d2ea8',
  // Luigi Pira
  '2030fffb055c211d','a6c6b5ac404cc638','6d38a4343d1e528c','68531a8b15fb4b0c',
  '30a709d11e9e2ad9','bdafdf223acc774a','67f61fb111f4b2b5','8d2eb29461b5aa42',
  '98c78aa0e72e36e2',
  // Maison Chandon
  'f7bd860cf4ed65ef',
  // Marchese Antinori Tenuta Tignanello
  '4b4beb72483c12ea',
  // Marqués de Murrieta
  '807a23a22074cc75',
  // Masseto
  '1f584a7b539703e7','cd080a8389db8460',
  // Massolino
  '639c0bb16e375f19','024398448550acba','fe20e5cd86ceb116','7780b9b99adf9e1f',
  '7679fe57e94e2c5e','7f71aeebcc457460','544889a25a93c33a','67274c87cde50c80',
  'a1b3b47412633830','07f612c4caaa3622','eef3bf02abe14c3e','1352d7b4693accc3',
  'f5716537fb3ee848','1e60dd7ad342bca7','06efa05cd14970c1',
  // Maverick
  'e83da9319e2387d0',
  // Maya
  'ddaf8bc5989f8ee4',
  // Meerlust
  'aeefb712364a9d75','8518cca0294873e0',
  // Morlet
  'ffa4e17562a6f7ff',
  // Oddero
  '581066ea2e7ed4b2',
  // Opus One
  '07237e853b6e0552','6b398f499c12e7c5','8e8eeb9af2fdb07d','2011f104852ae329',
  '7c38c0418208d682','d7ecbdc08e5086a0','3d01b08fe569dfec','67169969b313c4f8',
  '6000c5597335fb80','91416cbccbcfef29','82962178c5fa6b71','9438a46df9ec2f8d',
  'c53fad3bfc5c64d9',
  // Orma
  'f3071e32e8b44862',
  // Penfolds
  '05d2196273841823','e6f9f380f761dc8d','d13f7f29b6ba1787',
  // Pieropan
  '3be64245c10a1b07','0835cbfd07e056e5','b5cdf3b48415eec5','6224e9335b868ab6',
  '7bb225a3db604660','6e080ded188ac134','54c359642ea7b8ad',
  // Pine Ridge Vineyards
  'f05306f898232990','bb2be8e9fcf4ab03',
  // Pio Cesare
  '07fc0ff40d306810','9609f88fea922324','f52ee4f1230cc9dd','ced85ac514dda37f',
  '0b80dde7b84bd95e','914f2b41e9af9259','7ffdbc5fa9261247','795270b6db0b1d9e',
  'ee37c0038d38fd1d','8133c0f9e44948df','47d317987c3a02e4','afb6bdc4c88bf263',
  'fcd13b6bd2319679','ff3f12908b1e28d1','a12cd87c09b8f8e1',
  // Produttori del Barbaresco
  '05b24fa7fa650bb3','6c60befc3c9e9503','b70e4a87895e84d2',
  // Prunotto
  'b423d13e17d157ca','2e2f864914bd90e7','edb2ab0f87f5d334','ce91e3552859acae',
  '88f5a4bf9bf9327a','a7dda79f9ba04ac7','e1d59a916ed97d06','e921a7d40050cb4f',
  '110c56c6c65c5710','63db76b43e869bcf','b84e78baa81210da','d967a347b3c4b02e',
  // Querciabella
  '336cc24d0dfac408',
  // Quintessa
  '8b29671a687052ea','ee2fb571e762a8ca','c035835a313c1967',
  // Ramos Pinto
  'b14c751e6351e659','6c6effce96aa73aa','1570f952cc57ef9d','86c943be865b12a1',
  '01268b89250df98e','3ea16dc31d436acc',
  // Reyneke
  '5d1d2fff355ddab1',
  // Ridge Vineyards
  '36aca2a86293cee2',
  // Roberto Voerzio
  '80a34ecf92876921',
  // Rockford
  '6b782c3b192dec8c','d5564926bbe27b0c','b72f886c849d577c','97e0b37d6939b799',
  'b9e690472b788af1','09f60d5aa424d43d','4ef36042d716b00b',
  // Scarzello
  '55faec248dbff6f9','59ebd9286daab5d0',
  // Schiavenza
  '1d314df9c9d10974','efbaf38936782b68',
  // Shafer Vineyards
  '5bce7e07a2af659e','113bc68982126d6a','3f84cfefeb8e48e4','e55c3efcdc1846a0',
  'f0ca45c7f16b30ca',
  // Tenuta di Biserno
  'c5dbaafa0a99dc31',
  // Tenuta San Guido
  '3079d7e30a842f20','51c63377429e24c7','ecc4263cf477f132','278752d4a3f80c10',
  '0c9005453238ac06',
  // Tesseron Estate
  '78d96ebba8a7293c','fe9ae657e5e3b451',
  // Tommasi
  'eef7894650ff299d','ac161160ee44c03a',
  // Torbreck
  '45b4673bd67b05ad','2414e1648f4194e4','1622096eeb79f19d','190681d6875c399b',
  'ff6adfed4f98a09f','b9db34dfb0ed242a','8b712899d1a618e0','ef6ed5e2e562c033',
  // Tua Rita
  '75becaacbfc8acbd',
  // Ulysses
  'e3154de2407203e7',
  // Vasse Felix
  '4f86c146884181ec','1a5f28e77cee5950','5d32d0ae3e10d273','df0421b86c5b8380',
  '07009755c0f5fe7f','65f71436df2c6488',
  // Vietti
  'c958ce7dddbbf51b','ec0fa68b7f0930a4','5aa37a718f69ab06','c5063fc991169a5c',
  '7024d8b78d8fdd2a','1936cf1a21405dc1','becdc781635b425e','4e8b37d7d91b3041',
  'cfccb8524b8c16e1','9504c85a67872f86','aaaa23fc0994c8b4','d41b1a1273540603',
  // Vina Cobos
  '3e7320c65f574154',
  // Vinatis (gift set)
  '0aed55fc4412f0c0',
  // VivaltuS
  '858c4bb5ee8fe2b7',
  // Warramate
  'adee929b1187f234','6c1a16bff7942fbd',
  // Yarra Yering
  '34c83ebdefd544fa','f43991b61196a257','e3d4b271d7a77d25','f2e9724cd05a5e60',
  '6f41870baa17bee0','0c1a0374e5f5e268','54f9a9eabd1fd666','52e1718ea4c55328',
  '180ea38193141faa','c3e9e2720324f6a8','2674946c40b9631e','47c3bf0e9f49238b',
  '5a19bd3c326a9e43','45838277032af3ca','5d9989e98356716b','ce7d7216e3e7f12a',
  'ca4c404dee4e2f22',
];

const KEYS = ALL_NON_FRENCH_KEYS.filter(k => !KEEP_KEYS.has(k));

const CHILD_TABLES = [
  'fact_price', 'fact_rating', 'cellar_inventory', 'cellar_consumption',
  'bridge_wine_variety', 'staging_price_candidates',
];

const fetchWine = db.prepare(`
  SELECT w.wine_key, w.cuvee_name, p.producer_name, w.vintage
  FROM dim_wine w JOIN dim_producer p ON p.producer_key = w.producer_key
  WHERE w.wine_key = ?
`);

console.log(`=== Non-French VdF wine deletions (${KEYS.length} wines) ===`);
let found = 0, missing = 0;
for (const key of KEYS) {
  const w = fetchWine.get(key);
  if (w) { console.log(`  DELETE [${key}] ${w.producer_name} "${w.cuvee_name || ''}" ${w.vintage ?? 'NV'}`); found++; }
  else { missing++; }
}
console.log(`\n  ${found} found, ${missing} already gone`);

if (APPLY) {
  const delChild = (table) => db.prepare(`DELETE FROM ${table} WHERE wine_key = ?`);
  const delWine = db.prepare('DELETE FROM dim_wine WHERE wine_key = ?');
  const cleanOrphans = db.prepare(`
    DELETE FROM dim_producer
    WHERE producer_key IN (
      SELECT producer_key FROM dim_producer p
      WHERE NOT EXISTS (SELECT 1 FROM dim_wine w WHERE w.producer_key = p.producer_key)
    )
  `);

  const tx = db.transaction(() => {
    let deleted = 0;
    for (const key of KEYS) {
      for (const tbl of CHILD_TABLES) delChild(tbl).run(key);
      const r = delWine.run(key);
      if (r.changes) deleted++;
    }
    const orphans = cleanOrphans.run();
    console.log(`\nDeleted ${deleted} dim_wine rows.`);
    console.log(`Removed ${orphans.changes} orphaned producers.`);
  });
  tx();
  console.log('\nDone.');
} else {
  console.log('\n(Dry-run — re-run with --apply to mutate.)');
}

db.close();
