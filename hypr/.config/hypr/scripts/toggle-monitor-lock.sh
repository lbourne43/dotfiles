#!/bin/bash

MON="HDMI-A-2"

# Check current position
CURRENT=$(hyprctl monitors | grep "$MON" -A 5 | grep "1920x1080" | head -1 | awk '{print $3}')

if [[ "$CURRENT" == "-3000x0" ]]; then
    # Switch to auto
    hyprctl keyword monitor "$MON,1920x1080,auto,1.0,transform,2"
else
    # Switch to manual position
    hyprctl keyword monitor "$MON,1920x1080,-3000x0,1.0,transform,2"
fi
