// Data-analyse-dashboard voor de kamerverhuurvergunningen. Haalt de volledige lijst
// op via /api/vergunningen en rekent alle aggregaten + grafieken client-side uit,
// zodat de filters (wijk / afgelopen X dagen / groepering) meteen reageren zonder
// extra server-calls. Grafieken zijn kale inline-SVG - geen externe library.

const wijkSelect = document.getElementById("wijk-select");
const dagenInput = document.getElementById("dagen-input");
const periodeSelect = document.getElementById("periode-select");
const toon4plusEl = document.getElementById("toon-4plus");
const toon3kamerEl = document.getElementById("toon-3kamer-analyse");
const resetKnop = document.getElementById("reset-knop");
const kerncijfersEl = document.getElementById("kerncijfers");
const trendEl = document.getElementById("trend-grafiek");
const trendTitelEl = document.getElementById("trend-titel");
const wijkGrafiekEl = document.getElementById("wijk-grafiek");
const statusEl = document.getElementById("laad-status");
const metaEl = document.getElementById("meta");

let alleVergunningen = [];

function escapeHtml(tekst) {
  const div = document.createElement("div");
  div.textContent = tekst === null || tekst === undefined ? "" : String(tekst);
  return div.innerHTML;
}

function parseDatum(s) {
  return s ? new Date(s + "T00:00:00") : null;
}

function isoWeekKey(d) {
  const dt = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const dag = (dt.getUTCDay() + 6) % 7;
  dt.setUTCDate(dt.getUTCDate() - dag + 3);
  const eersteDonderdag = new Date(Date.UTC(dt.getUTCFullYear(), 0, 4));
  const week = 1 + Math.round(((dt - eersteDonderdag) / 86400000 - 3 + ((eersteDonderdag.getUTCDay() + 6) % 7)) / 7);
  return dt.getUTCFullYear() + "-W" + String(week).padStart(2, "0");
}

function periodeKey(datumStr, periode) {
  if (!datumStr) return null;
  if (periode === "jaar") return datumStr.slice(0, 4);
  if (periode === "maand") return datumStr.slice(0, 7);
  const d = parseDatum(datumStr);
  return d ? isoWeekKey(d) : null;
}

// Precies 3 bewoners = "3-kamer" (legt geen 50m-eis op); 4+ en onbekend vallen
// in de "4+"-bak.
function isDrieKamer(v) {
  return v.aantal_personen === 3;
}

// De actueel gefilterde selectie (wijk + afgelopen X dagen + grootte-toggles).
function gefilterd() {
  const wijk = wijkSelect.value;
  const dagen = parseInt(dagenInput.value, 10);
  const toon3 = toon3kamerEl.checked;
  const toon4 = toon4plusEl.checked;
  let grens = null;
  if (!isNaN(dagen) && dagen > 0) {
    const d = new Date();
    d.setDate(d.getDate() - dagen);
    grens = d.toISOString().slice(0, 10);
  }
  return alleVergunningen.filter((v) => {
    const drie = isDrieKamer(v);
    if (drie && !toon3) return false;
    if (!drie && !toon4) return false;
    if (wijk && (v.gebied || "Onbekend") !== wijk) return false;
    if (grens && (v.datum || "") < grens) return false;
    return true;
  });
}

function telPer(vergunningen, sleutelFn) {
  const telling = new Map();
  for (const v of vergunningen) {
    const k = sleutelFn(v);
    if (k === null || k === undefined) continue;
    telling.set(k, (telling.get(k) || 0) + 1);
  }
  return telling;
}

// --- SVG-grafieken ---

function verticaleBars(paren, opts) {
  // paren: [[label, waarde], ...] in chronologische volgorde
  if (!paren.length) return '<p class="muted">Geen data in deze selectie.</p>';
  const barB = 26;
  const gap = 6;
  const hoogte = 200;
  const marge = { boven: 12, onder: 46, links: 34 };
  const maxV = Math.max(...paren.map((p) => p[1]), 1);
  const plotH = hoogte - marge.boven - marge.onder;
  const breedte = marge.links + paren.length * (barB + gap) + gap;
  const labelElke = Math.ceil(paren.length / 24);

  let svg = `<svg viewBox="0 0 ${breedte} ${hoogte}" width="${breedte}" height="${hoogte}" role="img">`;
  // y-as referentielijnen (0 en max)
  const yBij = (v) => marge.boven + plotH - (v / maxV) * plotH;
  for (const v of [0, maxV]) {
    const y = yBij(v);
    svg += `<line x1="${marge.links}" y1="${y}" x2="${breedte}" y2="${y}" stroke="#e2e6ea"/>`;
    svg += `<text x="${marge.links - 5}" y="${y + 3}" text-anchor="end" font-size="10" fill="#66707a">${v}</text>`;
  }
  paren.forEach((p, i) => {
    const x = marge.links + gap + i * (barB + gap);
    const h = (p[1] / maxV) * plotH;
    const y = marge.boven + plotH - h;
    svg += `<rect x="${x}" y="${y}" width="${barB}" height="${h}" fill="${opts.kleur}" rx="2"><title>${escapeHtml(p[0])}: ${p[1]}</title></rect>`;
    svg += `<text x="${x + barB / 2}" y="${y - 3}" text-anchor="middle" font-size="9" fill="#1c2126">${p[1]}</text>`;
    if (i % labelElke === 0) {
      svg += `<text x="${x + barB / 2}" y="${hoogte - marge.onder + 14}" text-anchor="end" font-size="9" fill="#66707a" transform="rotate(-45 ${x + barB / 2} ${hoogte - marge.onder + 14})">${escapeHtml(p[0])}</text>`;
    }
  });
  svg += "</svg>";
  return svg;
}

