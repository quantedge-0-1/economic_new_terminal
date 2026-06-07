# Economic News Terminal — Launcher
# Arranca backend + frontend y abre el navegador automaticamente

$projectRoot = "C:\Users\Lenovo Ideapad\OneDrive\Desktop\workspace\economic_news_terminal"
$python      = "C:\Users\Lenovo Ideapad\AppData\Local\Programs\Python\Python311\python.exe"

# Liberar puertos si hay procesos huerfanos
$p8001 = Get-NetTCPConnection -LocalPort 8001 -ErrorAction SilentlyContinue
if ($p8001) {
    Stop-Process -Id $p8001.OwningProcess -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}
$p3000 = Get-NetTCPConnection -LocalPort 3000 -ErrorAction SilentlyContinue
if ($p3000) {
    Stop-Process -Id $p3000.OwningProcess -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}

# Arrancar backend
Start-Process powershell -ArgumentList "-NoExit", "-Command",
    "cd '$projectRoot\backend'; & '$python' -m uvicorn app.main:app --host 0.0.0.0 --port 8001"

# Arrancar frontend
Start-Process powershell -ArgumentList "-NoExit", "-Command",
    "cd '$projectRoot\frontend'; npm run dev"

# Esperar a que ambos levanten
Start-Sleep -Seconds 6

# Abrir navegador
Start-Process "http://localhost:3000"
