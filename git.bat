@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul

set "GITHUB_USER=Chunn241529"
set "REMOTE=origin"
set "BRANCH_MAIN=main"
for /f "delims=#" %%A in ('"prompt #$E# & for %%B in (1) do rem"') do set "ESC=%%A"
set "RESET=%ESC%[0m"
set "BOLD=%ESC%[1m"
set "CYAN=%ESC%[96m"
set "GREEN=%ESC%[92m"
set "YELLOW=%ESC%[93m"
set "GRAY=%ESC%[90m"

where git.exe >nul 2>&1 || (
    echo [LỖI] Không tìm thấy Git trong PATH.
    exit /b 1
)

if "%~1"=="" goto help
if /i "%~1"=="help" goto help
if /i "%~1"=="-h" goto help
if /i "%~1"=="--help" goto help
if /i "%~1"=="--install-completion" goto install_completion
if /i "%~1"=="init" goto init
if /i "%~1"=="commit" goto commit
if /i "%~1"=="push" goto push
if /i "%~1"=="branch" goto branch
if /i "%~1"=="checkout" goto checkout
if /i "%~1"=="merge" goto merge
if /i "%~1"=="history" goto history
if /i "%~1"=="log" goto history
if /i "%~1"=="revert" goto revert
if /i "%~1"=="reset" goto reset
if /i "%~1"=="tag" goto tag
if /i "%~1"=="stash" goto stash
if /i "%~1"=="diff" goto diff
if /i "%~1"=="status" goto status
echo [LỖI] Lệnh không hợp lệ: "%~1"
echo Chạy git.bat help để xem hướng dẫn.
exit /b 1

:require_repo
git.exe rev-parse --is-inside-work-tree >nul 2>&1
if not errorlevel 1 exit /b 0
echo [LỖI] Thư mục hiện tại chưa phải Git repository.
exit /b 1

:setup_config
git.exe config --get user.name >nul 2>&1
if errorlevel 1 (
    call :configure_user_name || exit /b 1
)
git.exe config --get user.email >nul 2>&1
if errorlevel 1 (
    call :configure_user_email || exit /b 1
)
exit /b 0

:configure_user_name
set /p "USER_NAME=Nhập tên Git user: "
if not defined USER_NAME exit /b 1
git.exe config --global user.name "%USER_NAME%"
exit /b %errorlevel%

:configure_user_email
set /p "USER_EMAIL=Nhập email: "
if not defined USER_EMAIL exit /b 1
git.exe config --global user.email "%USER_EMAIL%"
exit /b %errorlevel%

:init
echo %CYAN%[INIT] Bắt đầu khởi tạo Git repository...%RESET%
call :setup_config || exit /b 1
for %%I in ("%CD%") do set "DEFAULT_REPO=%%~nxI"
set "REPO_NAME=%~2"
if not defined REPO_NAME set "REPO_NAME=%DEFAULT_REPO%"
set "REMOTE_URL=https://github.com/%GITHUB_USER%/%REPO_NAME%.git"
echo Repository: %REPO_NAME%
echo Remote:     %REMOTE_URL%
echo.

call :validate_git_state || exit /b 1
git.exe rev-parse --git-dir >nul 2>&1
if not errorlevel 1 goto init_existing
echo %YELLOW%[1/4] Đang kiểm tra repository trên GitHub...%RESET%
git.exe ls-remote "%REMOTE_URL%" >nul 2>&1
if errorlevel 1 goto init_new

echo %YELLOW%[2/4] Remote đã tồn tại, đang lấy Git metadata...%RESET%
git.exe init || exit /b 1
git.exe remote add "%REMOTE%" "%REMOTE_URL%" || exit /b 1
git.exe fetch "%REMOTE%" || exit /b 1
git.exe checkout -b "%BRANCH_MAIN%" "%REMOTE%/%BRANCH_MAIN%" >nul 2>&1
if errorlevel 1 git.exe checkout -b "%BRANCH_MAIN%" >nul 2>&1
echo [OK] Đã đồng bộ metadata với remote repository.
goto init_push

