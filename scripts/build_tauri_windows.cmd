@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_tauri_windows.ps1" %*
