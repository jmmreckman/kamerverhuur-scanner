const kaart = L.map("kaart", { zoomControl: false }).setView([51.9225, 4.47917], 12);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution: "&copy; OpenStreetMap-medewerkers",
  maxZoom: 19,
}).addTo(kaart);

const straalLaag = L.layerGroup().addTo(kaart);
const markerLaag = L.layerGroup().addTo(kaart);
const lijstEl = document.getElementById("lijst");
const aantalTekstEl = document.getElementById("aantal-tekst");
const statusTekstEl = document.getElementById("status-tekst");
const filterWijkEl = document.getElementById("filter-wijk");
const filterEigenInlegEl = document.getElementById("filter-eigen-inleg");
const filterWinstEl = document.getElementById("filter-winst");
const filterZoekEl = document.getElementById("filter-zoek");
const filterDagenEl = document.getElementById("filter-dagen");
const filterStadEl = document.getElementById("filter-stad");
const filterInvesteerdersEl = document.getElementById("filter-investeerders");
const filterSchakelgeldEl = document.getElementById("filter-schakelgeld");
const filterSorteerEl = document.getElementById("filter-sorteer");
const verversKnop = document.getElementById("ververs-knop");
const bekendmakingenKnop = document.getElementById("bekendmakingen-knop");
const toonKansenEl = document.getElementById("toon-kansen");
const toonVergunningenEl = document.getElementById("toon-vergunningen");
const toon3kamerEl = document.getElementById("toon-3kamer");
const vergunningenStatusEl = document.getElementById("vergunningen-status");
const zijbalkEl = document.getElementById("zijbalk");
const zijbalkKnop = document.getElementById("zijbalk-knop");
const zijbalkSluitenKnop = document.getElementById("zijbalk-sluiten-knop");

let alleKansen = [];
const markerPerId = new Map();

function formatEuro(bedrag) {
  if (bedrag === null || bedrag === undefined) return "onbekend";
  return "€" + Math.round(bedrag).toLocaleString("nl-NL");
}

// De winst en eigen inleg worden door het gekozen aantal investeerders (1/2/3)
// gedeeld; de API levert daarvoor de investeerder-onafhankelijke totalen aan.
function aantalInvesteerders() {
  const n = parseInt(filterInvesteerdersEl ? filterInvesteerdersEl.value : "2", 10);
  return n === 1 || n === 3 ? n : 2;
}

function perPersoon(totaal) {
  if (totaal === null || totaal === undefined) return null;
  return totaal / aantalInvesteerders();
}

function kansCijfers(kans) {
  return {
    winst: perPersoon(kans.winst_pm_totaal),
    eigenInleg: perPersoon(kans.eigen_inleg_na_ophoging_totaal),
    schakelgeld: perPersoon(kans.schakelgeld_totaal),
  };
}

// Waarde waarop de lijst gesorteerd wordt (altijd oplopend, laagste bovenaan);
// null/onbekend zakt naar onderen.
function sorteerWaarde(kans) {
  const veld = filterSorteerEl ? filterSorteerEl.value : "inleg";
  const c = kansCijfers(kans);
  if (veld === "winst") return c.winst;
  if (veld === "schakelgeld") return c.schakelgeld;
  if (veld === "datum") {
    const d = new Date(kans.eerst_gezien);
    return isNaN(d.getTime()) ? null : d.getTime();
  }
  return c.eigenInleg;
}

function escapeHtml(tekst) {
  const div = document.createElement("div");
  div.textContent = tekst === null || tekst === undefined ? "" : String(tekst);
  return div.innerHTML;
}

// Waarschuwingsblok met nieuwe kamerverhuurvergunningen (officiële bekendmakingen)
// binnen 50 m van deze woning - leeg als er niets is.
function waarschuwingHtml(kans) {
  const lijst = kans.bekendmaking_waarschuwingen || [];
  if (!lijst.length) return "";
  const regels = lijst
    .map((w) => {
      const datum = w.datum ? ` (${escapeHtml(w.datum)})` : "";
      const pers = w.aantal_personen ? `${escapeHtml(w.aantal_personen)} pers., ` : "";
      return `<li><a href="${escapeHtml(w.url)}" target="_blank" rel="noopener">${escapeHtml(w.adres)}</a> — ${pers}${escapeHtml(w.afstand_m)} m${datum}</li>`;
    })
    .join("");
  return `<div class="vergunning-waarschuwing">
      ⚠ Vergunning (4+ bewoners) binnen 50 m afgegeven:
      <ul>${regels}</ul>
    </div>`;
}

