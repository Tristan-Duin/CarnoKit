#!/usr/bin/env bash
#
# 04-apply-rates.sh - Apply server rates + QoL + mod configs to every map.
#
# Profile: PvE, balanced ~2.5-5x rates, moderate breeding,
# slightly increased stack sizes, official wild level 150.
#
# Raw Prime Meat, Raw Mutton, and Giant Bee Honey are specifically
# overridden to stack to exactly 5.
#
# Edit the values below and re-run any time; it merges in place.
# The per-map name shown in the server list comes from CLUSTER_NAME below;
# ServerAdminPassword and other existing keys are preserved.
#
# Run as root:
#   sudo bash deploy/04-apply-rates.sh
#
set -euo pipefail

BASE_DIR="${BASE_DIR:-/opt/asa-cluster}"
MAPS="island scorched extinction"
# Server-list name prefix; each map appends its label, e.g.
# "Battling Poverty [Island]". Edit this to rename every server at once.
CLUSTER_NAME="${CLUSTER_NAME:-Battling Poverty}"
CFG_REL="server-files/ShooterGame/Saved/Config/WindowsServer"
TS="$(date +%Y%m%d-%H%M%S)"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root (sudo)." >&2
  exit 1
fi

echo "==> Stopping cluster"
cd "${BASE_DIR}/deploy"
docker compose -p asa-cluster down

# --- Game.ini: breeding, stats, QoL, and individual item stacks ---
# These settings are identical on every map.
read -r -d '' GAME_INI <<'GAMEINI' || true
[/Script/ShooterGame.ShooterGameMode]
MatingIntervalMultiplier=0.5
EggHatchSpeedMultiplier=10.0
BabyImprintAmountMultiplier=2.0
BabyFoodConsumptionSpeedMultiplier=2.0
LayEggIntervalMultiplier=0.5
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

# Force these normally single-stack items to stack to exactly 5.
# bIgnoreMultiplier=True prevents the global 2x stack multiplier from
# increasing these overrides from 5 to 10.
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
    extinction) map_label="Extinction" ;;
    *)          map_label="${m}" ;;
  esac
  session_name="${CLUSTER_NAME} [${map_label}]"

  # Merge [ServerSettings], [SessionSettings], and mod sections into
  # GameUserSettings.ini while preserving everything else, including
  # ServerAdminPassword.
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
    ("TamingSpeedMultiplier", "8.0"),
    ("BabyMatureSpeedMultiplier", "8.0"),
    ("BabyCuddleIntervalMultiplier", "0.15"),
    ("ResourcesRespawnPeriodMultiplier", "0.7"),
    ("ItemStackSizeMultiplier", "1.5"),
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
    ("TheMaxStructuresInRange", "10500.0"),
    ("PreventDownloadSurvivors", "False"),
    ("PreventDownloadItems", "False"),
    ("PreventDownloadDinos", "False"),
    ("PreventUploadSurvivors", "False"),
    ("PreventUploadItems", "False"),
    ("PreventUploadDinos", "False"),
    ("NoTributeDownloads", "False"),
    ("AdminLogging", "True"),
    ("ShowFloatingDamageText", "True"),
    ("AlwaysAllowStructurePickup", "True"),
    ("NonPermanentDiseases", "True"),
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
    ("CryoRestrictedItems", "True"),
    ("CryoInventoryItems", "True"),
    ("BossIgnoreDragWeight", "True"),
    ("AllowTribeLogs", "False"),
    ("AllowCuddleReroll", "True"),
    ("PreventCaveCryo", "False"),
    ("EnableCryoRifle", "True"),
])

desired["CybersStructures"] = collections.OrderedDict([
    ("EnableEngramOverride", "True"),
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

for section_name, desired_values in desired.items():
    if section_name not in sections:
        sections[section_name] = []
        order.append(section_name)

    remaining = collections.OrderedDict(desired_values)
    updated_body = []

    for line in sections[section_name]:
        setting_match = re.match(r"^\s*([A-Za-z0-9_]+)\s*=", line)

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

cat <<'NOTE'

Rates + QoL + mod configs applied to all maps, and the cluster is restarting.

Current major rates:
  - XP:                    3x
  - Harvest amount:        2.5x
  - Taming speed:          5x
  - General stack size:    2x
  - Raw Prime Meat stack:  5
  - Raw Mutton stack:      5
  - Giant Bee Honey stack: 5
  - Egg hatch speed:       10x
  - Baby maturation:       15x
  - Cuddle frequency:      5x
  - Imprint amount:        2x

IMPORTANT — one-time step:

Once the maps are back online, wipe wild dinos once so the Shad's Critter
Reworks variants and the official-difficulty level 150 spawns take effect.

In Discord, run this once for each map:

  /server destroy-wild-dinos

Or run this through RCON:

  DestroyWildDinos

A wild-dino wipe is not required when only changing rates or stack sizes.

To change the rates later, edit the values in this script and run it again.

NOTE
