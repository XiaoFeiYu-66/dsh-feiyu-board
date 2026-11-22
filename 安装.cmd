@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ================================================
echo   小飞鱼画板 · 安装
echo ================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo [!] 没找到 python
  echo     请先装 Python 3.10 或更高版本，安装时勾选 "Add python.exe to PATH"
  echo     下载：https://www.python.org/downloads/
  pause
  exit /b 1
)
for /f "delims=" %%v in ('python -c "import sys;print(sys.version.split()[0])"') do set PYVER=%%v
echo [i] 用的是 Python %PYVER%

if exist ".venv\Scripts\python.exe" (
  echo [i] 虚拟环境已存在，直接用
  goto :deps
)
echo [1/3] 建虚拟环境 .venv ...
python -m venv .venv
if errorlevel 1 (
  echo [!] 建虚拟环境失败
  pause
  exit /b 1
)

:deps
echo [2/3] 装依赖（PySide6 约 100MB，慢一点）...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo [!] 直接装失败，换清华镜像再试一次...
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
  if errorlevel 1 (
    echo [!] 还是失败，检查一下网络
    pause
    exit /b 1
  )
)

echo [3/3] 试渲染一张，确认能跑...
".venv\Scripts\python.exe" "%~dp0fyb.py" render scenes\apple.fyb --out renders\apple.png --scale 1
if errorlevel 1 (
  echo [!] 渲染失败，但依赖装好了。可以试：
  echo     fyb.cmd check scenes\apple.fyb
  pause
  exit /b 1
)

echo.
echo ================================================
echo   装好了。
echo.
echo   用法（用完整路径调用 fyb.cmd 即可）：
echo     fyb.cmd check  scenes\apple.fyb
echo     fyb.cmd render scenes\apple.fyb --out renders\apple.png
echo     fyb.cmd balance scenes\room.fyb
echo.
echo   想更方便：把这个目录加到 PATH，之后直接敲 fyb
echo   语法手册看 DSL.md，例子在 scenes\ 里
echo   要把它装进 DSH 当插件（带网页面板），看 plugin\README.md
echo ================================================
pause
