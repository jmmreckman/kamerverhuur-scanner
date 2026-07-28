const testStatusTekstEl = document.getElementById("test-status-tekst");
const testKnoppen = document.querySelectorAll(".test-knop");

function zetKnoppenUit(uit) {
  for (const knop of testKnoppen) knop.disabled = uit;
}

for (const knop of testKnoppen) {
  knop.addEventListener("click", async () => {
    const url = knop.dataset.url;
    zetKnoppenUit(true);
    testStatusTekstEl.textContent = "Bezig met testen (een paar seconden)...";
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
      } else {
        testStatusTekstEl.textContent = `${data.aantal} woning(en) herkend${data.adressen.length ? ": " + data.adressen.join(", ") : ""}.`;
        if (data.fouten && data.fouten.length) {
          testStatusTekstEl.textContent += ` Waarschuwing: ${data.fouten.join(" | ")}`;
        }
      }
    } catch (err) {
      testStatusTekstEl.textContent = "Test starten is mislukt - probeer het nog eens.";
    } finally {
      zetKnoppenUit(false);
    }
  });
}
