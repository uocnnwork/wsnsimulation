# WSN Gradient Simulator — Configuration Settings
# Tuned for nRF54L15 BLE Mesh Indoor scenario

# ---------------------------------------------------------------------------
# Network topology
# ---------------------------------------------------------------------------
SINK_POSITION: tuple[float, float] = (25.0, 25.0)
AREA_WIDTH:    float = 50.0   # metres
AREA_HEIGHT:   float = 50.0   # metres
NUM_NODES:     int   = 100
TOPOLOGY:      str   = "Random"   # "Random" | "Grid" | "Star" | "Tree"

# ---------------------------------------------------------------------------
# Simulation time
# ---------------------------------------------------------------------------
SIM_DURATION:    float = 60.0   # seconds of simulated time
DATA_INTERVAL:   float = 1.0    # seconds between DATA generations per node
DATA_RATE:       int   = 1      # packets per interval per node
NUM_TIME_STEPS:  int   = 100    # kept for backwards compat (unused in SimPy mode)

# ---------------------------------------------------------------------------
# Gradient routing — dynamic beacon / route management
# ---------------------------------------------------------------------------
BEACON_PERIOD_S:        float = 5.0      # seconds between periodic beacons
ROUTE_TIMEOUT_S:        float = 15.0     # seconds before neighbor entry expires
HOLD_DOWN_TIME_S:       float = 1.0      # hold-down before gradient recovery
START_DELAY_MAX_S:      float = 5.0      # max random start delay per node
HEARTBEAT_INTERVAL_MIN_S: float = 5.0    # heartbeat exponential backoff min
HEARTBEAT_INTERVAL_MAX_S: float = 10800.0  # heartbeat exponential backoff max (3 h)
HEARTBEAT_BACKOFF_FACTOR: float = 1.5    # heartbeat backoff multiplier
GRADIENT_INFINITY:      int   = 255      # gradient value meaning "no route"

# ---------------------------------------------------------------------------
# Packet
# ---------------------------------------------------------------------------
PACKET_SIZE_BYTES: int = 64

# ---------------------------------------------------------------------------
# Energy  (nRF54L15 typical values, mJ)
# ---------------------------------------------------------------------------
INITIAL_ENERGY:  float = 3000.0   # mJ  (~2 × AA batteries ≈ 3000 mJ usable)
ENERGY_PER_TX:   float = 0.01     # mJ per transmission attempt
ENERGY_PER_RX:   float = 0.005    # mJ per received packet

# ---------------------------------------------------------------------------
# RF / neighbour discovery  (nRF54L15 BLE 1 Mbps, indoor)
# ---------------------------------------------------------------------------
TX_POWER_DBM:            float = 4.0    # dBm
RSSI_AT_1M:              float = -45.0  # dBm  (measured reference at 1 m)
PATH_LOSS_EXPONENT:      float = 2.5    # indoor environment
RECEIVER_SENSITIVITY_DBM: float = -70.0  # dBm  minimum detectable signal

# Rician LUT path (used for transmission success probability)
LUT_PATH: str = "data/rician_LUT.csv"

# TRANSMISSION_RANGE derived from RECEIVER_SENSITIVITY_DBM at runtime in
# network.py, but also kept here as a hard cap / fallback (metres).
TRANSMISSION_RANGE: float = 15.0

# ---------------------------------------------------------------------------
# MAC / BLE Mesh SAR  (realistic nRF54L15 parameters)
# ---------------------------------------------------------------------------
SAR_TX_JITTER_MIN_MS:      float = 5.0    # ms  min random backoff before TX
SAR_TX_JITTER_MAX_MS:      float = 25.0   # ms  max random backoff before TX
SAR_INTER_SEGMENT_DELAY_MS: float = 10.0  # ms  spacing between segments
SAR_RETRY_TIMEOUT_MS:      float = 200.0  # ms  base retry timeout
SAR_RETRY_MAX:             int   = 5      # max retransmission attempts
SAR_RETRY_BACKOFF:         float = 1.3    # exponential backoff multiplier
SAR_ACK_TIMEOUT_MS:        float = 150.0  # ms  wait for ACK
SAR_UNICAST_RETRIES:       int   = 3      # max unicast retries
CCA_MIN_SPACING_MS:        float = 10.0   # ms  clear-channel assessment spacing
CCA_MAX_RETRIES:           int   = 5      # CCA retry limit before forced TX

# ---------------------------------------------------------------------------
# RX Buffer  (byte-based, realistic BLE Mesh node)
# ---------------------------------------------------------------------------
RX_BUFFER_BYTES_NODE:    int = 384    # bytes  standard mesh node
RX_BUFFER_BYTES_GATEWAY: int = 2048   # bytes  sink / gateway

# ---------------------------------------------------------------------------
# Duplicate detection cache
# ---------------------------------------------------------------------------
DUP_CACHE_TIMEOUT_S: float = 600.0   # seconds  (10 min, per BLE Mesh spec)
DUP_CACHE_MAX_SIZE:  int   = 500

# ---------------------------------------------------------------------------
# ADUP protocol parameters  (§3.1.4)
# ---------------------------------------------------------------------------
ADUP_BASE_INTERVAL_S: float = 2.0   # Base_interval for control messages
ADUP_TIME_UNIT_S:     float = 1.0   # Time_unit per Rank increment
ADUP_SAFETY_THRESHOLD_DBM:    float = -60.0  # Safety zone boundary
ADUP_HYSTERESIS_DB:           float = 5.0    # Hysteresis added to Old RSSI

# ---------------------------------------------------------------------------
# Flooding protocol
# ---------------------------------------------------------------------------
FLOODING_TTL: int      = 12   # max hops for pure flooding (caps coroutine count)
N_FLOOD_WORKERS: int   = 8    # parallel TX workers per node
RANDOM_SEED: int = 42   # set to None to disable fixed seed: Default = 42

# ---------------------------------------------------------------------------
# Simulation mode
# ---------------------------------------------------------------------------
# "uplink"   — nodes → sink only
# "downlink" — sink → nodes only
# "both"     — run uplink first, then downlink; show grouped bar chart
SIM_MODE: str = "both"

# ---------------------------------------------------------------------------
# Progress monitor
# ---------------------------------------------------------------------------
PROGRESS_INTERVAL_S: float = 30.0   # print progress every N simulated seconds
