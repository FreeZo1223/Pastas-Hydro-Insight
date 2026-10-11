/* PastasDash v3: de pagina.
   Het rekenwerk gebeurt in de werker (Python met de rekenkern van v2). Hier staat
   het scherm, de projectmap op schijf en het doorgeven van vragen aan de werker. */
'use strict';

const CFG = JSON.parse(document.getElementById('pd-bronnen').textContent);
const CODE = JSON.parse(document.getElementById('pd-code').textContent);
const STAAT = JSON.parse(document.getElementById('pd-staat').textContent || '{}');
const $ = (id) => document.getElementById(id);

const WEERGAVEN = [
  ['project', 'Project'], ['reeksen', 'Reeksen'], ['model', 'Model'], ['vergelijk', 'Vergelijken'],
  ['statistiek', 'Statistiek'], ['kaart', 'Kaart'], ['droogte', 'Droogte']
];
const RESPONSFUNCTIES = ['Gamma', 'Exponential', 'DoubleExponential', 'Hantush'];
const KAN_MAPPEN = 'showDirectoryPicker' in window;

const S = {
  versies: null,
  toestand: { geladen: false, putten: [], stresses: [], modellen: [] },
  selectie: [],
  weergave: 'project',
  map: null,            /* de projectmap op schijf (FileSystemDirectoryHandle), of null */
  mapNaam: '',
  vuil: false,          /* er zijn wijzigingen die nog nergens op schijf staan */
  bewaardOm: null,
  filter: '',
  beurt: 0,
  vorige: null,         /* de laatst gebruikte projectmap, onthouden door de browser */
  broVerslag: [],
  inst: Object.assign({
    onderElkaar: false, metStress: false, rfunc: 'Gamma', ruis: true, tmin: '', tmax: '', modelPut: '',
    gemFoe: true, tovMaaiveld: false, metriek: 'rsq', kleurschaal: 'Viridis', omgekeerd: false,
    station: null, refVan: 1990, refTot: 2020, jaren: '2018, 2020, 2024', knip: true
  }, lees('pastasdash.inst') || {})
};

/* ── klein gereedschap ─────────────────────────────────────────────────── */
function lees(sleutel) { try { return JSON.parse(localStorage.getItem(sleutel)); } catch (e) { return null; } }
function zet(sleutel, waarde) { try { localStorage.setItem(sleutel, JSON.stringify(waarde)); } catch (e) { /* geen opslag: jammer, niet erg */ } }
function bewaarInst() { zet('pastasdash.inst', S.inst); }

function el(tag, eig, ...kinderen) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(eig || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') e.className = v;
    else if (k === 'text') e.textContent = v;
    else if (k === 'data') Object.assign(e.dataset, v);
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (k in e) e[k] = v;
    else e.setAttribute(k, v);
  }
  for (const kind of kinderen.flat(3)) if (kind != null && kind !== false) e.append(kind);
  return e;
}

/* Vervang de inhoud; lege kinderen (null, false) worden overgeslagen. */
function vul(ouder, ...kinderen) {
  ouder.replaceChildren(...kinderen.flat(3).filter((k) => k != null && k !== false));
  return ouder;
}

function fmt(waarde, decimalen = 2, leeg = '—') {
  return typeof waarde === 'number' && isFinite(waarde) ? waarde.toFixed(decimalen).replace('.', ',') : leeg;
}
function jaar(iso) { return iso ? iso.slice(0, 4) : ''; }
function dag(iso) { return iso ? iso.slice(0, 10) : ''; }
function netteNaam(naam) { return (naam || '').replace(/[^A-Za-z0-9_-]+/g, '_').replace(/^_+|_+$/g, '') || 'project'; }

function knop(tekst, bijKlik, soort, extra) {
  return el('button', Object.assign({ class: 'knop', type: 'button', text: tekst, onclick: bijKlik, data: soort ? { soort } : null }, extra || {}));
}
function schakel(tekst, aan, bijWissel) {
  return el('label', { class: 'schakel' },
    el('input', { type: 'checkbox', checked: !!aan, onchange: (e) => bijWissel(e.target.checked) }), tekst);
}
function veld(tekst, invoer) { return el('label', { class: 'veld' }, el('span', { text: tekst }), invoer); }
function keuze(opties, waarde, bijWissel, eig) {
  const s = el('select', Object.assign({ class: 'invoer', onchange: (e) => bijWissel(e.target.value) }, eig || {}),
    opties.map((o) => Array.isArray(o) ? el('option', { value: String(o[0]), text: o[1] }) : el('option', { value: o, text: o })));
  s.value = String(waarde);
  return s;
}
function kaartje(...kinderen) { return el('div', { class: 'peil-card kaart' }, kinderen); }
function kental(label, waarde) {
  return el('div', { class: 'kental' }, el('span', { class: 'peil-label', text: label }), el('span', { class: 'peil-num peil-num-lg', text: String(waarde) }));
}

/* ── meldingen en bezig ────────────────────────────────────────────────── */
function meld(tekst, soort) {
  const m = $('melding');
  m.hidden = false;
  m.dataset.soort = soort || 'fout';
  vul(m, el('span', { text: tekst }), el('button', { text: '×', title: 'Sluiten', onclick: () => { m.hidden = true; } }));
}
function meldFout(f) { console.error(f, f.spoor || ''); meld(f.message || String(f)); }

const bezig = [];
function toonBezig() {
  $('bezig').hidden = !bezig.length;
  $('bezig-tekst').textContent = bezig.length ? bezig[0] + (bezig.length > 1 ? ' +' + (bezig.length - 1) : '') : '';
}
async function metBezig(label, taak) {
  bezig.push(label); toonBezig();
  try { return await taak(); } finally { bezig.splice(bezig.indexOf(label), 1); toonBezig(); }
}

/* ── de werker ─────────────────────────────────────────────────────────── */
let werker = null, volgnr = 0;
const wachtend = new Map();

