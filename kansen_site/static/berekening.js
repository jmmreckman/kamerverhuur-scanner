// Rekentool per woning: links pas je de uitgangspunten aan, rechts rollen de
// sommen eruit. Elke wijziging wordt (debounced) naar de server gestuurd, die de
// waarden bij de woning bewaart en de doorgerekende resultaten terugstuurt.

const layout = document.querySelector(".reken-layout");
const objectId = window.__objectId;
const form = document.getElementById("reken-form");
const statusEl = document.getElementById("opslag-status");

const EURO_MET_CENTEN = new Intl.NumberFormat("nl-NL", {
  style: "currency",
  currency: "EUR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

function formatEuro(bedrag) {
  if (bedrag === null || bedrag === undefined) return "—";
  return EURO_MET_CENTEN.format(bedrag);
}

function formatRendement(fractie) {
  if (fractie === null || fractie === undefined) return "—";
  return (fractie * 100).toLocaleString("nl-NL", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }) + "%";
}

function renderResultaat(res) {
  for (const cel of document.querySelectorAll("[data-veld]")) {
    const veld = cel.dataset.veld;
    cel.textContent = veld === "rendement" ? formatRendement(res[veld]) : formatEuro(res[veld]);
  }
}

function verzamelInvoer() {
  const data = {};
  for (const input of form.elements) {
    if (input.name) data[input.name] = input.value;
  }
  return data;
}

let timer = null;
let bezig = false;

async function opslaan() {
  bezig = true;
  statusEl.textContent = "Opslaan…";
  try {
    const resp = await fetch(`/woning/${encodeURIComponent(objectId)}/berekening`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(verzamelInvoer()),
    });
    if (!resp.ok) throw new Error("opslaan mislukt");
    const res = await resp.json();
    renderResultaat(res);
    statusEl.textContent = "Opgeslagen ✓";
  } catch (err) {
    statusEl.textContent = "Opslaan mislukt — probeer het nog eens.";
  } finally {
    bezig = false;
  }
}

function planOpslaan() {
  statusEl.textContent = "Wijzigingen…";
  if (timer) clearTimeout(timer);
  timer = setTimeout(opslaan, 400);
}

form.addEventListener("input", planOpslaan);

renderResultaat(window.__resultaat);