function dagenOpFunda(eerstGezien) {
  if (!eerstGezien) return null;
  const start = new Date(eerstGezien);
  if (isNaN(start.getTime())) return null;
  const dagen = Math.floor((Date.now() - start.getTime()) / (1000 * 60 * 60 * 24));
  return dagen >= 0 ? dagen : null;
}

function datumKort(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  if (isNaN(d.getTime())) return null;
  return d.toLocaleDateString("nl-NL", { day: "numeric", month: "short" });
}

// Regeltje over de dagelijkse beschikbaarheid-check: bevestigd nog te koop, of de
// laatste controle kon de status niet lezen. Alleen relevant voor actieve woningen.
function beschikbaarheidRegel(kans) {
  if (kans.status && kans.status !== "actief") return "";
  const gecheckt = datumKort(kans.laatst_gecheckt);
  if (!gecheckt) return "";
  if (kans.laatst_beschikbaar) {
    return `<span style="color:#1b7a43;font-size:0.85em">✓ nog te koop &middot; gecheckt ${gecheckt}</span><br>`;
  }
  return `<span style="color:#8a6d00;font-size:0.85em">status niet te lezen &middot; laatste poging ${gecheckt}</span><br>`;
}

function vulWijkFilter(kansen) {
  const huidige = filterWijkEl.value;
  const wijken = [...new Set(kansen.map((k) => k.wijknaam).filter(Boolean))].sort();
  filterWijkEl.innerHTML = '<option value="">Alle wijken</option>';
  for (const wijk of wijken) {
    const optie = document.createElement("option");
    optie.value = wijk;
    optie.textContent = wijk;
    filterWijkEl.appendChild(optie);
  }
  filterWijkEl.value = huidige;
}

function gefilterd() {
  const wijk = filterWijkEl.value;
  const maxEigenInleg = parseFloat(filterEigenInlegEl.value);
  const maxSchakelgeld = parseFloat(filterSchakelgeldEl.value);
  const minWinst = parseFloat(filterWinstEl.value);
  const zoek = filterZoekEl.value.trim().toLowerCase();
  const maxDagen = parseFloat(filterDagenEl.value);
  const stad = filterStadEl ? filterStadEl.value : "";

  return alleKansen.filter((k) => {
    const c = kansCijfers(k);
    if (stad && (k.stad || "rotterdam") !== stad) return false;
    if (wijk && k.wijknaam !== wijk) return false;
    if (!isNaN(maxEigenInleg) && (c.eigenInleg === null || c.eigenInleg > maxEigenInleg)) return false;
    if (!isNaN(maxSchakelgeld) && (c.schakelgeld === null || c.schakelgeld > maxSchakelgeld)) return false;
    if (!isNaN(minWinst) && (c.winst === null || c.winst < minWinst)) return false;
    if (zoek && !k.weergavenaam.toLowerCase().includes(zoek)) return false;
    if (!isNaN(maxDagen)) {
      const dagen = dagenOpFunda(k.eerst_gezien);
      if (dagen === null || dagen > maxDagen) return false;
    }
    return true;
  });
}

