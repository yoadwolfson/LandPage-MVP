#!/usr/bin/env python
"""
Wrapper script to run the agent from project root.
Ensures Python path includes the project directory.
"""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Now import and run
from agent.main import main

if __name__ == '__main__':
    main()
