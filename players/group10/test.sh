#!/bin/bash

################################################################################
# Test Configuration

# Player to test (10 = group10)
PLAYER="10"

# Number of helpers
NUM_HELPERS=8

# Animal populations (space-separated list)
ANIMALS="10 20 40 60 80 100 120 140"

# Ark position (X Y coordinates)
ARK_X=500
ARK_Y=500

# Simulation duration (turns)
TIME=2500

# Random seed for reproducibility
SEED=12345

# Enable GUI (true/false)
GUI="true"

################################################################################
if [ "$GUI" = "true" ]; then
    uv run main.py \
        --player "$PLAYER" \
        --num_helpers "$NUM_HELPERS" \
        --animals $ANIMALS \
        --ark "$ARK_X" "$ARK_Y" \
        -T "$TIME" \
        --seed "$SEED" \
        --gui
else
    uv run main.py \
        --player "$PLAYER" \
        --num_helpers "$NUM_HELPERS" \
        --animals $ANIMALS \
        --ark "$ARK_X" "$ARK_Y" \
        -T "$TIME" \
        --seed "$SEED"
fi

