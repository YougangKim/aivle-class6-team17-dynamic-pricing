$ErrorActionPreference = "Stop"

if (-not (Test-Path ".venv")) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) {
        $pythonCommand = Get-Command py -ErrorAction SilentlyContinue
    }
    if (-not $pythonCommand) {
        throw "Python을 찾을 수 없습니다. Python 3.12 이상을 설치한 뒤 다시 실행해주세요."
    }
    & $pythonCommand.Source -m venv .venv
}

& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
& .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8010
