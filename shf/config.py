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

# ---------------------------------------------------------------------------
# Hourly restoration study (scripts/load_shape.py, scripts/hourly_restoration.py)
# ---------------------------------------------------------------------------
# Hourly load from the PJM AEP region (Kaggle "Hourly Energy Consumption",
# file AEP_hourly.csv). Download it by hand into data/external/pjm/ (git-ignored).
# Only the SHAPE is used: each hour's MW divided by that year's peak MW gives a
# feeder-wide LoadMult. ASSUMPTIONS:
#   - every spot load on the feeder follows this one regional shape (a real
#     feeder is less smooth than a whole utility region);
#   - the IEEE nominal spot loads are the annual peak (LoadMult 1.0);
#   - capacitors stay fixed as in the IEEE case (no CapControl);
#   - the adjacent feeder behind tie Sw9 has no load of its own (as above).
LOAD_SHAPE_COLUMN = "AEP_MW"


def _find_load_shape() -> Path:
    """data/external/pjm/AEP_hourly.csv locally; on Kaggle, the attached
    "Hourly Energy Consumption" dataset under /kaggle/input. SHF_LOAD_SHAPE_CSV overrides."""
    import os
    if os.environ.get("SHF_LOAD_SHAPE_CSV"):
        return Path(os.environ["SHF_LOAD_SHAPE_CSV"])
    local = ROOT / "data" / "external" / "pjm" / "AEP_hourly.csv"
    kaggle = Path("/kaggle/input")
    if not local.exists() and kaggle.is_dir():
        return next(kaggle.rglob("AEP_hourly.csv"), local)
    return local


