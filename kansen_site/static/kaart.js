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
const sweepKnop = document.getElementById("sweep-knop");
const zijbalkEl = document.getElementById("zijbalk");
const zijbalkKnop = document.getElementById("zijbalk-knop");
const zijbalkSluitenKnop = document.getElementById("zijbalk-sluiten-knop");

let alleKansen = [];
const markerPerId = new Map();

function formatEuro(bedrag) {
  if (bedrag === null || bedrag === undefined) return "onbekend";
  return "€" + Math.round(bedrag).toLocaleString("nl-NL");
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
  div.innerHTML = `
    <span class="adres">${kans.weergavenaam}</span>
    ${kans.wijknaam ? kans.wijknaam + "<br>" : ""}
    Vraagprijs: ${formatEuro(kans.prijs)}<br>
    ${kans.bag_oppervlakte ? kans.bag_oppervlakte + " m²<br>" : ""}
    ${kans.aantal_kamers_mogelijk ? kans.aantal_kamers_mogelijk + " kamer(s) mogelijk<br>" : ""}
    ${kans.winst_pm_pp !== null ? "Winst p.p./mnd: " + formatEuro(kans.winst_pm_pp) + "<br>" : ""}
    ${kans.eigen_inleg_pp !== null ? "Eigen inleg p.p.: " + formatEuro(kans.eigen_inleg_pp) + "<br>" : ""}
    ${kans.woz_check_nodig ? '<span style="color:#b3261e">WOZ-waarde handmatig checken</span><br>' : ""}
    <a href="${kans.url}" target="_blank" rel="noopener">Bekijk op Funda &rarr;</a>
  `;
  return div;
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
    li.innerHTML = `
      <button type="button" class="verwijder-knop" title="Verwijderen uit kansenlijst">&times;</button>
      <span class="adres">${kans.weergavenaam}</span>
      <div class="cijfers">
        <span>${formatEuro(kans.prijs)}</span>
        ${kans.winst_pm_pp !== null ? `<span class="goed">+${formatEuro(kans.winst_pm_pp)} p.p./mnd</span>` : ""}
        ${kans.eigen_inleg_pp !== null ? `<span>${formatEuro(kans.eigen_inleg_pp)} inleg p.p.</span>` : ""}
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

const SWEEP_POLL_INTERVAL_MS = 15000;

// De sweep draait server-side in een achtergrondthread, losgekoppeld van
// deze fetch-verbindingen - een mobiele browser onderbreekt een lang
// openstaande fetch() al snel zodra het tabblad naar de achtergrond gaat
// (bv. om de Apify-billing te checken), dus we pollen periodiek i.p.v. op
// één doorlopende aanvraag te wachten. Werkt daarom ook prima als je
// tussentijds herlaadt of het tabblad sluit en later teruggaat.
async function pollSweepStatus() {
  try {
    const resp = await fetch("/sweep/status");
    const data = await resp.json();

    if (data.status === "bezig") {
      sweepKnop.disabled = true;
      statusTekstEl.textContent =
        "Bezig met totale sweep (kan lang duren - dit tabblad mag gerust op de achtergrond staan of dicht, de voortgang wordt gewoon bijgehouden)...";
      setTimeout(pollSweepStatus, SWEEP_POLL_INTERVAL_MS);
      return;
    }

    sweepKnop.disabled = false;
    if (data.status === "klaar") {
      statusTekstEl.textContent = `Sweep klaar: ${data.nieuw_actief} nieuwe kans(en), ${data.nieuw_afgevallen} afgevallen.`;
      if (data.fouten && data.fouten.length) {
        statusTekstEl.textContent += ` Waarschuwing: ${data.fouten.join(" | ")}`;
      }
      await laadKansen();
    } else if (data.status === "mislukt") {
      statusTekstEl.textContent = "Totale sweep mislukt.";
      if (data.fouten && data.fouten.length) {
        statusTekstEl.textContent += ` ${data.fouten.join(" | ")}`;
      }
    }
  } catch (err) {
    // Netwerkfout tijdens het pollen zelf - de sweep loopt intussen gewoon
    // door op de server, dus straks nog eens proberen i.p.v. opgeven.
    setTimeout(pollSweepStatus, SWEEP_POLL_INTERVAL_MS);
  }
}

sweepKnop.addEventListener("click", async () => {
  const maxItems = sweepKnop.dataset.maxItems;
  const maxKosten = parseFloat(sweepKnop.dataset.maxKosten);
  const maxKostenEuro = (maxKosten * 0.92).toFixed(2);
  const bevestigd = window.confirm(
    `Dit haalt een VOLLEDIGE Apify-scan op (tot max. ${maxItems} resultaten in totaal, over al je zoekopdrachten samen) - dit kan geld kosten.\n\n` +
    `Bij het maximum ca. $${maxKosten.toFixed(2)} (~€${maxKostenEuro}), meestal minder omdat er vaak minder dan het maximum aan resultaten binnenkomt.\n\n` +
    "Wil je doorgaan met de totale sweep?"
  );
  if (!bevestigd) return;

  sweepKnop.disabled = true;
  statusTekstEl.textContent = "Totale sweep starten...";
  try {
    const resp = await fetch("/sweep", { method: "POST" });
    const data = await resp.json();
    if (data.fout) {
      statusTekstEl.textContent = data.fout;
      sweepKnop.disabled = false;
    } else {
      pollSweepStatus();
    }
  } catch (err) {
    statusTekstEl.textContent = "Totale sweep starten is mislukt - probeer het nog eens.";
    sweepKnop.disabled = false;
  }
});

// Bij het laden van de pagina meteen checken of er al een sweep bezig is
// (bv. gestart vanuit een ander tabblad, of vóór een pagina-herlaad) en dan
// meteen verder pollen. Toont bewust niets als er geen sweep bezig is - het
// resultaat van een oude sweep hoeft niet op elke pagina-herlaad terug te
// komen, "Ververs nu" en de kansenlijst zelf zijn dan leidend.
(async () => {
  try {
    const resp = await fetch("/sweep/status");
    const data = await resp.json();
    if (data.status === "bezig") pollSweepStatus();
  } catch (err) {
    // Best-effort - als dit mislukt, kan de gebruiker gewoon zelf op de knop klikken.
  }
})();

laadKansen();
