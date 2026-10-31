# GitHub: приватный репозиторий и будущий open source

## 1. Создать приватный репозиторий

На GitHub: **New repository**

- name: `pluto-scanner`
- visibility: **Private**
- не добавлять README, .gitignore и license — они уже есть в проекте.

Скопировать HTTPS-URL, например:

```text
https://github.com/<USER>/pluto-scanner.git
```

## 2. Привязать и отправить

Из папки `NEW`:

```powershell
git remote add origin https://github.com/<USER>/pluto-scanner.git
git push -u origin main
git push origin v0.1.0
```

Git for Windows при первом push откроет вход через браузер (Git Credential
Manager). Токен в файлы проекта не записывать.

## 3. Проверить

```powershell
git remote -v
git log --oneline --decorate -5
git status
```

В репозитории должны быть только исходники, тесты, документация и
презентация. `.venv/`, `user_data/`, `scan_logs/`, `drone_logs/`, IQ-клипы и
ярлыки должны отсутствовать.

## 4. Откат на версию

Посмотреть историю:

```powershell
git log --oneline --decorate --all
```

Посмотреть состояние тега без изменения рабочей папки:

```powershell
git show v0.1.0
```

Создать ветку из старой версии:

```powershell
git switch -c restore-v0.1.0 v0.1.0
```

Вернуть рабочую папку к тегу (осторожно: незакоммиченные изменения нужно
сохранить или закоммитить):

```powershell
git switch main
git reset --hard v0.1.0
```

Если нужен именно откат уже отправленной ветки:

```powershell
git revert <commit>
git push
```

`git revert` безопаснее для общей истории, чем `reset --hard` + force push.

## 5. Новая версия

```powershell
git add .
git commit -m "Describe the change"
git tag -a v0.4.2 -m "Pluto Scanner 0.4.2"
git push
git push origin v0.4.2
```

## 6. Перед публикацией репозитория

- [ ] Проверить, что в истории нет токенов, паролей, серийников и личных путей.
- [ ] Проверить, что `user_data/`, логи и IQ-клипы не попали в Git.
- [ ] Выбрать лицензию (сейчас MIT) и подтвердить права на код.
- [ ] Проверить источники и лицензии библиотеки сигнатур.
- [ ] Включить GitHub Actions и private vulnerability reporting.
- [ ] Добавить описание, topics и скриншоты в настройках репозитория.
- [ ] Помнить: после смены private → public **вся история** становится публичной.

Если в историю случайно попали секреты, недостаточно удалить файл новым
коммитом: нужен `git filter-repo` или новый чистый репозиторий.
