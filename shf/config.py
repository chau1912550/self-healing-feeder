"""Project-wide settings: file paths, switching devices, limits and assumptions.

Every number here that is an assumption (not part of the IEEE test case) is
marked ASSUMPTION so it can be listed in the README.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FEEDER_MASTER = ROOT / "data" / "feeder" / "ieee123" / "IEEE123Switches.dss"
GENERATED = ROOT / "data" / "generated"    # simulated dataset (not in git, run.py recreates it)
MODELS = ROOT / "models"                   # trained model (not in git)
RESULTS = ROOT / "results"                 # metrics and tables
FIGURES = RESULTS / "figures"

SOURCE_BUS = "150"
# Buses that are not part of the 4.16 kV distribution circuit we study.
EXCLUDED_BUSES = {"150", "150r", "610", "fdr2"}

# ---------------------------------------------------------------------------
# Switching devices
# ---------------------------------------------------------------------------
# Sectionalizing devices (normally closed). Each one is an existing OpenDSS
# Line. Sw1..Sw5 are the switches defined in the IEEE 123-bus test case.
# A1..A5 are ASSUMPTION: existing line segments that we treat as automated
# switches (an IntelliRupter-style recloser/switch at the upstream end of the
# segment) to split the feeder into smaller zones.
SECTIONALIZERS = {
    "Sw1": "Feeder-head recloser (IEEE Sw1, 150r-149)",
    "Sw2": "IEEE Sw2 (13-152)",
    "Sw3": "IEEE Sw3 (18-135)",
    "Sw4": "IEEE Sw4 (60-160)",
    "Sw5": "IEEE Sw5 (97-197)",
    "L13": "Added auto-switch A1 on line 13-18",
    "L45": "Added auto-switch A2 on line 44-47",
    "L61": "Added auto-switch A3 on line 60-62",
    "L68": "Added auto-switch A4 on line 67-97",
    "L77": "Added auto-switch A5 on line 76-86",
}

# Normally-open tie switches used for restoration.
# Sw7 is from the IEEE case (151-300). Sw9 is ASSUMPTION: a tie from bus 450 to
# an adjacent feeder, modeled below.
TIES = {
    "Sw7": "IEEE tie Sw7 (151-300)",
    "Sw9": "Added tie to adjacent feeder (450-fdr2)",
}
# IEEE Sw8 (54-94) is a single-phase tie. We leave it open and do not use it
# for restoration, because a 1-phase tie cannot pick up 3-phase load.

# ASSUMPTION: the adjacent feeder is a 4.16 kV substation bus held at 1.03 pu
# (typical LTC setpoint ~124 V on a 120 V base) behind 4,000 ft of the same
# 336,400 ACSR trunk (IEEE linecode 1). Its own load is not modeled, i.e. we
# assume its spare capacity is limited only by voltage drop and ampacity.
ADJACENT_FEEDER_DSS = [
    "New Vsource.Fdr2 bus1=fdr2src basekv=4.16 pu=1.03 phases=3 R1=0.01 X1=0.1 R0=0.01 X0=0.1",
    "New Line.Fdr2Trunk phases=3 bus1=fdr2src bus2=fdr2 linecode=1 length=4.0 units=kft",
    "New Line.Sw9 phases=3 bus1=450 bus2=fdr2 switch=yes r1=1e-3 r0=1e-3 x1=0 x0=0 c1=0 c0=0 length=0.001",
    "Open Line.Sw9 term=2",
]

# ---------------------------------------------------------------------------
# Ratings and limits
# ---------------------------------------------------------------------------
# Conductors from the IEEE 123 feeder data (config data.xls):
#   configs 1-8: 336,400 26/7 ACSR phase; configs 9-11: 1/0 ACSR;
#   config 12: 1/0 AA underground cable.
# ASSUMPTION: ampacities from typical conductor tables (verify before reuse):
#   336,400 26/7 ACSR ~530 A, 1/0 ACSR ~230 A, 1/0 AA UG cable ~200 A.
LINECODE_AMPACITY = {
    **{str(c): 530.0 for c in range(1, 9)},
    **{str(c): 230.0 for c in (9, 10, 11)},
    "12": 200.0,
}
EMERGENCY_FACTOR = 1.25  # ASSUMPTION: emergency rating = 125% of normal
SWITCH_AMPACITY = 600.0  # ASSUMPTION: 600 A continuous rating for switch/tie lines

# ANSI C84.1 Range A service voltage is 114-126 V on a 120 V base
# (0.95-1.05 pu). We apply it to primary nodes as a simple screening limit.
V_MIN_PU = 0.95
V_MAX_PU = 1.05
V_TOL = 0.0005  # numerical tolerance; the base case sits at 1.04996 pu

# ---------------------------------------------------------------------------
# Fault study settings
# ---------------------------------------------------------------------------
# Every simulated fault gets its own random loading scenario. A first version
# used three fixed load levels and the model scored 99.9% even on magnitude-only
# features: with so few distinct pre-fault states it could memorize "normal"
# currents. Real load drifts continuously and unevenly, so we randomize both.
LOAD_MULT_RANGE = (0.3, 1.1)   # feeder-wide load multiplier, uniform
LOAD_SPREAD = 0.20             # each spot load scaled by N(1, 0.20), clipped to [0.3, 1.7]
SCENARIOS_PER_CASE = 3         # random loading scenarios per fault case
SLG_RESISTANCES = [0.01, 1, 5, 10, 25, 50, 100, 200, 400]   # ohms, line-to-ground
PHASE_RESISTANCES = [0.01, 0.5, 2]     # ohms, LL / LLG / 3-phase faults
# ASSUMPTION: measurement error of CT/PT + device electronics (1 sigma)
NOISE_MAG = 0.01        # 1% magnitude
NOISE_ANG_DEG = 0.5     # 0.5 degree phase angle

# Conventional fault passage indication (the baseline we compare against).
# ASSUMPTION: phase pickup = 2x the device's peak-load phase current (a common
# rule of thumb); ground pickup = 0.5x peak-load phase current, but never below
# 1.2x the natural residual current caused by unbalanced load.
FPI_PHASE_FACTOR = 2.0
FPI_GROUND_FACTOR = 0.5
FPI_GROUND_MARGIN = 1.2

# ---------------------------------------------------------------------------
# Restoration timing (ASSUMPTION, used only for the customer-minutes metric)
# ---------------------------------------------------------------------------
T_AUTOMATED_MIN = 1      # automated isolation + tie switching
T_MANUAL_MIN = 90        # crew patrol + manual switching for healthy zones
T_REPAIR_MIN = 240       # repair time for the faulted zone
