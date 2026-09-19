"""Print static delivery requirements for native release scripts."""
from dataclasses import asdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from delivery import delivery_plan

if __name__ == '__main__':
    print(json.dumps(asdict(delivery_plan(sys.platform))))
