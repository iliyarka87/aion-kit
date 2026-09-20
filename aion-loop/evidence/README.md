# evidence

One folder per checklist item: `evidence/<ITEM>/…` — probe output, journals, reports. The worker submits these
files through the gate (`vorota.py report PASS_CANDIDATE --evidence <file>`); `bin/uliki.py` indexes them with sha256
fingerprints, so a forged or missing file is caught before the judge reads it.
