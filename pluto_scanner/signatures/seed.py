"""Built-in catalog of common signal families.

The entries describe *typical* bands and spectral behaviour, not confirmed
protocol decoders and not a specific drone model.  They are deliberately
conservative: the matcher shows them as hypotheses with references.
"""
from __future__ import annotations

from .models import SignalSignature

SEED_VERSION = 1

_REF = "Открытые справочники: ITU/FCC band allocations, SigIDWiki, RadioReference"
_LIC = "Справочные данные; проверяйте актуальность для своего региона"


def _sig(
    sid: str, name: str, category: str, source: str,
    start_mhz: float, end_mhz: float, bw_khz: float,
    modulation: str, duty: float, burst_ms: float, hop: str,
    notes: str, confidence: float, refs: list[str] | None = None,
) -> SignalSignature:
    return SignalSignature(
        id=sid,
        name=name,
        category=category,
        source_class=source,
        start_hz=start_mhz * 1e6,
        end_hz=end_mhz * 1e6,
        bw_hz=bw_khz * 1e3,
        modulation=modulation,
        duty=duty,
        burst_ms=burst_ms,
        hop=hop,
        notes=notes,
        references=refs or [_REF],
        license=_LIC,
        confidence=confidence,
        builtin=True,
    )


SEED_SIGNATURES: list[SignalSignature] = [
    _sig("builtin-fm-broadcast", "FM-вещание", "Вещание", "broadcast",
         87.5, 108.0, 180.0, "FM, широкополосная ЧМ", 1.0, 0.0, "none",
         "Непрерывный аналоговый ЧМ-сигнал с пилот-тоном.", 0.90),
    _sig("builtin-dvb-t", "DVB-T / DVB-T2", "Вещание", "broadcast",
         470.0, 790.0, 8000.0, "OFDM", 1.0, 0.0, "none",
         "Широкополосный OFDM-телевизионный сигнал; полоса 6/7/8 МГц.", 0.85),
    _sig("builtin-adsb", "ADS-B 1090", "Авиация", "navigation",
         1085.0, 1095.0, 1000.0, "PPM / импульсная модуляция", 0.02, 0.5, "none",
         "Короткие импульсные посылки транспондеров воздушных судов.", 0.88),
    _sig("builtin-ais", "AIS", "Морской", "navigation",
         161.9, 162.1, 25.0, "GMSK", 0.30, 26.0, "none",
         "Судовая автоматическая идентификация; две узкие частоты.", 0.82),
    _sig("builtin-gps-l1", "GPS L1", "Навигация", "navigation",
         1574.4, 1576.4, 2000.0, "BPSK / DSSS", 1.0, 0.0, "none",
         "Слабый широкополосный навигационный сигнал под шумом.", 0.80),
    _sig("builtin-wifi-24", "Wi-Fi 2.4 ГГц", "Wi-Fi", "wifi",
         2400.0, 2483.5, 20000.0, "OFDM (802.11 b/g/n/ax)", 0.70, 1.0, "none",
         "Каналы 20/40 МГц; beacon-интервал около 102.4 мс.", 0.95),
    _sig("builtin-wifi-5", "Wi-Fi 5 ГГц", "Wi-Fi", "wifi",
         5150.0, 5850.0, 40000.0, "OFDM (802.11 a/n/ac/ax)", 0.70, 1.0, "none",
         "Каналы 20/40/80/160 МГц; широкополосный OFDM.", 0.92),
    _sig("builtin-bt-classic", "Bluetooth Classic", "Bluetooth", "bluetooth",
         2402.0, 2480.0, 1000.0, "GFSK / FHSS", 0.30, 0.625, "fast",
         "Прыжки по 79 каналам, слоты 625 мкс.", 0.85),
    _sig("builtin-ble", "Bluetooth LE", "Bluetooth", "bluetooth",
         2402.0, 2480.0, 2000.0, "GFSK", 0.10, 0.2, "slow",
         "Короткие пакеты, реклама и соединения; похоже на телеметрию.", 0.80),
    _sig("builtin-zigbee", "Zigbee / 802.15.4", "Умный дом", "zigbee",
         2405.0, 2480.0, 2000.0, "DSSS / O-QPSK", 0.20, 4.0, "slow",
         "Узкие каналы 2/5 МГц; датчики и умный дом.", 0.80),
    _sig("builtin-rc-24", "RC-пульт 2.4 ГГц (FHSS)", "Пульты", "rc",
         2400.0, 2483.5, 1500.0, "FHSS / GFSK", 0.40, 1.0, "fast",
         "Типичный скачкообразный линк пульта; не конкретная модель.", 0.78),
    _sig("builtin-telemetry-24", "Телеметрия/пульт 2.4 ГГц", "Телеметрия", "telemetry",
         2400.0, 2483.5, 250.0, "GFSK / O-QPSK", 0.10, 10.0, "slow",
         "Узкие периодические посылки; телеметрия, пульт или BLE-подобный линк.", 0.72),
    _sig("builtin-drone-24", "Дрон-линк 2.4 ГГц (семейство)", "Дроны", "drone_control",
         2400.0, 2483.5, 20000.0, "OFDM / FHSS", 0.60, 2.0, "fast",
         "Типовая полоса OcuSync/Lightbridge и аналогов; НЕ определяет модель.", 0.70,
         ["Открытые описания DJI OcuSync/Lightbridge; типовые полосы, не модель"]),
    _sig("builtin-drone-58", "Дрон-видео 5.8 ГГц", "Дроны", "drone_video",
         5725.0, 5875.0, 20000.0, "OFDM / FM-видео", 0.65, 2.0, "fast",
         "Типовая полоса FPV-видео и части управления; зависит от региона.", 0.72,
         ["Открытые описания FPV-видеолинков; типовые полосы, не модель"]),
    _sig("builtin-fpv-analog-58", "Аналоговое FPV 5.8 ГГц", "Дроны", "drone_video",
         5645.0, 5945.0, 8000.0, "FM-видео", 1.0, 0.0, "none",
         "Непрерывный аналоговый видеосигнал; характерная ширина 6–10 МГц.", 0.82),
    _sig("builtin-video-12", "Аналоговое видео 1.2–1.3 ГГц", "Видео", "analog_video",
         1080.0, 1360.0, 8000.0, "FM-видео", 1.0, 0.0, "none",
         "Старые FPV/камеры и видеопередатчики; широкий непрерывный сигнал.", 0.75),
    _sig("builtin-lora-868", "LoRa 868", "Телеметрия", "telemetry",
         863.0, 870.0, 125.0, "CSS / chirp", 0.05, 100.0, "slow",
         "Узкополосная Chirp-модуляция; датчики и телеметрия.", 0.80),
    _sig("builtin-lora-915", "LoRa 915", "Телеметрия", "telemetry",
         902.0, 928.0, 125.0, "CSS / chirp", 0.05, 100.0, "slow",
         "US ISM; узкополосные Chirp-посылки.", 0.80),
    _sig("builtin-sik-433", "SiK / MAVLink 433", "Телеметрия", "telemetry",
         433.05, 434.79, 250.0, "GFSK", 0.10, 10.0, "slow",
         "Типичная телеметрия дронов/наземных станций; короткие пакеты.", 0.82),
    _sig("builtin-sik-915", "SiK / MAVLink 915", "Телеметрия", "telemetry",
         902.0, 928.0, 250.0, "GFSK", 0.10, 10.0, "slow",
         "US ISM телеметрия; короткие пакеты.", 0.82),
    _sig("builtin-narrow-24", "Узкая несущая / спур 2.4", "Помеха", "unknown",
         2400.0, 2483.5, 20.0, "CW / AM", 1.0, 0.0, "none",
         "Узкий постоянный носитель или спур; не дрон сам по себе.", 0.35),
]


def seed_signatures() -> list[SignalSignature]:
    return [SignalSignature.from_dict(sig.to_dict()) for sig in SEED_SIGNATURES]
