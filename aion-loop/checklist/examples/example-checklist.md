# Учебный чек-лист (пример) — формат источника для sobrat.py

Каждый пункт: заголовок `### N-… · Имя` и поля списком. Ворота читают только это.

### N-L0-00 · Сверка канона с реальностью

- CLASS: MIGRATION_ITEM
- IMPLEMENTATION_MODE: VERIFY
- TASK_STATE: PLANNED
- LEVEL: L0
- DEPENDS: нет
- RISK: RED
- REQUIRED_EVIDENCE: вывод сверки
- ACCEPTANCE: каждое расхождение исправлено или помечено
- INDEPENDENT_REVIEW: ТРЕБУЕТСЯ: отдельная личность, не Builder
- OBJECTIVE: документы = диску

### N-L0-01 · Машинное зеркало состояния

- CLASS: BUILD_ITEM
- IMPLEMENTATION_MODE: BUILD
- TASK_STATE: PLANNED
- LEVEL: L0
- DEPENDS: N-L0-00
- RISK: GREEN
- REQUIRED_EVIDENCE: state/current.json
- ACCEPTANCE: зеркало = документу
- INDEPENDENT_REVIEW: НЕ ТРЕБУЕТСЯ (GREEN): достаточно автоматической проверки
- OBJECTIVE: состояние читается машиной

### N-L0-02 · Ворота чек-листа

- CLASS: BUILD_ITEM
- IMPLEMENTATION_MODE: BUILD
- TASK_STATE: PLANNED
- LEVEL: L0
- DEPENDS: N-L0-01
- RISK: GREEN
- REQUIRED_EVIDENCE: вывод проб ворот
- ACCEPTANCE: один пункт в работе; DONE только с уликой
- INDEPENDENT_REVIEW: НЕ ТРЕБУЕТСЯ (GREEN): достаточно автоматической проверки
- OBJECTIVE: механический замок на чек-лист

### N-L0-05 · Сверка перед публикацией

- CLASS: BUILD_ITEM
- IMPLEMENTATION_MODE: BUILD
- TASK_STATE: PLANNED
- LEVEL: L0
- DEPENDS: N-L0-01, N-L0-02
- RISK: YELLOW
- REQUIRED_EVIDENCE: вывод сверки
- ACCEPTANCE: расхождение закрывает публикацию
- INDEPENDENT_REVIEW: НЕ ТРЕБУЕТСЯ (GREEN): достаточно автоматической проверки
- OBJECTIVE: reconcile перед каждым push

### N-L1-01 · Связь Директор → исполнитель

- CLASS: BUILD_ITEM
- IMPLEMENTATION_MODE: BUILD
- TASK_STATE: PLANNED
- LEVEL: L1
- DEPENDS: N-L0-05
- RISK: YELLOW
- REQUIRED_EVIDENCE: журнал доставки
- ACCEPTANCE: повтор доставки не запускает работу дважды
- INDEPENDENT_REVIEW: НЕ ТРЕБУЕТСЯ (GREEN): достаточно автоматической проверки
- OBJECTIVE: идемпотентная доставка по ключу

### N-COMPLETE-01 · Завершение проекта

- CLASS: MIGRATION_ITEM
- IMPLEMENTATION_MODE: VERIFY
- TASK_STATE: PLANNED
- LEVEL: COMPLETE
- DEPENDS: N-L1-01
- RISK: RED
- REQUIRED_EVIDENCE: все улики
- ACCEPTANCE: все пункты DONE
- INDEPENDENT_REVIEW: ТРЕБУЕТСЯ: владелец
- OBJECTIVE: PROJECT_COMPLETE
