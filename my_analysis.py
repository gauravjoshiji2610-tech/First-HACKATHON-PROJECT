# Smart Health Surveillance – Unified AI (Symptoms + Water → Disease + Risk)
# Run:  pip install flask
#       python my_analysis.py
from flask import Flask, request, jsonify
from collections import Counter, defaultdict
from datetime import datetime

app = Flask(__name__)

SAFE = {
    "pH_min": 6.5, "pH_max": 8.5,
    "turbidity_ideal": 1.0, "turbidity_max": 5.0,  # WHO/BIS
    "ecoli": 0.0,             # /100 ml
    "coliforms": 0.0,         # /100 ml
    "hpc_max": 500.0,         # CFU/ml
    "arsenic_max": 0.01,      # mg/L
    "fluoride_max": 1.5,      # mg/L
    "nitrate_max": 45.0,      # mg/L as NO3-
    "lead_max": 0.01          # mg/L
}

SYMPTOM_KEYS = ["fever", "diarrhea", "vomit", "vomiting", "jaundice", "abdominal pain", "stomach pain", "nausea"]

def _get_float(v, default=0.0):
    try:
        if v in (None, "", "null"): return default
        return float(v)
    except Exception:
        return default

def score_and_infer(report):
    """
    Per-report scoring + disease inference.
    Input keys (all optional except location, symptoms are recommended):
      location, symptoms (text),
      pH, turbidity, bacteria_count (E. coli), coliforms, hpc,
      arsenic, fluoride, nitrate, lead,
      report_time
    Returns dict with: risk_level, score, issues, likely_diseases
    """
    stext = (report.get("symptoms") or "").lower()
    loc = report.get("location") or "Unknown"

    pH = _get_float(report.get("pH"), 7.0)
    turb = _get_float(report.get("turbidity"), 0.0)
    ecoli = _get_float(report.get("bacteria_count"), 0.0)  # interpret as E. coli count (/100 ml)
    coliforms = _get_float(report.get("coliforms"), 0.0)   # total coliforms (/100 ml)
    hpc = _get_float(report.get("hpc"), 0.0)               # CFU/ml
    arsenic = _get_float(report.get("arsenic"), 0.0)
    fluoride = _get_float(report.get("fluoride"), 0.0)
    nitrate = _get_float(report.get("nitrate"), 0.0)
    lead = _get_float(report.get("lead"), 0.0)

    score = 0
    issues, diseases = [], []

    # ---- Symptom-derived risk ----
    if "fever" in stext: score += 2
    if "diarrhea" in stext: score += 3
    if "vomit" in stext or "vomiting" in stext or "nausea" in stext: score += 2
    if "jaundice" in stext: score += 2
    if "abdominal pain" in stext or "stomach pain" in stext: score += 1

    # ---- Water quality thresholds (WHO/BIS-inspired) ----
    # pH
    if pH < SAFE["pH_min"] or pH > SAFE["pH_max"]:
        score += 2
        issues.append("Unsafe pH")
        diseases.append("Metal leaching / gastritis / skin irritation")

    # Turbidity
    if turb > 30:
        score += 4
        issues.append("Very high turbidity")
        diseases.append("Pathogens likely; chlorination failure")
    elif turb > SAFE["turbidity_max"]:
        score += 2
        issues.append("High turbidity")
        diseases.append("Pathogens may survive; diarrhea risk")
    elif turb > SAFE["turbidity_ideal"]:
        # informative but minor
        issues.append("Turbidity above ideal")

    # E. coli & Coliforms (any > 0 is unsafe)
    if ecoli > 0:
        score += 5
        issues.append("E. coli present")
        diseases.extend(["Diarrhea", "Cholera", "Typhoid"])
    if coliforms > 0:
        score += 3
        issues.append("Fecal contamination (coliforms)")
        diseases.extend(["Gastroenteritis", "Hepatitis A"])

    # HPC
    if hpc > SAFE["hpc_max"]:
        score += 2
        issues.append("High HPC")
        diseases.append("Opportunistic infections")

    # Chemicals
    if arsenic > SAFE["arsenic_max"]:
        score += 4
        issues.append("Arsenic above safe limit")
        diseases.append("Arsenicosis / cancer risk")
    if fluoride > SAFE["fluoride_max"]:
        score += 2
        issues.append("High fluoride")
        diseases.append("Dental/Skeletal fluorosis")
    if nitrate > SAFE["nitrate_max"]:
        score += 3
        issues.append("High nitrate")
        diseases.append("Methemoglobinemia (Blue Baby)")
    if lead > SAFE["lead_max"]:
        score += 4
        issues.append("Lead above safe limit")
        diseases.append("Neurotoxicity / developmental issues")

    # Couple symptoms with water for stronger disease suggestions
    if "diarrhea" in stext and (ecoli > 0 or coliforms > 0 or turb > SAFE["turbidity_max"]):
        if "Cholera" not in diseases: diseases.append("Cholera")
        if "Typhoid" not in diseases: diseases.append("Typhoid")
        if "Gastroenteritis" not in diseases: diseases.append("Gastroenteritis")
    if "jaundice" in stext and (coliforms > 0 or ecoli > 0):
        if "Hepatitis A" not in diseases: diseases.append("Hepatitis A")

    # Risk buckets
    # 0-2 Low, 3-5 Medium, >=6 High (tuned for mixed signals)
    if score >= 6: risk = "High"
    elif score >= 3: risk = "Medium"
    else: risk = "Low"

    # Deduplicate diseases while preserving order
    seen = set()
    diseases_unique = []
    for d in diseases:
        if d not in seen:
            seen.add(d)
            diseases_unique.append(d)

    return {
        "location": loc,
        "score": score,
        "risk_level": risk,
        "issues_found": issues,
        "likely_diseases": diseases_unique
    }

