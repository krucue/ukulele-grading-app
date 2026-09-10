@echo off
chcp 65001 >nul
title ระบบตรวจข้อสอบอูคูเลเล่ (เปิดให้มือถือใช้ได้)
cd /d "%~dp0"

rem หา Python ในเครื่อง — ตัวติดตั้งจาก python.org ให้ทั้ง py และ python
rem แต่จาก Microsoft Store ให้แค่ python เท่านั้น จึงต้องลองทั้งสองแบบ
set "PYEXE="
where py >nul 2>nul
if not errorlevel 1 set "PYEXE=py"
if not defined PYEXE (
    where python >nul 2>nul
    if not errorlevel 1 set "PYEXE=python"
)
if not defined PYEXE goto nopython

rem ครั้งแรกในเครื่องใหม่จะยังไม่มีไลบรารี ติดตั้งให้เลยดีกว่าปล่อยให้พังตอนกดตรวจ
rem เช็คทั้ง 4 ตัวที่ต้องใช้จริง — anthropic คือตัวที่ใช้อ่านลายมือกับตรวจข้อบรรยาย
%PYEXE% -c "import flask, cv2, pypdf, anthropic" >nul 2>nul
if errorlevel 1 (
    echo.
    echo   ครั้งแรกในเครื่องนี้ ต้องติดตั้งไลบรารีก่อน รอสัก 2-3 นาที...
    echo.
    %PYEXE% -m pip install -r requirements.txt
    if errorlevel 1 goto pipfailed
)

echo.
echo   กำลังเปิดระบบตรวจข้อสอบ แบบเปิดให้มือถือใช้ได้ รอสักครู่...
echo   เบราว์เซอร์บนคอมจะเปิดขึ้นมาเอง ส่วนมือถือให้สแกน QR ที่พิมพ์ด้านล่าง
echo.
echo   ครั้งแรกที่เปิด Windows จะถามว่าจะอนุญาตให้ Python ใช้เครือข่ายไหม
echo   ต้องกด Allow และติ๊ก Private networks ไม่งั้นมือถือจะเข้าไม่ได้
echo.
%PYEXE% web_app.py --มือถือ
goto done

:pipfailed
echo.
echo ======================================================================
echo   ติดตั้งไลบรารีไม่สำเร็จ
echo ======================================================================
echo.
echo   ลองเปิด PowerShell ที่โฟลเดอร์นี้แล้วพิมพ์คำสั่งนี้เอง เพื่อดูข้อความเต็ม ๆ:
echo       python -m pip install -r requirements.txt
echo.
echo   ถ้าติดที่เน็ตของโรงเรียนบล็อกไว้ ให้ลองเน็ตมือถือแทน
echo.
goto done

:nopython
echo.
echo ======================================================================
echo   ยังไม่ได้ติดตั้ง Python ในเครื่องนี้
echo ======================================================================
echo.
echo   ดาวน์โหลดที่ https://www.python.org/downloads/
echo   ตอนติดตั้ง อย่าลืมติ๊กช่อง "Add Python to PATH" ด้วย
echo.

:done
echo.
echo   โปรแกรมปิดแล้ว — กดปุ่มอะไรก็ได้เพื่อปิดหน้าต่างนี้
pause >nul