:init_new
echo %YELLOW%[2/4] Không tìm thấy remote; đang tạo repository local...%RESET%
git.exe init || exit /b 1
git.exe branch -M "%BRANCH_MAIN%" || exit /b 1
>README.md echo # %REPO_NAME%
call :ensure_gitignore || exit /b 1
git.exe add README.md .gitignore && git.exe commit -m "Initial commit" || exit /b 1
git.exe remote add "%REMOTE%" "%REMOTE_URL%" || exit /b 1
echo [OK] Repository đã được khởi tạo.
goto init_push

:init_existing
echo %YELLOW%[2/4] Repository local đã tồn tại; đang kiểm tra remote...%RESET%
git.exe remote get-url "%REMOTE%" >nul 2>&1
if errorlevel 1 (
    git.exe remote add "%REMOTE%" "%REMOTE_URL%" || exit /b 1
) else (
    call :update_remote_url || exit /b 1
)

:init_push
echo %YELLOW%[3/4] Đang chuẩn bị .gitignore...%RESET%
call :ensure_gitignore || exit /b 1
echo %YELLOW%[4/4] Đang push branch "%BRANCH_MAIN%" lên GitHub...%RESET%
git.exe push -u "%REMOTE%" "%BRANCH_MAIN%"
if errorlevel 1 echo [CẢNH BÁO] Chưa thể push; hãy commit code rồi push lại.
echo [OK] Repository đã sẵn sàng.
exit /b 0

:validate_git_state
if not exist ".git" exit /b 0
git.exe rev-parse --git-dir >nul 2>&1
if not errorlevel 1 exit /b 0
rmdir ".git" >nul 2>&1
if exist ".git" (
    echo [LỖI] Thư mục .git tồn tại nhưng không phải repository hợp lệ.
    echo        Dữ liệu bên trong được giữ nguyên để tránh mất lịch sử.
    exit /b 1
)
echo [CẢNH BÁO] Đã dọn thư mục .git rỗng từ lần init bị gián đoạn.
exit /b 0

:update_remote_url
for /f "delims=" %%U in ('git.exe remote get-url "%REMOTE%"') do set "CURRENT_URL=%%U"
if /i "%CURRENT_URL%"=="%REMOTE_URL%" exit /b 0
git.exe remote set-url "%REMOTE%" "%REMOTE_URL%"
exit /b %errorlevel%

:ensure_gitignore
if exist ".gitignore" exit /b 0
> ".gitignore" (
    echo # Operating systems
    echo .DS_Store
    echo Thumbs.db
    echo Desktop.ini
    echo $RECYCLE.BIN/
    echo.
    echo # Editors and IDEs
    echo .idea/
    echo .vscode/
    echo *.swp
    echo *.swo
    echo *~
    echo *.suo
    echo *.user
    echo *.userosscache
    echo *.sln.docstates
    echo.
    echo # Secrets and local environment
    echo .env
    echo .env.*
    echo !.env.example
    echo !.env.sample
    echo *.pem
    echo *.key
    echo *.p12
    echo *.pfx
    echo.
    echo # Logs, temporary files and coverage
    echo *.log
    echo logs/
    echo tmp/
    echo temp/
    echo .cache/
    echo coverage/
    echo .coverage
    echo htmlcov/
    echo.
    echo # Python
    echo __pycache__/
    echo *.py[cod]
    echo *.pyd
    echo .pytest_cache/
    echo .mypy_cache/
    echo .ruff_cache/
    echo .tox/
    echo .nox/
    echo .venv/
    echo venv/
    echo env/
    echo *.egg-info/
    echo dist/
    echo build/
    echo.
    echo # JavaScript and TypeScript
    echo node_modules/
    echo .npm/
    echo .yarn/cache/
    echo .pnpm-store/
    echo .next/
    echo .nuxt/
    echo .svelte-kit/
    echo .parcel-cache/
    echo .turbo/
    echo *.tsbuildinfo
    echo.
    echo # Java, Kotlin and Gradle
    echo .gradle/
    echo out/
    echo *.class
    echo *.jar
    echo *.war
    echo *.ear
    echo.
    echo # .NET
    echo [Bb]in/
    echo [Oo]bj/
    echo [Dd]ebug/
    echo [Rr]elease/
    echo packages/
    echo TestResults/
    echo.
    echo # Go
    echo *.test
    echo *.out
    echo go.work
    echo.
    echo # Rust
    echo target/
    echo **/*.rs.bk
    echo.
    echo # Ruby
    echo .bundle/
    echo vendor/bundle/
    echo .byebug_history
    echo.
    echo # PHP and Composer
    echo vendor/
    echo .phpunit.result.cache
    echo.
    echo # C, C++ and CMake
    echo *.o
    echo *.obj
    echo *.a
    echo *.lib
    echo *.so
    echo *.dll
    echo *.dylib
    echo *.exe
    echo CMakeFiles/
    echo CMakeCache.txt
    echo cmake-build-*/
    echo.
    echo # Swift and Xcode
    echo .build/
    echo DerivedData/
    echo *.xcworkspace/xcuserdata/
    echo *.xcodeproj/xcuserdata/
    echo.
    echo # Dart and Flutter
    echo .dart_tool/
    echo .flutter-plugins
    echo .flutter-plugins-dependencies
    echo .packages
    echo.
    echo # Infrastructure tools
    echo .terraform/
    echo *.tfstate
    echo *.tfstate.*
    echo .serverless/
    echo .aws-sam/
)
echo [OK] Đã tạo .gitignore đa ngôn ngữ.
exit /b 0