def aggregate_location_patterns(reports):
    """
    Build location-wise pattern: symptom trends, water issues, risk distribution, likely diseases.
    """
    loc_symptoms = defaultdict(Counter)
    loc_diseases = defaultdict(Counter)
    loc_risk = defaultdict(Counter)
    loc_issues = defaultdict(Counter)

    per_report = []
    for r in reports:
        # count symptoms
        stext = (r.get("symptoms") or "").lower()
        loc = r.get("location") or "Unknown"
        for key in SYMPTOM_KEYS:
            if key in stext: loc_symptoms[loc][key] += 1

        # score + infer
        result = score_and_infer(r)
        per_report.append({**r, **result})

        # aggregate
        for d in result["likely_diseases"]:
            loc_diseases[loc][d] += 1
        loc_risk[loc][result["risk_level"]] += 1
        for iss in result["issues_found"]:
            loc_issues[loc][iss] += 1

    # summarize per location
    location_summary = {}
    for loc in set([pr["location"] for pr in per_report] or ["Unknown"]):
        location_summary[loc] = {
            "symptom_trends": dict(loc_symptoms[loc]),
            "risk_counts": dict(loc_risk[loc]),
            "top_issues": [k for k, _ in loc_issues[loc].most_common(5)],
            "likely_diseases_top": [k for k, _ in loc_diseases[loc].most_common(5)]
        }

    return per_report, location_summary

def overall_risk_from_reports(per_report):
    if not per_report:
        return "No Data"
    counts = Counter([r["risk_level"] for r in per_report])
    total = len(per_report)
    if counts["High"] / total >= 0.33: return "High"
    if (counts["Medium"] / total) >= 0.33: return "Medium"
    return "Low"

@app.route("/analyze", methods=["POST"])
def analyze():
    """
    POST JSON: [ {location, symptoms, pH, turbidity, bacteria_count, coliforms, hpc,
                   arsenic, fluoride, nitrate, lead, report_time }, ... ]
    Returns:
      {
        total_reports,
        overall_risk,
        per_report: [ { ...score/risk/diseases... }, ... ],
        location_summary: {
           "VillageA": {
              symptom_trends, risk_counts, top_issues, likely_diseases_top
           }, ...
        },
        high_risk_locations: ["VillageA", ...]
      }
    """
    data = request.get_json(force=True) or []
    if not isinstance(data, list):
        return jsonify({"error": "Expecting a JSON array of reports"}), 400

    # Normalize timestamps (optional)
    for r in data:
        ts = r.get("report_time")
        if ts and isinstance(ts, str):
            try:
                r["report_time"] = datetime.fromisoformat(ts)
            except Exception:
                pass

    per_report, location_summary = aggregate_location_patterns(data)
    overall = overall_risk_from_reports(per_report)

    # mark high-risk locations (>= 2 High reports or top issues severe)
    high_risk_locs = []
    for loc, summary in location_summary.items():
        rc = summary.get("risk_counts", {})
        if rc.get("High", 0) >= 2:
            high_risk_locs.append(loc)
        else:
            # If E. coli/Arsenic/Lead flagged frequently, consider high
            severe_flags = {"E. coli present", "Arsenic above safe limit", "Lead above safe limit", "Fecal contamination (coliforms)"}
            if any(iss in (i.lower() for i in summary.get("top_issues", [])) for iss in map(str.lower, severe_flags)):
                high_risk_locs.append(loc)

    return jsonify({
        "total_reports": len(per_report),
        "overall_risk": overall,
        "per_report": per_report,
        "location_summary": location_summary,
        "high_risk_locations": list(sorted(set(high_risk_locs)))
    })

@app.route("/healthz", methods=["GET"])
def healthz():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    # Bind to localhost; change to 0.0.0.0 if you want remote access
    app.run(host="127.0.0.1", port=5000, debug=True)