function startWerker() {
  const bron = $('pd-werker').textContent;
  werker = new Worker(URL.createObjectURL(new Blob([bron], { type: 'text/javascript' })));
  werker.onmessage = (e) => {
    const m = e.data;
    if (m.soort === 'voortgang') { $('opstart-stap').textContent = m.stap; return; }
    const w = wachtend.get(m.id);
    if (!w) return;
    wachtend.delete(m.id);
    if (m.fout) { const f = new Error(m.fout); f.spoor = m.spoor; w.nee(f); } else w.ja(m);
  };
  werker.onerror = (e) => {
    const f = new Error('De rekenkern is gestopt: ' + (e.message || 'onbekende fout'));
    wachtend.forEach((w) => w.nee(f)); wachtend.clear();
  };
}
function vraag(bericht, overdracht) {
  return new Promise((ja, nee) => {
    const id = ++volgnr;
    wachtend.set(id, { ja, nee });
    werker.postMessage(Object.assign({ id }, bericht), overdracht || []);
  });
}
/* Eén handeling van de rekenkern; wat daarbij in het project verandert, gaat naar schijf. */
function roep(naam, args, label) {
  return metBezig(label || 'Rekenen', async () => {
    const m = await vraag({ soort: 'roep', naam, args: args || {} });
    if (m.bestanden) await bewaar(m.bestanden);
    return m.ok;
  });
}

/* ── de projectmap op schijf ───────────────────────────────────────────── */
async function schrijfBestand(wortel, pad, data) {
  const delen = pad.split('/');
  let map = wortel;
  for (const deel of delen.slice(0, -1)) map = await map.getDirectoryHandle(deel, { create: true });
  const schrijver = await (await map.getFileHandle(delen[delen.length - 1], { create: true })).createWritable();
  await schrijver.write(data);
  await schrijver.close();
}
async function wisBestand(wortel, pad) {
  const delen = pad.split('/');
  try {
    let map = wortel;
    for (const deel of delen.slice(0, -1)) map = await map.getDirectoryHandle(deel);
    await map.removeEntry(delen[delen.length - 1]);
  } catch (e) { /* al weg */ }
}
async function leesMap(map, voor, uit) {
  uit = uit || {};
  for await (const [naam, h] of map.entries()) {
    if (h.kind === 'directory') await leesMap(h, (voor || '') + naam + '/', uit);
    else uit[(voor || '') + naam] = new Uint8Array(await (await h.getFile()).arrayBuffer());
  }
  return uit;
}
async function inhoud(map) {
  const namen = [];
  for await (const [naam, h] of map.entries()) namen.push([naam, h]);
  return namen.sort((a, b) => a[0].localeCompare(b[0]));
}
/* Zoek de store: in de gekozen map zelf, of één map dieper. */
async function vindStore(map) {
  const eigen = await inhoud(map);
  const hier = eigen.find(([naam, h]) => h.kind === 'file' && naam.endsWith('.pastastore'));
  if (hier) return { map, naam: hier[0].replace(/\.pastastore$/, '') };
  for (const [, h] of eigen.filter(([, h]) => h.kind === 'directory')) {
    const gevonden = (await inhoud(h)).find(([naam, k]) => k.kind === 'file' && naam.endsWith('.pastastore'));
    if (gevonden) return { map: h, naam: gevonden[0].replace(/\.pastastore$/, '') };
  }
  return { map: null, leeg: eigen.length === 0 };
}

async function bewaar(b) {
  if (!Object.keys(b.schrijf).length && !b.weg.length) return;
  if (!S.map) { S.vuil = true; toonOpslag(); return; }
  try {
    for (const [pad, data] of Object.entries(b.schrijf)) await schrijfBestand(S.map, pad, data);
    for (const pad of b.weg) await wisBestand(S.map, pad);
    S.bewaardOm = new Date(); S.vuil = false;
  } catch (f) {
    S.vuil = true;
    meld('Opslaan in de projectmap is mislukt (' + f.message + '). Kies "Opslaan in map" om het opnieuw te proberen, of exporteer het project als zip.');
  }
  toonOpslag();
}

function db() {
  return new Promise((ja, nee) => {
    const r = indexedDB.open('pastasdash', 1);
    r.onupgradeneeded = () => r.result.createObjectStore('kv');
    r.onsuccess = () => ja(r.result);
    r.onerror = () => nee(r.error);
  });
}
async function onthoud(sleutel, waarde) {
  try {
    const d = await db();
    await new Promise((ja, nee) => { const tx = d.transaction('kv', 'readwrite'); tx.objectStore('kv').put(waarde, sleutel); tx.oncomplete = ja; tx.onerror = () => nee(tx.error); });
  } catch (e) { /* onthouden lukt niet in elke browser */ }
}
async function herinner(sleutel) {
  try {
    const d = await db();
    return await new Promise((ja, nee) => { const r = d.transaction('kv').objectStore('kv').get(sleutel); r.onsuccess = () => ja(r.result || null); r.onerror = () => nee(r.error); });
  } catch (e) { return null; }
}

function neemToestand(t) {
  S.toestand = t;
  const bestaand = new Set(t.putten.map((p) => p.naam));
  S.selectie = S.selectie.filter((n) => bestaand.has(n));
}
function projectGeopend() {
  S.selectie = (lees('pastasdash.selectie.' + S.toestand.naam) || []);
  neemToestand(S.toestand);
  if (!S.selectie.length) S.selectie = S.toestand.putten.slice(0, 3).map((p) => p.naam);
  S.broVerslag = [];
  S.weergave = S.toestand.putten.length ? 'reeksen' : 'project';
  tekenAlles();
}

