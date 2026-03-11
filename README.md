Зачем и что именно описывать
Собирать описание деятельности нужно для трех практических задач: зафиксировать реальную работу, перевести ее в язык компетенций и затем связать с backward design учебной программы. Если этого шага нет, программа почти неизбежно превращается в набор дисциплин «про тему», а не в систему подготовки под реальные действия, решения и результаты выпускника.

В приложенных материалах ядро описания строится вокруг самой деятельности: задач, решений, контекста, инструментов, outputs, KPI, знаний, навыков и ограничений, а не вокруг красивого названия вакансии. Поэтому полезно развести три уровня: профессия — это широкое occupational field; должность — конкретное штатное место в организации; роль — функция в процессе или команде, которая может меняться даже внутри одной должности, что видно на примерах Agile-ролей вроде Product Owner или Scrum Master.
​

Для университета я бы брал базовой единицей не «должность», а связку профессия + целевые роли внутри нее. Причина простая: вуз готовит человека не к строке в оргштатке, а к типовым видам деятельности, уровню самостоятельности и типу задач, которые рынок реально предъявляет.

Как собирать описание
Здесь почти никогда не работает один метод. Нужен стек, потому что разные методы снимают разные слои работы.
​

DACUM/SCID дает быструю карту duties и tasks через экспертную декомпозицию; его сильная сторона — явные функции и обязанности, слабая — скрытое мышление и редкие исключения.
​

CTA/ACTA нужен там, где важны решения, диагностика, приоритизация и tacit knowledge; он опирается на интервью, think-aloud, сценарии и critical incidents, поэтому хорошо ловит то, чего нет в вакансии и оргрегламенте.

Наблюдение, shadowing, job performance, интервью, анкеты, review документов и daily logs — классический набор job analysis; наблюдение хорошо работает для видимых действий, а опросы дают масштаб и частотность.

PAQ, task inventory и competency-based job analysis полезны, когда нужно стандартизировать признаки и затем сравнивать роли между собой.

Автоматический слой тоже нужен: вакансии, job descriptions, ESCO/O*NET, кейсы, curricular analytics, рабочие артефакты и, где это допустимо, цифровые следы вроде тикетов, репозиториев или postmortem’ов; но этот слой шумный и без экспертной проверки быстро уезжает в рекрутинговые штампы.

Если говорить совсем по-инженерному, описание лучше строить не как эссе, а как матрицу признаков. Каждый источник превращается в feature family: tasks, decisions, tools, artifacts, inputs/outputs, knowledge, skills, soft skills, constraints, context, collaboration patterns, KPI, failure modes, evidence source и confidence score.

Для каждой сущности — профессии, роли или должности — у признака должен быть статус: available, unavailable, not-important, inferred, verified. Такая схема хорошо ложится на multisource knowledge graph и делает портрет пригодным не только для чтения, но и для дальнейшей машинной обработки.
​

Как проверить полноту и правильность
Проверка — это не «дать почитать одному эксперту». Это отдельный контур валидации.
​
​

Минимальный набор такой:

Content validation: есть ли прямая связь между задачами и требуемыми знаниями/навыками, и подтверждают ли это SME.
​

Reliability: сходятся ли между собой независимые эксперты, что можно оценивать через inter-judge agreement, interjudge reliability и internal consistency.
​

Criterion-related validation: коррелирует ли описание с реальными показателями успеха в работе — качеством результата, производительностью, безопасностью, скоростью выполнения или другими outcome-метриками.
​

В DACUM-подходе после workshop логично делать Task Verification survey, чтобы проверить, что карта задач типична для поля, а не просто отражает стиль одной экспертной группы. Плюс полезно гонять cross-source consistency check: совпадают ли важные задачи и требования между интервью, вакансиями, ESCO/O*NET, кейсами и артефактами работы.

