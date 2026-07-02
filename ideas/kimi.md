User: Есть git для людей. Посмотри что можно придумать для агента, сохранив концепцию git. Не смотри внешние источники! Смотри только официальный репозиторий git
Kimi: Я не буду лезть в поисковик или читать чужие статьи — сформулирую идею исходя из самой архитектуры Git, как её можно понять из официального репозитория и документации.

---

## Git для агента: **Cogit** (Cognitive Git)

Концепция Git построена на простой, но мощной идее: **сохранять не дельты, а снимки состояний, а дельты вычислять на лету**. Для агента это означает, что мы сохраняем не «изменения в промпте», а **снимки когнитивного состояния**.

### 1. Объекты Cogit (аналог объектной модели Git)

В Git есть 4 типа объектов: blob, tree, commit, tag. Для агента:

| Git | Cogit | Смысл |
|-----|-------|-------|
| **Blob** | **Fact** | Атомарный факт: «температура в Москве 20°C», «пользователь предпочитает краткие ответы». Неизменяемый, адресуется по хешу содержимого. |
| **Tree** | **Mindset** | Снимок текущей «картины мира» агента: какие факты активны, какие правила применяются, какой контекст загружен. |
| **Commit** | **Thought** | Точка принятия решения. Содержит ссылку на Mindset, родительскую Thought, сообщение (рассуждение агента о том, почему он так решил), timestamp и автора (какой под-агент/модуль это сделал). |
| **Tag** | **Anchor** | Важная веха: «здесь я понял задачу», «здесь я согласовал план с пользователем». Не двигается при новых Thought. |

### 2. Ветки как гипотезы

В Git ветка — это просто указатель на коммит. В Cogit:
- **Ветка** = **гипотеза поведения** или **альтернативная линия рассуждений**.
- Агент может «ответвиться», чтобы проверить другую стратегию решения, не теряя текущую.
- `git checkout` → **context switch**: агент мгновенно переключается между задачами, загружая полное когнитивное состояние из Mindset.

### 3. Merge и конфликты

Когда две ветки-гипотезы приходят к разным выводам из одних фактов:
- **Merge** = **синтез знаний**. Если факты совместимы — объединяем Mindset.
- **Конфликт** = **когнитивный диссонанс**. Агент не может просто взять «оба варианта». Нужен **rerere** (Reuse Recorded Resolution) — агент запоминает, как он разрешал похожие противоречия раньше, и применяет тот же паттерн.

### 4. Rebase интеллекта

`git rebase` — переписывание истории поверх нового базиса. Для агента:
- Агент получил новый фундаментальный факт (например, «пользователь — врач, не программист»).
- Все предыдущие Thought нужно **переосмыслить** (rebase) поверх этого нового факта, сохраняя логику, но меняя выводы.
- История становится чище: нет «я думал, что ты программист» в логе.

### 5. Cherry-pick инсайтов

`git cherry-pick` — перенос конкретного коммита в другую ветку без всей истории.
- Агент решил задачу А и нашёл универсальный принцип.
- **Cherry-pick Thought** в ветку задачи Б: применить только этот инсайт, не таща весь контекст задачи А.

### 6. Blame и отладка

`git blame` — кто последний менял эту строку. В Cogit:
- **Blame Fact** — какой Thought (или какой входной промпт/документ) привёл к тому, что агент считает X истинным?
- Критически важно для **прослеживаемости** (traceability): почему агент совершил ошибку? Какой Fact в Mindset был источником?

### 7. Stash отложенных намерений

`git stash` — спрятать изменения, не коммитя. Для агента:
- Пользователь прервал текущую задачу вопросом в сторону.
- Агент делает **stash текущего Mindset**, переключается на новый контекст, потом `stash pop` — и возвращается к прерванной мысли без потери состояния.

### 8. Bisect для поиска ошибки