async function openMap(map) {
  const plek = await vindStore(map);
  if (plek.map) {
    const bestanden = await metBezig('Projectmap lezen', () => leesMap(plek.map));
    await vraag({ soort: 'schrijf', wortel: '/project/' + plek.naam, bestanden, leeg: true });
    S.map = null;                 /* tijdens het openen wordt er niets teruggeschreven */
    S.toestand = await roep('open_project', { naam: plek.naam }, 'Project openen');
    S.map = plek.map;
  } else {
    S.map = plek.leeg ? map : await map.getDirectoryHandle('pastastore', { create: true });
    S.toestand = await roep('nieuw_project', { naam: plek.leeg ? netteNaam(map.name) : 'pastastore' }, 'Project aanmaken');
  }
  S.mapNaam = map.name; S.vuil = false; S.bewaardOm = new Date();
  await onthoud('laatste', map); S.vorige = map;
  projectGeopend();
}
async function kiesMap() {
  let map;
  try { map = await window.showDirectoryPicker({ id: 'pastasdash', mode: 'readwrite' }); } catch (e) { return; }
  try { await openMap(map); } catch (f) { meldFout(f); }
}
async function heropen() {
  try {
    if (await S.vorige.requestPermission({ mode: 'readwrite' }) !== 'granted') return;
    await openMap(S.vorige);
  } catch (f) { meldFout(f); }
}
async function nieuwLos(naam) {
  S.map = null; S.mapNaam = '';
  S.toestand = await roep('nieuw_project', { naam: netteNaam(naam || 'project') }, 'Project aanmaken');
  S.vuil = false;
  projectGeopend();
}
async function openZip(bestand) {
  try {
    const data = new Uint8Array(await bestand.arrayBuffer());
    const naam = netteNaam(bestand.name.replace(/\.zip$/i, '')) + '.zip';
    await vraag({ soort: 'schrijf', wortel: '/tmp/in', bestanden: { [naam]: data }, leeg: true });
    S.map = null; S.mapNaam = '';
    S.toestand = await roep('open_zip', { pad: '/tmp/in/' + naam }, 'Zip openen');
    S.vuil = false;               /* de zip zelf is de kopie op schijf */
    projectGeopend();
  } catch (f) { meldFout(f); }
}
async function exporteerZip() {
  try {
    const z = await roep('maak_zip', {}, 'Zip maken');
    const data = (await vraag({ soort: 'lees', pad: z.pad })).ok;
    download(new Blob([data], { type: 'application/zip' }), z.bestandsnaam);
    if (!S.map) { S.vuil = false; toonOpslag(); }
  } catch (f) { meldFout(f); }
}
/* Zet een project dat alleen in dit tabblad staat alsnog in een map. */
async function opslaanInMap() {
  let map;
  try { map = await window.showDirectoryPicker({ id: 'pastasdash', mode: 'readwrite' }); } catch (e) { return; }
  try {
    let doel = map;
    if ((await inhoud(map)).length) {
      doel = await map.getDirectoryHandle(S.toestand.naam, { create: true });
      if ((await inhoud(doel)).length) { meld('In deze map staat al een map "' + S.toestand.naam + '" met inhoud. Kies een lege map.'); return; }
    }
    S.map = doel; S.mapNaam = map.name;
    await bewaar((await metBezig('Opslaan', () => vraag({ soort: 'alles' }))).bestanden);
    await onthoud('laatste', map); S.vorige = map;
    tekenAlles();
  } catch (f) { meldFout(f); }
}
function download(blob, naam) {
  const a = el('a', { href: URL.createObjectURL(blob), download: naam });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 4000);
}

/* ── omlijsting: kop, tabs, peilbuizenlijst ────────────────────────────── */
function toonOpslag() {
  const o = $('opslag'), t = S.toestand;
  $('kop-bron').textContent = t.geladen ? t.naam + ' · ' + t.putten.length + ' peilbuizen' : 'geen project geopend';
  if (!t.geladen) { o.textContent = ''; return; }
  if (S.map) {
    o.dataset.staat = S.vuil ? 'los' : 'vast';
    o.textContent = S.vuil ? 'Niet alles is opgeslagen' : 'Opgeslagen in map ' + S.mapNaam + (S.bewaardOm ? ' · ' + S.bewaardOm.toLocaleTimeString('nl-NL', { hour: '2-digit', minute: '2-digit' }) : '');
  } else {
    o.dataset.staat = S.vuil ? 'los' : 'vast';
    o.textContent = S.vuil ? 'Niet opgeslagen: kies een map of exporteer' : 'Alleen in dit tabblad';
  }
}
function tekenTabs() {
  $('tabs').replaceChildren(...WEERGAVEN.map(([sleutel, label]) =>
    el('button', { class: 'peil-tab', type: 'button', text: label, data: { active: String(sleutel === S.weergave), tab: sleutel }, onclick: () => { S.weergave = sleutel; tekenTabs(); teken(); } })));
}
function zetSelectie(namen) {
  S.selectie = namen;
  if (S.toestand.geladen) zet('pastasdash.selectie.' + S.toestand.naam, namen);
  tekenZijbalk(); teken();
}
function tekenZijbalk() {
  const z = $('zijbalk'), putten = S.toestand.putten;
  if (!S.toestand.geladen || !putten.length) {
    vul(z, el('div', { class: 'zij-leeg' },
      el('span', { class: 'peil-label', text: 'Peilbuizen' }),
      el('span', { class: 'zacht', text: S.toestand.geladen ? 'Dit project heeft nog geen peilbuizen. Voeg ze toe onder Project.' : 'Open eerst een project.' })));
    return;
  }
  const tijden = putten.filter((p) => p.van && p.tot).flatMap((p) => [Date.parse(p.van), Date.parse(p.tot)]);
  const vroegst = Math.min(...tijden), duur = (Math.max(...tijden) - vroegst) || 1;
  const lijst = el('div', { class: 'zij-lijst', id: 'zij-lijst' });
  const teller = el('span', { class: 'peil-label peil-num' });
  function vulLijst() {
    teller.textContent = S.selectie.length + '/' + putten.length;
    const zichtbaar = putten.filter((p) => p.naam.toLowerCase().includes(S.filter.toLowerCase()));
    vul(lijst, ...(zichtbaar.length ? zichtbaar.map(rij) : [el('div', { class: 'zij-leeg zacht', text: 'Niets gevonden.' })]));
  }
  function rij(p) {
    const wissel = () => zetSelectie(S.selectie.includes(p.naam) ? S.selectie.filter((n) => n !== p.naam) : S.selectie.concat(p.naam));
    const r = el('div', { class: 'peil-row', tabIndex: 0, title: p.naam, data: { selected: String(S.selectie.includes(p.naam)), put: p.naam },
      onclick: wissel, onkeydown: (e) => { if (e.key === 'Enter') wissel(); } },
      el('div', { class: 'rij-naam' }, el('span', { text: p.naam }), p.model ? el('span', { class: 'rij-model', text: 'model', title: 'Voor deze peilbuis is een model gefit' }) : null));
    if (p.van && p.tot) {
      const links = (Date.parse(p.van) - vroegst) / duur * 100, breedte = Math.max((Date.parse(p.tot) - Date.parse(p.van)) / duur * 100, 1.5);
      r.append(el('div', { class: 'peil-span-track' }, el('div', { class: 'peil-span-fill', style: 'left:' + links.toFixed(1) + '%;width:' + breedte.toFixed(1) + '%' })),
        el('div', { class: 'rij-bij peil-num', text: jaar(p.van) + '–' + jaar(p.tot) + ' · ' + p.metingen + ' metingen' }));
    }
    return r;
  }
  vul(z, 
    el('div', { class: 'zij-kop' }, el('span', { class: 'peil-label', text: 'Peilbuizen' }), teller),
    el('input', { class: 'invoer zij-filter', placeholder: 'Filter op naam', value: S.filter, oninput: (e) => { S.filter = e.target.value; vulLijst(); } }),
    lijst,
    el('div', { class: 'zij-voet' },
      knop('Alles', () => zetSelectie(putten.map((p) => p.naam)), 'kaal'),
      knop('Wissen', () => zetSelectie([]), 'kaal')));
  vulLijst();
}
function tekenAlles() { toonOpslag(); tekenTabs(); tekenZijbalk(); teken(); }

