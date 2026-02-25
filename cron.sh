#!/bin/bash

# Source the conda.sh script to initialize conda
source /home/yifei/miniconda3/etc/profile.d/conda.sh

# Activate the pi-pulse environment
conda activate pi-pulse

# Change to the directory where the Python script is located
cd /home/yifei/repos/pi-pulse

# Kill any existing instances of the Python script
pkill -f pi_pulse.py

# Wait briefly to ensure the old process is fully terminated
sleep 1

# Run the Python scripts
nohup python pi_pulse.py &