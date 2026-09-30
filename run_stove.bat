@echo off
chcp 65001 > nul
echo ============================================================
echo  SecretShopBot-E7 (STOVE Mode)
echo ============================================================
echo.
"%~dp0.venv\Scripts\python.exe" "%~dp0main.py" --stove
