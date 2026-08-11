"""Point-in-time Envelope adapter for the real portfolio optimiser."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
from covariance import estimate_cov
from optimize_report import build_portfolio

class ContractError(ValueError): pass

def _hash(value: dict) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()

def _validate(document: dict, root: Path, profile: str) -> None:
    sys.path.insert(0, str(root / "scripts"))
    from validate_contract import validate_contract
    if document.get("$contract", {}).get("profile") != profile or validate_contract(document, root)["status"] != "valid":
        raise ContractError(f"invalid {profile} contract")

def _time(value: str) -> datetime: return datetime.fromisoformat(value.replace("Z", "+00:00"))

def build_target(factor_panel: dict, market_bars: dict, *, lookback: int, min_observations: int,
                 alpha_scale: float, portfolio_id: str, registry_root: Path) -> dict:
    if not isinstance(lookback, int) or lookback < 2 or not isinstance(min_observations, int) or min_observations < 2:
        raise ContractError("lookback and min_observations must be integers >= 2")
    if not isinstance(alpha_scale, (int, float)) or isinstance(alpha_scale, bool) or not math.isfinite(alpha_scale) or alpha_scale <= 0:
        raise ContractError("alpha_scale must be a finite positive score-to-return calibration")
    _validate(factor_panel, registry_root, "factor-panel"); _validate(market_bars, registry_root, "market-bar")
    factors = factor_panel["payload"]["records"]
    ids, timestamps, directions = {x["factor_id"] for x in factors}, {x["timestamp"] for x in factors}, {x["direction"] for x in factors}
    if len(ids) != 1: raise ContractError("factor-panel must have exactly one globally unique factor_id")
    if len(timestamps) != 1: raise ContractError("all factor assets must share one signal timestamp")
    if len(directions) != 1 or "neutral" in directions: raise ContractError("neutral or mixed factor directions are not usable")
    signal = timestamps.pop(); signal_time = _time(signal); direction = directions.pop()
    scores = {x["instrument_id"]: x["value"] for x in factors}
    if len(scores) != len(factors) or any(x is None or not math.isfinite(x) for x in scores.values()): raise ContractError("one finite score per instrument is required")
    factor_meta, bar_meta, bars = factor_panel["meta"], market_bars["meta"], market_bars["payload"]["records"]
    if factor_meta.get("currency") and factor_meta["currency"] != bar_meta["currency"]: raise ContractError("input currencies must match")
    if factor_meta.get("calendar") and factor_meta["calendar"] != bar_meta.get("calendar"): raise ContractError("input calendars must match")
    signatures = {(x["frequency"], x["calendar"], x["adjustment"]) for x in bars}
    if len(signatures) != 1: raise ContractError("bars must share frequency, calendar, and adjustment")
    factor_frequencies = {x["frequency"] for x in factors}
    if len(factor_frequencies) != 1 or factor_frequencies.pop() != next(iter(signatures))[0]:
        raise ContractError("factor and market-bar frequencies must match")
    by_asset: dict[str, list[dict]] = {}
    for bar in bars:
        if _time(bar["timestamp"]) >= signal_time: raise ContractError("bars must be strictly before signal timestamp")
        by_asset.setdefault(bar["instrument_id"], []).append(bar)
    if set(scores) != set(by_asset): raise ContractError("factor and market-bar instruments must intersect exactly")
    columns = {}
    for asset, rows in by_asset.items():
        rows.sort(key=lambda x: x["timestamp"])
        if len(rows) < lookback: raise ContractError("insufficient pre-signal market-bar lookback")
        columns[asset] = pd.Series({x["timestamp"]: x["close"] for x in rows[-lookback:]})
    returns = pd.DataFrame(columns).sort_index().pct_change().dropna(how="any")
    if len(returns) < min_observations: raise ContractError("insufficient aligned return observations")
    expected = pd.Series(scores, dtype=float) * (1.0 if direction == "higher-is-better" else -1.0) * float(alpha_scale)
    result = build_portfolio("mean_variance", estimate_cov(returns, method="sample"), mu=expected)
    if not result["diagnostics"]["solver_success"]: raise ContractError("real optimize_report solver failed; no fallback is allowed")
    factor_hash, bars_hash = _hash(factor_panel), _hash(market_bars)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    lineage = {"sources": [{"profile": "factor-panel", "version": "1.0.0", "artifact_ref": factor_meta["dataset_id"], "sha256": factor_hash}, {"profile": "market-bar", "version": "1.0.0", "artifact_ref": bar_meta["dataset_id"], "sha256": bars_hash}], "evidence_refs": ["adapter://portfolio-optimize/real-optimize-report", f"calibration://alpha-scale/{alpha_scale}"]}
    document = {"$contract": {"envelope": "quantskills-envelope", "envelope_version": "1.0.0", "profile": "portfolio-target", "profile_version": "1.0.0"}, "meta": {"dataset_id": f"{portfolio_id}-{signal}", "producer": "skill-portfolio-optimize", "generated_at": now, "as_of": signal, "timezone": factor_meta.get("timezone", "UTC"), "currency": bar_meta["currency"], "calendar": bar_meta.get("calendar", next(iter(signatures))[1]), "provenance": [{"provider": "skill-portfolio-optimize", "dataset": "portfolio-target", "raw_ref": "adapter://portfolio-optimize", "raw_sha256": factor_hash}]}, "schema": {"primary_key": ["portfolio_id", "as_of"], "fields": {"portfolio_id": {"type": "string", "nullable": False}, "as_of": {"type": "string", "nullable": False, "format": "date-time"}, "target_weights": {"type": "object", "nullable": False}, "cash_target": {"type": "number", "nullable": False, "unit": "ratio"}, "constraints": {"type": "array", "nullable": False}, "lineage": {"type": "object", "nullable": False}}}, "payload": {"native": {"provider": "skill-portfolio-optimize", "raw_records": [result["diagnostics"]]}, "records": [{"portfolio_id": portfolio_id, "as_of": signal, "target_weights": {k: float(v) for k, v in result["weights"].items()}, "cash_target": 0.0, "constraints": ["long-only", "full-investment", "mean-variance", f"lookback={lookback}", f"min-observations={min_observations}", f"alpha-scale={alpha_scale}"], "lineage": lineage}]}, "quality": {"status": "pass", "checks": ["strict-pre-signal-bars", "strict-instrument-intersection", "real-optimize-report", "score-to-return-calibration"], "warnings": []}}
    _validate(document, registry_root, "portfolio-target")
    return document

def main() -> None:
    p = argparse.ArgumentParser(description="Build portfolio-target from Envelope inputs; demo fallback is forbidden.")
    p.add_argument("--factor-panel", required=True); p.add_argument("--market-bars", required=True)
    p.add_argument("--lookback", required=True, type=int); p.add_argument("--min-observations", required=True, type=int); p.add_argument("--alpha-scale", required=True, type=float)
    p.add_argument("--portfolio-id", default="portfolio-target"); p.add_argument("--registry-root", required=True); p.add_argument("--out", required=True)
    a = p.parse_args()
    document = build_target(json.loads(Path(a.factor_panel).read_text(encoding="utf-8")), json.loads(Path(a.market_bars).read_text(encoding="utf-8")), lookback=a.lookback, min_observations=a.min_observations, alpha_scale=a.alpha_scale, portfolio_id=a.portfolio_id, registry_root=Path(a.registry_root))
    Path(a.out).write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
if __name__ == "__main__": main()
