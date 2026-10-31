# GitHub: публикация и версии

Репозиторий: <https://github.com/MaxBond7/pluto-scanner>

## 1. Текущий статус

- visibility: **Public**;
- лицензия: **MIT**;
- основная ветка: `main`;
- версии: теги `v0.1.0` … `v0.12.0`;
- GitHub Actions: тесты на Windows;
- приватные отчёты об уязвимостях: включить в Settings → Security.

В репозитории должны быть только исходники, тесты, документация и
презентация. `.venv/`, `user_data/`, `scan_logs/`, `drone_logs/`,
`iq_recordings/`, логи, IQ-клипы и ярлыки отсутствуют.

## 2. Клонирование и отправка

```powershell
git clone https://github.com/MaxBond7/pluto-scanner.git
cd pluto-scanner
git remote -v
git log --oneline --decorate -5
```

Первый push откроет вход через браузер (Git Credential Manager). Токен в
файлы проекта не записывать.

## 3. Откат на версию

```powershell
git log --oneline --decorate --all
git show v0.12.0
git switch -c restore-v0.12.0 v0.12.0
```

Вернуть рабочую папку к тегу (осторожно: незакоммиченные изменения нужно
сохранить или закоммитить):

```powershell
git switch main
git reset --hard v0.12.0
```

Если ветка уже отправлена, безопаснее откат коммитом:

```powershell
git revert <commit>
git push
```

## 4. Новая версия

```powershell
git add .
git commit -m "Describe the change"
git tag -a v0.12.0 -m "Pluto Scanner 0.12.0"
git push
git push origin v0.12.0
```

Для сборки релиза:

```powershell
.\build_windows.ps1 -Clean -Installer
```

## 5. Оформление страницы

- [x] README с баннером, скриншотами, возможностями и быстрым стартом.
- [x] Лицензия MIT, CONTRIBUTING, SECURITY, CITATION.
- [x] GitHub Actions для тестов.
- [x] Topics и описание репозитория.
- [x] GitHub Release `v0.12.0` с ZIP, Setup и `SHA256SUMS.txt`.
- [ ] Social preview 1280×640 в Settings → General.
- [ ] Включить private vulnerability reporting.
- [ ] Dependabot alerts.

## 6. Безопасность истории

Перед публикацией проверено:

- [x] в истории нет токенов, паролей и приватных ключей;
- [x] `user_data/`, логи и IQ-клипы не попали в Git;
- [x] личные пути и серийники не добавлены в документацию;
- [x] лицензии сторонних компонентов описаны в `THIRD_PARTY_NOTICES.md`;
- [x] публичный релиз `v0.12.0` с проверенными артефактами.

Если секрет всё же попал в историю, удалить файл новым коммитом
недостаточно: нужен `git filter-repo` или новый чистый репозиторий.
