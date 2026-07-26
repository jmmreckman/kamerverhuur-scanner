const kaart = L.map("kaart").setView([51.9225, 4.47917], 12);
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
  const minWinst = parseFloat(filterWinstEl.value);
  const zoek = filterZoekEl.value.trim().toLowerCase();

  return alleKansen.filter((k) => {
    if (wijk && k.wijknaam !== wijk) return false;
    if (!isNaN(maxEigenInleg) && (k.eigen_inleg_pp === null || k.eigen_inleg_pp > maxEigenInleg)) return false;
    if (!isNaN(minWinst) && (k.winst_pm_pp === null || k.winst_pm_pp < minWinst)) return false;
    if (zoek && !k.weergavenaam.toLowerCase().includes(zoek)) return false;
    return true;
  });
}

function bouwPopup(kans) {
  const div = document.createElement("div");
  div.className = "popup-inhoud";
  const dagen = dagenOpFunda(kans.eerst_gezien);
  const kamersWaarde = kans.aantal_kamers_mogelijk === null || kans.aantal_kamers_mogelijk === undefined ? "" : kans.aantal_kamers_mogelijk;
  div.innerHTML = `
    <button type="button" class="verwijder-knop popup-verwijder-knop" title="Verwijderen uit kansenlijst">&times;</button>
    <span class="adres">${kans.weergavenaam}</span>
    ${kans.wijknaam ? kans.wijknaam + "<br>" : ""}
    Vraagprijs: ${formatEuro(kans.prijs)}<br>
    ${kans.primaire_oppervlakte ? kans.primaire_oppervlakte + " m²<br>" : ""}
    ${kans.bag_oppervlakte && kans.bag_oppervlakte !== kans.primaire_oppervlakte ? kans.bag_oppervlakte + " m² (BAG, ter info)<br>" : ""}
    <span class="kamers-editor">
      Kamers mogelijk: <input type="number" class="kamers-input" min="0" step="1" inputmode="numeric" value="${kamersWaarde}">
      ${kans.aantal_kamers_handmatig ? '<button type="button" class="kamers-reset-knop" title="Terug naar automatisch berekend (18m²-regel)">automatisch</button>' : ""}
    </span><br>
    ${kans.winst_pm_pp !== null ? "Winst p.p./mnd: " + formatEuro(kans.winst_pm_pp) + "<br>" : ""}
    ${kans.eigen_inleg_pp !== null ? "Eigen inleg p.p.: " + formatEuro(kans.eigen_inleg_pp) + "<br>" : ""}
    ${dagen !== null ? dagen + " dag(en) op Funda<br>" : ""}
    ${kans.woz_check_nodig ? '<span style="color:#b3261e">WOZ-waarde handmatig checken</span><br>' : ""}
    ${kans.woz_check_nodig && kans.woz_check_url ? `<a href="${kans.woz_check_url}" target="_blank" rel="noopener">Zelf WOZ-waarde opzoeken &rarr;</a><br>` : ""}
    ${kans.opmerking ? `<span style="color:#5f6368;font-size:0.9em">${kans.opmerking}</span><br>` : ""}
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
    if (a.eigen_inleg_pp === null) return 1;
    if (b.eigen_inleg_pp === null) return -1;
    return a.eigen_inleg_pp - b.eigen_inleg_pp;
  });
  for (const kans of gesorteerd) {
    const li = document.createElement("li");
    li.className = "lijst-item";
    const dagen = dagenOpFunda(kans.eerst_gezien);
    li.innerHTML = `
      <button type="button" class="verwijder-knop" title="Verwijderen uit kansenlijst">&times;</button>
      <span class="adres">${kans.weergavenaam}</span>
      <div class="cijfers">
        <span>${formatEuro(kans.prijs)}</span>
        ${kans.winst_pm_pp !== null ? `<span class="goed">+${formatEuro(kans.winst_pm_pp)} p.p./mnd</span>` : ""}
        ${kans.eigen_inleg_pp !== null ? `<span>${formatEuro(kans.eigen_inleg_pp)} inleg p.p.</span>` : ""}
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

for (const el of [filterWijkEl, filterEigenInlegEl, filterWinstEl, filterZoekEl]) {
  el.addEventListener("input", renderAlles);
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
