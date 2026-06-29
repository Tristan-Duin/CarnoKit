#!/usr/bin/env bash
#
# 04-apply-rates.sh - Apply server rates + QoL + mod configs to every map.
#
# Profile: PvE, balanced rates, moderate breeding, normal global stack sizes,
# official wild max level 150, and a mildly improved wild-level distribution
# when Custom Dino Levels is installed.
#
# Run as root:
#   sudo bash deploy/04-apply-rates.sh
#
set -euo pipefail

BASE_DIR="${BASE_DIR:-/opt/asa-cluster}"
MAPS="island scorched ragnarok"

# Server-list name prefix; each map appends its label, e.g.
# "Battling Poverty [Island]". Edit this to rename every server at once.
CLUSTER_NAME="${CLUSTER_NAME:-Battling Poverty}"

CFG_REL="server-files/ShooterGame/Saved/Config/WindowsServer"
TS="$(date +%Y%m%d-%H%M%S)"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root (sudo)." >&2
  exit 1
fi

if [[ ! -d "${BASE_DIR}/deploy" ]]; then
  echo "Missing deploy directory: ${BASE_DIR}/deploy" >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "docker was not found in PATH." >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 was not found in PATH." >&2
  exit 1
fi

# ==============================================================================
# SAFE SAVE SYSTEM
# ==============================================================================
ENV_FILE="${BASE_DIR}/deploy/.env"
if [[ -f "${ENV_FILE}" ]]; then
  echo "==> Sourcing cluster credentials from .env..."
  # Safely parse required variables without evaluating the whole file
  RCON_PASS=$(grep -E '^ADMIN_PASSWORD=' "${ENV_FILE}" | cut -d'=' -f2)
else
  echo "Error: Missing environment config file at ${ENV_FILE}" >&2
  exit 1
fi

echo "==> Warning players and issuing safe-saves across the cluster..."

for m in ${MAPS}; do
  # Dynamically build and read the variable name from your .env file (e.g., ISLAND_RCON_PORT)
  UPPER_MAP=$(echo "${m}" | tr '[:lower:]' '[:upper:]')
  PORT_VAR="${UPPER_MAP}_RCON_PORT"
  
  port=$(grep -E "^${PORT_VAR}=" "${ENV_FILE}" | cut -d'=' -f2 || true)
  
  if [[ -n "${port}" && -n "${RCON_PASS}" ]]; then
    echo "==> Sending save command to [${m}] on RCON port ${port}..."
    
    python3 - "${port}" "${RCON_PASS}" <<'RCONEOF'
import sys
import socket

port = int(sys.argv[1])
password = sys.argv[2]

def send_rcon_cmd(cmd_str):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(4)
        s.connect(('127.0.0.1', port))
        
        # Authenticate packet (Type 3)
        auth_body = int.to_bytes(10, 4, 'little') + int.to_bytes(3, 4, 'little') + password.encode('utf-8') + b'\x00\x00'
        s.sendall(int.to_bytes(len(auth_body), 4, 'little') + auth_body)
        s.recv(4096)
        
        # Command packet (Type 2)
        cmd_body = int.to_bytes(11, 4, 'little') + int.to_bytes(2, 4, 'little') + cmd_str.encode('utf-8') + b'\x00\x00'
        s.sendall(int.to_bytes(len(cmd_body), 4, 'little') + cmd_body)
        s.recv(4096)
        s.close()
    except Exception as e:
        print(f"    [Warning] Could not reach port {port}: {e}")

send_rcon_cmd("ServerChat Server updating! Saving world progress...")
send_rcon_cmd("SaveWorld")
RCONEOF
  else
    echo "    [Warning] Could not dynamically resolve RCON port for map: ${m}"
  fi
done

echo "==> Waiting 15 seconds for game data disk writes to complete..."
sleep 15

echo "==> Stopping cluster"
cd "${BASE_DIR}/deploy"
docker compose -p asa-cluster down