:commit
call :require_repo || exit /b 1
call :setup_config || exit /b 1
set "COMMIT_MSG=%~2"
if not defined COMMIT_MSG set /p "COMMIT_MSG=Nhập commit message: "
if not defined COMMIT_MSG (
    echo [LỖI] Commit message không được để trống.
    exit /b 1
)
for /f "delims=" %%B in ('git.exe branch --show-current') do set "CURRENT_BRANCH=%%B"
git.exe pull "%REMOTE%" "%CURRENT_BRANCH%" --no-rebase >nul 2>&1
if errorlevel 1 echo [CẢNH BÁO] Không thể pull; remote có thể chưa tồn tại hoặc đây là branch mới.
call :clear_pycache
git.exe add -A || exit /b 1
git.exe diff --cached --quiet
if not errorlevel 1 (
    echo [CẢNH BÁO] Không có thay đổi để commit.
    exit /b 0
)
git.exe commit -m "%COMMIT_MSG%" || exit /b 1
echo [OK] Đã commit: "%COMMIT_MSG%"
exit /b 0

:clear_pycache
set /a CACHE_COUNT=0
for /d /r %%D in (__pycache__) do if exist "%%D\" (
    rmdir /s /q "%%D"
    set /a CACHE_COUNT+=1
)
echo [OK] Đã dọn %CACHE_COUNT% thư mục __pycache__.
exit /b 0

:push
call :require_repo || exit /b 1
for /f "delims=" %%B in ('git.exe branch --show-current') do set "CURRENT_BRANCH=%%B"
if not defined CURRENT_BRANCH (
    echo [LỖI] Không xác định được branch hiện tại.
    exit /b 1
)
set "FORCE_FLAG="
if /i "%~2"=="-f" goto confirm_force
if /i "%~2"=="--force" goto confirm_force
git.exe pull "%REMOTE%" "%CURRENT_BRANCH%" --no-rebase --no-edit >nul 2>&1
if errorlevel 1 echo [CẢNH BÁO] Branch chưa có trên remote hoặc không thể pull.
goto do_push
:confirm_force
echo [CẢNH BÁO] Force push sẽ ghi đè lịch sử remote.
set /p "CONFIRM=Bạn chắc chắn? (y/N): "
if /i not "%CONFIRM%"=="y" (
    echo Đã hủy force push.
    exit /b 0
)
set "FORCE_FLAG=--force"
:do_push
git.exe push "%REMOTE%" "%CURRENT_BRANCH%" %FORCE_FLAG% || exit /b 1
echo [OK] Đã push branch "%CURRENT_BRANCH%".
exit /b 0

