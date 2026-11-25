# Multi-Feeder Cross-Feeder Zero-Shot Benchmark (`T-27`)

Status: **Complete (3 parallel Kaggle VMs: `bench-g1`, `bench-g2`, `bench-g3`, merged with SHA-256 provenance)** (pre-registered 2026-11-24 before running any new feeder evaluation). All results are pure steady-state OpenDSS simulation; no field data, no utility deployment.

Related study plans:
- Passive cross-feeder transfer (IEEE 123-bus → IEEE 34-bus): [`research/gnn-transfer/PLAN.md`](../gnn-transfer/PLAN.md)
- Active-grid transfer + Split Conformal Prediction (IEEE 123-bus → IEEE 34-bus): [`research/active-grid-gnn/PLAN.md`](../active-grid-gnn/PLAN.md)
- Third feeder: urban underground IEEE 37-bus (4.8 kV, 3-wire delta): [`research/ieee37-underground/PLAN.md`](../ieee37-underground/PLAN.md)

## 1. Objective

Test the **exact frozen IEEE 123-bus Stage-1 models** (`models/transfer/per_node_gbdt_ieee123.pkl` and `models/transfer/gnn_ieee123.pt`, trained strictly on IEEE 123-bus with zero retraining and zero hyperparameter tuning) across **all official IEEE & EPRI distribution test feeders available in `dss-extensions/electricdss-tst`** to build a comprehensive, honest multi-feeder evidence table showing:
1. Where zero-shot transfer from a single 4.16 kV feeder succeeds across voltage levels (0.416 kV LV to 34.5 kV MV), frequencies (50 Hz & 60 Hz), and utility scales (16 to 6,058 buses).
2. Where transfer degrades or breaks due to physics (e.g., high load-to-fault ratio on large substations, LV impedance, ungrounded delta) or topology (meshed secondary networks, closed loops, non-convergent circuit exports).

## 2. Official Feeder Inventory (`dss-extensions/electricdss-tst`, `Version8/Distrib/`)

Alongside our 3 already-evaluated feeders (**IEEE 123-bus**, **IEEE 34-bus**, **IEEE 37-bus**), this benchmark tests **11 official OpenDSS circuits** (and documents **CIGRE MV** transparently):

| Group (Kaggle VM) | ID | Official OpenDSS Source | Nominal kV / Freq | Topology / Expected Compatibility |
|---|---|---|---|---|
| **VM 1 (`bench-g1`)** | `ieee13` | `IEEETestCases/13Bus/IEEE13Nodeckt.dss` | 4.16 kV / 60 Hz | Compact, heavily unbalanced radial (16 buses) |
| **VM 1 (`bench-g1`)** | `eu_lv` | `IEEETestCases/LVTestCase/Master.dss` | **0.416 kV / 50 Hz** | European 50 Hz radial LV cable feeder (907 buses) |
| **VM 1 (`bench-g1`)** | `ieee342` | `IEEETestCases/LVTestCaseNorthAmerican/Master.dss` | 13.8 / 0.208 kV / 60 Hz | **Meshed LV network (71 cycles)** — expected `incompatible_meshed` for radial `PLACEMENT_RULE` |
| **VM 1 (`bench-g1`)** | `cigre_mv` | *Not present in `electricdss-tst`* | 20 kV / 50 Hz | Recorded honestly as `no_official_opendss_case` (no synthetic substitute fabricated) |
| **VM 2 (`bench-g2`)** | `epri_ckt5` | `EPRITestCircuits/ckt5/Master_ckt5.dss` | 12.47 kV / 60 Hz | Large radial utility feeder (2,998 buses) |
| **VM 2 (`bench-g2`)** | `epri_ckt7` | `EPRITestCircuits/ckt7/Master_ckt7.dss` | 12.47 kV / 60 Hz | Large radial utility feeder (1,255 buses; substation has 2 unloaded adjacent-feeder stubs) |
| **VM 2 (`bench-g2`)** | `epri_ckt24` | `EPRITestCircuits/ckt24/master_ckt24.dss` | 34.5 / 13.2 kV / 60 Hz | Large utility feeder (6,058 buses; 2 internal step-down loops — evaluated on primary BFS tree and flagged `semi_looped`) |
| **VM 3 (`bench-g3`)** | `ieee8500` | `IEEETestCases/8500-Node/Master-unbal.dss` | 12.47 kV / 60 Hz | Massive North American radial feeder (4,876 buses) |
| **VM 3 (`bench-g3`)** | `ieee9500` | `IEEETestCases/ieee9500dss/ieee9500_base.dss` | 12.47 kV / 60 Hz | Probe OpenDSSDirect 0.9.4 convergence; if base power flow diverges (`conv=False`), record honestly as `non_converged_base_case` |
| **VM 3 (`bench-g3`)** | `epri_j1` | `EPRITestCircuits/epri_dpv/J1/Master_noPV.dss` | 12.47 kV / 60 Hz | Utility radial feeder (3,434 buses) |
| **VM 3 (`bench-g3`)** | `epri_k1` | `EPRITestCircuits/epri_dpv/K1/Master_NoPV.dss` | 13.2 kV / 60 Hz | Utility radial feeder (1,282 buses) |
| **VM 3 (`bench-g3`)** | `epri_m1` | `EPRITestCircuits/epri_dpv/M1/Master_NoPV.dss` | 12.47 kV / 60 Hz | Utility radial feeder (2,596 buses) |