`git bisect` — бинарный поиск коммита, где всё сломалось.
- Агент дал 10 Thought подряд, и на 10-м ответ стал некорректным.
- **Bisect Thought** — автоматический бинарный поиск: на каком шаге рассуждения факт/логика стала неверной?

### 9. Detached HEAD = свободное размышление

`detached HEAD` — когда HEAD не указывает на ветку, а на конкретный коммит.
- Агент может войти в режим **без записи**: «а что если я предположу, что Земля плоская?» — порассуждать, не сохраняя в основную историю. Чисто спекулятивная ветка, которую можно выбросить.

---

## Почему это работает именно для агента, а не для человека?

| Человек | Агент |
|---------|-------|
| Коммитит код, который видит | Коммитит **состояние убеждений**, которое не видно |
| История — для отката | История — для **объяснения** (explainability) |
| Конфликт — технический | Конфликт — **логический**, требует арбитража |
| Blame — социальный инструмент | Blame — **механизм самокоррекции** |

Git для людей решает проблему **совместной работы над кодом**.  
**Cogit** решает проблему **совместной работы агента с самим собой через время** — когда текущий агент должен понять, доверять ли решениям предыдущего «себя», и уметь откатиться не просто к «версии», а к **конкретной точке рассуждения**.
User: Отлично, а теперь подумай про архитектуру и технологический стек. Не смотри внешние источники!
Kimi: Я не открываю браузер и не лезу в поиск — всё ниже выстраиваю из первых принципов, исходя из того, как устроен Git внутри (content-addressable store, plumbing/porcelain, packfiles) и какие задачи стоят перед агентной системой.

---

## Архитектура Cogit: пять слоёв

Если Git — это **content-addressable filesystem + VCS layer**, то Cogit — это **content-addressable cognitive store + reasoning-versioning layer**.

```
┌─────────────────────────────────────────────┐
│  5. PORCELAIN (Agent API, CLI, Web UI)     │
├─────────────────────────────────────────────┤
│  4. REASONING ENGINE (Merge, Blame, Diff)  │
├─────────────────────────────────────────────┤
│  3. INDEX (Staging Area / Pre-commit Mind) │
├─────────────────────────────────────────────┤
│  2. REFS DB (Mutable pointers to Thoughts)  │
├─────────────────────────────────────────────┤
│  1. OBJECT STORE (Immutable Facts/Mindsets)│
└─────────────────────────────────────────────┘
```

---

## 1. Object Store (Layer 1): «.git/objects» для разума

**Принцип Git:** объект адресуется хешем своего содержимого. Это даёт дедупликацию «for free» и криптографическую целостность.

### Формат объектов

Я бы взял **MessagePack** вместо JSON — компактнее, быстрее парсится, сохраняет бинарные данные (эмбеддинги, если они входят в Mindset). Структура аналогична Git-object:

```
type | size\0 | content
```

| Тип | Содержимое | Адресация |
|-----|-----------|-----------|
| **fact** | Нормализованное утверждение + confidence + source URI | SHA-256 от canonical representation |
| **mindset** | Упорядоченный список fact-hashes + metadata (timestamp, agent-version) | SHA-256 от сериализованного дерева |
| **thought** | parent-thought-hash + mindset-hash + message (рассуждение) + author-module + signature | SHA-256 |
| **anchor** | thought-hash + label + annotator | SHA-256 |

**Почему SHA-256, а не SHA-1:** в современном Git уже переходят на SHA-256 (hash-transition). Для агента это критично — collision-атака на когнитивную историю хуже, чем на код.

### Хранилище

**Выбор: RocksDB (embedded) или LMDB.**

Почему не файловая система как в Git:
- Агент работает в embedded-режиме (внутри процесса), а не как отдельный демон.
- Нужны миллисекундные `get()` по хешу при восстановлении Mindset.
- Git использует FS из исторических соображений (2005 год, простота). Сегодня embedded KV даёт лучшую производительность для small random reads.