function bouwPopup(kans) {
  const div = document.createElement("div");
  div.className = "popup-inhoud";
  const dagen = dagenOpFunda(kans.eerst_gezien);
  const isDenHaag = kans.stad === "den_haag";
  const kamersLabel = isDenHaag ? "Max bewoners" : "Kamers mogelijk";
  const resetTitel = isDenHaag ? "Terug naar automatisch (m²/18, max 8)" : "Terug naar automatisch berekend (18m²-regel)";
  const signalen = (kans.check_signalen || [])
    .map((s) => `<span style="color:#5f6368;font-size:0.85em">&bull; ${s}</span>`)
    .join("<br>");

  const kamersWaarde = kans.aantal_kamers_mogelijk === null || kans.aantal_kamers_mogelijk === undefined ? "" : kans.aantal_kamers_mogelijk;
  const c = kansCijfers(kans);
  div.innerHTML = `
    <button type="button" class="verwijder-knop popup-verwijder-knop" title="Verwijderen uit kansenlijst">&times;</button>
    <button type="button" class="ster-knop ${kans.favoriet ? "ster-actief" : ""}" title="${kans.favoriet ? "Favoriet - wordt gemonitord op nieuwe vergunningen binnen 50 m" : "Als favoriet instellen (monitoren op nieuwe kamerverhuurvergunningen binnen 50 m)"}">${kans.favoriet ? "★" : "☆"}</button>
    ${waarschuwingHtml(kans)}
    <span class="adres">${kans.weergavenaam}</span>${isDenHaag ? ' <span class="stad-tag">Den Haag</span>' : ""}${kans.status && kans.status !== "actief" ? ' <span class="stad-tag" title="Niet meer actief op Funda, blijft staan omdat het een favoriet is">niet meer op Funda</span>' : ""}
    ${kans.wijknaam ? kans.wijknaam + "<br>" : ""}
    Vraagprijs: ${formatEuro(kans.prijs)}<br>
    ${kans.primaire_oppervlakte ? kans.primaire_oppervlakte + " m²<br>" : ""}
    ${kans.bag_oppervlakte && kans.bag_oppervlakte !== kans.primaire_oppervlakte ? kans.bag_oppervlakte + " m² (BAG, ter info)<br>" : ""}
    <span class="kamers-editor">
      ${kamersLabel}: <input type="number" class="kamers-input" min="0" step="1" inputmode="numeric" value="${kamersWaarde}">
      ${kans.aantal_kamers_handmatig ? `<button type="button" class="kamers-reset-knop" title="${resetTitel}">automatisch</button>` : ""}
    </span><br>
    ${c.winst !== null ? "Winst p.p./mnd: " + formatEuro(c.winst) + "<br>" : ""}
    ${c.eigenInleg !== null ? "Eigen inleg p.p. (ná verhoging): " + formatEuro(c.eigenInleg) + "<br>" : ""}
    ${c.schakelgeld !== null ? "Schakelgeld p.p. (vóór verhoging): " + formatEuro(c.schakelgeld) + "<br>" : ""}
    ${dagen !== null ? dagen + " dag(en) op Funda<br>" : ""}
    ${beschikbaarheidRegel(kans)}
    ${kans.woz_check_nodig ? '<span style="color:#b3261e">WOZ-waarde handmatig checken</span><br>' : ""}
    ${kans.woz_check_nodig && kans.woz_check_url ? `<a href="${kans.woz_check_url}" target="_blank" rel="noopener">Zelf WOZ-waarde opzoeken &rarr;</a><br>` : ""}
    ${signalen ? signalen + "<br>" : ""}
    ${kans.opmerking ? `<span style="color:#5f6368;font-size:0.9em">${kans.opmerking}</span><br>` : ""}
    <a href="/woning/${encodeURIComponent(kans.object_id)}/berekening" class="reken-link">Rekenen met deze woning &rarr;</a><br>
    ${kans.url
      ? `<a href="${kans.url}" target="_blank" rel="noopener">Bekijk op Funda &rarr;</a>`
      : `<a href="${kans.funda_zoek_url}" target="_blank" rel="noopener">Zoek op Funda &rarr;</a>`}
  `;

  div.querySelector(".popup-verwijder-knop").addEventListener("click", () => verwijderKans(kans));
  div.querySelector(".ster-knop").addEventListener("click", () => favorietToggle(kans));

  const kamersInput = div.querySelector(".kamers-input");
  kamersInput.addEventListener("change", () => kamersAanpassen(kans, kamersInput.value));

  const resetKnop = div.querySelector(".kamers-reset-knop");
  if (resetKnop) {
    resetKnop.addEventListener("click", () => kamersAanpassen(kans, ""));
  }

  return div;
}

async function kamersAanpassen(kans, waarde) {
  try {
    const body = new URLSearchParams();
    body.set("aantal_kamers", waarde);
    const resp = await fetch(`/kansen/${encodeURIComponent(kans.object_id)}/kamers`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body,
    });
    if (!resp.ok) throw new Error("aanpassen mislukt");
    const bijgewerkt = await resp.json();
    Object.assign(kans, bijgewerkt);
    renderAlles();
    const marker = markerPerId.get(kans.object_id);
    if (marker) marker.openPopup();
  } catch (err) {
    alert("Aanpassen van het aantal kamers is mislukt - probeer het nog eens.");
  }
}

async function favorietToggle(kans) {
  try {
    const resp = await fetch(`/kansen/${encodeURIComponent(kans.object_id)}/favoriet`, {
      method: "POST",
    });
    if (!resp.ok) throw new Error("favoriet mislukt");
    const data = await resp.json();
    kans.favoriet = data.favoriet;
    renderAlles();
    const marker = markerPerId.get(kans.object_id);
    if (marker) marker.openPopup();
  } catch (err) {
    alert("Favoriet instellen is mislukt - probeer het nog eens.");
  }
}

