# Marstek Energy System - Home Assistant Integration

[![HACS Validation](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![API Rev: 2.0](https://img.shields.io/badge/Marstek_Open_API-Rev_2.0-blue.svg)](https://github.com/HARd/marstek-ha)

[English](#english) | [Українська](#українська)

---

<a name="english"></a>
## English

A custom Home Assistant integration for **Marstek** energy storage systems and battery power stations (including **Venus A**, **Venus C/E**, **Venus D**, and other models supporting **Marstek Open API Rev 2.0** over LAN/UDP).

> [!IMPORTANT]
> **Local UDP Communication:** This integration operates entirely within your local area network via UDP broadcast and direct datagrams. No cloud connectivity or internet access is required. To enable API access, you must turn on the **Open API** feature in the official Marstek mobile app.

### Key Features

* **Automatic LAN Discovery:** Utilizes UDP broadcast to automatically detect supported Marstek devices on your local network during configuration.
* **Power & Backup State Monitoring:**
  * Accurately distinguishes between normal grid operation (including UPS bypass mode) and off-grid battery discharge during power outages.
  * Designed to provide reliable trigger states for home automation systems, emergency lighting, and automated power switchovers (e.g., Switchbot / Svitlobot).
* **Comprehensive Real-Time Telemetry:**
  * Monitors battery State of Charge (SOC %), remaining and rated capacity (Wh), and battery temperature (°C).
  * Tracks power metrics (W) across all nodes: grid import/export (`ongrid_power`), backup load output (`offgrid_power`), battery charge/discharge (`battery_power`), and multi-string solar generation (`pv_power`, `pv_voltage`, `pv_current`).
  * Features adaptive data processing to handle firmware telemetry optimizations (e.g., zero-value omission in Rev 2.0 firmware).
* **Device Control:**
  * **Operating Mode:** Switch dynamically between `Auto`, `AI`, `Manual`, `Passive`, and `UPS` modes.
  * **Depth of Discharge (DOD):** Configure the minimum battery discharge limit (30% to 88%).
  * **LED & Bluetooth:** Toggle device chassis LED display and Bluetooth (BLE) broadcast.
* **Modern HA Architecture:** Built on standard `ConfigEntry` using `runtime_data`, fully compatible with Home Assistant 2026.7+ and Python 3.14.

### Installation

#### Method 1: HACS (Recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=HARd&repository=marstek-ha&category=integration)

1. Click the **Open in HACS** button above to open this repository directly in Home Assistant.
2. Alternatively, open **HACS** in Home Assistant, select the three dots in the top right corner -> **Custom repositories**.
3. Enter `https://github.com/HARd/marstek-ha`, select **Integration** as the category, and click **Add**.
4. Locate **Marstek Energy System** in the HACS store and click **Download**.
5. Restart Home Assistant.

#### Method 2: Manual Installation
1. Download or clone this repository.
2. Copy the `custom_components/marstek` directory to your Home Assistant `/config/custom_components/` directory.
3. Restart Home Assistant.

### Configuration

1. Open the **Marstek** mobile app on your smartphone.
2. Navigate to your device settings and enable **Open API** (default port: `30000`).
3. It is recommended to assign a static IP address to your Marstek device in your DHCP/router settings.
4. In Home Assistant, navigate to **Settings** -> **Devices & Services** -> **Add Integration**.
5. Search for **Marstek**.
6. Select the discovered device or enter its IP address and port manually.
7. Polling interval can be adjusted in the integration options (default: 10 seconds).

### Available Entities

| Entity | Type | Description | API Specification |
| :--- | :--- | :--- | :--- |
| `binary_sensor.marstek_grid_power_present` | Binary Sensor | **Grid Power Present (220V):** Active (`on`) when grid power is available or when operating in UPS bypass mode without battery discharge. | `ES.GetStatus` / `ES.GetMode` |
| `binary_sensor.marstek_backup_power_active` | Binary Sensor | **Backup Power Active (Off-grid):** Active (`on`) during grid outages when the battery is actively discharging to supply backup loads. | `ES.GetStatus` / `ES.GetMode` |
| `binary_sensor.marstek_battery_charging` | Binary Sensor | **Charging:** Active (`on`) when the battery is charging from grid or solar. | `Bat.GetStatus` / `ES.GetStatus` |
| `binary_sensor.marstek_battery_discharging` | Binary Sensor | **Discharging:** Active (`on`) when the battery is discharging to supply loads. | `Bat.GetStatus` / `ES.GetStatus` |
| `binary_sensor.marstek_battery_charging_permission` | Binary Sensor | Hardware permission flag for charging (`charg_flag`). | `Bat.GetStatus` |
| `binary_sensor.marstek_battery_discharging_permission` | Binary Sensor | Hardware permission flag for discharging (`dischrg_flag`). | `Bat.GetStatus` |
| `sensor.marstek_battery_soc` | Sensor | Battery State of Charge (%) | `Bat.GetStatus` / `ES.GetStatus` |
| `sensor.marstek_ongrid_power` | Sensor | Grid import/export power (W) | `ES.GetStatus` |
| `sensor.marstek_offgrid_power` | Sensor | Backup output load power (W) | `ES.GetStatus` |
| `sensor.marstek_battery_power` | Sensor | Net battery charging/discharging power (W) | `ES.GetStatus` |
| `sensor.marstek_pv_power` | Sensor | Total solar generation power across PV1-PV4 strings (W) | `PV.GetStatus` / `ES.GetStatus` |
| `sensor.marstek_pv_voltage` | Sensor | Maximum solar array voltage across all strings (V) | `PV.GetStatus` |
| `sensor.marstek_pv_current` | Sensor | Total solar array current across all strings (A) | `PV.GetStatus` |
| `sensor.marstek_battery_temperature` | Sensor | Internal battery temperature (°C) | `Bat.GetStatus` |
| `sensor.marstek_battery_capacity` | Sensor | Current remaining energy capacity (Wh) | `Bat.GetStatus` / `ES.GetStatus` |
| `sensor.marstek_rated_capacity` | Sensor | Rated factory energy capacity (Wh) | `Bat.GetStatus` |
| `sensor.marstek_em_total_power` | Sensor | External energy meter or CT transformer power (W) | `EM.GetStatus` / `ES.GetMode` |
| `select.marstek_operating_mode` | Select | Operating mode selection (`Auto`, `AI`, `Manual`, `Passive`, `UPS`) | `ES.GetMode` / `ES.SetMode` |
| `number.marstek_depth_of_discharge` | Number | Depth of Discharge limit setting (30% - 88%) | `DOD.SET` |
| `switch.marstek_led_display` | Switch | Toggle chassis LED display indicator | `Led.Ctrl` |
| `switch.marstek_bluetooth_broadcast` | Switch | Toggle Bluetooth (BLE) advertisement broadcast | `Ble.Adv` |

---

<a name="українська"></a>
## Українська

Повнофункціональна локальна інтеграція Home Assistant для енергетичних систем та акумуляторних станцій **Marstek** (серії **Venus A**, **Venus C/E**, **Venus D** та інших, що підтримують протокол **Marstek Open API Rev 2.0** через LAN/UDP).

> [!IMPORTANT]
> **Локальна взаємодія (UDP):** Інтеграція працює виключно в межах локальної мережі (LAN) через UDP-мовлення та прямі запити. Підключення до інтернету чи хмарних сервісів не потрібне. Для доступу до API необхідно увімкнути функцію **Open API** в офіційному мобільному додатку Marstek.

### Основні можливості

* **Автоматичне виявлення в LAN:** Використовує UDP-мовлення для автоматичного знаходження сумісних пристроїв Marstek у локальній мережі під час налаштування.
* **Моніторинг мережі та резервного живлення:**
  * Точне розпізнавання нормальної роботи від мережі (включаючи режим транзиту / UPS байпас) та автономного живлення від акумулятора під час відключень електроенергії.
  * Забезпечує надійні тригери для систем домашньої автоматизації, аварійного освітлення та сценаріїв перемикання резерву (наприклад, Switchbot / Світлобот).
* **Повна телеметрія у реальному часі:**
  * Відслідковування рівня заряду (SOC %), залишкової та номінальної ємності (Вт·год), а також температури акумулятора (°C).
  * Моніторинг потужності (Вт) на всіх вузлах: споживання/віддача з мережі (`ongrid_power`), вихідна потужність навантаження (`offgrid_power`), заряд/розряд батареї (`battery_power`) та багатострінгова генерація сонячних панелей (`pv_power`, `pv_voltage`, `pv_current`).
  * Адаптивні алгоритми обробки даних для коректної роботи з оптимізаціями телеметрії у прошивках Rev 2.0 (коли при нульових значеннях окремі параметри не передаються у пакетах).
* **Керування пристроєм:**
  * **Режим роботи (Operating Mode):** Динамічне перемикання між режимами `Auto`, `AI`, `Manual`, `Passive` та `UPS`.
  * **Глибина розряду (DOD):** Налаштування мінімального рівня розряду акумулятора (від 30% до 88%).
  * **LED та Bluetooth:** Керування індикацією на корпусі пристрою та трансляцією Bluetooth (BLE).
* **Сучасна архітектура HA:** Побудовано на стандартному `ConfigEntry` з використанням `runtime_data`, повна сумісність з Home Assistant 2026.7+ та Python 3.14.

### Встановлення

#### Спосіб 1: Через HACS (Рекомендовано)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=HARd&repository=marstek-ha&category=integration)

1. Натисніть на кнопку **Open in HACS** вище, щоб відкрити та додати цей репозиторій безпосередньо у вашому Home Assistant.
2. Або відкрийте **HACS** вручну, натисніть на три крапки у верхньому правому куті -> **Користувацькі репозиторії (Custom repositories)**.
3. Вставте посилання `https://github.com/HARd/marstek-ha`, оберіть категорію **Інтеграція (Integration)** та натисніть **Додати**.
4. Знайдіть **Marstek Energy System** у списку та натисніть **Завантажити (Download)**.
5. Перезавантажте Home Assistant.

#### Спосіб 2: Вручну
1. Завантажте архів з репозиторію або склонуйте його.
2. Скопіюйте директорію `custom_components/marstek` у папку `/config/custom_components/` вашого Home Assistant.
3. Перезавантажте Home Assistant.

### Налаштування

1. Відкрийте додаток **Marstek** на смартфоні.
2. Перейдіть у налаштування пристрою та увімкніть **Open API** (стандартний порт: `30000`).
3. Рекомендується закріпити статичну IP-адресу за пристроєм Marstek у налаштуваннях вашого роутера/DHCP.
4. У Home Assistant перейдіть до **Налаштування** -> **Пристрої та служби** -> **Додати інтеграцію**.
5. Знайдіть **Marstek**.
6. Оберіть знайдений у мережі пристрій або введіть його IP-адресу та порт вручну.
7. Інтервал опитування можна змінити в параметрах інтеграції (за замовчуванням: 10 секунд).

### Опис доступних сутностей (Entities)

| Сутність | Тип | Опис | Специфікація API |
| :--- | :--- | :--- | :--- |
| `binary_sensor.marstek_grid_power_present` | Binary Sensor | **Наявність мережі (220В):** Активний (`on`), коли наявне живлення з мережі або пристрій працює в режимі транзиту (UPS байпас) без розряду батареї. | `ES.GetStatus` / `ES.GetMode` |
| `binary_sensor.marstek_backup_power_active` | Binary Sensor | **Резервне живлення (Off-grid):** Активний (`on`) під час відключення мережі, коли акумулятор активно віддає енергію на навантаження. | `ES.GetStatus` / `ES.GetMode` |
| `binary_sensor.marstek_battery_charging` | Binary Sensor | **Заряджання:** Активний (`on`), коли акумулятор заряджається від мережі або сонця. | `Bat.GetStatus` / `ES.GetStatus` |
| `binary_sensor.marstek_battery_discharging` | Binary Sensor | **Розряджання:** Активний (`on`), коли акумулятор віддає енергію. | `Bat.GetStatus` / `ES.GetStatus` |
| `binary_sensor.marstek_battery_charging_permission` | Binary Sensor | Апаратний прапорець дозволу на заряджання (`charg_flag`). | `Bat.GetStatus` |
| `binary_sensor.marstek_battery_discharging_permission` | Binary Sensor | Апаратний прапорець дозволу на розряджання (`dischrg_flag`). | `Bat.GetStatus` |
| `sensor.marstek_battery_soc` | Sensor | Рівень заряду акумулятора (%) | `Bat.GetStatus` / `ES.GetStatus` |
| `sensor.marstek_ongrid_power` | Sensor | Потужність споживання або віддачі в мережу (Вт) | `ES.GetStatus` |
| `sensor.marstek_offgrid_power` | Sensor | Потужність навантаження на резервному виході (Вт) | `ES.GetStatus` |
| `sensor.marstek_battery_power` | Sensor | Результуюча потужність заряду/розряду акумулятора (Вт) | `ES.GetStatus` |
| `sensor.marstek_pv_power` | Sensor | Сумарна потужність сонячної генерації на всіх трекерах PV1-PV4 (Вт) | `PV.GetStatus` / `ES.GetStatus` |
| `sensor.marstek_pv_voltage` | Sensor | Максимальна напруга сонячного масиву (В) | `PV.GetStatus` |
| `sensor.marstek_pv_current` | Sensor | Сумарний струм сонячного масиву (А) | `PV.GetStatus` |
| `sensor.marstek_battery_temperature` | Sensor | Внутрішня температура акумулятора (°C) | `Bat.GetStatus` |
| `sensor.marstek_battery_capacity` | Sensor | Поточна доступна ємність (Вт·год) | `Bat.GetStatus` / `ES.GetStatus` |
| `sensor.marstek_rated_capacity` | Sensor | Номінальна заводська ємність (Вт·год) | `Bat.GetStatus` |
| `sensor.marstek_em_total_power` | Sensor | Потужність зовнішнього лічильника або CT-трансформатора (Вт) | `EM.GetStatus` / `ES.GetMode` |
| `select.marstek_operating_mode` | Select | Вибір режиму роботи (`Auto`, `AI`, `Manual`, `Passive`, `UPS`) | `ES.GetMode` / `ES.SetMode` |
| `number.marstek_depth_of_discharge` | Number | Встановлення ліміту глибини розряду DOD (30% - 88%) | `DOD.SET` |
| `switch.marstek_led_display` | Switch | Увімкнення/вимкнення LED-індикатора на корпусі | `Led.Ctrl` |
| `switch.marstek_bluetooth_broadcast` | Switch | Увімкнення/вимкнення BLE-трансляції | `Ble.Adv` |
