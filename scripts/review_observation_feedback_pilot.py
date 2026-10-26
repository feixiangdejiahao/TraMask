"""Offline review entry point for observation-only feedback presentation."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from scripts import run_observation_feedback_pilot as experiment
from scripts import review_validation_evolution_pilot as review
review.RUN=experiment.RUN
review.EVAL=experiment.RUN/'evaluation'
review.ARMS=['E_observations']
review.check=experiment.check
if __name__=='__main__':review.main()
