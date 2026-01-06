@echo off
chcp 65001 > nul
title 재무제표 챗봇

cd /d "%~dp0"

echo ========================================
echo    재무제표 분석 챗봇 실행 중...
echo ========================================
echo.

streamlit run app.py

pause
