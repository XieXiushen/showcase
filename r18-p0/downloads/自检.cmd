@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
rem ===================================================================
rem  R15-C1 landing-page kit: three-check self test for local vision server
rem  Usage: 自检.cmd [full path of llama-server.exe]
rem  Check 1: is the CUDA runtime dll next to the exe (same directory)?
rem  Check 2: nvidia-smi memory usage + list of GPU processes
rem  Check 3: resident VRAM after model load, vs expected band
rem  Expected band and its sources are documented in 说明.md
rem ===================================================================

set "EXE=%~1"
if "%EXE%"=="" set "EXE=%~dp0llama-server.exe"

echo ============================================================
echo  本地视觉服务自检（三段判据）
echo  目标程序: %EXE%
echo  时间: %DATE% %TIME%
echo ============================================================
echo.

rem ---------- check 1 ----------
echo [判据一] 启动目录与 CUDA DLL 位置
echo ------------------------------------------------------------
if not exist "%EXE%" goto j1_missing
for %%F in ("%EXE%") do set "EXEDIR=%%~dpF"
echo   启动目录  : %EXEDIR%
echo   同级 DLL  :
dir /b "%EXEDIR%*.dll" 2>nul
echo.
echo   cuda_v13 子目录 DLL :
if exist "%EXEDIR%cuda_v13" goto j1_sub
echo     (无 cuda_v13 子目录)
goto j1_check
:j1_sub
dir /b "%EXEDIR%cuda_v13\*.dll" 2>nul
goto j1_check
:j1_missing
echo   [FAIL] 找不到 %EXE%
echo   用法: 自检.cmd "D:\ollama\bin\llama-server.exe"
goto judge2
:j1_check
echo.
set "CUDASAME=0"
if exist "%EXEDIR%ggml-cuda.dll" set "CUDASAME=1"
if exist "%EXEDIR%cublas64_13.dll" set "CUDASAME=1"
if "%CUDASAME%"=="1" goto j1_ok
echo   判定: [风险] exe 同级没有 ggml-cuda.dll / cublas64_13.dll。
echo         若它们只躺在 cuda_v13 子目录里，llama.cpp 在 Windows 上不会进子目录找，
echo         启动日志会出现 "no usable GPU found, --gpu-layers option will be ignored"，
echo         模型会全部跑在 CPU 上且进程不报错。解法：把整个目录（含 cuda_v13）复制/
echo         链接到一个 exe 与 DLL 同级的目录，再从该目录启动。
goto judge2
:j1_ok
echo   判定: [OK] CUDA 运行库与 exe 同级，-ngl 99 有机会生效。

:judge2
echo.
echo [判据二] nvidia-smi 显存占用与占显存进程清单
echo ------------------------------------------------------------
where nvidia-smi >nul 2>nul
if errorlevel 1 goto j2_skip
nvidia-smi --query-gpu=name,driver_version,memory.used,memory.total --format=csv
echo.
nvidia-smi
goto judge3
:j2_skip
echo   [SKIP] PATH 里没有 nvidia-smi，请先安装 NVIDIA 驱动。

:judge3
echo.
echo [判据三] 模型加载后驻留显存（每约 1 秒采样一次，共 12 次取峰值）
echo ------------------------------------------------------------
where nvidia-smi >nul 2>nul
if errorlevel 1 goto j3_skip
set "PEAK=0"
set "LAST=0"
for /L %%I in (1,1,12) do (
  nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits > "%TEMP%\r15_selfcheck_used.txt" 2>nul
  set "USED="
  set /p USED=<"%TEMP%\r15_selfcheck_used.txt"
  set "USED=!USED: =!"
  set "LAST=!USED!"
  if !USED! GTR !PEAK! set "PEAK=!USED!"
  ping -n 2 127.0.0.1 >nul
)
echo   最后一次采样: !LAST! MiB
echo   采样峰值    : !PEAK! MiB
if !PEAK! LSS 2000 goto j3_fail
if !PEAK! LSS 6000 goto j3_warn
if !PEAK! LEQ 9500 goto j3_ok
goto j3_high
:j3_fail
echo   判定: [FAIL] 可能已退化 CPU —— 显存只占 !PEAK! MiB，那是桌面自己占的，
echo         权重根本没上卡。先回判据一确认 CUDA DLL 位置，再看启动日志有没有
echo         "no usable GPU found" 或 "-ngl 99 被忽略" 的字样。
goto done
:j3_warn
echo   判定: [WARN] !PEAK! MiB 未落在预期区间（本机预期 6284-8369 MiB）。
echo         可能只卸载了部分层，检查 -ngl 参数与其他占显存的程序。
goto done
:j3_ok
echo   判定: [OK] 权重已上卡(本机 G4 组记录: 加载 8268 / 峰值 8369 MiB, 见 result-G4.json)
goto done
:j3_high
echo   判定: [WARN] !PEAK! MiB 高于预期区间，先关掉其他占显存的程序再测一次。
goto done
:j3_skip
echo   [SKIP] PATH 里没有 nvidia-smi。

:done
echo.
echo ============================================================
echo  三段判据跑完。任一段 FAIL 都不要发稿/交付，先修再测。
echo ============================================================
endlocal
