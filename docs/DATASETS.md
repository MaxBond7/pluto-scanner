# Внешние датасеты

## Принцип

Мы **не перепубликуем** чужие базы. Данные скачиваются с первоисточника,
импортируются локально, а лицензия остаётся у автора.

Это важно, потому что почти все полезные RF-датасеты — это:

- десятки–сотни гигабайт;
- разные лицензии: от `CC BY 4.0` до `CC BY-NC-SA 4.0` и условий
  IEEE DataPort;
- разметка по **моделям дронов** или **модуляциям**, а не по нашим шести
  классам `FHSS / TELEMETRY / VIDEO_* / WIFI / NARROW`.

Поэтому в проекте есть импорт, а не копия данных.

## Проверенные источники

| Источник | Что внутри | Объём | Лицензия / доступ | Для нас |
|---|---|---|---|---|
| **DroneDetect** (Swinney, Woods) | raw IQ, 2.4 ГГц, 60 MS/s, 7 моделей дронов, 4 помеховых сценария, 390 файлов | ZIP **65.76 ГБ** | IEEE DataPort, DOI `10.21227/5jjj-1m32`, **CC BY 4.0**; нужен бесплатный логин IEEE | лучший внешний raw-IQ для 2.4 ГГц; метки — модели, не наши классы |
| **DroneRF** (Al-Sa'd et al.) | RF-сегменты, 3 дрона (off/on/hover/fly/video) + фон | ~40 ГБ | Mendeley, DOI `10.17632/f4c2b4n755.1`, **CC BY 4.0** | отлично для binary «дрон/фон», но не для наших 6 классов |
| **CardRF** (Medaiyese et al.) | UAV + Bluetooth + Wi-Fi, outdoor, LOS/NLOS | >65 ГБ | IEEE DataPort, DOI `10.21227/1xp7-ge95`, **CC BY 4.0** | хорош для `WIFI` vs дрон; формат CSV/PNG/AVI — не raw IQ |
| **Drone Remote Controller RF** (Ezuma et al.) | 17 пультов, 8 производителей, RF fingerprints | 124 ГБ | IEEE DataPort, DOI `10.21227/ss99-8d56`, **CC BY 4.0** | сырьё для `FHSS`/`TELEMETRY`, но нужна ручная карта классов |
| **DroneRFb-Spectra** (Yu) | 7 брендов, spectrogram `.npy` | 5.5 ГБ | IEEE DataPort, DOI `10.21227/wv7h-sv64`, **CC BY 4.0** | только CNN по спектрограммам, не наш IQ-пайплайн |
| **DroneRFa / DroneRFb-DIR** (Zhejiang Univ.) | raw samples, 3 ISM-полосы, 24 класса + фон | ~616 ГБ | ScienceDB, DOI `10.57760/sciencedb.18475`, **CC BY-NC-SA 4.0** | огромный, некоммерческий; только локально |
| **RFVS** (Stella050527) | RGB + raw IQ, 8 дронов, 153.6 MS/s | Google Drive | код MIT; условия данных проверить | широкополосный, метки — модели |
| **LakeShark Signal Corpus** | короткие SigMF IQ (P25/FM/ADS-B/…) | МБ | записи CC0/CC BY 4.0 | примеры формата, не дроны |
| **Kampfraum** | MIT-агрегатор датасетов RF/acoustic/visual | индекс | MIT | навигация по источникам |
| **RadioML / WiSig** | raw IQ, модуляции / Wi-Fi fingerprinting | ГБ | условия DeepSig / **CC BY-NC-SA 4.0** | не наши классы |
| **SigIDWiki / RadioScanner** | справочники сигналов | веб | условия сайтов | только ссылки/ручная сверка |

## Что из этого реально использовать

1. **DroneDetect** — лучший raw-IQ для 2.4 ГГц: 7 моделей, 60 MS/s, `.dat`.
   Импортировать можно первые секунды файла, не всю базу. Лицензия CC BY 4.0.
2. **DroneRF** — 40 ГБ, 3 дрона + фон, CC BY 4.0. Лучший вариант для
   **binary «дрон/фон»**, но не для наших шести классов.
3. **CardRF** — 65 ГБ, UAV + Bluetooth + Wi-Fi, CC BY 4.0. Полезен для
   `WIFI` vs дрон, но формат CSV/PNG/AVI, не raw IQ.
4. **Drone RC RF** — 124 ГБ, 17 пультов, CC BY 4.0. Сырьё для
   `FHSS`/`TELEMETRY`, но метки — модели пультов.
5. **DroneRFb-Spectra** — 5.5 ГБ `.npy` спектрограмм, CC BY 4.0. Только
   отдельная CNN-ветка, не наш IQ-пайплайн.
6. **SigMF/LakeShark** — небольшие записи для проверки импорта, не дроны.
7. **RadioML/WiSig** — не наши классы; отдельные modulation/fingerprinting
   задачи.
8. **RFUAV, Noisy Drone RF, CageDroneRF** — лицензия не подтверждена;
   не используем, пока не проверим первоисточник.

**Честный вывод:** CC BY 4.0 датасетов достаточно, но ни один не размечен
ровно нашими шестью классами. Поэтому:

- для **binary drone/background** берём DroneRF;
- для **WIFI vs drone** — CardRF;
- для **raw IQ 2.4 ГГц** — DroneDetect;
- для наших `FHSS/TELEMETRY/VIDEO/WIFI/NARROW` всё равно нужна ручная
  разметка или отдельная модель «модель дрона».

## Импорт

### SigMF

```powershell
.\.venv\Scripts\python.exe -m pluto_scanner.ml.import_dataset `
  --format sigmf --src dataset.sigmf-meta --label WIFI
```

Если в аннотации есть `core:label`, импорт попробует взять метку оттуда.
Незнакомые метки игнорируются — их можно поставить вручную во вкладке
«Запись IQ».

### Raw float32 I/Q (DroneDetect и подобные)

```powershell
.\.venv\Scripts\python.exe -m pluto_scanner.ml.import_dataset `
  --format dat --src AIR_00_00.dat `
  --sample-rate 60e6 --center 2437.5e6 --max-seconds 2 `
  --label VIDEO_DIGITAL
```

`--max-seconds` обязателен для больших файлов: один файл DroneDetect —
около 1 ГБ, вся база — сотни гигабайт.

### Обучение

```powershell
.\.venv\Scripts\python.exe -m pluto_scanner.ml.train --real-dir iq_recordings
```

Метки DroneDetect — это модели (`AIR`, `MP1`, `PHA`…), а не наши классы.
Их нельзя автоматически превратить в `FHSS`/`VIDEO`; для нашего классификатора
нужна ручная метка морфологии или отдельная модель «модель дрона».

## Почему не складываем это в Git

- 600+ ГБ не помещаются в репозиторий и бэкап.
- `CC BY-NC-SA` запрещает коммерческое использование и требует
  share-alike; смешивать с MIT-кодом нельзя.
- IEEE DataPort и другие площадки имеют свои условия перепубликации.
- Разметка не совпадает с нашей задачей; хранить «сырые» гигабайты без
  пользы — плохая инженерия.

## Наша уникальная часть

- признаки и модель под **дрон-полосы Pluto**, а не абстрактные модуляции;
- разметка записей и обучение на **своих** IQ;
- проверка domain gap между синтетикой и эфиром;
- связка с эвристикой, white list, IQ-доказательствами и событием;
- импорт чужих форматов без потери лицензии.
