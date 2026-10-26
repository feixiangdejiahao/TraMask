"""Offline review of the same-file append corrected evolution pilot."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/"src"), str(ROOT)]
from scripts import run_validation_evolution_pilot_v3 as experiment
from scripts import review_validation_evolution_pilot as review
review.RUN = experiment.RUN
review.EVAL = experiment.RUN/"evaluation"
if __name__ == "__main__": review.main()