**Схема:**
- `objects/<first-2-hex>/<remaining-62-hex>` — если всё-таки FS (для отладки).
- Или одна колонка в RocksDB: key = `obj:<sha256>`, value = zlib-compressed MessagePack.

---

## 2. Refs Database (Layer 2): указатели на мысли

В Git refs лежат в `.git/refs` и `.git/packed-refs`. Они **изменяемы** — в отличие от объектов.

**Cogit Refs:**

| Ref | Смысл |
|-----|-------|
| `HEAD` | Текущая активная Thought (где агент «сейчас») |
| `refs/heads/hypothesis-X` | Ветка-гипотеза |
| `refs/remotes/agent-B/main` | Состояние другого агента (аналог remote tracking branch) |
| `refs/anchors/v1.0` | Важная веха (тег) |
| `refs/stash` | Отложенное состояние |

**Технология:** отдельная SQLite таблица или LMDB (write-optimized). Нужны **atomic updates** — когда агент коммитит Thought, HEAD должен сдвинуться атомарно с созданием объекта.

```sql
-- refs.db
CREATE TABLE refs (
    name TEXT PRIMARY KEY,
    target TEXT NOT NULL,  -- SHA-256 thought-hash
    type TEXT CHECK(type IN ('direct', 'symbolic'))
);
```

---

## 3. Index / Staging Area (Layer 3): «подготовка убеждений»

В Git index — это бинарный файл, описывающий, какое дерево будет закоммичено. В Cogit Index — это **рабочая память агента перед коммитом**.

**Структура Index:**
- `base_mindset`: хеш mindset, от которого мы отталкиваемся.
- `stage[]`: массив изменений фактов. Каждая запись:
  - `fact_hash` (или null для удаления)
  - `mode`: `add` | `modify` | `delete` | `conflict`
  - `confidence_delta`: насколько агент «переубедился»
  - `source`: какой входной сигнал вызвал изменение (prompt-chunk, tool-result, inference)

**Алгоритм коммита Thought:**
1. Берём base_mindset, применяем stage[], получаем новый mindset-hash.
2. Создаём thought-объект: parent = HEAD, mindset = new_hash, message = reasoning_trace.
3. Атомарно: записываем thought в Object Store, обновляем HEAD.

**Технология:** in-memory структура с WAL в SQLite. При перезагрузке агента Index восстанавливается — агент не теряет «недосказанную мысль».

---

## 4. Reasoning Engine (Layer 4): plumbing команд

Это аналог `git diff`, `git merge`, `git blame`, но для семантических объектов.

### Diff Mindset
Не построчный, а **фактовый**. Выход:
- `added_facts[]`
- `removed_facts[]`
- `modified_facts[]` (изменился confidence или источник)

### Blame Fact
Рекурсивный обход истории Thought: «в каком коммите этот fact впервые появился с confidence > threshold?».
- Требует индекса «fact → first thought». Можно строить фоново, как `git gc` строит commit-graph.

### Merge Engine (самый сложный компонент)
Git использует 3-way merge на уровне строк. Cogit нужен **semantic 3-way merge**:

1. Находим common ancestor Thought (merge-base).
2. Сравниваем три Mindset: ancestor, ours, theirs.
3. Для каждого fact:
   - Если `ours == ancestor` → берём `theirs`.
   - Если `theirs == ancestor` → берём `ours`.
   - Если оба изменились **согласованно** (например, confidence вырос в обоих) → merge confidence.
   - Если **конфликт** (один удалил, другой повысил confidence до 0.95) → mark as `conflict` в Index.

**Conflict Resolution Protocol:**
- Агент не может «руками править файл». Нужен арбитражный модуль (встроенный LLM-judge или hardcoded policy).
- Резолюция записывается как отдельный Thought с `parent1` + `parent2`.

**Технология:** движок на Rust или Go — нужна скорость для обхода графа. Python-агент вызывает его через FFI/gRPC.

---