:branch
call :require_repo || exit /b 1
set "BRANCH_NAME=%~2"
if not defined BRANCH_NAME set "BRANCH_NAME=feature/%DATE:~-4%%DATE:~3,2%%DATE:~0,2%-%TIME:~0,2%%TIME:~3,2%%TIME:~6,2%"
set "BRANCH_NAME=%BRANCH_NAME: =0%"
git.exe show-ref --verify --quiet "refs/heads/%BRANCH_NAME%"
if errorlevel 1 (git.exe checkout -b "%BRANCH_NAME%") else (git.exe checkout "%BRANCH_NAME%")
if errorlevel 1 exit /b 1
echo [OK] Đang ở branch "%BRANCH_NAME%".
exit /b 0

:checkout
call :require_repo || exit /b 1
set "BRANCH_NAME=%~2"
if not defined BRANCH_NAME (
    git.exe branch -a
    set /p "BRANCH_NAME=Nhập tên branch: "
)
if not defined BRANCH_NAME exit /b 1
git.exe show-ref --verify --quiet "refs/heads/%BRANCH_NAME%" || (
    echo [LỖI] Branch local "%BRANCH_NAME%" không tồn tại.
    git.exe branch -a
    exit /b 1
)
git.exe checkout "%BRANCH_NAME%" || exit /b 1
echo [OK] Đã chuyển sang branch "%BRANCH_NAME%".
exit /b 0

:merge
call :require_repo || exit /b 1
set "TARGET_BRANCH=%~2"
if not defined TARGET_BRANCH set "TARGET_BRANCH=%BRANCH_MAIN%"
for /f "delims=" %%B in ('git.exe branch --show-current') do set "CURRENT_BRANCH=%%B"
if /i "%CURRENT_BRANCH%"=="%TARGET_BRANCH%" (
    echo [CẢNH BÁO] Đang ở branch đích; không thể tự merge chính nó.
    exit /b 0
)
git.exe checkout "%TARGET_BRANCH%" || exit /b 1
git.exe pull "%REMOTE%" "%TARGET_BRANCH%" --no-rebase >nul 2>&1
git.exe merge "%CURRENT_BRANCH%" --no-ff -m "Merge branch '%CURRENT_BRANCH%' into '%TARGET_BRANCH%'" || exit /b 1
git.exe push "%REMOTE%" "%TARGET_BRANCH%" || exit /b 1
echo [OK] Đã merge "%CURRENT_BRANCH%" vào "%TARGET_BRANCH%".
exit /b 0

:history
call :require_repo || exit /b 1
git.exe log --oneline --graph -10 --color=always
if errorlevel 1 echo [CẢNH BÁO] Chưa có commit nào.
exit /b 0

:revert
call :require_repo || exit /b 1
set "COMMIT_HASH=%~2"
if not defined COMMIT_HASH (
    git.exe log --oneline --graph -10
    set /p "COMMIT_HASH=Nhập commit hash: "
)
git.exe show "%COMMIT_HASH%" >nul 2>&1 || (echo [LỖI] Commit không tồn tại. & exit /b 1)
git.exe revert --no-edit "%COMMIT_HASH%" || exit /b 1
echo [OK] Đã revert commit %COMMIT_HASH%.
exit /b 0

:reset
call :require_repo || exit /b 1
set "COMMIT_HASH=%~2"
if not defined COMMIT_HASH (
    git.exe log --oneline --graph -10
    set /p "COMMIT_HASH=Nhập commit hash: "
)
git.exe show "%COMMIT_HASH%" >nul 2>&1 || (echo [LỖI] Commit không tồn tại. & exit /b 1)
echo 1. Soft  2. Mixed  3. Hard  4. Hủy
set /p "RESET_TYPE=Chọn loại reset (1/2/3/4): "
if "%RESET_TYPE%"=="1" goto soft_reset
if "%RESET_TYPE%"=="3" goto hard_reset
if "%RESET_TYPE%"=="4" (
    echo Đã hủy reset.
    exit /b 0
)
git.exe reset --mixed "%COMMIT_HASH%"
exit /b %errorlevel%
:soft_reset
git.exe reset --soft "%COMMIT_HASH%"
exit /b %errorlevel%
:hard_reset
set /p "CONFIRM=HARD RESET sẽ xóa thay đổi. Tiếp tục? (y/N): "
if /i not "%CONFIRM%"=="y" (
    echo Đã hủy reset.
    exit /b 0
)
git.exe reset --hard "%COMMIT_HASH%"
exit /b %errorlevel%