/* ── figuren ───────────────────────────────────────────────────────────── */
function figuur(houder, fig) {
  const d = el('div');
  houder.append(d);
  if (fig) window.Plotly.newPlot(d, fig.data, fig.layout, { responsive: true, displaylogo: false });
  return d;
}
function figuurKaart(titel) {
  const k = el('div', { class: 'peil-card figuur' }, titel ? el('div', { class: 'peil-label', style: 'padding:6px 8px', text: titel }) : null);
  return k;
}
function legeStaat(titel, tekst, ...knoppen) {
  return el('div', { class: 'peil-card kaart kaart-smal' }, el('h3', { text: titel }), el('p', { class: 'zacht', text: tekst }), knoppen.length ? el('div', { class: 'rij' }, knoppen) : null);
}
const naarProject = () => { S.weergave = 'project'; tekenTabs(); teken(); };
function vereis(vlak, selectieNodig) {
  if (!S.toestand.geladen) { vul(vlak, legeStaat('Nog geen project', 'Open eerst een project met peilbuisreeksen.', knop('Project kiezen', naarProject))); return false; }
  if (!S.toestand.putten.length) { vul(vlak, legeStaat('Nog geen peilbuizen', 'Voeg peilbuizen toe uit de BRO.', knop('Naar Project', naarProject))); return false; }
  if (selectieNodig && !S.selectie.length) { vul(vlak, legeStaat('Kies een peilbuis', 'Selecteer links een of meer peilbuizen. Je keuze blijft staan als je naar een andere weergave gaat.')); return false; }
  return true;
}

/* ── kaart (Leaflet) ───────────────────────────────────────────────────── */
const KLEURSCHALEN = {
  Viridis: ['#440154', '#3b528b', '#21918c', '#5ec962', '#fde725'],
  Plasma: ['#0d0887', '#7e03a8', '#cc4778', '#f89540', '#f0f921'],
  RdYlGn: ['#a50026', '#f46d43', '#ffffbf', '#66bd63', '#006837'],
  Blues: ['#f7fbff', '#c6dbef', '#6baed6', '#2171b5', '#08306b']
};
function kleurOp(schaal, deel) {
  const stappen = schaal.map((h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16)));
  const plek = Math.min(Math.max(deel, 0), 1) * (stappen.length - 1), i = Math.min(Math.floor(plek), stappen.length - 2), f = plek - i;
  return 'rgb(' + stappen[i].map((v, k) => Math.round(v + (stappen[i + 1][k] - v) * f)).join(',') + ')';
}
/* Putten op de BRT-achtergrondkaart. Met opties.schaal krijgt elke put de kleur van zijn waarde;
   zonder schaal krijgt alleen de selectie de accentkleur. Klikken wisselt de selectie. */
function tekenKaart(houder, punten, opties) {
  opties = opties || {};
  if (!punten.length) { houder.append(el('p', { class: 'zacht', style: 'padding:10px', text: 'Van deze peilbuizen is geen ligging bekend.' })); return null; }
  const vlak = el('div', { class: 'kaartvlak' });
  houder.append(vlak);
  const kaart = window.L.map(vlak, { zoomSnap: 0.5, attributionControl: true });
  window.L.tileLayer(CFG.kaart.tegels, { maxZoom: 19, attribution: CFG.kaart.bron }).addTo(kaart);
  let schaal = opties.schaal ? KLEURSCHALEN[opties.schaal].slice() : null;
  if (schaal && opties.omgekeerd) schaal.reverse();
  const waarden = punten.map((p) => p.waarde).filter((w) => w != null);
  const laag = Math.min(...waarden), hoog = Math.max(...waarden);
  /* Filters van één put liggen op dezelfde plek: die worden ringen om elkaar heen,
     de buitenste eerst getekend zodat elke ring aan te wijzen blijft. */
  const perPlek = {};
  punten.forEach((p) => { const s = p.lat.toFixed(6) + ',' + p.lon.toFixed(6); (perPlek[s] = perPlek[s] || []).push(p); });
  Object.values(perPlek).forEach((groep) => groep.slice().reverse().forEach((p, i) => {
    const ring = groep.length - 1 - i, gekozen = S.selectie.includes(p.naam);
    let vulling = gekozen ? '#C2703D' : '#006F92';
    if (schaal) vulling = p.waarde == null ? '#FFFFFF' : kleurOp(schaal, hoog > laag ? (p.waarde - laag) / (hoog - laag) : 0.5);
    const stip = window.L.circleMarker([p.lat, p.lon], {
      radius: 7 + ring * 6, weight: gekozen ? 3 : 1.5, color: gekozen ? '#0F1C24' : (schaal ? '#5A6B75' : '#FFFFFF'), fillColor: vulling, fillOpacity: 0.95
    }).addTo(kaart);
    stip.bindTooltip(p.naam + (schaal ? ': ' + (p.waarde == null ? 'geen waarde' : fmt(p.waarde, opties.decimalen ?? 2)) : ''));
    stip.on('click', () => zetSelectie(gekozen ? S.selectie.filter((n) => n !== p.naam) : S.selectie.concat(p.naam)));
  }));
  kaart.fitBounds(window.L.latLngBounds(punten.map((p) => [p.lat, p.lon])).pad(0.3), { maxZoom: 14 });
  if (schaal) {
    houder.append(el('div', { class: 'kaart-legenda' },
      waarden.length ? [el('span', { class: 'peil-num', text: fmt(laag, opties.decimalen ?? 2) }),
        el('div', { class: 'kaart-balk', style: 'background:linear-gradient(to right,' + schaal.join(',') + ')' }),
        el('span', { class: 'peil-num', text: fmt(hoog, opties.decimalen ?? 2) })] : el('span', { text: 'Geen enkele peilbuis heeft hier een waarde voor.' }),
      waarden.length < punten.length ? [el('span', { class: 'kaart-stip' }), el('span', { text: 'geen waarde' })] : null));
  }
  return kaart;
}

/* ── weergaven ─────────────────────────────────────────────────────────── */
const TEKEN = {};

