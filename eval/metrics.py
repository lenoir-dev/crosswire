"""Independent detection/attribution metrics and uncertainty (QUALITY Q1 / M1)."""

import math
import random


def wilson(successes, total):
    """Return a two-sided 95% Wilson interval or None for an empty denominator."""
    if not total:
        return None
    z = 1.959963984540054
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    radius = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return [max(0, centre - radius), min(1, centre + radius)]


def match(predictions, diagnostics):
    """One-to-one M1 match; a wrong culprit does not turn a detection TP into FP."""
    remaining = set(range(len(diagnostics)))
    matched, false_positives, reasons = [], [], []
    for prediction in predictions:
        def identity(item):
            fields = ("type", "path", "module") if item.get("type") == "PY-2" else ("type", "path", "symbol", "occurrence")
            return tuple(item.get(k) for k in fields)
        found = next((i for i in sorted(remaining) if identity(prediction) == identity(diagnostics[i])), None)
        if found is None:
            false_positives.append(prediction)
            continue
        remaining.remove(found)
        oracle = diagnostics[found]
        attribution = prediction.get("attribution")
        matched.append({"prediction": prediction, "diagnostic": oracle, "attribution": attribution})
        if prediction.get("rule") == "CW002" and prediction.get("reason") not in oracle.get("reasons", [oracle.get("reason")]):
            reasons.append({"prediction": prediction.get("reason"), "oracle": oracle.get("reason")})
    return {"tp": len(matched), "fp": len(false_positives), "fn": len(remaining), "matches": matched,
            "false_positives": false_positives, "misses": [diagnostics[i] for i in sorted(remaining)],
            "reason_mismatches": reasons}


def aggregate(rows, *, cluster_bounds=True):
    """Aggregate eligible case rows; expose excluded shares and empty cells."""
    eligible = [row for row in rows if row["eligible"]]
    totals = {key: sum(row.get(key, 0) for row in eligible) for key in ("tp", "fp", "fn")}
    tp, fp, fn = (totals[k] for k in ("tp", "fp", "fn"))
    attribution = [a for row in eligible for a in row.get("attribution", []) if a is not None]
    excluded_predictions = sum(len(row.get("unlabelled_predictions", [])) for row in rows)
    enough = tp + fp >= 20 and tp + fn >= 20
    bounds = clustered(rows) if cluster_bounds else None
    lower = min(wilson(tp, tp + fp)[0], bounds["precision"][0]) if tp + fp and bounds and bounds["precision"] else wilson(tp, tp + fp)[0] if tp + fp else None
    precision_gate = "insufficient data" if not enough else "pass" if tp / (tp + fp) >= .95 and lower >= .9 else "fail"
    recall_gate = "insufficient data" if not enough else "pass" if tp / (tp + fn) >= .8 else "fail"
    return {**totals, "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "precision_wilson95": wilson(tp, tp + fp), "recall_wilson95": wilson(tp, tp + fn),
            "attribution_accuracy": sum(attribution) / len(attribution) if attribution else None,
            "attribution_labelled": len(attribution), "eligible_cases": len(eligible),
            "unlabelled_predictions": excluded_predictions,
            "unlabelled_prediction_share": excluded_predictions / (tp + fp + excluded_predictions) if tp + fp + excluded_predictions else None,
            "unlabelled_cases": len(rows) - len(eligible), "unlabelled_share": 1 - len(eligible) / len(rows) if rows else None,
            "precision_gate": precision_gate, "recall_gate": recall_gate,
            "detector_errors": sum(bool(row.get("detector_failure")) for row in rows),
            "precision_gate_lower_bound": lower,
            "status": "measured" if enough else "insufficient data"}


def clustered(rows, seed=9042026, replicates=2000):
    """Percentile bootstrap resampling whole repositories, never individual cases."""
    repositories = sorted({row["repository"] for row in rows if row.get("eligible") and "repository" in row})
    if len(repositories) < 5:
        return {"precision": None, "recall": None, "repositories": len(repositories), "status": "not estimable"}
    grouped = {repo: [row for row in rows if row["repository"] == repo] for repo in repositories}
    samples = {"precision": [], "recall": []}
    rng = random.Random(seed)
    for _ in range(replicates):
        sampled = [row for repo in rng.choices(repositories, k=len(repositories)) for row in grouped[repo]]
        values = aggregate(sampled, cluster_bounds=False)
        for key in samples:
            if values[key] is not None:
                samples[key].append(values[key])
    return {**{key: [sorted(values)[int(.025 * (len(values) - 1))], sorted(values)[int(.975 * (len(values) - 1))]] if values else None
               for key, values in samples.items()}, "repositories": len(repositories), "replicates": replicates, "seed": seed}
