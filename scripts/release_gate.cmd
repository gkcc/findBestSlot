@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0release_gate.ps1" %*