async function teken() {
  const beurt = ++S.beurt, vlak = $('vlak');
  try { await TEKEN[S.weergave](vlak, () => beurt === S.beurt); } catch (f) { if (beurt === S.beurt) meldFout(f); }
}

TEKEN.project = async function (vlak) {
  const t = S.toestand, blokken = [];
  const zipInvoer = el('input', { type: 'file', accept: '.zip', hidden: true, onchange: (e) => { if (e.target.files[0]) openZip(e.target.files[0]); } });
  const openKnoppen = [
    KAN_MAPPEN ? knop('Projectmap openen…', kiesMap, t.geladen ? 'rand' : null, { id: 'knop-map' }) : null,
    S.vorige && S.vorige !== S.map && !(S.map && S.mapNaam === S.vorige.name) ? knop('Heropen "' + S.vorige.name + '"', heropen, 'rand', { id: 'knop-heropen' }) : null,
    knop('Zip openen…', () => zipInvoer.click(), 'rand'),
    knop('Leeg project beginnen', () => nieuwLos('project').catch(meldFout), 'rand', { id: 'knop-leeg' }),
    zipInvoer
  ];
  if (!t.geladen) {
    blokken.push(el('div', { class: 'kolom kaart-smal' },
      el('h2', { text: 'Grondwaterreeksen bekijken en modelleren' }),
      el('p', { class: 'zacht', text: 'Kies een projectmap. Daarin komen de peilbuisreeksen en de modellen te staan, in hetzelfde formaat als PastasDash op de desktop. Een map op OneDrive is meteen gedeeld met collega\'s.' })));
    blokken.push(el('div', { class: 'peil-card kaart kaart-smal' },
      el('span', { class: 'peil-label', text: 'Project' }),
      el('div', { class: 'rij' }, openKnoppen),
      KAN_MAPPEN ? null : el('p', { class: 'waarschuwing', text: 'Deze browser kan niet in een map op schijf schrijven. Gebruik Edge of Chrome, of werk met zip-bestanden: open een zip en exporteer aan het eind.' })));
  } else {
    blokken.push(kaartje(
      el('span', { class: 'peil-label', text: 'Inhoud' }),
      el('div', { class: 'kentallen' }, kental('Peilbuizen', t.putten.length), kental('Verklarende reeksen', t.stresses.length), kental('Modellen', t.modellen.length)),
      el('p', { class: 'noot', text: S.map
        ? 'Elke wijziging gaat direct naar de projectmap "' + S.mapNaam + '". PastasDash op de desktop kan dezelfde map openen.'
        : 'Dit project staat alleen in dit tabblad. Zet het in een map of exporteer het als zip, anders is het weg als je het tabblad sluit.' }),
      el('div', { class: 'rij' },
        !S.map && KAN_MAPPEN ? knop('Opslaan in map…', opslaanInMap, null, { id: 'knop-opslaan' }) : null,
        knop('Exporteer als zip', exporteerZip, S.map ? 'rand' : (KAN_MAPPEN ? 'rand' : null), { id: 'knop-zip' }),
        openKnoppen)));

    const invoer = el('textarea', { class: 'invoer', id: 'bro-invoer', placeholder: 'GMW000000069526\nGMW000000012345', spellcheck: false });
    const verslag = el('div', { class: 'kolom', id: 'bro-verslag' });
    const toonVerslag = () => vul(verslag, ...S.broVerslag.map((r) => el('div', { class: r.fout ? 'waarschuwing' : 'klein', text: r.tekst })));
    toonVerslag();
    const haalOp = async () => {
      const nummers = [...new Set((invoer.value.toUpperCase().match(/GMW\d{12}/g) || []))];
      if (!nummers.length) { meld('Vul een of meer BRO-putnummers in. Een putnummer begint met GMW en heeft twaalf cijfers.'); return; }
      await voegPuttenToe(nummers, toonVerslag);
      invoer.value = '';
    };
    blokken.push(kaartje(
      el('span', { class: 'peil-label', text: 'Peilbuizen toevoegen uit de BRO' }),
      el('p', { class: 'noot', text: 'Plak BRO-putnummers (GMW…), gescheiden door een spatie, komma of nieuwe regel. Van elke put komen alle filters met metingen in het project, als daggemiddelde in m NAP. Een put die er al in zit, wordt ververst.' }),
      invoer,
      el('div', { class: 'rij' }, knop('Ophalen uit de BRO', haalOp, null, { id: 'knop-bro' })),
      verslag));

    if (t.putten.length) {
      blokken.push(kaartje(
        el('span', { class: 'peil-label', text: 'Peilbuizen in dit project' }),
        el('div', { class: 'tabel-rol' }, el('table', { class: 'tabel peil-num', id: 'tabel-putten' },
          el('thead', {}, el('tr', {}, ['Naam', 'Periode', 'Metingen', 'Maaiveld', 'Filter', 'Model', ''].map((k) => el('th', { text: k })))),
          el('tbody', {}, t.putten.map((p) => el('tr', {},
            el('td', { text: p.naam }),
            el('td', { text: p.van ? dag(p.van) + ' – ' + dag(p.tot) : '—' }),
            el('td', { text: String(p.metingen) }),
            el('td', { text: fmt(p.maaiveld) }),
            el('td', { text: p.filter_boven == null ? '—' : fmt(p.filter_boven) + ' tot ' + fmt(p.filter_onder) }),
            el('td', { text: p.model ? 'ja' : '—' }),
            el('td', {}, knop('Verwijderen', () => verwijderPut(p.naam), 'kaal')))))))));
    }
  }
  if (S.versies) {
    blokken.push(el('p', { class: 'noot', text: 'PastasDash ' + S.versies.pastasdash + ' · PASTAS ' + S.versies.pastas + ' · pastastore ' + S.versies.pastastore +
      ' · gebouwd ' + VERSIE + '. Metingen: ' + CFG.bro.bron + '. Neerslag en verdamping: ' + CFG.knmi.bron + '.' }));
  }
  vul(vlak, ...blokken);
};

