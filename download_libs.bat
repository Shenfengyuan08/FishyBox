@echo off
cd /d "%~dp0"
echo [1/4] downloading marked.min.js ...
curl -sL --max-time 60 -o "static\marked.min.js" "https://registry.npmmirror.com/marked/11.2.0/files/marked.min.js"
echo [2/4] downloading purify.min.js ...
curl -sL --max-time 60 -o "static\purify.min.js" "https://registry.npmmirror.com/dompurify/3.1.6/files/dist/purify.min.js"
echo [3/4] downloading highlight.min.js ...
curl -sL --max-time 60 -o "static\highlight.min.js" "https://registry.npmmirror.com/@highlightjs/cdn-assets/11.9.0/files/highlight.min.js"
echo [4/4] downloading highlight.min.css ...
curl -sL --max-time 60 -o "static\highlight.min.css" "https://registry.npmmirror.com/@highlightjs/cdn-assets/11.9.0/files/styles/github.min.css"
echo.
echo ==== Result (0 bytes = FAILED) ====
dir "static\marked.min.js" "static\purify.min.js" "static\highlight.min.js" "static\highlight.min.css"
pause
