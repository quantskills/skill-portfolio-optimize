import copy
import json
import subprocess
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT.parents[1] / "registry"
sys.path.insert(0, str(ROOT / "scripts"))
from portfolio_adapter import ContractError, build_target

def envelope(profile, records):
    fields = {"factor-panel": {"instrument_id": {"type":"string","nullable":False}, "timestamp":{"type":"string","nullable":False,"format":"date-time"}, "factor_id":{"type":"string","nullable":False}, "value":{"type":"number","nullable":True,"unit":"score"}, "direction":{"type":"string","nullable":False}, "frequency":{"type":"string","nullable":False}, "universe":{"type":"string","nullable":False}, "missing_policy":{"type":"string","nullable":False}, "neutralization":{"type":"string","nullable":False}}, "market-bar": {"instrument_id":{"type":"string","nullable":False}, "timestamp":{"type":"string","nullable":False,"format":"date-time"}, "open":{"type":"number","nullable":False,"unit":"currency"}, "high":{"type":"number","nullable":False,"unit":"currency"}, "low":{"type":"number","nullable":False,"unit":"currency"}, "close":{"type":"number","nullable":False,"unit":"currency"}, "volume":{"type":"number","nullable":False,"unit":"shares"}, "frequency":{"type":"string","nullable":False}, "adjustment":{"type":"string","nullable":False}, "calendar":{"type":"string","nullable":False}}}[profile]
    keys = ["instrument_id", "timestamp", "factor_id"] if profile == "factor-panel" else ["instrument_id", "timestamp"]
    return {"$contract":{"envelope":"quantskills-envelope","envelope_version":"1.0.0","profile":profile,"profile_version":"1.0.0"},"meta":{"dataset_id":profile,"producer":"test","generated_at":"2026-08-10T12:00:00Z","as_of":"2026-08-10T12:00:00Z","timezone":"UTC","currency":"CNY","calendar":"SYNX","provenance":[{"provider":"test","dataset":profile,"raw_ref":"fixture://x","raw_sha256":"sha256:" + "0"*64}]},"schema":{"primary_key":keys,"fields":fields},"payload":{"native":{"raw_ref":"fixture://x"},"records":records},"quality":{"status":"pass","checks":[],"warnings":[]}}

class AdapterTests(unittest.TestCase):
    def setUp(self):
        signal = "2026-08-10T12:00:00Z"; assets = ["A", "B", "C"]
        self.factor = envelope("factor-panel", [{"instrument_id":a,"timestamp":signal,"factor_id":"quality","value":i+1,"direction":"higher-is-better","frequency":"1d","universe":"u","missing_policy":"exclude","neutralization":"none"} for i,a in enumerate(assets)])
        bars=[]
        for day in range(5):
            stamp=f"2026-08-0{day+5}T12:00:00Z"
            for i,a in enumerate(assets):
                close=10+i+day*(i+1)*0.1; bars.append({"instrument_id":a,"timestamp":stamp,"open":close,"high":close+.1,"low":close-.1,"close":close,"volume":100,"frequency":"1d","adjustment":"none","calendar":"SYNX"})
        self.bars=envelope("market-bar", bars)
    def build(self, factor=None, bars=None, **kw):
        args={"lookback":5,"min_observations":3,"alpha_scale":0.01,"portfolio_id":"p","registry_root":REGISTRY}; args.update(kw)
        return build_target(factor or self.factor, bars or self.bars, **args)
    def test_valid_output_is_contract_valid_and_calibrated(self):
        result=self.build(); self.assertEqual(result["payload"]["records"][0]["as_of"], "2026-08-10T12:00:00Z"); self.assertIn("alpha-scale=0.01", result["payload"]["records"][0]["constraints"])
    def test_multiple_factor_ids_rejected(self):
        factor=copy.deepcopy(self.factor); factor["payload"]["records"][1]["factor_id"]="value"
        with self.assertRaisesRegex(ContractError, "globally unique"): self.build(factor)
    def test_lookahead_rejected(self):
        bars=copy.deepcopy(self.bars); bars["payload"]["records"][0]["timestamp"]="2026-08-10T12:00:00Z"
        with self.assertRaisesRegex(ContractError, "strictly before"): self.build(bars=bars)
    def test_missing_instrument_and_invalid_calibration_rejected(self):
        bars=copy.deepcopy(self.bars); bars["payload"]["records"]=[x for x in bars["payload"]["records"] if x["instrument_id"] != "C"]
        with self.assertRaisesRegex(ContractError, "intersect exactly"): self.build(bars=bars)
        with self.assertRaisesRegex(ContractError, "alpha_scale"): self.build(alpha_scale=0)
    def test_neutral_and_missing_observations_rejected(self):
        factor=copy.deepcopy(self.factor); factor["payload"]["records"][0]["direction"]="neutral"
        with self.assertRaisesRegex(ContractError, "neutral"): self.build(factor)
        with self.assertRaisesRegex(ContractError, "observations"): self.build(min_observations=5)
    def test_demo_flag_is_not_an_adapter_fallback(self):
        run = subprocess.run([sys.executable, str(ROOT / "scripts" / "portfolio_adapter.py"), "--factor-panel", "x", "--market-bars", "x", "--lookback", "2", "--min-observations", "2", "--alpha-scale", "1", "--registry-root", "x", "--out", "x", "--demo"], text=True, capture_output=True)
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("unrecognized arguments: --demo", run.stderr)

if __name__ == "__main__": unittest.main()