async function voegPuttenToe(nummers, naElke) {
  const nieuw = [];
  for (let i = 0; i < nummers.length; i++) {
    const gmw = nummers[i];
    try {
      const r = await roep('voeg_put_toe', { gmw }, 'Put ' + (i + 1) + ' van ' + nummers.length + ': ' + gmw);
      r.toegevoegd.forEach((f) => { nieuw.push(f.naam); S.broVerslag.push({ tekst: f.naam + ': ' + f.metingen + ' dagwaarden, ' + f.van + ' tot ' + f.tot + (f.meldingen.length ? ' (' + f.meldingen.join('; ') + ')' : '') }); });
      r.overgeslagen.forEach((f) => S.broVerslag.push({ fout: true, tekst: f.naam + ' overgeslagen: ' + f.reden }));
      if (!r.toegevoegd.length && !r.overgeslagen.length) S.broVerslag.push({ fout: true, tekst: gmw + ': de put heeft geen filters in de BRO' });
    } catch (f) {
      S.broVerslag.push({ fout: true, tekst: gmw + ': ' + f.message });
    }
    if (naElke) naElke();
  }
  neemToestand(await roep('toestand'));
  S.selectie = [...new Set(S.selectie.concat(nieuw))];
  if (S.toestand.geladen) zet('pastasdash.selectie.' + S.toestand.naam, S.selectie);
  tekenAlles();
}
async function verwijderPut(naam) {
  try { neemToestand(await roep('verwijder_put', { naam }, 'Verwijderen: ' + naam)); tekenAlles(); } catch (f) { meldFout(f); }
}

TEKEN.reeksen = async function (vlak, nogActueel) {
  if (!vereis(vlak, true)) return;
  const grafiek = figuurKaart(), kaart = figuurKaart('Ligging');
  const opnieuw = () => { bewaarInst(); teken(); };
  vul(vlak, 
    el('div', { class: 'rij rij-midden tussen' },
      el('div', { class: 'kolom', style: 'gap:2px' }, el('span', { class: 'peil-label', text: 'Grondwaterstand' }), el('span', { class: 'zacht', text: S.selectie.length + (S.selectie.length === 1 ? ' reeks' : ' reeksen') })),
      el('div', { class: 'rij rij-midden' },
        schakel('Onder elkaar', S.inst.onderElkaar, (v) => { S.inst.onderElkaar = v; opnieuw(); }),
        schakel('Neerslag en verdamping', S.inst.metStress, (v) => { S.inst.metStress = v; opnieuw(); }))),
    grafiek, kaart);
  const r = await roep('reeksen', { namen: S.selectie, onder_elkaar: S.inst.onderElkaar, met_stress: S.inst.metStress }, 'Reeksen tekenen');
  if (!nogActueel()) return;
  figuur(grafiek, r.figuur);
  const l = await roep('ligging', {}, 'Kaart tekenen');
  if (!nogActueel()) return;
  if (l.punten.length) tekenKaart(kaart, l.punten); else kaart.remove();
};

TEKEN.model = async function (vlak, nogActueel) {
  if (!vereis(vlak, false)) return;
  const namen = S.toestand.putten.map((p) => p.naam);
  /* Eén model tegelijk. Begin bij wat links geselecteerd staat. */
  let put = S.selectie.includes(S.inst.modelPut) ? S.inst.modelPut : (S.selectie[0] || (namen.includes(S.inst.modelPut) ? S.inst.modelPut : namen[0]));
  const uitkomst = el('div', { class: 'kolom', style: 'gap:20px', id: 'model-uitkomst' });
  const verslag = el('div', { class: 'kolom', id: 'fit-verslag' });
  const opties = () => ({ rfunc: S.inst.rfunc, ruis: S.inst.ruis, tmin: S.inst.tmin, tmax: S.inst.tmax });

  async function toon() {
    vul(uitkomst, el('p', { class: 'zacht', text: 'Model laden…' }));
    const m = await roep('model', { naam: put }, 'Model tekenen');
    if (!nogActueel()) return;
    if (!m.heeft_model) { vul(uitkomst, legeStaat('Nog geen model', 'Voor ' + put + ' is nog geen model gefit. Kies hierboven "Model fitten".')); return; }
    const s = m.samenvatting, res = figuurKaart('Resultaten'), diag = figuurKaart('Diagnostiek');
    vul(uitkomst, 
      kaartje(el('span', { class: 'peil-label', text: 'Samenvatting' }),
        el('div', { class: 'kentallen', id: 'model-kentallen' }, kental('R²', fmt(s.rsq, 3)), kental('Verklaarde variantie', fmt(s.evp, 1) + ' %'), kental('Metingen', s.n_obs ?? '—'), kental('Van', dag(s.tmin) || '—'), kental('Tot', dag(s.tmax) || '—')),
        m.stresses.length ? el('p', { class: 'noot', text: 'Verklarende reeksen: ' + m.stresses.join(', ') + '.' }) : null),
      res, diag,
      kaartje(el('span', { class: 'peil-label', text: 'Parameters' }),
        el('div', { class: 'tabel-rol' }, el('table', { class: 'tabel peil-num' },
          el('thead', {}, el('tr', {}, ['Parameter', 'Waarde', 'Standaardfout'].map((k) => el('th', { text: k })))),
          el('tbody', {}, m.parameters.map((p) => el('tr', {}, el('td', { text: p.naam }), el('td', { text: fmt(p.waarde, 4) }), el('td', { text: fmt(p.stderr, 4) }))))))));
    figuur(res, m.resultaten); figuur(diag, m.diagnostiek);
  }
  async function fit(lijst) {
    bewaarInst();
    S.fitVerslag = [];
    for (let i = 0; i < lijst.length; i++) {
      const naam = lijst[i];
      try {
        const r = await roep('fit', Object.assign({ naam }, opties()), lijst.length > 1 ? 'Model ' + (i + 1) + ' van ' + lijst.length + ': ' + naam : 'Model fitten: ' + naam);
        S.fitVerslag.push({ fout: !r.gelukt, tekst: naam + ': ' + (r.gelukt ? 'R² ' + fmt(r.samenvatting.rsq, 3) : r.melding) + (r.meldingen.length ? ' · ' + r.meldingen.join('; ') : '') });
      } catch (f) { S.fitVerslag.push({ fout: true, tekst: naam + ': ' + f.message }); }
      toonVerslag();
    }
    neemToestand(await roep('toestand'));
    toonOpslag(); tekenZijbalk();
    if (nogActueel()) await toon();
  }
  function toonVerslag() { vul(verslag, ...(S.fitVerslag || []).map((r) => el('div', { class: r.fout ? 'waarschuwing' : 'klein', text: r.tekst }))); }
  toonVerslag();

  vul(vlak, 
    kaartje(
      el('span', { class: 'peil-label', text: 'Model fitten' }),
      el('div', { class: 'rij' },
        veld('Peilbuis', keuze(namen, put, (v) => { put = v; S.inst.modelPut = v; bewaarInst(); toon().catch(meldFout); }, { id: 'model-put' })),
        veld('Responsfunctie', keuze(RESPONSFUNCTIES, S.inst.rfunc, (v) => { S.inst.rfunc = v; })),
        veld('Vanaf (optioneel)', el('input', { class: 'invoer', type: 'date', value: S.inst.tmin, onchange: (e) => { S.inst.tmin = e.target.value; } })),
        veld('Tot en met (optioneel)', el('input', { class: 'invoer', type: 'date', value: S.inst.tmax, onchange: (e) => { S.inst.tmax = e.target.value; } })),
        schakel('Ruismodel', S.inst.ruis, (v) => { S.inst.ruis = v; }),
        knop('Model fitten', () => fit([put]).catch(meldFout), null, { id: 'knop-fit' }),
        S.selectie.length > 1 ? knop('Fit alle ' + S.selectie.length + ' geselecteerde', () => fit(S.selectie.slice()).catch(meldFout), 'rand', { id: 'knop-fit-alle' }) : null),
      el('p', { class: 'noot', text: 'Het model verklaart de grondwaterstand uit neerslag en verdamping van het dichtstbijzijnde KNMI-station. Die reeksen worden bij de eerste fit opgehaald en in het project bewaard.' }),
      verslag),
    uitkomst);
  await toon();
};