# --- Game.ini: breeding, stats, QoL, photo mode, and item overrides ---
# These settings are identical on every map.
read -r -d '' GAME_INI <<'GAMEINI' || true
[/Script/ShooterGame.ShooterGameMode]
MatingIntervalMultiplier=0.01
MatingSpeedMultiplier=2.0
EggHatchSpeedMultiplier=20.0
LayEggIntervalMultiplier=0.5
BabyMatureSpeedMultiplier=90.0
BabyFoodConsumptionSpeedMultiplier=1.0
BabyCuddleIntervalMultiplier=0.01
BabyCuddleGracePeriodMultiplier=3.0
BabyCuddleLoseImprintQualitySpeedMultiplier=0.1
BabyImprintAmountMultiplier=2.5
BabyImprintingStatScaleMultiplier=1.0
CropGrowthSpeedMultiplier=2.0
PoopIntervalMultiplier=0.5
GlobalSpoilingTimeMultiplier=2.0
GlobalItemDecompositionTimeMultiplier=2.0
GlobalCorpseDecompositionTimeMultiplier=2.0
CraftingSkillBonusMultiplier=1.5
bAllowUnlimitedRespecs=True
bAllowPlatformSaddleMultiFloors=True
ResourceNoReplenishRadiusStructures=0.5
ResourceNoReplenishRadiusPlayers=0.5
PerLevelStatsMultiplier_Player[7]=3.0
bUseSingleplayerSettings=False
PerLevelStatsMultiplier_DinoTamed[7]=1.1
bDisablePhotoMode=False
PhotoModeRangeLimit=9000
ConfigOverrideItemMaxQuantity=(ItemClassString="PrimalItemConsumable_RawPrimeMeat_C",Quantity=(MaxItemQuantity=5,bIgnoreMultiplier=True))
ConfigOverrideItemMaxQuantity=(ItemClassString="PrimalItemConsumable_RawMutton_C",Quantity=(MaxItemQuantity=5,bIgnoreMultiplier=True))
ConfigOverrideItemMaxQuantity=(ItemClassString="PrimalItemConsumable_Honey_C",Quantity=(MaxItemQuantity=5,bIgnoreMultiplier=True))
GAMEINI

for m in ${MAPS}; do
  cfg="${BASE_DIR}/${m}/${CFG_REL}"
  mkdir -p "${cfg}"

  echo "==> [${m}] backing up + writing configs"

  if [[ -f "${cfg}/Game.ini" ]]; then
    cp "${cfg}/Game.ini" "${cfg}/Game.ini.bak.${TS}"
  fi

  if [[ -f "${cfg}/GameUserSettings.ini" ]]; then
    cp \
      "${cfg}/GameUserSettings.ini" \
      "${cfg}/GameUserSettings.ini.bak.${TS}"
  fi

  printf '%s\n' "${GAME_INI}" > "${cfg}/Game.ini"

  # Per-map server-list name: "Battling Poverty [Island]" etc.
  case "${m}" in
    island)     map_label="Island" ;;
    scorched)   map_label="Scorched" ;;
    ragnarok)   map_label="Ragnarok" ;;
    *)          map_label="${m}" ;;
  esac

  session_name="${CLUSTER_NAME} [${map_label}]"

  python3 - "${cfg}/GameUserSettings.ini" "${session_name}" <<'PYEOF'
import collections
import re
import sys

path = sys.argv[1]
session_name = sys.argv[2] if len(sys.argv) > 2 else ""

desired = collections.OrderedDict()

