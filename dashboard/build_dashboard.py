"""Inject the pipeline's dashboard_data.json into the HTML template -> output/payroll_dashboard.html"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
data = json.loads((ROOT / "output" / "dashboard_data.json").read_text())
html = (ROOT / "dashboard" / "template.html").read_text()
out = ROOT / "output" / "payroll_dashboard.html"
out.write_text(html.replace("__DATA__", json.dumps(data).replace("</", "<\\/")))
print(f"wrote {out}")