## 5. Porcelain (Layer 5): API агента

Высокоуровневые команды, которые агент вызывает в своём цикле:

```python
# Псевдокод
cogit = CogitAgent(repo_path="/var/agent/memory")

# Начать новую гипотезу
cogit.checkout("-b", "alternative-plan")

# Добавить факт в staging
cogit.add_fact(Fact("user_prefers_json", confidence=0.9, source="system_prompt"))

# Коммит рассуждения
thought = cogit.commit(
    message="User asked for structured output; switching to JSON mode",
    author="planner_module"
)

# Откатиться, если рассуждение пошло не туда
cogit.reset("--hard", "HEAD~1")

# Cherry-pick инсайта из другой ветки
cogit.cherry_pick("hypothesis-X", insight_hash="abc123...")

# Stash текущей задачи
cogit.stash("push", message="interrupted by weather query")

# Blame: почему мы считаем, что пользователь врач?
source_thought = cogit.blame_fact("user_is_doctor")
```

---

## Packfiles и Garbage Collection

Git хранит объекты loose, а потом «упаковывает» в packfiles с дельта-компрессией. Для агента это критично — история рассуждений растёт быстро.

**Архитектура фонового GC:**
- **Repack:** фоновый поток собирает старые Thoughts в packfiles. Дельта не по тексту, а по Mindset: «какие факты изменились относительно parent».
- **Bloom filters:** как в Git 2.x — ускоряют `git blame`. В Cogit: bloom filter по фактам в ветке, чтобы быстро сказать «этот fact точно не встречается в этой ветке».
- **Reachability:** `git gc` удаляет unreachable объекты. Cogit удаляет Thoughts, не связанные с `HEAD`, `refs/heads/*`, `refs/anchors/*` и не моложе N дней (retention policy).

**Технология:** packfile-формат можно унаследовать от Git (zlib + delta), но с другой семантикой дельты. Или взять **zstd с custom dictionary** — лучшее сжатие для повторяющихся структур MessagePack.

---

## Distributed Protocol: push/pull между агентами

Если агенты работают в swarm, нужен протокол синхронизации.

**Transport:** gRPC over HTTP/2 (bidirectional streaming для real-time).

**Команды:**

| Git | Cogit | Смысл |
|-----|-------|-------|
| `fetch` | `fetch_thoughts` | Забрать Thoughts и Mindsets из remote agent |
| `push` | `push_context` | Отправить свою ветку в общий hub |
| `clone` | `clone_personality` | Скопировать базовую личность агента-наставника |

**Smart Protocol (аналог Git):**
1. Агент А отправляет Агенту Б: «у меня есть HEAD=abc123, хочу refs/heads/main».
2. Агент Б отвечает: «мне не хватает объектов abc123, def456...».
3. Агент А пакует недостающие объекты в packfile и стримит.
4. Агент Б проверяет хеши, записывает в Object Store, обновляет `refs/remotes/agent-A/main`.

**Безопасность:** каждый Thought подписывается Ed25519 ключом модуля-автора. При `fetch` агент проверяет цепочку подписей — не принимает мысли из неизвестного источника.

---

## Технологический стек: итоговая таблица

| Компонент | Технология | Обоснование |
|-----------|-----------|-------------|
| **Object Store** | RocksDB / LMDB (embedded) | Миллисекундный доступ, встраиваемость, не требует отдельного процесса |
| **Сериализация** | MessagePack + zlib | Компактнее JSON, сохраняет бинарные эмбеддинги |
| **Refs / Index** | SQLite (WAL mode) | ACID для mutable state, восстановление после краша |
| **Merge/Diff** | Rust-модуль | Скорость обхода графа, без GIL |
| **Packfiles** | Custom (zstd + semantic delta) | Лучшее сжатие структур данных |
| **API** | Python bindings (ctypes/pyo3) | Агенты чаще всего на Python |
| **Network** | gRPC | Строгая типизация, streaming, двоичный протокол |
| **Crypto** | Ed25519 signatures | Легковесная подпись каждого Thought |

