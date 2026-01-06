@echo off
chcp 65001 > nul
title 재무제표 챗봇 - 설치

cd /d "%~dp0"

echo ========================================
echo    재무제표 챗봇 설치
echo ========================================
echo.

echo [1/2] 패키지 설치 중...
pip install -r requirements.txt

echo.
echo [2/2] 환경 설정 파일 생성 중...
if not exist ".env" (
    copy .env.example .env
    echo .env 파일이 생성되었습니다.
    echo .env 파일을 열어 ANTHROPIC_API_KEY를 설정하세요.
) else (
    echo .env 파일이 이미 존재합니다.
)

echo.
echo ========================================
echo    설치 완료!
echo ========================================
echo.
echo 다음 단계:
echo 1. .env 파일에 Claude API 키를 입력하세요
echo 2. run.bat을 실행하여 앱을 시작하세요
echo.

pause
