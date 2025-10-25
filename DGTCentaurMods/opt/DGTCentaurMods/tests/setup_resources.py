#!/usr/bin/env python3
"""
Resource Setup Script for Promotion Tests

This script sets up the required resource paths so that AssetManager
can find the font files when running tests.

USAGE:
    # Navigate to opt folder
    cd /home/pi/DGTCentaurMods/DGTCentaurMods/opt
    
    # Activate virtual environment
    source DGTCentaurMods/.venv/bin/activate
    
    # Run this script to set up resources
    python3 DGTCentaurMods/tests/setup_resources.py
    
    # Then run your tests
    python3 DGTCentaurMods/tests/test_promotion_hardware.py --hardware
"""

import os
import sys
import shutil

def setup_resources():
    """Set up resource paths for AssetManager"""
    print("Setting up resource paths for AssetManager...")
    
    # Current working directory should be /home/pi/DGTCentaurMods/DGTCentaurMods/opt
    current_dir = os.getcwd()
    print(f"Current directory: {current_dir}")
    
    # Source resources directory
    source_resources = os.path.join(current_dir, "DGTCentaurMods", "resources")
    print(f"Source resources: {source_resources}")
    
    # Check if source resources exist
    if not os.path.exists(source_resources):
        print(f"ERROR: Source resources directory not found: {source_resources}")
        return False
    
    # Target directories that AssetManager looks for
    target_dirs = [
        "/home/pi/resources",
        "/opt/DGTCentaurMods/resources"
    ]
    
    success = True
    for target_dir in target_dirs:
        print(f"\nSetting up: {target_dir}")
        
        # Create target directory if it doesn't exist
        try:
            os.makedirs(target_dir, exist_ok=True)
            print(f"  Created directory: {target_dir}")
        except PermissionError:
            print(f"  WARNING: Cannot create {target_dir} - permission denied")
            print(f"  You may need to run: sudo mkdir -p {target_dir}")
            success = False
            continue
        
        # Copy resources to target directory
        try:
            # Copy each file individually to avoid overwriting existing files unnecessarily
            for filename in os.listdir(source_resources):
                source_file = os.path.join(source_resources, filename)
                target_file = os.path.join(target_dir, filename)
                
                if os.path.isfile(source_file):
                    if not os.path.exists(target_file):
                        shutil.copy2(source_file, target_file)
                        print(f"  Copied: {filename}")
                    else:
                        print(f"  Exists: {filename}")
                        
        except PermissionError:
            print(f"  WARNING: Cannot copy files to {target_dir} - permission denied")
            print(f"  You may need to run: sudo cp -r {source_resources}/* {target_dir}/")
            success = False
    
    return success

def verify_resources():
    """Verify that required resources are available"""
    print("\nVerifying resources...")
    
    required_files = ["Font.ttc"]
    target_dirs = [
        "/home/pi/resources",
        "/opt/DGTCentaurMods/resources"
    ]
    
    all_found = True
    for target_dir in target_dirs:
        print(f"\nChecking: {target_dir}")
        if os.path.exists(target_dir):
            for filename in required_files:
                file_path = os.path.join(target_dir, filename)
                if os.path.exists(file_path):
                    print(f"  ✓ Found: {filename}")
                else:
                    print(f"  ✗ Missing: {filename}")
                    all_found = False
        else:
            print(f"  ✗ Directory does not exist")
            all_found = False
    
    return all_found

def main():
    """Main function"""
    print("DGTCentaurMods Resource Setup")
    print("=" * 40)
    
    # Set up resources
    if setup_resources():
        print("\n✓ Resource setup completed successfully")
    else:
        print("\n✗ Resource setup had issues - check permissions")
    
    # Verify resources
    if verify_resources():
        print("\n✓ All required resources are available")
        print("\nYou can now run your tests!")
        return 0
    else:
        print("\n✗ Some resources are missing")
        print("\nManual setup required:")
        print("  sudo mkdir -p /home/pi/resources /opt/DGTCentaurMods/resources")
        print("  sudo cp -r DGTCentaurMods/resources/* /home/pi/resources/")
        print("  sudo cp -r DGTCentaurMods/resources/* /opt/DGTCentaurMods/resources/")
        return 1

if __name__ == "__main__":
    sys.exit(main())
