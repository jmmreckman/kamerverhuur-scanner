"use strict";
// WWSO-rekentool: bouw de woning additief op (kamers met eigen voorzieningen +
// gedeelde ruimtes), vraag de puntentelling op bij de server en toon per kamer de
// maximale kale huur. "Gebruik" zet de gemiddelde huur als kale huur per kamer in
// de investerings-rekentool.

const W = window.__wwso;

const RUBRIEK_LABELS = {
  oppervlakte: "Oppervlakte (vertrek + overige)",
  verwarming: "Verwarming",
  energie: "Energieprestatie",
  keuken: "Keuken",
  sanitair: "Sanitair",
  buitenruimte: "Buitenruimte",
  woz: "WOZ-waarde",
};

const AANRECHT_OPTIES = [
  ["0", "geen keuken"],
  ["1.5", "1 – 2 meter (4 pt)"],
  ["2.5", "2 – 3 meter (7 pt)"],
  ["4", "3 – 5 meter (10 pt)"],
  ["6", "meer dan 5 meter (13 pt, ≥8 kamers)"],
];

function euro(bedrag) {
  return "€ " + Number(bedrag).toLocaleString("nl-NL", {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  });
}

function el(tag, cls, html) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (html !== undefined) n.innerHTML = html;
  return n;
}

// --- Velden van één element (keuken / m² / verwarmd) ------------------------
function keukenVeldenHtml() {
  const opties = AANRECHT_OPTIES
    .map(([v, l]) => '<option value="' + v + '"' + (v === "2.5" ? " selected" : "") + ">" + l + "</option>")
    .join("");
  const voorz = Object.entries(W.keukenVoorzieningen)
    .map(([k, l]) => '<label class="wwso-check"><input type="checkbox" class="keuken-voorz" value="' + k + '"> ' + l + "</label>")
    .join("");
  return (
    '<label class="wwso-veldje"><span>Aanrechtlengte</span>' +
    '<select class="veld-aanrecht">' + opties + "</select></label>" +
    '<div class="wwso-checks">' + voorz + "</div>" +
    '<label class="wwso-veldje"><span>Extra kastruimte (per 60 cm)</span>' +
    '<input type="number" class="veld-kastruimte" step="1" min="0" value="0"></label>'
  );
}

function elementVeldenHtml(spec) {
  let h = "";
  if (spec.effect === "keuken") h += keukenVeldenHtml();
  if ((spec.velden || []).includes("m2")) {
    h += '<label class="wwso-veldje"><span>Oppervlakte</span>' +
      '<span class="reken-invoer"><input type="number" class="veld-m2" step="any" min="0" value="0" inputmode="decimal"><span class="teken">m²</span></span></label>';
  }
  if ((spec.velden || []).includes("verwarmd")) {
    h += '<label class="wwso-check wwso-inline"><input type="checkbox" class="veld-verwarmd" checked> verwarmd</label>';
  }
  return h;
}

// --- Eén element-kaartje (privé of gedeeld) ---------------------------------
function maakElement(type, gedeeld) {
  const spec = W.elementen[type];
  const node = el("div", "wwso-element");
  node.dataset.type = type;
  node.appendChild(el("div", "wwso-element-kop",
    "<span>" + spec.label + "</span>" +
    '<button type="button" class="wwso-verwijder" title="Verwijderen">&times;</button>'));
  const body = el("div", "wwso-element-body", elementVeldenHtml(spec));
  if (gedeeld) {
    body.insertAdjacentHTML("beforeend",
      '<label class="wwso-veldje"><span>Gedeeld door … kamers <small>(leeg = alle)</small></span>' +
      '<input type="number" class="veld-toegang" step="1" min="1" placeholder="alle"></label>');
  }
  node.appendChild(body);
  node.querySelector(".wwso-verwijder").addEventListener("click", () => node.remove());
  return node;
}

