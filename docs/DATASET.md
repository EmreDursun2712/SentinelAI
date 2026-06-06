# Dataset — CIC-IDS2017

SentinelAI's Detection Agent is trained on the Canadian Institute for Cybersecurity
**CIC-IDS2017** dataset.

- Source: https://www.unb.ca/cic/datasets/ids-2017.html
- Format: labelled NetFlow-style CSVs across multiple capture days.
- License: research use as defined by CIC. Cite their paper in any derived work.

## Local layout

Place the downloaded CSV files under `ml/data/` (gitignored). Example:

```
ml/data/
├── Monday-WorkingHours.pcap_ISCX.csv
├── Tuesday-WorkingHours.pcap_ISCX.csv
└── ...
```

A small anonymized slice will be checked in under `backend/data/samples/` once Phase 3 lands,
so the demo can run without the full dataset.

## What the pipeline uses

- 70+ NetFlow features (flow duration, packet counts, byte counts, IAT statistics, flag counts).
- Label column (`Label`) is mapped to attack family + benign.
- A fixed feature ordering is published in `ml/feature_list.py` (Phase 2) and consumed by the
  Detection Agent at runtime.

## Notes

- Drop or impute `Infinity` / `NaN` values present in some flows.
- Strip leading/trailing whitespace from column names — the official CSVs have inconsistent spacing.
- Class imbalance is significant; expect to use class weights or stratified sampling during training.
