"use strict";
// WWSO-rekentool: verzamelt de invoer, vraagt de puntentelling op bij de server
// en toont per kamer de maximale kale huur. "Gebruik" zet de gemiddelde huur als
// kale huur per kamer in de investerings-rekentool van deze woning.

const RUBRIEK_LABELS = {
  oppervlakte: "Oppervlakte (vertrek + overige)",
  verwarming: "Verwarming",
  energie: "Energieprestatie",
  keuken: "Keuken",
  sanitair: "Sanitair",
  buitenruimte: "Buitenruimte",
  woz: "WOZ-waarde",
};

function euro(bedrag) {
  return "€ " + Number(bedrag).toLocaleString("nl-NL", {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  });
}

function bouwKamerRijen() {
  const container = document.getElementById("kamer-rijen");
  const aantalInput = document.getElementById("aantal-kamers");
  const standaardM2 = container.dataset.kamerM2 || "";
  let aantal = parseInt(aantalInput.value, 10);
  if (!Number.isFinite(aantal) || aantal < 1) aantal = 1;
  if (aantal > 40) aantal = 40;

  // Bewaar bestaande ingevulde m²-waarden zodat herbouwen niets wist.
  const bestaand = Array.from(container.querySelectorAll(".kamer-m2")).map((i) => i.value);
  container.innerHTML = "";
  for (let n = 0; n < aantal; n++) {
    const rij = document.createElement("div");
    rij.className = "kamer-rij";
    const waarde = bestaand[n] !== undefined ? bestaand[n] : standaardM2;
    rij.innerHTML =
      '<span class="kamer-nr">Kamer ' + (n + 1) + '</span>' +
      '<span class="reken-invoer"><input type="number" class="kamer-m2" step="any" ' +
      'min="0" inputmode="decimal" value="' + waarde + '"><span class="teken">m²</span></span>' +
      '<label class="wwso-check wwso-inline"><input type="checkbox" class="kamer-verwarmd" checked> verwarmd</label>';
    container.appendChild(rij);
  }
}

function verzamelPayload() {
  const num = (sel) => document.querySelector(sel).value;
  const kamers = Array.from(document.querySelectorAll(".kamer-rij")).map((rij) => ({
    oppervlakte_m2: rij.querySelector(".kamer-m2").value,
    verwarmd: rij.querySelector(".kamer-verwarmd").checked,
  }));

  const keukenVoorz = Array.from(document.querySelectorAll(".keuken-voorz:checked")).map((c) => c.value);
  const sanitairVoorz = Array.from(document.querySelectorAll(".sanitair-voorz:checked")).map((c) => c.value);

  const gedeeldeRuimten = [];
  const woonkamer = num('input[name="woonkamer_m2"]');
  if (parseFloat(woonkamer) > 0) {
    gedeeldeRuimten.push({
      oppervlakte_m2: woonkamer, is_vertrek: true,
      verwarmd: document.getElementById("woonkamer_verwarmd").checked,
      aantal_adressen: num('input[name="aantal_adressen"]'),
    });
  }
  const berging = num('input[name="berging_m2"]');
  if (parseFloat(berging) > 0) {
    gedeeldeRuimten.push({
      oppervlakte_m2: berging, is_vertrek: false, verwarmd: false,
      aantal_adressen: num('input[name="aantal_adressen"]'),
    });
  }

  return {
    kamers,
    energielabel: num("#energielabel"),
    bouwjaar: num('input[name="bouwjaar"]'),
    woz_waarde: num('input[name="woz_waarde"]'),
    woz_oppervlakte_m2: num('input[name="woz_oppervlakte_m2"]'),
    corop_gemiddelde_woz_m2: num('input[name="corop_gemiddelde_woz_m2"]'),
    keuken: {
      aanrecht_m: num("#aanrecht_m"),
      voorzieningen: keukenVoorz,
      extra_kastruimte_60cm: num('input[name="extra_kastruimte_60cm"]'),
    },
    sanitair: { voorzieningen: sanitairVoorz },
    gedeelde_ruimten: gedeeldeRuimten,
    gemeenschappelijke_buitenruimte: {
      oppervlakte_m2: num('input[name="buitenruimte_m2"]'),
      aantal_adressen: num('input[name="aantal_adressen"]'),
    },
  };
}

let laatsteGemiddelde = null;

async function bereken() {
  const foutEl = document.getElementById("wwso-fout");
  const resEl = document.getElementById("wwso-resultaat");
  foutEl.hidden = true;
  try {
    const resp = await fetch(window.__wwso.berekenUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(verzamelPayload()),
    });
    const data = await resp.json();
    if (!resp.ok) {
      foutEl.textContent = data.fout || "Er ging iets mis bij het rekenen.";
      foutEl.hidden = false;
      resEl.hidden = true;
      return;
    }
    toonResultaat(data);
  } catch (e) {
    foutEl.textContent = "Netwerkfout - probeer opnieuw.";
    foutEl.hidden = false;
  }
}

function toonResultaat(data) {
  laatsteGemiddelde = data.gemiddelde_huur;
  document.querySelector('[data-veld="gemiddelde_huur"]').textContent = euro(data.gemiddelde_huur);
  document.querySelector('[data-veld="laagste_huur"]').textContent = euro(data.laagste_huur);
  document.querySelector('[data-veld="totaal_huur"]').textContent = euro(data.totaal_huur);

  const tbody = document.querySelector("#wwso-kamer-tabel tbody");
  tbody.innerHTML = "";
  data.kamers.forEach((k, n) => {
    const tr = document.createElement("tr");
    tr.innerHTML =
      "<td>Kamer " + (n + 1) + "</td>" +
      "<td>" + k.oppervlakte_m2 + " m²</td>" +
      "<td>" + k.totaal_punten + "</td>" +
      "<td>" + euro(k.max_kale_huur) + "</td>";
    tbody.appendChild(tr);
  });

  const rub = document.querySelector("#wwso-rubriek-tabel tbody");
  rub.innerHTML = "";
  const eerste = data.kamers[0];
  if (eerste) {
    Object.keys(RUBRIEK_LABELS).forEach((key) => {
      const punten = eerste.punten_per_rubriek[key];
      if (punten === undefined) return;
      const tr = document.createElement("tr");
      tr.innerHTML = "<td>" + RUBRIEK_LABELS[key] + "</td><td>" +
        Number(punten).toLocaleString("nl-NL") + " pt</td>";
      rub.appendChild(tr);
    });
    const totaal = document.createElement("tr");
    totaal.className = "groot";
    totaal.innerHTML = "<td>Totaal (afgerond)</td><td>" + eerste.totaal_punten + " pt</td>";
    rub.appendChild(totaal);
  }

  document.getElementById("wwso-resultaat").hidden = false;
}

async function gebruik() {
  if (laatsteGemiddelde == null) return;
  const btn = document.getElementById("wwso-gebruik");
  btn.disabled = true;
  try {
    const resp = await fetch(window.__wwso.gebruikUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kale_huur_per_kamer: laatsteGemiddelde }),
    });
    const data = await resp.json();
    if (resp.ok && data.url) {
      window.location.href = data.url;
    } else {
      btn.disabled = false;
    }
  } catch (e) {
    btn.disabled = false;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  bouwKamerRijen();
  document.getElementById("aantal-kamers").addEventListener("input", bouwKamerRijen);
  document.getElementById("wwso-bereken").addEventListener("click", bereken);
  document.getElementById("wwso-gebruik").addEventListener("click", gebruik);
});