// --- Kamer-kaart -----------------------------------------------------------
function paletOpties(keys) {
  return keys.map((k) => '<option value="' + k + '">' + W.elementen[k].label + "</option>").join("");
}

function maakKamer(m2) {
  const kamer = el("div", "wwso-kamer");
  kamer.innerHTML =
    '<div class="wwso-kamer-kop">' +
    '<span class="kamer-nr"></span>' +
    '<span class="reken-invoer"><input type="number" class="kamer-m2" step="any" min="0" ' +
    'inputmode="decimal" value="' + (m2 || "") + '"><span class="teken">m²</span></span>' +
    '<label class="wwso-check wwso-inline"><input type="checkbox" class="kamer-verwarmd" checked> verwarmd</label>' +
    '<button type="button" class="wwso-verwijder" title="Kamer verwijderen">&times;</button>' +
    "</div>" +
    '<div class="wwso-kamer-elementen"></div>' +
    '<div class="wwso-toevoeg-rij">' +
    '<select class="kamer-kies"><option value="">— voorziening toevoegen —</option>' +
    paletOpties(W.privePalet) + "</select>" +
    '<button type="button" class="wwso-knop-secundair kamer-el-toevoegen">+ toevoegen</button>' +
    "</div>";

  kamer.querySelector(".wwso-verwijder").addEventListener("click", () => {
    kamer.remove();
    nummerKamers();
  });
  const kies = kamer.querySelector(".kamer-kies");
  kamer.querySelector(".kamer-el-toevoegen").addEventListener("click", () => {
    if (!kies.value) return;
    kamer.querySelector(".wwso-kamer-elementen").appendChild(maakElement(kies.value, false));
    kies.value = "";
  });
  return kamer;
}

function nummerKamers() {
  document.querySelectorAll("#kamers .wwso-kamer").forEach((k, n) => {
    k.querySelector(".kamer-nr").textContent = "Kamer " + (n + 1);
  });
}

// --- Uitlezen ---------------------------------------------------------------
function leesElement(node) {
  const spec = W.elementen[node.dataset.type];
  const out = { type: node.dataset.type };
  if (spec.effect === "keuken") {
    out.aanrecht_m = node.querySelector(".veld-aanrecht").value;
    out.voorzieningen = Array.from(node.querySelectorAll(".keuken-voorz:checked")).map((c) => c.value);
    out.extra_kastruimte_60cm = node.querySelector(".veld-kastruimte").value;
  }
  const m2 = node.querySelector(".veld-m2");
  if (m2) out.oppervlakte_m2 = m2.value;
  const verw = node.querySelector(".veld-verwarmd");
  if (verw) out.verwarmd = verw.checked;
  const toegang = node.querySelector(".veld-toegang");
  if (toegang) out.aantal_kamers_toegang = toegang.value;
  return out;
}

function verzamelPayload() {
  const val = (id) => document.getElementById(id).value;
  const kamers = Array.from(document.querySelectorAll("#kamers .wwso-kamer")).map((k) => ({
    oppervlakte_m2: k.querySelector(".kamer-m2").value,
    verwarmd: k.querySelector(".kamer-verwarmd").checked,
    elementen: Array.from(k.querySelectorAll(".wwso-kamer-elementen .wwso-element")).map(leesElement),
  }));
  const gedeelde = Array.from(document.querySelectorAll("#gedeelde-ruimtes .wwso-element")).map(leesElement);
  return {
    kamers,
    gedeelde_elementen: gedeelde,
    energielabel: val("energielabel"),
    bouwjaar: val("bouwjaar"),
    woz_waarde: val("woz_waarde"),
    woz_oppervlakte_m2: val("woz_oppervlakte_m2"),
    corop_gemiddelde_woz_m2: val("corop_gemiddelde_woz_m2"),
  };
}

// --- Rekenen + tonen --------------------------------------------------------
let laatsteGemiddelde = null;