TEKEN.vergelijk = async function (vlak, nogActueel) {
  if (!vereis(vlak, true)) return;
  const grafiek = figuurKaart(), tabel = el('div', { class: 'kolom' });
  vul(vlak, el('div', { class: 'kolom', style: 'gap:2px' }, el('span', { class: 'peil-label', text: 'Modellen vergelijken' }), el('span', { class: 'zacht', text: 'De modellen van de peilbuizen die links geselecteerd zijn.' })), grafiek, tabel);
  const r = await roep('vergelijk', { namen: S.selectie }, 'Modellen vergelijken');
  if (!nogActueel()) return;
  figuur(grafiek, r.figuur);
  vul(tabel, 
    r.tabel.length ? kaartje(el('div', { class: 'tabel-rol' }, el('table', { class: 'tabel peil-num', id: 'tabel-vergelijk' },
      el('thead', {}, el('tr', {}, ['Model', 'R²', 'Verklaarde variantie %', 'Metingen', 'Van', 'Tot'].map((k) => el('th', { text: k })))),
      el('tbody', {}, r.tabel.map((s) => el('tr', {}, el('td', { text: s.naam }), el('td', { text: fmt(s.rsq, 3) }), el('td', { text: fmt(s.evp, 1) }), el('td', { text: String(s.n_obs ?? '—') }), el('td', { text: dag(s.tmin) }), el('td', { text: dag(s.tmax) }))))))) : null,
    r.zonder_model.length ? el('p', { class: 'noot', text: 'Nog geen model voor: ' + r.zonder_model.join(', ') + '. Fit ze onder Model.' }) : null);
};

TEKEN.statistiek = async function (vlak, nogActueel) {
  if (!vereis(vlak, false)) return;
  const links = el('div', { class: 'kolom' }), hydro = figuurKaart(), foe = figuurKaart(), regime = figuurKaart();
  const opnieuw = () => { bewaarInst(); teken(); };
  vul(vlak, el('div', { class: 'twee' }, links, el('div', { class: 'kolom', style: 'gap:14px' }, hydro, foe, regime)));
  const r = await roep('statistiek', { namen: S.selectie, gemiddelde_foe: S.inst.gemFoe, tov_maaiveld: S.inst.tovMaaiveld }, 'Statistiek berekenen');
  if (!nogActueel()) return;
  const kolommen = [['name', 'Naam'], ['gt', 'Gt'], ['mlgl', 'GLG'], ['mg', 'Gem.'], ['msgl', 'GVG'], ['mhgl', 'GHG'], ['surface_level', 'Maaiveld'], ['jaren', 'Jaren']];
  const cel = (rij, k) => k === 'name' || k === 'gt' ? (rij[k] ?? '—') : k === 'jaren' ? String(rij[k] ?? '—') : fmt(rij[k]);
  const csv = () => download(new Blob(['﻿' + [kolommen.map((k) => k[1]).join(';')].concat(r.rijen.map((rij) => kolommen.map(([k]) => cel(rij, k)).join(';'))).join('\r\n')], { type: 'text/csv' }), (S.toestand.naam || 'project') + '_gxg.csv');
  vul(links, 
    el('span', { class: 'peil-label', text: 'Grondwaterstatistiek' }),
    el('span', { class: 'zacht klein', text: 'GxG in m NAP en grondwatertrap per peilbuis. De grafieken volgen je selectie links.' }),
    el('div', { class: 'peil-card tabel-rol' }, el('table', { class: 'tabel peil-num', id: 'tabel-statistiek' },
      el('thead', {}, el('tr', {}, kolommen.map(([k, titel]) => el('th', { text: titel, class: k === 'gt' ? 'links' : null })))),
      el('tbody', {}, r.rijen.map((rij) => el('tr', { data: { selected: String(S.selectie.includes(rij.name)) } },
        kolommen.map(([k]) => el('td', { text: cel(rij, k), class: k === 'gt' ? 'links' : (k === 'mhgl' ? 'peil-high' : k === 'mlgl' ? 'peil-low' : null) }))))))),
    r.rijen.every((rij) => !rij.gt || rij.gt === '?') ? el('p', { class: 'waarschuwing', text: 'Grondwatertrap ontbreekt: bij deze peilbuizen is geen maaiveldhoogte bekend, of de reeks is te kort voor een GxG.' }) : null,
    el('p', { class: 'noot', text: 'Een GxG vraagt minstens acht hydrologische jaren met genoeg metingen; de kolom Jaren toont hoeveel er bruikbaar zijn.' }),
    el('div', { class: 'rij rij-midden' },
      schakel('Gemiddelde duurlijn tonen', S.inst.gemFoe, (v) => { S.inst.gemFoe = v; opnieuw(); }),
      schakel('Ten opzichte van maaiveld', S.inst.tovMaaiveld, (v) => { S.inst.tovMaaiveld = v; opnieuw(); }),
      knop('Tabel als CSV', csv, 'rand')));
  figuur(hydro, r.hydro); figuur(foe, r.foe); figuur(regime, r.regime);
};

