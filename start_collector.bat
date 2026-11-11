@echo off
cd /d %~dp0
python -m ahtracker.collector --loop
