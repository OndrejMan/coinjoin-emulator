#!/bin/bash

# Call this as: source managePythonVirtualEnvironment.sh 

# Check if a virtual environment is currently active
if [ -n "$VIRTUAL_ENV" ]; then
    echo "Active virtual environment detected at: $VIRTUAL_ENV"
    
    VENV_DIR="$VIRTUAL_ENV"

    # Deactivate the environment
    deactivate
    echo "Virtual environment disabled successfully."

    # Cross-shell compatible prompt (Works in both Zsh and Bash)
    printf "Do you want to delete this virtual environment's data? (y/N): "
    read confirm
    
    # Check if the user answered 'y' or 'Y'
    if [[ "$confirm" =~ ^[Yy]$ ]]; then
        # Save the path before we deactivate

        
        # Delete the virtual environment folder completely
        rm -rf "$VENV_DIR"
        echo "Virtual environment deleted from: $VENV_DIR"
    else
        echo "Deletion aborted. The virtual environment remains untouched."
    fi
else
    # Standard operations when no venv is active
    echo "No virtual environment active. Running standard operations..."
    
    python3 -m venv env  
    source env/bin/activate
    pip install -r requirements.txt
    python3 -m pip install mypy
    pip install --upgrade pip
    python3 -m pip install --no-deps types-docker
    python3 -m pip install --no-deps types-requests

fi