---

## Ключевое архитектурное отличие от «просто базы данных»

Обычная БД хранит **текущее состояние**. Cogit, как Git, хранит **все состояния и их происхождение**. Это позволяет:

1. **Откат с осмыслением:** агент не просто «возвращается к старому prompt», а к конкретной точке рассуждения с полным контекстом.
2. **Fork без копирования:** ветвление гипотезы — это O(1) операция (новый ref), а не дублирование терабайта контекста.
3. **Audit trail:** любой факт можно трассировать до источника через `blame`.

Система получается гибридом **event sourcing** (все события сохраняются) и **content-addressable store** (дедупликация через хеши), с VCS-семантикой поверх — именно то, что делает Git революционным для кода, но адаптировано для когнитивных процессов.
User: Воспользуйся принципом KISS, пересмотри архитектуру и технологический стек. Не смотри внешние источники!
Kimi: Хорошо. Выкидываем всё, что не является необходимым для работы. Git в 2005 году был просто набором shell-скриптов поверх файловой системы — и работал. Cogit должен повторить этот путь.

---

## KISS-философия

**Правило:** если для реализации фичи нужна внешняя зависимость, фича откладывается до тех пор, пока без неё не станет больно.  
**Цель:** репозиторий агента — это просто директория, которую можно `cat`, `cp`, `rsync` и `tar`.

---

## Архитектура: 3 слоя вместо 5

```
┌─────────────────────────────────────┐
│  3. PORCELAIN (Python-функции)       │
│     commit(), checkout(), blame()    │
├─────────────────────────────────────┤
│  2. REFS + INDEX (текстовые файлы)   │
│     HEAD, refs/heads/*, index.json   │
├─────────────────────────────────────┤
│  1. OBJECT STORE (директория)        │
│     .cogit/objects/xx/xxxxx...       │
└─────────────────────────────────────┘
```

Всё. Нет отдельного движка, нет Rust-модуля, нет gRPC.

---

## Технологический стек: только стандартная библиотека

| Компонент | Решение | Почему |
|-----------|---------|--------|
| **Хранение** | Файловая система (`os`, `pathlib`) | Git так и делает. Можно зайти `ls` и понять, что происходит. |
| **Формат** | JSON (`json` module) | Human-readable. Можно `cat` объект и прочитать мысль агента. MessagePack откладываем. |
| **Сжатие** | zlib (`zlib` module, stdlib) | Как в Git. Один объект — один сжатый файл. |
| **Хеш** | SHA-256 (`hashlib`, stdlib) | Достаточно. |
| **Блокировки** | Atomic rename (`os.replace`) | Не нужен filelock. Пишем во временный файл → rename. Git так делает. |
| **Язык** | Тот же, что агент (Python/JS/Rust) | Никаких FFI, никаких gRPC. Вызов — обычная функция. |

**Внешних зависимостей: ноль.**

---

## Структура репозитория

```
~/agent_memory/
├── .cogit/
│   ├── HEAD                    # "ref: refs/heads/main"
│   ├── index.json              # staging area (один JSON)
│   ├── refs/
│   │   ├── heads/
│   │   │   ├── main            # "sha256:abc123..."
│   │   │   └── hypothesis-1    # "sha256:def456..."
│   │   └── anchors/
│   │       └── v1.0            # "sha256:abc123..."
│   └── objects/
│       ├── ab/
│       │   └── c123...789      # zlib(JSON). Факт.
│       ├── de/
│       │   └── f456...012      # zlib(JSON). Mindset.
│       └── 12/
│           └── 3456...abc      # zlib(JSON). Thought.
└── ... (рабочие файлы агента, если нужны)
```

---

## Формат объектов (JSON)