// Favorieten krijgen een goudkleurige, iets grotere marker; een favoriet met een
// openstaande vergunning-waarschuwing wordt rood, zodat 'm meteen opvalt.
function markerIcoon(kans) {
  const heeftWaarschuwing = (kans.bekendmaking_waarschuwingen || []).length > 0;
  if (!kans.favoriet && !heeftWaarschuwing) return null;
  const kleur = heeftWaarschuwing ? "#b3261e" : "#f4b400";
  const teken = heeftWaarschuwing ? "⚠" : "★";
  return L.divIcon({
    className: "favoriet-marker",
    html: `<div class="favoriet-marker-punt" style="background:${kleur}">${teken}</div>`,
    iconSize: [26, 26],
    iconAnchor: [13, 13],
  });
}

// Lichtblauwe 50m-straal rond elke favoriet: zo zie je in één oogopslag welke
// omliggende panden binnen de afstandseis vallen en dus in de gaten gehouden
// moeten worden voor nieuwe kamerverhuurvergunningen. Bewust onafhankelijk van de
// filters en de "toon kansen"-toggle - je favorietenzones blijven zichtbaar, ook
// als je alleen de vergunningenlaag aan hebt om te checken wat erbinnen valt.
function renderStralen() {
  straalLaag.clearLayers();
  for (const kans of alleKansen) {
    if (!kans.favoriet || kans.lat == null || kans.lon == null) continue;
    L.circle([kans.lat, kans.lon], {
      radius: 50, // meter
      color: "#0284c7",
      weight: 1.5,
      opacity: 0.8,
      fillColor: "#7dd3fc",
      fillOpacity: 0.15,
      interactive: false, // klikken gaan door naar de markers/vergunningen eronder
    }).addTo(straalLaag);
  }
}

function renderMarkers(kansen) {
  markerLaag.clearLayers();
  markerPerId.clear();
  if (toonKansenEl && !toonKansenEl.checked) return;
  for (const kans of kansen) {
    const icoon = markerIcoon(kans);
    const marker = (icoon ? L.marker([kans.lat, kans.lon], { icon: icoon }) : L.marker([kans.lat, kans.lon])).bindPopup(bouwPopup(kans));
    marker.addTo(markerLaag);
    markerPerId.set(kans.object_id, marker);
  }
}

function renderLijst(kansen) {
  lijstEl.innerHTML = "";
  const gesorteerd = [...kansen].sort((a, b) => {
    const va = sorteerWaarde(a);
    const vb = sorteerWaarde(b);
    if (va === null || va === undefined) return 1;
    if (vb === null || vb === undefined) return -1;
    return va - vb;
  });
  for (const kans of gesorteerd) {
    const li = document.createElement("li");
    li.className = "lijst-item";
    const dagen = dagenOpFunda(kans.eerst_gezien);
    const c = kansCijfers(kans);
    li.innerHTML = `
      <button type="button" class="verwijder-knop" title="Verwijderen uit kansenlijst">&times;</button>
      <button type="button" class="ster-knop ster-lijst ${kans.favoriet ? "ster-actief" : ""}" title="${kans.favoriet ? "Favoriet" : "Als favoriet instellen"}">${kans.favoriet ? "★" : "☆"}</button>
      <span class="adres">${kans.weergavenaam}</span>
      ${kans.stad === "den_haag" ? '<span class="stad-tag">Den Haag</span>' : ""}
      ${(kans.bekendmaking_waarschuwingen || []).length ? '<span class="lijst-waarschuwing" title="Nieuwe kamerverhuurvergunning binnen 50 m">⚠ vergunning &lt;50 m</span>' : ""}
      <div class="cijfers">
        <span>${formatEuro(kans.prijs)}</span>
        ${c.winst !== null ? `<span class="goed">+${formatEuro(c.winst)} p.p./mnd</span>` : ""}
        ${c.eigenInleg !== null ? `<span>${formatEuro(c.eigenInleg)} inleg p.p.</span>` : ""}
        ${c.schakelgeld !== null ? `<span>${formatEuro(c.schakelgeld)} schakelgeld p.p.</span>` : ""}
        ${dagen !== null ? `<span>${dagen} dag(en) op Funda</span>` : ""}
      </div>
    `;
    li.addEventListener("click", () => {
      kaart.setView([kans.lat, kans.lon], 16);
      const marker = markerPerId.get(kans.object_id);
      if (marker) marker.openPopup();
      sluitZijbalk();
    });
    li.querySelector(".verwijder-knop").addEventListener("click", (event) => {
      event.stopPropagation();
      verwijderKans(kans);
    });
    li.querySelector(".ster-knop").addEventListener("click", (event) => {
      event.stopPropagation();
      favorietToggle(kans);
    });
    lijstEl.appendChild(li);
  }
  aantalTekstEl.textContent = `${kansen.length} van ${alleKansen.length} kansen`;
}