LLM здесь полезен, но в очень конкретной роли: извлекать признаки, нормализовать формулировки, искать дубликаты, подсвечивать пропуски и помогать в curricular analytics и skill extraction. Финальный арбитр — не LLM, а экспертная проверка и, по возможности, чистый эталонный набор данных.
​
​

На Hugging Face есть датасеты с job descriptions и job-skill pairs, но их лучше воспринимать как weak-supervision corpora, а не как gold standard, потому что они собраны из вакансий и описаний без строгой экспертной разметки и без сильной методологии валидации. Для реальной проверки качества профиля надежнее собирать небольшой, но чистый benchmark с ручной экспертной разметкой задач, навыков и связей между ними.

Эталонный pipeline
Представьте вполне земную сцену: университет хочет открыть STEM-трек не «про данные вообще», а под выходную роль Data Engineer. В вашем шаблоне НИР Data Engineer уже фигурирует как разумный proof-of-concept объект, поэтому на нем удобно показать эталонный маршрут от сырого материала до результата.
​

Сначала фиксируем единицу анализа: profession = Data Engineer, а role — например, entry-level инженер, который строит и поддерживает data pipelines в продуктовой или аналитической среде.

Потом собираем evidence stack: вакансии, ESCO/O*NET, экспертные интервью, DACUM-сессию, CTA-интервью по сложным задачам, кейсы и рабочие артефакты.

Затем нормализуем все в структуру: mission, work context, tasks, subtasks, tools, inputs/outputs, decisions, knowledge, hard skills, soft skills, constraints, KPI, common errors, evidence spans, confidence.

После этого запускаем валидацию: SME review, task verification, проверку согласованности между источниками, LLM-gap scan и ручное утверждение спорных узлов.
​

И только потом переводим профиль в curriculum: learning outcomes, module map, assessment tasks, practice formats, prerequisite graph и progression by level.
​

Короткий фрагмент результата может выглядеть так: задача — проектировать и поддерживать data pipelines; артефакт — ETL/ELT workflow; решение — выбирать схему оркестрации, мониторинга и обработки сбоев; знание — storage, SQL, data modeling, observability; критерий успешности — надежность pipeline, актуальность данных и воспроизводимость результата. Вот в этот момент портрет перестает быть разговором «в целом о профессии» и становится спецификацией, из которой уже можно честно собирать программу обучения.
