**Fact** — атомарное знание:
```json
{
  "type": "fact",
  "content": "user_prefers_brief_answers",
  "confidence": 0.92,
  "source": "system_prompt_v3"
}
```

**Mindset** — снимок состояния:
```json
{
  "type": "mindset",
  "facts": [
    "sha256:abc...",
    "sha256:def...",
    "sha256:123..."
  ],
  "created_at": "2026-05-26T20:15:00Z"
}
```

**Thought** — коммит рассуждения:
```json
{
  "type": "thought",
  "parent": "sha256:parent...",
  "mindset": "sha256:mind...",
  "message": "User interrupted with weather query. Switching context.",
  "author": "context_manager",
  "timestamp": "2026-05-26T20:15:01Z"
}
```

**Почему JSON:** потому что когда агент сломается, разработчик зайдёт `cat .cogit/objects/xx/xxxx | python -m zlib -d | python -m json.tool` и поймёт, на каком этапе агент начал врать. С бинарным форматом это невозможно.

---

## Ключевые операции (псевдокод)

### Запись объекта (как `git hash-object -w`)
```python
import json, zlib, hashlib, os
from pathlib import Path

def write_object(data: dict, repo: Path) -> str:
    content = json.dumps(data, sort_keys=True, ensure_ascii=False)
    raw = f"{data['type']} {len(content)}\0{content}"
    sha = hashlib.sha256(raw.encode()).hexdigest()
    
    obj_dir = repo / ".cogit" / "objects" / sha[:2]
    obj_dir.mkdir(parents=True, exist_ok=True)
    obj_path = obj_dir / sha[2:]
    
    # atomic write
    tmp = obj_path.with_suffix(".tmp")
    tmp.write_bytes(zlib.compress(raw.encode()))
    os.replace(tmp, obj_path)
    
    return sha
```

### Чтение объекта (как `git cat-file`)
```python
def read_object(sha: str, repo: Path) -> dict:
    path = repo / ".cogit" / "objects" / sha[:2] / sha[2:]
    raw = zlib.decompress(path.read_bytes())
    null_idx = raw.index(b'\0')
    content = raw[null_idx+1:].decode()
    return json.loads(content)
```

### Коммит Thought (как `git commit`)
```python
def commit_thought(message: str, author: str, repo: Path) -> str:
    # 1. Собрать mindset из index
    index = json.loads((repo / ".cogit" / "index.json").read_text())
    mindset = {
        "type": "mindset",
        "facts": index["staged_facts"],
        "created_at": now()
    }
    mindset_sha = write_object(mindset, repo)
    
    # 2. Прочитать HEAD
    head_path = repo / ".cogit" / "HEAD"
    ref = head_path.read_text().strip().split(": ")[1]
    ref_path = repo / ".cogit" / ref
    parent_sha = ref_path.read_text().strip() if ref_path.exists() else None
    
    # 3. Создать thought
    thought = {
        "type": "thought",
        "parent": parent_sha,
        "mindset": mindset_sha,
        "message": message,
        "author": author,
        "timestamp": now()
    }
    thought_sha = write_object(thought, repo)
    
    # 4. Обновить ref атомарно
    tmp = ref_path.with_suffix(".tmp")
    tmp.write_text(thought_sha)
    os.replace(tmp, ref_path)
    
    # 5. Очистить index
    (repo / ".cogit" / "index.json").write_text('{"staged_facts":[]}')
    
    return thought_sha
```

**Всё.** Это и есть ядро системы. ~50 строк Python.

---

## Merge: максимально тупой, но рабочий

Git делает сложный diff/patch. Cogit работает с **множествами фактов**:

```python
def merge_mindsets(base: list, ours: list, theirs: list) -> dict:
    # Множества хешей фактов
    B, O, T = set(base), set(ours), set(theirs)
    
    # Автоматический merge
    result = (O | T) - (O - B) - (T - B)  # union minus conflicts
    conflicts = (O - B) & (T - B) & (O ^ T)  # оба изменили, но по-разному
    
    return {
        "facts": list(result),
        "conflicts": list(conflicts)  # агент решает вручную (или через LLM)
    }
```

