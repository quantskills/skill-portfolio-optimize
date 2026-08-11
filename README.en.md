# skill-portfolio-optimize

[简体中文](README.md) | English

Build auditable portfolio target weights from alpha scores under explicit risk
and trading constraints. The general optimiser supports mean-variance,
minimum-variance, maximum-Sharpe, risk-parity, and maximum-diversification
objectives, plus weight caps, sector or factor neutrality, and turnover limits.
It uses `scipy` SLSQP and reports optimisation diagnostics; it does not make a
performance or profitability claim.

## Versioned Envelope interface (P1′)

For structured exchange, use `scripts/portfolio_adapter.py`. It requires
`factor-panel@1.0.0` and `market-bar@1.0.0` documents and emits a
`portfolio-target@1.0.0` document. The adapter has no demo or default-data
fallback and calls the real `optimize_report.build_portfolio` implementation.
The current adapter path uses the `mean_variance` objective with a
sample-covariance estimate.

```bash
python scripts/portfolio_adapter.py \
  --factor-panel factor-panel.json \
  --market-bars market-bars.json \
  --lookback 60 \
  --min-observations 40 \
  --alpha-scale 0.01 \
  --portfolio-id research-portfolio \
  --registry-root /path/to/registry \
  --out portfolio-target.json
```

### Inputs and parameters

`factor-panel` must contain one globally unique `factor_id`, one shared signal
`timestamp`, one finite score per instrument, and one non-neutral `direction`
(`higher-is-better` or `lower-is-better`). Its frequency must match the bars.
The `market-bar` records provide `instrument_id`, timestamped OHLCV values,
frequency, adjustment, and calendar metadata. Input currencies and calendars
must agree, and the two documents must have exactly the same instrument set.

The adapter requires:

- `lookback` and `min-observations`: integers of at least 2;
- `alpha-scale`: a finite, strictly positive score-to-return calibration;
- `portfolio-id`: optional (defaults to `portfolio-target`), plus the required
  registry and output paths.

The expected-return vector is computed as `score × direction_sign ×
alpha_scale`. `alpha-scale` is supplied by the caller, is recorded in the
output constraints and lineage, and is not learned or validated for predictive
quality by this adapter. Calibrate it using an appropriate research process
and disclose the choice.

### Lookahead and evidence controls

Every market bar must be strictly earlier than the shared factor signal
timestamp. The adapter sorts each instrument's bars, takes the final
pre-signal `lookback` observations, computes aligned close-to-close returns,
and requires at least `min-observations` rows. It rejects mixed factor IDs or
timestamps, neutral or non-finite scores, mismatched metadata, missing or
extra instruments, insufficient history, invalid calibration, and solver
failure. A same-timestamp or future bar is never substituted or silently
discarded.

### Output

The result is a validated `portfolio-target@1.0.0` envelope containing:

- `portfolio_id` and the factor signal `as_of` timestamp;
- `target_weights` and `cash_target` (the adapter emits `0.0` cash for its
  long-only, full-investment result);
- declared constraints, including the lookback, observation count, and
  alpha-scale;
- lineage with source profile versions, dataset references, hashes, and
  adapter/calibration evidence references;
- native optimisation diagnostics and a passing quality record.

## General optimiser workflow

For direct CSV-based use, install dependencies and run the demo or report
builder:

```bash
pip install -r requirements.txt
python examples/run_demo.py

python scripts/optimize_report.py \
  --returns returns.csv \
  --signal alpha.csv \
  --objective mean_variance \
  --weight-cap 0.05 \
  --out weights.csv
```

The general workflow estimates a covariance matrix, builds the requested
constraints, solves with SLSQP, and returns weights plus volatility, holdings,
risk contributions, sector/factor exposure, turnover, and solver diagnostics.
See [`references/methodology.md`](references/methodology.md) for the objective
definitions and references. `scripts/data_source.py` can adapt `panda_data`
when valid credentials are supplied; it must not silently fall back to
synthetic data.

## Data, assumptions, and limitations

- Data sources: Envelope factor scores and market-bar closes for the P1′ path;
  user-provided return and signal CSVs for the general CLI.
- Assumptions: one factor and one point-in-time signal, aligned pre-signal
  observations, compatible currency/calendar/frequency metadata, and a
  feasible constraint set.
- Parameters: objective, weight cap, risk aversion, long/short mode, turnover
  or neutrality constraints, `lookback`, `min-observations`, and positive
  `alpha-scale` as applicable.
- Sample covariance can be noisy or singular, and annualisation or score-scale
  choices affect weights. Tight constraints or SLSQP feasibility can prevent a
  target. Non-convex objectives may return a local solution. Validate results
  out of sample and inspect all diagnostics.

This package is for quantitative research and education only. It is not
investment advice, an offer to trade, or a guarantee of results. Maintainers
do not verify data quality, calibration quality, or performance claims.

## Runtime files and maintenance

`SKILL.md` is the canonical skill entrypoint. `CLAUDE.md`,
`.cursor/rules/quantskills-skill.mdc`, and `agents/openai.yaml` provide the
runtime adapters and metadata. The community maintainer is
[abgyjaguo](https://github.com/abgyjaguo); this repository is not an official
or certified product.

## License

GNU General Public License v3.0 only. See [`LICENSE`](LICENSE).