function renderAlles() {
  const kansen = gefilterd();
  renderStralen();
  renderMarkers(kansen);
  renderLijst(kansen);
}

function sluitZijbalk() {
  zijbalkEl.classList.remove("zijbalk-open");
  zijbalkKnop.textContent = "Toon lijst";
}

function toggleZijbalk() {
  const open = zijbalkEl.classList.toggle("zijbalk-open");
  zijbalkKnop.textContent = open ? "Toon kaart" : "Toon lijst";
}

zijbalkKnop.addEventListener("click", toggleZijbalk);
zijbalkSluitenKnop.addEventListener("click", sluitZijbalk);

async function verwijderKans(kans) {
  const reden = window.prompt(
    `${kans.weergavenaam} verwijderen uit de kansenlijst?\n\nLaat staan voor een standaardreden, of typ zelf een reden (bv. "zelfbewoningsplicht"). Annuleren = niet verwijderen.`,
    ""
  );
  if (reden === null) return;

  try {
    const body = new URLSearchParams();
    if (reden.trim()) body.set("reden", reden.trim());
    const resp = await fetch(`/kansen/${encodeURIComponent(kans.object_id)}/verwijderen`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body,
    });
    if (!resp.ok) throw new Error("verwijderen mislukt");
    alleKansen = alleKansen.filter((k) => k.object_id !== kans.object_id);
    vulWijkFilter(alleKansen);
    renderAlles();
  } catch (err) {
    alert("Verwijderen is mislukt - probeer het nog eens.");
  }
}

async function laadKansen() {
  const resp = await fetch("/api/kansen");
  alleKansen = await resp.json();
  vulWijkFilter(alleKansen);
  renderAlles();
}

// --- Vergunningenlaag (alle verleende kamerverhuurvergunningen, geclusterd) ---

const vergunningenLaag = L.markerClusterGroup
  ? L.markerClusterGroup({ chunkedLoading: true, maxClusterRadius: 50 })
  : L.layerGroup();
let vergunningenGeladen = false;
let vergunningenData = [];

function bouwVergunningPopup(v) {
  const div = document.createElement("div");
  div.className = "popup-inhoud popup-vergunning";
  const personen = v.aantal_personen ? `${v.aantal_personen} personen` : "aantal onbekend";
  const datum = v.besluitdatum || v.datum || "onbekend";
  div.innerHTML = `
    <span class="adres">${escapeHtml(v.adres || "onbekend adres")}</span>
    <span class="vergunning-badge">vergunning</span><br>
    ${v.gebied ? "Wijk: " + escapeHtml(v.gebied) + "<br>" : ""}
    Verleend voor: <strong>${escapeHtml(personen)}</strong><br>
    Besluitdatum: ${escapeHtml(datum)}<br>
    ${v.postcode ? "Postcode: " + escapeHtml(v.postcode) + "<br>" : ""}
    ${v.zaaknummer ? "Zaaknummer: " + escapeHtml(v.zaaknummer) + "<br>" : ""}
    ${v.url ? `<a href="${escapeHtml(v.url)}" target="_blank" rel="noopener">Bekijk bekendmaking &rarr;</a>` : ""}
  `;
  return div;
}

// 3-kamer vergunningen (precies 3 bewoners) leggen geen 50m-eis op; standaard
// tonen we alleen de 4+ (en onbekende, conservatief). Het vinkje "ook 3-kamer"
// voegt de 3-persoons toe, in een andere kleur.
function isDrieKamer(v) {
  return v.aantal_personen === 3;
}

