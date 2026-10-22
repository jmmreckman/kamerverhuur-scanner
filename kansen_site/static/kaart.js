const kaart = L.map("kaart", { zoomControl: false }).setView([51.9225, 4.47917], 12);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution: "&copy; OpenStreetMap-medewerkers",
  maxZoom: 19,
}).addTo(kaart);

const straalLaag = L.layerGroup().addTo(kaart);
const markerLaag = L.layerGroup().addTo(kaart);
// Eigen laag voor handmatig toegevoegde test-adressen (groene 50m-cirkels), los
// van de filters/toggles - zie de "test 50m adres toevoegen"-functie onderaan.
const testLaag = L.layerGroup().addTo(kaart);
const lijstEl = document.getElementById("lijst");
const aantalTekstEl = document.getElementById("aantal-tekst");
const statusTekstEl = document.getElementById("status-tekst");
const filterWijkEl = document.getElementById("filter-wijk");
const filterEigenInlegEl = document.getElementById("filter-eigen-inleg");
const filterWinstEl = document.getElementById("filter-winst");
const filterM2MinEl = document.getElementById("filter-m2-min");
const filterM2MaxEl = document.getElementById("filter-m2-max");
const filterPrijsM2MaxEl = document.getElementById("filter-prijs-m2-max");
const filterWoningtypeEl = document.getElementById("filter-woningtype");
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
const testAdresInvoerEl = document.getElementById("test-adres-invoer");
const testAdresKnop = document.getElementById("test-adres-knop");
const testAdresStatusEl = document.getElementById("test-adres-status");
const opkoopScanInvoerEl = document.getElementById("opkoop-scan-invoer");
const opkoopScanKnop = document.getElementById("opkoop-scan-knop");
const opkoopScanStatusEl = document.getElementById("opkoop-scan-status");
const opkoopScanOntvangersEl = document.getElementById("opkoop-scan-ontvangers");
const zoekInvoerEl = document.getElementById("zoek-invoer");
const zoekResultatenEl = document.getElementById("zoek-resultaten");

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
  // m²-filter op de advertentie-oppervlakte (NIET de BAG-oppervlakte).
  const minM2 = filterM2MinEl ? parseFloat(filterM2MinEl.value) : NaN;
  const maxM2 = filterM2MaxEl ? parseFloat(filterM2MaxEl.value) : NaN;
  // Max. prijs per m², ook op de advertentie-oppervlakte (NIET de BAG).
  const maxPrijsM2 = filterPrijsM2MaxEl ? parseFloat(filterPrijsM2MaxEl.value) : NaN;
  const zoek = filterZoekEl.value.trim().toLowerCase();
  const maxDagen = parseFloat(filterDagenEl.value);
  const stad = filterStadEl ? filterStadEl.value : "";
  const woningtype = filterWoningtypeEl ? filterWoningtypeEl.value : "";

  return alleKansen.filter((k) => {
    const c = kansCijfers(k);
    if (stad && (k.stad || "rotterdam") !== stad) return false;
    if (wijk && k.wijknaam !== wijk) return false;
    if (!isNaN(maxEigenInleg) && (c.eigenInleg === null || c.eigenInleg > maxEigenInleg)) return false;
    if (!isNaN(maxSchakelgeld) && (c.schakelgeld === null || c.schakelgeld > maxSchakelgeld)) return false;
    if (!isNaN(minWinst) && (c.winst === null || c.winst < minWinst)) return false;
    if (!isNaN(minM2) || !isNaN(maxM2)) {
      // Woningen zonder advertentie-m² vallen weg zodra er een m²-grens staat:
      // we kunnen niet bevestigen dat ze binnen het bereik vallen.
      const m2 = k.oppervlakte_advertentie;
      if (m2 === null || m2 === undefined) return false;
      if (!isNaN(minM2) && m2 < minM2) return false;
      if (!isNaN(maxM2) && m2 > maxM2) return false;
    }
    if (!isNaN(maxPrijsM2)) {
      // €/m² op de advertentie-oppervlakte; zonder m²/prijs niet te bepalen → weg.
      const m2 = k.oppervlakte_advertentie;
      if (!m2 || k.prijs === null || k.prijs === undefined) return false;
      if (k.prijs / m2 > maxPrijsM2) return false;
    }
    if (woningtype && k.woningtype !== woningtype) return false;
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
    ${kans.woningtype_label ? `${kans.woningtype_label}${kans.woningtype ? ` &middot; ${kans.woningtype}` : ""}<br>` : ""}
    ${kans.perceel_oppervlakte ? `Perceel: ${kans.perceel_oppervlakte} m²<br>` : ""}
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
    ${kans.concurrentie_samenvatting
      ? `<span style="color:#1b7a43;font-size:0.9em">Concurrentie (50 m): ${escapeHtml(kans.concurrentie_samenvatting)}</span><br>`
      : (kans._concurrentie_scan_loopt
          ? `<span style="color:#5f6368;font-size:0.85em">Concurrentie-scan loopt op de achtergrond… (ververs zo voor de samenvatting)</span><br>`
          : "")}
    ${kans.opmerking ? `<span style="color:#5f6368;font-size:0.9em">${kans.opmerking}</span><br>` : ""}
    <a href="/woning/${encodeURIComponent(kans.object_id)}/berekening" class="reken-link">Rekenen met deze woning &rarr;</a><br>
    ${window.IS_BEHEERDER ? `<a href="#" class="concurrentie-scan-link">Start concurrentie-scan voor dit adres &rarr;</a><br>` : ""}
    ${kans.url
      ? `<a href="${kans.url}" target="_blank" rel="noopener">Bekijk op Funda &rarr;</a>`
      : `<a href="${kans.zoek_url}" target="_blank" rel="noopener">Zoek op Google &rarr;</a>`}
  `;

  div.querySelector(".popup-verwijder-knop").addEventListener("click", () => verwijderKans(kans));
  const scanLink = div.querySelector(".concurrentie-scan-link");
  if (scanLink) scanLink.addEventListener("click", (e) => { e.preventDefault(); startConcurrentieScanVoor(kans, scanLink); });
  div.querySelector(".ster-knop").addEventListener("click", () => favorietToggle(kans));

  const kamersInput = div.querySelector(".kamers-input");
  kamersInput.addEventListener("change", () => kamersAanpassen(kans, kamersInput.value));

  const resetKnop = div.querySelector(".kamers-reset-knop");
  if (resetKnop) {
    resetKnop.addEventListener("click", () => kamersAanpassen(kans, ""));
  }

  return div;
}

async function startConcurrentieScanVoor(kans, linkEl) {
  // Start de concurrentie-scan voor dit adres zonder overtypen; de ontvanger wordt
  // server-side bepaald uit de mail-voorkeuren van het ingelogde account. Resultaat
  // komt per mail (PDF-rapport). De link toont kort de melding/fout als feedback.
  const origineel = linkEl.textContent;
  linkEl.textContent = "Concurrentie-scan starten…";
  linkEl.style.pointerEvents = "none";
  try {
    const resp = await fetch("/opkoop-scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ adres: kans.weergavenaam }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      linkEl.textContent = data.fout || "Scan starten mislukt";
      linkEl.style.pointerEvents = "";
      return;
    }
    linkEl.textContent = "✓ " + (data.melding || "Scan gestart; resultaat komt per mail.");
  } catch (err) {
    linkEl.textContent = "Scan starten mislukt — probeer opnieuw";
    linkEl.style.pointerEvents = "";
  }
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
    openWoning(kans);
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
    if (data.concurrentie_samenvatting) kans.concurrentie_samenvatting = data.concurrentie_samenvatting;
    // Net favoriet gemaakt: de concurrentie-scan draait op de achtergrond; toon dat
    // zodat de gebruiker weet dat de samenvatting zo verschijnt (na een ververs).
    kans._concurrentie_scan_loopt = !!data.concurrentie_scan_loopt;
    renderAlles();
    openWoning(kans);
  } catch (err) {
    alert("Favoriet instellen is mislukt - probeer het nog eens.");
  }
}

function _puntIcoon(kleur, teken) {
  return L.divIcon({
    className: "favoriet-marker",
    html: `<div class="favoriet-marker-punt" style="background:${kleur}">${teken}</div>`,
    iconSize: [26, 26],
    iconAnchor: [13, 13],
  });
}

// Markerkleur op prioriteit: rood (openstaande vergunning-waarschuwing) > goud
// (favoriet) > paars (appartement). Woonhuis en onbekend woningtype houden de
// standaard blauwe Leaflet-pin (null = geen eigen icoon).
function markerIcoon(kans) {
  if ((kans.bekendmaking_waarschuwingen || []).length > 0) return _puntIcoon("#b3261e", "⚠");
  if (kans.favoriet) return _puntIcoon("#f4b400", "★");
  if (kans.woningtype === "appartement") return _puntIcoon("#7c3aed", "");
  return null;
}

// Woningen op exact dezelfde coördinaat (bv. Coolhaven 150a en 150b) overlappen op
// de kaart zodat je er maar één kunt aanklikken. Zulke plekken krijgen daarom één
// marker met het aantal erop (rood bij een waarschuwing, goud bij een favoriet,
// anders blauw); klikken opent een keuzelijstje met de losse woningen.
function groepMarkerIcoon(groep) {
  const heeftWaarschuwing = groep.some((k) => (k.bekendmaking_waarschuwingen || []).length > 0);
  const heeftFavoriet = groep.some((k) => k.favoriet);
  const kleur = heeftWaarschuwing ? "#b3261e" : heeftFavoriet ? "#f4b400" : "#2a81cb";
  return L.divIcon({
    className: "groep-marker",
    html: `<div class="groep-marker-punt" style="background:${kleur}">${groep.length}</div>`,
    iconSize: [28, 28],
    iconAnchor: [14, 14],
  });
}

function bouwGroepKeuze(groep) {
  const div = document.createElement("div");
  div.className = "groep-keuze";
  const titel = document.createElement("div");
  titel.className = "groep-keuze-titel";
  titel.textContent = `${groep.length} woningen op deze plek`;
  div.appendChild(titel);
  for (const kans of groep) {
    const knop = document.createElement("button");
    knop.type = "button";
    knop.className = "groep-keuze-item";
    knop.innerHTML = `${kans.favoriet ? "★ " : ""}${escapeHtml(straatHuisnummer(kans))}`;
    knop.addEventListener("click", () => { kaart.closePopup(); openWoning(kans); });
    div.appendChild(knop);
  }
  return div;
}

// Opent het ballonnetje van één specifieke woning, waar 'ie ook staat: heeft 'ie een
// eigen marker (alleenstaand) dan die popup; zit 'ie in een coördinaat-groep of valt
// 'ie buiten de filters, dan tonen we de volledige popup los op de locatie.
function openWoning(kans) {
  if (kans.lat == null || kans.lon == null) return;
  const marker = markerPerId.get(kans.object_id);
  if (marker) {
    marker.openPopup();
  } else {
    L.popup().setLatLng([kans.lat, kans.lon]).setContent(bouwPopup(kans)).openOn(kaart);
  }
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
  const toonKansen = !toonKansenEl || toonKansenEl.checked;
  const teTonen = toonKansen ? [...kansen] : [];
  const ids = new Set(teTonen.map((k) => k.object_id));
  // Favorieten krijgen ALTIJD een marker (net als hun 50m-cirkel, zie renderStralen) -
  // ook als 'toon kansen' uit staat of de favoriet buiten de ingestelde filters valt.
  // Anders zie je een losse 50m-cirkel zonder klikbare woning op de kaart.
  for (const kans of alleKansen) {
    if (kans.favoriet && kans.lat != null && kans.lon != null && !ids.has(kans.object_id)) {
      teTonen.push(kans);
      ids.add(kans.object_id);
    }
  }
  // Groepeer op coördinaat zodat woningen op exact dezelfde plek niet overlappen.
  const groepen = new Map();
  for (const kans of teTonen) {
    if (kans.lat == null || kans.lon == null) continue;
    const sleutel = `${kans.lat.toFixed(6)},${kans.lon.toFixed(6)}`;
    if (!groepen.has(sleutel)) groepen.set(sleutel, []);
    groepen.get(sleutel).push(kans);
  }
  for (const groep of groepen.values()) {
    if (groep.length === 1) {
      const kans = groep[0];
      const icoon = markerIcoon(kans);
      const marker = (icoon ? L.marker([kans.lat, kans.lon], { icon: icoon }) : L.marker([kans.lat, kans.lon])).bindPopup(bouwPopup(kans));
      marker.addTo(markerLaag);
      markerPerId.set(kans.object_id, marker);
    } else {
      // Meerdere woningen op één plek: één telmarker met een keuzelijst. markerPerId
      // vullen we hier bewust niet; openWoning() valt dan terug op een losse popup,
      // zodat de lijst/zoekfunctie alsnog de juiste woning kan openen.
      const marker = L.marker([groep[0].lat, groep[0].lon], { icon: groepMarkerIcoon(groep) });
      marker.bindPopup(bouwGroepKeuze(groep));
      marker.addTo(markerLaag);
    }
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
      openWoning(kans);
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

// --- Snelzoeken op straatnaam (zweeft linksboven over de kaart) ---------------
// Typ (een deel van) een straatnaam; typefouten mogen. We tonen een korte lijst
// met alleen straat + huisnummer en springen bij een klik naar de woning op de
// kaart met het ballonnetje open. Fuzzy, zodat zowel "onies" (deel) als
// "mahonystraat" (typefout) de Mahoniestraat vinden.
const ZOEK_MAX_RESULTATEN = 15;

function normaliseerZoek(tekst) {
  return (tekst || "")
    .toLowerCase()
    .normalize("NFD").replace(/[̀-ͯ]/g, "") // accenten weg
    .replace(/[^a-z0-9 ]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

// "Mahoniestraat 15, Rotterdam" -> "Mahoniestraat 15" (stad weg voor weergave).
function straatHuisnummer(kans) {
  const naam = kans.weergavenaam || "";
  return (naam.split(",")[0] || naam).trim();
}

// Minimale edit-afstand om `zoek` ergens ín `doel` terug te vinden (benaderd
// substring-matchen): rij 0 blijft 0 zodat de match overal mag beginnen, en we
// nemen het minimum van de laatste rij zodat 'ie overal mag eindigen. Zo telt een
// deeltreffer ("onies") als afstand 0 en een typefout ("mahony") als afstand 1.
function fuzzyAfstand(zoek, doel) {
  const m = zoek.length, n = doel.length;
  if (m === 0) return 0;
  let vorige = new Array(n + 1).fill(0);
  for (let i = 1; i <= m; i++) {
    const huidige = new Array(n + 1);
    huidige[0] = i;
    for (let j = 1; j <= n; j++) {
      const kost = zoek[i - 1] === doel[j - 1] ? 0 : 1;
      huidige[j] = Math.min(vorige[j - 1] + kost, vorige[j] + 1, huidige[j - 1] + 1);
    }
    vorige = huidige;
  }
  return Math.min(...vorige);
}

function zoekWoningen(term) {
  const zoek = normaliseerZoek(term);
  if (!zoek) return [];
  // Hoe langer de zoekterm, hoe meer typefouten we toestaan.
  const drempel = zoek.length <= 4 ? 1 : Math.floor(zoek.length / 4) + 1;
  const treffers = [];
  for (const kans of alleKansen) {
    if (kans.lat == null || kans.lon == null) continue; // zonder plek niets om heen te vliegen
    const afstand = fuzzyAfstand(zoek, normaliseerZoek(straatHuisnummer(kans)));
    if (afstand <= drempel) treffers.push({ kans, afstand });
  }
  treffers.sort((a, b) => {
    if (a.afstand !== b.afstand) return a.afstand - b.afstand;
    return straatHuisnummer(a.kans).localeCompare(straatHuisnummer(b.kans), "nl", { numeric: true });
  });
  return treffers.slice(0, ZOEK_MAX_RESULTATEN).map((t) => t.kans);
}

function verbergZoekResultaten() {
  zoekResultatenEl.hidden = true;
  zoekResultatenEl.innerHTML = "";
}

function gaNaarWoning(kans) {
  verbergZoekResultaten();
  zoekInvoerEl.value = "";
  if (kans.lat != null && kans.lon != null) kaart.setView([kans.lat, kans.lon], 17);
  openWoning(kans);
  sluitZijbalk();
}

function toonZoekResultaten() {
  if (!zoekInvoerEl || !zoekResultatenEl) return;
  if (!normaliseerZoek(zoekInvoerEl.value)) { verbergZoekResultaten(); return; }
  const treffers = zoekWoningen(zoekInvoerEl.value);
  zoekResultatenEl.innerHTML = "";
  if (!treffers.length) {
    const leeg = document.createElement("li");
    leeg.className = "zoek-geen";
    leeg.textContent = "Geen woning gevonden";
    zoekResultatenEl.appendChild(leeg);
    zoekResultatenEl.hidden = false;
    return;
  }
  for (const kans of treffers) {
    const naam = straatHuisnummer(kans);
    // Straat vet, huisnummer grijs: splits op de eerste losse cijfergroep.
    const match = naam.match(/^(.*?)(\s+\d.*)?$/);
    const straat = (match && match[1] ? match[1] : naam).trim();
    const nr = match && match[2] ? match[2].trim() : "";
    const li = document.createElement("li");
    li.className = "zoek-resultaat";
    li.innerHTML = `<strong>${escapeHtml(straat)}</strong>${nr ? ` <span class="huisnr">${escapeHtml(nr)}</span>` : ""}`;
    li.addEventListener("click", () => gaNaarWoning(kans));
    zoekResultatenEl.appendChild(li);
  }
  zoekResultatenEl.hidden = false;
}

if (zoekInvoerEl) {
  zoekInvoerEl.addEventListener("input", toonZoekResultaten);
  zoekInvoerEl.addEventListener("focus", toonZoekResultaten);
  zoekInvoerEl.addEventListener("keydown", (e) => {
    // Android-toetsenbord stuurt tijdens woordcompositie/autocorrectie een pseudo-
    // Enter (isComposing / keyCode 229). Die NIET als "ga naar eerste resultaat"
    // behandelen: dat maakte het veld leeg + blurde 'm, waardoor het toetsenbord
    // telkens wegsprong zodra je verder wilde typen.
    if (e.isComposing || e.keyCode === 229) return;
    if (e.key === "Escape") {
      zoekInvoerEl.value = "";
      verbergZoekResultaten();
      zoekInvoerEl.blur();
    } else if (e.key === "Enter") {
      const eerste = zoekWoningen(zoekInvoerEl.value)[0];
      if (eerste) { e.preventDefault(); gaNaarWoning(eerste); }
    }
  });
  // Klik buiten de zoekbalk sluit de resultatenlijst.
  document.addEventListener("click", (e) => {
    const balk = document.getElementById("zoek-balk");
    if (balk && !balk.contains(e.target)) verbergZoekResultaten();
  });
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
  // Opgeslagen filters eenmalig toepassen - ná vulWijkFilter, zodat de bewaarde
  // wijk-keuze ook werkt (de wijk-opties bestaan dan pas), en vóór de eerste render.
  if (!_filtersToegepast) {
    _filtersToegepast = true;
    try { pasFiltersToe(await _opgeslagenFiltersPromise); } catch (e) { /* standaardfilters */ }
  }
  renderAlles();
}

// --- Vergunningenlaag (alle verleende kamerverhuurvergunningen, geclusterd) ---

const vergunningenLaag = L.markerClusterGroup
  ? L.markerClusterGroup({ chunkedLoading: true, maxClusterRadius: 50 })
  : L.layerGroup();
// Aparte laag voor de 50m-cirkels rond elke vergunning. Bewust NIET in de
// cluster-laag (die is voor punt-markers; echte meter-radius-cirkels horen daar
// niet in) maar in een losse laag die samen met de vergunningenlaag aan/uit gaat.
// Canvas-renderer: er kunnen honderden/duizenden vergunningen zijn, en zoveel
// SVG-paden maken pannen/zoomen traag; op canvas blijft het vloeiend.
const vergunningStralenLaag = L.layerGroup();
const stralenRenderer = L.canvas({ padding: 0.5 });
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
  vergunningStralenLaag.clearLayers();
  const toon3 = toon3kamerEl && toon3kamerEl.checked;
  const punten = vergunningenData.filter(
    (v) => v.lat != null && v.lon != null && (toon3 || !isDrieKamer(v))
  );
  const markers = punten.map((v) => {
    const drie = isDrieKamer(v);
    const stipKleur = drie ? "#00796b" : "#7b1fa2";
    // 50m-cirkel (de wettelijke norm-afstand) rond de vergunning, in dezelfde
    // kleur als de stip. Niet-interactief zodat een klik doorgaat naar de stip.
    L.circle([v.lat, v.lon], {
      radius: 50, // meter
      color: stipKleur,
      weight: 1,
      fillColor: stipKleur,
      fillOpacity: 0.08,
      interactive: false,
      renderer: stralenRenderer,
    }).addTo(vergunningStralenLaag);
    return L.circleMarker([v.lat, v.lon], {
      radius: drie ? 5 : 6,
      color: stipKleur,
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
      if (toonVergunningenEl.checked) {
        kaart.addLayer(vergunningStralenLaag);
        kaart.addLayer(vergunningenLaag);
      }
    } else {
      kaart.removeLayer(vergunningenLaag);
      kaart.removeLayer(vergunningStralenLaag);
    }
  });
}
if (toon3kamerEl) {
  toon3kamerEl.addEventListener("change", () => {
    if (vergunningenGeladen && toonVergunningenEl.checked) renderVergunningen();
  });
}

for (const el of [filterWijkEl, filterEigenInlegEl, filterSchakelgeldEl, filterWinstEl,
                  filterM2MinEl, filterM2MaxEl, filterPrijsM2MaxEl, filterZoekEl,
                  filterDagenEl, filterStadEl, filterInvesteerdersEl, filterSorteerEl]) {
  if (el) el.addEventListener("input", renderAlles);
}
for (const el of [filterStadEl, filterInvesteerdersEl, filterSorteerEl, filterWoningtypeEl]) {
  if (el) el.addEventListener("change", renderAlles);
}

// --- Filters onthouden per ingelogd account (server-side) ---
function verzamelFilters() {
  return {
    "toon-kansen": toonKansenEl ? toonKansenEl.checked : undefined,
    "toon-vergunningen": toonVergunningenEl ? toonVergunningenEl.checked : undefined,
    "toon-3kamer": toon3kamerEl ? toon3kamerEl.checked : undefined,
    "filter-stad": filterStadEl ? filterStadEl.value : undefined,
    "filter-wijk": filterWijkEl ? filterWijkEl.value : undefined,
    "filter-investeerders": filterInvesteerdersEl ? filterInvesteerdersEl.value : undefined,
    "filter-eigen-inleg": filterEigenInlegEl ? filterEigenInlegEl.value : undefined,
    "filter-schakelgeld": filterSchakelgeldEl ? filterSchakelgeldEl.value : undefined,
    "filter-winst": filterWinstEl ? filterWinstEl.value : undefined,
    "filter-m2-min": filterM2MinEl ? filterM2MinEl.value : undefined,
    "filter-m2-max": filterM2MaxEl ? filterM2MaxEl.value : undefined,
    "filter-prijs-m2-max": filterPrijsM2MaxEl ? filterPrijsM2MaxEl.value : undefined,
    "filter-woningtype": filterWoningtypeEl ? filterWoningtypeEl.value : undefined,
    "filter-zoek": filterZoekEl ? filterZoekEl.value : undefined,
    "filter-dagen": filterDagenEl ? filterDagenEl.value : undefined,
    "filter-sorteer": filterSorteerEl ? filterSorteerEl.value : undefined,
  };
}

function pasFiltersToe(f) {
  if (!f || typeof f !== "object") return;
  const zetWaarde = (el, v) => { if (el && v !== undefined && v !== null) el.value = v; };
  const zetCheck = (el, v) => { if (el && typeof v === "boolean") el.checked = v; };
  zetCheck(toonKansenEl, f["toon-kansen"]);
  zetCheck(toon3kamerEl, f["toon-3kamer"]);
  zetWaarde(filterStadEl, f["filter-stad"]);
  zetWaarde(filterWijkEl, f["filter-wijk"]);  // alleen effectief als de wijk-optie al bestaat
  zetWaarde(filterInvesteerdersEl, f["filter-investeerders"]);
  zetWaarde(filterEigenInlegEl, f["filter-eigen-inleg"]);
  zetWaarde(filterSchakelgeldEl, f["filter-schakelgeld"]);
  zetWaarde(filterWinstEl, f["filter-winst"]);
  zetWaarde(filterM2MinEl, f["filter-m2-min"]);
  zetWaarde(filterM2MaxEl, f["filter-m2-max"]);
  zetWaarde(filterPrijsM2MaxEl, f["filter-prijs-m2-max"]);
  zetWaarde(filterWoningtypeEl, f["filter-woningtype"]);
  zetWaarde(filterZoekEl, f["filter-zoek"]);
  zetWaarde(filterDagenEl, f["filter-dagen"]);
  zetWaarde(filterSorteerEl, f["filter-sorteer"]);
  // Vergunningenlaag apart: aanzetten triggert het laden van de laag.
  if (toonVergunningenEl && f["toon-vergunningen"] && !toonVergunningenEl.checked) {
    toonVergunningenEl.checked = true;
    toonVergunningenEl.dispatchEvent(new Event("change"));
  }
}

let _filtersOpslaanTimer = null;
function slaFiltersOp() {
  clearTimeout(_filtersOpslaanTimer);
  _filtersOpslaanTimer = setTimeout(() => {
    fetch("/api/filters", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(verzamelFilters()),
    }).catch(() => { /* stil: opslaan is best-effort */ });
  }, 400);
}

// Elke wijziging aan een filter opslaan (gedebounced).
for (const el of [toonKansenEl, toonVergunningenEl, toon3kamerEl, filterStadEl, filterWijkEl,
                  filterInvesteerdersEl, filterEigenInlegEl, filterSchakelgeldEl, filterWinstEl,
                  filterM2MinEl, filterM2MaxEl, filterPrijsM2MaxEl, filterWoningtypeEl,
                  filterZoekEl, filterDagenEl, filterSorteerEl]) {
  if (el) {
    el.addEventListener("input", slaFiltersOp);
    el.addEventListener("change", slaFiltersOp);
  }
}

// Opgeslagen filters eenmalig ophalen (bij het laden toegepast, zie laadKansen).
let _filtersToegepast = false;
const _opgeslagenFiltersPromise = fetch("/api/filters")
  .then((r) => (r.ok ? r.json() : null))
  .catch(() => null);

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

// --- Test-adressen: handmatig een groene 50m-cirkel op de kaart (beheerders) ---
// Om de kamerverhuurvergunning-afstandseis te testen: voeg een willekeurig adres
// toe (hoeft niet te koop te staan), er komt een groene 50m-cirkel omheen. Klik op
// het groene punt in het midden om het weer te verwijderen.

let testAdressen = [];

function renderTestAdressen() {
  testLaag.clearLayers();
  for (const t of testAdressen) {
    if (t.lat == null || t.lon == null) continue;
    L.circle([t.lat, t.lon], {
      radius: 50, // meter
      color: "#15803d",
      weight: 1.5,
      opacity: 0.85,
      fillColor: "#86efac",
      fillOpacity: 0.2,
      interactive: false, // klikken gaan naar het middenpunt eronder
    }).addTo(testLaag);

    const punt = L.circleMarker([t.lat, t.lon], {
      radius: 6,
      color: "#15803d",
      weight: 1,
      fillColor: "#22c55e",
      fillOpacity: 0.9,
    });
    const popup = document.createElement("div");
    popup.className = "popup-inhoud popup-test-adres";
    popup.innerHTML = `
      <span class="adres">${escapeHtml(t.weergavenaam || "test-adres")}</span>
      <span class="test-badge">test 50 m</span>
      <button type="button" class="popup-verwijder-knop">Verwijderen</button>
    `;
    popup.querySelector(".popup-verwijder-knop").addEventListener("click", () => {
      punt.closePopup();
      verwijderTestAdres(t.id);
    });
    punt.bindPopup(popup);
    punt.addTo(testLaag);
  }
}

async function laadTestAdressen() {
  try {
    const resp = await fetch("/api/test-adressen", { cache: "no-store" });
    if (!resp.ok) return;
    const data = await resp.json();
    testAdressen = data.adressen || [];
    renderTestAdressen();
  } catch (err) {
    /* stil: zonder test-adressen werkt de kaart gewoon */
  }
}

async function voegTestAdresToe() {
  const adres = (testAdresInvoerEl.value || "").trim();
  if (!adres) return;
  testAdresKnop.disabled = true;
  testAdresStatusEl.textContent = "Adres opzoeken...";
  try {
    const resp = await fetch("/api/test-adressen", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ adres }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      testAdresStatusEl.textContent = data.fout || "Toevoegen mislukt.";
      return;
    }
    const nieuw = data.adres;
    if (!testAdressen.some((t) => t.id === nieuw.id)) testAdressen.push(nieuw);
    renderTestAdressen();
    testAdresInvoerEl.value = "";
    testAdresStatusEl.textContent = `Toegevoegd: ${nieuw.weergavenaam}`;
    kaart.setView([nieuw.lat, nieuw.lon], 16);
  } catch (err) {
    testAdresStatusEl.textContent = "Toevoegen mislukt - probeer het nog eens.";
  } finally {
    testAdresKnop.disabled = false;
  }
}

async function verwijderTestAdres(id) {
  try {
    const resp = await fetch(`/api/test-adressen/${encodeURIComponent(id)}/verwijderen`, {
      method: "POST",
    });
    if (!resp.ok) throw new Error("verwijderen mislukt");
    testAdressen = testAdressen.filter((t) => t.id !== id);
    renderTestAdressen();
  } catch (err) {
    alert("Test-adres verwijderen is mislukt - probeer het nog eens.");
  }
}

if (testAdresKnop && testAdresInvoerEl) {
  testAdresKnop.addEventListener("click", voegTestAdresToe);
  testAdresInvoerEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); voegTestAdresToe(); }
  });
  laadTestAdressen();
}

// Opkoopbescherming-scan: adres -> alle adressen binnen 50 m scannen op WOZ
// boven/onder de grens; het resultaat wordt gemaild (de scan draait op de
// server in de achtergrond, dus hier alleen starten + de melding tonen).
async function startOpkoopScan() {
  const adres = (opkoopScanInvoerEl.value || "").trim();
  if (!adres) return;
  const ontvangers = opkoopScanOntvangersEl ? (opkoopScanOntvangersEl.value || "").trim() : "";
  opkoopScanKnop.disabled = true;
  opkoopScanStatusEl.textContent = "Scan starten...";
  try {
    const resp = await fetch("/opkoop-scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ adres, ontvangers }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      opkoopScanStatusEl.textContent = data.fout || "Scan starten mislukt.";
      return;
    }
    opkoopScanInvoerEl.value = "";
    opkoopScanStatusEl.textContent = data.melding || "Scan gestart; resultaat komt per mail.";
  } catch (err) {
    opkoopScanStatusEl.textContent = "Scan starten mislukt - probeer het nog eens.";
  } finally {
    opkoopScanKnop.disabled = false;
  }
}

if (opkoopScanKnop && opkoopScanInvoerEl) {
  opkoopScanKnop.addEventListener("click", startOpkoopScan);
  opkoopScanInvoerEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); startOpkoopScan(); }
  });
}

laadKansen();
