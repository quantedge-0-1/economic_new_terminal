# Economic News Terminal — Launcher (modo silencioso)
# Arranca backend + frontend en segundo plano y abre el navegador

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

# Arrancar backend en segundo plano (sin ventana)
Start-Process -FilePath $python `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001" `
    -WorkingDirectory "$projectRoot\backend" `
    -WindowStyle Hidden

# Arrancar frontend en segundo plano (sin ventana)
Start-Process -FilePath "cmd.exe" `
    -ArgumentList "/c", "npm run dev" `
    -WorkingDirectory "$projectRoot\frontend" `
    -WindowStyle Hidden

# Esperar a que levanten
Start-Sleep -Seconds 7

# Abrir navegador
Start-Process "http://localhost:3000"
