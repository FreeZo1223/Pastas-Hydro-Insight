/* De rekenwerker: Python (Pyodide) met de rekenkern, buiten het scherm om.
   De pagina stuurt berichten { id, soort, ... } en krijgt { id, ok } of { id, fout } terug.
   Na een handeling die het project verandert, gaan de gewijzigde bestanden mee terug,
   zodat de pagina ze in de projectmap kan zetten. */

var py = null;
var roepPy = null;
var KERN = '/kern';

/* Handelingen waarna de projectmap bijgewerkt moet worden. */
var VERANDERT = { nieuw_project: 1, open_zip: 1, voeg_put_toe: 1, verwijder_put: 1, fit: 1 };

var OPSTART = [
  'import sys, types',
  'sys.path.insert(0, "' + KERN + '")',
  '# pastastore maakt een slot uit multiprocessing aan; dat bestaat in de browser niet.',
  '# Er is hier maar een enkel proces, dus een slot dat altijd vrij is volstaat.',
  'class _Slot:',
  '    SEM_VALUE_MAX = 1',
  '    handle = 0; kind = 0; maxvalue = 1; name = None',
  '    def __init__(self, *a, **k): pass',
  '    def acquire(self, *a, **k): return True',
  '    def release(self, *a, **k): pass',
  '    def __enter__(self): return True',
  '    def __exit__(self, *a): pass',
  '    def _count(self): return 0',
  '    def _is_mine(self): return True',
  '_mp = types.ModuleType("_multiprocessing")',
  '_mp.SemLock = _Slot; _mp.sem_unlink = lambda *a: None; _mp.flags = {}',
  'sys.modules["_multiprocessing"] = _mp',
  '# Laat urllib via de browser ophalen.',
  'import pyodide_http; pyodide_http.patch_all()',
  'import matplotlib; matplotlib.use("agg")',
  'from pastasdash_v3.brug import roep'
].join('\n');

function meld(stap) { postMessage({ soort: 'voortgang', stap: stap }); }

function schrijf(wortel, bestanden) {
  Object.keys(bestanden).forEach(function (pad) {
    var vol = wortel + '/' + pad;
    py.FS.mkdirTree(vol.split('/').slice(0, -1).join('/'));
    py.FS.writeFile(vol, bestanden[pad]);
  });
}

function wis(pad) {
  var info;
  try { info = py.FS.analyzePath(pad); } catch (e) { return; }
  if (!info.exists) return;
  if (py.FS.isDir(info.object.mode)) {
    py.FS.readdir(pad).forEach(function (n) { if (n !== '.' && n !== '..') wis(pad + '/' + n); });
    py.FS.rmdir(pad);
  } else py.FS.unlink(pad);
}

async function start(cfg, code) {
  importScripts(cfg.pyodide.basis + 'pyodide.js');
  meld('Python starten');
  py = await loadPyodide({ indexURL: cfg.pyodide.basis });
  meld('Rekenpakketten laden');
  await py.loadPackage(cfg.pakketten.pyodide);
  meld('PASTAS installeren');
  py.globals.set('_pip', py.toPy(cfg.pakketten.pip));
  py.globals.set('_kaal', py.toPy(cfg.pakketten.pip_zonder_afhankelijkheden));
  await py.runPythonAsync('import micropip\nawait micropip.install(_pip)\nawait micropip.install(_kaal, deps=False)');
  meld('Rekenkern laden');
  schrijf(KERN, code);
  await py.runPythonAsync(OPSTART);
  roepPy = py.globals.get('roep');
  return JSON.parse(roepPy('versies', '{}')).ok;
}

/* Wat er in het project veranderd is, met de inhoud erbij. */
function wijzigingen() {
  var w = JSON.parse(roepPy('gewijzigd', '{}')).ok;
  var uit = { schrijf: {}, weg: w.weg };
  w.schrijf.forEach(function (pad) { uit.schrijf[pad] = py.FS.readFile(w.wortel + '/' + pad); });
  return uit;
}

function buffers(b) { return Object.keys(b.schrijf).map(function (k) { return b.schrijf[k].buffer; }); }

onmessage = async function (e) {
  var m = e.data;
  try {
    if (m.soort === 'start') {
      postMessage({ id: m.id, ok: await start(m.cfg, m.code) });
    } else if (m.soort === 'roep') {
      var antwoord = JSON.parse(roepPy(m.naam, JSON.stringify(m.args || {})));
      if (antwoord.fout) { postMessage({ id: m.id, fout: antwoord.fout, spoor: antwoord.spoor }); return; }
      var b = VERANDERT[m.naam] ? wijzigingen() : null;
      postMessage({ id: m.id, ok: antwoord.ok, bestanden: b }, b ? buffers(b) : []);
    } else if (m.soort === 'schrijf') {
      if (m.leeg) wis(m.wortel);
      schrijf(m.wortel, m.bestanden);
      postMessage({ id: m.id, ok: true });
    } else if (m.soort === 'lees') {
      var data = py.FS.readFile(m.pad);
      postMessage({ id: m.id, ok: data }, [data.buffer]);
    } else if (m.soort === 'alles') {
      /* De hele store opnieuw aanbieden, bijvoorbeeld voor een nieuwe projectmap. */
      roepPy('schijf_is_leeg', '{}');
      var alles = wijzigingen();
      postMessage({ id: m.id, ok: true, bestanden: alles }, buffers(alles));
    }
  } catch (f) {
    postMessage({ id: m.id, fout: String(f && f.message || f) });
  }
};