TEKEN.kaart = async function (vlak, nogActueel) {
  if (!vereis(vlak, false)) return;
  const grafiek = figuurKaart();
  const opnieuw = () => { bewaarInst(); teken(); };
  const metrieken = [['rsq', 'R² (modelkwaliteit)'], ['evp', 'Verklaarde variantie (%)'], ['ghg', 'GHG (m NAP)'], ['glg', 'GLG (m NAP)'], ['gvg', 'GVG (m NAP)'], ['n_observations', 'Aantal metingen']];
  vul(vlak,
    el('div', { class: 'rij' },
      veld('Toon op de kaart', keuze(metrieken, S.inst.metriek, (v) => { S.inst.metriek = v; opnieuw(); }, { id: 'kaart-metriek' })),
      veld('Kleurschaal', keuze(Object.keys(KLEURSCHALEN), S.inst.kleurschaal, (v) => { S.inst.kleurschaal = v; opnieuw(); })),
      schakel('Omkeren', S.inst.omgekeerd, (v) => { S.inst.omgekeerd = v; opnieuw(); })),
    grafiek,
    el('p', { class: 'noot', text: 'Klik op een peilbuis om hem aan de selectie toe te voegen of eruit te halen. R² en verklaarde variantie bestaan alleen voor peilbuizen met een model.' }));
  const r = await roep('kaart', { metriek: S.inst.metriek }, 'Kaart tekenen');
  if (!nogActueel()) return;
  tekenKaart(grafiek, r.punten, { schaal: S.inst.kleurschaal, omgekeerd: S.inst.omgekeerd, decimalen: S.inst.metriek === 'n_observations' ? 0 : (S.inst.metriek === 'evp' ? 1 : 2) });
};

TEKEN.droogte = async function (vlak, nogActueel) {
  const grafiek = figuurKaart(), noot = el('p', { class: 'noot' });
  const st = S.stations || (S.stations = await roep('stations', {}, 'Stations laden'));
  if (!nogActueel()) return;
  if (S.inst.station == null) S.inst.station = st.standaard;
  async function bereken() {
    const jaren = (String(S.inst.jaren).match(/\d{4}/g) || []).map(Number);
    bewaarInst();
    vul(grafiek, el('p', { class: 'zacht', style: 'padding:10px', text: 'KNMI-gegevens ophalen…' }));
    try {
      const r = await roep('droogte', { station: Number(S.inst.station), ref_van: Number(S.inst.refVan), ref_tot: Number(S.inst.refTot), jaren, knip: S.inst.knip }, 'Neerslagtekort berekenen');
      if (!nogActueel()) return;
      vul(grafiek); figuur(grafiek, r.figuur);
      noot.textContent = 'Bron: ' + CFG.knmi.bron + ', laatste dag ' + r.laatste_dag + '. Het tekort is verdamping min neerslag, opgeteld vanaf 1 januari.';
    } catch (f) { vul(grafiek); meldFout(f); }
  }
  vul(vlak, el('div', { class: 'twee', style: 'grid-template-columns: 290px minmax(0, 1fr)' },
    kaartje(
      el('span', { class: 'peil-label', text: 'Neerslagtekort' }),
      veld('KNMI-station', keuze(st.stations.map((s) => [s.code, s.naam + ' (' + s.code + ')']), S.inst.station, (v) => { S.inst.station = Number(v); }, { id: 'droogte-station' })),
      el('div', { class: 'rij' },
        veld('Referentie vanaf', el('input', { class: 'invoer', type: 'number', style: 'width:110px', value: S.inst.refVan, onchange: (e) => { S.inst.refVan = e.target.value; } })),
        veld('tot en met', el('input', { class: 'invoer', type: 'number', style: 'width:110px', value: S.inst.refTot, onchange: (e) => { S.inst.refTot = e.target.value; } }))),
      veld('Jaren om te vergelijken', el('input', { class: 'invoer', value: S.inst.jaren, onchange: (e) => { S.inst.jaren = e.target.value; } })),
      schakel('Tekort niet onder nul', S.inst.knip, (v) => { S.inst.knip = v; }),
      knop('Berekenen', bereken, null, { id: 'knop-droogte' })),
    el('div', { class: 'kolom' }, grafiek, noot)));
  if (S.droogteGedaan) await bereken();
  S.droogteGedaan = true;
};

/* ── opstarten ─────────────────────────────────────────────────────────── */
function laadScript(adres) {
  return new Promise((ja, nee) => {
    document.head.append(el('script', { src: adres, onload: ja, onerror: () => nee(new Error('Kan ' + adres + ' niet laden. Is er internet?')) }));
  });
}
function gevraagdePutten() {
  const uitHash = (decodeURIComponent(location.hash).match(/GMW\d{12}/gi) || []).map((s) => s.toUpperCase());
  return [...new Set(uitHash.concat(STAAT.putten || []))];
}

async function opstarten() {
  tekenTabs(); tekenZijbalk();
  try {
    startWerker();
    const plotly = laadScript(CFG.plotly_js.adres.replace('{versie}', CFG.plotly_js.versie));
    S.versies = (await vraag({ soort: 'start', cfg: CFG, code: CODE })).ok;
    $('opstart-stap').textContent = 'Grafieken laden';
    await plotly;
    if (S.versies.plotly_js !== CFG.plotly_js.versie) console.warn('Plotly in de pagina (' + CFG.plotly_js.versie + ') wijkt af van Plotly in Python (' + S.versies.plotly_js + ').');
  } catch (f) {
    $('opstart-draaier').hidden = true;
    $('opstart-stap').textContent = 'Het laden is niet gelukt.';
    $('opstart-fout').hidden = false;
    $('opstart-fout').textContent = (f.message || String(f)) + '\n\nControleer de internetverbinding en laad de pagina opnieuw.';
    return;
  }
  S.vorige = await herinner('laatste');
  $('opstart').hidden = true;
  $('opstart').style.display = 'none';
  document.body.dataset.klaar = 'ja';

  const putten = gevraagdePutten();
  if (putten.length) {
    try {
      await nieuwLos(STAAT.titel || 'project');
      S.weergave = 'project'; tekenAlles();
      await voegPuttenToe(putten, null);
      if (S.toestand.putten.length) { S.weergave = 'reeksen'; tekenAlles(); }
    } catch (f) { meldFout(f); }
  } else tekenAlles();
}

window.addEventListener('beforeunload', (e) => { if (S.vuil) { e.preventDefault(); e.returnValue = ''; } });
window.PD = { S, roep, vraag, openMap, opslaanInMap, exporteerZip, teken, tekenAlles, zetSelectie, voegPuttenToe };
opstarten();