:tag
call :require_repo || exit /b 1
set "TAG_ACTION=%~2"
set "TAG_NAME=%~3"
if not defined TAG_ACTION set "TAG_ACTION=list"
if /i "%TAG_ACTION%"=="list" goto tag_list
if /i "%TAG_ACTION%"=="l" goto tag_list
if /i "%TAG_ACTION%"=="create" goto tag_create
if /i "%TAG_ACTION%"=="c" goto tag_create
if /i "%TAG_ACTION%"=="push" goto tag_push
if /i "%TAG_ACTION%"=="p" goto tag_push
if /i "%TAG_ACTION%"=="delete" goto tag_delete
if /i "%TAG_ACTION%"=="d" goto tag_delete
echo [LỖI] Tag action không hợp lệ.
exit /b 1
:tag_list
git.exe tag -l --sort=-v:refname
exit /b %errorlevel%
:tag_create
if not defined TAG_NAME set /p "TAG_NAME=Nhập tên tag: "
if not defined TAG_NAME exit /b 1
git.exe tag "%TAG_NAME%" || exit /b 1
echo [OK] Đã tạo tag "%TAG_NAME%".
exit /b 0
:tag_push
if not defined TAG_NAME set /p "TAG_NAME=Nhập tên tag hoặc all: "
if /i "%TAG_NAME%"=="all" goto tag_push_all
git.exe push "%REMOTE%" "%TAG_NAME%"
exit /b %errorlevel%
:tag_push_all
git.exe push "%REMOTE%" --tags
exit /b %errorlevel%
:tag_delete
if not defined TAG_NAME git.exe tag -l & set /p "TAG_NAME=Nhập tên tag cần xóa: "
if not defined TAG_NAME exit /b 1
git.exe tag -d "%TAG_NAME%"
exit /b %errorlevel%

:stash
call :require_repo || exit /b 1
set "STASH_ACTION=%~2"
set "STASH_VALUE=%~3"
if not defined STASH_ACTION set "STASH_ACTION=save"
if /i "%STASH_ACTION%"=="save" goto stash_save
if /i "%STASH_ACTION%"=="s" goto stash_save
if /i "%STASH_ACTION%"=="list" goto stash_list
if /i "%STASH_ACTION%"=="l" goto stash_list
if /i "%STASH_ACTION%"=="pop" goto stash_pop
if /i "%STASH_ACTION%"=="p" goto stash_pop
if /i "%STASH_ACTION%"=="apply" goto stash_apply
if /i "%STASH_ACTION%"=="a" goto stash_apply
if /i "%STASH_ACTION%"=="drop" goto stash_drop
if /i "%STASH_ACTION%"=="d" goto stash_drop
if /i "%STASH_ACTION%"=="clear" goto stash_clear
if /i "%STASH_ACTION%"=="c" goto stash_clear
echo [LỖI] Stash action không hợp lệ.
exit /b 1
:stash_list
git.exe stash list
exit /b %errorlevel%
:stash_pop
git.exe stash pop
exit /b %errorlevel%
:stash_save
if defined STASH_VALUE (git.exe stash push -m "%STASH_VALUE%") else (git.exe stash)
exit /b %errorlevel%
:stash_apply
if not defined STASH_VALUE set "STASH_VALUE=0"
git.exe stash apply "stash@{%STASH_VALUE%}"
exit /b %errorlevel%
:stash_drop
if not defined STASH_VALUE set "STASH_VALUE=0"
git.exe stash drop "stash@{%STASH_VALUE%}"
exit /b %errorlevel%
:stash_clear
set /p "CONFIRM=Xóa tất cả stash? (y/N): "
if /i not "%CONFIRM%"=="y" (
    echo Đã hủy.
    exit /b 0
)
git.exe stash clear
exit /b %errorlevel%