async function bereken() {
  const foutEl = document.getElementById("wwso-fout");
  foutEl.hidden = true;
  try {
    const resp = await fetch(W.berekenUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(verzamelPayload()),
    });
    const data = await resp.json();
    if (!resp.ok) {
      foutEl.textContent = data.fout || "Er ging iets mis bij het rekenen.";
      foutEl.hidden = false;
      document.getElementById("wwso-resultaat").hidden = true;
      return;
    }
    toonResultaat(data);
  } catch (e) {
    foutEl.textContent = "Netwerkfout - probeer opnieuw.";
    foutEl.hidden = false;
  }
}

function toonRubrieken(kamer) {
  const rub = document.querySelector("#wwso-rubriek-tabel tbody");
  rub.innerHTML = "";
  Object.keys(RUBRIEK_LABELS).forEach((key) => {
    const punten = kamer.punten_per_rubriek[key];
    if (punten === undefined) return;
    rub.appendChild(el("tr", null,
      "<td>" + RUBRIEK_LABELS[key] + "</td><td>" +
      Number(punten).toLocaleString("nl-NL") + " pt</td>"));
  });
  rub.appendChild(el("tr", "groot",
    "<td>Totaal (afgerond)</td><td>" + kamer.totaal_punten + " pt</td>"));
}

function toonResultaat(data) {
  laatsteGemiddelde = data.gemiddelde_huur;
  document.querySelector('[data-veld="gemiddelde_huur"]').textContent = euro(data.gemiddelde_huur);
  document.querySelector('[data-veld="laagste_huur"]').textContent = euro(data.laagste_huur);
  document.querySelector('[data-veld="totaal_huur"]').textContent = euro(data.totaal_huur);

  const tbody = document.querySelector("#wwso-kamer-tabel tbody");
  tbody.innerHTML = "";
  data.kamers.forEach((k, n) => {
    const tr = el("tr", null,
      "<td>Kamer " + (n + 1) + "</td><td>" + k.oppervlakte_m2 + " m²</td><td>" +
      k.totaal_punten + "</td><td>" + euro(k.max_kale_huur) + "</td>");
    tr.classList.add("wwso-kamer-rij");
    tr.addEventListener("click", () => {
      document.getElementById("wwso-rubriek-kamer").textContent = n + 1;
      toonRubrieken(k);
    });
    tbody.appendChild(tr);
  });

  if (data.kamers[0]) {
    document.getElementById("wwso-rubriek-kamer").textContent = "1";
    toonRubrieken(data.kamers[0]);
  }
  document.getElementById("wwso-resultaat").hidden = false;
}

async function gebruik() {
  if (laatsteGemiddelde == null) return;
  const btn = document.getElementById("wwso-gebruik");
  btn.disabled = true;
  try {
    const resp = await fetch(W.gebruikUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kale_huur_per_kamer: laatsteGemiddelde }),
    });
    const data = await resp.json();
    if (resp.ok && data.url) window.location.href = data.url;
    else btn.disabled = false;
  } catch (e) {
    btn.disabled = false;
  }
}

// --- Init -------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", () => {
  const kamersEl = document.getElementById("kamers");
  const aantal = Math.max(1, W.aantalKamers || 1);
  for (let n = 0; n < aantal; n++) kamersEl.appendChild(maakKamer(W.kamerM2));
  nummerKamers();

  document.getElementById("kamer-toevoegen").addEventListener("click", () => {
    kamersEl.appendChild(maakKamer(W.kamerM2));
    nummerKamers();
  });

  const gedeeldKies = document.getElementById("gedeeld-kies");
  document.getElementById("gedeeld-toevoegen").addEventListener("click", () => {
    if (!gedeeldKies.value) return;
    document.getElementById("gedeelde-ruimtes").appendChild(maakElement(gedeeldKies.value, true));
    gedeeldKies.value = "";
  });

  document.getElementById("wwso-bereken").addEventListener("click", bereken);
  document.getElementById("wwso-gebruik").addEventListener("click", gebruik);
});
