<#
.SYNOPSIS
    Робочі команди проєкту SILLAGE.

.DESCRIPTION
    Обгортка над manage.py, ruff і black, щоб не памʼятати довгі шляхи.
    Сам знаходить python у .venv — активувати середовище не обовʼязково.

.PARAMETER Command
    run | migrate | makemigrations | seed | seed-fast | render | test | lint
    | format | superuser
    | check | check-prod | collectstatic | shell | urls | install | help

.EXAMPLE
    .\scripts\dev.ps1 run
    .\scripts\dev.ps1 test
    .\scripts\dev.ps1 makemigrations -Args shop
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Command = 'help',

    [Parameter(Position = 1, ValueFromRemainingArguments = $true)]
    [string[]]$Args = @()
)

$ErrorActionPreference = 'Stop'

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$Manage = Join-Path $ProjectRoot 'manage.py'

if (-not (Test-Path $Python)) {
    Write-Host "Не знайдено $Python" -ForegroundColor Red
    Write-Host "Створи середовище:  python -m venv .venv" -ForegroundColor Yellow
    exit 1
}

Push-Location $ProjectRoot
try {
    switch ($Command.ToLower()) {

        'run' {
            Write-Host '→ runserver на http://127.0.0.1:8000/' -ForegroundColor Cyan
            & $Python $Manage runserver @Args
        }

        'migrate' {
            & $Python $Manage migrate @Args
        }

        'makemigrations' {
            & $Python $Manage makemigrations @Args
        }

        'seed' {
            # Повний цикл: схема -> каталог -> зображення. Саме в такому
            # порядку, бо рендерер бере товари з бази.
            Write-Host '→ migrate' -ForegroundColor Cyan
            & $Python $Manage migrate
            Write-Host '→ наповнення каталогу SILLAGE' -ForegroundColor Cyan
            & $Python $Manage seed_shop --flush @Args
            Write-Host '→ рендер зображень (це надовго)' -ForegroundColor Cyan
            & $Python $Manage render_product_images --force
        }

        'seed-fast' {
            Write-Host '→ каталог без зображень' -ForegroundColor Cyan
            & $Python $Manage migrate
            & $Python $Manage seed_shop --flush --no-images @Args
        }

        'render' {
            & $Python $Manage render_product_images @Args
        }

        'test' {
            & $Python $Manage test @Args
        }

        'lint' {
            Write-Host '→ ruff check' -ForegroundColor Cyan
            & $Python -m ruff check . @Args
            Write-Host '→ black --check' -ForegroundColor Cyan
            & $Python -m black --check . @Args
        }

        'format' {
            Write-Host '→ ruff check --fix' -ForegroundColor Cyan
            & $Python -m ruff check --fix .
            Write-Host '→ black' -ForegroundColor Cyan
            & $Python -m black .
        }

        'superuser' {
            & $Python $Manage createsuperuser @Args
        }

        'check' {
            & $Python $Manage check @Args
        }

        'check-prod' {
            Write-Host '→ check --deploy з prod-налаштуваннями' -ForegroundColor Cyan
            & $Python $Manage check --deploy --settings=shop_project.settings.prod @Args
        }

        'collectstatic' {
            & $Python $Manage collectstatic --noinput @Args
        }

        'shell' {
            # shell_plus від django-extensions: моделі імпортуються самі.
            & $Python $Manage shell_plus @Args
        }

        'urls' {
            & $Python $Manage show_urls @Args
        }

        'install' {
            Write-Host '→ requirements.txt + requirements-dev.txt' -ForegroundColor Cyan
            & $Python -m pip install -r requirements.txt -r requirements-dev.txt
        }

        default {
            Write-Host ''
            Write-Host 'SILLAGE — команди розробки' -ForegroundColor Cyan
            Write-Host ''
            Write-Host '  .\scripts\dev.ps1 <команда> [аргументи]'
            Write-Host ''
            Write-Host '  run             runserver на 127.0.0.1:8000'
            Write-Host '  migrate         застосувати міграції'
            Write-Host '  makemigrations  створити міграції'
            Write-Host '  seed            migrate + каталог + рендер зображень'
            Write-Host '  seed-fast       каталог без рендеру зображень'
            Write-Host '  render          лише рендер (--only=slug, --force)'
            Write-Host '  test            прогнати тести'
            Write-Host '  lint            ruff check + black --check'
            Write-Host '  format          ruff --fix + black'
            Write-Host '  superuser       створити адміністратора'
            Write-Host '  check           manage.py check'
            Write-Host '  check-prod      check --deploy з prod-налаштуваннями'
            Write-Host '  collectstatic   зібрати статику в staticfiles/'
            Write-Host '  shell           shell_plus'
            Write-Host '  urls            show_urls'
            Write-Host '  install         поставити залежності'
            Write-Host ''
            if ($Command -ne 'help') {
                Write-Host "Невідома команда: $Command" -ForegroundColor Red
                exit 1
            }
        }
    }
}
finally {
    Pop-Location
}