:diff
call :require_repo || exit /b 1
if not "%~2"=="" goto diff_target
echo Changes chưa staged:
git.exe diff --color=always
echo.
echo Changes đã staged:
git.exe diff --staged --color=always
exit /b 0
:diff_target
git.exe diff "%~2" --color=always
exit /b %errorlevel%

:status
call :require_repo || exit /b 1
for /f "delims=" %%R in ('git.exe rev-parse --show-toplevel') do echo Repository: %%~nxR
for /f "delims=" %%B in ('git.exe branch --show-current') do echo Branch hiện tại: %%B
git.exe remote get-url "%REMOTE%" 2>nul
if errorlevel 1 echo Remote: Chưa thiết lập
echo.
git.exe status -sb
exit /b %errorlevel%

:install_completion
echo CMD đã tự hoàn thành tên file/thư mục bằng phím Tab.
echo Hoàn thành lệnh theo ngữ cảnh như Bash không được CMD thuần hỗ trợ.
echo Có thể dùng git.bat help để xem nhanh toàn bộ lệnh.
exit /b 0

:help
echo.
echo %CYAN%  +------------------------------------------------------------+%RESET%
echo %CYAN%  ^|%RESET%              %BOLD%GIT HELPER FOR WINDOWS%RESET%                    %CYAN%^|%RESET%
echo %CYAN%  ^|%RESET%          Git workflow nhanh, gọn và an toàn             %CYAN%^|%RESET%
echo %CYAN%  +------------------------------------------------------------+%RESET%
echo.
echo %YELLOW%  REPOSITORY%RESET%
echo %GREEN%    git.bat init%RESET%                     Khởi tạo và đồng bộ GitHub
echo %GREEN%    git.bat status%RESET%                   Xem repository, branch, remote
echo %GREEN%    git.bat history%RESET%                  Xem 10 commit gần nhất
echo %GREEN%    git.bat diff [commit]%RESET%            Xem thay đổi trong code
echo.
echo %YELLOW%  LÀM VIỆC HẰNG NGÀY%RESET%
echo %GREEN%    git.bat commit "message"%RESET%         Pull, dọn cache, stage và commit
echo %GREEN%    git.bat push [-f]%RESET%                Push branch; -f để force push
echo %GREEN%    git.bat branch [name]%RESET%            Tạo hoặc chuyển sang branch
echo %GREEN%    git.bat checkout [name]%RESET%          Chuyển sang branch local
echo %GREEN%    git.bat merge [target]%RESET%           Merge branch hiện tại vào target
echo.
echo %YELLOW%  KHÔI PHỤC%RESET%
echo %GREEN%    git.bat revert [hash]%RESET%            Hoàn tác bằng một commit mới
echo %GREEN%    git.bat reset [hash]%RESET%             Soft, mixed hoặc hard reset
echo.
echo %YELLOW%  TAG VÀ STASH%RESET%
echo %GREEN%    git.bat tag list%RESET%                 Liệt kê tag
echo %GREEN%    git.bat tag create v1.0.0%RESET%        Tạo tag
echo %GREEN%    git.bat tag push v1.0.0%RESET%          Push tag; dùng "all" để push tất cả
echo %GREEN%    git.bat tag delete v1.0.0%RESET%        Xóa tag local
echo %GREEN%    git.bat stash save "message"%RESET%     Cất thay đổi tạm thời
echo %GREEN%    git.bat stash list%RESET%               Liệt kê stash
echo %GREEN%    git.bat stash pop%RESET%                Áp dụng và xóa stash mới nhất
echo %GREEN%    git.bat stash apply [index]%RESET%      Áp dụng stash theo index
echo %GREEN%    git.bat stash drop [index]%RESET%       Xóa stash theo index
echo %GREEN%    git.bat stash clear%RESET%              Xóa toàn bộ stash
echo.
echo %YELLOW%  VÍ DỤ%RESET%
echo %GRAY%    git.bat branch feature/login%RESET%
echo %GRAY%    git.bat commit "Add login page"%RESET%
echo %GRAY%    git.bat push%RESET%
echo %GRAY%    git.bat merge main%RESET%
echo.
echo %GRAY%  Gõ git.bat help bất kỳ lúc nào để mở lại bảng này.%RESET%
echo.
exit /b 0