Окей, тогда разворачиваем задачу по‑другому: не “похоже ли описание на правду”, а “достаточно ли данных, чтобы из них собрать учебную программу без дыр”. Для этого нужна не экспертная вкусовщина, а проверка профиля как датасета: на покрытие, устойчивость, связность и извлекаемость из реальных источников. [onetcenter](https://www.onetcenter.org/database.html)

## Что берем за истину

Якорь №1 — O*NET: это не блог и не чья-то статья, а рабочая база с 40 файлами, словарями данных, связями Tasks to DWAs и web services для машинного доступа. Якорь №2 — ESCO: это формальная классификация occupations, skills, competences и qualifications, а в matrix tables можно смотреть доли skill-групп по occupation groups; в техническом отчете указаны 13,485 skills и 2,942 occupations на самом детальном уровне. [onetonline](https://www.onetonline.org/help/onet/database)

Якорь №3 — размеченные benchmark-наборы для проверки extractor-а, а не всей профессии целиком: SkillSpan дает 14.5K предложений и больше 12.5K размеченных skill spans, а Green Benchmark содержит 18.6k сущностей пяти типов — Skill, Qualification, Experience, Occupation, Domain. Рыночный слой — это корпуса вакансий и job descriptions, например HF-наборы `jacob-hugging-face/job-descriptions`, `lang-uk/recruitment-dataset-job-descriptions-english`, `batuhanmtl/job-skill-set`; это не gold standard, а корпус для проверки частотности, стабильности и рыночной поддержки признаков. [aclanthology](https://aclanthology.org/2022.naacl-main.366/)

## Пять признаков

Ниже — минимальная матрица, которую реально можно валидировать, и она не разваливается в “все обо всем”. DACUM здесь нужен как форма представления: Duty -> Task, а признаки навешиваются на task-уровень. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/167034859/0e16c8c8-f3a9-42b9-b916-dea3f88db643/Metodologicheskie_podkhody_k_opisaniiu_professionalnoi_deiatelnosti.md)

| Признак | Что хранить | Откуда брать | Объективная проверка |
|---|---|---|---|
| Объект работы | С чем роль работает: данные, документы, оборудование, сигналы  [onetcenter](https://www.onetcenter.org/content.html) | O*NET Work Activities/Tasks, ESCO, вакансии  [onetcenter](https://www.onetcenter.org/database.html) | Для каждого объекта должен существовать хотя бы один task, который этот объект принимает или меняет |
| Действие | 6–10 core tasks в форме DACUM  [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/167034859/0e16c8c8-f3a9-42b9-b916-dea3f88db643/Metodologicheskie_podkhody_k_opisaniiu_professionalnoi_deiatelnosti.md) | O*NET Tasks to DWAs, вакансии, LLM extraction  [onetcenter](https://www.onetcenter.org/database.html) | Task проходит, если встречается в canonical source и в market corpus |
| Артефакт | Что остается после выполнения task: pipeline, отчет, модель, протокол, код  [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/167034859/0e16c8c8-f3a9-42b9-b916-dea3f88db643/Metodologicheskie_podkhody_k_opisaniiu_professionalnoi_deiatelnosti.md) | Вакансии, job descriptions, кейсы  [huggingface](https://huggingface.co/datasets/lang-uk/recruitment-dataset-job-descriptions-english) | У каждого task должен быть хотя бы один наблюдаемый output |
| Качество | Как понять, что output не мусор: accuracy, timeliness, reliability, safety, compliance  [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/167034859/0e16c8c8-f3a9-42b9-b916-dea3f88db643/Metodologicheskie_podkhody_k_opisaniiu_professionalnoi_deiatelnosti.md) | O*NET descriptors, вакансии, SLA/requirements  [onetcenter](https://www.onetcenter.org/content.html) | У каждого output должен быть хотя бы один quality criterion |
| Требуемая способность | Какое знание или skill нужен, чтобы task выполнить  [onetcenter](https://www.onetcenter.org/content.html) | O*NET Skills/Knowledge, ESCO skills, LLM span extraction  [onetcenter](https://www.onetcenter.org/content.html) | Каждый skill должен быть привязан минимум к одному task и одному output |

Вот и все. Если признак нельзя привязать к task, output или canonical taxonomy, он не идет в профиль.

## Пример: Data Engineer

Возьмем Data Engineer как рыночную роль для STEM-программы, а DACUM-chart соберем из рыночных job descriptions плюс canonical occupational layers. В реальных описаниях этой роли стабильно встречаются ingestion данных, построение и поддержка pipelines, преобразование raw data, quality checks, monitoring и troubleshooting. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/167034859/3714e213-ea89-4b44-a025-009a9107505a/Shablon-otcheta-NIR-2.md)

Упрощенный DACUM для Data Engineer может выглядеть так: [indeed](https://www.indeed.com/q-etl-data-engineer-jobs.html)
- Duty A. Собирать данные: подключать источники, тянуть raw data, проверять схему и формат. [coursera](https://www.coursera.org/articles/what-does-a-data-engineer-do-and-how-do-i-become-one)
- Duty B. Готовить данные: чистить, трансформировать, загружать в целевое хранилище, поддерживать pipeline. [resources.workable](https://resources.workable.com/data-engineer-job-description)
- Duty C. Держать систему живой: мониторить jobs, ловить quality issues, чинить сбои, документировать изменения. [splunk](https://www.splunk.com/en_us/blog/learn/data-engineer-role-responsibilities.html)

Теперь раскладываем это по пяти признакам: [indeed](https://www.indeed.com/q-etl-data-engineer-jobs.html)
- Объект работы: raw data, feeds, databases, APIs. [splunk](https://www.splunk.com/en_us/blog/learn/data-engineer-role-responsibilities.html)
- Действия: ingest, transform, validate, orchestrate, monitor, troubleshoot. [coursera](https://www.coursera.org/articles/what-does-a-data-engineer-do-and-how-do-i-become-one)
- Артефакты: pipeline, table, dataset, alert, documentation. [indeed](https://www.indeed.com/q-etl-data-engineer-jobs.html)
- Качество: reliability, consistency, security, efficiency, integrity. [betterteam](https://www.betterteam.com/data-engineer-job-description)
- Требуемые способности: SQL, data modeling, ETL/ELT, scripting, monitoring, debugging. [resources.workable](https://resources.workable.com/data-engineer-job-description)

## Валидация как в ML

Здесь лучше разделить две вещи. Есть качество extractor-а, и оно меряется на размеченных benchmark-наборах вроде SkillSpan и Green Benchmark обычными ML-метриками — precision, recall, F1. А есть качество самого occupational profile, и его надо мерить не похожестью на датасет, а готовностью к curriculum design по всем фронтам. [esco.ec.europa](https://esco.ec.europa.eu/en/about-esco/publications/publication/skills-occupations-matrix-tables)

Я бы оставил одну верхнюю метрику — **Curriculum Readiness Score**. Она считается из четырех объективных блоков:
- Extractor accuracy: F1 на SkillSpan и Green Benchmark, чтобы понять, можно ли вообще доверять автоматическому извлечению skill/entity spans. [eprints.whiterose.ac](https://eprints.whiterose.ac.uk/id/eprint/208054/)
- Canonical coverage: доля task/skill/quality элементов профиля, которые маппятся в O*NET и ESCO без ручных “ну примерно похоже”. [esco.ec.europa](https://esco.ec.europa.eu/system/files/2023-04/en_ESCO%20Skill-Occupation%20Matrix%20Tables%20Technical%20Report.pdf)
- Market stability: насколько профиль устойчив на реальном корпусе вакансий; если при bootstrap-подвыборках top tasks постоянно скачут, профиль сырой. [huggingface](https://huggingface.co/datasets/jacob-hugging-face/job-descriptions)
- Structural completeness: доля tasks, у которых одновременно есть объект работы, output, quality criterion и required capability; именно этот блок отвечает за пригодность для сборки образовательной программы. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/167034859/3714e213-ea89-4b44-a025-009a9107505a/Shablon-otcheta-NIR-2.md)

Это уже очень похоже на нормальную ML-валидацию, просто target здесь другой. Вы валидируете не “угадай лейбл”, а “достаточно ли структурированной правды в профиле, чтобы из него строить learning outcomes, modules, assessments и prerequisite graph”. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/167034859/3714e213-ea89-4b44-a025-009a9107505a/Shablon-otcheta-NIR-2.md)

## Жесткие правила приемки

Чтобы профиль считался годным, я бы ставил не расплывчатые “выглядит хорошо”, а binary checks. Они простые и злые, и это хорошо.

- Нет task без output.
- Нет output без quality criterion.
- Нет skill без task.
- Нет task без поддержки хотя бы из двух независимых источников: canonical + market, или canonical + labeled extraction. [onetcenter](https://www.onetcenter.org/database.html)
- Нет LLM-извлечения без raw span, source id и confidence; Skill-LLM как раз показывает правильную логику, где LLM работает как extractor skills из текста, а не как “автор профессии”. [arxiv](https://arxiv.org/html/2410.12052v1)
- Нет curriculum mapping, пока structural completeness не закрывает почти все core tasks, потому что в вашем собственном шаблоне НИР именно профиль деятельности служит входом в competency formalization, knowledge graph и curriculum generation. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/167034859/3714e213-ea89-4b44-a025-009a9107505a/Shablon-otcheta-NIR-2.md)

Если совсем коротко, то объективная валидация здесь такая:  
1) extractor проходит benchmark;  
2) профиль покрывает O*NET/ESCO;  
3) профиль устойчив на вакансиях;  
4) у него нет сиротских узлов task→output→quality→skill;  
5) только после этого он считается пригодным для проектирования программы. [esco.ec.europa](https://esco.ec.europa.eu/en/about-esco/publications/publication/skills-occupations-matrix-tables)

Хочешь, я следующим сообщением дам это уже в виде совсем инженерного артефакта: JSON-schema профиля + формулы метрик + чеклист приемки для одной роли?










Да: на вход должен идти не “текст про профессию”, а **JSON-профиль роли**, собранный по DACUM-логике, где есть role, mission, tasks, outputs, quality metrics, skills, tools, context и evidence spans по каждому утверждению. Проверяется он не “нравится/не нравится”, а как ML-объект: сначала на валидность структуры, потом на связность графа task-output-skill, потом на покрытие O*NET/ESCO, потом на поддержку реальным корпусом вакансий, и только потом на пригодность для curriculum design. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/167034859/0e16c8c8-f3a9-42b9-b916-dea3f88db643/Metodologicheskie_podkhody_k_opisaniiu_professionalnoi_deiatelnosti.md)

## Что на входе

Минимальный входной объект для Data Engineer я бы делал из шести сущностей: `role`, `mission`, `tasks`, `outputs`, `quality_metrics`, `skills`, а внутри каждого task обязательно хранить `task_id`, `task_text`, `inputs`, `output_ids`, `skill_ids`, `evidence_spans`, `source_ids` и `confidence`. В ваших материалах уже есть логика JSON-структуры вида role -> functions -> tasks, где у tasks могут быть поля goal, knowledge, skills, tools, errors, context, interaction, а сверху могут жить competencies и quality metrics, поэтому это не выдумка, а естественное продолжение DACUM-представления в машинный формат. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/167034859/0e16c8c8-f3a9-42b9-b916-dea3f88db643/Metodologicheskie_podkhody_k_opisaniiu_professionalnoi_deiatelnosti.md)

Если упростить до рабочего минимума, то JSON для одной роли должен содержать:  
- `role_name` и `mission`, чтобы зафиксировать границы роли. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/167034859/0e16c8c8-f3a9-42b9-b916-dea3f88db643/Metodologicheskie_podkhody_k_opisaniiu_professionalnoi_deiatelnosti.md)
- `tasks[ ]`, потому что DACUM держится на duty/task decomposition. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/167034859/0e16c8c8-f3a9-42b9-b916-dea3f88db643/Metodologicheskie_podkhody_k_opisaniiu_professionalnoi_deiatelnosti.md)
- `outputs[ ]`, потому что task без наблюдаемого результата бесполезен для проектирования обучения. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/167034859/3714e213-ea89-4b44-a025-009a9107505a/Shablon-otcheta-NIR-2.md)
- `quality_metrics[ ]`, потому что HPT- и outcome-driven логика в ваших материалах прямо требует связки с quality/KPI. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/167034859/0e16c8c8-f3a9-42b9-b916-dea3f88db643/Metodologicheskie_podkhody_k_opisaniiu_professionalnoi_deiatelnosti.md)
- `skills[ ]` и `knowledge[ ]`, потому что потом именно они переходят в competency formalization и curriculum generation. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/167034859/3714e213-ea89-4b44-a025-009a9107505a/Shablon-otcheta-NIR-2.md)
- `evidence[ ]` с raw span и source id, потому что в шаблоне НИР extraction/normalization опирается на evidence spans и multisource fusion, а не на свободный пересказ модели. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/167034859/3714e213-ea89-4b44-a025-009a9107505a/Shablon-otcheta-NIR-2.md)

## Как он проверяется

Проверка идет в четыре слоя, и каждый слой либо дает pass/fail, либо численный score. Важная мысль: LLM здесь не “судья профессии”, а только extractor и matcher, а сами проверки должны быть формальными и воспроизводимыми. [onetcenter](https://www.onetcenter.org/database.html)

1. **Schema validation**: JSON должен проходить JSON Schema без пропусков обязательных полей, неправильных типов и битых ссылок между `task_id`, `output_id`, `skill_id` и `source_id`. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/167034859/0e16c8c8-f3a9-42b9-b916-dea3f88db643/Metodologicheskie_podkhody_k_opisaniiu_professionalnoi_deiatelnosti.md)
2. **Structural validation**: у каждого task должен быть хотя бы один input, один output, один quality metric и одна required capability; если цепочка рвется, task считается неполным для образовательного дизайна. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/167034859/3714e213-ea89-4b44-a025-009a9107505a/Shablon-otcheta-NIR-2.md)
3. **Canonical validation**: tasks и skills должны маппиться на O*NET и ESCO, потому что O*NET Database и ESCO matrix tables дают формальный внешний каркас occupations, tasks и skills. [esco.ec.europa](https://esco.ec.europa.eu/en/about-esco/publications/publication/skills-occupations-matrix-tables)
4. **Corpus validation**: каждый core task должен подтверждаться корпусом вакансий или job descriptions, а не только вашим JSON; для этого подходят HF job corpora и реальные postings. [huggingface](https://huggingface.co/datasets/jacob-hugging-face/job-descriptions)

Вот в этот момент у вас уже не “описание профессии”, а объект, который можно прогонять через deterministic checks и считать метрики. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/167034859/3714e213-ea89-4b44-a025-009a9107505a/Shablon-otcheta-NIR-2.md)

## Метрики проверки

Я бы для одного профиля считал пять метрик, и все они объективные. Они отвечают не на вопрос “мы похожи на датасет?”, а на вопрос “полон ли профиль настолько, чтобы собирать программу”. [onetcenter](https://www.onetcenter.org/database.html)

- **Schema Pass Rate** = доля объектов, прошедших JSON Schema и referential integrity checks; целевое значение для production — 100%. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/167034859/0e16c8c8-f3a9-42b9-b916-dea3f88db643/Metodologicheskie_podkhody_k_opisaniiu_professionalnoi_deiatelnosti.md)
- **Structural Completeness** = доля tasks, у которых есть полный контур `input -> action -> output -> quality -> skill`; это главная метрика полноты для curriculum readiness. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/167034859/3714e213-ea89-4b44-a025-009a9107505a/Shablon-otcheta-NIR-2.md)
- **Canonical Coverage** = доля task/skill узлов, которые имеют уверенный match в O*NET или ESCO. [esco.ec.europa](https://esco.ec.europa.eu/system/files/2023-04/en_ESCO%20Skill-Occupation%20Matrix%20Tables%20Technical%20Report.pdf)
- **Market Support** = доля core tasks, которые встречаются в реальном корпусе вакансий выше заданного порога частоты. [huggingface](https://huggingface.co/datasets/lang-uk/recruitment-dataset-job-descriptions-english)
- **Evidence Coverage** = доля утверждений в JSON, у которых есть raw evidence span и source id; без этого узел нельзя считать проверяемым. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/167034859/3714e213-ea89-4b44-a025-009a9107505a/Shablon-otcheta-NIR-2.md)

Рекомендуемый итоговый score можно собрать так:  
\[
CRS = 0.35 \cdot SC + 0.25 \cdot CC + 0.20 \cdot MS + 0.20 \cdot EC
\]
где \(SC\) — Structural Completeness, \(CC\) — Canonical Coverage, \(MS\) — Market Support, \(EC\) — Evidence Coverage. В этой формуле главный вес у структурной полноты, потому что ваша конечная цель — не классифицировать профессию, а построить из профиля полноценную образовательную программу. [esco.ec.europa](https://esco.ec.europa.eu/en/about-esco/publications/publication/skills-occupations-matrix-tables)

## Пример для Data Engineer

Представим, что JSON для Data Engineer содержит task `build and maintain data pipelines`, output `reliable production pipeline`, quality metric `pipeline reliability`, skill `ETL/ELT`, а evidence spans взяты из вакансий и job descriptions. Тогда проверка идет так: [coursera](https://www.coursera.org/articles/what-does-a-data-engineer-do-and-how-do-i-become-one)

- Schema-check смотрит, что `task.output_ids` ссылается на реальный output, а `task.skill_ids` — на реальные skill-узлы. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/167034859/0e16c8c8-f3a9-42b9-b916-dea3f88db643/Metodologicheskie_podkhody_k_opisaniiu_professionalnoi_deiatelnosti.md)
- Structural-check убеждается, что у task есть входные данные, наблюдаемый результат и критерий качества, а не просто глагол “manage” без содержания. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/167034859/3714e213-ea89-4b44-a025-009a9107505a/Shablon-otcheta-NIR-2.md)
- Canonical-check ищет, есть ли близкий occupational/task/skill match в O*NET и ESCO. [onetcenter](https://www.onetcenter.org/database.html)
- Corpus-check проверяет, что этот task стабильно встречается в job descriptions для Data Engineer, а не всплыл один раз в странной вакансии. [huggingface](https://huggingface.co/datasets/batuhanmtl/job-skill-set)
- Evidence-check проверяет, что task не был “дописан моделью”, а привязан к конкретным spans текста, как в логике skill extraction benchmarks вроде SkillSpan. [aclanthology](https://aclanthology.org/2022.naacl-main.366/)

Если task прошел все пять проверок, он остается в профиле. Если он не маппится в canonical layer, не поддерживается рынком и не имеет evidence spans, его надо либо удалять, либо переводить в статус `hypothesis`, но не тащить дальше в curriculum generation. [esco.ec.europa](https://esco.ec.europa.eu/en/about-esco/publications/publication/skills-occupations-matrix-tables)

## Жесткий чеклист

Ниже — короткий критерий приемки JSON-профиля, который можно автоматизировать без ручного “эксперт сказал”. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/167034859/0e16c8c8-f3a9-42b9-b916-dea3f88db643/Metodologicheskie_podkhody_k_opisaniiu_professionalnoi_deiatelnosti.md)

- Нет битых ссылок между task, output, skill и evidence. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/167034859/0e16c8c8-f3a9-42b9-b916-dea3f88db643/Metodologicheskie_podkhody_k_opisaniiu_professionalnoi_deiatelnosti.md)
- Нет task без output. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/167034859/3714e213-ea89-4b44-a025-009a9107505a/Shablon-otcheta-NIR-2.md)
- Нет output без quality metric. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/167034859/0e16c8c8-f3a9-42b9-b916-dea3f88db643/Metodologicheskie_podkhody_k_opisaniiu_professionalnoi_deiatelnosti.md)
- Нет skill без хотя бы одного task, где он нужен. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/167034859/3714e213-ea89-4b44-a025-009a9107505a/Shablon-otcheta-NIR-2.md)
- Нет core task без поддержки из внешнего canonical source и внешнего market corpus. [huggingface](https://huggingface.co/datasets/jacob-hugging-face/job-descriptions)
- Нет утверждения без evidence span и source id. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/167034859/3714e213-ea89-4b44-a025-009a9107505a/Shablon-otcheta-NIR-2.md)
- Нет перехода к curriculum mapping, пока Structural Completeness не закрывает почти все core tasks роли. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/167034859/3714e213-ea89-4b44-a025-009a9107505a/Shablon-otcheta-NIR-2.md)

Если совсем коротко: **вход** — это JSON-граф роли, а **валидация** — это последовательность формальных тестов на структуру, полноту, внешнее покрытие и корпусную поддержку. Если профиль проходит эти проверки, его уже можно считать не “описанием”, а нормальной машинно-проверяемой спецификацией для сборки учебной программы. [onetcenter](https://www.onetcenter.org/database.html)























