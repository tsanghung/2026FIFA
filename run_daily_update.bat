@echo off
cd /d "%~dp0"
python sync_fifa.py
python external_predictions.py
python build_static.py
