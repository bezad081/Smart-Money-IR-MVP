@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv
)
call .venv\Scripts\activate.bat

python -m pip install --upgrade pip
pip install -r requirements-notebook.txt
python -m jupyter lab notebooks/Smart_Money_IR.ipynb