## 3. Pre-Registered Assumptions & Rules (Locked Before Running)

1. **Frozen models (`ZERO` leakage):** Use the exact frozen `models/transfer/per_node_gbdt_ieee123.pkl` and `models/transfer/gnn_ieee123.pt` trained exclusively on IEEE 123-bus (`shf/transfer.py` 21 relative features). Never retrain or tune thresholds on any test feeder.
2. **Switch placement (`ASSUMPTION`, frozen `BRANCH_SHARE = 0.05`):**
   - Build the energized topology graph from enabled closed `Line`, `Transformer`, and `Reactor` elements starting from the `Vsource` root bus.
   - If the connected component has `> 5` independent cycles (heavily meshed network such as `ieee342` with 71 cycles), classify as `incompatible_meshed` and do **not** force fake radial zones.
   - If the connected component is radial (`cycles == 0`) or has minor local loops (`1 <= cycles <= 5`, e.g., `epri_ckt24`'s 2 step-down loops), build the BFS tree from `root`, walk past transformers/reactors to the main loaded trunk (`>= 5%` load), and apply the exact `BRANCH_SHARE = 0.05` rule. Assign each bus to the nearest upstream chosen switch on its BFS tree path (guaranteeing clean zone partitioning while logging `cycles` transparently).
3. **Primary fault bus selection (`ASSUMPTION`):**
   - FLISR sectionalizers protect the primary distribution feeder, not 120/240 V customer service drops behind pole-top transformers.
   - For MV feeders (where the head switch sits at `>= 1.0 kV` LL), fault buses are restricted to primary MV buses (`kV_LL >= 1.0 kV`) inside the zones.
   - For LV feeders (`eu_lv`, where the head switch itself is `0.416 kV` LL), all `0.416 kV` feeder buses inside the zones are eligible.
4. **Stratified bus sampling (`ASSUMPTION`, fixed `seed = 0`):**
   - If eligible primary buses `<= 60` (e.g., `ieee13`): evaluate **100% of eligible buses** with `scenarios = 3` (identical to IEEE 123/34/37).
   - If eligible primary buses `> 60` (large utility feeders with 500–2,500 MV buses): sample up to **60 primary buses** stratified across all zones (minimum `3` buses per zone where available, remainder proportional to zone bus count, sorted deterministic `rng = np.random.default_rng(0)`) with `scenarios = 1`. Each sampled bus receives the full fault suite (`SLG` at `[0.01, 1, 5, 10, 25, 50, 100, 200, 400] Ω`, `LL/LLG/3PH` at `[0.01, 0.5, 2] Ω`), random `LoadMult ~ Uniform(0.3, 1.1)`, per-load spread `N(1, 0.20)` clipped `[0.3, 1.7]`, and `1%` / `0.5°` CT/PT noise.
   - Non-converged fault snapshots are excluded from accuracy and reported transparently (`converged / total`).
5. **Execution environment:** Run all 3 feeder groups in parallel on **Kaggle VMs** (`christoopherchau/self-healing-feeder-bench-g1`, `bench-g2`, `bench-g3`) using offline OpenDSS wheels (`OpenDSSDirect.py==0.9.4`), then pull and merge outputs locally with `shf.provenance.record()`.

## 4. Pre-Committed Verdict Rules

For each evaluated compatible feeder:
- **Strong zero-shot transfer (`Pass`):** Best frozen 123-bus model beats FPI by `>= +15.0` percentage points AND achieves `>= 80.0%` overall zero-shot accuracy.
- **Partial / physics-bounded transfer (`Partial`):** Best frozen 123-bus model beats FPI by `>= +10.0` points OR achieves `>= 85.0%` on phase faults (`3PH/LL/LLG`) while degrading on high-impedance SLG.
- **Transfer breakdown (`Fail`):** Neither bar is met — report the exact accuracy, signal-to-load ratio, and physical cause unchanged.
- **Out-of-scope / solver limit (`Incompatible` / `Non-converged` / `Not available`):** Document honestly with exact circuit statistics (cycle count, solver iteration count, or missing source).

---

## 5. Results (Kaggle 3-VM Parallel Run; Simulation Only)

Outputs: `results/transfer/multi_feeder_benchmark.json`, `results/transfer/multi_feeder_benchmark.csv`, provenance `results/provenance/transfer_multi_feeder_benchmark.json`.

| Feeder | kV / Hz | Zones | Events | FPI | Zero-shot GBDT | Zero-shot GNN | 1 sensor off (GBDT / GNN) | Verdict |
|---|---|---:|---:|---:|---:|---:|---:|---|
| **IEEE 13-bus** | 4.16 kV · 60 Hz | 6 | 1,278 | `50.9%` | **`95.5%`** | `89.0%` | `78.8%` / `78.4%` | **Pass** |
| **IEEE European LV** | **0.416 kV · 50 Hz** | 9 | 2,880 | `60.3%` | **`93.3%`** | `91.3%` | `83.1%` / `82.9%` | **Pass** |
| **IEEE 8500-Node** | 12.47 kV · 60 Hz | 13 | 1,203 | `44.1%` | **`99.8%`** | `99.0%` | `91.8%` / `91.7%` | **Pass** |
| **EPRI Ckt5** | 12.47 kV · 60 Hz | 11 | 1,125 | `55.6%` | **`98.0%`** | `97.6%` | `86.8%` / **`89.7%`** | **Pass** |
| **EPRI Ckt7** | 12.47 kV · 60 Hz | **18** | 2,373 | `71.6%` | `98.7%` | **`99.2%`** | `90.5%` / **`94.3%`** | **Pass** |
| **EPRI Ckt24** (`2` loops) | **34.5 kV** · 60 Hz | 7 | 1,374 | `59.3%` | **`99.7%`** | `98.6%` | `85.5%` / **`87.3%`** | **Pass** |
| **EPRI J1** | 12.47 kV · 60 Hz | 9 | 1,445 | `53.9%` | `99.2%` | **`99.3%`** | `87.7%` / **`90.3%`** | **Pass** |
| **EPRI K1** | 13.2 kV · 60 Hz | 13 | 1,476 | `52.2%` | **`99.7%`** | `99.6%` | `91.0%` / **`92.5%`** | **Pass** |
| **EPRI M1** | 12.47 kV · 60 Hz | 3 | 1,788 | `79.0%` | **`99.6%`** | `88.3%` | `66.6%` / **`69.0%`** | **Pass** |
| **IEEE 342-Node** | 13.8/0.208 kV · 60 Hz | – | – | – | – | – | – | **Incompatible (71 cycles)** |
| **IEEE 9500-Node** | 12.47 kV · 60 Hz | – | – | – | – | – | – | **Non-converged base flow** |
| **CIGRE MV** | 20 kV · 50 Hz | – | – | – | – | – | – | **Not available in repo** |

**Key findings:**
1. **10 of 11 total unseen evaluated feeders pass zero-shot** (including 9 of 9 new IEEE/EPRI radial/semi-looped feeders plus IEEE 34-bus; only ungrounded 3-wire delta IEEE 37-bus breaks down on SLG).
2. **Cross-frequency & cross-voltage transfer holds:** frozen 60 Hz / 4.16 kV models transfer cleanly to 50 Hz / 0.416 kV European LV (`93.3%` GBDT, `91.3%` GNN vs `60.3%` FPI) and 34.5 kV / 6,058-bus EPRI Ckt24 (`99.7%` GBDT, `98.6%` GNN vs `59.3%` FPI).
3. **GNN advantage under missing sensors on large feeders:** on every single one of the six large EPRI utility feeders, `ZoneTreeGNN` outperforms `PerNodeGBDT` when one sensor is offline (e.g., `94.3%` vs `90.5%` on 18-zone EPRI Ckt7).

