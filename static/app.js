const todayIso = new Date().toISOString().slice(0, 10);
document.getElementById("entry-date").value = todayIso;

const statusEl = document.getElementById("save-status");
const form = document.getElementById("weight-form");

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const dateVal = document.getElementById("entry-date").value;
  const weightVal = parseFloat(document.getElementById("entry-weight").value);
  statusEl.textContent = "Opslaan...";
  statusEl.className = "status";
  try {
    const res = await fetch("/api/weight", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ date: dateVal, weight: weightVal }),
    });
    if (!res.ok) throw new Error((await res.json()).detail || "Opslaan mislukt");
    statusEl.textContent = "Opgeslagen. Grafieken bijgewerkt.";
    statusEl.className = "status ok";
    document.getElementById("entry-weight").value = "";
    refreshActiveView();
  } catch (err) {
    statusEl.textContent = err.message;
    statusEl.className = "status error";
  }
});

const viewButtons = document.querySelectorAll(".buttons button");
const views = {
  all: document.getElementById("view-all"),
  yearly: document.getElementById("view-yearly"),
  compare: document.getElementById("view-compare"),
  averages: document.getElementById("view-averages"),
};
let activeView = null;
let chartAll = null;
let chartYearly = null;

viewButtons.forEach((btn) => {
  btn.addEventListener("click", () => showView(btn.dataset.view));
});

function showView(name) {
  activeView = name;
  viewButtons.forEach((b) => b.classList.toggle("active", b.dataset.view === name));
  Object.entries(views).forEach(([key, el]) => el.classList.toggle("hidden", key !== name));
  refreshActiveView();
}

function refreshActiveView() {
  if (activeView === "all") loadChartAll();
  if (activeView === "yearly") loadChartYearly();
  if (activeView === "compare") loadCompare();
  if (activeView === "averages") loadAverages();
}

const YEAR_COLORS = (year, allYears) => {
  const idx = allYears.indexOf(year);
  const hue = Math.round((idx * 360) / Math.max(allYears.length, 1));
  return `hsl(${hue}, 70%, 55%)`;
};

let cachedAllData = null;
let selectedRangeDays = "all";

const rangeButtons = document.querySelectorAll("#range-buttons button");
rangeButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    selectedRangeDays = btn.dataset.range;
    rangeButtons.forEach((b) => b.classList.toggle("active", b === btn));
    renderChartAll();
  });
});
rangeButtons[rangeButtons.length - 1].classList.add("active");

async function loadChartAll() {
  cachedAllData = await (await fetch("/api/chart/all")).json();
  renderChartAll();
}

function renderChartAll() {
  if (!cachedAllData) return;
  let data = cachedAllData;
  if (selectedRangeDays !== "all") {
    const cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - Number(selectedRangeDays));
    const cutoffIso = cutoff.toISOString().slice(0, 10);
    data = cachedAllData.filter((d) => d.date >= cutoffIso);
  }

  const ctx = document.getElementById("chart-all");
  if (chartAll) chartAll.destroy();
  chartAll = new Chart(ctx, {
    type: "line",
    data: {
      labels: data.map((d) => d.date),
      datasets: [
        {
          label: "Gewicht (kg)",
          data: data.map((d) => d.weight),
          borderColor: "#2f6fed",
          borderWidth: 1.5,
          pointRadius: 0,
          tension: 0,
        },
      ],
    },
    options: {
      animation: false,
      maintainAspectRatio: false,
      scales: {
        x: { ticks: { maxTicksLimit: 12 }, grid: { color: "#2a2f38" } },
        y: { grid: { color: "#2a2f38" } },
      },
      plugins: { legend: { display: false } },
    },
  });
}

