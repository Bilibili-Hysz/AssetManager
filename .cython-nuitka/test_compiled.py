#!/usr/bin/env python
"""Test if the compiled application can run with Qt plugins."""
import subprocess
import sys
import os
import time


def test_run():
    """Test if the application can run."""
    dist_dir = "dist"
    exe_path = os.path.join(dist_dir, "AssetManager.exe")
    
    if not os.path.exists(exe_path):
        print(f"ERROR: {exe_path} not found!")
        return False
    
    # Set Qt plugin path
    env = os.environ.copy()
    env["QT_PLUGIN_PATH"] = os.path.join(dist_dir, "main.dist", "PySide6", "plugins")
    
    print(f"Testing: {exe_path}")
    print(f"Qt plugin path: {env['QT_PLUGIN_PATH']}")
    
    # Verify Qt plugins exist
    qwindows_path = os.path.join(env["QT_PLUGIN_PATH"], "platforms", "qwindows.dll")
    if os.path.exists(qwindows_path):
        print(f"[OK] qwindows.dll found at: {qwindows_path}")
    else:
        print(f"[FAIL] qwindows.dll not found at: {qwindows_path}")
        return False
    
    try:
        # Try to run the application for a few seconds
        print("\nStarting application...")
        result = subprocess.Popen(
            [exe_path],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # Wait a bit to see if it starts
        time.sleep(5)
        
        # Check if process is still running
        if result.poll() is None:
            print("[SUCCESS] Application started successfully!")
            print(f"The application is running (PID: {result.pid})")
            result.terminate()
            return True
        else:
            print(f"[FAILED] Application exited with code {result.returncode}")
            stdout, stderr = result.communicate()
            if stdout:
                print(f"STDOUT: {stdout.decode()}")
            if stderr:
                print(f"STDERR: {stderr.decode()}")
            return False
            
    except Exception as e:
        print(f"[ERROR] {e}")
        return False


if __name__ == "__main__":
    success = test_run()
    if success:
        print("\n" + "="*60)
        print("The compiled application works correctly!")
        print("="*60)
        print("\nTo run the application:")
        print("  1. Double-click dist/AssetManager.bat")
        print("  2. Or run dist/AssetManager.ps1")
        print("\nThe launcher will set the Qt plugin path automatically.")
    else:
        print("\n" + "="*60)
        print("The application failed to start.")
        print("="*60)
    sys.exit(0 if success else 1)