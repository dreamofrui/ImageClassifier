@echo off
setlocal

echo ====================================
echo ImageClassifier build
echo ====================================
echo.

echo [1/4] Cleaning previous build output...
if exist "build" rmdir /s /q "build"
if errorlevel 1 goto :build_failed
if exist "dist" rmdir /s /q "dist"
if errorlevel 1 goto :build_failed
echo Clean complete.
echo.

echo [2/4] Running PyInstaller...
D:\miniforge3\envs\tool\python.exe -m PyInstaller ImageClassifier.spec --clean
if errorlevel 1 goto :build_failed
echo PyInstaller complete.
echo.

echo [3/4] Copying release assets...
copy /Y "config.json" "dist\config.json" > nul
if errorlevel 1 goto :build_failed
copy /Y "USER_GUIDE.md" "dist\USER_GUIDE.md" > nul
if errorlevel 1 goto :build_failed
echo Release assets copied.
echo.

echo [4/4] Creating release package...
cd dist
if errorlevel 1 goto :build_failed
if exist "ImageClassifier_Release" rmdir /s /q "ImageClassifier_Release"
if errorlevel 1 goto :build_failed
mkdir "ImageClassifier_Release"
if errorlevel 1 goto :build_failed
move "ImageClassifier.exe" "ImageClassifier_Release\" > nul
if errorlevel 1 goto :build_failed
copy /Y "..\config.json" "ImageClassifier_Release\" > nul
if errorlevel 1 goto :build_failed
copy /Y "..\USER_GUIDE.md" "ImageClassifier_Release\" > nul
if errorlevel 1 goto :build_failed
if exist "config.json" del "config.json"
if errorlevel 1 goto :build_failed
if exist "USER_GUIDE.md" del "USER_GUIDE.md"
if errorlevel 1 goto :build_failed

echo.
echo ====================================
echo Build succeeded.
echo Release folder: dist\ImageClassifier_Release\
echo Files:
echo   - ImageClassifier.exe
echo   - config.json
echo   - USER_GUIDE.md
echo ====================================
echo.

endlocal
exit /b 0

:build_failed
echo.
echo ====================================
echo Build failed.
echo See the message above for the failing command.
echo ====================================
echo.
endlocal
exit /b 1
