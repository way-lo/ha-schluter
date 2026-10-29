"""Constants for the schluter integration."""

DOMAIN = "schluter"
ZERO_WATTS = 0

# Regulation modes as the Schluter cloud reports them. The aioschluter library
# names 2 "MANUAL" and 3 "AWAY", but observed behaviour on a DITRA-HEAT-E-WiFi
# is different:
#   1 = following the programmed schedule
#   2 = temporary hold at ComfortTemperature, until ComfortEndTime
#       (the next scheduled change when set from the app/website)
#   3 = permanent hold at ManualTemperature, until the schedule is resumed
MODE_SCHEDULE = 1
MODE_TEMPORARY_HOLD = 2
MODE_PERMANENT_HOLD = 3

PRESET_SCHEDULE = "On schedule"
PRESET_TEMPORARY = "Temporary hold"
PRESET_PERMANENT = "Permanent hold"

# Extra refreshes after a command. The cloud applies a mode change at once but
# the thermostat reports its new set point a little later.
FOLLOWUP_REFRESH_DELAYS = (15, 45)