Нет строковых diff-алгоритмов. Факт либо есть, либо нет. Если конфликт — агент получает список `conflicts` и решает, какой факт взять.

---

## Distributed: не gRPC, а файлы

**Push/pull между агентами:**

```bash
# Агент А упаковывает свою память
tar czf agent_a_memory.tar.gz .cogit/

# Агент Б распаковывает и мержит
cd agent_b_workspace
python -m cogit remote-add agent_a ./agent_a_memory.tar.gz
python -m cogit fetch agent_a
python -m cogit merge agent_a/main
```

Или вообще: **shared directory** через NFS/S3. Агенты пишут в одну `.cogit/objects`, но свои `refs/remotes/agent-X/`. Это как bare-репозиторий Git, но без демона.

**Нет протокола.** Есть файловая система.

---

## GC: просто удалить мусор

```python
def gc(repo: Path):
    # Найти все reachable объекты
    reachable = set()
    for ref_file in (repo / ".cogit" / "refs").rglob("*"):
        if ref_file.is_file():
            walk_history(ref_file.read_text().strip(), reachable)
    
    # Удалить всё остальное
    for obj_dir in (repo / ".cogit" / "objects").iterdir():
        for obj in obj_dir.iterdir():
            sha = obj_dir.name + obj.name
            if sha not in reachable:
                obj.unlink()
```

Нет packfiles. Нет дельта-сжатия. Если репозиторий разрастётся — тогда добавим packfiles. Но не сейчас.

---

## Что выкинули и почему

| Было | Стало | Причина выброса |
|------|-------|-----------------|
| RocksDB/LMDB | Файлы | Зависимость. Файлы проще отлаживать. |
| SQLite для refs | Текстовые файлы | Зависимость. `cat` быстрее `sqlite3`. |
| Rust-модуль merge | Python функции | FFI усложняет сборку. Python достаточно быстр для set-операций. |
| MessagePack | JSON | Не читается человеком. JSON — lingua franca. |
| gRPC / сетевой протокол | tar / rsync | Не нужен демон. Агенты редко real-time синхронизируются. |
| Ed25519 подписи | Ничего | MVP. Доверяем локальной ФС. |
| Bloom filters | Линейный поиск | Оптимизация. Добавим, когда `blame` станет медленным. |
| Packfiles | Loose objects | Оптимизация. 1000 файлов — не проблема для современной ФС. |

---

## Когда усложнять (роадмайм)

1. **Сейчас (KISS):** JSON + zlib + файлы. Работает на одной машине.
2. **Когда больно от размера:** Добавляем packfiles (как в Git). Но свой формат — просто `tar` со сжатыми объектами.
3. **Когда больно от скорости blame:** Добавляем индекс `fact → first thought` (SQLite, наконец).
4. **Когда больно от сети:** Добавляем простой HTTP endpoint для `fetch`/`push` (Flask/FastAPI, один endpoint).
5. **Когда больно от безопасности:** Добавляем Ed25519 подписи Thought.

---

## Итог

**Cogit по KISS** — это не база данных и не микросервис. Это **договорённость о директории `.cogit/`**, которую агент читает и пишет как обычные файлы. 

Преимущества:
- **Прозрачность:** `find .cogit/objects -type f | wc -l` показывает, сколько мыслей у агента.
- **Переносимость:** `scp -r .cogit` переносит память агента на другой сервер.
- **Надёжность:** если процесс агента упал во время записи, `index.json.tmp` останется, а репозиторий не испортится (atomic rename).
- **Нулевые зависимости:** агент запускается в голом Docker-контейнере без `apt-get install`.

Это тот же подход, который сделал Git доминирующим: **не оптимизировать всё заранее, а сделать прозрачную модель, которую можно понять, заглянув под капот.**
