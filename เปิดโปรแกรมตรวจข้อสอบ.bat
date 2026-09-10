@echo off
chcp 65001 >nul
title ระบบตรวจข้อสอบอูคูเลเล่
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
rem เช็คตัวที่ต้องใช้จริง — anthropic คือตัวที่ใช้อ่านลายมือกับตรวจข้อบรรยาย
rem ส่วน pillow_heif ใช้แปลงรูป .heic ของ iPhone (ใส่ไว้ด้วยเพื่อให้เครื่องที่ติดตั้ง
rem ไปแล้วก่อนหน้านี้ได้ของใหม่โดยไม่ต้องพิมพ์คำสั่งเอง)
%PYEXE% -c "import flask, cv2, pypdf, anthropic, pillow_heif, qrcode" >nul 2>nul
if errorlevel 1 (
    echo.
    echo   ครั้งแรกในเครื่องนี้ ต้องติดตั้งไลบรารีก่อน รอสัก 2-3 นาที...
    echo.
    %PYEXE% -m pip install -r requirements.txt
    if errorlevel 1 goto pipfailed
)

echo.
echo   กำลังเปิดระบบตรวจข้อสอบ รอสักครู่...
echo   เบราว์เซอร์จะเปิดขึ้นมาเอง ถ้าไม่ขึ้น ให้ดูลิงก์ที่พิมพ์ด้านล่าง
echo.
%PYEXE% web_app.py
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
