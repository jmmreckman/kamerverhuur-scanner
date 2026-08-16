const kaart = L.map("kaart", { zoomControl: false }).setView([51.9225, 4.47917], 12);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution: "&copy; OpenStreetMap-medewerkers",
  maxZoom: 19,
}).addTo(kaart);

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
const verversKnop = document.getElementById("ververs-knop");
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

function dagenOpFunda(eerstGezien) {
  if (!eerstGezien) return null;
  const start = new Date(eerstGezien);
  if (isNaN(start.getTime())) return null;
  const dagen = Math.floor((Date.now() - start.getTime()) / (1000 * 60 * 60 * 24));
  return dagen >= 0 ? dagen : null;
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
    <span class="adres">${kans.weergavenaam}</span>${isDenHaag ? ' <span class="stad-tag">Den Haag</span>' : ""}
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
    ${kans.woz_check_nodig ? '<span style="color:#b3261e">WOZ-waarde handmatig checken</span><br>' : ""}
    ${kans.woz_check_nodig && kans.woz_check_url ? `<a href="${kans.woz_check_url}" target="_blank" rel="noopener">Zelf WOZ-waarde opzoeken &rarr;</a><br>` : ""}
    ${signalen ? signalen + "<br>" : ""}
    ${kans.opmerking ? `<span style="color:#5f6368;font-size:0.9em">${kans.opmerking}</span><br>` : ""}
    <a href="/woning/${encodeURIComponent(kans.object_id)}/berekening" class="reken-link">Rekenen met deze woning &rarr;</a><br>
    <a href="${kans.url}" target="_blank" rel="noopener">Bekijk op Funda &rarr;</a>
  `;

  div.querySelector(".popup-verwijder-knop").addEventListener("click", () => verwijderKans(kans));

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

function renderMarkers(kansen) {
  markerLaag.clearLayers();
  markerPerId.clear();
  for (const kans of kansen) {
    const marker = L.marker([kans.lat, kans.lon]).bindPopup(bouwPopup(kans));
    marker.addTo(markerLaag);
    markerPerId.set(kans.object_id, marker);
  }
}

function renderLijst(kansen) {
  lijstEl.innerHTML = "";
  const gesorteerd = [...kansen].sort((a, b) => {
    const ea = perPersoon(a.eigen_inleg_na_ophoging_totaal);
    const eb = perPersoon(b.eigen_inleg_na_ophoging_totaal);
    if (ea === null) return 1;
    if (eb === null) return -1;
    return ea - eb;
  });
  for (const kans of gesorteerd) {
    const li = document.createElement("li");
    li.className = "lijst-item";
    const dagen = dagenOpFunda(kans.eerst_gezien);
    const c = kansCijfers(kans);
    li.innerHTML = `
      <button type="button" class="verwijder-knop" title="Verwijderen uit kansenlijst">&times;</button>
      <span class="adres">${kans.weergavenaam}</span>
      ${kans.stad === "den_haag" ? '<span class="stad-tag">Den Haag</span>' : ""}
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
    lijstEl.appendChild(li);
  }
  aantalTekstEl.textContent = `${kansen.length} van ${alleKansen.length} kansen`;
}

function renderAlles() {
  const kansen = gefilterd();
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

for (const el of [filterWijkEl, filterEigenInlegEl, filterSchakelgeldEl, filterWinstEl, filterZoekEl,
                  filterDagenEl, filterStadEl, filterInvesteerdersEl]) {
  if (el) el.addEventListener("input", renderAlles);
}
for (const el of [filterStadEl, filterInvesteerdersEl]) {
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

laadKansen();
