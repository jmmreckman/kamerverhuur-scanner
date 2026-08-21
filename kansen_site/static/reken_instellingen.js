// Globale reken-instellingen: dezelfde BAR-rente-koppeling als de per-woning
// rekentool (ΔBAR = LTV × Δrente), maar hier zonder auto-opslag — je slaat op met
// de knop "Opslaan voor alle panden".
const form = document.getElementById("reken-instellingen-form");

if (form) {
  const renteInput = form.querySelector('[name="rente"]');
  const barInput = form.querySelector('[name="bar"]');
  const ltvInput = form.querySelector('[name="ltv"]');

  if (renteInput && barInput) {
    let vorigeRente = parseFloat(renteInput.value);
    renteInput.addEventListener("input", () => {
      const renteNieuw = parseFloat(renteInput.value);
      if (isNaN(renteNieuw)) return;
      const bar = parseFloat(barInput.value);
      const ltv = ltvInput ? parseFloat(ltvInput.value) : NaN;
      const factor = isNaN(ltv) ? 0.8 : ltv / 100;
      if (!isNaN(vorigeRente) && !isNaN(bar)) {
        barInput.value = String(Math.round((bar + factor * (renteNieuw - vorigeRente)) * 100) / 100);
      }
      vorigeRente = renteNieuw;
    });
  }
}