desired["ServerSettings"] = collections.OrderedDict([
    ("ServerPVE", "True"),
    ("ProximityChat", "False"),
    ("bPvEAllowTribeWar", "False"),
    ("XPMultiplier", "2.0"),
    ("EnableCryoSicknessPVE", "False"),
    ("HarvestAmountMultiplier", "2.0"),
    ("HarvestHealthMultiplier", "1.0"),
    ("TamingSpeedMultiplier", "6.5"),
    ("DinoCharacterHealthRecoveryMultiplier", "1.5"),
    ("DinoCharacterStaminaDrainMultiplier", "0.75"),
    ("PlayerCharacterFoodDrainMultiplier", "0.5"),
    ("PlayerCharacterWaterDrainMultiplier", "0.5"),
    ("ResourcesRespawnPeriodMultiplier", "1.0"),
    ("ItemStackSizeMultiplier", "1.0"),
    ("AllowThirdPersonPlayer", "True"),
    ("ServerCrosshair", "True"),
    ("ShowMapPlayerLocation", "True"),
    ("AllowFlyerCarryPvE", "True"),
    ("AllowCaveBuildingPvE", "True"),
    ("bDisableStructureDecayPvE", "True"),
    ("DisableDinoDecayPvE", "True"),
    ("OverrideOfficialDifficulty", "5.0"),
    ("DifficultyOffset", "1.0"),
    ("DayCycleSpeedScale", "0.8"),
    ("DayTimeSpeedScale", "0.8"),
    ("NightTimeSpeedScale", "1.2"),
    ("bUseCorpseLocator", "True"),
    ("AllowAnyoneBabyImprintCuddle", "True"),
    ("DisableImprintDinoBuff", "False"),
    ("TheMaxStructuresInRange", "10500.0"),
    ("PreventDownloadSurvivors", "False"),
    ("PreventDownloadItems", "False"),
    ("PreventDownloadDinos", "False"),
    ("PreventUploadSurvivors", "False"),
    ("PreventUploadItems", "False"),
    ("PreventUploadDinos", "False"),
    ("NoTributeDownloads", "False"),
    ("AdminLogging", "False"),
    ("ShowFloatingDamageText", "True"),
    ("AlwaysAllowStructurePickup", "True"),
    ("NonPermanentDiseases", "True"),
    ("DinoCountMultiplier", "0.9"),
    ("AutoSavePeriodMinutes", "30.0"),
])

if session_name:
    desired["SessionSettings"] = collections.OrderedDict([
        ("SessionName", session_name),
    ])

desired["ConfigurableCryopods"] = collections.OrderedDict([
    ("PreventCryoSickness", "True"),
    ("CanAlwaysCapture", "True"),
    ("PlatformSaddleTimer", "True"),
    ("MaxBossLimit", "50"),
    ("CryoSpeed", "0.2"),
    ("OwnerCryoOnly", "False"),
    ("RestrictedCryoDeploy", "True"),
    ("CryoRestrictedItems", "False"),
    ("CryoInventoryItems", "False"),
    ("BossIgnoreDragWeight", "True"),
    ("AllowTribeLogs", "False"),
    ("AllowCuddleReroll", "True"),
    ("PreventCaveCryo", "False"),
    ("EnableCryoRifle", "True"),
])

desired["CybersStructures"] = collections.OrderedDict([
    ("EnableEngramOverride", "True"),
    ("HatcheryRangeInFoundations", "15"),
    ("HatcheryScanInterval", "15"),
    ("HatcherySlotCount", "100"),
])

try:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        lines = fh.read().splitlines()
except FileNotFoundError:
    lines = []

order = []
sections = collections.OrderedDict()
preamble = []
current_section = None

for line in lines:
    section_match = re.match(r"^\s*\[(.+)\]\s*$", line)

    if section_match:
        current_section = section_match.group(1)

        if current_section not in sections:
            sections[current_section] = []
            order.append(current_section)
    else:
        if current_section is None:
            preamble.append(line)
        else:
            sections[current_section].append(line)

# Keys to strip from GameUserSettings.ini if present because they now belong
# in Game.ini or were retired. This prevents stale duplicate settings.
deprecated = {
    "ServerSettings": [
        "BabyMatureSpeedMultiplier",
        "BabyCuddleIntervalMultiplier",
        "PhotoModeRangeLimit",
        "bDisablePhotoMode",
    ],
}

for section_name, desired_values in desired.items():
    if section_name not in sections:
        sections[section_name] = []
        order.append(section_name)

    remaining = collections.OrderedDict(desired_values)
    drop = set(deprecated.get(section_name, []))
    updated_body = []

    for line in sections[section_name]:
        setting_match = re.match(r"^\s*([A-Za-z0-9_]+)\s*=", line)

        if setting_match and setting_match.group(1) in drop:
            continue

        if setting_match and setting_match.group(1) in remaining:
            key = setting_match.group(1)
            updated_body.append(f"{key}={remaining.pop(key)}")
        else:
            updated_body.append(line)

    for key, value in remaining.items():
        updated_body.append(f"{key}={value}")

    sections[section_name] = updated_body

output = list(preamble)

for section_name in order:
    output.append(f"[{section_name}]")
    output.extend(sections[section_name])

with open(path, "w", encoding="utf-8") as fh:
    fh.write("\n".join(output).rstrip("\n") + "\n")

print(f"   updated {path}")
PYEOF
done

echo "==> Starting cluster"
docker compose -p asa-cluster up -d
