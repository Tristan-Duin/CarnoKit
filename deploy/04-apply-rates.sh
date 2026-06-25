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
BabyMatureSpeedMultiplier=35.0
BabyFoodConsumptionSpeedMultiplier=1.1
BabyCuddleIntervalMultiplier=0.03
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
    extinction) map_label="Extinction" ;;
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

cat <<'NOTE'

Rates + QoL + mod configs were applied to all maps, and the cluster is
restarting.

Current major rates and changes:
  - XP:                         2x
  - Harvest amount:             2x
  - Taming speed:               5x (reduced from 8x)
  - General stack size:         normal / 1x
  - Raw Prime Meat stack:       5
  - Raw Mutton stack:           5
  - Giant Bee Honey stack:      5
  - Egg hatch speed:            10x
  - Baby maturation:            10x
  - Mating cooldown:            0.1x normal
  - Imprint:                    2x per cuddle
  - Tamed dino weight/level:    2x
  - Tamed dino stamina/level:   1.25x
  - Tamed dino healing:         1.5x
  - Dino stamina drain:         0.75x
  - Player food/water drain:    0.5x
  - Photo Mode range:           9000 (3x default)
  - Admin commands in chat:     disabled
  - CS Gravestone engram:       disabled/hidden
  - Wild max level:             150
  - Wild level distribution:    Ragnarok-like if Custom Dino Levels is loaded

IMPORTANT — one-time actions:

1. Remove existing Cybers Structures gravestones. Hiding the engram prevents
   new ones from being crafted, but it does not automatically destroy ones
   that are already placed. Run this once on each map through RCON or the
   in-game admin console:

     DestroyAll Gravestone_CS_C

2. Wipe wild dinos once so the official level-150 setting, Shad's Critter
   Reworks variants, and the Custom Dino Levels distribution can repopulate:

     DestroyWildDinos

   Or in Discord, run this once for each map:

     /server destroy-wild-dinos

3. The higher average wild-level distribution requires the Custom Dino Levels
   ASA mod (CurseForge project/mod ID 928708) to be included in each server's
   active mod list. Without that mod, the server remains at the normal vanilla
   level distribution while still keeping the maximum wild level at 150.

A wild-dino wipe is not required when only changing rates, stack sizes, photo
mode range, admin logging, or tamed-dino per-level stats.

To change the rates later, edit the values in this script and run it again.

NOTE