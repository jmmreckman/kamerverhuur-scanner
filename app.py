"""Gewicht-tracker webapp.

Draait lokaal op je thuisnetwerk. Start met run.bat (Windows) of
`uvicorn app:app --host 0.0.0.0 --port 8420`, en open dan vanaf je
telefoon (zelfde wifi) http://<ip-van-deze-pc>:8420
"""
from datetime import date

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import db

app = FastAPI(title="Gewicht Tracker")
app.mount("/static", StaticFiles(directory="static"), name="static")

db.init_db()


class WeightEntry(BaseModel):
    date: str  # YYYY-MM-DD
    weight: float


@app.get("/")
def index():
    return FileResponse("static/index.html")


@app.post("/api/weight")
def add_weight(entry: WeightEntry):
    try:
        entry_date = date.fromisoformat(entry.date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Ongeldige datum")
    if entry.weight <= 0 or entry.weight > 400:
        raise HTTPException(status_code=400, detail="Ongeldig gewicht")
    db.upsert_manual_weight(entry_date, entry.weight)
    return {"ok": True}


@app.get("/api/weight/today")
def weight_today():
    result = db.get_weight_for_date(date.today())
    return result or {}


@app.get("/api/chart/all")
def chart_all():
    rows = db.get_all_daily_weights()
    return [
        {"date": r["date"], "weight": r["weight"], "is_estimate": bool(r["is_interpolated"])}
        for r in rows
    ]


@app.get("/api/chart/yearly")
def chart_yearly():
    rows = db.get_all_daily_weights()
    series: dict[int, list[dict]] = {}
    for r in rows:
        d = date.fromisoformat(r["date"])
        series.setdefault(d.year, []).append(
            {"day_of_year": d.timetuple().tm_yday, "date": r["date"], "weight": r["weight"]}
        )
    return series


@app.get("/api/compare")
def compare(target: str | None = None):
    target_date = date.fromisoformat(target) if target else date.today()
    current = db.get_weight_for_date(target_date)
    if not current:
        raise HTTPException(status_code=404, detail="Nog geen data")

    years = db.get_years_with_data()
    results = []
    for year in years:
        if year == target_date.year:
            continue
        try:
            historic_date = target_date.replace(year=year)
        except ValueError:
            historic_date = date(year, 2, 28)  # 29 feb bestaat niet in dat jaar
        historic = db.get_weight_for_date(historic_date)
        if not historic:
            continue
        diff = round(current["weight"] - historic["weight"], 2)
        results.append(
            {
                "year": year,
                "date": historic["date"],
                "weight": historic["weight"],
                "is_estimate": historic["is_estimate"],
                "diff_vs_today": diff,
                "verdict": "lichter_nu" if diff < 0 else ("zwaarder_nu" if diff > 0 else "gelijk"),
            }
        )
    results.sort(key=lambda r: r["year"])
    return {"today": current, "target_date": target_date.isoformat(), "comparisons": results}
