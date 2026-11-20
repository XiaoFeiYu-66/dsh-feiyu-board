@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

rem 优先用 venv 里的 fyb 命令；没有就用启动器 fyb.py（任何目录都能跑）
if exist ".venv\Scripts\fyb.exe" (
  ".venv\Scripts\fyb.exe" %*
  goto :done
)
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" "%~dp0fyb.py" %*
  goto :done
)
echo 还没装。先双击 安装.cmd
pause
exit /b 1

:done
endlocal
