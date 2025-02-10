"""Main entry point for the trading application"""
import sys
from pathlib import Path

# Add the project root directory to Python path
root_dir = Path(__file__).resolve().parent
sys.path.append(str(root_dir))

# Now we can import our modules
from ui.dashboard import main

if __name__ == "__main__":
    main()
