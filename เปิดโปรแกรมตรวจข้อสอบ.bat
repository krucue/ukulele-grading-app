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

echo.
echo   กำลังเปิดระบบตรวจข้อสอบ รอสักครู่...
echo   เบราว์เซอร์จะเปิดขึ้นมาเอง ถ้าไม่ขึ้น ให้ดูลิงก์ที่พิมพ์ด้านล่าง
echo.
%PYEXE% web_app.py
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