async function loadChartYearly() {
  const seriesByYear = await (await fetch("/api/chart/yearly")).json();
  const years = Object.keys(seriesByYear).map(Number).sort((a, b) => a - b);
  const ctx = document.getElementById("chart-yearly");
  if (chartYearly) chartYearly.destroy();

  const allWeights = years.flatMap((year) => seriesByYear[year].map((p) => p.weight));
  const dataMin = Math.min(...allWeights);
  const dataMax = Math.max(...allWeights);
  const padding = Math.max((dataMax - dataMin) * 0.05, 0.5);

  chartYearly = new Chart(ctx, {
    type: "line",
    data: {
      datasets: years.map((year) => ({
        label: String(year),
        data: seriesByYear[year].map((p) => ({ x: p.day_of_year, y: p.weight })),
        borderColor: YEAR_COLORS(year, years),
        borderWidth: 1.5,
        pointRadius: 0,
        tension: 0,
        parsing: false,
      })),
    },
    options: {
      animation: false,
      maintainAspectRatio: false,
      scales: {
        x: {
          type: "linear",
          min: 1,
          max: 366,
          ticks: {
            callback: (value) => dayOfYearToLabel(value),
            stepSize: 30,
          },
          grid: { color: "#2a2f38" },
        },
        y: {
          min: Math.floor(dataMin - padding),
          max: Math.ceil(dataMax + padding),
          grid: { color: "#2a2f38" },
        },
      },
      plugins: { legend: { position: "bottom", labels: { boxWidth: 12 } } },
    },
  });
}

function dayOfYearToLabel(day) {
  const d = new Date(2023, 0, 1);
  d.setDate(day);
  return d.toLocaleDateString("nl-NL", { day: "numeric", month: "short" });
}

async function loadCompare() {
  const data = await (await fetch("/api/compare")).json();
  const heading = document.getElementById("compare-heading");
  const tbody = document.querySelector("#compare-table tbody");
  tbody.innerHTML = "";

  if (!data.today) {
    heading.textContent = "Nog geen data om te vergelijken.";
    return;
  }

  heading.textContent = `Vandaag (${data.today.date}): ${data.today.weight} kg`;

  const streakEl = document.getElementById("compare-streak");
  if (data.last_lighter_or_equal) {
    const l = data.last_lighter_or_equal;
    streakEl.textContent = `Je was voor het laatst zo licht (of lichter) op ${l.date} (${l.weight} kg) — dat is ${l.days_ago} dagen geleden.`;
  } else {
    streakEl.textContent = "Dit is het laagste gewicht dat je ooit gemeten hebt sinds het begin van je data!";
  }

  if (data.comparisons.length === 0) {
    const row = document.createElement("tr");
    row.innerHTML = `<td colspan="4">Nog geen data van andere jaren op deze datum.</td>`;
    tbody.appendChild(row);
    return;
  }

  data.comparisons.forEach((c) => {
    const row = document.createElement("tr");
    const diffLabel =
      c.verdict === "lichter_nu"
        ? `${Math.abs(c.diff_vs_today)} kg lichter nu`
        : c.verdict === "zwaarder_nu"
        ? `${Math.abs(c.diff_vs_today)} kg zwaarder nu`
        : "gelijk";
    const cellClass = c.verdict === "lichter_nu" ? "lighter" : c.verdict === "zwaarder_nu" ? "heavier" : "";
    row.innerHTML = `
      <td>${c.year}</td>
      <td>${c.date}${c.is_estimate ? " (geschat)" : ""}</td>
      <td>${c.weight} kg</td>
      <td class="${cellClass}">${diffLabel}</td>
    `;
    tbody.appendChild(row);
  });
}

async function loadAverages() {
  const data = await (await fetch("/api/averages")).json();
  const tbody = document.querySelector("#averages-table tbody");
  tbody.innerHTML = "";

  if (!data.today) return;

  data.periods.forEach((p) => {
    const row = document.createElement("tr");
    const lighterNu = p.diff < 0;
    const diffLabel = p.diff < 0
      ? `${Math.abs(p.diff)} kg lichter nu`
      : p.diff > 0
      ? `${Math.abs(p.diff)} kg zwaarder nu`
      : "gelijk";
    const cellClass = lighterNu ? "lighter" : p.diff > 0 ? "heavier" : "";
    row.innerHTML = `
      <td>${p.label}</td>
      <td>${p.average} kg</td>
      <td class="${cellClass}">${diffLabel}</td>
    `;
    tbody.appendChild(row);
  });
}

showView("all");