LOAD_SHAPE_CSV = _find_load_shape()
HOURLY = RESULTS / "hourly"
# Restoration depends only on LoadMult when all loads share one shape, so we run
# it once per level on a grid and map every hour onto the nearest grid level.
HOURLY_LEVEL_STEP = 0.01
HOURLY_LEVEL_RANGE = LOAD_MULT_RANGE   # same range the fault sweep covers
# A tie closed at the fault hour must still be within limits until the repair
# ends, so we also plan for the highest load in the next HOLD_HOURS hours.
HOLD_HOURS = -(-(T_MANUAL_MIN + T_REPAIR_MIN) // 60)   # ceil(330 min / 60) = 6
SUMMER_MONTHS = (6, 7, 8)
WINTER_MONTHS = (12, 1, 2)

# ---------------------------------------------------------------------------
# LTspice circuits (shf/spice.py, scripts/spice_run.py)
# ---------------------------------------------------------------------------
# Time-domain circuits for what the phasor power flow in OpenDSS does not show.
# Circuit values come from the OpenDSS model (Thevenin impedance at the fault bus,
# feeder-head pre-fault current); the measurement chain values are ASSUMPTIONS.
SPICE_DIR = ROOT / "spice"
SPICE_FAULT_BUS = "60"         # same bus as the SCADA replay demo
SPICE_FAULT_R = 0.01           # ohms, bolted fault (as in the fault sweep)
CT_RATIO = 1000                # ASSUMPTION: 1000:1 recloser CT (ideal, no saturation)
ADC_BITS = 12                  # ASSUMPTION: 12-bit ADC on a 3.3 V microcontroller (ESP32-class)
ADC_VREF = 3.3
ADC_BIAS = 1.65                # mid-rail bias so the AC signal swings both ways
ADC_SAMPLES_PER_CYCLE = 32     # ASSUMPTION: 1920 samples/s at 60 Hz, one-cycle DFT
FRONTEND_HEADROOM_V = 1.2      # burden sized so the steady fault peak is 1.2 V (of 1.65 V)
FRONTEND_RC = (1000.0, 330e-9) # anti-alias RC: 1 kohm, 330 nF -> about 480 Hz corner

# Arcing high-impedance fault (spice/hif_arc.asc). The fault sweep treats a high-impedance
# ground fault as a fixed resistance. A real one arcs: the classic two-diode model
# (Emanuel et al. 1990) conducts only while the phase voltage is above an arc voltage,
# Vp on the positive half cycle and Vn on the negative one, through resistances Rp = Rn.
# For each fault resistance below, Rp = Rn is chosen so the arc current has the same RMS
# value as the fixed-resistance fault; the circuit then shows how the waveform differs.
HIF_R_CASES = (100, 400)       # ohms, two of the SLG_RESISTANCES in the fault sweep
HIF_VP_FRAC = 0.30             # ASSUMPTION: positive arc voltage = 30% of the phase peak voltage
HIF_VN_FRAC = 0.33             # ASSUMPTION: negative arc voltage 10% higher (asymmetric arc)

# ---------------------------------------------------------------------------
# SolidWorks 3D recloser (shf/mech.py, scripts/solidworks_build.py)
# ---------------------------------------------------------------------------
# ASSUMPTION: a generic pole-mounted 3-phase recloser drawn for the report's 3D view,
# with illustrative sizes in millimetres. It is not any manufacturer's design and is not
# used by any calculation in the study.
MECH_DIR = ROOT / "mech"
RECLOSER_MM = {
    "tank": (900, 420, 500),          # width x depth x height of the interrupter tank
    "frame": (1000, 500, 40),         # mounting frame under the tank
    "phase_spacing": 300,             # between the three phases (x)
    "bushing_row": 120,               # source / load bushing rows at z = +-120
    "bushing": (80, 400),             # core diameter, height above the tank
    "shed": (150, 15, 4),             # shed diameter, thickness, count per bushing
    "terminal": (30, 60),             # terminal stud diameter, height
    "pole": (300, 3800),              # reference pole segment: diameter, height
    "pole_z": 600,                    # pole axis behind the recloser (z)
    "cabinet": (500, 300, 800),       # control cabinet width x depth x height
    "cabinet_top": -600,              # cabinet hangs below the tank (top at y = -600)
}
# ASSUMPTION: the other equipment in the report's 3D view, generic and illustrative like the
# recloser (millimetres; none of it is a manufacturer's design or used by any calculation).
AUTO_SWITCH_MM = {                    # automated pole-top switch with a radio (A1-A5 in the study)
    "tank": (700, 350, 450), "frame": (800, 420, 40), "phase_spacing": 230, "bushing_row": 100,
    "bushing": (70, 300), "shed": (120, 12, 3), "terminal": (26, 50),
    "pole": (300, 3800), "pole_z": 560, "cabinet": (400, 250, 600), "cabinet_top": -600,
    "antenna": (20, 700), "radome": (90, 90),
}
REGULATOR_MM = {                      # single-phase step voltage regulator
    "base": (900, 900, 60), "tank": (700, 1100), "lid": (760, 40),
    "fin": (40, 260, 800, 3),         # thickness, reach out of the tank, height, fins per side
    "bushing": (80, 350), "shed": (140, 14, 3), "terminal": (28, 50), "bushing_x": (-200, 0, 200),
    "cabinet": (350, 200, 500), "indicator": (180, 60, 180),
}
CAPACITOR_MM = {                      # pole-mounted 3-phase capacitor bank
    "rack": (1300, 350, 60), "can": (340, 140, 560), "can_x": (-420, 0, 420),
    "bushing": (60, 200), "shed": (110, 12, 2), "terminal": (24, 40),
    "pole": (300, 3800), "pole_z": 400,
}
TRANSFORMER_MM = {                    # single-phase pole-top distribution transformer
    "tank": (550, 900), "lid": (590, 30),
    "hv_bushing": (70, 250), "hv_shed": (120, 12, 3), "hv_x": (-130, 130), "hv_z": 80,
    "lv_bushing": (40, 90), "lv_x": (-150, 0, 150), "lv_z": -180, "terminal": (24, 40),
    "hanger": (200, 100, 500), "pole": (300, 3800), "pole_z": 500,
}
SUBSTATION_MM = {                     # 4.16 kV source transformer on a concrete pad
    "pad": (3000, 2200, 200), "tank": (2000, 1300, 1800),
    "radiator": (120, 900, 1400, 5),  # thickness, reach out of the tank, height, fins per side
    "hv_bushing": (140, 900), "hv_shed": (260, 20, 6), "hv_x": (-500, 0, 500), "hv_z": 300,
    "lv_bushing": (100, 500), "lv_shed": (180, 16, 3), "lv_x": (-500, 0, 500), "lv_z": -350,
    "terminal": (40, 80), "conservator": (400, 700), "cabinet": (600, 400, 1000),
}
