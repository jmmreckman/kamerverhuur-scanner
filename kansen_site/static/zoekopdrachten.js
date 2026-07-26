const testStatusTekstEl = document.getElementById("test-status-tekst");
const testKnoppen = document.querySelectorAll(".test-knop");

const SWEEP_POLL_INTERVAL_MS = 15000;

// Zelfde achtergrondtaak-mechaniek als "Totale sweep" op de kaartpagina
// (server-side achtergrondthread + /sweep/status pollen) - een test van één
// zoekopdracht duurt weliswaar meestal korter, maar kan bij een trage
// Apify-scrape ook een paar minuten kosten, en een mobiele browser
// onderbreekt een lang openstaande fetch() al snel zodra het tabblad naar de
// achtergrond gaat.
function zetKnoppenUit(uit) {
  for (const knop of testKnoppen) knop.disabled = uit;
}

async function pollTestStatus() {
  try {
    const resp = await fetch("/sweep/status");
    const data = await resp.json();

    if (data.status === "bezig") {
      zetKnoppenUit(true);
      const welke = data.url ? `zoekopdracht (${data.url})` : "Apify-taak";
      testStatusTekstEl.textContent =
        `Bezig met het testen van deze ${welke} - dit tabblad mag gerust op de achtergrond staan of dicht...`;
      setTimeout(pollTestStatus, SWEEP_POLL_INTERVAL_MS);
      return;
    }

    zetKnoppenUit(false);
    if (data.status === "klaar") {
      testStatusTekstEl.textContent = `Test klaar: ${data.nieuw_actief} nieuwe kans(en), ${data.nieuw_afgevallen} afgevallen.`;
      if (data.fouten && data.fouten.length) {
        testStatusTekstEl.textContent += ` Waarschuwing: ${data.fouten.join(" | ")}`;
      }
    } else if (data.status === "mislukt") {
      testStatusTekstEl.textContent = "Test mislukt.";
      if (data.fouten && data.fouten.length) {
        testStatusTekstEl.textContent += ` ${data.fouten.join(" | ")}`;
      }
    }
  } catch (err) {
    setTimeout(pollTestStatus, SWEEP_POLL_INTERVAL_MS);
  }
}

for (const knop of testKnoppen) {
  knop.addEventListener("click", async () => {
    const url = knop.dataset.url;
    zetKnoppenUit(true);
    testStatusTekstEl.textContent = "Test starten...";
    try {
      const body = new URLSearchParams();
      body.set("url", url);
      const resp = await fetch("/zoekopdrachten/testen", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body,
      });
      const data = await resp.json();
      if (data.fout) {
        testStatusTekstEl.textContent = data.fout;
        zetKnoppenUit(false);
      } else {
        pollTestStatus();
      }
    } catch (err) {
      testStatusTekstEl.textContent = "Test starten is mislukt - probeer het nog eens.";
      zetKnoppenUit(false);
    }
  });
}

// Bij het laden van de pagina meteen checken of er al een Apify-taak bezig
// is (bv. gestart vanaf de kaartpagina, of vóór een pagina-herlaad hier) en
// dan meteen verder pollen.
(async () => {
  try {
    const resp = await fetch("/sweep/status");
    const data = await resp.json();
    if (data.status === "bezig") pollTestStatus();
  } catch (err) {
    // Best-effort - als dit mislukt, kan de gebruiker gewoon zelf op Testen klikken.
  }
})();