function horizontaleBars(paren, opts) {
  // paren: [[label, waarde], ...] gesorteerd op waarde (desc)
  if (!paren.length) return '<p class="muted">Geen data in deze selectie.</p>';
  const rijH = 24;
  const labelB = 130;
  const barMax = 320;
  const maxV = Math.max(...paren.map((p) => p[1]), 1);
  const breedte = labelB + barMax + 46;
  const hoogte = paren.length * rijH + 8;
  let svg = `<svg viewBox="0 0 ${breedte} ${hoogte}" width="${breedte}" height="${hoogte}" role="img">`;
  paren.forEach((p, i) => {
    const y = i * rijH + 4;
    const b = (p[1] / maxV) * barMax;
    svg += `<text x="${labelB - 6}" y="${y + rijH / 2 + 3}" text-anchor="end" font-size="11" fill="#1c2126">${escapeHtml(p[0])}</text>`;
    svg += `<rect x="${labelB}" y="${y + 3}" width="${Math.max(b, 1)}" height="${rijH - 8}" fill="${opts.kleur}" rx="2"><title>${escapeHtml(p[0])}: ${p[1]}</title></rect>`;
    svg += `<text x="${labelB + Math.max(b, 1) + 5}" y="${y + rijH / 2 + 3}" font-size="10" fill="#66707a">${p[1]}</text>`;
  });
  svg += "</svg>";
  return svg;
}

function kaart(label, waarde) {
  return `<div class="kerncijfer"><span class="kerncijfer-waarde">${escapeHtml(waarde)}</span><span class="kerncijfer-label">${escapeHtml(label)}</span></div>`;
}

function render() {
  const selectie = gefilterd();
  const periode = periodeSelect.value;

  // Trend per periode (chronologisch gesorteerd).
  const perPeriode = [...telPer(selectie, (v) => periodeKey(v.datum, periode)).entries()].sort(
    (a, b) => (a[0] < b[0] ? -1 : 1)
  );
  const labelPeriode = { week: "week", maand: "maand", jaar: "jaar" }[periode];
  trendTitelEl.textContent = `Vergunningen per ${labelPeriode}${wijkSelect.value ? " — " + wijkSelect.value : ""}`;
  trendEl.innerHTML = verticaleBars(perPeriode, { kleur: "#ab47bc" });

  // Per wijk (desc).
  const perWijk = [...telPer(selectie, (v) => v.gebied || "Onbekend").entries()].sort((a, b) => b[1] - a[1]);
  wijkGrafiekEl.innerHTML = horizontaleBars(perWijk, { kleur: "#1b7a43" });

  // Kerncijfers.
  const totaal = selectie.length;
  const drukste = perWijk[0];
  const aantalWeken = perPeriode.length && periode === "week" ? perPeriode.length : null;
  const gemPerWeek = periode === "week" && aantalWeken ? (totaal / aantalWeken).toFixed(1) : null;
  kerncijfersEl.innerHTML =
    kaart("vergunningen in selectie", totaal) +
    kaart("wijken", perWijk.length) +
    (drukste ? kaart("drukste wijk", `${drukste[0]} (${drukste[1]})`) : "") +
    (gemPerWeek ? kaart("gem. per week", gemPerWeek) : "");
}

function vulWijkKeuze() {
  const wijken = [...new Set(alleVergunningen.map((v) => v.gebied || "Onbekend"))].sort();
  for (const w of wijken) {
    const opt = document.createElement("option");
    opt.value = w;
    opt.textContent = w;
    wijkSelect.appendChild(opt);
  }
}

async function laad() {
  try {
    const resp = await fetch("/api/vergunningen");
    const data = await resp.json();
    alleVergunningen = (data.vergunningen || []).filter((v) => v.datum);
    if (data.bijgewerkt) {
      metaEl.textContent = `Laatst bijgewerkt: ${data.bijgewerkt.replace("T", " ").slice(0, 16)}.` + (data.compleet ? "" : " Index nog in opbouw.");
    }
    if (!alleVergunningen.length) {
      statusEl.textContent = "Nog geen vergunningen in de index — de opbouw draait op de achtergrond, kom straks terug.";
      return;
    }
    statusEl.textContent = "";
    vulWijkKeuze();
    render();
  } catch (err) {
    statusEl.textContent = "Data laden mislukt — probeer het later nog eens.";
  }
}

for (const el of [wijkSelect, dagenInput, periodeSelect, toon4plusEl, toon3kamerEl]) {
  el.addEventListener("input", render);
  el.addEventListener("change", render);
}
resetKnop.addEventListener("click", () => {
  wijkSelect.value = "";
  dagenInput.value = "";
  periodeSelect.value = "maand";
  toon4plusEl.checked = true;
  toon3kamerEl.checked = true;
  render();
});

laad();
