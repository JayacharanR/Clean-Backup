import json
import os
from pathlib import Path

CONFIG_FILE = Path("config.json")
DEFAULT_CONFIG = {
    "phash_threshold": 10
}

def load_config():
    """Load configuration from JSON file. Returns default if not found."""
    if not CONFIG_FILE.exists():
        return DEFAULT_CONFIG.copy()
    
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
            # Merge with defaults to ensure all keys exist
            return {**DEFAULT_CONFIG, **config}
    except Exception as e:
        print(f"Error loading config: {e}. Using defaults.")
        return DEFAULT_CONFIG.copy()

def save_config(key, value):
    """Update a specific config key and save to file."""
    config = load_config()
    config[key] = value
    
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)
        return True
    except Exception as e:
        print(f"Error saving config: {e}")
        return False

def get_threshold():
    """Get the persistent threshold value."""
    config = load_config()
    return config.get("phash_threshold", 10)