function renderVergunningen() {
  vergunningenLaag.clearLayers();
  const toon3 = toon3kamerEl && toon3kamerEl.checked;
  const punten = vergunningenData.filter(
    (v) => v.lat != null && v.lon != null && (toon3 || !isDrieKamer(v))
  );
  const markers = punten.map((v) => {
    const drie = isDrieKamer(v);
    return L.circleMarker([v.lat, v.lon], {
      radius: drie ? 5 : 6,
      color: drie ? "#00796b" : "#7b1fa2",
      weight: 1,
      fillColor: drie ? "#4db6ac" : "#ab47bc",
      fillOpacity: 0.8,
    }).bindPopup(bouwVergunningPopup(v));
  });
  if (vergunningenLaag.addLayers) {
    vergunningenLaag.addLayers(markers);
  } else {
    markers.forEach((m) => m.addTo(vergunningenLaag));
  }
}

async function laadVergunningen() {
  if (vergunningenGeladen) return;
  vergunningenStatusEl.textContent = "Vergunningen laden...";
  try {
    const resp = await fetch("/api/vergunningen");
    const data = await resp.json();
    vergunningenData = data.vergunningen || [];
    vergunningenGeladen = true;
    renderVergunningen();
    const drie = vergunningenData.filter(isDrieKamer).length;
    const vierPlus = vergunningenData.length - drie;
    const opmerking = data.compleet ? "" : " (index nog in opbouw)";
    vergunningenStatusEl.textContent = `${vergunningenData.length} vergunningen: ${vierPlus}× 4+, ${drie}× 3-kamer${opmerking}.`;
  } catch (err) {
    vergunningenStatusEl.textContent = "Vergunningen laden mislukt.";
    toonVergunningenEl.checked = false;
  }
}

if (toonKansenEl) {
  toonKansenEl.addEventListener("change", renderAlles);
}
if (toonVergunningenEl) {
  toonVergunningenEl.addEventListener("change", async () => {
    if (toonVergunningenEl.checked) {
      await laadVergunningen();
      if (toonVergunningenEl.checked) kaart.addLayer(vergunningenLaag);
    } else {
      kaart.removeLayer(vergunningenLaag);
    }
  });
}
if (toon3kamerEl) {
  toon3kamerEl.addEventListener("change", () => {
    if (vergunningenGeladen && toonVergunningenEl.checked) renderVergunningen();
  });
}

for (const el of [filterWijkEl, filterEigenInlegEl, filterSchakelgeldEl, filterWinstEl, filterZoekEl,
                  filterDagenEl, filterStadEl, filterInvesteerdersEl, filterSorteerEl]) {
  if (el) el.addEventListener("input", renderAlles);
}
for (const el of [filterStadEl, filterInvesteerdersEl, filterSorteerEl]) {
  if (el) el.addEventListener("change", renderAlles);
}

verversKnop.addEventListener("click", async () => {
  verversKnop.disabled = true;
  statusTekstEl.textContent = "Bezig met verversen (kan even duren)...";
  try {
    const resp = await fetch("/ververs", { method: "POST" });
    const data = await resp.json();
    statusTekstEl.textContent = `Klaar: ${data.nieuw_actief} nieuwe kans(en), ${data.nieuw_afgevallen} afgevallen.`;
    if (data.fouten && data.fouten.length) {
      statusTekstEl.textContent += ` Waarschuwing: ${data.fouten.join(" | ")}`;
    }
    await laadKansen();
  } catch (err) {
    statusTekstEl.textContent = "Verversen mislukt - probeer het nog eens.";
  } finally {
    verversKnop.disabled = false;
  }
});

bekendmakingenKnop.addEventListener("click", async () => {
  bekendmakingenKnop.disabled = true;
  statusTekstEl.textContent = "Bezig met checken van officiële bekendmakingen...";
  try {
    const resp = await fetch("/bekendmakingen/check", { method: "POST" });
    const data = await resp.json();
    if (data.aantal_nieuw) {
      statusTekstEl.textContent = `${data.aantal_nieuw} nieuwe vergunning(en) binnen 50 m van een favoriet gevonden - zie de gemarkeerde woning(en) + je mail.`;
    } else {
      statusTekstEl.textContent = "Geen nieuwe kamerverhuurvergunningen binnen 50 m van je favorieten.";
    }
    if (data.fouten && data.fouten.length) {
      statusTekstEl.textContent += ` Waarschuwing: ${data.fouten.join(" | ")}`;
    }
    await laadKansen();
  } catch (err) {
    statusTekstEl.textContent = "Checken van bekendmakingen mislukt - probeer het nog eens.";
  } finally {
    bekendmakingenKnop.disabled = false;
  }
});

laadKansen();
